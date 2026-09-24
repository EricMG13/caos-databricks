"""The actual extended route accepts CP-CF only from anchored owner inputs."""

from __future__ import annotations

import json
import re
from copy import deepcopy
from dataclasses import replace
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest
from canonical_fixtures import (
    AUTHORED,
    CATALOG,
    CONTRACT,
    fields_from_prompt,
    skill,
    wire,
)
from canonical_route_fixtures import LIMITATION, PACK, RouteCompletions
from conftest import tamper
from forecast_fixtures import forecast_request
from lite_route_fixtures import _yaml
from test_canonical_execution import _node
from test_canonical_runtime import _module_provider, _run_route, _status
from test_execution_freshness import _Harness
from test_relative_value_route import harness as _harness

from caos.boundary_text import BoundaryText
from caos.calculators.cash_flow import cash_flow_forecast
from caos.deliverable.canonical import Revision, canonical_payload
from caos.evidence.ingest import Document
from caos.graph.route import ResolvedRoute, RouteExtensions, resolve_route
from caos.methodology.forecast import forecast_projection
from caos.methodology.handoff import read_record, record_bytes, validate_markdown
from caos.methodology.invocation import host_identity
from caos.provider import Completion
from caos.qualification.matrix import (
    ExpectedCitation,
    ExpectedForecast,
    ForecastValue,
    QualificationCase,
    QualificationSet,
    build_matrix,
)
from caos.qualification.proof import assert_orchestration_proof
from caos.refusals import Refusal, RefusalCode

harness = _harness


def request_data() -> dict[str, Any]:
    request = forecast_request()
    request["periods"] = request["periods"][:1]
    request["periods"][0]["period_id"] = "FY2026"
    request["drivers"] = request["drivers"][:1]
    request["drivers"][0].update(
        period_id="FY2026",
        acquisitions_disposals="0",
        distributions="0",
        stated_closing_debt="600",
        stated_closing_cash="145",
    )
    request["opening"]["debt_by_facility"] = [{"facility_id": "TERM", "amount": "600"}]
    request["contractual"]["amortisation"] = request["contractual"]["amortisation"][:1]
    request["contractual"]["amortisation"][0]["period_id"] = "FY2026"
    return request


def assignment_rows(value: object, pointer: str = "") -> dict[str, str]:
    if isinstance(value, dict) and value:
        return {
            p: v
            for k, item in value.items()
            for p, v in assignment_rows(item, pointer + "/" + k).items()
        }
    if isinstance(value, list) and value:
        return {
            p: v
            for i, item in enumerate(value)
            for p, v in assignment_rows(item, pointer + "/" + str(i)).items()
        }
    return {pointer: pointer + " = " + json.dumps(value)}


def owner_of(pointer: str) -> str:
    """The module that owns a request pointer's assignment."""
    if pointer.startswith("/contractual/"):
        return "CP-4"
    return "CP-2G" if pointer.startswith("/drivers/") else "CP-1"


def owner_quotes(rows: dict[str, str]) -> dict[str, str]:
    """Each owner's assignment lines, one per request leaf it owns."""
    return {
        m: "\n".join(v for p, v in rows.items() if owner_of(p) == m)
        for m in ("CP-1", "CP-2G", "CP-4")
    }


ROWS = assignment_rows(request_data())
OWNER = {p: owner_of(p) for p in ROWS}
OWNER_QUOTES = owner_quotes(ROWS)

# C2, end to end: CP-2G's BASE FY2026 driver cells as the vendor signs them
# (outflows negative), the request movements CP-CF maps them to (the
# calculator's outflows positive), and the stated close they reconcile to
# from the route request's opening cash of 100.
SIGNED: dict[str, tuple[dict[str, str], dict[str, str], str]] = {
    "dividend": ({"dividends_paid": "(45)"}, {"distributions": "45"}, "100"),
    "acquisition": (
        {"acquisitions_disposals": "(45)"},
        {"acquisitions_disposals": "45"},
        "100",
    ),
    "disposal": (
        {"acquisitions_disposals": "45"},
        {"acquisitions_disposals": "-45"},
        "190",
    ),
    "zero": ({"dividends_paid": "(0)", "acquisitions_disposals": "-0"}, {}, "145"),
}


def signed_request(case: str) -> dict[str, Any]:
    """The route request with `SIGNED[case]`'s movements and stated close."""
    _cells, movements, closing = SIGNED[case]
    request = request_data()
    request["drivers"][0].update(movements, stated_closing_cash=closing)
    return request


@pytest.fixture
def route(
    monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest
) -> ResolvedRoute:
    """The model-extended route over a pack carrying the owners' assignment
    lines: the route request's, or a `SIGNED` case's when parametrized with
    its name."""
    import test_relative_value_route

    case = getattr(request, "param", None)
    rows = ROWS if case is None else assignment_rows(signed_request(case))
    monkeypatch.setattr(
        test_relative_value_route,
        "PACK",
        PACK + b"\n" + "\n".join(owner_quotes(rows).values()).encode(),
    )
    return resolve_route(
        CATALOG,
        "FULL_CREDIT_32",
        "RELATIVE_VALUE",
        extensions=RouteExtensions(model_extension=True),
    )


class ForecastCompletions(RouteCompletions):
    def __init__(
        self,
        source_id: UUID,
        *,
        defect: str = "",
        limitations: tuple[str, ...] = (),
        request: dict[str, Any] | None = None,
        cells: dict[str, str] | None = None,
    ) -> None:
        self.request = request or request_data()
        self.rows = assignment_rows(self.request)
        super().__init__(source_id, quotes_by_module=owner_quotes(self.rows))
        self.defect = defect
        self.limitations = limitations
        # CP-2G's BASE FY2026 driver cells to write in place of its zeros.
        self.cells = cells or {}

    def _driver_cells(self, done: Completion) -> Completion:
        """CP-2G's answer with `cells` written into its driver table."""
        assert done.content is not None
        answer = json.loads(done.content)
        for driver, value in self.cells.items():
            row = f"| {driver} |  | BASE | FY2026 | 2026 | "
            written = answer["canonical_markdown"].replace(
                row + "0 | CURRENCY_MM", row + value + " | CURRENCY_MM", 1
            )
            assert written != answer["canonical_markdown"], driver
            answer["canonical_markdown"] = written
        return replace(done, content=json.dumps(answer))

    def complete(self, prompt: str, *, json_object: bool = False) -> Completion:
        fields = fields_from_prompt(prompt)
        if fields["module_id"] == "CP-2G" and self.cells:
            return self._driver_cells(super().complete(prompt, json_object=json_object))
        if fields["module_id"] != "CP-CF":
            return super().complete(prompt, json_object=json_object)
        self.prompts.append(prompt)
        request = deepcopy(self.request)
        # Each binding quotes its owner's one anchored line (N28).
        bindings = {
            p: {"module_id": owner_of(p), "quote": q} for p, q in self.rows.items()
        }
        result = cash_flow_forecast(request)
        if self.defect == "missing":
            del bindings["/opening/cash"]
        elif self.defect == "wrong-owner":
            bindings["/opening/cash"]["module_id"] = "CP-2G"
        elif self.defect == "result":
            result["rows"][0]["closing_cash"] = "999"
        document = {"request": request, "bindings": bindings, "forecast": result}
        front = {
            **fields,
            "confidence_score": 90,
            "confidence_band": "High",
            "committee_status": "Draft Only",
            "limitation_flags": list(self.limitations),
            "validation_warnings": [],
            "downstream_consumers": [],
            **AUTHORED["Passed"],
            "qa_status": "Passed",
        }
        if self.defect == "retain-restriction":
            front.update(AUTHORED["Restricted"])
            front.update(qa_status="Restricted", limitation_flags=[LIMITATION])
        quotes = "\n".join(owner_quotes(self.rows).values())
        body = "".join(
            "## "
            + h
            + "\n\n"
            + (
                "```caos-forecast-v1\n" + json.dumps(document) + "\n```\n\n"
                if h == "Analysis"
                else ""
            )
            + quotes
            + "\n\n"
            for h in CONTRACT.validate_handoff.CANONICAL_HEADINGS
        )
        markdown = ("---\n" + _yaml(front) + "\n---\n" + body).encode()
        self.answers.append(markdown)
        return Completion(
            wire(
                markdown,
                [
                    {"source_id": str(self.source_id), "page": 1, "matched_text": q}
                    for q in self.rows.values()
                ],
            ),
            Decimal("0.0000041"),
            "gen-forecast",
        )


def test_forecast_route_accepts_real_host_calculated_artifact(
    harness: _Harness,
) -> None:
    from conftest import priced
    from test_loop_charges import ESTIMATE

    from caos.deliverable.revisions import save_revision
    from caos.graph.runtime import Execution, accepted_artifacts, run_route

    answers = ForecastCompletions(harness.source_id)
    run_route(
        harness.conn,
        harness.blobs,
        run_id=harness.run_id,
        route=harness.route,
        execution=Execution(
            _module_provider(harness, answers), priced(ESTIMATE), harness.bundle
        ),
    )
    assert _status(harness) == "COMPLETE"
    assert (
        len(
            accepted_artifacts(
                harness.conn,
                harness.blobs,
                harness.route,
                harness.run_id,
                bundle=harness.bundle,
            )
        )
        == 10
    )
    result = forecast_projection(answers.answers[-1])
    assert result["rows"][0]["cash"]["closing"] == "145.000000"
    # The forecast owners are the only modules handed the extension, and this
    # is the only route fixture that emits it: prove it opens and closes.
    owners = {
        fields_from_prompt(p)["module_id"]: p
        for p in answers.prompts
        if fields_from_prompt(p)["module_id"] in OWNER_QUOTES
    }
    assert set(owners) == set(OWNER_QUOTES)
    for prompt in owners.values():
        tag = re.search(r"--- EVIDENCE ([0-9a-f]{16}) ---", prompt)
        assert tag is not None
        opened = re.findall(
            rf"^--- (?!END )([A-Z0-9 -]+?) {tag.group(1)}\b", prompt, re.M
        )
        closed = re.findall(rf"^--- END ([A-Z0-9 -]+?) {tag.group(1)}\b", prompt, re.M)
        assert "HOST FORECAST EXTENSION" in closed
        assert sorted(opened) == sorted(closed), (opened, closed)
    revision = save_revision(
        harness.conn,
        harness.blobs,
        harness.bundle,
        case_id=harness.case_id,
        run_id=harness.run_id,
        actor_id=harness.approver,
        narrative=[],
    )
    assert isinstance(revision, UUID)


@pytest.mark.parametrize(
    ("route", "signed"), [(c, c) for c in SIGNED], indirect=["route"]
)
def test_cp_cf_maps_each_cp2g_sign_to_the_calculator_end_to_end(
    harness: _Harness, signed: str
) -> None:
    """C2: CP-2G writes a dividend and an acquisition as the vendor's model
    adds them into net cash flow, `(45)`, and a disposal as 45; CP-CF's
    request carries the calculator's own inputs -- distributions 45,
    acquisitions_disposals 45, and -45 for the disposal -- and the route
    accepts the forecast those project, closing cash 100, 100 and 190. A zero
    written `(0)` or `-0` is the request's 0. Before, no dividend-paying
    forecast could pass, and the acquisition was accepted only as an inflow."""
    from conftest import priced
    from test_loop_charges import ESTIMATE

    from caos.graph.runtime import Execution, run_route

    cells, _movements, closing = SIGNED[signed]
    answers = ForecastCompletions(
        harness.source_id, request=signed_request(signed), cells=cells
    )
    run_route(
        harness.conn,
        harness.blobs,
        run_id=harness.run_id,
        route=harness.route,
        execution=Execution(
            _module_provider(harness, answers), priced(ESTIMATE), harness.bundle
        ),
    )
    assert _status(harness) == "COMPLETE"
    called = [fields_from_prompt(p)["module_id"] for p in answers.prompts]
    assert called.count("CP-CF") == 1, "accepted at the first attempt"
    result = forecast_projection(answers.answers[-1])
    assert result["rows"][0]["cash"]["closing"] == f"{closing}.000000"


@pytest.mark.parametrize("defect", ["missing", "wrong-owner", "result"])
def test_forecast_route_refuses_unbound_or_altered_projection(
    harness: _Harness, defect: str
) -> None:
    answers = ForecastCompletions(harness.source_id, defect=defect)
    assert (
        _run_route(harness, _module_provider(harness, answers))
        is RefusalCode.HANDOFF_INCOMPLETE
    )
    assert _status(harness) != "COMPLETE"


def test_forecast_cannot_drop_an_accepted_owner_restriction(harness: _Harness) -> None:
    answers = ForecastCompletions(harness.source_id)
    answers.qa_by_module = {"CP-1": "Restricted"}
    assert (
        _run_route(harness, _module_provider(harness, answers))
        is RefusalCode.HANDOFF_INCOMPLETE
    )


def test_forecast_retains_an_accepted_owner_restriction(harness: _Harness) -> None:
    answers = ForecastCompletions(harness.source_id, defect="retain-restriction")
    answers.qa_by_module = {"CP-1": "Restricted"}
    assert _run_route(harness, _module_provider(harness, answers)) is None
    assert _status(harness) == "COMPLETE"


def _forge_cp_cf(harness: _Harness, answers: ForecastCompletions) -> None:
    """Replace the accepted, restriction-retaining CP-CF artifact with a
    self-consistent forgery that drops the restriction it was accepted having
    kept, built by the exact same completion code with the defect off, so it
    is vendor-valid -- just no longer honest about what CP-1 restricted."""
    node = _node(harness, "CP-CF")
    row = harness.conn.execute(
        "SELECT attempt_id, artifact_sha256, record_sha256 FROM artifacts"
        " WHERE run_id=%s AND route_node_id=%s",
        (harness.run_id, node.route_node_id),
    ).fetchone()
    assert row is not None
    attempt, old_artifact, old_record = row
    identity = host_identity(
        harness.conn,
        harness.bundle,
        run_id=harness.run_id,
        route=harness.route,
        node=node,
        attempt_id=attempt,
    )
    record = read_record(
        harness.blobs,
        artifact_sha256=old_artifact,
        record_sha256=old_record,
        expected=identity,
    )
    [prompt] = [
        p for p in answers.prompts if fields_from_prompt(p)["module_id"] == "CP-CF"
    ]
    passed = ForecastCompletions(harness.source_id)
    passed.complete(prompt)
    markdown = passed.answers[-1]
    artifact = harness.blobs.put(markdown)
    projections = validate_markdown(
        CONTRACT,
        CATALOG,
        skill("CP-CF"),
        markdown,
        identity=identity,
        gate_expects=frozenset(),
    )
    record_sha = harness.blobs.put(
        record_bytes(replace(record, artifact_sha256=artifact, projections=projections))
    )
    tamper(
        harness.conn,
        "UPDATE artifacts SET artifact_sha256=%s, record_sha256=%s"
        " WHERE run_id=%s AND route_node_id=%s",
        (artifact, record_sha, harness.run_id, node.route_node_id),
    )
    harness.conn.commit()


def test_proof_and_payload_reject_a_self_consistent_cp_cf_restriction_forgery(
    harness: _Harness,
) -> None:
    """FP-32: `assert_orchestration_proof` and `canonical_payload` re-verify
    owner restrictions only when a node's `module_id == "CP-5"`; CP-CF (the
    forecast module, `MODEL_MODULE`) is the other module `_forecast_inputs`
    holds to the same rule at acceptance, and both proof callers must hold a
    later, forged artifact to it too."""
    answers = ForecastCompletions(harness.source_id, defect="retain-restriction")
    answers.qa_by_module = {"CP-1": "Restricted"}
    assert _run_route(harness, _module_provider(harness, answers)) is None
    assert _status(harness) == "COMPLETE"

    _forge_cp_cf(harness, answers)

    with pytest.raises(Refusal) as proof_refused:
        assert_orchestration_proof(
            harness.conn, harness.blobs, harness.bundle, run_id=harness.run_id
        )
    harness.conn.rollback()
    assert proof_refused.value.code is RefusalCode.ARTIFACT_RECORD_MISMATCH

    with pytest.raises(Refusal) as payload_refused:
        canonical_payload(
            harness.conn,
            harness.blobs,
            harness.bundle,
            Revision(
                harness.case_id,
                harness.run_id,
                BoundaryText.of("Acme Holdings plc"),
                BoundaryText.of("00000000-0000-0000-0000-000000000000"),
            ),
        )
    harness.conn.rollback()
    assert payload_refused.value.code is RefusalCode.ARTIFACT_RECORD_MISMATCH


def test_qualification_checks_host_recomputed_forecast_not_its_citation(
    harness: _Harness,
) -> None:
    """A matching CP-1 quote cannot hide a wrong CP-CF conclusion."""
    from conftest import priced
    from test_loop_charges import ESTIMATE

    from caos.graph.runtime import Execution, run_route

    limitations = (LIMITATION, "Forecast excludes uncommitted acquisitions")
    answers = ForecastCompletions(harness.source_id, limitations=limitations)
    run_route(
        harness.conn,
        harness.blobs,
        run_id=harness.run_id,
        route=harness.route,
        execution=Execution(
            _module_provider(harness, answers), priced(ESTIMATE), harness.bundle
        ),
    )
    row = harness.conn.execute(
        "SELECT document_sha256 FROM live_sources WHERE source_id = %s",
        (harness.source_id,),
    ).fetchone()
    assert row is not None
    document_sha256 = str(row[0])
    citation = next(
        quote
        for module, _document, quote in assert_orchestration_proof(
            harness.conn, harness.blobs, harness.bundle, run_id=harness.run_id
        ).anchored
        if module == "CP-1"
    )
    case = QualificationCase(
        label="acme-cf",
        documents=(
            Document(
                filename=BoundaryText.of("issuer-pack.txt"),
                data=harness.blobs.get(document_sha256),
            ),
        ),
        profile_id="FULL_CREDIT_32",
        selection_id="RELATIVE_VALUE",
        model_extension=True,
        expects=(ExpectedCitation("CP-1", document_sha256, citation),),
        forecast=ExpectedForecast(
            scenario="BASE",
            period_id="FY2026",
            values=(ForecastValue("cash.closing", "145.000000"),),
            currency="USD",
            scale="millions",
            perimeter="Consolidated",
            qa_status="Passed",
            limitation_flags=limitations,
            readiness=tuple(
                sorted(
                    (node.module_id, "READY")
                    for node in harness.route.nodes
                    if node.module_id not in {"CP-0", "CP-CF"}
                )
            ),
        ),
    )
    matrix = build_matrix(
        harness.conn,
        harness.blobs,
        harness.bundle,
        qualification=QualificationSet((case,)),
        runs={case.label: harness.run_id},
    )
    [qualified] = matrix.rows
    assert qualified.met == case.expects
    assert qualified.forecast_met is True

    assert case.forecast is not None
    reordered = replace(
        case.forecast,
        readiness=tuple(reversed(case.forecast.readiness)),
        limitation_flags=tuple(reversed(case.forecast.limitation_flags)),
    )
    [same_key] = build_matrix(
        harness.conn,
        harness.blobs,
        harness.bundle,
        qualification=QualificationSet((replace(case, forecast=reordered),)),
        runs={case.label: harness.run_id},
    ).rows
    assert same_key.forecast_met is True
    for forecast in (
        replace(case.forecast, perimeter="Parent"),
        replace(case.forecast, scale="units"),
        replace(
            case.forecast,
            values=(ForecastValue("cash.closing", "999.000000"),),
        ),
    ):
        wrong = QualificationSet((replace(case, forecast=forecast),))
        [mismatch] = build_matrix(
            harness.conn,
            harness.blobs,
            harness.bundle,
            qualification=wrong,
            runs={case.label: harness.run_id},
        ).rows
        assert mismatch.met == case.expects
        assert mismatch.forecast_met is False


_NET_EQUITY = (
    "| net_equity_issue_repay |  | BASE | FY2026 | 2026 | {value} | CURRENCY_MM"
    " | A-BASE-2026-net_equity_issue_repay- | {status} |"
)


class _NotApplicableDriver(ForecastCompletions):
    """CP-2G marks the `net_equity_issue_repay` row CP-CF needs NOT_APPLICABLE
    with a blank value: the status its own steps permit (G3-9)."""

    def complete(self, prompt: str, *, json_object: bool = False) -> Completion:
        done = super().complete(prompt, json_object=json_object)
        if fields_from_prompt(prompt)["module_id"] != "CP-2G":
            return done
        assert done.content is not None
        answer = json.loads(done.content)
        ready = _NET_EQUITY.format(value="0", status="READY")
        assert ready in answer["canonical_markdown"]
        answer["canonical_markdown"] = answer["canonical_markdown"].replace(
            ready, _NET_EQUITY.format(value="", status="NOT_APPLICABLE"), 1
        )
        return replace(done, content=json.dumps(answer))


def test_a_not_applicable_cp2g_driver_stops_cp_cf_as_not_ready(
    harness: _Harness,
) -> None:
    """G3-9: CP-2G's permitted NOT_APPLICABLE row is accepted as CP-2G's, and
    CP-CF then stops `FORECAST_DRIVER_NOT_READY` -- "Complete the driver
    first." -- with no second attempt, which could not change CP-2G's row. It
    was refused `HANDOFF_INCOMPLETE`, a malformed handoff, before."""
    answers = _NotApplicableDriver(harness.source_id)
    code = _run_route(harness, _module_provider(harness, answers))
    assert code is RefusalCode.FORECAST_DRIVER_NOT_READY
    called = [fields_from_prompt(p)["module_id"] for p in answers.prompts]
    assert called.count("CP-2G") == 1 and called.count("CP-CF") == 1
    assert _status(harness) != "COMPLETE"


class _MisMappedOnce(ForecastCompletions):
    """CP-CF's first answer puts 4 in the request's distributions, where
    CP-2G's `dividends_paid` row says 0; its second answer is right."""

    flawed: bool = False

    def complete(self, prompt: str, *, json_object: bool = False) -> Completion:
        done = super().complete(prompt, json_object=json_object)
        if fields_from_prompt(prompt)["module_id"] != "CP-CF" or self.flawed:
            return done
        self.flawed = True
        assert done.content is not None
        answer = json.loads(done.content)
        markdown = answer["canonical_markdown"]
        assert '"distributions": "0"' in markdown
        answer["canonical_markdown"] = markdown.replace(
            '"distributions": "0"', '"distributions": "4"', 1
        )
        return replace(done, content=json.dumps(answer))


def test_cp_cf_second_attempt_names_the_driver_row_it_could_not_map(
    harness: _Harness,
) -> None:
    """G3-9: CP-CF's one second attempt is told which CP-2G driver row its
    request did not match, by driver ID, case and period -- never a value.
    Priced at half the usual estimate, so the run's default ceiling covers the
    eleventh call the second attempt is."""
    from conftest import priced

    from caos.graph.runtime import Execution, run_route

    answers = _MisMappedOnce(harness.source_id)
    # Its completions bill at the price the run is executed at (N15).
    answers.price = priced(Decimal("0.25"))
    run_route(
        harness.conn,
        harness.blobs,
        run_id=harness.run_id,
        route=harness.route,
        execution=Execution(
            _module_provider(harness, answers), priced(Decimal("0.25")), harness.bundle
        ),
    )
    cf = [p for p in answers.prompts if fields_from_prompt(p)["module_id"] == "CP-CF"]
    assert len(cf) == 2
    assert "host driver check" not in cf[0]
    assert (
        "host driver check: CP-2G's `dividends_paid` row for BASE FY2026 does not"
        " equal the request's distributions" in cf[1]
    )
    assert _status(harness) == "COMPLETE"

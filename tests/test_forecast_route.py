"""The actual extended route accepts CP-CF only from anchored owner inputs."""

from __future__ import annotations

import json
import re
from dataclasses import replace
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest
from canonical_fixtures import AUTHORED, CATALOG, CONTRACT, fields_from_prompt, wire
from canonical_route_fixtures import LIMITATION, PACK, RouteCompletions
from forecast_fixtures import forecast_request
from lite_route_fixtures import _yaml
from test_canonical_runtime import _module_provider, _run_route, _status
from test_execution_freshness import _Harness
from test_relative_value_route import harness as _harness

from caos.boundary_text import BoundaryText
from caos.calculators.cash_flow import cash_flow_forecast
from caos.evidence.ingest import Document
from caos.graph.route import ResolvedRoute, RouteExtensions, resolve_route
from caos.methodology.forecast import forecast_projection
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
from caos.refusals import RefusalCode

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


ROWS = assignment_rows(request_data())
OWNER = {
    p: (
        "CP-4"
        if p.startswith("/contractual/")
        else "CP-2G"
        if p.startswith("/drivers/")
        else "CP-1"
    )
    for p in ROWS
}
OWNER_QUOTES = {
    m: "\n".join(v for p, v in ROWS.items() if OWNER[p] == m)
    for m in ("CP-1", "CP-2G", "CP-4")
}


@pytest.fixture
def route(monkeypatch: pytest.MonkeyPatch) -> ResolvedRoute:
    import test_relative_value_route

    monkeypatch.setattr(
        test_relative_value_route,
        "PACK",
        PACK + b"\n" + "\n".join(OWNER_QUOTES.values()).encode(),
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
    ) -> None:
        super().__init__(source_id, quotes_by_module=OWNER_QUOTES)
        self.defect = defect
        self.limitations = limitations

    def complete(self, prompt: str, *, json_object: bool = False) -> Completion:
        fields = fields_from_prompt(prompt)
        if fields["module_id"] != "CP-CF":
            return super().complete(prompt, json_object=json_object)
        self.prompts.append(prompt)
        request = request_data()
        bindings = {
            p: {"module_id": OWNER[p], "quote": OWNER_QUOTES[OWNER[p]]} for p in ROWS
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
        quotes = "\n".join(OWNER_QUOTES.values())
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
                    for q in OWNER_QUOTES.values()
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

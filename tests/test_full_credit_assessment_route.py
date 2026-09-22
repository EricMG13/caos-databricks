"""The deterministic 19-node ``FULL_CREDIT_ASSESSMENT`` route."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from canonical_fixtures import BUNDLE, CATALOG, CONTRACT, fields_from_prompt, skill
from conftest import _url_for, priced
from full_assessment_route_fixtures import (
    MODULES,
    ROUTE,
    ROUTE_PACK,
    ROUTE_QUOTES,
    SELECTION,
    FullAssessmentCompletions,
    route_identity,
    route_markdown,
)
from test_canonical_execution import _node
from test_canonical_runtime import _module_provider, _run_route, _status
from test_execution_freshness import _counts, _events, _Harness
from test_gates import _approval
from test_loop_charges import ESTIMATE

from caos.blobs import BlobStore
from caos.boundary_text import BoundaryText
from caos.evidence.ingest import Document, admit_pack
from caos.graph.route import ResolvedRoute, resolve_route
from caos.graph.runtime import Execution, run_route
from caos.methodology.handoff import (
    ADAPTER_MODULES,
    ADAPTER_ROUTES,
    invocation_fields,
)
from caos.provider import MAX_REQUEST_BYTES
from caos.qualification.proof import assert_orchestration_proof
from caos.store import StoreConnection, connect
from caos.store.gates import Gate, approve_gate
from caos.store.members import Standing, grant
from caos.store.routes import pin_route
from caos.store.run_inputs import RunSubject, pin_run_input
from caos.store.runs import start_run
from caos.store.source_sets import snapshot_source_set


@pytest.fixture
def route() -> ResolvedRoute:
    return resolve_route(CATALOG, *SELECTION)


@pytest.fixture
def harness(
    case: tuple[StoreConnection, UUID], tmp_path: Path, route: ResolvedRoute
) -> _Harness:
    conn, case_id = case
    blobs = BlobStore(tmp_path / "blobs")
    [source] = admit_pack(
        conn,
        blobs,
        case_id=case_id,
        documents=[
            Document(filename=BoundaryText.of("issuer-pack.txt"), data=ROUTE_PACK)
        ],
    )
    run_id = start_run(conn, case_id, budget_ceiling=Decimal("10"))
    conn.commit()
    source_set = snapshot_source_set(conn, case_id)
    pin_route(conn, run_id, route)
    pin_run_input(
        conn,
        run_id,
        source_set.version,
        BUNDLE,
        subject=RunSubject("ACME", "Acme Holdings plc", "FY2025", "2026-09-19"),
    )
    approver = uuid4()
    grant(conn, case_id=case_id, user_id=approver, standing=Standing.APPROVER)
    conn.commit()
    for gate in Gate:
        approve_gate(conn, _approval(conn, run_id, approver, gate))
    return _Harness(
        conn,
        case_id,
        run_id,
        source,
        source,
        blobs,
        route,
        BUNDLE,
        approver,
        _url_for(conn.info.dbname),
    )


def _modules(answers: FullAssessmentCompletions) -> list[str]:
    return [str(fields_from_prompt(prompt)["module_id"]) for prompt in answers.prompts]


def _run(harness: _Harness, answers: FullAssessmentCompletions) -> None:
    run_route(
        harness.conn,
        harness.blobs,
        run_id=harness.run_id,
        route=harness.route,
        execution=Execution(
            _module_provider(harness, answers), priced(ESTIMATE), BUNDLE
        ),
    )


def _attempts(harness: _Harness, module: str) -> tuple[int, int]:
    with connect(harness.url) as observer:
        row = observer.execute(
            "SELECT count(*), count(r.attempt_id) FROM run_attempts t"
            " LEFT JOIN budget_reservations r USING (attempt_id)"
            " WHERE t.route_node_id=%s",
            (_node(harness, module).route_node_id,),
        ).fetchone()
    assert row is not None
    return int(row[0]), int(row[1])


def test_full_credit_assessment_is_exact_and_enabled() -> None:
    pathways = sum(len(profile["pathways"]) for profile in CATALOG["profiles"].values())
    assert MODULES == (
        "CP-0",
        "CP-1",
        "CP-1A",
        "CP-2E",
        "CP-1B",
        "CP-1C",
        "CP-2A",
        "CP-1D",
        "CP-2",
        "CP-4",
        "CP-2D",
        "CP-2G",
        "CP-2H",
        "CP-3D",
        "CP-3C",
        "CP-4C",
        "CP-3",
        "CP-5",
        "CP-6",
    )
    assert len(ROUTE.edges) == 88
    assert set(MODULES) <= ADAPTER_MODULES
    assert SELECTION in ADAPTER_ROUTES
    assert (len(ADAPTER_ROUTES), pathways - len(ADAPTER_ROUTES)) == (18, 0)
    assert all(quote.encode() in ROUTE_PACK for quote in ROUTE_QUOTES.values())


@pytest.mark.parametrize("module", MODULES)
def test_every_full_assessment_handoff_is_vendor_valid(module: str) -> None:
    ident = route_identity(module)
    markdown = route_markdown(
        module,
        invocation_fields(CONTRACT, ident),
        "Restricted" if module in {"CP-1B", "CP-3C", "CP-6"} else "Passed",
        {},
    )
    assert CONTRACT.validate_handoff.validate_text(markdown.decode()).exit_code == 0
    assert (
        CONTRACT.completeness_check.check(
            skill(module).decode(), markdown.decode(), module
        )[0]
        == []
    )
    assert ROUTE_QUOTES[module].encode() in markdown


def test_cp5_register_preserves_upstream_qa_statuses() -> None:
    ident = route_identity("CP-5")
    markdown = route_markdown(
        "CP-5", invocation_fields(CONTRACT, ident), "Passed", {}
    ).decode()
    registers = CONTRACT.completeness_check.find_registers(markdown)
    statuses = {row["Module"]: row["QA Status"] for row in registers["T5.1"][1]}
    restricted = {
        module for module, status in statuses.items() if status == "Restricted"
    }
    assert restricted == {
        "CP-1A",
        "CP-1B",
        "CP-2E",
        "CP-2H",
        "CP-3C",
        "CP-4C",
    }


def test_cp6_describes_full_assessment_inputs_as_present() -> None:
    ident = route_identity("CP-6")
    markdown = route_markdown(
        "CP-6", invocation_fields(CONTRACT, ident), "Restricted", {}
    ).decode()
    assert "CP-2A is supplied as direct upstream" in markdown
    assert "CP-2D is supplied as direct upstream" in markdown
    assert "CP-3C is supplied as direct upstream" in markdown
    assert all(module not in markdown for module in ("CP-3A", "CP-3B", "CP-4A"))


def test_full_credit_assessment_completes_and_proves(harness: _Harness) -> None:
    answers = FullAssessmentCompletions(harness.source_id)
    _run(harness, answers)
    assert _status(harness) == "COMPLETE"
    assert _modules(answers) == list(MODULES)
    assert all(
        len(answers.request_bytes(prompt, json_object=True)) <= MAX_REQUEST_BYTES
        for prompt in answers.prompts
    )
    cp5_fields = next(
        fields_from_prompt(prompt)
        for prompt in answers.prompts
        if fields_from_prompt(prompt)["module_id"] == "CP-5"
    )
    assert len(cp5_fields["upstream_artifacts_used"]) == 16
    proof = assert_orchestration_proof(
        harness.conn, harness.blobs, BUNDLE, run_id=harness.run_id
    )
    harness.conn.rollback()
    assert (proof.artifacts, proof.citations) == (19, 19)
    assert {module for module, _, _ in proof.anchored} == set(MODULES)


def test_restricted_cp5_holds_cp6_without_work(harness: _Harness) -> None:
    answers = FullAssessmentCompletions(
        harness.source_id, qa_by_module={"CP-5": "Restricted"}
    )
    assert _run_route(harness, _module_provider(harness, answers)) is None
    assert _modules(answers) == list(MODULES[:-1])
    assert (_status(harness), _events(harness, "RUN_BLOCKED")) == ("BLOCKED", 1)
    assert _attempts(harness, "CP-6") == (0, 0)
    assert _counts(harness)[0] == 18

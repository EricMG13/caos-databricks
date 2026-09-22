"""The deterministic ``FULL_CREDIT_32 / PORTFOLIO_DECISION`` route."""

from __future__ import annotations

import hashlib
from dataclasses import replace
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from canonical_fixtures import BUNDLE, CATALOG, CONTRACT, fields_from_prompt
from conftest import _url_for, priced
from cp6_route_fixtures import (
    LIMITATION,
    MODULES,
    QUOTE,
    ROUTE,
    ROUTE_PACK,
    ROUTE_QUOTES,
    SELECTION,
    PortfolioDecisionCompletions,
)
from fastapi.testclient import TestClient
from test_api_routes import _section, _serve, _view
from test_canonical_execution import _node
from test_canonical_runtime import (
    _attempt_of,
    _blocking_verdict,
    _module_provider,
    _run_route,
    _status,
)
from test_execution_freshness import _counts, _events, _Harness
from test_gates import _approval
from test_lite_route_e2e_positive import _revision
from test_loop_charges import ESTIMATE

from caos.api import app as app_module
from caos.api.app import app
from caos.blobs import BlobStore
from caos.boundary_text import BoundaryText
from caos.deliverable.canonical import freeze_canonical, payload_bytes, verify_frozen
from caos.deliverable.filing import sign_opinion
from caos.deliverable.revisions import read_revision, save_revision
from caos.evidence.ingest import Document, admit_pack
from caos.graph.route import EdgeType, ResolvedRoute, resolve_route
from caos.graph.runtime import Execution, run_route
from caos.methodology.handoff import (
    ADAPTER_MODULES,
    ADAPTER_ROUTES,
    CanonicalRecord,
    read_record,
)
from caos.methodology.invocation import host_identity
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
    run_id = start_run(conn, case_id)
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


def _modules(answers: PortfolioDecisionCompletions) -> list[str]:
    return [str(fields_from_prompt(prompt)["module_id"]) for prompt in answers.prompts]


def _run(harness: _Harness, answers: PortfolioDecisionCompletions) -> None:
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


def _record(harness: _Harness, module: str) -> CanonicalRecord:
    node = _node(harness, module)
    row = harness.conn.execute(
        "SELECT attempt_id, artifact_sha256, record_sha256 FROM artifacts"
        " WHERE run_id=%s AND route_node_id=%s",
        (harness.run_id, node.route_node_id),
    ).fetchone()
    assert row is not None
    attempt, artifact, record = row
    return read_record(
        harness.blobs,
        artifact_sha256=artifact,
        record_sha256=record,
        expected=host_identity(
            harness.conn,
            BUNDLE,
            run_id=harness.run_id,
            route=harness.route,
            node=node,
            attempt_id=attempt,
        ),
    )


def test_portfolio_decision_route_is_exact_and_enabled() -> None:
    pathways = sum(len(profile["pathways"]) for profile in CATALOG["profiles"].values())
    assert "CP-6" in ADAPTER_MODULES
    assert SELECTION in ADAPTER_ROUTES
    assert (len(ADAPTER_ROUTES), pathways - len(ADAPTER_ROUTES)) == (18, 0)
    assert MODULES == (
        "CP-0",
        "CP-1",
        "CP-3D",
        "CP-2",
        "CP-4",
        "CP-3",
        "CP-5",
        "CP-6",
    )
    assert [(edge.source, edge.target, edge.type) for edge in ROUTE.edges] == [
        ("CP-0", "CP-1", EdgeType.REQUIRED),
        ("CP-0", "CP-2", EdgeType.REQUIRED),
        ("CP-0", "CP-3", EdgeType.REQUIRED),
        ("CP-0", "CP-4", EdgeType.REQUIRED),
        ("CP-0", "CP-5", EdgeType.REQUIRED),
        ("CP-0", "CP-6", EdgeType.REQUIRED),
        ("CP-1", "CP-2", EdgeType.REQUIRED),
        ("CP-1", "CP-3", EdgeType.REQUIRED),
        ("CP-1", "CP-4", EdgeType.REQUIRED),
        ("CP-1", "CP-6", EdgeType.REQUIRED),
        ("CP-2", "CP-3", EdgeType.REQUIRED),
        ("CP-2", "CP-6", EdgeType.REQUIRED),
        ("CP-3", "CP-6", EdgeType.REQUIRED),
        ("CP-5", "CP-6", EdgeType.QA_GATE),
        ("CP-1", "CP-5", EdgeType.ADVISORY),
        ("CP-2", "CP-5", EdgeType.ADVISORY),
        ("CP-3", "CP-5", EdgeType.ADVISORY),
        ("CP-4", "CP-5", EdgeType.ADVISORY),
        ("CP-4", "CP-3", EdgeType.ADVISORY),
        ("CP-0", "CP-3D", EdgeType.REQUIRED),
        ("CP-3D", "CP-3", EdgeType.OPTIONAL),
        ("CP-3D", "CP-5", EdgeType.ADVISORY),
        ("CP-3D", "CP-6", EdgeType.OPTIONAL),
    ]
    assert all(quote.encode() in ROUTE_PACK for quote in ROUTE_QUOTES.values())


def test_portfolio_decision_completes_proves_and_freezes(harness: _Harness) -> None:
    answers = PortfolioDecisionCompletions(harness.source_id)
    _run(harness, answers)
    assert _status(harness) == "COMPLETE"
    assert _modules(answers) == list(MODULES)
    assert all(
        len(answers.request_bytes(prompt, json_object=True)) <= MAX_REQUEST_BYTES
        for prompt in answers.prompts
    )
    handoffs = dict(zip(_modules(answers), answers.answers, strict=True))
    registers = CONTRACT.completeness_check.find_registers(handoffs["CP-5"].decode())
    severities = {
        row["Severity"]
        for _columns, rows in registers.values()
        for row in rows
        if "Severity" in row
    }
    assert severities == {"MINOR"}

    cp6 = _record(harness, "CP-6")
    assert cp6.projections.decision_scope == "FULL"
    assert cp6.projections.qa_status == "Restricted"
    assert cp6.projections.limitation_flags == (LIMITATION,)
    assert tuple(ref.module_id for ref in cp6.identity.upstream) == (
        "CP-0",
        "CP-1",
        "CP-2",
        "CP-3D",
        "CP-3",
        "CP-5",
    )
    assert {
        (citation.document_sha256, citation.matched_text) for citation in cp6.citations
    } == {(hashlib.sha256(ROUTE_PACK).hexdigest(), QUOTE)}
    assert all(citation.bboxes for citation in cp6.citations)

    cp5 = _record(harness, "CP-5")
    assert cp5.projections.qa_status == "Passed"
    assert cp5.projections.limitation_flags == ()
    assert tuple(ref.module_id for ref in cp5.identity.upstream) == (
        "CP-0",
        "CP-1",
        "CP-2",
        "CP-4",
        "CP-3D",
        "CP-3",
    )

    proof = assert_orchestration_proof(
        harness.conn, harness.blobs, BUNDLE, run_id=harness.run_id
    )
    harness.conn.rollback()
    assert (proof.artifacts, proof.citations) == (8, 8)
    assert {module for module, _, _ in proof.anchored} == set(MODULES)

    saved = save_revision(
        harness.conn,
        harness.blobs,
        BUNDLE,
        case_id=harness.case_id,
        run_id=harness.run_id,
        actor_id=harness.approver,
        narrative=[],
    )
    payload = read_revision(
        harness.conn, harness.blobs, case_id=harness.case_id, revision_id=saved
    )
    harness.conn.rollback()
    assert [artifact["route_node_id"] for artifact in payload["artifacts"]] == [
        node.route_node_id for node in ROUTE.nodes
    ]
    data = payload_bytes(payload)
    sign_opinion(
        harness.conn,
        case_id=harness.case_id,
        actor_id=harness.approver,
        revision_id=saved,
    )
    freezer = uuid4()
    grant(
        harness.conn,
        case_id=harness.case_id,
        user_id=freezer,
        standing=Standing.APPROVER,
    )
    harness.conn.commit()
    assert (
        freeze_canonical(
            harness.conn,
            harness.blobs,
            BUNDLE,
            replace(_revision(harness), revision_id=BoundaryText.of(str(saved))),
            actor_id=freezer,
        )
        == hashlib.sha256(data).hexdigest()
    )
    verify_frozen(
        harness.conn,
        harness.blobs,
        BUNDLE,
        case_id=harness.case_id,
        revision_id=saved,
        payload=data,
    )


def test_cp0_block_prevents_every_downstream_attempt_and_reservation(
    harness: _Harness,
) -> None:
    answers = PortfolioDecisionCompletions(
        harness.source_id,
        readiness={module: "BLOCKED" for module in MODULES[1:]},
    )
    assert _run_route(harness, _module_provider(harness, answers)) is None
    assert _modules(answers) == ["CP-0"]
    assert (_status(harness), _events(harness, "RUN_BLOCKED")) == ("BLOCKED", 1)
    assert _events(harness, "RUN_COMPLETE") == 0
    assert all(_attempts(harness, module) == (0, 0) for module in MODULES[1:])
    assert _counts(harness) == (1, [answers.charge], 1, 1, 1)
    assert _blocking_verdict(harness) is None


def test_restricted_cp5_holds_cp6_without_an_attempt(harness: _Harness) -> None:
    answers = PortfolioDecisionCompletions(
        harness.source_id, qa_by_module={"CP-5": "Restricted"}
    )
    assert _run_route(harness, _module_provider(harness, answers)) is None
    assert _modules(answers) == list(MODULES[:-1])
    assert (_status(harness), _events(harness, "RUN_BLOCKED")) == ("BLOCKED", 1)
    assert _record(harness, "CP-5").projections.qa_status == "Restricted"
    assert _attempts(harness, "CP-6") == (0, 0)
    assert _blocking_verdict(harness) is None


def test_blocked_cp5_terminates_before_cp6(harness: _Harness) -> None:
    answers = PortfolioDecisionCompletions(
        harness.source_id, qa_by_module={"CP-5": "Blocked"}
    )
    assert _run_route(harness, _module_provider(harness, answers)) is None
    assert _modules(answers) == list(MODULES[:-1])
    assert (_status(harness), _events(harness, "RUN_BLOCKED")) == ("BLOCKED", 1)
    assert _attempts(harness, "CP-6") == (0, 0)
    assert _blocking_verdict(harness) == _attempt_of(harness, "CP-5")


def test_restricted_cp5_gate_is_reported_over_http(
    harness: _Harness,
    empty_database: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    answers = PortfolioDecisionCompletions(
        harness.source_id, qa_by_module={"CP-5": "Restricted"}
    )
    assert _run_route(harness, _module_provider(harness, answers)) is None
    viewer = uuid4()
    grant(
        harness.conn,
        case_id=harness.case_id,
        user_id=viewer,
        standing=Standing.READER,
    )
    harness.conn.commit()
    monkeypatch.setenv(app_module.DATABASE_URL, empty_database)
    _serve(harness.conn, harness.blobs, BUNDLE)
    try:
        with TestClient(app) as client:
            body = _view(_section(client, harness.case_id, harness.run_id, viewer))
    finally:
        app.dependency_overrides.clear()
    cp6 = next(node for node in body["nodes"] if node["module_id"] == "CP-6")
    assert (cp6["state"], cp6["awaiting_gate"], cp6["gate_verdict"]) == (
        "BLOCKED",
        False,
        "Restricted",
    )
    assert cp6["waiting_on"] == [{"source": "CP-5", "type": "QA_GATE"}]

"""The deterministic ``FULL_CREDIT_32 / LIQUIDITY_REVIEW`` route."""

from __future__ import annotations

import hashlib
from dataclasses import replace
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from canonical_fixtures import BUNDLE, CATALOG, fields_from_prompt
from conftest import _url_for, priced
from liquidity_route_fixtures import (
    MODULES,
    PACK,
    ROUTE,
    SELECTION,
    LiquidityCompletions,
)
from test_canonical_execution import _node
from test_canonical_runtime import (
    _blocking_verdict,
    _module_provider,
    _run_route,
    _status,
)
from test_execution_freshness import _counts, _events, _Harness
from test_gates import _approval
from test_lite_route_e2e_positive import _revision
from test_loop_charges import ESTIMATE

from caos.blobs import BlobStore
from caos.boundary_text import BoundaryText
from caos.deliverable.canonical import freeze_canonical, payload_bytes, verify_frozen
from caos.deliverable.filing import sign_opinion
from caos.deliverable.revisions import read_revision, save_revision
from caos.evidence.ingest import Document, admit_pack
from caos.graph.route import ResolvedRoute, resolve_route
from caos.graph.runtime import Execution, run_route
from caos.methodology.handoff import ADAPTER_ROUTES, read_record
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
        documents=[Document(filename=BoundaryText.of("issuer-pack.txt"), data=PACK)],
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


def _modules(answers: LiquidityCompletions) -> list[str]:
    return [str(fields_from_prompt(prompt)["module_id"]) for prompt in answers.prompts]


def _attempts_at(harness: _Harness, module_id: str) -> tuple[int, int]:
    with connect(harness.url) as observer:
        row = observer.execute(
            "SELECT count(*), count(r.attempt_id) FROM run_attempts t"
            " LEFT JOIN budget_reservations r USING (attempt_id)"
            " WHERE t.route_node_id = %s",
            (_node(harness, module_id).route_node_id,),
        ).fetchone()
    assert row is not None
    return int(row[0]), int(row[1])


def run_completed(
    harness: _Harness, answers: LiquidityCompletions | None = None
) -> LiquidityCompletions:
    answers = answers or LiquidityCompletions(harness.source_id)
    run_route(
        harness.conn,
        harness.blobs,
        run_id=harness.run_id,
        route=harness.route,
        execution=Execution(
            _module_provider(harness, answers), priced(ESTIMATE), BUNDLE
        ),
    )
    assert _status(harness) == "COMPLETE"
    assert _modules(answers) == list(MODULES)
    return answers


def test_liquidity_route_completes_proves_and_freezes(harness: _Harness) -> None:
    assert SELECTION in ADAPTER_ROUTES
    assert MODULES == ("CP-0", "CP-1", "CP-2", "CP-2D")
    assert [(edge.source, edge.target) for edge in ROUTE.edges] == [
        ("CP-0", "CP-1"),
        ("CP-0", "CP-2"),
        ("CP-1", "CP-2"),
        ("CP-0", "CP-2D"),
        ("CP-1", "CP-2D"),
        ("CP-2", "CP-2D"),
    ]

    run_completed(harness)
    terminal = _node(harness, "CP-2D")
    row = harness.conn.execute(
        "SELECT attempt_id, artifact_sha256, record_sha256 FROM artifacts"
        " WHERE run_id=%s AND route_node_id=%s",
        (harness.run_id, terminal.route_node_id),
    ).fetchone()
    assert row is not None
    attempt_id, artifact_sha256, record_sha256 = row
    record = read_record(
        harness.blobs,
        artifact_sha256=artifact_sha256,
        record_sha256=record_sha256,
        expected=host_identity(
            harness.conn,
            BUNDLE,
            run_id=harness.run_id,
            route=harness.route,
            node=terminal,
            attempt_id=attempt_id,
        ),
    )
    assert record.projections.decision_scope == "FULL"
    assert {upstream.module_id for upstream in record.identity.upstream} == {
        "CP-0",
        "CP-1",
        "CP-2",
    }
    assert _events(harness, "RUN_COMPLETE") == 1
    proof = assert_orchestration_proof(
        harness.conn, harness.blobs, BUNDLE, run_id=harness.run_id
    )
    harness.conn.rollback()
    assert (proof.artifacts, proof.citations) == (4, 4)
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


def test_liquidity_requests_fit_the_request_ceiling(harness: _Harness) -> None:
    answers = run_completed(harness)
    assert len(answers.prompts) == 4
    assert all(
        len(answers.request_bytes(prompt, json_object=True)) <= MAX_REQUEST_BYTES
        for prompt in answers.prompts
    )


def test_a_blocked_cp0_calls_no_downstream_liquidity_modules(harness: _Harness) -> None:
    answers = LiquidityCompletions(harness.source_id, readiness={"CP-1": "BLOCKED"})
    assert _run_route(harness, _module_provider(harness, answers)) is None
    assert _modules(answers) == ["CP-0"]
    assert (_status(harness), _events(harness, "RUN_BLOCKED")) == ("BLOCKED", 1)
    assert _events(harness, "RUN_COMPLETE") == 0
    assert all(_attempts_at(harness, module) == (0, 0) for module in MODULES[1:])
    assert _counts(harness) == (1, [answers.charge], 1, 1, 1)
    assert _blocking_verdict(harness) is None

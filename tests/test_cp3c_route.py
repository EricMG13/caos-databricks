"""The deterministic ``FULL_CREDIT_32 / COVENANT_REFINANCING`` route."""

from __future__ import annotations

import hashlib
from dataclasses import replace
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from canonical_fixtures import BUNDLE, CATALOG, CONTRACT, fields_from_prompt
from conftest import _url_for, priced
from cp3c_route_fixtures import (
    LIMITATION,
    MODULES,
    QUOTE,
    ROUTE,
    ROUTE_PACK,
    ROUTE_QUOTES,
    SELECTION,
    RefinancingCompletions,
)
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

from caos.blobs import BlobStore
from caos.boundary_text import BoundaryText
from caos.deliverable.canonical import freeze_canonical, payload_bytes, verify_frozen
from caos.deliverable.filing import sign_opinion
from caos.deliverable.revisions import read_revision, save_revision
from caos.evidence.ingest import Document, admit_pack
from caos.graph.route import EdgeType, ResolvedRoute, resolve_route
from caos.graph.runtime import Execution, run_route
from caos.methodology.handoff import ADAPTER_MODULES, ADAPTER_ROUTES, read_record
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
        subject=RunSubject("ACME", "Acme Holdings", "FY2025", "2026-09-19"),
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


def _modules(answers: RefinancingCompletions) -> list[str]:
    return [str(fields_from_prompt(prompt)["module_id"]) for prompt in answers.prompts]


def _run(harness: _Harness, answers: RefinancingCompletions) -> None:
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


def test_covenant_refinancing_route_is_exact_and_enabled() -> None:
    assert "CP-3C" in ADAPTER_MODULES
    assert SELECTION in ADAPTER_ROUTES and len(ADAPTER_ROUTES) == 18
    assert MODULES == (
        "CP-0",
        "CP-1",
        "CP-4",
        "CP-2",
        "CP-2D",
        "CP-3C",
        "CP-5",
    )
    assert [(edge.source, edge.target, edge.type) for edge in ROUTE.edges] == [
        ("CP-0", "CP-1", EdgeType.REQUIRED),
        ("CP-0", "CP-2", EdgeType.REQUIRED),
        ("CP-0", "CP-4", EdgeType.REQUIRED),
        ("CP-0", "CP-5", EdgeType.REQUIRED),
        ("CP-1", "CP-2", EdgeType.REQUIRED),
        ("CP-1", "CP-4", EdgeType.REQUIRED),
        ("CP-1", "CP-5", EdgeType.ADVISORY),
        ("CP-2", "CP-5", EdgeType.ADVISORY),
        ("CP-4", "CP-5", EdgeType.ADVISORY),
        ("CP-0", "CP-2D", EdgeType.REQUIRED),
        ("CP-1", "CP-2D", EdgeType.REQUIRED),
        ("CP-2", "CP-2D", EdgeType.REQUIRED),
        ("CP-0", "CP-3C", EdgeType.REQUIRED),
        ("CP-1", "CP-3C", EdgeType.REQUIRED),
        ("CP-2D", "CP-3C", EdgeType.REQUIRED),
        ("CP-4", "CP-3C", EdgeType.OPTIONAL),
        ("CP-2D", "CP-5", EdgeType.ADVISORY),
        ("CP-3C", "CP-5", EdgeType.ADVISORY),
    ]
    assert all(quote.encode() in ROUTE_PACK for quote in ROUTE_QUOTES.values())


def test_covenant_refinancing_completes_proves_and_freezes(
    harness: _Harness,
) -> None:
    answers = RefinancingCompletions(harness.source_id)
    _run(harness, answers)
    assert _status(harness) == "COMPLETE"
    assert _modules(answers) == list(MODULES)
    assert all(
        len(answers.request_bytes(prompt, json_object=True)) <= MAX_REQUEST_BYTES
        for prompt in answers.prompts
    )
    handoffs = dict(zip(_modules(answers), answers.answers, strict=True))
    assert LIMITATION.encode() in handoffs["CP-3C"]
    assert LIMITATION.encode() in handoffs["CP-5"]
    cp5_registers = CONTRACT.completeness_check.find_registers(
        handoffs["CP-5"].decode()
    )
    severities = {
        row["Severity"]
        for _columns, rows in cp5_registers.values()
        for row in rows
        if "Severity" in row
    }
    assert severities == {"MATERIAL"}

    cp3c = _node(harness, "CP-3C")
    row = harness.conn.execute(
        "SELECT attempt_id, artifact_sha256, record_sha256 FROM artifacts"
        " WHERE run_id=%s AND route_node_id=%s",
        (harness.run_id, cp3c.route_node_id),
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
            node=cp3c,
            attempt_id=attempt_id,
        ),
    )
    assert record.projections.decision_scope == "FULL"
    assert record.projections.qa_status == "Restricted"
    assert record.projections.limitation_flags == (LIMITATION,)
    assert tuple(ref.module_id for ref in record.identity.upstream) == (
        "CP-0",
        "CP-1",
        "CP-4",
        "CP-2D",
    )
    actual = {
        (citation.document_sha256, citation.matched_text)
        for citation in record.citations
    }
    assert actual == {(hashlib.sha256(ROUTE_PACK).hexdigest(), QUOTE)}
    assert all(citation.bboxes for citation in record.citations)

    cp5 = _node(harness, "CP-5")
    cp5_row = harness.conn.execute(
        "SELECT attempt_id, artifact_sha256, record_sha256 FROM artifacts"
        " WHERE run_id=%s AND route_node_id=%s",
        (harness.run_id, cp5.route_node_id),
    ).fetchone()
    assert cp5_row is not None
    cp5_attempt, cp5_artifact, cp5_record = cp5_row
    terminal = read_record(
        harness.blobs,
        artifact_sha256=cp5_artifact,
        record_sha256=cp5_record,
        expected=host_identity(
            harness.conn,
            BUNDLE,
            run_id=harness.run_id,
            route=harness.route,
            node=cp5,
            attempt_id=cp5_attempt,
        ),
    )
    assert terminal.projections.qa_status == "Restricted"
    assert terminal.projections.limitation_flags == (LIMITATION,)

    proof = assert_orchestration_proof(
        harness.conn, harness.blobs, BUNDLE, run_id=harness.run_id
    )
    harness.conn.rollback()
    assert (proof.artifacts, proof.citations) == (7, 7)
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
    answers = RefinancingCompletions(harness.source_id, readiness={"CP-1": "BLOCKED"})
    assert _run_route(harness, _module_provider(harness, answers)) is None
    assert _modules(answers) == ["CP-0"]
    assert (_status(harness), _events(harness, "RUN_BLOCKED")) == ("BLOCKED", 1)
    assert _events(harness, "RUN_COMPLETE") == 0
    assert all(_attempts(harness, module) == (0, 0) for module in MODULES[1:])
    assert _counts(harness) == (1, [answers.charge], 1, 1, 1)
    assert _blocking_verdict(harness) is None


def test_validated_blocked_cp3c_terminates_the_route(harness: _Harness) -> None:
    answers = RefinancingCompletions(
        harness.source_id, qa_by_module={"CP-3C": "Blocked"}
    )
    assert _run_route(harness, _module_provider(harness, answers)) is None
    modules = _modules(answers)
    assert modules == list(MODULES[:-1])
    assert (_status(harness), _events(harness, "RUN_BLOCKED")) == ("BLOCKED", 1)
    assert _events(harness, "RUN_COMPLETE") == 0
    blocked = hashlib.sha256(
        answers.bodies[modules.index("CP-3C")].encode()
    ).hexdigest()
    with connect(harness.url) as observer:
        row = observer.execute(
            "SELECT count(*) FROM call_outcomes o JOIN run_attempts t"
            " USING (attempt_id) WHERE o.diagnostic_sha256=%s"
            " AND t.route_node_id=%s AND NOT EXISTS"
            " (SELECT 1 FROM artifacts a WHERE a.attempt_id=o.attempt_id)",
            (blocked, _node(harness, "CP-3C").route_node_id),
        ).fetchone()
    assert row == (1,)
    assert _blocking_verdict(harness) == _attempt_of(harness, "CP-3C")
    assert _attempts(harness, "CP-5") == (0, 0)

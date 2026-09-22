"""The deterministic FULL decision-ledger route (CP-0 -> CP-8)."""

from __future__ import annotations

import hashlib
from dataclasses import replace
from uuid import uuid4

import pytest
from canonical_fixtures import BUNDLE, CATALOG
from canonical_route_fixtures import (
    LEDGER_PACK,
    LEDGER_QUOTES,
    LedgerCompletions,
)
from conftest import priced
from test_canonical_execution import _node
from test_canonical_runtime import (
    _attempt_of,
    _blocking_verdict,
    _module_provider,
    _run_route,
    _status,
)
from test_execution_freshness import _counts, _events, _Harness
from test_lite_decision_ledger_route import (
    _attempts_at,
    _modules,
)
from test_lite_decision_ledger_route import (
    harness as _ledger_harness,
)
from test_lite_route_e2e_positive import _revision
from test_loop_charges import ESTIMATE

from caos.boundary_text import BoundaryText
from caos.deliverable.canonical import freeze_canonical, payload_bytes, verify_frozen
from caos.deliverable.filing import sign_opinion
from caos.deliverable.revisions import read_revision, save_revision
from caos.graph.route import EdgeType, ResolvedRoute, resolve_route
from caos.graph.runtime import Execution, run_route
from caos.methodology.handoff import ADAPTER_ROUTES, read_record
from caos.methodology.invocation import host_identity
from caos.provider import MAX_REQUEST_BYTES
from caos.qualification.proof import assert_orchestration_proof
from caos.store import connect
from caos.store.members import Standing, grant

FULL_LEDGER = ("FULL_CREDIT_32", "DECISION_LEDGER")
_registered_harness = pytest.fixture(name="harness")(
    _ledger_harness.__wrapped__  # type: ignore[attr-defined]
)


@pytest.fixture
def route() -> ResolvedRoute:
    return resolve_route(CATALOG, *FULL_LEDGER)


def run_completed(
    harness: _Harness, answers: LedgerCompletions | None = None
) -> LedgerCompletions:
    answers = answers or LedgerCompletions(
        harness.source_id, harness.witness_id, selection=FULL_LEDGER
    )
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
    assert _modules(answers) == [node.module_id for node in harness.route.nodes]
    return answers


def test_full_decision_ledger_completes_proves_and_freezes(
    harness: _Harness,
) -> None:
    modules = tuple(node.module_id for node in harness.route.nodes)
    assert modules == ("CP-0", "CP-8")
    assert [(edge.source, edge.target, edge.type) for edge in harness.route.edges] == [
        ("CP-0", "CP-8", EdgeType.REQUIRED)
    ]
    assert harness.route.nodes[-1].module_id == "CP-8"
    assert FULL_LEDGER in ADAPTER_ROUTES

    run_completed(harness)
    assert _events(harness, "RUN_COMPLETE") == 1
    proof = assert_orchestration_proof(
        harness.conn, harness.blobs, BUNDLE, run_id=harness.run_id
    )
    harness.conn.rollback()
    assert proof.artifacts == 2
    assert proof.citations == 3
    assert {module for module, _, _ in proof.anchored} == set(modules)

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
        node.route_node_id for node in harness.route.nodes
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


def test_full_cp8_projects_full_scope_exact_lineage_and_sources(
    harness: _Harness,
) -> None:
    run_completed(harness)
    node = _node(harness, "CP-8")
    row = harness.conn.execute(
        "SELECT attempt_id, artifact_sha256, record_sha256 FROM artifacts"
        " WHERE run_id=%s AND route_node_id=%s",
        (harness.run_id, node.route_node_id),
    ).fetchone()
    assert row is not None
    attempt, artifact, record_sha = row
    ident = host_identity(
        harness.conn,
        BUNDLE,
        run_id=harness.run_id,
        route=harness.route,
        node=node,
        attempt_id=attempt,
    )
    record = read_record(
        harness.blobs,
        artifact_sha256=artifact,
        record_sha256=record_sha,
        expected=ident,
    )
    assert record.projections.module_id == "CP-8"
    assert record.projections.decision_scope == "FULL"
    assert tuple(ref.module_id for ref in ident.upstream) == ("CP-0",)
    actual = {
        (citation.document_sha256, citation.matched_text)
        for citation in record.citations
    }
    assert actual == {
        (hashlib.sha256(LEDGER_PACK[document]).hexdigest(), quote)
        for document, quote in LEDGER_QUOTES["CP-8"]
    }
    assert all(citation.bboxes for citation in record.citations)
    harness.conn.rollback()


def test_full_decision_ledger_requests_fit_the_ceiling(harness: _Harness) -> None:
    answers = run_completed(harness)
    assert len(answers.prompts) == 2
    assert all(
        len(answers.request_bytes(prompt, json_object=True)) <= MAX_REQUEST_BYTES
        for prompt in answers.prompts
    )


def test_full_cp0_block_prevents_cp8_attempt_and_reservation(
    harness: _Harness,
) -> None:
    answers = LedgerCompletions(
        harness.source_id,
        harness.witness_id,
        selection=FULL_LEDGER,
        readiness={"CP-8": "BLOCKED"},
    )
    assert _run_route(harness, _module_provider(harness, answers)) is None
    assert _modules(answers) == ["CP-0"]
    assert (_status(harness), _events(harness, "RUN_BLOCKED")) == ("BLOCKED", 1)
    assert _attempts_at(harness, "CP-8") == (0, 0)
    assert _counts(harness) == (1, [answers.charge], 1, 1, 1)
    assert _blocking_verdict(harness) is None


def test_full_validated_blocked_cp8_ends_the_run_blocked(
    harness: _Harness,
) -> None:
    answers = LedgerCompletions(
        harness.source_id,
        harness.witness_id,
        selection=FULL_LEDGER,
        qa_by_module={"CP-8": "Blocked"},
    )
    assert _run_route(harness, _module_provider(harness, answers)) is None
    assert _modules(answers) == ["CP-0", "CP-8"]
    assert (_status(harness), _events(harness, "RUN_BLOCKED")) == ("BLOCKED", 1)
    assert _counts(harness) == (2, [answers.charge] * 2, 1, 2, 2)
    blocked = hashlib.sha256(answers.bodies[1].encode()).hexdigest()
    with connect(harness.url) as observer:
        row = observer.execute(
            "SELECT count(*) FROM call_outcomes o JOIN run_attempts t"
            " USING (attempt_id) WHERE o.diagnostic_sha256 = %s"
            " AND t.route_node_id = %s AND NOT EXISTS"
            " (SELECT 1 FROM artifacts a WHERE a.attempt_id = o.attempt_id)",
            (blocked, _node(harness, "CP-8").route_node_id),
        ).fetchone()
    assert row == (1,)
    assert _blocking_verdict(harness) == _attempt_of(harness, "CP-8")

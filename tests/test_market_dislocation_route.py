"""The deterministic ``FULL_CREDIT_32 / MARKET_DISLOCATION`` route."""

from __future__ import annotations

import hashlib
from dataclasses import replace
from uuid import uuid4

import pytest
from canonical_fixtures import BUNDLE, CATALOG, fields_from_prompt
from canonical_route_fixtures import LIMITATION, PACK, QUOTES, RouteCompletions
from conftest import priced
from test_canonical_execution import _node
from test_canonical_runtime import _module_provider, _run_route, _status
from test_execution_freshness import _counts, _events, _Harness
from test_lite_route_e2e_positive import _revision
from test_loop_charges import ESTIMATE
from test_relative_value_route import harness

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
from caos.store.members import Standing, grant

__all__ = ["harness"]

SELECTION = ("FULL_CREDIT_32", "MARKET_DISLOCATION")
MODULES = ("CP-0", "CP-3D")


@pytest.fixture
def route() -> ResolvedRoute:
    return resolve_route(CATALOG, *SELECTION)


def _answers(
    harness: _Harness,
    *,
    readiness: dict[str, str] | None = None,
    qa_by_module: dict[str, str] | None = None,
) -> RouteCompletions:
    return RouteCompletions(
        harness.source_id,
        selection=SELECTION,
        readiness=readiness or {},
        qa_by_module=qa_by_module or {},
    )


def _run(harness: _Harness, answers: RouteCompletions) -> None:
    run_route(
        harness.conn,
        harness.blobs,
        run_id=harness.run_id,
        route=harness.route,
        execution=Execution(
            _module_provider(harness, answers), priced(ESTIMATE), BUNDLE
        ),
    )


def test_market_dislocation_route_is_exact_and_enabled() -> None:
    route = resolve_route(CATALOG, *SELECTION)
    assert tuple(node.module_id for node in route.nodes) == MODULES
    assert [(edge.source, edge.target, edge.type) for edge in route.edges] == [
        ("CP-0", "CP-3D", EdgeType.REQUIRED)
    ]
    assert SELECTION in ADAPTER_ROUTES
    assert QUOTES["CP-3D"].encode() in PACK


def test_market_dislocation_completes_proves_and_freezes(
    harness: _Harness,
) -> None:
    answers = _answers(harness)
    _run(harness, answers)
    assert _status(harness) == "COMPLETE"
    assert [fields_from_prompt(prompt)["module_id"] for prompt in answers.prompts] == [
        *MODULES
    ]
    assert all(
        len(answers.request_bytes(prompt, json_object=True)) <= MAX_REQUEST_BYTES
        for prompt in answers.prompts
    )
    assert _events(harness, "RUN_COMPLETE") == 1

    proof = assert_orchestration_proof(
        harness.conn, harness.blobs, BUNDLE, run_id=harness.run_id
    )
    harness.conn.rollback()
    assert proof.artifacts == proof.citations == 2
    assert {module for module, _, _ in proof.anchored} == set(MODULES)

    cp3d = _node(harness, "CP-3D")
    row = harness.conn.execute(
        "SELECT attempt_id, artifact_sha256, record_sha256 FROM artifacts"
        " WHERE run_id=%s AND route_node_id=%s",
        (harness.run_id, cp3d.route_node_id),
    ).fetchone()
    assert row is not None
    attempt, artifact, record_sha = row
    record = read_record(
        harness.blobs,
        artifact_sha256=artifact,
        record_sha256=record_sha,
        expected=host_identity(
            harness.conn,
            BUNDLE,
            run_id=harness.run_id,
            route=harness.route,
            node=cp3d,
            attempt_id=attempt,
        ),
    )
    assert record.projections.decision_scope == "FULL"
    assert {citation.matched_text for citation in record.citations} == {QUOTES["CP-3D"]}

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
    data = payload_bytes(payload)
    # FP-33: the signer must be independent of the actor who saved the
    # narrative (`harness.approver`), so a fresh approver signs here.
    signer = uuid4()
    grant(
        harness.conn,
        case_id=harness.case_id,
        user_id=signer,
        standing=Standing.APPROVER,
    )
    harness.conn.commit()
    sign_opinion(
        harness.conn,
        case_id=harness.case_id,
        actor_id=signer,
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


def test_blocked_market_owner_never_attempts_cp3d(harness: _Harness) -> None:
    answers = _answers(harness, readiness={"CP-3D": "BLOCKED"})
    assert _run_route(harness, _module_provider(harness, answers)) is None
    assert [fields_from_prompt(prompt)["module_id"] for prompt in answers.prompts] == [
        "CP-0"
    ]
    assert _status(harness) == "BLOCKED"
    assert _counts(harness) == (1, [answers.charge], 1, 1, 1)


def test_restricted_market_analysis_keeps_its_limitation(harness: _Harness) -> None:
    answers = _answers(harness, qa_by_module={"CP-3D": "Restricted"})
    _run(harness, answers)
    assert _status(harness) == "COMPLETE"
    assert LIMITATION in answers.answers[-1].decode()

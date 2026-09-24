"""The deterministic ``LITE_CREDIT_22 / LITE_COVENANT_REFINANCING`` route."""

from __future__ import annotations

import hashlib
from dataclasses import replace
from uuid import uuid4

import pytest
from canonical_fixtures import BUNDLE, CATALOG, fields_from_prompt
from conftest import priced
from cp3c_route_fixtures import (
    LIMITATION,
    RefinancingCompletions,
)
from test_canonical_execution import _node
from test_canonical_runtime import _module_provider, _run_route, _status
from test_cp3c_route import _attempts, harness
from test_execution_freshness import _counts, _events, _Harness
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
from caos.store.members import Standing, grant

__all__ = ["harness"]

SELECTION = ("LITE_CREDIT_22", "LITE_COVENANT_REFINANCING")
MODULES = ("CP-0", "CP-L10", "CP-3C", "CP-5")


@pytest.fixture
def route() -> ResolvedRoute:
    return resolve_route(CATALOG, *SELECTION)


def _answers(
    harness: _Harness,
    *,
    readiness: dict[str, str] | None = None,
    qa_by_module: dict[str, str] | None = None,
) -> RefinancingCompletions:
    return RefinancingCompletions(
        harness.source_id,
        selection=SELECTION,
        readiness=readiness or {},
        qa_by_module=qa_by_module or {},
    )


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


def _modules(answers: RefinancingCompletions) -> list[str]:
    return [str(fields_from_prompt(prompt)["module_id"]) for prompt in answers.prompts]


def test_lite_covenant_refinancing_route_is_exact_and_enabled() -> None:
    route = resolve_route(CATALOG, *SELECTION)
    assert tuple(node.module_id for node in route.nodes) == MODULES
    assert [(edge.source, edge.target, edge.type) for edge in route.edges] == [
        ("CP-0", "CP-5", EdgeType.REQUIRED),
        ("CP-L10", "CP-5", EdgeType.ADVISORY),
        ("CP-0", "CP-L10", EdgeType.REQUIRED),
        ("CP-0", "CP-3C", EdgeType.REQUIRED),
        ("CP-L10", "CP-3C", EdgeType.REQUIRED),
        ("CP-3C", "CP-5", EdgeType.ADVISORY),
    ]
    assert SELECTION in ADAPTER_ROUTES and len(ADAPTER_ROUTES) == 18


def test_lite_covenant_refinancing_completes_proves_and_freezes(
    harness: _Harness,
) -> None:
    answers = _answers(harness)
    _run(harness, answers)
    assert _status(harness) == "COMPLETE"
    assert _modules(answers) == list(MODULES)
    assert all(
        len(answers.request_bytes(prompt, json_object=True)) <= MAX_REQUEST_BYTES
        for prompt in answers.prompts
    )
    assert _events(harness, "RUN_COMPLETE") == 1

    cp0 = _node(harness, "CP-0")
    row = harness.conn.execute(
        "SELECT attempt_id, artifact_sha256, record_sha256 FROM artifacts"
        " WHERE run_id=%s AND route_node_id=%s",
        (harness.run_id, cp0.route_node_id),
    ).fetchone()
    assert row is not None
    attempt, cp0_artifact, record_sha = row
    cp0_record = read_record(
        harness.blobs,
        artifact_sha256=cp0_artifact,
        record_sha256=record_sha,
        expected=host_identity(
            harness.conn,
            BUNDLE,
            run_id=harness.run_id,
            route=harness.route,
            node=cp0,
            attempt_id=attempt,
        ),
    )
    assert cp0_record.projections.readiness == tuple(
        (module, "READY") for module in sorted(MODULES[1:])
    )

    cp3c = _node(harness, "CP-3C")
    row = harness.conn.execute(
        "SELECT attempt_id, artifact_sha256, record_sha256 FROM artifacts"
        " WHERE run_id=%s AND route_node_id=%s",
        (harness.run_id, cp3c.route_node_id),
    ).fetchone()
    assert row is not None
    attempt, cp3c_artifact, record_sha = row
    record = read_record(
        harness.blobs,
        artifact_sha256=cp3c_artifact,
        record_sha256=record_sha,
        expected=host_identity(
            harness.conn,
            BUNDLE,
            run_id=harness.run_id,
            route=harness.route,
            node=cp3c,
            attempt_id=attempt,
        ),
    )
    assert record.projections.decision_scope == "SCREENING_ONLY"
    assert record.projections.qa_status == "Restricted"
    assert record.projections.limitation_flags == (LIMITATION,)

    cp5 = _node(harness, "CP-5")
    row = harness.conn.execute(
        "SELECT attempt_id, artifact_sha256, record_sha256 FROM artifacts"
        " WHERE run_id=%s AND route_node_id=%s",
        (harness.run_id, cp5.route_node_id),
    ).fetchone()
    assert row is not None
    attempt, cp5_artifact, record_sha = row
    cp5_record = read_record(
        harness.blobs,
        artifact_sha256=cp5_artifact,
        record_sha256=record_sha,
        expected=host_identity(
            harness.conn,
            BUNDLE,
            run_id=harness.run_id,
            route=harness.route,
            node=cp5,
            attempt_id=attempt,
        ),
    )
    assert tuple(ref.module_id for ref in cp5_record.identity.upstream) == (
        "CP-0",
        "CP-L10",
        "CP-3C",
    )
    assert (
        next(
            ref.sha256
            for ref in cp5_record.identity.upstream
            if ref.module_id == "CP-3C"
        )
        == cp3c_artifact
    )
    assert cp5_record.projections.qa_status == record.projections.qa_status
    assert cp5_record.projections.limitation_flags == (
        record.projections.limitation_flags
    )
    cp5_prompt = answers.prompts[_modules(answers).index("CP-5")]
    assert "module_id: CP-3C" in cp5_prompt
    assert LIMITATION in cp5_prompt

    proof = assert_orchestration_proof(
        harness.conn, harness.blobs, BUNDLE, run_id=harness.run_id
    )
    harness.conn.rollback()
    assert proof.artifacts == proof.citations == 4
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


def test_blocked_lite_refinancing_owner_never_attempts_downstream(
    harness: _Harness,
) -> None:
    answers = _answers(harness, readiness={"CP-L10": "BLOCKED"})
    assert _run_route(harness, _module_provider(harness, answers)) is None
    assert _modules(answers) == ["CP-0"]
    assert (_status(harness), _events(harness, "RUN_BLOCKED")) == ("BLOCKED", 1)
    assert all(_attempts(harness, module) == (0, 0) for module in MODULES[1:])
    assert _counts(harness) == (1, [answers.charge], 1, 1, 1)


def test_restricted_cp3c_propagates_to_cp5(harness: _Harness) -> None:
    answers = _answers(harness)
    _run(harness, answers)
    assert _status(harness) == "COMPLETE"
    assert LIMITATION.encode() in answers.answers[-1]
    assert _modules(answers) == list(MODULES)

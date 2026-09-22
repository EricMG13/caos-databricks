"""The deterministic ``LITE_CREDIT_22 / LITE_DISTRESSED_RESTRUCTURING`` route."""

from __future__ import annotations

import hashlib
from dataclasses import replace
from uuid import uuid4

import pytest
from canonical_fixtures import BUNDLE, CATALOG, fields_from_prompt
from conftest import priced
from cp2h_contract_fixtures import LIMITATION as RATINGS_LIMITATION
from cp4c_contract_fixtures import LIMITATION as RESTRUCTURING_LIMITATION
from full_assessment_route_fixtures import ROUTE_QUOTES, FullAssessmentCompletions
from test_canonical_execution import _node
from test_canonical_runtime import _module_provider, _run_route, _status
from test_execution_freshness import _counts, _events, _Harness
from test_full_credit_assessment_route import _attempts, harness
from test_lite_route_e2e_positive import _revision
from test_loop_charges import ESTIMATE

from caos.boundary_text import BoundaryText
from caos.deliverable.canonical import freeze_canonical, payload_bytes, verify_frozen
from caos.deliverable.filing import sign_opinion
from caos.deliverable.revisions import read_revision, save_revision
from caos.graph.route import EdgeType, ResolvedRoute, resolve_route
from caos.graph.runtime import Execution, run_route
from caos.methodology.handoff import ADAPTER_ROUTES, CanonicalRecord, read_record
from caos.methodology.invocation import host_identity
from caos.provider import MAX_REQUEST_BYTES
from caos.qualification.proof import assert_orchestration_proof
from caos.store.members import Standing, grant

__all__ = ["harness"]

SELECTION = ("LITE_CREDIT_22", "LITE_DISTRESSED_RESTRUCTURING")
MODULES = ("CP-0", "CP-L10", "CP-2A", "CP-2H", "CP-4C")


@pytest.fixture
def route() -> ResolvedRoute:
    return resolve_route(CATALOG, *SELECTION)


def _answers(
    harness: _Harness, *, readiness: dict[str, str] | None = None
) -> FullAssessmentCompletions:
    return FullAssessmentCompletions(
        harness.source_id, selection=SELECTION, readiness=readiness or {}
    )


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


def _modules(answers: FullAssessmentCompletions) -> list[str]:
    return [str(fields_from_prompt(prompt)["module_id"]) for prompt in answers.prompts]


def _record(harness: _Harness, module: str) -> tuple[str, CanonicalRecord]:
    node = _node(harness, module)
    row = harness.conn.execute(
        "SELECT attempt_id, artifact_sha256, record_sha256 FROM artifacts"
        " WHERE run_id=%s AND route_node_id=%s",
        (harness.run_id, node.route_node_id),
    ).fetchone()
    assert row is not None
    attempt, artifact, record_sha = row
    return artifact, read_record(
        harness.blobs,
        artifact_sha256=artifact,
        record_sha256=record_sha,
        expected=host_identity(
            harness.conn,
            BUNDLE,
            run_id=harness.run_id,
            route=harness.route,
            node=node,
            attempt_id=attempt,
        ),
    )


def test_lite_distressed_restructuring_route_is_exact_and_enabled() -> None:
    route = resolve_route(CATALOG, *SELECTION)
    assert tuple(node.module_id for node in route.nodes) == MODULES
    assert [(edge.source, edge.target, edge.type) for edge in route.edges] == [
        ("CP-0", "CP-2A", EdgeType.REQUIRED),
        ("CP-0", "CP-2H", EdgeType.REQUIRED),
        ("CP-0", "CP-4C", EdgeType.REQUIRED),
        ("CP-L10", "CP-2H", EdgeType.REQUIRED),
        ("CP-L10", "CP-4C", EdgeType.REQUIRED),
        ("CP-2A", "CP-4C", EdgeType.REQUIRED),
        ("CP-0", "CP-L10", EdgeType.REQUIRED),
        ("CP-L10", "CP-2A", EdgeType.REQUIRED),
    ]
    assert SELECTION in ADAPTER_ROUTES


def test_lite_distressed_restructuring_completes_proves_and_freezes(
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

    _cp0_artifact, cp0 = _record(harness, "CP-0")
    assert cp0.projections.readiness == (
        ("CP-2A", "READY"),
        ("CP-2H", "READY"),
        ("CP-4C", "READY"),
        ("CP-L10", "READY"),
    )
    cp2h_artifact, cp2h = _record(harness, "CP-2H")
    cp4c_artifact, cp4c = _record(harness, "CP-4C")
    assert (
        cp2h.projections.decision_scope
        == cp4c.projections.decision_scope
        == "SCREENING_ONLY"
    )
    assert cp2h.projections.qa_status == cp4c.projections.qa_status == "Restricted"
    assert cp2h.projections.limitation_flags == (RATINGS_LIMITATION,)
    assert cp4c.projections.limitation_flags == (RESTRUCTURING_LIMITATION,)
    assert {citation.matched_text for citation in cp2h.citations} == {
        ROUTE_QUOTES["CP-2H"]
    }
    assert {citation.matched_text for citation in cp4c.citations} == {
        ROUTE_QUOTES["CP-4C"]
    }
    assert tuple(ref.module_id for ref in cp4c.identity.upstream) == (
        "CP-0",
        "CP-L10",
        "CP-2A",
    )
    assert {ref.sha256 for ref in cp4c.identity.upstream} == {
        _record(harness, module)[0] for module in ("CP-0", "CP-L10", "CP-2A")
    }
    handoffs = dict(zip(_modules(answers), answers.answers, strict=True))
    assert RATINGS_LIMITATION in handoffs["CP-2H"].decode()
    assert RESTRUCTURING_LIMITATION in handoffs["CP-4C"].decode()
    assert cp2h_artifact and cp4c_artifact

    proof = assert_orchestration_proof(
        harness.conn, harness.blobs, BUNDLE, run_id=harness.run_id
    )
    harness.conn.rollback()
    assert proof.artifacts == proof.citations == len(MODULES)
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


def test_blocked_lite_distressed_owner_never_attempts_downstream(
    harness: _Harness,
) -> None:
    answers = _answers(harness, readiness={"CP-L10": "BLOCKED"})
    assert _run_route(harness, _module_provider(harness, answers)) is None
    assert _modules(answers) == ["CP-0"]
    assert (_status(harness), _events(harness, "RUN_BLOCKED")) == ("BLOCKED", 1)
    assert all(_attempts(harness, module) == (0, 0) for module in MODULES[1:])
    assert _counts(harness) == (1, [answers.charge], 1, 1, 1)

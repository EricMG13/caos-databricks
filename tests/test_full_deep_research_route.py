"""The deterministic FULL deep-research contract (CP-0 -> CP-DR).

This proves the existing research adapter under FULL identity. It uses the
same supplied-only evidence and deterministic provider as the LITE contract;
no live provider or qualification corpus is involved.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from uuid import uuid4

import pytest
from canonical_fixtures import BUNDLE, CATALOG
from canonical_route_fixtures import (
    RESEARCH_BRIEF,
    RESEARCH_PACK,
    RESEARCH_QUOTES,
    ResearchCompletions,
    research_section,
)
from conftest import priced
from test_canonical_execution import _node
from test_canonical_runtime import (
    _blocking_verdict,
    _module_provider,
    _run_route,
    _status,
)
from test_execution_freshness import _counts, _events, _Harness
from test_lite_deep_research_route import (
    _attempts_at,
    _modules,
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
from caos.store.members import Standing, grant

FULL_RESEARCH = ("FULL_CREDIT_32", "DEEP_RESEARCH")


@pytest.fixture
def route() -> ResolvedRoute:
    return resolve_route(CATALOG, *FULL_RESEARCH)


def run_completed(
    harness: _Harness, answers: ResearchCompletions | None = None
) -> ResearchCompletions:
    answers = answers or ResearchCompletions(
        harness.source_id, harness.witness_id, selection=FULL_RESEARCH
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


def test_full_deep_research_route_completes_proves_and_freezes(
    harness: _Harness,
) -> None:
    modules = tuple(node.module_id for node in harness.route.nodes)
    assert modules == ("CP-0", "CP-DR")
    assert [(edge.source, edge.target, edge.type) for edge in harness.route.edges] == [
        ("CP-0", "CP-DR", EdgeType.REQUIRED)
    ]
    assert harness.route.nodes[-1].module_id == "CP-DR"
    assert FULL_RESEARCH in ADAPTER_ROUTES

    run_completed(harness)
    assert _events(harness, "RUN_COMPLETE") == 1
    proof = assert_orchestration_proof(
        harness.conn, harness.blobs, BUNDLE, run_id=harness.run_id
    )
    harness.conn.rollback()
    assert proof.artifacts == 2
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


def test_full_cp_dr_identity_brief_projection_citations_and_ceiling(
    harness: _Harness,
) -> None:
    answers = run_completed(harness)
    cp0 = _node(harness, "CP-0")
    cp_dr = _node(harness, "CP-DR")
    row = harness.conn.execute(
        "SELECT attempt_id, artifact_sha256, record_sha256 FROM artifacts"
        " WHERE run_id=%s AND route_node_id=%s",
        (harness.run_id, cp_dr.route_node_id),
    ).fetchone()
    assert row is not None
    attempt, artifact, record_sha = row
    identity = host_identity(
        harness.conn,
        BUNDLE,
        run_id=harness.run_id,
        route=harness.route,
        node=cp_dr,
        attempt_id=attempt,
    )
    record = read_record(
        harness.blobs,
        artifact_sha256=artifact,
        record_sha256=record_sha,
        expected=identity,
    )
    cp0_sha256 = harness.conn.execute(
        "SELECT artifact_sha256 FROM artifacts WHERE run_id=%s AND route_node_id=%s",
        (harness.run_id, cp0.route_node_id),
    ).fetchone()
    assert cp0_sha256 is not None
    harness.conn.rollback()

    assert (record.identity.profile_id, record.identity.selection_id) == FULL_RESEARCH
    assert record.projections.decision_scope == "FULL"
    assert json.loads(str(record.identity.research_brief)) == {
        **RESEARCH_BRIEF,
        "run_id": record.identity.run_id,
        "cp0_sha256": cp0_sha256[0],
        "authority_sha256": record.identity.authority_bundle_sha256,
    }
    assert research_section(answers.prompts[1]) == record.identity.research_brief
    citations = {
        (citation.document_sha256, citation.matched_text)
        for citation in record.citations
    }
    assert citations == {
        (hashlib.sha256(RESEARCH_PACK[document]).hexdigest(), quote)
        for document, quote in RESEARCH_QUOTES["CP-DR"]
    }
    assert len(answers.prompts) == 2
    assert all(
        len(answers.request_bytes(prompt, json_object=True)) <= MAX_REQUEST_BYTES
        for prompt in answers.prompts
    )


def test_blocked_full_cp0_never_attempts_cp_dr(harness: _Harness) -> None:
    answers = ResearchCompletions(
        harness.source_id,
        harness.witness_id,
        selection=FULL_RESEARCH,
        readiness={"CP-DR": "BLOCKED"},
    )
    assert _run_route(harness, _module_provider(harness, answers)) is None
    assert _modules(answers) == ["CP-0"]
    assert _status(harness) == "BLOCKED"
    assert _attempts_at(harness, "CP-DR") == (0, 0)
    assert _counts(harness) == (1, [answers.charge], 1, 1, 1)
    assert _blocking_verdict(harness) is None

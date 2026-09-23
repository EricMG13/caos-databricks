"""The deterministic ``FULL_CREDIT_32 / DISTRESSED_RESTRUCTURING`` route."""

from __future__ import annotations

import hashlib
from dataclasses import replace
from uuid import uuid4

import pytest
from canonical_fixtures import BUNDLE, CATALOG, fields_from_prompt
from conftest import priced
from full_assessment_route_fixtures import (
    ROUTE_PACK,
    ROUTE_QUOTES,
    FullAssessmentCompletions,
)
from test_canonical_runtime import (
    _attempt_of,
    _blocking_verdict,
    _module_provider,
    _run_route,
    _status,
)
from test_execution_freshness import _counts, _events, _Harness
from test_full_credit_assessment_route import _attempts, harness
from test_lite_full_credit_screen_route import _record
from test_lite_route_e2e_positive import _revision
from test_loop_charges import ESTIMATE

from caos.boundary_text import BoundaryText
from caos.deliverable.canonical import freeze_canonical, payload_bytes, verify_frozen
from caos.deliverable.filing import sign_opinion
from caos.deliverable.revisions import read_revision, save_revision
from caos.graph.route import EdgeType, ResolvedRoute, resolve_route
from caos.graph.runtime import Execution, run_route
from caos.methodology.handoff import ADAPTER_ROUTES
from caos.provider import MAX_REQUEST_BYTES
from caos.qualification.proof import assert_orchestration_proof
from caos.store.members import Standing, grant

__all__ = ["harness"]

SELECTION = ("FULL_CREDIT_32", "DISTRESSED_RESTRUCTURING")
MODULES = (
    "CP-0",
    "CP-1",
    "CP-2",
    "CP-2A",
    "CP-4",
    "CP-2D",
    "CP-2G",
    "CP-3C",
    "CP-2H",
    "CP-4C",
    "CP-3",
    "CP-5",
    "CP-6",
)
EDGES = [
    ("CP-0", "CP-1", EdgeType.REQUIRED),
    ("CP-0", "CP-2", EdgeType.REQUIRED),
    ("CP-0", "CP-2A", EdgeType.REQUIRED),
    ("CP-0", "CP-2G", EdgeType.REQUIRED),
    ("CP-0", "CP-2H", EdgeType.REQUIRED),
    ("CP-0", "CP-3", EdgeType.REQUIRED),
    ("CP-0", "CP-4C", EdgeType.REQUIRED),
    ("CP-0", "CP-4", EdgeType.REQUIRED),
    ("CP-0", "CP-5", EdgeType.REQUIRED),
    ("CP-0", "CP-6", EdgeType.REQUIRED),
    ("CP-1", "CP-2", EdgeType.REQUIRED),
    ("CP-1", "CP-2A", EdgeType.REQUIRED),
    ("CP-1", "CP-2G", EdgeType.REQUIRED),
    ("CP-1", "CP-2H", EdgeType.REQUIRED),
    ("CP-1", "CP-3", EdgeType.REQUIRED),
    ("CP-1", "CP-4C", EdgeType.REQUIRED),
    ("CP-1", "CP-4", EdgeType.REQUIRED),
    ("CP-1", "CP-6", EdgeType.REQUIRED),
    ("CP-2", "CP-3", EdgeType.REQUIRED),
    ("CP-2", "CP-6", EdgeType.REQUIRED),
    ("CP-2A", "CP-2G", EdgeType.REQUIRED),
    ("CP-2G", "CP-2H", EdgeType.REQUIRED),
    ("CP-2G", "CP-4C", EdgeType.REQUIRED),
    ("CP-2H", "CP-3", EdgeType.OPTIONAL),
    ("CP-4", "CP-4C", EdgeType.REQUIRED),
    ("CP-3", "CP-6", EdgeType.REQUIRED),
    ("CP-2A", "CP-6", EdgeType.OPTIONAL),
    ("CP-2G", "CP-3", EdgeType.OPTIONAL),
    ("CP-2A", "CP-4C", EdgeType.REQUIRED),
    ("CP-5", "CP-6", EdgeType.QA_GATE),
    ("CP-1", "CP-5", EdgeType.ADVISORY),
    ("CP-2", "CP-5", EdgeType.ADVISORY),
    ("CP-2A", "CP-5", EdgeType.ADVISORY),
    ("CP-2G", "CP-5", EdgeType.ADVISORY),
    ("CP-2H", "CP-5", EdgeType.ADVISORY),
    ("CP-3", "CP-5", EdgeType.ADVISORY),
    ("CP-4C", "CP-5", EdgeType.ADVISORY),
    ("CP-4", "CP-5", EdgeType.ADVISORY),
    ("CP-4", "CP-3", EdgeType.ADVISORY),
    ("CP-0", "CP-2D", EdgeType.REQUIRED),
    ("CP-1", "CP-2D", EdgeType.REQUIRED),
    ("CP-2", "CP-2D", EdgeType.REQUIRED),
    ("CP-0", "CP-3C", EdgeType.REQUIRED),
    ("CP-1", "CP-3C", EdgeType.REQUIRED),
    ("CP-2D", "CP-3C", EdgeType.REQUIRED),
    ("CP-2D", "CP-2G", EdgeType.OPTIONAL),
    ("CP-2A", "CP-3C", EdgeType.OPTIONAL),
    ("CP-4", "CP-3C", EdgeType.OPTIONAL),
    ("CP-3C", "CP-4C", EdgeType.OPTIONAL),
    ("CP-3C", "CP-3", EdgeType.OPTIONAL),
    ("CP-4C", "CP-3", EdgeType.OPTIONAL),
    ("CP-2D", "CP-5", EdgeType.ADVISORY),
    ("CP-3C", "CP-5", EdgeType.ADVISORY),
    ("CP-2D", "CP-3", EdgeType.OPTIONAL),
    ("CP-2D", "CP-6", EdgeType.OPTIONAL),
    ("CP-3C", "CP-6", EdgeType.OPTIONAL),
]


@pytest.fixture
def route() -> ResolvedRoute:
    return resolve_route(CATALOG, *SELECTION)


def _answers(
    harness: _Harness,
    *,
    readiness: dict[str, str] | None = None,
    qa_by_module: dict[str, str] | None = None,
) -> FullAssessmentCompletions:
    return FullAssessmentCompletions(
        harness.source_id,
        selection=SELECTION,
        readiness=readiness or {},
        qa_by_module=qa_by_module or {},
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


def test_distressed_restructuring_route_is_exact() -> None:
    route = resolve_route(CATALOG, *SELECTION)
    assert tuple(node.module_id for node in route.nodes) == MODULES
    assert [(edge.source, edge.target, edge.type) for edge in route.edges] == EDGES
    assert len(EDGES) == 56


def test_distressed_restructuring_completes_proves_and_freezes(
    harness: _Harness,
) -> None:
    assert SELECTION in ADAPTER_ROUTES
    answers = _answers(harness)
    _run(harness, answers)
    assert (_status(harness), _events(harness, "RUN_COMPLETE")) == ("COMPLETE", 1)
    assert _modules(answers) == list(MODULES)
    assert all(
        len(answers.request_bytes(prompt, json_object=True)) <= MAX_REQUEST_BYTES
        for prompt in answers.prompts
    )

    artifacts = {module: _record(harness, module)[0] for module in MODULES}
    records = {module: _record(harness, module)[1] for module in MODULES}
    assert records["CP-0"].identity.upstream == ()
    assert records["CP-0"].projections.readiness == tuple(
        (module, "READY") for module in sorted(MODULES[1:])
    )
    assert all(
        record.projections.decision_scope == "FULL" for record in records.values()
    )
    for module, record in records.items():
        direct = {source for source, target, _edge_type in EDGES if target == module}
        assert {ref.module_id for ref in record.identity.upstream} == direct
        assert {ref.module_id: ref.sha256 for ref in record.identity.upstream} == {
            source: artifacts[source] for source in direct
        }
        assert {citation.matched_text for citation in record.citations} == {
            ROUTE_QUOTES[module]
        }
        assert {citation.document_sha256 for citation in record.citations} == {
            hashlib.sha256(ROUTE_PACK).hexdigest()
        }
        assert all(citation.bboxes for citation in record.citations)

    assert records["CP-5"].projections.qa_status == "Passed"
    assert _attempts(harness, "CP-6") == (1, 1)
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


def test_cp0_block_prevents_every_downstream_attempt_and_reservation(
    harness: _Harness,
) -> None:
    answers = _answers(harness, readiness={module: "BLOCKED" for module in MODULES[1:]})
    assert _run_route(harness, _module_provider(harness, answers)) is None
    assert _modules(answers) == ["CP-0"]
    assert (_status(harness), _events(harness, "RUN_BLOCKED")) == ("BLOCKED", 1)
    assert all(_attempts(harness, module) == (0, 0) for module in MODULES[1:])
    assert _counts(harness) == (1, [answers.charge], 1, 1, 1)


@pytest.mark.parametrize("qa_status", ["Blocked"])
def test_cp5_gate_holds_cp6_without_an_attempt_or_reservation(
    harness: _Harness, qa_status: str
) -> None:
    answers = _answers(harness, qa_by_module={"CP-5": qa_status})
    assert _run_route(harness, _module_provider(harness, answers)) is None
    assert _modules(answers) == list(MODULES[:-1])
    assert (_status(harness), _events(harness, "RUN_BLOCKED")) == ("BLOCKED", 1)
    assert _attempts(harness, "CP-6") == (0, 0)
    if qa_status == "Blocked":
        assert _blocking_verdict(harness) == _attempt_of(harness, "CP-5")
    else:
        assert _record(harness, "CP-5")[1].projections.qa_status == "Restricted"
        assert _blocking_verdict(harness) is None

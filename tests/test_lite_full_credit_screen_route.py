"""The deterministic ``LITE_CREDIT_22 / LITE_FULL_CREDIT_SCREEN`` route."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from uuid import uuid4

import pytest
from canonical_fixtures import BUNDLE, CATALOG, CONTRACT, fields_from_prompt, skill
from conftest import priced
from cp1a_contract_fixtures import LIMITATION as SPONSOR_LIMITATION
from cp2h_contract_fixtures import LIMITATION as RATINGS_LIMITATION
from cp3c_route_fixtures import LIMITATION as REFINANCING_LIMITATION
from cp4c_contract_fixtures import LIMITATION as RESTRUCTURING_LIMITATION
from full_assessment_route_fixtures import ROUTE_QUOTES, FullAssessmentCompletions
from test_canonical_execution import _node
from test_canonical_runtime import _module_provider, _run_route, _status
from test_execution_freshness import _counts, _events, _Harness
from test_full_credit_assessment_route import _attempts, harness
from test_lite_route_e2e_positive import _revision
from test_loop_charges import ESTIMATE
from test_runtime import _Boom, _DiesAfterItsBill

from caos.boundary_text import BoundaryText
from caos.deliverable.canonical import (
    canonical_payload,
    freeze_canonical,
    payload_bytes,
    verify_frozen,
)
from caos.deliverable.filing import sign_opinion
from caos.deliverable.revisions import read_revision, save_revision
from caos.graph.route import EdgeType, ResolvedRoute, resolve_route
from caos.graph.runtime import Execution, run_route
from caos.methodology.canonical import accepted_handoff, accepted_projections
from caos.methodology.handoff import (
    ADAPTER_ROUTES,
    CanonicalRecord,
    read_record,
    record_bytes,
    validate_markdown,
)
from caos.methodology.invocation import host_identity
from caos.methodology.verification import AcceptedRow, verify_owner_restrictions
from caos.provider import MAX_REQUEST_BYTES, Completion
from caos.qualification.proof import assert_orchestration_proof
from caos.refusals import Refusal, RefusalCode
from caos.store.members import Standing, grant

__all__ = ["harness"]

SELECTION = ("LITE_CREDIT_22", "LITE_FULL_CREDIT_SCREEN")
MODULES = (
    "CP-0",
    "CP-L10",
    "CP-1A",
    "CP-1C",
    "CP-2A",
    "CP-2H",
    "CP-3C",
    "CP-4C",
    "CP-5",
)
RESTRICTED = {
    "CP-1A": SPONSOR_LIMITATION,
    "CP-2H": RATINGS_LIMITATION,
    "CP-3C": REFINANCING_LIMITATION,
    "CP-4C": RESTRUCTURING_LIMITATION,
}


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


class _StrippingCp5(FullAssessmentCompletions):
    """A vendor-valid CP-5 that lies about its restricted direct inputs."""

    def complete(self, prompt: str, *, json_object: bool = False) -> Completion:
        answer = super().complete(prompt, json_object=json_object)
        if fields_from_prompt(prompt)["module_id"] != "CP-5":
            return answer
        assert answer.content is not None
        body = json.loads(answer.content)
        markdown = _stripped_cp5(body["canonical_markdown"])
        body["canonical_markdown"] = markdown
        self.answers[-1] = markdown.encode()
        return replace(answer, content=json.dumps(body))


def _stripped_cp5(markdown: str) -> str:
    limitation_flags = next(
        line for line in markdown.splitlines() if line.startswith("limitation_flags: ")
    )
    for old, new in (
        ("confidence_score: 50", "confidence_score: 90"),
        ('confidence_band: "Low"', 'confidence_band: "High"'),
        ('committee_status: "Restricted"', 'committee_status: "Draft Only"'),
        (limitation_flags, "limitation_flags: []"),
        ('qa_status: "Restricted"', 'qa_status: "Passed"'),
        ("MATERIAL", "MINOR"),
    ):
        assert old in markdown
        markdown = markdown.replace(old, new)
    return markdown


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


def _forge_cp5(harness: _Harness) -> AcceptedRow:
    """Replace CP-5 with a vendor-valid, self-consistent legacy forgery."""
    node = _node(harness, "CP-5")
    row = harness.conn.execute(
        "SELECT attempt_id, artifact_sha256, record_sha256 FROM artifacts"
        " WHERE run_id=%s AND route_node_id=%s",
        (harness.run_id, node.route_node_id),
    ).fetchone()
    assert row is not None
    attempt, old_artifact, old_record = row
    identity = host_identity(
        harness.conn,
        BUNDLE,
        run_id=harness.run_id,
        route=harness.route,
        node=node,
        attempt_id=attempt,
    )
    record = read_record(
        harness.blobs,
        artifact_sha256=old_artifact,
        record_sha256=old_record,
        expected=identity,
    )
    markdown = _stripped_cp5(harness.blobs.get(old_artifact).decode()).encode()
    artifact = harness.blobs.put(markdown)
    projections = validate_markdown(
        CONTRACT,
        CATALOG,
        skill("CP-5"),
        markdown,
        identity=identity,
        gate_expects=frozenset(),
    )
    record_sha = harness.blobs.put(
        record_bytes(replace(record, artifact_sha256=artifact, projections=projections))
    )
    harness.conn.execute(
        "UPDATE artifacts SET artifact_sha256=%s, record_sha256=%s"
        " WHERE run_id=%s AND route_node_id=%s",
        (artifact, record_sha, harness.run_id, node.route_node_id),
    )
    harness.conn.commit()
    return AcceptedRow(
        run_id=harness.run_id,
        route_node_id=node.route_node_id,
        attempt_id=attempt,
        artifact_sha256=artifact,
        record_sha256=record_sha,
    )


def test_lite_full_credit_screen_route_is_exact_and_enabled() -> None:
    route = resolve_route(CATALOG, *SELECTION)
    assert tuple(node.module_id for node in route.nodes) == MODULES
    assert [(edge.source, edge.target, edge.type) for edge in route.edges] == [
        ("CP-0", "CP-1A", EdgeType.REQUIRED),
        ("CP-0", "CP-1C", EdgeType.REQUIRED),
        ("CP-0", "CP-2A", EdgeType.REQUIRED),
        ("CP-0", "CP-2H", EdgeType.REQUIRED),
        ("CP-0", "CP-4C", EdgeType.REQUIRED),
        ("CP-0", "CP-5", EdgeType.REQUIRED),
        ("CP-L10", "CP-1C", EdgeType.REQUIRED),
        ("CP-L10", "CP-2H", EdgeType.REQUIRED),
        ("CP-L10", "CP-4C", EdgeType.REQUIRED),
        ("CP-2A", "CP-4C", EdgeType.REQUIRED),
        ("CP-L10", "CP-5", EdgeType.ADVISORY),
        ("CP-1A", "CP-5", EdgeType.ADVISORY),
        ("CP-1C", "CP-5", EdgeType.ADVISORY),
        ("CP-2A", "CP-5", EdgeType.ADVISORY),
        ("CP-2H", "CP-5", EdgeType.ADVISORY),
        ("CP-4C", "CP-5", EdgeType.ADVISORY),
        ("CP-0", "CP-L10", EdgeType.REQUIRED),
        ("CP-L10", "CP-2A", EdgeType.REQUIRED),
        ("CP-0", "CP-3C", EdgeType.REQUIRED),
        ("CP-L10", "CP-3C", EdgeType.REQUIRED),
        ("CP-3C", "CP-4C", EdgeType.OPTIONAL),
        ("CP-3C", "CP-5", EdgeType.ADVISORY),
    ]
    assert SELECTION in ADAPTER_ROUTES


def test_lite_full_credit_screen_completes_proves_and_freezes(
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

    cp0_artifact, cp0 = _record(harness, "CP-0")
    assert cp0.projections.readiness == tuple(
        (module, "READY") for module in sorted(MODULES[1:])
    )
    assert cp0.identity.upstream == ()

    artifacts = {module: _record(harness, module)[0] for module in MODULES}
    records = {module: _record(harness, module)[1] for module in MODULES}
    assert all(
        record.projections.decision_scope == "SCREENING_ONLY"
        for record in records.values()
    )
    assert all(
        {citation.matched_text for citation in records[module].citations}
        == {ROUTE_QUOTES.get(module, ROUTE_QUOTES["CP-0"])}
        for module in MODULES
    )
    for module, limitation in RESTRICTED.items():
        assert records[module].projections.qa_status == "Restricted"
        assert records[module].projections.limitation_flags == (limitation,)

    cp5 = records["CP-5"]
    direct = {"CP-0", "CP-L10", "CP-1A", "CP-1C", "CP-2A", "CP-2H", "CP-3C", "CP-4C"}
    assert {ref.module_id for ref in cp5.identity.upstream} == direct
    assert {ref.module_id: ref.sha256 for ref in cp5.identity.upstream} == {
        module: artifacts[module] for module in direct
    }
    assert cp5.projections.qa_status == "Restricted"
    assert cp5.projections.limitation_flags == tuple(RESTRICTED.values())
    cp5_prompt = answers.prompts[_modules(answers).index("CP-5")]
    for module, limitation in RESTRICTED.items():
        assert f"module_id: {module}" in cp5_prompt
        assert limitation in cp5_prompt
    assert cp0_artifact

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


def test_cp5_cannot_strip_restricted_direct_upstream_limits(
    harness: _Harness,
) -> None:
    answers = _StrippingCp5(harness.source_id, selection=SELECTION)
    assert (
        _run_route(harness, _module_provider(harness, answers))
        is RefusalCode.HANDOFF_INCOMPLETE
    )
    assert _modules(answers)[-1] == "CP-5"
    with pytest.raises(Refusal) as direct:
        verify_owner_restrictions(
            CONTRACT,
            answers.answers[-1],
            answers.answers[:-1],
            refuse=RefusalCode.HANDOFF_INCOMPLETE,
            selection=SELECTION,
        )
    assert direct.value.code is RefusalCode.HANDOFF_INCOMPLETE
    for module, limitation in RESTRICTED.items():
        _artifact, record = _record(harness, module)
        assert record.projections.qa_status == "Restricted"
        assert record.projections.limitation_flags == (limitation,)
    node = _node(harness, "CP-5")
    assert harness.conn.execute(
        "SELECT COUNT(*) FROM artifacts WHERE run_id=%s AND route_node_id=%s",
        (harness.run_id, node.route_node_id),
    ).fetchone() == (0,)


def test_billed_cp5_replay_cannot_strip_restricted_direct_upstream_limits(
    harness: _Harness,
) -> None:
    answers = _StrippingCp5(harness.source_id, selection=SELECTION)
    with pytest.raises(_Boom):
        _run_route(
            harness,
            _DiesAfterItsBill(_module_provider(harness, answers)),  # type: ignore[arg-type]
        )
    assert _modules(answers).count("CP-5") == 1
    # The replay itself makes no call; N52 then gives CP-5 its one second
    # attempt, which strips the same limits and is refused the same way.
    assert (
        _run_route(harness, _module_provider(harness, answers))
        is RefusalCode.HANDOFF_INCOMPLETE
    )
    assert _modules(answers).count("CP-5") == 2
    assert _attempts(harness, "CP-5") == (2, 2)


def test_accepted_cp5_reads_reject_a_self_consistent_restriction_forgery(
    harness: _Harness,
) -> None:
    _run(harness, _answers(harness))
    row = _forge_cp5(harness)
    for read in (accepted_handoff, accepted_projections):
        with pytest.raises(Refusal) as refused:
            read(harness.conn, harness.blobs, BUNDLE, harness.route, row)
        harness.conn.rollback()
        assert refused.value.code is RefusalCode.HANDOFF_INCOMPLETE


def test_proof_rejects_a_self_consistent_cp5_restriction_forgery(
    harness: _Harness,
) -> None:
    _run(harness, _answers(harness))
    _forge_cp5(harness)
    with pytest.raises(Refusal) as refused:
        assert_orchestration_proof(
            harness.conn, harness.blobs, BUNDLE, run_id=harness.run_id
        )
    harness.conn.rollback()
    assert refused.value.code is RefusalCode.ARTIFACT_RECORD_MISMATCH


def test_payload_and_freeze_reject_a_self_consistent_cp5_restriction_forgery(
    harness: _Harness,
) -> None:
    _run(harness, _answers(harness))
    saved = save_revision(
        harness.conn,
        harness.blobs,
        BUNDLE,
        case_id=harness.case_id,
        run_id=harness.run_id,
        actor_id=harness.approver,
        narrative=[],
    )
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
    _forge_cp5(harness)
    revision = replace(_revision(harness), revision_id=BoundaryText.of(str(saved)))
    with pytest.raises(Refusal) as payload_refused:
        canonical_payload(harness.conn, harness.blobs, BUNDLE, revision)
    harness.conn.rollback()
    assert payload_refused.value.code is RefusalCode.ARTIFACT_RECORD_MISMATCH
    with pytest.raises(Refusal) as freeze_refused:
        freeze_canonical(
            harness.conn,
            harness.blobs,
            BUNDLE,
            revision,
            actor_id=freezer,
        )
    harness.conn.rollback()
    assert freeze_refused.value.code is RefusalCode.ARTIFACT_RECORD_MISMATCH


def test_blocked_lite_full_credit_screen_owner_never_attempts_downstream(
    harness: _Harness,
) -> None:
    answers = _answers(harness, readiness={module: "BLOCKED" for module in MODULES[1:]})
    assert _run_route(harness, _module_provider(harness, answers)) is None
    assert _modules(answers) == ["CP-0"]
    assert (_status(harness), _events(harness, "RUN_BLOCKED")) == ("BLOCKED", 1)
    assert all(_attempts(harness, module) == (0, 0) for module in MODULES[1:])
    assert _counts(harness) == (1, [answers.charge], 1, 1, 1)

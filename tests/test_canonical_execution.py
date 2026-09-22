"""The canonical executor: one call, billing first, then a validated handoff and
its host record, or a typed refusal (Task 3.1 slice c-5a; §41, §42).

The claims path's guarantees carry over unchanged -- the attempt, the stored
identity and the upstream are rechecked after transport -- and three are new:
the Markdown is the vendor's conforming handoff for exactly this invocation,
every citation anchors or the whole handoff is refused, and every answer's
exact response body is addressed as the call's diagnostic before analysis.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

import pytest
from canonical_fixtures import (
    CATALOG,
    CONTRACT,
    QUOTE,
    UNANCHORED,
    CanonicalCompletions,
    skill,
)
from conftest import recorded_statements
from conftest import reserve_at as reserve
from test_execution_freshness import (
    _counts,
    _Harness,
    _revoke_during_transport,
    harness,
)
from test_loop_charges import ESTIMATE, REPORT, REPORTED

from caos.blobs import BlobStore
from caos.evidence import read as evidence_read
from caos.graph.route import ResolvedRoute, RouteNode, resolve_route
from caos.graph.runtime import ProviderResult
from caos.methodology import executor, runner
from caos.methodology.bundle import Bundle
from caos.methodology.canonical import HandoffOutcome, execute_handoff
from caos.methodology.executor import Assignment, captured_blocks
from caos.methodology.handoff import read_record, validate_markdown
from caos.methodology.invocation import host_identity
from caos.methodology.runner import ModuleProvider
from caos.provider import Completion, CompletionProvider, encode_request
from caos.refusals import Refusal, RefusalCode
from caos.store import StoreConnection
from caos.store.run_inputs import load_run_input
from caos.store.runs import Accepted, accept_attempt, start_attempt
from caos.store.source_sets import load_source_set

__all__ = ["harness"]

LITE = ("LITE_CREDIT_22", "LITE_EARNINGS_UPDATE")


@pytest.fixture
def route(request: pytest.FixtureRequest) -> ResolvedRoute:
    return resolve_route(CATALOG, *getattr(request, "param", LITE))


def _node(harness: _Harness, module_id: str) -> RouteNode:
    return next(n for n in harness.route.nodes if n.module_id == module_id)


def _reserved(harness: _Harness, module_id: str) -> UUID:
    attempt = start_attempt(
        harness.conn, harness.run_id, _node(harness, module_id).route_node_id
    )
    reserve(harness.conn, attempt, ESTIMATE)
    return attempt


def _run(
    harness: _Harness, module_id: str, completions: CompletionProvider
) -> tuple[UUID, ProviderResult]:
    attempt = _reserved(harness, module_id)
    node = _node(harness, module_id)
    provider = ModuleProvider(
        harness.conn,
        harness.bundle,
        harness.blobs,
        completions,
        harness.route,
        harness.run_id,
    )
    return attempt, provider.execute(node.route_node_id, module_id, attempt_id=attempt)


def _refused(
    harness: _Harness, module_id: str, completions: CompletionProvider
) -> RefusalCode:
    with pytest.raises(Refusal) as refused:
        _run(harness, module_id, completions)
    assert refused.value.__context__ is None and refused.value.__cause__ is None
    return refused.value.code


def _body(body: str) -> str:
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def _diagnostic(harness: _Harness) -> str | None:
    row = harness.conn.execute("SELECT diagnostic_sha256 FROM call_outcomes").fetchone()
    harness.conn.rollback()
    assert row is not None
    return None if row[0] is None else str(row[0])


def _accept(harness: _Harness, attempt: UUID, result: ProviderResult) -> None:
    accepted = Accepted(
        result.artifact_sha256,
        result.charge,
        result.model,
        result.generation_id,
        diagnostic_sha256=result.diagnostic_sha256,
        record_sha256=result.record_sha256,
    )
    assert accept_attempt(harness.conn, attempt_id=attempt, accepted=accepted)


def _verified(
    harness: _Harness, module_id: str, attempt: UUID, result: ProviderResult
) -> bytes:
    identity = host_identity(
        harness.conn,
        harness.bundle,
        run_id=harness.run_id,
        route=harness.route,
        node=_node(harness, module_id),
        attempt_id=attempt,
    )
    harness.conn.rollback()
    markdown = harness.blobs.get(result.artifact_sha256)
    assert result.record_sha256 is not None
    record = read_record(
        harness.blobs,
        artifact_sha256=result.artifact_sha256,
        record_sha256=result.record_sha256,
        expected=identity,
    )
    gate = frozenset({"CP-L10", "CP-5"}) if module_id == "CP-0" else frozenset()
    projections = validate_markdown(
        CONTRACT,
        CATALOG,
        skill(module_id),
        markdown,
        identity=identity,
        gate_expects=gate,
    )
    assert record.projections == projections
    [citation] = record.citations
    assert (citation.matched_text, citation.page) == (QUOTE, 1)
    assert citation.document_sha256 == hashlib.sha256(REPORT).hexdigest()
    return markdown


def test_the_executor_produces_a_validated_handoff_and_its_record(
    harness: _Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    outcomes: list[HandoffOutcome] = []

    def kept(
        conn: StoreConnection,
        bundle: Bundle,
        blobs: BlobStore,
        *,
        assignment: Assignment,
        provider: CompletionProvider,
    ) -> HandoffOutcome:
        outcomes.append(
            execute_handoff(
                conn, bundle, blobs, assignment=assignment, provider=provider
            )
        )
        return outcomes[-1]

    monkeypatch.setattr(runner, "execute_handoff", kept)
    completions = CanonicalCompletions(harness.source_id)
    with recorded_statements(harness.conn) as statements:
        gate_attempt, gate = _run(harness, "CP-0", completions)
    # The delivered blocks are read once, in one statement, before the call:
    # the anchoring after it uses the very deliveries the prompt was built from,
    # and no block costs a round trip of its own.
    assert statements.count(evidence_read._RUN_BLOCKS_QUERY) == 1
    # And the captured pins are no longer a read of their own beside it.
    assert statements.count(executor._CAPTURED) == 0
    # The runner stores exactly the executor's two blobs.
    assert harness.blobs.get(gate.artifact_sha256) == outcomes[0].markdown
    assert gate.record_sha256 == hashlib.sha256(outcomes[0].record).hexdigest()
    assert (
        gate.diagnostic_sha256 == _body(completions.bodies[0]) == _diagnostic(harness)
    )
    assert gate.artifact_sha256 == hashlib.sha256(completions.answers[0]).hexdigest()
    assert (gate.charge, gate.generation_id) == (REPORTED, "gen-canonical-test")
    gate_markdown = _verified(harness, "CP-0", gate_attempt, gate)
    assert gate_markdown == completions.answers[0]
    _accept(harness, gate_attempt, gate)

    screen_attempt, screen = _run(harness, "CP-L10", completions)
    assert gate_markdown.decode() in completions.prompts[1]
    _verified(harness, "CP-L10", screen_attempt, screen)
    _accept(harness, screen_attempt, screen)
    assert _counts(harness) == (2, [REPORTED, REPORTED], 2, 2, 2)


def test_provider_claimed_identity_never_survives(harness: _Harness) -> None:
    tampered = CanonicalCompletions(
        harness.source_id, mutate=lambda f: {**f, "issuer_name": "Other plc"}
    )
    assert _refused(harness, "CP-0", tampered) is (
        RefusalCode.HANDOFF_IDENTITY_MISMATCH
    )
    assert _counts(harness) == (1, [REPORTED], 0, 1, 1)
    assert _diagnostic(harness) == _body(tampered.bodies[0])


def test_cp0_receives_the_verified_source_preparation_snapshot(
    harness: _Harness,
) -> None:
    completions = CanonicalCompletions(harness.source_id)
    _run(harness, "CP-0", completions)
    pin = load_run_input(harness.conn, harness.run_id)
    assert pin is not None
    source_set = load_source_set(harness.conn, pin.case_id, pin.source_version)
    assert source_set is not None
    [prompt] = completions.prompts
    assert "HOST SOURCE PREPARATION" in prompt
    for member in source_set.members:
        assert f"blob://sha256/{member.document_sha256}" in prompt
        assert member.extraction_sha256 in prompt


def test_cp0_refuses_before_the_provider_when_an_original_blob_is_missing(
    harness: _Harness,
) -> None:
    pin = load_run_input(harness.conn, harness.run_id)
    assert pin is not None
    source_set = load_source_set(harness.conn, pin.case_id, pin.source_version)
    assert source_set is not None
    harness.blobs.path_of(source_set.members[0].document_sha256).unlink()
    completions = CanonicalCompletions(harness.source_id)
    assert _refused(harness, "CP-0", completions) is RefusalCode.BLOB_NOT_FOUND
    assert completions.prompts == []


def test_cp0_maps_original_store_io_failure_before_the_provider(
    harness: _Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    pin = load_run_input(harness.conn, harness.run_id)
    assert pin is not None
    source_set = load_source_set(harness.conn, pin.case_id, pin.source_version)
    assert source_set is not None
    original_get = BlobStore.get

    def unavailable(self: BlobStore, digest: str) -> bytes:
        if digest == source_set.members[0].document_sha256:
            raise OSError
        return original_get(self, digest)

    monkeypatch.setattr(BlobStore, "get", unavailable)
    completions = CanonicalCompletions(harness.source_id)
    assert _refused(harness, "CP-0", completions) is RefusalCode.STORE_UNAVAILABLE
    assert completions.prompts == []


def test_cp0_refuses_a_billed_answer_when_an_original_moves_during_transport(
    harness: _Harness,
) -> None:
    pin = load_run_input(harness.conn, harness.run_id)
    assert pin is not None
    source_set = load_source_set(harness.conn, pin.case_id, pin.source_version)
    assert source_set is not None
    completions = CanonicalCompletions(
        harness.source_id,
        during=lambda: harness.blobs.path_of(
            source_set.members[0].document_sha256
        ).unlink(),
    )
    assert _refused(harness, "CP-0", completions) is RefusalCode.BLOB_NOT_FOUND
    assert len(completions.prompts) == 1
    assert _counts(harness) == (1, [REPORTED], 0, 1, 1)


@dataclass
class _ClaimsJson:
    """Answers in the claims-JSON shape the claims adapter accepted."""

    source_id: UUID
    model: str = "a-model/for-the-test"
    prompts: list[str] = field(default_factory=list)

    def request_bytes(self, prompt: str, *, json_object: bool = False) -> bytes:
        return encode_request(self.model, prompt, json_object=json_object)

    def complete(self, prompt: str, *, json_object: bool = False) -> Completion:
        self.prompts.append(prompt)
        citation = {"source_id": str(self.source_id), "page": 1, "matched_text": QUOTE}
        claim = {"statement": "Total debt was USD 1,240.0m.", "citations": [citation]}
        return Completion(json.dumps({"claims": [claim]}), REPORTED, "gen-claims")


def test_a_wrong_adapter_cannot_become_authority(harness: _Harness) -> None:
    """RED 6. A claims-JSON body is not a conforming handoff for any pin: the
    canonical executor is the only one that can run on a canonical pin (the
    claims executor itself is retired and deleted, f-2b), and it refuses this
    body as malformed rather than parsing it as claims."""
    claims = _ClaimsJson(harness.source_id)
    assert _refused(harness, "CP-0", claims) is RefusalCode.HANDOFF_MALFORMED
    # Not a canonical transport, but still exactly what was said.
    said = _ClaimsJson(harness.source_id).complete(claims.prompts[0], json_object=True)
    assert isinstance(said.content, str)
    assert _diagnostic(harness) == _body(said.content)
    assert _counts(harness) == (1, [REPORTED], 0, 1, 1)


def test_an_upstream_statement_is_not_citable_evidence(harness: _Harness) -> None:
    """Invariant 11 does not soften for the chain (REBUILD_PLAN Phase 11 exit,
    on the canonical adapter since f-1c): CP-L10 quoting a sentence that only
    CP-0's accepted handoff carries is refused, although that handoff reached
    its prompt verbatim."""
    attempt, gate = _run(harness, "CP-0", CanonicalCompletions(harness.source_id))
    _accept(harness, attempt, gate)
    upstream = harness.blobs.get(gate.artifact_sha256).decode("utf-8")
    assert UNANCHORED in upstream
    quoting = CanonicalCompletions(harness.source_id, quotes=(UNANCHORED,))
    assert _refused(harness, "CP-L10", quoting) is RefusalCode.CITATION_NOT_LOCATED
    [prompt] = quoting.prompts
    assert upstream in prompt


def test_one_unanchorable_quote_refuses_the_whole_handoff(harness: _Harness) -> None:
    both = CanonicalCompletions(harness.source_id, quotes=(QUOTE, UNANCHORED))
    assert _refused(harness, "CP-0", both) is RefusalCode.CITATION_NOT_LOCATED
    assert _counts(harness) == (1, [REPORTED], 0, 1, 1)


def test_a_blocked_handoff_is_billed_and_kept_as_a_diagnostic(
    harness: _Harness,
) -> None:
    blocked = CanonicalCompletions(harness.source_id, qa_status="Blocked")
    assert _refused(harness, "CP-0", blocked) is RefusalCode.HANDOFF_BLOCKED
    digest = _body(blocked.bodies[0])
    assert _diagnostic(harness) == digest
    # The whole closed transport, so the verdict can be re-derived (§42.3).
    assert harness.blobs.get(digest) == blocked.bodies[0].encode("utf-8")
    assert _counts(harness) == (1, [REPORTED], 0, 1, 1)


def test_a_late_authority_change_refuses_before_analysis(harness: _Harness) -> None:
    late = CanonicalCompletions(
        harness.source_id, during=lambda: _revoke_during_transport(harness)
    )
    assert _refused(harness, "CP-0", late) is RefusalCode.GATE_APPROVAL_MISMATCH
    assert len(late.prompts) == 1
    assert _counts(harness) == (1, [REPORTED], 0, 1, 1)


@pytest.mark.parametrize(
    ("knobs", "code"),
    [
        (
            {"mutate": lambda f: {**f, "run_id": "COS-other"}},
            "HANDOFF_IDENTITY_MISMATCH",
        ),
        ({"content": "not json"}, "HANDOFF_MALFORMED"),
        ({"quotes": (UNANCHORED,)}, "CITATION_NOT_LOCATED"),
        ({"readiness": {"CP-5": "NOT-A-STATUS"}}, "HANDOFF_INCOMPLETE"),
        ({"qa_status": "Blocked"}, "HANDOFF_BLOCKED"),
    ],
)
def test_billing_survives_every_analytical_refusal(
    harness: _Harness, knobs: dict[str, Any], code: str
) -> None:
    completions = CanonicalCompletions(harness.source_id, **knobs)
    assert _refused(harness, "CP-0", completions) is RefusalCode(code)
    assert _counts(harness) == (1, [REPORTED], 0, 1, 1)
    assert _diagnostic(harness) == _body(completions.bodies[0])


def test_a_quote_outside_the_captured_blocks_refuses_the_handoff(
    harness: _Harness,
) -> None:
    """Wiring for the page grain: the executor anchors on the blocks it
    delivered. Since §95 a real run narrows delivery to whole pinned members
    the gate's T8 row names (`tests/test_evidence_selection.py`), but never
    below a whole source, so an undelivered *page* of a delivered source is
    still reached only by deleting a block with the immutability trigger
    disabled, as here. The rule itself -- an undelivered page of a delivered
    source cannot be cited -- is proven at `verify_citations` in
    `tests/test_awkward_evidence.py`."""
    conn, source = harness.conn, harness.source_id
    whole = captured_blocks(conn, harness.run_id)
    assert whole[source] == frozenset({"b000000", "b000001"})
    row = conn.execute("SELECT current_database()").fetchone()
    assert row is not None and str(row[0]).startswith("caos_test_")
    conn.rollback()
    with conn.transaction():  # test-only narrowing; no production knob exists
        conn.execute("ALTER TABLE source_blocks DISABLE TRIGGER evidence_immutable")
        conn.execute(
            "DELETE FROM source_blocks WHERE source_id = %s AND block_id = 'b000001'",
            (source,),
        )
        conn.execute("ALTER TABLE source_blocks ENABLE TRIGGER evidence_immutable")
    narrowed = captured_blocks(conn, harness.run_id)
    assert narrowed == {**whole, source: frozenset({"b000000"})}
    conn.rollback()

    quoting = CanonicalCompletions(source)
    assert _refused(harness, "CP-0", quoting) is RefusalCode.CITATION_NOT_DELIVERED
    [prompt] = quoting.prompts
    assert QUOTE not in prompt

"""A canonical route through the real runtime (Task 3.1 slice c-5b; §41, §42).

`run_route` accepts a canonical result with its host record, replays the
executor's diagnostic exactly, reads CP-0 readiness and QA from records
verified against their Markdown, and ends the run BLOCKED on a validated
Blocked handoff. The post-call freshness guarantees are proven here too
(their claims-adapter variants were removed with the claims route in f-1a).
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
from canonical_fixtures import QUOTE, UNANCHORED, CanonicalCompletions
from conftest import priced, recorded_statements
from test_canonical_execution import (
    _accept,
    _node,
    _reserved,
    _run,
    harness,
    route,
)
from test_execution_freshness import (
    _counts,
    _events,
    _Harness,
    _RefusedCompletion,
    _revoke_during_transport,
    _still_running,
)
from test_loop_charges import ESTIMATE, MODEL, REPORTED

from caos.blobs import BlobStore
from caos.evidence import read as evidence_read
from caos.graph import runtime
from caos.graph.runtime import Execution, Provider, ProviderResult, run_route
from caos.methodology import canonical, executor, invocation
from caos.methodology.canonical import (
    Replayed,
    Verdict,
    accepted_projections,
    blocked_verdict,
    replay_billed,
    unexplained_charge,
)
from caos.methodology.handoff import (
    Projections,
    _decoded_record,
    read_record,
    record_bytes,
)
from caos.methodology.invocation import host_identity
from caos.methodology.runner import ModuleProvider
from caos.methodology.verification import AcceptedRow
from caos.pricing import ModelPrice
from caos.provider import Completion, CompletionProvider, encode_request
from caos.refusals import Refusal, RefusalCode
from caos.store import StoreConnection, connect, outcomes
from caos.store.events import lock_run
from caos.store.outcomes import CallOutcome, accepted_rows
from caos.store.run_inputs import load_run_input
from caos.store.runs import block_run
from caos.store.source_sets import load_source_set
from caos.store.work import Lease

__all__ = ["harness", "route"]


@dataclass
class _Answers:
    """A deterministic canonical answer, with a hook inside the call."""

    delegate: CanonicalCompletions
    during: Callable[[], None] = lambda: None
    facts: dict[str, Any] = field(default_factory=dict)
    model: str = MODEL
    calls: int = 0

    def request_bytes(self, prompt: str, *, json_object: bool = False) -> bytes:
        return encode_request(self.model, prompt, json_object=json_object)

    def complete(self, prompt: str, *, json_object: bool = False) -> Completion:
        self.calls += 1
        self.during()
        return replace(
            self.delegate.complete(prompt, json_object=json_object), **self.facts
        )


def _answers(
    harness: _Harness,
    during: Callable[[], None] = lambda: None,
    facts: dict[str, Any] | None = None,
) -> _Answers:
    return _Answers(CanonicalCompletions(harness.source_id), during, facts or {})


def _module_provider(
    harness: _Harness, completions: CompletionProvider
) -> ModuleProvider:
    return ModuleProvider(
        harness.conn,
        harness.bundle,
        harness.blobs,
        completions,
        harness.route,
        harness.run_id,
    )


def _run_route(harness: _Harness, provider: Provider) -> RefusalCode | None:
    try:
        run_route(
            harness.conn,
            harness.blobs,
            run_id=harness.run_id,
            route=harness.route,
            execution=Execution(provider, priced(ESTIMATE), harness.bundle),
        )
    except Refusal as refused:
        assert refused.__cause__ is None and refused.__context__ is None
        return refused.code
    return None


def _status(harness: _Harness) -> str:
    with connect(harness.url) as observer:
        row = observer.execute(
            "SELECT status FROM runs WHERE run_id=%s", (harness.run_id,)
        ).fetchone()
    assert row is not None
    return str(row[0])


def _projections(harness: _Harness) -> dict[str, Projections]:
    """Every accepted record, read back under the identity the store rebuilds."""
    rows = harness.conn.execute(
        "SELECT t.route_node_id, a.attempt_id, a.artifact_sha256, a.record_sha256,"
        " o.diagnostic_sha256 FROM artifacts a JOIN run_attempts t USING (attempt_id)"
        " JOIN call_outcomes o USING (attempt_id)"
    ).fetchall()
    read = {}
    for node_id, attempt, artifact, record, diagnostic in rows:
        node = next(n for n in harness.route.nodes if n.route_node_id == node_id)
        identity = host_identity(
            harness.conn,
            harness.bundle,
            run_id=harness.run_id,
            route=harness.route,
            node=node,
            attempt_id=attempt,
        )
        # The diagnostic is the whole response body the Markdown came out of.
        said = json.loads(harness.blobs.get(diagnostic))
        assert said["canonical_markdown"].encode() == harness.blobs.get(artifact)
        found = read_record(
            harness.blobs,
            artifact_sha256=artifact,
            record_sha256=record,
            expected=identity,
        )
        assert [c.matched_text for c in found.citations] == [QUOTE]
        read[node.module_id] = found.projections
    harness.conn.rollback()
    return read


@pytest.mark.parametrize("qa", ["Passed", "Restricted"])
def test_a_lite_route_completes_through_the_real_runtime(
    harness: _Harness, qa: str
) -> None:
    answers = CanonicalCompletions(harness.source_id, qa_by_module={"CP-L10": qa})
    assert _run_route(harness, _module_provider(harness, answers)) is None
    assert _counts(harness) == (3, [REPORTED] * 3, 3, 3, 3)
    assert [
        _events(harness, name)
        for name in ("CALL_OUTCOME_RECORDED", "ATTEMPT_ACCEPTED", "RUN_COMPLETE")
    ] == [3, 3, 1]
    read = _projections(harness)
    assert sorted(read) == ["CP-0", "CP-5", "CP-L10"]
    assert read["CP-0"].readiness == (("CP-5", "READY"), ("CP-L10", "READY"))
    screen = read["CP-L10"]
    assert (screen.qa_status, bool(screen.limitation_flags)) == (
        qa,
        qa == "Restricted",
    )


def _run_one_lite_node(harness: _Harness) -> None:
    """Run the LITE route with CP-L10 gate-blocked, so exactly one node is
    called, billed and accepted before the empty frontier ends the run.

    Both callers rest on the three assertions below: they are this helper's
    contract, not either test's private working, so weaken one and the other
    test stops saying what its name claims.
    """
    answers = CanonicalCompletions(harness.source_id, readiness={"CP-L10": "BLOCKED"})
    assert _run_route(harness, _module_provider(harness, answers)) is None
    called = [prompt.split(maxsplit=6)[5] for prompt in answers.prompts]
    assert called == ["CP-0"]
    assert _counts(harness) == (1, [REPORTED], 1, 1, 1)


def test_cp5_is_not_invoked_without_an_accepted_named_lite_object(
    harness: _Harness,
) -> None:
    """§46.1: CP-L10's edge into CP-5 is soft, but CP-5's verified LITE block
    retains `NAMED_LITE_OBJECT_ACCEPTED`. With CP-L10 gate-blocked no upstream
    owns an accepted object, so the run ends BLOCKED and CP-5 costs nothing."""
    _run_one_lite_node(harness)
    with connect(harness.url) as observer:
        cp5 = observer.execute(
            "SELECT count(*), count(r.attempt_id) FROM run_attempts t"
            " LEFT JOIN budget_reservations r USING (attempt_id)"
            " WHERE t.route_node_id=%s",
            (_node(harness, "CP-5").route_node_id,),
        ).fetchone()
    assert cp5 == (0, 0)
    assert (_status(harness), _events(harness, "RUN_BLOCKED")) == ("BLOCKED", 1)


def test_an_accepted_node_records_its_outcome_exactly_twice(
    harness: _Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    """W1: the executor records the bill once, with the call, and that row is
    what a crash before acceptance is replayed from; acceptance re-asserts
    exactly it in its own unit, where a legacy row is what routes the replay.
    A third record costs a COMMIT and two row locks and decides nothing."""
    calls: list[UUID] = []
    original = outcomes._record

    def counting(conn: StoreConnection, attempt: UUID, outcome: CallOutcome) -> bool:
        calls.append(attempt)
        return original(conn, attempt, outcome)

    monkeypatch.setattr(outcomes, "_record", counting)
    _run_one_lite_node(harness)
    assert (len(calls), len(set(calls))) == (2, 1), calls


def test_a_validated_blocked_handoff_ends_the_run_blocked_without_retry(
    harness: _Harness,
) -> None:
    answers = CanonicalCompletions(harness.source_id, qa_by_module={"CP-5": "Blocked"})
    assert _run_route(harness, _module_provider(harness, answers)) is None
    assert len(answers.prompts) == 3
    assert _counts(harness) == (3, [REPORTED] * 3, 2, 3, 3)
    assert (_status(harness), _events(harness, "RUN_BLOCKED")) == ("BLOCKED", 1)
    assert _events(harness, "RUN_COMPLETE") == 0
    # The Blocked answer is the attempt's diagnostic, never an artifact.
    blocked = hashlib.sha256(answers.bodies[2].encode()).hexdigest()
    with connect(harness.url) as observer:
        row = observer.execute(
            "SELECT count(*) FROM call_outcomes o JOIN run_attempts t"
            " USING (attempt_id) WHERE o.diagnostic_sha256=%s"
            " AND t.route_node_id=%s AND NOT EXISTS"
            " (SELECT 1 FROM artifacts a WHERE a.attempt_id=o.attempt_id)",
            (blocked, _node(harness, "CP-5").route_node_id),
        ).fetchone()
    assert row == (1,)
    # The transition recorded which answer ended the run, in the transaction
    # that ended it. Nothing can re-derive this later: `replay_billed` goes
    # through `check_attempt`, which refuses once the run is no longer RUNNING,
    # so the row is the only durable form of the cause (§68).
    assert _blocking_verdict(harness) == _attempt_of(harness, "CP-5")


def test_a_blocking_verdict_names_only_an_attempt_of_the_run_it_ends(
    harness: _Harness,
) -> None:
    """`block_run(verdict=)` is the store recording the runtime's decision, and
    it records only an attempt this run made: another run's, or one that does
    not exist, refuses `ATTEMPT_NOT_FOUND` and ends nothing -- the status, the
    event and the verdict are one transaction. Without a verdict the run still
    ends BLOCKED (§39's empty frontier) and names no node."""
    with pytest.raises(Refusal, match=r"^ATTEMPT_NOT_FOUND$"):
        block_run(harness.conn, harness.run_id, verdict=uuid4())
    _still_running(harness)
    assert _events(harness, "RUN_BLOCKED") == 0
    assert _blocking_verdict(harness) is None

    assert block_run(harness.conn, harness.run_id) is True
    assert (_status(harness), _events(harness, "RUN_BLOCKED")) == ("BLOCKED", 1)
    assert _blocking_verdict(harness) is None


def _blocking_verdict(harness: _Harness) -> UUID | None:
    """The attempt the store says ended this run with a Blocked verdict."""
    with connect(harness.url) as observer:
        row = observer.execute(
            "SELECT attempt_id FROM run_blocking_verdicts WHERE run_id=%s",
            (harness.run_id,),
        ).fetchone()
    return None if row is None else UUID(str(row[0]))


def _attempt_of(harness: _Harness, module_id: str) -> UUID:
    """The one attempt this run made at `module_id`."""
    with connect(harness.url) as observer:
        rows = observer.execute(
            "SELECT attempt_id FROM run_attempts WHERE run_id=%s AND route_node_id=%s",
            (harness.run_id, _node(harness, module_id).route_node_id),
        ).fetchall()
    assert len(rows) == 1
    return UUID(str(rows[0][0]))


def test_an_unanchorable_blocked_handoff_is_an_ordinary_refusal(
    harness: _Harness,
) -> None:
    """Quotes are anchored before Blocked is honoured (c-5b, P3-2)."""
    answers = CanonicalCompletions(
        harness.source_id, qa_status="Blocked", quotes=(UNANCHORED,)
    )
    code = _run_route(harness, _module_provider(harness, answers))
    assert code is RefusalCode.CITATION_NOT_LOCATED
    assert _counts(harness) == (1, [REPORTED], 0, 1, 1)
    _still_running(harness)
    assert _events(harness, "RUN_BLOCKED") == 0


@dataclass
class _UnbilledBlocked:
    """A Provider claiming Blocked without any call behind it."""

    model: str = MODEL

    def check_context(self, route_node_id: str, module_id: str) -> int:
        # No prompt is built here, so there are no request bytes to price.
        return 0

    def execute(
        self, route_node_id: str, module_id: str, *, attempt_id: UUID
    ) -> ProviderResult:
        raise Refusal(RefusalCode.HANDOFF_BLOCKED)


def test_an_unbilled_blocked_claim_never_ends_the_run(harness: _Harness) -> None:
    assert _run_route(harness, _UnbilledBlocked()) is RefusalCode.HANDOFF_BLOCKED
    assert _counts(harness) == (0, [], 0, 1, 1)
    _still_running(harness)


def test_a_crash_before_the_block_commits_resumes_blocked_without_a_second_call(
    harness: _Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The verdict is re-derived from the stored bill and diagnostic (P1)."""
    crashes = [RefusalCode.STORE_UNAVAILABLE]

    def crashing(
        conn: StoreConnection,
        run_id: UUID,
        *,
        lease: Lease | None = None,
        verdict: UUID | None = None,
    ) -> bool:
        if crashes:
            raise Refusal(crashes.pop())
        return block_run(conn, run_id, lease=lease, verdict=verdict)

    monkeypatch.setattr(runtime, "block_run", crashing)
    answers = CanonicalCompletions(harness.source_id, qa_by_module={"CP-5": "Blocked"})
    provider = _module_provider(harness, answers)
    assert _run_route(harness, provider) is RefusalCode.STORE_UNAVAILABLE
    _still_running(harness)
    screen = _node(harness, "CP-5").route_node_id
    with recorded_statements(harness.conn) as statements:
        verdict = blocked_verdict(
            harness.conn,
            harness.blobs,
            harness.bundle,
            run_id=harness.run_id,
            route=harness.route,
            route_node_ids=[screen],
        )
    assert verdict == _attempt_of(harness, "CP-5")
    # The delivered blocks are read once, in one statement, by the reader the
    # verdict re-anchors on.
    assert statements.count(evidence_read._RUN_BLOCKS_QUERY) == 1
    # And the captured pins are no longer a read of their own beside it.
    assert statements.count(executor._CAPTURED) == 0
    harness.conn.rollback()
    replayed = replay_billed(
        harness.conn,
        harness.blobs,
        harness.bundle,
        run_id=harness.run_id,
        route=harness.route,
        route_node_ids=[screen],
    )
    harness.conn.rollback()
    assert isinstance(replayed, Replayed)
    assert (replayed.verdict, replayed.outcome, replayed.code) == (
        Verdict.BLOCKED,
        None,
        None,
    )
    # Resume: no attempt, reservation or call; the run ends BLOCKED once.
    assert _run_route(harness, provider) is None
    assert len(answers.prompts) == 3
    assert _counts(harness) == (3, [REPORTED] * 3, 2, 3, 3)
    assert (_status(harness), _events(harness, "RUN_BLOCKED")) == ("BLOCKED", 1)
    # The replayed path records the same reason the live path would have.
    assert _blocking_verdict(harness) == _attempt_of(harness, "CP-5")


def test_an_unreadable_stored_verdict_is_a_fault_not_a_second_call(
    harness: _Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A diagnostic blob that will not read never counts as "not blocked"."""
    crashes = [RefusalCode.STORE_UNAVAILABLE]

    def crashing(
        conn: StoreConnection,
        run_id: UUID,
        *,
        lease: Lease | None = None,
        verdict: UUID | None = None,
    ) -> bool:
        if crashes:
            raise Refusal(crashes.pop())
        return block_run(conn, run_id, lease=lease, verdict=verdict)

    monkeypatch.setattr(runtime, "block_run", crashing)
    answers = CanonicalCompletions(harness.source_id, qa_by_module={"CP-5": "Blocked"})
    provider = _module_provider(harness, answers)
    assert _run_route(harness, provider) is RefusalCode.STORE_UNAVAILABLE
    blocked = hashlib.sha256(answers.bodies[2].encode()).hexdigest()
    harness.blobs.path_of(blocked).unlink()
    # A stored body that is gone is its own code (DL-5): the worker parks the
    # run with it, where a store fault would release it to the head of the
    # queue and block every other run. Still never a second call.
    assert _run_route(harness, provider) is RefusalCode.BLOB_NOT_FOUND
    assert len(answers.prompts) == 3
    _still_running(harness)


def test_a_lost_original_after_billing_replays_after_it_is_restored(
    harness: _Harness,
) -> None:
    pin = load_run_input(harness.conn, harness.run_id)
    assert pin is not None
    source_set = load_source_set(harness.conn, pin.case_id, pin.source_version)
    assert source_set is not None
    original = harness.blobs.get(source_set.members[0].document_sha256)
    harness.conn.rollback()
    lost = False

    def remove_once() -> None:
        nonlocal lost
        if not lost:
            harness.blobs.path_of(source_set.members[0].document_sha256).unlink()
            lost = True

    answers = _answers(harness, during=remove_once)
    provider = _module_provider(harness, answers)
    assert _run_route(harness, provider) is RefusalCode.BLOB_NOT_FOUND
    assert _counts(harness) == (1, [REPORTED], 0, 1, 1)
    row = harness.conn.execute("SELECT count(*) FROM attempt_refusals").fetchone()
    assert row == (0,)
    harness.conn.rollback()
    _still_running(harness)

    assert harness.blobs.put(original) == source_set.members[0].document_sha256
    assert _run_route(harness, provider) is None
    assert len(answers.delegate.prompts) == 3
    assert _counts(harness) == (3, [REPORTED] * 3, 3, 3, 3)


def test_a_body_that_cannot_be_stored_refuses_after_its_bill(
    harness: _Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    answers = CanonicalCompletions(harness.source_id)
    provider = _module_provider(harness, answers)
    real_put = BlobStore.put

    def failing(self: BlobStore, data: bytes) -> str:
        if answers.bodies and data == answers.bodies[-1].encode():
            raise OSError
        return real_put(self, data)

    monkeypatch.setattr(BlobStore, "put", failing)
    assert _run_route(harness, provider) is RefusalCode.STORE_UNAVAILABLE
    assert _counts(harness)[:2] == (1, [REPORTED])
    _still_running(harness)


def test_a_billed_node_with_no_stored_body_is_not_billed_again(
    harness: _Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The charge committed, the body did not: nobody may pay twice by default.

    `replay_billed` needs a diagnostic to settle the attempt from, and this
    outcome has none, so before this refusal the next pass simply started a
    fresh attempt, reserved again and called the provider again. Paying again
    may be right, but it is an operator's decision -- so the run parks with a
    code instead of spending.
    """
    answers = CanonicalCompletions(harness.source_id)
    provider = _module_provider(harness, answers)
    real_put = BlobStore.put

    def failing(self: BlobStore, data: bytes) -> str:
        if answers.bodies and data == answers.bodies[-1].encode():
            raise OSError
        return real_put(self, data)

    monkeypatch.setattr(BlobStore, "put", failing)
    assert _run_route(harness, provider) is RefusalCode.STORE_UNAVAILABLE
    called = len(answers.prompts)
    assert called == 1
    harness.conn.rollback()

    monkeypatch.setattr(BlobStore, "put", real_put)
    node = unexplained_charge(
        harness.conn,
        run_id=harness.run_id,
        route_node_ids=[node.route_node_id for node in harness.route.nodes],
    )
    assert node is not None, "the charged node with no body is the one found"
    harness.conn.rollback()
    assert _run_route(harness, provider) is RefusalCode.CALL_OUTCOME_UNEXPLAINED
    assert len(answers.prompts) == called, "no second call for the same node"
    assert _counts(harness)[:2] == (1, [REPORTED]), "and no second charge"
    _still_running(harness)


@dataclass
class _ClaimsBlocked:
    """Makes a real, billed call, then says Blocked whatever the answer was."""

    inner: ModuleProvider
    module: str = "CP-0"
    model: str = MODEL

    def check_context(self, route_node_id: str, module_id: str) -> int:
        return self.inner.check_context(route_node_id, module_id)

    def execute(
        self, route_node_id: str, module_id: str, *, attempt_id: UUID
    ) -> ProviderResult:
        try:
            result = self.inner.execute(route_node_id, module_id, attempt_id=attempt_id)
        except Refusal:
            result = None
        if module_id == self.module:
            raise Refusal(RefusalCode.HANDOFF_BLOCKED)
        assert result is not None
        return result


@pytest.mark.parametrize(
    "knobs",
    [{}, {"qa_status": "Blocked", "quotes": (UNANCHORED,)}],
    ids=["passed", "unanchorable-blocked"],
)
def test_a_blocked_claim_without_a_validated_diagnostic_never_ends_the_run(
    harness: _Harness, knobs: dict[str, Any]
) -> None:
    answers = CanonicalCompletions(harness.source_id, **knobs)
    lying = _ClaimsBlocked(_module_provider(harness, answers))
    assert _run_route(harness, lying) is RefusalCode.HANDOFF_BLOCKED
    assert _counts(harness) == (1, [REPORTED], 0, 1, 1)
    assert _events(harness, "RUN_BLOCKED") == 0
    _still_running(harness)


def test_readers_verify_the_record_against_its_markdown(harness: _Harness) -> None:
    from caos.graph.runtime import accepted_artifacts

    answers = CanonicalCompletions(harness.source_id)
    assert _run_route(harness, _module_provider(harness, answers)) is None
    gate = _node(harness, "CP-0").route_node_id
    args = (harness.conn, harness.blobs, harness.route, harness.run_id)
    body = accepted_artifacts(*args, bundle=harness.bundle)[gate]
    harness.conn.rollback()
    assert body.readiness == (("CP-5", "READY"), ("CP-L10", "READY"))
    with pytest.raises(Refusal) as unbundled:
        accepted_artifacts(*args)
    harness.conn.rollback()
    assert unbundled.value.code is RefusalCode.ORCHESTRATION_ARTIFACT_UNREADABLE
    rows = {row[0]: row for row in accepted_rows(harness.conn, harness.run_id)}
    harness.conn.rollback()
    assert sorted(rows) == sorted(n.route_node_id for n in harness.route.nodes)
    _node_id, attempt, artifact, record = rows[gate]
    assert record is not None
    # A record in canonical form, bound to the right Markdown and identity, whose
    # projections the Markdown does not say.
    decoded = _decoded_record(harness.blobs.get(record))
    lying = replace(
        decoded,
        projections=replace(decoded.projections, readiness=(("CP-5", "READY"),)),
    )
    with pytest.raises(Refusal) as mismatch:
        accepted_projections(
            harness.conn,
            harness.blobs,
            harness.bundle,
            harness.route,
            AcceptedRow(
                run_id=harness.run_id,
                route_node_id=gate,
                attempt_id=attempt,
                artifact_sha256=artifact,
                record_sha256=harness.blobs.put(record_bytes(lying)),
            ),
        )
    harness.conn.rollback()
    assert mismatch.value.code is RefusalCode.ARTIFACT_RECORD_MISMATCH


# P2-2: the post-call guarantees, through ModuleProvider.


def _accepted_first(harness: _Harness) -> tuple[str, str]:
    """Accept the route's first node for real; return the second node's ids."""
    first, second = harness.route.nodes[:2]
    attempt, result = _run(harness, first.module_id, _answers(harness))
    _accept(harness, attempt, result)
    return second.route_node_id, second.module_id


def _execute(
    harness: _Harness, module_id: str, completions: CompletionProvider
) -> tuple[RefusalCode, UUID]:
    attempt = _reserved(harness, module_id)
    node = _node(harness, module_id)
    with pytest.raises(Refusal) as refused:
        _module_provider(harness, completions).execute(
            node.route_node_id, module_id, attempt_id=attempt
        )
    assert refused.value.__cause__ is None and refused.value.__context__ is None
    return refused.value.code, attempt


def test_upstream_rewritten_during_transport_is_refused_keeping_the_bill(
    harness: _Harness,
) -> None:
    _node_id, module_id = _accepted_first(harness)
    first = harness.route.nodes[0].route_node_id

    def rewrite() -> None:
        with connect(harness.url) as other:
            lock_run(other, harness.run_id)
            other.execute(
                "UPDATE artifacts SET artifact_sha256=%s WHERE route_node_id=%s",
                (harness.blobs.put(b"other accepted bytes"), first),
            )
            other.commit()

    answers = _answers(harness, during=rewrite)
    code, _attempt = _execute(harness, module_id, answers)
    assert (code, answers.calls) == (RefusalCode.ROUTE_IDENTITY_INVALID, 1)
    assert _counts(harness) == (2, [REPORTED] * 2, 1, 2, 2)


def test_host_identity_changed_during_transport_is_refused_keeping_the_bill(
    harness: _Harness,
) -> None:
    """Only the host identity moves: the attempt's stored ordinal."""

    def renumber() -> None:
        with connect(harness.url) as other:
            other.execute("UPDATE run_attempts SET ordinal = ordinal + 1")
            other.commit()

    answers = _answers(harness, during=renumber)
    code, _attempt = _execute(harness, "CP-0", answers)
    assert (code, answers.calls) == (RefusalCode.ROUTE_IDENTITY_INVALID, 1)
    assert _counts(harness) == (1, [REPORTED], 0, 1, 1)


@pytest.mark.parametrize(
    ("facts", "billed"),
    [({"charge": None}, []), ({"generation_id": "not a handle!"}, [REPORTED])],
)
def test_an_unknown_charge_or_generation_is_refused_keeping_the_bill(
    harness: _Harness, facts: dict[str, Any], billed: list[Any]
) -> None:
    answers = _answers(harness, facts=facts)
    module_id = harness.route.nodes[0].module_id
    code, _attempt = _execute(harness, module_id, answers)
    assert code is RefusalCode.PROVIDER_RESPONSE_INVALID
    assert _counts(harness) == (1, billed, 0, 1, 1)
    _still_running(harness)


def test_a_known_provider_refusal_keeps_precedence_over_stale_authority(
    harness: _Harness,
) -> None:
    completion = _RefusedCompletion(lambda: _revoke_during_transport(harness))
    module_id = harness.route.nodes[0].module_id
    code, _attempt = _execute(harness, module_id, completion)
    assert (code, completion.calls) == (RefusalCode.PROVIDER_REFUSED, 1)
    assert _counts(harness) == (1, [REPORTED], 0, 1, 1)
    _still_running(harness)


@pytest.mark.parametrize("failure", ["sql", "interrupt"])
@pytest.mark.parametrize("stage", ["evidence", "upstream"])
def test_a_failure_while_deriving_context_makes_no_call(
    harness: _Harness, monkeypatch: pytest.MonkeyPatch, stage: str, failure: str
) -> None:
    module_id = harness.route.nodes[0].module_id
    if stage == "upstream":
        _node_id, module_id = _accepted_first(harness)
    owner = canonical
    name = {"evidence": "_delivered", "upstream": "upstream_markdown"}[stage]
    real = getattr(owner, name)

    def failing(*args: object, **kwargs: object) -> object:
        real(*args, **kwargs)
        if failure == "sql":
            harness.conn.execute("SELECT (%s)::int", (QUOTE,))
        raise KeyboardInterrupt

    monkeypatch.setattr(owner, name, failing)
    answers = _answers(harness)
    attempt = _reserved(harness, module_id)
    node = _node(harness, module_id)
    with pytest.raises((Refusal, KeyboardInterrupt)) as raised:
        _module_provider(harness, answers).execute(
            node.route_node_id, module_id, attempt_id=attempt
        )
    if failure == "sql":
        assert isinstance(raised.value, Refusal)
        assert raised.value.code is RefusalCode.STORE_UNAVAILABLE
    else:
        assert type(raised.value) is KeyboardInterrupt
    assert answers.calls == 0
    with connect(harness.url) as observer:
        row = observer.execute(
            "SELECT count(*) FROM call_outcomes WHERE attempt_id=%s", (attempt,)
        ).fetchone()
    assert row == (0,)
    _still_running(harness)


def test_a_changed_root_reference_refuses_before_the_call(harness: _Harness) -> None:
    """§45.1 through the runtime: a root file SKILL.md names, changed on disk
    under an unchanged manifest, refuses before any attempt, reservation or call."""
    canon = harness.bundle.root / "CANON_SHARED.md"
    canon.write_bytes(canon.read_bytes().replace(b"CP", b"CQ", 1))
    answers = _answers(harness)
    assert _run_route(harness, _module_provider(harness, answers)) is (
        RefusalCode.AUTHORITY_BYTES_MISMATCH
    )
    assert answers.calls == 0
    assert _counts(harness) == (0, [], 0, 0, 0)
    _still_running(harness)


def test_an_over_ceiling_context_refuses_without_truncation_or_call(
    harness: _Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§45.3 through the runtime: the ceiling is met before `start_attempt`, so
    an over-ceiling context leaves no attempt, reservation, call or charge.
    (Exactness at the ceiling, and no truncation, is proven on the prompt in
    `test_handoff_invocation.py`.) The ceiling here admits the prompt's own
    JSON encoding exactly, so only the request around it is over."""
    sized = _Sized(_answers(harness))
    provider = _module_provider(harness, sized)
    first = harness.route.nodes[0]
    provider.check_context(first.route_node_id, first.module_id)
    harness.conn.rollback()
    monkeypatch.setattr(invocation, "MAX_REQUEST_BYTES", len(json.dumps(sized.seen[0])))
    assert _run_route(harness, provider) is RefusalCode.CONTEXT_OVER_CEILING
    assert sized.inner.calls == 0
    assert _counts(harness) == (0, [], 0, 0, 0)
    _still_running(harness)


def test_an_over_bound_upstream_section_refuses_before_its_attempt(
    harness: _Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The per-section bound through the runtime: a node whose direct upstream
    handoff is past `MAX_UPSTREAM_HANDOFF_BYTES` refuses before `start_attempt`,
    so the node that could not be prompted leaves no attempt, reservation, call
    or charge -- and the upstream that ran before it keeps everything it paid
    for. The bound is moved rather than the handoff, because an accepted
    handoff's bytes are immutable."""
    answers = _answers(harness)
    provider = _module_provider(harness, answers)
    monkeypatch.setattr(invocation, "MAX_UPSTREAM_HANDOFF_BYTES", 1)
    assert _run_route(harness, provider) is RefusalCode.UPSTREAM_SECTION_OVER_CEILING
    assert answers.calls == 1
    assert _counts(harness) == (1, [REPORTED], 1, 1, 1)
    _still_running(harness)


@dataclass
class _Sized:
    """Records each prompt whose request is bounded; `after_check` runs once,
    after the first bound (the pre-attempt check) has passed."""

    inner: _Answers
    after_check: Callable[[], None] = lambda: None
    seen: list[str] = field(default_factory=list)

    @property
    def model(self) -> str:
        return self.inner.model

    def request_bytes(self, prompt: str, *, json_object: bool = False) -> bytes:
        self.seen.append(prompt)
        return self.inner.request_bytes(prompt, json_object=json_object)

    def complete(self, prompt: str, *, json_object: bool = False) -> Completion:
        return self.inner.complete(prompt, json_object=json_object)


@dataclass
class _ChangesAfterCheck:
    """Passes the pre-attempt check, then changes what the attempt reads."""

    inner: ModuleProvider
    change: Callable[[], None]
    model: str = MODEL

    def check_context(self, route_node_id: str, module_id: str) -> int:
        measured = self.inner.check_context(route_node_id, module_id)
        self.change()
        return measured

    def execute(
        self, route_node_id: str, module_id: str, *, attempt_id: UUID
    ) -> ProviderResult:
        return self.inner.execute(route_node_id, module_id, attempt_id=attempt_id)


@pytest.mark.parametrize("moved", ["ceiling", "root-file"])
def test_the_executor_rechecks_the_context_after_reservation(
    harness: _Harness, monkeypatch: pytest.MonkeyPatch, moved: str
) -> None:
    """What passed `check_context` can move before the attempt's own build:
    the executor's second bound refuses, after the attempt and its reservation
    exist and before any provider call (the Phase 4 ledger residual)."""
    canon = harness.bundle.root / "CANON_SHARED.md"

    def change() -> None:
        if moved == "ceiling":
            monkeypatch.setattr(invocation, "MAX_REQUEST_BYTES", 4096)
        else:
            canon.write_bytes(canon.read_bytes().replace(b"CP", b"CQ", 1))

    answers = _answers(harness)
    provider = _ChangesAfterCheck(_module_provider(harness, answers), change)
    expected = {
        "ceiling": RefusalCode.CONTEXT_OVER_CEILING,
        "root-file": RefusalCode.AUTHORITY_BYTES_MISMATCH,
    }[moved]
    assert _run_route(harness, provider) is expected
    assert answers.calls == 0
    assert _counts(harness) == (0, [], 0, 1, 1)
    _still_running(harness)


def test_a_reservation_never_falls_below_the_call_it_pays_for(
    harness: _Harness,
) -> None:
    """Invariant 8 under Task 8.2's tighter bound, over a whole canonical run.

    The reservation is no longer the byte ceiling, so the property has to be
    asserted rather than assumed: priced on the request the provider was sent
    and the completion cap, the only way past it is a provider billing more
    than the price it was reserved under.
    """
    answers = CanonicalCompletions(harness.source_id)
    assert _run_route(harness, _module_provider(harness, answers)) is None

    rows = harness.conn.execute(
        "SELECT r.amount, l.amount, r.price_model FROM budget_reservations AS r"
        " JOIN budget_ledger AS l USING (attempt_id, run_id)"
    ).fetchall()
    assert len(rows) == 3, "every attempt of the run reserved and was charged"
    for reserved, charged, model in rows:
        assert charged <= reserved, (reserved, charged)
        assert model == MODEL, "under the price of the model that answered"
    harness.conn.rollback()


# A real frontier model's rates, where the request size actually moves the
# price: $3/M input, $15/M output.
# Input is priced, so a request measured at a tenth reserves too little; low
# enough that one worst-case call at the 4 MiB ceiling (D29) still fits the
# harness's default run ceiling and the run is admitted.
_PRICED_INPUT = ModelPrice(
    MODEL, Decimal("0.0000009"), Decimal("0.000015"), date(2026, 9, 17)
)


@dataclass
class _UnderMeasures:
    """A provider whose pre-check under-reports the request it will send."""

    inner: ModuleProvider

    @property
    def model(self) -> str:
        return self.inner.model

    def check_context(self, route_node_id: str, module_id: str) -> int:
        return self.inner.check_context(route_node_id, module_id) // 10

    def execute(
        self, route_node_id: str, module_id: str, *, attempt_id: UUID
    ) -> ProviderResult:
        return self.inner.execute(route_node_id, module_id, attempt_id=attempt_id)


def test_a_request_costing_more_than_was_reserved_refuses_before_the_call(
    harness: _Harness,
) -> None:
    """The window Task 8.2 opens, closed inside the unit that spends.

    The loop prices the prompt the pre-check built; the attempt unit builds its
    own. A rebuilt prompt that is bigger, or a `CAOS_MODEL_PRICE` that moved
    between the two, would otherwise call under a reservation too small for the
    call -- invariant 8's "no provider call without a reservation" met in form
    only. Whatever the cause, it reaches the executor as a reservation that
    does not cover the request, which is what a pre-check reporting a tenth of
    its own prompt reproduces here at the one seam it can enter by.

    `execute_handoff` reads its own reservation back with the price it was
    taken under and prices the request it is about to send against exactly
    that, so the refusal costs no call and no charge.
    """
    answers = CanonicalCompletions(harness.source_id)
    provider = _UnderMeasures(_module_provider(harness, answers))

    with pytest.raises(Refusal) as caught:
        run_route(
            harness.conn,
            harness.blobs,
            run_id=harness.run_id,
            route=harness.route,
            execution=Execution(provider, _PRICED_INPUT, harness.bundle),
        )

    assert caught.value.code is RefusalCode.RESERVATION_BELOW_REQUEST
    assert answers.prompts == [], "nothing reached the provider"
    assert _counts(harness)[1] == [], "and nothing was charged"
    # The reservation stands: nothing is released (`caos/store/budget.py`).
    assert harness.conn.execute(
        "SELECT count(*) FROM budget_reservations"
    ).fetchone() == (1,)
    harness.conn.rollback()

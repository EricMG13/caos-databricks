"""D110 (N148, the owner's decision of 6 October 2026): a node whose call the
provider itself declared failed -- a status, or an error body or event, and
nothing generated -- gets one automatic re-attempt, ledger-gated like D30's
guided retry. Never a call abandoned at its deadline, one the client ended by
raising, a connection reset, or a stream cut after it had begun to answer.

Invariant 6: exactly one accepted attempt per node, and the ledger, not the
frame that saw the drop, says whether the re-attempt is due, so a crash
between the drop and the re-attempt changes nothing. Invariant 8: the dropped
attempt's reservation is never released; the re-attempt reserves beside it,
and a ceiling that cannot cover both leaves the drop's refusal standing.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass, replace
from decimal import Decimal
from typing import cast
from uuid import uuid4

import pytest
from canonical_fixtures import CanonicalCompletions
from fake_chat import ScriptedChat, StatusError, answer, fake_completions
from openai import OpenAIError
from test_canonical_execution import _node, harness, route
from test_execution_freshness import _Harness
from test_loop_charges import ESTIMATE
from test_second_attempt import (
    SECOND,
    VENDOR_LINE,
    _cp0_ledger,
    _module,
    _run,
    _with_material,
)

from caos import models
from caos.methodology.canonical import (
    DROP_REATTEMPTS,
    _feedback_source,
    drop_reattempt_due,
    reattempts_a_drop,
)
from caos.pricing import ModelPrice
from caos.provider import Completion, DropKind
from caos.refusals import Refusal, RefusalCode
from caos.store import connect
from caos.store.outcomes import CallOutcome, NodeAttempt, record_outcome

__all__ = ["harness", "route"]

PROMPT = "q" * 1000
_ROUTER_ERROR = {
    "code": 502,
    "message": "private upstream words",
    "metadata": {"error_type": "provider_unavailable"},
}


class _Body(OpenAIError):
    """The client's `APIError` for an SSE `error` event: the provider's error
    object as its body, no status (the stream's `200` was already sent)."""

    def __init__(self, body: object) -> None:
        super().__init__("private")
        self.body = body


class _Unreadable(OpenAIError):
    """A vendor error whose body cannot be read without raising."""

    @property
    def body(self) -> object:
        raise RuntimeError("private")


class _Escaping(BaseException):
    """What `suppress(Exception)` does not hold back."""


def _cut() -> Exception:
    import httpx2
    from openai import APIConnectionError

    failed = APIConnectionError(request=httpx2.Request("POST", "https://x.invalid"))
    failed.__cause__ = httpx2.RemoteProtocolError("private")
    return failed


def _never(released: threading.Event) -> Callable[[str], object]:
    def dripping(_prompt: str) -> object:
        released.wait(10)
        return answer(finish="stop")

    return dripping


# -- The seam says how an unanswered call ended (F513's kind, typed) ----------


@pytest.mark.parametrize(
    ("failure", "kind", "code"),
    [
        pytest.param(StatusError(503), DropKind.DECLARED, "PROVIDER_UNAVAILABLE"),
        pytest.param(StatusError(429), DropKind.DECLARED, "PROVIDER_UNAVAILABLE"),
        pytest.param(StatusError(402), DropKind.DECLARED, "PROVIDER_CALL_INVALID"),
        pytest.param(_Body(_ROUTER_ERROR), DropKind.DECLARED, "PROVIDER_UNAVAILABLE"),
        pytest.param(
            _Body({"error": _ROUTER_ERROR}), DropKind.DECLARED, "PROVIDER_UNAVAILABLE"
        ),
        pytest.param(_Body({}), DropKind.VENDOR, "PROVIDER_UNAVAILABLE"),
        pytest.param(_Body("private"), DropKind.VENDOR, "PROVIDER_UNAVAILABLE"),
        pytest.param(_cut(), DropKind.VENDOR, "PROVIDER_UNAVAILABLE"),
        pytest.param(_Unreadable("private"), DropKind.VENDOR, "PROVIDER_UNAVAILABLE"),
        pytest.param(TypeError(_ROUTER_ERROR), DropKind.RAISED, "PROVIDER_UNAVAILABLE"),
    ],
)
def test_an_unanswered_call_carries_how_it_ended(
    failure: Exception, kind: DropKind, code: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A status or a provider error object is the provider's own word; a
    reset, an unreadable error, or anything the client raised is not."""
    monkeypatch.setattr(models, "_sleep", lambda _seconds: None)
    completion = fake_completions(ScriptedChat(answer=failure)).complete(PROMPT)
    assert completion.refusal is RefusalCode(code)
    assert completion.drop_kind is kind
    assert (completion.content, completion.charge, completion.generation_id) == (
        None,
        None,
        None,
    )


def test_a_deadline_and_an_escape_are_never_declared(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(models, "TIMEOUT_SECONDS", 0.2)
    released = threading.Event()
    late = fake_completions(ScriptedChat(answer=_never(released))).complete(PROMPT)
    released.set()
    assert late.drop_kind is DropKind.DEADLINE

    monkeypatch.setattr(threading, "excepthook", lambda _args: None)

    def escaping(_prompt: str) -> object:
        raise _Escaping

    gone = fake_completions(ScriptedChat(answer=escaping)).complete(PROMPT)
    assert gone.drop_kind is DropKind.ESCAPED


def test_an_answered_call_states_no_drop() -> None:
    done = fake_completions(ScriptedChat(answer=answer(finish="stop"))).complete(PROMPT)
    assert done.drop_kind is None
    truncated = fake_completions(ScriptedChat(answer=answer())).complete(PROMPT)
    assert truncated.refusal is RefusalCode.PROVIDER_OUTPUT_TRUNCATED
    assert truncated.drop_kind is None


# -- The ledger rule, walked on attempts alone --------------------------------


def _attempt(code: str | None, drop: DropKind | None = None) -> NodeAttempt:
    return NodeAttempt(uuid4(), code, None, None if drop is None else drop.value)


def test_the_ledger_gives_one_re_attempt_after_one_declared_drop() -> None:
    unavailable, malformed = "PROVIDER_UNAVAILABLE", "HANDOFF_MALFORMED"
    declared = _attempt(unavailable, DropKind.DECLARED)
    assert DROP_REATTEMPTS == 1
    assert reattempts_a_drop([declared])
    # Unexplained (a crash between the bill and its refusal row) still counts.
    assert reattempts_a_drop([_attempt(None, DropKind.DECLARED)])
    assert reattempts_a_drop([_attempt(malformed), declared])
    # A second declared drop at the node, anywhere before, stops it.
    assert not reattempts_a_drop([declared, _attempt(None), declared])
    assert not reattempts_a_drop([declared, declared])
    # Only the latest attempt earns it, and only a declared drop of this code.
    assert not reattempts_a_drop([declared, _attempt(malformed)])
    assert not reattempts_a_drop([_attempt("PROVIDER_CALL_INVALID", DropKind.DECLARED)])
    for kind in (DropKind.VENDOR, DropKind.RAISED, DropKind.ESCAPED, DropKind.DEADLINE):
        assert not reattempts_a_drop([_attempt(unavailable, kind)])
    assert not reattempts_a_drop([_attempt(unavailable)])
    assert not reattempts_a_drop([])


def test_a_declared_drop_is_invisible_to_the_guided_retry_count() -> None:
    """The re-attempt repeats the guided retry it replaces and spends none."""
    first = _attempt("HANDOFF_MALFORMED")
    dropped = _attempt("PROVIDER_UNAVAILABLE", DropKind.DECLARED)
    assert _feedback_source([first, dropped]) == first
    # Any other drop is an ordinary attempt, as before D110.
    timed_out = _attempt("PROVIDER_UNAVAILABLE", DropKind.DEADLINE)
    assert _feedback_source([first, timed_out]) is None


# -- The store keeps the kind, and only beside no answer ----------------------


def test_the_outcome_keeps_its_drop_kind_and_refuses_one_beside_an_answer(
    harness: _Harness,
) -> None:
    from caos.store.runs import start_attempt

    node = _node(harness, "CP-0").route_node_id
    attempt = start_attempt(harness.conn, harness.run_id, node)
    harness.conn.commit()
    for invalid in (
        CallOutcome(Decimal("0.01"), "m", None, drop_kind=DropKind.DECLARED),
        CallOutcome(None, "m", "gen-1", drop_kind=DropKind.DECLARED),
        CallOutcome(None, "m", None, "a" * 64, drop_kind=DropKind.DECLARED),
        # The right word, untyped: the field is the enum, never a string.
        CallOutcome(None, "m", None, drop_kind=cast("DropKind", "declared")),
    ):
        with pytest.raises(Refusal, match=r"^CALL_OUTCOME_INVALID$"):
            record_outcome(harness.conn, attempt_id=attempt, outcome=invalid)
    dropped = CallOutcome(None, "m", None, drop_kind=DropKind.DECLARED)
    assert record_outcome(harness.conn, attempt_id=attempt, outcome=dropped)
    assert not record_outcome(harness.conn, attempt_id=attempt, outcome=dropped)
    with pytest.raises(Refusal, match=r"^CALL_OUTCOME_CONFLICT$"):
        record_outcome(
            harness.conn,
            attempt_id=attempt,
            outcome=CallOutcome(None, "m", None, drop_kind=DropKind.DEADLINE),
        )
    with connect(harness.url) as observer:
        assert observer.execute(
            "SELECT drop_kind FROM call_outcomes WHERE attempt_id = %s", (attempt,)
        ).fetchone() == ("declared",)
        # The table refuses a drop beside a charge, whoever writes it.
        with pytest.raises(Exception, match="call_outcomes_drop"):
            observer.execute(
                "INSERT INTO call_outcomes (attempt_id, run_id, model,"
                " generation_id, drop_kind) VALUES (%s, %s, 'm', 'g', 'declared')",
                (start_attempt(observer, harness.run_id, node), harness.run_id),
            )


# -- The run: one re-attempt, ledger-gated, priced beside the held one --------


@dataclass(frozen=True)
class _Drop:
    """One call that ends as the production seam ends it for `failure`."""

    failure: object


# One CP-0 call's step: drop it, flaw its answer, or (None) answer it.
_Step = _Drop | Callable[[str], str] | None


@dataclass
class _Scripted:
    """CanonicalCompletions whose calls at `module` follow `steps`, then
    answer. A drop is the production seam's own (`caos.models.ChatCompletions`
    over a scripted chat), so its drop kind is what production would record."""

    delegate: CanonicalCompletions
    steps: list[_Step]
    module: str = "CP-0"

    @property
    def model(self) -> str:
        return self.delegate.model

    @property
    def price(self) -> ModelPrice | None:
        return self.delegate.price

    def request_bytes(self, prompt: str, *, json_object: bool = False) -> bytes:
        return self.delegate.request_bytes(prompt, json_object=json_object)

    def complete(self, prompt: str, *, json_object: bool = False) -> Completion:
        mine = _module(prompt) == self.module and self.steps
        step = self.steps.pop(0) if mine else None
        if isinstance(step, _Drop):
            self.delegate.prompts.append(prompt)
            return fake_completions(ScriptedChat(answer=step.failure)).complete(prompt)
        done = self.delegate.complete(prompt, json_object=json_object)
        if step is None:
            return done
        assert done.content is not None
        return replace(done, content=step(done.content))


def _dropping(answers: CanonicalCompletions, failure: object, n: int = 1) -> _Scripted:
    return _Scripted(answers, [_Drop(failure)] * n)


def _drop_kinds(harness: _Harness, module: str = "CP-0") -> list[str | None]:
    node = _node(harness, module).route_node_id
    with connect(harness.url) as observer:
        rows = observer.execute(
            "SELECT o.drop_kind FROM run_attempts t"
            " LEFT JOIN call_outcomes o USING (attempt_id)"
            " WHERE t.run_id = %s AND t.route_node_id = %s ORDER BY t.ordinal",
            (harness.run_id, node),
        ).fetchall()
    return [None if row[0] is None else str(row[0]) for row in rows]


def _reserved(harness: _Harness, module: str = "CP-0") -> list[Decimal]:
    node = _node(harness, module).route_node_id
    with connect(harness.url) as observer:
        rows = observer.execute(
            "SELECT b.amount FROM run_attempts t JOIN budget_reservations b"
            " USING (attempt_id) WHERE t.run_id = %s AND t.route_node_id = %s"
            " ORDER BY t.ordinal",
            (harness.run_id, node),
        ).fetchall()
    return [Decimal(row[0]) for row in rows]


@pytest.mark.parametrize(
    "failure",
    [
        pytest.param(StatusError(503), id="a-5xx-status"),
        pytest.param(_Body(_ROUTER_ERROR), id="an-error-event"),
    ],
)
def test_a_declared_drop_is_re_attempted_once_and_accepted_once(
    harness: _Harness, failure: Exception
) -> None:
    answers = CanonicalCompletions(harness.source_id)
    assert _run(harness, _dropping(answers, failure)) is None
    called = [_module(prompt) for prompt in answers.prompts]
    assert called == ["CP-0", "CP-0", "CP-L10", "CP-5"]
    # Two attempts, two reservations -- the dropped one held, never released
    # -- the drop explained once, one accepted artifact.
    assert _cp0_ledger(harness) == (2, 2, ["PROVIDER_UNAVAILABLE"], 1)
    assert _reserved(harness) == [ESTIMATE, ESTIMATE]
    assert _drop_kinds(harness) == ["declared", None]
    # Not a guided retry: nothing about the drop is carried.
    assert SECOND not in answers.prompts[1]


@pytest.mark.parametrize(
    ("failure", "kind"),
    [
        pytest.param(_cut(), "vendor", id="a-reset"),
        pytest.param(TypeError(_ROUTER_ERROR), "raised", id="a-200-error-body"),
        pytest.param("deadline", "deadline", id="the-deadline"),
    ],
)
def test_an_undeclared_drop_stops_the_run_with_no_re_attempt(
    harness: _Harness, failure: object, kind: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    released = threading.Event()
    if failure == "deadline":
        monkeypatch.setattr(models, "TIMEOUT_SECONDS", 0.2)
        failure = _never(released)
    answers = CanonicalCompletions(harness.source_id)
    stopped = _run(harness, _dropping(answers, failure))
    released.set()
    assert stopped is RefusalCode.PROVIDER_UNAVAILABLE
    assert [_module(prompt) for prompt in answers.prompts] == ["CP-0"]
    assert _cp0_ledger(harness) == (1, 1, ["PROVIDER_UNAVAILABLE"], 0)
    assert _drop_kinds(harness) == [kind]


def test_a_second_declared_drop_stops_the_run(harness: _Harness) -> None:
    answers = CanonicalCompletions(harness.source_id)
    dropping = _dropping(answers, StatusError(503), 3)
    assert _run(harness, dropping) is RefusalCode.PROVIDER_UNAVAILABLE
    assert [_module(prompt) for prompt in answers.prompts] == ["CP-0", "CP-0"]
    assert _cp0_ledger(harness) == (2, 2, ["PROVIDER_UNAVAILABLE"] * 2, 0)
    assert _drop_kinds(harness) == ["declared", "declared"]
    # An operator's requeue after that is an ordinary attempt, and a third
    # declared drop earns nothing either: one re-attempt per node, ever.
    assert _run(harness, dropping) is RefusalCode.PROVIDER_UNAVAILABLE
    assert _cp0_ledger(harness)[0] == 3
    assert _run(harness, dropping) is None
    assert _cp0_ledger(harness)[3] == 1


def test_a_ceiling_that_cannot_cover_the_re_attempt_leaves_the_drop_standing(
    harness: _Harness,
) -> None:
    """Invariant 8: the held reservation is never released, so a ceiling of
    one reservation has nothing left for a second, and the run stops with the
    drop's own code, not the ceiling's."""
    harness.conn.execute(
        "UPDATE runs SET budget_ceiling = %s WHERE run_id = %s",
        (ESTIMATE, harness.run_id),
    )
    harness.conn.commit()
    answers = CanonicalCompletions(harness.source_id)
    assert _run(harness, _dropping(answers, StatusError(503))) is (
        RefusalCode.PROVIDER_UNAVAILABLE
    )
    assert [_module(prompt) for prompt in answers.prompts] == ["CP-0"]
    assert _reserved(harness) == [ESTIMATE]
    with connect(harness.url) as observer:
        assert observer.execute(
            "SELECT count(*) FROM budget_ledger WHERE run_id = %s", (harness.run_id,)
        ).fetchone() == (0,)


def test_a_ceiling_that_covers_both_re_attempts_beside_the_held_reservation(
    harness: _Harness,
) -> None:
    harness.conn.execute(
        "UPDATE runs SET budget_ceiling = %s WHERE run_id = %s",
        (2 * ESTIMATE, harness.run_id),
    )
    harness.conn.commit()
    answers = CanonicalCompletions(harness.source_id)
    stopped = _run(harness, _dropping(answers, StatusError(503)))
    # CP-0 is accepted on the second reservation; the ceiling then stops the
    # next node, which is the ceiling doing its job, not the re-attempt.
    assert stopped is RefusalCode.BUDGET_CEILING_REACHED
    assert _cp0_ledger(harness) == (2, 2, ["PROVIDER_UNAVAILABLE"], 1)
    assert _reserved(harness) == [ESTIMATE, ESTIMATE]


def test_the_re_attempt_of_a_dropped_guided_retry_is_that_guided_retry(
    harness: _Harness,
) -> None:
    """The re-attempt does not spend a guided retry: the 2nd attempt was the
    guided retry of the 1st and was dropped, so the 3rd is told of the 1st,
    as the 2nd was, and is still the node's first guided retry."""
    answers = CanonicalCompletions(harness.source_id)
    steps: list[_Step] = [_with_material, _Drop(StatusError(503))]
    assert _run(harness, _Scripted(answers, steps)) is None
    cp0 = [p for p in answers.prompts if _module(p) == "CP-0"]
    assert len(cp0) == 3
    assert SECOND in cp0[1] and VENDOR_LINE in cp0[1]
    assert SECOND in cp0[2] and VENDOR_LINE in cp0[2]
    count, reserved, codes, accepted = _cp0_ledger(harness)
    assert (count, reserved, accepted) == (3, 3, 1)
    assert sorted(codes) == ["HANDOFF_MALFORMED", "PROVIDER_UNAVAILABLE"]
    assert _drop_kinds(harness) == [None, "declared", None]


def test_a_store_that_cannot_say_leaves_the_drop_standing(
    harness: _Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    from caos.graph import runtime

    def unreadable(*_args: object, **_kwargs: object) -> bool:
        raise Refusal(RefusalCode.STORE_UNAVAILABLE)

    monkeypatch.setattr(runtime, "drop_reattempt_due", unreadable)
    answers = CanonicalCompletions(harness.source_id)
    stopped = _run(harness, _dropping(answers, StatusError(503)))
    assert stopped is RefusalCode.PROVIDER_UNAVAILABLE
    assert _cp0_ledger(harness) == (1, 1, ["PROVIDER_UNAVAILABLE"], 0)


def test_drop_reattempt_due_reads_the_ledger(
    harness: _Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    """After one declared drop the ledger owes the node its re-attempt,
    whatever the frame that saw it decided; after two, never."""
    from caos.graph import runtime

    node = _node(harness, "CP-0").route_node_id

    def due() -> bool:
        return drop_reattempt_due(
            harness.conn, run_id=harness.run_id, route_node_id=node
        )

    assert not due()
    monkeypatch.setattr(runtime, "drop_reattempt_due", lambda *_a, **_k: False)
    answers = CanonicalCompletions(harness.source_id)
    dropping = _dropping(answers, StatusError(503), 2)
    assert _run(harness, dropping) is RefusalCode.PROVIDER_UNAVAILABLE
    monkeypatch.undo()
    assert due()
    assert _run(harness, dropping) is RefusalCode.PROVIDER_UNAVAILABLE
    assert not due()
    assert _drop_kinds(harness) == ["declared", "declared"]

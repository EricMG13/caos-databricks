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
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass, replace
from decimal import Decimal
from typing import ClassVar, cast
from uuid import UUID, uuid4

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
    _feedback_source,
    drop_reattempt_due,
    reattempts_a_drop,
)
from caos.pricing import ModelPrice
from caos.provider import Completion, CutAfterContentError, DropKind
from caos.refusals import Refusal, RefusalCode
from caos.store import StoreConnection, connect
from caos.store.outcomes import (
    DROP_REATTEMPTS,
    CallOutcome,
    NodeAttempt,
    declared_drop,
    drop_stop_owed,
    record_outcome,
)

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


class _Status200(_Body):
    """A provider error object beside a status that says the call succeeded."""

    status_code = 200


class _Argued(OpenAIError):
    """A vendor error whose only argument is a mapping: no status, no body."""


def _validation_200() -> Exception:
    """The client's error for a `200` whose body it could not validate."""
    import httpx2
    from openai import APIResponseValidationError

    request = httpx2.Request("POST", "https://x.invalid/v1/chat/completions")
    response = httpx2.Response(200, request=request, json={"choices": "private"})
    return APIResponseValidationError(response=response, body=_ROUTER_ERROR)


class _RaisingStatus(OpenAIError):
    """A vendor error whose status cannot be read without raising (N162)."""

    @property
    def status_code(self) -> int:
        raise RuntimeError("private")


class _RaisingResponse(OpenAIError):
    """A rate limit whose response cannot be read without raising (N162)."""

    status_code = 429

    @property
    def response(self) -> object:
        raise RuntimeError("private")


class _Unreadable(OpenAIError):
    """A vendor error whose body cannot be read without raising."""

    @property
    def body(self) -> object:
        raise RuntimeError("private")


class _Escaping(BaseException):
    """What `suppress(Exception)` does not hold back."""


def _cut(body: object = None) -> Exception:
    """A reset mid-body; with `body`, one that still carries an error
    object, which a connection's failure never declares."""
    import httpx2
    from openai import APIConnectionError

    failed = APIConnectionError(request=httpx2.Request("POST", "https://x.invalid"))
    failed.__cause__ = httpx2.RemoteProtocolError("private")
    if body is not None:
        failed.body = body
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
        # F530: a 4xx is the provider's own word, but no drop: only a call
        # refused PROVIDER_UNAVAILABLE is ever declared.
        pytest.param(StatusError(402), DropKind.VENDOR, "PROVIDER_CALL_INVALID"),
        pytest.param(StatusError(400), DropKind.VENDOR, "PROVIDER_CALL_INVALID"),
        # F530: a status below 400 or above 599 says no failure, body or not.
        pytest.param(StatusError(200), DropKind.VENDOR, "PROVIDER_UNAVAILABLE"),
        pytest.param(StatusError(600), DropKind.VENDOR, "PROVIDER_UNAVAILABLE"),
        pytest.param(StatusError(599), DropKind.DECLARED, "PROVIDER_UNAVAILABLE"),
        pytest.param(StatusError(408), DropKind.DECLARED, "PROVIDER_UNAVAILABLE"),
        pytest.param(
            _Status200(_ROUTER_ERROR), DropKind.VENDOR, "PROVIDER_UNAVAILABLE"
        ),
        pytest.param(_validation_200(), DropKind.VENDOR, "PROVIDER_UNAVAILABLE"),
        # F530: an argument is not a body.
        pytest.param(_Argued({"anything": 1}), DropKind.VENDOR, "PROVIDER_UNAVAILABLE"),
        pytest.param(
            _Body(["not", "a", "mapping"]), DropKind.VENDOR, "PROVIDER_UNAVAILABLE"
        ),
        pytest.param(_Body(_ROUTER_ERROR), DropKind.DECLARED, "PROVIDER_UNAVAILABLE"),
        pytest.param(
            _Body({"error": _ROUTER_ERROR}), DropKind.DECLARED, "PROVIDER_UNAVAILABLE"
        ),
        pytest.param(_Body({}), DropKind.VENDOR, "PROVIDER_UNAVAILABLE"),
        pytest.param(_Body("private"), DropKind.VENDOR, "PROVIDER_UNAVAILABLE"),
        pytest.param(_cut(), DropKind.VENDOR, "PROVIDER_UNAVAILABLE"),
        pytest.param(_cut(_ROUTER_ERROR), DropKind.VENDOR, "PROVIDER_UNAVAILABLE"),
        pytest.param(StatusError(99), DropKind.VENDOR, "PROVIDER_UNAVAILABLE"),
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


# -- D118: a cut after content, declared by the provider's own error object --


def _after(
    code: object = 502, kind: object = "provider_unavailable", *, nested: bool = False
) -> CutAfterContentError:
    """The cut an adapter raises when the provider's error event follows
    content (F529), its error object holding `code` and `error_type`."""
    error: dict[str, object] = {"message": "private upstream words"}
    if code is not None:
        error["code"] = code
    if kind is not None:
        error["metadata"] = {"error_type": kind}
    return CutAfterContentError({"error": error} if nested else error)


def _reset_after() -> CutAfterContentError:
    """A cut whose cause is a connection's failure: what was received is
    unknown, whatever body it carries."""
    import httpx2
    from openai import APIConnectionError

    cut = _after()
    cut.__cause__ = APIConnectionError(
        request=httpx2.Request("POST", "https://x.invalid")
    )
    return cut


class _RaisingBody(Mapping[str, object]):
    """An error object whose every read raises."""

    def __getitem__(self, _key: str) -> object:
        raise RuntimeError("private")

    def __iter__(self) -> Iterator[str]:
        raise RuntimeError("private")

    def __len__(self) -> int:
        return 1


@pytest.mark.parametrize(
    ("cut", "kind"),
    [
        pytest.param(_after(), DropKind.DECLARED, id="502-event"),
        pytest.param(_after(nested=True), DropKind.DECLARED, id="502-nested"),
        pytest.param(_after("503"), DropKind.DECLARED, id="503-as-digits"),
        pytest.param(_after(500, None), DropKind.DECLARED, id="500-no-type"),
        pytest.param(_after(599, None), DropKind.DECLARED, id="599"),
        pytest.param(_after(429, "rate_limit_exceeded"), DropKind.DECLARED, id="429"),
        pytest.param(
            _after(None, "provider_unavailable"), DropKind.DECLARED, id="type-only"
        ),
        pytest.param(_after(None, "timeout"), DropKind.DECLARED, id="timeout-type"),
        pytest.param(
            _after(None, "provider_overloaded"), DropKind.DECLARED, id="overloaded"
        ),
        pytest.param(_after(None, "server"), DropKind.DECLARED, id="server-type"),
        # A 4xx is the provider's word against the request: never a drop, the
        # type beside it notwithstanding (fail closed).
        pytest.param(_after(400, "invalid_request"), DropKind.RAISED, id="400"),
        pytest.param(_after(408, "timeout"), DropKind.RAISED, id="408-timeout"),
        pytest.param(_after(402, "provider_unavailable"), DropKind.RAISED, id="402"),
        pytest.param(_after(499, None), DropKind.RAISED, id="499"),
        pytest.param(_after(600, None), DropKind.RAISED, id="600"),
        pytest.param(_after(200, "provider_unavailable"), DropKind.RAISED, id="200"),
        pytest.param(_after(True, "provider_unavailable"), DropKind.RAISED, id="bool"),
        pytest.param(_after("5xx", "server"), DropKind.RAISED, id="code-not-status"),
        pytest.param(_after(None, "invalid_request"), DropKind.RAISED, id="4xx-type"),
        pytest.param(_after(None, "private words"), DropKind.RAISED, id="odd-type"),
        pytest.param(_after(None, None), DropKind.RAISED, id="no-code-no-type"),
        # No provider error frame: a plain cut.
        pytest.param(CutAfterContentError({}), DropKind.RAISED, id="empty-body"),
        pytest.param(CutAfterContentError(None), DropKind.RAISED, id="no-body"),
        pytest.param(CutAfterContentError("private"), DropKind.RAISED, id="text"),
        pytest.param(_reset_after(), DropKind.RAISED, id="reset-cause"),
        pytest.param(
            CutAfterContentError(_RaisingBody()),
            DropKind.RAISED,
            id="unreadable",
        ),
    ],
)
def test_a_cut_after_content_is_declared_only_by_a_transient_provider_error(
    cut: CutAfterContentError, kind: DropKind, capsys: pytest.CaptureFixture[str]
) -> None:
    """D118: the provider's error object after content earns the re-attempt
    when it states a 5xx, a 429 or a transient `error_type`; anything else
    stays `raised`. F513's line is unchanged -- the client raised -- and the
    call is never sent again inside the seam."""
    chat = ScriptedChat(answer=cut)
    completion = fake_completions(chat).complete(PROMPT)
    assert completion == Completion(
        None, None, None, RefusalCode.PROVIDER_UNAVAILABLE, kind
    )
    assert chat.calls == 1
    line = capsys.readouterr().err
    assert line.startswith("PROVIDER_UNAVAILABLE call=raised class=")
    assert "private" not in line and "private" not in repr(completion)


def test_a_declared_cut_past_the_deadline_is_the_deadline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A provider's 502 that arrives after the call's one deadline is never
    re-attempted: the host abandoned the call first."""
    monkeypatch.setattr(models, "TIMEOUT_SECONDS", 0.2)
    released = threading.Event()

    def late(_prompt: str) -> object:
        released.wait(10)
        return _after()

    completion = fake_completions(ScriptedChat(answer=late)).complete(PROMPT)
    released.set()
    assert completion.drop_kind is DropKind.DEADLINE


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
    # F530: a declared kind beside another code is no drop and spends nothing.
    invalid = _attempt("PROVIDER_CALL_INVALID", DropKind.DECLARED)
    assert declared_drop(declared) and declared_drop(_attempt(None, DropKind.DECLARED))
    assert not declared_drop(invalid)
    assert not declared_drop(_attempt(unavailable, DropKind.VENDOR))
    assert reattempts_a_drop([invalid, declared])
    assert reattempts_a_drop([invalid, _attempt(None), declared])
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
    # F530: so is a declared kind beside another code, and an unexplained
    # declared drop is passed over as an explained one is.
    invalid = _attempt("PROVIDER_CALL_INVALID", DropKind.DECLARED)
    assert _feedback_source([first, invalid]) is None
    assert _feedback_source([first, _attempt(None, DropKind.DECLARED)]) == first


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


@dataclass(frozen=True)
class _Said:
    """One call whose completion `change` restates: what a provider that
    says more than it should returns."""

    change: Callable[[Completion], Completion]


# One CP-0 call's step: drop it, restate it, flaw its answer, or answer it.
_Step = _Drop | _Said | Callable[[str], str] | None


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
        if isinstance(step, _Said):
            return step.change(done)
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
        # D118: LCR10-dec's stop, an upstream 502 after content had begun.
        pytest.param(_after(), id="a-502-event-after-content"),
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
        # D118: a cut after content with no provider error frame, or one
        # that states a 4xx, is still never re-attempted.
        pytest.param(CutAfterContentError({}), "raised", id="a-plain-cut"),
        pytest.param(_after(400, "invalid_request"), "raised", id="a-4xx-cut"),
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


@pytest.mark.parametrize(
    ("first", "second"),
    [
        pytest.param(_after(), _after(), id="cut-then-cut"),
        pytest.param(StatusError(503), _after(), id="status-then-cut"),
        pytest.param(_after(), _Body(_ROUTER_ERROR), id="cut-then-event"),
    ],
)
def test_a_second_drop_on_the_re_attempt_stops_the_run(
    harness: _Harness, first: Exception, second: Exception
) -> None:
    """D118: a declared cut spends the node's one re-attempt as a drop before
    content does: whichever comes second stops the run, with two calls, two
    held reservations and nothing accepted."""
    answers = CanonicalCompletions(harness.source_id)
    dropping = _Scripted(answers, [_Drop(first), _Drop(second)])
    assert _run(harness, dropping) is RefusalCode.PROVIDER_UNAVAILABLE
    assert [_module(prompt) for prompt in answers.prompts] == ["CP-0", "CP-0"]
    assert _cp0_ledger(harness) == (2, 2, ["PROVIDER_UNAVAILABLE"] * 2, 0)
    assert _reserved(harness) == [ESTIMATE, ESTIMATE]
    assert _drop_kinds(harness) == ["declared", "declared"]


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


def test_a_ceiling_that_covers_both_reservations_makes_the_re_attempt(
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


def test_a_drop_after_three_guided_retries_repeats_the_third(
    harness: _Harness,
) -> None:
    """Five passes: the 4th attempt, the third guided retry, is dropped, and
    the 5th repeats it, told of the 3rd; the guided retries are not spent."""
    answers = CanonicalCompletions(harness.source_id)
    steps: list[_Step] = [_with_material] * 3 + [_Drop(StatusError(503))]
    assert _run(harness, _Scripted(answers, steps)) is None
    cp0 = [p for p in answers.prompts if _module(p) == "CP-0"]
    assert len(cp0) == 5
    assert all(SECOND in prompt for prompt in cp0[1:])
    count, reserved, codes, accepted = _cp0_ledger(harness)
    assert (count, reserved, accepted) == (5, 5, 1)
    assert sorted(codes) == ["HANDOFF_MALFORMED"] * 3 + ["PROVIDER_UNAVAILABLE"]
    assert _drop_kinds(harness) == [None, None, None, "declared", None]


_UNAVAILABLE = RefusalCode.PROVIDER_UNAVAILABLE


@pytest.mark.parametrize(
    "said",
    [
        pytest.param(
            Completion(None, Decimal("0.01"), None, _UNAVAILABLE, DropKind.DECLARED),
            id="beside-a-charge",
        ),
        pytest.param(
            Completion(None, None, "gen-said", _UNAVAILABLE, DropKind.DECLARED),
            id="beside-a-generation",
        ),
        pytest.param(
            Completion(None, None, None, _UNAVAILABLE, cast("DropKind", "declared")),
            id="untyped",
        ),
    ],
)
def test_a_drop_stated_beside_anything_said_is_never_re_attempted(
    harness: _Harness, said: Completion
) -> None:
    """A provider is believed on the money and never on a drop it states
    beside a charge or a generation, or untyped: the bill commits as said,
    no drop kind is recorded, and the run stops."""
    answers = CanonicalCompletions(harness.source_id)
    stopped = _run(harness, _Scripted(answers, [_Said(lambda _done: said)]))
    assert stopped is RefusalCode.PROVIDER_UNAVAILABLE
    assert [_module(prompt) for prompt in answers.prompts] == ["CP-0"]
    assert _drop_kinds(harness) == [None]
    with connect(harness.url) as observer:
        billed = observer.execute(
            "SELECT o.generation_id, l.amount FROM call_outcomes o"
            " LEFT JOIN budget_ledger l ON l.attempt_id = o.charged_attempt_id"
            " WHERE o.run_id = %s",
            (harness.run_id,),
        ).fetchall()
    assert billed == [(said.generation_id, said.charge)]


def test_an_answer_stating_a_drop_is_accepted_as_an_answer(harness: _Harness) -> None:
    answers = CanonicalCompletions(harness.source_id)
    declared = _Said(lambda done: replace(done, drop_kind=DropKind.DECLARED))
    assert _run(harness, _Scripted(answers, [declared])) is None
    assert _cp0_ledger(harness) == (1, 1, [], 1)
    assert _drop_kinds(harness) == [None]


def test_the_passes_are_bounded_whatever_the_ledger_says(
    harness: _Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The frame bounds its own passes -- one, `GUIDED_RETRIES` guided retries
    and `DROP_REATTEMPTS` re-attempts -- so a ledger that always says "again"
    still ends the node, with the last refusal standing."""
    from caos.graph import runtime
    from caos.methodology.canonical import GUIDED_RETRIES

    monkeypatch.setattr(runtime, "second_attempt_due", lambda *_a, **_k: True)
    answers = CanonicalCompletions(harness.source_id)
    steps: list[_Step] = [_with_material] * 9
    stopped = _run(harness, _Scripted(answers, steps))
    assert stopped is RefusalCode.HANDOFF_MALFORMED
    passes = 1 + GUIDED_RETRIES + DROP_REATTEMPTS
    assert [_module(prompt) for prompt in answers.prompts] == ["CP-0"] * passes


def test_a_declared_refusal_of_another_code_earns_nothing(harness: _Harness) -> None:
    """A 402 is the provider's own word too, but `PROVIDER_CALL_INVALID`
    cannot succeed by being repeated: one call, and the run stops."""
    answers = CanonicalCompletions(harness.source_id)
    stopped = _run(harness, _dropping(answers, StatusError(402), 2))
    assert stopped is RefusalCode.PROVIDER_CALL_INVALID
    assert [_module(prompt) for prompt in answers.prompts] == ["CP-0"]
    assert _drop_kinds(harness) == ["vendor"]


def test_a_4xx_on_a_guided_retry_is_not_repeated_as_that_guided_retry(
    harness: _Harness,
) -> None:
    """F530 (audit finding 2): a guided retry refused 400 is an ordinary
    refusal; the operator's requeue after it makes an ordinary attempt, not
    the same guided retry again on every requeue."""
    answers = CanonicalCompletions(harness.source_id)
    steps: list[_Step] = [_with_material, _Drop(StatusError(400))]
    steps.append(_Drop(StatusError(400)))
    scripted = _Scripted(answers, steps)
    assert _run(harness, scripted) is RefusalCode.PROVIDER_CALL_INVALID
    assert _run(harness, scripted) is RefusalCode.PROVIDER_CALL_INVALID
    assert _run(harness, scripted) is None
    cp0 = [p for p in answers.prompts if _module(p) == "CP-0"]
    assert [SECOND in prompt for prompt in cp0] == [False, True, False, False]


def test_a_4xx_does_not_spend_the_nodes_re_attempt(harness: _Harness) -> None:
    """F530 (audit finding 2): after a 400 and a requeue, a declared 503 is
    still the node's first drop and is re-attempted."""
    answers = CanonicalCompletions(harness.source_id)
    steps: list[_Step] = [_Drop(StatusError(400)), _Drop(StatusError(503))]
    scripted = _Scripted(answers, steps)
    assert _run(harness, scripted) is RefusalCode.PROVIDER_CALL_INVALID
    assert _run(harness, scripted) is None
    assert [_module(p) for p in answers.prompts][:3] == ["CP-0"] * 3
    assert _drop_kinds(harness) == ["vendor", "declared", None]


@pytest.mark.parametrize(
    "failure",
    [
        pytest.param(_RaisingStatus("private"), id="status-raises"),
        pytest.param(_RaisingResponse("private"), id="rate-limit-response-raises"),
    ],
)
def test_a_vendor_error_that_cannot_be_read_is_unavailable_and_recorded(
    harness: _Harness,
    failure: Exception,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """F530 (N162): a `RuntimeError` from reading the error escaped
    `complete` untyped before the bill -- no outcome, no F513 line, the run
    parked INTERNAL_FAULT. It is now `PROVIDER_UNAVAILABLE`, `raised`, and
    its outcome is recorded; nothing of its text travels."""
    monkeypatch.setattr(models, "_sleep", lambda _seconds: None)
    done = fake_completions(ScriptedChat(answer=failure)).complete(PROMPT)
    assert done.refusal is RefusalCode.PROVIDER_UNAVAILABLE
    assert done.drop_kind is DropKind.RAISED
    line = capsys.readouterr().err
    assert line.startswith("PROVIDER_UNAVAILABLE call=raised class=")
    assert "private" not in line
    if isinstance(failure, _RaisingStatus):
        # Its facts are unknown, as F513 says of a failure that raises when read.
        assert "class=? cause=? status=?" in line
    answers = CanonicalCompletions(harness.source_id)
    stopped = _run(harness, _dropping(answers, failure))
    assert stopped is RefusalCode.PROVIDER_UNAVAILABLE
    assert _cp0_ledger(harness) == (1, 1, ["PROVIDER_UNAVAILABLE"], 0)
    assert _drop_kinds(harness) == ["raised"]


def test_a_direct_callers_rerun_after_a_spent_re_attempt_is_its_own_decision(
    harness: _Harness,
) -> None:
    """F530: with no work row there is no park to wait for -- a direct
    caller (the harness, the suite) reruns only by deciding to -- so no stop
    is owed and the rerun calls."""
    answers = CanonicalCompletions(harness.source_id)
    dropping = _dropping(answers, StatusError(503), 2)
    assert _run(harness, dropping) is RefusalCode.PROVIDER_UNAVAILABLE
    node = _node(harness, "CP-0").route_node_id
    with connect(harness.url) as observer:
        assert not drop_stop_owed(observer, run_id=harness.run_id, route_node_id=node)
    assert _run(harness, dropping) is None
    assert _drop_kinds(harness) == ["declared", "declared", None]


def test_node_attempts_reads_each_attempt_as_the_ledger_holds_it(
    harness: _Harness,
) -> None:
    """The dropped attempt: its refusal, no body, its drop kind; the accepted
    one: no refusal, its body's address, no drop kind -- unknown is None,
    never the word."""
    from caos.store.outcomes import node_attempts

    answers = CanonicalCompletions(harness.source_id)
    assert _run(harness, _dropping(answers, StatusError(503))) is None
    node = _node(harness, "CP-0").route_node_id
    with connect(harness.url) as observer:
        dropped, accepted = node_attempts(observer, harness.run_id, node)
    assert (dropped.refusal, dropped.diagnostic_sha256, dropped.drop_kind) == (
        "PROVIDER_UNAVAILABLE",
        None,
        "declared",
    )
    assert accepted.refusal is None and accepted.drop_kind is None
    assert accepted.diagnostic_sha256 is not None
    assert len(accepted.diagnostic_sha256) == 64


class _GetRaises:
    def get(self, _name: str) -> object:
        raise RuntimeError("private")


class _Headed:
    headers = _GetRaises()


class _LimitedUnreadably(OpenAIError):
    status_code = 429
    response = _Headed()


def test_a_rate_limits_facts_that_raise_read_as_unreadable_or_the_default_wait(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """F530 (N162), below the client: a `Retry-After` whose read raises waits
    the default; a status or a response that raises is `_UnreadableError`,
    and the call it ends is `raised`, PROVIDER_UNAVAILABLE, never untyped."""
    from caos.provider import TIMEOUT_SECONDS

    assert models._retry_after(_LimitedUnreadably("private")) == (
        models.RETRY_AFTER_SECONDS
    )
    with pytest.raises(models._UnreadableError):
        models._retry_after(_RaisingResponse("private"))
    with pytest.raises(models._UnreadableError):
        models._rate_limited(_RaisingStatus("private"))
    with pytest.raises(models._UnreadableError):
        models._status_refusal(_RaisingStatus("private"))
    ended = models._vendor_ended(
        _RaisingResponse("private"), 1, models._clock() + TIMEOUT_SECONDS, 0.0
    )
    assert ended == Completion(
        None, None, None, RefusalCode.PROVIDER_UNAVAILABLE, DropKind.RAISED
    )
    assert capsys.readouterr().err.startswith(
        "PROVIDER_UNAVAILABLE call=raised class=_RaisingResponse "
    )


class _Retry:
    headers: ClassVar[dict[str, str]] = {"retry-after": "0.5"}


class _LimitedBriefly(OpenAIError):
    status_code = 429
    response = _Retry()


def test_the_declared_bounds_and_a_brief_retry_after() -> None:
    """`_declared`'s failure statuses are 400 to 599 inclusive, and a stated
    wait under a second is waited as stated."""
    assert models._declared(StatusError(400)) and models._declared(StatusError(599))
    assert not models._declared(StatusError(399))
    assert not models._declared(StatusError(600))
    assert models._retry_after(_LimitedBriefly("private")) == 0.5


def test_drop_stop_owed_reads_the_park_against_the_latest_drop(
    harness: _Harness,
) -> None:
    """F530: two declared drops, a park, a third declared drop with no park
    after it: the stop is owed for the third, whatever the park said of the
    two before it; a park after the third settles it."""
    from caos.store.events import RunEvent, append
    from caos.store.runs import start_attempt
    from caos.store.work import enqueue_run

    node = _node(harness, "CP-0").route_node_id
    conn = harness.conn
    dropped = CallOutcome(None, "m", None, drop_kind=DropKind.DECLARED)

    def drop() -> None:
        attempt = start_attempt(conn, harness.run_id, node)
        assert record_outcome(conn, attempt_id=attempt, outcome=dropped)

    def park() -> None:
        append(conn, harness.run_id, RunEvent.RUN_PARKED)
        conn.commit()

    def owed() -> bool:
        said = drop_stop_owed(conn, run_id=harness.run_id, route_node_id=node)
        conn.rollback()
        return said

    drop()
    drop()
    park()
    drop()
    assert not owed(), "no work row: a direct caller's"
    enqueue_run(conn, harness.run_id)
    conn.commit()
    assert owed()
    # F530 round 2: the stop is decided under the run lock, in the unit
    # that would start the attempt -- after the lease answer, as every
    # start is -- and nothing is written.
    from caos.boundary_text import BoundaryText
    from caos.store.work import claim_run

    with pytest.raises(Refusal, match=r"^LEASE_NOT_HELD$"):
        start_attempt(conn, harness.run_id, node)
    lease = claim_run(conn, worker=BoundaryText.of("worker-a"), lease_seconds=60)
    conn.commit()
    assert lease is not None
    with pytest.raises(Refusal, match=r"^PROVIDER_UNAVAILABLE$"):
        start_attempt(conn, harness.run_id, node, lease=lease)
    assert _drop_kinds(harness) == ["declared"] * 3
    park()
    assert not owed()
    start_attempt(conn, harness.run_id, node, lease=lease)
    assert _drop_kinds(harness) == ["declared"] * 3 + [None]


def test_a_drop_billed_after_the_node_moved_on_is_kept_but_not_counted(
    harness: _Harness,
) -> None:
    """F530 round 2: a bill is never fenced -- the call happened -- but a
    drop billed after a later attempt at the node was started (a holder
    wedged past its call hold) keeps its row without its kind: the ledger
    already decided without it. An exact replay of that bill is a no-op."""
    from caos.store.runs import start_attempt

    node = _node(harness, "CP-0").route_node_id
    conn = harness.conn
    dropped = CallOutcome(None, "m", None, drop_kind=DropKind.DECLARED)
    first = start_attempt(conn, harness.run_id, node)
    assert record_outcome(conn, attempt_id=first, outcome=dropped)
    late = start_attempt(conn, harness.run_id, node)
    latest = start_attempt(conn, harness.run_id, node)
    assert record_outcome(conn, attempt_id=latest, outcome=dropped)
    assert record_outcome(conn, attempt_id=late, outcome=dropped)
    assert not record_outcome(conn, attempt_id=late, outcome=dropped)
    assert _drop_kinds(harness) == ["declared", None, "declared"]


class _RaisingEquality:
    """A status that raises when compared or hashed (round 2's INFO)."""

    def __eq__(self, other: object) -> bool:
        raise RuntimeError("private")

    def __hash__(self) -> int:
        raise RuntimeError("private")


class _OddStatus(OpenAIError):
    def __init__(self, status: object) -> None:
        super().__init__("private")
        self.status_code = status


class _RaisingInt(int):
    def __eq__(self, other: object) -> bool:
        raise RuntimeError("private")

    def __hash__(self) -> int:
        raise RuntimeError("private")


@pytest.mark.parametrize("status", [_RaisingEquality(), _RaisingInt(429)])
def test_a_status_that_raises_when_compared_is_no_status(status: object) -> None:
    """F530 round 2: a status is compared only once it is an `int` itself,
    so no comparison runs code of the client's; anything else is no status,
    and the call is PROVIDER_UNAVAILABLE, `vendor`, never an escape."""
    failed = _OddStatus(status)
    done = fake_completions(ScriptedChat(answer=failed)).complete(PROMPT)
    assert done.refusal is RefusalCode.PROVIDER_UNAVAILABLE
    assert done.drop_kind is DropKind.VENDOR
    assert not models._rate_limited(failed)
    assert models._status_refusal(failed) is RefusalCode.PROVIDER_UNAVAILABLE


def test_an_exact_replay_of_a_kept_drop_after_a_later_start_is_a_no_op(
    harness: _Harness,
) -> None:
    """F530 round 3 (re-audit P1): a drop written with its kind, then replayed
    exactly after a later attempt at its node started, is the same bill --
    a no-op, never `CALL_OUTCOME_CONFLICT`. A different replay still is."""
    from caos.store.runs import start_attempt

    node = _node(harness, "CP-0").route_node_id
    conn = harness.conn
    dropped = CallOutcome(None, "m", None, drop_kind=DropKind.DECLARED)
    first = start_attempt(conn, harness.run_id, node)
    assert record_outcome(conn, attempt_id=first, outcome=dropped)
    start_attempt(conn, harness.run_id, node)
    assert not record_outcome(conn, attempt_id=first, outcome=dropped)
    assert _drop_kinds(harness) == ["declared", None]
    for other in (
        CallOutcome(None, "m", None, drop_kind=DropKind.VENDOR),
        CallOutcome(None, "m", None),
    ):
        with pytest.raises(Refusal, match=r"^CALL_OUTCOME_CONFLICT$"):
            record_outcome(conn, attempt_id=first, outcome=other)


def test_a_bill_retried_after_a_lost_ack_and_a_later_start_is_a_no_op(
    harness: _Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    """F530 round 3 (re-audit P1b), the production path: `bill`'s first write
    commits and its answer is lost; another worker starts an attempt at the
    node during the pause; the retry replays the drop exactly and the bill
    completes, with the kind first written."""
    from caos.methodology import canonical
    from caos.store.runs import start_attempt

    node = _node(harness, "CP-0").route_node_id
    conn = harness.conn
    dropped = CallOutcome(None, "m", None, drop_kind=DropKind.DECLARED)
    first = start_attempt(conn, harness.run_id, node)
    real = record_outcome
    tries: list[int] = []

    def lost_ack(c: StoreConnection, *, attempt_id: UUID, outcome: CallOutcome) -> bool:
        tries.append(1)
        said = real(c, attempt_id=attempt_id, outcome=outcome)
        if len(tries) == 1:
            raise Refusal(RefusalCode.STORE_UNAVAILABLE)
        return said

    def pause(_seconds: float) -> None:
        with connect(harness.url) as other:
            start_attempt(other, harness.run_id, node)

    monkeypatch.setattr(canonical, "record_outcome", lost_ack)
    monkeypatch.setattr(canonical, "_pause", pause)
    canonical.bill(conn, first, dropped)
    assert len(tries) == 2
    assert _drop_kinds(harness) == ["declared", None]

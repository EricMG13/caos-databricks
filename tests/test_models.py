"""The model factory: one seam, priced and identified, and nothing leaks (D7, D8)."""

from __future__ import annotations

import time
from datetime import date
from decimal import Decimal

import pytest
from fake_chat import MODEL, PRICE, ScriptedChat, StatusError, answer, fake_completions
from langchain_core.language_models import BaseChatModel

from caos import models
from caos.models import (
    ChatCompletions,
    chat_model,
    completions,
    configured_endpoint,
    from_environment,
)
from caos.pricing import ModelPrice, price_from_environment
from caos.provider import (
    MAX_COMPLETION_TOKENS,
    MAX_REQUEST_BYTES,
    finish_refusal,
    reported_charge,
)
from caos.refusals import Refusal, RefusalCode

# Long enough that its request carries the fixtures' 1,000 input tokens: no
# request holds more tokens than bytes (ST-11).
PROMPT = "q" * 1000


def test_the_charge_is_tokens_times_the_dated_price_exactly() -> None:
    provider = fake_completions(
        ScriptedChat(answer=answer(finish="stop", tokens=(3, 7)))
    )
    completion = provider.complete(PROMPT, json_object=True)
    assert completion.charge == Decimal("0.0010")
    assert completion.content == "private"
    assert completion.generation_id == "generation"
    assert completion.refusal is None
    # Unknown, never zero, when the response carried no usage.
    without = fake_completions(ScriptedChat(answer=answer(finish="stop", tokens=None)))
    unknown = without.complete(PROMPT)
    assert unknown.charge is None
    assert unknown.refusal is RefusalCode.PROVIDER_RESPONSE_INVALID


@pytest.mark.parametrize(
    "finish,code",
    [
        ("length", RefusalCode.PROVIDER_OUTPUT_TRUNCATED),
        ("content_filter", RefusalCode.PROVIDER_REFUSED),
        ("tool_calls", RefusalCode.PROVIDER_RESPONSE_INVALID),
    ],
)
def test_a_finish_reason_other_than_stop_is_a_refusal_with_its_bill(
    finish: str, code: RefusalCode
) -> None:
    assert finish_refusal("stop") is None
    assert finish_refusal(finish) is code
    provider = fake_completions(ScriptedChat(answer=answer(finish=finish)))
    completion = provider.complete(PROMPT)
    assert (completion.content, completion.refusal) == (None, code)
    assert completion.charge == Decimal("0.25")


@pytest.mark.parametrize(
    "failure,code",
    [
        (StatusError(402), RefusalCode.PROVIDER_CALL_INVALID),
        (StatusError(429), RefusalCode.PROVIDER_UNAVAILABLE),
        (StatusError(503), RefusalCode.PROVIDER_UNAVAILABLE),
        (TimeoutError("private"), RefusalCode.PROVIDER_UNAVAILABLE),
        (ValueError("private"), RefusalCode.PROVIDER_UNAVAILABLE),
    ],
)
def test_a_vendor_failure_maps_to_its_status_class_and_carries_no_text(
    failure: Exception, code: RefusalCode
) -> None:
    provider = fake_completions(ScriptedChat(answer=failure))
    completion = provider.complete(PROMPT)
    assert completion == completion.__class__(None, None, None, code)
    assert "private" not in repr(completion)


def test_a_fenced_answer_is_unwrapped_and_a_blank_id_is_host_minted() -> None:
    # LangChain assigns a run id when the vendor sends none; an id the host
    # cannot accept as a producer identifier (a space) is what gets minted over.
    fenced = answer('```json\n{"a": 1}\n```', finish="stop", generation="bad id")
    provider = fake_completions(ScriptedChat(answer=fenced))
    completion = provider.complete(PROMPT)
    assert completion.content == '{"a": 1}'
    assert completion.generation_id is not None
    assert completion.generation_id.startswith(models.HOST_MINTED)
    again = fake_completions(ScriptedChat(answer=fenced)).complete(PROMPT)
    assert again.generation_id == completion.generation_id, "minted from the bytes"


def test_the_request_is_bounded_and_the_identity_is_the_endpoint() -> None:
    provider = fake_completions(ScriptedChat(answer=answer()), model="databricks-x")
    assert provider.model == "databricks-x"
    assert (
        provider.qualification_identity
        == f"databricks/databricks-x/none/{MAX_COMPLETION_TOKENS}"
    )
    assert b'"max_completion_tokens": 65536' in provider.request_bytes("q")
    assert b"json_object" in provider.request_bytes("q", json_object=True)
    with pytest.raises(Refusal, match=r"^PROVIDER_CALL_INVALID$"):
        provider.complete("x" * (MAX_REQUEST_BYTES + 1))
    with pytest.raises(Refusal, match=r"^PROVIDER_NOT_CONFIGURED$"):
        ChatCompletions(ScriptedChat(answer=answer()), "bad model", PRICE).complete(
            PROMPT
        )


def test_completions_is_priced_for_exactly_its_endpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(models.ENDPOINT_ENV, raising=False)
    assert configured_endpoint() == models.DEFAULT_ENDPOINT
    monkeypatch.setenv(models.ENDPOINT_ENV, "databricks-y")
    assert configured_endpoint() == "databricks-y"
    other = ModelPrice("databricks-y", Decimal(1), Decimal(1), date(2026, 9, 22))
    with pytest.raises(Refusal, match=r"^PROVIDER_NOT_CONFIGURED$"):
        completions(other, chat=ScriptedChat(answer=answer()), endpoint=MODEL)
    provider = completions(other, chat=ScriptedChat(answer=answer()))
    assert provider.model == "databricks-y"
    assert isinstance(provider.chat, BaseChatModel)


def test_from_environment_reads_three_names_and_never_a_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _Gateway(ScriptedChat):
        pass

    built: list[str] = []

    def fake_chat_model(*, endpoint: str | None = None) -> BaseChatModel:
        built.append(endpoint or "")
        return _Gateway(answer=answer())

    monkeypatch.setattr(models, "chat_model", fake_chat_model)
    monkeypatch.setenv(models.ENDPOINT_ENV, "databricks-z")
    monkeypatch.delenv(models.MODEL_PRICE_ENV, raising=False)
    with pytest.raises(Refusal, match=r"^PROVIDER_NOT_CONFIGURED$"):
        from_environment()
    monkeypatch.setenv(
        models.MODEL_PRICE_ENV, "databricks-z,0.000001,0.000004,2026-09-22"
    )
    monkeypatch.setenv(models.REASONING_EFFORT_ENV, "high")
    with pytest.raises(Refusal, match=r"^PROVIDER_NOT_CONFIGURED$"):
        # AR-15: an effort the endpoint never receives names no profile.
        from_environment()
    monkeypatch.delenv(models.REASONING_EFFORT_ENV)
    provider = from_environment()
    assert built == ["databricks-z"]
    assert provider.qualification_identity == "databricks/databricks-z/none/65536"
    # The same profile from the names alone, so a caller can refuse an
    # unexpected one before any client is built (`scripts/qualify.py`).
    assert models.identity_of("databricks-z") == provider.qualification_identity
    assert models.identity_of("m", "high") == "databricks/m/high/65536"
    assert (
        price_from_environment(
            "databricks-z", "databricks-z,0.000001,0.000004,2026-09-22"
        )
        == provider.price
    )


def test_the_production_model_is_chat_databricks_on_the_endpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import databricks_langchain

    seen: dict[str, object] = {}

    class _ChatDatabricks(ScriptedChat):
        def __init__(self, **given: object) -> None:
            seen.update(given)
            super().__init__(answer=answer())

    monkeypatch.setattr(databricks_langchain, "ChatDatabricks", _ChatDatabricks)
    client = object()
    monkeypatch.setattr("caos.workspace.workspace_client", lambda: client)
    monkeypatch.setenv(models.ENDPOINT_ENV, "databricks-claude-opus-5")
    model = chat_model()
    assert isinstance(model, _ChatDatabricks)
    assert seen == {
        "endpoint": "databricks-claude-opus-5",
        "max_tokens": 65536,
        "timeout": 240.0,
        "max_retries": 0,
        # The process's bounded client (CR-6), not the library's default one
        # with the SDK's five-minute discovery budget.
        "workspace_client": client,
    }
    assert isinstance(chat_model(endpoint="other"), _ChatDatabricks)
    assert seen["endpoint"] == "other"


def test_reported_charge_is_exact_known_money_or_unknown() -> None:
    assert reported_charge(Decimal("0.25")) == Decimal("0.25")
    assert reported_charge(3) == Decimal(3)
    assert reported_charge(Decimal("NaN")) is None
    assert reported_charge(Decimal("-1")) is None
    assert reported_charge(0.25) is None
    assert reported_charge("0.25") is None


def test_a_finish_reason_the_response_does_not_state_is_not_stop() -> None:
    """`stop` is the one completed reason (F34): a response with no finish
    reason, or a null one, is refused as invalid with its bill kept."""
    from langchain_core.messages import AIMessage

    for metadata in ({}, {"finish_reason": None}, {"finish_reason": ""}):
        message = AIMessage(
            content='{"a": 1}',
            id="generation",
            response_metadata=metadata,
            usage_metadata={"input_tokens": 3, "output_tokens": 7, "total_tokens": 10},
        )
        completion = fake_completions(ScriptedChat(answer=message)).complete(PROMPT)
        assert completion.refusal is RefusalCode.PROVIDER_RESPONSE_INVALID, metadata
        assert completion.content is None and completion.charge is not None


def test_an_answer_past_the_response_ceiling_is_billed_and_refused() -> None:
    from caos.provider import MAX_RESPONSE_BYTES

    huge = answer("x" * (MAX_RESPONSE_BYTES + 1), finish="stop", tokens=(1, 1))
    completion = fake_completions(ScriptedChat(answer=huge)).complete(PROMPT)
    assert completion.refusal is RefusalCode.PROVIDER_RESPONSE_INVALID
    assert completion.content is None and completion.charge is not None
    exact = answer("x" * MAX_RESPONSE_BYTES, finish="stop", tokens=(1, 1))
    assert fake_completions(ScriptedChat(answer=exact)).complete(PROMPT).refusal is None


def test_a_langchain_run_id_is_never_recorded_as_the_provider_s() -> None:
    """LangChain fills an id the response did not carry with its own run id
    (F36); the record says host-minted, and a completion id the client
    surfaces wins over the message id."""
    from langchain_core.messages import AIMessage

    minted = answer("body", finish="stop", generation="lc_run--0192-abc-0")
    completion = fake_completions(ScriptedChat(answer=minted)).complete(PROMPT)
    assert completion.generation_id is not None
    assert completion.generation_id.startswith(models.HOST_MINTED)
    surfaced = AIMessage(
        content="body",
        id="lc_run--0192-abc-0",
        response_metadata={"finish_reason": "stop", "id": "chatcmpl-77"},
        usage_metadata={"input_tokens": 1, "output_tokens": 1, "total_tokens": 2},
    )
    assert (
        fake_completions(ScriptedChat(answer=surfaced)).complete(PROMPT).generation_id
        == "chatcmpl-77"
    )


def test_the_chat_model_carries_the_socket_deadline_and_never_retries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """F40: the lease is sized against `TIMEOUT_SECONDS` (brief D5), so the
    transport must actually carry it, and a retry is the caller's reservation."""
    from databricks.sdk import WorkspaceClient
    from databricks.sdk.config import Config
    from databricks_langchain import ChatDatabricks

    from caos.models import chat_model
    from caos.provider import TIMEOUT_SECONDS

    assert TIMEOUT_SECONDS == 240.0, "a generation budget inside the lease (MX-4)"
    client = WorkspaceClient(config=Config(host="http://127.0.0.1:9", token="t"))
    monkeypatch.setattr("caos.workspace.workspace_client", lambda: client)
    chat = chat_model(endpoint="databricks-x")
    assert isinstance(chat, ChatDatabricks)
    assert chat.timeout == TIMEOUT_SECONDS
    assert chat.max_retries == 0


def test_a_rate_limit_is_asked_again_under_the_same_reservation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """DP-5: a 429 reached no model, so it is the one vendor failure that is
    retried below the seam -- bounded, waiting the gateway's `Retry-After`."""
    from types import SimpleNamespace

    from caos.models import (
        RATE_LIMIT_TRIES,
        RATE_LIMITED,
        RETRY_AFTER_CAP_SECONDS,
        RETRY_AFTER_SECONDS,
    )

    slept: list[float] = []
    monkeypatch.setattr(models, "_sleep", slept.append)
    calls = {"n": 0}

    def limited_twice(prompt: str) -> object:
        calls["n"] += 1
        if calls["n"] < 3:
            return StatusError(RATE_LIMITED)
        return answer(finish="stop")

    provider = fake_completions(ScriptedChat(answer=limited_twice))
    completion = provider.complete(PROMPT)
    assert completion.refusal is None and calls["n"] == 3
    assert slept == [RETRY_AFTER_SECONDS, RETRY_AFTER_SECONDS]

    always = ScriptedChat(answer=StatusError(RATE_LIMITED))
    completion = fake_completions(always).complete(PROMPT)
    assert completion.refusal is RefusalCode.PROVIDER_UNAVAILABLE
    assert always.calls == RATE_LIMIT_TRIES

    class _Stated(StatusError):
        def __init__(self, retry_after: str) -> None:
            super().__init__(RATE_LIMITED)
            self.response = SimpleNamespace(headers={"retry-after": retry_after})

    assert models._retry_after(_Stated("7")) == 7.0
    assert models._retry_after(_Stated("9999")) == RETRY_AFTER_CAP_SECONDS
    assert models._retry_after(_Stated("soon")) == RETRY_AFTER_SECONDS
    # Every other status is answered once, by its class (F40 stands).
    once = ScriptedChat(answer=StatusError(503))
    assert (
        fake_completions(once).complete(PROMPT).refusal
        is RefusalCode.PROVIDER_UNAVAILABLE
    )
    assert once.calls == 1


def test_a_usage_block_with_a_negative_or_fractional_count_is_not_billed() -> None:
    """AR-14: malformed accounting is an answer the host does not understand,
    refused with an unknown charge, never a zero bill."""
    for tokens in ((-5, 1), (3, -1)):
        provider = fake_completions(
            ScriptedChat(answer=answer(finish="stop", tokens=tokens))
        )
        completion = provider.complete(PROMPT)
        assert completion.charge is None
        assert completion.refusal is RefusalCode.PROVIDER_RESPONSE_INVALID
    assert models._count(0, most=7) == 0 and models._count(7, most=7) == 7


class _Limited(StatusError):
    """A 429 carrying the gateway's `Retry-After`."""

    def __init__(self, retry_after: str) -> None:
        from types import SimpleNamespace

        super().__init__(models.RATE_LIMITED)
        self.response = SimpleNamespace(headers={"retry-after": retry_after})


def test_a_non_finite_retry_after_waits_the_default_and_stays_typed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ST-8, MAX-16: `nan` survived the clamp and `sleep(nan)` raised
    `ValueError` out of `complete`, untyped, parking the run INTERNAL_FAULT."""
    for stated in ("nan", "NaN", "inf", "-inf"):
        assert models._retry_after(_Limited(stated)) == models.RETRY_AFTER_SECONDS
    calls = {"n": 0}

    def limited_then_answered(prompt: str) -> object:
        calls["n"] += 1
        return _Limited("nan") if calls["n"] == 1 else answer(finish="stop")

    slept: list[float] = []
    monkeypatch.setattr(models, "_sleep", slept.append)
    completion = fake_completions(ScriptedChat(answer=limited_then_answered)).complete(
        PROMPT
    )
    assert completion.refusal is None and slept == [models.RETRY_AFTER_SECONDS]


def test_whatever_the_client_raises_once_sent_is_indeterminate_not_untyped() -> None:
    """ST-8: an answer with an empty `choices` is an `IndexError` from the
    client, which escaped `complete` before `record_outcome`; the run was
    parked INTERNAL_FAULT and the requeue paid again. Any failure once the
    request may have been sent is PROVIDER_UNAVAILABLE, with no text."""
    for raised in (
        IndexError("private"),
        KeyError("private"),
        AttributeError("private"),
        ZeroDivisionError("private"),
    ):
        completion = fake_completions(ScriptedChat(answer=raised)).complete(PROMPT)
        assert completion == completion.__class__(
            None, None, None, RefusalCode.PROVIDER_UNAVAILABLE
        )
        assert "private" not in repr(completion)


def test_one_deadline_bounds_the_whole_call_and_the_lease_outlives_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ST-9, MAX-21: three tries at the socket deadline and two capped waits
    held one `complete` for 760 s against a 600 s lease, and the tests only
    checked one try. Every try and wait now shares `TIMEOUT_SECONDS`, the worst
    case the lease and the staleness threshold are asserted against here."""
    from caos.provider import TIMEOUT_SECONDS
    from caos.store.work import LEASE_SECONDS, WORKER_STALE_AFTER

    clock = {"t": 0.0}
    monkeypatch.setattr(models, "_clock", lambda: clock["t"])

    def waited(seconds: float) -> None:
        clock["t"] += seconds

    monkeypatch.setattr(models, "_sleep", waited)

    def slow_limit(prompt: str) -> object:
        clock["t"] += 100.0  # each 429 arrives late
        return _Limited(str(models.RETRY_AFTER_CAP_SECONDS))

    chat = ScriptedChat(answer=slow_limit)
    completion = fake_completions(chat).complete(PROMPT)
    assert completion.refusal is RefusalCode.PROVIDER_UNAVAILABLE
    assert chat.calls == 2, "the third try would have outlived the deadline"
    worst = clock["t"]
    assert worst <= TIMEOUT_SECONDS
    assert LEASE_SECONDS > 2 * TIMEOUT_SECONDS, "a lease outlives two whole calls (D5)"
    assert WORKER_STALE_AFTER >= TIMEOUT_SECONDS + 60.0


def test_an_answer_that_never_finishes_arriving_is_abandoned_at_the_deadline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ST-9: the client's timeout bounds each read, not the call, so a server
    that sent a byte at a time held one call open with no limit. The call is
    abandoned at the whole call's deadline and read as indeterminate."""
    import threading

    from caos import provider as seam

    monkeypatch.setattr(models, "TIMEOUT_SECONDS", 0.3)
    released = threading.Event()

    def dripping(prompt: str) -> object:
        released.wait(10)
        return answer(finish="stop")

    started = time.monotonic()
    completion = fake_completions(ScriptedChat(answer=dripping)).complete(PROMPT)
    elapsed = time.monotonic() - started
    released.set()
    assert completion.refusal is RefusalCode.PROVIDER_UNAVAILABLE
    assert completion.charge is None, "possibly billed: the reservation is kept"
    assert elapsed < 5
    assert seam.TIMEOUT_SECONDS == 240.0


def test_a_re_send_asks_every_installed_check_first() -> None:
    """ST-7: a check that raises stops the re-send, outermost first, and a
    check lives only as long as the block that installed it."""
    from caos.provider import check_resend, resend_checked

    asked: list[str] = []

    def outer() -> None:
        asked.append("outer")

    def refusing() -> None:
        asked.append("inner")
        raise Refusal(RefusalCode.RUN_CANCEL_REQUESTED)

    check_resend()
    with resend_checked(outer), resend_checked(refusing):
        with pytest.raises(Refusal, match=r"^RUN_CANCEL_REQUESTED$"):
            check_resend()
    assert asked == ["outer", "inner"]
    check_resend()
    assert asked == ["outer", "inner"], "gone with its block"

    always = ScriptedChat(answer=_Limited("0"))
    with resend_checked(refusing):
        with pytest.raises(Refusal, match=r"^RUN_CANCEL_REQUESTED$"):
            fake_completions(always).complete(PROMPT)
    assert always.calls == 1, "nothing is sent again once a check refuses"


@pytest.mark.parametrize(
    ("tokens", "content"),
    [
        ((0, 1500), "private"),  # a null or absent input count, read as zero
        ((1000, 0), "private"),  # a null or absent output count for an answer
        ((10**9, 1500), "private"),  # more tokens than the request has bytes
        ((1000, MAX_COMPLETION_TOKENS + 1), "private"),  # past the ceiling asked
        ((10**100, 1), "private"),
    ],
)
def test_a_count_the_provider_could_not_have_meant_is_not_billed(
    tokens: tuple[int, int], content: str
) -> None:
    """ST-11, MAX-05: the client fills an absent or null count with zero, and
    an impossible count was billed as stated -- 25,000 against a 1.66
    reservation, into the immutable ledger. Either is an unknown charge."""
    message = answer(content, finish="stop", tokens=tokens)
    completion = fake_completions(ScriptedChat(answer=message)).complete(PROMPT)
    assert completion.charge is None
    assert completion.refusal is RefusalCode.PROVIDER_RESPONSE_INVALID


def test_a_charge_is_computed_in_the_reservation_s_exact_context() -> None:
    """MAX-N03: charges were multiplied at precision 60 without trapping
    `Inexact`, so a price the reservation accepted was billed rounded. An
    empty answer may still bill its input and no output."""
    from decimal import Inexact

    from caos.pricing import exact_context

    context = exact_context()
    assert context.traps[Inexact]
    precise = ModelPrice(MODEL, Decimal("1." + "0" * 69 + "1"), Decimal(1), PRICE.as_of)
    exact = fake_completions(
        ScriptedChat(answer=answer(finish="stop", tokens=(1, 1))), price=precise
    ).complete(PROMPT)
    assert exact.charge == Decimal("2." + "0" * 69 + "1"), "not rounded to 60 digits"
    empty = fake_completions(
        ScriptedChat(answer=answer("", finish="length", tokens=(1000, 0)))
    ).complete(PROMPT)
    assert empty.charge == Decimal("0.1")


@pytest.mark.parametrize("blank", ["", "   \n\t ", "```json\n```", "```\n  \n```"])
def test_a_blank_answer_is_an_invalid_response_billed_not_a_success(
    blank: str,
) -> None:
    """CF-047: a completed call whose text is empty or whitespace -- a fence
    around nothing included -- became a billed, empty, "successful"
    `Completion`, and surfaced downstream as a malformed handoff (and a second
    attempt spent on nothing). It is the provider's invalid response, like no
    text at all, and its known charge still stands."""
    message = answer(blank, finish="stop", tokens=(1000, 0))
    completion = fake_completions(ScriptedChat(answer=message)).complete(PROMPT)
    assert completion.content is None
    assert completion.refusal is RefusalCode.PROVIDER_RESPONSE_INVALID
    assert completion.charge == Decimal("0.1")
    assert completion.generation_id == "generation"

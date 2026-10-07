"""The test-only OpenRouter adapter's request shape, identity (F479) and
streaming (F511, F512). No network."""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import date
from decimal import Decimal
from pathlib import Path

import httpx
import pytest
from langchain_core.messages import AIMessage
from langchain_openai import ChatOpenAI
from openrouter_adapter import (
    CACHE_OFF,
    EFFORT_ENV,
    KEY_ENV,
    PROVIDER_ENV,
    CutAfterContentError,
    effort_from_environment,
    extra_body_from_environment,
    generating,
    openrouter_chat_model,
    provider_order_from_environment,
    qualification_identity,
)

from caos.models import ChatCompletions
from caos.pricing import ModelPrice
from caos.provider import MAX_COMPLETION_TOKENS, Completion, DropKind
from caos.refusals import RefusalCode

MODEL = "openai/gpt-6-luna"


def _chat(model: str) -> ChatOpenAI:
    chat = openrouter_chat_model(model)
    assert isinstance(chat, ChatOpenAI)
    return chat


@pytest.fixture(autouse=True)
def _clean(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(EFFORT_ENV, raising=False)
    monkeypatch.delenv(PROVIDER_ENV, raising=False)
    monkeypatch.setenv(KEY_ENV, "test-key-not-real")


def test_unset_sends_only_the_cache_switch() -> None:
    assert extra_body_from_environment() == {}
    assert effort_from_environment() is None
    assert provider_order_from_environment() == ()
    assert _chat(MODEL).extra_body == CACHE_OFF


def test_every_request_turns_prompt_caching_off() -> None:
    """D113 live probes: on openai/gpt-6-luna through OpenRouter, automatic
    caching wrote the whole prompt (billed at 1.25x) on every call and read
    nothing, even an identical prompt resent within minutes; explicit mode
    with no breakpoint wrote nothing and cost 20% less. Every request turns
    it off, whatever the two names say."""
    assert CACHE_OFF == {"prompt_cache_options": {"mode": "explicit"}}
    sent: list[dict[str, object]] = []
    _complete(OPENROUTER_STREAM, sent)
    assert sent[0]["prompt_cache_options"] == {"mode": "explicit"}


def test_effort_alone_is_the_reasoning_field(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(EFFORT_ENV, "high")
    assert extra_body_from_environment() == {"reasoning": {"effort": "high"}}


def test_provider_alone_pins_without_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(PROVIDER_ENV, " openai/flex , other ")
    assert extra_body_from_environment() == {
        "provider": {"order": ["openai/flex", "other"], "allow_fallbacks": False}
    }


def test_both_reach_the_chat_model(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(EFFORT_ENV, "high")
    monkeypatch.setenv(PROVIDER_ENV, "openai/flex")
    chat = _chat(MODEL)
    assert chat.extra_body == {
        "reasoning": {"effort": "high"},
        "provider": {"order": ["openai/flex"], "allow_fallbacks": False},
        **CACHE_OFF,
    }


def test_an_invalid_effort_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(EFFORT_ENV, "extreme")
    with pytest.raises(RuntimeError, match=EFFORT_ENV):
        extra_body_from_environment()
    with pytest.raises(RuntimeError, match=EFFORT_ENV):
        qualification_identity(MODEL)


def test_identity_for_each_combination(monkeypatch: pytest.MonkeyPatch) -> None:
    top = str(MAX_COMPLETION_TOKENS)
    assert qualification_identity(MODEL) == f"openrouter/{MODEL}/none/{top}"
    monkeypatch.setenv(EFFORT_ENV, "high")
    assert qualification_identity(MODEL) == f"openrouter/{MODEL}/high/{top}"
    monkeypatch.setenv(PROVIDER_ENV, "openai/flex")
    assert qualification_identity(MODEL) == f"openrouter/{MODEL}@openai/flex/high/{top}"
    monkeypatch.delenv(EFFORT_ENV)
    monkeypatch.setenv(PROVIDER_ENV, "a,b")
    assert qualification_identity(MODEL) == f"openrouter/{MODEL}@a,b/none/{top}"


def test_the_qualify_wrapper_carries_the_adapter_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`tests/qualify_openrouter.py` hands `qualify` a provider whose
    `qualification_identity` is the adapter's, effort and pin included."""
    import importlib

    import qualify_openrouter

    qualify = importlib.import_module("qualify")

    seen: list[ChatCompletions] = []

    def capture(argv: list[str]) -> int:
        seen.append(qualify.from_environment())
        return 0

    monkeypatch.setattr(qualify, "from_environment", qualify.from_environment)
    monkeypatch.setattr(qualify, "main", capture)
    monkeypatch.setenv("CAOS_MODEL_ENDPOINT", MODEL)
    monkeypatch.setenv("CAOS_MODEL_PRICE", f"{MODEL},0.000005,0.000025,2026-09-22")
    monkeypatch.setenv(EFFORT_ENV, "high")
    monkeypatch.setenv(PROVIDER_ENV, "openai/flex")
    assert qualify_openrouter.main([]) == 0
    top = str(MAX_COMPLETION_TOKENS)
    assert (
        seen[0].qualification_identity == f"openrouter/{MODEL}@openai/flex/high/{top}"
    )


@pytest.mark.parametrize("raw", ["", "  "])
def test_an_empty_or_blank_effort_counts_as_unset(
    monkeypatch: pytest.MonkeyPatch, raw: str
) -> None:
    monkeypatch.setenv(EFFORT_ENV, raw)
    assert effort_from_environment() is None


def test_effort_matching_is_case_sensitive(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(EFFORT_ENV, "High")
    with pytest.raises(RuntimeError, match=EFFORT_ENV):
        effort_from_environment()


# Streams as OpenRouter documents them (the streaming, errors and usage
# accounting references, read 5 October 2026): keep-alive comments between
# frames, `role` repeated on every delta, reasoning deltas beside the content,
# and a usage frame that repeats the stream's `finish_reason` in one choice
# instead of OpenAI's empty `choices` (F512). Each is the SSE body's frames.
_HEAD = {"id": "gen-f512", "object": "chat.completion.chunk", "created": 1}
_USAGE = {
    "prompt_tokens": 11,
    "completion_tokens": 7,
    "total_tokens": 18,
    "cost": 0.000095,
    "prompt_tokens_details": {"cached_tokens": 0},
    "completion_tokens_details": {"reasoning_tokens": 3},
}
_KEEP_ALIVE = ": OPENROUTER PROCESSING\n\n"
_DONE = "data: [DONE]\n\n"


def _frame(event: dict[str, object]) -> str:
    body = {**_HEAD, "model": MODEL, "provider": "OpenAI", **event}
    return f"data: {json.dumps(body)}\n\n"


def _delta(delta: dict[str, object], finish: str | None = None) -> str:
    choice: dict[str, object] = {"index": 0, "delta": delta, "finish_reason": finish}
    if finish is not None:
        choice["native_finish_reason"] = "completed"
    return _frame({"choices": [choice]})


_ANSWER = [
    _KEEP_ALIVE,
    _delta({"role": "assistant", "content": "", "reasoning": "Weighing"}),
    _KEEP_ALIVE,
    _delta({"role": "assistant", "content": "", "reasoning": " the ask."}),
    _delta({"role": "assistant", "content": '{"a"'}),
    _delta({"role": "assistant", "content": ": 1}"}, finish="stop"),
]
_USAGE_CHOICE = {
    "index": 0,
    "delta": {"role": "assistant", "content": ""},
    "finish_reason": "stop",
    "native_finish_reason": "completed",
}
OPENROUTER_STREAM = [
    *_ANSWER,
    _frame({"choices": [_USAGE_CHOICE], "usage": _USAGE}),
    _DONE,
]
OPENAI_SPEC_STREAM = [*_ANSWER, _frame({"choices": [], "usage": _USAGE}), _DONE]
_ERROR = {
    "code": 502,
    "message": "private upstream words",
    "metadata": {"error_type": "provider_unavailable", "provider_code": "server"},
}
_ERROR_FRAME = _frame(
    {
        "error": _ERROR,
        "choices": [{"index": 0, "delta": {"content": ""}, "finish_reason": "error"}],
    }
)
MID_STREAM_ERROR = [*_ANSWER[:5], _ERROR_FRAME]
ERROR_ONLY = [_KEEP_ALIVE, _ERROR_FRAME]
CUT_SHORT = _ANSWER[:5]
NO_USAGE = [*_ANSWER, _DONE]
_PRICE = ModelPrice(MODEL, Decimal("0.001"), Decimal("0.01"), date(2026, 10, 5))


def _transport(
    frames: list[str], sent: list[dict[str, object]] | None = None
) -> httpx.Client:
    """A fake OpenRouter answering every request with `frames` as one SSE
    body, recording each request body into `sent`. No network."""

    def answer(request: httpx.Request) -> httpx.Response:
        if sent is not None:
            sent.append(json.loads(request.content))
        return httpx.Response(
            200, headers={"content-type": "text/event-stream"}, text="".join(frames)
        )

    return httpx.Client(transport=httpx.MockTransport(answer))


def _complete(
    frames: list[str], sent: list[dict[str, object]] | None = None
) -> Completion:
    chat = openrouter_chat_model(MODEL, http_client=_transport(frames, sent))
    return ChatCompletions(chat, MODEL, _PRICE).complete("hi", json_object=True)


@pytest.mark.parametrize(
    "frames",
    [
        pytest.param(OPENROUTER_STREAM, id="openrouter-usage-frame"),
        pytest.param(OPENAI_SPEC_STREAM, id="openai-spec-usage-frame"),
    ],
)
def test_a_streamed_json_call_keeps_text_usage_and_id(
    monkeypatch: pytest.MonkeyPatch, frames: list[str]
) -> None:
    """F511, F512: the call streams, and the seam gets the whole answer, the
    charge from the usage and the provider's completion id, from OpenRouter's
    own frame shapes. L9's first live call was refused PROVIDER_RESPONSE_INVALID:
    langchain-openai's JSON-mode stream accumulated `role` across deltas
    (`assistantassistant`), dropped the usage of a message that was then no
    assistant message, and joined the repeated `finish_reason` (`stopstop`).
    JSON mode, the effort, the pin and the ceiling travel; the identity is
    unchanged."""
    monkeypatch.setenv(EFFORT_ENV, "high")
    monkeypatch.setenv(PROVIDER_ENV, "openai/flex")
    sent: list[dict[str, object]] = []
    completion = _complete(frames, sent)
    assert completion.refusal is None
    assert completion.content == '{"a": 1}'
    assert completion.generation_id == "gen-f512"
    assert completion.charge == Decimal("0.081")
    body = sent[0]
    assert body["stream"] is True
    assert body["stream_options"] == {"include_usage": True}
    assert body["response_format"] == {"type": "json_object"}
    assert body["reasoning"] == {"effort": "high"}
    assert body["provider"] == {"order": ["openai/flex"], "allow_fallbacks": False}
    assert body["max_completion_tokens"] == MAX_COMPLETION_TOKENS
    assert body["prompt_cache_options"] == {"mode": "explicit"}
    top = str(MAX_COMPLETION_TOKENS)
    assert qualification_identity(MODEL) == f"openrouter/{MODEL}@openai/flex/high/{top}"


def test_a_streamed_answer_is_one_assistant_message() -> None:
    """The message `invoke` returns: the content alone (reasoning deltas never
    join it), one `finish_reason`, the usage whole with its reasoning tokens,
    and the completion id; nothing is sent that was not asked for."""
    sent: list[dict[str, object]] = []
    chat = openrouter_chat_model(MODEL, http_client=_transport(OPENROUTER_STREAM, sent))
    message = chat.invoke("hi", response_format={"type": "json_object"})
    assert isinstance(message, AIMessage)
    assert message.content == '{"a": 1}'
    assert message.response_metadata["id"] == "gen-f512"
    assert message.response_metadata["finish_reason"] == "stop"
    usage = message.usage_metadata
    assert usage is not None
    assert (usage["input_tokens"], usage["output_tokens"]) == (11, 7)
    assert usage.get("output_token_details", {}).get("reasoning") == 3
    assert "reasoning" not in sent[0]


@pytest.mark.parametrize(
    ("frames", "drop", "said"),
    [
        # D118: LCR10-dec's stop -- an upstream 502 after content -- is a
        # drop the provider declared after content (its own kind since fix
        # round 1); F513's line still says the client raised.
        pytest.param(
            MID_STREAM_ERROR,
            DropKind.DECLARED_AFTER_CONTENT,
            "call=raised class=CutAfterContentError cause=APIError ",
            id="after-partial-output",
        ),
        pytest.param(
            ERROR_ONLY,
            DropKind.DECLARED,
            "call=vendor class=APIError cause=- ",
            id="first-and-only-event",
        ),
    ],
)
def test_a_mid_stream_error_is_unavailable_and_carries_no_text(
    frames: list[str],
    drop: DropKind,
    said: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A provider error after the `200` is committed arrives as an SSE `error`
    event: no answer, no charge, no partial content, and none of its words.
    Before anything was generated it is a drop the provider declared (D110);
    after, it is one too when its error object states a 5xx, a 429 or a
    transient type (D118), and the seam never sends it again itself."""
    completion = _complete(frames)
    # A cut after content keeps the stream's generation id, so its partial
    # bill can be reconciled (D118 fix round 1); a drop before content has
    # nothing generated to reconcile.
    generation = "gen-f512" if drop is DropKind.DECLARED_AFTER_CONTENT else None
    assert completion == Completion(
        None, None, generation, RefusalCode.PROVIDER_UNAVAILABLE, drop
    )
    unanswered = capsys.readouterr().err
    assert said in unanswered
    assert "error_code=502" in unanswered
    assert "error_type=provider_unavailable" in unanswered
    assert "private" not in unanswered and "private" not in repr(completion)


def _error_frame(error: object, content: str = "") -> str:
    """An SSE error frame whose delta carries `content`, as a provider may
    send its last words and its error in one frame."""
    delta = {"content": content}
    return _frame(
        {
            "error": error,
            "choices": [{"index": 0, "delta": delta, "finish_reason": "error"}],
        }
    )


_INVALID_TYPE = {"error_type": "invalid_request"}
_INVALID = {
    "code": 400,
    "message": "private",
    "metadata": {"error_type": "invalid_request"},
}


@pytest.mark.parametrize(
    ("frames", "drop", "said"),
    [
        # L1: a 4xx is never declared, before content or after.
        pytest.param(
            [_KEEP_ALIVE, _error_frame(_INVALID)], DropKind.VENDOR, "", id="400-before"
        ),
        pytest.param(
            [_KEEP_ALIVE, _error_frame({"code": 402, "message": "private"})],
            DropKind.VENDOR,
            "",
            id="402-before",
        ),
        pytest.param(
            [_KEEP_ALIVE, _error_frame({"code": 429, "message": "private"})],
            DropKind.DECLARED,
            "",
            id="429-before",
        ),
        # F566: positive evidence only, before content as after.
        pytest.param(
            [_KEEP_ALIVE, _error_frame({"code": 400.0, "metadata": _INVALID_TYPE})],
            DropKind.VENDOR,
            "",
            id="400-float-before",
        ),
        pytest.param(
            [_KEEP_ALIVE, _error_frame({"code": "invalid_request_error"})],
            DropKind.VENDOR,
            "",
            id="code-word-before",
        ),
        pytest.param(
            [
                _KEEP_ALIVE,
                _error_frame({"metadata": {"error_type": "payment_required"}}),
            ],
            DropKind.VENDOR,
            "",
            id="payment-type-before",
        ),
        pytest.param(
            [_KEEP_ALIVE, _error_frame({"metadata": {"error_type": "timeout"}})],
            DropKind.DECLARED,
            "",
            id="timeout-type-before",
        ),
        # L1: content in the error frame itself is content: the 400 is a cut
        # after content, and a 502 there is declared after content.
        pytest.param(
            [_KEEP_ALIVE, _error_frame(_INVALID, '{"x": 1')],
            DropKind.RAISED,
            "",
            id="400-with-content-in-the-error-frame",
        ),
        pytest.param(
            [_KEEP_ALIVE, _error_frame(_ERROR, '{"x": 1')],
            DropKind.DECLARED_AFTER_CONTENT,
            "",
            id="502-with-content-in-the-error-frame",
        ),
        # L2: the outer error object's own code is read, never an inner one.
        pytest.param(
            [*_ANSWER[:5], _error_frame({"code": 400, "error": {"code": 502}})],
            DropKind.RAISED,
            " error_code=400 ",
            id="outer-400-inner-502",
        ),
    ],
)
def test_an_error_frame_is_read_whole_and_by_its_own_code(
    frames: list[str], drop: DropKind, said: str, capsys: pytest.CaptureFixture[str]
) -> None:
    sent: list[dict[str, object]] = []
    completion = _complete(frames, sent)
    assert completion.refusal is RefusalCode.PROVIDER_UNAVAILABLE
    assert completion.drop_kind is drop
    assert completion.content is None and completion.charge is None
    assert len(sent) == 1
    line = capsys.readouterr().err
    assert said in line and "private" not in line


def test_a_cut_keeps_the_id_its_content_was_generated_under() -> None:
    """The first id the stream named is the generation that streamed the
    content; an error frame that names another does not replace it."""
    choice = {"index": 0, "delta": {"content": ""}, "finish_reason": "error"}
    later = _frame({"id": "gen-later", "error": _ERROR, "choices": [choice]})
    completion = _complete([*_ANSWER[:5], later])
    assert completion.drop_kind is DropKind.DECLARED_AFTER_CONTENT
    assert completion.generation_id == "gen-f512"


def _reset_after_content(sent: list[dict[str, object]]) -> httpx.Client:
    """A fake OpenRouter whose stream carries content, then the connection
    fails with no error frame. No network."""

    class _Cut(httpx.SyncByteStream):
        def __iter__(self) -> Iterator[bytes]:
            yield "".join(_ANSWER[:5]).encode()
            raise httpx.RemoteProtocolError("private")

    def answer(request: httpx.Request) -> httpx.Response:
        sent.append(json.loads(request.content))
        headers = {"content-type": "text/event-stream"}
        return httpx.Response(200, headers=headers, stream=_Cut())

    return httpx.Client(transport=httpx.MockTransport(answer))


@pytest.mark.parametrize("cut", ["reset", "truncated"])
def test_a_cut_after_content_without_an_error_frame_is_not_declared(
    cut: str, capsys: pytest.CaptureFixture[str]
) -> None:
    """D118: the provider said nothing -- a reset mid-stream, or a stream that
    simply stops -- so nothing is declared, nothing is re-attempted, and the
    call is sent once."""
    sent: list[dict[str, object]] = []
    if cut == "reset":
        client = _reset_after_content(sent)
        chat = openrouter_chat_model(MODEL, http_client=client)
        completion = ChatCompletions(chat, MODEL, _PRICE).complete("hi")
        assert completion == Completion(
            None, None, None, RefusalCode.PROVIDER_UNAVAILABLE, DropKind.RAISED
        )
        assert "call=raised" in capsys.readouterr().err
    else:
        completion = _complete(CUT_SHORT, sent)
        assert completion.refusal is RefusalCode.PROVIDER_RESPONSE_INVALID
        assert completion.drop_kind is None
    assert len(sent) == 1


def test_only_a_frame_carrying_something_generated_has_begun() -> None:
    """D110: a role, an empty string or a keep-alive is not an answer begun;
    content, reasoning or a tool call is, and an error after it keeps the
    provider's error object for F513's line but is no declared drop."""
    role_only = {"choices": [{"index": 0, "delta": {"role": "assistant"}}]}
    empty = {"choices": [{"index": 0, "delta": {"content": "", "refusal": None}}]}
    assert not generating(role_only) and not generating(empty)
    assert not generating({"choices": []}) and not generating({})
    assert generating({"choices": [{"delta": {"role": "assistant", "reasoning": "x"}}]})
    assert generating({"choices": [{"delta": {"content": "{"}}]})
    assert generating({"choices": [{"delta": {"tool_calls": [{"index": 0}]}}]})
    assert CutAfterContentError(_ERROR).body == _ERROR
    assert CutAfterContentError(_ERROR).generation_id is None
    assert CutAfterContentError(_ERROR, generation_id="gen-1").generation_id == "gen-1"
    # A malformed frame says nothing generated, and raises nothing.
    assert not generating({"choices": ["x", {"delta": "y"}, None]})
    assert not generating({"choices": "x"})


@pytest.mark.parametrize(
    "frames",
    [
        pytest.param(CUT_SHORT, id="no-finish-no-usage-no-done"),
        pytest.param(NO_USAGE, id="finished-without-usage"),
    ],
)
def test_a_stream_without_its_finish_or_usage_is_not_an_answer(
    frames: list[str],
) -> None:
    """A stream that ends without a stated finish, or without the usage the
    charge is computed from, is a response the host does not understand:
    refused with an unknown charge, never accepted on a partial or unbilled
    body."""
    completion = _complete(frames)
    assert completion.refusal is RefusalCode.PROVIDER_RESPONSE_INVALID
    assert completion.content is None and completion.charge is None


# The raw SSE body of one live streamed call (5 October 2026, `openai/gpt-6-luna`
# pinned to `openai`, effort low, JSON mode): synthetic prompt, no key.
REAL_SAMPLE = Path(__file__).parent / "fixtures" / "openrouter_sse_sample.txt"
REAL_ID = "gen-1791224618-E6l1ZYiIUACmmPituFit"


def test_a_real_openrouter_stream_reads_whole() -> None:
    """F512 on observed bytes: the live sample repeats `role` on every delta
    and carries its usage in a frame that repeats the finish in one choice,
    as the references say; the adapter reads it as one answer, one finish,
    the stated usage and the stream's id, and the seam bills it exactly."""
    frames = [REAL_SAMPLE.read_text(encoding="utf-8")]
    chat = openrouter_chat_model(MODEL, http_client=_transport(frames))
    message = chat.invoke("hi", response_format={"type": "json_object"})
    assert isinstance(message, AIMessage)
    assert message.content == '{"ok": true}'
    assert message.response_metadata["finish_reason"] == "stop"
    assert message.response_metadata["id"] == REAL_ID
    usage = message.usage_metadata
    assert usage is not None
    assert (usage["input_tokens"], usage["output_tokens"]) == (20, 12)
    assert usage["total_tokens"] == 32
    assert usage.get("output_token_details") == {"reasoning": 0}
    price = ModelPrice(MODEL, Decimal("2E-7"), Decimal("0.000001"), date(2026, 10, 2))
    chat = openrouter_chat_model(MODEL, http_client=_transport(frames))
    completion = ChatCompletions(chat, MODEL, price).complete(
        "q" * 200, json_object=True
    )
    assert completion.refusal is None
    assert completion.charge == Decimal("0.0000160")
    assert completion.generation_id == REAL_ID

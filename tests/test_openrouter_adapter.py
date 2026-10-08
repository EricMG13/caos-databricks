"""The test-only OpenRouter adapter's request shape, identity (F479) and
streaming (F511, F512). No network."""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal

import httpx
import pytest
from langchain_core.messages import AIMessage
from langchain_openai import ChatOpenAI
from openrouter_adapter import (
    EFFORT_ENV,
    KEY_ENV,
    PROVIDER_ENV,
    effort_from_environment,
    extra_body_from_environment,
    openrouter_chat_model,
    provider_order_from_environment,
    qualification_identity,
)

from caos.models import ChatCompletions
from caos.pricing import ModelPrice
from caos.provider import MAX_COMPLETION_TOKENS, Completion
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


def test_unset_sends_no_extra_body() -> None:
    assert extra_body_from_environment() == {}
    assert effort_from_environment() is None
    assert provider_order_from_environment() == ()
    assert _chat(MODEL).extra_body is None


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
    "frames",
    [
        pytest.param(MID_STREAM_ERROR, id="after-partial-output"),
        pytest.param(ERROR_ONLY, id="first-and-only-event"),
    ],
)
def test_a_mid_stream_error_is_unavailable_and_carries_no_text(
    frames: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    """A provider error after the `200` is committed arrives as an SSE `error`
    event: no answer, no charge, no partial content, and none of its words."""
    completion = _complete(frames)
    assert completion == Completion(None, None, None, RefusalCode.PROVIDER_UNAVAILABLE)
    unanswered = capsys.readouterr().err
    assert "error_code=502" in unanswered
    assert "error_type=provider_unavailable" in unanswered
    assert "private" not in unanswered and "private" not in repr(completion)


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

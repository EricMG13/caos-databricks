"""The test-only OpenRouter adapter's request shape, identity (F479) and
streaming (F511). No network."""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal

import httpx
import pytest
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
from caos.provider import MAX_COMPLETION_TOKENS

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


def _streamed(sent: list[dict[str, object]]) -> httpx.Client:
    """A fake OpenRouter: records each request body and answers it as an SSE
    stream, a keep-alive comment first, the usage in a last choiceless chunk."""
    head = {"id": "gen-f511", "object": "chat.completion.chunk", "created": 1}
    events: list[dict[str, object]] = [
        {"choices": [{"index": 0, "delta": {"role": "assistant", "content": '{"a"'}}]},
        {"choices": [{"index": 0, "delta": {"content": ": 1}"}}]},
        {"choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]},
        {
            "choices": [],
            "usage": {
                "prompt_tokens": 11,
                "completion_tokens": 7,
                "total_tokens": 18,
                "completion_tokens_details": {"reasoning_tokens": 3},
            },
        },
    ]

    def answer(request: httpx.Request) -> httpx.Response:
        sent.append(json.loads(request.content))
        frames = [": OPENROUTER PROCESSING\n\n"]
        frames += [
            f"data: {json.dumps({**head, 'model': MODEL, **event})}\n\n"
            for event in events
        ]
        frames.append("data: [DONE]\n\n")
        return httpx.Response(
            200, headers={"content-type": "text/event-stream"}, text="".join(frames)
        )

    return httpx.Client(transport=httpx.MockTransport(answer))


def test_a_streamed_json_call_keeps_text_usage_and_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """F511: the call streams, and the seam still gets the whole answer, the
    charge from the usage and the provider's completion id; JSON mode, the
    effort, the pin and the ceiling all travel, and the identity is unchanged."""
    monkeypatch.setenv(EFFORT_ENV, "high")
    monkeypatch.setenv(PROVIDER_ENV, "openai/flex")
    sent: list[dict[str, object]] = []
    chat = openrouter_chat_model(MODEL, http_client=_streamed(sent))
    price = ModelPrice(MODEL, Decimal("0.001"), Decimal("0.01"), date(2026, 10, 5))
    completion = ChatCompletions(chat, MODEL, price).complete("hi", json_object=True)
    assert completion.refusal is None
    assert completion.content == '{"a": 1}'
    assert completion.generation_id == "gen-f511"
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


def test_a_streamed_answer_carries_reasoning_tokens() -> None:
    """The usage the stream ends on reaches the message whole, reasoning included."""
    sent: list[dict[str, object]] = []
    chat = openrouter_chat_model(MODEL, http_client=_streamed(sent))
    message = chat.invoke("hi", response_format={"type": "json_object"})
    assert message.content == '{"a": 1}'
    assert message.response_metadata["id"] == "gen-f511"
    assert message.response_metadata["finish_reason"] == "stop"
    usage = getattr(message, "usage_metadata", None)
    assert usage is not None
    assert (usage["input_tokens"], usage["output_tokens"]) == (11, 7)
    assert usage.get("output_token_details", {}).get("reasoning") == 3
    assert "reasoning" not in sent[0]

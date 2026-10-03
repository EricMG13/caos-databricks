"""The test-only OpenRouter adapter's request shape and identity (F479). No network."""

from __future__ import annotations

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

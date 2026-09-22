"""The model factory: one seam, priced and identified, and nothing leaks (D7, D8)."""

from __future__ import annotations

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
from caos.provider import MAX_COMPLETION_TOKENS, finish_refusal, reported_charge
from caos.refusals import Refusal, RefusalCode


def test_the_charge_is_tokens_times_the_dated_price_exactly() -> None:
    provider = fake_completions(
        ScriptedChat(answer=answer(finish="stop", tokens=(3, 7)))
    )
    completion = provider.complete("q", json_object=True)
    assert completion.charge == Decimal("0.0010")
    assert completion.content == "private"
    assert completion.generation_id == "generation"
    assert completion.refusal is None
    # Unknown, never zero, when the response carried no usage.
    without = fake_completions(ScriptedChat(answer=answer(finish="stop", tokens=None)))
    unknown = without.complete("q")
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
    completion = provider.complete("q")
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
    completion = provider.complete("q")
    assert completion == completion.__class__(None, None, None, code)
    assert "private" not in repr(completion)


def test_a_fenced_answer_is_unwrapped_and_a_blank_id_is_host_minted() -> None:
    # LangChain assigns a run id when the vendor sends none; an id the host
    # cannot accept as a producer identifier (a space) is what gets minted over.
    fenced = answer('```json\n{"a": 1}\n```', finish="stop", generation="bad id")
    provider = fake_completions(ScriptedChat(answer=fenced))
    completion = provider.complete("q")
    assert completion.content == '{"a": 1}'
    assert completion.generation_id is not None
    assert completion.generation_id.startswith(models.HOST_MINTED)
    again = fake_completions(ScriptedChat(answer=fenced)).complete("q")
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
        provider.complete("x" * 1_048_577)
    with pytest.raises(Refusal, match=r"^PROVIDER_NOT_CONFIGURED$"):
        ChatCompletions(ScriptedChat(answer=answer()), "bad model", PRICE).complete("q")


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
    provider = from_environment()
    assert built == ["databricks-z"]
    assert provider.qualification_identity == "databricks/databricks-z/high/65536"
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
        def __init__(self, *, endpoint: str, max_tokens: int) -> None:
            seen.update(endpoint=endpoint, max_tokens=max_tokens)
            super().__init__(answer=answer())

    monkeypatch.setattr(databricks_langchain, "ChatDatabricks", _ChatDatabricks)
    monkeypatch.setenv(models.ENDPOINT_ENV, "databricks-claude-opus-5")
    model = chat_model()
    assert isinstance(model, _ChatDatabricks)
    assert seen == {"endpoint": "databricks-claude-opus-5", "max_tokens": 65536}
    assert isinstance(chat_model(endpoint="other"), _ChatDatabricks)
    assert seen["endpoint"] == "other"


def test_reported_charge_is_exact_known_money_or_unknown() -> None:
    assert reported_charge(Decimal("0.25")) == Decimal("0.25")
    assert reported_charge(3) == Decimal(3)
    assert reported_charge(Decimal("NaN")) is None
    assert reported_charge(Decimal("-1")) is None
    assert reported_charge(0.25) is None
    assert reported_charge("0.25") is None

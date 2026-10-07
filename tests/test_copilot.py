"""GitHub Copilot as the model behind the one factory (D77, addendum 2): the
names, the shared reply mapping against the SDK's own event schema (R1), the
AI-unit charge (R2.3, R2.4, R2.9) and spend on a failed call (R2.10).

Every fake event is built through `copilot.SessionEvent.from_dict(...).to_dict()`
(R5), so a field the pinned SDK does not know, or a value it cannot parse,
fails the fake and not the adapter.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from decimal import Decimal
from typing import Any, cast
from uuid import uuid4

import pytest
from copilot import SessionEvent
from copilot.generated.session_events import SessionEventType
from langchain_core.messages import AIMessage

from caos import copilot as copilot_module
from caos.copilot import (
    CopilotModel,
    Event,
    parsed,
    reply_message,
    settled_charge,
)
from caos.provider import (
    MAX_COMPLETION_TOKENS,
    reserved_amount,
    reserving,
)
from caos.refusals import Refusal, RefusalCode

PIN = "claude-opus-5.5"
MODEL = f"copilot:{PIN}@high"
TARGET = CopilotModel("copilot", PIN, "high")
PROMPT = "q" * 1000
# GitHub's published rate, one AI credit in US dollars (D77).
CREDIT = Decimal("0.01")


# -- The fakes (R5): every one through the SDK's own types. ----------------


def wire(kind: str, /, **data: object) -> Event:
    """One session event exactly as the pinned SDK writes it."""
    written: dict[str, object] = SessionEvent.from_dict(
        {
            "type": kind,
            "data": {key: value for key, value in data.items() if value is not None},
            "id": str(uuid4()),
            "timestamp": "2026-10-06T00:00:00Z",
        }
    ).to_dict()
    return written


def started(model: str = PIN, version: str = "1.0.90") -> Event:
    return wire(
        "session.start",
        copilotVersion=version,
        producer="copilot-agent",
        sessionId=str(uuid4()),
        startTime="2026-10-06T00:00:00Z",
        version=1,
        selectedModel=model,
        reasoningEffort="high",
        contextTier="long_context",
    )


def turn_start() -> Event:
    return wire("assistant.turn_start", turnId="turn-1", model=PIN)


def call_start(model: str = PIN) -> Event:
    return wire("model.call_start", turnId="turn-1", model=model)


def answer(
    content: str = "answer", model: str | None = PIN, **changed: object
) -> Event:
    data: dict[str, object] = {
        "content": content,
        "messageId": "message-1",
        "model": model,
        "apiCallId": "api-call-1",
    }
    data.update(changed)
    return wire("assistant.message", **data)


def call_finished(outcome: str = "success") -> Event:
    return wire(
        "model.call_finished",
        dispatchDurationMs=1200,
        editClassifierVersion=1,
        outcome=outcome,
        turnId="turn-1",
    )


def final_result(
    model: str = PIN, result: str = "success", isByok: bool | None = False
) -> Event:
    return wire("model.call_final_result", model=model, result=result, isByok=isByok)


def usage(**changed: object) -> Event:
    """One exact call's usage: 900 + 80 cache-read + 20 cache-written prompt
    tokens and 40 output tokens, on the pinned model at the pinned effort."""
    data: dict[str, object] = {
        "model": PIN,
        "inputTokens": 900,
        "cacheReadTokens": 80,
        "cacheWriteTokens": 20,
        "outputTokens": 40,
        "finishReason": "end_turn",
        "reasoningEffort": "high",
        "providerCallId": "provider-call-1",
        "apiCallId": "api-call-1",
        "isByok": False,
        "copilotUsage": {"totalNanoAiu": 251_164_000, "model": PIN},
    }
    data.update(changed)
    return wire("assistant.usage", **data)


def turn_end() -> Event:
    return wire("assistant.turn_end", turnId="turn-1", model=PIN)


def checkpoint(nano_aiu: float, premium_requests: float | None = None) -> Event:
    return wire(
        "session.usage_checkpoint",
        totalNanoAiu=nano_aiu,
        totalPremiumRequests=premium_requests,
    )


def idle(aborted: bool | None = None) -> Event:
    return wire("session.idle", aborted=aborted)


def turn_retry(reason: str = "provider_error") -> Event:
    return wire("assistant.turn_retry", turnId="turn-1", model=PIN, reason=reason)


def model_change(new: str, previous: str = PIN) -> Event:
    return wire("session.model_change", newModel=new, previousModel=previous)


def mcp_loaded(servers: Sequence[Mapping[str, object]]) -> Event:
    return wire("session.mcp_servers_loaded", servers=list(servers))


def skills_loaded(skills: Sequence[Mapping[str, object]]) -> Event:
    return wire("session.skills_loaded", skills=list(skills))


def extensions_loaded(extensions: Sequence[Mapping[str, object]]) -> Event:
    return wire("session.extensions_loaded", extensions=list(extensions))


def agents_updated(agents: Sequence[Mapping[str, object]]) -> Event:
    return wire(
        "session.custom_agents_updated", agents=list(agents), errors=[], warnings=[]
    )


Part = Event | Sequence[Event] | None


def sdk_call(**parts: Part) -> list[Event]:
    """The SDK's happy path, with any named part replaced or (None) removed.
    `extra` goes after the settled result and before the turn ends."""
    order: dict[str, Part] = {
        "started": started(),
        "turn_start": turn_start(),
        "call_start": call_start(),
        "answer": answer(),
        "call_finished": call_finished(),
        "usage": usage(),
        "final_result": final_result(),
        "extra": (),
        "turn_end": turn_end(),
        "checkpoint": checkpoint(251_164_000, 1),
        "idle": idle(),
    }
    unknown = set(parts) - set(order)
    assert not unknown, unknown
    order.update(parts)
    seen: list[Event] = []
    for part in order.values():
        if part is None:
            continue
        seen.extend([part] if isinstance(part, Mapping) else part)
    return seen


SDK_HAPPY = sdk_call()


# -- Names (Design 1). -------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        (MODEL, TARGET),
        ("copilot:gpt-6-luna", CopilotModel("copilot", "gpt-6-luna", None)),
        (
            "copilot-cli:gpt-6-luna@low",
            CopilotModel("copilot-cli", "gpt-6-luna", "low"),
        ),
        ("claude-opus-5-5", None),
        ("databricks-claude-opus-5", None),
        ("other:thing", None),
        ("openai/gpt-6-luna", None),
    ],
)
def test_a_copilot_name_is_its_platform_model_and_effort_and_any_other_is_an_endpoint(
    name: str, expected: CopilotModel | None
) -> None:
    assert parsed(name) == expected


@pytest.mark.parametrize(
    "name",
    [
        "copilot:",
        "copilot-cli:",
        "copilot:Claude-Opus",
        "copilot:gpt-6@turbo",
        "copilot:gpt-6@none",
        "copilot:gpt-6@high@low",
        "copilot:gpt 6",
        "copilot:-gpt",
        "copilot:gpt:6",
        "copilot:gpt-6\n",
        "Copilot:gpt-6",
        "COPILOT-CLI:gpt-6",
        "copilot:" + "a" * 129,
    ],
)
def test_a_name_that_claims_copilot_and_does_not_parse_is_refused(name: str) -> None:
    with pytest.raises(Refusal) as refused:
        parsed(name)
    assert refused.value.code is RefusalCode.PROVIDER_NOT_CONFIGURED


def test_the_longest_model_id_parses() -> None:
    longest = "a" * 128
    assert parsed("copilot:" + longest) == CopilotModel("copilot", longest, None)


# -- The witnesses (R1). -----------------------------------------------------


@pytest.mark.parametrize(
    ("output_tokens", "finish"),
    [(MAX_COMPLETION_TOKENS - 1, "stop"), (MAX_COMPLETION_TOKENS, "length")],
)
def test_without_a_usage_event_an_answer_at_the_output_cap_is_length(
    output_tokens: int, finish: str
) -> None:
    seen = sdk_call(usage=None, answer=answer(outputTokens=output_tokens))
    assert reply_message(seen, TARGET).response_metadata["finish_reason"] == finish


@pytest.mark.parametrize(
    ("data", "expected"),
    [
        ({"providerCallId": "p", "apiCallId": "a"}, "p"),
        ({"providerCallId": "", "apiCallId": "a"}, "a"),
        ({"providerCallId": None, "apiCallId": None}, None),
    ],
)
def test_the_call_id_is_the_usages_provider_or_api_call_id(
    data: dict[str, object], expected: str | None
) -> None:
    message = reply_message(sdk_call(usage=usage(**data)), TARGET)
    assert message.response_metadata.get("id") == expected


@pytest.mark.parametrize(
    ("data", "expected"),
    [
        ({"apiCallId": "a", "requestId": "r", "serviceRequestId": "s"}, "a"),
        ({"apiCallId": "", "requestId": "r", "serviceRequestId": "s"}, "r"),
        ({"apiCallId": None, "requestId": None, "serviceRequestId": "s"}, "s"),
        ({"apiCallId": None}, None),
    ],
)
def test_without_a_usage_the_call_id_is_the_messages_first_stated_id(
    data: dict[str, Any], expected: str | None
) -> None:
    seen = sdk_call(usage=None, answer=answer(**data))
    assert reply_message(seen, TARGET).response_metadata.get("id") == expected


# Half the session's AI units, so two of them are no more than its checkpoint.
half = usage(copilotUsage={"totalNanoAiu": 125_582_000, "model": PIN})


ADMITTED: dict[str, Event] = {
    "model-change-to-the-pin": model_change(PIN, previous="auto"),
    "no-mcp-server": mcp_loaded([]),
    "no-skill": skills_loaded([]),
    "no-extension": extensions_loaded([]),
    "no-custom-agent": agents_updated([]),
    "turn-retry": turn_retry(),
    "user-message": wire("user.message", content=PROMPT),
    "assistant-idle": wire("assistant.idle"),
    "title": wire("session.title_changed", title="t"),
}


@pytest.mark.parametrize("extra", list(ADMITTED.values()), ids=list(ADMITTED))
def test_an_allow_listed_event_leaves_the_finish_reason_stated(extra: Event) -> None:
    message = reply_message(sdk_call(extra=extra), TARGET)
    assert message.response_metadata["finish_reason"] == "stop"


def test_the_allow_list_and_the_refusing_names_are_disjoint_and_in_the_schema() -> None:
    schema = {kind.value for kind in SessionEventType}
    allowed = copilot_module._ALLOWED
    assert allowed <= schema, allowed - schema
    for kind in allowed:
        assert not kind.startswith(copilot_module._REFUSING), kind
    # Every refusing name or prefix names something the schema has.
    for prefix in copilot_module._REFUSING:
        assert any(kind.startswith(prefix) for kind in schema), prefix


@pytest.mark.parametrize(
    ("reported", "read"),
    [
        ("stop", "stop"),
        ("end_turn", "stop"),
        ("stop_sequence", "stop"),
        ("max_tokens", "length"),
        ("length", "length"),
        ("refusal", "content_filter"),
        ("tool_use", "tool_use"),
    ],
)
def test_a_finish_reason_is_read_in_the_provider_vocabulary(
    reported: str, read: str
) -> None:
    message = reply_message(sdk_call(usage=usage(finishReason=reported)), TARGET)
    assert message.response_metadata["finish_reason"] == read


@pytest.mark.parametrize(
    "event",
    [
        {"type": "assistant.usage", "data": "x"},
        {"type": 7, "data": {}},
        {"data": {}},
    ],
)
def test_an_event_not_in_wire_form_refuses_the_finish_reason(event: Event) -> None:
    message = reply_message([*SDK_HAPPY[:-1], event, SDK_HAPPY[-1]], TARGET)
    assert "finish_reason" not in message.response_metadata


@pytest.mark.parametrize(
    "changed",
    [
        {"inputTokens": None},
        {"outputTokens": None},
        {"cacheReadTokens": -1},
    ],
)
def test_a_count_not_stated_as_a_whole_number_is_no_usage(
    changed: dict[str, object],
) -> None:
    seen = sdk_call(usage=usage(**changed))
    assert reply_message(seen, TARGET).usage_metadata is None


# -- The charge (R2.3, R2.4, R2.9). ------------------------------------------


def test_the_largest_whole_ai_unit_count_is_charged_exactly() -> None:
    largest = 2**53 - 1
    message = AIMessage(content="answer", response_metadata={"nano_aiu": largest})
    expected = Decimal(largest) * Decimal("0.03") / Decimal(10**9)
    assert settled_charge(message, Decimal("0.03")) == expected


@pytest.mark.parametrize(
    ("nano_aiu", "credit"),
    [
        (None, CREDIT),
        ("251164000", CREDIT),
        (251_164_000.0, CREDIT),
        (True, CREDIT),
        (-1, CREDIT),
        (2**53, CREDIT),
        (251_164_000, None),
        (251_164_000, 0.01),
        (251_164_000, Decimal("0")),
        (251_164_000, Decimal("-0.01")),
        (251_164_000, Decimal("NaN")),
    ],
)
def test_a_charge_with_no_whole_ai_units_or_no_credit_price_is_unknown(
    nano_aiu: object, credit: object
) -> None:
    message = AIMessage(content="answer", response_metadata={"nano_aiu": nano_aiu})
    assert settled_charge(message, cast(Decimal, credit)) is None


def test_a_stated_zero_settles_at_zero() -> None:
    message = AIMessage(content="", response_metadata={"nano_aiu": 0})
    assert settled_charge(message, CREDIT) == Decimal(0)


# -- Spend on a failed call (R2.10) and the errors (R1). ---------------------


# -- ChatCopilot (the seam `ChatCompletions` calls). --------------------------


# -- The reservation in scope (R2.7's input; `caos.provider`). ---------------


def test_reserving_names_the_reservation_only_inside_its_block() -> None:
    assert reserved_amount.get() is None
    with reserving(Decimal("1.5")):
        assert reserved_amount.get() == Decimal("1.5")
        with reserving(Decimal("0.25")):
            assert reserved_amount.get() == Decimal("0.25")
        assert reserved_amount.get() == Decimal("1.5")
    assert reserved_amount.get() is None
    with pytest.raises(RuntimeError), reserving(Decimal(2)):
        raise RuntimeError
    assert reserved_amount.get() is None


@pytest.mark.parametrize(
    ("amount", "code"),
    [
        (1.5, RefusalCode.MONEY_NOT_DECIMAL),
        (Decimal(-1), RefusalCode.MONEY_INVALID),
        (Decimal("NaN"), RefusalCode.MONEY_INVALID),
    ],
)
def test_reserving_refuses_an_amount_that_is_no_spend(
    amount: object, code: RefusalCode
) -> None:
    with pytest.raises(Refusal) as refused, reserving(cast(Decimal, amount)):
        pytest.fail("entered")
    assert refused.value.code is code
    assert reserved_amount.get() is None


# -- What mutation testing found the suite did not pin. ----------------------

NO_EFFORT = CopilotModel("copilot", PIN, None)


@pytest.mark.parametrize("effort", [None, "", "none"])
def test_a_model_pinned_at_no_effort_takes_a_usage_stating_none(
    effort: str | None,
) -> None:
    message = reply_message(sdk_call(usage=usage(reasoningEffort=effort)), NO_EFFORT)
    assert message.response_metadata["finish_reason"] == "stop"


def test_every_usages_tokens_are_counted_and_an_absent_cache_count_is_zero() -> None:
    message = reply_message(sdk_call(usage=[half, half]), TARGET)
    assert message.usage_metadata == {
        "input_tokens": 2000,
        "output_tokens": 80,
        "total_tokens": 2080,
    }
    uncached = usage(cacheReadTokens=None, cacheWriteTokens=None)
    assert reply_message(sdk_call(usage=uncached), TARGET).usage_metadata == {
        "input_tokens": 900,
        "output_tokens": 40,
        "total_tokens": 940,
    }
    zero = usage(cacheReadTokens=0, cacheWriteTokens=0)
    assert reply_message(sdk_call(usage=zero), TARGET).usage_metadata == {
        "input_tokens": 900,
        "output_tokens": 40,
        "total_tokens": 940,
    }

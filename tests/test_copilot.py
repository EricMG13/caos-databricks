"""GitHub Copilot as the model behind the one factory (D77, addendum 2): the
names, the shared reply mapping against the SDK's own event schema (R1), the
AI-unit charge (R2.3, R2.4, R2.9) and spend on a failed call (R2.10).

Every fake event is built through `copilot.SessionEvent.from_dict(...).to_dict()`
(R5), so a field the pinned SDK does not know, or a value it cannot parse,
fails the fake and not the adapter.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from datetime import date
from decimal import Decimal
from typing import Any, cast
from uuid import uuid4

import pytest
from copilot import SessionEvent
from copilot.generated.session_events import SessionEventType
from langchain_core.messages import AIMessage, HumanMessage

from caos import copilot as copilot_module
from caos import models
from caos.copilot import (
    ChatCopilot,
    CopilotModel,
    CopilotStatusError,
    Event,
    parsed,
    reply_message,
    settled_charge,
)
from caos.models import ChatCompletions, completions
from caos.pricing import ModelPrice
from caos.provider import (
    MAX_COMPLETION_TOKENS,
    TIMEOUT_SECONDS,
    DropKind,
    reserved_amount,
    reserving,
)
from caos.refusals import Refusal, RefusalCode

PIN = "claude-opus-5.5"
OTHER = "claude-sonnet-5.5"
MODEL = f"copilot:{PIN}@high"
TARGET = CopilotModel("copilot", PIN, "high")
PRICE = ModelPrice(MODEL, Decimal("0.000005"), Decimal("0.00002"), date(2026, 10, 1))
PROMPT = "q" * 1000
# GitHub's published rate, one AI credit in US dollars (D77).
CREDIT = Decimal("0.01")
SECRET = "private text the runtime wrote"


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


def auto_resolved(
    chosen: str = PIN,
    available: Sequence[str] = (PIN, OTHER),
    routing: str = "classifier",
    fallback: bool = False,
) -> Event:
    return wire(
        "session.auto_mode_resolved",
        chosenModel=chosen,
        availableModels=list(available),
        routingMethod=routing,
        fallback=fallback,
    )


def error(status: int | None, error_type: str = "provider") -> Event:
    return wire(
        "session.error",
        errorType=error_type,
        message=SECRET,
        statusCode=status,
        stack=SECRET,
        url="https://example.invalid/" + SECRET.replace(" ", "-"),
    )


def failure(
    kind: str, status: int | None = None, bad_request_kind: str | None = None
) -> Event:
    return wire(
        "model.call_failure",
        source="top_level",
        failureKind=kind,
        statusCode=status,
        badRequestKind=bad_request_kind,
        errorMessage=SECRET,
        model=PIN,
    )


def truncation() -> Event:
    return wire(
        "session.truncation",
        messagesRemovedDuringTruncation=1,
        performedBy="runtime",
        postTruncationMessagesLength=1,
        postTruncationTokensInMessages=10,
        preTruncationMessagesLength=2,
        preTruncationTokensInMessages=20,
        tokenLimit=10,
        tokensRemovedDuringTruncation=10,
    )


def compaction_start() -> Event:
    return wire("session.compaction_start", model=PIN)


def limits_exhausted(used: float = 31.0, maximum: float = 30.0) -> Event:
    return wire(
        "session_limits_exhausted.requested",
        requestId="limits-1",
        usedAiCredits=used,
        maxAiCredits=maximum,
    )


def turn_retry(reason: str = "provider_error") -> Event:
    return wire("assistant.turn_retry", turnId="turn-1", model=PIN, reason=reason)


def model_change(new: str, previous: str = PIN) -> Event:
    return wire("session.model_change", newModel=new, previousModel=previous)


def server_tool_progress() -> Event:
    return wire(
        "assistant.server_tool_progress", kind="web_search", outputIndex=0, status="x"
    )


def tools_updated(model: str = PIN) -> Event:
    """`session.tools_updated` as 1.0.16 types it: the model, and no tool list."""
    return wire("session.tools_updated", model=model)


def mcp_loaded(servers: Sequence[Mapping[str, object]]) -> Event:
    return wire("session.mcp_servers_loaded", servers=list(servers))


def mcp_status(server: str) -> Event:
    return wire(
        "session.mcp_server_status_changed", serverName=server, status="connected"
    )


SKILL = {
    "description": "d",
    "enabled": True,
    "name": "skill",
    "source": "project",
    "userInvocable": True,
}
EXTENSION = {"id": "e", "name": "e", "source": "project", "status": "running"}
AGENT = {
    "description": "d",
    "displayName": "a",
    "id": "a",
    "name": "a",
    "source": "project",
    "tools": [],
    "userInvocable": True,
}


def skills_loaded(skills: Sequence[Mapping[str, object]]) -> Event:
    return wire("session.skills_loaded", skills=list(skills))


def extensions_loaded(extensions: Sequence[Mapping[str, object]]) -> Event:
    return wire("session.extensions_loaded", extensions=list(extensions))


def agents_updated(agents: Sequence[Mapping[str, object]]) -> Event:
    return wire(
        "session.custom_agents_updated", agents=list(agents), errors=[], warnings=[]
    )


def permission_requested() -> Event:
    return wire(
        "permission.requested",
        requestId="permission-1",
        permissionRequest={
            "kind": "url",
            "intention": "read",
            "url": "https://example.invalid",
        },
    )


def fusion(event: Event, **attribution: object) -> Event:
    """`event` with a fusion block: a synthetic multi-model turn."""
    block: dict[str, object] = {
        "fusionId": "fusion-1",
        "pattern": "advisor",
        "policy": "default",
        "syntheticModel": "fusion-model",
        **attribution,
    }
    return wire(event["type"], **{**event["data"], "fusion": block})


def unknown_event(kind: str = "session.future_thing") -> Event:
    return wire(kind, anything=1)


def sampling_requested() -> Event:
    return wire(
        "sampling.requested", mcpRequestId=1, requestId="sampling-1", serverName="s"
    )


def hook_start() -> Event:
    return wire("hook.start", hookInvocationId="hook-1", hookType="preToolUse")


def skill_invoked() -> Event:
    return wire("skill.invoked", content="x", name="skill", path="/skill")


def tool_search_activated() -> Event:
    return wire("tool_search.activated", strategy="bm25", toolNames=["bash"])


def external_tool_requested() -> Event:
    return wire(
        "external_tool.requested",
        requestId="external-1",
        sessionId="session-1",
        toolCallId="tool-1",
        toolName="bash",
    )


def run_started() -> Event:
    return wire("workflow.run_started", attempt=1, runId="run-1", workflowName="w")


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


# R5's sequences. HAPPY is either transport's (no `assistant.usage`, the CLI's
# shape); SDK_HAPPY adds the usage the SDK may deliver.
HAPPY = sdk_call(usage=None)
SDK_HAPPY = sdk_call()
RECOVERED = [
    started(),
    turn_start(),
    call_start(),
    failure("api", 503),
    turn_retry("provider_error"),
    call_start(),
    answer(),
    call_finished("success"),
    final_result(),
    turn_end(),
    checkpoint(300_000_000, 1),
    idle(),
]
SPENT_FAILURE = [
    started(),
    turn_start(),
    call_start(),
    failure("api", 500),
    checkpoint(100_000_000, 1),
    error(500),
]

Ask = Callable[[str, CopilotModel, float], Sequence[Event]]


def replying(*seen: Event) -> Ask:
    """An `ask` that answers every prompt with exactly these events."""

    def ask(prompt: str, target: CopilotModel, seconds: float) -> list[Event]:
        return list(seen)

    return ask


def provider(ask: Ask) -> ChatCompletions:
    """The production provider over `ChatCopilot` with a scripted transport."""
    return completions(PRICE, chat=ChatCopilot(model=MODEL, ask=ask), endpoint=MODEL)


def invoked(seen: Sequence[Event]) -> AIMessage:
    message = ChatCopilot(model=MODEL, ask=replying(*seen)).invoke(
        [HumanMessage(content=PROMPT)]
    )
    assert isinstance(message, AIMessage)
    return message


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


def test_one_exact_call_is_witnessed_by_message_final_result_and_capi_usage() -> None:
    message = reply_message(SDK_HAPPY, TARGET)
    assert message.content == "answer"
    assert message.response_metadata == {
        "id": "provider-call-1",
        "finish_reason": "stop",
        "nano_aiu": 251_164_000,
        "premium_requests": "1.0",
    }
    assert message.usage_metadata == {
        "input_tokens": 1000,
        "output_tokens": 40,
        "total_tokens": 1040,
    }


def test_a_finish_reason_is_derived_without_a_usage_event() -> None:
    message = reply_message(HAPPY, TARGET)
    assert message.content == "answer"
    assert message.response_metadata == {
        "id": "api-call-1",
        "finish_reason": "stop",
        "nano_aiu": 251_164_000,
        "premium_requests": "1.0",
    }
    assert message.usage_metadata is None


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
REFUSED: dict[str, list[Event]] = {
    "other-model-in-message": sdk_call(answer=answer(model=OTHER)),
    "message-names-no-model": sdk_call(answer=answer(model=None)),
    "other-model-in-final-result": sdk_call(final_result=final_result(model=OTHER)),
    "other-model-in-usage": sdk_call(usage=usage(model=OTHER)),
    "other-model-in-copilot-usage": sdk_call(
        usage=usage(copilotUsage={"totalNanoAiu": 251_164_000, "model": OTHER})
    ),
    "two-final-results": sdk_call(final_result=[final_result(), final_result()]),
    "no-final-result": sdk_call(final_result=None),
    "final-result-not-success": sdk_call(final_result=final_result(result="http_5xx")),
    "byok-unknown": sdk_call(final_result=final_result(isByok=None)),
    "byok-true": sdk_call(final_result=final_result(isByok=True)),
    "usage-byok-unknown": sdk_call(usage=usage(isByok=None)),
    "usage-byok-true": sdk_call(usage=usage(isByok=True)),
    "usage-auto": sdk_call(usage=usage(isAuto=True)),
    "fusion-on-message": sdk_call(answer=fusion(answer())),
    "fusion-on-usage": sdk_call(usage=fusion(usage())),
    "fusion-on-call-start": sdk_call(call_start=fusion(call_start())),
    "fusion-on-failure": sdk_call(
        call_start=[call_start(), fusion(failure("api", 503)), call_start()]
    ),
    "auto-resolved-even-naming-the-pin": sdk_call(extra=auto_resolved(PIN)),
    "model-change-other": sdk_call(extra=model_change(OTHER)),
    "server-tools-bare-provider": sdk_call(
        answer=answer(serverTools={"provider": "openai-responses"})
    ),
    "server-tools-advisor": sdk_call(
        answer=answer(serverTools={"provider": "anthropic", "advisorModel": OTHER})
    ),
    "tool-request": sdk_call(
        answer=answer(toolRequests=[{"name": "bash", "toolCallId": "tool-1"}])
    ),
    "tools-updated": sdk_call(extra=tools_updated()),
    "mcp-server-loaded": sdk_call(
        extra=mcp_loaded([{"name": "github-mcp-server", "status": "connected"}])
    ),
    "mcp-server-status": sdk_call(extra=mcp_status("github-mcp-server")),
    "skill-loaded": sdk_call(extra=skills_loaded([SKILL])),
    "extension-loaded": sdk_call(extra=extensions_loaded([EXTENSION])),
    "custom-agent-loaded": sdk_call(extra=agents_updated([AGENT])),
    "permission-requested": sdk_call(extra=permission_requested()),
    "unknown-event-type": sdk_call(extra=unknown_event()),
    "sampling-requested": sdk_call(extra=sampling_requested()),
    "hook-start": sdk_call(extra=hook_start()),
    "skill-invoked": sdk_call(extra=skill_invoked()),
    "tool-search-activated": sdk_call(extra=tool_search_activated()),
    "external-tool-requested": sdk_call(extra=external_tool_requested()),
    "workflow-run-started": sdk_call(extra=run_started()),
    "server-tool-progress": sdk_call(extra=server_tool_progress()),
    "truncated": sdk_call(extra=truncation()),
    "compacted": sdk_call(extra=compaction_start()),
    "limits-exhausted": sdk_call(extra=limits_exhausted()),
    "idle-aborted": sdk_call(idle=idle(aborted=True)),
    "no-idle": sdk_call(idle=None),
    "no-turn-end": sdk_call(turn_end=None),
    "no-answer": sdk_call(answer=None),
    "two-answers": sdk_call(answer=[answer(), answer()]),
    "usage-other-effort": sdk_call(usage=usage(reasoningEffort="low")),
    "usage-no-effort": sdk_call(usage=usage(reasoningEffort=None)),
    "usage-effort-none": sdk_call(usage=usage(reasoningEffort="none")),
    "usage-empty-finish-reason": sdk_call(usage=usage(finishReason="")),
    "usage-tools-offered": sdk_call(usage=usage(availableToolCount=3)),
    "usage-content-filter": sdk_call(usage=usage(contentFilterTriggered=True)),
    "usage-no-finish-reason": sdk_call(usage=usage(finishReason=None)),
    "two-usages": sdk_call(usage=[half, half]),
    "call-finished-error": sdk_call(call_finished=call_finished("error")),
    "failure-after-the-result": sdk_call(extra=failure("api", 503)),
    "session-error-beside-the-answer": sdk_call(extra=error(500)),
}


@pytest.mark.parametrize("seen", list(REFUSED.values()), ids=list(REFUSED))
def test_anything_but_the_call_asked_for_states_no_finish_reason_and_keeps_its_bill(
    seen: list[Event],
) -> None:
    message = reply_message(seen, TARGET)
    assert "finish_reason" not in message.response_metadata
    assert message.response_metadata["nano_aiu"] == 251_164_000


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


def test_a_failure_before_the_one_settled_result_is_the_runtimes_own_recovery() -> None:
    message = reply_message(RECOVERED, TARGET)
    assert message.response_metadata["finish_reason"] == "stop"
    assert message.response_metadata["nano_aiu"] == 300_000_000


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


def test_the_charge_is_the_checkpoints_ai_units_at_the_reservations_credit_price() -> (
    None
):
    message = reply_message(SDK_HAPPY, TARGET)
    charge = settled_charge(message, CREDIT)
    # 251,164,000 nano-AIU is 0.251164 credits; at $0.01 a credit, exactly.
    assert charge == Decimal("0.00251164")
    assert isinstance(charge, Decimal)


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


def test_zero_ai_units_on_an_answered_call_is_an_unknown_charge() -> None:
    seen = sdk_call(usage=None, checkpoint=checkpoint(0, 1))
    message = reply_message(seen, TARGET)
    assert "nano_aiu" not in message.response_metadata
    assert settled_charge(message, CREDIT) is None
    # One nano-AIU is a stated spend, and is billed.
    seen = sdk_call(usage=None, checkpoint=checkpoint(1, 1))
    assert reply_message(seen, TARGET).response_metadata["nano_aiu"] == 1


def test_a_stated_zero_settles_at_zero() -> None:
    message = AIMessage(content="", response_metadata={"nano_aiu": 0})
    assert settled_charge(message, CREDIT) == Decimal(0)


def test_zero_ai_units_on_an_unanswered_call_is_a_stated_zero() -> None:
    seen = sdk_call(answer=None, usage=None, checkpoint=checkpoint(0))
    assert reply_message(seen, TARGET).response_metadata["nano_aiu"] == 0


@pytest.mark.parametrize("nano_aiu", [251_164_000.5, 2.0**53, -1.0, float("inf")])
def test_a_checkpoint_that_is_not_a_whole_number_is_an_unknown_charge(
    nano_aiu: float,
) -> None:
    message = reply_message(sdk_call(checkpoint=checkpoint(nano_aiu, 1)), TARGET)
    assert "nano_aiu" not in message.response_metadata
    assert settled_charge(message, CREDIT) is None


def test_no_checkpoint_is_an_unknown_charge_even_with_token_counts() -> None:
    message = reply_message(sdk_call(checkpoint=None), TARGET)
    assert message.usage_metadata is not None
    assert "nano_aiu" not in message.response_metadata
    assert settled_charge(message, CREDIT) is None


def test_the_last_checkpoint_is_the_sessions_total() -> None:
    seen = sdk_call(
        call_start=[checkpoint(1_000), call_start()],
        checkpoint=[checkpoint(200_000_000), checkpoint(251_164_000)],
    )
    assert reply_message(seen, TARGET).response_metadata["nano_aiu"] == 251_164_000


def test_a_checkpoint_that_falls_is_no_running_total_and_an_unknown_charge() -> None:
    seen = sdk_call(checkpoint=[checkpoint(300_000_000), checkpoint(251_164_000)])
    assert "nano_aiu" not in reply_message(seen, TARGET).response_metadata


def test_a_checkpoint_before_the_answer_does_not_bill_it() -> None:
    seen = sdk_call(
        call_start=[call_start(), checkpoint(251_164_000)],
        checkpoint=None,
    )
    assert "nano_aiu" not in reply_message(seen, TARGET).response_metadata


def test_per_request_ai_units_above_the_checkpoint_are_unknown() -> None:
    over = usage(copilotUsage={"totalNanoAiu": 251_164_001, "model": PIN})
    message = reply_message(sdk_call(usage=over), TARGET)
    assert "nano_aiu" not in message.response_metadata
    at = usage(copilotUsage={"totalNanoAiu": 251_164_000, "model": PIN})
    assert reply_message(sdk_call(usage=at), TARGET).response_metadata["nano_aiu"] == (
        251_164_000
    )


@pytest.mark.parametrize(
    ("premium", "read"),
    [
        (1, "1.0"),
        (0.5, "0.5"),
        (0, "0.0"),
        (None, None),
        (-1.0, None),
        (float("nan"), None),
    ],
)
def test_premium_requests_are_read_as_a_decimal(
    premium: float | None, read: str | None
) -> None:
    message = reply_message(
        sdk_call(checkpoint=checkpoint(251_164_000, premium)), TARGET
    )
    assert message.response_metadata["premium_requests"] == read
    if read is not None:
        assert Decimal(read) == Decimal(str(premium))


# -- Spend on a failed call (R2.10) and the errors (R1). ---------------------


def test_a_runtime_recovered_answer_is_one_billed_call_never_raised() -> None:
    asked: list[str] = []

    def ask(prompt: str, target: CopilotModel, seconds: float) -> list[Event]:
        asked.append(prompt)
        return RECOVERED

    message = ChatCopilot(model=MODEL, ask=ask).invoke([HumanMessage(content=PROMPT)])
    assert isinstance(message, AIMessage)
    assert message.response_metadata["finish_reason"] == "stop"
    assert settled_charge(message, CREDIT) == Decimal("0.003")
    completion = provider(ask).complete(PROMPT)
    assert completion.drop_kind is None
    assert asked == [PROMPT, PROMPT]


@pytest.mark.parametrize("status", [500, 429])
def test_a_failed_call_with_spend_is_billed_and_refused_never_a_drop(
    status: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(models, "_sleep", lambda _seconds: None)
    seen = [*SPENT_FAILURE[:-1], error(status)]
    message = invoked(seen)
    assert message.response_metadata["nano_aiu"] == 100_000_000
    assert "finish_reason" not in message.response_metadata
    assert settled_charge(message, CREDIT) == Decimal("0.001")
    asked: list[str] = []

    def ask(prompt: str, target: CopilotModel, seconds: float) -> list[Event]:
        asked.append(prompt)
        return seen

    completion = provider(ask).complete(PROMPT)
    assert completion.refusal is RefusalCode.PROVIDER_RESPONSE_INVALID
    assert completion.drop_kind is None
    assert completion.content is None
    # Spent, so never re-sent: a 429 that carried spend is not asked again.
    assert asked == [PROMPT]


def test_an_answer_with_no_checkpoint_is_never_a_drop() -> None:
    seen = [started(), turn_start(), call_start(), answer(), error(503)]
    message = invoked(seen)
    assert "nano_aiu" not in message.response_metadata
    completion = provider(replying(*seen)).complete(PROMPT)
    assert (completion.refusal, completion.drop_kind) == (
        RefusalCode.PROVIDER_RESPONSE_INVALID,
        None,
    )


def test_a_checkpoint_whose_figure_is_unreadable_is_spend() -> None:
    unreadable: Event = {"type": "session.usage_checkpoint", "data": {}}
    seen = [started(), failure("api", 500), unreadable, error(500)]
    message = invoked(seen)
    assert "nano_aiu" not in message.response_metadata


UNSPENT = [started(), turn_start(), call_start()]


@pytest.mark.parametrize(
    ("ending", "status", "body"),
    [
        ([failure("api", 500), checkpoint(0), error(500)], 500, None),
        ([error(None)], None, None),
        ([failure("api", 503), error(None)], 503, None),
        ([failure("transport"), error(None)], None, None),
        ([failure("api", 400, "bodyless")], 400, None),
        ([failure("api", 400, "structured_error"), idle()], 400, None),
        ([failure("transport")], None, None),
        ([failure("transport"), final_result(result="http_5xx")], None, None),
        (
            [failure("api"), final_result(result="http_5xx")],
            None,
            {"error": {"result": "http_5xx"}},
        ),
        (
            [error(None), final_result(result="http_4xx")],
            None,
            {"error": {"result": "http_4xx"}},
        ),
        ([failure("api"), final_result(result="http_400")], 400, None),
        ([failure("api"), final_result(result="http_413")], 413, None),
        ([failure("api"), final_result(result="http_429")], 429, None),
        ([failure("api"), final_result(result="transport_error")], None, None),
        ([failure("api"), final_result(result="other_error")], None, None),
        (
            [final_result(result="http_5xx"), idle()],
            None,
            {"error": {"result": "http_5xx"}},
        ),
        ([checkpoint(0), error(502)], 502, None),
        ([failure("api", 503), error(429)], 429, None),
    ],
)
def test_a_failure_event_maps_to_its_status_class_and_declaration(
    ending: list[Event], status: int | None, body: object
) -> None:
    with pytest.raises(CopilotStatusError) as raised:
        invoked([*UNSPENT, *ending])
    assert raised.value.status_code == status
    assert raised.value.body == body
    assert SECRET not in str(raised.value)
    assert SECRET not in repr(raised.value.args)


@pytest.mark.parametrize(
    "ending",
    [[idle(aborted=True)], [failure("api", 500), idle(aborted=True), error(500)], []],
    ids=["aborted", "aborted-beside-an-error", "never-ended"],
)
def test_a_session_aborted_or_never_ended_is_indeterminate(ending: list[Event]) -> None:
    with pytest.raises(TimeoutError):
        invoked([*UNSPENT, *ending])


def test_a_session_that_idles_with_no_answer_and_no_spend_is_refused_not_raised() -> (
    None
):
    for ending in (
        [checkpoint(0), idle()],
        [final_result(), checkpoint(0), idle()],
        # A failure the settled result recovered from is no failure.
        [failure("api", 503), final_result(), checkpoint(0), idle()],
    ):
        message = invoked([*UNSPENT, *ending])
        assert message.content == ""
        assert "finish_reason" not in message.response_metadata


@pytest.mark.parametrize(
    ("ending", "code", "drop"),
    [
        ([error(500)], RefusalCode.PROVIDER_UNAVAILABLE, DropKind.DECLARED),
        ([error(400)], RefusalCode.PROVIDER_CALL_INVALID, DropKind.VENDOR),
        ([error(None)], RefusalCode.PROVIDER_UNAVAILABLE, DropKind.VENDOR),
        ([failure("transport")], RefusalCode.PROVIDER_UNAVAILABLE, DropKind.VENDOR),
        (
            [failure("api"), final_result(result="http_5xx")],
            RefusalCode.PROVIDER_UNAVAILABLE,
            DropKind.DECLARED,
        ),
        ([idle(aborted=True)], RefusalCode.PROVIDER_UNAVAILABLE, DropKind.RAISED),
    ],
)
def test_a_failed_call_with_no_spend_and_no_answer_is_a_drop_by_its_status(
    ending: list[Event], code: RefusalCode, drop: DropKind
) -> None:
    completion = provider(replying(*UNSPENT, *ending)).complete(PROMPT)
    assert (completion.content, completion.charge, completion.refusal) == (
        None,
        None,
        code,
    )
    assert completion.drop_kind is drop
    assert SECRET not in repr(completion)


def test_a_rate_limit_with_no_spend_is_asked_again_under_the_same_reservation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(models, "_sleep", lambda _seconds: None)
    answers = iter([[*UNSPENT, error(429)], SDK_HAPPY])
    calls: list[str] = []

    def ask(prompt: str, target: CopilotModel, seconds: float) -> Sequence[Event]:
        calls.append(prompt)
        return next(answers)

    completion = provider(ask).complete(PROMPT)
    assert completion.refusal is None
    assert calls == [PROMPT, PROMPT]


def test_a_status_error_carries_its_status_and_no_text() -> None:
    raised = CopilotStatusError(503)
    assert (raised.status_code, raised.body, str(raised)) == (503, None, "copilot")
    declared = CopilotStatusError(None, declared="http_5xx")
    assert declared.body == {"error": {"result": "http_5xx"}}
    # A declaration only stands for a failure with no status, and only as one
    # of the two declared results: anything else is undeclared.
    assert CopilotStatusError(500, declared="http_5xx").body is None
    assert CopilotStatusError(None, declared="transport_error").body is None
    assert models._declared(declared)
    assert not models._declared(CopilotStatusError(None))


# -- ChatCopilot (the seam `ChatCompletions` calls). --------------------------


def test_chat_copilot_asks_once_with_the_prompt_its_pinned_model_and_deadline() -> None:
    asked: list[tuple[str, CopilotModel, float]] = []

    def ask(prompt: str, target: CopilotModel, seconds: float) -> list[Event]:
        asked.append((prompt, target, seconds))
        return SDK_HAPPY

    message = ChatCopilot(model=MODEL, ask=ask).invoke([HumanMessage(content=PROMPT)])
    assert message.content == "answer"
    assert asked == [(PROMPT, TARGET, TIMEOUT_SECONDS)]


def test_through_the_factory_the_exact_call_completes_with_its_call_id() -> None:
    completion = provider(replying(*SDK_HAPPY)).complete(PROMPT, json_object=True)
    assert completion.refusal is None
    assert completion.content == "answer"
    assert completion.generation_id == "provider-call-1"


def test_a_call_that_was_not_the_one_asked_for_is_refused_and_never_a_drop() -> None:
    seen = REFUSED["other-model-in-final-result"]
    completion = provider(replying(*seen)).complete(PROMPT)
    assert completion.content is None
    assert completion.refusal is RefusalCode.PROVIDER_RESPONSE_INVALID
    assert completion.drop_kind is None


@pytest.mark.parametrize(
    ("model", "messages", "stop"),
    [
        ("databricks-claude-opus-5", [HumanMessage(content=PROMPT)], None),
        (MODEL, [HumanMessage(content=[{"type": "text", "text": PROMPT}])], None),
        (MODEL, [HumanMessage(content=PROMPT)], ["\n"]),
        (MODEL, [HumanMessage(content="first"), HumanMessage(content=PROMPT)], None),
    ],
    ids=["not-copilot", "not-text", "stop-sequence", "two-messages"],
)
def test_chat_copilot_refuses_a_call_it_cannot_send_as_asked(
    model: str, messages: list[HumanMessage], stop: list[str] | None
) -> None:
    asked: list[str] = []

    def ask(prompt: str, target: CopilotModel, seconds: float) -> list[Event]:
        asked.append(prompt)
        return SDK_HAPPY

    with pytest.raises(Refusal):
        ChatCopilot(model=model, ask=ask).invoke(messages, stop=stop)
    assert asked == []


def test_a_call_that_does_not_end_in_time_is_indeterminate() -> None:
    def ask(prompt: str, target: CopilotModel, seconds: float) -> list[Event]:
        raise TimeoutError

    completion = provider(ask).complete(PROMPT)
    assert completion.refusal is RefusalCode.PROVIDER_UNAVAILABLE
    assert completion.charge is None


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


def test_the_reservation_in_scope_reaches_the_call_on_its_own_thread() -> None:
    """`ChatCompletions` makes the call on a helper thread with a copy of the
    caller's context, so the transport sees the reservation it runs under."""
    seen: list[Decimal | None] = []

    def ask(prompt: str, target: CopilotModel, seconds: float) -> list[Event]:
        seen.append(reserved_amount.get())
        return SDK_HAPPY

    with reserving(Decimal("0.42")):
        provider(ask).complete(PROMPT)
    provider(ask).complete(PROMPT)
    assert seen == [Decimal("0.42"), None]


# -- What mutation testing found the suite did not pin. ----------------------

NO_EFFORT = CopilotModel("copilot", PIN, None)


@pytest.mark.parametrize("effort", [None, "", "none"])
def test_a_model_pinned_at_no_effort_takes_a_usage_stating_none(
    effort: str | None,
) -> None:
    message = reply_message(sdk_call(usage=usage(reasoningEffort=effort)), NO_EFFORT)
    assert message.response_metadata["finish_reason"] == "stop"


def test_equal_checkpoints_are_a_running_total() -> None:
    seen = sdk_call(checkpoint=[checkpoint(251_164_000), checkpoint(251_164_000)])
    assert reply_message(seen, TARGET).response_metadata["nano_aiu"] == 251_164_000


def test_a_settled_result_right_after_the_checkpoint_is_not_billed_by_it() -> None:
    seen = sdk_call(
        usage=None,
        final_result=[checkpoint(251_164_000), final_result()],
        checkpoint=None,
    )
    assert "nano_aiu" not in reply_message(seen, TARGET).response_metadata


@pytest.mark.parametrize(
    "usages",
    [
        # Each below the checkpoint, together above it.
        [
            usage(copilotUsage={"totalNanoAiu": 200_000_000, "model": PIN}),
            usage(copilotUsage={"totalNanoAiu": 200_000_000, "model": PIN}),
        ],
        # A usage with no per-request figure does not end the sum.
        [
            usage(copilotUsage=None),
            usage(copilotUsage={"totalNanoAiu": 251_164_001, "model": PIN}),
        ],
    ],
    ids=["summed", "after-a-usage-with-none"],
)
def test_every_per_request_figure_counts_against_the_checkpoint(
    usages: list[Event],
) -> None:
    assert (
        "nano_aiu"
        not in reply_message(sdk_call(usage=usages), TARGET).response_metadata
    )


def test_a_zero_per_request_figure_is_a_stated_count() -> None:
    zero = usage(copilotUsage={"totalNanoAiu": 0, "model": PIN})
    message = reply_message(sdk_call(usage=zero), TARGET)
    assert message.response_metadata["nano_aiu"] == 251_164_000


def _malformed(event: Event, **data: object) -> Event:
    """`event` with fields the SDK would never write: wire the host must read
    and refuse without raising, because a transport delivers dicts."""
    return {**event, "data": {**event["data"], **data}}


def test_a_per_request_figure_that_is_not_an_object_is_an_unknown_charge() -> None:
    seen = sdk_call(usage=_malformed(usage(), copilotUsage="x"))
    message = reply_message(seen, TARGET)
    assert "nano_aiu" not in message.response_metadata
    assert "finish_reason" not in message.response_metadata


def test_a_status_that_is_not_a_number_is_no_status() -> None:
    with pytest.raises(CopilotStatusError) as raised:
        invoked([*UNSPENT, _malformed(error(500), statusCode="500")])
    assert raised.value.status_code is None


def test_a_settled_result_that_is_not_a_name_declares_nothing() -> None:
    odd = _malformed(final_result(result="http_5xx"), result=["http_5xx"])
    with pytest.raises(CopilotStatusError) as raised:
        invoked([*UNSPENT, error(None), odd])
    assert (raised.value.status_code, raised.value.body) == (None, None)


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


def test_a_credit_price_too_precise_to_multiply_exactly_is_an_unknown_charge() -> None:
    """Within the ledger's envelope, but past the exact context's precision:
    refused rather than rounded (invariant 7)."""
    message = AIMessage(content="answer", response_metadata={"nano_aiu": 251_164_000})
    assert settled_charge(message, Decimal("0." + "1" * 1200)) is None


def test_a_checkpoint_stating_a_boolean_is_spend_and_an_unknown_charge() -> None:
    stated = _malformed(checkpoint(251_164_000, 1), totalNanoAiu=True)
    message = reply_message(sdk_call(checkpoint=stated), TARGET)
    assert "nano_aiu" not in message.response_metadata
    assert "nano_aiu" not in invoked([*UNSPENT, stated, error(500)]).response_metadata

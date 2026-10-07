"""GitHub Copilot as the model behind the one factory (D77, addendum 2): the
names, the shared reply mapping against the SDK's own event schema (R1), the
AI-unit charge (R2.3, R2.4, R2.9) and spend on a failed call (R2.10).

Every fake event is built through `copilot.SessionEvent.from_dict(...).to_dict()`
(R5), so a field the pinned SDK does not know, or a value it cannot parse,
fails the fake and not the adapter.
"""

from __future__ import annotations

import contextlib
import inspect
import io
import logging
import math
import os
import re
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, date, datetime, tzinfo
from decimal import Decimal
from fractions import Fraction
from pathlib import Path
from typing import Any, ClassVar, cast
from uuid import uuid4

import pytest
from copilot import (
    ModelCapabilitiesOverride,
    ModelLimitsOverride,
    SessionEvent,
    StdioRuntimeConnection,
)
from copilot.generated import session_events
from copilot.generated.rpc import PermissionDecisionReject
from copilot.generated.session_events import SessionEventType
from hypothesis import assume, given, settings
from hypothesis import strategies as st
from langchain_core.messages import AIMessage, HumanMessage

from caos import copilot as copilot_module
from caos import models
from caos.copilot import (
    CREDIT_PRICE_ENV,
    NANO_PER_CREDIT,
    PERMISSION_ASKED,
    RUNTIME_ENV,
    ChatCopilot,
    CopilotModel,
    CopilotStatusError,
    Event,
    ask_copilot,
    child_environment,
    credit_price,
    output_cap,
    parsed,
    reply_message,
    session_options,
    settled_charge,
)
from caos.methodology import canonical
from caos.models import ChatCompletions, completions
from caos.pricing import CreditPrice, ModelPrice
from caos.provider import (
    MAX_COMPLETION_TOKENS,
    TIMEOUT_SECONDS,
    DropKind,
    reserved_amount,
    reserved_credit,
    reserving,
)
from caos.refusals import Refusal, RefusalCode
from caos.store.budget import Reservation

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
    return enveloped(
        {
            "type": kind,
            "data": {key: value for key, value in data.items() if value is not None},
            "id": str(uuid4()),
            "timestamp": "2026-10-06T00:00:00Z",
        }
    )


def enveloped(event: Mapping[str, object], **envelope: object) -> Event:
    """`event` with these envelope fields (`agentId`, `parentId`), through the
    SDK. `from_dict` drops a key it does not know without a word, so every key
    sent must come back from `to_dict`: a fake can only say what the SDK says."""
    sent = {**event, **envelope}
    written: dict[str, object] = SessionEvent.from_dict(sent).to_dict()
    _survived(sent, written, "event")
    return written


def _survived(sent: object, written: object, where: str) -> None:
    """Every non-None key of `sent` is in `written`, at every depth."""
    if isinstance(sent, Mapping):
        assert isinstance(written, Mapping), where
        for key, value in sent.items():
            if value is None:
                continue
            assert key in written, f"{where}.{key} was dropped by the SDK"
            _survived(value, written[key], f"{where}.{key}")
    elif isinstance(sent, list):
        assert isinstance(written, list) and len(written) == len(sent), where
        for index, (item, kept) in enumerate(zip(sent, written, strict=True)):
            _survived(item, kept, f"{where}[{index}]")


def started(
    model: str | None = PIN, version: str = "1.0.90", effort: str | None = "high"
) -> Event:
    return wire(
        "session.start",
        copilotVersion=version,
        producer="copilot-agent",
        sessionId=str(uuid4()),
        startTime="2026-10-06T00:00:00Z",
        version=1,
        selectedModel=model,
        reasoningEffort=effort,
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


def model_change(new: str, previous: str = PIN, effort: str | None = "high") -> Event:
    return wire(
        "session.model_change",
        newModel=new,
        previousModel=previous,
        reasoningEffort=effort,
    )


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
# One logical dispatch that recovered inside itself: the SDK's
# `ModelCallFinishedData` is "the final lifecycle outcome for one logical model
# dispatch", which "may include internal reconnect or fallback work", and a
# `model.call_failure` is one attempt's telemetry (F573). So the retry opens no
# second dispatch, and the one dispatch closes on its `model.call_finished`.
RECOVERED = [
    started(),
    turn_start(),
    call_start(),
    failure("api", 503),
    turn_retry("provider_error"),
    answer(),
    call_finished("success"),
    final_result(),
    turn_end(),
    checkpoint(300_000_000, 1),
    idle(),
]
# The failed dispatch closes on its `model.call_finished` with outcome `error`
# (F573): R5's shape left it open, which no longer settles a checkpoint.
SPENT_FAILURE = [
    started(),
    turn_start(),
    call_start(),
    failure("api", 500),
    call_finished("error"),
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
        call_start=[call_start(), fusion(failure("api", 503))]
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
    assert message.response_metadata.get("nano_aiu") == _bill_kept(seen)


def _bill_kept(seen: list[Event]) -> int | None:
    """The bill a refused call keeps: its checkpoint, unless a sub-agent's work
    or a spend figure above the checkpoint voids it (F572). An oracle of its
    own, not the code under test."""
    if any(
        event.get("agentId") is not None
        or str(event["type"]).startswith(("subagent.", "workflow."))
        for event in seen
    ):
        return None
    if any(event["type"] == "session_limits_exhausted.requested" for event in seen):
        return None  # 31 credits used, above the checkpoint
    return 251_164_000


ADMITTED: dict[str, Event] = {
    "model-change-to-the-pin": model_change(PIN),
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


def test_zero_ai_units_on_a_call_that_did_no_work_is_a_stated_zero() -> None:
    seen = [*UNSPENT, failure("api", 500), checkpoint(0), error(500)]
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


# A session that started and opened no dispatch: an unclosed `model.call_start`
# is itself possible spend (F574).
UNSPENT = [started(), turn_start()]
# One dispatch that failed and closed: still no spend.
FAILED_DISPATCH = [call_start(), failure("api", 500), call_finished("error")]


# The body a runtime-declared 5xx with no status carries: its own result, and
# the provider error type D118's `_declares` reads as the provider's failure.
FIVE_XX = {
    "error": {"result": "http_5xx", "metadata": {"error_type": "provider_unavailable"}}
}


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
            FIVE_XX,
        ),
        # A 4xx however stated is never declared (D118, F566).
        ([error(None), final_result(result="http_4xx")], None, None),
        ([failure("api"), final_result(result="http_400")], 400, None),
        ([failure("api"), final_result(result="http_413")], 413, None),
        ([failure("api"), final_result(result="http_429")], 429, None),
        ([failure("api"), final_result(result="transport_error")], None, None),
        ([failure("api"), final_result(result="other_error")], None, None),
        (
            [final_result(result="http_5xx"), idle()],
            None,
            FIVE_XX,
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

    with reserving(Decimal("2.00"), credit=CREDIT):
        completion = provider(ask).complete(PROMPT)
    assert completion.refusal is None
    # Billed once, for the call that answered: the 429 spent nothing.
    assert completion.charge == Decimal("0.00251164")
    assert calls == [PROMPT, PROMPT]


def test_a_status_error_carries_its_status_and_no_text() -> None:
    raised = CopilotStatusError(503)
    assert (raised.status_code, raised.body, str(raised)) == (503, None, "copilot")
    declared = CopilotStatusError(None, declared="http_5xx")
    assert declared.body == FIVE_XX
    # A declaration only stands for a failure with no status, and only as a
    # 5xx: a 4xx is never declared (D118, F566), nor anything else.
    assert CopilotStatusError(500, declared="http_5xx").body is None
    assert CopilotStatusError(None, declared="http_4xx").body is None
    assert CopilotStatusError(None, declared="transport_error").body is None
    assert models._declared(declared)
    assert not models._declared(CopilotStatusError(None))
    assert not models._declared(CopilotStatusError(None, declared="http_4xx"))


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
    with reserving(Decimal("2.00"), credit=CREDIT):
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


def test_reserving_names_the_credit_price_beside_the_amount() -> None:
    assert reserved_credit.get() is None
    with reserving(Decimal("1.5"), credit=CREDIT):
        assert (reserved_amount.get(), reserved_credit.get()) == (
            Decimal("1.5"),
            CREDIT,
        )
        with reserving(Decimal("0.25")):
            assert (reserved_amount.get(), reserved_credit.get()) == (
                Decimal("0.25"),
                None,
            )
        assert reserved_credit.get() == CREDIT
    assert (reserved_amount.get(), reserved_credit.get()) == (None, None)
    for credit, code in (
        (0.01, RefusalCode.MONEY_NOT_DECIMAL),
        (Decimal(-1), RefusalCode.MONEY_INVALID),
        (Decimal("Infinity"), RefusalCode.MONEY_INVALID),
    ):
        with (
            pytest.raises(Refusal) as refused,
            reserving(Decimal(1), credit=cast(Decimal, credit)),
        ):
            pytest.fail("entered")
        assert refused.value.code is code
        assert (reserved_amount.get(), reserved_credit.get()) == (None, None)


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
    seen = sdk_call(started=started(effort=effort), usage=usage(reasoningEffort=effort))
    message = reply_message(seen, NO_EFFORT)
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


def test_a_settled_result_that_is_not_a_name_is_spend_never_a_drop() -> None:
    """F567: a settled result is quiet only when it names a failure."""
    odd = _malformed(final_result(result="http_5xx"), result=["http_5xx"])
    assert isinstance(invoked([*UNSPENT, error(None), odd]), AIMessage)


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


# -- Fix round 1: the adversarial audit's probes, as tests. ------------------


def shutdown(shutdown_type: str = "routine", **changed: object) -> Event:
    """`session.shutdown` naming only the pin, its totals equal to the bill."""
    data: dict[str, object] = {
        "codeChanges": {"filesModified": [], "linesAdded": 0, "linesRemoved": 0},
        "modelMetrics": {PIN: metric(251_164_000)},
        "sessionStartTime": 0,
        "shutdownType": shutdown_type,
        "totalApiDurationMs": 10,
        "totalNanoAiu": 251_164_000,
        "currentModel": PIN,
    }
    data.update(changed)
    return wire("session.shutdown", **data)


def metric(nano_aiu: int | None) -> dict[str, object]:
    return {
        "requests": {"count": 1, "cost": 1.0},
        "usage": {
            "cacheReadTokens": 0,
            "cacheWriteTokens": 0,
            "inputTokens": 10,
            "outputTokens": 10,
        },
        "totalNanoAiu": nano_aiu,
    }


def reasoning() -> Event:
    return wire("assistant.reasoning", content="r", reasoningId="reasoning-1")


def test_a_fake_carrying_a_key_the_sdk_does_not_know_fails() -> None:
    with pytest.raises(AssertionError, match="dropped by the SDK"):
        wire("session.idle", notAField=1)
    with pytest.raises(AssertionError, match="dropped by the SDK"):
        usage(copilotUsage={"totalNanoAiu": 1, "model": PIN, "notAField": 1})


# Item 1 (R2.10): a call showing any work or any spend is never a drop.
WORKED: dict[str, list[Event]] = {
    "per-request-units-no-checkpoint": [
        *UNSPENT,
        usage(copilotUsage={"totalNanoAiu": 500_000_000, "model": PIN}),
        failure("api", 500),
        error(500),
        idle(),
    ],
    "zero-checkpoint-before-the-spend": [
        *UNSPENT,
        checkpoint(0, 0),
        usage(copilotUsage={"totalNanoAiu": 500_000_000, "model": PIN}),
        failure("api", 500),
        error(500),
        idle(),
    ],
    "settled-success-zero-checkpoint": [
        *UNSPENT,
        call_finished("success"),
        final_result(),
        checkpoint(0, 0),
        error(503),
        idle(),
    ],
    "finished-dispatch-only": [*UNSPENT, call_finished("success"), error(503), idle()],
    "reasoning-only": [*UNSPENT, reasoning(), error(503), idle()],
    "shutdown-states-spend": [
        *UNSPENT,
        failure("api", 500),
        error(500),
        idle(),
        shutdown(modelMetrics={}, totalNanoAiu=1),
    ],
    "shutdown-metric-states-spend": [
        *UNSPENT,
        failure("api", 500),
        error(500),
        idle(),
        shutdown(totalNanoAiu=None, modelMetrics={PIN: metric(5)}),
    ],
    "model-worked-no-message-zero-checkpoint": sdk_call(
        answer=None, usage=usage(copilotUsage=None), checkpoint=checkpoint(0, 0)
    ),
}


@pytest.mark.parametrize("seen", list(WORKED.values()), ids=list(WORKED))
def test_a_call_showing_work_or_spend_is_never_a_drop_and_never_billed_zero(
    seen: list[Event],
) -> None:
    message = invoked(seen)
    assert "finish_reason" not in message.response_metadata
    assert "nano_aiu" not in message.response_metadata
    asked: list[str] = []

    def ask(prompt: str, target: CopilotModel, seconds: float) -> list[Event]:
        asked.append(prompt)
        return seen

    completion = provider(ask).complete(PROMPT)
    assert completion.drop_kind is None
    assert completion.refusal is RefusalCode.PROVIDER_RESPONSE_INVALID
    assert asked == [PROMPT]


# Items 2, 3 and 5: the bill is final only once the session settled after it.
UNSETTLED: dict[str, list[Event]] = {
    "idle-aborted": sdk_call(idle=idle(aborted=True)),
    "no-idle": sdk_call(idle=None),
    "dispatch-after-the-checkpoint": [
        *UNSPENT,
        failure("api", 503),
        checkpoint(100_000_000, 1),
        turn_retry("provider_error"),
        call_start(),
    ],
    "reasoning-after-the-checkpoint": sdk_call(usage=None, idle=[reasoning(), idle()]),
    "answer-after-idle": [
        *sdk_call(answer=None, idle=[idle(), answer()], checkpoint=None),
        checkpoint(251_164_000, 1),
    ],
}


@pytest.mark.parametrize("seen", list(UNSETTLED.values()), ids=list(UNSETTLED))
def test_a_session_that_did_not_settle_after_its_checkpoint_has_an_unknown_charge(
    seen: list[Event],
) -> None:
    message = reply_message(seen, TARGET)
    assert "finish_reason" not in message.response_metadata
    assert "nano_aiu" not in message.response_metadata


# F562: a shutdown states the session's figures too; any that disagrees with
# the checkpoint leaves the charge unknown.
DISAGREEING: dict[str, list[Event]] = {
    "shutdown-total-above-the-checkpoint": sdk_call(
        idle=[
            idle(),
            shutdown(
                totalNanoAiu=900_000_000,
                modelMetrics={PIN: metric(251_164_000), OTHER: metric(648_836_000)},
                currentModel=OTHER,
            ),
        ]
    ),
    "shutdown-total-below-the-checkpoint": sdk_call(
        idle=[idle(), shutdown(totalNanoAiu=1)]
    ),
    "shutdown-metrics-above-the-checkpoint": sdk_call(
        idle=[idle(), shutdown(modelMetrics={PIN: metric(251_164_001)})]
    ),
    "shutdown-metric-with-no-figure-then-one-above": sdk_call(
        idle=[
            idle(),
            shutdown(modelMetrics={OTHER: metric(None), PIN: metric(251_164_001)}),
        ]
    ),
    "shutdown-metrics-unreadable": sdk_call(
        idle=[idle(), _malformed(shutdown(), modelMetrics={PIN: "x"})]
    ),
    "shutdown-metrics-not-an-object": sdk_call(
        idle=[idle(), _malformed(shutdown(), modelMetrics="x")]
    ),
}


@pytest.mark.parametrize("seen", list(DISAGREEING.values()), ids=list(DISAGREEING))
def test_a_shutdown_figure_that_disagrees_with_the_checkpoint_is_an_unknown_charge(
    seen: list[Event],
) -> None:
    assert "nano_aiu" not in reply_message(seen, TARGET).response_metadata


@pytest.mark.parametrize(
    "shutdown_event",
    [
        _malformed(shutdown(modelMetrics={}, totalNanoAiu=None), modelMetrics="x"),
        _malformed(shutdown(modelMetrics={}, totalNanoAiu=None), modelMetrics={PIN: 7}),
    ],
    ids=["metrics-not-an-object", "metric-not-an-object"],
)
def test_an_unreadable_shutdown_figure_is_spend(shutdown_event: Event) -> None:
    seen = [*UNSPENT, failure("api", 500), error(500), idle(), shutdown_event]
    assert "finish_reason" not in invoked(seen).response_metadata


def test_a_shutdown_stating_zero_is_no_spend() -> None:
    zero = shutdown(modelMetrics={}, totalNanoAiu=0)
    with pytest.raises(CopilotStatusError):
        invoked([*UNSPENT, failure("api", 500), error(500), idle(), zero])


def test_a_dispatch_after_the_checkpoint_is_spend_never_a_drop() -> None:
    completion = provider(
        replying(*UNSETTLED["dispatch-after-the-checkpoint"])
    ).complete(PROMPT)
    assert (completion.charge, completion.drop_kind) == (None, None)


NO_USAGE_START = {
    "copilotVersion": "1.0.90",
    "producer": "copilot-agent",
    "sessionId": "session-1",
    "startTime": "2026-10-06T00:00:00Z",
    "version": 1,
    "selectedModel": PIN,
    "reasoningEffort": "high",
}
OTHER_DISPATCH = [started(), turn_start(), call_start(OTHER), call_finished("success")]

# Items 3 to 5: the model proof, each billed and refused (the bill kept).
REFUSED_ROUND_1: dict[str, list[Event]] = {
    "dispatch-to-another-model": sdk_call(started=OTHER_DISPATCH),
    "start-selects-another-model": sdk_call(started=started(model=OTHER)),
    "start-effort-other-no-usage": sdk_call(
        usage=None,
        started=wire("session.start", **{**NO_USAGE_START, "reasoningEffort": "low"}),
    ),
    "start-auto-tier-no-usage": sdk_call(
        usage=None,
        started=wire("session.start", **{**NO_USAGE_START, "autoTier": "balance"}),
    ),
    "start-effort-other-with-usage": sdk_call(
        started=wire("session.start", **{**NO_USAGE_START, "reasoningEffort": "low"})
    ),
    "no-start-no-usage": sdk_call(usage=None, started=None),
    "model-change-other-effort": sdk_call(
        usage=None,
        extra=wire(
            "session.model_change",
            newModel=PIN,
            previousModel=OTHER,
            reasoningEffort="low",
        ),
    ),
    "model-change-auto-tier": sdk_call(
        extra=wire(
            "session.model_change",
            newModel=PIN,
            previousModel=OTHER,
            reasoningEffort="high",
            autoTier="intelligence",
        ),
    ),
    "usage-num-tool-calls": sdk_call(usage=usage(numToolCalls=2)),
    "usage-tool-counts": sdk_call(usage=usage(toolCounts={"bash": 2})),
    "usage-parent-tool-call": sdk_call(usage=usage(parentToolCallId="tool-1")),
    "usage-initiator-sub-agent": sdk_call(usage=usage(initiator="sub-agent")),
    "turn-retry-another-model": sdk_call(
        extra=wire("assistant.turn_retry", turnId="t", model=OTHER, reason="fallback")
    ),
    "turn-start-another-model": sdk_call(
        turn_start=wire("assistant.turn_start", turnId="turn-1", model=OTHER)
    ),
    "turn-end-another-model": sdk_call(
        turn_end=wire("assistant.turn_end", turnId="turn-1", model=OTHER)
    ),
    "failure-on-another-model": sdk_call(
        call_start=[
            call_start(),
            wire(
                "model.call_failure",
                source="top_level",
                failureKind="api",
                statusCode=503,
                model=OTHER,
            ),
        ]
    ),
    "message-chunk-0-of-2": sdk_call(answer=answer(chunkCount=2, chunkIndex=0)),
    "message-chunk-1-of-1": sdk_call(answer=answer(chunkCount=1, chunkIndex=1)),
    "message-parent-tool-call": sdk_call(answer=answer(parentToolCallId="tool-1")),
    "message-from-a-sub-agent": sdk_call(answer=enveloped(answer(), agentId="agent-1")),
    "usage-from-a-sub-agent": sdk_call(usage=enveloped(usage(), agentId="agent-1")),
    "result-from-a-sub-agent": sdk_call(
        final_result=enveloped(final_result(), agentId="agent-1")
    ),
    "autopilot-continuation": sdk_call(
        started=[
            started(),
            wire("user.message", content=PROMPT),
            wire("user.message", content="other", isAutopilotContinuation=True),
        ]
    ),
    "lone-autopilot-continuation": sdk_call(
        started=[
            started(),
            wire("user.message", content=PROMPT, isAutopilotContinuation=True),
        ]
    ),
    "reasoning-right-after-the-turn-end": sdk_call(turn_end=[turn_end(), reasoning()]),
    "two-user-messages": sdk_call(
        started=[
            started(),
            wire("user.message", content=PROMPT),
            wire("user.message", content=PROMPT),
        ]
    ),
    "shutdown-error": sdk_call(idle=[idle(), shutdown("error")]),
    "shutdown-names-another-model": sdk_call(
        idle=[
            idle(),
            shutdown(
                modelMetrics={PIN: metric(251_164_000 - 1), OTHER: metric(1)},
            ),
        ]
    ),
    "shutdown-current-model-other": sdk_call(
        idle=[idle(), shutdown(currentModel=OTHER)]
    ),
}


@pytest.mark.parametrize(
    "seen", list(REFUSED_ROUND_1.values()), ids=list(REFUSED_ROUND_1)
)
def test_a_dispatch_turn_effort_or_tool_signal_off_the_pin_is_billed_and_refused(
    seen: list[Event],
) -> None:
    message = reply_message(seen, TARGET)
    assert "finish_reason" not in message.response_metadata
    assert message.response_metadata.get("nano_aiu") == _bill_kept(seen)


ADMITTED_ROUND_1: dict[str, list[Event]] = {
    "usage-witnesses-the-effort-with-no-start": sdk_call(started=None),
    "usage-initiator-user": sdk_call(usage=usage(initiator="user")),
    "message-chunk-0-of-1": sdk_call(answer=answer(chunkCount=1, chunkIndex=0)),
    "shutdown-routine-on-the-pin": sdk_call(idle=[idle(), shutdown()]),
    "shutdown-stating-no-total": sdk_call(
        idle=[idle(), shutdown(totalNanoAiu=None, modelMetrics={})]
    ),
    "model-change-to-the-pin-at-its-effort": sdk_call(
        usage=None,
        extra=wire(
            "session.model_change",
            newModel=PIN,
            previousModel=PIN,
            reasoningEffort="high",
        ),
    ),
    "turns-naming-no-model": sdk_call(
        turn_start=wire("assistant.turn_start", turnId="turn-1"),
        turn_end=wire("assistant.turn_end", turnId="turn-1"),
    ),
}


@pytest.mark.parametrize(
    "seen", list(ADMITTED_ROUND_1.values()), ids=list(ADMITTED_ROUND_1)
)
def test_a_call_that_names_only_the_pin_states_its_finish_and_bill(
    seen: list[Event],
) -> None:
    message = reply_message(seen, TARGET)
    assert message.response_metadata["finish_reason"] == "stop"
    assert message.response_metadata["nano_aiu"] == 251_164_000


# -- Properties (D121): the money arithmetic and the mapping's rules. --------

UNITS = st.integers(min_value=0, max_value=2**53 - 1)
CREDITS = st.decimals(
    min_value=Decimal("0.00000001"),
    max_value=Decimal(1000),
    places=8,
    allow_nan=False,
    allow_infinity=False,
)
INVALID_UNITS = st.one_of(
    st.integers(max_value=-1),
    st.integers(min_value=2**53),
    st.floats(),
    st.booleans(),
    st.none(),
    st.text(max_size=4),
)
INVALID_CREDITS = st.one_of(
    st.decimals(max_value=Decimal(0)),
    st.decimals(allow_nan=True).filter(lambda value: not value.is_finite()),
    st.just(Decimal("0." + "1" * 1200)),
    st.floats(),
    st.integers(),
    st.booleans(),
    st.none(),
)
EXAMPLES = settings(deadline=None, max_examples=200)


def charged(units: object, credit: object) -> Decimal | None:
    message = AIMessage(content="", response_metadata={"nano_aiu": units})
    return settled_charge(message, cast(Decimal, credit))


@EXAMPLES
@given(UNITS, CREDITS)
def test_property_the_charge_is_exactly_the_units_at_the_credit_price(
    units: int, credit: Decimal
) -> None:
    charge = charged(units, credit)
    assert isinstance(charge, Decimal)
    assert Fraction(charge) * NANO_PER_CREDIT == units * Fraction(credit)


@EXAMPLES
@given(UNITS, UNITS, CREDITS)
def test_property_the_charge_is_additive_in_the_units(
    first: int, second: int, credit: Decimal
) -> None:
    assume(first + second < 2**53)
    whole, part, rest = (
        charged(first + second, credit),
        charged(first, credit),
        charged(second, credit),
    )
    assert whole is not None and part is not None and rest is not None
    assert Fraction(whole) == Fraction(part) + Fraction(rest)


@EXAMPLES
@given(UNITS, UNITS, CREDITS, CREDITS)
def test_property_the_charge_never_falls_as_units_or_the_credit_price_rise(
    first: int, second: int, low: Decimal, high: Decimal
) -> None:
    less, more = sorted((first, second))
    cheap, dear = sorted((low, high))
    assert cast(Decimal, charged(less, cheap)) <= cast(Decimal, charged(more, cheap))
    assert cast(Decimal, charged(less, cheap)) <= cast(Decimal, charged(less, dear))


@EXAMPLES
@given(INVALID_UNITS, CREDITS)
def test_property_a_count_that_is_no_whole_figure_charges_nothing(
    units: object, credit: Decimal
) -> None:
    assert charged(units, credit) is None


@EXAMPLES
@given(UNITS, INVALID_CREDITS)
def test_property_a_credit_price_that_is_no_positive_decimal_charges_nothing(
    units: int, credit: object
) -> None:
    assert charged(units, credit) is None


@EXAMPLES
@given(
    st.one_of(
        st.floats(),
        st.integers(min_value=-(2**60), max_value=2**60).map(float),
    )
)
def test_property_a_checkpoint_bills_its_value_only_as_a_whole_count(
    value: float,
) -> None:
    seen = [*UNSPENT, failure("api", 500), checkpoint(value), error(500)]
    nano = reply_message(seen, TARGET).response_metadata.get("nano_aiu")
    if math.isfinite(value) and value.is_integer() and 0 <= value < 2**53:
        assert nano == int(value)
    else:
        assert nano is None
        assert copilot_module._spent(seen)


ALL_TYPES = sorted(kind.value for kind in SessionEventType)
UNSETTLING = sorted(set(ALL_TYPES) - copilot_module._SETTLING)


def raw(kind: str) -> Event:
    """Raw wire, not a fake: every type has its own required fields, and these
    properties are about the type alone, over every type the SDK knows."""
    return {"type": kind, "data": {}}


@EXAMPLES
@given(st.sampled_from(UNSETTLING), st.booleans())
def test_property_any_unsettling_type_after_the_last_checkpoint_voids_the_bill(
    kind: str, after_idle: bool
) -> None:
    late = raw(kind)
    seen = sdk_call(idle=[idle(), late] if after_idle else [late, idle()])
    message = reply_message(seen, TARGET)
    assert "nano_aiu" not in message.response_metadata
    # A late checkpoint becomes the last one (unreadable here, so no bill);
    # the end of the turn admits a checkpoint after it (R1.7).
    if kind != "session.usage_checkpoint":
        assert "finish_reason" not in message.response_metadata


@EXAMPLES
@given(UNITS.filter(bool), UNITS.filter(bool))
def test_property_checkpoints_bill_their_last_only_when_none_falls(
    first: int, second: int
) -> None:
    seen = sdk_call(usage=None, checkpoint=[checkpoint(first), checkpoint(second)])
    nano = reply_message(seen, TARGET).response_metadata.get("nano_aiu")
    assert nano == (second if second >= first else None)


@EXAMPLES
@given(
    st.lists(st.integers(min_value=0, max_value=10**9), min_size=1, max_size=3),
    st.integers(min_value=1, max_value=3 * 10**9),
)
def test_property_per_request_figures_bill_only_within_the_checkpoint(
    figures: list[int], total: int
) -> None:
    usages = [
        usage(copilotUsage={"totalNanoAiu": figure, "model": PIN}) for figure in figures
    ]
    seen = sdk_call(usage=usages, checkpoint=checkpoint(total))
    nano = reply_message(seen, TARGET).response_metadata.get("nano_aiu")
    assert nano == (total if sum(figures) <= total else None)


OUTSIDE = sorted(
    kind.value for kind in SessionEventType if kind.value not in copilot_module._ALLOWED
)


@EXAMPLES
@given(st.sampled_from(OUTSIDE), st.integers(min_value=0, max_value=len(SDK_HAPPY)))
def test_property_any_event_type_off_the_allow_list_refuses_its_finish(
    kind: str, at: int
) -> None:
    # Raw wire, not a fake: every type has its own required fields, and the
    # property is about the type alone.
    seen = [*SDK_HAPPY[:at], raw(kind), *SDK_HAPPY[at:]]
    message = reply_message(seen, TARGET)
    assert "finish_reason" not in message.response_metadata
    settled_at = len(SDK_HAPPY) - 2  # the checkpoint, before the idle
    if at <= settled_at and not kind.startswith(("subagent.", "workflow.")):
        assert message.response_metadata["nano_aiu"] == 251_164_000
    else:
        assert "nano_aiu" not in message.response_metadata


POOL = [
    started(),
    started(model=OTHER),
    turn_start(),
    call_start(),
    call_start(OTHER),
    answer(),
    call_finished("success"),
    call_finished("error"),
    usage(),
    final_result(),
    final_result(result="http_5xx"),
    final_result(result="http_429"),
    turn_end(),
    turn_retry(),
    reasoning(),
    checkpoint(0),
    checkpoint(5, 1),
    idle(),
    idle(aborted=True),
    error(500),
    error(429),
    error(None),
    failure("api", 500),
    failure("api", 400, "bodyless"),
    failure("transport"),
    truncation(),
    auto_resolved(),
    tools_updated(),
    shutdown(),
    shutdown("error"),
    unknown_event(),
]
SPEND = [
    answer(),
    checkpoint(251_164_000, 1),
    checkpoint(1.5),
    checkpoint(float("nan")),
]


@EXAMPLES
@given(
    st.lists(st.sampled_from(POOL), max_size=12),
    st.sampled_from(SPEND),
    st.integers(min_value=0, max_value=12),
)
def test_property_a_call_holding_an_answer_or_spend_is_never_raised(
    events: list[Event], spend: Event, at: int
) -> None:
    seen = [*events[:at], spend, *events[at:]]
    assert isinstance(invoked(seen), AIMessage)


def test_a_credit_price_too_precise_for_any_count_charges_not_even_zero() -> None:
    """F564, found by the property above: a price that cannot charge the
    largest count exactly prices no count, zero included."""
    precise = Decimal("0." + "1" * 1200)
    assert charged(0, precise) is None
    # The most digits a price may carry still charges the largest count.
    widest = Decimal("0." + "1" * (1000 - len(str(2**53))))
    assert charged(2**53 - 1, widest) is not None
    too_wide = Decimal("0." + "1" * (1001 - len(str(2**53))))
    assert charged(2**53 - 1, too_wide) is None
    assert charged(0, too_wide) is None


@pytest.mark.parametrize("figure", [float("inf"), float("nan"), -1.0])
def test_a_per_request_or_per_model_figure_that_is_no_count_is_an_unknown_charge(
    figure: float,
) -> None:
    capi = usage(copilotUsage={"totalNanoAiu": figure, "model": PIN})
    assert (
        "nano_aiu" not in reply_message(sdk_call(usage=capi), TARGET).response_metadata
    )
    metered = shutdown(totalNanoAiu=None, modelMetrics={PIN: metric(None)})
    odd = _malformed(
        metered, modelMetrics={PIN: {**metric(None), "totalNanoAiu": figure}}
    )
    seen = sdk_call(idle=[idle(), odd])
    assert "nano_aiu" not in reply_message(seen, TARGET).response_metadata


NOT_QUIET = sorted(set(ALL_TYPES) - copilot_module._QUIET)


@EXAMPLES
@given(
    st.sampled_from(NOT_QUIET),
    st.integers(min_value=0, max_value=len(UNSPENT)),
    st.sampled_from([[error(500)], [failure("api", 500), error(500), idle()]]),
)
def test_property_any_type_off_the_quiet_list_is_spend_never_a_drop(
    kind: str, at: int, ending: list[Event]
) -> None:
    seen = [*UNSPENT[:at], raw(kind), *UNSPENT[at:], *ending]
    assert isinstance(invoked(seen), AIMessage)
    assert copilot_module._spent(seen)


# Quiet parts: a dispatch is quiet only as a closed, failed one (F574).
QUIET_FAKES: list[list[Event]] = [
    [started()],
    [wire("user.message", content=PROMPT)],
    [turn_start()],
    [turn_end()],
    FAILED_DISPATCH,
    [call_start(), failure("transport"), call_finished("error")],
    [call_start(), call_finished("error")],
    [failure("api", 500)],
    [final_result(result="http_5xx")],
    [checkpoint(0)],
    [checkpoint(0, 0)],
    [error(500)],
    [idle()],
    [wire("session.info", infoType="x", message="m")],
    [wire("session.warning", warningType="x", message="m")],
    [shutdown(modelMetrics={}, totalNanoAiu=0)],
    [shutdown(modelMetrics={}, totalNanoAiu=None, totalPremiumRequests=0)],
]


def test_every_quiet_type_has_a_quiet_fake() -> None:
    conditional = {
        "model.call_final_result",
        "model.call_finished",
        "model.call_failure",
        "session.usage_checkpoint",
        "session.shutdown",
    }
    faked = {event["type"] for part in QUIET_FAKES for event in part}
    assert copilot_module._QUIET | conditional <= faked | {
        "session.managed_settings_resolved",
        "session.managed_settings_enforced",
    }


@EXAMPLES
@given(st.lists(st.sampled_from(QUIET_FAKES), max_size=12))
def test_property_a_call_of_quiet_events_alone_spent_nothing(
    parts: list[list[Event]],
) -> None:
    assert not copilot_module._spent([event for part in parts for event in part])


# -- Fix round 2: the re-audit's probes, as tests. ---------------------------


def message_delta() -> Event:
    return wire("assistant.message_delta", deltaContent="partial", messageId="m1")


def reasoning_delta() -> Event:
    return wire("assistant.reasoning_delta", deltaContent="think", reasoningId="r1")


def fusion_completed(nano_aiu: int) -> Event:
    return wire(
        "session.fusion_completed",
        cachedTokens=0,
        commitId="c",
        durationMs=1.0,
        finalSourceModel=OTHER,
        followUpModel=OTHER,
        fusionId="f",
        inputTokens=10,
        outcome="success",
        outputTokens=10,
        pattern="single",
        phaseCount=1,
        requestCount=2,
        syntheticModel="fusion-model",
        totalNanoAiu=nano_aiu,
        turnId="turn-1",
    )


def run_settled(nano_aiu: int) -> Event:
    return wire(
        "workflow.run_settled",
        consumedNanoAiu=nano_aiu,
        consumedSubagents=1,
        elapsedMs=5,
        runId="r",
        status="completed",
    )


def compaction_complete() -> Event:
    return wire(
        "session.compaction_complete",
        success=True,
        compactionTokensUsed={
            "inputTokens": 1000,
            "outputTokens": 200,
            "cacheReadTokens": 0,
            "cacheWriteTokens": 0,
            "model": PIN,
            "copilotUsage": {"totalNanoAiu": 400_000_000, "model": PIN},
        },
    )


def subagent_completed() -> Event:
    return wire(
        "subagent.completed",
        agentDisplayName="a",
        agentName="a",
        toolCallId="t",
        model=OTHER,
        totalTokens=5000,
    )


def agent_metrics(model: str, nano_aiu: int) -> dict[str, object]:
    return {
        "sub": {
            "modelMetrics": {model: metric(nano_aiu)},
            "totalApiDurationMs": 1,
            "totalNanoAiu": nano_aiu,
        }
    }


def switch_eligible_error() -> Event:
    return wire(
        "session.error",
        errorType="provider",
        message=SECRET,
        statusCode=500,
        eligibleForAutoSwitch=True,
    )


def switch_requested() -> Event:
    return wire("auto_mode_switch.requested", requestId="s1", errorCode="x")


def cache_break(**changed: object) -> Event:
    return wire(
        "prompt_cache_break",
        contributingReasons=["model"],
        frontierTokens=1,
        primaryReason="model_change",
        retentionRatio=0.0,
        shortfallTokens=1,
        survivedTokens=0,
        **changed,
    )


def failure_with(**changed: object) -> Event:
    data: dict[str, object] = {
        "source": "top_level",
        "failureKind": "api",
        "statusCode": 503,
        "model": PIN,
    }
    data.update(changed)
    return wire("model.call_failure", **data)


def recovered_from(failed: Event) -> list[Event]:
    return [*RECOVERED[:3], failed, *RECOVERED[4:]]


UNSEEN_SPEND: dict[str, Event] = {
    "message-delta": message_delta(),
    "reasoning-delta": reasoning_delta(),
    "fusion-completed": fusion_completed(500_000_000),
    "run-settled": run_settled(500_000_000),
    "compaction-complete": compaction_complete(),
    "subagent-completed": subagent_completed(),
}


@pytest.mark.parametrize("spend", list(UNSEEN_SPEND.values()), ids=list(UNSEEN_SPEND))
def test_an_event_off_the_quiet_list_makes_a_failed_call_spend_never_a_drop(
    spend: Event,
) -> None:
    seen = [*UNSPENT, spend, failure("api", 500), error(500), idle()]
    assert isinstance(invoked(seen), AIMessage)
    completion = provider(replying(*seen)).complete(PROMPT)
    assert (completion.drop_kind, completion.charge) == (None, None)


def test_a_shutdown_reporting_a_sub_agents_spend_is_never_a_drop() -> None:
    sub = shutdown(
        "error", modelMetrics={}, totalNanoAiu=0, agentMetrics=agent_metrics(PIN, 5)
    )
    seen = [*UNSPENT, failure("api", 500), error(500), idle(), sub]
    assert isinstance(invoked(seen), AIMessage)


LATE: dict[str, list[Event]] = {
    "message-delta": [message_delta()],
    "fusion-completed": [fusion_completed(900_000_000)],
    "run-settled": [run_settled(900_000_000)],
    "compaction": [compaction_start(), compaction_complete()],
    "subagent-completed": [subagent_completed()],
}


@pytest.mark.parametrize("late", list(LATE.values()), ids=list(LATE))
def test_work_the_old_deny_list_missed_after_the_checkpoint_voids_the_bill(
    late: list[Event],
) -> None:
    message = reply_message(sdk_call(idle=[*late, idle()]), TARGET)
    assert "nano_aiu" not in message.response_metadata


OPEN: dict[str, list[Event]] = {
    "dispatch-open-then-error": [
        *UNSPENT,
        call_start(),
        checkpoint(100_000_000, 1),
        error(500),
    ],
    "dispatch-open-then-idle": [
        *UNSPENT,
        call_start(),
        checkpoint(100_000_000, 1),
        idle(),
    ],
    "switch-eligible-error": [
        *UNSPENT,
        failure("api", 500),
        checkpoint(100_000_000, 1),
        switch_eligible_error(),
    ],
    "switch-eligible-error-then-switch": [
        *UNSPENT,
        failure("api", 500),
        checkpoint(100_000_000, 1),
        switch_eligible_error(),
        switch_requested(),
    ],
}


@pytest.mark.parametrize("seen", list(OPEN.values()), ids=list(OPEN))
def test_an_open_dispatch_or_a_pending_model_switch_voids_the_bill(
    seen: list[Event],
) -> None:
    assert "nano_aiu" not in reply_message(seen, TARGET).response_metadata
    completion = provider(replying(*seen)).complete(PROMPT)
    assert (completion.drop_kind, completion.charge) == (None, None)


FIELDS: dict[str, list[Event]] = {
    "cache-break-to-another-model": sdk_call(
        extra=cache_break(modelFrom=PIN, modelTo=OTHER)
    ),
    "cache-break-adding-tools": sdk_call(extra=cache_break(toolsAdded=["bash"])),
    "cache-break-for-an-agent": sdk_call(extra=cache_break(agentName="sub")),
    "recovered-failure-auto": recovered_from(failure_with(isAuto=True)),
    "recovered-failure-other-effort": recovered_from(
        failure_with(reasoningEffort="low")
    ),
    "recovered-failure-sub-agent-initiator": recovered_from(
        failure_with(initiator="sub-agent")
    ),
    "recovered-failure-tool-child": recovered_from(
        failure_with(parentToolCallId="tool-1")
    ),
    "dispatch-tool-child": sdk_call(
        call_start=wire(
            "model.call_start", turnId="turn-1", model=PIN, parentToolCallId="tool-1"
        )
    ),
    "turn-tool-child": sdk_call(
        turn_start=wire(
            "assistant.turn_start", turnId="turn-1", model=PIN, parentToolCallId="t"
        )
    ),
    "dispatch-by-a-sub-agent": sdk_call(
        call_start=enveloped(call_start(), agentId="agent-1")
    ),
    "idle-by-a-sub-agent": sdk_call(idle=enveloped(idle(), agentId="agent-1")),
    "prompt-for-an-agent-task": sdk_call(
        extra=wire("user.message", content=PROMPT, parentAgentTaskId="task-1")
    ),
    "prompt-in-autopilot-mode": sdk_call(
        extra=wire("user.message", content=PROMPT, agentMode="autopilot")
    ),
    "shutdown-sub-agent-on-another-model": sdk_call(
        idle=[idle(), shutdown(agentMetrics=agent_metrics(OTHER, 1))]
    ),
    "shutdown-sub-agent-on-the-pin": sdk_call(
        idle=[idle(), shutdown(agentMetrics=agent_metrics(PIN, 1))]
    ),
    "usage-token-detail-on-another-model": sdk_call(
        usage=usage(
            copilotUsage={
                "totalNanoAiu": 251_164_000,
                "model": PIN,
                "tokenDetails": [
                    {
                        "batchSize": 1,
                        "costPerBatch": 1.0,
                        "tokenCount": 1,
                        "tokenType": "input",
                        "model": OTHER,
                    }
                ],
            }
        )
    ),
}


@pytest.mark.parametrize("seen", list(FIELDS.values()), ids=list(FIELDS))
def test_any_field_naming_another_model_effort_agent_or_tool_refuses(
    seen: list[Event],
) -> None:
    message = reply_message(seen, TARGET)
    assert "finish_reason" not in message.response_metadata


SECOND_TURN: dict[str, list[Event]] = {
    "two-turn-ends": sdk_call(turn_end=[turn_end(), turn_end()]),
    "a-turn-before-the-turn": sdk_call(
        started=[started(), turn_start(), turn_end()],
    ),
    "a-second-turn-start": sdk_call(turn_start=[turn_start(), turn_start()]),
    "no-turn-start": sdk_call(turn_start=None),
}


@pytest.mark.parametrize("seen", list(SECOND_TURN.values()), ids=list(SECOND_TURN))
def test_one_prompt_is_one_turn(seen: list[Event]) -> None:
    """F570, found by the after-the-checkpoint property: a second turn is a
    second inference round, whichever side of the bill it falls on."""
    message = reply_message(seen, TARGET)
    assert "finish_reason" not in message.response_metadata
    assert message.response_metadata["nano_aiu"] == 251_164_000


FIELDS_ADMITTED: dict[str, list[Event]] = {
    "cache-break-from-the-pin-to-the-pin": sdk_call(
        extra=cache_break(modelFrom=PIN, modelTo=PIN)
    ),
    "prompt-in-interactive-mode": sdk_call(
        extra=wire("user.message", content=PROMPT, agentMode="interactive")
    ),
    "model-change-from-the-pin": sdk_call(extra=model_change(PIN, previous=PIN)),
    "model-change-by-this-host": sdk_call(
        extra=wire(
            "session.model_change", newModel=PIN, reasoningEffort="high", source="sdk"
        )
    ),
}


@pytest.mark.parametrize(
    "seen", list(FIELDS_ADMITTED.values()), ids=list(FIELDS_ADMITTED)
)
def test_a_field_naming_only_the_pin_is_admitted(
    seen: list[Event],
) -> None:
    assert reply_message(seen, TARGET).response_metadata["finish_reason"] == "stop"


# What the round-2 mutation run found the suite did not pin.

NAMED_FIELDS = [
    ("model", OTHER, False),
    ("modelId", OTHER, False),
    ("modelTo", OTHER, False),
    ("behaviorModelId", OTHER, False),
    ("chosenModel", OTHER, False),
    ("chosenModel", PIN, True),
    ("previousModel", OTHER, False),
    ("previousModel", PIN, True),
    ("modelFrom", OTHER, False),
    ("modelFrom", PIN, True),
    ("models", [PIN, OTHER], False),
    ("models", [PIN], True),
    ("candidateModels", [OTHER], False),
    ("effort", "low", False),
    ("effort", "high", True),
    ("initialEffort", "low", False),
    ("previousReasoningEffort", "low", False),
    ("previousReasoningEffort", "high", True),
    ("isAuto", True, False),
    ("autoTier", "balance", False),
    ("effectiveAutoTier", "fast", False),
    ("previousAutoTier", "fast", False),
    ("agentId", "a", False),
    ("interruptedAgentCount", 1, False),
    ("consumedSubagents", 1, False),
    ("consumedSubagents", 0, True),
    ("agentMode", "plan", False),
    ("agentMode", "interactive", True),
    ("initiator", "agent", False),
    ("initiator", "user", True),
    ("toolsAdded", ["bash"], False),
    ("finalTool", "bash", False),
    ("toolDefinitionsTokens", 0, True),
    ("contextTier", "long_context", True),
]


@pytest.mark.parametrize(("key", "value", "agrees"), NAMED_FIELDS)
def test_a_field_is_held_by_the_family_its_name_puts_it_in(
    key: str, value: object, agrees: bool
) -> None:
    """F569: each family's rule, at the top and nested at any depth."""
    assert copilot_module._fields_agree({key: value}, TARGET) is agrees
    assert copilot_module._fields_agree({"outer": [{key: value}]}, TARGET) is agrees


UNSTATED: dict[str, list[Event]] = {
    "start-states-no-effort": sdk_call(started=started(effort=None)),
    "model-change-states-no-effort": sdk_call(extra=model_change(PIN, effort=None)),
}


@pytest.mark.parametrize("seen", list(UNSTATED.values()), ids=list(UNSTATED))
def test_an_effort_left_unstated_by_the_session_refuses(seen: list[Event]) -> None:
    """F561: the start and every model change state the pinned effort; leaving
    it out is no statement of it, whatever the usage says."""
    assert "finish_reason" not in reply_message(seen, TARGET).response_metadata


def test_a_fusion_block_refuses_even_naming_the_pin() -> None:
    seen = sdk_call(answer=fusion(answer(), syntheticModel=PIN))
    assert "finish_reason" not in reply_message(seen, TARGET).response_metadata


def test_two_dispatches_with_one_closed_leave_one_open() -> None:
    seen = sdk_call(call_start=[call_start(), call_start()])
    assert "nano_aiu" not in reply_message(seen, TARGET).response_metadata


def test_a_sub_agents_metered_spend_leaves_the_charge_unknown() -> None:
    seen = sdk_call(idle=[idle(), shutdown(agentMetrics=agent_metrics(PIN, 1))])
    assert "nano_aiu" not in reply_message(seen, TARGET).response_metadata


@pytest.mark.parametrize("kind", ["session.idle", "session.start", "user.message"])
def test_a_quiet_type_with_unreadable_data_is_spend(kind: str) -> None:
    unreadable: Event = {"type": kind, "data": "x"}
    seen = [*UNSPENT, unreadable, failure("api", 500), error(500)]
    assert isinstance(invoked(seen), AIMessage)


@pytest.mark.parametrize(
    "event", [{"type": 7, "data": {}}, {"type": "session.info", "data": "x"}]
)
def test_an_event_not_in_wire_form_before_the_turn_refuses(event: Event) -> None:
    seen = [SDK_HAPPY[0], event, *SDK_HAPPY[1:]]
    assert "finish_reason" not in reply_message(seen, TARGET).response_metadata


# -- Fix round 3: the re-audit's probes, as tests. ---------------------------


def run_completed_notice(nano_aiu: int) -> Event:
    return wire(
        "system.notification",
        content="c",
        kind={
            "type": "workflow_completed",
            "attempt": 1,
            "consumedNanoAiu": nano_aiu,
            "consumedSubagents": 2,
            "elapsedMs": 1,
            "runId": "r",
            "status": "completed",
            "workflowName": "w",
        },
    )


def phase_completed(nano_aiu: int) -> Event:
    return wire(
        "assistant.fusion_phase_completed",
        content="c",
        conversationScope="root",
        durationMs=1.0,
        fusionId="f",
        model=PIN,
        phaseId="p",
        phaseKind="primary",
        role="r",
        status="succeeded",
        verdict="v",
        usage={
            "cachedTokens": 0,
            "inputTokens": 1,
            "outputTokens": 1,
            "requestCount": 1,
            "totalNanoAiu": nano_aiu,
        },
    )


def compaction_complete_at(nano_aiu: int) -> Event:
    event = compaction_complete()
    usage_block = {**event["data"]["compactionTokensUsed"]}
    usage_block["copilotUsage"] = {"totalNanoAiu": nano_aiu, "model": PIN}
    return wire(event["type"], **{**event["data"], "compactionTokensUsed": usage_block})


# Item 1 (F572): a spend figure stated anywhere above the bill leaves it unknown.
ABOVE: dict[str, Event] = {
    "fusion-completed": fusion_completed(900_000_000),
    "fusion-phase-usage": phase_completed(900_000_000),
    "compaction-copilot-usage": compaction_complete_at(900_000_000),
    "limits-exhausted-credits": limits_exhausted(31.0, 30.0),
}


@pytest.mark.parametrize("figure", list(ABOVE.values()), ids=list(ABOVE))
def test_a_spend_figure_above_the_checkpoint_anywhere_leaves_the_charge_unknown(
    figure: Event,
) -> None:
    assert (
        "nano_aiu"
        not in reply_message(sdk_call(extra=figure), TARGET).response_metadata
    )


WITHIN: dict[str, Event] = {
    "fusion-completed": fusion_completed(100_000_000),
    "limits-exhausted-credits": limits_exhausted(0.1, 30.0),
}


@pytest.mark.parametrize("figure", list(WITHIN.values()), ids=list(WITHIN))
def test_a_spend_figure_within_the_checkpoint_keeps_the_bill(figure: Event) -> None:
    message = reply_message(sdk_call(extra=figure), TARGET)
    assert message.response_metadata["nano_aiu"] == 251_164_000


SUB_AGENT_SPEND: dict[str, Event] = {
    "workflow-settled-below": run_settled(50_000_000),
    "workflow-notice": run_completed_notice(50_000_000),
    "subagent-completed": subagent_completed(),
    "sub-agent-envelope": enveloped(
        wire("session.info", infoType="x", message="m"), agentId="agent-1"
    ),
}


@pytest.mark.parametrize(
    "spend", list(SUB_AGENT_SPEND.values()), ids=list(SUB_AGENT_SPEND)
)
def test_a_sub_agents_spend_voids_the_bill_wherever_it_is_stated(spend: Event) -> None:
    """F572: voided everywhere, as `shutdown.agentMetrics` voids it (F568),
    even below the checkpoint: it cannot be reconciled with it."""
    seen = sdk_call(extra=spend)
    assert "nano_aiu" not in reply_message(seen, TARGET).response_metadata


@pytest.mark.parametrize(
    ("premium", "billed"), [(1, True), (2, False)], ids=["equal", "above"]
)
def test_premium_requests_stated_elsewhere_may_not_exceed_the_checkpoints(
    premium: int, billed: bool
) -> None:
    seen = sdk_call(idle=[idle(), shutdown(totalPremiumRequests=premium)])
    assert ("nano_aiu" in reply_message(seen, TARGET).response_metadata) is billed


# Item 2 (F573): a dispatch closes only on `model.call_finished`.
NOT_CLOSED: dict[str, list[Event]] = {
    "closed-by-an-attempts-failure": [
        *UNSPENT,
        call_start(),
        failure("api", 503),
        checkpoint(100_000_000, 1),
        error(500),
    ],
    "closed-by-a-sub-agents-failure": [
        *UNSPENT,
        call_start(),
        wire(
            "model.call_failure",
            source="subagent",
            failureKind="api",
            statusCode=503,
            model=PIN,
        ),
        checkpoint(100_000_000, 1),
        error(500),
    ],
}


@pytest.mark.parametrize("seen", list(NOT_CLOSED.values()), ids=list(NOT_CLOSED))
def test_only_a_finished_dispatch_is_closed(seen: list[Event]) -> None:
    assert "nano_aiu" not in reply_message(seen, TARGET).response_metadata


def test_a_failed_dispatch_closed_by_its_finish_bills_its_checkpoint() -> None:
    message = reply_message(SPENT_FAILURE, TARGET)
    assert message.response_metadata["nano_aiu"] == 100_000_000


# Item 3 (F574): each is spend, never a declared drop.
RE_PAY: dict[str, list[Event]] = {
    "premium-requests-on-a-zero-checkpoint": [
        *UNSPENT,
        *FAILED_DISPATCH,
        checkpoint(0, 1),
        error(500),
        idle(),
    ],
    "shutdown-stating-premium-requests": [
        *UNSPENT,
        *FAILED_DISPATCH,
        error(500),
        idle(),
        shutdown(modelMetrics={}, totalNanoAiu=None, totalPremiumRequests=2),
    ],
    "dispatch-never-closed": [*UNSPENT, call_start(), error(500), idle()],
    "dispatch-never-closed-settled-http-5xx": [
        *UNSPENT,
        call_start(),
        final_result(result="http_5xx"),
        idle(),
    ],
    "a-sub-agents-failure": [
        *UNSPENT,
        wire(
            "model.call_failure",
            source="subagent",
            failureKind="api",
            statusCode=500,
            model=OTHER,
        ),
        error(500),
        idle(),
    ],
    "quiet-events-of-a-sub-agent": [
        *UNSPENT,
        enveloped(call_start(OTHER), agentId="agent-1"),
        enveloped(failure("api", 500), agentId="agent-1"),
        enveloped(call_finished("error"), agentId="agent-1"),
        error(500),
        idle(),
    ],
}


@pytest.mark.parametrize("seen", list(RE_PAY.values()), ids=list(RE_PAY))
def test_these_are_spend_never_a_declared_drop(seen: list[Event]) -> None:
    assert isinstance(invoked(seen), AIMessage)
    completion = provider(replying(*seen)).complete(PROMPT)
    assert completion.drop_kind is None


def test_a_closed_failed_dispatch_is_still_a_declared_drop() -> None:
    """The D110 path stays open: no spend, the dispatch closed, a 5xx."""
    seen = [*UNSPENT, *FAILED_DISPATCH, error(500), idle()]
    completion = provider(replying(*seen)).complete(PROMPT)
    assert completion.drop_kind is DropKind.DECLARED


# Item 4 (F575): fields that say another agent, mode or provider answered.
FIELD_GAPS: dict[str, list[Event]] = {
    "recovered-failure-from-a-sub-agent": recovered_from(
        failure_with(source="subagent")
    ),
    "recovered-failure-from-mcp-sampling": recovered_from(
        failure_with(source="mcp_sampling")
    ),
    "recovered-failure-interaction-type": recovered_from(
        failure_with(interactionType="conversation-subagent")
    ),
    "recovered-failure-byok": recovered_from(failure_with(isByok=True)),
    "usage-interaction-type": sdk_call(
        usage=usage(interactionType="conversation-subagent")
    ),
    "dispatch-edited-a-file": sdk_call(
        call_finished=wire(
            "model.call_finished",
            dispatchDurationMs=1,
            editClassifierVersion=1,
            outcome="success",
            turnId="turn-1",
            containsBuiltInFileEditRequest=True,
        )
    ),
    "idle-in-autopilot-mode": sdk_call(idle=wire("session.idle", mode="autopilot")),
    "idle-in-plan-mode": sdk_call(idle=wire("session.idle", mode="plan")),
}


@pytest.mark.parametrize("seen", list(FIELD_GAPS.values()), ids=list(FIELD_GAPS))
def test_a_field_naming_another_agent_mode_or_provider_refuses(
    seen: list[Event],
) -> None:
    assert "finish_reason" not in reply_message(seen, TARGET).response_metadata


def test_an_idle_in_interactive_mode_is_admitted() -> None:
    seen = sdk_call(idle=wire("session.idle", mode="interactive"))
    assert reply_message(seen, TARGET).response_metadata["finish_reason"] == "stop"


# Item 5: every spend field name the pinned SDK defines, from its own source.
def _sdk_field_names() -> set[str]:
    names: set[str] = set()
    for _name, cls in inspect.getmembers(session_events, inspect.isclass):
        source = getattr(cls, "from_dict", None)
        if source is not None and inspect.isfunction(source):
            names |= set(re.findall(r'obj\.get\("(\w+)"\)', inspect.getsource(source)))
    return names


SPEND_NAMES = sorted(
    name
    for name in _sdk_field_names()
    if re.search(r"NanoAiu|AiCredits|PremiumRequests", name)
)
CAPS = {"maxAiCredits", "declaredMaxAiCredits", "additionalAiCredits"}


def test_every_spend_name_in_the_sdk_is_read_as_spend_or_named_a_cap() -> None:
    for name in SPEND_NAMES:
        assert (copilot_module._unit(name) is None) == (name in CAPS), name
    assert {"totalNanoAiu", "consumedNanoAiu", "usedAiCredits"} <= set(SPEND_NAMES)


@EXAMPLES
@given(
    st.sampled_from(sorted(set(SPEND_NAMES) - CAPS)),
    st.sampled_from(ALL_TYPES),
    st.integers(min_value=0, max_value=2),
    st.integers(min_value=0, max_value=len(SDK_HAPPY) - 2),
)
def test_property_a_spend_figure_above_the_checkpoint_anywhere_voids_the_bill(
    name: str, kind: str, depth: int, at: int
) -> None:
    unit = copilot_module._unit(name)
    above: object = {
        "nano": 251_164_001,
        "credits": 0.251164001 * 10,
        "premium": 2,
    }[cast(str, unit)]
    figure: object = {name: above}
    for _level in range(depth):
        figure = {"nested": [figure]}
    event: Event = {"type": kind, "data": cast(dict[str, object], figure)}
    seen = [*SDK_HAPPY[:at], event, *SDK_HAPPY[at:]]
    assert "nano_aiu" not in reply_message(seen, TARGET).response_metadata


# What the round-3 mutation run found the suite did not pin.


@pytest.mark.parametrize(
    ("credits", "total", "billed"),
    [(0.5, 251_164_000, False), (0.25, 250_000_000, True), (0.25, 249_999_999, False)],
    ids=["above", "exactly-equal", "just-above"],
)
def test_ai_credits_used_are_read_in_nano_ai_units(
    credits: float, total: int, billed: bool
) -> None:
    seen = sdk_call(
        usage=None,
        extra=limits_exhausted(credits, 30.0),
        checkpoint=checkpoint(total, 1),
    )
    assert ("nano_aiu" in reply_message(seen, TARGET).response_metadata) is billed


@pytest.mark.parametrize("figure", [float("inf"), float("nan"), -1.0])
def test_a_stated_spend_figure_that_is_no_count_leaves_the_charge_unknown(
    figure: float,
) -> None:
    stated = _malformed(fusion_completed(1), totalNanoAiu=figure)
    assert (
        "nano_aiu"
        not in reply_message(sdk_call(extra=stated), TARGET).response_metadata
    )


def test_a_completed_runs_spend_voids_the_bill_with_no_sub_agent_named() -> None:
    notice = run_completed_notice(1)
    kind = {**notice["data"]["kind"], "consumedSubagents": 0}
    alone = wire(notice["type"], **{**notice["data"], "kind": kind})
    assert (
        "nano_aiu" not in reply_message(sdk_call(extra=alone), TARGET).response_metadata
    )


def test_per_model_figures_after_one_stating_none_still_sum() -> None:
    metered = shutdown(
        totalNanoAiu=None,
        modelMetrics={
            "a": metric(None),
            "b": metric(200_000_000),
            "c": metric(200_000_000),
        },
    )
    seen = sdk_call(idle=[idle(), metered])
    assert "nano_aiu" not in reply_message(seen, TARGET).response_metadata


def test_every_field_is_found_at_every_depth_and_list_position() -> None:
    pairs = copilot_module._pairs({"a": [{"b": 1}, {"c": [{"d": 2}]}], "e": 3})
    for pair in (("b", 1), ("d", 2), ("e", 3)):
        assert pair in pairs


def test_an_event_whose_type_is_not_text_is_spend_and_never_raises() -> None:
    """F577: a malformed type is read as no type -- not quiet, not settling --
    and no membership test on it raises."""
    odd: Event = {"type": ["session.idle"], "data": {}}
    assert isinstance(invoked([*UNSPENT, odd, error(500)]), AIMessage)
    late = sdk_call(idle=[odd, idle()])
    assert "nano_aiu" not in reply_message(late, TARGET).response_metadata


@pytest.mark.parametrize("source", [["sdk"], {"k": "sdk"}])
def test_a_model_change_whose_source_is_not_text_is_spend_and_never_raises(
    source: object,
) -> None:
    """F581: a malformed source is no chosen source -- refused, billed, never a
    TypeError from a hash of a list or dict."""
    mc = wire(
        "session.model_change", newModel=PIN, reasoningEffort="high", source="sdk"
    )
    odd = {**mc, "data": {**mc["data"], "source": source}}
    seq = sdk_call(extra=[odd])
    assert copilot_module._spent(seq)
    assert isinstance(invoked(seq), AIMessage)


# -- Fix round 4: the re-audit of 581d2e2, as tests. -------------------------

FINISH_OUTCOMES = sorted(
    outcome.value for outcome in session_events.ModelCallFinishedOutcome
)


# Item 1 (F578): `rejected` follows a provider response ("rejected during
# post-response acceptance processing") and `cancelled` may follow a streamed
# one, so only `error` closes a dispatch quietly.
RE_PAY_ROUND_4: dict[str, list[Event]] = {
    f"{outcome}-{shape}": [
        *UNSPENT,
        call_start(),
        *middle,
        call_finished(outcome),
        *end,
    ]
    for outcome in ("rejected", "cancelled")
    for shape, middle, end in (
        ("after-a-500", [failure("api", 500)], [error(500), idle()]),
        ("settled-http-5xx", [], [final_result(result="http_5xx"), idle()]),
        ("settled-other-error", [], [final_result(result="other_error"), idle()]),
    )
}


@pytest.mark.parametrize(
    "seen", list(RE_PAY_ROUND_4.values()), ids=list(RE_PAY_ROUND_4)
)
def test_a_dispatch_rejected_or_cancelled_is_spend_never_a_declared_drop(
    seen: list[Event],
) -> None:
    assert isinstance(invoked(seen), AIMessage)
    completion = provider(replying(*seen)).complete(PROMPT)
    assert completion.drop_kind is None


@EXAMPLES
@given(
    st.sampled_from(FINISH_OUTCOMES),
    st.sampled_from(
        [
            [failure("api", 500), error(500), idle()],
            [final_result(result="http_5xx"), idle()],
            [failure("api", 429), error(429)],
        ]
    ),
)
def test_property_only_a_dispatch_that_finished_in_error_can_be_a_drop(
    outcome: str, ending: list[Event]
) -> None:
    seen = [*UNSPENT, call_start(), call_finished(outcome), *ending]
    assert copilot_module._spent(seen) is (outcome != "error")
    if outcome == "error":
        with pytest.raises(CopilotStatusError):
            invoked(seen)
    else:
        assert isinstance(invoked(seen), AIMessage)


# Item 2 (F579): per-request spend is summed across every event that states it.
def phase_failed(nano_aiu: int) -> Event:
    return wire(
        "assistant.fusion_phase_failed",
        conversationScope="root",
        durationMs=1.0,
        fusionId="f",
        model=PIN,
        phaseId="q",
        phaseKind="primary",
        reason="r",
        role="r",
        status="failed",
        usage={
            "cachedTokens": 0,
            "inputTokens": 1,
            "outputTokens": 1,
            "requestCount": 1,
            "totalNanoAiu": nano_aiu,
        },
    )


SUMMED_ABOVE: dict[str, list[Event]] = {
    "compaction-and-request": sdk_call(
        started=[started(), compaction_complete_at(250_000_000)]
    ),
    "two-fusion-phases": sdk_call(
        usage=usage(copilotUsage=None),
        extra=[phase_completed(200_000_000), phase_failed(200_000_000)],
    ),
    "fusion-phase-and-request": sdk_call(extra=phase_completed(1)),
}


@pytest.mark.parametrize("seen", list(SUMMED_ABOVE.values()), ids=list(SUMMED_ABOVE))
def test_per_request_spend_summed_across_event_types_above_the_bill_voids_it(
    seen: list[Event],
) -> None:
    assert "nano_aiu" not in reply_message(seen, TARGET).response_metadata


def test_per_request_spend_summed_to_exactly_the_bill_is_billed() -> None:
    seen = sdk_call(
        started=[started(), compaction_complete_at(1_164_000)],
        usage=usage(copilotUsage={"totalNanoAiu": 200_000_000, "model": PIN}),
        extra=phase_completed(50_000_000),
    )
    assert reply_message(seen, TARGET).response_metadata["nano_aiu"] == 251_164_000


HOLDERS: dict[str, Callable[[int], Event]] = {
    "usage": lambda n: usage(copilotUsage={"totalNanoAiu": n, "model": PIN}),
    "compaction": compaction_complete_at,
    "fusion-phase-completed": phase_completed,
    "fusion-phase-failed": phase_failed,
}


@EXAMPLES
@given(
    st.lists(
        st.tuples(
            st.sampled_from(sorted(HOLDERS)),
            st.integers(min_value=0, max_value=3 * 10**8),
        ),
        min_size=1,
        max_size=4,
    ),
    st.integers(min_value=1, max_value=10**9),
)
def test_property_per_request_spend_bills_only_when_its_sum_is_within_the_bill(
    stated: list[tuple[str, int]], total: int
) -> None:
    held = [HOLDERS[holder](figure) for holder, figure in stated]
    seen = sdk_call(usage=None, extra=held, checkpoint=checkpoint(total))
    nano = reply_message(seen, TARGET).response_metadata.get("nano_aiu")
    assert nano == (total if sum(figure for _h, figure in stated) <= total else None)


def test_only_a_fusion_phase_states_its_request_as_usage() -> None:
    """F579, found by mutation testing: a `usage` field of any other event is
    no per-request block, so it is held alone and never added."""
    phase = phase_completed(7)
    other = {**phase, "type": "session.fusion_completed"}
    assert copilot_module._requests([other]) == []
    assert copilot_module._requests([phase]) == [phase["data"]["usage"]]


# The SDK classes that state nano-AIU, by how the bill holds each: summed as
# per-request spend, the cumulative bill itself, an aggregate held alone (a
# fusion turn's total of its phases; a shutdown's per-model sum), or a
# sub-agent's, which voids.
PER_REQUEST_CLASSES = {
    "AssistantUsageCopilotUsage",
    "_CompactionCompleteCompactionTokensUsedCopilotUsage",
    "FusionPhaseUsage",
}
HELD_OTHERWISE = {
    "SessionUsageCheckpointData",
    "SessionShutdownData",
    "ShutdownModelMetric",
    "SessionFusionCompletedData",
    "ShutdownAgentMetric",
}


def test_every_sdk_class_stating_nano_ai_units_is_summed_or_held_otherwise() -> None:
    stating = {
        name
        for name, cls in inspect.getmembers(session_events, inspect.isclass)
        if "total_nano_aiu" in getattr(cls, "__annotations__", {})
    }
    assert stating == PER_REQUEST_CLASSES | HELD_OTHERWISE
    for holder in HOLDERS.values():
        blocks = copilot_module._requests([holder(7)])
        assert [
            cast(Mapping[str, object], block)["totalNanoAiu"] for block in blocks
        ] == [7]


# Item 3 (F580): the model proof reads the past too, and a dispatch must name.
MODEL_PROOF_ROUND_4: dict[str, list[Event]] = {
    "cache-break-from-another-model": sdk_call(
        extra=cache_break(modelFrom=OTHER, modelTo=PIN)
    ),
    "model-change-from-another-model": sdk_call(
        extra=model_change(PIN, previous=OTHER)
    ),
    "model-change-automatic": sdk_call(
        extra=wire(
            "session.model_change",
            newModel=PIN,
            reasoningEffort="high",
            source="automatic",
        )
    ),
    "model-change-by-an-agent": sdk_call(
        extra=wire(
            "session.model_change", newModel=PIN, reasoningEffort="high", source="agent"
        )
    ),
    "model-change-by-plan-mode": sdk_call(
        extra=wire(
            "session.model_change",
            newModel=PIN,
            reasoningEffort="high",
            source="plan_mode",
        )
    ),
    "dispatch-naming-no-model": sdk_call(
        call_start=wire("model.call_start", turnId="turn-1")
    ),
    "an-unnamed-dispatch-before-the-pins": sdk_call(
        turn_start=[
            turn_start(),
            wire("model.call_start", turnId="turn-1"),
            reasoning(),
            call_finished(),
        ]
    ),
    "start-selecting-no-model": sdk_call(usage=None, started=started(model=None)),
}


@pytest.mark.parametrize(
    "seen", list(MODEL_PROOF_ROUND_4.values()), ids=list(MODEL_PROOF_ROUND_4)
)
def test_another_model_named_in_the_past_or_no_model_named_refuses(
    seen: list[Event],
) -> None:
    message = reply_message(seen, TARGET)
    assert "finish_reason" not in message.response_metadata
    assert message.response_metadata["nano_aiu"] == 251_164_000


CHANGE_SOURCES = sorted(source.value for source in session_events.ModelChangeSource)
REFUSED_SOURCES = {"automatic", "agent", "plan_mode", "auto_tier_recommendation"}


@EXAMPLES
@given(
    st.sampled_from([None, *CHANGE_SOURCES]),
    st.sampled_from([None, PIN, OTHER]),
    st.sampled_from([None, PIN, OTHER]),
    st.booleans(),
    st.booleans(),
)
def test_property_the_finish_stands_only_when_every_dispatch_names_only_the_pin(
    source: str | None,
    previous: str | None,
    moved_from: str | None,
    dispatch_named: bool,
    start_named: bool,
) -> None:
    change = wire(
        "session.model_change",
        newModel=PIN,
        previousModel=previous,
        reasoningEffort="high",
        source=source,
    )
    seen = sdk_call(
        started=started(model=PIN if start_named else None),
        call_start=call_start()
        if dispatch_named
        else wire("model.call_start", turnId="turn-1"),
        extra=[change, cache_break(modelFrom=moved_from, modelTo=PIN)],
    )
    stands = (
        source not in REFUSED_SOURCES
        and previous in (None, PIN)
        and moved_from in (None, PIN)
        and dispatch_named
        and start_named
    )
    message = reply_message(seen, TARGET)
    assert ("finish_reason" in message.response_metadata) is stands
    assert message.response_metadata["nano_aiu"] == 251_164_000


# Task 3 (R8 row 2): the credit price, the output cap, the SDK transport and
# the factory dispatch.


def test_the_credit_price_is_a_dated_decimal_or_not_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert credit_price("0.01,2026-10-01") == CreditPrice(
        Decimal("0.01"), date(2026, 10, 1)
    )
    monkeypatch.setenv(CREDIT_PRICE_ENV, "0.0125,2026-09-30")
    assert credit_price() == CreditPrice(Decimal("0.0125"), date(2026, 9, 30))
    monkeypatch.delenv(CREDIT_PRICE_ENV)
    for written in (
        None,
        "",
        "0.01",
        "0.01,",
        ",2026-10-01",
        "0.01,2026-10-01,x",
        "0,2026-10-01",
        "0.00,2026-10-01",
        "-0.01,2026-10-01",
        "+0.01,2026-10-01",
        "1e-2,2026-10-01",
        ".01,2026-10-01",
        " 0.01,2026-10-01",
        "0.01 ,2026-10-01",
        "NaN,2026-10-01",
        "\u0660.\u0660\u0661,2026-10-01",
        "0.01,2026-13-01",
        "0.01,20261001",
        "0.01,2026-10-1",
        "0.01,2999-01-01",
        "1" + "0" * 131072 + ",2026-10-01",
    ):
        with pytest.raises(Refusal) as refused:
            credit_price(written)
        assert refused.value.code is RefusalCode.PROVIDER_NOT_CONFIGURED
        assert refused.value.args == (RefusalCode.PROVIDER_NOT_CONFIGURED,)


def test_the_credit_price_is_never_later_than_today_in_utc(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    today = datetime.now(UTC).date()
    assert credit_price(f"0.01,{today.isoformat()}").as_of == today

    class Clock(datetime):
        """Half past midnight in UTC, still the evening before locally."""

        @classmethod
        def now(cls, tz: tzinfo | None = None) -> Clock:
            if tz is UTC:
                return cls(2026, 10, 7, 0, 30, tzinfo=UTC)
            return cls(2026, 10, 6, 20, 30)

    monkeypatch.setattr(copilot_module, "datetime", Clock)
    assert credit_price("0.01,2026-10-07").as_of == date(2026, 10, 7)
    with pytest.raises(Refusal):
        credit_price("0.01,2026-10-08")


def test_the_output_cap_is_the_sessions_cap_and_the_cli_is_deferred() -> None:
    assert output_cap(MODEL) == MAX_COMPLETION_TOKENS == 65536
    assert output_cap("copilot:gpt-6-luna") == 65536
    assert output_cap("claude-opus-5-5") == 65536
    for deferred in ("copilot-cli:gpt-6-luna", "copilot-cli:claude-opus-5.5@high"):
        with pytest.raises(Refusal) as refused:
            output_cap(deferred)
        assert refused.value.code is RefusalCode.PROVIDER_NOT_CONFIGURED


# Every name R3 excludes from the child, set in the parent with a value that
# must not cross.
EXCLUDED = (
    "GH_TOKEN",
    "GITHUB_TOKEN",
    "GITHUB_ASKPASS",
    "GIT_ASKPASS",
    "SSH_ASKPASS",
    "COPILOT_HMAC_KEY",
    "COPILOT_HMAC_ASKPASS",
    "COPILOT_PROVIDER_BASE_URL",
    "COPILOT_PROVIDER_API_KEY",
    "COPILOT_PROVIDER_API_KEY_COMMAND",
    "COPILOT_PROVIDER_BEARER_TOKEN",
    "COPILOT_PROVIDER_ANYTHING",
    "COPILOT_ALLOW_ALL",
    "COPILOT_OTEL_ENABLED",
    "OTEL_EXPORTER_OTLP_ENDPOINT",
    "OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT",
    "GH_HOST",
    "COPILOT_GH_HOST",
    "COPILOT_CLI_PATH",
    "COPILOT_MODEL",
    "COPILOT_AUTO_TIER",
    "COPILOT_CUSTOM_INSTRUCTIONS_DIRS",
    "COPILOT_OFFLINE",
    "GITHUB_COPILOT_PROMPT_MODE_ANY",
    "USE_TGREP",
    "BASH_ENV",
    "COPILOT_SDK_DEFAULT_CONNECTION",
    "COPILOT_HOME",
    "CAOS_COPILOT_RUNTIME",
    "CAOS_COPILOT_CREDIT_PRICE",
    "http_proxy",
    "SOME_OTHER_NAME",
)
POSIX_NEEDS = ("HOME", "TMPDIR", "LANG")
WINDOWS_NEEDS = (
    "SYSTEMROOT",
    "SYSTEMDRIVE",
    "USERPROFILE",
    "TEMP",
    "TMP",
    "LOCALAPPDATA",
)
PROXY = (
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "NO_PROXY",
    "SSL_CERT_FILE",
    "NODE_EXTRA_CA_CERTS",
)


def parent_environment(monkeypatch: pytest.MonkeyPatch, *names: str) -> None:
    for name in list(os.environ):
        monkeypatch.delenv(name)
    for name in names:
        monkeypatch.setenv(name, f"parent-{name}")


@pytest.mark.parametrize(
    ("platform", "needs"), [("darwin", POSIX_NEEDS), ("win32", WINDOWS_NEEDS)]
)
def test_the_child_environment_is_exactly_the_allow_list(
    monkeypatch: pytest.MonkeyPatch, platform: str, needs: tuple[str, ...]
) -> None:
    parent_environment(
        monkeypatch,
        *EXCLUDED,
        *POSIX_NEEDS,
        *WINDOWS_NEEDS,
        *PROXY,
        "COPILOT_GITHUB_TOKEN",
        "PATH",
    )
    monkeypatch.setattr("sys.platform", platform)
    runtime = os.path.join("opt", "copilot", "bin", "copilot-runtime")
    child = child_environment("private-home", runtime)
    assert child == {
        "COPILOT_HOME": "private-home",
        "COPILOT_GITHUB_TOKEN": "parent-COPILOT_GITHUB_TOKEN",
        "COPILOT_DISABLE_KEYTAR": "1",
        "COPILOT_AUTO_UPDATE": "false",
        "NO_COLOR": "1",
        "PATH": os.path.join("opt", "copilot", "bin"),
        **{name: f"parent-{name}" for name in (*needs, *PROXY)},
    }


def test_the_child_environment_copies_only_what_is_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    parent_environment(monkeypatch)
    monkeypatch.setattr("sys.platform", "linux")
    assert child_environment("home", "/runtime/copilot") == {
        "COPILOT_HOME": "home",
        "COPILOT_DISABLE_KEYTAR": "1",
        "COPILOT_AUTO_UPDATE": "false",
        "NO_COLOR": "1",
        "PATH": "/runtime",
    }


def test_a_script_runtime_finds_node_and_nothing_else_on_its_path(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    node_home = tmp_path / "node" / "bin"
    node_home.mkdir(parents=True)
    node = node_home / "node"
    node.write_text("#!/bin/sh\n", encoding="utf-8")
    node.chmod(0o755)
    gh = tmp_path / "gh" / "bin"
    gh.mkdir(parents=True)
    (gh / "gh").write_text("#!/bin/sh\n", encoding="utf-8")
    (gh / "gh").chmod(0o755)
    parent_environment(monkeypatch)
    monkeypatch.setenv("PATH", os.pathsep.join((str(gh), str(node_home))))
    monkeypatch.setattr("sys.platform", "linux")
    child = child_environment("home", "/runtime/index.js")
    assert child["PATH"] == os.pathsep.join(("/runtime", str(node_home)))
    monkeypatch.setenv("PATH", str(gh))
    with pytest.raises(Refusal) as refused:
        child_environment("home", "/runtime/index.js")
    assert refused.value.code is RefusalCode.PROVIDER_NOT_CONFIGURED


def test_the_sdk_logger_reaches_no_handler(
    capsys: pytest.CaptureFixture[str],
) -> None:
    caught: list[logging.LogRecord] = []

    class Caught(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            caught.append(record)

    root = logging.getLogger()
    held = Caught()
    root.addHandler(held)
    try:
        copilot_module._silenced()
        sdk = logging.getLogger("copilot")
        assert sdk.propagate is False
        assert sdk.level == logging.CRITICAL
        assert [type(handler) for handler in sdk.handlers] == [logging.NullHandler]
        for name in ("copilot._jsonrpc", "copilot.client", "copilot"):
            logging.getLogger(name).warning("[CLI] %s", SECRET)
            logging.getLogger(name).critical("[CLI] %s", SECRET)
        # Idempotent, and it undoes a handler someone attached since.
        sdk.addHandler(logging.StreamHandler())
        copilot_module._silenced()
        assert [type(handler) for handler in sdk.handlers] == [logging.NullHandler]
        logging.getLogger("copilot._jsonrpc").error("[CLI] %s", SECRET)
    finally:
        root.removeHandler(held)
    assert caught == []
    out, err = capsys.readouterr()
    assert SECRET not in out + err


# -- The SDK transport (Task 3; R3, R7, R2.7) ---------------------------------

# The runtime the SDK downloads, as `ensure_runtime_wrapper` names it.
DOWNLOADED = os.path.join(os.sep, "cache", "copilot", "1.0.90", "copilot-runtime")


class Wire:
    """A session event as the SDK hands it to a handler."""

    def __init__(self, wire: Event) -> None:
        self.wire = wire

    def to_dict(self) -> Event:
        return self.wire


def url_request() -> object:
    """A permission request the runtime could raise, through the SDK's type."""
    return session_events.PermissionRequestUrl.from_dict(
        {"kind": "url", "intention": "read", "url": "https://example.invalid"}
    )


class FakeSession:
    """Stands in for `copilot.CopilotSession`: delivers its events to the
    `on_event` handler it was created with when the prompt is sent, asking the
    permission handler first at `asks_at` when set."""

    def __init__(
        self, seen: Sequence[Event], *, ends: bool = True, asks_at: int | None = None
    ) -> None:
        self.seen = seen
        self.ends = ends
        self.asks_at = asks_at
        self.options: dict[str, Any] = {}
        self.sent: list[str] = []
        self.decisions: list[object] = []
        self.aborted = False
        self.closed = False

    async def send(self, prompt: str) -> str:
        self.sent.append(prompt)
        delivered = list(self.seen) if self.ends else []
        for index, event in enumerate(delivered):
            if index == self.asks_at:
                decided = self.options["on_permission_request"](
                    url_request(),
                    {"session_id": "s", "managed_settings_enabled": False},
                )
                self.decisions.append(decided)
            self.options["on_event"](Wire(event))
        return "message-1"

    async def abort(self) -> None:
        self.aborted = True

    async def __aenter__(self) -> FakeSession:
        return self

    async def __aexit__(self, *_exc: object) -> None:
        self.closed = True


class FakeRuntime:
    """Stands in for `copilot.CopilotClient`: one per call, each recorded. It
    writes to the SDK's logger as the runtime's stderr reader does."""

    made: ClassVar[list[FakeRuntime]] = []
    session: ClassVar[FakeSession] = FakeSession([])

    def __init__(self, **options: object) -> None:
        self.options: dict[str, Any] = dict(options)
        self.home = Path(str(options["base_directory"]))
        self.home_existed = self.home.is_dir()
        self.created: dict[str, Any] = {}
        self.entered = False
        self.exited = False
        type(self).made.append(self)

    async def __aenter__(self) -> FakeRuntime:
        self.entered = True
        logging.getLogger("copilot._jsonrpc").warning("[CLI] %s", SECRET)
        return self

    async def __aexit__(self, *_exc: object) -> None:
        self.exited = True

    async def create_session(self, **options: object) -> FakeSession:
        self.created = dict(options)
        session = type(self).session
        session.options = self.created
        return session


@pytest.fixture
def runtime(monkeypatch: pytest.MonkeyPatch) -> type[FakeRuntime]:
    class Runtime(FakeRuntime):
        made: ClassVar[list[FakeRuntime]] = []
        session: ClassVar[FakeSession] = FakeSession(SDK_HAPPY)

    monkeypatch.setattr("copilot.CopilotClient", Runtime)
    monkeypatch.setattr(
        "copilot._cli_download.ensure_runtime_wrapper", lambda: DOWNLOADED
    )
    monkeypatch.delenv(RUNTIME_ENV, raising=False)
    return Runtime


def sent_options(made: FakeRuntime) -> dict[str, Any]:
    """What the session was created with, less the two per-call handlers."""
    return {
        key: value
        for key, value in made.created.items()
        if key not in ("on_event", "on_permission_request")
    }


def test_a_session_has_no_tool_no_compaction_no_system_text_and_the_cap() -> None:
    posture = {
        "model": "claude-opus-5.5",
        "reasoning_effort": "high",
        "available_tools": [],
        "tools": [],
        "system_message": {"mode": "replace", "content": ""},
        "infinite_sessions": {"enabled": False},
        "context_tier": "long_context",
        "model_capabilities": ModelCapabilitiesOverride(
            limits=ModelLimitsOverride(max_output_tokens=65536)
        ),
        "working_directory": "home",
        "streaming": False,
        "disabled_mcp_servers": ["github-mcp-server", "githubiq"],
        "mcp_servers": {},
        "enable_skills": False,
        "skip_custom_instructions": True,
        "enable_file_hooks": False,
        "plugin_directories": [],
        "skill_directories": [],
        "custom_agents": [],
        "enable_session_telemetry": False,
    }
    assert session_options(TARGET, "home") == posture
    assert session_options(TARGET, "home", 42) == {
        **posture,
        "session_limits": {"max_ai_credits": 42},
    }
    unpinned = session_options(CopilotModel("copilot", PIN, None), "home")
    assert unpinned["reasoning_effort"] is None


def test_one_call_is_one_fresh_runtime_and_session_and_leaves_nothing_on_disk(
    runtime: type[FakeRuntime], capsys: pytest.CaptureFixture[str]
) -> None:
    assert ask_copilot(PROMPT, TARGET, 5.0) == SDK_HAPPY
    [made] = runtime.made
    assert made.home_existed
    assert made.home.name.startswith("caos-copilot-")
    assert not made.home.exists()
    assert made.entered and made.exited
    assert sent_options(made) == session_options(TARGET, str(made.home))
    assert runtime.session.sent == [PROMPT]
    assert runtime.session.closed
    assert not runtime.session.aborted
    # The runtime's stderr, as the SDK logs it, reaches no handler (R7).
    out, err = capsys.readouterr()
    assert (out, err) == ("", "")
    assert ask_copilot(PROMPT, TARGET, 5.0) == SDK_HAPPY
    first, second = runtime.made
    assert first.home != second.home


def test_the_runtime_never_auto_logs_in_and_sees_only_the_allow_listed_environment(
    runtime: type[FakeRuntime], monkeypatch: pytest.MonkeyPatch
) -> None:
    for name in ("GH_TOKEN", "GITHUB_TOKEN", "COPILOT_PROVIDER_API_KEY", "GH_HOST"):
        monkeypatch.setenv(name, f"parent-{name}")
    # Neither may redirect the runtime: the connection is always an explicit
    # child process of the runtime CAOS resolved.
    monkeypatch.setenv("COPILOT_CLI_PATH", "/elsewhere/copilot")
    monkeypatch.setenv("COPILOT_SDK_DEFAULT_CONNECTION", "inprocess")
    monkeypatch.setenv("COPILOT_GITHUB_TOKEN", "parent-token")
    ask_copilot(PROMPT, TARGET, 5.0)
    [made] = runtime.made
    connection = made.options.pop("connection")
    assert isinstance(connection, StdioRuntimeConnection)
    assert (connection.path, tuple(connection.args), connection.env) == (
        DOWNLOADED,
        (),
        None,
    )
    environment = made.options.pop("env")
    assert made.options == {
        "mode": "empty",
        "base_directory": str(made.home),
        "working_directory": str(made.home),
        "log_level": "none",
        "use_logged_in_user": False,
    }
    assert environment == child_environment(str(made.home), DOWNLOADED)
    assert environment["PATH"] == os.path.dirname(DOWNLOADED)
    assert environment["COPILOT_GITHUB_TOKEN"] == "parent-token"
    for name in ("GH_TOKEN", "GITHUB_TOKEN", "COPILOT_PROVIDER_API_KEY", "GH_HOST"):
        assert name not in environment
    assert "COPILOT_CLI_PATH" not in environment


def test_a_runtime_the_operator_names_is_started_when_its_path_is_absolute(
    runtime: type[FakeRuntime], monkeypatch: pytest.MonkeyPatch
) -> None:
    named = os.path.join(os.sep, "opt", "it", "copilot")
    monkeypatch.setenv(RUNTIME_ENV, named)
    ask_copilot(PROMPT, TARGET, 5.0)
    [made] = runtime.made
    assert made.options["connection"].path == named
    assert made.options["env"]["PATH"] == os.path.dirname(named)
    for relative in ("copilot", os.path.join("bin", "copilot"), ""):
        monkeypatch.setenv(RUNTIME_ENV, relative)
        if not relative:
            # Empty is unset: the downloaded runtime.
            ask_copilot(PROMPT, TARGET, 5.0)
            assert runtime.made[-1].options["connection"].path == DOWNLOADED
            continue
        with pytest.raises(Refusal) as refused:
            ask_copilot(PROMPT, TARGET, 5.0)
        assert refused.value.code is RefusalCode.PROVIDER_NOT_CONFIGURED
    assert len(runtime.made) == 2


def test_a_call_that_does_not_end_in_time_is_aborted_and_raises(
    runtime: type[FakeRuntime],
) -> None:
    runtime.session = FakeSession([], ends=False)
    with pytest.raises(TimeoutError):
        ask_copilot(PROMPT, TARGET, 0.01)
    assert runtime.session.aborted
    assert runtime.session.closed
    [made] = runtime.made
    assert made.exited
    assert not made.home.exists()


def test_a_session_error_ends_the_wait_and_is_returned_as_data(
    runtime: type[FakeRuntime],
) -> None:
    failed = [*UNSPENT, error(402)]
    runtime.session = FakeSession(failed)
    assert ask_copilot(PROMPT, TARGET, 5.0) == failed
    assert not runtime.session.aborted


def test_only_the_main_agents_idle_or_error_ends_the_wait(
    runtime: type[FakeRuntime],
) -> None:
    for ending in (idle(), error(500)):
        runtime.session = FakeSession(
            [*UNSPENT, enveloped(ending, agentId="sub-agent")], ends=True
        )
        with pytest.raises(TimeoutError):
            ask_copilot(PROMPT, TARGET, 0.05)
        assert runtime.session.aborted


def test_a_permission_request_during_a_call_is_denied_and_refuses_the_call(
    runtime: type[FakeRuntime],
) -> None:
    runtime.session = FakeSession(SDK_HAPPY, asks_at=4)
    seen = ask_copilot(PROMPT, TARGET, 5.0)
    [decided] = runtime.session.decisions
    assert isinstance(decided, PermissionDecisionReject)
    assert decided.feedback is None
    assert [event["type"] for event in seen].count(PERMISSION_ASKED) == 1
    assert seen.index({"type": PERMISSION_ASKED, "data": {}}) == 4
    answered = provider(lambda *_args: seen).complete(PROMPT)
    assert answered.refusal is RefusalCode.PROVIDER_RESPONSE_INVALID
    assert (answered.content, answered.drop_kind) == (None, None)
    # Asked with nothing else spent: still never a drop, so never re-sent.
    runtime.session = FakeSession([*UNSPENT, error(500)], asks_at=1)
    quiet = ask_copilot(PROMPT, TARGET, 5.0)
    unanswered = provider(lambda *_args: quiet).complete(PROMPT)
    assert unanswered.refusal is RefusalCode.PROVIDER_RESPONSE_INVALID
    assert unanswered.drop_kind is None


@pytest.mark.parametrize(
    ("amount", "credit", "cap"),
    [
        (Decimal("0.05"), CREDIT, 30),
        (Decimal("0.30"), CREDIT, 30),
        (Decimal("0.31"), CREDIT, 31),
        (Decimal("1.00"), CREDIT, 100),
        (Decimal("1.001"), CREDIT, 101),
        (Decimal("2.5"), Decimal("0.0125"), 200),
        (Decimal("0"), CREDIT, 30),
        (Decimal("1.00"), None, None),
    ],
)
def test_a_session_is_capped_at_its_reservation_in_credits_never_below_thirty(
    runtime: type[FakeRuntime], amount: Decimal, credit: Decimal | None, cap: int | None
) -> None:
    with reserving(amount, credit=credit):
        ask_copilot(PROMPT, TARGET, 5.0)
    [made] = runtime.made
    assert made.created.get("session_limits") == (
        None if cap is None else {"max_ai_credits": cap}
    )


def test_a_call_with_no_reservation_in_scope_sends_no_cap(
    runtime: type[FakeRuntime],
) -> None:
    ask_copilot(PROMPT, TARGET, 5.0)
    assert "session_limits" not in runtime.made[-1].created


def test_the_cap_reaches_a_call_made_through_the_provider(
    runtime: type[FakeRuntime],
) -> None:
    chat = completions(PRICE, chat=ChatCopilot(model=MODEL), endpoint=MODEL)
    with reserving(Decimal("0.75"), credit=CREDIT):
        chat.complete(PROMPT)
    assert runtime.made[-1].created["session_limits"] == {"max_ai_credits": 75}


def test_chat_copilot_answers_through_the_sdk_unless_told_otherwise() -> None:
    assert ChatCopilot(model=MODEL).ask is ask_copilot


def test_a_home_the_runtime_left_behind_is_named_on_stderr_without_its_path(
    runtime: type[FakeRuntime],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def kept(path: object, *_args: object, **_kwargs: object) -> None:
        return None

    monkeypatch.setattr("shutil.rmtree", kept)
    ask_copilot(PROMPT, TARGET, 5.0)
    [made] = runtime.made
    assert made.home.exists()
    made.home.rmdir()
    _out, err = capsys.readouterr()
    assert err == "COPILOT_HOME_NOT_REMOVED\n"


# -- The factory dispatch (Task 3, Design 2) ----------------------------------


def test_a_copilot_model_is_answered_by_chat_copilot_never_the_gateway(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import databricks_langchain

    def gateway(**_given: object) -> None:
        pytest.fail("a copilot: model reached the gateway")

    monkeypatch.setattr(databricks_langchain, "ChatDatabricks", gateway)
    monkeypatch.setattr(
        "caos.workspace.workspace_client",
        lambda: pytest.fail("a copilot: model built a workspace client"),
    )
    chat = models.chat_model(endpoint=MODEL)
    assert isinstance(chat, ChatCopilot)
    assert (chat.model, chat.ask, chat.timeout) == (
        MODEL,
        ask_copilot,
        TIMEOUT_SECONDS,
    )
    monkeypatch.setenv(models.ENDPOINT_ENV, "copilot:gpt-6-luna")
    configured = models.chat_model()
    assert isinstance(configured, ChatCopilot)
    assert configured.model == "copilot:gpt-6-luna"


def test_a_copilot_identity_names_its_platform_model_and_effort() -> None:
    assert models.identity_of(MODEL) == "copilot/claude-opus-5.5/high/65536"
    assert models.identity_of("copilot:gpt-6-luna") == "copilot/gpt-6-luna/none/65536"
    # The Copilot name carries its own effort: a separate one is not its.
    assert models.identity_of(MODEL, "low") == "copilot/claude-opus-5.5/high/65536"
    assert (
        models.identity_of("claude-opus-5-5") == "databricks/claude-opus-5-5/none/65536"
    )
    assert (
        models.identity_of("claude-opus-5-5", "high")
        == "databricks/claude-opus-5-5/high/65536"
    )
    assert provider(replying()).qualification_identity == (
        "copilot/claude-opus-5.5/high/65536"
    )


@pytest.mark.parametrize(
    "name", ["copilot:Opus", "COPILOT:gpt-6-luna", "copilot:", "copilot:x@turbo"]
)
def test_a_malformed_copilot_name_is_refused_before_any_client(
    name: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    import databricks_langchain

    monkeypatch.setattr(
        databricks_langchain, "ChatDatabricks", lambda **_: pytest.fail("built")
    )
    for refused_call in (
        lambda: models.chat_model(endpoint=name),
        lambda: models.identity_of(name),
    ):
        with pytest.raises(Refusal) as refused:
            refused_call()
        assert refused.value.code is RefusalCode.PROVIDER_NOT_CONFIGURED


def test_a_cli_copilot_name_is_refused_until_its_transport_is_built(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import databricks_langchain

    monkeypatch.setattr(
        databricks_langchain, "ChatDatabricks", lambda **_: pytest.fail("built")
    )
    for refused_call in (
        lambda: models.chat_model(endpoint="copilot-cli:gpt-6-luna"),
        lambda: models.identity_of("copilot-cli:gpt-6-luna@high"),
    ):
        with pytest.raises(Refusal) as refused:
            refused_call()
        assert refused.value.code is RefusalCode.PROVIDER_NOT_CONFIGURED


# -- The charge through `ChatCompletions` (R2.4, R2.5) ------------------------


def test_a_copilot_message_is_billed_in_ai_units_at_the_reservations_credit_price() -> (
    None
):
    for seen in (HAPPY, SDK_HAPPY):
        with reserving(Decimal("2.00"), credit=CREDIT):
            completion = provider(replying(*seen)).complete(PROMPT)
        assert completion.refusal is None
        # 251,164,000 nano-AIU at $0.01 a credit, never the token counts.
        assert completion.charge == Decimal("0.00251164")
    with reserving(Decimal("2.00"), credit=Decimal("0.02")):
        doubled = provider(replying(*SDK_HAPPY)).complete(PROMPT)
    assert doubled.charge == Decimal("0.00502328")


def test_a_copilot_message_with_no_ai_units_is_an_unknown_charge() -> None:
    no_checkpoint = [
        event for event in SDK_HAPPY if event["type"] != "session.usage_checkpoint"
    ]
    with reserving(Decimal("2.00"), credit=CREDIT):
        completion = provider(replying(*no_checkpoint)).complete(PROMPT)
    # Its token counts are not its bill (R2.4).
    assert invoked(no_checkpoint).usage_metadata is not None
    assert (completion.content, completion.charge, completion.refusal) == (
        None,
        None,
        RefusalCode.PROVIDER_RESPONSE_INVALID,
    )
    assert completion.drop_kind is None


def test_a_reservation_with_no_credit_price_cannot_settle_a_copilot_call() -> None:
    for scope in (reserving(Decimal("2.00")), contextlib.nullcontext()):
        with scope:
            completion = provider(replying(*SDK_HAPPY)).complete(PROMPT)
        assert (completion.content, completion.charge, completion.refusal) == (
            None,
            None,
            RefusalCode.PROVIDER_RESPONSE_INVALID,
        )


@pytest.mark.parametrize(
    "changed",
    [
        {"inputTokens": 10**7},
        {"outputTokens": MAX_COMPLETION_TOKENS + 1},
        {"inputTokens": 0, "cacheReadTokens": 0, "cacheWriteTokens": 0},
    ],
)
def test_token_counts_past_their_bound_leave_a_copilot_charge_unknown(
    changed: dict[str, object],
) -> None:
    seen = sdk_call(usage=usage(**changed))
    with reserving(Decimal("2.00"), credit=CREDIT):
        completion = provider(replying(*seen)).complete(PROMPT)
    assert completion.charge is None
    assert completion.refusal is RefusalCode.PROVIDER_RESPONSE_INVALID


# -- Properties (D121): settlement against the reservation (R2.6, R2.7) -------

AMOUNTS = st.decimals(
    min_value=Decimal(0),
    max_value=Decimal(10_000),
    places=10,
    allow_nan=False,
    allow_infinity=False,
)


@EXAMPLES
@given(UNITS.filter(bool), CREDITS, AMOUNTS)
def test_property_a_settled_charge_is_within_its_reservation_or_named_exactly(
    units: int, credit: Decimal, amount: Decimal
) -> None:
    charge = charged(units, credit)
    assert charge is not None
    taken = Reservation(amount, PRICE, CreditPrice(credit, date(2026, 10, 1)))
    said = io.StringIO()
    with contextlib.redirect_stderr(said):
        within = canonical._settled_within(taken, charge)
    assert within is (charge <= amount)
    if within:
        assert said.getvalue() == ""
    else:
        # The line names the reservation, the charge and the very AI units
        # that settled it: the arithmetic round-trips exactly.
        assert said.getvalue() == (
            f"BUDGET_CHARGE_OVER_RESERVATION reserved={amount} charged={charge}"
            f" nano_aiu={units}\n"
        )


@EXAMPLES
@given(AMOUNTS, AMOUNTS)
def test_property_a_token_priced_reservation_bounds_no_charge(
    amount: Decimal, charge: Decimal
) -> None:
    """With no credit price the bill is the gateway's tokens, whose overrun
    the run's capacity absorbs (Phase 2's budget exit): never refused here."""
    said = io.StringIO()
    with contextlib.redirect_stderr(said):
        assert canonical._settled_within(Reservation(amount, PRICE), charge)
    assert said.getvalue() == ""


@EXAMPLES
@given(AMOUNTS, CREDITS)
def test_property_the_session_cap_covers_its_reservation_tightly(
    amount: Decimal, credit: Decimal
) -> None:
    with reserving(amount, credit=credit):
        cap = copilot_module._credit_cap()
    assert cap is not None
    assert cap >= copilot_module.MIN_CREDIT_CAP
    # Never below the reservation in credits, and never a whole credit above
    # it unless the floor holds it up.
    assert cap * Fraction(credit) >= Fraction(amount)
    assert cap == copilot_module.MIN_CREDIT_CAP or (cap - 1) * Fraction(
        credit
    ) < Fraction(amount)


@EXAMPLES
@given(UNITS.filter(bool), CREDITS, AMOUNTS)
def test_property_a_copilot_charge_is_its_reservations_credit_never_another(
    units: int, credit: Decimal, amount: Decimal
) -> None:
    # No per-request figure to hold against the checkpoint (F579).
    seen = sdk_call(usage=None, checkpoint=checkpoint(units, 1))
    with reserving(amount, credit=credit):
        completion = provider(replying(*seen)).complete(PROMPT)
    assert completion.charge == charged(units, credit)

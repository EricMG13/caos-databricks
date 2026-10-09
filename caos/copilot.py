"""GitHub Copilot as the model behind the one factory (D77, addendum 2).

AI Gateway is disabled in the enterprise workspace, so a model named
`copilot:<model>[@<effort>]` is answered by the GitHub Copilot runtime on the
machine the worker runs on. Copilot is only the model: CAOS keeps the run
order, the attempt ledger and the pin.

Whatever transport carries a call, its answer arrives as the runtime's session
events in their wire form, `{"type": ..., "data": {...}}` with the camelCase
keys `copilot.SessionEvent.to_dict()` writes (`github-copilot-sdk` 1.0.16),
and is shaped here into the `AIMessage` `models.ChatCompletions` prices,
bounds and refuses. A finish reason is stated only when the events witness
exactly the call asked for (the plan's re-spec, R1): every event type on an
allow-list, one answer and one settled model operation both naming the pinned
model, any usage agreeing, nothing auto-routed, BYOK, fused, tool-shaped,
truncated or compacted. Anything else keeps its bill and is refused as an
invalid response (F34).

The bill is in AI units (R2.3): the session's last usage checkpoint, in
nano-AIU, times the credit price the reservation was taken under, exact in
`Decimal` (invariant 7); any figure that is not a whole count the runtime
stated is an unknown charge, never a guess. A call whose events carry spend
or an answer is returned, never raised, so it is never a drop and never
re-attempted or re-sent (R2.10). No error's text travels: only a status, or
the runtime's own enum value for a failure it declared.

The SDK itself is imported only by the transport (Task 3), never here.
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal, DecimalException
from typing import Any, TypeIs

from langchain_core.messages import AIMessage
from langchain_core.messages.ai import UsageMetadata

from caos.pricing import exact_context
from caos.provider import MAX_COMPLETION_TOKENS, reported_charge
from caos.refusals import Refusal, RefusalCode
from caos.store.budget import validate_spend

PLATFORM = "copilot"
# The CLI fallback (D78): parsed so that it is never read as an endpoint, and
# refused at readiness while only the SDK transport is built (decision (a)).
CLI_PLATFORM = "copilot-cli"
_PLATFORMS = frozenset({PLATFORM, CLI_PLATFORM})
# `<platform>:<model>[@<effort>]`: the transport, the runtime's own model id,
# and the effort it is sent at, one of the runtime's levels. The effort is part
# of the name because the runtime applies a model's default effort when none
# is sent, and no identity may name an effort the model did not receive (AR-15).
_NAME = re.compile(
    r"(copilot|copilot-cli):([a-z0-9][a-z0-9.-]{0,127})"
    r"(?:@(low|medium|high|xhigh|max))?"
)
# One AI credit in nano-AIU: `creditsUsedNanoAiu` is "exact window
# consumption in non-negative integer nano-AIU" beside fractional credits.
# An assumption until the firm-seat spike measures it (R2, N177).
NANO_PER_CREDIT = 10**9
# A float from the wire is a whole count only below 2**53, where every integer
# is exactly representable (R2.3).
_MOST_UNITS = 2**53
# The finish reasons model families report, read in the one vocabulary
# `provider.finish_refusal` knows. Any other passes through unchanged and is
# refused there as an invalid response.
_FINISH = {
    "end_turn": "stop",
    "stop_sequence": "stop",
    "max_tokens": "length",
    "refusal": "content_filter",
}
# R1.0: the only event types a call may carry and still be the call asked for.
# Any other type keeps the bill and refuses the finish reason. Left out on
# purpose: `session.tools_updated`, which R1.0 admits "only with an empty tool
# list", because 1.0.16 types it with the model alone and no tool list, so the
# condition can never be shown (F556); the owner extends this list on the
# firm-seat spike's evidence only (R6, N177).
_ALLOWED = frozenset(
    {
        "session.start",
        "session.idle",
        "session.shutdown",
        "session.info",
        "session.warning",
        "session.title_changed",
        "session.usage_info",
        "session.usage_checkpoint",
        "session.model_change",
        "session.mcp_servers_loaded",
        "session.mcp_server_status_changed",
        "session.skills_loaded",
        "session.extensions_loaded",
        "session.custom_agents_updated",
        "session.managed_settings_resolved",
        "session.managed_settings_enforced",
        "user.message",
        "assistant.turn_start",
        "assistant.turn_end",
        "assistant.turn_retry",
        "assistant.idle",
        "assistant.reasoning",
        "assistant.message",
        "assistant.usage",
        "model.call_start",
        "model.call_finished",
        "model.call_final_result",
        "model.call_failure",
        "session.error",
        "prompt_cache_break",
    }
)
# R1.0's refusing names and prefixes, checked ahead of the allow-list so that
# no edit to it can admit one by mistake.
_REFUSING = (
    "session.auto_mode_resolved",
    "session.model_deselected",
    "auto_mode_switch.",
    "session.auto_tier_",
    "session.fusion_",
    "assistant.fusion_",
    "assistant.server_tool_progress",
    "tool.",
    "tool_search.activated",
    "skill.",
    "hook.",
    "sampling.",
    "external_tool.",
    "workflow.run_",
    "subagent.",
    "permission.",
    "user_input.",
    "elicitation.",
    "mcp.",
    "session.truncation",
    "session.compaction_",
    "session.context_cleared",
    "session.handoff",
    "session_limits_exhausted.",
    "session.completion_receipt",
    "session.binary_asset",
    "command.",
    "unknown",
)
# Events that can carry spend: a usage checkpoint must follow every one of them
# to be the session's whole bill, or the charge is unknown.
_BILLED = frozenset(
    {
        "assistant.message",
        "assistant.usage",
        "model.call_final_result",
        "model.call_failure",
        "model.call_finished",
    }
)

# One session event as the runtime writes it: `{"type": ..., "data": {...}}`.
Event = Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class CopilotModel:
    """One Copilot model: the transport that carries it, the runtime's id, and
    the effort it is sent at."""

    platform: str
    name: str
    reasoning_effort: str | None


def parsed(model: str) -> CopilotModel | None:
    """The Copilot model `model` names; None for any other name (a gateway
    endpoint). A name that claims a Copilot platform, in any case, and does not
    parse is refused, never read as an endpoint."""
    platform, colon, _rest = model.partition(":")
    if not colon or platform.strip().lower() not in _PLATFORMS:
        return None
    matched = _NAME.fullmatch(model)
    if matched is None:
        raise Refusal(RefusalCode.PROVIDER_NOT_CONFIGURED)
    return CopilotModel(matched.group(1), matched.group(2), matched.group(3))


def reply_message(seen: Sequence[Event], target: CopilotModel) -> AIMessage:
    """One call's events as the `AIMessage` `ChatCompletions` reads: the
    answer, the token counts, the call id, the AI units and premium requests
    of its bill (R2.4), and a finish reason only when the events witness
    exactly the call asked for (R1)."""
    answers = _data(seen, "assistant.message")
    usages = _data(seen, "assistant.usage")
    metadata: dict[str, Any] = {}
    claimed = _call_id(usages, answers)
    if claimed is not None:
        metadata["id"] = claimed
    if _witnessed(seen, usages, answers, target):
        finish = _finish_reason(usages, answers[0])
        if finish is not None:
            metadata["finish_reason"] = finish
    metadata.update(_bill(seen, answered=bool(answers)))
    content = answers[-1].get("content") if answers else None
    return AIMessage(
        content=content if isinstance(content, str) else "",
        response_metadata=metadata,
        usage_metadata=_usage(usages),
    )


def settled_charge(message: AIMessage, credit: Decimal | None) -> Decimal | None:
    """The call's charge in dollars: its nano-AIU at `credit`, the credit price
    its reservation was taken under, divided by `NANO_PER_CREDIT`, exactly
    (R2.3). Unknown when the message carries no whole AI-unit count or the
    reservation no positive credit price: the call is then billed unknown and
    its reservation kept, never charged a guess."""
    units = message.response_metadata.get("nano_aiu")
    if type(units) is not int or not 0 <= units < _MOST_UNITS:
        return None
    if not isinstance(credit, Decimal):
        return None
    try:
        validate_spend(credit)
    except Refusal:
        return None
    if not credit:
        return None
    exact = exact_context()
    try:
        amount = exact.divide(
            exact.multiply(Decimal(units), credit), Decimal(NANO_PER_CREDIT)
        )
    except DecimalException:
        return None
    return reported_charge(amount)


def _kind(event: Event) -> object:
    return event.get("type")


def _indexed(seen: Sequence[Event], kind: str) -> list[tuple[int, Mapping[str, Any]]]:
    """Where each event of one type sits, with its data; a malformed one is
    empty data, so whatever it carried is unknown rather than skipped."""
    return [
        (at, event["data"] if isinstance(event.get("data"), Mapping) else {})
        for at, event in enumerate(seen)
        if _kind(event) == kind
    ]


def _data(seen: Sequence[Event], kind: str) -> list[Mapping[str, Any]]:
    """The data of every event of one type, in order."""
    return [data for _at, data in _indexed(seen, kind)]


def _call_id(
    usages: Sequence[Mapping[str, Any]], answers: Sequence[Mapping[str, Any]]
) -> str | None:
    """R1.8: the usage's provider or API call id when a usage is present, else
    the message's API, request or service request id; the first that is a
    non-empty string. None leaves `ChatCompletions` to mint one."""
    names: tuple[str, ...]
    if usages:
        source, names = usages[-1], ("providerCallId", "apiCallId")
    elif answers:
        source, names = answers[-1], ("apiCallId", "requestId", "serviceRequestId")
    else:
        return None
    for name in names:
        claimed = source.get(name)
        if isinstance(claimed, str) and claimed:
            return claimed
    return None


def _witnessed(
    seen: Sequence[Event],
    usages: Sequence[Mapping[str, Any]],
    answers: Sequence[Mapping[str, Any]],
    target: CopilotModel,
) -> bool:
    """R1.0 to R1.7: every event admitted, one answer and one settled
    operation naming the pin, any usage agreeing, and the session ended."""
    return (
        all(_admitted(event, target) for event in seen)
        and _one_answer(answers, target)
        and _one_operation(seen, target)
        and _usage_agrees(usages, target)
        and _ended(seen)
    )


def _admitted(event: Event, target: CopilotModel) -> bool:
    """R1.0: an allow-listed type, never a refusing one, carrying no fusion
    attribution (a synthetic multi-model turn), and meeting its condition: a
    model change only to the pin, a server status only for no server, and a
    load of MCP servers, skills, extensions or custom agents only of none."""
    kind, data = event.get("type"), event.get("data")
    if not isinstance(kind, str) or not isinstance(data, Mapping):
        return False
    if kind.startswith(_REFUSING) or kind not in _ALLOWED:
        return False
    if data.get("fusion") is not None:
        return False
    if kind == "session.model_change":
        return data.get("newModel") == target.name
    if kind == "session.mcp_server_status_changed":
        return not data.get("serverName")
    loaded = _LOADS.get(kind)
    return loaded is None or _loaded_nothing(data.get(loaded))


# The loads R1.0 admits only when they loaded nothing, by the field they list.
_LOADS = {
    "session.mcp_servers_loaded": "servers",
    "session.skills_loaded": "skills",
    "session.extensions_loaded": "extensions",
    "session.custom_agents_updated": "agents",
}


def _loaded_nothing(loaded: object) -> bool:
    return isinstance(loaded, list) and not loaded


def _one_answer(answers: Sequence[Mapping[str, Any]], target: CopilotModel) -> bool:
    """R1.1 and R1.5: exactly one answer, naming the pin, with no tool request
    and no server tool (which can mean a second, advisor model)."""
    if len(answers) != 1:
        return False
    answer = answers[0]
    return (
        answer.get("model") == target.name
        and not answer.get("toolRequests")
        and answer.get("serverTools") is None
    )


def _one_operation(seen: Sequence[Event], target: CopilotModel) -> bool:
    """R1.2 and R1.6: exactly one settled model operation, a success on the
    pin stated not BYOK; every finished dispatch a success; no session error;
    and any failure before the settled result (the runtime's own recovery)."""
    finals = _indexed(seen, "model.call_final_result")
    if len(finals) != 1:
        return False
    settled_at, final = finals[0]
    if (
        final.get("model") != target.name
        or final.get("result") != "success"
        or final.get("isByok") is not False
    ):
        return False
    if any(
        data.get("outcome") != "success" for data in _data(seen, "model.call_finished")
    ):
        return False
    if _data(seen, "session.error"):
        return False
    return all(at < settled_at for at, _data_ in _indexed(seen, "model.call_failure"))


def _usage_agrees(usages: Sequence[Mapping[str, Any]], target: CopilotModel) -> bool:
    """R1.3: at most one usage; when present it and its CAPI witness name the
    pin, at the pinned effort, not auto-routed, stated not BYOK, offering no
    tool, and no content filter triggered."""
    if not usages:
        return True
    if len(usages) != 1:
        return False
    usage = usages[0]
    capi = usage.get("copilotUsage")
    return (
        usage.get("model") == target.name
        and (
            capi is None
            or (isinstance(capi, Mapping) and capi.get("model") == target.name)
        )
        and not usage.get("isAuto")
        and usage.get("isByok") is False
        and not usage.get("availableToolCount")
        and _effort(usage.get("reasoningEffort")) == target.reasoning_effort
        and usage.get("contentFilterTriggered") is not True
    )


def _ended(seen: Sequence[Event]) -> bool:
    """R1.7: the turn ended and then the session idled, never aborted."""
    idles = _indexed(seen, "session.idle")
    if not idles or any(data.get("aborted") is True for _at, data in idles):
        return False
    last_idle = idles[-1][0]
    return any(at < last_idle for at, _data_ in _indexed(seen, "assistant.turn_end"))


def _effort(reported: object) -> str | None:
    return (
        reported if isinstance(reported, str) and reported not in ("", "none") else None
    )


def _finish_reason(
    usages: Sequence[Mapping[str, Any]], answer: Mapping[str, Any]
) -> str | None:
    """The usage's finish reason in the provider vocabulary when a usage is
    present; else derived from the answer alone (R1.7)."""
    if not usages:
        return _derived_finish(answer)
    reason = usages[0].get("finishReason")
    if not isinstance(reason, str) or not reason:
        return None
    return _FINISH.get(reason, reason)


def _derived_finish(answer: Mapping[str, Any]) -> str:
    """R1.7: with no usage, `length` when the answer states output at least
    the cap (`MAX_COMPLETION_TOKENS`, which the SDK session sets), else `stop`.
    Nothing else is derived; the executor still validates the envelope."""
    output = answer.get("outputTokens")
    if type(output) is int and output >= MAX_COMPLETION_TOKENS:
        return "length"
    return "stop"


def _bill(seen: Sequence[Event], *, answered: bool) -> dict[str, Any]:
    """R2.3 and R2.4: `nano_aiu` when the checkpoint states a whole count the
    call can be charged on -- above zero once anything was answered -- and
    `premium_requests` as a decimal string or None. No checkpoint, no bill."""
    marks = _indexed(seen, "session.usage_checkpoint")
    if not marks:
        return {}
    bill: dict[str, Any] = {}
    units = _ai_units(seen, marks)
    if units is not None and (units > 0 or not answered):
        bill["nano_aiu"] = units
    bill["premium_requests"] = _premium(marks[-1][1].get("totalPremiumRequests"))
    return bill


def _ai_units(
    seen: Sequence[Event], marks: Sequence[tuple[int, Mapping[str, Any]]]
) -> int | None:
    """The session's AI units: its last checkpoint, which is cumulative. Every
    checkpoint must be a whole count, none below the one before it, the last
    after every event that can carry spend, and no smaller than the sum of the
    per-request figures; anything else is an unknown charge."""
    totals: list[int] = []
    for _at, data in marks:
        total = _whole_units(data.get("totalNanoAiu"))
        if total is None or (totals and total < totals[-1]):
            return None
        totals.append(total)
    if any(_kind(event) in _BILLED for event in seen[marks[-1][0] + 1 :]):
        return None
    requested = _per_request_units(_data(seen, "assistant.usage"))
    if requested is None or requested > totals[-1]:
        return None
    return totals[-1]


def _whole_units(value: object) -> int | None:
    """A whole, non-negative count below 2**53, from an int or an integral
    float; None for anything else (R2.3, R2.9)."""
    if isinstance(value, bool):
        return None
    if isinstance(value, float):
        if not value.is_integer():
            return None
        value = int(value)
    if isinstance(value, int) and 0 <= value < _MOST_UNITS:
        return value
    return None


def _per_request_units(usages: Sequence[Mapping[str, Any]]) -> Decimal | None:
    """The sum of the per-request `copilotUsage.totalNanoAiu` figures, exactly,
    or None when one is stated and is not a finite, non-negative number."""
    total = Decimal(0)
    for usage in usages:
        capi = usage.get("copilotUsage")
        if capi is None:
            continue
        figure = capi.get("totalNanoAiu") if isinstance(capi, Mapping) else None
        if not _finite_count(figure):
            return None
        total += Decimal(figure)  # exact: a float converts without rounding
    return total


def _finite_count(value: object) -> TypeIs[int | float]:
    return (
        isinstance(value, int | float)
        and not isinstance(value, bool)
        and math.isfinite(value)
        and value >= 0
    )


def _premium(value: object) -> str | None:
    """`totalPremiumRequests` as a decimal string (it can be fractional), never
    money: it goes on the bill line, and N123 reconciles it."""
    if not _finite_count(value):
        return None
    return str(Decimal(str(value)))


def _usage(usages: Sequence[Mapping[str, Any]]) -> UsageMetadata | None:
    """Every usage's tokens, or None when one did not state its input or output
    as a whole count. Prompt tokens read from or written to a cache are counted
    as input (Design 5). Not the bill (R2.4): `ChatCompletions` bounds them."""
    if not usages:
        return None
    prompt = output = 0
    try:
        for usage in usages:
            prompt += (
                _whole(usage.get("inputTokens"))
                + _whole(usage.get("cacheReadTokens") or 0)
                + _whole(usage.get("cacheWriteTokens") or 0)
            )
            output += _whole(usage.get("outputTokens"))
    except ValueError:
        return None
    return UsageMetadata(
        input_tokens=prompt, output_tokens=output, total_tokens=prompt + output
    )


def _whole(count: object) -> int:
    if isinstance(count, bool) or not isinstance(count, int) or count < 0:
        raise ValueError
    return count

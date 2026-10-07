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
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, TypeIs

from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.messages.ai import UsageMetadata
from langchain_core.outputs import ChatGeneration, ChatResult
from openai import OpenAIError

from caos.pricing import exact_context
from caos.provider import MAX_COMPLETION_TOKENS, TIMEOUT_SECONDS, reported_charge
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
_COUNT_DIGITS = len(str(_MOST_UNITS))
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
# The two allow-lists the bill rests on (F567, F568). An allow-list, never a
# deny-list: an event type the SDK adds later, or one this module never named,
# falls on the side that keeps the money safe.
#
# R2.10: the event types a call may hold and still be a drop -- one that spent
# nothing, which D110 may re-attempt. Each is documented by the SDK as metadata,
# telemetry or display: the session's start, the prompt, a turn's start and end,
# a dispatch's start, an error, an idle, an info or a warning, and
# managed-settings notices. Five more are quiet only as `_QUIET_WHEN` states
# (F567, F574). Any other type -- a delta, a sub-agent, a fusion, a compaction,
# a workflow -- means spend is possible: never a drop. So does any event a
# sub-agent wrote, and a dispatch that never finished.
_QUIET = frozenset(
    {
        "session.start",
        "user.message",
        "assistant.turn_start",
        "assistant.turn_end",
        "model.call_start",
        "session.error",
        "session.idle",
        "session.info",
        "session.warning",
        "session.managed_settings_resolved",
        "session.managed_settings_enforced",
    }
)
# R2.3: the event types that may follow the last checkpoint and leave it the
# session's whole bill -- its ending, and its shutdown summary. Any other type
# after it voids the settlement: the charge is unknown and the reservation is
# kept.
_SETTLING = frozenset({"session.idle", "session.error", "session.shutdown"})
# R1.7: the event types that may follow the end of the turn in the call asked
# for: the bill, the ending, the shutdown summary.
_AFTER_TURN = frozenset(
    {"session.usage_checkpoint", "session.idle", "session.shutdown"}
)
# `model.call_final_result.result` values that state an HTTP status (R1).
_RESULT_STATUS: Mapping[str | None, int] = {
    "http_400": 400,
    "http_413": 413,
    "http_429": 429,
}
# The values that declare a failure with no status (D110): a provider-stated
# 4xx or 5xx class. `transport_error` and `other_error` declare nothing.
_DECLARED_RESULTS = frozenset({"http_4xx", "http_5xx"})

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


class CopilotStatusError(OpenAIError):
    """A failed call with no spend and no answer, by its status alone, so
    `ChatCompletions` maps it as it maps a gateway status (`NEVER_RETRIED`, the
    429 re-send under the same reservation, D110's `DropKind`). A failure the
    runtime declared with no status carries `{"error": {"result": <value>}}`
    as its body, which `models._declared` reads as declared; no other failure
    carries a body. Its message is the platform's name and nothing else."""

    def __init__(self, status_code: int | None, *, declared: str | None = None) -> None:
        super().__init__(PLATFORM)
        self.status_code = status_code
        self.body: Mapping[str, Any] | None = (
            {"error": {"result": declared}}
            if status_code is None and declared in _DECLARED_RESULTS
            else None
        )


Ask = Callable[[str, CopilotModel, float], Sequence[Event]]


class ChatCopilot(BaseChatModel):
    """The chat model a Copilot name is answered by: one prompt, one call, one
    reply. `ask` is the transport: it sends the prompt to the pinned model
    within the deadline and returns the session's events."""

    model: str
    timeout: float = TIMEOUT_SECONDS
    ask: Ask

    @property
    def _llm_type(self) -> str:
        return PLATFORM

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: object,
    ) -> ChatResult:
        # `response_format` arrives in `kwargs` and is not sent (D77): the
        # canonical executor validates the envelope it asked for (invariant 9),
        # and the request is still priced as though it carried it. A stop
        # sequence cannot be sent, so a call asking for one is refused unsent.
        target = parsed(self.model)
        if target is None:
            raise Refusal(RefusalCode.PROVIDER_NOT_CONFIGURED)
        prompt = messages[-1].content if len(messages) == 1 else None
        if stop or not isinstance(prompt, str):
            raise Refusal(RefusalCode.PROVIDER_CALL_INVALID)
        seen = self.ask(prompt, target, self.timeout)
        if not _spent(seen):
            failed = _failure(seen)
            if failed is not None:
                raise failed
        message = reply_message(seen, target)
        return ChatResult(generations=[ChatGeneration(message=message)])


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
    metadata.update(_bill(seen, worked=_spent(seen)))
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
    exact = exact_context()
    # A price must charge every count exactly, or it prices none: one too
    # precise to multiply the largest count in the exact context would settle
    # a zero count and refuse every other (F564). Past this check the product
    # has at most `exact.prec` digits, and dividing by a power of ten only
    # moves its exponent, which `validate_spend` keeps far inside the
    # context's: neither operation can trap.
    if not credit or len(credit.as_tuple().digits) + _COUNT_DIGITS > exact.prec:
        return None
    amount = exact.divide(
        exact.multiply(Decimal(units), credit), Decimal(NANO_PER_CREDIT)
    )
    return reported_charge(amount)


def _kind(event: Event) -> str | None:
    """The event's type, or None when it is not text: so no membership test
    on a malformed type can raise (F577)."""
    kind = event.get("type")
    return kind if isinstance(kind, str) else None


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
    operation naming the pin, any usage agreeing, the session's own statements
    agreeing, and the session ended."""
    return (
        all(_admitted(event, target) for event in seen)
        and _one_answer(answers, target)
        and _one_operation(seen, target)
        and _usage_agrees(usages, target)
        and _session_agrees(seen, usages, target)
        and _ended(seen)
    )


def _admitted(event: Event, target: CopilotModel) -> bool:
    """R1.0: an allow-listed type, never a refusing one, carrying no fusion
    attribution (a synthetic multi-model turn) and no sub-agent's envelope,
    every field agreeing with the pin (`_fields_agree`; a model change only to
    the pin among them), and meeting its type's condition (`_condition_holds`)."""
    kind, data = event.get("type"), event.get("data")
    if not isinstance(kind, str) or not isinstance(data, Mapping):
        return False
    if kind.startswith(_REFUSING) or kind not in _ALLOWED:
        return False
    if data.get("fusion") is not None or event.get("agentId") is not None:
        return False
    return _fields_agree(data, target) and _condition_holds(kind, data)


def _condition_holds(kind: str, data: Mapping[str, Any]) -> bool:
    """R1.0's conditions by type: a server status only for no server; a
    dispatch failure only of the top-level agent's own call (F575); a model
    change only from a source that is no runtime, agent or plan-mode choice, a
    session start and a dispatch only naming their model (F580); a load of
    MCP servers, skills, extensions or custom agents only of none."""
    if kind == "session.mcp_server_status_changed":
        return not data.get("serverName")
    if kind == "model.call_failure":
        return data.get("source") == "top_level"
    if kind == "session.model_change":
        source = data.get("source")
        return (source is None or isinstance(source, str)) and source in _CHOSEN
    named = _NAMING.get(kind)
    if named is not None:
        return data.get(named) is not None
    loaded = _LOADS.get(kind)
    return loaded is None or _loaded_nothing(data.get(loaded))


def _fields_agree(data: Mapping[str, Any], target: CopilotModel) -> bool:
    """F569: every field, at any depth, that names a model, an effort, an auto
    tier, an agent, a tool or an initiator agrees with the call asked for. The
    rule is read from the field's name, so a field the SDK adds later in one of
    these families is held to it too, a field about the past (`previous*`,
    `modelFrom`) among them: a model the session moved from may have answered
    part of the call (F580)."""
    for key, value in data.items():
        rule = _FIELD_RULES.get(_family(key))
        if rule is not None:
            if not rule(value, target):
                return False
        elif not _nested_agree(value, target):
            return False
    return True


def _nested_agree(value: object, target: CopilotModel) -> bool:
    if isinstance(value, Mapping):
        return _fields_agree(value, target)
    if isinstance(value, list):
        return all(_nested_agree(item, target) for item in value)
    return True


def _family(key: str) -> str | None:
    """The family a field's name puts it in, or None for any other field."""
    named = _NAMED_FIELDS.get(key)
    if named is not None:
        return named
    if key.endswith(("Model", "ModelId")):
        return "model"
    if key.endswith("Models"):
        return "models"
    if key.endswith("Effort"):
        return "effort"
    if key.endswith("AutoTier") or key.startswith(("agent", "tool")):
        return "absent"
    if any(part in key for part in ("Agent", "ubagent", "Tool")):
        return "absent"
    return None


# Fields held by their exact name (F569, F575, F580). `interactionType` is a
# free string whose expected value no source states, so any stated one refuses
# until the firm-seat spike records it (N182). `modelFrom` is held to the pin:
# an unnamed dispatch before the cache broke may have run on it (F580).
_NAMED_FIELDS = {
    "model": "model",
    "modelId": "model",
    "modelTo": "model",
    "modelFrom": "model",
    "models": "models",
    "effort": "effort",
    "agentMode": "mode",
    "mode": "mode",
    "initiator": "initiator",
    "isByok": "byok",
    "isAuto": "absent",
    "autoTier": "absent",
    "interactionType": "absent",
    "containsBuiltInFileEditRequest": "absent",
}


def _is_the_pin(value: object, target: CopilotModel) -> bool:
    return value is None or value == target.name


def _only_the_pin(value: object, target: CopilotModel) -> bool:
    return value is None or (
        isinstance(value, list) and all(item == target.name for item in value)
    )


def _at_the_effort(value: object, target: CopilotModel) -> bool:
    return value is None or _effort(value) == target.reasoning_effort


def _interactive(value: object, target: CopilotModel) -> bool:
    return value in (None, "interactive")


def _by_the_user(value: object, target: CopilotModel) -> bool:
    return value in (None, "user")


def _absent(value: object, target: CopilotModel) -> bool:
    return not value


def _not_byok(value: object, target: CopilotModel) -> bool:
    return value is not True


_FIELD_RULES: Mapping[str | None, Callable[[object, CopilotModel], bool]] = {
    "model": _is_the_pin,
    "models": _only_the_pin,
    "effort": _at_the_effort,
    "mode": _interactive,
    "initiator": _by_the_user,
    "byok": _not_byok,
    "absent": _absent,
}


# F580: the `ModelChangeSource` values a model change may state -- a user's, a
# policy's, startup's or the SDK caller's (this host's) choice -- or none.
# Refused: `automatic` ("rate-limit recovery or refusal fallback"), `agent` (an
# agent's configured model), `plan_mode`, `auto_tier_recommendation` (a
# CAPI-issued Auto tier), and any value the SDK adds later.
_CHOSEN = frozenset(
    {
        None,
        "model_command",
        "settings_command",
        "config_command",
        "model_picker",
        "changeboarding_shortcut",
        "managed_settings",
        "repo_settings",
        "startup",
        "sdk",
    }
)
# F580: the events that must name their model, not merely not contradict the
# pin. A start that selects none "resolves a default as though the user had
# never chosen a model" (`session.model_deselected`), and a dispatch is the unit
# that spends, which the settled result alone does not witness: one "may include
# internal reconnect or fallback work".
_NAMING = {"session.start": "selectedModel", "model.call_start": "model"}

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
    """R1.1 and R1.5: exactly one answer, naming the pin, and whole: one chunk
    of one, if chunked at all (F563). A server tool, which can mean a second,
    advisor model, refuses as any `*Tool*` field does (`_fields_agree`)."""
    if len(answers) != 1:
        return False
    answer = answers[0]
    return (
        answer.get("model") == target.name
        and answer.get("chunkCount") in (None, 1)
        and answer.get("chunkIndex") in (None, 0)
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
    pin, at the pinned effort -- stated, not merely not contradicted -- stated
    not BYOK, and no content filter triggered. Auto routing, tools and the
    initiator are held by `_fields_agree` (F561, F569)."""
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
        and usage.get("isByok") is False
        and _effort(usage.get("reasoningEffort")) == target.reasoning_effort
        and usage.get("contentFilterTriggered") is not True
    )


def _session_agrees(
    seen: Sequence[Event], usages: Sequence[Mapping[str, Any]], target: CopilotModel
) -> bool:
    """F561, F562, F563 (AR-15): the session's start and every model change
    state the pinned effort, an unstated one included (auto tiers are held by
    `_fields_agree`); with no usage to witness the effort, the session's start
    must. One prompt only:
    a single user message, no autopilot continuation. Any shutdown is routine,
    on the pin alone."""
    stated = [*_data(seen, "session.start"), *_data(seen, "session.model_change")]
    if not usages and not _data(seen, "session.start"):
        return False
    if any(
        _effort(data.get("reasoningEffort")) != target.reasoning_effort
        for data in stated
    ):
        return False
    prompts = _data(seen, "user.message")
    if len(prompts) > 1 or any(data.get("isAutopilotContinuation") for data in prompts):
        return False
    return all(
        _shutdown_agrees(data, target) for data in _data(seen, "session.shutdown")
    )


def _shutdown_agrees(data: Mapping[str, Any], target: CopilotModel) -> bool:
    """F562: a routine shutdown whose model metrics name only the pin."""
    metrics = data.get("modelMetrics")
    return (
        data.get("shutdownType") == "routine"
        and isinstance(metrics, Mapping)
        and all(model == target.name for model in metrics)
    )


def _ended(seen: Sequence[Event]) -> bool:
    """R1.7: exactly one turn, which ended, nothing but `_AFTER_TURN` followed it -- no
    reasoning, no dispatch, no answer after the end or after an idle (F560,
    F563, F568) -- and then the session idled, never aborted."""
    idles = _indexed(seen, "session.idle")
    ends = _indexed(seen, "assistant.turn_end")
    if len(ends) != 1 or len(_data(seen, "assistant.turn_start")) != 1:
        return False  # one prompt, one turn (F570)
    if not idles or any(data.get("aborted") is True for _at, data in idles):
        return False
    last_end = ends[-1][0]
    return last_end < idles[-1][0] and all(
        _kind(event) in _AFTER_TURN for event in seen[last_end + 1 :]
    )


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


def _bill(seen: Sequence[Event], *, worked: bool) -> dict[str, Any]:
    """R2.3 and R2.4: `nano_aiu` when the checkpoint states a whole count the
    call can be charged on -- above zero once the call may have spent, any event
    off the quiet allow-list (F560, F567) --
    and `premium_requests` as a decimal string or None. No checkpoint, no
    bill."""
    marks = _indexed(seen, "session.usage_checkpoint")
    if not marks:
        return {}
    bill: dict[str, Any] = {}
    units = _ai_units(seen, marks)
    if units is not None and (units > 0 or not worked):
        bill["nano_aiu"] = units
    bill["premium_requests"] = _premium(marks[-1][1].get("totalPremiumRequests"))
    return bill


def _ai_units(
    seen: Sequence[Event], marks: Sequence[tuple[int, Mapping[str, Any]]]
) -> int | None:
    """The session's AI units: its last checkpoint, which is cumulative. Every
    checkpoint must be a whole count, none below the one before it; the last
    must be settled -- every dispatch finished, no work after it, the session
    ended after it, nothing aborted (F560, F568, F573) -- and no spend figure
    the session states anywhere may exceed it, nor any be a sub-agent's, which
    cannot be reconciled with it (F558, F562, F572). Anything else is an
    unknown charge: never the lower figure."""
    totals: list[int] = []
    for _at, data in marks:
        total = _whole_units(data.get("totalNanoAiu"))
        if total is None or (totals and total < totals[-1]):
            return None
        totals.append(total)
    premium = marks[-1][1].get("totalPremiumRequests")
    if not _settled_after(seen, marks[-1][0]) or not _figures_agree(
        seen, totals[-1], premium
    ):
        return None
    return totals[-1]


def _settled_after(seen: Sequence[Event], at: int) -> bool:
    """F568: the checkpoint at `at` is the session's whole bill only if every
    dispatch started before it had closed, only `_SETTLING` events follow it
    -- no error that leaves the runtime free to switch model and go on -- and
    the session ended after it, a `session.idle` or a `session.error`, with no
    idle anywhere aborted."""
    after = seen[at + 1 :]
    if _dispatch_open(seen[:at]) or not all(_settles(event) for event in after):
        return False
    if any(data.get("aborted") is True for data in _data(seen, "session.idle")):
        return False
    return any(_kind(event) in ("session.idle", "session.error") for event in after)


def _settles(event: Event) -> bool:
    data = event.get("data")
    if _kind(event) not in _SETTLING or not isinstance(data, Mapping):
        return False
    return data.get("eligibleForAutoSwitch") is not True


def _dispatch_open(seen: Sequence[Event]) -> bool:
    """Whether a `model.call_start` has no `model.call_finished` closing it: a
    dispatch still running. Only the finish closes one -- "the final lifecycle
    outcome for one logical model dispatch" -- while a `model.call_failure` is
    one attempt's telemetry, and a sub-agent's at that (F573)."""
    running = 0
    for event in seen:
        kind = _kind(event)
        if kind == "model.call_start":
            running += 1
        elif kind == "model.call_finished":
            running = max(running - 1, 0)
    return running > 0


def _figures_agree(seen: Sequence[Event], total: int, premium: object) -> bool:
    """F558, F562, F572, F579: no sub-agent's spend anywhere; the per-request
    figures of every event (`_requests`) sum to no more than `total`; every
    spend figure any event states (`_unit`), at any depth, is no more than
    `total` -- premium requests no more than the checkpoint's `premium`; and a
    shutdown's session total, when stated, is exactly `total`, its per-model
    figures summing to no more."""
    if any(_sub_agent(event) for event in seen):
        return False
    requested = _summed(_requests(seen))
    if requested is None or requested > total:
        return False
    # The checkpoints are walked too: being cumulative, none states more than
    # the last, so a premium-request count that falls is no running total.
    stated = [
        (key, value) for event in seen for key, value in _pairs(event.get("data"))
    ]
    if not all(_within(key, value, total, premium) for key, value in stated):
        return False
    return all(
        _shutdown_figures_agree(data, total) for data in _data(seen, "session.shutdown")
    )


def _requests(seen: Sequence[Event]) -> list[object]:
    """F579: every per-request spend block the session states, each a separate
    request, so they are summed: each CAPI `copilotUsage` ("per-request cost and
    usage data") at any depth of any event -- an answer's usage, a compaction's
    -- and each fusion phase's `usage` ("concrete-model usage for one
    HydraFusion phase"). Aggregates of these (a fusion turn's total, the
    shutdown's) are held alone (`_within`), never added to them."""
    blocks: list[object] = []
    for event in seen:
        data = event.get("data")
        blocks += [item for key, item in _pairs(data) if key == "copilotUsage"]
        if _kind(event) in _PHASES and isinstance(data, Mapping):
            blocks.append(data.get("usage"))
    return [block for block in blocks if block is not None]


_PHASES = frozenset(
    {"assistant.fusion_phase_completed", "assistant.fusion_phase_failed"}
)


def _pairs(value: object) -> list[tuple[str, object]]:
    """Every field of `value`, at any depth, as (name, value)."""
    found: list[tuple[str, object]] = []
    if isinstance(value, Mapping):
        for key, item in value.items():
            found.append((key, item))
            found += _pairs(item)
    elif isinstance(value, list):
        for item in value:
            found += _pairs(item)
    return found


def _unit(key: str) -> str | None:
    """The unit a spend figure's name states (F572): nano-AIU, AI credits used,
    or premium requests. None for any other field, a credit cap (`max*`,
    `declaredMax*`) or grant (`additional*`) among them; `cost` states no unit
    (R2 names it experimental) and is not read."""
    if key.endswith("NanoAiu"):
        return "nano"
    if key.endswith("AiCredits") and key.startswith("used"):
        return "credits"
    if key.endswith("PremiumRequests"):
        return "premium"
    return None


def _within(key: str, value: object, total: int, premium: object) -> bool:
    """A stated figure no more than the bill, in its own unit; any field that
    is no spend figure holds trivially."""
    unit = _unit(key)
    if unit is None:
        return True
    if not _finite_count(value):
        return False
    if unit == "nano":
        return Decimal(value) <= total
    if unit == "credits":
        return Decimal(value) * NANO_PER_CREDIT <= total
    return not value or (_finite_count(premium) and Decimal(value) <= Decimal(premium))


def _sub_agent(event: Event) -> bool:
    """F568, F572: an event that is or states a sub-agent's work -- written by
    one (`agentId`), a sub-agent's or a workflow's own event, or one carrying
    `agentMetrics`, `consumedSubagents` or a workflow's `consumedNanoAiu`."""
    kind = _kind(event)
    if event.get("agentId") is not None:
        return True
    if kind is not None and kind.startswith(("subagent.", "workflow.")):
        return True
    return any(
        key == "consumedNanoAiu" or (key in _SUB_AGENT_FIELDS and value)
        for key, value in _pairs(event.get("data"))
    )


_SUB_AGENT_FIELDS = frozenset({"agentMetrics", "consumedSubagents"})


def _shutdown_figures_agree(data: Mapping[str, Any], total: int) -> bool:
    stated = data.get("totalNanoAiu")
    if stated is not None and _whole_units(stated) != total:
        return False
    metrics = data.get("modelMetrics")
    metered = _summed(list(metrics.values())) if isinstance(metrics, Mapping) else None
    return metered is not None and metered <= total


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


def _summed(blocks: Sequence[object]) -> Decimal | None:
    """The sum of the `totalNanoAiu` figures of these blocks (per-request CAPI
    usage, or a shutdown's per-model metrics), exactly; a block that states
    none adds nothing. None when a block is not an object, or its figure is
    not a finite, non-negative number."""
    total = Decimal(0)
    for block in blocks:
        if not isinstance(block, Mapping):
            return None
        figure = block.get("totalNanoAiu")
        if figure is None:
            continue
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


def _spent(seen: Sequence[Event]) -> bool:
    """R2.10, F567, F574: whether the session can have cost anything -- any
    event off the quiet allow-list, or a dispatch that never finished. Such a
    call is returned and billed, never raised: it is no drop, so it is never
    re-attempted or re-sent (invariants 6 and 8; D110)."""
    return not all(_quiet(event) for event in seen) or _dispatch_open(seen)


def _quiet(event: Event) -> bool:
    """One event on R2.10's allow-list: no sub-agent's (`agentId`), readable,
    and a `_QUIET` type or one `_QUIET_WHEN` admits."""
    kind, data = _kind(event), event.get("data")
    if not isinstance(data, Mapping) or event.get("agentId") is not None:
        return False
    if kind in _QUIET:
        return True
    condition = _QUIET_WHEN.get(kind)
    return condition is not None and condition(data)


def _failed_result(data: Mapping[str, Any]) -> bool:
    result = data.get("result")
    return isinstance(result, str) and result != "success"


def _failed_finish(data: Mapping[str, Any]) -> bool:
    """F578: only `error` -- "a provider or transport error" -- may close a
    dispatch with nothing spent. `rejected` follows a provider response ("rejected
    during post-response acceptance processing") and `cancelled` may follow a
    streamed one, so either is spend."""
    return data.get("outcome") == "error"


def _own_failure(data: Mapping[str, Any]) -> bool:
    return data.get("source") == "top_level"


def _zero_checkpoint(data: Mapping[str, Any]) -> bool:
    return _stated_zero(data.get("totalNanoAiu")) and _none_or_zero(
        data.get("totalPremiumRequests")
    )


def _empty_shutdown(data: Mapping[str, Any]) -> bool:
    return (
        data.get("modelMetrics") == {}
        and not data.get("agentMetrics")
        and _none_or_zero(data.get("totalNanoAiu"))
        and _none_or_zero(data.get("totalPremiumRequests"))
    )


def _none_or_zero(value: object) -> bool:
    return value is None or _stated_zero(value)


# The types quiet only on a condition (F567, F574, F578): a settled result naming
# a failure; a dispatch's finish in `error` (it closes the dispatch);
# the top-level agent's own failed attempt; a checkpoint stating zero AI units
# and no premium request; a shutdown that metered no model and no agent and
# states no spend.
_QUIET_WHEN: Mapping[str | None, Callable[[Mapping[str, Any]], bool]] = {
    "model.call_final_result": _failed_result,
    "model.call_finished": _failed_finish,
    "model.call_failure": _own_failure,
    "session.usage_checkpoint": _zero_checkpoint,
    "session.shutdown": _empty_shutdown,
}


def _stated_zero(value: object) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool) and value == 0


def _failure(seen: Sequence[Event]) -> Exception | None:
    """R1's errors, for a call with no spend and no work (`_spent` is False, so
    no settled result or dispatch succeeded): an aborted session
    or one that never ended is indeterminate (`TimeoutError`); otherwise the
    status a session error states, else an API failure's, else the settled
    result's. A transport failure declares nothing. A session that idled with
    no error is None: it is refused as an invalid response, not raised."""
    if any(data.get("aborted") is True for data in _data(seen, "session.idle")):
        return TimeoutError()
    errors = _data(seen, "session.error")
    failure = _open_failure(seen)
    stated = _status_of(errors[-1]) if errors else None
    if stated is None and failure is not None:
        if failure.get("failureKind") != "api":
            return CopilotStatusError(None)
        stated = _status_of(failure)
    if stated is not None:
        return CopilotStatusError(stated)
    settled = _settled_result(seen)
    if errors or failure is not None or settled is not None:
        return _from_result(settled)
    return None if _data(seen, "session.idle") else TimeoutError()


def _open_failure(seen: Sequence[Event]) -> Mapping[str, Any] | None:
    """The last `model.call_failure`. On a call with no spend, no settled
    result succeeded, so none was recovered from."""
    failures = _data(seen, "model.call_failure")
    return failures[-1] if failures else None


def _settled_result(seen: Sequence[Event]) -> str | None:
    """The last settled result's name. On a call with no spend every settled
    result is quiet, so each names a failure (`_quiet`)."""
    finals = _data(seen, "model.call_final_result")
    result: str | None = finals[-1].get("result") if finals else None
    return result


def _status_of(data: Mapping[str, Any]) -> int | None:
    status = data.get("statusCode")
    return status if type(status) is int else None


def _from_result(settled: str | None) -> CopilotStatusError:
    """A settled result with no status from any event: the status it names, a
    declared class with none, or undeclared."""
    status = _RESULT_STATUS.get(settled)
    if status is not None:
        return CopilotStatusError(status)
    return CopilotStatusError(None, declared=settled)


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

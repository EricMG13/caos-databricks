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

import re
from dataclasses import dataclass
from decimal import Decimal, DecimalException

from langchain_core.messages import AIMessage

from caos.pricing import exact_context
from caos.provider import reported_charge
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

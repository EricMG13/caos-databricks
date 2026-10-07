#!/usr/bin/env python3
"""One real call through the production model path (A31): AI Gateway or Copilot.

Builds the provider exactly as the worker does -- `caos.models.completions`
with no injected chat model, so the chat model is `ChatDatabricks` on the
configured endpoint under the SDK's unified auth -- sends one short prompt,
and prints the endpoint, the chat model class, the response id and the token
usage. For a Copilot model the chat model is `ChatCopilot` on its real
transport (D77), never a scripted one; both calls run under a reservation at
the pinned credit price, and the charge printed is the plain call's AI
units, printed beside them, at that price. Exits nonzero unless the class
is one of those two and the call answered: an injected or scripted model can never make this pass. No secret
is read by this script and none is printed.
"""

from __future__ import annotations

import json
import sys
from contextlib import AbstractContextManager, nullcontext
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from langchain_core.messages import AIMessage

    from caos.models import ChatCompletions

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

PROMPT = "Reply with the single word OK."
# The second call is the production seam in JSON mode (F27): an endpoint
# that rejects `response_format` fails here, not on the first module call.
JSON_PROMPT = 'Reply with exactly this JSON object: {"ok": true}'


def main() -> int:
    from langchain_core.messages import HumanMessage

    from caos import copilot
    from caos.models import from_environment

    provider = from_environment()
    chat = provider.chat
    kind = type(chat).__name__
    # The production model only: `ChatDatabricks` on an endpoint, or
    # `ChatCopilot` on the SDK transport, never a scripted one.
    production = kind == "ChatDatabricks" or (
        isinstance(chat, copilot.ChatCopilot) and chat.ask is copilot.ask_copilot
    )
    if not production:
        print(f"gateway_smoke: refused, chat model is {kind}", file=sys.stderr)
        return 2
    with _reserved(provider):
        message = chat.invoke([HumanMessage(content=PROMPT)])
        completion = provider.complete(JSON_PROMPT, json_object=True)
        charge = _charged(provider, message, completion.charge)
    usage: dict[str, object] = dict(message.usage_metadata or {})
    # The answer is parsed here, not only accepted (AR-17): JSON mode that
    # the endpoint takes and ignores would otherwise pass the smoke and fail
    # the first module call.
    if completion.refusal is not None:
        json_mode = completion.refusal.name
    elif _json_object(completion.content):
        json_mode = "accepted"
    else:
        json_mode = "not JSON"
    print(
        "gateway_smoke: endpoint={endpoint} model={kind} response_id={rid} "
        "input_tokens={i} output_tokens={o} charge={charge} nano_aiu={nano} "
        "json_mode={json_mode}".format(
            endpoint=provider.model,
            kind=kind,
            rid=message.id or message.response_metadata.get("id"),
            i=usage.get("input_tokens"),
            o=usage.get("output_tokens"),
            charge=charge if isinstance(charge, Decimal) else "unknown",
            nano=message.response_metadata.get("nano_aiu", "-"),
            json_mode=json_mode,
        )
    )
    answered = isinstance(message.content, str | list)
    return 0 if answered and json_mode == "accepted" else 1


def _reserved(provider: ChatCompletions) -> AbstractContextManager[None]:
    """For a Copilot model, the reservation its calls run under, as the
    executor's are (R2.4): the JSON call's bound at the pinned price, and the
    credit price its AI units are charged at, or `PROVIDER_NOT_CONFIGURED`.
    A gateway endpoint's calls are charged on tokens and need none."""
    from caos import copilot
    from caos.pricing import priced_request
    from caos.provider import reserving

    if copilot.parsed(provider.model) is None:
        return nullcontext()
    sent = provider.request_bytes(JSON_PROMPT, json_object=True)
    return reserving(
        priced_request(provider.price, len(sent)),
        credit=copilot.credit_price().per_credit,
    )


def _charged(
    provider: ChatCompletions, message: AIMessage, json_charge: Decimal | None
) -> Decimal | None:
    """The charge printed, of one call (F604): for a Copilot model the plain
    call's AI units, printed beside it, at the reservation's credit price; for
    a gateway endpoint, which states no AI units, the JSON call's, as before."""
    from caos import copilot
    from caos.provider import reserved_credit

    if copilot.parsed(provider.model) is None:
        return json_charge
    return copilot.settled_charge(message, reserved_credit.get())


def _json_object(text: str | None) -> bool:
    try:
        return isinstance(json.loads(text or ""), dict)
    except ValueError:
        return False


if __name__ == "__main__":
    sys.exit(main())

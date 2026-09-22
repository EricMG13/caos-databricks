#!/usr/bin/env python3
"""One real call through Databricks AI Gateway, on the production path (A31).

Builds the provider exactly as the worker does -- `caos.models.completions`
with no injected chat model, so the chat model is `ChatDatabricks` on the
configured endpoint under the SDK's unified auth -- sends one short prompt,
and prints the endpoint, the chat model class, the response id and the token
usage. Exits nonzero unless the class is `ChatDatabricks` and the call
answered: an injected or scripted model can never make this pass. No secret
is read by this script and none is printed.
"""

from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

PROMPT = "Reply with the single word OK."


def main() -> int:
    from langchain_core.messages import HumanMessage

    from caos.models import from_environment

    provider = from_environment()
    chat = provider.chat
    kind = type(chat).__name__
    if kind != "ChatDatabricks":
        print(f"gateway_smoke: refused, chat model is {kind}", file=sys.stderr)
        return 2
    message = chat.invoke([HumanMessage(content=PROMPT)])
    usage: dict[str, object] = dict(message.usage_metadata or {})
    charge = provider.complete(PROMPT).charge
    print(
        "gateway_smoke: endpoint={endpoint} model={kind} response_id={rid} "
        "input_tokens={i} output_tokens={o} charge={charge}".format(
            endpoint=provider.model,
            kind=kind,
            rid=message.id or message.response_metadata.get("id"),
            i=usage.get("input_tokens"),
            o=usage.get("output_tokens"),
            charge=charge if isinstance(charge, Decimal) else "unknown",
        )
    )
    return 0 if isinstance(message.content, str | list) else 1


if __name__ == "__main__":
    sys.exit(main())

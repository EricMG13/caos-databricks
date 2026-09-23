"""The provider seam: one prompt in, one `Completion` out, a closed set of refusals.

What the canonical executor depends on and nothing more. The transport that
answers lives behind `caos/models.py` (Databricks AI Gateway through the one
model factory); this module holds the shape both sides agree on: the request
and response ceilings, the request bytes a call is priced on, the refusal a
finish reason maps to, and the rule that a charge is exact known money or
unknown -- never a float, never a guess (invariant 7).

Nothing here quotes a response. A completion echoes the prompt and the prompt
carries evidence, so a refusal that included the body -- or a vendor's error
string, which often contains it -- would be the leak `caos/refusals.py` exists
to prevent.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Protocol

from caos.refusals import Refusal, RefusalCode
from caos.store.budget import validate_spend

# The most one non-streamed call may take to answer: nothing arrives until
# generation ends, so this is the generation budget (MX-4), sized inside the
# 300 s lease with room to bill and accept. `MAX_COMPLETION_TOKENS` is what
# the reservation covers, not what this deadline promises to deliver.
TIMEOUT_SECONDS = 240.0
# Host resource ceilings, not guarantees that every canonical handoff fits.
# Oversized requests/responses refuse; no prefix is accepted as a whole answer.
MAX_REQUEST_BYTES = 1_048_576
MAX_RESPONSE_BYTES = 4_194_304
MAX_COMPLETION_TOKENS = 65_536

# A call that cannot succeed by being repeated. Retrying one of these spends a
# second reservation on the same certain failure.
NEVER_RETRIED = frozenset({400, 401, 402, 403, 404, 413, 422})
# A call whose outcome is unknown. The attempt stays indeterminate and keeps its
# reservation, because it may have reached the provider and may be billed.
TRANSIENT = frozenset({408, 429})

_FINISH_REFUSALS = {
    "length": RefusalCode.PROVIDER_OUTPUT_TRUNCATED,
    "content_filter": RefusalCode.PROVIDER_REFUSED,
}


def finish_refusal(finish_reason: str) -> RefusalCode | None:
    """The refusal a finish reason carries; `None` for a completed answer.

    `stop` is the one completed reason. Anything unnamed here is a response
    the host does not understand, which is invalid rather than accepted.
    """
    if finish_reason == "stop":
        return None
    return _FINISH_REFUSALS.get(finish_reason, RefusalCode.PROVIDER_RESPONSE_INVALID)


@dataclass(frozen=True, slots=True)
class Completion:
    """Independent call facts beside usable content or an analytical refusal.

    None is unknown, never zero. Failed analytical content is discarded.
    A returned refusal describes a call; pre-send rejection raises Refusal.
    """

    content: str | None = field(repr=False)
    charge: Decimal | None
    generation_id: str | None = field(repr=False)
    refusal: RefusalCode | None = None


class CompletionProvider(Protocol):
    """Anything that can answer a prompt with a `Completion`.

    Named for what it returns rather than for who implements it: the module
    executor depends on this, and `caos/graph/runtime.py`'s `Provider` is a
    different shape for a different job -- one takes a prompt, the other takes a
    route node. Keeping them apart is what stops a test double for one being
    accepted where the other was meant.
    """

    @property
    def model(self) -> str:
        """The identity the host configured -- the endpoint name -- which is
        the identity that answers: the gateway routes one endpoint to one
        model and this host configures no fallback.

        Read from here rather than from the response body: a model naming
        itself is a claim, and invariant 3 says the host owns identity.

        A property rather than a plain annotation, so a frozen implementer
        satisfies it.
        """

    def complete(self, prompt: str, *, json_object: bool = False) -> Completion: ...

    def request_bytes(self, prompt: str, *, json_object: bool = False) -> bytes:
        """The whole encoded request `complete` would send for this prompt.

        Pure: no call, no credential. What a caller bounds against
        `MAX_REQUEST_BYTES` before reserving, so the ceiling it meets is the
        one the provider enforces rather than the prompt's share of it.
        """
        ...


def encode_request(model: str, prompt: str, *, json_object: bool = False) -> bytes:
    """The chat-completions body one prompt becomes: the bytes a call is
    measured, bounded and priced on (Task 8.2), whichever transport sends it."""
    request: dict[str, Any] = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
        "max_completion_tokens": MAX_COMPLETION_TOKENS,
    }
    if json_object:
        request["response_format"] = {"type": "json_object"}
    return json.dumps(request).encode("utf-8")


def reported_charge(value: object) -> Decimal | None:
    """Exact known money within the ledger's envelope, or unknown."""
    if type(value) is int:
        value = Decimal(value)
    if isinstance(value, Decimal):
        try:
            validate_spend(value)
        except Refusal:
            return None
        return value
    return None

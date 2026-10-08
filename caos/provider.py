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
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from decimal import Decimal
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Protocol

from caos.refusals import Refusal, RefusalCode
from caos.store.budget import validate_spend

# How an unanswered call ended (D110): the ledger's vocabulary, so it lives
# with the store that records it and is named here for the seam that says it.
from caos.store.outcomes import DropKind as DropKind

if TYPE_CHECKING:
    from caos.pricing import ModelPrice

# The most one `complete` may take, every rate-limit re-send and wait included
# (ST-9): nothing arrives until generation ends, so this is the generation
# budget (MX-4), sized inside the 600 s lease (`caos.store.work.LEASE_SECONDS`).
# The 180 s that remain are a liveness budget, not a safety invariant: the
# reservation renews the lease just before the call, but the same 180 s also
# cover the work before it (the call check, reading upstreams and evidence,
# the re-encode) and after it (the bill, the answer's checks, the fenced
# acceptance). A lease lost anyway pays nothing twice: exactly-once rests on
# `call_hold`, `_UNSETTLED` and `replay_billed` (D83).
# 420 s since D83: 5 of 19 default-tier calls ran past 240 s on 2 October.
# `MAX_COMPLETION_TOKENS` is what the reservation covers, not what this
# deadline promises to deliver.
TIMEOUT_SECONDS = 420.0
# Host resource ceilings, not guarantees that every canonical handoff fits.
# Oversized requests/responses refuse; no prefix is accepted as a whole answer.
# 4 MiB, not the legacy 1 MiB (D29, N31): the catalog's widest node carries
# about 1 MiB of authority and upstream sections at their bound, so under the
# legacy ceiling a FULL route with real handoffs refused at CP-5 by
# construction. Claude on the gateway carries a 1M-token context, and the
# one-token-per-byte reservation still over-counts, so the bound holds.
MAX_REQUEST_BYTES = 4_194_304
MAX_RESPONSE_BYTES = 4_194_304
MAX_COMPLETION_TOKENS = 65_536

# D116 (N157): the transport ceiling is not the model's. Each endpoint's
# context window in tokens, declared here and pinned with the host, keyed by
# the endpoint name a run is priced and called under (its model identity).
# An endpoint missing here has no known context and is refused before any
# reservation (`request_ceiling`). Sources: `openai/gpt-6-luna`, the
# listing of the router the qualification adapter calls (1,050,000), which
# answered FCA3-dec's 4,033,648-byte CP-0 request with a 400 this bound now
# prevents; `databricks-claude-opus-5`, the 1M tokens D29 sized the transport
# ceiling against.
CONTEXT_TOKENS: Mapping[str, int] = MappingProxyType(
    {
        "openai/gpt-6-luna": 1_050_000,
        "databricks-claude-opus-5": 1_000_000,
    }
)
# The fewest request bytes one prompt token is assumed to take: the bound is
# `(context - MAX_COMPLETION_TOKENS) * BYTES_PER_TOKEN_FLOOR` request bytes.
# Measured (D116): over 195 live calls of 3 to 5 October, request bytes per
# native prompt token ran 3.82 to 4.64, and per the router's own prompt count
# 4.02 throughout; FCA3-dec's CP-0 took 4.53 per o200k token. Three is below
# every one, so a request under the bound is under the context by any of
# those counts. A pack of numeric tables alone can tokenise denser (the
# fund's N-PORT schedule, 2.54): such a request is refused by the provider
# before any generation, as FCA3-dec's was, never cut.
BYTES_PER_TOKEN_FLOOR = 3

# A call that cannot succeed by being repeated. Retrying one of these spends a
# second reservation on the same certain failure.
NEVER_RETRIED = frozenset({400, 401, 402, 403, 404, 413, 422})

_FINISH_REFUSALS = {
    "length": RefusalCode.PROVIDER_OUTPUT_TRUNCATED,
    "content_filter": RefusalCode.PROVIDER_REFUSED,
}


def request_ceiling(model: str) -> int:
    """The most request bytes one call to `model` may carry (D116): its
    declared context less the completion it may return, at
    `BYTES_PER_TOKEN_FLOOR` bytes a token, and never past the transport's
    `MAX_REQUEST_BYTES`. An endpoint with no declared context refuses
    `PROVIDER_NOT_CONFIGURED`: a bound nobody declared is not a bound."""
    tokens = CONTEXT_TOKENS.get(model)
    if tokens is None or tokens <= MAX_COMPLETION_TOKENS:
        raise Refusal(RefusalCode.PROVIDER_NOT_CONFIGURED)
    return min(
        MAX_REQUEST_BYTES, (tokens - MAX_COMPLETION_TOKENS) * BYTES_PER_TOKEN_FLOOR
    )


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
    `drop_kind` says how a call that got no answer ended (D110); None for
    an answered call, and for any refusal whose ending was not stated.
    """

    content: str | None = field(repr=False)
    charge: Decimal | None
    generation_id: str | None = field(repr=False)
    refusal: RefusalCode | None = None
    drop_kind: DropKind | None = None


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

    @property
    def price(self) -> ModelPrice | None:
        """The dated price the charges it reports are billed at: what a run's
        reservation must have been priced at (`pricing.bills_at`). None states
        no price, and such a provider is refused (N15): budgets fail closed."""

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


# What must still hold before a call is sent again (ST-7): each check raises
# the refusal that stops it. Scoped to the call that installs it, so a check
# never outlives the attempt it guards.
_RESEND_CHECKS: ContextVar[tuple[Callable[[], None], ...]] = ContextVar(
    "caos_resend_checks", default=()
)


@contextmanager
def resend_checked(check: Callable[[], None]) -> Iterator[None]:
    """Run `check` before any re-send made inside this block.

    A transport that asks again -- a rate limit reached no model and is asked
    again under the same reservation (DP-5) -- first asks every check installed
    around it, outermost first, and sends nothing when one raises: a cancel,
    a lost lease or a process that is stopping ends the attempt instead.
    """
    installed = _RESEND_CHECKS.set((*_RESEND_CHECKS.get(), check))
    try:
        yield
    finally:
        _RESEND_CHECKS.reset(installed)


def check_resend() -> None:
    """Raise what the first failing check raises; a transport calls this
    immediately before it sends a call again."""
    for check in _RESEND_CHECKS.get():
        check()

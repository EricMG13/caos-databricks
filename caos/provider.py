"""The provider seam: one prompt in, one `Completion` out, a closed set of refusals.

What the canonical executor depends on and nothing more. The transport that
answers lives behind `caos/models.py` (Databricks AI Gateway, or GitHub
Copilot for a Copilot model, through the one model factory); this module
holds the shape both sides agree on: the request
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
import re
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
# budget (MX-4), sized inside the 900 s lease (`caos.store.work.LEASE_SECONDS`).
# The 180 s that remain are a liveness budget and, after a session cut, the
# safety margin: the reservation renews the lease just before the call, but
# the same 180 s also cover the work before it (the call check, reading
# upstreams and evidence, the re-encode) and after it (the bill, the answer's
# checks, the fenced acceptance). While the call's session lives, a lease lost
# anyway pays nothing twice: exactly-once rests on `call_hold`, `_UNSETTLED`
# and `replay_billed` (D83). A session the server cut mid-call (a failover, a
# suspend; never idleness, `caos.store.IDLE_SESSION_SET`, unless the server
# refuses that `SET`, D120) took `call_hold` with it, and then only the live
# lease keeps a second worker off the node until the bill lands (D117).
# 420 s since D83: 5 of 19 default-tier calls ran past 240 s on 2 October.
# 720 s since D117 (owner, 6 October), the lease raised with it: CP-3C at
# effort high took 327 s in LCR6 and ran past 420 s in LCR9-dec.
# `MAX_COMPLETION_TOKENS` is what the reservation covers, not what this
# deadline promises to deliver.
TIMEOUT_SECONDS = 720.0
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
# Source of the three `openai/` names: `context_length` in the keyless listing of the
# router the qualification adapter calls (`GET /api/v1/models`, read
# 2026-10-05). Luna answered FCA3-dec's 4,033,648-byte CP-0 request with a
# 400, which this bound now prevents. The workspace endpoints are declared at
# 1,000,000 tokens on the owner's word of 2026-10-06 (D119, closing N170).
# An endpoint missing here keeps the transport ceiling, and its run says so
# (`context_notice`); a `copilot:` name missing here is declared at
# `COPILOT_CONTEXT_TOKENS`.
OWNER_DECLARED_CONTEXT = 1_000_000
WORKSPACE_ENDPOINTS: tuple[str, ...] = (
    "grok-4-7",
    "claude-sonnet-5-5",
    "gpt-6-luna",
    "claude-opus-5-5",
    "gpt-6-sol",
    "deepseek-v4-1-flash",
    "gpt-6-astra",
    "gemini-3-8-flash",
    "glm-5-3",
    "glm-5-3-flash",
    "databricks-claude-opus-5",
)
CONTEXT_TOKENS: Mapping[str, int] = MappingProxyType(
    {
        **dict.fromkeys(WORKSPACE_ENDPOINTS, OWNER_DECLARED_CONTEXT),
        "openai/gpt-6-luna": 1_050_000,
        "openai/gpt-6-luna-pro": 1_050_000,
        "openai/gpt-6-sol": 1_050_000,
    }
)
# Every approved `copilot:` model's context, at the long-context tier each
# session requests (D77, R4): source "owner, 2026-10-06, 1M". A host constant,
# so a run's request ceiling is the same in every worker process and on every
# replay (MEDIUM-1); readiness holds the seat's listing to it as a floor and
# never reads the ceiling from it (`caos.copilot.require_ready`).
COPILOT_CONTEXT_TOKENS = OWNER_DECLARED_CONTEXT
# The fewest request bytes one prompt token is assumed to take. Measured
# (D116) at 3.82 to 4.64 per native token over 195 live calls, 4.02 per the
# router's count; a numeric-table pack can be denser (2.54, N170).
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
    `MAX_REQUEST_BYTES`. An endpoint with no declared context keeps
    `MAX_REQUEST_BYTES`, the bound every run had before D116 (review round
    1: refusing it stopped every approved workspace endpoint). A declared
    context no wider than the completion leaves the prompt no room, and
    refuses `PROVIDER_NOT_CONFIGURED`. A Copilot model's context is its
    pinned entry, else `COPILOT_CONTEXT_TOKENS` (`caos.copilot.context_tokens`),
    and its completion is its own output cap (`caos.copilot.output_cap`, R2.5).
    Imported here: `caos.copilot` imports this module at its top."""
    from caos import copilot

    cap = copilot.output_cap(model)
    tokens = copilot.context_tokens(model)
    if tokens is None:
        return MAX_REQUEST_BYTES
    if tokens <= cap:
        raise Refusal(RefusalCode.PROVIDER_NOT_CONFIGURED)
    return min(MAX_REQUEST_BYTES, (tokens - cap) * BYTES_PER_TOKEN_FLOOR)


# What a run driven on an endpoint with no declared context says on stderr,
# once (D116): the code and the endpoint's name, nothing else.
CONTEXT_NOT_DECLARED = "CONTEXT_NOT_DECLARED"
# A name the notice prints as it is; any other is printed as `-`.
_PLAIN_NAME = re.compile(r"[A-Za-z0-9._:/@+-]{1,256}")


def context_notice(model: str) -> str | None:
    """The line a run on `model` prints when no context is declared for it,
    or None when one is (D116, N170; every `copilot:` model is declared)."""
    from caos import copilot

    if copilot.context_tokens(model) is not None:
        return None
    name = model if _PLAIN_NAME.fullmatch(model) else "-"
    return f"{CONTEXT_NOT_DECLARED} endpoint={name}"


def finish_refusal(finish_reason: str) -> RefusalCode | None:
    """The refusal a finish reason carries; `None` for a completed answer.

    `stop` is the one completed reason. Anything unnamed here is a response
    the host does not understand, which is invalid rather than accepted.
    """
    if finish_reason == "stop":
        return None
    return _FINISH_REFUSALS.get(finish_reason, RefusalCode.PROVIDER_RESPONSE_INVALID)


class CutAfterContentError(Exception):
    """A call the provider failed after it had begun to answer (D110, D118):
    what a transport adapter raises when a stream it was reading ends in the
    provider's own error object after something was generated. It keeps that
    object as its body and none of the error's words; `caos.models` decides
    from the body alone whether the provider declared the failure, and so
    whether the node earns its one re-attempt (D118)."""

    def __init__(self, body: object, *, generation_id: object = None) -> None:
        super().__init__()
        self.body = body
        self.generation_id = generation_id


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


# The amount the attempt making this call reserved (R2.7), for a transport
# that sends its own spend cap: a guard after the fact, never the bound -- the
# reservation and the settled check are. Unset, no cap is sent. Scoped like
# `_RESEND_CHECKS`, and read on the call's own thread through the context
# `models._invoked` copies.
reserved_amount: ContextVar[Decimal | None] = ContextVar(
    "caos_reserved_amount", default=None
)


# The price of one AI credit that reservation was taken under (R2.2): what a
# Copilot call made inside it is settled at, never the environment's figure.
# None for a reservation that names none, which settles no Copilot call.
reserved_credit: ContextVar[Decimal | None] = ContextVar(
    "caos_reserved_credit", default=None
)


# The seconds left of the one call deadline (ST-9) when `models._invoked`
# hands a try to its chat model: a transport that runs its own timer
# (`caos.copilot.ChatCopilot`) asks for no more than this, so a session sent
# again after a 429 cannot outlive the deadline the worker records. Set in the
# context the call's own thread runs in; None outside a call.
call_seconds: ContextVar[float | None] = ContextVar("caos_call_seconds", default=None)


@contextmanager
def reserving(amount: Decimal, *, credit: Decimal | None = None) -> Iterator[None]:
    """Name `amount`, and the credit price it was taken under, as the
    reservation every call made inside this block runs under; the previous
    one is restored when the block ends, however it ends. An amount or a
    credit price that is no spend is refused before the block is entered."""
    validate_spend(amount)
    if credit is not None:
        validate_spend(credit)
    named = reserved_amount.set(amount)
    priced = reserved_credit.set(credit)
    try:
        yield
    finally:
        reserved_credit.reset(priced)
        reserved_amount.reset(named)

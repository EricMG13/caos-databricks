"""A reservation priced from the configured model (F06, §16, §40).

The provider is asked at most `MAX_REQUEST_BYTES` of request and
`MAX_COMPLETION_TOKENS` of completion (§38). With no tokenizer, the conservative
input bound is one token per request byte, so the cost of one call is at most
`request bytes * input + MAX_COMPLETION_TOKENS * output`. That is
`priced_request`, and it is what every call reserves: the bytes the provider
will actually be sent, not the largest request the transport would carry.

`worst_case` is the same arithmetic at `MAX_REQUEST_BYTES`. It is the run's
admission check -- a ceiling that cannot afford one call at its worst is refused
before an attempt exists -- and no longer a per-call reservation, because
reserving the transport ceiling per call made a three-node route unaffordable
under any sane ceiling at a real model's rates (Task 8.2).

Neither is a forecast. An application price cannot guarantee a vendor bill; the
known charge is still reconciled after the call, and an overrun consumes the
remaining capacity. The price a reservation was taken under is stored beside it,
so a row can be read back to the dated price that produced it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import (
    MAX_EMAX,
    MIN_EMIN,
    Context,
    Decimal,
    DecimalException,
    Inexact,
    InvalidOperation,
    Overflow,
)

from caos.provider import MAX_COMPLETION_TOKENS, MAX_REQUEST_BYTES
from caos.refusals import Refusal, RefusalCode
from caos.store.budget import validate_spend


@dataclass(frozen=True, slots=True)
class ModelPrice:
    """A dated per-token price for one configured model identity."""

    model: str
    input_per_token: Decimal
    output_per_token: Decimal
    as_of: date


def priced_request(price: ModelPrice, request_bytes: int) -> Decimal:
    """The most a call sending `request_bytes` can cost at this price, exactly.

    Input is priced per request byte rather than per token, which over-counts:
    a token is at least one byte, so the bound holds without a tokenizer.
    Output is priced at the completion cap, which is what the provider is
    permitted to return. Over the transport ceiling is refused rather than
    priced -- that request cannot be sent, so there is nothing to reserve for.
    """
    if not isinstance(price.model, str) or not price.model:
        raise Refusal(RefusalCode.PROVIDER_NOT_CONFIGURED)
    validate_spend(price.input_per_token)
    validate_spend(price.output_per_token)
    if isinstance(request_bytes, bool) or not isinstance(request_bytes, int):
        raise Refusal(RefusalCode.MONEY_NOT_DECIMAL)
    if request_bytes < 0:
        raise Refusal(RefusalCode.MONEY_INVALID)
    if request_bytes > MAX_REQUEST_BYTES:
        raise Refusal(RefusalCode.CONTEXT_OVER_CEILING)
    # An explicit context, not the caller's: exact or refused, never rounded.
    exact = Context(
        prec=1000,
        Emax=MAX_EMAX,
        Emin=MIN_EMIN,
        traps=[Inexact, Overflow, InvalidOperation],
    )
    try:
        amount = exact.add(
            exact.multiply(price.input_per_token, request_bytes),
            exact.multiply(price.output_per_token, MAX_COMPLETION_TOKENS),
        )
    except DecimalException:
        raise Refusal(RefusalCode.MONEY_INVALID) from None
    validate_spend(amount)
    # A free price would reserve nothing, and a ceiling spent to exactly zero
    # admits a zero reservation: the call it pays for could overspend.
    if not amount:
        raise Refusal(RefusalCode.MONEY_INVALID)
    return amount


def worst_case(price: ModelPrice) -> Decimal:
    """The most any one call can cost at this price, exactly, or a refusal.

    The whole transport ceiling as input. A run whose budget cannot cover this
    once is refused before it starts, so no run spends on a route it could
    never have afforded a single call of (invariant 8).
    """
    return priced_request(price, MAX_REQUEST_BYTES)


def price_from_environment(model: str, value: str) -> ModelPrice:
    """A dated price for exactly the configured model, or a typed refusal.

    `model,input_per_token,output_per_token,YYYY-MM-DD` (legacy section 49).
    The value is never printed; the refusal names only the code.
    """
    parts = value.split(",")
    try:
        name, given_input, given_output, as_of = parts
        price = ModelPrice(
            name, Decimal(given_input), Decimal(given_output), date.fromisoformat(as_of)
        )
    except (ValueError, InvalidOperation):
        raise Refusal(RefusalCode.PROVIDER_NOT_CONFIGURED) from None
    if price.model != model:
        raise Refusal(RefusalCode.PROVIDER_NOT_CONFIGURED)
    worst_case(price)
    return price

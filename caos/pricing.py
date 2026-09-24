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

import re
from dataclasses import dataclass
from datetime import UTC, date, datetime
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
    exact = exact_context()
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


def bills_at(provider: object, price: ModelPrice) -> bool:
    """Whether `provider` bills its calls at exactly `price` (CF-089).

    A call reserves at the run's price and is charged what the provider
    reports, and `models.ChatCompletions` computes that charge from its own
    dated price. So the provider's model must be the price's, and the price it
    states it charges at must be this one, rates and date alike: another
    would reserve one number and bill another. A provider that states no
    price -- one reporting money it did not price, or a wrapper that does not
    pass its inner provider's on -- is not known to bill at this one, and is
    refused like a wrong one (N15): budgets fail closed (invariant 8), and it
    was compared by model name alone.
    """
    if getattr(provider, "model", None) != price.model:
        return False
    stated = getattr(provider, "price", None)
    return isinstance(stated, ModelPrice) and stated == price


def exact_context() -> Context:
    """The context money is computed in: an explicit one, not the caller's,
    exact or refused and never rounded. A reservation and a charge are both
    computed here, so the two agree on the precision a price may carry
    (MAX-N03)."""
    return Context(
        prec=1000,
        Emax=MAX_EMAX,
        Emin=MIN_EMIN,
        traps=[Inexact, Overflow, InvalidOperation],
    )


def worst_case(price: ModelPrice) -> Decimal:
    """The most any one call can cost at this price, exactly, or a refusal.

    The whole transport ceiling as input. A run whose budget cannot cover this
    once is refused before it starts, so no run spends on a route it could
    never have afforded a single call of (invariant 8).
    """
    return priced_request(price, MAX_REQUEST_BYTES)


# A per-token rate as written: ASCII digits, an optional fraction, no sign,
# exponent or other script's digits (DF-10). A date is ISO `YYYY-MM-DD`.
_RATE = re.compile(r"[0-9]+(?:\.[0-9]+)?")
_DAY = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")


def price_from_environment(model: str, value: str) -> ModelPrice:
    """A dated price for exactly the configured model, or a typed refusal.

    `model,input_per_token,output_per_token,YYYY-MM-DD` (legacy section 49).
    The value is never printed; the refusal names only the code. Each rate is
    plain ASCII digits and above zero, and the date is no later than today in
    UTC (DF-10): a free half would price every reservation and every charge
    at nothing for that half, and a price dated in the future is not the one
    in force. `scripts/preflight.py` reads the price through this, so the app
    and the deploy agree.
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
    if not (
        _RATE.fullmatch(given_input)
        and _RATE.fullmatch(given_output)
        and _DAY.fullmatch(as_of)
        and price.input_per_token > 0
        and price.output_per_token > 0
        and price.as_of <= datetime.now(UTC).date()
    ):
        raise Refusal(RefusalCode.PROVIDER_NOT_CONFIGURED)
    return price

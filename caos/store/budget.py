"""Reservations. Invariant 8: every ceiling refuses the next operation.

No provider call without a reservation, and the reservation is taken *before* the
call. A ceiling checked afterwards is an invoice.

Two properties are deliberate and both cost money on purpose:

*The reservation commits on its own.* It does not ride the transaction that later
accepts the artifact. A process that died after the provider completed would
otherwise roll back the record of money that was really spent, and the retry
would reserve against a ceiling that had forgotten it.

*A reservation names its price.* The four `price_*` columns hold the dated
price the amount was computed from (§40). The amount alone cannot be read back
to one -- many prices and request sizes reach the same number -- and the unit
that later spends reads the price back to check that the request it is about to
send still fits what was set aside.

*Nothing is released.* An indeterminate call may have reached the provider and
may be billed (`docs/DECISIONS.md` §16: `PROVIDER_UNAVAILABLE` leaves the attempt
indeterminate with its reservation). Releasing it would let the retry spend money
the run has already committed. A retry is a new attempt and a new reservation --
the price of a provider with no idempotency key, paid knowingly.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING
from uuid import UUID

import psycopg

from caos.refusals import Refusal, RefusalCode
from caos.store import StoreConnection, committed_unit

if TYPE_CHECKING:
    from caos.pricing import ModelPrice
    from caos.store.work import Lease

# What a run may spend when its caller names no ceiling. A run with no ceiling
# at all would be invariant 8 with the number left out.
CEILING = Decimal("5.00")
# The deployment's own default for a new run (F28): a priced policy the bundle
# sets (`run_ceiling`), because `CEILING` is below one worst-case call at the
# gateway's Claude prices and every run would refuse `BUDGET_CEILING_REACHED`.
CEILING_ENV = "CAOS_RUN_CEILING"


def configured_ceiling(value: str | None = None) -> Decimal | None:
    """The ceiling the environment names for a new run, or None for `CEILING`.

    Malformed or out of range refuses `PROVIDER_NOT_CONFIGURED`: the ceiling
    is what the run may pay the provider, and a process that cannot state it
    must not start runs.
    """
    raw = os.environ.get(CEILING_ENV) if value is None else value
    if raw is None or not raw.strip():
        return None
    try:
        ceiling = Decimal(raw.strip())
    except InvalidOperation:
        raise Refusal(RefusalCode.PROVIDER_NOT_CONFIGURED) from None
    try:
        validate_spend(ceiling)
    except Refusal:
        raise Refusal(RefusalCode.PROVIDER_NOT_CONFIGURED) from None
    return ceiling


def validate_spend(amount: Decimal) -> None:
    """Exact nonnegative spend within PostgreSQL's native numeric envelope.

    These are representation bounds, not economic ceilings. Check before
    adaptation, without rounding or normalizing even zero's supplied exponent.
    """
    if not isinstance(amount, Decimal):
        raise Refusal(RefusalCode.MONEY_NOT_DECIMAL)
    if (
        not amount.is_finite()
        or amount < 0
        or amount.adjusted() >= 131072
        or int(amount.as_tuple().exponent) < -16383
    ):
        raise Refusal(RefusalCode.MONEY_INVALID)


@dataclass(frozen=True, slots=True)
class Reservation:
    """What an attempt set aside, and the dated price that produced it."""

    amount: Decimal
    price: ModelPrice


def reserve(
    conn: StoreConnection,
    attempt_id: UUID,
    amount: Decimal,
    *,
    price: ModelPrice,
    lease: Lease | None = None,
) -> None:
    """Set `amount` aside for this attempt, or refuse `BUDGET_CEILING_REACHED`.

    `price` is the dated price the amount was computed from and is stored with
    it, so the row can be read back to what it was priced at rather than only
    to a number (§40).

    Taken under the run row lock, which is what makes two connections reserving
    at once resolve to one: without it both read the same remaining balance and
    both believe they fit. Under the same lock the run's lease must be held and
    no cancel requested (brief 4.3 D3).
    """
    with committed_unit(conn):
        _reserve(conn, attempt_id, amount, price, lease)


def _reserve(
    conn: StoreConnection,
    attempt_id: UUID,
    amount: Decimal,
    price: ModelPrice,
    lease: Lease | None,
) -> None:
    # Both import this module at their top: `outcomes` directly, `work` through it.
    from caos.store.outcomes import _require_attempt
    from caos.store.work import require_running

    validate_spend(amount)
    _validate_price(price)
    if conn.autocommit:
        raise Refusal(RefusalCode.STORE_NOT_TRANSACTIONAL)
    run_id = _run_of(conn, attempt_id)
    require_running(conn, run_id, lease)
    _require_attempt(conn, attempt_id, run_id)
    if (
        reserved_for(conn, attempt_id) is not None
        or conn.execute(
            "SELECT 1 FROM budget_ledger WHERE attempt_id = %s", (attempt_id,)
        ).fetchone()
    ):
        raise Refusal(RefusalCode.BUDGET_ALREADY_RESERVED)
    if amount > _remaining(conn, run_id):
        raise Refusal(RefusalCode.BUDGET_CEILING_REACHED)
    conn.execute(
        "INSERT INTO budget_reservations (attempt_id, run_id, amount,"
        " price_model, price_input, price_output, price_as_of)"
        " VALUES (%s, %s, %s, %s, %s, %s, %s)",
        (
            attempt_id,
            run_id,
            amount,
            price.model,
            price.input_per_token,
            price.output_per_token,
            price.as_of,
        ),
    )


def _validate_price(price: ModelPrice) -> None:
    """A price the row can be read back from: a named model, exact rates, a date.

    `caos.pricing` imports this module, so the check lives here rather than
    reaching back for `priced_request`; the two agree on what a price is.
    """
    if not isinstance(price.model, str) or not price.model:
        raise Refusal(RefusalCode.PROVIDER_NOT_CONFIGURED)
    validate_spend(price.input_per_token)
    validate_spend(price.output_per_token)
    if not isinstance(price.as_of, date) or isinstance(price.as_of, bool):
        raise Refusal(RefusalCode.PROVIDER_NOT_CONFIGURED)


def remaining(conn: StoreConnection, run_id: UUID) -> Decimal:
    """Ceiling less per-attempt max(reserved, charged); caller owns transaction."""
    try:
        return _remaining(conn, run_id)
    except psycopg.Error:
        raise Refusal(RefusalCode.STORE_UNAVAILABLE) from None


def ceiling_of(conn: StoreConnection, run_id: UUID) -> Decimal:
    """The run's own ceiling, unreduced by what it has spent.

    `remaining` answers "may this next operation be paid for", which is what
    invariant 8 refuses on. This answers a different question -- "could this run
    ever have afforded one full-sized call" -- and it is a property of the run
    rather than of its progress, so it must not shrink as the run spends. Since
    Task 8.2 a reservation is the priced request rather than a worst case, and a
    run can legitimately spend to within one worst case of its ceiling while
    still affording its last node; reading `remaining` here refused exactly that
    run on resume, one node short of finishing.
    """
    try:
        row = conn.execute(
            "SELECT budget_ceiling FROM runs WHERE run_id = %s", (run_id,)
        ).fetchone()
    except psycopg.Error:
        raise Refusal(RefusalCode.STORE_UNAVAILABLE) from None
    if row is None:
        raise Refusal(RefusalCode.RUN_NOT_FOUND)
    ceiling: Decimal = row[0]
    return ceiling


def reserved_for(conn: StoreConnection, attempt_id: UUID) -> Reservation | None:
    """What this attempt set aside and under which price, or None if it never
    reserved. A legacy row (`0024_reservation_price`) reads back as the
    unnamed price it was migrated with, which no caller may spend under."""
    from caos.pricing import ModelPrice

    try:
        row = conn.execute(
            "SELECT amount, price_model, price_input, price_output, price_as_of"
            " FROM budget_reservations WHERE attempt_id = %s",
            (attempt_id,),
        ).fetchone()
    except psycopg.Error:
        raise Refusal(RefusalCode.STORE_UNAVAILABLE) from None
    if row is None:
        return None
    amount, model, per_input, per_output, as_of = row
    return Reservation(amount, ModelPrice(model, per_input, per_output, as_of))


def _remaining(conn: StoreConnection, run_id: UUID) -> Decimal:
    row = conn.execute(
        "SELECT runs.budget_ceiling"
        " - coalesce(sum(greatest(reservations.amount, ledger.amount)), 0)"
        " FROM runs"
        " LEFT JOIN run_attempts USING (run_id)"
        " LEFT JOIN budget_reservations AS reservations USING (run_id, attempt_id)"
        " LEFT JOIN budget_ledger AS ledger USING (run_id, attempt_id)"
        " WHERE runs.run_id = %s"
        " GROUP BY runs.budget_ceiling",
        (run_id,),
    ).fetchone()
    if row is None:
        raise Refusal(RefusalCode.RUN_NOT_FOUND)
    left: Decimal = row[0]
    return left


def _run_of(conn: StoreConnection, attempt_id: UUID) -> UUID:
    row = conn.execute(
        "SELECT run_id FROM run_attempts WHERE attempt_id = %s", (attempt_id,)
    ).fetchone()
    if row is None:
        raise Refusal(RefusalCode.ATTEMPT_NOT_FOUND)
    return UUID(str(row[0]))

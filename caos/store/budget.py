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

*A Copilot reservation names its credit price* (0048, D77 addendum 2): the
dated price of one AI credit pinned when it was taken, which settles the call's
AI units. The process's pin is read at the reservation and nowhere after it.

*Nothing is released.* An indeterminate call may have reached the provider and
may be billed (`PROVIDER_UNAVAILABLE` leaves the attempt indeterminate with its
reservation). Releasing it would let the retry spend money the run has
already committed. A retry is a new attempt and a new reservation --
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
    from caos.pricing import CreditPrice, ModelPrice
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
    """What an attempt set aside, the dated price that produced it, and for a
    Copilot model the dated credit price its AI units are settled at (0048)."""

    amount: Decimal
    price: ModelPrice
    credit: CreditPrice | None = None


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

    For a Copilot model the process's pinned credit price
    (`caos.copilot.credit_price`) is stored beside it, read here and only
    here, so the call is settled at the price in force when it was reserved;
    a Copilot model with no valid pin refuses `PROVIDER_NOT_CONFIGURED` before
    anything is written (R2.2).

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
    credit = _credit_for(price)
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
        " price_model, price_input, price_output, price_as_of,"
        " credit_price, credit_as_of)"
        " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
        (
            attempt_id,
            run_id,
            amount,
            price.model,
            price.input_per_token,
            price.output_per_token,
            price.as_of,
            None if credit is None else credit.per_credit,
            None if credit is None else credit.as_of,
        ),
    )


def _credit_for(price: ModelPrice) -> CreditPrice | None:
    """The process's pinned credit price for a Copilot model, or refused
    `PROVIDER_NOT_CONFIGURED`; None for any other model. Imported here:
    `caos.copilot` imports this module at its top."""
    from caos import copilot

    if copilot.parsed(price.model) is None:
        return None
    return copilot.credit_price()


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


def overspent(conn: StoreConnection, run_id: UUID) -> bool:
    """Whether a call of this run was charged above a reservation that names
    a credit price (R2.6): an AI-unit bill the run's pinned per-token price
    did not bound, so any further attempt would reserve the same way and
    overshoot the same way. Read from the ledger, which holds the whole
    charge whatever became of the refusal or the park after it (F589). A
    token-priced overrun is not counted: it keeps the budget exit it always
    had. Caller owns the transaction."""
    try:
        row = conn.execute(
            "SELECT 1 FROM budget_reservations r"
            " JOIN budget_ledger l USING (run_id, attempt_id)"
            " WHERE r.run_id = %s AND r.credit_price IS NOT NULL"
            " AND l.amount > r.amount LIMIT 1",
            (run_id,),
        ).fetchone()
    except psycopg.Error:
        raise Refusal(RefusalCode.STORE_UNAVAILABLE) from None
    return row is not None


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


def price_of(conn: StoreConnection, run_id: UUID) -> ModelPrice | None:
    """The model and dated price the run was started on (0043), or None for a
    run started before its model was pinned, which runs on the deployment's
    configured model."""
    from caos.pricing import ModelPrice

    try:
        row = conn.execute(
            "SELECT price_model, price_input, price_output, price_as_of"
            " FROM runs WHERE run_id = %s",
            (run_id,),
        ).fetchone()
    except psycopg.Error:
        raise Refusal(RefusalCode.STORE_UNAVAILABLE) from None
    if row is None:
        raise Refusal(RefusalCode.RUN_NOT_FOUND)
    if row[0] is None:
        return None
    return ModelPrice(*row)


def reserved_for(conn: StoreConnection, attempt_id: UUID) -> Reservation | None:
    """What this attempt set aside and under which price, or None if it never
    reserved. A legacy row (`0024_reservation_price`) reads back as the
    unnamed price it was migrated with, which no caller may spend under. A
    row from before 0048, or for a model that is not Copilot's, names no
    credit price."""
    from caos.pricing import CreditPrice, ModelPrice

    try:
        row = conn.execute(
            "SELECT amount, price_model, price_input, price_output, price_as_of,"
            " credit_price, credit_as_of"
            " FROM budget_reservations WHERE attempt_id = %s",
            (attempt_id,),
        ).fetchone()
    except psycopg.Error:
        raise Refusal(RefusalCode.STORE_UNAVAILABLE) from None
    if row is None:
        return None
    amount, model, per_input, per_output, as_of, per_credit, credit_as_of = row
    credit = None if per_credit is None else CreditPrice(per_credit, credit_as_of)
    return Reservation(amount, ModelPrice(model, per_input, per_output, as_of), credit)


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

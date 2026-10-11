"""The rate deck: saved by a global ADMIN, immutable, pinned per run.

A deck is the desk's dated statement of reference rates per fiscal year for
the Base and Downside cases (`CONTEXT.md`), read back as Plan 1's
`caos.calculators.credit_model.projection.RateDeck`. Four things hold, each
enforced by the store itself (`0050_rate_decks.sql`) and not only by this
module.

*A deck never changes.* Its row, its rates and every run's pin refuse
UPDATE, DELETE and TRUNCATE; a deck gains no rate after the transaction that
saved it; and its `rates_sha256`, the digest of its rates as written
(`rates_digest`), is checked on every read, so rates changed behind the
triggers fail closed (`ARTIFACT_RECORD_MISMATCH`) rather than read as a
different deck.

*"Latest" moves only forward, in commit order.* A save holds one
transaction-scoped advisory lock (`SAVE_LOCK`) exclusively, and the store
refuses a deck inserted without it; the deck's `deck_seq` identity is handed
out under that lock, so its order is commit order. The latest deck is the
greatest `deck_seq`. `saved_at` is the clock at the save, for display only.

*A run's pin is part of the run's creation.* `pin_latest_deck` runs inside
`start_run`'s unit, and the store refuses a pin from any other transaction:
the run and its pin commit together or not at all, and a later save never
moves a pin already written. With no deck, nothing is pinned.

*A pin never misses a deck in flight.* The pin takes the save lock shared
first, so it waits for a save not yet committed and then pins that deck: a
deck acknowledged to its admin before the run commits is never passed over.
The wait is bounded (`PIN_LOCK_TIMEOUT_MS`), so a save queued behind a long run
unit cannot hold every other run start with it.

The store checks who wrote what by write-once transaction ids
(`rate_decks.saved_xact`, `runs.created_xact`), never by a timestamp a later
transaction could rewrite: a deck's rates only in the transaction that saved
it, a run's pin only in the transaction that created it, and a deck only with
the identity its save drew under the lock.

Nothing here commits: `save_deck` writes in the caller's unit, beside the
command receipt the route records.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from caos.calculators.credit_model.projection import RateDeck, RateDeckYear
from caos.digest import canonical_digest
from caos.refusals import Refusal, RefusalCode
from caos.store import StoreConnection

# The reference rates a deck may state, as `0050_rate_decks.sql` checks them.
REFERENCE_RATES = frozenset({"SOFR", "TERM_SOFR", "EURIBOR", "SONIA"})
# FY+1 to FY+5: the projection's horizon (`RateDeckYear.fiscal_year_offset`).
YEAR_OFFSETS = range(1, 6)
# Four reference rates over five years, each at most once.
DECK_ROWS_MAX = len(REFERENCE_RATES) * len(YEAR_OFFSETS)
# A rate is a decimal strictly inside (-1, 1): 0.0380 is 3.80%.
_RATE_BOUND = Decimal(1)
# The longest rate text the store holds: the wire's decimal text
# (`caos.api.wire.DecimalText`, `FIGURE_CHARS`) carries 64 characters back.
RATE_CHARS = 64
# The class of the advisory lock every save takes exclusively and every pin
# shared (the two-key form, as `caos.store.work` and `caos.store.outcomes`
# use; the second key is 0, since there is one deck sequence). Arbitrary and
# permanent; `0050_rate_decks.sql` names it too, as 211812432.
SAVE_LOCK = 0x0CA0_0050

# Each statement is one literal, never assembled (bandit B608). "Latest" is
# the greatest `deck_seq`, spelled the same in the read and the pin.
#
# A deck, its digest and its rates in one round trip, rates in (reference
# rate, year) order. A LEFT JOIN, so a deck is never read as absent for lack
# of a rate row; its digest then refuses it.
_READ_LATEST = (
    "SELECT d.deck_id, d.as_of, d.saved_at, d.rates_sha256,"
    " r.reference_rate, r.year_offset, r.base_rate, r.downside_rate"
    " FROM rate_decks d LEFT JOIN rate_deck_rates r ON r.deck_id = d.deck_id"
    " WHERE d.deck_id = (SELECT deck_id FROM rate_decks"
    " ORDER BY deck_seq DESC LIMIT 1)"
    " ORDER BY r.reference_rate, r.year_offset"
)
# From the run, so an unknown run (no row) is told from a run with no deck (a
# row of nulls).
_READ_PINNED = (
    "SELECT d.deck_id, d.as_of, d.saved_at, d.rates_sha256,"
    " r.reference_rate, r.year_offset, r.base_rate, r.downside_rate"
    " FROM runs u LEFT JOIN run_rate_decks p ON p.run_id = u.run_id"
    " LEFT JOIN rate_decks d ON d.deck_id = p.deck_id"
    " LEFT JOIN rate_deck_rates r ON r.deck_id = d.deck_id"
    " WHERE u.run_id = %s"
    " ORDER BY r.reference_rate, r.year_offset"
)


@dataclass(frozen=True, slots=True)
class SavedDeck:
    """A deck as the read route shows it: the projection's `RateDeck` and
    when it was saved."""

    deck: RateDeck
    saved_at: datetime


def _figure(rate: Decimal) -> str:
    """A rate's value as text: plain notation, no trailing zero and no
    negative zero. Postgres keeps a numeric's scale but not a zero's sign, so
    the digest reads the value, never its spelling."""
    text = f"{rate:f}"
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return "0" if text == "-0" else text


def rates_digest(rates: Sequence[RateDeckYear]) -> str:
    """SHA-256 of a deck's rates: canonical JSON of the rows sorted by
    (reference rate, year), each rate as its value (`_figure`)."""
    rows = sorted(
        [
            year.reference_rate,
            year.fiscal_year_offset,
            _figure(year.base),
            _figure(year.downside),
        ]
        for year in rates
    )
    return canonical_digest(rows)


def check_rates(rates: Sequence[RateDeckYear]) -> None:
    """Refuse a deck the store would not hold, before any write.

    One to `DECK_ROWS_MAX` rows; each a known reference rate at a year offset
    in `YEAR_OFFSETS`, at most once per (reference rate, year); each rate a
    finite decimal strictly inside (-1, 1), at most `RATE_CHARS` long in
    plain notation. `REQUEST_INVALID`, naming nothing the caller sent.
    """
    keys = {(year.reference_rate, year.fiscal_year_offset) for year in rates}
    if not 1 <= len(rates) <= DECK_ROWS_MAX or len(keys) != len(rates):
        raise Refusal(RefusalCode.REQUEST_INVALID)
    for year in rates:
        if (
            year.reference_rate not in REFERENCE_RATES
            or year.fiscal_year_offset not in YEAR_OFFSETS
            or not all(
                rate.is_finite()
                and -_RATE_BOUND < rate < _RATE_BOUND
                and len(f"{rate:f}") <= RATE_CHARS
                for rate in (year.base, year.downside)
            )
        ):
            raise Refusal(RefusalCode.REQUEST_INVALID)


def save_deck(
    conn: StoreConnection,
    actor_id: UUID,
    as_of: date,
    rates: Sequence[RateDeckYear],
) -> UUID:
    """Write one deck and its rates in the caller's unit; its new id.

    Checked first (`check_rates`), so a refused deck writes nothing. Then the
    save lock, held exclusively to the unit's end; the deck, its identity
    handed out under that lock, stamped with the clock and carrying the
    digest of its rates; and the rates -- three statements.
    """
    check_rates(rates)
    conn.execute("SELECT pg_advisory_xact_lock(%s::integer, 0)", (SAVE_LOCK,))
    deck_id = uuid4()
    conn.execute(
        "INSERT INTO rate_decks (deck_id, as_of, saved_by, saved_at, rates_sha256)"
        " VALUES (%s, %s, %s, clock_timestamp(), %s)",
        (deck_id, as_of, actor_id, rates_digest(rates)),
    )
    conn.execute(
        "INSERT INTO rate_deck_rates"
        " (deck_id, reference_rate, year_offset, base_rate, downside_rate)"
        " SELECT %s, * FROM unnest(%s::text[], %s::integer[],"
        " %s::numeric[], %s::numeric[])",
        (
            deck_id,
            [year.reference_rate for year in rates],
            [year.fiscal_year_offset for year in rates],
            [year.base for year in rates],
            [year.downside for year in rates],
        ),
    )
    return deck_id


def _deck(rows: list[tuple[Any, ...]]) -> SavedDeck | None:
    """The rows a deck read returned, as one deck; None for no rows or a row
    naming no deck. `ARTIFACT_RECORD_MISMATCH` when the rates read are not
    the rates the deck was saved with."""
    if not rows or rows[0][0] is None:
        return None
    deck_id, as_of, saved_at, rates_sha256 = rows[0][:4]
    years = tuple(
        RateDeckYear(
            reference_rate=str(reference_rate),
            fiscal_year_offset=int(year_offset),
            base=Decimal(base),
            downside=Decimal(downside),
        )
        for *_deck_columns, reference_rate, year_offset, base, downside in rows
        if reference_rate is not None
    )
    if not years or rates_digest(years) != rates_sha256:
        raise Refusal(RefusalCode.ARTIFACT_RECORD_MISMATCH)
    return SavedDeck(RateDeck(str(deck_id), as_of.isoformat(), years), saved_at)


def latest_saved_deck(conn: StoreConnection) -> SavedDeck | None:
    """The latest committed deck and when it was saved, or None. One round
    trip; its rates verified against their digest."""
    return _deck(conn.execute(_READ_LATEST).fetchall())


def latest_deck(conn: StoreConnection) -> RateDeck | None:
    """The latest committed deck, or None when none was ever saved."""
    saved = latest_saved_deck(conn)
    return None if saved is None else saved.deck


def deck_for_run(conn: StoreConnection, run_id: UUID) -> RateDeck | None:
    """The deck the run pinned at its creation, or None when there was no
    deck then; `RUN_NOT_FOUND` for a run the store does not hold. One round
    trip; the rates verified against their digest."""
    rows = conn.execute(_READ_PINNED, (run_id,)).fetchall()
    if not rows:
        raise Refusal(RefusalCode.RUN_NOT_FOUND)
    saved = _deck(rows)
    return None if saved is None else saved.deck

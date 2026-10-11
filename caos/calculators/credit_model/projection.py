"""The projected columns: business-unit revenue, the amortisation schedule,
rate-deck interest and the cash flow, per case and year, chained (spec
M10-M14).

One column per (case, period) of CP-CF's request, Base and Downside only.
Business-unit revenue is the prior year's (the last historical FY, then the
year before) times one plus its slot's CP-2G growth, noted "growth outside
±100%" where that growth is (the figure kept); a segment in no slot, and
corporate and eliminations, is held flat. Revenue is CP-CF's own (every ratio
and growth reads it), the business units' sum only where CP-CF's request has
no revenue; the layout notes business units that do not sum to it. EBITDA,
capex, taxes, distributions, issuance,
repayments and acquisitions are CP-CF's drivers signed into the frame's
convention (outflows negative); CP-CF's `cfo` is before interest and taxes,
so `other_operating` is `cfo - ebitda`, working capital included.

The schedule opens at the historical column CP-CF's request opens at
(`opening.as_of_period_id`), else the last FY (the host LTM without one):
each facility's `fac:` balance and CP-1's terms there, cash and total debt. An
interest-bearing facility (not a lease, not a `DEBT ADJUSTMENT` row, in the
register's currency) amortises `min(annual_amortisation, balance)` a year,
never below zero; a null amortisation is none, noted. A maturity inside a
projected fiscal year is assumed refinanced: the balance stays, noted.
Finance leases and the debt adjustment are held flat; a facility in another
currency is held flat and left out (spec B13: no FX); operating leases are
not projected. A rate term outside CP-1's value set or its range is never
used: a spread outside 0-2,000 bp or a floor outside 0-1,000 bp, either not a
whole number of basis points (a percent read as basis points), or a fixed
coupon outside 0.5-30 percent (a decimal read as a percent), or any term
CP-1 wrote so (a spread or floor written with `%`, `terms_out_of_range`). The rate falls
back to the implied rate, and a negative amortisation to none, each noted
"term out of range".

Interest is the weighted rate of the interest-bearing facilities, weighted
on their scheduled opening balances, times the interest base: the year's
opening debt from CP-CF's roll-forward less what in it bears no interest
(finance leases, the debt adjustment), so CP-CF's repayments, issuance and
non-cash movements reach it (spec M13): no circularity. It is computed as
`(sum of balance x rate) x base / (sum of balance)`, never through the
rounded weighted rate; a negative base has none, noted "negative interest
base". A
facility's rate is its fixed coupon, the deck's reference rate for the case
and year offset (floor applied) plus its spread, or the implied rate: LTM
cash interest over the average of the LTM's opening and closing total debt
(none, with the opening's note, where the LTM's opening stack is incomplete).
The year offset counts from the last historical FY (FY+1 is the year after);
a year past the deck holds its last rate, a year the deck skips the year
before it, each noted, and a reference rate the deck lacks is implied.

The aggregate debt roll-forward is CP-CF's: opening, less the scheduled
amortisation, plus issuance, less optional repayment (`debt_raised_net`),
plus PIK, capitalised interest and FX (`debt_non_cash`; absent is none).
CP-CF has no equity movement (its distributions carry every equity outflow),
so equity raised is zero, noted. Secured debt sums the scheduled secured
balances, noted "excludes unallocated CP-CF movements" in a year CP-CF's
total debt moves off the schedule; the revolver's undrawn amount is held at
the opening. A facility in another currency at the opening is noted
"excludes facility in another currency" on the totals it would have entered,
and from total debt on net debt, the roll-forward, the interest base and the
cash interest.

A request without the fields the projection reads (`opening` and its
`as_of_period_id`, the periods' `case`, `period_id`, `fiscal_year` and
`days`, the drivers' `case` and `period_id`) or of another shape is refused,
`HANDOFF_MALFORMED`, and so is a period year outside 1900-2200 or more than
ten years from the base year. A driver of zero is zero, never negative zero.

Pure: Decimal only, no I/O, no rounding.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, localcontext

from caos.calculators.credit_model._cells import (
    CONTEXT,
)
from caos.calculators.credit_model.frame import Case, Cell
from caos.methodology.model_inputs import (
    FacilityRow,
)

IMPLIED = "implied rate"
NO_DECK = "no rate deck"
OUT_OF_RANGE = "term out of range"
AMORTISATION_NOT_STATED = "amortisation not stated"
REFINANCED = "assumed refinanced"
HELD_FLAT = "held flat"
DECK_HELD_FLAT = "last deck rate held flat"
DECK_YEAR_MISSING = "deck year missing"
NOT_IN_DECK = "reference rate not in deck"
NO_MIX = "no facility mix, implied rate"
GROWTH_UNBOUNDED = "growth outside ±100%"
NEGATIVE_BASE = "negative interest base"
WORKING_CAPITAL = "includes working capital"
NOT_READY = "driver not ready"
NO_EQUITY_MOVEMENT = "not a CP-CF movement"
RCF_HELD = "RCF drawing held at opening"

_CASES: dict[str, Case] = {"BASE": "BASE", "DOWNSIDE": "DOWNSIDE"}
_RATE_TYPES = frozenset({"FIXED", "FLOATING", "NOT_STATED"})
_REFERENCE_RATES = frozenset(
    {"SOFR", "TERM_SOFR", "EURIBOR", "SONIA", "NONE", "NOT_STATED"}
)
_DECK_RATES = frozenset({"SOFR", "TERM_SOFR", "EURIBOR", "SONIA"})
_DEBT_ADJUSTMENT = "DEBT ADJUSTMENT"
_NON_CASH = ("pik", "capitalised_interest", "fx_perimeter")
_BPS = Decimal(10_000)
_PERCENT = Decimal(100)
# Each term's range, and whether it is a whole number: basis points are.
_SPREAD = (Decimal(0), Decimal(2000), True)
_FLOOR = (Decimal(0), Decimal(1000), True)
_COUPON = (Decimal("0.5"), Decimal(30), False)
# CP-CF's decimal strings (`cash_flow._NUMBER`) and whole day counts.
_NUMBER = re.compile(r"-?(0|[1-9][0-9]{0,17})(\.[0-9]{1,6})?")
_WHOLE = re.compile(r"[1-9][0-9]{0,2}")
_NOT_PROJECTED = Cell(None, "NOT_PROJECTED")
# Lease balances, working-capital balances and days, and the FFO split.
_NOT_PROJECTED_KEYS = (
    "ebitda",
    "lease_cash_not_in_ebitda",
    "ffo",
    "working_capital_change",
    "lease_liabilities",
    "lease_adjusted_debt",
    "lease_adjusted_net_debt",
    "accounts_receivable",
    "inventory",
    "accounts_payable",
    "dso",
    "dio",
    "dpo",
    "ccc",
    "days",
)


@dataclass(frozen=True, slots=True)
class RateDeckYear:
    reference_rate: str
    fiscal_year_offset: int  # FY+1 is 1
    base: Decimal  # a decimal: 0.0380 is 3.80%
    downside: Decimal


@dataclass(frozen=True, slots=True)
class RateDeck:
    deck_id: str
    as_of: str
    years: tuple[RateDeckYear, ...]


def _stated(deck: RateDeck, reference_rate: str, offset: int) -> list[RateDeckYear]:
    return [
        year
        for year in deck.years
        if year.reference_rate == reference_rate and year.fiscal_year_offset <= offset
    ]


def rate_for(
    deck: RateDeck | None, reference_rate: str, case: Case, offset: int
) -> Decimal | None:
    """The deck's rate for the case at the year offset: the latest stated year
    at or before it, so a year past the deck holds its last rate flat. None
    with no deck, no row for the reference rate, or none that early."""
    if deck is None:
        return None
    stated = _stated(deck, reference_rate, offset)
    if not stated:
        return None
    year = max(stated, key=lambda row: row.fiscal_year_offset)
    return year.base if case == "BASE" else year.downside


def _deck_note(deck: RateDeck, reference_rate: str, offset: int) -> str | None:
    """Why the deck's rate for the year is not its own: the reference rate
    is not in the deck, the year is past the deck's last (held flat) or a
    year the deck skips (the year before it held)."""
    offsets = {
        year.fiscal_year_offset
        for year in deck.years
        if year.reference_rate == reference_rate
    }
    if not offsets:
        return NOT_IN_DECK
    if offset > max(offsets):
        return DECK_HELD_FLAT
    return None if offset in offsets else DECK_YEAR_MISSING


def _term_in_range(term: Decimal | None, bounds: tuple[Decimal, Decimal, bool]) -> bool:
    """A term not stated, or one inside its range (a whole number where it
    is basis points)."""
    low, high, whole = bounds
    if term is None:
        return True
    return low <= term <= high and (not whole or term == term.to_integral_value())


def _rate_terms_in_range(row: FacilityRow) -> bool:
    terms = (
        (row.spread_bps, _SPREAD),
        (row.floor_bps, _FLOOR),
        (row.fixed_rate, _COUPON),
    )
    return (
        not row.terms_out_of_range
        and row.rate_type in _RATE_TYPES
        and row.reference_rate in _REFERENCE_RATES
        and all(_term_in_range(term, bounds) for term, bounds in terms)
    )


def facility_rate(
    row: FacilityRow,
    deck: RateDeck | None,
    case: Case,
    offset: int,
    implied: Decimal | None,
) -> tuple[Decimal | None, str | None]:
    """The facility's all-in rate as a decimal, and the note when it is not
    its own terms': a `FIXED` coupon (percent) / 100; a `FLOATING` rate on a
    deck reference rate, `max(deck rate, floor) + spread`, noted where the
    deck year is held ("last deck rate held flat", "deck year missing");
    else `implied`, noted "implied rate", "no rate deck", "reference rate
    not in deck", "deck year missing" (none that early) or "term out of
    range" (a term outside CP-1's value set or its range)."""
    with localcontext(CONTEXT):
        if not _rate_terms_in_range(row):
            return implied, OUT_OF_RANGE
        if row.rate_type == "FIXED" and row.fixed_rate is not None:
            return row.fixed_rate / _PERCENT, None
        floating = row.rate_type == "FLOATING" and row.reference_rate in _DECK_RATES
        if not floating or row.spread_bps is None:
            return implied, IMPLIED
        if deck is None:
            return implied, NO_DECK
        note = _deck_note(deck, row.reference_rate, offset)
        reference = rate_for(deck, row.reference_rate, case, offset)
        if reference is None:
            return implied, note
        if row.floor_bps is not None:
            reference = max(reference, row.floor_bps / _BPS)
        return reference + row.spread_bps / _BPS, note

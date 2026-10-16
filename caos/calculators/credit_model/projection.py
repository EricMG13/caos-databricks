"""The projected columns: business-unit revenue, the amortisation schedule,
rate-deck interest and the cash flow, per case and year, chained (spec
M10-M14).

One column per (case, period) of CP-CF's request, Base and Downside only.
The base is the latest labelled historical FY, including an undated one:
if it is short, long or unknown under history's whole-month/slack rules,
every projected figure is COMPONENT_MISSING with the base reason. Structural
NOT_PROJECTED and NOT_APPLICABLE cells remain. No FY retains the existing
LTM/opening fallback. Requests still validate before figures are withheld.
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
coupon (as `model_inputs` reads it) outside 0-30 percent (from 0, a
zero-coupon convertible; 0.5-30 where read as a fraction), or any term CP-1
wrote so (a spread or floor written with `%`, or a coupon below half a
percent that no text decides, `terms_out_of_range`). The
rate falls back to the implied rate, and a negative amortisation to none,
each noted "term out of range". A `FIXED` coupon `model_inputs` read as a
fraction (`0.065` as 6.5 percent) is priced at the percent read, noted
"coupon read as a fraction"; that note also reaches the year's weighted
rate and cash interest (and so the coverage metrics built on it) where a
drawn, priced facility carries it, and no other facility-rate note does.

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
(none, with the opening's note, where the LTM's opening stack is incomplete;
noted "facility history incomplete" where the opening is CP-1's stated
total for that reason, as is a facility priced at it).
The year offset counts from the last historical FY (FY+1 is the year after);
a year past the deck holds its last rate, a year the deck skips the year
before it, each noted, and a reference rate the deck lacks is implied.

The aggregate debt roll-forward is CP-CF's: opening, less the scheduled
amortisation, plus issuance, less optional repayment (`debt_raised_net`),
plus PIK, capitalised interest and FX (`debt_non_cash`; absent is none).
Explicit equity and other investing/financing movements enter NCF; absent
equity retains the historical zero and note. Explicit restricted-cash
transfers adjust cash outside NCF, and carrying-value changes enter only
noncash debt. Secured debt sums the scheduled secured
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

With OWNED_CASH_DEBT_SERVICE explicitly selected, CP-1 validates the opening
and actual bridge, and a complete public cash-flow recomputation supplies the
aggregate cash/debt contract. No native facility schedule or rate determines
these totals. Instruments, secured debt, rates and RCF liquidity are expressly
unprojected; total debt remains visible as unallocated. Explicit validated
segment levels replace the slot growth for their row.

Pure: Decimal only, no I/O, no rounding.
"""

from __future__ import annotations

import calendar
import re
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import date
from decimal import Decimal, localcontext
from typing import Any

from caos.calculators.cash_flow import cash_flow_forecast
from caos.calculators.credit_model._cells import (
    ABSENT,
    CONTEXT,
    FOREIGN,
    calc,
    join_notes,
    periods_at,
    refs,
)
from caos.calculators.credit_model.debt import (
    COUPON_AS_FRACTION,
    TERMS_AS_BPS,
    EXCLUDES_FOREIGN,
    EXCLUDES_UNALLOCATED,
    HISTORY_INCOMPLETE,
    SECURED_RANKS,
    carried,
    facility_keys,
    is_operating_lease,
    left_out,
    notes_of,
    payment_rank,
)
from caos.calculators.credit_model.frame import Case, Cell, Column, Frame, SourceRef
from caos.calculators.credit_model.history import _fiscal_year_note, historical_columns
from caos.methodology.forecast_debt_service import validate_owned_debt_service
from caos.methodology.forecast_segments import validate_segment_revenue
from caos.methodology.model_inputs import (
    Cp1Registers,
    DivisionGrowth,
    FacilityRow,
    PeriodRow,
    SlotAllocation,
    coupon_in_range,
    fiscal_year_number,
)
from caos.refusals import Refusal, RefusalCode

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
OWNED_BASIS = "OWNED_CASH_DEBT_SERVICE"
OWNED_NOTE = "Cash debt-service basis: accepted CP-CF aggregate forecast"
ALLOCATION_NOTE = (
    "Aggregate cash debt-service forecast. Instrument allocation not supplied"
)
SEGMENT_NOTE = "explicit CP-2G forecast assumption"
RESTRICTED_NOTE = "restricted-cash transfer outside accessible cash"
OWNED_DIAGNOSTICS = (
    "secured_debt",
    "rcf_drawn",
    "undrawn_rcf",
    "liquidity",
    "reference_rate",
    "wa_rate",
    "interest_bearing_debt_opening",
    "metric:senior_secured_leverage",
    "metric:senior_secured_net_leverage",
    "metric:liquidity_to_debt",
)

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
# Each basis-point term's range; a basis-point term is a whole number.
_SPREAD = (Decimal(0), Decimal(2000))
_FLOOR = (Decimal(0), Decimal(1000))
# CP-1 states spreads and floors in integer basis points. One above nil and
# at most this (the highest percent a fixed coupon takes) reads like a whole
# percent ("3", "3.00"): priced as the basis points stated, and noted.
_WHOLE_PERCENT_MAX = Decimal(30)
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


@dataclass(frozen=True, slots=True)
class ProjectionInputs:
    regs: Cp1Registers
    request: Mapping[str, Any]  # CP-CF's accepted request
    growth: tuple[DivisionGrowth, ...]
    slots: tuple[SlotAllocation, ...]
    deck: RateDeck | None
    history: Frame  # `statement_frame` over `historical_columns(regs)`
    forecast_sources: Mapping[str, SourceRef] | None = None


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


def _term_in_range(term: Decimal | None, bounds: tuple[Decimal, Decimal]) -> bool:
    """A basis-point term not stated, or a whole number inside its range."""
    low, high = bounds
    if term is None:
        return True
    return low <= term <= high and term == term.to_integral_value()


def _rate_terms_in_range(row: FacilityRow) -> bool:
    terms = ((row.spread_bps, _SPREAD), (row.floor_bps, _FLOOR))
    return (
        not row.terms_out_of_range
        and row.rate_type in _RATE_TYPES
        and row.reference_rate in _REFERENCE_RATES
        and all(_term_in_range(term, bounds) for term, bounds in terms)
        and (
            row.fixed_rate is None
            or coupon_in_range(row.fixed_rate, as_fraction=row.coupon_as_fraction)
        )
    )


def _reads_like_percent(row: FacilityRow) -> bool:
    """Whether a spread or floor is above nil and at most `_WHOLE_PERCENT_MAX`."""
    return any(
        term is not None and 0 < term <= _WHOLE_PERCENT_MAX
        for term in (row.spread_bps, row.floor_bps)
    )


def facility_rate(
    row: FacilityRow,
    deck: RateDeck | None,
    case: Case,
    offset: int,
    implied: Cell,
) -> tuple[Decimal | None, str | None]:
    """The facility's all-in rate as a decimal, and the note when it is not
    its own terms': a `FIXED` coupon (percent) / 100, noted "coupon read as
    a fraction" where `model_inputs` read it so (a coupon below half a
    percent is read by its text: times 100, as stated, or, undecided, out of
    range, below); a `FLOATING` rate on a
    deck reference rate, `max(deck rate, floor) + spread`, noted where the
    deck year is held ("last deck rate held flat", "deck year missing");
    else the `implied` rate's figure, noted "implied rate", "no rate deck",
    "reference rate not in deck", "deck year missing" (none that early) or
    "term out of range" (a term outside CP-1's value set or its range), then
    with the implied rate's own note where it has a figure ("facility
    history incomplete"; without one, its reason is the weighted rate's)."""
    with localcontext(CONTEXT):
        if not _rate_terms_in_range(row):
            return _fallback(implied, OUT_OF_RANGE)
        if row.rate_type == "FIXED" and row.fixed_rate is not None:
            note = COUPON_AS_FRACTION if row.coupon_as_fraction else None
            return row.fixed_rate / _PERCENT, note
        floating = row.rate_type == "FLOATING" and row.reference_rate in _DECK_RATES
        if not floating or row.spread_bps is None:
            return _fallback(implied, IMPLIED)
        if deck is None:
            return _fallback(implied, NO_DECK)
        note = _deck_note(deck, row.reference_rate, offset)
        reference = rate_for(deck, row.reference_rate, case, offset)
        if reference is None:
            return _fallback(implied, note)
        note = join_notes((note, TERMS_AS_BPS if _reads_like_percent(row) else None))
        if row.floor_bps is not None:
            reference = max(reference, row.floor_bps / _BPS)
        return reference + row.spread_bps / _BPS, note


def _fallback(implied: Cell, note: str | None) -> tuple[Decimal | None, str | None]:
    """The implied rate's figure, noted why it is used, then with its own
    note where it has a figure."""
    if implied.value is None:
        return None, note
    return implied.value, join_notes((note, implied.note))


@dataclass(frozen=True, slots=True)
class _Period:
    case: Case
    period_id: str
    fiscal_year: str
    year: int
    days: int


@dataclass(frozen=True, slots=True)
class _Context:
    """What every projected year reads: the registers' facilities and
    segments, CP-2G's growth and allocation, the deck and the anchor."""

    regs: Cp1Registers
    deck: RateDeck | None
    drivers: dict[tuple[str, str], Mapping[str, Any]]
    growth: dict[tuple[str, int | None, str], Decimal]
    slot_of: dict[str, str]
    corporate: frozenset[str]
    facilities: tuple[FacilityRow, ...]  # at the opening, register order
    implied: Cell  # the LTM's implied rate, or why there is none
    undrawn: Cell  # the revolver undrawn at the opening, held
    left_out: frozenset[str]  # the totals a facility in another currency left
    base_year: int  # the last historical FY: FY+1 is the year after
    year_end: date  # its end date (31 December without one)
    base_note: str | None  # selected FY is not twelve whole months
    owned: dict[tuple[str, str], Mapping[str, Any]]
    request: Mapping[str, Any]
    forecast_sources: Mapping[str, SourceRef] | None
    driver_pointers: dict[tuple[str, str], str]


@dataclass(frozen=True, slots=True)
class _State:
    """A case's balances as a year opens."""

    business_units: dict[str, Cell]
    balances: dict[str, Decimal | None]
    cash: Cell
    debt: Cell


@dataclass(frozen=True, slots=True)
class _Schedule:
    """A year's facility cells, closing balances and scheduled amortisation."""

    cells: dict[str, Cell]
    balances: dict[str, Decimal | None]
    scheduled: Cell
    secured: Cell
    held: Cell  # in total debt but bearing no interest, at its opening
    rated: tuple[tuple[Decimal | None, Decimal | None], ...]  # (opening, rate)
    in_total: Cell  # the closing balances total debt counts
    fraction: bool = False  # a drawn, priced facility's coupon read as a fraction
    bps: bool = False  # a drawn, priced facility's spread or floor read as bp


def _malformed() -> Refusal:
    return Refusal(RefusalCode.HANDOFF_MALFORMED)


def _mapping(value: object) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise _malformed()
    return value


def _field(row: Mapping[str, Any], name: str) -> object:
    """The request's field; refused, typed, where it has none."""
    if name not in row:
        raise _malformed()
    return row[name]


def _text(row: Mapping[str, Any], name: str) -> str:
    value = _field(row, name)
    if not isinstance(value, str):
        raise _malformed()
    return value


def _rows(request: Mapping[str, Any], name: str) -> list[Mapping[str, Any]]:
    """The request's list of rows; refused, typed, where it is not one."""
    rows = _field(request, name)
    if not isinstance(rows, list):
        raise _malformed()
    return [_mapping(row) for row in rows]


def _number(value: object) -> Decimal:
    """A CP-CF figure; a request that is not one is refused, typed."""
    if not isinstance(value, str) or _NUMBER.fullmatch(value) is None:
        raise Refusal(RefusalCode.METHODOLOGY_INPUT_INVALID)
    return Decimal(value)


def _source(ctx: _Context | ProjectionInputs, pointer: str) -> tuple[SourceRef, ...]:
    """Pure callers may omit provenance; an explicitly supplied map is exact."""
    sources = ctx.forecast_sources
    if sources is None:
        return ()
    if pointer not in sources:
        raise _malformed()
    return (sources[pointer],)


def _driver_sources(ctx: _Context, period: _Period, name: str) -> tuple[SourceRef, ...]:
    pointer = ctx.driver_pointers[(period.case, period.period_id)]
    return _source(ctx, f"{pointer}/{name}")


def _driver(ctx: _Context, period: _Period, name: str, sign: int) -> Cell:
    """CP-CF's driver for the period, signed: `NOT_SOURCED` without the row or
    the field, `NOT_STATED` on a row that is not READY."""
    row = ctx.drivers.get((period.case, period.period_id))
    if row is None or name not in row:
        return ABSENT
    sources = _driver_sources(ctx, period, name)
    if row.get("status") != "READY":
        return Cell(None, "NOT_STATED", sources=sources, note=NOT_READY)
    value = _number(row[name]) * sign
    return Cell(
        value.copy_abs() if value.is_zero() else value, basis="DRIVER", sources=sources
    )


def _movement(ctx: _Context, period: _Period, name: str) -> Cell:
    """A non-cash debt movement CP-CF's request may leave out: absent is
    none."""
    cell = _driver(ctx, period, name, 1)
    return Cell(Decimal(0)) if cell.reason == "NOT_SOURCED" else cell


def _fy_end(ctx: _Context, year: int) -> date:
    """The fiscal year's end: the last historical FY's end date moved to
    `year` (the month's last day where it has fewer)."""
    target = ctx.year_end.year + year - ctx.base_year
    month = ctx.year_end.month
    day = min(ctx.year_end.day, calendar.monthrange(target, month)[1])
    return date(target, month, day)


def _matures_in(ctx: _Context, row: FacilityRow, year: int) -> bool:
    """Whether the facility's ISO maturity date falls in the fiscal year; a
    maturity that is not an ISO date is none the schedule can place."""
    if row.maturity_date is None:
        return False
    try:
        maturity = date.fromisoformat(row.maturity_date)
    except ValueError:
        return False
    return _fy_end(ctx, year - 1) < maturity <= _fy_end(ctx, year)


def _interest_bearing(row: FacilityRow, currency: str) -> bool:
    return (
        row.currency == currency
        and row.lease_classification not in {"FINANCE_LEASE", "OPERATING_LEASE"}
        and row.facility_type != _DEBT_ADJUSTMENT
    )


def _amortisation(row: FacilityRow) -> tuple[Decimal, str | None]:
    """The scheduled amortisation a year: none, noted, when not stated or
    negative."""
    if row.annual_amortisation is None:
        return Decimal(0), AMORTISATION_NOT_STATED
    if row.annual_amortisation < 0:
        return Decimal(0), OUT_OF_RANGE
    return row.annual_amortisation, None


def _balance_cell(value: Decimal | None, note: str | None) -> Cell:
    if value is None:
        return Cell(None, "COMPONENT_MISSING", note=note)
    return Cell(value, basis="PROJECTED", note=note)


def _held(row: FacilityRow, opening: Decimal | None, currency: str) -> Cell:
    """A facility the schedule does not amortise: an operating lease is not
    projected; another currency, a finance lease or the debt adjustment is
    held flat."""
    if is_operating_lease(row):
        return _NOT_PROJECTED
    return _balance_cell(opening, FOREIGN if row.currency != currency else HELD_FLAT)


def _schedule(ctx: _Context, state: _State, period: _Period) -> _Schedule:
    """Each facility's closing balance after the year's amortisation."""
    currency = ctx.regs.currency
    cells: dict[str, Cell] = {}
    balances: dict[str, Decimal | None] = {}
    scheduled: list[tuple[Cell, int]] = []
    secured: list[tuple[Cell, int]] = []
    held: list[tuple[Cell, int]] = []
    rated: list[tuple[Decimal | None, Decimal | None]] = []
    fraction = False
    bps = False
    in_total: list[tuple[Cell, int]] = []
    for row in ctx.facilities:
        opening = state.balances[row.facility_id]
        key = f"fac:{row.facility_id}"
        if not _interest_bearing(row, currency):
            balances[row.facility_id] = opening
            cells[key] = _held(row, opening, currency)
            if "total_debt" in facility_keys(row, currency):
                held.append((_balance_cell(opening, None), 1))
                in_total.append((cells[key], 1))
            continue
        amount, amortisation_note = _amortisation(row)
        paid: Decimal | None = None
        closing: Decimal | None = None
        if opening is not None:
            paid = max(Decimal(0), min(amount, opening))
            closing = opening - paid
        rate, rate_note = facility_rate(
            row, ctx.deck, period.case, period.year - ctx.base_year, ctx.implied
        )
        refinanced = REFINANCED if _matures_in(ctx, row, period.year) else None
        note = join_notes((rate_note, amortisation_note, refinanced))
        balances[row.facility_id] = closing
        cells[key] = _balance_cell(closing, note)
        if payment_rank(row) in SECURED_RANKS:
            secured.append((cells[key], 1))
        scheduled.append((_balance_cell(paid, None), 1))
        rated.append((opening, rate))
        fraction = fraction or (
            rate is not None
            and bool(opening)
            and COUPON_AS_FRACTION in notes_of(rate_note)
        )
        bps = bps or (
            rate is not None and bool(opening) and TERMS_AS_BPS in notes_of(rate_note)
        )
        in_total.append((cells[key], 1))
    return _Schedule(
        cells,
        balances,
        calc(scheduled),
        calc(secured),
        calc(held),
        tuple(rated),
        calc(in_total),
        fraction,
        bps,
    )


def _reference_rate(ctx: _Context, period: _Period) -> Cell:
    """The deck rate the first floating facility on a deck reference rate
    reads, noted as `facility_rate` notes it."""
    floating = next(
        (
            row
            for row in ctx.facilities
            if _interest_bearing(row, ctx.regs.currency)
            and _rate_terms_in_range(row)
            and row.rate_type == "FLOATING"
            and row.reference_rate in _DECK_RATES
        ),
        None,
    )
    if floating is None:
        return Cell(None, "NOT_APPLICABLE")
    offset = period.year - ctx.base_year
    if ctx.deck is None:
        return Cell(None, "NOT_SOURCED", note=NO_DECK)
    note = _deck_note(ctx.deck, floating.reference_rate, offset)
    rate = rate_for(ctx.deck, floating.reference_rate, period.case, offset)
    if rate is None:
        return Cell(None, "NOT_SOURCED", note=note)
    return Cell(rate, basis="DRIVER", note=note)


def _unweighted(implied: Cell, base: Cell) -> Cell:
    """The rate with no facility weight: the implied rate, noted (with its
    own note), on a positive base (debt CP-CF issued onto facilities at
    nil), else none."""
    if base.value is None or base.value <= 0:
        return Cell(None, "ZERO_OR_NEGATIVE_DENOMINATOR")
    if implied.value is None:
        return Cell(None, implied.reason, note=implied.note)
    note = join_notes((NO_MIX, implied.note))
    return Cell(implied.value, basis="CALCULATED", note=note)


@dataclass(frozen=True, slots=True)
class _Mix:
    """The weighted rate and, where facilities weight it, its two sums."""

    rate: Cell
    weighted: Decimal = Decimal(0)  # the sum of balance x rate
    weights: Decimal = Decimal(0)  # the sum of balance


def _mix(schedule: _Schedule, implied: Cell, base: Cell) -> _Mix:
    """The facilities' rates weighted on their opening scheduled balances. A
    balance missing, or a drawn facility's rate (only the implied rate can
    be missing), leaves none: the implied rate's own reason and note. With
    no facility weight but a positive base (debt CP-CF issued onto
    facilities at nil), the implied rate, noted; with no base either,
    none. The weighted rate is noted "coupon read as a fraction" where a
    drawn, priced facility's coupon was (`_Schedule.fraction`), and "spread or
    floor read as basis points" where its spread or floor was (`_Schedule.bps`),
    and only so."""
    known = [(opening, rate) for opening, rate in schedule.rated if opening is not None]
    if len(known) != len(schedule.rated):
        return _Mix(Cell(None, "COMPONENT_MISSING"))
    drawn = [(opening, rate) for opening, rate in known if opening != 0]
    priced = [(opening, rate) for opening, rate in drawn if rate is not None]
    if len(priced) != len(drawn):
        return _Mix(Cell(None, implied.reason, note=implied.note))
    weights = sum((opening for opening, _ in priced), Decimal(0))
    if weights <= 0:
        return _Mix(_unweighted(implied, base))
    weighted = sum((opening * rate for opening, rate in priced), Decimal(0))
    note = join_notes(
        (
            COUPON_AS_FRACTION if schedule.fraction else None,
            TERMS_AS_BPS if schedule.bps else None,
        )
    )
    return _Mix(
        Cell(weighted / weights, basis="CALCULATED", note=note), weighted, weights
    )


def _charge(mix: _Mix, rate: Decimal, base: Decimal) -> Decimal:
    """Minus the rate times a positive base, from the weights where there
    are any: no rounding through the weighted rate."""
    if mix.weights > 0:
        return -(mix.weighted * base / mix.weights)
    return -(rate * base)


def _interest(state: _State, schedule: _Schedule, implied: Cell) -> dict[str, Cell]:
    """The interest base, CP-CF's opening debt less what in it bears no
    interest (finance leases, the debt adjustment; another currency is in no
    total), with what that debt leaves out; its weighted rate; and the cash
    interest: none on no debt, none, noted, on a negative base. The interest
    carries the base's note, and the weighted rate's note where facilities
    weight it, not the no-mix reason."""
    base = calc(((state.debt, 1), (schedule.held, -1)), carried((state.debt,)))
    mix = _mix(schedule, implied, base)
    if base.value is None:
        interest = base
    elif base.value < 0:
        interest = Cell(None, "COMPONENT_MISSING", note=NEGATIVE_BASE)
    elif base.value == 0:
        interest = Cell(Decimal(0), basis="CALCULATED")
    elif mix.rate.value is None:
        interest = mix.rate
    else:
        charge = _charge(mix, mix.rate.value, base.value)
        # The weighted rate's note ("coupon read as a fraction") reaches the
        # interest; with no facility weight the rate's note is the no-mix
        # reason (and the implied rate's own), which stays on the rate.
        weighted_note = mix.rate.note if mix.weights > 0 else None
        note = join_notes((carried((base,)), weighted_note))
        interest = Cell(charge, basis="CALCULATED", note=note)
    return {
        "interest_bearing_debt_opening": base,
        "wa_rate": mix.rate,
        "cash_interest": interest,
    }


def _grown(ctx: _Context, segment: str, prior: Cell, period: _Period) -> Cell:
    """The segment's revenue: the prior year's times one plus its slot's
    growth; held flat in no slot or as corporate and eliminations."""
    slot = ctx.slot_of.get(segment)
    if prior.value is None:
        return Cell(None, "COMPONENT_MISSING", note=prior.note)
    if slot is None or segment in ctx.corporate:
        return Cell(prior.value, basis="PROJECTED", note=HELD_FLAT)
    growth = ctx.growth.get((period.case, period.year, slot))
    if growth is None:
        return ABSENT
    note = GROWTH_UNBOUNDED if abs(growth) > 1 else None
    return Cell(prior.value * (1 + growth), basis="PROJECTED", note=note)


def _revenue(
    ctx: _Context, state: _State, period: _Period
) -> tuple[dict[str, Cell], dict[str, Cell]]:
    """The `bu:` cells and revenue: CP-CF's, else (no revenue in its
    request) the business units' sum."""
    driver = ctx.drivers.get((period.case, period.period_id), {})
    if "segment_revenue" in driver:
        units = {
            segment: Cell(
                _number(value),
                basis="PROJECTED",
                note=SEGMENT_NOTE,
                sources=_driver_sources(ctx, period, f"segment_revenue/{segment}"),
            )
            if driver.get("status") == "READY"
            else Cell(
                None,
                "NOT_STATED",
                note=NOT_READY,
                sources=_driver_sources(ctx, period, f"segment_revenue/{segment}"),
            )
            for segment, value in driver["segment_revenue"].items()
        }
    else:
        units = {
            segment: _grown(ctx, segment, prior, period)
            for segment, prior in state.business_units.items()
        }
    cells = {f"bu:{segment}": cell for segment, cell in units.items()}
    revenue = _driver(ctx, period, "revenue", 1)
    if revenue.reason == "NOT_SOURCED" and units:
        revenue = calc((cell, 1) for cell in units.values())
    cells["revenue"] = revenue
    return units, cells


def _cash_flow(
    ctx: _Context, period: _Period, interest: Cell, scheduled: Cell
) -> dict[str, Cell]:
    """Adjusted EBITDA to the net cash flow, from CP-CF's drivers signed into
    the frame's convention, with the host's interest and amortisation."""
    ebitda = _driver(ctx, period, "ebitda", 1)
    other = calc(((_driver(ctx, period, "cfo", 1), 1), (ebitda, -1)), WORKING_CAPITAL)
    taxes = _driver(ctx, period, "cash_taxes", -1)
    capex = _driver(ctx, period, "capex", -1)
    cfo = calc(((ebitda, 1), (other, 1), (interest, 1), (taxes, 1)))
    fcf = calc(((cfo, 1), (capex, 1)))
    raised = calc(
        (
            (_driver(ctx, period, "issuance", 1), 1),
            (_driver(ctx, period, "optional_repayment", 1), -1),
            (scheduled, -1),
        )
    )
    flows = {
        # CP-CF deducts `acquisitions_disposals` from cash: an outflow.
        "acquisitions_net": _driver(ctx, period, "acquisitions_disposals", -1),
        "debt_raised_net": raised,
        "equity_raised_net": Cell(
            Decimal(0), basis="CALCULATED", note=NO_EQUITY_MOVEMENT
        ),
        "dividends": _driver(ctx, period, "distributions", -1),
    }
    driver = ctx.drivers.get((period.case, period.period_id), {})
    if "net_equity_issue_repay" in driver:
        flows["equity_raised_net"] = _driver(ctx, period, "net_equity_issue_repay", 1)
    if "other_investing_financing" in driver:
        flows["other_investing_financing"] = _driver(
            ctx, period, "other_investing_financing", 1
        )
    return {
        "adjusted_ebitda": ebitda,
        "cash_taxes": taxes,
        "other_operating": other,
        "cfo_adjusted": cfo,
        "capex": capex,
        "fcf": fcf,
        **flows,
        "ncf": calc([(fcf, 1), *((cell, 1) for cell in flows.values())]),
    }


def _year(
    ctx: _Context, state: _State, period: _Period
) -> tuple[dict[str, Cell], _State]:
    """One projected year's cells and the state the next opens with."""
    units, revenue = _revenue(ctx, state, period)
    if ctx.owned:
        cells = _owned_year(ctx, state, period, revenue)
        return cells, _State(units, {}, cells["cash_closing"], cells["debt_closing"])
    schedule = _schedule(ctx, state, period)
    interest = _interest(state, schedule, ctx.implied)
    flows = _cash_flow(ctx, period, interest["cash_interest"], schedule.scheduled)
    cash = calc(((state.cash, 1), (flows["ncf"], 1)))
    transfers = _cash_transfer(ctx, period)
    if transfers:
        cash = calc(((cash, 1), (transfers["fx_and_other_cash"], 1)))
    non_cash = calc((_movement(ctx, period, name), 1) for name in _NON_CASH)
    driver = ctx.drivers.get((period.case, period.period_id), {})
    if "carrying_value_change" in driver:
        non_cash = calc(
            ((non_cash, 1), (_driver(ctx, period, "carrying_value_change", 1), 1))
        )
    raised = flows["debt_raised_net"]
    debt = calc(((state.debt, 1), (raised, 1), (non_cash, 1)), carried((state.debt,)))
    cells = {
        **revenue,
        **flows,
        "cash_opening": state.cash,
        "cash_closing": cash,
        **transfers,
        **schedule.cells,
        "total_debt": debt,
        "secured_debt": _secured(ctx, schedule, debt),
        "net_debt": calc(((debt, 1), (cash, -1)), carried((debt,))),
        "undrawn_rcf": ctx.undrawn,
        "liquidity": calc(((cash, 1), (ctx.undrawn, 1))),
        "debt_opening": state.debt,
        "debt_non_cash": non_cash,
        "debt_closing": debt,
        "reference_rate": _reference_rate(ctx, period),
        **interest,
        **dict.fromkeys(_NOT_PROJECTED_KEYS, _NOT_PROJECTED),
        **{f"kpi:{row.kpi_id}": _NOT_PROJECTED for row in ctx.regs.kpis},
    }
    return cells, _State(units, schedule.balances, cash, debt)


def _cash_transfer(ctx: _Context, period: _Period) -> dict[str, Cell]:
    """An explicitly stated restricted-cash transfer, including zero."""
    driver = ctx.drivers.get((period.case, period.period_id), {})
    if "restricted_cash_change" not in driver:
        return {}
    cell = _driver(ctx, period, "restricted_cash_change", -1)
    return {
        "fx_and_other_cash": replace(
            cell, note=join_notes((cell.note, RESTRICTED_NOTE))
        )
    }


def _owned_rows(request: Mapping[str, Any]) -> dict[tuple[str, str], Mapping[str, Any]]:
    """Recompute the complete public cash contract, never native facility prices."""
    if request.get("projection_basis") != OWNED_BASIS:
        return {}
    result = cash_flow_forecast(request)
    if result["status"] != "complete":
        raise _malformed()
    return {(row["case"], row["period_id"]): row for row in result["rows"]}


def _principal_sources(ctx: _Context, period: _Period) -> tuple[SourceRef, ...]:
    rows = ctx.request["contractual"]["aggregate_amortisation"]
    identity = (period.case, period.period_id)
    return refs(
        source
        for index, row in enumerate(rows)
        if (row["case"], row["period_id"]) == identity
        for source in _source(
            ctx, f"/contractual/aggregate_amortisation/{index}/amount"
        )
    )


def _actual_sources(ctx: _Context, period: _Period) -> tuple[SourceRef, ...]:
    rows = ctx.request["actuals"]["debt_cash_movements"]
    period_id = period.period_id
    return refs(
        source
        for index, row in enumerate(rows)
        if row["period_id"] == period_id
        for source in _source(ctx, f"/actuals/debt_cash_movements/{index}/amount")
    )


def _owned_provenance(
    ctx: _Context, period: _Period, cells: dict[str, Cell]
) -> dict[str, Cell]:
    """Propagate actual operands without coupling the independent numeric check."""
    driver = ctx.drivers[(period.case, period.period_id)]
    noncash = refs(
        source
        for name in (*_NON_CASH, "carrying_value_change")
        if name in driver
        for source in _driver_sources(ctx, period, name)
    )
    cells["debt_non_cash"] = replace(cells["debt_non_cash"], sources=noncash)
    for target, operands in (
        ("cash_closing", ("ncf", "fx_and_other_cash", "cash_opening")),
        ("debt_closing", ("debt_raised_net", "debt_non_cash", "debt_opening")),
        ("total_debt", ("debt_closing",)),
        ("net_debt", ("debt_closing", "cash_closing")),
    ):
        sources = refs(
            source
            for operand in operands
            for source in cells.get(operand, ABSENT).sources
        )
        cells[target] = replace(cells[target], sources=sources)
    selector = _source(ctx, "/projection_basis")
    return {
        key: replace(cell, sources=refs((*cell.sources, *selector)))
        for key, cell in cells.items()
    }


def _owned_year(
    ctx: _Context, state: _State, period: _Period, revenue: dict[str, Cell]
) -> dict[str, Cell]:
    """Aggregate cash debt service; no inferred instrument or rate allocation."""
    # Public cash rows use NFC; keep the request's original identity elsewhere.
    row = ctx.owned[(period.case, unicodedata.normalize("NFC", period.period_id))]
    financing, debt, cash = row["financing"], row["debt"], row["cash"]
    interest = Cell(
        -Decimal(financing["cash_interest"]),
        basis="DRIVER",
        sources=_driver_sources(ctx, period, "cash_interest"),
    )
    principal = Cell(
        Decimal(financing["contractual_repayment"]),
        basis="DRIVER",
        sources=_principal_sources(ctx, period),
    )
    actual = Cell(
        Decimal(financing["actual_debt_cash_movement"]),
        basis="DRIVER",
        sources=_actual_sources(ctx, period),
    )
    flows = _cash_flow(ctx, period, interest, principal)
    flows["debt_raised_net"] = calc(((flows["debt_raised_net"], 1), (actual, 1)))
    flows["ncf"] = calc(((flows["ncf"], 1), (actual, 1)))
    non_cash = sum((Decimal(debt[name]) for name in _NON_CASH), Decimal(0)) + Decimal(
        debt.get("carrying_value_change", "0")
    )
    cells = {
        **revenue,
        **flows,
        **_cash_transfer(ctx, period),
        "cash_interest": interest,
        "contractual_repayment": replace(
            principal, value=-principal.value if principal.value else Decimal(0)
        ),
        "actual_debt_cash_movement": actual,
        "cash_opening": replace(
            state.cash, value=Decimal(cash["opening"]), reason=None, basis="CALCULATED"
        ),
        "cash_closing": Cell(Decimal(cash["closing"]), basis="CALCULATED"),
        "debt_opening": replace(
            state.debt, value=Decimal(debt["opening"]), reason=None, basis="CALCULATED"
        ),
        "debt_closing": Cell(Decimal(debt["closing"]), basis="CALCULATED"),
        "total_debt": Cell(Decimal(debt["closing"]), basis="CALCULATED"),
        "debt_non_cash": Cell(non_cash, basis="CALCULATED"),
        "net_debt": Cell(
            Decimal(debt["closing"]) - Decimal(cash["closing"]), basis="CALCULATED"
        ),
    }
    cells = _owned_provenance(ctx, period, cells)
    for key, cell in cells.items():
        cells[key] = replace(cell, note=join_notes((cell.note, OWNED_NOTE)))
    diagnostic = Cell(None, "NOT_PROJECTED", note=ALLOCATION_NOTE)
    cells.update(dict.fromkeys(_NOT_PROJECTED_KEYS, _NOT_PROJECTED))
    cells.update(dict.fromkeys(OWNED_DIAGNOSTICS, diagnostic))
    cells.update({f"fac:{r.facility_id}": diagnostic for r in ctx.regs.facilities})
    cells.update({f"rank:{payment_rank(r)}": diagnostic for r in ctx.regs.facilities})
    cells.update({f"kpi:{r.kpi_id}": _NOT_PROJECTED for r in ctx.regs.kpis})
    cells["debt:unallocated"] = Cell(
        Decimal(debt["closing"]),
        basis="CALCULATED",
        note=ALLOCATION_NOTE,
        sources=cells["total_debt"].sources,
    )
    return cells


def _secured(ctx: _Context, schedule: _Schedule, debt: Cell) -> Cell:
    """The scheduled secured balances, noted with a secured facility in
    another currency left out and with total debt moved off the schedule
    (CP-CF's unallocated movements, which carry no security)."""
    unallocated = calc(((debt, 1), (schedule.in_total, -1)))
    moved = unallocated.value is not None and unallocated.value != 0
    foreign = "secured_debt" in ctx.left_out
    notes = (
        EXCLUDES_FOREIGN if foreign else None,
        EXCLUDES_UNALLOCATED if moved else None,
    )
    secured = schedule.secured
    if secured.value is None:
        return secured
    return Cell(secured.value, basis=secured.basis, note=join_notes(notes))


def _undrawn(
    cells: Mapping[str, Cell], facilities: tuple[FacilityRow, ...], currency: str
) -> Cell:
    """The revolver's commitment less its drawing at the opening, held for
    every projected year: CP-1's `rcf_commitment` and `rcf_drawn` accounts,
    else the revolver's own row (a `facility_type` naming a revolver or RCF,
    in the register's currency); `NOT_SOURCED` with neither."""
    commitment = cells.get("acct:rcf_commitment", ABSENT)
    drawn = cells.get("acct:rcf_drawn", ABSENT)
    if "NOT_SOURCED" in {commitment.reason, drawn.reason}:
        rcf = next(
            (
                row
                for row in facilities
                if row.currency == currency
                and ("REVOLV" in row.facility_type or row.facility_type == "RCF")
            ),
            None,
        )
        if rcf is None:
            return ABSENT
        if rcf.commitment is None or rcf.drawn_amount is None:
            return Cell(None, "COMPONENT_MISSING")
        undrawn = rcf.commitment - rcf.drawn_amount
        return Cell(
            undrawn, basis="CALCULATED", sources=refs([rcf.source]), note=RCF_HELD
        )
    return calc(((commitment, 1), (drawn, -1)), RCF_HELD)


def _opening_cell(cell: Cell) -> Cell:
    """An anchor balance as the projection's opening: its figure, sourced,
    with what it leaves out; without one, why."""
    if cell.value is None:
        return Cell(None, "COMPONENT_MISSING", note=cell.note)
    return Cell(
        cell.value, basis="CALCULATED", sources=cell.sources, note=carried((cell,))
    )


def _implied(cells: Mapping[str, Cell]) -> Cell:
    """LTM cash interest over the average of the LTM's opening and closing
    total debt, noted `HISTORY_INCOMPLETE` where the opening is
    (`debt_frame`: CP-1's stated total, a facility's history missing);
    `COMPONENT_MISSING` without a figure, with the missing inputs' notes
    (the opening's "opening stack incomplete"), and
    `ZERO_OR_NEGATIVE_DENOMINATOR` with an average <= 0."""
    parts = [
        cells.get(key, ABSENT)
        for key in ("cash_interest", "debt_opening", "total_debt")
    ]
    interest, opening, closing = (part.value for part in parts)
    if interest is None or opening is None or closing is None:
        why = join_notes(tuple(part.note for part in parts if part.value is None))
        return Cell(None, "COMPONENT_MISSING", note=why)
    average = (opening + closing) / 2
    if average <= 0:
        return Cell(None, "ZERO_OR_NEGATIVE_DENOMINATOR")
    history = HISTORY_INCOMPLETE in notes_of(parts[1].note)
    return Cell(-interest / average, note=HISTORY_INCOMPLETE if history else None)


def _anchor_rows(
    regs: Cp1Registers, opened: Column | None, cells: Mapping[str, Cell]
) -> tuple[FacilityRow, ...]:
    """The terms of each facility with a `fac:` cell at the opening column:
    its row where the cell was read, the column's own period first, then
    any period ending that day (`periods_at`, as `debt_frame` reads)."""
    if opened is None:
        return ()
    rows: dict[str, FacilityRow] = {}
    for period_id in periods_at(regs, opened.period_id, opened.end_date):
        for row in regs.facilities:
            if row.period_id == period_id and f"fac:{row.facility_id}" in cells:
                rows.setdefault(row.facility_id, row)
    return tuple(rows.values())


def _periods(request: Mapping[str, Any]) -> list[_Period]:
    """CP-CF's Base and Downside periods, request order; a period without a
    four-digit fiscal year cannot be placed and is refused, and two for one
    case and year are malformed."""
    periods = []
    seen: set[tuple[Case, int]] = set()
    for row in _rows(request, "periods"):
        case = _CASES.get(_text(row, "case"))
        period_id, fiscal_year = _text(row, "period_id"), _text(row, "fiscal_year")
        days = _field(row, "days")
        if case is None:
            continue
        year = fiscal_year_number(fiscal_year)
        if year is None or not isinstance(days, str) or _WHOLE.fullmatch(days) is None:
            raise Refusal(RefusalCode.METHODOLOGY_INPUT_INVALID)
        if (case, year) in seen:
            raise _malformed()
        seen.add((case, year))
        periods.append(_Period(case, period_id, fiscal_year, year, int(days)))
    return periods


def _drivers(
    request: Mapping[str, Any],
) -> dict[tuple[str, str], Mapping[str, Any]]:
    """CP-CF's driver rows by case and period."""
    return {
        (_text(row, "case"), _text(row, "period_id")): row
        for row in _rows(request, "drivers")
    }


def _as_of(request: Mapping[str, Any]) -> object:
    """The period CP-CF's opening balances are at."""
    return _field(_mapping(_field(request, "opening")), "as_of_period_id")


def _opening(
    inputs: ProjectionInputs,
    facilities: tuple[FacilityRow, ...],
    anchor: Mapping[str, Cell],
    prior: Mapping[str, Cell],
) -> _State:
    """What each case opens with: the last FY's business units (a segment it
    has no row for is not projected) and the anchor's balances."""
    segments = dict.fromkeys(row.segment_id for row in inputs.regs.segments)
    units = {segment: prior.get(f"bu:{segment}", ABSENT) for segment in segments}
    cash = _opening_cell(anchor.get("cash_closing", ABSENT))
    debt = _opening_cell(anchor.get("total_debt", ABSENT))
    if inputs.forecast_sources is not None:
        cash = replace(
            cash,
            sources=refs((*_source(inputs, "/opening/cash"), *cash.sources)),
        )
        debt_sources = [
            source
            for index, _ in enumerate(inputs.request["opening"]["debt_by_facility"])
            for source in _source(inputs, f"/opening/debt_by_facility/{index}/amount")
        ]
        debt = replace(debt, sources=refs((*debt_sources, *debt.sources)))
    return _State(
        business_units={
            segment: cell
            for segment, cell in units.items()
            if cell.reason != "NOT_SOURCED"
        },
        balances={
            row.facility_id: anchor[f"fac:{row.facility_id}"].value
            for row in facilities
        },
        cash=cash,
        debt=debt,
    )


@dataclass(frozen=True, slots=True)
class _Request:
    """What the projection reads from CP-CF's request, its shape checked."""

    periods: list[_Period]
    drivers: dict[tuple[str, str], Mapping[str, Any]]
    as_of: object


# A request year the projection places: 1900-2200, within this of the base.
_FIRST_YEAR, _LAST_YEAR, _YEARS_FROM_BASE = 1900, 2200, 10


def _placed(periods: list[_Period], base_year: int) -> int:
    """`base_year`, refused (`HANDOFF_MALFORMED`) where a period's year is
    outside 1900-2200 or more than ten years from it: no fiscal year end
    could be placed for it."""
    for period in periods:
        in_range = _FIRST_YEAR <= period.year <= _LAST_YEAR
        if not in_range or abs(period.year - base_year) > _YEARS_FROM_BASE:
            raise _malformed()
    return base_year


def _context(inputs: ProjectionInputs, request: _Request) -> tuple[_Context, _State]:
    """The context every year reads and the state each case opens with.
    Balances open at the historical column of CP-CF's `as_of_period_id`,
    else the last FY (the host LTM without one); the implied rate is the
    host LTM's; the base year the latest labelled historical FY, even if
    undated (the year before the first projected one without one).
    Its span determines whether all projected figures must be withheld."""
    regs = inputs.regs
    columns = historical_columns(regs)
    ltm = next((column for column in columns if column.kind == "LTM"), None)
    anchor = inputs.history.get(ltm.column_id, {}) if ltm is not None else {}
    last_fy = max(
        (column for column in reversed(columns) if column.kind == "FY"),
        key=lambda column: fiscal_year_number(column.fiscal_year) or 0,
        default=None,
    )
    prior = inputs.history.get(last_fy.column_id, {}) if last_fy is not None else {}
    first = min(period.year for period in request.periods)
    base_year = _placed(
        request.periods,
        (fiscal_year_number(last_fy.fiscal_year) if last_fy is not None else None)
        or first - 1,
    )
    end = last_fy.end_date if last_fy is not None else None
    named = next(
        (column for column in columns if column.period_id == request.as_of), None
    )
    opened = named or last_fy or ltm
    opening_cells = (
        inputs.history.get(opened.column_id, {}) if opened is not None else {}
    )
    facilities = _anchor_rows(regs, opened, opening_cells)
    periods: dict[str | None, PeriodRow] = {p.period_id: p for p in regs.periods}
    base_note = (
        None if last_fy is None else _fiscal_year_note(periods[last_fy.period_id])
    )
    context = _Context(
        regs=regs,
        deck=inputs.deck,
        drivers=request.drivers,
        growth={
            (g.case, fiscal_year_number(g.fiscal_year), g.slot_id): g.value
            for g in inputs.growth
        },
        slot_of={
            segment: slot.slot_id
            for slot in inputs.slots
            for segment in slot.component_segment_ids
        },
        corporate=frozenset(
            row.segment_id
            for row in regs.segments
            if row.segment_type == "CORPORATE_ELIMINATION"
        ),
        facilities=facilities,
        implied=_implied(anchor),
        undrawn=_undrawn(opening_cells, facilities, regs.currency),
        left_out=left_out(facilities, regs.currency),
        base_year=base_year,
        year_end=date.fromisoformat(end) if end else date(base_year, 12, 31),
        base_note=base_note,
        owned=_owned_rows(inputs.request),
        request=inputs.request,
        forecast_sources=inputs.forecast_sources,
        driver_pointers={
            (_text(row, "case"), _text(row, "period_id")): f"/drivers/{index}"
            for index, row in enumerate(_rows(inputs.request, "drivers"))
        },
    )
    return context, _opening(inputs, facilities, opening_cells, prior)


def projection(inputs: ProjectionInputs) -> tuple[tuple[Column, ...], Frame]:
    """The projected columns, Base then Downside in CP-CF's request order,
    and their frame: business-unit revenue, the cash flow from CP-CF's
    drivers, each facility's schedule, interest and the cash and debt
    roll-forwards, each year opening at the one before it. An incomplete
    selected base FY withholds every numeric figure, for every case/year,
    after request validation; structural unprojected/nonapplicable cells remain."""
    with localcontext(CONTEXT):
        validate_segment_revenue(inputs.request, inputs.regs)
        validate_owned_debt_service(inputs.request, inputs.regs)
        request = _Request(
            _periods(inputs.request), _drivers(inputs.request), _as_of(inputs.request)
        )
        if not request.periods:
            return (), {}
        context, opening = _context(inputs, request)
        states: dict[Case, _State] = {}
        columns: list[Column] = []
        frame: Frame = {}
        for period in request.periods:
            state = states.get(period.case, opening)
            cells, states[period.case] = _year(context, state, period)
            if context.base_note is not None:
                refused = Cell(
                    None,
                    "COMPONENT_MISSING",
                    note=f"projection base: {context.base_note}",
                )
                cells = {
                    key: cell
                    if cell.reason in {"NOT_PROJECTED", "NOT_APPLICABLE"}
                    else refused
                    for key, cell in cells.items()
                }
            column = Column(
                column_id=f"{period.case}:{period.fiscal_year}",
                kind="PROJECTED",
                label=f"FY{period.year % 100:02d}E",
                period_id=period.period_id,
                fiscal_year=period.fiscal_year,
                end_date=_fy_end(context, period.year).isoformat(),
                days=period.days,
                case=period.case,
            )
            columns.append(column)
            frame[column.column_id] = cells
        return tuple(columns), frame

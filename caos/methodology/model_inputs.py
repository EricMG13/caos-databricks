"""CP-1, CP-2G and CP-CF tagged tables read into the credit model's typed inputs.

A row's figure is the host's own reading of the cell (`TableCell.value`, read
with `Decimal`, invariant 7); the cell's text stands verbatim, `[C<n>]` markers
kept, in its `SourceRef` (D107). An enumerated column's text that names a
member of its closed vocabulary on case and separators (`_`, `-` and
whitespace alike) reads as that member's canonical spelling, so
`DEBT_ADJUSTMENT` is `DEBT ADJUSTMENT`; any other text reads in upper case.

A table the run did not write reads as no rows, except the period register:
the currency and unit every figure is in come from it, so without it nothing
reads. A present table missing a column it needs, a row whose width is not its
header's, a null in a required enumerated column, or a period register stating
two currencies or two units, is `HANDOFF_MALFORMED`; so is one register id
twice in one period, two periods for one fiscal quarter, YTD or year, a
fiscal year without a four-digit year, more than `MAX_PERIODS` periods, a
period naming one component twice or nesting components more than
`MAX_NESTING` deep (or in a cycle), a fiscal year outside 1900-2200 or more
than a year from its period's end date's year, a start or end date that is
not a `YYYY-MM-DD` calendar date in 1900-2200, a start after the end, a day
count that is not the dates' own (end - start + 1) or not positive, a figure
that is not finite, of `MAX_FIGURE` or more in size, or written to more than
`MAX_DECIMALS` decimals (never rounded silently), a negative facility
carrying value other than a `DEBT ADJUSTMENT` row's (CP-MODEL's
`validate_cp_model_inputs` rule), a negative facility commitment or drawing
(on any row), a negative RCF commitment or drawing, and one READY growth
driver written twice for a case, year and slot. The rate and amortisation
columns the CP-1 fork added (owner-authorised 2026-10-10) are absent from an
older run's debt register: they read as `NOT_STATED` or no value, never as a
fault. A rate term written in the wrong unit (a spread or floor written with
`%` or not a whole number of basis points, a fixed coupon outside 0-30
percent) is kept as read, the row flagged `terms_out_of_range`. A fixed
coupon is CP-1's decimal percent (`6.500`): 0 is a zero-coupon convertible,
as stated. On a `FIXED` row, a coupon strictly between 0 and 0.5 written
without `%` is a decimal fraction written in place of the percent, read
times 100 (`0.065` is 6.5 percent) and flagged `coupon_as_fraction`; the
figure read is then in range from 0.5 to 30. The cost: a genuine coupon
below half a percent written without `%` reads 100 times over, flagged. A
coupon written with `%` is the percent it states, and on any other row the
coupon is as written.
An account row whose calculation status is Not Available or Not Calculable
has no value, whatever figure it carries. A period's accounting basis and
entity perimeter are read as written, and as not stated where null or where
the run predates those columns.

Pure: no I/O.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_EVEN, Context, Decimal

from caos.calculators.credit_model.frame import Case, SourceRef
from caos.methodology.citation_markers import unmarked
from caos.methodology.tables import HandoffTable, TableCell
from caos.refusals import Refusal, RefusalCode

_PERIODS = "cp1.model_period_register"
_ACCOUNTS = "cp1.model_account_register"
_ADDBACKS = "cp1.adjusted_ebitda_bridge"
_SEGMENTS = "cp1.segment_revenue_schedule"
_KPIS = "cp1.operating_kpi_schedule"
_FACILITIES = "cp1.debt_facility_register"
_PRO_FORMA = "cp1.pro_forma_adjustment_register"
_ALLOCATION = "cp1.cp_model_segment_allocation"
_DRIVERS = "cp2g.cp_model_forecast_drivers"

# CP-MODEL's own null text (`validate_cp_model_inputs.NULL_TEXT`): not the
# bundle's wider vocabulary, whose `none` is a reference rate here.
_NULL_TEXT = frozenset(
    {"", "null", "n/a", "not available", "not calculable", "-", "\u2014", "\u2013"}
)
# The closed vocabularies, each member in its canonical spelling: CP-MODEL's
# validator's own sets, CP-1's statuses (REF_CP-1_STEPS, two of which are
# also null text: there they are a status, never a null) and rate terms, and
# the one facility type the host reads (the column is otherwise open).
_PERIOD_TYPES = frozenset({"QUARTER", "YTD", "FY", "LTM", "PERIOD_END"})
_PERIOD_UNITS = frozenset({"UNITS", "THOUSANDS", "MILLIONS"})
_CALCULATION_STATUSES = frozenset(
    {
        "VERIFIED",
        "CALCULATED",
        "ESTIMATED",
        "PROXY",
        "NOT CALCULABLE",
        "PARTIAL",
        "CONFLICTED",
        "NOT AVAILABLE",
    }
)
# The statuses under which an account row has no figure (CP-MODEL's
# validator: "zero cannot stand in for unavailable/null").
_UNAVAILABLE = frozenset({"NOT CALCULABLE", "NOT AVAILABLE"})
_ADDBACK_CLASSIFICATIONS = frozenset(
    {
        "RESTRUCTURING",
        "SBC",
        "COST_SAVINGS",
        "RUN_RATE",
        "SYNERGY",
        "TRANSACTION_COSTS",
        "OTHER_EXPLICIT",
    }
)
_REALIZATION_STATUSES = frozenset({"REALIZED", "UNREALIZED", "NOT_STATED"})
_SEGMENT_TYPES = frozenset({"OPERATING_SEGMENT", "CORPORATE_ELIMINATION"})
_KPI_VALUE_TYPES = frozenset({"PERIOD_END", "PERIOD_FLOW", "RATE"})
_FACILITY_TYPES = frozenset({"DEBT ADJUSTMENT"})
_SECURED_STATUSES = frozenset({"SECURED", "UNSECURED", "NOT_STATED"})
_SENIORITIES = frozenset(
    {
        "SUPER_SENIOR",
        "SENIOR",
        "SENIOR_SUBORDINATED",
        "SUBORDINATED",
        "JUNIOR",
        "NOT_STATED",
    }
)
_LEASE_CLASSIFICATIONS = frozenset(
    {"FINANCE_LEASE", "OPERATING_LEASE", "NOT_LEASE", "NOT_STATED"}
)
_PF_CLASSIFICATIONS = frozenset(
    {
        "ACQUISITION",
        "DISPOSAL",
        "REFINANCING",
        "SUBSEQUENT_EVENT",
        "LENDER_UPDATE",
        "OTHER_EXPLICIT",
    }
)
_RATE_TYPES = frozenset({"FIXED", "FLOATING", "NOT_STATED"})
_REFERENCE_RATES = frozenset(
    {"SOFR", "TERM_SOFR", "EURIBOR", "SONIA", "NONE", "NOT_STATED"}
)
_DRIVER_CASES = frozenset({"BASE", "DOWNSIDE"})
_DRIVER_STATUSES = frozenset({"READY", "NOT_APPLICABLE"})
_DRIVER_UNITS = frozenset({"PERCENT_DECIMAL", "CURRENCY_MM"})
_SEPARATORS = re.compile(r"[\s_-]+")
_LIST_SEPARATOR = re.compile(r"[;,]")
_FOUR_DIGITS = re.compile(r"(?<!\d)\d{4}(?!\d)")
# A fiscal year spelt over two years: `2025/26`, `2025-2026`, `2025 - 26`.
_TWO_YEARS = re.compile(r"(?<!\d)(\d{4})\s*[/-]\s*(\d{4}|\d{2})(?!\d)")
_ISO_DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
_FIRST_YEAR, _LAST_YEAR = 1900, 2200
# The longest period two dates in that range can span.
_MAX_DAYS = (date(_LAST_YEAR, 12, 31) - date(_FIRST_YEAR, 1, 1)).days + 1
MAX_PERIODS = 200
# A figure's bounds: below 10^18 in size, at most 10 decimals, so it has at
# most 28 significant digits and every sum the model takes of such figures
# stays exact at precision 38; a product or quotient of two can need more,
# and is rounded half to even at the 38th digit (`_cells.CONTEXT`).
MAX_FIGURE = Decimal(10) ** 18
MAX_DECIMALS = 10
_PLACES = Decimal(1).scaleb(-MAX_DECIMALS)
# Room for any figure's 28 digits, whatever the caller's context.
_ROUNDING = Context(prec=38, rounding=ROUND_HALF_EVEN)
# A fixed coupon in percent, from 0 (a zero-coupon convertible); outside it,
# a term in the wrong unit.
_COUPON_RANGE = (Decimal(0), Decimal(30))
# On a `FIXED` row, a coupon above 0 and below this, written without `%`, is
# a decimal fraction written in place of the percent, read times 100; read
# so, it is at least this.
_FRACTION_BELOW = Decimal("0.5")
_BPS_TERMS = ("spread_bps", "floor_bps")
MAX_NESTING = 4  # a period's components, theirs, and so on, at most this deep
_DEBT_ADJUSTMENT = "DEBT ADJUSTMENT"
_RCF_BALANCES = frozenset({"rcf_drawn", "rcf_commitment"})
_CASES: dict[str, Case] = {"BASE": "BASE", "DOWNSIDE": "DOWNSIDE"}

_Row = Mapping[str, TableCell]


@dataclass(frozen=True, slots=True)
class PeriodRow:
    period_id: str
    fiscal_year: str
    fiscal_quarter: str | None
    period_type: str  # QUARTER|YTD|FY|LTM|PERIOD_END
    start_date: str | None
    end_date: str | None
    day_count: int | None
    currency: str
    unit: str
    component_period_ids: tuple[str, ...]
    # CP-1's `accounting_basis` and `entity_perimeter`: None where not stated
    # (a null, or a run that predates the columns).
    accounting_basis: str | None = None
    entity_perimeter: str | None = None


@dataclass(frozen=True, slots=True)
class AccountRow:
    metric_id: str
    period_id: str
    value: Decimal | None
    calculation_status: str
    source: SourceRef | None


@dataclass(frozen=True, slots=True)
class AddbackRow:
    addback_id: str
    label: str
    classification: str
    realization_status: str
    display_priority: int
    period_id: str
    value: Decimal | None
    source: SourceRef | None


@dataclass(frozen=True, slots=True)
class SegmentRow:
    segment_id: str
    segment_name: str
    segment_type: str
    display_priority: int
    period_id: str
    revenue: Decimal | None
    source: SourceRef | None


@dataclass(frozen=True, slots=True)
class KpiRow:
    kpi_id: str
    kpi_label: str
    display_priority: int
    period_id: str
    value: Decimal | None
    unit: str
    value_type: str  # PERIOD_END|PERIOD_FLOW|RATE
    source: SourceRef | None


@dataclass(frozen=True, slots=True)
class FacilityRow:
    facility_id: str
    facility_name: str
    period_id: str
    facility_type: str
    currency: str
    carrying_value: Decimal | None
    commitment: Decimal | None
    drawn_amount: Decimal | None
    secured_status: str
    seniority: str
    lease_classification: str
    maturity_date: str | None
    margin_or_coupon: str
    rate_type: str
    reference_rate: str
    spread_bps: Decimal | None
    floor_bps: Decimal | None
    fixed_rate: Decimal | None
    annual_amortisation: Decimal | None
    source: SourceRef | None
    # A spread or floor written with `%` or not whole basis points, or a
    # fixed coupon (as read) outside 0-30 percent (0.5-30 read as a
    # fraction): the terms are not priced.
    terms_out_of_range: bool = False
    # The fixed coupon was written as a decimal fraction (strictly between 0
    # and 0.5) and `fixed_rate` is it times 100.
    coupon_as_fraction: bool = False


@dataclass(frozen=True, slots=True)
class PfAdjustmentRow:
    adjustment_id: str
    label: str
    period_id: str
    classification: str
    metric_id: str
    value: Decimal
    source: SourceRef | None


@dataclass(frozen=True, slots=True)
class Cp1Registers:
    periods: tuple[PeriodRow, ...]
    accounts: tuple[AccountRow, ...]
    addbacks: tuple[AddbackRow, ...]
    segments: tuple[SegmentRow, ...]
    kpis: tuple[KpiRow, ...]
    facilities: tuple[FacilityRow, ...]
    pro_forma: tuple[PfAdjustmentRow, ...]
    currency: str
    unit: str


@dataclass(frozen=True, slots=True)
class DivisionGrowth:
    case: Case
    fiscal_year: str
    slot_id: str
    value: Decimal  # PERCENT_DECIMAL, READY rows only


@dataclass(frozen=True, slots=True)
class SlotAllocation:
    slot_id: str
    component_segment_ids: tuple[str, ...]


def _malformed() -> Refusal:
    return Refusal(RefusalCode.HANDOFF_MALFORMED)


def _table(tables: Sequence[HandoffTable], table_id: str) -> HandoffTable | None:
    return next((table for table in tables if table.table_id == table_id), None)


def _rows(table: HandoffTable | None, required: frozenset[str]) -> list[_Row]:
    """`table`'s rows keyed by column; none for an absent table, and refused
    for a present one missing a `required` column or with a ragged row."""
    if table is None:
        return []
    if not required <= set(table.columns):
        raise _malformed()
    if any(len(row) != len(table.columns) for row in table.rows):
        raise _malformed()
    return [dict(zip(table.columns, row, strict=True)) for row in table.rows]


def _read[T](
    tables: Sequence[HandoffTable],
    table_id: str,
    required: frozenset[str],
    reader: Callable[[_Row], T],
) -> tuple[T, ...]:
    return tuple(reader(row) for row in _rows(_table(tables, table_id), required))


def _text(row: _Row, column: str) -> str:
    return unmarked(row[column].text).strip()


def _optional(row: _Row, column: str) -> str | None:
    """The column's text, or None for a null or an absent column."""
    if column not in row:
        return None
    text = _text(row, column)
    return None if text.casefold() in _NULL_TEXT else text


def _key(text: str) -> str:
    """`text` casefolded, each run of `_`, `-` and whitespace one space."""
    return _SEPARATORS.sub(" ", text.casefold()).strip()


def _member(text: str, vocabulary: frozenset[str]) -> str | None:
    """The member of `vocabulary` `text` names on case and separators, in its
    canonical spelling; None for none."""
    key = _key(text)
    return next((m for m in vocabulary if _key(m) == key), None)


def _enum(row: _Row, column: str, vocabulary: frozenset[str] = frozenset()) -> str:
    """A required enumerated column: a member of `vocabulary` in its canonical
    spelling, else the text in upper case; refused when null (a member is
    never null, though it read as null text)."""
    text = _text(row, column) if column in row else ""
    member = _member(text, vocabulary)
    if member is not None:
        return member
    if text.casefold() in _NULL_TEXT:
        raise _malformed()
    return text.upper()


def _rate_term(row: _Row, column: str, vocabulary: frozenset[str]) -> str:
    """A rate term the CP-1 fork added, read as `_enum` reads; `NOT_STATED`
    where the column is absent (an older run) or null."""
    if _optional(row, column) is None:
        return "NOT_STATED"
    return _enum(row, column, vocabulary)


def _figure(row: _Row, column: str) -> Decimal | None:
    """The host's reading of the cell's figure; None for no figure or no
    column. Refused when it is not finite, is `MAX_FIGURE` or more in size,
    or has more than `MAX_DECIMALS` decimals. A negative zero (how "(0)"
    reads) is zero."""
    text = row[column].value if column in row else None
    if text is None:
        return None
    value = Decimal(text)
    if not value.is_finite() or abs(value) >= MAX_FIGURE:
        raise _malformed()
    if -int(value.as_tuple().exponent) > MAX_DECIMALS:
        raise _malformed()
    return value.copy_abs() if value.is_zero() else value


def _integer(row: _Row, column: str) -> int | None:
    value = _figure(row, column)
    if value is None:
        return None
    if value != value.to_integral_value():
        raise _malformed()
    return int(value)


def _priority(row: _Row) -> int:
    priority = _integer(row, "display_priority")
    if priority is None:
        raise _malformed()
    return priority


def _ids(row: _Row, column: str) -> tuple[str, ...]:
    text = _optional(row, column)
    if text is None:
        return ()
    return tuple(part.strip() for part in _LIST_SEPARATOR.split(text) if part.strip())


def _source(row: _Row, figure_column: str) -> SourceRef | None:
    """Where the row's figure came from, its cell text verbatim; None when the
    row names no source."""
    source_id = _optional(row, "source_id")
    if source_id is None:
        return None
    return SourceRef(
        source_id=source_id,
        source_locator=_optional(row, "source_locator") or "",
        cell_text=row[figure_column].text,
    )


_PERIOD_COLUMNS = frozenset(
    {
        "period_id",
        "fiscal_year",
        "fiscal_quarter",
        "period_type",
        "start_date",
        "end_date",
        "day_count",
        "currency",
        "unit",
        "component_period_ids",
    }
)


def _end_year(start: str, end: str) -> int | None:
    """The year a two-year spelling ends in: `2025/2026` and `2025/26` are
    2026; None where the second year does not follow the first."""
    first = int(start)
    if len(end) == 4:
        return int(end) if int(end) == first + 1 else None
    return first + 1 if int(end) == (first + 1) % 100 else None


def fiscal_year_number(text: str) -> int | None:
    """A fiscal year's four-digit year: a two-year spelling's END year
    (`FY2025/26`, `FY2025/2026` and `2025-26` are all 2026), else the last
    run of exactly four digits in its text (`2025`, `FY2025`); None without
    one."""
    for start, end in reversed(_TWO_YEARS.findall(text)):
        year = _end_year(start, end)
        if year is not None:
            return year
    runs = _FOUR_DIGITS.findall(text)
    return int(runs[-1]) if runs else None


def iso_date(text: str | None) -> date | None:
    """`text` as a calendar date where it is written exactly `YYYY-MM-DD`
    (ASCII digits); None otherwise, or for None."""
    if text is None or _ISO_DATE.fullmatch(text) is None:
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:  # `2025-02-30`, `0000-01-01`: no such day
        return None


def _date(row: _Row, column: str) -> date | None:
    """The column's date; None for a null; refused when it is not a
    `YYYY-MM-DD` calendar date from 1900 to 2200."""
    text = _optional(row, column)
    if text is None:
        return None
    day = iso_date(text)
    if day is None or not _FIRST_YEAR <= day.year <= _LAST_YEAR:
        raise _malformed()
    return day


def _span(row: _Row) -> tuple[date | None, date | None, int | None]:
    """The period's start, end and day count; refused unless the day count is
    positive and, with both dates, is their span (end - start + 1)."""
    start, end = _date(row, "start_date"), _date(row, "end_date")
    days = _integer(row, "day_count")
    if start is not None and end is not None:
        if start > end:
            raise _malformed()
        if days is not None and days != (end - start).days + 1:
            raise _malformed()
    if days is not None and not 1 <= days <= _MAX_DAYS:
        raise _malformed()
    return start, end, days


def _components(row: _Row) -> tuple[str, ...]:
    """The period's component ids, refused when one is named twice."""
    ids = _ids(row, "component_period_ids")
    if len(set(ids)) != len(ids):
        raise _malformed()
    return ids


def _fiscal_year(row: _Row, end: date | None) -> str:
    """The period's fiscal year, refused without a four-digit year from 1900
    to 2200 or, with an end date, more than a year from the end's year (a
    fiscal year is named for the year it starts or ends in)."""
    text = _text(row, "fiscal_year")
    year = fiscal_year_number(text)
    if year is None or not _FIRST_YEAR <= year <= _LAST_YEAR:
        raise _malformed()
    if end is not None and abs(year - end.year) > 1:
        raise _malformed()
    return text


def _period(row: _Row) -> PeriodRow:
    start, end, days = _span(row)
    return PeriodRow(
        period_id=_text(row, "period_id"),
        fiscal_year=_fiscal_year(row, end),
        fiscal_quarter=_optional(row, "fiscal_quarter"),
        period_type=_enum(row, "period_type", _PERIOD_TYPES),
        start_date=None if start is None else start.isoformat(),
        end_date=None if end is None else end.isoformat(),
        day_count=days,
        currency=_enum(row, "currency"),
        unit=_enum(row, "unit", _PERIOD_UNITS),
        component_period_ids=_components(row),
        accounting_basis=_optional(row, "accounting_basis"),
        entity_perimeter=_optional(row, "entity_perimeter"),
    )


_ACCOUNT_COLUMNS = frozenset(
    {
        "metric_id",
        "period_id",
        "value",
        "calculation_status",
        "source_id",
        "source_locator",
    }
)


def _account(row: _Row) -> AccountRow:
    """An account row; a negative RCF commitment or drawing (a balance, never
    an outflow) is refused. Under a calculation status in `_UNAVAILABLE` the
    value is null whatever figure the row carries."""
    metric_id = _text(row, "metric_id")
    value = _figure(row, "value")
    if metric_id in _RCF_BALANCES and value is not None and value < 0:
        raise _malformed()
    status = _enum(row, "calculation_status", _CALCULATION_STATUSES)
    return AccountRow(
        metric_id=metric_id,
        period_id=_text(row, "period_id"),
        value=None if status in _UNAVAILABLE else value,
        calculation_status=status,
        source=_source(row, "value"),
    )


_ADDBACK_COLUMNS = frozenset(
    {
        "addback_id",
        "addback_label",
        "addback_classification",
        "realization_status",
        "display_priority",
        "period_id",
        "value",
        "source_id",
        "source_locator",
    }
)


def _addback(row: _Row) -> AddbackRow:
    return AddbackRow(
        addback_id=_text(row, "addback_id"),
        label=_text(row, "addback_label"),
        classification=_enum(row, "addback_classification", _ADDBACK_CLASSIFICATIONS),
        realization_status=_enum(row, "realization_status", _REALIZATION_STATUSES),
        display_priority=_priority(row),
        period_id=_text(row, "period_id"),
        value=_figure(row, "value"),
        source=_source(row, "value"),
    )


_SEGMENT_COLUMNS = frozenset(
    {
        "segment_id",
        "segment_name",
        "segment_type",
        "display_priority",
        "period_id",
        "revenue",
        "source_id",
        "source_locator",
    }
)


def _segment(row: _Row) -> SegmentRow:
    return SegmentRow(
        segment_id=_text(row, "segment_id"),
        segment_name=_text(row, "segment_name"),
        segment_type=_enum(row, "segment_type", _SEGMENT_TYPES),
        display_priority=_priority(row),
        period_id=_text(row, "period_id"),
        revenue=_figure(row, "revenue"),
        source=_source(row, "revenue"),
    )


_KPI_COLUMNS = frozenset(
    {
        "kpi_id",
        "kpi_label",
        "display_priority",
        "period_id",
        "value",
        "unit",
        "value_type",
        "source_id",
        "source_locator",
    }
)


def _kpi(row: _Row) -> KpiRow:
    return KpiRow(
        kpi_id=_text(row, "kpi_id"),
        kpi_label=_text(row, "kpi_label"),
        display_priority=_priority(row),
        period_id=_text(row, "period_id"),
        value=_figure(row, "value"),
        unit=_enum(row, "unit"),
        value_type=_enum(row, "value_type", _KPI_VALUE_TYPES),
        source=_source(row, "value"),
    )


# Not the rate and amortisation columns: an older run's register has none.
_FACILITY_COLUMNS = frozenset(
    {
        "facility_id",
        "facility_name",
        "period_id",
        "facility_type",
        "currency",
        "carrying_value",
        "drawn_amount",
        "commitment",
        "secured_status",
        "seniority",
        "margin_or_coupon",
        "maturity_date",
        "lease_classification",
        "source_id",
        "source_locator",
    }
)


def _non_negative(row: _Row, column: str) -> Decimal | None:
    """The column's figure, refused when negative."""
    value = _figure(row, column)
    if value is not None and value < 0:
        raise _malformed()
    return value


def coupon_percent(written: Decimal) -> tuple[Decimal, bool]:
    """A fixed coupon in CP-1's percent, and whether it was read as a
    fraction: a figure strictly between 0 and 0.5 is a decimal fraction
    written in place of the percent, read times 100 (`0.065` is 6.5); any
    other figure is as written. `_facility` applies it only to a `FIXED`
    row's coupon written without `%`."""
    if 0 < written < _FRACTION_BELOW:
        return written.scaleb(2, _ROUNDING), True
    return written, False


def coupon_in_range(coupon: Decimal, *, as_fraction: bool) -> bool:
    """Whether a fixed coupon in percent (as read) is priced: 0-30 inclusive
    (from 0, a zero-coupon convertible); 0.5-30 where it was read as a
    fraction."""
    low, high = _COUPON_RANGE
    return (_FRACTION_BELOW if as_fraction else low) <= coupon <= high


def _coupon(row: _Row, rate_type: str) -> tuple[Decimal | None, bool]:
    """The fixed coupon in percent, and whether it was read as a fraction:
    only a `FIXED` row's coupon written without `%` is (`coupon_percent`);
    any other is as written."""
    written = _figure(row, "fixed_rate")
    if written is None or rate_type != "FIXED" or "%" in _text(row, "fixed_rate"):
        return written, False
    return coupon_percent(written)


def _out_of_range(row: _Row, coupon: Decimal | None, as_fraction: bool) -> bool:
    """Whether a rate term is written in the wrong unit: a spread or floor
    with `%` in its text or not whole basis points, or a fixed coupon (as
    read) out of its range."""
    for column in _BPS_TERMS:
        value = _figure(row, column)
        if value is None:
            continue
        if "%" in _text(row, column) or value != value.to_integral_value():
            return True
    return coupon is not None and not coupon_in_range(coupon, as_fraction=as_fraction)


def _facility(row: _Row) -> FacilityRow:
    """A debt row; a negative carrying value is refused except on a
    `DEBT ADJUSTMENT` row (CP-MODEL's validator's own rule), a negative
    commitment or drawing on any row."""
    facility_type = _enum(row, "facility_type", _FACILITY_TYPES)
    carrying = _figure(row, "carrying_value")
    if carrying is not None and carrying < 0 and facility_type != _DEBT_ADJUSTMENT:
        raise _malformed()
    rate_type = _rate_term(row, "rate_type", _RATE_TYPES)
    coupon, as_fraction = _coupon(row, rate_type)
    return FacilityRow(
        facility_id=_text(row, "facility_id"),
        facility_name=_text(row, "facility_name"),
        period_id=_text(row, "period_id"),
        facility_type=facility_type,
        currency=_enum(row, "currency"),
        carrying_value=carrying,
        commitment=_non_negative(row, "commitment"),
        drawn_amount=_non_negative(row, "drawn_amount"),
        secured_status=_enum(row, "secured_status", _SECURED_STATUSES),
        seniority=_enum(row, "seniority", _SENIORITIES),
        lease_classification=_enum(row, "lease_classification", _LEASE_CLASSIFICATIONS),
        maturity_date=_optional(row, "maturity_date"),
        margin_or_coupon=_text(row, "margin_or_coupon"),
        rate_type=rate_type,
        reference_rate=_rate_term(row, "reference_rate", _REFERENCE_RATES),
        spread_bps=_figure(row, "spread_bps"),
        floor_bps=_figure(row, "floor_bps"),
        fixed_rate=coupon,
        annual_amortisation=_figure(row, "annual_amortisation"),
        source=_source(row, "carrying_value"),
        terms_out_of_range=_out_of_range(row, coupon, as_fraction),
        coupon_as_fraction=as_fraction,
    )


_PRO_FORMA_COLUMNS = frozenset(
    {
        "adjustment_id",
        "label",
        "period_id",
        "effective_date",
        "classification",
        "metric_id",
        "value",
        "source_id",
        "source_locator",
    }
)


def _pro_forma(row: _Row) -> PfAdjustmentRow:
    """A stated adjustment; one with no figure is no adjustment, and refused."""
    value = _figure(row, "value")
    if value is None:
        raise _malformed()
    return PfAdjustmentRow(
        adjustment_id=_text(row, "adjustment_id"),
        label=_text(row, "label"),
        period_id=_text(row, "period_id"),
        classification=_enum(row, "classification", _PF_CLASSIFICATIONS),
        metric_id=_text(row, "metric_id"),
        value=value,
        source=_source(row, "value"),
    )


def _one(values: set[str]) -> str:
    """The one value every period row states, or refused."""
    if len(values) != 1:
        raise _malformed()
    return next(iter(values))


def _distinct[T](
    rows: tuple[T, ...], key: Callable[[T], tuple[str, ...]]
) -> tuple[T, ...]:
    """`rows`, refused when two share a key: one register id in one period is
    one figure, never two for the model to choose between."""
    keys = [key(row) for row in rows]
    if len(set(keys)) != len(keys):
        raise _malformed()
    return rows


def _fiscal_period(period: PeriodRow) -> tuple[str, int | None, str] | None:
    """The fiscal period a quarter, YTD or FY covers: its type, year and
    quarter (`2` and `Q2` alike); None for any other period, or a quarter or
    YTD without a fiscal quarter."""
    year = fiscal_year_number(period.fiscal_year)
    if period.period_type == "FY":
        return "FY", year, ""
    if period.period_type in {"QUARTER", "YTD"} and period.fiscal_quarter:
        return period.period_type, year, period.fiscal_quarter.upper().removeprefix("Q")
    return None


def _one_each(periods: tuple[PeriodRow, ...]) -> tuple[PeriodRow, ...]:
    """`periods`, refused when two cover one fiscal quarter, YTD or year:
    the model would have to choose between them."""
    covered = [key for p in periods if (key := _fiscal_period(p)) is not None]
    if len(set(covered)) != len(covered):
        raise _malformed()
    return periods


def _depth(
    period_id: str,
    components: Mapping[str, tuple[str, ...]],
    depths: dict[str, int],
    open_ids: frozenset[str],
) -> int:
    """How deep the period's components nest (none: 0); refused past
    `MAX_NESTING` or in a cycle. `depths` keeps each period's, so a period
    named by many is walked once."""
    if period_id in depths:
        return depths[period_id]
    if period_id in open_ids:
        raise _malformed()
    inner = open_ids | {period_id}
    parts = components.get(period_id, ())
    depth = max((_depth(p, components, depths, inner) + 1 for p in parts), default=0)
    if depth > MAX_NESTING:
        raise _malformed()
    depths[period_id] = depth
    return depth


def _bounded(periods: tuple[PeriodRow, ...]) -> tuple[PeriodRow, ...]:
    """`periods`, refused past `MAX_PERIODS` or nested past `MAX_NESTING`:
    the model's work grows with both."""
    if len(periods) > MAX_PERIODS:
        raise _malformed()
    components = {p.period_id: p.component_period_ids for p in periods}
    depths: dict[str, int] = {}
    for period in periods:
        _depth(period.period_id, components, depths, frozenset())
    return periods


def cp1_registers(tables: Sequence[HandoffTable]) -> Cp1Registers:
    """CP-1's period, account, add-back, segment, KPI, debt and pro forma
    registers as typed rows, in the currency and unit of the period register.
    A period id written twice, a register id written twice for one period, two
    periods for one fiscal quarter, YTD or year, a fiscal year without a
    four-digit year, or more periods or deeper components than the model
    reads, is refused."""
    periods = _bounded(
        _distinct(
            _one_each(_read(tables, _PERIODS, _PERIOD_COLUMNS, _period)),
            lambda p: (p.period_id,),
        )
    )
    if not periods:
        raise _malformed()
    return Cp1Registers(
        periods=periods,
        accounts=_distinct(
            _read(tables, _ACCOUNTS, _ACCOUNT_COLUMNS, _account),
            lambda a: (a.metric_id, a.period_id),
        ),
        addbacks=_distinct(
            _read(tables, _ADDBACKS, _ADDBACK_COLUMNS, _addback),
            lambda b: (b.addback_id, b.period_id),
        ),
        segments=_distinct(
            _read(tables, _SEGMENTS, _SEGMENT_COLUMNS, _segment),
            lambda g: (g.segment_id, g.period_id),
        ),
        kpis=_distinct(
            _read(tables, _KPIS, _KPI_COLUMNS, _kpi),
            lambda k: (k.kpi_id, k.period_id),
        ),
        facilities=_distinct(
            _read(tables, _FACILITIES, _FACILITY_COLUMNS, _facility),
            lambda f: (f.facility_id, f.period_id),
        ),
        pro_forma=_distinct(
            _read(tables, _PRO_FORMA, _PRO_FORMA_COLUMNS, _pro_forma),
            lambda a: (a.adjustment_id, a.period_id),
        ),
        currency=_one({p.currency for p in periods}),
        unit=_one({p.unit for p in periods}),
    )


_DRIVER_COLUMNS = frozenset(
    {"driver_id", "slot_id", "case", "fiscal_year", "value", "unit", "status"}
)


def _fraction(row: _Row) -> Decimal:
    """A READY growth driver's value as a decimal fraction, CP-MODEL's
    convention (`validate_cp_model_inputs._number`): a cell written with `%`
    divides by 100, where the host's figure keeps the points, then is
    rounded half to even to `MAX_DECIMALS` decimals where that leaves more.
    Refused when the unit is not `PERCENT_DECIMAL` or the row has no
    value."""
    value = _figure(row, "value")
    if _enum(row, "unit", _DRIVER_UNITS) != "PERCENT_DECIMAL" or value is None:
        raise _malformed()
    if "%" not in unmarked(row["value"].text):
        return value
    # The exponent moves two places, exactly: no context rounds it.
    sign, digits, exponent = value.as_tuple()
    fraction = Decimal((sign, digits, int(exponent) - 2))
    if -int(fraction.as_tuple().exponent) <= MAX_DECIMALS:
        return fraction
    return fraction.quantize(_PLACES, context=_ROUNDING)


def _growth(row: _Row) -> DivisionGrowth | None:
    """The row as a division-growth driver, or None when it is another
    driver, not READY, or of a case the model does not read."""
    if _text(row, "driver_id").casefold() != "division_growth":
        return None
    case = _CASES.get(_enum(row, "case", _DRIVER_CASES))
    if _enum(row, "status", _DRIVER_STATUSES) != "READY" or case is None:
        return None
    return DivisionGrowth(
        case, _text(row, "fiscal_year"), _enum(row, "slot_id"), _fraction(row)
    )


def _growth_key(growth: DivisionGrowth) -> tuple[str, ...]:
    """The case, year and slot a growth figure is for; the year as its
    four-digit year (`FY2027` is `2027`) where it has one."""
    year = fiscal_year_number(growth.fiscal_year)
    written = growth.fiscal_year if year is None else str(year)
    return growth.case, written, growth.slot_id


def division_growth(tables: Sequence[HandoffTable]) -> tuple[DivisionGrowth, ...]:
    """CP-2G's READY `division_growth` drivers for the base and downside cases
    (`cp2g.cp_model_forecast_drivers`), each a decimal fraction; two for one
    case, year and slot are refused."""
    rows = _rows(_table(tables, _DRIVERS), _DRIVER_COLUMNS)
    return _distinct(
        tuple(growth for row in rows if (growth := _growth(row)) is not None),
        _growth_key,
    )


_ALLOCATION_COLUMNS = frozenset({"slot_id", "component_segment_ids"})


def slot_allocation(tables: Sequence[HandoffTable]) -> tuple[SlotAllocation, ...]:
    """CP-1's forecast-slot allocation (`cp1.cp_model_segment_allocation`):
    each slot and the segment ids it binds; a segment bound to two slots
    would grow twice, and is refused."""
    slots = tuple(
        SlotAllocation(_enum(row, "slot_id"), _ids(row, "component_segment_ids"))
        for row in _rows(_table(tables, _ALLOCATION), _ALLOCATION_COLUMNS)
    )
    segments = [segment for slot in slots for segment in slot.component_segment_ids]
    if len(set(segments)) != len(segments):
        raise _malformed()
    return slots

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
`%` or not a whole number of basis points, a fixed coupon below 0.5 or above
30 percent) is kept as read, the row flagged `terms_out_of_range`.

Pure: no I/O.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence
from datetime import date
from decimal import Decimal

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
# A figure's bounds: below 10^18 in size, at most 10 decimals, so every sum
# and product the model takes of it stays exact at precision 38.
MAX_FIGURE = Decimal(10) ** 18
MAX_DECIMALS = 10
# A fixed coupon in percent; outside it, a decimal read as a percent.
_COUPON_RANGE = (Decimal("0.5"), Decimal(30))
_BPS_TERMS = ("spread_bps", "floor_bps")
MAX_NESTING = 4  # a period's components, theirs, and so on, at most this deep
_DEBT_ADJUSTMENT = "DEBT ADJUSTMENT"
_RCF_BALANCES = frozenset({"rcf_drawn", "rcf_commitment"})
_CASES: dict[str, Case] = {"BASE": "BASE", "DOWNSIDE": "DOWNSIDE"}

_Row = Mapping[str, TableCell]


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

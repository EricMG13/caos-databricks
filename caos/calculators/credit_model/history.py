"""The historical columns and the frame of CP-1's figures over them (spec M2).

Columns run quarters, PYTD, YTD, FY, then LTM. Every reported quarter is a
column; where CP-1's period register has no quarter, one is calculated as
H1 - Q1, 9M - H1 or FY - 9M when both periods exist.

The anchor is the latest end date of a quarter, YTD or FY period. At a
fiscal-year end there is no YTD and the LTM is that FY when it is twelve whole
months (a 52- or 53-week year is); a short or long FY (a transition year) or an
undated one is no LTM, its flows `COMPONENT_MISSING` noted "short fiscal year
(id)", "long fiscal year (id)" or `UNSPANNED`. Otherwise the YTD is
the YTD period ending at the anchor, else the anchor year's quarters to date
when every one is a column (a YTD's fiscal quarter is its register label, else,
as CP-1 leaves it null on every period that is not a QUARTER, its whole
months as quarters: 6 months is H1); the PYTD is the prior year's YTD period of the
same fiscal quarter, else (by its dates, its fiscal quarter not required) the
one YTD period of the same whole months starting a year earlier, else
the prior year's same quarters; and the LTM is FY + YTD - PYTD with the FY of
the prior year, the PYTD's, so the months always number twelve. A period is
n whole months when the day after it ends lies within `SLACK_DAYS` (7) days
of its first day plus n months, `WEEK_SLACK_DAYS` (14) where its length is a
whole number of weeks (a 14-week quarter), one n at most; a year earlier is
within `SLACK_DAYS` of twelve months earlier, so 52/53-week calendars
resolve; periods that follow one another meet exactly (end + 1 day = next
start). The dates
leave the PYTD ambiguous where a YTD period ends before the YTD starts, or
has no dates, but not exactly one dated period is that one (or the YTD is
not whole months); without the prior year's quarters either, the LTM's flows
are then `COMPONENT_MISSING`, noted `UNSPANNED`.
CP-1's LTM row ending at the anchor names the LTM column and supplies the
stated figures; one ending later than the anchor keeps its own column,
its flows `COMPONENT_MISSING` with CP-1's figure as `stated` (spec M4: the
host recomputes, it never adopts CP-1's arithmetic).

The LTM's FY must end the day before its YTD starts, its PYTD start with
that FY, and its YTD and PYTD be as many days long within `SLACK_DAYS`;
otherwise its flows are `COMPONENT_MISSING`, noted `UNSPANNED`. The twelve
months ending a quarter are its four quarters only where they tile and,
as one span, are twelve whole months: each part's slack never adds up.

A recurring sparse item's (a lease or interest payment classed in
financing) interim without a row counts as nothing in that LTM only when
the other interim has none either (the LTM is then the FY's); with some of
its FY, YTD and PYTD stated and another without a row, its LTM is
`COMPONENT_MISSING`, noted `PARTLY_STATED`, never a sum over 18 or 6
months, and so are its twelve months ending a quarter with some quarters
stated and another without a row. An add-back is a one-off that CP-1 writes
only for the periods it occurred in: any of these without a row is nothing,
noted `treated_as_zero` with its name. (An FY without a row beside a stated
PYTD inside it already resolves `COMPONENT_MISSING`, noted `UNSPANNED`, by
its cover.)

Every row of an outflow account in `OUTFLOW_METRICS` (cash taxes are signed:
a positive one is a refund) is read as minus its absolute value before
anything is summed, so CP-1 writing a quarter positive
and a year negative reads one way; a cell whose figure came from a row
written positive is noted `SIGN_NORMALISED`, and so is every sum of it.

A flow on a reported column is CP-1's figure. A derived column (a calculated
quarter, a YTD or PYTD built from quarters, the LTM, and a YTD or FY period
that names its component periods) adds and subtracts its components; CP-1's
own figure for that column is kept as `stated` and noted when it differs
beyond its rounding. A period's named components must be distinct periods,
each starting the day after the one before ends, from its start date to its
end date (a period without a start date starts its day count before its
end); otherwise its derived cells are `COMPONENT_MISSING`, noted
`UNSPANNED`. A period with no row is `NOT_SOURCED`, and one whose row
has no figure `NOT_STATED`. A sum with a component that has no figure, or
that is not a period, is `COMPONENT_MISSING`; with no row for any component
it is `NOT_SOURCED`; with rows for only some, `COMPONENT_MISSING`.

A sparse item (an add-back; a lease or interest payment classed in
financing) has rows only for the periods it occurred in, so it resolves
bottom-up: a period's figure is its own row (noted "differs from components"
where its parts disagree beyond its rounding: often an add-back is disclosed
only for a half or a year, so that row is the only figure), else the sum of
its components, or else of its cover: from its start date, the longest other
period starting then and ending within it that has a figure (a half or 9M
before its quarters), else the shortest such period without a row, which is
nothing, repeated from the day after the part taken ends; a part with the
period's own dates gives only its own row. A cover counts only where its
parts tile the period to its end date: a day on which no part starts is a
gap. Over a gap the period's own row stands un-noted, and a period without
a row is `COMPONENT_MISSING`, noted `UNSPANNED` (`NOT_SOURCED` where no part
has a row): a partial sum is never the period's figure. Every part without
a row is `NOT_SOURCED`, and a part with a null figure `COMPONENT_MISSING`.
Each period is resolved once per item, so the work is polynomial in the
periods. Columns then add and subtract these resolved figures (the LTM is
FY + YTD - PYTD of them).

For any other flow, a component that is itself a YTD or FY with components
is their sum, one level deep. A balance is the observation at the column's
end date: the column's own period first, then any period ending that day, in
register order. A RATE KPI, and an account in neither metric list, is shown
only on its own period.

`model_inputs.cp1_registers` refuses a register id written twice for one
period, two periods for one fiscal quarter, YTD or year, a fiscal year
without a four-digit year, a date that is not `YYYY-MM-DD`, more than 200
periods and components nested past four deep or in a cycle, so every key and
period here has one row and every fiscal period one period. Registers built
otherwise never raise here: a date that is not one is no date. Fiscal years
compare as that four-digit year (`FY2025` is `2025`, `FY2024/25` is
`2025`).

A period on another footing than the anchor's (`_cells.off_footing`)
enters no other period's figure, and, without its own row of a sparse item,
has none of it either (never its parts', on the anchor's footing). Whatever
the anchor states, a figure whose periods (a column's own and its terms'; a
period and its components; a sparse period and its parts with a figure;
the four quarters of twelve months) state a basis, or a perimeter, two
ways is `COMPONENT_MISSING`, noted `OTHER_FOOTING` (`combined_footing`).

Pure: Decimal only, no I/O, no rounding.
"""

from __future__ import annotations

import calendar
import operator
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass, field, replace
from datetime import date
from decimal import Decimal, localcontext
from typing import Literal

from caos.calculators.credit_model._cells import (
    ABSENT,
    CONTEXT,
    DIFFERS,
    OTHER_FOOTING,
    SIGN_NORMALISED,
    UNSPANNED,
    UNSTATED_FOOTING,
    Footing,
    Footings,
    anchor_period,
    beyond_rounding,
    calc,
    combined_footing,
    footing_of,
    join_notes,
    no_negative_zero,
    odd_year,
    off_footing,
    refs,
    treated_as_zero,
)
from caos.calculators.credit_model.frame import Cell, Column, Frame, SourceRef
from caos.methodology.model_inputs import (
    Cp1Registers,
    PeriodRow,
    fiscal_year_number,
    iso_date,
)

FLOW_METRICS = frozenset(
    {
        "revenue",
        "cogs",
        "gross_profit",
        "opex_including_da",
        "ebit",
        "depreciation_amortization",
        "ebitda",
        "adjusted_ebitda",
        "cash_interest_paid",
        "cash_lease_payments",
        "cash_taxes_paid",
        "cfo_ncfo",
        "working_capital_change",
        "capex_and_intangible_investment",
        "acquisitions_disposals",
        "net_debt_issue_repay",
        "net_equity_issue_repay",
        "dividends_paid",
        "other_investing_financing",
        "net_cash_change",
        "pretax_income",
        "income_tax_expense",
        "operating_lease_cost",
        "lease_payments_in_financing",
        "interest_paid_in_financing",
    }
)
# The expense and outflow accounts, sign-agnostic in CP-1's register: each
# row is read as minus its absolute value (`statements.OUTFLOW_METRICS`).
# Cash taxes are not one: CP-1 writes inflows positive, so a positive cash
# tax is a refund and keeps its sign.
OUTFLOW_METRICS = frozenset(
    {
        "cogs",
        "opex_including_da",
        "depreciation_amortization",
        "cash_interest_paid",
        "cash_lease_payments",
        "capex_and_intangible_investment",
        "operating_lease_cost",
        "lease_payments_in_financing",
        "interest_paid_in_financing",
        "dividends_paid",
    }
)
BALANCE_METRICS = frozenset(
    {
        "cash_and_equivalents",
        "rcf_commitment",
        "rcf_drawn",
        "senior_secured_debt",
        "unsecured_debt",
        "total_debt",
        "net_accounts_receivable",
        "inventory",
        "accounts_payable",
    }
)

_YTD_LABELS = {1: "Q1", 2: "H1", 3: "9M", 4: "12M"}
_QUARTERS = {f"{prefix}{n}": n for n in range(1, 5) for prefix in ("", "Q")}
_ADDITIVE = frozenset({"YTD", "FY"})
# A period is n whole months when the day after it ends lies within this many
# days of its first day plus n months, and a year earlier within this many
# days of twelve months earlier: 52/53-week calendars shift by days. Periods
# that follow one another still meet exactly (end + 1 day = next start).
SLACK_DAYS = 7
# A span of whole weeks (a 52/53-week calendar's 14-week quarter is 8 days
# over January-March) is n whole months within this many days; two n within
# it are none.
WEEK_SLACK_DAYS = 14

# "sparse" is a flow CP-1 writes only for the periods it occurred in (an
# add-back, a lease or interest payment classed in financing): a period
# without a row is its parts' sum, and a quarter without one is nothing.
# "flow" needs a row for every period it sums.
_Kind = Literal["flow", "sparse", "balance", "exact"]


@dataclass(frozen=True, slots=True)
class _Spec:
    """A column and how its cells are read."""

    column: Column
    own: str | None  # the register period the column is, if any
    terms: tuple[_Term, ...] | None  # None: the own period as reported
    stated: str | None = None  # where CP-1 stated a derived column's figure
    # (read only when `terms` is set)
    quarter: tuple[int, int] | None = None  # (fiscal year, quarter) of a quarter
    unbuilt: str | None = None  # why the terms cannot be summed, if they cannot


# A term adds (+1) or subtracts (-1) a register period's figure, a column's
# cell, or nothing: None is a component that does not exist.
_Term = tuple["str | _Spec | None", int]
_UNBUILT: tuple[_Term, ...] = ((None, 1),)  # no component the host can build


@dataclass(frozen=True, slots=True)
class _Series:
    kind: _Kind
    # Each row's cell, keyed by period id; None, no period, is never a key.
    rows: dict[str | None, Cell]
    # A sparse item's resolved cell per period, each worked out once; and
    # the periods whose working out has started: one met again before it is
    # resolved is in a cycle (`cp1_registers` refuses them), which stops at
    # that period's own row.
    resolved: dict[str | None, Cell] = field(default_factory=dict)
    started: set[str | None] = field(default_factory=set)
    # The footing of each period's figure as worked out, where it has one:
    # its own row's, else its and its parts' (`combined_footing`).
    footed: dict[str | None, Footing] = field(default_factory=dict)
    # An add-back: a one-off, so twelve months take an interim or a quarter
    # without a row as nothing, noted (never `PARTLY_STATED`).
    one_off: bool = False


@dataclass(frozen=True, slots=True)
class _Register:
    periods: dict[str | None, PeriodRow]  # None is never a key
    ending: dict[str | None, tuple[str, ...]]  # end date -> ids, register order
    # Start date -> the dated flow periods starting then, register order:
    # what a sparse item's cover of a period is chosen from.
    starting: dict[str, tuple[PeriodRow, ...]]
    # Every dated period as (first day, last day, id), shortest first, then
    # in register order: the order `_resolve_within` works periods out in.
    shortest: tuple[tuple[int, int, str], ...] = ()
    # The periods on another footing (`off_footing`): in no other's figure.
    off: frozenset[str | None] = frozenset()
    # Each period's own footing (`footing_of`).
    footings: dict[str | None, Footing] = field(default_factory=dict)


def _quarter_number(period: PeriodRow) -> int | None:
    """The register's fiscal quarter, `2` or `Q2`, as 1 to 4; else None."""
    if period.fiscal_quarter is None:
        return None
    return _QUARTERS.get(period.fiscal_quarter.upper())


def _ytd_quarter(period: PeriodRow) -> int | None:
    """A period's fiscal quarter (`_quarter_number`). CP-1 leaves it null
    on every period that is not a QUARTER, so a YTD without one takes it
    from its whole months since the fiscal year began (`_whole_months`), as
    quarters: 3 months is 1, 6 is 2, 9 is 3 and 12 is 4. Else None."""
    if period.fiscal_quarter is not None or period.period_type != "YTD":
        return _quarter_number(period)
    months = _whole_months(_dated(period))
    if months is None or months[1] % 3:
        return None
    return _QUARTERS.get(str(months[1] // 3))


def _year(period: PeriodRow) -> int | None:
    return fiscal_year_number(period.fiscal_year)


def _yy(fiscal_year: str) -> str:
    """The year's last two digits: of its four-digit year where it has one."""
    year = fiscal_year_number(fiscal_year)
    return fiscal_year[-2:] if year is None else f"{year % 100:02d}"


def _by_end(periods: Iterable[PeriodRow]) -> list[PeriodRow]:
    return sorted(periods, key=lambda period: period.end_date or "")


def _of_type(regs: Cp1Registers, period_type: str) -> list[PeriodRow]:
    return [p for p in regs.periods if p.period_type == period_type]


def _by_quarter(
    periods: Iterable[PeriodRow],
) -> dict[tuple[int | None, int], PeriodRow]:
    """Each (fiscal year, quarter: `_ytd_quarter`) to its period. Neither of
    two periods for one is (`cp1_registers` refuses a second only where
    both are labelled)."""
    index: dict[tuple[int | None, int], PeriodRow] = {}
    seen: set[tuple[int | None, int]] = set()
    for period in periods:
        number = _ytd_quarter(period)
        if number is None:
            continue
        key = (_year(period), number)
        if key in seen:
            index.pop(key, None)
        else:
            index[key] = period
        seen.add(key)
    return index


def _days(minuend: PeriodRow, subtrahend: PeriodRow) -> int | None:
    if minuend.day_count is None or subtrahend.day_count is None:
        return None
    return minuend.day_count - subtrahend.day_count


def _quarter_spec(
    period: PeriodRow,
    number: int | None,
    own: str | None,
    terms: tuple[_Term, ...] | None,
) -> _Spec:
    """A quarter's column, labelled `Q{n} {yy}`; by its period id when the
    register's fiscal quarter is not 1 to 4."""
    year = _year(period)
    label = (
        period.period_id if number is None else f"Q{number} {_yy(period.fiscal_year)}"
    )
    return _Spec(
        column=Column(
            column_id=f"Q:{own}" if own is not None else f"Q:{_term_ids(terms)}",
            kind="QUARTER",
            label=label,
            period_id=own,
            fiscal_year=period.fiscal_year,
            end_date=period.end_date,
            days=period.day_count,
            case=None,
        ),
        own=own,
        terms=terms,
        quarter=None if year is None or number is None else (year, number),
    )


def _term_ids(terms: tuple[_Term, ...] | None) -> str:
    return "-".join(str(period_id) for period_id, _ in terms or ())


def _calculated_quarters(regs: Cp1Registers) -> list[_Spec]:
    """Q2 = H1 - Q1, Q3 = 9M - H1 and Q4 = FY - 9M, where the register has
    no such quarter and both periods exist; unbuilt, noted `UNSPANNED`,
    unless the two start together and the remainder is three whole months
    (`_whole_months`)."""
    reported = _by_quarter(_of_type(regs, "QUARTER"))
    ytd = _by_quarter(_of_type(regs, "YTD"))
    fiscal = {_year(p): p for p in _of_type(regs, "FY")}
    specs = []
    for year in dict.fromkeys(_year(p) for p in regs.periods):
        pairs = {
            2: (ytd.get((year, 2)), reported.get((year, 1))),
            3: (ytd.get((year, 3)), ytd.get((year, 2))),
            4: (fiscal.get(year), ytd.get((year, 3))),
        }
        for number, (minuend, subtrahend) in pairs.items():
            if (year, number) in reported or minuend is None or subtrahend is None:
                continue
            terms = ((minuend.period_id, 1), (subtrahend.period_id, -1))
            spec = _quarter_spec(minuend, number, None, terms)
            days = _days(minuend, subtrahend)
            quarter = _remainder_months(_dated(minuend), _dated(subtrahend)) == 3
            specs.append(
                replace(
                    spec,
                    column=replace(spec.column, days=days),
                    unbuilt=None if quarter else UNSPANNED,
                )
            )
    return specs


def _remainder_months(
    whole: tuple[int, int] | None, part: tuple[int, int] | None
) -> int | None:
    """The whole months (`_whole_months`) from the day after `part` ends to
    the day `whole` ends, where the two spans (ordinals) start together;
    else None."""
    if whole is None or part is None or whole[0] != part[0]:
        return None
    months = _whole_months((part[1] + 1, whole[1]))
    return None if months is None else months[1]


def _quarters(regs: Cp1Registers) -> list[_Spec]:
    specs = _calculated_quarters(regs)
    for period in _of_type(regs, "QUARTER"):
        number = _quarter_number(period)
        specs.append(_quarter_spec(period, number, period.period_id, None))
    return sorted(specs, key=lambda spec: spec.column.end_date or "")


def _period_spec(period: PeriodRow, kind: Literal["PYTD", "YTD", "FY"]) -> _Spec:
    """A register period's column; derived when it names its components."""
    number = _ytd_quarter(period)
    if kind == "FY":
        label = f"FY{_yy(period.fiscal_year)}"
    elif number is None:
        label = f"{kind} {period.period_id}"
    else:
        label = f"{kind} {_YTD_LABELS[number]} {_yy(period.fiscal_year)}"
    derived = bool(period.component_period_ids)
    return _Spec(
        column=Column(
            column_id=f"{kind}:{period.period_id}",
            kind=kind,
            label=label,
            period_id=period.period_id,
            fiscal_year=period.fiscal_year,
            end_date=period.end_date,
            days=period.day_count,
            case=None,
        ),
        own=period.period_id,
        terms=((period.period_id, 1),) if derived else None,
        stated=period.period_id,
    )


def _quarter_index(specs: Iterable[_Spec]) -> dict[tuple[int, int], _Spec]:
    """Each (fiscal year, quarter) to its quarter column: one each, as
    `cp1_registers` refuses a second period for one fiscal quarter."""
    return {spec.quarter: spec for spec in specs if spec.quarter is not None}


def _summed(
    kind: Literal["PYTD", "YTD"],
    quarters: dict[tuple[int, int], _Spec],
    known: tuple[int, int],
    periods: Mapping[str | None, PeriodRow],
) -> _Spec | None:
    """The fiscal year's quarters 1 to the quarter `known` as one column;
    None unless every one is a column; unbuilt, noted `UNSPANNED`, unless
    they tile by their dates (`_tiles`)."""
    year, number = known
    specs = []
    for n in range(1, number + 1):
        spec = quarters.get((year, n))
        if spec is None:
            return None
        specs.append(spec)
    last = specs[-1].column
    terms: tuple[_Term, ...] = tuple((spec, 1) for spec in specs)
    return _Spec(
        unbuilt=None if _tiles(specs, periods) else UNSPANNED,
        column=Column(
            column_id=f"{kind}:{last.column_id.removeprefix('Q:')}",
            kind=kind,
            label=f"{kind} {_YTD_LABELS[number]} {_yy(last.fiscal_year)}",
            period_id=None,
            fiscal_year=last.fiscal_year,
            end_date=last.end_date,
            days=_term_days(terms),
            case=None,
        ),
        own=None,
        terms=terms,
    )


def _plus_months(day: date, months: int) -> date | None:
    """`day` moved by `months` calendar months, on the same day of the month
    or that month's last; None beyond the calendar."""
    index = day.year * 12 + day.month - 1 + months
    year, month = divmod(index, 12)
    if not 1 <= year <= date.max.year:
        return None
    return date(year, month + 1, min(day.day, calendar.monthrange(year, month + 1)[1]))


def _whole_months(dated: tuple[int, int] | None) -> tuple[int, int] | None:
    """A span (ordinals) as its first day and its number of whole months:
    the n (at least 1) where the day after its last lies within `SLACK_DAYS`
    days of its first day plus n months (`WEEK_SLACK_DAYS` where its length
    is whole weeks); None where no n does, where two do (months 28 days
    apart, 14 either side), or for no span. Within 14 days, n is the
    calendar months from its first day to the day after, give or take one."""
    if dated is None or not 1 <= dated[0] <= dated[1] < date.max.toordinal():
        return None
    first, following = date.fromordinal(dated[0]), dated[1] + 1
    after = date.fromordinal(following)
    guess = after.year * 12 + after.month - first.year * 12 - first.month
    slack = WEEK_SLACK_DAYS if (following - dated[0]) % 7 == 0 else SLACK_DAYS
    found = [
        months
        for months in (guess - 1, guess, guess + 1)
        if months >= 1
        and (moved := _plus_months(first, months)) is not None
        and abs(moved.toordinal() - following) <= slack
    ]
    return (dated[0], found[0]) if len(found) == 1 else None


def _year_before(prior: tuple[int, int] | None, months: tuple[int, int] | None) -> bool:
    """Whether `prior` (first day, whole months: `_whole_months`) is as many
    months as `months`, starting within `SLACK_DAYS` days of twelve months
    before it."""
    if prior is None or months is None or prior[1] != months[1]:
        return False
    shifted = _plus_months(date.fromordinal(months[0]), -12)
    return shifted is not None and abs(shifted.toordinal() - prior[0]) <= SLACK_DAYS


def _spec_dated(
    spec: _Spec, periods: Mapping[str | None, PeriodRow]
) -> tuple[int, int] | None:
    """A column's first day (`_start`) and end date as ordinals; None where
    either is unknown."""
    first, end = _start(spec, periods), iso_date(spec.column.end_date)
    if first is None or end is None:
        return None
    return first, end.toordinal()


def _spec_months(
    spec: _Spec, periods: Mapping[str | None, PeriodRow]
) -> tuple[int, int] | None:
    """A column's first day and whole months (`_whole_months`); None where
    they are not whole months."""
    return _whole_months(_spec_dated(spec, periods))


def _tiles(specs: Iterable[_Spec], periods: Mapping[str | None, PeriodRow]) -> bool:
    """Whether the quarter columns, in time order, each span three whole
    months (`_whole_months`), each starting the day after the one before
    ends."""
    return _tiled(specs, periods) is not None


def _tiled(
    specs: Iterable[_Spec], periods: Mapping[str | None, PeriodRow]
) -> tuple[int, int] | None:
    """The first day of the first quarter column and the last of the last
    (ordinals) where, in time order, each spans three whole months
    (`_whole_months`), each starting the day after the one before ends;
    None where they do not, or for none."""
    span: tuple[int, int] | None = None
    for spec in specs:
        dated = _spec_dated(spec, periods)
        months = _whole_months(dated)
        if dated is None or months is None or months[1] != 3:
            return None
        if span is not None and span[1] + 1 != dated[0]:
            return None
        span = (dated[0] if span is None else span[0], dated[1])
    return span


def _twelve_months(
    specs: Iterable[_Spec], periods: Mapping[str | None, PeriodRow]
) -> bool:
    """Whether the quarter columns tile (`_tiled`) and, as one span from the
    first's start to the last's end, are twelve whole months
    (`_whole_months`, under the same slack): each quarter's slack never adds
    up past the window's."""
    months = _whole_months(_tiled(specs, periods))
    return months is not None and months[1] == 12


def _dated_prior(regs: Cp1Registers, ytd: _Spec | None) -> tuple[_Spec | None, bool]:
    """The PYTD of `ytd` by dates: the one other YTD period of the same whole
    months starting a year before it (`_year_before`). Else None, and whether the dates
    leave it ambiguous: a YTD period ends before `ytd` starts, or has no
    dates, while none or several are that one."""
    if ytd is None:
        return None, False
    periods: dict[str | None, PeriodRow] = {p.period_id: p for p in regs.periods}
    first = _start(ytd, periods)
    months = _spec_months(ytd, periods)
    before = [
        p
        for p in _of_type(regs, "YTD")
        if p.period_id != ytd.own
        and ((dated := _dated(p)) is None or first is None or dated[1] < first)
    ]
    found = [p for p in before if _year_before(_whole_months(_dated(p)), months)]
    if len(found) == 1 and None not in map(_dated, before):
        return _period_spec(found[0], "PYTD"), False
    return None, bool(before)


def _to_date(
    regs: Cp1Registers,
    quarters: dict[tuple[int, int], _Spec],
    anchor: PeriodRow | None,
) -> tuple[_Spec | None, _Spec | None, bool]:
    """(PYTD, YTD) to the anchor, neither at a fiscal-year end; and whether
    no PYTD was found because the dates leave it ambiguous."""
    if anchor is None or anchor.period_type == "FY":
        return None, None, False
    row = next(
        (p for p in _of_type(regs, "YTD") if p.end_date == anchor.end_date), None
    )
    year, number = _year(anchor), _ytd_quarter(row or anchor)
    known = None if year is None or number is None else (year, number)
    if row is not None:
        ytd: _Spec | None = _period_spec(row, "YTD")
    else:
        periods: dict[str | None, PeriodRow] = {p.period_id: p for p in regs.periods}
        ytd = None if known is None else _summed("YTD", quarters, known, periods)
    pytd, ambiguous = _prior_to_date(regs, quarters, ytd, known)
    return pytd, ytd, ambiguous


def _labelled_prior(regs: Cp1Registers, known: tuple[int, int] | None) -> _Spec | None:
    """The PYTD column of the prior fiscal year's YTD period of the quarter
    `known` (the anchor's fiscal year and quarter); None without one."""
    if known is None:
        return None
    year, number = known
    labelled = next(
        (
            p
            for p in _of_type(regs, "YTD")
            if _year(p) == year - 1 and _quarter_number(p) == number
        ),
        None,
    )
    return None if labelled is None else _period_spec(labelled, "PYTD")


def _prior_to_date(
    regs: Cp1Registers,
    quarters: dict[tuple[int, int], _Spec],
    ytd: _Spec | None,
    known: tuple[int, int] | None,
) -> tuple[_Spec | None, bool]:
    """The PYTD of `ytd`, the anchor's fiscal year and quarter `known`: the
    prior year's YTD period of that quarter; else the one by its dates
    (`_dated_prior`); else the prior year's quarters to that one. A labelled
    period or quarters to date count only with `ytd`'s whole months, a year
    earlier (`_year_before`; without `ytd` there is nothing to match). And whether
    none was found because the dates leave it ambiguous or a candidate's
    months differ."""
    periods: dict[str | None, PeriodRow] = {p.period_id: p for p in regs.periods}
    months = None if ytd is None else _spec_months(ytd, periods)
    dated, ambiguous = _dated_prior(regs, ytd)
    candidates = [_labelled_prior(regs, known), dated]
    if known is not None:
        candidates.append(_summed("PYTD", quarters, (known[0] - 1, known[1]), periods))
    found = [c for c in candidates if c is not None]
    for spec in found:
        if ytd is None or _year_before(_spec_months(spec, periods), months):
            return spec, False
    return None, ambiguous or bool(found)


def _ltm_label(period: PeriodRow, number: int | None) -> str:
    if number is None:
        return f"LTM {period.period_id}"
    return f"LTM Q{number} {_yy(period.fiscal_year)}"


def _term_days(terms: tuple[_Term, ...]) -> int | None:
    """The terms' columns' day counts added and subtracted; None when one is
    unknown."""
    days = 0
    for spec, sign in terms:
        count = spec.column.days if isinstance(spec, _Spec) else None
        if count is None:
            return None
        days += sign * count
    return days


def _first_day(period: PeriodRow) -> date | None:
    """The period's start date; without one, its end less its day count
    (end - days + 1); None where neither is known or the day count is not
    positive."""
    start = iso_date(period.start_date)
    end = iso_date(period.end_date)
    if start is not None or end is None or period.day_count is None:
        return start
    first = end.toordinal() - period.day_count + 1
    return date.fromordinal(first) if 1 <= first <= end.toordinal() else None


def _dated(period: PeriodRow | None) -> tuple[int, int] | None:
    """The period's first and last day as ordinals (the first derived from
    the day count where no start is stated); None without both or with the
    end before the start."""
    if period is None:
        return None
    start, end = _first_day(period), iso_date(period.end_date)
    if start is None or end is None or end < start:
        return None
    return start.toordinal(), end.toordinal()


def _start(spec: _Spec, periods: Mapping[str | None, PeriodRow]) -> int | None:
    """A column's first day as an ordinal: its own period's start; else its
    end date less its days; else, for quarters to date, the first quarter's
    start; None when none is known. (The FY, YTD and PYTD are never a
    calculated quarter.)"""
    own = _dated(periods.get(spec.own))
    if own is not None:
        return own[0]
    end = iso_date(spec.column.end_date)
    if end is not None and spec.column.days is not None:
        return end.toordinal() - spec.column.days + 1
    first = (spec.terms or _UNBUILT)[0][0]
    return _start(first, periods) if isinstance(first, _Spec) else None


def _meets(regs: Cp1Registers, fy: _Spec, ytd: _Spec, pytd: _Spec) -> bool:
    """Whether the FY ends the day before the YTD starts, the PYTD starts
    with the FY, and the YTD and PYTD are as long within `SLACK_DAYS`
    (`_alike`): FY + YTD - PYTD is then the twelve months to the YTD's
    end."""
    periods: dict[str | None, PeriodRow] = {p.period_id: p for p in regs.periods}
    starts = [_start(s, periods) for s in (fy, ytd, pytd)]
    year_end = iso_date(fy.column.end_date)
    if year_end is None or None in starts:
        return False
    year, current, prior = starts
    met = year_end.toordinal() + 1 == current and prior == year
    return met and _alike(_spec_dated(ytd, periods), _spec_dated(pytd, periods))


def _alike(current: tuple[int, int] | None, prior: tuple[int, int] | None) -> bool:
    """Whether two spans (ordinals: first day, last day) have day counts
    within `SLACK_DAYS` of each other: a YTD and a PYTD each within its
    slack of the same whole months may still differ by twice it."""
    if current is None or prior is None:
        return False
    return abs((current[1] - current[0]) - (prior[1] - prior[0])) <= SLACK_DAYS


def _rolled(
    regs: Cp1Registers,
    anchor: PeriodRow,
    fiscal: list[_Spec],
    to_date: tuple[_Spec | None, _Spec | None],
) -> tuple[tuple[_Term, ...], str | None]:
    """FY + YTD - PYTD with the FY of the year before the anchor's, and
    `UNSPANNED` where the three do not meet (else None)."""
    pytd, ytd = to_date
    year = _year(anchor)
    prior = None if year is None else year - 1
    fy = next(
        (s for s in fiscal if fiscal_year_number(s.column.fiscal_year) == prior),
        None,
    )
    met = not (fy and ytd and pytd) or _meets(regs, fy, ytd, pytd)
    return ((fy, 1), (ytd, 1), (pytd, -1)), None if met else UNSPANNED


def _fiscal_year_note(period: PeriodRow) -> str | None:
    """Why the fiscal year is not twelve whole months, else None: `UNSPANNED`
    where its span cannot be dated, "short fiscal year (id)" where the day
    after it ends comes before its first day plus twelve months (or that
    day is beyond the calendar), and "long fiscal year (id)" where it is
    not twelve whole months otherwise."""
    dated = _dated(period)
    if dated is None or not 1 <= dated[0] <= dated[1] < date.max.toordinal():
        return UNSPANNED
    months = _whole_months(dated)
    if months is not None and months[1] == 12:
        return None
    twelve = _plus_months(date.fromordinal(dated[0]), 12)
    short = twelve is None or dated[1] + 1 < twelve.toordinal()
    return odd_year(period.period_id, short)


def _host_ltm(
    regs: Cp1Registers,
    anchor: PeriodRow,
    fiscal: list[_Spec],
    to_date: tuple[_Spec | None, _Spec | None],
) -> _Spec:
    """The LTM to the anchor: the FY ending then, if it is twelve whole
    months, or FY + YTD - PYTD with the prior year's FY; named by CP-1's LTM
    row ending at the anchor. Unbuilt, noted, where that FY is short, long or
    undated (`_fiscal_year_note`), or that FY, YTD and PYTD do not meet."""
    unbuilt = None
    if anchor.period_type == "FY":
        own_fy = next(spec for spec in fiscal if spec.own == anchor.period_id)
        terms: tuple[_Term, ...] = ((own_fy, 1),)
        unbuilt = _fiscal_year_note(anchor)
        number: int | None = 4
    else:
        terms, unbuilt = _rolled(regs, anchor, fiscal, to_date)
        number = _ytd_quarter(anchor)
    stated = next(
        (p for p in _of_type(regs, "LTM") if p.end_date == anchor.end_date), None
    )
    own = stated.period_id if stated is not None else None
    days = stated.day_count if stated is not None else None
    return _Spec(
        column=Column(
            column_id=f"LTM:{own or anchor.period_id}",
            kind="LTM",
            label=_ltm_label(anchor, number),
            period_id=own,
            fiscal_year=anchor.fiscal_year,
            end_date=anchor.end_date,
            days=_term_days(terms) if days is None else days,
            case=None,
        ),
        own=own,
        terms=terms,
        stated=own,
        unbuilt=unbuilt,
    )


def _unadopted_ltm(period: PeriodRow) -> _Spec:
    """CP-1's LTM ending after anything the host can build: its column, with
    no components, so CP-1's figure is only ever `stated`."""
    return _Spec(
        column=Column(
            column_id=f"LTM:{period.period_id}",
            kind="LTM",
            label=_ltm_label(period, _quarter_number(period)),
            period_id=period.period_id,
            fiscal_year=period.fiscal_year,
            end_date=period.end_date,
            days=period.day_count,
            case=None,
        ),
        own=period.period_id,
        terms=_UNBUILT,
        stated=period.period_id,
    )


def _plan(regs: Cp1Registers) -> tuple[_Spec, ...]:
    quarters = _quarters(regs)
    anchor = anchor_period(regs)
    pytd, ytd, ambiguous = _to_date(regs, _quarter_index(quarters), anchor)
    fiscal = [_period_spec(p, "FY") for p in _by_end(_of_type(regs, "FY"))]
    specs = [*quarters, *(s for s in (pytd, ytd) if s is not None), *fiscal]
    if anchor is not None:
        ltm = _host_ltm(regs, anchor, fiscal, (pytd, ytd))
        specs.append(replace(ltm, unbuilt=UNSPANNED) if ambiguous else ltm)
    end = anchor.end_date if anchor is not None else None
    specs.extend(
        _unadopted_ltm(p)
        for p in _by_end(_of_type(regs, "LTM"))
        if end is None or p.end_date is None or p.end_date > end
    )
    return tuple(specs)


def historical_columns(regs: Cp1Registers) -> tuple[Column, ...]:
    """The historical columns in the spec's order: quarters by end date, PYTD,
    YTD, the fiscal years by end date, LTM."""
    return tuple(spec.column for spec in _plan(regs))


_KPI_KINDS: dict[str, _Kind] = {"PERIOD_FLOW": "flow", "PERIOD_END": "balance"}
_Entry = tuple[str, _Kind, str, Cell]


_SPARSE_ACCOUNTS = frozenset(
    {"lease_payments_in_financing", "interest_paid_in_financing"}
)


def _account_kind(metric_id: str) -> _Kind:
    if metric_id in _SPARSE_ACCOUNTS:
        return "sparse"
    if metric_id in FLOW_METRICS:
        return "flow"
    return "balance" if metric_id in BALANCE_METRICS else "exact"


def _row(
    value: Decimal | None, source: SourceRef | None, outflow: bool = False
) -> Cell:
    """A register row's cell: `NOT_STATED` without a figure; a negative zero
    is zero; an outflow written positive is read negative (exactly: no
    context rounds it) and noted."""
    if value is None:
        return _UNSTATED
    value = no_negative_zero(value)
    cell = Cell(value, basis="REPORTED", sources=refs([source]))
    if outflow and value > 0:
        return replace(cell, value=value.copy_negate(), note=SIGN_NORMALISED)
    return cell


def _entries(regs: Cp1Registers) -> Iterator[_Entry]:
    """(key, kind, period id, cell) for every register row."""
    for a in regs.accounts:
        kind = _account_kind(a.metric_id)
        cell = _row(a.value, a.source, a.metric_id in OUTFLOW_METRICS)
        yield f"acct:{a.metric_id}", kind, a.period_id, cell
    for s in regs.segments:
        yield f"bu:{s.segment_id}", "flow", s.period_id, _row(s.revenue, s.source)
    for b in regs.addbacks:
        yield f"addback:{b.addback_id}", "sparse", b.period_id, _row(b.value, b.source)
    for k in regs.kpis:
        kind = _KPI_KINDS.get(k.value_type, "exact")
        yield f"kpi:{k.kpi_id}", kind, k.period_id, _row(k.value, k.source)
    for f in regs.facilities:
        cell = _row(f.carrying_value, f.source)
        yield f"fac:{f.facility_id}", "balance", f.period_id, cell


def _series(regs: Cp1Registers) -> dict[str, _Series]:
    """Every frame key's rows by period (one each: `cp1_registers` refuses a
    second), read by the kind of the key's first row."""
    series: dict[str, _Series] = {}
    for key, kind, period_id, cell in _entries(regs):
        one_off = key.startswith("addback:")
        series.setdefault(key, _Series(kind, {}, one_off=one_off)).rows[period_id] = (
            cell
        )
    return series


def _register(regs: Cp1Registers) -> _Register:
    periods: dict[str | None, PeriodRow] = {}
    ending: dict[str | None, tuple[str, ...]] = {}
    starting: dict[str, tuple[PeriodRow, ...]] = {}
    for period in regs.periods:
        first = _first_day(period)
        if period.period_type in _COVERING and first and period.end_date:
            starting[first.isoformat()] = (
                *starting.get(first.isoformat(), ()),
                period,
            )
        periods[period.period_id] = period
        if period.end_date is not None:
            ending[period.end_date] = (
                *ending.get(period.end_date, ()),
                period.period_id,
            )
    spans = [
        (*span, p.period_id) for p in regs.periods if (span := _dated(p)) is not None
    ]
    shortest = tuple(sorted(spans, key=lambda found: found[1] - found[0]))
    footings: dict[str | None, Footing] = {
        p.period_id: footing_of(p) for p in regs.periods
    }
    return _Register(periods, ending, starting, shortest, off_footing(regs), footings)


_MISSING = Cell(None, "COMPONENT_MISSING")  # a part not stated, or no period
_FROM_PARTS = "differs from components"
# Twelve months whose parts (FY, YTD and PYTD; or four quarters) are stated
# on some but not all: a sum of them would span more or fewer months.
PARTLY_STATED = "twelve months not all stated"
# The periods a sparse item's cover is chosen from.
_COVERING = frozenset({"QUARTER", "YTD", "FY", "LTM"})
_UNSTATED = Cell(None, "NOT_STATED")  # a row without a figure


def _reported(series: _Series, period_id: str | None) -> Cell:
    """The period's row: `NOT_SOURCED` when there is none, `NOT_STATED`
    when it has no figure."""
    return series.rows.get(period_id, ABSENT)


def _sum(series: _Series, parts: Iterable[tuple[Cell, int]]) -> Cell:
    """The parts added (+1) or subtracted (-1), noted `SIGN_NORMALISED`
    where one is. A part not stated, or missing, is `COMPONENT_MISSING` (with
    that part's note); every part absent is `NOT_SOURCED`; some absent is
    `COMPONENT_MISSING`, except in a sparse series, where an absent part is
    nothing."""
    cells = list(parts)
    if not cells:
        return ABSENT
    missing = [cell for cell, _ in cells if cell.value is None]
    unstated = next((c for c in missing if c.reason != "NOT_SOURCED"), None)
    if unstated is not None:
        return Cell(None, "COMPONENT_MISSING", note=unstated.note)
    if missing and (len(missing) == len(cells) or series.kind != "sparse"):
        return ABSENT if len(missing) == len(cells) else _MISSING
    return calc((cell, sign) for cell, sign in cells if cell.value is not None)


def _named_sum(series: _Series, parts: Iterable[tuple[str, Cell, int]]) -> Cell:
    """`_sum` of the named parts; with a figure, noted with each part it took
    as nothing (`treated_as_zero`: in a sparse series, a part without a
    row)."""
    named = list(parts)
    total = _sum(series, ((cell, sign) for _, cell, sign in named))
    nothing = [name for name, cell, _ in named if cell.reason == "NOT_SOURCED"]
    if total.value is None or not nothing:
        return total
    notes = (total.note, *map(treated_as_zero, nothing))
    return replace(total, note=join_notes(notes))


def _spans(register: _Register, period: PeriodRow) -> bool:
    """Whether the period's components are distinct periods, each starting
    the day after the one before ends, from its start date to its end
    date."""
    ids = period.component_period_ids
    whole = _dated(period)
    parts = [_dated(register.periods.get(part)) for part in ids]
    if whole is None or None in parts or len(set(ids)) != len(ids):
        return False
    following = whole[0]
    for start, end in sorted(part for part in parts if part is not None):
        if start != following:
            return False
        following = end + 1
    return following == whole[1] + 1


_UNSPANNED_PARTS = Cell(None, "COMPONENT_MISSING", note=UNSPANNED)
_OFF = Cell(None, "COMPONENT_MISSING", note=OTHER_FOOTING)


def _component(series: _Series, register: _Register, period_id: str | None) -> Cell:
    """A term's cell: the sum of a YTD or FY period's components where it
    names them (`COMPONENT_MISSING`, noted, where they do not span it), else
    the period's own; `COMPONENT_MISSING` for no period."""
    period = register.periods.get(period_id)
    if period is None:
        return _MISSING
    if period_id in register.off:
        return _OFF
    if series.kind == "sparse":
        return _resolved(series, register, period.period_id)
    parts: tuple[str, ...] = (period.period_id,)
    if period.period_type in _ADDITIVE and period.component_period_ids:
        if not _spans(register, period):
            return _UNSPANNED_PARTS
        parts = period.component_period_ids
        if not register.off.isdisjoint(parts):
            return _OFF
    return _sum(series, ((_reported(series, part), 1) for part in parts))


def _footing(
    footed: Mapping[str | None, Footing], register: _Register, ref: str | _Spec | None
) -> Footing | None:
    """The footing (`combined_footing`) of a term's figure: a column's, of
    its own period's and its terms'; a sparse period's as worked out
    (`footed`: `_Series.footed`) where it has a figure; else a period's own
    and its named components'; not stated for no period. None where two
    differ. (A derived period's figure is only ever summed under its
    column's, so `_flow` refuses one whose components differ.)"""
    if isinstance(ref, _Spec):
        parts = (ref.own, *(term for term, _ in ref.terms or ()))
        return combined_footing(_footing(footed, register, part) for part in parts)
    if ref in footed:
        return footed[ref]
    period = register.periods.get(ref)
    if period is None:
        return UNSTATED_FOOTING
    ids = (period.period_id, *period.component_period_ids)
    return combined_footing(register.footings.get(i, UNSTATED_FOOTING) for i in ids)


def _resolved(series: _Series, register: _Register, period_id: str | None) -> Cell:
    """A sparse item's cell for a period: its own row, noted where parts that
    tile it differ beyond its rounding; else its parts' where they tile it
    (`NOT_SOURCED` when none has a row), and `COMPONENT_MISSING`, noted
    `UNSPANNED`, where they leave a gap but one has a figure. Worked out once
    per period."""
    known = series.resolved.get(period_id)
    if known is not None:
        return known
    own = _reported(series, period_id)
    period = register.periods.get(period_id)
    if period is None or period_id in series.started:
        return own
    series.started.add(period_id)
    _resolve_within(series, register, period)
    parts, tiled, footing = _parts(series, register, period)
    if own.value is not None:
        differs = (
            tiled
            and parts.value is not None
            and beyond_rounding(own.value, parts.value)
        )
        cell = replace(
            own, note=join_notes((own.note, _FROM_PARTS if differs else None))
        )
        series.footed[period_id] = register.footings[period_id]
    elif own.reason != "NOT_SOURCED":
        cell = own
    elif period_id in register.off:
        cell = _OFF  # never its parts' figure, on the anchor's footing
    elif tiled or parts.value is None:
        cell = parts
        series.footed[period_id] = footing
    else:
        cell = _UNSPANNED_PARTS  # a partial sum is never the period's figure
    series.resolved[period_id] = cell
    return cell


def _resolve_within(series: _Series, register: _Register, period: PeriodRow) -> None:
    """Works out every period within `period`'s dates and shorter, shortest
    first, before `period` itself: every cover part and spanning component
    is one, so each is then already resolved and the walk never nests deeper
    than a chain of equal spans (`MAX_NESTING`), however many periods cover
    one another."""
    whole = _dated(period)
    if whole is None:
        return
    for first, last, inner in register.shortest:
        if last - first >= whole[1] - whole[0]:
            return
        if whole[0] <= first and last <= whole[1] and inner not in series.resolved:
            _resolved(series, register, inner)


def _parts(
    series: _Series, register: _Register, period: PeriodRow
) -> tuple[Cell, bool, Footing]:
    """A sparse item's figure for a period from its parts, whether they
    tile it, and the footing of the period and every part with a figure
    (`combined_footing`): its components where it names them
    (`COMPONENT_MISSING`, noted, where they do not span it), else its cover;
    `COMPONENT_MISSING`, noted `OTHER_FOOTING`, where two footings differ."""
    if period.component_period_ids:
        if not _spans(register, period):
            return _UNSPANNED_PARTS, False, UNSTATED_FOOTING
        if not register.off.isdisjoint(period.component_period_ids):
            return _OFF, False, UNSTATED_FOOTING
        cells = [
            (part, _resolved(series, register, part))
            for part in period.component_period_ids
        ]
        tiled = True
    else:
        cells, tiled = _cover(series, register, period)
    footing = combined_footing(
        (
            register.footings[period.period_id],
            *(
                _footing(series.footed, register, n)
                for n, c in cells
                if c.value is not None
            ),
        )
    )
    if footing is None:
        return _OFF, False, UNSTATED_FOOTING
    total = _named_sum(series, ((name, cell, 1) for name, cell in cells))
    return total, tiled, footing


def _cover(
    series: _Series, register: _Register, period: PeriodRow
) -> tuple[list[tuple[str, Cell]], bool]:
    """The period's parts (named, those taken as nothing `NOT_SOURCED`) from
    its start date, one `_step` at a time from the day after the last part
    ends, and whether they tile it to its end date:
    a day on which no part starts is a gap, and the cover goes on from the
    next day a period starts (so a part with a figure past a gap is still
    seen)."""
    whole = _dated(period)
    if whole is None:
        return [], False
    cells: list[tuple[str, Cell]] = []
    tiled = True
    day = whole[0]
    while day <= whole[1]:
        step = _step(series, register, (period, (day, whole[1])))
        if step is None:
            tiled = False
            day = _next_start(register, day, whole[1] + 1)
            continue
        last, name, cell = step
        cells.append((name, cell))
        day = last + 1
    return cells, tiled


def _next_start(register: _Register, day: int, beyond: int) -> int:
    """The first day after `day` (ordinals) on which a period starts; else
    `beyond`."""
    after = date.fromordinal(day).isoformat()
    later = (start for start in sorted(register.starting) if start > after)
    following = next(later, None)
    return beyond if following is None else date.fromisoformat(following).toordinal()


def _part(
    series: _Series, register: _Register, period: PeriodRow, part: PeriodRow
) -> Cell:
    """A cover part's cell: resolved, except a part with the period's own
    dates, which gives its own row only (so neither resolves the other)."""
    if _dated(part) == _dated(period):
        return _reported(series, part.period_id)
    return _resolved(series, register, part.period_id)


def _step(
    series: _Series, register: _Register, at: tuple[PeriodRow, tuple[int, int]]
) -> tuple[int, str, Cell] | None:
    """The cover part starting on `at`'s day (ordinal), as its last day, its
    id and its cell: the longest other period starting then and ending by
    `at`'s last day that has a figure; else the shortest without a row, which
    is nothing (`NOT_SOURCED`); else one whose components do not span it,
    which leaves its days without a figure; None where no period starts then
    (a gap). A part with the period's own dates and no row is never
    nothing."""
    period, (day, end) = at
    fitting = sorted(
        (
            (span[1], part)
            for part in register.starting.get(date.fromordinal(day).isoformat(), ())
            if part.period_id != period.period_id
            and part.period_id not in register.off
            and (span := _dated(part)) is not None
            and span[1] <= end
        ),
        key=lambda found: found[0],
        reverse=True,
    )
    nothing: tuple[int, str, Cell] | None = None
    unspanned: tuple[int, str, Cell] | None = None
    for last, part in fitting:
        cell = _part(series, register, period, part)
        if cell == _UNSPANNED_PARTS:
            unspanned = unspanned or (last, part.period_id, cell)
        elif cell.reason != "NOT_SOURCED":
            return last, part.period_id, cell
        elif _dated(part) != _dated(period):
            nothing = (last, part.period_id, ABSENT)
    return nothing or unspanned


def _term(series: _Series, register: _Register, ref: str | _Spec | None) -> Cell:
    """A term's cell: a column's, or a register period's; `COMPONENT_MISSING`,
    noted `OTHER_FOOTING`, for a column whose own period is on another
    footing."""
    if isinstance(ref, _Spec):
        if ref.own is not None and ref.own in register.off:
            return _OFF
        return _flow(series, register, ref)
    return _component(series, register, ref)


def _term_name(ref: str | _Spec | None) -> str:
    """A term's name in a note: its period's id, else its column's."""
    if isinstance(ref, _Spec):
        return ref.own or ref.column.column_id
    return str(ref)


def _partly_stated(spec: _Spec, cells: list[tuple[Cell, int]]) -> bool:
    """Whether an LTM built as FY + YTD - PYTD has some of the three stated
    and another without a row (`NOT_SOURCED`), except both interims without
    one (the LTM is then the FY's). A part missing otherwise is `_sum`'s."""
    if spec.column.kind != "LTM" or len(cells) != 3:
        return False
    found = [cell.value is not None for cell, _ in cells]
    absent = [cell.reason == "NOT_SOURCED" for cell, _ in cells]
    if not any(found) or not all(map(operator.or_, found, absent)):
        return False
    return any(absent) and not (absent[1] and absent[2])


def _flow(series: _Series, register: _Register, spec: _Spec) -> Cell:
    if spec.terms is None:
        if series.kind == "sparse":
            return _resolved(series, register, spec.own)
        return _reported(series, spec.own)
    stated = _reported(series, spec.stated).value
    if spec.unbuilt is not None:
        return Cell(None, "COMPONENT_MISSING", stated=stated, note=spec.unbuilt)
    terms = [(_term(series, register, ref), sign) for ref, sign in spec.terms]
    if _footing(series.footed, register, spec) is None:
        return Cell(None, "COMPONENT_MISSING", stated=stated, note=OTHER_FOOTING)
    recurring = series.kind == "sparse" and not series.one_off
    if recurring and _partly_stated(spec, terms):
        return Cell(None, "COMPONENT_MISSING", stated=stated, note=PARTLY_STATED)
    names = (_term_name(ref) for ref, _ in spec.terms)
    total = _named_sum(
        series,
        ((name, cell, sign) for name, (cell, sign) in zip(names, terms, strict=True)),
    )
    if total.value is None:
        return Cell(None, total.reason, stated=stated, note=total.note)
    differs = stated is not None and beyond_rounding(stated, total.value)
    note = join_notes((total.note, DIFFERS if differs else None))
    return replace(total, stated=stated, note=note)


def _stated_footing(register: _Register, period_id: str | None) -> str:
    """The period's id with its basis and perimeter as written, `not stated`
    for one it does not state."""
    period = register.periods.get(period_id)
    basis = period.accounting_basis if period else None
    perimeter = period.entity_perimeter if period else None
    return f"{period_id} ({basis or 'not stated'}, {perimeter or 'not stated'})"


def _apart(register: _Register, own: str | None, other: str) -> bool:
    """Whether the two periods state a different basis or perimeter (not
    stated matches anything)."""
    first = register.footings.get(own, UNSTATED_FOOTING)
    second = register.footings.get(other, UNSTATED_FOOTING)
    return combined_footing((first, second)) is None


def _balance(series: _Series, register: _Register, spec: _Spec) -> Cell:
    """The first observation at the column's end date: its own period's, then
    any period's ending that day, in register order; none on another footing
    than the anchor's, and only its own where it is. A period ending that day
    on a footing that differs from the column's own period's (both stated)
    is not read: where it alone has the figure, the cell is
    `COMPONENT_MISSING`, its note naming both footings (R7, N206)."""
    ending = register.ending.get(spec.column.end_date, ())
    if spec.own in register.off:
        ending = ()
    on = (period_id for period_id in ending if period_id not in register.off)
    ids = (spec.own, *on)
    cells = [_reported(series, period_id) for period_id in ids]
    refused: Cell | None = None
    for period_id, cell in zip(ids, cells, strict=True):
        if cell.value is None:
            continue
        if period_id != spec.own and _apart(register, spec.own, str(period_id)):
            refused = refused or Cell(
                None,
                "COMPONENT_MISSING",
                note=(
                    f"{OTHER_FOOTING}: {_stated_footing(register, spec.own)} and "
                    f"{_stated_footing(register, period_id)}"
                ),
            )
            continue
        return cell
    if refused is not None:
        return refused
    return _UNSTATED if _UNSTATED in cells else ABSENT


def _exact(series: _Series, register: _Register, spec: _Spec) -> Cell:
    """A rate: only a row for exactly the column's own period."""
    return _reported(series, spec.own)


_READERS = {"flow": _flow, "sparse": _flow, "balance": _balance, "exact": _exact}


def account_frame(regs: Cp1Registers, columns: tuple[Column, ...]) -> Frame:
    """CP-1's figures over `columns` (from `historical_columns`): each column
    to `acct:<metric_id>`, `bu:<segment_id>`, `addback:<addback_id>`,
    `kpi:<kpi_id>` and `fac:<facility_id>` cells."""
    with localcontext(CONTEXT):
        specs = {spec.column.column_id: spec for spec in _plan(regs)}
        series = _series(regs)
        register = _register(regs)
        return {
            column.column_id: {
                key: _READERS[one.kind](one, register, specs[column.column_id])
                for key, one in series.items()
            }
            for column in columns
        }


def _earlier(spec: _Spec, quarters: dict[tuple[int, int], _Spec]) -> list[_Spec | None]:
    """The three quarters before `spec`'s; None where one is not a column."""
    if spec.quarter is None:
        return [None, None, None]
    year, number = spec.quarter
    earlier: list[_Spec | None] = []
    for back in (1, 2, 3):
        prior_year, prior = divmod(year * 4 + number - 1 - back, 4)
        earlier.append(quarters.get((prior_year, prior + 1)))
    return earlier


@dataclass(frozen=True, slots=True)
class _Window:
    """The twelve months ending a quarter column: the column, the three
    quarters before it (None where one is not a column), whether the four
    tile and span twelve whole months (`_twelve_months`), and the FY period
    of exactly those months."""

    spec: _Spec
    earlier: list[_Spec | None]
    tiled: bool
    year: str | None


def _fiscal_year_of(spec: _Spec, register: _Register) -> str | None:
    """The FY period of twelve whole months (`_whole_months`) ending the day
    the quarter column ends (a fiscal Q4's); None without one."""
    end = iso_date(spec.column.end_date)
    return next(
        (
            p.period_id
            for p in register.periods.values()
            if p.period_type == "FY"
            and (dated := _dated(p)) is not None
            and end is not None
            and dated[1] == end.toordinal()
            and (months := _whole_months(dated)) is not None
            and months[1] == 12
        ),
        None,
    )


def _ltm_cell(series: _Series, register: _Register, window: _Window) -> Cell:
    """A flow over the quarter and the three before it is their sum,
    `UNSPANNED` where they do not tile, `OTHER_FOOTING` where two of their
    footings differ (`combined_footing`); a balance is the quarter's; a rate
    has no observation for twelve months. A sparse item over a fiscal year's
    twelve months is that FY's, as its column reads it; over others it is
    `COMPONENT_MISSING`, noted `PARTLY_STATED`, where some quarters have a
    figure and others no row, except an add-back's, whose quarter without a
    row is nothing, named (`_named_sum`)."""
    if series.kind == "balance":
        return _balance(series, register, window.spec)
    if series.kind == "exact":
        return Cell(None, "NOT_SOURCED")
    if series.kind == "sparse" and window.year is not None:
        return _component(series, register, window.year)
    if not window.tiled:
        return _UNSPANNED_PARTS
    four = (window.spec, *window.earlier)
    quarters = [
        (_MISSING if quarter is None else _term(series, register, quarter), 1)
        for quarter in four
    ]
    if combined_footing(_footing(series.footed, register, q) for q in four) is None:
        return _OFF
    recurring = series.kind == "sparse" and not series.one_off
    if recurring and _some_unstated(quarters):
        return Cell(None, "COMPONENT_MISSING", note=PARTLY_STATED)
    names = (_term_name(quarter) for quarter in four)
    return _named_sum(
        series,
        (
            (name, cell, sign)
            for name, (cell, sign) in zip(names, quarters, strict=True)
        ),
    )


def _some_unstated(cells: list[tuple[Cell, int]]) -> bool:
    """Whether some cells have a figure and others no row (`NOT_SOURCED`)."""
    found = any(cell.value is not None for cell, _ in cells)
    return found and any(cell.reason == "NOT_SOURCED" for cell, _ in cells)


def column_footings(regs: Cp1Registers, columns: tuple[Column, ...]) -> Footings:
    """The footings growth compares (`_cells.Footings`): the anchor's; each
    of `columns` (from `historical_columns`), of its own period and the
    periods its terms are built on, with their named components; and the
    twelve months ending each quarter column, of its four quarters'. None
    where two state a basis, or a perimeter, differently."""
    plan = {spec.column.column_id: spec for spec in _plan(regs)}
    quarters = _quarter_index(plan.values())
    register = _register(regs)
    specs = [plan[column.column_id] for column in columns]
    anchor = anchor_period(regs)
    return Footings(
        anchor=UNSTATED_FOOTING if anchor is None else footing_of(anchor),
        columns={spec.column.column_id: _footing({}, register, spec) for spec in specs},
        windows={
            spec.column.column_id: combined_footing(
                _footing({}, register, quarter)
                for quarter in (spec, *_earlier(spec, quarters))
            )
            for spec in specs
            if spec.column.kind == "QUARTER"
        },
    )


def ltm_frames(
    regs: Cp1Registers, columns: tuple[Column, ...]
) -> dict[str, dict[str, Cell]]:
    """For each quarter column in `columns`, the cells of the twelve months
    ending with it: flows summed over it and the three quarters before it,
    `COMPONENT_MISSING` without all four (an add-back's absent quarter adds
    nothing only where none of the four has a figure: `_ltm_cell`), and noted
    `UNSPANNED` where the four do not tile, each three whole months starting
    the day after the one before ends, or their span, from the first's
    start to the last's end, is not twelve whole months (`_twelve_months`)."""
    with localcontext(CONTEXT):
        plan = {spec.column.column_id: spec for spec in _plan(regs)}
        quarters = _quarter_index(plan.values())
        series = _series(regs)
        register = _register(regs)
        frames: dict[str, dict[str, Cell]] = {}
        periods = register.periods
        for spec in (plan[c.column_id] for c in columns if c.kind == "QUARTER"):
            earlier = _earlier(spec, quarters)
            found = [q for q in (*reversed(earlier), spec) if q is not None]
            window = _Window(
                spec,
                earlier,
                tiled=len(found) < 4 or _twelve_months(found, periods),
                year=_fiscal_year_of(spec, register),
            )
            frames[spec.column.column_id] = {
                key: _ltm_cell(one, register, window) for key, one in series.items()
            }
        return frames

"""The historical columns and the frame of CP-1's figures over them (spec M2).

Columns run quarters, PYTD, YTD, FY, then LTM. Every reported quarter is a
column; where CP-1's period register has no quarter, one is calculated as
H1 - Q1, 9M - H1 or FY - 9M when both periods exist.

The anchor is the latest end date of a quarter, YTD or FY period. At a
fiscal-year end there is no YTD and the LTM is that FY. Otherwise the YTD is
the YTD period ending at the anchor, else the anchor year's quarters to date
when every one is a column; the PYTD is the prior year's YTD period of the
same length, else the prior year's same quarters; and the LTM is FY + YTD -
PYTD with the FY of the prior year, the PYTD's, so the months always number
twelve. CP-1's LTM row ending at the anchor names the LTM column and supplies
the stated figures; one ending later than the anchor keeps its own column,
its flows `COMPONENT_MISSING` with CP-1's figure as `stated` (spec M4: the
host recomputes, it never adopts CP-1's arithmetic).

The LTM's FY must end the day before its YTD starts, and its PYTD start
with that FY; otherwise its flows are `COMPONENT_MISSING`, noted
`UNSPANNED`.

Every row of an outflow account in `OUTFLOW_METRICS` is read as minus its
absolute value before anything is summed, so CP-1 writing a quarter positive
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
before its quarters), a quarter without a row being nothing, repeated after
the part taken ends; a part with the period's own dates gives only its own
row. Every part without a row is `NOT_SOURCED`, and a part with a null
figure `COMPONENT_MISSING`. Each period is resolved once per item, so the
work is polynomial in the periods. Columns then add and subtract these
resolved figures (the LTM is FY + YTD - PYTD of them).

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

Pure: Decimal only, no I/O, no rounding.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field, replace
from datetime import date
from typing import Literal

from caos.calculators.credit_model._cells import (
    UNSPANNED,
)
from caos.calculators.credit_model.frame import Cell, Column
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
OUTFLOW_METRICS = frozenset(
    {
        "cogs",
        "opex_including_da",
        "depreciation_amortization",
        "cash_interest_paid",
        "cash_lease_payments",
        "cash_taxes_paid",
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

# "sparse" is a flow CP-1 writes only for the periods it occurred in (an
# add-back, a lease or interest payment classed in financing): a period
# without a row is its parts' sum, and a quarter without one is nothing.
# "flow" needs a row for every period it sums.
_Kind = Literal["flow", "sparse", "balance", "exact"]
_RANK = {"FY": 0, "YTD": 1, "QUARTER": 2}  # which period at the anchor date


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


@dataclass(frozen=True, slots=True)
class _Register:
    periods: dict[str | None, PeriodRow]  # None is never a key
    ending: dict[str | None, tuple[str, ...]]  # end date -> ids, register order
    # Start date -> the dated flow periods starting then, register order:
    # what a sparse item's cover of a period is chosen from.
    starting: dict[str, tuple[PeriodRow, ...]]


def _quarter_number(period: PeriodRow) -> int | None:
    """The register's fiscal quarter, `2` or `Q2`, as 1 to 4; else None."""
    if period.fiscal_quarter is None:
        return None
    return _QUARTERS.get(period.fiscal_quarter.upper())


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
    """Each (fiscal year, quarter) to its period: one each, `cp1_registers`
    refuses a second."""
    index: dict[tuple[int | None, int], PeriodRow] = {}
    for period in periods:
        number = _quarter_number(period)
        if number is not None:
            index[_year(period), number] = period
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
    no such quarter and both periods exist."""
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
            specs.append(replace(spec, column=replace(spec.column, days=days)))
    return specs


def _quarters(regs: Cp1Registers) -> list[_Spec]:
    specs = _calculated_quarters(regs)
    for period in _of_type(regs, "QUARTER"):
        number = _quarter_number(period)
        specs.append(_quarter_spec(period, number, period.period_id, None))
    return sorted(specs, key=lambda spec: spec.column.end_date or "")


def _period_spec(period: PeriodRow, kind: Literal["PYTD", "YTD", "FY"]) -> _Spec:
    """A register period's column; derived when it names its components."""
    number = _quarter_number(period)
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


def _anchor(regs: Cp1Registers) -> PeriodRow | None:
    """The period at the latest end date of a quarter, YTD or FY: an FY
    ending then, else a YTD, else a quarter, first in register order. An end
    that is not a `YYYY-MM-DD` date is none (its text would sort anywhere)."""
    candidates = [p for p in regs.periods if p.period_type in _RANK]
    ends = [day.isoformat() for p in candidates if (day := iso_date(p.end_date))]
    if not ends:
        return None
    return min(
        (p for p in candidates if p.end_date == max(ends)),
        key=lambda p: _RANK[p.period_type],
    )


def _quarter_index(specs: Iterable[_Spec]) -> dict[tuple[int, int], _Spec]:
    """Each (fiscal year, quarter) to its quarter column: one each, as
    `cp1_registers` refuses a second period for one fiscal quarter."""
    return {spec.quarter: spec for spec in specs if spec.quarter is not None}


def _summed(
    kind: Literal["PYTD", "YTD"],
    quarters: dict[tuple[int, int], _Spec],
    year: int,
    number: int,
) -> _Spec | None:
    """The year's quarters 1 to `number` as one column; None unless every
    one is a column."""
    specs = []
    for n in range(1, number + 1):
        spec = quarters.get((year, n))
        if spec is None:
            return None
        specs.append(spec)
    last = specs[-1].column
    terms: tuple[_Term, ...] = tuple((spec, 1) for spec in specs)
    return _Spec(
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


def _to_date(
    regs: Cp1Registers,
    quarters: dict[tuple[int, int], _Spec],
    anchor: PeriodRow | None,
) -> tuple[_Spec | None, _Spec | None]:
    """(PYTD, YTD) to the anchor; neither at a fiscal-year end."""
    if anchor is None or anchor.period_type == "FY":
        return None, None
    ytds = _of_type(regs, "YTD")
    row = next((p for p in ytds if p.end_date == anchor.end_date), None)
    year, number = _year(anchor), _quarter_number(row or anchor)
    if year is None or number is None:
        return None, _period_spec(row, "YTD") if row else None
    ytd = _period_spec(row, "YTD") if row else _summed("YTD", quarters, year, number)
    prior = next(
        (p for p in ytds if _year(p) == year - 1 and _quarter_number(p) == number),
        None,
    )
    if prior is not None:
        return _period_spec(prior, "PYTD"), ytd
    return _summed("PYTD", quarters, year - 1, number), ytd


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
    """Whether the FY ends the day before the YTD starts and the PYTD starts
    with the FY: FY + YTD - PYTD is then the twelve months to the YTD's end."""
    periods: dict[str | None, PeriodRow] = {p.period_id: p for p in regs.periods}
    starts = [_start(s, periods) for s in (fy, ytd, pytd)]
    year_end = iso_date(fy.column.end_date)
    if year_end is None or None in starts:
        return False
    year, current, prior = starts
    return year_end.toordinal() + 1 == current and prior == year


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


def _host_ltm(
    regs: Cp1Registers,
    anchor: PeriodRow,
    fiscal: list[_Spec],
    to_date: tuple[_Spec | None, _Spec | None],
) -> _Spec:
    """The LTM to the anchor: the FY ending then, or FY + YTD - PYTD with the
    prior year's FY; named by CP-1's LTM row ending at the anchor. Unbuilt,
    noted, where that FY, YTD and PYTD do not meet."""
    unbuilt = None
    if anchor.period_type == "FY":
        own_fy = next(spec for spec in fiscal if spec.own == anchor.period_id)
        terms: tuple[_Term, ...] = ((own_fy, 1),)
        number: int | None = 4
    else:
        terms, unbuilt = _rolled(regs, anchor, fiscal, to_date)
        number = _quarter_number(anchor)
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
    anchor = _anchor(regs)
    pytd, ytd = _to_date(regs, _quarter_index(quarters), anchor)
    fiscal = [_period_spec(p, "FY") for p in _by_end(_of_type(regs, "FY"))]
    specs = [*quarters, *(s for s in (pytd, ytd) if s is not None), *fiscal]
    if anchor is not None:
        specs.append(_host_ltm(regs, anchor, fiscal, (pytd, ytd)))
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

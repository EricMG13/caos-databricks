"""The credit metrics on every column: leverage, coverage, cash flow and
liquidity ratios, margins, and growth against the like period a year earlier.

Leverage and coverage are on a 12-month basis: a quarter reads the LTM ending
it (`ltm_ending`, the statements over `ltm_frames`), an FY, LTM, PF-LTM or
projected column itself, and on a PYTD or YTD they are `NOT_APPLICABLE`, as
are the flow-to-debt ratios (FFO and FCF over debt). Liquidity to debt is on
the 12-month basis where there is one, else on the PYTD or YTD itself. A
ratio of two flows of one period (FCF to adjusted EBITDA, capex to revenue
and the margins) is always on the column's own period, quarters included.
On the PF-LTM the reported-EBITDA variants of total and net leverage and of
interest coverage are `NOT_APPLICABLE`: pro forma is on adjusted EBITDA; so
are its EBITDA margins unless a pro forma adjustment reached revenue (its
revenue cell is then `PRO_FORMA`).

Debt and EBITDA are the frame's: the reported variants divide by `ebitda`,
the adjusted by `adjusted_ebitda`, and the lease-adjusted by
`adjusted_ebitdar`. Cash interest, capex and the operating lease cost are
outflows, negative in the frame, so the formulas negate them. A key a
projected column has no cell for (gross profit, the lease cost, EBITDAR) is
`NOT_PROJECTED`, as are the reported EBITDA and the lease balances it carries
so; any other column's missing key is `NOT_SOURCED`.

A metric with an input that has no figure takes that input's reason, the
first in formula order; a denominator at or below zero is
`ZERO_OR_NEGATIVE_DENOMINATOR`. A metric with a figure carries what its
inputs leave out ("excludes facility in another currency", "excludes
unallocated CP-CF movements", `debt.carried`), so leverage on debt without a
foreign facility, or projected secured debt without CP-CF's sweeps, says so.
Leverage and coverage are multiples (`x`), the rest decimal fractions shown
as percent (0.08 is 8%).

Growth compares a quarter with the quarter a year earlier, a YTD with the
PYTD, an FY with the FY and an LTM with the LTM a year earlier (the column of
that kind ending within a week of a year before, for 52- and 53-week years;
for an LTM without one, the LTM ending the quarter that ends then, from
`ltm_ending`), and a projection with its case's prior year, else the
historical FY of that year. Without such a column, and on a PYTD or PF-LTM,
it is `NOT_APPLICABLE`, as is a `bu_growth:` for a corporate or eliminations
segment (`corporate`).

Pure: Decimal only, no I/O, no rounding.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import date
from decimal import Decimal, localcontext
from typing import Literal

from caos.calculators.credit_model._cells import ABSENT, CONTEXT, refs
from caos.calculators.credit_model.debt import carried
from caos.calculators.credit_model.frame import Cell, Column, Frame
from caos.methodology.model_inputs import fiscal_year_number

Unit = Literal["MULTIPLE", "PERCENT"]
# "twelve": the 12-month basis, not applicable on a PYTD or YTD; "rolling":
# the 12-month basis where there is one, else the column; "own": the column's
# own period on every column, quarters included.
_Scope = Literal["twelve", "rolling", "own"]
_Parts = tuple[tuple[str, int], ...]


@dataclass(frozen=True, slots=True)
class _Metric:
    unit: Unit
    scope: _Scope
    numerator: _Parts
    denominator: _Parts


_DEBT: _Parts = (("total_debt", 1),)
_NET: _Parts = (("total_debt", 1), ("cash_closing", -1))
_EBITDA: _Parts = (("ebitda", 1),)
_ADJUSTED: _Parts = (("adjusted_ebitda", 1),)
_EBITDAR: _Parts = (("adjusted_ebitdar", 1),)
_INTEREST: _Parts = (("cash_interest", -1),)
_LEASED: _Parts = (("lease_adjusted_debt", 1),)
_REVENUE: _Parts = (("revenue", 1),)


_LEVERAGE: tuple[Unit, _Scope] = ("MULTIPLE", "twelve")  # leverage and coverage


_METRICS: dict[str, _Metric] = {
    "total_leverage_reported": _Metric(*_LEVERAGE, _DEBT, _EBITDA),
    "total_leverage_adjusted": _Metric(*_LEVERAGE, _DEBT, _ADJUSTED),
    "net_leverage_reported": _Metric(*_LEVERAGE, _NET, _EBITDA),
    "net_leverage_adjusted": _Metric(*_LEVERAGE, _NET, _ADJUSTED),
    "senior_secured_leverage": _Metric(*_LEVERAGE, (("secured_debt", 1),), _ADJUSTED),
    "senior_secured_net_leverage": _Metric(
        *_LEVERAGE, (("secured_debt", 1), ("cash_closing", -1)), _ADJUSTED
    ),
    "lease_adjusted_leverage": _Metric(*_LEVERAGE, _LEASED, _EBITDAR),
    "lease_adjusted_net_leverage": _Metric(
        *_LEVERAGE, (("lease_adjusted_net_debt", 1),), _EBITDAR
    ),
    "interest_coverage_reported": _Metric(*_LEVERAGE, _EBITDA, _INTEREST),
    "interest_coverage_adjusted": _Metric(*_LEVERAGE, _ADJUSTED, _INTEREST),
    "capex_adjusted_coverage": _Metric(
        *_LEVERAGE, (("adjusted_ebitda", 1), ("capex", 1)), _INTEREST
    ),
    "ebitdar_coverage": _Metric(
        *_LEVERAGE,
        (("adjusted_ebitdar", 1), ("capex", 1)),
        (("cash_interest", -1), ("operating_lease_cost", -1)),
    ),
    "ffo_to_debt": _Metric("PERCENT", "twelve", (("ffo", 1),), _DEBT),
    "ffo_to_lease_adjusted_debt": _Metric("PERCENT", "twelve", (("ffo", 1),), _LEASED),
    "fcf_to_debt": _Metric("PERCENT", "twelve", (("fcf", 1),), _DEBT),
    "fcf_to_adjusted_ebitda": _Metric("PERCENT", "own", (("fcf", 1),), _ADJUSTED),
    "capex_to_revenue": _Metric("PERCENT", "own", (("capex", -1),), _REVENUE),
    "liquidity_to_debt": _Metric("PERCENT", "rolling", (("liquidity", 1),), _DEBT),
    "gross_margin": _Metric("PERCENT", "own", (("gross_profit", 1),), _REVENUE),
    "ebitda_margin": _Metric("PERCENT", "own", _EBITDA, _REVENUE),
    "adjusted_ebitda_margin": _Metric("PERCENT", "own", _ADJUSTED, _REVENUE),
}
# The reported-EBITDA variants: not applicable on the PF-LTM.
_REPORTED = frozenset(
    {"total_leverage_reported", "net_leverage_reported", "interest_coverage_reported"}
)
# EBITDA margins: not applicable on the PF-LTM unless its revenue is adjusted
# too (acquired EBITDA over unadjusted revenue is no margin).
_PF_MARGINS = frozenset({"ebitda_margin", "adjusted_ebitda_margin"})
_GROWTH = ("revenue", "adjusted_ebitda")
_GROWTH_KEYS = frozenset({"revenue_growth", "adjusted_ebitda_growth"})
_LIKE = {"QUARTER": "QUARTER", "YTD": "PYTD", "FY": "FY", "LTM": "LTM"}
_YEAR = 365
_WEEK = 7  # a 52- or 53-week year ends within a week of the calendar year
_NOT_APPLICABLE = Cell(None, "NOT_APPLICABLE")
_NOT_PROJECTED = Cell(None, "NOT_PROJECTED")


def unit_of(key: str) -> Unit:
    """A metric or growth key's unit; a `KeyError` for any other key."""
    if key in _GROWTH_KEYS or key.startswith("bu_growth:"):
        return "PERCENT"
    if not key.startswith("metric:"):
        raise KeyError(key)
    return _METRICS[key.removeprefix("metric:")].unit


def _get(cells: Mapping[str, Cell], key: str, column: Column) -> Cell:
    """The cell, or why there is none: a projection does not project it, any
    other column has no source for it."""
    default = _NOT_PROJECTED if column.kind == "PROJECTED" else ABSENT
    return cells.get(key, default)


def _total(parts: Iterable[tuple[Cell, int]]) -> Decimal:
    """The parts added (+1) or subtracted (-1); each has a figure."""
    total = Decimal(0)
    for cell, sign in parts:
        if cell.value is not None:
            total += cell.value * sign
    return total


def _ratio(
    numerator: Sequence[tuple[Cell, int]], denominator: Sequence[tuple[Cell, int]]
) -> Cell:
    """The numerator's parts over the denominator's, noted with what they
    leave out: the first part without a figure gives its reason; a
    denominator <= 0 refuses."""
    parts = (*numerator, *denominator)
    missing = next((cell for cell, _ in parts if cell.value is None), None)
    if missing is not None:
        return Cell(None, missing.reason)
    bottom = _total(denominator)
    if bottom <= 0:
        return Cell(None, "ZERO_OR_NEGATIVE_DENOMINATOR")
    sources = refs(source for cell, _ in parts for source in cell.sources)
    note = carried(cell for cell, _ in parts)
    value = _total(numerator) / bottom
    return Cell(value, basis="CALCULATED", sources=sources, note=note)


def _basis(
    column: Column,
    own: Mapping[str, Cell],
    ltm_ending: Mapping[str, dict[str, Cell]],
    scope: _Scope,
) -> Mapping[str, Cell] | None:
    """The cells a metric of `scope` reads for the column; None where it is
    not applicable."""
    if scope == "own":
        return own
    if column.kind == "QUARTER":
        return ltm_ending[column.column_id]
    if column.kind in ("PYTD", "YTD"):
        return None if scope == "twelve" else own
    return own


def _pf_blank(column: Column, own: Mapping[str, Cell], name: str) -> bool:
    """Whether the metric is not applicable on a PF-LTM: a reported-EBITDA
    variant, or an EBITDA margin where no adjustment reached revenue."""
    if column.kind != "PF_LTM":
        return False
    revenue = _get(own, "revenue", column)
    return name in _REPORTED or (name in _PF_MARGINS and revenue.basis != "PRO_FORMA")


def _metrics(
    column: Column,
    own: Mapping[str, Cell],
    ltm_ending: Mapping[str, dict[str, Cell]],
) -> dict[str, Cell]:
    cells: dict[str, Cell] = {}
    for name, metric in _METRICS.items():
        blank = _pf_blank(column, own, name)
        basis = None if blank else _basis(column, own, ltm_ending, metric.scope)
        if basis is None:
            cells[f"metric:{name}"] = _NOT_APPLICABLE
            continue
        numerator = [(_get(basis, key, column), sign) for key, sign in metric.numerator]
        denominator = [
            (_get(basis, key, column), sign) for key, sign in metric.denominator
        ]
        cells[f"metric:{name}"] = _ratio(numerator, denominator)
    return cells


def _year_before(column: Column, other: Column) -> bool:
    """Whether `other` ends within a week of a year before `column`."""
    if column.end_date is None or other.end_date is None:
        return False
    gap = date.fromisoformat(column.end_date) - date.fromisoformat(other.end_date)
    return abs(gap.days - _YEAR) <= _WEEK


def _projected_prior(column: Column, columns: tuple[Column, ...]) -> Column | None:
    """A projection's prior year: its case's, else the historical FY."""
    year = fiscal_year_number(column.fiscal_year)
    if year is None:
        return None
    before = [c for c in columns if fiscal_year_number(c.fiscal_year) == year - 1]
    same = [c for c in before if c.kind == "PROJECTED" and c.case == column.case]
    fiscal = [c for c in before if c.kind == "FY"]
    return next(iter((*same, *fiscal)), None)


def _prior(column: Column, columns: tuple[Column, ...]) -> Column | None:
    """The like period a year earlier, or None."""
    if column.kind == "PROJECTED":
        return _projected_prior(column, columns)
    like = _LIKE.get(column.kind)
    return next(
        (c for c in columns if c.kind == like and _year_before(column, c)),
        None,
    )


_Prior = tuple[Column, Mapping[str, Cell]]


def _prior_cells(
    column: Column,
    columns: tuple[Column, ...],
    frame: Frame,
    ltm_ending: Mapping[str, dict[str, Cell]],
) -> _Prior | None:
    """The like period a year earlier and its cells: for an LTM without an
    LTM column then, the LTM ending the quarter that ends then."""
    prior = _prior(column, columns)
    if prior is not None:
        return prior, frame[prior.column_id]
    if column.kind != "LTM":
        return None
    quarter = next(
        (c for c in columns if c.kind == "QUARTER" and _year_before(column, c)),
        None,
    )
    return None if quarter is None else (quarter, ltm_ending[quarter.column_id])


def _growth(
    column: Column,
    own: Mapping[str, Cell],
    prior: _Prior | None,
    corporate: frozenset[str],
) -> dict[str, Cell]:
    """`revenue_growth`, `adjusted_ebitda_growth` and each `bu_growth:`
    against the prior period's cells."""
    segments = [key.removeprefix("bu:") for key in own if key.startswith("bu:")]
    keys = {
        **{f"{key}_growth": key for key in _GROWTH},
        **{f"bu_growth:{segment}": f"bu:{segment}" for segment in segments},
    }
    cells: dict[str, Cell] = {}
    for growth_key, key in keys.items():
        segment = key.startswith("bu:") and key.removeprefix("bu:") in corporate
        if prior is None or segment:
            cells[growth_key] = _NOT_APPLICABLE
            continue
        before, before_cells = prior
        ratio = _ratio(
            ((_get(own, key, column), 1),),
            ((_get(before_cells, key, before), 1),),
        )
        if ratio.value is not None:
            ratio = replace(ratio, value=ratio.value - 1)
        cells[growth_key] = ratio
    return cells


def metric_frame(
    columns: tuple[Column, ...],
    frame: Frame,
    ltm_ending: Mapping[str, dict[str, Cell]],
    *,
    corporate: frozenset[str] = frozenset(),
) -> Frame:
    """Each column's cells in `frame` plus its `metric:<name>` keys,
    `revenue_growth`, `adjusted_ebitda_growth` and a `bu_growth:<segment>`
    for each of its `bu:` keys. `ltm_ending[column_id]` is the statements of
    the LTM ending a quarter column (`statement_frame` over `ltm_frames`);
    `corporate` the corporate and eliminations segments, never grown."""
    with localcontext(CONTEXT):
        result: Frame = {}
        for column in columns:
            own = frame[column.column_id]
            prior = _prior_cells(column, columns, frame, ltm_ending)
            result[column.column_id] = {
                **own,
                **_metrics(column, own, ltm_ending),
                **_growth(column, own, prior, corporate),
            }
        return result

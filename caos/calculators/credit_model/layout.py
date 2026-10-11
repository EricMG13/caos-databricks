"""The credit model's lines: every row of the worked layout, in its bands
and order, with one cell per column (spec, layout rule and row economy).

Bands run KPIs, business-unit revenue, gross profit, operating expenses to
EBITDA, adjusted EBITDA, the waterfall to free cash flow, the net cash flow
with cash and liquidity, the debt stack by payment rank, the debt
roll-forward, the projections' interest, working capital and the credit
metrics. Every line is emitted, zero or empty ones included: hiding them is
the frontend's job.

A line reads its frame key on each column; a key a column has no cell for is
`NOT_PROJECTED` on a projection, `NOT_APPLICABLE` for a pro forma row or an
interest line elsewhere, else `NOT_SOURCED`. Two kinds of line are the
layout's own: "Less: cash and equivalents" (closing cash negated) and a
payment rank's subtotal, shown only where the rank has more than one facility
in its totals, and, after the ranks and in none, "Unallocated movements
(CP-CF)": a projection's total debt less its scheduled facilities, so the
stack foots on every column. A pro forma row sits under the account it adjusts (a
facility, cash interest, closing cash, the operating lease liabilities),
which on the PF-LTM shows the LTM's unadjusted figure, or above the subtotal
it enters (revenue, EBITDA, adjusted EBITDA); a facility the register has
no row for, or a `total_debt` adjustment, sits above total debt. Subtotals
and totals include the PF rows. Where the business units (and revenue PF
rows) do not sum to revenue beyond its rounding, the revenue cell is noted
"business units do not sum to revenue". A `MEMO` line enters no total: the
CFO as reported, an add-back left out by "exclude unrealised", and a
facility in another currency. Operating leases are not facilities in the
stack: their balance is the operating lease liabilities line (a `DEBT
ADJUSTMENT` row is debt however it is classified, `debt.is_operating_lease`).
An add-back's label shows the realisation status "exclude unrealised" reads:
its last row's that is unrealised or not stated, else its last row's. The
roll-forward's debt raised on the PF-LTM is the LTM's, so the PF-LTM's
roll-forward foots to its pro forma closing debt.

Pure: Decimal only, no I/O, no rounding.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from decimal import Decimal, localcontext
from typing import Literal

from caos.calculators.credit_model._cells import (
    CONTEXT,
    beyond_rounding,
    calc,
    join_notes,
)
from caos.calculators.credit_model.debt import (
    PAYMENT_RANKS,
    is_operating_lease,
    payment_rank,
)
from caos.calculators.credit_model.frame import Cell, Column, Frame
from caos.calculators.credit_model.metrics import unit_of
from caos.calculators.credit_model.statements import UNREALISED, excluded_addbacks
from caos.methodology.model_inputs import (
    AddbackRow,
    Cp1Registers,
    FacilityRow,
    PfAdjustmentRow,
)

LineKind = Literal["ACCOUNT", "SUBTOTAL", "RATIO", "MEMO", "PF", "GROWTH"]
Unit = Literal["MONEY", "PERCENT", "MULTIPLE", "DAYS", "COUNT", "RATE", "KPI"]

BANDS: tuple[str, ...] = (
    "Operating KPIs",
    "Revenue by business unit",
    "Gross profit",
    "Operating expenses to EBITDA",
    "Adjusted EBITDA",
    "Adjusted EBITDA to free cash flow",
    "Net cash flow, cash and liquidity",
    "Debt stack by payment rank, period end",
    "Debt roll-forward",
    "Interest calculation, projections",
    "Working capital, period end",
    "Credit metrics (leverage and coverage on 12-month EBITDA)",
)
(
    _KPI_BAND,
    _REVENUE_BAND,
    _GROSS_BAND,
    _OPEX_BAND,
    _ADJUSTED_BAND,
    _CASH_FLOW_BAND,
    _LIQUIDITY_BAND,
    _DEBT_BAND,
    _ROLLFORWARD_BAND,
    _INTEREST_BAND,
    _WORKING_CAPITAL_BAND,
    _METRIC_BAND,
) = BANDS

_REALISATION = {
    "REALIZED": "realised",
    "UNREALIZED": "unrealised",
    "NOT_STATED": "realisation not stated",
}
_REFERENCE_RATES = {
    "SOFR": "SOFR",
    "TERM_SOFR": "Term SOFR",
    "EURIBOR": "EURIBOR",
    "SONIA": "SONIA",
    "NONE": "none",
    "NOT_STATED": "not stated",
}
_NOT_STATED = "not stated"
UNALLOCATED = "debt:unallocated"
BU_NOT_SUMMED = "business units do not sum to revenue"
_FACILITY = "facility:"
# Where a pro forma adjustment's row sits: the line it adjusts or enters.
_PF_PLACES = {
    "revenue": "revenue",
    "ebitda": "ebitda",
    "adjusted_ebitda": "adjusted_ebitda",
    "cash_interest_paid": "cash_interest",
    "cash_and_equivalents": "cash_closing",
    "total_debt": "total_debt",
}
_INTEREST_KEYS = frozenset(
    {"reference_rate", "interest_bearing_debt_opening", "wa_rate"}
)
_METRICS = (
    ("total_leverage_reported", "Total leverage, reported EBITDA"),
    ("total_leverage_adjusted", "Total leverage, adjusted EBITDA"),
    ("net_leverage_reported", "Net leverage, reported EBITDA"),
    ("net_leverage_adjusted", "Net leverage, adjusted EBITDA"),
    ("senior_secured_leverage", "Senior secured leverage, adjusted EBITDA"),
    ("senior_secured_net_leverage", "Senior secured net leverage, adjusted EBITDA"),
    ("lease_adjusted_leverage", "Lease-adjusted leverage, adjusted EBITDAR"),
    ("lease_adjusted_net_leverage", "Lease-adjusted net leverage, adjusted EBITDAR"),
    ("interest_coverage_reported", "EBITDA / cash interest, reported"),
    ("interest_coverage_adjusted", "Adjusted EBITDA / cash interest"),
    ("capex_adjusted_coverage", "(Adjusted EBITDA - capex) / cash interest"),
    ("ebitdar_coverage", "(Adjusted EBITDAR - capex) / (cash interest + rent)"),
    ("ffo_to_debt", "FFO / total debt"),
    ("ffo_to_lease_adjusted_debt", "FFO / lease-adjusted debt"),
    ("fcf_to_debt", "FCF / total debt"),
    ("fcf_to_adjusted_ebitda", "FCF / adjusted EBITDA"),
    ("capex_to_revenue", "Capex / revenue"),
    ("liquidity_to_debt", "Liquidity / total debt"),
)


@dataclass(frozen=True, slots=True)
class FacilityTerms:
    reference_rate: str
    spread_or_coupon: str  # "+225 bp" or "6.500%"
    floor: str  # "0.50%", "none" or "n.a."
    maturity: str  # the ISO date as given
    amortisation: str  # "24 p.a.", "bullet" or "not stated"


@dataclass(frozen=True, slots=True)
class Line:
    line_id: str
    band: str
    label: str
    kind: LineKind
    unit: Unit
    unit_label: str | None
    rank: str | None
    terms: FacilityTerms | None
    cells: tuple[Cell, ...]  # one per column, in column order


@dataclass(frozen=True, slots=True)
class _Spec:
    """A line before its cells: the frame `key` it reads, or the `parts` it
    sums (a rank subtotal), negated where `negate`; on a projection, the
    `parts` short of `total` (the unallocated movements); on the PF-LTM, the
    LTM's cell where `unadjusted` (its PF rows sit beneath)."""

    line_id: str
    key: str
    label: str
    kind: LineKind
    unit: Unit = "MONEY"
    unit_label: str | None = None
    rank: str | None = None
    terms: FacilityTerms | None = None
    parts: tuple[str, ...] = ()
    negate: bool = False
    total: str | None = None
    unadjusted: bool = False


def _plain(key: str, label: str, kind: LineKind = "ACCOUNT") -> _Spec:
    return _Spec(key, key, label, kind)


def _pf_place(
    adjustment: PfAdjustmentRow, stack: Mapping[str, _Spec], leases: frozenset[str]
) -> str | None:
    """The line a pro forma row sits by: its facility's in the stack, the
    operating lease liabilities for an operating lease, or total debt for a
    facility the register has not; else its metric's line; None for a
    metric no line takes."""
    if adjustment.metric_id.startswith(_FACILITY):
        key = f"fac:{adjustment.metric_id.removeprefix(_FACILITY)}"
        if key in stack:
            return key
        return "lease_liabilities" if key in leases else "total_debt"
    return _PF_PLACES.get(adjustment.metric_id)


def _pf_specs(
    regs: Cp1Registers, stack: Mapping[str, _Spec], periods: frozenset[str | None]
) -> dict[str, list[_Spec]]:
    """The rows of the pro forma adjustments to `periods` (the PF-LTM's) by
    the line they sit by, register order."""
    rows = {row.facility_id: row for row in regs.facilities}
    leases = frozenset(
        f"fac:{facility_id}"
        for facility_id, row in rows.items()
        if is_operating_lease(row)
    )
    places: dict[str, list[_Spec]] = {}
    for adjustment in regs.pro_forma:
        if adjustment.period_id not in periods:
            continue
        place = _pf_place(adjustment, stack, leases)
        if place is None:
            continue
        key = f"pf:{adjustment.adjustment_id}"
        label = f"PF adjustment: {adjustment.label}"
        places.setdefault(place, []).append(_Spec(key, key, label, "PF"))
    return places


def _kpi_specs(regs: Cp1Registers) -> list[_Spec]:
    rows = {row.kpi_id: row for row in regs.kpis}
    ordered = sorted(rows.values(), key=lambda row: row.display_priority)
    return [
        _Spec(
            f"kpi:{row.kpi_id}",
            f"kpi:{row.kpi_id}",
            row.kpi_label,
            "ACCOUNT",
            unit="KPI",
            unit_label=row.unit,
        )
        for row in ordered
    ]


def _revenue_specs(regs: Cp1Registers, pro_forma: list[_Spec]) -> list[_Spec]:
    """Each business unit and its growth (none for corporate and
    eliminations), the revenue PF rows, total revenue and its growth."""
    rows = {row.segment_id: row for row in regs.segments}
    specs: list[_Spec] = []
    for row in sorted(rows.values(), key=lambda row: row.display_priority):
        specs.append(_plain(f"bu:{row.segment_id}", row.segment_name))
        if row.segment_type != "CORPORATE_ELIMINATION":
            growth = f"bu_growth:{row.segment_id}"
            label = f"{row.segment_name} growth YoY"
            specs.append(_Spec(growth, growth, label, "GROWTH", unit="PERCENT"))
    return [
        *specs,
        *pro_forma,
        _plain("revenue", "Total revenue", "SUBTOTAL"),
        _Spec(
            "revenue_growth",
            "revenue_growth",
            "Total revenue growth YoY",
            "GROWTH",
            unit="PERCENT",
        ),
    ]


def _ratio(name: str, label: str) -> _Spec:
    key = f"metric:{name}"
    return _Spec(key, key, label, "RATIO", unit=unit_of(key))


def _income_specs(pf: Mapping[str, list[_Spec]]) -> list[tuple[str, _Spec]]:
    gross = [
        _plain("cogs", "Cost of revenue"),
        _plain("gross_profit", "Gross profit", "SUBTOTAL"),
        _ratio("gross_margin", "Gross margin"),
    ]
    opex = [
        _plain("opex_ex_da", "Operating expenses excluding D&A"),
        _plain("da", "Depreciation and amortisation"),
        _plain("opex_total", "Total operating expenses", "SUBTOTAL"),
        _plain("ebit", "EBIT", "SUBTOTAL"),
        *pf.get("ebitda", []),
        _plain("ebitda", "EBITDA", "SUBTOTAL"),
        _ratio("ebitda_margin", "EBITDA margin"),
    ]
    return [
        *((_GROSS_BAND, spec) for spec in gross),
        *((_OPEX_BAND, spec) for spec in opex),
    ]


def _addback_spec(
    row: AddbackRow, statuses: list[str], excluded: frozenset[str]
) -> _Spec:
    """The add-back's line, `row` its last; labelled with the status that
    "exclude unrealised" reads from all its rows (`statuses`)."""
    unrealised = [status for status in statuses if status in UNREALISED]
    shown = unrealised[-1] if unrealised else row.realization_status
    status = _REALISATION.get(shown, shown)
    key = f"addback:{row.addback_id}"
    if row.addback_id in excluded:
        return _Spec(key, key, f"Add-back: {row.label} ({status}), excluded", "MEMO")
    return _Spec(key, key, f"Add-back: {row.label} ({status})", "ACCOUNT")


def _adjusted_specs(
    regs: Cp1Registers, excluded: frozenset[str], pro_forma: list[_Spec]
) -> list[_Spec]:
    rows = {row.addback_id: row for row in regs.addbacks}
    statuses: dict[str, list[str]] = {}
    for row in regs.addbacks:
        statuses.setdefault(row.addback_id, []).append(row.realization_status)
    ordered = sorted(rows.values(), key=lambda row: row.display_priority)
    return [
        *(_addback_spec(row, statuses[row.addback_id], excluded) for row in ordered),
        *pro_forma,
        _plain("adjusted_ebitda", "Adjusted EBITDA", "SUBTOTAL"),
        _ratio("adjusted_ebitda_margin", "Adjusted EBITDA margin"),
        _plain("operating_lease_cost", "Operating lease cost (rent)"),
        _plain("adjusted_ebitdar", "Adjusted EBITDAR", "SUBTOTAL"),
    ]


def _cash_flow_specs(pro_forma: list[_Spec]) -> list[_Spec]:
    return [
        replace(_plain("cash_interest", "Cash interest paid"), unadjusted=True),
        *pro_forma,
        _plain("lease_cash_not_in_ebitda", "Lease cash not in EBITDA"),
        _plain("cash_taxes", "Cash taxes paid"),
        _plain("other_operating", "Other operating cash items (residual)"),
        _plain("ffo", "Funds from operations (FFO)", "SUBTOTAL"),
        _plain("working_capital_change", "Change in working capital"),
        _plain(
            "cfo_adjusted",
            "Cash from operations, after all interest and lease cash",
            "SUBTOTAL",
        ),
        _plain("cfo_reported", "Memo: cash from operations as reported", "MEMO"),
        _plain("capex", "Capital expenditure"),
        _plain("fcf", "Free cash flow (FCF)", "SUBTOTAL"),
    ]


def _liquidity_specs(pro_forma: list[_Spec]) -> list[_Spec]:
    return [
        _plain("acquisitions_net", "Acquisitions and disposals, net"),
        _plain("debt_raised_net", "Debt raised, net of repayments"),
        _plain("equity_raised_net", "Equity raised, net of buybacks"),
        _plain("dividends", "Dividends and other distributions"),
        _plain("other_investing_financing", "Other investing and financing"),
        _plain("ncf", "Net cash flow (NCF)", "SUBTOTAL"),
        _plain("cash_opening", "Opening cash"),
        _plain("fx_and_other_cash", "FX and other cash movements (residual)"),
        replace(
            _plain("cash_closing", "Closing cash and equivalents", "SUBTOTAL"),
            unadjusted=True,
        ),
        *pro_forma,
        _plain("undrawn_rcf", "Undrawn RCF"),
        _plain("liquidity", "Liquidity", "SUBTOTAL"),
    ]


def _decimal_text(value: Decimal) -> str:
    """The figure as written, never rounded or in exponent form."""
    return format(value, "f")


def _spread_or_coupon(row: FacilityRow) -> str:
    if row.rate_type == "FIXED" and row.fixed_rate is not None:
        return f"{_decimal_text(row.fixed_rate)}%"
    if row.rate_type == "FLOATING" and row.spread_bps is not None:
        return f"+{_decimal_text(row.spread_bps)} bp"
    return _NOT_STATED


def _floor(row: FacilityRow) -> str:
    if row.floor_bps is not None:
        return f"{_decimal_text(row.floor_bps.scaleb(-2))}%"
    return "none" if row.rate_type == "FLOATING" else "n.a."


def _amortisation(row: FacilityRow) -> str:
    if row.annual_amortisation is None:
        return _NOT_STATED
    if row.annual_amortisation == 0:
        return "bullet"
    return f"{_decimal_text(row.annual_amortisation)} p.a."


def facility_terms(row: FacilityRow) -> FacilityTerms:
    """The facility's terms as the stack shows them, one per column: the
    reference rate, the spread (bp) or fixed coupon (%), the floor (%), the
    maturity as given and the stated annual amortisation; never rounded."""
    return FacilityTerms(
        reference_rate=_REFERENCE_RATES.get(row.reference_rate, row.reference_rate),
        spread_or_coupon=_spread_or_coupon(row),
        floor=_floor(row),
        maturity=row.maturity_date or _NOT_STATED,
        amortisation=_amortisation(row),
    )


def _stack(regs: Cp1Registers) -> dict[str, _Spec]:
    """Each facility's line by its last register row, operating leases left
    out; one in another currency is a memo, in no total."""
    rows = {row.facility_id: row for row in regs.facilities}
    stack: dict[str, _Spec] = {}
    for facility_id, row in rows.items():
        if is_operating_lease(row):
            continue
        key = f"fac:{facility_id}"
        foreign = row.currency != regs.currency
        stack[key] = _Spec(
            key,
            key,
            row.facility_name,
            "MEMO" if foreign else "ACCOUNT",
            rank=payment_rank(row),
            terms=facility_terms(row),
            unadjusted=True,
        )
    return stack


def _rank_specs(
    rank: str, facilities: list[_Spec], pf: Mapping[str, list[_Spec]]
) -> list[_Spec]:
    """A rank's facilities, each with its PF rows, and its subtotal where
    more than one enters its totals."""
    specs: list[_Spec] = []
    for facility in facilities:
        specs.append(facility)
        specs.extend(replace(row, rank=rank) for row in pf.get(facility.key, []))
    summed = tuple(f.key for f in facilities if f.kind == "ACCOUNT")
    if len(summed) > 1:
        key = f"rank:{rank}"
        label = f"Total {rank.lower()}"
        specs.append(_Spec(key, key, label, "SUBTOTAL", rank=rank, parts=summed))
    return specs


def _debt_specs(
    stack: Mapping[str, _Spec], pf: Mapping[str, list[_Spec]]
) -> list[_Spec]:
    specs: list[_Spec] = []
    for rank in PAYMENT_RANKS:
        facilities = [spec for spec in stack.values() if spec.rank == rank]
        specs.extend(_rank_specs(rank, facilities, pf))
    summed = tuple(key for key, spec in stack.items() if spec.kind == "ACCOUNT")
    unallocated = _Spec(
        UNALLOCATED,
        UNALLOCATED,
        "Unallocated movements (CP-CF)",
        "ACCOUNT",
        parts=summed,
        total="total_debt",
    )
    return [
        *specs,
        unallocated,
        *pf.get("total_debt", []),
        _plain("total_debt", "Total debt", "SUBTOTAL"),
        replace(
            _plain("lease_liabilities", "Operating lease liabilities"),
            unadjusted=True,
        ),
        *pf.get("lease_liabilities", []),
        _plain("lease_adjusted_debt", "Lease-adjusted debt", "SUBTOTAL"),
        _Spec(
            "less_cash",
            "cash_closing",
            "Less: cash and equivalents",
            "ACCOUNT",
            negate=True,
        ),
        _plain("net_debt", "Net debt", "SUBTOTAL"),
        _plain("lease_adjusted_net_debt", "Lease-adjusted net debt", "SUBTOTAL"),
    ]


def _rollforward_specs(
    stack: Mapping[str, _Spec], pf: Mapping[str, list[_Spec]]
) -> list[_Spec]:
    """Opening, debt raised, non-cash and lease movements, the PF rows that
    enter total debt, and closing."""
    places = [key for key, spec in stack.items() if spec.kind == "ACCOUNT"]
    rows = [row for place in (*places, "total_debt") for row in pf.get(place, [])]
    return [
        _plain("debt_opening", "Opening total debt"),
        _Spec(
            "rollforward:debt_raised_net",
            "debt_raised_net",
            "Debt raised, net of repayments",
            "ACCOUNT",
            unadjusted=True,
        ),
        _plain("debt_non_cash", "Non-cash and lease movements (residual)"),
        *(replace(row, line_id=f"rollforward:{row.key}") for row in rows),
        _plain("debt_closing", "Closing total debt", "SUBTOTAL"),
    ]


def _interest_specs(deck_as_of: str | None) -> list[_Spec]:
    label = "Reference rate" + (f", rate deck {deck_as_of}" if deck_as_of else "")
    return [
        _Spec("reference_rate", "reference_rate", label, "ACCOUNT", unit="RATE"),
        _plain("interest_bearing_debt_opening", "Interest-bearing debt, opening"),
        _Spec(
            "wa_rate", "wa_rate", "Weighted average all-in rate", "RATIO", unit="RATE"
        ),
    ]


def _working_capital_specs() -> list[_Spec]:
    days = (
        ("dso", "DSO"),
        ("dio", "DIO"),
        ("dpo", "DPO"),
        ("ccc", "Cash conversion cycle"),
    )
    return [
        _plain("accounts_receivable", "Accounts receivable"),
        _plain("inventory", "Inventory"),
        _plain("accounts_payable", "Accounts payable"),
        *(_Spec(key, key, label, "RATIO", unit="DAYS") for key, label in days),
    ]


def _metric_specs() -> list[_Spec]:
    return [
        *(_ratio(name, label) for name, label in _METRICS),
        _Spec(
            "adjusted_ebitda_growth",
            "adjusted_ebitda_growth",
            "Adjusted EBITDA growth YoY",
            "GROWTH",
            unit="PERCENT",
        ),
    ]


def _specs(
    regs: Cp1Registers,
    columns: tuple[Column, ...],
    exclude_unrealised: bool,
    deck_as_of: str | None,
) -> list[tuple[str, _Spec]]:
    """Every line, band by band, before its cells."""
    stack = _stack(regs)
    periods = frozenset(c.period_id for c in columns if c.kind == "PF_LTM")
    pf = _pf_specs(regs, stack, periods)
    excluded = excluded_addbacks(regs, exclude_unrealised)
    banded: list[tuple[str, Iterable[_Spec]]] = [
        (_KPI_BAND, _kpi_specs(regs)),
        (_REVENUE_BAND, _revenue_specs(regs, pf.get("revenue", []))),
    ]
    specs = [(band, spec) for band, group in banded for spec in group]
    specs.extend(_income_specs(pf))
    banded = [
        (
            _ADJUSTED_BAND,
            _adjusted_specs(regs, excluded, pf.get("adjusted_ebitda", [])),
        ),
        (_CASH_FLOW_BAND, _cash_flow_specs(pf.get("cash_interest", []))),
        (_LIQUIDITY_BAND, _liquidity_specs(pf.get("cash_closing", []))),
        (_DEBT_BAND, _debt_specs(stack, pf)),
        (_ROLLFORWARD_BAND, _rollforward_specs(stack, pf)),
        (_INTEREST_BAND, _interest_specs(deck_as_of)),
        (_WORKING_CAPITAL_BAND, _working_capital_specs()),
        (_METRIC_BAND, _metric_specs()),
    ]
    specs.extend((band, spec) for band, group in banded for spec in group)
    return specs


def _missing(column: Column, key: str) -> Cell:
    """Why a column has no cell for the key."""
    if key.startswith("pf:"):
        return Cell(None, "NOT_APPLICABLE")
    if column.kind == "PROJECTED":
        return Cell(None, "NOT_PROJECTED")
    if key in _INTEREST_KEYS:
        return Cell(None, "NOT_APPLICABLE")
    return Cell(None, "NOT_SOURCED")


def _subtotal(
    column: Column, cells: Mapping[str, Cell], parts: tuple[str, ...]
) -> Cell:
    """The facilities a column has a cell for, summed; why there is none
    when it has none."""
    found = [
        cell
        for key in parts
        if (cell := cells.get(key)) is not None and cell.reason != "NOT_SOURCED"
    ]
    if not found:
        return _missing(column, parts[0])
    return calc((cell, 1) for cell in found)


def _unallocated(
    column: Column, cells: Mapping[str, Cell], spec: _Spec, total: str
) -> Cell:
    """A projection's total debt less its facilities (a facility it has no
    cell for adds nothing); not applicable on any other column."""
    if column.kind != "PROJECTED":
        return Cell(None, "NOT_APPLICABLE")
    facilities = [(cells[key], -1) for key in spec.parts if key in cells]
    return calc(((cells.get(total, _missing(column, total)), 1), *facilities))


def _cell(spec: _Spec, column: Column, cells: Mapping[str, Cell]) -> Cell:
    if spec.total is not None:
        return _unallocated(column, cells, spec, spec.total)
    if spec.parts:
        return _subtotal(column, cells, spec.parts)
    cell = cells.get(spec.key)
    if cell is None:
        return _missing(column, spec.key)
    if spec.negate and cell.value is not None:
        stated = None if cell.stated is None else -cell.stated
        return replace(cell, value=-cell.value, stated=stated)
    return cell


def _revenue_noted(lines: list[Line], columns: tuple[Column, ...]) -> list[Line]:
    """The revenue line, its cell noted on each column where the business
    units (and the revenue PF rows) do not sum to it beyond its rounding."""
    units = [line for line in lines if line.line_id.startswith("bu:")]
    if not units:
        return lines
    rows = [line for line in lines if line.band == _REVENUE_BAND and line.kind == "PF"]
    noted: list[Line] = []
    for line in lines:
        if line.line_id == "revenue":
            cells = tuple(
                _revenue_cell(line.cells[index], units, rows, index)
                for index in range(len(columns))
            )
            line = replace(line, cells=cells)
        noted.append(line)
    return noted


def _revenue_cell(
    revenue: Cell, units: list[Line], rows: list[Line], index: int
) -> Cell:
    parts = [line.cells[index] for line in units]
    adjustments = [line.cells[index].value for line in rows]
    if revenue.value is None or any(cell.value is None for cell in parts):
        return revenue
    summed = sum(
        (
            value
            for value in (*(c.value for c in parts), *adjustments)
            if value is not None
        ),
        Decimal(0),
    )
    if not beyond_rounding(revenue.value, summed):
        return revenue
    return replace(revenue, note=join_notes((revenue.note, BU_NOT_SUMMED)))


def _source(
    spec: _Spec, column: Column, frame: Frame, ltm_of: Mapping[str, str]
) -> Mapping[str, Cell]:
    """The cells a line reads on the column: the LTM's for an unadjusted
    line on the PF-LTM."""
    if spec.unadjusted and column.column_id in ltm_of:
        return frame[ltm_of[column.column_id]]
    return frame[column.column_id]


def layout(
    regs: Cp1Registers,
    columns: tuple[Column, ...],
    frame: Frame,
    exclude_unrealised: bool,
    deck_as_of: str | None,
) -> tuple[Line, ...]:
    """The model's lines over `columns`, read from `frame` (`metric_frame`
    over every column): every band's lines in the layout's order, one cell
    per column. `exclude_unrealised` marks the add-backs it leaves out as
    memos; `deck_as_of` names the rate deck on the reference rate."""
    ltm_of = {
        pf.column_id: ltm.column_id
        for pf in columns
        if pf.kind == "PF_LTM"
        for ltm in columns
        if ltm.kind == "LTM" and ltm.period_id == pf.period_id
    }
    with localcontext(CONTEXT):
        lines = [
            Line(
                line_id=spec.line_id,
                band=band,
                label=spec.label,
                kind=spec.kind,
                unit=spec.unit,
                unit_label=spec.unit_label,
                rank=spec.rank,
                terms=spec.terms,
                cells=tuple(
                    _cell(spec, column, _source(spec, column, frame, ltm_of))
                    for column in columns
                ),
            )
            for band, spec in _specs(regs, columns, exclude_unrealised, deck_as_of)
        ]
        return tuple(_revenue_noted(lines, columns))

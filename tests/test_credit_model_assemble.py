"""The assembled credit model: columns in the spec's order, the worked
layout's bands and lines, its limitations, and every bridge closing."""

from __future__ import annotations

from dataclasses import replace
from decimal import Decimal, localcontext
from typing import Any

import pytest
from credit_model_fixture import (
    example_deck,
    example_growth,
    example_registers,
    example_request,
    example_slots,
    with_figures,
)
from hypothesis import example, given, settings
from hypothesis import strategies as st

from caos.calculators.credit_model._cells import CONTEXT, treated_as_zero
from caos.calculators.credit_model.assemble import (
    NO_PROJECTIONS,
    NOT_APPLIED,
    PF_NOT_SHOWN,
    CreditModel,
    ModelInputs,
    credit_model,
    reconciliation_faults,
)
from caos.calculators.credit_model.frame import Cell, Column
from caos.calculators.credit_model.history import (
    account_frame,
    historical_columns,
)
from caos.calculators.credit_model.layout import (
    BANDS,
    FacilityTerms,
    Line,
    LineKind,
    Unit,
    facility_terms,
    layout,
)
from caos.calculators.credit_model.metrics import metric_frame
from caos.calculators.credit_model.statements import statement_frame
from caos.methodology.model_inputs import Cp1Registers, PeriodRow, PfAdjustmentRow

_PF = "PF:LTM_Q2_2026"
_LTM = "LTM:LTM_Q2_2026"
_BASE = "BASE:2026"


def _inputs(
    regs: Cp1Registers | None = None,
    request: dict[str, Any] | None = None,
    *,
    projected: bool = True,
    exclude_unrealised: bool = False,
) -> ModelInputs:
    return ModelInputs(
        registers=regs or example_registers(),
        request=(request or example_request()) if projected else None,
        growth=example_growth(),
        slots=example_slots(),
        deck=example_deck(),
        exclude_unrealised=exclude_unrealised,
    )


def _model(
    regs: Cp1Registers | None = None,
    request: dict[str, Any] | None = None,
    *,
    projected: bool = True,
    exclude_unrealised: bool = False,
) -> CreditModel:
    return credit_model(
        _inputs(
            regs, request, projected=projected, exclude_unrealised=exclude_unrealised
        )
    )


def _line(model: CreditModel, line_id: str) -> Line:
    return next(line for line in model.lines if line.line_id == line_id)


def _cell(model: CreditModel, line_id: str, column_id: str) -> Cell:
    index = [c.column_id for c in model.columns].index(column_id)
    return _line(model, line_id).cells[index]


def _value(model: CreditModel, line_id: str, column_id: str) -> Decimal:
    value = _cell(model, line_id, column_id).value
    assert value is not None, (line_id, column_id)
    return value


def _with_cell(
    model: CreditModel, line_id: str, column_id: str, cell: Cell
) -> CreditModel:
    """The model with one cell replaced."""
    index = [c.column_id for c in model.columns].index(column_id)
    lines = tuple(
        replace(
            line,
            cells=tuple(
                cell if i == index and line.line_id == line_id else old
                for i, old in enumerate(line.cells)
            ),
        )
        for line in model.lines
    )
    return replace(model, lines=lines)


def _nudged(model: CreditModel, line_id: str, column_id: str) -> CreditModel:
    """The model with one cell's figure one higher."""
    cell = _cell(model, line_id, column_id)
    assert cell.value is not None, (line_id, column_id)
    return _with_cell(model, line_id, column_id, replace(cell, value=cell.value + 1))


def test_the_worked_example_reconciles_with_no_faults() -> None:
    model = _model()
    assert reconciliation_faults(model) == ()
    assert model.currency == "USD"
    assert model.unit == "MILLIONS"
    assert model.rate_deck_id == "deck-1"


# (band index, line_id, kind, unit, rank, label), the worked example's order.
_LAYOUT: tuple[tuple[int, str, LineKind, Unit, str | None, str], ...] = (
    # Operating KPIs
    (
        0,
        "kpi:lv_room_nights",
        "ACCOUNT",
        "KPI",
        None,
        "Las Vegas room nights (thousands)",
    ),
    (0, "kpi:lv_occupancy", "ACCOUNT", "KPI", None, "Las Vegas hotel occupancy"),
    (0, "kpi:rewards_members", "ACCOUNT", "KPI", None, "Rewards members, period end"),
    # Revenue by business unit
    (1, "bu:las_vegas", "ACCOUNT", "MONEY", None, "Las Vegas"),
    (1, "bu_growth:las_vegas", "GROWTH", "PERCENT", None, "Las Vegas growth YoY"),
    (1, "bu:regional", "ACCOUNT", "MONEY", None, "Regional"),
    (1, "bu_growth:regional", "GROWTH", "PERCENT", None, "Regional growth YoY"),
    (1, "bu:digital", "ACCOUNT", "MONEY", None, "Digital"),
    (1, "bu_growth:digital", "GROWTH", "PERCENT", None, "Digital growth YoY"),
    (1, "bu:managed_other", "ACCOUNT", "MONEY", None, "Managed and other"),
    (
        1,
        "bu_growth:managed_other",
        "GROWTH",
        "PERCENT",
        None,
        "Managed and other growth YoY",
    ),
    (
        1,
        "bu:corporate_eliminations",
        "ACCOUNT",
        "MONEY",
        None,
        "Corporate and eliminations",
    ),
    (1, "revenue", "SUBTOTAL", "MONEY", None, "Total revenue"),
    (1, "revenue_growth", "GROWTH", "PERCENT", None, "Total revenue growth YoY"),
    # Gross profit
    (2, "cogs", "ACCOUNT", "MONEY", None, "Cost of revenue"),
    (2, "gross_profit", "SUBTOTAL", "MONEY", None, "Gross profit"),
    (2, "metric:gross_margin", "RATIO", "PERCENT", None, "Gross margin"),
    # Operating expenses to EBITDA
    (3, "opex_ex_da", "ACCOUNT", "MONEY", None, "Operating expenses excluding D&A"),
    (3, "da", "ACCOUNT", "MONEY", None, "Depreciation and amortisation"),
    (3, "opex_total", "SUBTOTAL", "MONEY", None, "Total operating expenses"),
    (3, "ebit", "SUBTOTAL", "MONEY", None, "EBIT"),
    (3, "ebitda", "SUBTOTAL", "MONEY", None, "EBITDA"),
    (3, "metric:ebitda_margin", "RATIO", "PERCENT", None, "EBITDA margin"),
    # Adjusted EBITDA
    (
        4,
        "addback:restructuring",
        "ACCOUNT",
        "MONEY",
        None,
        "Add-back: Restructuring (realised)",
    ),
    (
        4,
        "addback:stock_based_compensation",
        "ACCOUNT",
        "MONEY",
        None,
        "Add-back: Stock-based compensation (realised)",
    ),
    (
        4,
        "addback:transaction_costs",
        "ACCOUNT",
        "MONEY",
        None,
        "Add-back: Transaction costs (realised)",
    ),
    (
        4,
        "addback:run_rate_cost_savings",
        "ACCOUNT",
        "MONEY",
        None,
        "Add-back: Run-rate cost savings (unrealised)",
    ),
    (
        4,
        "pf:silverlake_ebitda",
        "PF",
        "MONEY",
        None,
        "PF adjustment: Silverlake Resort LTM adjusted EBITDA",
    ),
    (4, "adjusted_ebitda", "SUBTOTAL", "MONEY", None, "Adjusted EBITDA"),
    (
        4,
        "metric:adjusted_ebitda_margin",
        "RATIO",
        "PERCENT",
        None,
        "Adjusted EBITDA margin",
    ),
    (
        4,
        "operating_lease_cost",
        "ACCOUNT",
        "MONEY",
        None,
        "Operating lease cost (rent)",
    ),
    (4, "adjusted_ebitdar", "SUBTOTAL", "MONEY", None, "Adjusted EBITDAR"),
    # Adjusted EBITDA to free cash flow
    (5, "cash_interest", "ACCOUNT", "MONEY", None, "Cash interest paid"),
    (
        5,
        "pf:silverlake_interest",
        "PF",
        "MONEY",
        None,
        "PF adjustment: Interest on the add-on 7.000% notes",
    ),
    (
        5,
        "lease_cash_not_in_ebitda",
        "ACCOUNT",
        "MONEY",
        None,
        "Lease cash not in EBITDA",
    ),
    (5, "cash_taxes", "ACCOUNT", "MONEY", None, "Cash taxes paid"),
    (
        5,
        "other_operating",
        "ACCOUNT",
        "MONEY",
        None,
        "Other operating cash items (residual)",
    ),
    (5, "ffo", "SUBTOTAL", "MONEY", None, "Funds from operations (FFO)"),
    (
        5,
        "working_capital_change",
        "ACCOUNT",
        "MONEY",
        None,
        "Change in working capital",
    ),
    (
        5,
        "cfo_adjusted",
        "SUBTOTAL",
        "MONEY",
        None,
        "Cash from operations, after all interest and lease cash",
    ),
    (
        5,
        "cfo_reported",
        "MEMO",
        "MONEY",
        None,
        "Memo: cash from operations as reported",
    ),
    (5, "capex", "ACCOUNT", "MONEY", None, "Capital expenditure"),
    (5, "fcf", "SUBTOTAL", "MONEY", None, "Free cash flow (FCF)"),
    # Net cash flow, cash and liquidity
    (
        6,
        "acquisitions_net",
        "ACCOUNT",
        "MONEY",
        None,
        "Acquisitions and disposals, net",
    ),
    (6, "debt_raised_net", "ACCOUNT", "MONEY", None, "Debt raised, net of repayments"),
    (
        6,
        "equity_raised_net",
        "ACCOUNT",
        "MONEY",
        None,
        "Equity raised, net of buybacks",
    ),
    (6, "dividends", "ACCOUNT", "MONEY", None, "Dividends and other distributions"),
    (
        6,
        "other_investing_financing",
        "ACCOUNT",
        "MONEY",
        None,
        "Other investing and financing",
    ),
    (6, "ncf", "SUBTOTAL", "MONEY", None, "Net cash flow (NCF)"),
    (6, "cash_opening", "ACCOUNT", "MONEY", None, "Opening cash"),
    (
        6,
        "fx_and_other_cash",
        "ACCOUNT",
        "MONEY",
        None,
        "FX and other cash movements (residual)",
    ),
    (6, "cash_closing", "SUBTOTAL", "MONEY", None, "Closing cash and equivalents"),
    (
        6,
        "pf:silverlake_cash",
        "PF",
        "MONEY",
        None,
        "PF adjustment: Cash used in the acquisition",
    ),
    (6, "undrawn_rcf", "ACCOUNT", "MONEY", None, "Undrawn RCF"),
    (6, "liquidity", "SUBTOTAL", "MONEY", None, "Liquidity"),
    # Debt stack by payment rank, period end
    (
        7,
        "fac:rcf",
        "ACCOUNT",
        "MONEY",
        "Super senior",
        "Revolving credit facility ($2,200m commitment)",
    ),
    (7, "fac:tlb", "ACCOUNT", "MONEY", "Senior secured", "Term loan B"),
    (
        7,
        "fac:ssn29",
        "ACCOUNT",
        "MONEY",
        "Senior secured",
        "6.500% senior secured notes",
    ),
    (
        7,
        "fac:ssn31",
        "ACCOUNT",
        "MONEY",
        "Senior secured",
        "7.000% senior secured notes",
    ),
    (
        7,
        "pf:silverlake_notes",
        "PF",
        "MONEY",
        "Senior secured",
        "PF adjustment: Add-on 7.000% senior secured notes",
    ),
    (
        7,
        "rank:Senior secured",
        "SUBTOTAL",
        "MONEY",
        "Senior secured",
        "Total senior secured",
    ),
    (7, "fac:sun29", "ACCOUNT", "MONEY", "Senior unsecured", "4.625% senior notes"),
    (7, "fac:sun32", "ACCOUNT", "MONEY", "Senior unsecured", "6.000% senior notes"),
    (
        7,
        "rank:Senior unsecured",
        "SUBTOTAL",
        "MONEY",
        "Senior unsecured",
        "Total senior unsecured",
    ),
    (
        7,
        "fac:sub27",
        "ACCOUNT",
        "MONEY",
        "Subordinated",
        "8.125% senior subordinated notes",
    ),
    (7, "fac:finl", "ACCOUNT", "MONEY", "Finance leases", "Finance lease liabilities"),
    (
        7,
        "fac:disc",
        "ACCOUNT",
        "MONEY",
        "Debt adjustments",
        "Unamortised discount and issuance costs",
    ),
    (
        7,
        "debt:unallocated",
        "ACCOUNT",
        "MONEY",
        None,
        "Unallocated movements (CP-CF)",
    ),
    (7, "total_debt", "SUBTOTAL", "MONEY", None, "Total debt"),
    (7, "lease_liabilities", "ACCOUNT", "MONEY", None, "Operating lease liabilities"),
    (7, "lease_adjusted_debt", "SUBTOTAL", "MONEY", None, "Lease-adjusted debt"),
    (7, "less_cash", "ACCOUNT", "MONEY", None, "Less: cash and equivalents"),
    (7, "net_debt", "SUBTOTAL", "MONEY", None, "Net debt"),
    (
        7,
        "lease_adjusted_net_debt",
        "SUBTOTAL",
        "MONEY",
        None,
        "Lease-adjusted net debt",
    ),
    # Debt roll-forward
    (8, "debt_opening", "ACCOUNT", "MONEY", None, "Opening total debt"),
    (
        8,
        "rollforward:debt_raised_net",
        "ACCOUNT",
        "MONEY",
        None,
        "Debt raised, net of repayments",
    ),
    (
        8,
        "debt_non_cash",
        "ACCOUNT",
        "MONEY",
        None,
        "Non-cash and lease movements (residual)",
    ),
    (
        8,
        "rollforward:pf:silverlake_notes",
        "PF",
        "MONEY",
        None,
        "PF adjustment: Add-on 7.000% senior secured notes",
    ),
    (8, "debt_closing", "SUBTOTAL", "MONEY", None, "Closing total debt"),
    # Interest calculation, projections
    (
        9,
        "reference_rate",
        "ACCOUNT",
        "RATE",
        None,
        "Reference rate, rate deck 2026-10-01",
    ),
    (
        9,
        "interest_bearing_debt_opening",
        "ACCOUNT",
        "MONEY",
        None,
        "Interest-bearing debt, opening",
    ),
    (9, "wa_rate", "RATIO", "RATE", None, "Weighted average all-in rate"),
    # Working capital, period end
    (10, "accounts_receivable", "ACCOUNT", "MONEY", None, "Accounts receivable"),
    (10, "inventory", "ACCOUNT", "MONEY", None, "Inventory"),
    (10, "accounts_payable", "ACCOUNT", "MONEY", None, "Accounts payable"),
    (10, "dso", "RATIO", "DAYS", None, "DSO"),
    (10, "dio", "RATIO", "DAYS", None, "DIO"),
    (10, "dpo", "RATIO", "DAYS", None, "DPO"),
    (10, "ccc", "RATIO", "DAYS", None, "Cash conversion cycle"),
    # Credit metrics (leverage and coverage on 12-month EBITDA)
    (
        11,
        "metric:total_leverage_reported",
        "RATIO",
        "MULTIPLE",
        None,
        "Total leverage, reported EBITDA",
    ),
    (
        11,
        "metric:total_leverage_adjusted",
        "RATIO",
        "MULTIPLE",
        None,
        "Total leverage, adjusted EBITDA",
    ),
    (
        11,
        "metric:net_leverage_reported",
        "RATIO",
        "MULTIPLE",
        None,
        "Net leverage, reported EBITDA",
    ),
    (
        11,
        "metric:net_leverage_adjusted",
        "RATIO",
        "MULTIPLE",
        None,
        "Net leverage, adjusted EBITDA",
    ),
    (
        11,
        "metric:senior_secured_leverage",
        "RATIO",
        "MULTIPLE",
        None,
        "Senior secured leverage, adjusted EBITDA",
    ),
    (
        11,
        "metric:senior_secured_net_leverage",
        "RATIO",
        "MULTIPLE",
        None,
        "Senior secured net leverage, adjusted EBITDA",
    ),
    (
        11,
        "metric:lease_adjusted_leverage",
        "RATIO",
        "MULTIPLE",
        None,
        "Lease-adjusted leverage, adjusted EBITDAR",
    ),
    (
        11,
        "metric:lease_adjusted_net_leverage",
        "RATIO",
        "MULTIPLE",
        None,
        "Lease-adjusted net leverage, adjusted EBITDAR",
    ),
    (
        11,
        "metric:interest_coverage_reported",
        "RATIO",
        "MULTIPLE",
        None,
        "EBITDA / cash interest, reported",
    ),
    (
        11,
        "metric:interest_coverage_adjusted",
        "RATIO",
        "MULTIPLE",
        None,
        "Adjusted EBITDA / cash interest",
    ),
    (
        11,
        "metric:capex_adjusted_coverage",
        "RATIO",
        "MULTIPLE",
        None,
        "(Adjusted EBITDA - capex) / cash interest",
    ),
    (
        11,
        "metric:ebitdar_coverage",
        "RATIO",
        "MULTIPLE",
        None,
        "(Adjusted EBITDAR - capex) / (cash interest + rent)",
    ),
    (11, "metric:ffo_to_debt", "RATIO", "PERCENT", None, "FFO / total debt"),
    (
        11,
        "metric:ffo_to_lease_adjusted_debt",
        "RATIO",
        "PERCENT",
        None,
        "FFO / lease-adjusted debt",
    ),
    (11, "metric:fcf_to_debt", "RATIO", "PERCENT", None, "FCF / total debt"),
    (
        11,
        "metric:fcf_to_adjusted_ebitda",
        "RATIO",
        "PERCENT",
        None,
        "FCF / adjusted EBITDA",
    ),
    (11, "metric:capex_to_revenue", "RATIO", "PERCENT", None, "Capex / revenue"),
    (
        11,
        "metric:liquidity_to_debt",
        "RATIO",
        "PERCENT",
        None,
        "Liquidity / total debt",
    ),
    (
        11,
        "adjusted_ebitda_growth",
        "GROWTH",
        "PERCENT",
        None,
        "Adjusted EBITDA growth YoY",
    ),
)


def test_band_and_line_order_matches_the_layout() -> None:
    model = _model()
    assert [
        (
            BANDS.index(line.band),
            line.line_id,
            line.kind,
            line.unit,
            line.rank,
            line.label,
        )
        for line in model.lines
    ] == list(_LAYOUT)
    assert [line.band for line in model.lines] == sorted(
        (line.band for line in model.lines), key=BANDS.index
    )
    assert {line.band for line in model.lines} == set(BANDS)
    assert all(len(line.cells) == len(model.columns) for line in model.lines)
    kpis = {line.line_id: line.unit_label for line in model.lines if line.unit == "KPI"}
    assert kpis == {
        "kpi:lv_room_nights": "THOUSANDS",
        "kpi:lv_occupancy": "PERCENT",
        "kpi:rewards_members": "MILLIONS",
    }
    assert all(line.unit_label is None for line in model.lines if line.unit != "KPI")


def test_columns_run_history_pf_then_base_years_then_downside_years() -> None:
    request = example_request()
    request["periods"] = sorted(request["periods"], key=lambda p: p["case"] == "BASE")
    model = _model(request=request)
    assert [c.column_id for c in model.columns] == [
        *(f"Q:Q{q}_{y}" for y in (2024, 2025) for q in (1, 2, 3, 4)),
        "Q:Q1_2026",
        "Q:Q2_2026",
        "PYTD:H1_2025",
        "YTD:H1_2026",
        "FY:FY2023",
        "FY:FY2024",
        "FY:FY2025",
        _LTM,
        _PF,
        "BASE:2026",
        "BASE:2027",
        "BASE:2028",
        "DOWNSIDE:2026",
        "DOWNSIDE:2027",
        "DOWNSIDE:2028",
    ]


def test_a_rank_with_one_facility_has_no_subtotal() -> None:
    model = _model()
    subtotals = [
        line.line_id for line in model.lines if line.line_id.startswith("rank:")
    ]
    assert subtotals == ["rank:Senior secured", "rank:Senior unsecured"]
    regs = example_registers()
    regs = replace(
        regs, facilities=tuple(f for f in regs.facilities if f.facility_id != "sun32")
    )
    model = _model(regs=regs)
    subtotals = [
        line.line_id for line in model.lines if line.line_id.startswith("rank:")
    ]
    assert subtotals == ["rank:Senior secured"]
    assert reconciliation_faults(model) == ()


def test_a_rank_subtotal_sums_its_facilities_on_every_column() -> None:
    model = _model()
    for column in model.columns:
        if column.kind in ("PROJECTED", "PF_LTM"):
            continue
        secured = sum(
            _value(model, key, column.column_id)
            for key in ("fac:tlb", "fac:ssn29", "fac:ssn31")
        )
        assert _value(model, "rank:Senior secured", column.column_id) == secured
    assert _value(model, "rank:Senior secured", _PF) == 2316 + 2000 + 1600
    assert _value(model, "rank:Senior secured", _BASE) == (2328 - 24) + 2000 + 1000
    assert _cell(model, "rank:Senior secured", _LTM).basis == "CALCULATED"


def test_a_run_without_cp_cf_has_no_projection_columns() -> None:
    model = _model(projected=False)
    assert all(column.kind != "PROJECTED" for column in model.columns)
    assert model.columns[-1].column_id == _PF
    assert model.limitations[0] == NO_PROJECTIONS
    assert model.rate_deck_id is None
    assert _line(model, "reference_rate").label == "Reference rate"
    for key in ("reference_rate", "interest_bearing_debt_opening", "wa_rate"):
        assert {cell.reason for cell in _line(model, key).cells} == {"NOT_APPLICABLE"}
    assert reconciliation_faults(model) == ()
    assert NO_PROJECTIONS not in _model().limitations


def test_limitations_list_each_note_once() -> None:
    model = _model()
    notes = [text.split(": ")[0] for text in model.limitations]
    assert len(notes) == len(set(notes))
    for note in {cell.note for line in model.lines for cell in line.cells} - {None}:
        assert note in notes
    on = dict(text.split(": ", 1) for text in model.limitations)
    assert on["assumed refinanced"] == "BASE:2027, DOWNSIDE:2027"
    assert on["residual"].split(", ")[0] == "Q:Q1_2024"
    # On the PF-LTM only the roll-forward's residual, the LTM's, is shown.
    assert _PF in on["residual"].split(", ")
    residuals = [
        line.line_id for line in model.lines if _cell(model, line.line_id, _PF).note
    ]
    assert residuals == ["debt_non_cash"]
    assert len(model.limitations) == len(notes)


@pytest.mark.parametrize("addback", ["addback:run_rate_cost_savings"])
def test_exclude_unrealised_drops_unrealised_addbacks_from_adjusted_ebitda_everywhere(
    addback: str,
) -> None:
    included = _model()
    excluded = _model(exclude_unrealised=True)
    assert _line(included, addback).kind == "ACCOUNT"
    assert _line(excluded, addback).kind == "MEMO"
    assert _line(excluded, addback).label == (
        "Add-back: Run-rate cost savings (unrealised), excluded"
    )
    dropped = 0
    for column in excluded.columns:
        if column.kind == "PROJECTED":
            assert _cell(excluded, "adjusted_ebitda", column.column_id) == _cell(
                included, "adjusted_ebitda", column.column_id
            )
            continue
        savings = _value(included, addback, column.column_id)
        dropped += savings != 0
        assert _value(excluded, "adjusted_ebitda", column.column_id) == (
            _value(included, "adjusted_ebitda", column.column_id) - savings
        )
    assert dropped > 0
    # The quarters' leverage reads the LTM ending them, dropped there too.
    with localcontext(CONTEXT):
        leverage = _value(excluded, "total_debt", "Q:Q2_2026") / Decimal(4089 - 40)
    assert _value(excluded, "metric:total_leverage_adjusted", "Q:Q2_2026") == leverage
    assert reconciliation_faults(excluded) == ()
    assert any(text.startswith("excluded: ") for text in excluded.limitations)


_BRIDGES = (
    ("ebitda", "FY:FY2024", "ebitda"),
    ("ebit", _LTM, "ebitda"),
    ("adjusted_ebitda", "YTD:H1_2026", "adjusted_ebitda"),
    ("addback:restructuring", _PF, "adjusted_ebitda"),
    ("pf:silverlake_ebitda", _PF, "adjusted_ebitda"),
    ("ffo", "Q:Q3_2025", "ffo"),
    ("lease_cash_not_in_ebitda", "FY:FY2025", "ffo"),
    ("cfo_adjusted", "PYTD:H1_2025", "cfo"),
    ("fcf", _BASE, "fcf"),
    ("capex", "Q:Q2_2024", "fcf"),
    ("ncf", "DOWNSIDE:2027", "ncf"),
    ("other_investing_financing", "FY:FY2023", "ncf"),
    ("cash_closing", "BASE:2028", "cash"),
    ("fx_and_other_cash", "Q:Q4_2025", "cash"),
    ("liquidity", _PF, "liquidity"),
    ("undrawn_rcf", "DOWNSIDE:2026", "liquidity"),
    ("rank:Senior secured", "Q:Q1_2026", "rank:Senior secured"),
    ("fac:sun32", "Q:Q1_2026", "rank:Senior unsecured"),
    ("total_debt", _PF, "total_debt"),
    ("total_debt", _BASE, "total_debt"),
    ("debt:unallocated", "DOWNSIDE:2028", "total_debt"),
    ("pf:silverlake_notes", _PF, "rank:Senior secured"),
    ("pf:silverlake_cash", _PF, "liquidity"),
    ("fac:sub27", "FY:FY2025", "total_debt"),
    ("debt_closing", "BASE:2027", "debt_rollforward"),
    ("debt_opening", "Q:Q2_2026", "debt_rollforward"),
    ("rollforward:debt_raised_net", "Q:Q2_2026", "debt_rollforward"),
    ("cash_interest", "DOWNSIDE:2028", "interest"),
    ("wa_rate", _BASE, "interest"),
)


@pytest.mark.parametrize(("line_id", "column_id", "bridge"), _BRIDGES)
def test_each_bridge_reports_a_figure_that_breaks_it(
    line_id: str, column_id: str, bridge: str
) -> None:
    faults = reconciliation_faults(_nudged(_model(), line_id, column_id))
    assert f"{column_id}:{bridge}" in faults


def test_a_fault_names_only_the_bridges_the_figure_is_in() -> None:
    faults = reconciliation_faults(_nudged(_model(), "da", "Q:Q1_2024"))
    assert faults == ("Q:Q1_2024:ebitda",)
    faults = reconciliation_faults(_nudged(_model(), "fcf", "Q:Q1_2024"))
    assert faults == ("Q:Q1_2024:fcf", "Q:Q1_2024:ncf")


def test_a_bridge_with_a_line_without_a_figure_is_not_checked() -> None:
    model = _nudged(_model(), "ebitda", "FY:FY2024")
    unchecked = _with_cell(model, "ebit", "FY:FY2024", Cell(None, "NOT_STATED"))
    assert "FY:FY2024:ebitda" not in reconciliation_faults(unchecked)
    missing = _with_cell(
        model, "addback:restructuring", "FY:FY2024", Cell(None, "COMPONENT_MISSING")
    )
    assert "FY:FY2024:adjusted_ebitda" not in reconciliation_faults(missing)
    absent = _with_cell(
        _model(), "addback:restructuring", "FY:FY2024", Cell(None, "NOT_SOURCED")
    )
    assert reconciliation_faults(absent) == ("FY:FY2024:adjusted_ebitda",)
    total = _with_cell(model, "ebitda", "FY:FY2024", Cell(None, "NOT_STATED"))
    assert "FY:FY2024:ebitda" not in reconciliation_faults(total)
    rate = _with_cell(
        _nudged(_model(), "cash_interest", _BASE),
        "wa_rate",
        _BASE,
        Cell(None, "COMPONENT_MISSING"),
    )
    assert f"{_BASE}:interest" not in reconciliation_faults(rate)
    base = _with_cell(
        _nudged(_model(), "cash_interest", _BASE),
        "interest_bearing_debt_opening",
        _BASE,
        Cell(None, "COMPONENT_MISSING"),
    )
    assert f"{_BASE}:interest" not in reconciliation_faults(base)


def test_projected_stack_foots_through_unallocated_movements() -> None:
    model = _model()
    line = _line(model, "debt:unallocated")
    assert (line.label, line.kind, line.rank) == (
        "Unallocated movements (CP-CF)",
        "ACCOUNT",
        None,
    )
    ids = [line.line_id for line in model.lines]
    assert ids.index("debt:unallocated") + 1 == ids.index("total_debt")
    for column in model.columns:
        cell = _cell(model, "debt:unallocated", column.column_id)
        if column.kind != "PROJECTED":
            assert cell.reason == "NOT_APPLICABLE"
            continue
        facilities = sum(
            _value(model, line.line_id, column.column_id)
            for line in model.lines
            if line.line_id.startswith("fac:") and line.kind == "ACCOUNT"
        )
        with localcontext(CONTEXT):
            unallocated = _value(model, "total_debt", column.column_id) - facilities
        assert cell.value == unallocated
        assert cell.basis == "CALCULATED"
    # Base sweeps 822 of cash to optional repayment in FY2026.
    assert _value(model, "debt:unallocated", _BASE) == -822
    assert reconciliation_faults(model) == ()
    regs = example_registers()
    regs = replace(
        regs,
        facilities=tuple(
            replace(f, carrying_value=None)
            if f.facility_id == "sun29" and f.period_id in {"Q4_2025", "FY2025"}
            else f
            for f in regs.facilities
        ),
    )
    missing = _model(regs=regs)
    assert _cell(missing, "debt:unallocated", _BASE).reason == "COMPONENT_MISSING"


def test_pf_ltm_accounts_show_the_ltm_with_pf_rows_beneath() -> None:
    model = _model()
    for key in ("fac:ssn31", "cash_interest", "cash_closing", "fac:tlb"):
        assert _cell(model, key, _PF) == _cell(model, key, _LTM), key
    assert _value(model, "fac:ssn31", _PF) == 1000
    assert _value(model, "pf:silverlake_notes", _PF) == 600
    assert _value(model, "rank:Senior secured", _PF) == 2316 + 2000 + 1600
    assert _value(model, "total_debt", _PF) == (_value(model, "total_debt", _LTM) + 600)
    assert _value(model, "cash_closing", _PF) == 1000
    assert _value(model, "liquidity", _PF) == 950 + 2200
    assert _value(model, "less_cash", _PF) == -950
    assert _value(model, "adjusted_ebitda", _PF) == (
        _value(model, "adjusted_ebitda", _LTM) + 45
    )
    assert _value(model, "cash_interest", _PF) == -862
    assert reconciliation_faults(model) == ()


def test_business_units_that_do_not_sum_to_revenue_are_noted() -> None:
    regs = example_registers()
    regs = replace(
        regs,
        segments=tuple(
            replace(s, revenue=Decimal(3000))
            if s.segment_id == "digital" and s.period_id == "Q1_2024"
            else s
            for s in regs.segments
        ),
    )
    model = _model(regs=regs)
    note = "business units do not sum to revenue"
    assert _cell(model, "revenue", "Q:Q1_2024").note == note
    assert _cell(model, "revenue", "FY:FY2024").note is None
    assert f"{note}: Q:Q1_2024" in model.limitations
    assert reconciliation_faults(model) == ()
    assert all(cell.note != note for cell in _line(_model(), "revenue").cells)
    rounded = replace(
        regs,
        segments=tuple(
            replace(s, revenue=Decimal("270.4"))
            if s.segment_id == "digital" and s.period_id == "Q1_2024"
            else s
            for s in example_registers().segments
        ),
    )
    assert _cell(_model(regs=rounded), "revenue", "Q:Q1_2024").note is None


def test_a_note_on_revenue_keeps_cp1s_own() -> None:
    regs = example_registers()
    regs = replace(
        regs,
        accounts=tuple(
            replace(a, value=Decimal(5000))
            if a.metric_id == "revenue" and a.period_id == "H1_2026"
            else a
            for a in regs.accounts
        ),
        segments=tuple(
            replace(s, revenue=Decimal(1))
            if s.segment_id == "digital" and s.period_id == "Q1_2026"
            else s
            for s in regs.segments
        ),
    )
    cell = _cell(_model(regs=regs), "revenue", "YTD:H1_2026")
    assert cell.note == (
        "differs from CP-1 stated; business units do not sum to revenue"
    )


def test_cells_a_column_has_not_say_why() -> None:
    model = _model()
    assert _cell(model, "kpi:lv_occupancy", _BASE).reason == "NOT_PROJECTED"
    assert _cell(model, "cogs", _BASE).reason == "NOT_PROJECTED"
    assert _cell(model, "wa_rate", _LTM).reason == "NOT_APPLICABLE"
    assert _cell(model, "reference_rate", "Q:Q1_2024").reason == "NOT_APPLICABLE"
    assert _cell(model, "pf:silverlake_cash", _LTM).reason == "NOT_APPLICABLE"
    assert _cell(model, "pf:silverlake_cash", _BASE).reason == "NOT_APPLICABLE"
    assert _value(model, "pf:silverlake_cash", _PF) == -50
    regs = example_registers()
    regs = replace(regs, kpis=tuple(k for k in regs.kpis if k.period_id != "FY2023"))
    assert _cell(_model(regs=regs), "kpi:lv_occupancy", "FY:FY2023").reason == (
        "NOT_SOURCED"
    )
    assert _cell(model, "rank:Senior secured", _LTM).value is not None


def test_a_rank_subtotal_without_any_facility_at_a_date_says_why() -> None:
    regs = example_registers()
    regs = replace(
        regs,
        facilities=tuple(
            f
            for f in regs.facilities
            if not (f.facility_id in {"sun29", "sun32"} and f.period_id == "FY2023")
        ),
    )
    model = _model(regs=regs)
    assert _cell(model, "rank:Senior unsecured", "FY:FY2023").reason == "NOT_SOURCED"
    assert _value(model, "rank:Senior unsecured", "FY:FY2024") == 7100
    projected = Column(_BASE, "PROJECTED", "FY26E", "FY2026", "2026", None, 365, "BASE")
    lines = layout(regs, (projected,), {_BASE: {}}, False, None)
    subtotal = next(line for line in lines if line.line_id == "rank:Senior unsecured")
    assert subtotal.cells == (Cell(None, "NOT_PROJECTED"),)


def test_less_cash_is_closing_cash_negated() -> None:
    model = _model()
    for column in model.columns:
        if column.kind == "PF_LTM":
            continue  # closing cash shows the LTM's there, its PF row beneath
        cash = _cell(model, "cash_closing", column.column_id)
        less = _cell(model, "less_cash", column.column_id)
        assert cash.value is not None
        with localcontext(CONTEXT):
            assert less == replace(cash, value=-cash.value)
    assert _value(model, "less_cash", _PF) == -950
    regs = example_registers()
    stated = Decimal("1000")
    cash = replace(
        _cell(model, "cash_closing", _LTM), value=Decimal(1000), stated=stated
    )
    assert cash.stated == stated
    columns = historical_columns(regs)
    frame = statement_frame(account_frame(regs, columns), columns, regs)
    frame[_LTM]["cash_closing"] = cash
    metrics = metric_frame(columns, frame, {k: frame[k] for k in frame})
    lines = layout(regs, columns, metrics, False, None)
    index = [c.column_id for c in columns].index(_LTM)
    less = next(line for line in lines if line.line_id == "less_cash").cells[index]
    assert (less.value, less.stated) == (Decimal(-1000), Decimal(-1000))


def test_facility_terms_are_shown_as_stated_never_rounded() -> None:
    model = _model()
    assert _line(model, "fac:rcf").terms == FacilityTerms(
        "SOFR", "+225 bp", "none", "2030-01-31", "bullet"
    )
    assert _line(model, "fac:tlb").terms == FacilityTerms(
        "SOFR", "+275 bp", "0.50%", "2030-02-28", "24 p.a."
    )
    assert _line(model, "fac:ssn29").terms == FacilityTerms(
        "none", "6.500%", "n.a.", "2029-02-15", "bullet"
    )
    assert _line(model, "fac:finl").terms == FacilityTerms(
        "not stated", "not stated", "n.a.", "not stated", "not stated"
    )
    assert _line(model, "revenue").terms is None
    row = next(f for f in example_registers().facilities if f.facility_id == "tlb")
    odd = replace(
        row,
        reference_rate="TERM_SOFR",
        spread_bps=Decimal("262.5"),
        floor_bps=Decimal("12.5"),
        annual_amortisation=Decimal("0.0001"),
    )
    assert facility_terms(odd) == FacilityTerms(
        "Term SOFR", "+262.5 bp", "0.125%", "2030-02-28", "0.0001 p.a."
    )
    assert (
        facility_terms(replace(odd, reference_rate="LIBOR")).reference_rate == "LIBOR"
    )
    assert (
        facility_terms(replace(odd, spread_bps=None)).spread_or_coupon == "not stated"
    )
    assert facility_terms(replace(odd, rate_type="FIXED")).spread_or_coupon == (
        "not stated"
    )
    fixed = replace(odd, rate_type="FIXED", fixed_rate=Decimal("7.125"), floor_bps=None)
    assert (facility_terms(fixed).spread_or_coupon, facility_terms(fixed).floor) == (
        "7.125%",
        "n.a.",
    )
    assert (
        facility_terms(replace(odd, rate_type="NOT_STATED", floor_bps=None)).floor
        == "n.a."
    )
    assert (
        facility_terms(
            replace(odd, rate_type="FIXED", fixed_rate=Decimal("1E+1"))
        ).spread_or_coupon
        == "10%"
    )


def test_every_metric_in_the_frame_has_one_line() -> None:
    model = _model()
    ids = [line.line_id for line in model.lines]
    assert len(ids) == len(set(ids))
    regs = example_registers()
    columns = historical_columns(regs)
    frame = statement_frame(account_frame(regs, columns), columns, regs)
    ltm_ending = {c.column_id: frame[c.column_id] for c in columns}
    keys = metric_frame(columns, frame, ltm_ending)[_LTM]
    metrics = {
        k
        for k in keys
        if k.startswith(("metric:", "bu_growth:")) or k.endswith("_growth")
    }
    assert metrics - set(ids) == {"bu_growth:corporate_eliminations"}


def test_a_foreign_facility_is_a_memo_outside_its_rank_total() -> None:
    regs = example_registers()
    regs = replace(
        regs,
        facilities=tuple(
            replace(f, currency="EUR") if f.facility_id == "ssn29" else f
            for f in regs.facilities
        ),
    )
    regs = replace(
        regs, pro_forma=(*regs.pro_forma, _adjustment("eur", "facility:ssn29", 70))
    )
    model = _model(regs=regs)
    assert _line(model, "fac:ssn29").kind == "MEMO"
    assert _value(model, "pf:eur", _PF) == 70
    assert _line(model, "fac:ssn29").rank == "Senior secured"
    assert _value(model, "rank:Senior secured", _LTM) == 2316 + 1000
    assert _value(model, "rank:Senior secured", _PF) == 2316 + 1600
    assert reconciliation_faults(model) == ()
    one = replace(
        regs,
        facilities=tuple(
            replace(f, currency="EUR") if f.facility_id == "ssn31" else f
            for f in regs.facilities
        ),
    )
    assert "rank:Senior secured" not in {
        line.line_id for line in _model(regs=one).lines
    }


def _adjustment(adjustment_id: str, metric_id: str, value: int) -> PfAdjustmentRow:
    return PfAdjustmentRow(
        adjustment_id=adjustment_id,
        label=f"{adjustment_id} label",
        period_id="LTM_Q2_2026",
        classification="ACQUISITION",
        metric_id=metric_id,
        value=Decimal(value),
        source=None,
    )


def test_pf_rows_sit_by_the_line_they_adjust_and_reconcile() -> None:
    regs = example_registers()
    leases = tuple(
        replace(
            f,
            facility_id="opl",
            facility_name="Operating leases",
            lease_classification="OPERATING_LEASE",
        )
        for f in regs.facilities
        if f.facility_id == "finl"
    )
    regs = replace(
        regs,
        # Left out or placed nowhere first, so the rest are still read.
        facilities=(*leases, *regs.facilities),
        pro_forma=(
            replace(_adjustment("old", "revenue", 1), period_id="FY2025"),
            _adjustment("capex", "capex_and_intangible_investment", -5),
            *regs.pro_forma,
            _adjustment("rev", "revenue", 70),
            _adjustment("ebitda_pf", "ebitda", 20),
            _adjustment("new_loan", "facility:new_loan", 300),
            _adjustment("debt", "total_debt", 15),
            _adjustment("lease", "facility:opl", 9),
        ),
    )
    model = _model(regs=regs)
    ids = [line.line_id for line in model.lines]

    def before(first: str, second: str) -> bool:
        return ids.index(first) + 1 == ids.index(second)

    assert before("pf:rev", "revenue")
    assert before("pf:ebitda_pf", "ebitda")
    assert before("fac:disc", "debt:unallocated")
    assert before("debt:unallocated", "pf:new_loan")
    assert before("pf:new_loan", "pf:debt")
    assert before("pf:debt", "total_debt")
    assert before("lease_liabilities", "pf:lease")
    assert "fac:opl" not in ids
    assert _cell(model, "lease_liabilities", _PF) == _cell(
        model, "lease_liabilities", _LTM
    )
    assert _value(model, "lease_adjusted_debt", _PF) == (
        _value(model, "total_debt", _PF) + 260 + 9
    )
    assert "pf:capex" not in ids
    assert "pf:old" not in ids
    assert _line(model, "pf:new_loan").rank is None
    assert _line(model, "pf:silverlake_notes").rank == "Senior secured"
    assert [i for i in ids if i.startswith("rollforward:pf:")] == [
        "rollforward:pf:silverlake_notes",
        "rollforward:pf:new_loan",
        "rollforward:pf:debt",
    ]
    assert _value(model, "total_debt", _PF) == _value(model, "total_debt", _LTM) + 915
    assert reconciliation_faults(model) == ()
    assert f"{NOT_APPLIED}: capex label" in model.limitations
    assert not any("old label" in text for text in model.limitations)
    broken = _nudged(model, "pf:new_loan", _PF)
    assert reconciliation_faults(broken) == (f"{_PF}:total_debt",)
    assert _cell(model, "revenue", _PF).note is None
    broken = _nudged(model, "pf:ebitda_pf", _PF)
    assert reconciliation_faults(broken) == (f"{_PF}:ebitda",)
    broken = _nudged(model, "pf:lease", _PF)
    assert reconciliation_faults(broken) == ()


def test_a_model_without_segments_notes_nothing_on_revenue() -> None:
    regs = replace(example_registers(), segments=())
    model = _model(regs=regs, projected=False)
    assert not any(line.line_id.startswith("bu") for line in model.lines)
    assert all(cell.note is None for cell in _line(model, "revenue").cells)
    broken = _nudged(model, "revenue", "FY:FY2024")
    assert reconciliation_faults(broken) == ()


def _figures(low: int = -30000) -> st.SearchStrategy[Decimal | None]:
    """A figure in tenths up to 3,000.0, from `low` tenths; about one in 33
    has none, and a zero is written "(0)" (negative zero) half the time.
    Hypothesis shrinks it."""
    return st.tuples(
        st.integers(min_value=0, max_value=32),
        st.integers(min_value=low, max_value=30000),
    ).map(_figure)


def _figure(drawn: tuple[int, int]) -> Decimal | None:
    flag, tenths = drawn
    if flag == 0:
        return None
    return Decimal("-0") if tenths == 0 and flag % 2 else Decimal(tenths) / 10


_STATUSES = st.sampled_from(("REALIZED", "UNREALIZED", "NOT_STATED"))


@st.composite
def _registers(draw: st.DrawFn) -> Cp1Registers:
    """The example's registers with every figure redrawn; each period's
    revenue is its business units' sum, as CP-1's segment check requires."""
    regs = example_registers()
    segments = tuple(replace(s, revenue=draw(_figures(0))) for s in regs.segments)
    sums: dict[str, Decimal | None] = {}
    for segment in segments:
        held = sums.get(segment.period_id, Decimal(0))
        sums[segment.period_id] = (
            None if held is None or segment.revenue is None else held + segment.revenue
        )
    accounts = tuple(
        replace(
            a,
            value=sums.get(a.period_id)
            if a.metric_id == "revenue"
            else draw(_figures()),
        )
        for a in regs.accounts
    )
    addbacks = tuple(
        replace(a, value=draw(_figures()), realization_status=draw(_STATUSES))
        for a in regs.addbacks
    )
    facilities = tuple(
        replace(f, carrying_value=draw(_figures(-2000))) for f in regs.facilities
    )
    pro_forma = tuple(
        replace(p, value=draw(_figures()) or Decimal(1)) for p in regs.pro_forma
    )
    return replace(
        regs,
        segments=segments,
        accounts=accounts,
        addbacks=addbacks,
        facilities=facilities,
        pro_forma=pro_forma,
    )


@st.composite
def _requests(draw: st.DrawFn) -> dict[str, Any]:
    """CP-CF's example request with every driver redrawn."""
    request = example_request()
    flows = st.integers(min_value=0, max_value=9000).map(str)
    debt = st.integers(min_value=0, max_value=900).map(str)
    for driver in request["drivers"]:
        for name in (
            "revenue",
            "ebitda",
            "cfo",
            "capex",
            "cash_taxes",
            "distributions",
        ):
            driver[name] = draw(flows)
        driver["optional_repayment"] = draw(debt)
        driver["issuance"] = draw(debt)
    return request


@settings(max_examples=40, deadline=None)
@given(regs=_registers(), request=_requests(), exclude=st.booleans())
# Hypothesis's find: a year-end cash of "(0)" opened the next periods at -0.
@example(
    regs=with_figures(
        example_registers(), "FY2023", {"cash_and_equivalents": Decimal("-0")}
    ),
    request=example_request(),
    exclude=False,
)
def test_any_consistent_inputs_reconcile(
    regs: Cp1Registers, request: dict[str, Any], exclude: bool
) -> None:
    model = _model(regs=regs, request=request, exclude_unrealised=exclude)
    assert reconciliation_faults(model) == ()
    assert _signed_zeros(model) == []


def test_growth_lines_read_their_growth() -> None:
    model = _model()
    with localcontext(CONTEXT):
        revenue = Decimal(11519) / Decimal(11165) - 1
        adjusted = Decimal(4019) / Decimal(3872) - 1
    assert _value(model, "revenue_growth", "FY:FY2025") == revenue
    assert _value(model, "adjusted_ebitda_growth", "FY:FY2025") == adjusted


def test_an_add_back_with_another_realisation_status_shows_it() -> None:
    regs = example_registers()
    regs = replace(
        regs,
        addbacks=tuple(
            replace(a, realization_status="PARTIAL")
            if a.addback_id == "restructuring"
            else a
            for a in regs.addbacks
        ),
    )
    line = _line(_model(regs=regs, exclude_unrealised=True), "addback:restructuring")
    assert (line.label, line.kind) == ("Add-back: Restructuring (PARTIAL)", "ACCOUNT")


def test_projected_interest_reads_the_rate_deck() -> None:
    model = _model()
    assert _cell(model, "reference_rate", _BASE).value == Decimal("0.0380")
    assert _cell(model, "reference_rate", "DOWNSIDE:2026").value == Decimal("0.0480")


def test_registers_without_periods_give_a_model_without_columns() -> None:
    regs = replace(example_registers(), periods=())
    model = _model(regs=regs, projected=False)
    assert model.columns == ()
    assert all(line.cells == () for line in model.lines)
    # CP-1's PF rows have no column to go on, and say so.
    assert model.limitations == (
        NO_PROJECTIONS,
        f"{PF_NOT_SHOWN}: LTM_Q2_2026 (4 adjustments)",
    )
    assert reconciliation_faults(model) == ()


def test_debt_bridges_count_a_facility_absent_at_a_date_as_nothing() -> None:
    regs = example_registers()
    regs = replace(
        regs,
        facilities=tuple(
            f
            for f in regs.facilities
            if not (f.facility_id == "sun29" and f.period_id in {"Q4_2024", "FY2024"})
        ),
    )
    model = _model(regs=regs)
    assert _cell(model, "fac:sun29", "FY:FY2024").reason == "NOT_SOURCED"
    assert _value(model, "rank:Senior unsecured", "FY:FY2024") == 3500
    assert reconciliation_faults(model) == ()
    for line_id, bridge in (
        ("rank:Senior unsecured", "rank:Senior unsecured"),
        ("total_debt", "total_debt"),
    ):
        faults = reconciliation_faults(_nudged(model, line_id, "FY:FY2024"))
        assert f"FY:FY2024:{bridge}" in faults


def test_the_roll_forward_adds_its_pf_rows() -> None:
    model = _model()
    stray = _with_cell(model, "rollforward:pf:silverlake_notes", _LTM, Cell(Decimal(1)))
    assert reconciliation_faults(stray) == (f"{_LTM}:debt_rollforward",)


def test_a_period_without_revenue_notes_nothing() -> None:
    regs = example_registers()
    regs = replace(
        regs,
        accounts=tuple(
            replace(a, value=None)
            if a.metric_id == "revenue" and a.period_id == "Q1_2024"
            else a
            for a in regs.accounts
        ),
    )
    cell = _cell(_model(regs=regs), "revenue", "Q:Q1_2024")
    assert (cell.value, cell.note) == (None, None)


# Fix wave B (the adversary audit of b64facb7) and the Task 7 minors.

_BU_NOT_SUMMED = "business units do not sum to revenue"
_EXCLUDES_FOREIGN = "excludes facility in another currency"
_EXCLUDES_UNALLOCATED = "excludes unallocated CP-CF movements"
_DOUBLE_COUNT = (
    "PF register states both ebitda and adjusted_ebitda adjustments; "
    "check for double counting"
)


def _on(model: CreditModel) -> dict[str, str]:
    """Each limitation's note and the columns it is on."""
    return dict(text.split(": ", 1) for text in model.limitations if ": " in text)


def test_projected_metrics_read_cp_cf_revenue_not_a_partial_segment_sum() -> None:
    regs = example_registers()
    partial = replace(
        regs,
        segments=tuple(
            s for s in regs.segments if s.segment_id in {"las_vegas", "regional"}
        ),
    )
    model = _model(regs=partial)

    revenue = _cell(model, "revenue", _BASE)
    assert (revenue.value, revenue.basis) == (Decimal(11809), "DRIVER")
    assert revenue.note == _BU_NOT_SUMMED
    with localcontext(CONTEXT):
        assert _value(model, "metric:capex_to_revenue", _BASE) == Decimal(
            1700
        ) / Decimal(11809)
        assert _value(model, "metric:adjusted_ebitda_margin", _BASE) == Decimal(
            4136
        ) / Decimal(11809)
        assert (
            _value(model, "revenue_growth", _BASE)
            == Decimal(11809) / Decimal(11519) - 1
        )
    assert _value(model, "bu:las_vegas", _BASE) == Decimal(4213) * Decimal("1.025")
    assert _cell(_model(), "revenue", _BASE).note is None
    assert reconciliation_faults(model) == ()


def test_a_foreign_facility_is_noted_on_debt_interest_and_their_metrics() -> None:
    regs = example_registers()
    regs = replace(
        regs,
        accounts=tuple(a for a in regs.accounts if a.metric_id != "total_debt"),
        facilities=tuple(
            replace(f, currency="EUR") if f.facility_id == "sun29" else f
            for f in regs.facilities
        ),
    )
    model = _model(regs=regs)

    for column_id, line_id in (
        (_LTM, "total_debt"),
        (_LTM, "net_debt"),
        (_LTM, "metric:total_leverage_adjusted"),
        (_LTM, "metric:liquidity_to_debt"),
        (_PF, "total_debt"),
        (_PF, "metric:net_leverage_adjusted"),
        (_BASE, "total_debt"),
        (_BASE, "interest_bearing_debt_opening"),
        (_BASE, "cash_interest"),
        (_BASE, "metric:interest_coverage_adjusted"),
        ("DOWNSIDE:2028", "metric:fcf_to_debt"),
    ):
        assert _EXCLUDES_FOREIGN in (_cell(model, line_id, column_id).note or ""), (
            column_id,
            line_id,
        )
    # Historical interest is CP-1's own: nothing is left out of it.
    assert _cell(model, "metric:interest_coverage_adjusted", _LTM).note is None
    on = _on(model)
    assert _LTM in on[_EXCLUDES_FOREIGN].split(", ")
    assert reconciliation_faults(model) == ()


def test_projected_secured_metrics_note_unallocated_movements() -> None:
    model = _model()

    for line_id in (
        "metric:senior_secured_leverage",
        "metric:senior_secured_net_leverage",
    ):
        assert _cell(model, line_id, _BASE).note == _EXCLUDES_UNALLOCATED
        assert _cell(model, line_id, "DOWNSIDE:2026").note is None
        assert _cell(model, line_id, _LTM).note is None
    assert _on(model)[_EXCLUDES_UNALLOCATED] == "BASE:2026, BASE:2027, BASE:2028"


def test_a_pf_register_with_ebitda_and_adjusted_ebitda_rows_is_a_limitation() -> None:
    regs = example_registers()
    adjusted = next(a for a in regs.pro_forma if a.metric_id == "adjusted_ebitda")
    both = replace(
        regs,
        pro_forma=(
            *regs.pro_forma,
            replace(adjusted, adjustment_id="silverlake_reported", metric_id="ebitda"),
        ),
    )

    assert _DOUBLE_COUNT in _model(regs=both).limitations
    assert _DOUBLE_COUNT not in _model().limitations
    # Rows for another period than the LTM's are not on the PF-LTM.
    elsewhere = replace(
        both,
        pro_forma=(
            *regs.pro_forma,
            replace(
                adjusted,
                adjustment_id="silverlake_reported",
                metric_id="ebitda",
                period_id="FY2025",
            ),
        ),
    )
    assert _DOUBLE_COUNT not in _model(regs=elsewhere).limitations


def _signed_zeros(model: CreditModel) -> list[tuple[str, str]]:
    return [
        (line.line_id, column.column_id)
        for line in model.lines
        for column, cell in zip(model.columns, line.cells, strict=True)
        for figure in (cell.value, cell.stated)
        if figure is not None and figure.is_zero() and figure.is_signed()
    ]


def test_no_cell_is_a_negative_zero() -> None:
    request = example_request()
    for driver in request["drivers"]:
        driver.update({"capex": "0", "cash_taxes": "-0", "acquisitions_disposals": "0"})
    regs = with_figures(
        example_registers(),
        "FY2025",
        {"dividends_paid": Decimal(0), "capex_and_intangible_investment": Decimal(0)},
    )
    model = _model(regs=regs, request=request)

    assert _signed_zeros(model) == []
    assert _value(model, "dividends", "DOWNSIDE:2026") == 0


def test_projected_interest_is_exact_and_its_bridge_still_bites() -> None:
    model = _model()
    assert _value(model, "cash_interest", _BASE) == Decimal("-858.984")
    assert reconciliation_faults(model) == ()
    cell = _cell(model, "cash_interest", _BASE)
    off = replace(cell, value=Decimal("-858.984001"))
    assert reconciliation_faults(_with_cell(model, "cash_interest", _BASE, off)) == (
        f"{_BASE}:interest",
    )


def test_a_compound_note_is_listed_under_each_of_its_notes() -> None:
    regs = example_registers()
    regs = replace(
        regs,
        facilities=tuple(
            replace(f, rate_type="NOT_STATED", annual_amortisation=None)
            if f.facility_id == "tlb"
            else f
            for f in regs.facilities
        ),
    )
    model = _model(regs=regs)
    assert (
        _cell(model, "fac:tlb", _BASE).note == "implied rate; amortisation not stated"
    )

    on = _on(model)
    assert not any("; " in note for note in on)
    assert _BASE in on["implied rate"].split(", ")
    assert _BASE in on["amortisation not stated"].split(", ")


def test_the_pf_ltm_debt_roll_forward_foots() -> None:
    model = _model()
    assert _cell(model, "debt_opening", _PF) == _cell(model, "debt_opening", _LTM)
    assert _cell(model, "debt_non_cash", _PF) == _cell(model, "debt_non_cash", _LTM)
    assert _cell(model, "rollforward:debt_raised_net", _PF) == _cell(
        model, "rollforward:debt_raised_net", _LTM
    )
    assert _value(model, "debt_closing", _PF) == _value(model, "total_debt", _PF)
    assert reconciliation_faults(model) == ()
    assert reconciliation_faults(_nudged(model, "debt_closing", _PF)) == (
        f"{_PF}:debt_rollforward",
    )


def test_a_debt_adjustment_classified_as_an_operating_lease_is_in_the_stack() -> None:
    regs = example_registers()
    regs = replace(
        regs,
        facilities=tuple(
            replace(f, lease_classification="OPERATING_LEASE")
            if f.facility_id == "disc"
            else f
            for f in regs.facilities
        ),
    )
    model = _model(regs=regs)

    line = _line(model, "fac:disc")
    assert (line.kind, line.rank) == ("ACCOUNT", "Debt adjustments")
    assert _value(model, "fac:disc", _BASE) == _value(model, "fac:disc", "FY:FY2025")
    assert _value(model, "debt:unallocated", "DOWNSIDE:2026") == 0
    assert reconciliation_faults(model) == ()


def test_the_unallocated_line_has_no_payment_rank() -> None:
    assert _line(_model(), "debt:unallocated").rank is None


def test_an_add_back_label_shows_the_status_that_excludes_it() -> None:
    regs = example_registers()
    rows = [a for a in regs.addbacks if a.addback_id == "restructuring"]
    regs = replace(
        regs,
        addbacks=tuple(
            replace(a, realization_status="UNREALIZED") if a is rows[0] else a
            for a in regs.addbacks
        ),
    )
    assert rows[-1].realization_status == "REALIZED"

    line = _line(_model(regs=regs, exclude_unrealised=True), "addback:restructuring")
    assert (line.label, line.kind) == (
        "Add-back: Restructuring (unrealised), excluded",
        "MEMO",
    )
    line = _line(_model(regs=regs), "addback:restructuring")
    assert (line.label, line.kind) == (
        "Add-back: Restructuring (unrealised)",
        "ACCOUNT",
    )


def test_a_pf_facility_issued_after_the_ltm_sums_in_its_rank() -> None:
    regs = example_registers()
    ssn31 = next(f for f in regs.facilities if f.facility_id == "ssn31")
    later = next(p for p in regs.periods if p.period_id == "LTM_Q2_2026")
    post = replace(later, period_id="PE_2026_09", end_date="2026-09-30")
    new = replace(
        ssn31,
        facility_id="ssn33",
        facility_name="New 2033 notes",
        period_id="PE_2026_09",
        carrying_value=Decimal(600),
    )
    notes = next(a for a in regs.pro_forma if a.metric_id == "facility:ssn31")
    regs = replace(
        regs,
        periods=(*regs.periods, post),
        facilities=(*regs.facilities, new),
        pro_forma=(
            *(a for a in regs.pro_forma if a is not notes),
            replace(notes, adjustment_id="ssn33_pf", metric_id="facility:ssn33"),
        ),
    )
    model = _model(regs=regs, projected=False)

    assert _value(model, "rank:Senior secured", _PF) == 2316 + 2000 + 1000 + 600
    assert reconciliation_faults(model) == ()


def test_interest_at_an_implied_rate_reconciles_to_its_last_digits() -> None:
    regs = example_registers()
    regs = replace(
        regs,
        facilities=tuple(
            replace(f, spread_bps=Decimal("2.25"))
            if f.facility_id == "tlb"
            else replace(f, fixed_rate=Decimal("0.065"))
            if f.facility_id == "ssn29"
            else f
            for f in regs.facilities
        ),
    )
    model = _model(regs=regs)

    assert _cell(model, "fac:tlb", "BASE:2027").note == "term out of range"
    assert reconciliation_faults(model) == ()


def test_business_unit_growth_reads_the_like_period() -> None:
    model = _model()
    with localcontext(CONTEXT):
        las_vegas = (
            _value(model, "bu:las_vegas", "FY:FY2025")
            / _value(model, "bu:las_vegas", "FY:FY2024")
            - 1
        )
    assert _value(model, "bu_growth:las_vegas", "FY:FY2025") == las_vegas
    assert _value(model, "bu_growth:las_vegas", _BASE) == Decimal("0.025")


def test_an_acquisition_reconciles_through_the_net_cash_flow() -> None:
    regs = with_figures(
        example_registers(), "FY2025", {"acquisitions_disposals": Decimal(-120)}
    )
    model = _model(regs=regs)
    assert _value(model, "acquisitions_net", "FY:FY2025") == -120
    assert reconciliation_faults(model) == ()


def _interest_at(gap: Decimal) -> tuple[str, ...]:
    """The interest faults with a base of 1 at 5% and interest `gap` more
    negative than minus their product: the check allows a unit of the rate
    times the base (1E-39), the interest's rounding (about 5E-39) and a unit
    of the interest (1E-39), about 7E-39."""
    model = _model()
    for line_id, value in (
        ("interest_bearing_debt_opening", Decimal(1)),
        ("wa_rate", Decimal("0.05")),
        ("cash_interest", Decimal("-0.05") - gap),
    ):
        cell = replace(_cell(model, line_id, _BASE), value=value)
        model = _with_cell(model, line_id, _BASE, cell)
    return tuple(f for f in reconciliation_faults(model) if f.endswith(":interest"))


def test_the_interest_bridge_allows_exactly_its_last_digits() -> None:
    with localcontext(CONTEXT):
        assert _interest_at(Decimal(0)) == ()
        assert _interest_at(Decimal("6E-39")) == ()
        assert _interest_at(Decimal("8E-39")) == (f"{_BASE}:interest",)


def test_a_pf_register_of_only_ebitda_and_adjusted_ebitda_rows_is_noted() -> None:
    regs = example_registers()
    adjusted = next(a for a in regs.pro_forma if a.metric_id == "adjusted_ebitda")
    only = replace(
        regs,
        pro_forma=(
            adjusted,
            replace(adjusted, adjustment_id="silverlake_reported", metric_id="ebitda"),
        ),
    )
    assert _DOUBLE_COUNT in _model(regs=only).limitations


def test_a_pf_refinancing_that_cuts_interest_raises_pf_coverage() -> None:
    regs = example_registers()
    regs = replace(
        regs,
        pro_forma=tuple(
            replace(a, value=Decimal(30)) if a.metric_id == "cash_interest_paid" else a
            for a in regs.pro_forma
        ),
    )
    model = _model(regs=regs)

    coverage = "metric:interest_coverage_adjusted"
    assert _value(model, coverage, _PF) > _value(model, coverage, _LTM)
    assert _value(model, "pf:silverlake_interest", _PF) == 30


def test_a_parenthesised_zero_is_never_a_negative_zero() -> None:
    zero = Decimal("-0")  # how the host reads "(0)"
    regs = with_figures(
        example_registers(),
        "FY2025",
        {"revenue": zero, "dividends_paid": zero},
    )
    regs = with_figures(regs, "Q2_2026", {"dividends_paid": zero})
    regs = replace(
        regs,
        pro_forma=tuple(
            replace(a, value=zero) if a.metric_id == "cash_interest_paid" else a
            for a in regs.pro_forma
        ),
    )
    model = _model(regs=regs)

    assert _signed_zeros(model) == []
    assert str(_value(model, "pf:silverlake_interest", _PF)) == "0"


def test_adjusted_ebitda_and_its_metrics_name_an_add_back_taken_as_nil() -> None:
    """The audit's p10 (a): restructuring stated only in 2026. An add-back
    is a one-off (MAJOR-A): FY2025 and H1 2025 without a row are nothing,
    named on the LTM add-back and every figure built from it."""
    regs = example_registers()
    kept = {"Q1_2026", "Q2_2026", "H1_2026"}
    regs = replace(
        regs,
        addbacks=tuple(
            a
            for a in regs.addbacks
            if a.addback_id != "restructuring" or a.period_id in kept
        ),
    )
    model = _model(regs=regs)
    ltm = "LTM:LTM_Q2_2026"
    assert _cell(model, "ebitda", ltm).value == 3904
    assert _cell(model, "addback:restructuring", ltm).value == 16
    for line_id in (
        "addback:restructuring",
        "adjusted_ebitda",
        "ffo",
        "metric:total_leverage_adjusted",
        "metric:interest_coverage_adjusted",
    ):
        cell = _cell(model, line_id, ltm)
        assert cell.value is not None, line_id
        for nil in ("FY2025", "H1_2025"):
            assert treated_as_zero(nil) in (cell.note or "").split("; "), line_id


def test_pf_rows_for_an_ltm_without_a_pf_column_raise_a_limitation() -> None:
    """The adversary's MAJOR-6 probe: a later Q3 2026 moves the LTM past
    CP-1's LTM_Q2_2026, whose four PF rows have no column."""
    regs = example_registers()
    later = PeriodRow(
        "Q3_2026",
        "2026",
        "3",
        "QUARTER",
        "2026-07-01",
        "2026-09-30",
        92,
        "USD",
        "MILLIONS",
        (),
    )
    moved = replace(regs, periods=(*regs.periods, later))
    model = _model(regs=moved, projected=False)
    assert not any(c.kind == "PF_LTM" for c in model.columns)
    assert len(regs.pro_forma) == 4
    assert f"{PF_NOT_SHOWN}: LTM_Q2_2026 (4 adjustments)" in model.limitations
    # With its PF column, nothing is dropped.
    assert not any(t.startswith(PF_NOT_SHOWN) for t in _model().limitations)
    # One row for another period: named, counted once.
    first = regs.pro_forma[0]
    one = replace(regs, pro_forma=(*regs.pro_forma, replace(first, period_id="FY2025")))
    found = [t for t in _model(regs=one).limitations if t.startswith(PF_NOT_SHOWN)]
    assert found == [f"{PF_NOT_SHOWN}: FY2025 (1 adjustment)"]

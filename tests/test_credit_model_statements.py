"""Statements, the cash flow waterfall, liquidity, working capital and PF-LTM."""

from __future__ import annotations

from dataclasses import replace
from decimal import Decimal, localcontext

import pytest
from credit_model_fixture import example_registers, with_figures
from hypothesis import given, settings
from hypothesis import strategies as st

from caos.calculators.credit_model import statements
from caos.calculators.credit_model._cells import (
    SIGN_NORMALISED,
    UNSPANNED,
    treated_as_zero,
)
from caos.calculators.credit_model.frame import Cell, Column, Frame, SourceRef
from caos.calculators.credit_model.history import (
    OUTFLOW_METRICS,
    PARTLY_STATED,
    account_frame,
    historical_columns,
)
from caos.calculators.credit_model.statements import (
    UNREALISED,
    excluded_addbacks,
    pro_forma_column,
    statement_frame,
)
from caos.methodology.model_inputs import Cp1Registers

_OUTFLOWS = (
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
)
_WATERFALL = (
    "ffo",
    "working_capital_change",
    "cfo_adjusted",
    "cfo_reported",
    "capex",
    "fcf",
    "acquisitions_net",
    "debt_raised_net",
    "equity_raised_net",
    "dividends",
    "other_investing_financing",
    "ncf",
)


def _columns(regs: Cp1Registers) -> dict[str, Column]:
    return {column.label: column for column in historical_columns(regs)}


def _frame(regs: Cp1Registers, exclude_unrealised: bool = False) -> Frame:
    columns = historical_columns(regs)
    accounts = account_frame(regs, columns)
    return statement_frame(accounts, columns, regs, exclude_unrealised)


def _cells(regs: Cp1Registers, label: str, exclude: bool = False) -> dict[str, Cell]:
    return _frame(regs, exclude)[_columns(regs)[label].column_id]


def _values(cells: dict[str, Cell], *keys: str) -> tuple[object, ...]:
    return tuple(cells[key].value for key in keys)


def test_the_waterfall_reconciles_ffo_plus_wc_to_cfo_adjusted() -> None:
    regs = example_registers()
    q2 = _cells(regs, "Q2 26")
    assert _values(q2, "revenue", "cogs", "gross_profit", "da", "opex_ex_da") == (
        3008,
        -1263,
        1745,
        -310,
        -737,
    )
    assert _values(q2, "opex_total", "ebit", "ebitda", "adjusted_ebitda") == (
        -1047,
        698,
        1008,
        1053,
    )
    assert _values(q2, "operating_lease_cost", "adjusted_ebitdar") == (-28, 1081)
    assert _values(q2, "cash_interest", "lease_cash_not_in_ebitda", "cash_taxes") == (
        -214,
        -4,
        -42,
    )
    assert _values(
        q2, "other_operating", "ffo", "working_capital_change", "cfo_adjusted"
    ) == (-20, 773, 14, 787)
    assert _values(q2, "cfo_reported", "capex", "fcf") == (791, -380, 407)
    assert q2["other_operating"].basis == "CALCULATED"
    assert q2["other_operating"].note == "residual"
    assert q2["ebit"] == replace(q2["ebit"], stated=Decimal(698), note=None)
    assert q2["adjusted_ebitda"].stated == 1053
    assert q2["gross_profit"].stated is None
    ltm = _cells(regs, "LTM Q2 26")
    assert _values(ltm, "adjusted_ebitda", "other_operating", "ffo") == (
        4089,
        -80,
        2971,
    )
    assert _values(ltm, "cfo_adjusted", "fcf") == (3013, 1533)
    reconciled = 0
    for cells in _frame(regs).values():
        if cells["ffo"].value is not None:
            _equal(cells, ("ffo", "working_capital_change"), ("cfo_adjusted",))
            reconciled += 1
    assert reconciled == len(_columns(regs))


def test_ebitda_stated_differs_note() -> None:
    regs = with_figures(example_registers(), "Q2_2026", {"ebitda": Decimal(1000)})
    q2 = _cells(regs, "Q2 26")
    assert q2["ebitda"].value == 1008
    assert q2["ebitda"].stated == 1000
    assert q2["ebitda"].note == "differs from CP-1 stated"


def test_expense_metrics_written_positive_read_the_same() -> None:
    assert frozenset(_OUTFLOWS) == OUTFLOW_METRICS
    regs = example_registers()
    positive = replace(
        regs,
        accounts=tuple(
            replace(a, value=abs(a.value))
            if a.metric_id in _OUTFLOWS and a.value is not None
            else a
            for a in regs.accounts
        ),
    )
    # Every figure, CP-1's `acct:` cells included, reads one way.
    assert {
        column_id: {key: cell.value for key, cell in cells.items()}
        for column_id, cells in _frame(positive).items()
    } == {
        column_id: {key: cell.value for key, cell in cells.items()}
        for column_id, cells in _frame(regs).items()
    }


def test_cfo_adjusted_removes_lease_and_interest_classified_in_financing() -> None:
    for written in (Decimal(-10), Decimal(10)):
        regs = with_figures(
            example_registers(),
            "Q2_2026",
            {
                "interest_paid_in_financing": written,
                "lease_payments_in_financing": Decimal(-4),
            },
        )
        q2 = _cells(regs, "Q2 26")
        assert _values(q2, "cfo_reported", "lease_cash_not_in_ebitda") == (791, -4)
        assert q2["cfo_adjusted"].value == 791 - 4 - 10
        assert q2["cfo_reported"].basis == "REPORTED"


def test_ncf_equals_reported_net_cash_change() -> None:
    regs = example_registers()
    frame = _frame(regs)
    checked = 0
    for cells in frame.values():
        reported = cells["acct:net_cash_change"].value
        if reported is not None and cells["ncf"].value is not None:
            assert cells["ncf"].value == reported
            checked += 1
    assert checked >= 10
    q2 = _cells(regs, "Q2 26")
    assert _values(
        q2, "acquisitions_net", "debt_raised_net", "equity_raised_net", "dividends"
    ) == (0, -6, -343, 0)
    assert q2["other_investing_financing"].value == -8
    assert q2["other_investing_financing"].note == "residual"
    assert q2["other_investing_financing"].basis == "CALCULATED"
    assert _values(q2, "cash_opening", "ncf", "fx_and_other_cash", "cash_closing") == (
        950,
        50,
        0,
        1000,
    )
    assert q2["fx_and_other_cash"].note == "residual"
    bought = with_figures(
        regs,
        "Q2_2026",
        {"acquisitions_disposals": Decimal(-100), "dividends_paid": Decimal(10)},
    )
    acquired = _cells(bought, "Q2 26")
    assert _values(
        acquired, "acquisitions_net", "dividends", "other_investing_financing"
    ) == (-100, -10, 102)
    assert acquired["ncf"].value == 50
    assert _values(q2, "undrawn_rcf", "liquidity") == (2200, 3200)
    fy23 = _cells(regs, "FY23")
    assert fy23["cash_opening"] == Cell(None, "NOT_SOURCED")
    assert fy23["fx_and_other_cash"].reason == "COMPONENT_MISSING"
    ytd = _cells(regs, "YTD H1 26")
    assert _values(ytd, "cash_opening", "ncf", "cash_closing") == (980, 20, 1000)


def test_dio_and_dpo_are_null_when_cogs_is_not_negative() -> None:
    """Normalisation is sign-agnostic (cogs is read as -abs), so cogs written
    positive is negative too: cogs = 0 is the only null-denominator case."""
    regs = example_registers()
    q2 = _cells(regs, "Q2 26")
    assert q2["days"].value == 91
    with localcontext(prec=38):
        dso = Decimal(297) / Decimal(3008) * 91
        dio = Decimal(48) / Decimal(1263) * 91
        dpo = Decimal(443) / Decimal(1263) * 91
        ccc = dso + dio - dpo
    assert _values(q2, "dso", "dio", "dpo", "ccc") == (dso, dio, dpo, ccc)
    assert _values(q2, "accounts_receivable", "inventory", "accounts_payable") == (
        297,
        48,
        443,
    )
    zero = _cells(with_figures(regs, "Q2_2026", {"cogs": Decimal(0)}), "Q2 26")
    assert zero["dio"] == Cell(None, "ZERO_OR_NEGATIVE_DENOMINATOR")
    assert zero["dpo"] == Cell(None, "ZERO_OR_NEGATIVE_DENOMINATOR")
    assert zero["ccc"].reason == "COMPONENT_MISSING"
    assert zero["dso"].value == q2["dso"].value
    no_revenue = _cells(with_figures(regs, "Q2_2026", {"revenue": Decimal(0)}), "Q2 26")
    assert no_revenue["dso"] == Cell(None, "ZERO_OR_NEGATIVE_DENOMINATOR")


def test_exclude_unrealised_leaves_unrealised_and_not_stated_addbacks_out() -> None:
    regs = example_registers()
    regs = replace(
        regs,
        addbacks=tuple(
            replace(b, realization_status="NOT_STATED")
            if b.addback_id == "transaction_costs"
            else b
            for b in regs.addbacks
        ),
    )
    kept = _cells(regs, "Q2 26")
    assert kept["adjusted_ebitda"].value == 1053
    assert kept["addback:run_rate_cost_savings"].note is None
    q2 = _cells(regs, "Q2 26", exclude=True)
    assert q2["adjusted_ebitda"].value == 1008 + 8 + 24
    assert q2["adjusted_ebitda"].stated == 1053
    assert q2["adjusted_ebitda"].note is None
    assert q2["addback:run_rate_cost_savings"].value == 10
    assert q2["addback:run_rate_cost_savings"].note == "excluded"
    assert q2["addback:transaction_costs"].note == "excluded"
    assert q2["addback:restructuring"].note is None
    assert q2["adjusted_ebitdar"].value == 1008 + 8 + 24 + 28
    ltm = _cells(regs, "LTM Q2 26", exclude=True)
    assert ltm["adjusted_ebitda"].value == 3904 + 32 + 92


def test_adjusted_ebitda_needs_every_addback() -> None:
    regs = example_registers()
    regs = replace(
        regs,
        addbacks=tuple(
            replace(b, value=None)
            if (b.addback_id, b.period_id) == ("restructuring", "Q2_2026")
            else b
            for b in regs.addbacks
        ),
    )
    q2 = _cells(regs, "Q2 26")
    assert q2["adjusted_ebitda"] == Cell(
        None, "COMPONENT_MISSING", stated=Decimal(1053)
    )
    assert q2["ffo"].reason == "COMPONENT_MISSING"


def test_a_missing_account_is_not_sourced_and_its_lines_component_missing() -> None:
    regs = example_registers()
    regs = replace(
        regs,
        accounts=tuple(
            a
            for a in regs.accounts
            if (a.metric_id, a.period_id)
            != ("capex_and_intangible_investment", "Q2_2026")
        ),
    )
    q2 = _cells(regs, "Q2 26")
    assert q2["capex"] == Cell(None, "NOT_SOURCED")
    assert q2["fcf"].reason == "COMPONENT_MISSING"
    assert q2["other_investing_financing"].reason == "COMPONENT_MISSING"
    assert q2["ffo"].value == 773


def test_pro_forma_adds_each_adjustment_once_and_blanks_the_waterfall() -> None:
    regs = example_registers()
    columns = _columns(regs)
    ltm = columns["LTM Q2 26"]
    frame = _frame(regs)
    made = pro_forma_column(regs, ltm, frame)
    assert made is not None
    column, pf_frame = made
    assert column == Column(
        column_id="PF:LTM_Q2_2026",
        kind="PF_LTM",
        label="PF-LTM",
        period_id="LTM_Q2_2026",
        fiscal_year=ltm.fiscal_year,
        end_date=ltm.end_date,
        days=ltm.days,
        case=None,
    )
    assert set(pf_frame) == {column.column_id}
    pf = pf_frame[column.column_id]
    base = frame[ltm.column_id]
    assert set(pf) == set(base) | {
        "pf:silverlake_ebitda",
        "pf:silverlake_interest",
        "pf:silverlake_cash",
        "pf:silverlake_notes",
    }
    assert pf["pf:silverlake_notes"].value == 600
    assert pf["pf:silverlake_notes"].basis == "PRO_FORMA"
    assert pf["pf:silverlake_notes"].sources[0].source_id == "S12"
    assert _values(pf, "adjusted_ebitda", "cash_interest", "cash_closing") == (
        4134,
        -904,
        950,
    )
    assert pf["adjusted_ebitda"].basis == "PRO_FORMA"
    assert pf["adjusted_ebitda"].stated is None
    assert pf["adjusted_ebitda"].sources[-1].source_id == "S12"
    assert _values(pf, "total_debt", "fac:ssn31", "secured_debt") == (
        14706,
        1600,
        5916,
    )
    assert _values(pf, "net_debt", "liquidity", "lease_adjusted_debt") == (
        14706 - 950,
        950 + 2200,
        14706,
    )
    assert pf["lease_adjusted_net_debt"].value == 14706 - 950
    assert pf["adjusted_ebitdar"].value == 4134 + 112
    assert pf["revenue"] == base["revenue"]
    assert pf["ebitda"] == base["ebitda"]
    for key in (
        *_WATERFALL,
        "other_operating",
        "cash_opening",
        "fx_and_other_cash",
        "accounts_receivable",
        "inventory",
        "accounts_payable",
        "days",
        "dso",
        "dio",
        "dpo",
        "ccc",
        *(key for key in base if key.startswith("kpi:")),
    ):
        assert pf[key] == Cell(None, "NOT_APPLICABLE"), key
    assert "kpi:lv_room_nights" in base
    for key in ("lease_cash_not_in_ebitda", "cash_taxes", "bu:digital"):
        assert pf[key] == base[key], key


def test_pro_forma_revenue_and_total_debt_adjustments() -> None:
    regs = example_registers()
    extra = replace(
        regs.pro_forma[0], adjustment_id="silverlake_revenue", metric_id="revenue"
    )
    debt = replace(
        regs.pro_forma[0], adjustment_id="other_debt", metric_id="total_debt"
    )
    regs = replace(regs, pro_forma=(*regs.pro_forma, extra, debt))
    ltm = _columns(regs)["LTM Q2 26"]
    made = pro_forma_column(regs, ltm, _frame(regs))
    assert made is not None
    pf = made[1]["PF:LTM_Q2_2026"]
    assert pf["revenue"].value == 11654 + 45
    assert pf["total_debt"].value == 14706 + 45
    assert pf["secured_debt"].value == 5916


def test_pro_forma_is_none_without_adjustments_for_the_ltm() -> None:
    regs = example_registers()
    ltm = _columns(regs)["LTM Q2 26"]
    assert pro_forma_column(replace(regs, pro_forma=()), ltm, _frame(regs)) is None
    other = replace(
        regs,
        pro_forma=tuple(replace(a, period_id="LTM_Q4_2025") for a in regs.pro_forma),
    )
    assert pro_forma_column(other, ltm, _frame(regs)) is None


_FIGURE = st.decimals(
    min_value=-(10**6), max_value=10**6, places=2, allow_nan=False, allow_infinity=False
)
_ACCOUNTS = (
    "revenue",
    "cogs",
    "opex_including_da",
    "depreciation_amortization",
    "operating_lease_cost",
    "cash_interest_paid",
    "cash_taxes_paid",
    "working_capital_change",
    "cfo_ncfo",
    "lease_payments_in_financing",
    "interest_paid_in_financing",
    "capex_and_intangible_investment",
    "acquisitions_disposals",
    "net_debt_issue_repay",
    "net_equity_issue_repay",
    "dividends_paid",
    "net_cash_change",
    "cash_and_equivalents",
    "rcf_commitment",
    "rcf_drawn",
)
_BASE = example_registers()


def _equal(
    cells: dict[str, Cell], left: tuple[str, ...], right: tuple[str, ...]
) -> None:
    """The sum of the `left` keys equals the sum of the `right` keys."""
    lhs = [cells[key].value for key in left]
    rhs = [cells[key].value for key in right]
    assert None not in lhs and None not in rhs
    assert sum(v for v in lhs if v is not None) == sum(v for v in rhs if v is not None)


@settings(max_examples=40, deadline=None)
@given(st.fixed_dictionaries({metric: _FIGURE for metric in _ACCOUNTS}))
def test_every_bridge_reconciles_for_any_consistent_accounts(
    figures: dict[str, Decimal],
) -> None:
    regs = with_figures(_BASE, "Q2_2026", figures)
    frame = _frame(regs)
    for label in ("Q2 26", "LTM Q2 26", "YTD H1 26"):
        cells = frame[_columns(regs)[label].column_id]
        _equal(cells, ("gross_profit",), ("revenue", "cogs"))
        _equal(cells, ("ebit",), ("gross_profit", "opex_total"))
        _equal(cells, ("ebitda", "da"), ("ebit",))
        _equal(cells, ("opex_ex_da", "da"), ("opex_total",))
        _equal(cells, ("ffo", "working_capital_change"), ("cfo_adjusted",))
        _equal(cells, ("fcf",), ("cfo_adjusted", "capex"))
        _equal(
            cells,
            ("ncf",),
            (
                "fcf",
                "acquisitions_net",
                "debt_raised_net",
                "equity_raised_net",
                "dividends",
                "other_investing_financing",
            ),
        )
        _equal(cells, ("ncf",), ("acct:net_cash_change",))
        _equal(cells, ("cash_opening", "ncf", "fx_and_other_cash"), ("cash_closing",))
        _equal(
            cells,
            ("debt_opening", "debt_raised_net", "debt_non_cash"),
            ("debt_closing",),
        )
        _equal(cells, ("debt_closing",), ("total_debt",))
        _equal(cells, ("net_debt", "cash_closing"), ("total_debt",))
        _equal(cells, ("liquidity",), ("cash_closing", "undrawn_rcf"))
        _equal(
            cells, ("adjusted_ebitdar", "operating_lease_cost"), ("adjusted_ebitda",)
        )
        raw = cells["acct:interest_paid_in_financing"].value
        assert raw is not None
        lease = cells["lease_cash_not_in_ebitda"].value
        assert lease is not None and lease == -abs(lease)
        reported, adjusted = cells["cfo_reported"].value, cells["cfo_adjusted"].value
        assert reported is not None
        assert adjusted == reported + lease - abs(raw)
        addbacks = tuple(key for key in cells if key.startswith("addback:"))
        _equal(cells, ("adjusted_ebitda",), ("ebitda", *addbacks))
        _equal(cells, ("undrawn_rcf", "acct:rcf_drawn"), ("acct:rcf_commitment",))
        for key in ("cogs", "da", "cash_interest", "capex"):
            value = cells[key].value
            assert value is not None and value <= 0, key
    # Cash taxes keep CP-1's sign: a refund is an inflow.
    q2 = frame[_columns(regs)["Q2 26"].column_id]
    assert q2["cash_taxes"].value == figures["cash_taxes_paid"]


def test_pro_forma_new_facility_unknown_metric_and_a_missing_line() -> None:
    regs = example_registers()
    first = regs.pro_forma[0]
    regs = replace(
        regs,
        pro_forma=(
            *regs.pro_forma,
            replace(first, adjustment_id="newco", metric_id="facility:newco"),
            replace(first, adjustment_id="capex", metric_id="capex", source=None),
        ),
    )
    ltm = _columns(regs)["LTM Q2 26"]
    frame = _frame(regs)
    frame[ltm.column_id]["cash_closing"] = Cell(None, "NOT_SOURCED")
    made = pro_forma_column(regs, ltm, frame)
    assert made is not None
    pf = made[1]["PF:LTM_Q2_2026"]
    assert pf["fac:newco"].value == 45
    assert pf["fac:newco"].basis == "PRO_FORMA"
    assert pf["total_debt"].value == 14706 + 45
    assert pf["secured_debt"].value == 5916
    assert pf["pf:capex"] == Cell(Decimal(45), basis="PRO_FORMA")
    assert pf["capex"] == Cell(None, "NOT_APPLICABLE")
    assert pf["cash_closing"] == Cell(None, "COMPONENT_MISSING")
    assert pf["net_debt"] == Cell(None, "COMPONENT_MISSING")
    assert pf["liquidity"] == Cell(None, "COMPONENT_MISSING")
    assert set(pf) == set(frame[ltm.column_id]) | {
        "fac:newco",
        "pf:newco",
        "pf:capex",
        *(f"pf:{a.adjustment_id}" for a in example_registers().pro_forma),
    }


def test_a_column_without_days_has_no_opening_balances_or_days_ratios() -> None:
    regs = example_registers()
    columns = tuple(
        replace(column, days=None) if column.label == "Q2 26" else column
        for column in historical_columns(regs)
    )
    q2_id = _columns(regs)["Q2 26"].column_id
    frame = statement_frame(account_frame(regs, columns), columns, regs)
    q2 = frame[q2_id]
    assert q2["days"] == Cell(None, "NOT_SOURCED")
    assert q2["cash_opening"] == Cell(None, "NOT_SOURCED")
    assert q2["debt_opening"] == Cell(None, "NOT_SOURCED")
    for key in ("dso", "dio", "dpo", "ccc", "fx_and_other_cash", "debt_non_cash"):
        assert q2[key].reason == "COMPONENT_MISSING", key


def _without(regs: Cp1Registers, metric_id: str, *period_ids: str) -> Cp1Registers:
    """`regs` without the metric's rows for `period_ids` (all when none)."""
    return replace(
        regs,
        accounts=tuple(
            a
            for a in regs.accounts
            if a.metric_id != metric_id
            or (period_ids and a.period_id not in period_ids)
        ),
    )


def test_lines_keep_their_sources_and_cp1_stated_figures() -> None:
    regs = example_registers()
    q2 = _cells(regs, "Q2 26")
    assert q2["gross_profit"].sources == (
        *q2["revenue"].sources,
        *q2["cogs"].sources,
    )
    assert q2["cash_opening"] == Cell(
        Decimal(950),
        basis="REPORTED",
        sources=(SourceRef("S10", "10-Q Q1 2026, Item 1", "950"),),
    )
    assert q2["days"] == Cell(Decimal(91), basis="CALCULATED")
    assert q2["dso"] == Cell(
        q2["dso"].value,
        basis="CALCULATED",
        sources=(*q2["accounts_receivable"].sources, *q2["revenue"].sources),
    )
    # CP-1's H1 figure written positive is a negative `stated`.
    positive = with_figures(regs, "H1_2026", {"cogs": Decimal(2471)})
    assert _cells(positive, "YTD H1 26")["cogs"].stated == -2471
    # CP-1's EBITDA component missing: the host's EBITDA keeps CP-1's H1.
    gap = _without(regs, "ebitda", "Q1_2026")
    ytd = _cells(gap, "YTD H1 26")
    assert ytd["ebitda"].value == 1972
    assert ytd["ebitda"].stated == 1972
    absent = _cells(_without(regs, "operating_lease_cost"), "Q2 26")
    assert absent["operating_lease_cost"] == Cell(None, "NOT_SOURCED")
    assert absent["adjusted_ebitdar"].reason == "COMPONENT_MISSING"


def test_adjusted_ebitda_differs_note_unless_unrealised_are_excluded() -> None:
    regs = with_figures(
        example_registers(), "Q2_2026", {"adjusted_ebitda": Decimal(1000)}
    )
    columns = historical_columns(regs)
    accounts = account_frame(regs, columns)
    q2_id = _columns(regs)["Q2 26"].column_id
    default = statement_frame(accounts, columns, regs)[q2_id]
    assert default["adjusted_ebitda"].value == 1053
    assert default["adjusted_ebitda"].note == "differs from CP-1 stated"
    assert default["addback:run_rate_cost_savings"].note is None
    excluded = statement_frame(accounts, columns, regs, True)[q2_id]
    assert excluded["adjusted_ebitda"].stated == 1000
    assert excluded["adjusted_ebitda"].note is None


def test_days_ratios_divide_by_any_positive_flow_and_need_the_balance() -> None:
    regs = example_registers()
    half = _cells(with_figures(regs, "Q2_2026", {"revenue": Decimal("0.5")}), "Q2 26")
    assert half["dso"].value == Decimal(297) / Decimal("0.5") * 91
    ending = ("Q2_2026", "H1_2026", "LTM_Q2_2026")
    bare = _cells(_without(regs, "inventory", *ending), "Q2 26")
    assert bare["inventory"] == Cell(None, "NOT_SOURCED")
    assert bare["dio"] == Cell(None, "COMPONENT_MISSING")
    assert bare["dpo"].value is not None


def test_pro_forma_keeps_a_foreign_note_drops_a_differs_note_and_is_exact() -> None:
    regs = example_registers()
    rows = [
        replace(f, currency="EUR") if f.facility_id == "sun32" else f
        for f in regs.facilities
    ]
    first = regs.pro_forma[0]
    regs = replace(
        regs,
        facilities=tuple(rows),
        pro_forma=(
            replace(first, value=Decimal("0.1234567890123456789012345678901")),
            replace(first, adjustment_id="eur", metric_id="facility:sun32"),
        ),
    )
    regs = with_figures(regs, "LTM_Q2_2026", {"adjusted_ebitda": Decimal(4000)})
    ltm = _columns(regs)["LTM Q2 26"]
    frame = _frame(regs)
    assert frame[ltm.column_id]["adjusted_ebitda"].note == "differs from CP-1 stated"
    made = pro_forma_column(regs, ltm, frame)
    assert made is not None
    pf = made[1]["PF:LTM_Q2_2026"]
    assert pf["adjusted_ebitda"].value == Decimal(
        "4089.1234567890123456789012345678901"
    )
    assert pf["adjusted_ebitda"].note is None
    assert pf["adjusted_ebitdar"].basis == "PRO_FORMA"
    assert pf["fac:sun32"].value == 3500 + 45
    assert pf["fac:sun32"].note == "different currency, not converted"
    assert pf["total_debt"] == frame[ltm.column_id]["total_debt"]
    assert pf["net_debt"].basis == "PRO_FORMA"
    assert pf["net_debt"].value == frame[ltm.column_id]["net_debt"].value


def _without_addback(
    regs: Cp1Registers, addback_id: str, *period_ids: str
) -> Cp1Registers:
    return replace(
        regs,
        addbacks=tuple(
            b
            for b in regs.addbacks
            if b.addback_id != addback_id or b.period_id not in period_ids
        ),
    )


def test_an_addback_without_a_row_contributes_zero_and_a_null_one_is_missing() -> None:
    regs = _without_addback(example_registers(), "transaction_costs", "Q2_2026")
    frame = _frame(regs)
    by_label = _columns(regs)
    q2 = frame[by_label["Q2 26"].column_id]
    assert q2["addback:transaction_costs"] == Cell(None, "NOT_SOURCED")
    assert q2["adjusted_ebitda"].value == 1053 - 3
    assert _values(q2, "other_operating", "ffo") == (-20 + 3, 773)
    assert q2["adjusted_ebitdar"].value == 1050 + 28
    # CP-1's H1 2026 row (6) stands for the YTD and the LTM built on it.
    ytd = frame[by_label["YTD H1 26"].column_id]
    assert ytd["addback:transaction_costs"].value == 6
    assert ytd["adjusted_ebitda"].value == 2062
    assert frame[by_label["LTM Q2 26"].column_id]["adjusted_ebitda"].value == 4089
    nulled = replace(
        regs,
        addbacks=tuple(
            replace(b, value=None)
            if (b.addback_id, b.period_id) == ("restructuring", "Q1_2026")
            else b
            for b in regs.addbacks
            # without H1's own row, the YTD is built from the null Q1 row
            if (b.addback_id, b.period_id) != ("restructuring", "H1_2026")
        ),
    )
    ytd_null = _cells(nulled, "YTD H1 26")
    assert ytd_null["addback:restructuring"].reason == "COMPONENT_MISSING"
    assert ytd_null["adjusted_ebitda"].reason == "COMPONENT_MISSING"


def test_financing_lease_and_interest_without_rows_count_zero_in_cfo_adjusted() -> None:
    regs = example_registers()
    one = _cells(_without(regs, "interest_paid_in_financing", "Q2_2026"), "Q2 26")
    assert one["cfo_adjusted"] == replace(
        one["cfo_adjusted"],
        value=Decimal(787),
        note=treated_as_zero("interest_paid_in_financing"),
    )
    assert one["ffo"].value == 773
    both = _cells(
        _without(
            _without(regs, "interest_paid_in_financing", "Q2_2026"),
            "lease_payments_in_financing",
            "Q2_2026",
        ),
        "Q2 26",
    )
    assert both["lease_cash_not_in_ebitda"] == Cell(None, "NOT_SOURCED")
    assert both["cfo_adjusted"].value == 791
    assert both["cfo_adjusted"].note == (
        f"{treated_as_zero('lease_payments_in_financing')}; "
        f"{treated_as_zero('interest_paid_in_financing')}"
    )
    assert both["ffo"].value == 791 - 14
    _equal(both, ("ffo", "working_capital_change"), ("cfo_adjusted",))
    assert _cells(regs, "Q2 26")["cfo_adjusted"].note is None
    nulled = replace(
        regs,
        accounts=tuple(
            replace(a, value=None)
            if (a.metric_id, a.period_id) == ("lease_payments_in_financing", "Q2_2026")
            else a
            for a in regs.accounts
        ),
    )
    missing = _cells(nulled, "Q2 26")
    assert missing["lease_cash_not_in_ebitda"] == Cell(None, "NOT_STATED")
    assert missing["cfo_adjusted"] == Cell(None, "COMPONENT_MISSING")


def test_a_pro_forma_ebitda_adjustment_adds_to_ebitda_and_adjusted_ebitda() -> None:
    regs = example_registers()
    first = regs.pro_forma[0]
    regs = replace(
        regs,
        pro_forma=(replace(first, adjustment_id="synergy", metric_id="ebitda"),),
    )
    ltm = _columns(regs)["LTM Q2 26"]
    made = pro_forma_column(regs, ltm, _frame(regs))
    assert made is not None
    pf = made[1]["PF:LTM_Q2_2026"]
    assert _values(pf, "ebitda", "adjusted_ebitda", "adjusted_ebitdar") == (
        3904 + 45,
        4089 + 45,
        4089 + 45 + 112,
    )


def test_exclude_unrealised_compares_stated_where_nothing_was_excluded() -> None:
    regs = with_figures(
        example_registers(), "Q1_2024", {"adjusted_ebitda": Decimal(900)}
    )
    q1 = _cells(regs, "Q1 24", exclude=True)
    assert q1["addback:run_rate_cost_savings"].value == 0
    assert q1["adjusted_ebitda"].value == 946
    assert q1["adjusted_ebitda"].note == "differs from CP-1 stated"


def test_a_sparse_addback_and_financing_line_resolve_bottom_up() -> None:
    regs = example_registers()
    kept = [b for b in regs.addbacks if b.addback_id != "transaction_costs"]
    model = next(b for b in regs.addbacks if b.addback_id == "transaction_costs")
    probe = replace(
        regs,
        addbacks=(
            *kept,
            replace(model, period_id="Q1_2025", value=Decimal(3)),
            replace(model, period_id="H1_2025", value=Decimal(3)),
        ),
    )
    ltm = _cells(probe, "LTM Q2 26")
    # A PYTD row beside no YTD row: the add-back's LTM is not built, and the
    # adjusted EBITDA that adds it is missing too.
    assert ltm["addback:transaction_costs"] == Cell(
        None, "COMPONENT_MISSING", note=PARTLY_STATED
    )
    assert ltm["adjusted_ebitda"].value is None
    assert ltm["ebitda"].value == 3904
    lease = _without(regs, "lease_payments_in_financing", "Q2_2026", "H1_2026")
    ytd = _cells(lease, "YTD H1 26")
    assert ytd["cfo_adjusted"].value == 1504 - 4
    # Q2 2026 has no row inside the YTD: nothing there, and named.
    assert ytd["cfo_adjusted"].note == treated_as_zero("Q2_2026")


def test_an_all_absent_financing_line_with_a_stated_figure_counts_zero() -> None:
    regs = example_registers()
    regs = replace(
        regs,
        accounts=tuple(
            replace(a, value=Decimal(-5))
            if a.metric_id == "interest_paid_in_financing"
            else a
            for a in regs.accounts
            if a.metric_id != "interest_paid_in_financing"
            or a.period_id == "LTM_Q2_2026"
        ),
    )
    ltm = _cells(regs, "LTM Q2 26")
    assert ltm["acct:interest_paid_in_financing"] == Cell(
        None, "NOT_SOURCED", stated=Decimal(-5)
    )
    assert ltm["cfo_adjusted"].value == 3029 - 16
    assert ltm["cfo_adjusted"].note == treated_as_zero("interest_paid_in_financing")


def test_an_excluded_addback_absent_on_a_column_leaves_nothing_out() -> None:
    regs = example_registers()
    regs = replace(
        regs,
        addbacks=tuple(
            b
            for b in regs.addbacks
            if b.addback_id != "run_rate_cost_savings" or b.period_id == "LTM_Q2_2026"
        ),
    )
    regs = with_figures(regs, "LTM_Q2_2026", {"adjusted_ebitda": Decimal(4000)})
    ltm = _cells(regs, "LTM Q2 26", exclude=True)
    assert ltm["addback:run_rate_cost_savings"].reason == "NOT_SOURCED"
    assert ltm["addback:run_rate_cost_savings"].stated == 40
    assert ltm["adjusted_ebitda"].value == 3904 + 32 + 92 + 21
    assert ltm["adjusted_ebitda"].note == "differs from CP-1 stated"


# Fix wave B (the adversary audit of b64facb7): H6, M3, L2, L3, Task 7 (4).

_EXCLUDES_FOREIGN = "excludes facility in another currency"


def _pf(regs: Cp1Registers) -> dict[str, Cell]:
    ltm = _columns(regs)["LTM Q2 26"]
    made = pro_forma_column(regs, ltm, _frame(regs))
    assert made is not None
    return made[1]["PF:LTM_Q2_2026"]


def test_a_foreign_facility_is_noted_on_every_debt_balance_it_leaves() -> None:
    regs = example_registers()
    eur = replace(
        regs,
        facilities=tuple(
            replace(f, currency="EUR") if f.facility_id == "sun29" else f
            for f in regs.facilities
        ),
    )
    ltm = _cells(eur, "LTM Q2 26")
    for key in ("net_debt", "lease_adjusted_debt", "lease_adjusted_net_debt"):
        assert ltm[key].note == _EXCLUDES_FOREIGN, key
    assert ltm["liquidity"].note is None
    pf = _pf(eur)
    for key in ("total_debt", "net_debt", "lease_adjusted_debt"):
        assert pf[key].note == _EXCLUDES_FOREIGN, key
    clean = _cells(regs, "LTM Q2 26")
    for key in ("net_debt", "lease_adjusted_debt", "lease_adjusted_net_debt"):
        assert clean[key].note is None, key


def _pf_interest(regs: Cp1Registers, value: Decimal) -> Cp1Registers:
    """`regs` with the PF cash-interest adjustment set to `value`."""
    return replace(
        regs,
        pro_forma=tuple(
            replace(a, value=value) if a.metric_id == "cash_interest_paid" else a
            for a in regs.pro_forma
        ),
    )


def test_a_pf_adjustment_is_a_change_and_keeps_cp1s_sign() -> None:
    # A refinancing that cuts interest by 30 adds +30 to the (negative) line.
    pf = _pf(_pf_interest(example_registers(), Decimal(30)))

    assert pf["pf:silverlake_interest"].value == 30
    assert pf["pf:silverlake_interest"].note is None
    assert pf["cash_interest"].value == -862 + 30
    assert pf["cash_interest"].note is None
    unchanged = _pf(example_registers())
    assert unchanged["pf:silverlake_interest"].value == -42
    assert unchanged["cash_interest"].value == -862 - 42
    # Cash keeps its sign too.
    assert unchanged["pf:silverlake_cash"].value == -50
    # Read exactly, beyond the context's 38 digits.
    long = Decimal("-42.123456789012345678901234567890123456789")
    exact = _pf(_pf_interest(example_registers(), long))
    assert exact["pf:silverlake_interest"].value == long


def test_a_pf_facility_with_no_ltm_row_starts_from_zero() -> None:
    regs = example_registers()
    ltm = _columns(regs)["LTM Q2 26"]
    frame = _frame(regs)
    frame[ltm.column_id]["fac:ssn33"] = Cell(None, "NOT_SOURCED")
    first = regs.pro_forma[0]
    regs = replace(
        regs,
        pro_forma=(
            *regs.pro_forma,
            replace(first, adjustment_id="ssn33", metric_id="facility:ssn33"),
        ),
    )
    made = pro_forma_column(regs, ltm, frame)
    assert made is not None
    pf = made[1]["PF:LTM_Q2_2026"]

    assert pf["fac:ssn33"] == Cell(
        Decimal(45),
        basis="PRO_FORMA",
        sources=pf["pf:ssn33"].sources,
        note=treated_as_zero("fac:ssn33"),
    )
    assert pf["total_debt"].value == 14706 + 45
    # A line other than a facility's without an LTM figure stays without one.
    frame[ltm.column_id]["revenue"] = Cell(None, "NOT_SOURCED")
    revenue = replace(first, adjustment_id="rev", metric_id="revenue")
    made = pro_forma_column(replace(regs, pro_forma=(revenue,)), ltm, frame)
    assert made is not None
    assert made[1]["PF:LTM_Q2_2026"]["revenue"] == Cell(None, "COMPONENT_MISSING")


def test_the_pf_debt_roll_forward_opens_at_the_ltm_and_closes_with_the_pf() -> None:
    regs = example_registers()
    ltm = _cells(regs, "LTM Q2 26")
    pf = _pf(regs)

    assert pf["debt_opening"] == ltm["debt_opening"]
    assert pf["debt_non_cash"] == ltm["debt_non_cash"]
    assert pf["debt_closing"].value == pf["total_debt"].value == 14706


def test_an_outflow_of_zero_is_no_negative_zero() -> None:
    regs = with_figures(example_registers(), "FY2025", {"dividends_paid": Decimal(0)})
    value = _cells(regs, "FY25")["dividends"].value

    assert value == 0
    assert value is not None and not value.is_signed()


def test_excluded_addbacks_are_those_with_any_row_unrealised_or_not_stated() -> None:
    regs = example_registers()
    assert excluded_addbacks(regs, exclude_unrealised=False) == frozenset()
    statuses: dict[str, set[str]] = {b.addback_id: set() for b in regs.addbacks}
    for b in regs.addbacks:
        statuses[b.addback_id].add(b.realization_status)
    expected = {a for a, seen in statuses.items() if seen & UNREALISED}
    assert expected
    assert excluded_addbacks(regs, exclude_unrealised=True) == expected
    first = regs.addbacks[0]
    one_row = replace(
        regs,
        addbacks=tuple(
            replace(b, realization_status="NOT_STATED") if b is first else b
            for b in regs.addbacks
        ),
    )
    assert first.addback_id in excluded_addbacks(one_row, exclude_unrealised=True)
    assert UNREALISED == {"UNREALIZED", "NOT_STATED"}


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (Decimal(0), Decimal(0)),
        (Decimal("-0"), Decimal(0)),
        (Decimal("0.5"), Decimal("0.5")),
        (Decimal(-1), Decimal(-1)),
    ],
)
def test_a_pf_adjustment_is_never_flipped_and_never_a_negative_zero(
    value: Decimal, expected: Decimal
) -> None:
    pf = _pf(_pf_interest(example_registers(), value))
    cell = pf["pf:silverlake_interest"]

    assert cell.value is not None
    assert (cell.value, cell.value.is_signed(), cell.note) == (
        expected,
        expected < 0,
        None,
    )
    total = pf["cash_interest"].value
    assert total is not None and str(total) != "-0"


def test_a_figure_built_from_a_sign_normalised_part_says_so() -> None:
    """The audit's p10 (b): cogs written positive on Q2 2026."""
    regs = example_registers()
    regs = replace(
        regs,
        accounts=tuple(
            replace(a, value=-a.value)
            if a.metric_id == "cogs" and a.period_id == "Q2_2026" and a.value
            else a
            for a in regs.accounts
        ),
    )
    q2 = _cells(regs, "Q2 26")
    assert q2["cogs"].note == SIGN_NORMALISED
    for key in ("gross_profit", "ebit", "ebitda"):
        assert SIGN_NORMALISED in (q2[key].note or ""), key


def test_the_pro_forma_and_days_ratios_name_a_missing_input() -> None:
    """The audit's p11."""
    why = Cell(None, "COMPONENT_MISSING", note=UNSPANNED)
    pf = [
        a for a in example_registers().pro_forma if a.metric_id == "cash_interest_paid"
    ]
    assert statements._pf_add("cash_interest", why, pf) == why
    days = Cell(Decimal(365))
    assert statements._days_ratio(Cell(Decimal(10)), why, days) == why
    assert statements._days_ratio(why, Cell(Decimal(10)), days) == why
    bare = Cell(None, "NOT_SOURCED")
    assert statements._days_ratio(bare, Cell(Decimal(10)), days) == Cell(
        None, "COMPONENT_MISSING"
    )


def _restructuring(regs: Cp1Registers, figures: dict[str, int]) -> Cp1Registers:
    """`regs` with the restructuring add-back on the given periods only."""
    template = next(b for b in regs.addbacks if b.addback_id == "restructuring")
    rows = tuple(
        replace(template, period_id=period_id, value=Decimal(value))
        for period_id, value in figures.items()
    )
    kept = tuple(b for b in regs.addbacks if b.addback_id != "restructuring")
    return replace(regs, addbacks=(*kept, *rows))


def test_an_excluded_addback_keeps_its_own_notes() -> None:
    """The adversary's MINOR-11: "excluded" is appended, never overwrites
    "differs from components"."""
    regs = example_registers()
    differs = replace(
        regs,
        addbacks=tuple(
            replace(
                b,
                realization_status="UNREALIZED",
                value=Decimal(99) if b.period_id == "FY2025" else b.value,
            )
            if b.addback_id == "transaction_costs"
            else b
            for b in regs.addbacks
        ),
    )
    fy = _cells(differs, "FY25", exclude=True)["addback:transaction_costs"]
    assert (fy.value, fy.note) == (Decimal(99), "differs from components; excluded")
    assert _cells(differs, "FY25")["addback:transaction_costs"].note == (
        "differs from components"
    )

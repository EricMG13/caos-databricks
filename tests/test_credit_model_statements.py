"""Statements, the cash flow waterfall, liquidity, working capital and PF-LTM."""

from __future__ import annotations

from dataclasses import replace
from decimal import Decimal, localcontext

from credit_model_fixture import example_registers, with_figures
from hypothesis import given, settings
from hypothesis import strategies as st

from caos.calculators.credit_model.frame import Cell, Column, Frame
from caos.calculators.credit_model.history import (
    OUTFLOW_METRICS,
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
    "cash_taxes_paid",
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
        for key in ("cogs", "da", "cash_interest", "cash_taxes", "capex"):
            value = cells[key].value
            assert value is not None and value <= 0, key


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

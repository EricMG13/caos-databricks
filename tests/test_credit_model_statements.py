"""Statements, the cash flow waterfall, liquidity, working capital and PF-LTM."""

from __future__ import annotations

from dataclasses import replace
from decimal import Decimal

from credit_model_fixture import example_registers

from caos.calculators.credit_model.frame import Cell, Column, Frame
from caos.calculators.credit_model.history import (
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


def test_pro_forma_is_none_without_adjustments_for_the_ltm() -> None:
    regs = example_registers()
    ltm = _columns(regs)["LTM Q2 26"]
    assert pro_forma_column(replace(regs, pro_forma=()), ltm, _frame(regs)) is None
    other = replace(
        regs,
        pro_forma=tuple(replace(a, period_id="LTM_Q4_2025") for a in regs.pro_forma),
    )
    assert pro_forma_column(other, ltm, _frame(regs)) is None


def _equal(
    cells: dict[str, Cell], left: tuple[str, ...], right: tuple[str, ...]
) -> None:
    """The sum of the `left` keys equals the sum of the `right` keys."""
    lhs = [cells[key].value for key in left]
    rhs = [cells[key].value for key in right]
    assert None not in lhs and None not in rhs
    assert sum(v for v in lhs if v is not None) == sum(v for v in rhs if v is not None)


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

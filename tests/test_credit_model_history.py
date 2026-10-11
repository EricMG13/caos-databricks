"""Historical columns and derived periods: quarters, PYTD, YTD, FY and LTM."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from datetime import date
from decimal import Decimal

from credit_model_fixture import (
    example_registers,
)

from caos.calculators.credit_model import history
from caos.calculators.credit_model._cells import SIGN_NORMALISED
from caos.calculators.credit_model.frame import SourceRef
from caos.calculators.credit_model.history import (
    BALANCE_METRICS,
    FLOW_METRICS,
    OUTFLOW_METRICS,
    historical_columns,
)
from caos.methodology.model_inputs import (
    AccountRow,
    Cp1Registers,
    PeriodRow,
)

_Figures = Mapping[str, Mapping[str, Decimal | int | str | None]]

# Quarter n: start month-day, end month-day, days.
_QUARTER = {
    1: ("01-01", "03-31", 90),
    2: ("04-01", "06-30", 91),
    3: ("07-01", "09-30", 92),
    4: ("10-01", "12-31", 92),
}
_YTD = {"H1": (2, 181), "9M": (3, 273)}


def _period(period_id: str, components: tuple[str, ...]) -> PeriodRow:
    """A period from its id: `Q2_2025`, `H1_2025`, `9M_2025`, `FY2025`,
    `LTM_Q2_2026`."""
    head, _, year = period_id.rpartition("_")
    if period_id.startswith("FY"):
        year = period_id[2:]
        kind, quarter, start, end, days = "FY", None, "01-01", "12-31", 365
    elif head.startswith("LTM"):
        quarter = int(head[-1])
        kind, end, days = "LTM", _QUARTER[quarter][1], 365
        start = _QUARTER[quarter % 4 + 1][0]
    elif head in _YTD:
        quarter, days = _YTD[head]
        kind, start, end = "YTD", "01-01", _QUARTER[quarter][1]
    else:
        quarter = int(head[1])
        start, end, days = _QUARTER[quarter]
        kind = "QUARTER"
    start_year = int(year) - 1 if kind == "LTM" and quarter != 4 else int(year)
    return PeriodRow(
        period_id=period_id,
        fiscal_year=year,
        fiscal_quarter=None if quarter is None else str(quarter),
        period_type=kind,
        start_date=f"{start_year}-{start}",
        end_date=f"{year}-{end}",
        day_count=days,
        currency="USD",
        unit="MILLIONS",
        component_period_ids=components,
    )


def _regs(
    quarters: _Figures | None = None,
    fy: _Figures | None = None,
    ytd: _Figures | None = None,
    ltm: _Figures | None = None,
    components: Mapping[str, tuple[str, ...]] | None = None,
) -> Cp1Registers:
    """CP-1 registers holding the given account figures, each period's id
    naming its type and dates; `components` names a period's components."""
    figures = {**(quarters or {}), **(fy or {}), **(ytd or {}), **(ltm or {})}
    parts = components or {}
    accounts = tuple(
        AccountRow(
            metric_id=metric,
            period_id=period_id,
            value=None if value is None else Decimal(value),
            calculation_status="VERIFIED",
            source=SourceRef("S1", period_id, str(value)),
        )
        for period_id, values in figures.items()
        for metric, value in values.items()
    )
    return Cp1Registers(
        periods=tuple(_period(pid, parts.get(pid, ())) for pid in figures),
        accounts=accounts,
        addbacks=(),
        segments=(),
        kpis=(),
        facilities=(),
        pro_forma=(),
        currency="USD",
        unit="MILLIONS",
    )


def test_flow_and_balance_metrics_are_cp1_controlled_ids() -> None:
    assert len(FLOW_METRICS) == 25
    assert len(BALANCE_METRICS) == 9
    assert not FLOW_METRICS & BALANCE_METRICS
    assert {"revenue", "gross_profit", "cash_lease_payments", "pretax_income"} <= (
        FLOW_METRICS
    )
    assert {"cash_and_equivalents", "senior_secured_debt", "unsecured_debt"} <= (
        BALANCE_METRICS
    )
    assert "effective_tax_rate" not in FLOW_METRICS | BALANCE_METRICS


def test_a_ytd_ending_on_the_fy_end_is_left_out() -> None:
    regs = _regs(fy={"FY2025": {"revenue": 12}}, ytd={"9M_2025": {"revenue": 9}})
    fy, nine = regs.periods
    twelve = replace(
        nine, period_id="12M_2025", fiscal_quarter="4", end_date=fy.end_date
    )
    regs = replace(regs, periods=(fy, twelve))

    assert [c.kind for c in historical_columns(regs)] == ["FY", "LTM"]


def test_a_ytd_without_a_fiscal_quarter_is_labelled_by_its_id() -> None:
    regs = _regs(fy={"FY2025": {"revenue": 12}}, ytd={"H1_2026": {"revenue": 6}})
    fy, h1 = regs.periods
    regs = replace(regs, periods=(fy, replace(h1, fiscal_quarter=None)))

    columns = historical_columns(regs)

    assert [c.label for c in columns] == ["YTD H1_2026", "FY25", "LTM H1_2026"]


def test_the_fixture_half_years_are_derived_periods() -> None:
    regs = example_registers()
    halves = {"H1_2025", "H1_2026"}

    assert all(p.component_period_ids for p in regs.periods if p.period_id in halves)
    rows = [a for a in regs.accounts if a.period_id in halves]
    assert rows
    assert {(a.source, a.calculation_status) for a in rows} == {(None, "CALCULATED")}


def test_an_anchor_quarter_without_a_fiscal_quarter_has_no_ytd() -> None:
    regs = _regs(quarters={"Q1_2026": {"revenue": 1}})
    regs = replace(regs, periods=(replace(regs.periods[0], fiscal_quarter=None),))

    columns = historical_columns(regs)

    assert [(c.column_id, c.label) for c in columns] == [
        ("Q:Q1_2026", "Q1_2026"),
        ("LTM:Q1_2026", "LTM Q1_2026"),
    ]


def test_outflow_metrics_are_cp1s_sign_agnostic_outflows() -> None:
    assert OUTFLOW_METRICS == {
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
    assert OUTFLOW_METRICS <= FLOW_METRICS
    assert SIGN_NORMALISED == "sign normalised"


def _relabelled(regs: Cp1Registers, years: dict[str, str]) -> Cp1Registers:
    return replace(
        regs,
        periods=tuple(
            replace(p, fiscal_year=years[p.period_id]) if p.period_id in years else p
            for p in regs.periods
        ),
    )


def test_a_label_takes_the_four_digit_year_however_the_text_ends() -> None:
    regs = _relabelled(example_registers(), {"FY2025": "FY2025 (restated)"})
    labels = {c.column_id: c.label for c in historical_columns(regs)}
    assert labels["FY:FY2025"] == "FY25"


def test_a_derived_start_is_a_calendar_day_no_later_than_the_end() -> None:
    q2 = next(p for p in example_registers().periods if p.period_id == "Q2_2026")
    end = date(2026, 6, 30)
    undated = replace(q2, start_date=None)

    def first(days: int | None, end_date: str | None = "2026-06-30") -> date | None:
        return history._first_day(replace(undated, day_count=days, end_date=end_date))

    assert first(91) == date(2026, 4, 1)
    assert first(1) == end
    assert first(end.toordinal()) == date(1, 1, 1)
    assert first(end.toordinal() + 1) is None
    assert first(0) is None
    assert first(None) is None
    assert first(91, None) is None
    assert history._first_day(q2) == date(2026, 4, 1)

"""Historical columns and derived periods: quarters, PYTD, YTD, FY and LTM."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import replace
from datetime import date, timedelta
from decimal import Decimal, localcontext

import pytest
from credit_model_fixture import (
    example_deck,
    example_growth,
    example_registers,
    example_slots,
)
from hypothesis import example, given, settings
from hypothesis import strategies as st

from caos.calculators.credit_model import history
from caos.calculators.credit_model._cells import (
    CONTEXT,
    OTHER_FOOTING,
    SIGN_NORMALISED,
    UNSPANNED,
    Footing,
    anchor_period,
    off_footing,
    treated_as_zero,
)
from caos.calculators.credit_model.assemble import (
    NOT_COMBINED,
    CreditModel,
    ModelInputs,
    credit_model,
)
from caos.calculators.credit_model.debt import debt_frame
from caos.calculators.credit_model.frame import Cell, SourceRef
from caos.calculators.credit_model.history import (
    BALANCE_METRICS,
    FLOW_METRICS,
    OUTFLOW_METRICS,
    account_frame,
    historical_columns,
    ltm_frames,
)
from caos.methodology.model_inputs import (
    MAX_NESTING,
    MAX_PERIODS,
    AccountRow,
    AddbackRow,
    Cp1Registers,
    KpiRow,
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


def _frame(regs: Cp1Registers) -> dict[str, dict[str, Cell]]:
    return account_frame(regs, historical_columns(regs))


def _value(cell: Cell) -> Decimal:
    assert cell.value is not None, cell
    return cell.value


def _kpi(kpi_id: str, value_type: str, period_id: str, value: str) -> KpiRow:
    source = SourceRef("S1", period_id, value)
    return KpiRow(
        kpi_id, kpi_id, 1, period_id, Decimal(value), "UNITS", value_type, source
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


def test_columns_are_ordered_quarters_pytd_ytd_fy_ltm() -> None:
    columns = historical_columns(example_registers())

    assert [column.column_id for column in columns] == [
        *(f"Q:Q{n}_{year}" for year in (2024, 2025) for n in (1, 2, 3, 4)),
        "Q:Q1_2026",
        "Q:Q2_2026",
        "PYTD:H1_2025",
        "YTD:H1_2026",
        "FY:FY2023",
        "FY:FY2024",
        "FY:FY2025",
        "LTM:LTM_Q2_2026",
    ]
    assert [column.label for column in columns][-8:] == [
        "Q1 26",
        "Q2 26",
        "PYTD H1 25",
        "YTD H1 26",
        "FY23",
        "FY24",
        "FY25",
        "LTM Q2 26",
    ]
    assert [column.kind for column in columns][-8:] == [
        "QUARTER",
        "QUARTER",
        "PYTD",
        "YTD",
        "FY",
        "FY",
        "FY",
        "LTM",
    ]
    by_id = {column.column_id: column for column in columns}
    q3 = by_id["Q:Q3_2024"]
    assert (q3.period_id, q3.fiscal_year, q3.end_date, q3.days, q3.case) == (
        "Q3_2024",
        "2024",
        "2024-09-30",
        92,
        None,
    )
    ltm = by_id["LTM:LTM_Q2_2026"]
    assert (ltm.period_id, ltm.fiscal_year, ltm.end_date, ltm.days) == (
        "LTM_Q2_2026",
        "2026",
        "2026-06-30",
        365,
    )
    assert by_id["PYTD:H1_2025"].end_date == "2025-06-30"
    for column_id in ("PYTD:H1_2025", "YTD:H1_2026", "FY:FY2024"):
        column = by_id[column_id]
        assert column.column_id == f"{column.kind}:{column.period_id}"
        assert column.fiscal_year == column.column_id[-4:]
    assert by_id["FY:FY2024"].days == 366


def test_ytd_and_pytd_are_omitted_when_the_latest_period_is_a_fy_end() -> None:
    regs = _regs(
        quarters={"Q3_2025": {"revenue": 30}, "Q4_2025": {"revenue": 40}},
        fy={"FY2025": {"revenue": 140}},
        ytd={"H1_2025": {"revenue": 70}, "H1_2024": {"revenue": 60}},
    )

    columns = historical_columns(regs)

    assert [column.column_id for column in columns] == [
        "Q:Q3_2025",
        "Q:Q4_2025",
        "FY:FY2025",
        "LTM:FY2025",
    ]
    ltm = columns[-1]
    assert (ltm.label, ltm.period_id, ltm.end_date, ltm.days) == (
        "LTM Q4 25",
        None,
        "2025-12-31",
        365,
    )
    cell = account_frame(regs, columns)["LTM:FY2025"]["acct:revenue"]
    assert (cell.value, cell.basis, cell.stated) == (Decimal(140), "CALCULATED", None)


def test_a_derived_ltm_without_a_register_row_is_named_by_its_ytd() -> None:
    regs = _regs(
        fy={"FY2025": {"revenue": 400}},
        ytd={"H1_2025": {"revenue": 190}, "H1_2026": {"revenue": 210}},
    )

    columns = historical_columns(regs)
    frame = account_frame(regs, columns)

    assert [column.column_id for column in columns] == [
        "PYTD:H1_2025",
        "YTD:H1_2026",
        "FY:FY2025",
        "LTM:H1_2026",
    ]
    assert (columns[-1].label, columns[-1].days) == ("LTM Q2 26", 365)
    assert frame["LTM:H1_2026"]["acct:revenue"].value == Decimal(420)
    assert frame["YTD:H1_2026"]["acct:revenue"] == Cell(
        Decimal(210),
        basis="REPORTED",
        sources=(SourceRef("S1", "H1_2026", "210"),),
    )


def test_ltm_equals_fy_plus_ytd_minus_pytd_for_every_flow() -> None:
    frame = _frame(example_registers())
    ltm, fy = frame["LTM:LTM_Q2_2026"], frame["FY:FY2025"]
    ytd, pytd = frame["YTD:H1_2026"], frame["PYTD:H1_2025"]
    flows = [
        key
        for key in ltm
        if key.removeprefix("acct:") in FLOW_METRICS or key.startswith("bu:")
    ]

    assert len(flows) == 26
    for key in flows:
        expected = _value(fy[key]) + _value(ytd[key]) - _value(pytd[key])
        cell = ltm[key]
        assert cell.value == expected, key
        assert (cell.basis, cell.stated, cell.note) == ("CALCULATED", expected, None)
    assert ltm["acct:revenue"].value == Decimal(11654)
    assert ltm["acct:adjusted_ebitda"].value == Decimal(4089)
    assert ltm["addback:run_rate_cost_savings"].value == Decimal(40)
    assert ltm["acct:revenue"].sources[0] == SourceRef(
        "S3", "10-K FY2025, Item 8 and quarterly data", "11519"
    )


def test_a_ytd_with_components_is_their_sum_and_keeps_cp1_stated() -> None:
    frame = _frame(example_registers())

    ytd = frame["YTD:H1_2026"]["acct:revenue"]
    assert (ytd.value, ytd.basis, ytd.stated, ytd.note) == (
        Decimal(5885),
        "CALCULATED",
        Decimal(5885),
        None,
    )
    assert [ref.cell_text for ref in ytd.sources] == ["2877", "3008"]
    assert frame["YTD:H1_2026"]["bu:las_vegas"].value == Decimal(2175)


def test_a_reported_quarter_is_never_replaced_by_a_calculated_one() -> None:
    regs = _regs(
        quarters={"Q1_2025": {"revenue": 100}, "Q2_2025": {"revenue": 120}},
        ytd={"H1_2025": {"revenue": 230}},
    )

    columns = historical_columns(regs)
    frame = account_frame(regs, columns)

    quarters = [column.column_id for column in columns if column.kind == "QUARTER"]
    assert quarters == ["Q:Q1_2025", "Q:Q2_2025"]
    assert frame["Q:Q2_2025"]["acct:revenue"] == Cell(
        Decimal(120),
        basis="REPORTED",
        sources=(SourceRef("S1", "Q2_2025", "120"),),
    )
    assert frame["Q:Q1_2025"]["acct:revenue"].value == Decimal(100)


def test_q2_and_q3_are_calculated_from_the_ytd_periods() -> None:
    regs = _regs(
        quarters={"Q1_2025": {"revenue": 100}},
        ytd={"H1_2025": {"revenue": 230}, "9M_2025": {"revenue": "365.5"}},
    )

    columns = historical_columns(regs)
    frame = account_frame(regs, columns)

    by_id = {column.column_id: column for column in columns}
    q2, q3 = by_id["Q:H1_2025-Q1_2025"], by_id["Q:9M_2025-H1_2025"]
    assert [column.column_id for column in columns][:3] == [
        "Q:Q1_2025",
        "Q:H1_2025-Q1_2025",
        "Q:9M_2025-H1_2025",
    ]
    assert (q2.label, q2.period_id, q2.end_date, q2.days) == (
        "Q2 25",
        None,
        "2025-06-30",
        91,
    )
    assert (q3.label, q3.end_date, q3.days) == ("Q3 25", "2025-09-30", 92)
    assert frame[q2.column_id]["acct:revenue"].value == Decimal(130)
    assert frame[q3.column_id]["acct:revenue"].value == Decimal("135.5")
    assert frame[q3.column_id]["acct:revenue"].basis == "CALCULATED"


def test_q4_is_calculated_from_fy_minus_9m_only_without_a_reported_q4() -> None:
    quarters = {f"Q{n}_2025": {"revenue": 100 + n} for n in (1, 2, 3)}
    fy = {"FY2025": {"revenue": 420}}
    ytd = {"9M_2025": {"revenue": 306}}
    regs = _regs(quarters=quarters, fy=fy, ytd=ytd)

    columns = historical_columns(regs)
    frame = account_frame(regs, columns)

    q4 = next(column for column in columns if column.label == "Q4 25")
    assert q4.column_id == "Q:FY2025-9M_2025"
    assert (q4.kind, q4.period_id, q4.end_date, q4.days) == (
        "QUARTER",
        None,
        "2025-12-31",
        92,
    )
    cell = frame[q4.column_id]["acct:revenue"]
    assert (cell.value, cell.basis, cell.stated, cell.note) == (
        Decimal(114),
        "CALCULATED",
        None,
        None,
    )
    assert [ref.source_locator for ref in cell.sources] == ["FY2025", "9M_2025"]

    reported = _regs(quarters={**quarters, "Q4_2025": {"revenue": 90}}, fy=fy, ytd=ytd)
    columns = historical_columns(reported)
    assert [column.label for column in columns if column.kind == "QUARTER"] == [
        "Q1 25",
        "Q2 25",
        "Q3 25",
        "Q4 25",
    ]
    q4_cell = account_frame(reported, columns)["Q:Q4_2025"]["acct:revenue"]
    assert (q4_cell.value, q4_cell.basis) == (Decimal(90), "REPORTED")


def test_a_derived_column_with_a_missing_component_is_component_missing() -> None:
    regs = _regs(
        fy={"FY2025": {"revenue": 400, "cogs": -100}},
        ytd={
            "H1_2025": {"revenue": None, "cogs": -40},
            "H1_2026": {"revenue": 210, "cogs": -50},
        },
        ltm={"LTM_Q2_2026": {"revenue": 420}},
    )

    frame = _frame(regs)

    ltm = frame["LTM:LTM_Q2_2026"]
    assert ltm["acct:revenue"] == Cell(None, "COMPONENT_MISSING", stated=Decimal(420))
    assert ltm["acct:cogs"].value == Decimal(-110)
    # H1 2025's revenue row has no figure: not stated, not absent.
    assert frame["PYTD:H1_2025"]["acct:revenue"] == Cell(None, "NOT_STATED")

    no_pytd = _regs(fy={"FY2025": {"revenue": 400}}, ytd={"H1_2026": {"revenue": 1}})
    columns = historical_columns(no_pytd)
    assert [column.kind for column in columns] == ["YTD", "FY", "LTM"]
    assert account_frame(no_pytd, columns)["LTM:H1_2026"]["acct:revenue"] == Cell(
        None, "COMPONENT_MISSING"
    )

    halves = _regs(
        quarters={"Q1_2026": {"revenue": 100}},
        ytd={"H1_2026": {"revenue": 210}, "H1_2025": {"revenue": 200}},
        components={"H1_2026": ("Q1_2026", "Q2_2026")},
    )
    ytd_cell = _frame(halves)["YTD:H1_2026"]["acct:revenue"]
    assert ytd_cell == Cell(
        None, "COMPONENT_MISSING", stated=Decimal(210), note=UNSPANNED
    )


def test_a_calculated_quarter_with_a_missing_component_is_component_missing() -> None:
    regs = _regs(
        quarters={"Q1_2025": {"revenue": 100}},
        fy={"FY2025": {"revenue": 420}},
        ytd={"9M_2025": {"revenue": None}},
    )

    frame = _frame(regs)

    assert frame["Q:FY2025-9M_2025"]["acct:revenue"] == Cell(None, "COMPONENT_MISSING")


def test_a_stated_ltm_that_differs_beyond_rounding_is_noted() -> None:
    fy: _Figures = {
        "FY2025": {"revenue": 400, "ebitda": "100.4", "ebit": "80.5", "cogs": -1}
    }
    ytd = {
        "H1_2025": {"revenue": 190, "ebitda": 0, "ebit": 0, "cogs": 0},
        "H1_2026": {"revenue": 210, "ebitda": 0, "ebit": 0, "cogs": 0},
    }
    stated: dict[str, Decimal | int | str | None] = {
        "revenue": "420.6",
        "ebitda": 100,
        "ebit": 80,
        "cogs": "-1.0",
    }
    regs = _regs(fy=fy, ytd=ytd, ltm={"LTM_Q2_2026": stated})

    ltm = _frame(regs)["LTM:LTM_Q2_2026"]

    noted = "differs from CP-1 stated"
    # One decimal place stated: 0.6 is beyond 0.05.
    assert (ltm["acct:revenue"].value, ltm["acct:revenue"].stated) == (
        Decimal(420),
        Decimal("420.6"),
    )
    assert ltm["acct:revenue"].note == noted
    # A whole number stated: 0.4 and 0.5 are rounding, not a difference.
    assert ltm["acct:ebitda"].note is None
    assert ltm["acct:ebit"].note is None
    assert ltm["acct:ebit"].stated == Decimal(80)
    # Equal at the stated precision.
    assert ltm["acct:cogs"].note is None

    beyond = _regs(fy=fy, ytd=ytd, ltm={"LTM_Q2_2026": {"ebitda": 99, "cogs": "-1.1"}})
    frame = _frame(beyond)["LTM:LTM_Q2_2026"]
    assert frame["acct:ebitda"].note == noted
    assert frame["acct:cogs"].note == noted


def test_balances_take_the_column_end_period() -> None:
    frame = _frame(example_registers())

    def value(column_id: str, key: str) -> Decimal | None:
        return frame[column_id][key].value

    assert value("PYTD:H1_2025", "acct:total_debt") == Decimal(13870)
    assert value("YTD:H1_2026", "acct:total_debt") == Decimal(13846)
    assert value("LTM:LTM_Q2_2026", "acct:cash_and_equivalents") == Decimal(1000)
    assert value("FY:FY2023", "acct:total_debt") == Decimal(13906)
    assert value("Q:Q3_2025", "acct:cash_and_equivalents") == Decimal(920)
    # No facility row on H1 or the LTM: the quarter that ends with them.
    tlb = frame["YTD:H1_2026"]["fac:tlb"]
    assert (tlb.value, tlb.basis) == (Decimal(2316), "REPORTED")
    assert tlb.sources[0].source_id == "S11"
    assert value("LTM:LTM_Q2_2026", "fac:tlb") == Decimal(2316)
    assert value("PYTD:H1_2025", "fac:tlb") == Decimal(2340)
    assert value("FY:FY2024", "fac:tlb") == Decimal(2352)
    assert value("FY:FY2024", "fac:finl") == Decimal(260)
    # A period-end KPI is a balance too.
    assert value("YTD:H1_2026", "kpi:rewards_members") == Decimal("67.3")
    assert value("PYTD:H1_2025", "kpi:rewards_members") == Decimal("65.1")
    assert value("LTM:LTM_Q2_2026", "kpi:rewards_members") == Decimal("67.3")


def test_a_balance_on_a_calculated_quarter_is_its_end_period() -> None:
    regs = _regs(
        quarters={"Q3_2025": {"cash_and_equivalents": 50}},
        fy={"FY2025": {"revenue": 420, "cash_and_equivalents": 70}},
        ytd={"9M_2025": {"revenue": 306, "cash_and_equivalents": None}},
    )

    frame = _frame(regs)

    cash = frame["Q:FY2025-9M_2025"]["acct:cash_and_equivalents"]
    assert (cash.value, cash.basis) == (Decimal(70), "REPORTED")
    assert frame["Q:Q3_2025"]["acct:cash_and_equivalents"].value == Decimal(50)
    assert frame["Q:Q3_2025"]["acct:revenue"] == Cell(None, "NOT_SOURCED")
    assert frame["FY:FY2025"]["acct:cash_and_equivalents"].value == Decimal(70)


def test_a_rate_kpi_is_not_sourced_on_a_derived_column() -> None:
    frame = _frame(example_registers())

    occupancy = "kpi:lv_occupancy"
    assert frame["Q:Q2_2026"][occupancy].value == Decimal("94.3")
    assert frame["FY:FY2025"][occupancy].value == Decimal("92.6")
    for column_id in ("PYTD:H1_2025", "YTD:H1_2026", "LTM:LTM_Q2_2026"):
        assert frame[column_id][occupancy] == Cell(None, "NOT_SOURCED"), column_id

    regs = _regs(
        quarters={"Q1_2025": {"revenue": 100}},
        fy={"FY2025": {"revenue": 420}},
        ytd={"9M_2025": {"revenue": 306}},
    )
    rates = (
        _kpi("occupancy", "RATE", "FY2025", "91.0"),
        _kpi("occupancy", "RATE", "9M_2025", "92.0"),
        _kpi("nights", "PERIOD_FLOW", "FY2025", "40"),
        _kpi("nights", "PERIOD_FLOW", "9M_2025", "31"),
    )
    frame = _frame(replace(regs, kpis=rates))
    assert frame["Q:FY2025-9M_2025"]["kpi:occupancy"] == Cell(None, "NOT_SOURCED")
    assert frame["Q:FY2025-9M_2025"]["kpi:nights"].value == Decimal(9)
    assert frame["FY:FY2025"]["kpi:occupancy"].value == Decimal("91.0")


def test_period_flow_kpis_segments_and_addbacks_follow_the_flow_rules() -> None:
    frame = _frame(example_registers())

    nights = frame["YTD:H1_2026"]["kpi:lv_room_nights"]
    assert (nights.value, nights.basis, nights.stated) == (
        Decimal(5111),
        "CALCULATED",
        None,
    )
    assert frame["LTM:LTM_Q2_2026"]["kpi:lv_room_nights"].value == Decimal(10001)
    assert frame["FY:FY2024"]["bu:corporate_eliminations"].value == Decimal(-60)
    savings = frame["Q:Q3_2025"]["addback:run_rate_cost_savings"]
    assert (savings.value, savings.basis) == (Decimal(10), "REPORTED")
    assert frame["LTM:LTM_Q2_2026"]["bu:digital"].value == Decimal(1339)


def test_an_account_outside_both_lists_is_shown_only_for_its_own_period() -> None:
    regs = _regs(
        quarters={"Q2_2026": {"effective_tax_rate": "0.3"}},
        fy={"FY2025": {"revenue": 400, "effective_tax_rate": "0.21"}},
        ytd={
            "H1_2025": {"revenue": 190, "effective_tax_rate": "0.2"},
            "H1_2026": {"revenue": 210},
        },
    )

    frame = _frame(regs)

    assert frame["FY:FY2025"]["acct:effective_tax_rate"].value == Decimal("0.21")
    assert frame["PYTD:H1_2025"]["acct:effective_tax_rate"].value == Decimal("0.2")
    assert frame["YTD:H1_2026"]["acct:effective_tax_rate"] == Cell(None, "NOT_SOURCED")
    assert frame["LTM:H1_2026"]["acct:effective_tax_rate"] == Cell(None, "NOT_SOURCED")


def test_ltm_frames_sum_the_four_quarters_ending_each_quarter() -> None:
    regs = example_registers()
    columns = historical_columns(regs)

    frames = ltm_frames(regs, columns)

    assert list(frames) == [c.column_id for c in columns if c.kind == "QUARTER"]
    assert frames["Q:Q2_2026"]["acct:revenue"].value == Decimal(11654)
    assert frames["Q:Q2_2026"]["acct:revenue"].basis == "CALCULATED"
    assert len(frames["Q:Q2_2026"]["acct:revenue"].sources) == 4
    assert frames["Q:Q4_2024"]["acct:revenue"].value == Decimal(11165)
    assert frames["Q:Q4_2025"]["acct:adjusted_ebitda"].value == Decimal(4019)
    assert frames["Q:Q4_2025"]["kpi:lv_room_nights"].value == Decimal(9900)
    assert frames["Q:Q3_2024"]["acct:revenue"] == Cell(None, "COMPONENT_MISSING")
    # Balances and period-end KPIs are the quarter's own; rates are not summed.
    assert frames["Q:Q3_2025"]["acct:total_debt"].value == Decimal(13864)
    assert frames["Q:Q3_2025"]["fac:tlb"].value == Decimal(2334)
    assert frames["Q:Q3_2025"]["kpi:rewards_members"].value == Decimal("65.6")
    assert frames["Q:Q3_2025"]["kpi:lv_occupancy"] == Cell(None, "NOT_SOURCED")
    # Whatever the order the columns come in.
    assert set(ltm_frames(regs, tuple(reversed(columns)))) == set(frames)


def test_ltm_frames_include_calculated_quarters_and_refuse_a_gap() -> None:
    quarters = {
        "Q4_2024": {"revenue": 10},
        "Q1_2025": {"revenue": 1},
        "Q2_2025": {"revenue": 2},
        "Q3_2025": {"revenue": 3},
    }
    regs = _regs(
        quarters=quarters,
        fy={"FY2025": {"revenue": 10}},
        ytd={"9M_2025": {"revenue": 6}},
    )
    columns = historical_columns(regs)

    frames = ltm_frames(regs, columns)

    assert frames["Q:FY2025-9M_2025"]["acct:revenue"].value == Decimal(10)
    assert frames["Q:Q3_2025"]["acct:revenue"].value == Decimal(16)

    gap = _regs(quarters={k: v for k, v in quarters.items() if k != "Q2_2025"})
    gap_frames = ltm_frames(gap, historical_columns(gap))
    assert gap_frames["Q:Q3_2025"]["acct:revenue"] == Cell(None, "COMPONENT_MISSING")
    assert set(ltm_frames(gap, ())) == set()


_CENTS = st.integers(min_value=-(10**12), max_value=10**12).map(
    lambda cents: Decimal(cents).scaleb(-2)
)


@settings(deadline=None, max_examples=200)
@given(
    st.lists(_CENTS, min_size=6, max_size=6), st.lists(_CENTS, min_size=6, max_size=6)
)
def test_derived_flows_reconcile_for_any_quarter_values(
    revenue: list[Decimal], interest: list[Decimal]
) -> None:
    ids = ["Q1_2025", "Q2_2025", "Q3_2025", "Q4_2025", "Q1_2026", "Q2_2026"]
    quarters = {
        period_id: {"revenue": rev, "cash_interest_paid": paid}
        for period_id, rev, paid in zip(ids, revenue, interest, strict=True)
    }
    regs = _regs(
        quarters=quarters,
        fy={"FY2025": {}},
        ytd={"H1_2025": {}, "H1_2026": {}},
        components={
            "FY2025": tuple(ids[:4]),
            "H1_2025": tuple(ids[:2]),
            "H1_2026": tuple(ids[4:]),
        },
    )

    frame = _frame(regs)

    # An outflow reads as minus its absolute value, whatever sign CP-1 wrote.
    for key, values in (
        ("acct:revenue", revenue),
        ("acct:cash_interest_paid", [-abs(paid) for paid in interest]),
    ):
        fy = _value(frame["FY:FY2025"][key])
        ytd = _value(frame["YTD:H1_2026"][key])
        pytd = _value(frame["PYTD:H1_2025"][key])
        assert fy == sum(values[:4], Decimal(0))
        assert ytd == values[4] + values[5]
        assert pytd == values[0] + values[1]
        assert frame["LTM:H1_2026"][key].value == fy + ytd - pytd
        assert frame["LTM:H1_2026"][key].value == sum(values[2:], Decimal(0))


def test_an_irregular_period_is_kept_without_a_guess() -> None:
    regs = _regs(
        quarters={"Q1_2025": {"revenue": 100}, "Q4_2025": {"revenue": 1}},
        ytd={"H1_2025": {"revenue": 230}},
    )
    q1, q4, h1 = regs.periods
    stub = replace(q4, period_id="STUB", fiscal_quarter=None, end_date=None)
    regs = replace(
        regs,
        periods=(replace(q1, day_count=None), stub, h1),
        accounts=(
            *regs.accounts,
            AccountRow("revenue", "STUB", Decimal(5), "VERIFIED", None),
            AccountRow("total_debt", "STUB", Decimal(7), "VERIFIED", None),
        ),
    )

    columns = historical_columns(regs)
    frame = account_frame(regs, columns)
    frames = ltm_frames(regs, columns)

    assert [(c.column_id, c.label) for c in columns if c.kind == "QUARTER"] == [
        ("Q:STUB", "STUB"),
        ("Q:Q1_2025", "Q1 25"),
        ("Q:H1_2025-Q1_2025", "Q2 25"),
    ]
    assert columns[2].days is None
    assert frame["Q:STUB"]["acct:revenue"].value == Decimal(5)
    assert frame["Q:Q1_2025"]["acct:total_debt"] == Cell(None, "NOT_SOURCED")
    assert frames["Q:STUB"]["acct:revenue"] == Cell(None, "COMPONENT_MISSING")
    assert frames["Q:STUB"]["acct:total_debt"].value == Decimal(7)


def test_fiscal_quarters_read_with_or_without_a_q() -> None:
    regs = _regs(quarters={"Q1_2025": {"revenue": 1}, "Q2_2025": {"revenue": 2}})
    q1, q2 = regs.periods
    regs = replace(
        regs,
        periods=(replace(q1, fiscal_quarter="q1"), replace(q2, fiscal_quarter="Q2")),
    )

    columns = historical_columns(regs)

    # Both quarters to date are columns, so they are the YTD.
    assert [column.label for column in columns] == [
        "Q1 25",
        "Q2 25",
        "YTD H1 25",
        "LTM Q2 25",
    ]
    assert ltm_frames(regs, columns)["Q:Q2_2025"]["acct:revenue"] == Cell(
        None, "COMPONENT_MISSING"
    )


def test_a_fiscal_year_without_four_digits_is_labelled_by_its_last_two() -> None:
    regs = _regs(
        quarters={f"Q{n}_2025": {"revenue": n} for n in (1, 2, 3, 4)},
        ytd={"H1_2025": {"revenue": 3}, "H1_2026": {"revenue": 5}},
    )
    regs = replace(
        regs,
        periods=tuple(
            replace(p, fiscal_year=f"Y{p.fiscal_year[2:]}") for p in regs.periods
        ),
    )

    columns = historical_columns(regs)

    assert [column.label for column in columns] == [
        "Q1 25",
        "Q2 25",
        "Q3 25",
        "Q4 25",
        "PYTD H1 25",
        "YTD H1 26",
        "LTM Q2 26",
    ]
    # No year to count back from: no LTM year and no trailing quarters; the
    # PYTD is still found by its dates, twelve months before the YTD.
    ltm = account_frame(regs, columns)["LTM:H1_2026"]["acct:revenue"]
    assert ltm == Cell(None, "COMPONENT_MISSING")
    frames = ltm_frames(regs, columns)
    assert frames["Q:Q4_2025"]["acct:revenue"] == Cell(None, "COMPONENT_MISSING")


def test_undated_periods_are_never_the_latest() -> None:
    dated = _regs(
        fy={"FY2024": {"revenue": 1}, "FY2025": {"revenue": 2}},
        ytd={"H1_2026": {"revenue": 3}},
    )
    fy24, fy25, h1 = dated.periods
    no_fy_end = replace(dated, periods=(replace(fy24, end_date=None), fy25, h1))
    assert [c.column_id for c in historical_columns(no_fy_end)] == [
        "YTD:H1_2026",
        "FY:FY2024",
        "FY:FY2025",
        "LTM:H1_2026",
    ]
    assert _frame(no_fy_end)["LTM:H1_2026"]["acct:revenue"] == Cell(
        None, "COMPONENT_MISSING"
    )

    no_ytd_end = replace(dated, periods=(fy24, fy25, replace(h1, end_date=None)))
    assert [c.kind for c in historical_columns(no_ytd_end)] == ["FY", "FY", "LTM"]

    only_undated = replace(dated, periods=(replace(fy25, end_date=None), h1))
    assert [c.kind for c in historical_columns(only_undated)] == ["YTD", "FY", "LTM"]

    latest_undated = replace(dated, periods=(fy24, replace(fy25, end_date=None), h1))
    columns = historical_columns(latest_undated)
    assert [c.column_id for c in columns] == [
        "YTD:H1_2026",
        "FY:FY2025",
        "FY:FY2024",
        "LTM:H1_2026",
    ]


def test_a_ytd_ending_on_the_fy_end_is_left_out() -> None:
    regs = _regs(fy={"FY2025": {"revenue": 12}}, ytd={"9M_2025": {"revenue": 9}})
    fy, nine = regs.periods
    twelve = replace(
        nine, period_id="12M_2025", fiscal_quarter="4", end_date=fy.end_date
    )
    regs = replace(regs, periods=(fy, twelve))

    assert [c.kind for c in historical_columns(regs)] == ["FY", "LTM"]


def test_a_ytd_without_a_fiscal_quarter_is_labelled_by_its_months() -> None:
    regs = _regs(fy={"FY2025": {"revenue": 12}}, ytd={"H1_2026": {"revenue": 6}})
    fy, h1 = regs.periods
    unlabelled = replace(regs, periods=(fy, replace(h1, fiscal_quarter=None)))

    columns = historical_columns(unlabelled)

    assert [c.label for c in columns] == ["YTD H1 26", "FY25", "LTM Q2 26"]
    # Five months are no fiscal quarter: labelled by its id.
    five = replace(h1, fiscal_quarter=None, end_date="2026-05-31", day_count=151)
    columns = historical_columns(replace(regs, periods=(fy, five)))
    assert [c.label for c in columns] == ["YTD H1_2026", "FY25", "LTM H1_2026"]


def test_a_register_ltm_ending_elsewhere_is_not_the_columns() -> None:
    regs = _regs(
        fy={"FY2025": {"revenue": 400}},
        ytd={"H1_2025": {"revenue": 190}, "H1_2026": {"revenue": 210}},
        ltm={"LTM_Q1_2026": {"revenue": 999}},
    )

    columns = historical_columns(regs)
    ltm = account_frame(regs, columns)["LTM:H1_2026"]["acct:revenue"]

    assert columns[-1].column_id == "LTM:H1_2026"
    assert (ltm.value, ltm.stated, ltm.note) == (Decimal(420), None, None)


def test_the_register_ltm_supplies_its_days_and_its_own_rates() -> None:
    regs = _regs(
        fy={"FY2025": {"revenue": 400}},
        ytd={"H1_2025": {"revenue": 190}, "H1_2026": {"revenue": 210}},
        ltm={"LTM_Q2_2026": {"revenue": 420}},
    )
    fy, pytd, ytd, ltm = regs.periods
    regs = replace(
        regs,
        periods=(fy, pytd, ytd, replace(ltm, day_count=364)),
        kpis=(_kpi("occupancy", "RATE", "LTM_Q2_2026", "90.5"),),
    )

    columns = historical_columns(regs)
    frame = account_frame(regs, columns)

    assert columns[-1].days == 364
    assert frame["LTM:LTM_Q2_2026"]["kpi:occupancy"].value == Decimal("90.5")

    undated = replace(regs, periods=(fy, pytd, ytd, replace(ltm, day_count=None)))
    assert historical_columns(undated)[-1].days == 365


def test_derived_sums_are_exact_past_the_default_precision() -> None:
    big = Decimal("1234567890123456789012345678.91")
    regs = _regs(
        quarters={f"Q{n}_2025": {"revenue": big} for n in (1, 2, 3, 4)},
        fy={"FY2025": {}},
        components={"FY2025": tuple(f"Q{n}_2025" for n in (1, 2, 3, 4))},
    )

    columns = historical_columns(regs)

    # 30 significant digits: the default context's 28 would round them.
    exact = Decimal("4938271560493827156049382715.64")
    assert account_frame(regs, columns)["FY:FY2025"]["acct:revenue"].value == exact
    assert ltm_frames(regs, columns)["Q:Q4_2025"]["acct:revenue"].value == exact


def test_the_ltm_needs_the_fiscal_year_before_the_ytd() -> None:
    regs = example_registers()
    regs = replace(
        regs,
        periods=tuple(p for p in regs.periods if p.period_id != "FY2025"),
        accounts=tuple(a for a in regs.accounts if a.period_id != "FY2025"),
    )

    frame = _frame(regs)

    # FY2024 + H1 2026 - H1 2025 would be eighteen months.
    assert frame["LTM:LTM_Q2_2026"]["acct:revenue"] == Cell(
        None, "COMPONENT_MISSING", stated=Decimal(11654)
    )


def test_a_q1_only_year_builds_its_ytd_and_pytd_from_quarters() -> None:
    regs = _regs(
        quarters={"Q1_2025": {"revenue": 100}, "Q1_2026": {"revenue": 110}},
        fy={"FY2025": {"revenue": 420}},
        ltm={"LTM_Q1_2026": {"revenue": 430}},
    )

    columns = historical_columns(regs)
    frame = account_frame(regs, columns)

    assert [(c.column_id, c.label, c.period_id, c.days) for c in columns] == [
        ("Q:Q1_2025", "Q1 25", "Q1_2025", 90),
        ("Q:Q1_2026", "Q1 26", "Q1_2026", 90),
        ("PYTD:Q1_2025", "PYTD Q1 25", None, 90),
        ("YTD:Q1_2026", "YTD Q1 26", None, 90),
        ("FY:FY2025", "FY25", "FY2025", 365),
        ("LTM:LTM_Q1_2026", "LTM Q1 26", "LTM_Q1_2026", 365),
    ]
    pytd_column, ytd_column = columns[2], columns[3]
    assert (ytd_column.kind, ytd_column.fiscal_year, ytd_column.end_date) == (
        "YTD",
        "2026",
        "2026-03-31",
    )
    assert (pytd_column.kind, pytd_column.fiscal_year, pytd_column.end_date) == (
        "PYTD",
        "2025",
        "2025-03-31",
    )
    ytd = frame["YTD:Q1_2026"]["acct:revenue"]
    assert (ytd.value, ytd.basis, ytd.stated) == (Decimal(110), "CALCULATED", None)
    assert frame["PYTD:Q1_2025"]["acct:revenue"].value == Decimal(100)
    ltm = frame["LTM:LTM_Q1_2026"]["acct:revenue"]
    assert (ltm.value, ltm.stated, ltm.note) == (Decimal(430), Decimal(430), None)


def test_a_ytd_from_quarters_needs_every_quarter_to_date() -> None:
    regs = _regs(
        quarters={"Q2_2026": {"revenue": 110}},
        fy={"FY2025": {"revenue": 420}},
    )

    columns = historical_columns(regs)

    assert [c.column_id for c in columns] == ["Q:Q2_2026", "FY:FY2025", "LTM:Q2_2026"]
    assert columns[-1].label == "LTM Q2 26"
    assert account_frame(regs, columns)["LTM:Q2_2026"]["acct:revenue"] == Cell(
        None, "COMPONENT_MISSING"
    )


def test_a_register_ltm_later_than_the_host_can_build_is_kept_unadopted() -> None:
    regs = _regs(
        fy={"FY2025": {"revenue": 400}},
        ytd={"H1_2025": {"revenue": 190}, "H1_2026": {"revenue": 210}},
        ltm={"LTM_Q3_2026": {"revenue": 500}},
    )
    regs = replace(regs, kpis=(_kpi("occupancy", "RATE", "LTM_Q3_2026", "90.5"),))

    columns = historical_columns(regs)
    frame = account_frame(regs, columns)

    assert [c.column_id for c in columns][-2:] == ["LTM:H1_2026", "LTM:LTM_Q3_2026"]
    later = columns[-1]
    assert (later.label, later.period_id, later.end_date) == (
        "LTM Q3 26",
        "LTM_Q3_2026",
        "2026-09-30",
    )
    assert (later.kind, later.fiscal_year, later.days) == ("LTM", "2026", 365)
    assert frame["LTM:LTM_Q3_2026"]["kpi:occupancy"].value == Decimal("90.5")
    assert frame["LTM:H1_2026"]["acct:revenue"].value == Decimal(420)
    assert frame["LTM:LTM_Q3_2026"]["acct:revenue"] == Cell(
        None, "COMPONENT_MISSING", stated=Decimal(500)
    )


def test_a_stated_figure_in_hundreds_is_rounding_within_fifty() -> None:
    zero = {"revenue": 0, "cogs": 0}
    regs = _regs(
        fy={"FY2025": {"revenue": 1240, "cogs": -1260}},
        ytd={"H1_2025": zero, "H1_2026": zero},
        ltm={"LTM_Q2_2026": {"revenue": "1.2E+3", "cogs": "-1.2E+3"}},
    )

    ltm = _frame(regs)["LTM:LTM_Q2_2026"]

    assert ltm["acct:revenue"].note is None
    assert ltm["acct:cogs"].note == "differs from CP-1 stated"


def test_the_fixture_half_years_are_derived_periods() -> None:
    regs = example_registers()
    halves = {"H1_2025", "H1_2026"}

    assert all(p.component_period_ids for p in regs.periods if p.period_id in halves)
    rows = [a for a in regs.accounts if a.period_id in halves]
    assert rows
    assert {(a.source, a.calculation_status) for a in rows} == {(None, "CALCULATED")}


def test_a_register_with_only_an_ltm_row_keeps_it_unadopted() -> None:
    regs = _regs(ltm={"LTM_Q2_2026": {"revenue": 5}})

    columns = historical_columns(regs)

    assert [c.column_id for c in columns] == ["LTM:LTM_Q2_2026"]
    assert account_frame(regs, columns)["LTM:LTM_Q2_2026"]["acct:revenue"] == Cell(
        None, "COMPONENT_MISSING", stated=Decimal(5)
    )


def test_quarters_to_date_make_the_ytd_and_pytd_without_ytd_rows() -> None:
    values = {"Q1": 10, "Q2": 20, "Q3": 30, "Q4": 40}
    quarters = {f"{q}_2025": {"revenue": v} for q, v in values.items()}
    quarters |= {"Q1_2026": {"revenue": 11}, "Q2_2026": {"revenue": 21}}
    regs = _regs(quarters=quarters, fy={"FY2025": {"revenue": 100}})
    regs = replace(
        regs,
        periods=tuple(
            replace(p, day_count=None) if p.period_id == "Q1_2026" else p
            for p in regs.periods
        ),
    )

    columns = historical_columns(regs)
    frame = account_frame(regs, columns)

    by_id = {c.column_id: c for c in columns}
    assert (by_id["YTD:Q2_2026"].label, by_id["YTD:Q2_2026"].days) == (
        "YTD H1 26",
        None,
    )
    assert (by_id["PYTD:Q2_2025"].label, by_id["PYTD:Q2_2025"].days) == (
        "PYTD H1 25",
        181,
    )
    assert frame["YTD:Q2_2026"]["acct:revenue"].value == Decimal(32)
    assert frame["PYTD:Q2_2025"]["acct:revenue"].value == Decimal(30)
    assert frame["LTM:Q2_2026"]["acct:revenue"].value == Decimal(102)
    assert by_id["LTM:Q2_2026"].days is None


def test_an_anchor_quarter_without_a_fiscal_quarter_has_no_ytd() -> None:
    regs = _regs(quarters={"Q1_2026": {"revenue": 1}})
    regs = replace(regs, periods=(replace(regs.periods[0], fiscal_quarter=None),))

    columns = historical_columns(regs)

    assert [(c.column_id, c.label) for c in columns] == [
        ("Q:Q1_2026", "Q1_2026"),
        ("LTM:Q1_2026", "LTM Q1_2026"),
    ]


def test_an_undated_register_ltm_is_kept_unadopted() -> None:
    regs = _regs(
        fy={"FY2025": {"revenue": 400}},
        ltm={"LTM_Q2_2026": {"revenue": 420}},
    )
    fy, ltm = regs.periods
    regs = replace(regs, periods=(fy, replace(ltm, end_date=None)))

    columns = historical_columns(regs)

    assert [c.column_id for c in columns] == [
        "FY:FY2025",
        "LTM:FY2025",
        "LTM:LTM_Q2_2026",
    ]
    assert account_frame(regs, columns)["LTM:LTM_Q2_2026"]["acct:revenue"] == Cell(
        None, "COMPONENT_MISSING", stated=Decimal(420)
    )


def test_a_fiscal_year_reads_as_its_four_digit_year_however_written() -> None:
    regs = _regs(
        quarters={f"Q{n}_2025": {"revenue": n} for n in (1, 2, 3, 4)},
        fy={"FY2025": {"revenue": 10}},
        ytd={"H1_2025": {"revenue": 3}, "H1_2026": {"revenue": 5}},
    )
    written = {"FY2025": "FY2025", "H1_2025": "FY2025", "Q4_2025": "FY 2024/25"}
    regs = replace(
        regs,
        periods=tuple(
            replace(p, fiscal_year=written.get(p.period_id, p.fiscal_year))
            for p in regs.periods
        ),
    )

    columns = historical_columns(regs)
    frame = account_frame(regs, columns)

    assert [column.label for column in columns] == [
        "Q1 25",
        "Q2 25",
        "Q3 25",
        "Q4 25",
        "PYTD H1 25",
        "YTD H1 26",
        "FY25",
        "LTM Q2 26",
    ]
    assert frame["LTM:H1_2026"]["acct:revenue"].value == Decimal(12)
    assert ltm_frames(regs, columns)["Q:Q4_2025"]["acct:revenue"].value == Decimal(10)


def _rows_changed(
    regs: Cp1Registers, metric_id: str, period_ids: set[str], *, drop: bool
) -> Cp1Registers:
    """`regs` with the metric's rows for `period_ids` dropped, or nulled."""
    kept = []
    for a in regs.accounts:
        if a.metric_id != metric_id or a.period_id not in period_ids:
            kept.append(a)
        elif not drop:
            kept.append(replace(a, value=None))
    return replace(regs, accounts=tuple(kept))


def test_an_absent_row_is_not_sourced_and_a_null_row_not_stated_or_missing() -> None:
    regs = example_registers()
    columns = historical_columns(regs)

    def cell(changed: Cp1Registers, column_id: str, key: str) -> Cell:
        return account_frame(changed, columns)[column_id][key]

    q2 = {"Q2_2026"}
    dropped = _rows_changed(regs, "revenue", q2, drop=True)
    nulled = _rows_changed(regs, "revenue", q2, drop=False)
    assert cell(dropped, "Q:Q2_2026", "acct:revenue") == Cell(None, "NOT_SOURCED")
    assert cell(nulled, "Q:Q2_2026", "acct:revenue") == Cell(None, "NOT_STATED")
    # A flow with some components absent cannot be summed; with all absent it
    # is not sourced, CP-1's own figure kept.
    assert cell(dropped, "YTD:H1_2026", "acct:revenue").reason == "COMPONENT_MISSING"
    halves = _rows_changed(regs, "revenue", {"Q1_2026", "Q2_2026"}, drop=True)
    assert cell(halves, "YTD:H1_2026", "acct:revenue") == Cell(
        None, "NOT_SOURCED", stated=Decimal(5885)
    )
    assert cell(nulled, "YTD:H1_2026", "acct:revenue") == Cell(
        None, "COMPONENT_MISSING", stated=Decimal(5885)
    )
    # A balance: the first figure at the date; a null row there is missing.
    ending = {"Q2_2026", "H1_2026", "LTM_Q2_2026"}
    cash = "acct:cash_and_equivalents"
    one_null = _rows_changed(regs, "cash_and_equivalents", q2, drop=False)
    assert cell(one_null, "Q:Q2_2026", cash).value == 1000
    all_null = _rows_changed(regs, "cash_and_equivalents", ending, drop=False)
    assert cell(all_null, "Q:Q2_2026", cash) == Cell(None, "NOT_STATED")
    all_gone = _rows_changed(regs, "cash_and_equivalents", ending, drop=True)
    assert cell(all_gone, "Q:Q2_2026", cash) == Cell(None, "NOT_SOURCED")


def test_an_addback_without_a_row_for_a_period_counts_zero_in_a_sum() -> None:
    regs = example_registers()
    regs = replace(
        regs,
        addbacks=tuple(
            b
            for b in regs.addbacks
            if (b.addback_id, b.period_id) != ("transaction_costs", "Q2_2026")
        ),
    )
    columns = historical_columns(regs)
    frame = account_frame(regs, columns)
    key = "addback:transaction_costs"
    assert frame["Q:Q2_2026"][key] == Cell(None, "NOT_SOURCED")
    # H1 2026's own row (6) stands; the LTM is built from it.
    assert frame["YTD:H1_2026"][key].value == 6
    assert frame["LTM:LTM_Q2_2026"][key].value == 21
    halves = replace(
        regs,
        addbacks=tuple(
            b
            for b in regs.addbacks
            if (b.addback_id, b.period_id) != ("transaction_costs", "H1_2026")
        ),
    )
    resolved = account_frame(halves, historical_columns(halves))
    assert resolved["YTD:H1_2026"][key].value == 3
    assert resolved["LTM:LTM_Q2_2026"][key].value == 21 - 3
    # Q2 2026 has no row beside three stated quarters: never 12 + 3 + 3.
    assert ltm_frames(regs, columns)["Q:Q2_2026"][key] == Cell(
        None, "COMPONENT_MISSING", note=history.PARTLY_STATED
    )
    assert ltm_frames(regs, columns)["Q:Q2_2026"]["acct:revenue"].value == 11654


def _sparse_rows(regs: Cp1Registers, rows: dict[str, int]) -> Cp1Registers:
    """`regs` with transaction costs only in `rows` (period id: figure)."""
    kept = [b for b in regs.addbacks if b.addback_id != "transaction_costs"]
    model = next(b for b in regs.addbacks if b.addback_id == "transaction_costs")
    added = [
        replace(model, period_id=period_id, value=Decimal(value))
        for period_id, value in rows.items()
    ]
    return replace(regs, addbacks=(*kept, *added))


def _costs(regs: Cp1Registers) -> dict[str, Cell]:
    frame = account_frame(regs, historical_columns(regs))
    return {
        column_id: cells["addback:transaction_costs"]
        for column_id, cells in frame.items()
    }


def test_a_sparse_item_resolves_each_period_bottom_up() -> None:
    regs = example_registers()
    # (a) rows only for Q1 2025 and H1 2025: FY2025 is its quarters (3); the
    # PYTD is stated and the YTD has no row, so the LTM is never 3 + 0 - 3.
    probe = _costs(_sparse_rows(regs, {"Q1_2025": 3, "H1_2025": 3}))
    # Q3 and Q4 2025 have no row: nothing, and named.
    assert probe["FY:FY2025"] == Cell(
        Decimal(3),
        basis="CALCULATED",
        sources=probe["Q:Q1_2025"].sources,
        note="not stated, treated as zero (Q3_2025); "
        "not stated, treated as zero (Q4_2025)",
    )
    assert probe["LTM:LTM_Q2_2026"] == Cell(
        None, "COMPONENT_MISSING", note=history.PARTLY_STATED
    )
    assert probe["YTD:H1_2026"] == Cell(None, "NOT_SOURCED")
    assert probe["Q:Q2_2025"] == Cell(None, "NOT_SOURCED")
    # (b) only Q3 2025 and FY2025: the LTM keeps the 12, the YTD has none.
    third = _costs(_sparse_rows(regs, {"Q3_2025": 12, "FY2025": 12}))
    assert third["LTM:LTM_Q2_2026"].value == 12
    assert third["YTD:H1_2026"] == Cell(None, "NOT_SOURCED")
    assert third["PYTD:H1_2025"] == Cell(None, "NOT_SOURCED")
    # (c) only at the fiscal year: the FY's own figure, then the LTM from it.
    annual = _costs(_sparse_rows(regs, {"FY2025": 21}))
    assert annual["FY:FY2025"].value == 21
    assert annual["FY:FY2025"].basis == "REPORTED"
    assert annual["LTM:LTM_Q2_2026"].value == 21
    assert annual["FY:FY2024"] == Cell(None, "NOT_SOURCED")
    quarters = _costs(_sparse_rows(regs, {"Q1_2025": 3, "Q3_2025": 12, "Q4_2025": 5}))
    assert quarters["FY:FY2025"].value == 20
    assert quarters["Q:Q2_2025"] == Cell(None, "NOT_SOURCED")


def test_a_sparse_item_with_a_null_row_it_uses_is_component_missing() -> None:
    regs = _sparse_rows(example_registers(), {"Q1_2025": 3, "Q3_2025": 12})
    regs = replace(
        regs,
        addbacks=tuple(
            replace(b, value=None)
            if (b.addback_id, b.period_id) == ("transaction_costs", "Q3_2025")
            else b
            for b in regs.addbacks
        ),
    )
    costs = _costs(regs)
    assert costs["Q:Q3_2025"] == Cell(None, "NOT_STATED")
    assert costs["FY:FY2025"].reason == "COMPONENT_MISSING"
    assert costs["LTM:LTM_Q2_2026"].reason == "COMPONENT_MISSING"
    assert costs["PYTD:H1_2025"].value == 3


def test_financing_lines_are_sparse() -> None:
    regs = example_registers()
    regs = replace(
        regs,
        accounts=tuple(
            a
            for a in regs.accounts
            if a.metric_id != "lease_payments_in_financing"
            or a.period_id not in {"Q2_2026", "H1_2026"}
        ),
    )
    frame = account_frame(regs, historical_columns(regs))
    assert frame["YTD:H1_2026"]["acct:lease_payments_in_financing"].value == -4
    assert frame["Q:Q2_2026"]["acct:lease_payments_in_financing"] == Cell(
        None, "NOT_SOURCED"
    )


def _periods_changed(regs: Cp1Registers, *changed: PeriodRow) -> Cp1Registers:
    by_id = {p.period_id: p for p in changed}
    return replace(regs, periods=tuple(by_id.get(p.period_id, p) for p in regs.periods))


def test_a_sparse_period_resolves_only_through_dated_existing_parts() -> None:
    regs = _sparse_rows(
        example_registers(), {"Q1_2025": 3, "Q3_2025": 12, "Q4_2025": 5}
    )
    periods = {p.period_id: p for p in regs.periods}
    # A quarter without a start date (nor a day count to derive one) is not
    # within the year: its days are a gap, so Q1 + Q4 is not the year.
    undated = _periods_changed(
        regs, replace(periods["Q3_2025"], start_date=None, day_count=None)
    )
    assert _costs(undated)["FY:FY2025"] == Cell(
        None, "COMPONENT_MISSING", note=UNSPANNED
    )
    # A year without dates has no quarters; a quarter is never its own part.
    no_end = _periods_changed(regs, replace(periods["FY2025"], end_date=None))
    assert _costs(no_end)["FY:FY2025"] == Cell(None, "NOT_SOURCED")
    no_start = _periods_changed(
        regs, replace(periods["FY2025"], start_date=None, day_count=None)
    )
    assert _costs(no_start)["FY:FY2025"] == Cell(None, "NOT_SOURCED")
    assert _costs(regs)["Q:Q1_2025"].value == 3
    # Components that are not all periods do not span it; one naming itself
    # ends.
    ghost = _periods_changed(
        _sparse_rows(regs, {"Q1_2025": 3, "Q2_2025": 4}),
        replace(
            periods["H1_2025"], component_period_ids=("Q1_2025", "Q2_2025", "GHOST")
        ),
    )
    assert _costs(ghost)["PYTD:H1_2025"] == Cell(
        None, "COMPONENT_MISSING", note="components do not span the period"
    )
    cycle = _periods_changed(
        regs, replace(periods["H1_2025"], component_period_ids=("H1_2025",))
    )
    assert _costs(cycle)["PYTD:H1_2025"] == Cell(None, "NOT_SOURCED")


def test_a_flow_that_is_not_sparse_never_resolves_from_its_parts() -> None:
    regs = example_registers()
    regs = replace(
        regs,
        accounts=tuple(
            a
            for a in regs.accounts
            if (a.metric_id, a.period_id) != ("revenue", "FY2025")
        ),
    )
    frame = account_frame(regs, historical_columns(regs))
    assert frame["FY:FY2025"]["acct:revenue"] == Cell(None, "NOT_SOURCED")


def test_a_sparse_period_is_covered_greedily_by_its_longest_parts() -> None:
    regs = example_registers()
    # (a) H1 2025 and Q3 2025 only: FY2025 is H1 + Q3 + nothing for Q4; the
    # YTD has no row beside a stated PYTD, so the LTM is not built.
    probe = _costs(_sparse_rows(regs, {"H1_2025": 6, "Q3_2025": 12}))
    assert probe["FY:FY2025"].value == 18
    assert probe["PYTD:H1_2025"].value == 6
    assert probe["LTM:LTM_Q2_2026"].note == history.PARTLY_STATED
    # (b) a 9M row and Q4: FY = 9M + Q4.
    h1 = next(p for p in regs.periods if p.period_id == "H1_2025")
    nine = replace(
        h1,
        period_id="9M_2025",
        fiscal_quarter="3",
        end_date="2025-09-30",
        day_count=273,
        component_period_ids=(),
    )
    with_nine = replace(regs, periods=(*regs.periods, nine))
    nine_q4 = _costs(_sparse_rows(with_nine, {"9M_2025": 20, "Q4_2025": 5}))
    assert nine_q4["FY:FY2025"].value == 25
    # The longest part with a figure comes first: H1 (6) rather than Q1 (3).
    longest = _costs(_sparse_rows(regs, {"Q1_2025": 3, "H1_2025": 6}))
    assert longest["FY:FY2025"].value == 6
    # A longer period without a figure gives way to a shorter one that has one.
    ghost = replace(h1, component_period_ids=("GHOST",))
    hollow = _periods_changed(_sparse_rows(regs, {"Q1_2025": 3}), ghost)
    assert _costs(hollow)["PYTD:H1_2025"] == Cell(
        None, "COMPONENT_MISSING", note="components do not span the period"
    )
    assert _costs(hollow)["FY:FY2025"].value == 3
    # A period starting on the day the last part taken ends overlaps it.
    overlap = replace(
        h1,
        period_id="STUB_2025",
        fiscal_quarter=None,
        start_date="2025-06-30",
        day_count=1,
        component_period_ids=(),
    )
    stub = replace(regs, periods=(*regs.periods, overlap))
    covered = _costs(_sparse_rows(stub, {"H1_2025": 6, "STUB_2025": 100}))
    assert covered["FY:FY2025"].value == 6
    # (c) round 2's probe: rows for Q1 2025 and H1 2025 only; a stated PYTD
    # beside no YTD row, so the LTM is not built.
    first = _costs(_sparse_rows(regs, {"Q1_2025": 3, "H1_2025": 3}))
    assert first["FY:FY2025"].value == 3
    assert first["LTM:LTM_Q2_2026"].note == history.PARTLY_STATED


def test_a_sparse_own_row_wins_and_is_noted_where_its_parts_differ() -> None:
    regs = example_registers()
    agreed = _costs(regs)
    assert agreed["FY:FY2025"] == replace(agreed["FY:FY2025"], note=None)
    assert agreed["FY:FY2025"].value == 21
    restated = replace(
        regs,
        addbacks=tuple(
            replace(b, value=Decimal(30))
            if (b.addback_id, b.period_id) == ("transaction_costs", "FY2025")
            else b
            for b in regs.addbacks
        ),
    )
    costs = _costs(restated)
    assert costs["FY:FY2025"].value == 30
    assert costs["FY:FY2025"].basis == "REPORTED"
    assert costs["FY:FY2025"].note == "differs from components"
    assert costs["Q:Q4_2025"].note is None
    only_fy = _costs(_sparse_rows(regs, {"FY2025": 21}))
    assert only_fy["FY:FY2025"].note is None


def _without_periods(regs: Cp1Registers, *period_ids: str) -> Cp1Registers:
    """`regs` without those periods in its period register."""
    return replace(
        regs, periods=tuple(p for p in regs.periods if p.period_id not in period_ids)
    )


def _h1_2026_alone(rows: dict[str, int]) -> Cp1Registers:
    """Run 9b9e2b72's shape: H1 2026 names no components and no Q1 2026
    period exists, so no period covers January to March 2026."""
    regs = _sparse_rows(example_registers(), rows)
    h1 = next(p for p in regs.periods if p.period_id == "H1_2026")
    regs = _periods_changed(regs, replace(h1, component_period_ids=()))
    return _without_periods(regs, "Q1_2026")


def test_a_sparse_own_row_over_a_gap_is_never_compared_with_a_partial_cover() -> None:
    # Live run 9b9e2b72: stock comp H1 2026 YTD 47, Q2 2026 23, no Q1 2026
    # period. Q2 alone does not cover H1, so 47 is not "differs from" 23.
    h1 = _costs(_h1_2026_alone({"H1_2026": 47, "Q2_2026": 23}))["YTD:H1_2026"]
    assert (h1.value, h1.basis, h1.note) == (Decimal(47), "REPORTED", None)
    # A registered Q1 without a row is nothing, not a gap: Q1 + Q2 tile H1,
    # so the same rows disagree.
    tiled = _sparse_rows(example_registers(), {"H1_2026": 47, "Q2_2026": 23})
    h1_2026 = next(p for p in tiled.periods if p.period_id == "H1_2026")
    tiled = _periods_changed(tiled, replace(h1_2026, component_period_ids=()))
    noted = _costs(tiled)["YTD:H1_2026"]
    assert (noted.value, noted.note) == (Decimal(47), "differs from components")


def test_a_sparse_year_with_its_own_row_and_only_h1_below_keeps_its_row() -> None:
    # Live run 9b9e2b72: stock comp FY2025 95, H1 2025 50, no Q3 or Q4 2025.
    regs = _sparse_rows(example_registers(), {"FY2025": 95, "H1_2025": 50})
    fy = _costs(_without_periods(regs, "Q3_2025", "Q4_2025"))["FY:FY2025"]
    assert (fy.value, fy.basis, fy.note) == (Decimal(95), "REPORTED", None)


def test_a_sparse_period_without_a_row_over_a_gap_is_component_missing() -> None:
    regs = _sparse_rows(example_registers(), {"H1_2025": 50})
    gap = _without_periods(regs, "Q3_2025", "Q4_2025")
    # H1's 50 is not FY2025's figure: July to December has no period.
    assert _costs(gap)["FY:FY2025"] == Cell(None, "COMPONENT_MISSING", note=UNSPANNED)
    # Nor is Q2 2026's 23 H1 2026's.
    assert _costs(_h1_2026_alone({"Q2_2026": 23}))["YTD:H1_2026"] == Cell(
        None, "COMPONENT_MISSING", note=UNSPANNED
    )
    # A gap with no row on either side: nothing was sourced.
    empty = _without_periods(
        _sparse_rows(example_registers(), {"FY2024": 9}), "Q3_2025", "Q4_2025"
    )
    assert _costs(empty)["FY:FY2025"] == Cell(None, "NOT_SOURCED")


def test_a_complete_tiling_still_resolves_from_parts_and_notes_a_disagreement() -> None:
    regs = example_registers()
    quarters = {"Q1_2025": 3, "Q2_2025": 4, "Q3_2025": 12, "Q4_2025": 5}
    by_quarters = _costs(_sparse_rows(regs, quarters))["FY:FY2025"]
    assert (by_quarters.value, by_quarters.basis) == (Decimal(24), "CALCULATED")
    halves = {"H1_2025": 7, "Q3_2025": 12, "Q4_2025": 5}
    by_halves = _costs(_sparse_rows(regs, halves))["FY:FY2025"]
    assert (by_halves.value, by_halves.basis) == (Decimal(24), "CALCULATED")
    stated = _costs(_sparse_rows(regs, {**halves, "FY2025": 30}))["FY:FY2025"]
    assert (stated.value, stated.note) == (Decimal(30), "differs from components")
    agreed = _costs(_sparse_rows(regs, {**halves, "FY2025": 24}))["FY:FY2025"]
    assert (agreed.value, agreed.note) == (Decimal(24), None)


# One fiscal year's periods and the quarters (1 to 4) each runs over.
_SPANS = {
    "Q1_2025": (1, 1),
    "Q2_2025": (2, 2),
    "Q3_2025": (3, 3),
    "Q4_2025": (4, 4),
    "H1_2025": (1, 2),
    "9M_2025": (1, 3),
    "FY2025": (1, 4),
}


def _tiled(period_id: str, registered: set[str]) -> bool:
    """Whether other registered periods lie end to end over the period."""
    first, last = _SPANS[period_id]
    reached = {first}
    for quarter in range(first, last + 1):
        if quarter in reached:
            reached |= {
                _SPANS[other][1] + 1
                for other in registered - {period_id}
                if _SPANS[other][0] == quarter and _SPANS[other][1] <= last
            }
    return last + 1 in reached


@settings(deadline=None, max_examples=300)
@given(
    st.sets(st.sampled_from(sorted(_SPANS)), min_size=1),
    st.lists(st.integers(min_value=-40, max_value=40), min_size=4, max_size=4),
    st.sets(st.sampled_from(sorted(_SPANS))),
    st.sets(st.sampled_from(sorted(_SPANS))),
)
def test_a_sparse_figure_from_parts_comes_only_from_parts_that_tile_it(
    registered: set[str], amounts: list[int], zero_rows: set[str], dropped: set[str]
) -> None:
    # The item's true amount per quarter; every registered period with a
    # nonzero amount has its row (so a registered period without one is
    # truly nothing), except a period inside no other, whose row may be
    # dropped so that it resolves from its parts.
    truth = {
        pid: sum(amounts[q - 1] for q in range(_SPANS[pid][0], _SPANS[pid][1] + 1))
        for pid in registered
    }

    def outermost(pid: str) -> bool:
        lo, hi = _SPANS[pid]
        return not any(
            _SPANS[o][0] <= lo and hi <= _SPANS[o][1] for o in registered - {pid}
        )

    rows = {
        pid: value
        for pid, value in truth.items()
        if (value != 0 or pid in zero_rows) and not (pid in dropped and outermost(pid))
    }
    regs = _sparse_rows(example_registers(), rows)
    regs = replace(regs, periods=tuple(_period(pid, ()) for pid in sorted(registered)))
    resolved = _resolver(regs)
    for pid in sorted(registered):
        cell = resolved(pid)
        assert "differs from components" not in (cell.note or ""), (pid, cell)
        if pid in rows:
            assert cell.value == truth[pid], (pid, cell)
        elif cell.value is not None:
            assert _tiled(pid, registered), (pid, cell)
            assert cell.value == truth[pid], (pid, cell)


def _resolver(regs: Cp1Registers) -> Callable[[str], Cell]:
    """Transaction costs' resolved cell for a register period of `regs`."""
    empty = history._Series("sparse", {})
    series = history._series(regs).get("addback:transaction_costs", empty)
    register = history._register(regs)

    def resolved(period_id: str) -> Cell:
        with localcontext(CONTEXT):
            return history._resolved(series, register, period_id)

    return resolved


def _cover_case(rows: dict[str, int], *periods: PeriodRow) -> Callable[[str], Cell]:
    """Transaction costs in `rows` over FY2025 and `periods` only."""
    regs = _sparse_rows(example_registers(), rows)
    return _resolver(replace(regs, periods=(_period("FY2025", ()), *periods)))


def _covering(period_id: str, start: str, end: str, kind: str = "YTD") -> PeriodRow:
    return replace(_extra_period(period_id, start, end), period_type=kind)


def test_a_cover_reaches_the_last_day_of_the_period() -> None:
    most = _covering("MOST", "2025-01-01", "2025-12-30")
    last = _covering("LAST", "2025-12-31", "2025-12-31", "QUARTER")
    tiled = _cover_case({"MOST": 20, "LAST": 1}, most, last)("FY2025")
    assert (tiled.value, tiled.basis) == (Decimal(21), "CALCULATED")
    # Without a period for December 31 that day is a gap.
    assert _cover_case({"MOST": 20}, most)("FY2025") == Cell(
        None, "COMPONENT_MISSING", note=UNSPANNED
    )


def test_parts_with_the_same_dates_are_taken_in_register_order() -> None:
    h1 = _period("H1_2025", ())
    copy = replace(h1, period_id="H1X")
    rows = {"H1_2025": 6, "H1X": 7, "Q3_2025": 1}
    third, fourth = _period("Q3_2025", ()), _period("Q4_2025", ())
    assert _cover_case(rows, copy, h1, third, fourth)("FY2025").value == 8
    assert _cover_case(rows, h1, copy, third, fourth)("FY2025").value == 7


def test_a_part_whose_components_do_not_span_it_leaves_its_days_unknown() -> None:
    broken = _period("H1_2025", ("GHOST",))
    rest = (_period("Q3_2025", ()), _period("Q4_2025", ()))
    alone = _cover_case({"FY2024": 1}, broken, *rest)("FY2025")
    assert alone == Cell(None, "COMPONENT_MISSING", note=UNSPANNED)
    # A registered Q1 and Q2 without rows are nothing, and they tile H1's days.
    quarters = (_period("Q1_2025", ()), _period("Q2_2025", ()))
    tiled = _cover_case({"FY2024": 1}, broken, *quarters, *rest)("FY2025")
    assert tiled == Cell(None, "NOT_SOURCED")


def test_a_twin_without_a_row_is_never_nothing_over_the_period() -> None:
    twin = _covering("TWIN", "2025-01-01", "2025-12-31", "LTM")
    resolved = _cover_case({"Q2_2025": 5}, twin, _period("Q2_2025", ()))
    assert resolved("FY2025") == Cell(None, "COMPONENT_MISSING", note=UNSPANNED)


def _without_ltm_rows(regs: Cp1Registers) -> Cp1Registers:
    """`regs` without CP-1's LTM figures or pro forma: nothing stated to
    compare the host's LTM with."""
    accounts = tuple(a for a in regs.accounts if a.period_id != "LTM_Q2_2026")
    return replace(regs, accounts=accounts, pro_forma=())


def _written_positive(
    regs: Cp1Registers, period_ids: set[str], metric_ids: set[str]
) -> Cp1Registers:
    """`regs` with those accounts' figures written as their absolute value."""
    return replace(
        regs,
        accounts=tuple(
            replace(a, value=abs(a.value))
            if a.period_id in period_ids
            and a.metric_id in metric_ids
            and a.value is not None
            else a
            for a in regs.accounts
        ),
    )


def test_outflow_metrics_are_cp1s_sign_agnostic_outflows() -> None:
    assert OUTFLOW_METRICS == {
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
    # Cash taxes are signed: a refund is an inflow (CP-1's sign convention).
    assert "cash_taxes_paid" in FLOW_METRICS - OUTFLOW_METRICS
    assert OUTFLOW_METRICS <= FLOW_METRICS
    assert SIGN_NORMALISED == "sign normalised"


def test_an_outflow_row_written_positive_is_negative_before_any_sum() -> None:
    regs = _without_ltm_rows(example_registers())
    flows = {
        "capex_and_intangible_investment",
        "cash_interest_paid",
        "lease_payments_in_financing",
    }
    hostile = _written_positive(regs, {"Q1_2026", "Q2_2026"}, flows)
    # Without CP-1's own H1 figure, the sparse lease line sums the quarters.
    hostile = replace(
        hostile,
        accounts=tuple(
            a
            for a in hostile.accounts
            if (a.metric_id, a.period_id) != ("lease_payments_in_financing", "H1_2026")
        ),
    )
    columns = historical_columns(hostile)
    frame = account_frame(hostile, columns)
    base = account_frame(regs, historical_columns(regs))
    for metric in flows:
        key = f"acct:{metric}"
        for column_id in ("Q:Q2_2026", "YTD:H1_2026", "LTM:LTM_Q2_2026"):
            cell = frame[column_id][key]
            assert cell.value == base[column_id][key].value, (metric, column_id)
            assert cell.note == SIGN_NORMALISED, (metric, column_id)
        assert frame["FY:FY2025"][key] == base["FY:FY2025"][key]
        assert frame["FY:FY2025"][key].note is None
    assert frame["LTM:LTM_Q2_2026"]["acct:cash_interest_paid"].value == -862
    assert frame["Q:Q2_2026"]["acct:cash_interest_paid"].basis == "REPORTED"
    # A non-outflow and a zero outflow are never flipped.
    assert frame["Q:Q2_2026"]["acct:revenue"].note is None
    assert frame["Q:Q2_2026"]["acct:dividends_paid"] == Cell(
        Decimal(0),
        basis="REPORTED",
        sources=frame["Q:Q2_2026"]["acct:dividends_paid"].sources,
    )
    twelve = ltm_frames(hostile, columns)["Q:Q2_2026"]["acct:cash_interest_paid"]
    assert (twelve.value, twelve.note) == (Decimal(-862), SIGN_NORMALISED)


def _model_inputs(regs: Cp1Registers) -> ModelInputs:
    return ModelInputs(
        registers=regs,
        request=None,
        growth=example_growth(),
        slots=example_slots(),
        deck=example_deck(),
        exclude_unrealised=False,
    )


def _line_cell(model: CreditModel, line_id: str, column_id: str) -> Cell:
    columns = [c.column_id for c in model.columns]
    line = next(x for x in model.lines if x.line_id == line_id)
    return line.cells[columns.index(column_id)]


def test_the_audits_h1_2026_written_positive_keeps_the_ltm_coverage() -> None:
    # The audit's C1 probe: Q1 and Q2 2026 capex and cash interest written
    # positive read 681.5x interest coverage before the fix.
    regs = _without_ltm_rows(example_registers())
    flows = {"capex_and_intangible_investment", "cash_interest_paid"}
    hostile = _written_positive(regs, {"Q1_2026", "Q2_2026"}, flows)
    base = credit_model(_model_inputs(regs))
    model = credit_model(_model_inputs(hostile))
    ltm = "LTM:LTM_Q2_2026"
    interest = _line_cell(model, "cash_interest", ltm)
    assert (interest.value, interest.note) == (Decimal(-862), SIGN_NORMALISED)
    for line_id in (
        "capex",
        "fcf",
        "metric:interest_coverage_adjusted",
        "metric:capex_adjusted_coverage",
        "metric:fcf_to_debt",
    ):
        assert (
            _line_cell(model, line_id, ltm).value
            == _line_cell(base, line_id, ltm).value
        ), line_id
    coverage = _line_cell(model, "metric:interest_coverage_adjusted", ltm).value
    assert coverage is not None and Decimal("4.74") < coverage < Decimal("4.75")


def test_sixteen_nested_ltm_periods_work_out_each_period_once_per_item(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The audit's H1 probe: n LTM periods starting together, each a day
    longer, and an add-back with no FY2025 row, took 2^n before memoising.
    Counted, not timed (F621): a wrapper that delegates to the real
    `_parts` records each period an item's figure is worked out for."""
    regs = example_registers()
    extra = tuple(
        PeriodRow(
            period_id=f"X{i}",
            fiscal_year="2025",
            fiscal_quarter=None,
            period_type="LTM",
            start_date="2025-01-01",
            end_date=(date(2025, 1, 1) + timedelta(days=30 + i)).isoformat(),
            day_count=31 + i,
            currency="USD",
            unit="MILLIONS",
            component_period_ids=(),
        )
        for i in range(16)
    )
    regs = replace(
        regs,
        periods=regs.periods + extra,
        addbacks=tuple(
            b
            for b in regs.addbacks
            if (b.addback_id, b.period_id) != ("restructuring", "FY2025")
        ),
    )
    columns = historical_columns(regs)
    real = history._parts
    worked: list[tuple[int, str]] = []

    def counted(
        series: history._Series, register: history._Register, period: PeriodRow
    ) -> tuple[Cell, bool, Footing]:
        key = (id(series), period.period_id)
        # A period worked out twice for one item fails here, at once, where
        # the walk without the memo would go on for 2^n steps.
        assert key not in worked, key
        worked.append(key)
        return real(series, register, period)

    monkeypatch.setattr(history, "_parts", counted)
    frame = account_frame(regs, columns)

    assert frame["FY:FY2025"]["addback:restructuring"].value == 32
    # Each period once per sparse item: never again, however many covers
    # reach it.
    assert len(worked) == len(set(worked))
    sparse = {key for key, _ in worked}
    assert len(worked) <= len(sparse) * len(regs.periods)
    assert "X15" in {period for _, period in worked}


def _written(period: PeriodRow, field: str, written: str | int) -> PeriodRow:
    """`period` with a day count, or a start or end date, as written."""
    if isinstance(written, int):
        return replace(period, day_count=written)
    if field == "start_date":
        return replace(period, start_date=written)
    return replace(period, end_date=written)


@pytest.mark.parametrize(
    ("period_id", "field", "written"),
    [
        ("FY2025", "end_date", "31/12/2025"),
        ("FY2025", "end_date", "2025-12-31T00:00:00"),
        ("Q1_2026", "end_date", "20260331"),
        ("FY2025", "end_date", "9999-12-31"),
        ("FY2025", "start_date", "0001-01-01"),
        ("H1_2026", "start_date", "2026-02-30"),
        ("Q2_2026", "day_count", 800000),
        ("Q2_2026", "day_count", -90),
        ("Q2_2026", "day_count", 0),
        ("LTM_Q2_2026", "end_date", "30 June 2026"),
    ],
)
def test_a_date_or_day_count_that_is_not_one_never_raises(
    period_id: str, field: str, written: str | int
) -> None:
    # The audit's H2 probes, built directly (the parser refuses them).
    regs = example_registers()
    regs = replace(
        regs,
        periods=tuple(
            _written(p, field, written) if p.period_id == period_id else p
            for p in regs.periods
        ),
    )
    columns = historical_columns(regs)
    frame = account_frame(regs, columns)
    assert set(frame) == {column.column_id for column in columns}
    assert set(ltm_frames(regs, columns)) <= set(frame)
    # An end date that is not `YYYY-MM-DD` is no date: never the latest.
    if written != "9999-12-31":
        assert any(c.kind == "LTM" and c.end_date == "2026-06-30" for c in columns)


_SPLIT_H1 = "components do not span the period"


@pytest.mark.parametrize(
    "components",
    [
        ("Q1_2026", "Q1_2026", "Q2_2026"),
        ("Q2_2025", "Q2_2026"),
        ("FY2025",),
        ("Q2_2026", "Q1_2026", "GHOST"),
        ("Q2_2026",),
        (),
    ],
)
def test_a_derived_period_whose_components_do_not_span_it_is_missing(
    components: tuple[str, ...],
) -> None:
    # The audit's H3 probes: duplicate, foreign-year and 12-month components
    # once summed into the YTD and the LTM silently.
    regs = _without_ltm_rows(example_registers())
    regs = replace(
        regs, accounts=tuple(a for a in regs.accounts if a.period_id != "H1_2026")
    )
    changed = replace(
        regs,
        periods=tuple(
            replace(p, component_period_ids=components)
            if p.period_id == "H1_2026"
            else p
            for p in regs.periods
        ),
    )
    frame = account_frame(changed, historical_columns(changed))
    if not components:  # no components: CP-1's own row, here none
        assert frame["YTD:H1_2026"]["acct:revenue"] == Cell(None, "NOT_SOURCED")
        return
    for column_id in ("YTD:H1_2026", "LTM:LTM_Q2_2026"):
        assert frame[column_id]["acct:revenue"] == Cell(
            None, "COMPONENT_MISSING", note=UNSPANNED
        ), column_id
    assert UNSPANNED == _SPLIT_H1
    # Balances are read at the end date, not summed.
    assert frame["LTM:LTM_Q2_2026"]["acct:total_debt"].value == 13846


def test_components_in_any_order_that_span_the_period_are_summed() -> None:
    regs = _without_ltm_rows(example_registers())
    swapped = replace(
        regs,
        periods=tuple(
            replace(p, component_period_ids=("Q2_2026", "Q1_2026"))
            if p.period_id == "H1_2026"
            else p
            for p in regs.periods
        ),
    )
    frame = account_frame(swapped, historical_columns(swapped))
    assert frame["YTD:H1_2026"]["acct:revenue"].value == 5885
    assert frame["LTM:LTM_Q2_2026"]["acct:revenue"].value == 11654


def _relabelled(regs: Cp1Registers, years: dict[str, str]) -> Cp1Registers:
    return replace(
        regs,
        periods=tuple(
            replace(p, fiscal_year=years[p.period_id]) if p.period_id in years else p
            for p in regs.periods
        ),
    )


def test_two_year_fiscal_spellings_read_as_the_end_year_throughout() -> None:
    # The audit's H3 probe: quarters "FY2025/26" and years "FY2025/2026"
    # once read as 2025 and 2026, so the LTM took the wrong fiscal year.
    regs = _without_ltm_rows(example_registers())
    spelt = {"2024": "FY2023/24", "2025": "FY2024/25", "2026": "FY2025/26"}
    years = {
        p.period_id: spelt[p.fiscal_year]
        for p in regs.periods
        if p.period_type != "FY" and p.fiscal_year in spelt
    }
    years |= {"FY2023": "FY2022/2023", "FY2024": "FY2023/2024", "FY2025": "FY2024/2025"}
    changed = _relabelled(regs, years)
    columns = historical_columns(changed)
    frame = account_frame(changed, columns)
    base = account_frame(regs, historical_columns(regs))
    assert [c.label for c in columns] == [c.label for c in historical_columns(regs)]
    for key in ("acct:revenue", "acct:cash_interest_paid", "acct:adjusted_ebitda"):
        assert frame["LTM:LTM_Q2_2026"][key].value == (
            base["LTM:LTM_Q2_2026"][key].value
        )


def test_an_ltm_whose_fiscal_year_does_not_meet_its_ytd_is_missing() -> None:
    regs = _without_ltm_rows(example_registers())
    # FY2024 labelled 2025 and FY2025 labelled 2024: the LTM's "prior" year
    # ends a year before the YTD starts.
    swapped = _relabelled(regs, {"FY2024": "2025", "FY2025": "2024"})
    frame = account_frame(swapped, historical_columns(swapped))
    assert frame["LTM:LTM_Q2_2026"]["acct:revenue"] == Cell(
        None, "COMPONENT_MISSING", note=UNSPANNED
    )
    assert frame["LTM:LTM_Q2_2026"]["acct:total_debt"].value == 13846
    # A PYTD that does not start with the fiscal year, by more than a week.
    late = replace(
        regs,
        periods=tuple(
            replace(
                p,
                start_date="2025-01-09",
                day_count=173,
                component_period_ids=(),
            )
            if p.period_id == "H1_2025"
            else p
            for p in regs.periods
        ),
    )
    # A day late is within a week of a year earlier, so it is the PYTD; but
    # it does not start with the fiscal year (that meeting is exact), so the
    # LTM is not built.
    day_late = replace(
        regs,
        periods=tuple(
            replace(p, start_date="2025-01-02", day_count=180, component_period_ids=())
            if p.period_id == "H1_2025"
            else p
            for p in regs.periods
        ),
    )
    day_late_columns = historical_columns(day_late)
    assert [c.column_id for c in day_late_columns if c.kind == "PYTD"] == [
        "PYTD:H1_2025"
    ]
    assert account_frame(day_late, day_late_columns)["LTM:LTM_Q2_2026"][
        "acct:revenue"
    ] == Cell(None, "COMPONENT_MISSING", note=UNSPANNED)
    # It is not H1 2026's months a year earlier, so it is never the PYTD:
    # the quarters to date are, and the LTM is built from them.
    late_columns = historical_columns(late)
    assert [c.column_id for c in late_columns if c.kind == "PYTD"] == ["PYTD:Q2_2025"]
    late_frame = account_frame(late, late_columns)
    revenue = {k: _value(late_frame[k]["acct:revenue"]) for k in late_frame}
    assert revenue["LTM:LTM_Q2_2026"] == (
        revenue["FY:FY2025"] + revenue["YTD:H1_2026"] - revenue["PYTD:Q2_2025"]
    )
    # Without those quarters there is no PYTD, and the LTM is not built.
    alone = replace(
        late,
        periods=tuple(
            p for p in late.periods if p.period_id not in {"Q1_2025", "Q2_2025"}
        ),
    )
    alone_columns = historical_columns(alone)
    assert "PYTD" not in [c.kind for c in alone_columns]
    assert account_frame(alone, alone_columns)["LTM:LTM_Q2_2026"][
        "acct:revenue"
    ] == Cell(None, "COMPONENT_MISSING", note=UNSPANNED)
    # An undated fiscal year cannot be shown to meet it either.
    undated = replace(
        regs,
        periods=tuple(
            replace(p, start_date=None, day_count=None)
            if p.period_id == "FY2025"
            else p
            for p in regs.periods
        ),
    )
    undated_frame = account_frame(undated, historical_columns(undated))
    assert undated_frame["LTM:LTM_Q2_2026"]["acct:revenue"].reason == (
        "COMPONENT_MISSING"
    )
    # Nor does an undated PYTD start "with" an undated year.
    both = replace(
        undated,
        periods=tuple(
            replace(p, start_date=None, day_count=None, component_period_ids=())
            if p.period_id == "H1_2025"
            else p
            for p in undated.periods
        ),
    )
    both_frame = account_frame(both, historical_columns(both))
    assert both_frame["LTM:LTM_Q2_2026"]["acct:revenue"] == Cell(
        None, "COMPONENT_MISSING", note=UNSPANNED
    )


def test_a_sparse_period_takes_an_equal_twins_own_row_and_nothing_more() -> None:
    regs = example_registers()
    twin = PeriodRow(
        period_id="LTM_Q4_2025",
        fiscal_year="2025",
        fiscal_quarter="4",
        period_type="LTM",
        start_date="2025-01-01",
        end_date="2025-12-31",
        day_count=365,
        currency="USD",
        unit="MILLIONS",
        component_period_ids=(),
    )
    model = next(b for b in regs.addbacks if b.addback_id == "transaction_costs")
    regs = replace(
        regs,
        periods=(*regs.periods, twin),
        addbacks=(
            *(b for b in regs.addbacks if b.addback_id != "transaction_costs"),
            replace(model, period_id="LTM_Q4_2025", value=Decimal(40)),
            AddbackRow(
                "transaction_costs",
                model.label,
                model.classification,
                model.realization_status,
                model.display_priority,
                "Q1_2025",
                Decimal(3),
                None,
            ),
        ),
    )
    costs = _costs(regs)
    # FY2025 has no row: its twin's own row covers it, not the twin's parts.
    assert costs["FY:FY2025"].value == 40
    frame = account_frame(regs, historical_columns(regs))
    assert frame["FY:FY2025"]["addback:transaction_costs"].value == 40


def test_every_register_row_keeps_its_source() -> None:
    regs = example_registers()
    cells = account_frame(regs, historical_columns(regs))["Q:Q2_2026"]
    rows = {
        "bu:las_vegas": next(
            s
            for s in regs.segments
            if (s.segment_id, s.period_id) == ("las_vegas", "Q2_2026")
        ).source,
        "addback:restructuring": next(
            b
            for b in regs.addbacks
            if (b.addback_id, b.period_id) == ("restructuring", "Q2_2026")
        ).source,
        "kpi:lv_room_nights": next(
            k
            for k in regs.kpis
            if (k.kpi_id, k.period_id) == ("lv_room_nights", "Q2_2026")
        ).source,
    }
    for key, source in rows.items():
        assert source is not None
        assert cells[key].sources == (source,), key


def test_a_sparse_own_row_written_positive_keeps_its_note() -> None:
    regs = _written_positive(
        example_registers(), {"H1_2026"}, {"lease_payments_in_financing"}
    )
    cell = account_frame(regs, historical_columns(regs))["YTD:H1_2026"][
        "acct:lease_payments_in_financing"
    ]
    assert (cell.value, cell.note) == (Decimal(-8), SIGN_NORMALISED)


def _extra_period(
    period_id: str, start: str, end: str, components: tuple[str, ...] = ()
) -> PeriodRow:
    return PeriodRow(
        period_id=period_id,
        fiscal_year="2025",
        fiscal_quarter=None,
        period_type="PERIOD_END",
        start_date=start,
        end_date=end,
        day_count=None,
        currency="USD",
        unit="MILLIONS",
        component_period_ids=components,
    )


def test_a_one_day_component_spans_its_day() -> None:
    regs = _regs(fy={"FY2025": {"revenue": 10}})
    regs = replace(
        regs,
        periods=(
            *(replace(p, component_period_ids=("A", "B")) for p in regs.periods),
            _extra_period("A", "2025-01-01", "2025-12-30"),
            _extra_period("B", "2025-12-31", "2025-12-31"),
        ),
        accounts=(
            *regs.accounts,
            AccountRow("revenue", "A", Decimal(7), "VERIFIED", None),
            AccountRow("revenue", "B", Decimal(3), "VERIFIED", None),
        ),
    )
    cell = _frame(regs)["FY:FY2025"]["acct:revenue"]
    assert (cell.value, cell.stated, cell.note) == (Decimal(10), Decimal(10), None)


def test_a_cover_part_resolves_through_its_components_but_a_twin_does_not() -> None:
    regs = _sparse_rows(example_registers(), {"Q1_2025": 3, "M2": 4, "H2X": 9})
    periods = {p.period_id: p for p in regs.periods}
    # H1 2025 names Q1 and M2, a period no cover is chosen from: resolving
    # H1 reaches M2's figure; taking only H1's own row (none) would not.
    halves = _periods_changed(
        regs, replace(periods["H1_2025"], component_period_ids=("Q1_2025", "M2"))
    )
    halves = replace(
        halves,
        periods=(*halves.periods, _extra_period("M2", "2025-04-01", "2025-06-30")),
    )
    assert _costs(halves)["FY:FY2025"].value == 7
    # FY2025's twin, with the same dates and no row of its own, gives
    # nothing: its components (H1 and H2X) are not read through it.
    twin = replace(
        _extra_period("TWIN", "2025-01-01", "2025-12-31", ("H1_2025", "H2X")),
        period_type="LTM",
    )
    twinned = replace(
        halves,
        periods=(
            *halves.periods,
            twin,
            _extra_period("H2X", "2025-07-01", "2025-12-31"),
        ),
    )
    assert _costs(twinned)["FY:FY2025"].value == 7
    # A longer part whose parts have no row (none of them a quarter's dates)
    # gives way to a shorter one.
    hollow = _periods_changed(
        _sparse_rows(example_registers(), {"Q1_2025": 3}),
        replace(periods["H1_2025"], component_period_ids=("A1", "A2")),
    )
    hollow = replace(
        hollow,
        periods=(
            *hollow.periods,
            _extra_period("A1", "2025-01-01", "2025-02-28"),
            _extra_period("A2", "2025-03-01", "2025-06-30"),
        ),
    )
    assert _costs(hollow)["PYTD:H1_2025"] == Cell(None, "NOT_SOURCED")
    assert _costs(hollow)["FY:FY2025"].value == 3


def test_an_unbuilt_ltm_keeps_cp1s_figure_as_stated() -> None:
    regs = _relabelled(example_registers(), {"FY2024": "2025", "FY2025": "2024"})
    frame = account_frame(regs, historical_columns(regs))
    assert frame["LTM:LTM_Q2_2026"]["acct:revenue"] == Cell(
        None, "COMPONENT_MISSING", stated=Decimal(11654), note=UNSPANNED
    )


def test_a_label_takes_the_four_digit_year_however_the_text_ends() -> None:
    regs = _relabelled(example_registers(), {"FY2025": "FY2025 (restated)"})
    labels = {c.column_id: c.label for c in historical_columns(regs)}
    assert labels["FY:FY2025"] == "FY25"


def test_quarters_to_date_meet_the_year_by_their_days_without_a_start() -> None:
    values = {"Q1": 10, "Q2": 20, "Q3": 30, "Q4": 40}
    quarters = {f"{q}_2025": {"revenue": v} for q, v in values.items()}
    quarters |= {"Q1_2026": {"revenue": 11}, "Q2_2026": {"revenue": 21}}
    regs = _regs(quarters=quarters, fy={"FY2025": {"revenue": 100}})
    regs = replace(
        regs,
        periods=tuple(
            replace(p, start_date=None) if p.period_id == "Q1_2026" else p
            for p in regs.periods
        ),
    )
    frame = _frame(regs)
    assert frame["LTM:Q2_2026"]["acct:revenue"].value == 100 + 32 - 30


def test_a_period_without_a_start_date_starts_its_day_count_before_its_end() -> None:
    regs = example_registers()
    columns = historical_columns(regs)
    whole = account_frame(regs, columns)
    undated = replace(
        regs,
        periods=tuple(
            replace(p, start_date=None)
            if p.period_id in {"Q2_2026", "H1_2026", "FY2025"}
            else p
            for p in regs.periods
        ),
    )
    frame = account_frame(undated, historical_columns(undated))

    for column in ("YTD:H1_2026", "LTM:LTM_Q2_2026", "FY:FY2025"):
        assert frame[column]["acct:revenue"] == whole[column]["acct:revenue"]
    assert frame["YTD:H1_2026"]["acct:revenue"].reason is None
    # Sparse items cover a period from its derived start too.
    sparse = _sparse_rows(undated, {"Q1_2025": 3, "Q3_2025": 12, "Q4_2025": 5})
    assert _costs(sparse)["FY:FY2025"].value == 20


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


def test_a_ytd_built_from_quarters_with_a_gap_does_not_meet_the_year() -> None:
    regs = example_registers()
    built = replace(
        regs, periods=tuple(p for p in regs.periods if p.period_id != "H1_2026")
    )
    whole = account_frame(built, historical_columns(built))
    assert whole["LTM:LTM_Q2_2026"]["acct:revenue"].value == 11654
    gap = replace(
        built,
        periods=tuple(
            replace(p, start_date="2026-04-02", day_count=90)
            if p.period_id == "Q2_2026"
            else p
            for p in built.periods
        ),
    )
    frame = account_frame(gap, historical_columns(gap))
    assert frame["LTM:LTM_Q2_2026"]["acct:revenue"] == Cell(
        None, "COMPONENT_MISSING", stated=Decimal(11654), note=UNSPANNED
    )


def _unlabelled(regs: Cp1Registers) -> Cp1Registers:
    """The registers with every YTD period's fiscal quarter left out."""
    return replace(
        regs,
        periods=tuple(
            replace(p, fiscal_quarter=None) if p.period_type == "YTD" else p
            for p in regs.periods
        ),
    )


def _halves() -> Cp1Registers:
    """Run 9b9e2b72's shape: Q2 25 and Q2 26, FY24 and FY25, H1 25 and H1 26."""
    return _regs(
        quarters={
            "Q2_2025": {"revenue": "101.5", "cogs": -40},
            "Q2_2026": {"revenue": "111.25", "cogs": -44},
        },
        fy={
            "FY2024": {"revenue": 380, "cogs": -150},
            "FY2025": {"revenue": "400.5", "cogs": -160},
        },
        ytd={
            "H1_2025": {"revenue": "200.25", "cogs": -79},
            "H1_2026": {"revenue": "210.5", "cogs": -83},
        },
    )


def test_an_unlabelled_ytd_finds_its_prior_year_ytd_by_its_dates() -> None:
    regs = _unlabelled(_halves())

    columns = historical_columns(regs)
    frame = account_frame(regs, columns)

    assert [c.column_id for c in columns] == [
        "Q:Q2_2025",
        "Q:Q2_2026",
        "PYTD:H1_2025",
        "YTD:H1_2026",
        "FY:FY2024",
        "FY:FY2025",
        "LTM:H1_2026",
    ]
    assert columns[2].label == "PYTD H1 25"
    ltm = frame["LTM:H1_2026"]
    revenue = Decimal("400.5") + Decimal("210.5") - Decimal("200.25")
    assert ltm["acct:revenue"] == Cell(
        revenue, basis="CALCULATED", sources=ltm["acct:revenue"].sources
    )
    assert revenue == Decimal("410.75")
    assert ltm["acct:cogs"].value == Decimal(-164)
    assert frame["PYTD:H1_2025"]["acct:revenue"].value == Decimal("200.25")


def test_a_labelled_register_still_finds_its_prior_year_ytd_by_label() -> None:
    labelled = _halves()
    columns = historical_columns(labelled)
    assert [c.label for c in columns][2:4] == ["PYTD H1 25", "YTD H1 26"]
    unlabelled = _unlabelled(labelled)
    ltm = account_frame(labelled, columns)["LTM:H1_2026"]["acct:revenue"]
    dated = account_frame(unlabelled, historical_columns(unlabelled))
    assert ltm == dated["LTM:H1_2026"]["acct:revenue"]

    # A same-dated YTD without a label is a second candidate by dates only:
    # the label decides, so it is no ambiguity.
    h1 = next(p for p in labelled.periods if p.period_id == "H1_2025")
    twin = replace(h1, period_id="H1_2025_R", fiscal_quarter=None)
    restated = AccountRow("revenue", "H1_2025_R", Decimal(1), "VERIFIED", None)
    both = replace(
        labelled,
        periods=(*labelled.periods, twin),
        accounts=(*labelled.accounts, restated),
    )
    assert historical_columns(both)[2].column_id == "PYTD:H1_2025"
    assert (
        account_frame(both, historical_columns(both))["LTM:H1_2026"]["acct:revenue"]
        == ltm
    )


def _priors(regs: Cp1Registers, *priors: PeriodRow, keep: bool) -> Cp1Registers:
    """The registers with `priors` added, each with H1 2025's account rows;
    H1 2025 itself kept only with `keep`."""
    h1 = [a for a in regs.accounts if a.period_id == "H1_2025"]
    copied = tuple(replace(a, period_id=p.period_id) for p in priors for a in h1)
    return replace(
        regs,
        periods=(
            *(p for p in regs.periods if keep or p.period_id != "H1_2025"),
            *priors,
        ),
        accounts=(
            *(a for a in regs.accounts if keep or a.period_id != "H1_2025"),
            *copied,
        ),
    )


def _ambiguous_cases() -> dict[str, Cp1Registers]:
    regs = _unlabelled(_halves())
    h1 = next(p for p in regs.periods if p.period_id == "H1_2025")
    twin = replace(h1, period_id="H1_2025_R")
    q1 = replace(h1, period_id="Q1YTD_2025", end_date="2025-03-31", day_count=90)
    nine = replace(h1, period_id="9M_2025", end_date="2025-09-30", day_count=273)
    # More than `SLACK_DAYS` off H1 2026's months a year earlier.
    late = replace(h1, period_id="H1_2025_L", start_date="2025-01-09", day_count=173)
    short = replace(h1, period_id="H1_2025_S", end_date="2025-06-22", day_count=173)
    undated = replace(
        h1, period_id="H1_2025_U", start_date=None, end_date=None, day_count=None
    )
    return {
        "two candidates": _priors(regs, twin, keep=True),
        "spans differ (Q1)": _priors(regs, q1, keep=False),
        "spans differ (9M)": _priors(regs, nine, keep=False),
        "starts on another day": _priors(regs, late, keep=False),
        "ends on another day": _priors(regs, short, keep=False),
        "no dates": _priors(regs, undated, keep=False),
        "no dates beside a match": _priors(regs, undated, keep=True),
        "the YTD without a start": replace(
            regs,
            periods=tuple(
                replace(p, start_date=None, day_count=None)
                if p.period_id == "H1_2026"
                else p
                for p in regs.periods
            ),
        ),
    }


@pytest.mark.parametrize("case", list(_ambiguous_cases()))
def test_a_prior_year_ytd_the_dates_leave_ambiguous_is_no_pytd(case: str) -> None:
    regs = _ambiguous_cases()[case]

    columns = historical_columns(regs)
    frame = account_frame(regs, columns)

    quarters = ["Q:Q2_2025", "Q:Q2_2026"]
    if case == "spans differ (9M)":  # an unlabelled 9M is three quarters
        quarters.insert(1, "Q:FY2025-9M_2025")
    assert [c.column_id for c in columns if c.kind == "QUARTER"] == quarters
    assert [c.kind for c in columns if c.kind != "QUARTER"] == [
        "YTD",
        "FY",
        "FY",
        "LTM",
    ]
    for key in ("acct:revenue", "acct:cogs"):
        assert frame["LTM:H1_2026"][key] == Cell(
            None, "COMPONENT_MISSING", note=UNSPANNED
        )
    # The YTD itself is untouched.
    assert frame["YTD:H1_2026"]["acct:revenue"].value == Decimal("210.5")


def test_without_a_prior_year_ytd_the_ltm_is_missing_un_noted() -> None:
    regs = _priors(_unlabelled(_halves()), keep=False)
    # A YTD of the same year is no candidate for the prior year's.
    h1 = next(p for p in regs.periods if p.period_id == "H1_2026")
    q1 = replace(h1, period_id="Q1YTD_2026", end_date="2026-03-31", day_count=90)
    # Nor is one ending on the YTD's first day: it is not before the YTD.
    overlap = replace(
        h1,
        period_id="DEC_JAN",
        start_date="2025-12-01",
        end_date="2026-01-01",
        day_count=32,
    )
    for extra in ((), (q1,), (overlap,)):
        case = replace(regs, periods=(*regs.periods, *extra))
        frame = account_frame(case, historical_columns(case))
        assert frame["LTM:H1_2026"]["acct:revenue"] == Cell(None, "COMPONENT_MISSING")


def _fiscal(period_id: str, kind: str, year: int, first: date, last: date) -> PeriodRow:
    return PeriodRow(
        period_id=period_id,
        fiscal_year=str(year),
        fiscal_quarter=None,
        period_type=kind,
        start_date=first.isoformat(),
        end_date=last.isoformat(),
        day_count=(last - first).days + 1,
        currency="USD",
        unit="MILLIONS",
        component_period_ids=(),
    )


def _month(year: int, month: int) -> date:
    """The first day of the month, `month` counted on past December."""
    return date(year + (month - 1) // 12, (month - 1) % 12 + 1, 1)


@settings(deadline=None, max_examples=150)
@given(
    start=st.integers(min_value=1, max_value=12),
    months=st.sampled_from((3, 6, 9)),
    decoy=st.sampled_from((3, 6, 9)),
    year=st.integers(min_value=1990, max_value=2190),
    figures=st.tuples(*(st.integers(-(10**6), 10**6) for _ in range(4))),
)
def test_the_prior_year_ytd_by_dates_is_the_one_of_the_same_months(
    start: int,
    months: int,
    decoy: int,
    year: int,
    figures: tuple[int, int, int, int],
) -> None:
    """Any fiscal-year start month (a February month end included) and YTD
    length: the PYTD found is the YTD of the same months a year before, never
    the decoy of another length, and the LTM is FY + YTD - PYTD exactly."""
    fy_first = _month(year, start)
    ytd_first = _month(year, start + 12)
    day = timedelta(days=1)
    periods: tuple[PeriodRow, ...] = (
        _fiscal("FY", "FY", year, fy_first, ytd_first - day),
        _fiscal("PRIOR", "YTD", year, fy_first, _month(year, start + months) - day),
        _fiscal(
            "YTD", "YTD", year + 1, ytd_first, _month(year, start + 12 + months) - day
        ),
    )
    if decoy != months:
        decoy_last = _month(year, start + decoy) - day
        periods = (*periods, _fiscal("DECOY", "YTD", year, fy_first, decoy_last))
    tenths = [Decimal(f) / 10 for f in figures]
    accounts = tuple(
        AccountRow("revenue", period.period_id, value, "VERIFIED", None)
        for period, value in zip(periods, tenths, strict=False)
    )
    regs = Cp1Registers(
        periods=periods,
        accounts=accounts,
        addbacks=(),
        segments=(),
        kpis=(),
        facilities=(),
        pro_forma=(),
        currency="USD",
        unit="MILLIONS",
    )

    columns = historical_columns(regs)
    frame = account_frame(regs, columns)

    assert [c.column_id for c in columns if c.kind == "PYTD"] == ["PYTD:PRIOR"]
    fy, prior, ytd, _ = tenths
    assert frame["LTM:YTD"]["acct:revenue"].value == fy + ytd - prior


def test_a_labelled_ytd_falls_back_to_quarters_past_a_ytd_of_other_months() -> None:
    """A labelled H1 with no labelled prior H1 and a prior 9M of other months:
    the prior year's quarters still build the PYTD, and the LTM is un-noted."""
    regs = _regs(
        quarters={"Q1_2025": {"revenue": 3}, "Q2_2025": {"revenue": 4}},
        fy={"FY2025": {"revenue": 20}},
        ytd={"9M_2025": {"revenue": 12}, "H1_2026": {"revenue": 9}},
    )

    columns = historical_columns(regs)
    ltm = account_frame(regs, columns)["LTM:H1_2026"]["acct:revenue"]

    assert [c.column_id for c in columns if c.kind == "PYTD"] == ["PYTD:Q2_2025"]
    assert (ltm.value, ltm.note) == (Decimal(22), None)


def test_whole_months_reads_a_span_from_a_first_day_to_a_last_day() -> None:
    whole = history._whole_months
    jan, feb = date(2024, 1, 1).toordinal(), date(2024, 2, 29).toordinal()
    assert whole((jan, feb)) == (jan, 2)
    assert whole((jan, date(2024, 12, 31).toordinal())) == (jan, 12)
    september = date(2023, 9, 1).toordinal()
    assert whole((september, feb)) == (september, 6)
    assert whole((1, 31)) == (1, 1)  # 1 January of year 1
    assert whole((feb, jan)) is None  # ends before it starts
    assert whole((0, 31)) is None  # no such day
    assert whole((-30, 31)) is None
    december = date(9999, 12, 1).toordinal()
    assert whole((december, date.max.toordinal())) is None  # no following day
    assert whole(None) is None


def test_a_span_is_whole_months_within_a_week_either_way() -> None:
    """52/53-week calendars: the day after the span ends lies within
    `SLACK_DAYS` of its first day plus n months; eight days is too many."""
    whole = history._whole_months
    assert history.SLACK_DAYS == 7
    first = date(2024, 2, 4).toordinal()  # a Sunday; + 3 months is 4 May
    may = date(2024, 5, 4).toordinal()
    for off in range(-7, 8):
        assert whole((first, may - 1 + off)) == (first, 3), off
    # Eight days off on a span of no whole number of weeks (82 days).
    assert whole((first, may - 1 - 8)) is None
    assert whole((first, may - 1 + 9)) is None  # nine days off: 99 days
    # A 13-week quarter, a 14-week fourth quarter and a 53-week year.
    assert whole((first, first + 90)) == (first, 3)
    november = date(2024, 11, 3).toordinal()
    assert whole((november, november + 97)) == (november, 3)
    assert whole((first, first + 370)) == (first, 12)
    assert whole((first, first + 363)) == (first, 12)
    # A few days are no month; a month's first day on the 31st is clamped.
    assert whole((first, first + 6)) is None
    last = date(2024, 1, 31).toordinal()
    assert whole((last, date(2024, 2, 28).toordinal())) == (last, 1)
    # From the calendar's last month nothing is n months later.
    end = date(9999, 12, 20).toordinal()
    assert whole((end, end + 5)) is None
    assert history._plus_months(date(9999, 12, 1), 1) is None
    assert history._plus_months(date(1, 1, 1), -1) is None
    assert history._plus_months(date(2024, 3, 31), -1) == date(2024, 2, 29)
    assert history._plus_months(date(9999, 1, 31), 1) == date(9999, 2, 28)
    # Late in a month to early in the month after next: one month, not two.
    late = date(2024, 1, 28).toordinal()
    assert whole((late, date(2024, 3, 1).toordinal())) == (late, 1)


def test_a_whole_week_span_is_whole_months_within_two_weeks_either_way() -> None:
    """52/53-week calendars: a span of whole weeks is n whole months when the
    day after it ends lies within `WEEK_SLACK_DAYS` of its first day plus n
    months; any other span keeps `SLACK_DAYS`."""
    whole = history._whole_months
    assert history.WEEK_SLACK_DAYS == 14
    jan = date(2025, 1, 1).toordinal()
    # A 14-week January-March quarter: 98 days, 8 over January-March's 90.
    assert whole((jan, jan + 97)) == (jan, 3)
    # A 27-week first half (8 days over) and a 40-week nine months.
    assert whole((jan, jan + 27 * 7 - 1)) == (jan, 6)
    assert whole((jan, jan + 40 * 7 - 1)) == (jan, 9)
    # Fourteen days either way is in (from 1 April, 3 months is 91 days),
    # fifteen is out (from 1 January 90 days, from 1 July 92).
    april = date(2025, 4, 1).toordinal()
    assert whole((april, april + 15 * 7 - 1)) == (april, 3)
    assert whole((april, april + 11 * 7 - 1)) == (april, 3)
    assert whole((jan, jan + 15 * 7 - 1)) is None
    july = date(2025, 7, 1).toordinal()
    assert whole((july, july + 11 * 7 - 1)) is None
    # A span of no whole number of weeks 8 days over still refuses (99 days).
    leap = date(2024, 1, 1).toordinal()
    assert whole((leap, leap + 98)) is None
    # Two n within the slack (8 and 9 months from 1 June: 1 February and
    # 1 March, 14 days either side of 15 February): no n, refused.
    june = date(2025, 6, 1).toordinal()
    assert whole((june, june + 37 * 7 - 1)) is None
    assert whole((june, june + 36 * 7 - 1)) == (june, 8)  # 7 days from 1 February


@settings(max_examples=300)
@given(
    first=st.dates(min_value=date(1990, 1, 1), max_value=date(2100, 12, 31)),
    days=st.integers(min_value=1, max_value=800),
)
def test_whole_months_has_one_n_at_most(first: date, days: int) -> None:
    """Every n within the slack (14 days on whole weeks, else 7), counted
    afresh: exactly one is the answer, none or two are no answer."""
    start = first.toordinal()
    following = start + days
    slack = history.WEEK_SLACK_DAYS if days % 7 == 0 else history.SLACK_DAYS
    candidates = [
        n
        for n in range(1, days // 28 + 3)
        if (moved := history._plus_months(first, n)) is not None
        and abs(moved.toordinal() - following) <= slack
    ]
    expected = (start, candidates[0]) if len(candidates) == 1 else None

    assert history._whole_months((start, following - 1)) == expected


def test_a_remainder_is_whole_months_only_from_a_shared_start() -> None:
    remainder = history._remainder_months
    jan = date(2025, 1, 1).toordinal()
    h1, q1 = (jan, date(2025, 6, 30).toordinal()), (jan, date(2025, 3, 31).toordinal())
    assert remainder(h1, q1) == 3
    assert remainder(h1, (jan + 1, q1[1])) is None  # starts on another day
    assert remainder(None, q1) is None
    assert remainder(h1, None) is None
    assert remainder(h1, (jan, h1[1] - 50)) is None  # not whole months


def test_a_year_before_is_the_same_months_within_a_week_of_a_year_earlier() -> None:
    before = history._year_before
    start = date(2025, 2, 9).toordinal()
    year_earlier = date(2024, 2, 9).toordinal()
    for off in range(-7, 8):
        assert before((year_earlier + off, 6), (start, 6)), off
    assert not before((year_earlier - 8, 6), (start, 6))
    assert not before((year_earlier + 8, 6), (start, 6))
    assert not before((year_earlier, 3), (start, 6))  # other months
    assert not before(None, (start, 6))
    assert not before((year_earlier, 6), None)
    assert not before((1, 6), (date(1, 6, 1).toordinal(), 6))  # no year 0


def _week_period(
    period_id: str, kind: str, first: date, weeks: int, quarter: str | None
) -> PeriodRow:
    last = first + timedelta(weeks=weeks, days=-1)
    return PeriodRow(
        period_id=period_id,
        fiscal_year=period_id[-4:],
        fiscal_quarter=quarter,
        period_type=kind,
        start_date=first.isoformat(),
        end_date=last.isoformat(),
        day_count=weeks * 7,
        currency="USD",
        unit="MILLIONS",
        component_period_ids=(),
    )


def _retail(revenue: Mapping[str, int], ytd_quarter: str | None) -> Cp1Registers:
    """A 52/53-week filer (years ending the Saturday near 31 January;
    fiscal 2025 has a 53rd week, in its fourth quarter): 13-week quarters,
    26-week halves, revenue on the given periods."""
    year_2025 = date(2024, 2, 4)
    year_2026 = year_2025 + timedelta(weeks=53)
    year_2024 = date(2023, 1, 29)
    periods = {
        "FY2024": _week_period("FY2024", "FY", year_2024, 53, None),
        "FY2025": _week_period("FY2025", "FY", year_2025, 53, None),
        "H1_2025": _week_period("H1_2025", "YTD", year_2025, 26, ytd_quarter),
        "H1_2026": _week_period("H1_2026", "YTD", year_2026, 26, ytd_quarter),
    }
    for year, first in (("2025", year_2025), ("2026", year_2026)):
        for n in range(1, 5):
            weeks = 14 if (year, n) == ("2025", 4) else 13
            day = first + timedelta(weeks=13 * (n - 1))
            pid = f"Q{n}_{year}"
            periods[pid] = _week_period(pid, "QUARTER", day, weeks, str(n))
    accounts = tuple(
        AccountRow("revenue", pid, Decimal(v), "VERIFIED", None)
        for pid, v in revenue.items()
    )
    return Cp1Registers(
        periods=tuple(periods[pid] for pid in revenue),
        accounts=accounts,
        addbacks=(),
        segments=(),
        kpis=(),
        facilities=(),
        pro_forma=(),
        currency="USD",
        unit="MILLIONS",
    )


_RETAIL = {
    "FY2024": 1900,
    "Q1_2025": 480,
    "Q2_2025": 500,
    "Q3_2025": 510,
    "Q4_2025": 560,
    "FY2025": 2050,
    "H1_2025": 980,
    "Q1_2026": 490,
    "H1_2026": 1015,
}


@pytest.mark.parametrize("ytd_quarter", ["2", None])
def test_a_52_53_week_register_resolves_its_pytd_quarters_and_twelve_months(
    ytd_quarter: str | None,
) -> None:
    regs = _retail(_RETAIL, ytd_quarter)
    columns = historical_columns(regs)
    frame = account_frame(regs, columns)

    assert [c.column_id for c in columns if c.kind in ("PYTD", "YTD")] == [
        "PYTD:H1_2025",
        "YTD:H1_2026",
    ]
    ltm = next(c for c in columns if c.kind == "LTM")
    assert frame[ltm.column_id]["acct:revenue"] == Cell(
        Decimal(2050 + 1015 - 980), basis="CALCULATED"
    )
    if ytd_quarter is not None:  # a calculated quarter keys YTDs by quarter
        assert frame["Q:H1_2026-Q1_2026"]["acct:revenue"].value == 1015 - 490
    # The twelve months ending each quarter: four 13- or 14-week quarters.
    frames = ltm_frames(regs, columns)
    assert frames["Q:Q1_2026"]["acct:revenue"].value == 500 + 510 + 560 + 490
    assert frames["Q:Q4_2025"]["acct:revenue"].value == 480 + 500 + 510 + 560

    # Quarters to date, a year apart, without the half-year rows.
    quarters = {k: v for k, v in _RETAIL.items() if not k.startswith("H1")}
    quarterly = _retail({**quarters, "Q2_2026": 525}, ytd_quarter)
    columns = historical_columns(quarterly)
    frame = account_frame(quarterly, columns)
    assert [c.column_id for c in columns if c.kind in ("PYTD", "YTD")] == [
        "PYTD:Q2_2025",
        "YTD:Q2_2026",
    ]
    assert frame["LTM:Q2_2026"]["acct:revenue"].value == 2050 + 1015 - 980


def test_a_sparse_item_reads_a_53_week_fiscal_q4_as_its_year() -> None:
    regs = _interest(_retail(_RETAIL, "2"), {"FY2025": -40})
    frames = ltm_frames(regs, historical_columns(regs))
    assert frames["Q:Q4_2025"]["acct:interest_paid_in_financing"].value == -40


def test_a_period_eight_days_off_is_not_whole_months() -> None:
    regs = _regs(
        quarters={"Q1_2025": {"revenue": 100}},
        ytd={"H1_2025": {"revenue": 210}},
    )

    def quarter(h1_end: str) -> Cell:
        case = replace(
            regs,
            periods=tuple(
                replace(p, end_date=h1_end, day_count=None)
                if p.period_id == "H1_2025"
                else p
                for p in regs.periods
            ),
        )
        return _frame(case)["Q:H1_2025-Q1_2025"]["acct:revenue"]

    assert quarter("2025-07-07").value == 110  # a week over three months
    assert quarter("2025-07-08") == Cell(None, "COMPONENT_MISSING", note=UNSPANNED)
    assert quarter("2025-06-23").value == 110  # a week under
    assert quarter("2025-06-22") == Cell(None, "COMPONENT_MISSING", note=UNSPANNED)

    # A prior-year YTD starting eight days off a year earlier is no PYTD.
    def pytd(start: str, end: str) -> list[str]:
        prior = replace(
            _period("H1_2025", ()),
            period_id="P",
            fiscal_quarter=None,
            start_date=start,
            end_date=end,
            day_count=None,
        )
        case = _regs(ytd={"H1_2026": {"revenue": 1}})
        row = AccountRow("revenue", "P", Decimal(1), "VERIFIED", None)
        case = replace(
            case,
            periods=(prior, *_unlabelled(case).periods),
            accounts=(*case.accounts, row),
        )
        return [c.column_id for c in historical_columns(case) if c.kind == "PYTD"]

    assert pytd("2025-01-08", "2025-07-07") == ["PYTD:P"]
    assert pytd("2025-01-09", "2025-07-08") == []
    assert pytd("2024-12-25", "2025-06-24") == ["PYTD:P"]
    assert pytd("2024-12-24", "2025-06-23") == []


def test_the_example_register_follows_cp1s_fiscal_quarter_contract() -> None:
    """CP-1 leaves `fiscal_quarter` null on every period that is not a
    QUARTER (REF_CP-1_STEPS.md; CP-MODEL's validator refuses one there)."""
    for period in example_registers().periods:
        labelled = period.fiscal_quarter is not None
        assert labelled == (period.period_type == "QUARTER"), period.period_id


def test_a_ytd_without_a_fiscal_quarter_takes_its_length_from_its_dates() -> None:
    """The adversary's MAJOR-1: on a register that follows the contract the
    YTD's quarter comes from its whole months since the fiscal year began."""
    regs = example_registers()
    model = credit_model(_model_inputs(regs))
    labels = {c.column_id: c.label for c in model.columns}
    assert (labels["PYTD:H1_2025"], labels["YTD:H1_2026"]) == (
        "PYTD H1 25",
        "YTD H1 26",
    )
    assert labels["LTM:LTM_Q2_2026"] == "LTM Q2 26"
    ltm = "LTM:LTM_Q2_2026"
    for line_id, figure in (
        ("revenue", 11654),
        ("adjusted_ebitda", 4089),
        ("ffo", 2971),
    ):
        cell = _line_cell(model, line_id, ltm)
        assert (cell.value, cell.reason) == (Decimal(figure), None), line_id

    # Without a reported Q2 2026, Q2 is H1 less Q1, keyed by the H1's months.
    no_q2 = replace(
        regs,
        periods=tuple(
            replace(p, component_period_ids=()) if p.period_id == "H1_2026" else p
            for p in regs.periods
            if p.period_id != "Q2_2026"
        ),
        accounts=tuple(a for a in regs.accounts if a.period_id != "Q2_2026"),
    )
    frame = account_frame(no_q2, historical_columns(no_q2))
    assert frame["Q:H1_2026-Q1_2026"]["acct:revenue"].value == 3008

    # Without H1 2025, the PYTD is the prior year's quarters to H1's.
    no_h1 = replace(
        regs,
        periods=tuple(p for p in regs.periods if p.period_id != "H1_2025"),
        accounts=tuple(a for a in regs.accounts if a.period_id != "H1_2025"),
    )
    columns = historical_columns(no_h1)
    frame = account_frame(no_h1, columns)
    assert [c.column_id for c in columns if c.kind == "PYTD"] == ["PYTD:Q2_2025"]
    assert frame[ltm]["acct:revenue"].value == 11654

    # A YTD that is not whole quarters, or has no dates, has no quarter.
    h1 = next(p for p in regs.periods if p.period_id == "H1_2026")
    quarter = history._ytd_quarter
    assert quarter(h1) == 2
    assert quarter(replace(h1, end_date="2026-05-31")) is None
    assert quarter(replace(h1, end_date="2026-12-31")) == 4
    assert quarter(replace(h1, start_date=None, day_count=None)) is None
    assert quarter(replace(h1, end_date="2027-03-31")) is None  # 15 months
    # A label wins; another period's quarter is only ever its label.
    assert quarter(replace(h1, fiscal_quarter="Q3")) == 3
    fy = next(p for p in regs.periods if p.period_id == "FY2025")
    assert quarter(fy) is None
    assert quarter(replace(fy, fiscal_quarter="4")) == 4
    q2 = next(p for p in regs.periods if p.period_id == "Q2_2026")
    assert quarter(replace(q2, fiscal_quarter=None)) is None
    # Two YTDs of one fiscal year and months: neither is the quarter's.
    twin = replace(h1, period_id="H1_2026_R")
    assert history._by_quarter([h1]) == {(2026, 2): h1}
    assert history._by_quarter([h1, twin]) == {}
    assert history._by_quarter([h1, twin, replace(h1, period_id="X")]) == {}
    # A YTD of no whole quarters is passed over, never the end of the index.
    five = replace(h1, period_id="FIVE", end_date="2026-05-31")
    assert history._by_quarter([five, h1]) == {(2026, 2): h1}


def _interest(regs: Cp1Registers, figures: Mapping[str, int]) -> Cp1Registers:
    """The registers with interest paid in financing (a sparse account) on
    the given periods only."""
    rows = tuple(
        AccountRow("interest_paid_in_financing", pid, Decimal(v), "VERIFIED", None)
        for pid, v in figures.items()
    )
    kept = tuple(
        a for a in regs.accounts if a.metric_id != "interest_paid_in_financing"
    )
    return replace(regs, accounts=(*kept, *rows))


@pytest.mark.parametrize("labelled", [True, False])
def test_an_ltm_is_never_built_from_a_one_sided_interim(labelled: bool) -> None:
    regs = _halves() if labelled else _unlabelled(_halves())
    key = "acct:interest_paid_in_financing"

    def ltm(figures: Mapping[str, int]) -> Cell:
        case = _interest(regs, figures)
        return account_frame(case, historical_columns(case))["LTM:H1_2026"][key]

    one_sided = Cell(None, "COMPONENT_MISSING", note=history.PARTLY_STATED)
    assert ltm({"FY2025": -20, "H1_2026": -9}) == one_sided
    assert ltm({"FY2025": -20, "H1_2025": -8}) == one_sided
    # Neither interim stated: the item did not occur in them, so the LTM is
    # the year's, each interim named as taken as nothing.
    assert ltm({"FY2025": -20}).value == Decimal(-20)
    assert ltm({"FY2025": -20}).note == (
        f"{treated_as_zero('H1_2026')}; {treated_as_zero('H1_2025')}"
    )
    assert ltm({"FY2025": -20, "H1_2026": -9, "H1_2025": -8}).value == Decimal(-21)
    # A stated zero is a statement: both sides stated.
    assert ltm({"FY2025": -20, "H1_2026": 0, "H1_2025": -8}).value == Decimal(-12)

    # CP-1's own LTM figure is kept as `stated`, never adopted.
    stated = _interest(
        _regs(
            fy={"FY2025": {"revenue": 1}},
            ytd={"H1_2026": {"revenue": 1}, "H1_2025": {"revenue": 1}},
            ltm={"LTM_Q2_2026": {"revenue": 1}},
        ),
        {"FY2025": -20, "H1_2026": -9, "LTM_Q2_2026": -29},
    )
    frame = account_frame(stated, historical_columns(stated))
    assert frame["LTM:LTM_Q2_2026"][key] == Cell(
        None, "COMPONENT_MISSING", stated=Decimal(-29), note=history.PARTLY_STATED
    )


def test_a_one_sided_interim_leaves_the_ltm_cash_flow_missing() -> None:
    regs = _without_ltm_rows(example_registers())
    ltm = "LTM:LTM_Q2_2026"
    base = credit_model(_model_inputs(regs))
    prior = {"Q1_2025", "Q2_2025", "H1_2025"}
    one_sided = replace(
        regs,
        accounts=tuple(
            a
            for a in regs.accounts
            if not (
                a.metric_id == "interest_paid_in_financing" and a.period_id in prior
            )
        ),
    )
    model = credit_model(_model_inputs(one_sided))
    for line_id in ("cfo_adjusted", "fcf", "metric:fcf_to_debt"):
        assert _line_cell(base, line_id, ltm).value is not None, line_id
        assert _line_cell(model, line_id, ltm).value is None, line_id
    # Interest in financing has no line of its own: every figure built from
    # it names why it is missing, and the limitation is served through them.
    for line_id in ("cfo_adjusted", "fcf", "metric:fcf_to_debt"):
        cell = _line_cell(model, line_id, ltm)
        assert (cell.reason, cell.note) == (
            "COMPONENT_MISSING",
            history.PARTLY_STATED,
        ), line_id
    # Served once, on the LTM and on each quarter whose twelve months it
    # leaves partly stated.
    (served,) = [t for t in model.limitations if t.startswith(history.PARTLY_STATED)]
    assert served == (
        f"{history.PARTLY_STATED}: {ltm}, Q:Q1_2025, Q:Q2_2025, Q:Q3_2025, Q:Q1_2026"
    )
    leases = replace(
        regs,
        accounts=tuple(
            a
            for a in regs.accounts
            if not (
                a.metric_id == "lease_payments_in_financing" and a.period_id in prior
            )
        ),
    )
    model_leases = credit_model(_model_inputs(leases))
    lease = _line_cell(model_leases, "lease_cash_not_in_ebitda", ltm)
    assert (lease.reason, lease.note) == ("COMPONENT_MISSING", history.PARTLY_STATED)
    assert any(
        t.startswith(f"{history.PARTLY_STATED}: {ltm}")
        for t in model_leases.limitations
    )
    assert _line_cell(model_leases, "fcf", ltm).value is None
    # The fully stated lines are untouched.
    for line_id in ("revenue", "cash_interest", "capex"):
        assert _line_cell(model, line_id, ltm) == _line_cell(base, line_id, ltm)

    neither = replace(
        one_sided,
        accounts=tuple(
            a
            for a in one_sided.accounts
            if not (
                a.metric_id == "interest_paid_in_financing"
                and a.period_id in {"Q1_2026", "Q2_2026", "H1_2026"}
            )
        ),
    )
    model = credit_model(_model_inputs(neither))
    assert _line_cell(model, "fcf", ltm).value is not None


@pytest.mark.parametrize("labelled", [True, False])
def test_a_sparse_ltm_needs_its_fy_when_an_interim_is_stated(labelled: bool) -> None:
    regs = _halves() if labelled else _unlabelled(_halves())
    key = "acct:interest_paid_in_financing"

    def ltm(figures: Mapping[str, int]) -> Cell:
        case = _interest(regs, figures)
        return account_frame(case, historical_columns(case))["LTM:H1_2026"][key]

    partly = Cell(None, "COMPONENT_MISSING", note=history.PARTLY_STATED)
    # The interims are parts of the FY: without its row, never YTD - PYTD. A
    # stated PYTD inside an FY without a row leaves the FY's cover a gap.
    unspanned = Cell(None, "COMPONENT_MISSING", note=UNSPANNED)
    assert ltm({"H1_2026": -9, "H1_2025": -8}) == unspanned
    assert ltm({"H1_2025": -8}) == unspanned
    assert ltm({"H1_2026": -9}) == partly
    # Nothing stated over the twelve months: no row, not a missing component.
    assert ltm({"FY2024": -5}) == Cell(None, "NOT_SOURCED")
    assert ltm({"FY2025": -20}).value == Decimal(-20)
    assert ltm({"FY2025": -20, "H1_2026": -9, "H1_2025": -8}).value == Decimal(-21)


def test_partly_stated_reads_the_three_terms_of_a_rolled_ltm() -> None:
    """Every pattern of stated (S), no row (A) and missing otherwise (M) over
    FY, YTD and PYTD: only all stated, or the FY beside two interims without
    a row, is summed; a part missing otherwise is left to the sum."""
    regs = _halves()
    spec = next(s for s in history._plan(regs) if s.column.kind == "LTM")
    year = next(s for s in history._plan(regs) if s.column.kind == "FY")
    cells = {
        "S": Cell(Decimal(1)),
        "A": Cell(None, "NOT_SOURCED"),
        "M": Cell(None, "COMPONENT_MISSING"),
    }
    partly = {"ASS", "SAS", "SSA", "AAS", "ASA"}
    for pattern in (a + b + c for a in "SAM" for b in "SAM" for c in "SAM"):
        terms = [(cells[p], sign) for p, sign in zip(pattern, (1, 1, -1), strict=True)]
        expected = pattern in partly
        assert history._partly_stated(spec, terms) == expected, pattern
        assert not history._partly_stated(year, terms), pattern
    assert not history._partly_stated(spec, [(cells["S"], 1), (cells["A"], 1)])


def _quarter_labels(regs: Cp1Registers, **labels: str | None) -> Cp1Registers:
    """The registers with each named period's fiscal quarter set."""
    return replace(
        regs,
        periods=tuple(
            replace(p, fiscal_quarter=labels[p.period_id])
            if p.period_id in labels
            else p
            for p in regs.periods
        ),
    )


def test_a_labelled_pytd_of_other_months_is_never_the_pytd() -> None:
    unspanned = Cell(None, "COMPONENT_MISSING", note=UNSPANNED)
    # A 9M or a Q1-length YTD labelled fiscal quarter 2 (the audit's p1b).
    for prior, figure in (("9M_2025", 300), ("Q1YTD_2025", 95)):
        regs = _regs(
            fy={"FY2025": {"revenue": 400}},
            ytd={"H1_2026": {"revenue": 210}},
        )
        h1 = regs.periods[1]
        end = "2025-09-30" if prior == "9M_2025" else "2025-03-31"
        wrong = replace(
            h1,
            period_id=prior,
            fiscal_year="2025",
            start_date="2025-01-01",
            end_date=end,
            day_count=273 if prior == "9M_2025" else 90,
        )
        row = AccountRow("revenue", prior, Decimal(figure), "VERIFIED", None)
        regs = replace(
            regs, periods=(*regs.periods, wrong), accounts=(*regs.accounts, row)
        )
        columns = historical_columns(regs)
        assert [c.kind for c in columns] == ["YTD", "FY", "LTM"], prior
        frame = account_frame(regs, columns)
        assert frame["LTM:H1_2026"]["acct:revenue"] == unspanned, prior


def test_a_dated_pytd_beats_a_label_of_other_months() -> None:
    """The audit's p1c: a 9M labelled 2 beside an unlabelled H1 2025."""
    regs = _regs(
        fy={"FY2025": {"revenue": 400}},
        ytd={
            "9M_2025": {"revenue": 300},
            "H1_2025": {"revenue": 200},
            "H1_2026": {"revenue": 210},
        },
    )
    regs = _quarter_labels(regs, **{"9M_2025": "2", "H1_2025": None})

    columns = historical_columns(regs)
    frame = account_frame(regs, columns)

    assert [c.column_id for c in columns if c.kind == "PYTD"] == ["PYTD:H1_2025"]
    assert frame["LTM:H1_2026"]["acct:revenue"].value == Decimal(410)
    assert next(c for c in columns if c.kind == "LTM").days == 365


def test_a_calculated_quarter_must_be_three_whole_months() -> None:
    """The audit's p1d: 9M labelled 2, less Q1, is no Q2."""
    regs = _regs(
        quarters={"Q1_2025": {"revenue": 100}},
        fy={"FY2025": {"revenue": 420}},
        ytd={"9M_2025": {"revenue": 310}},
    )
    regs = _quarter_labels(regs, **{"9M_2025": "2"})

    frame = _frame(regs)

    assert frame["Q:9M_2025-Q1_2025"]["acct:revenue"] == Cell(
        None, "COMPONENT_MISSING", note=UNSPANNED
    )
    # A true H1 less Q1 is still Q2.
    good = _regs(
        quarters={"Q1_2025": {"revenue": 100}},
        ytd={"H1_2025": {"revenue": 210}},
    )
    assert _frame(good)["Q:H1_2025-Q1_2025"]["acct:revenue"].value == 110


def test_the_twelve_months_ending_a_quarter_must_tile_by_dates() -> None:
    """The audit's p13: Q4 2024 labelled fiscal 2025 and no Q4 2025."""
    regs = example_registers()
    periods = tuple(
        replace(p, fiscal_year="2025") if p.period_id == "Q4_2024" else p
        for p in regs.periods
        if p.period_id != "Q4_2025"
    )
    regs = replace(
        regs,
        periods=periods,
        accounts=tuple(a for a in regs.accounts if a.period_id != "Q4_2025"),
    )

    frame = ltm_frames(regs, historical_columns(regs))["Q:Q2_2026"]

    assert frame["acct:revenue"] == Cell(None, "COMPONENT_MISSING", note=UNSPANNED)
    assert frame["addback:restructuring"] == Cell(
        None, "COMPONENT_MISSING", note=UNSPANNED
    )
    # A balance is the quarter's own, whatever the window.
    assert frame["acct:cash_and_equivalents"].value == 1000


def test_quarters_to_date_must_tile_by_dates() -> None:
    """A quarter that is not three whole months never enters a sum of
    quarters to date."""
    regs = _regs(
        quarters={
            "Q1_2026": {"revenue": 100},
            "Q2_2026": {"revenue": 110},
            "Q1_2025": {"revenue": 90},
            "Q2_2025": {"revenue": 95},
        },
        fy={"FY2025": {"revenue": 400}},
    )
    whole = _frame(regs)
    assert whole["YTD:Q2_2026"]["acct:revenue"].value == 210
    assert whole["LTM:Q2_2026"]["acct:revenue"].value == 400 + 210 - 185
    short = replace(
        regs,
        periods=tuple(
            replace(p, start_date="2026-04-02", day_count=90)
            if p.period_id == "Q2_2026"
            else p
            for p in regs.periods
        ),
    )
    frame = _frame(short)
    unspanned = Cell(None, "COMPONENT_MISSING", note=UNSPANNED)
    assert frame["YTD:Q2_2026"]["acct:revenue"] == unspanned
    assert frame["LTM:Q2_2026"]["acct:revenue"] == unspanned
    # Its own column is CP-1's figure for its own dates.
    assert frame["Q:Q2_2026"]["acct:revenue"].value == 110


def test_quarters_to_date_of_other_months_are_never_the_pytd() -> None:
    """A 9M 2026 labelled fiscal quarter 2, no prior YTD period: Q1 + Q2
    2025 are six months, not the 9M's nine a year earlier."""
    regs = _regs(
        quarters={"Q1_2025": {"revenue": 90}, "Q2_2025": {"revenue": 95}},
        fy={"FY2025": {"revenue": 400}},
        ytd={"9M_2026": {"revenue": 300}},
    )
    regs = _quarter_labels(regs, **{"9M_2026": "2"})

    columns = historical_columns(regs)

    assert "PYTD" not in [c.kind for c in columns]
    assert account_frame(regs, columns)["LTM:9M_2026"]["acct:revenue"] == Cell(
        None, "COMPONENT_MISSING", note=UNSPANNED
    )


def _live_interest() -> Cp1Registers:
    """The example registers with run 9b9e2b72's interest in financing:
    FY2025 -1349, H1 2026 -686, Q1 and Q2 2026 -343 each, no 2025 interim."""
    return _interest(
        example_registers(),
        {"FY2025": -1349, "H1_2026": -686, "Q1_2026": -343, "Q2_2026": -343},
    )


def test_a_sparse_twelve_months_ending_a_quarter_needs_all_four() -> None:
    regs = _live_interest()
    key = "acct:interest_paid_in_financing"

    frames = ltm_frames(regs, historical_columns(regs))

    # Q3 and Q4 2025 have no row beside two stated 2026 quarters.
    assert frames["Q:Q2_2026"][key] == Cell(
        None, "COMPONENT_MISSING", note=history.PARTLY_STATED
    )
    # The fiscal Q4's twelve months are the FY's, as the FY column reads it.
    fy = account_frame(regs, historical_columns(regs))["FY:FY2025"][key]
    assert frames["Q:Q4_2025"][key] == fy
    assert fy.value == Decimal(-1349)
    # Nothing stated over the twelve months: no row; all four stated: summed.
    nothing = _interest(regs, {"FY2023": -1})
    assert ltm_frames(nothing, historical_columns(nothing))["Q:Q2_2026"][key] == Cell(
        None, "NOT_SOURCED"
    )
    quarters = {"Q3_2025": -1, "Q4_2025": -2, "Q1_2026": -3, "Q2_2026": -4}
    every = _interest(regs, quarters)
    assert ltm_frames(every, historical_columns(every))["Q:Q2_2026"][
        key
    ].value == Decimal(-10)
    # A flow (not sparse) with a quarter without a row is missing, as ever.
    gap = replace(
        regs,
        accounts=tuple(
            a
            for a in regs.accounts
            if (a.metric_id, a.period_id) != ("revenue", "Q3_2025")
        ),
    )
    assert ltm_frames(gap, historical_columns(gap))["Q:Q2_2026"][
        "acct:revenue"
    ] == Cell(None, "COMPONENT_MISSING")


def test_quarter_twelve_month_metrics_follow_a_partly_stated_sparse_item() -> None:
    """The audit's p8b: the same twelve months read the same on every
    column."""
    model = credit_model(_model_inputs(_live_interest()))
    # FY2025's FCF 155 and FFO 1552 over its total debt 14118.
    for line_id, flow in (("metric:fcf_to_debt", 155), ("metric:ffo_to_debt", 1552)):
        year = _line_cell(model, line_id, "FY:FY2025")
        with localcontext(CONTEXT):
            assert year.value == Decimal(flow) / Decimal(14118)
        assert _line_cell(model, line_id, "Q:Q4_2025").value == year.value
        for column_id in ("Q:Q2_2026", "LTM:LTM_Q2_2026"):
            cell = _line_cell(model, line_id, column_id)
            assert (cell.reason, cell.note) == (
                "COMPONENT_MISSING",
                history.PARTLY_STATED,
            ), (line_id, column_id)


def test_nested_covers_at_the_period_cap_never_exhaust_the_stack() -> None:
    """The audit's L2: one 10-day part and 199 periods all starting with it,
    each a day longer than the last (`MAX_PERIODS` in all): every period's
    cover is the next shorter one, 199 deep."""
    first = date(2010, 1, 1)

    def period(period_id: str, days: int, kind: str) -> PeriodRow:
        last = first + timedelta(days=days - 1)
        return PeriodRow(
            period_id,
            str(last.year),
            None,
            kind,
            first.isoformat(),
            last.isoformat(),
            days,
            "USD",
            "MILLIONS",
            (),
        )

    periods = (
        period("S0", 10, "QUARTER"),
        *(period(f"L{j}", 21 + j, "YTD") for j in range(MAX_PERIODS - 1)),
    )
    addback = AddbackRow(
        "a0", "a0", "SBC", "REALIZED", 0, "S0", Decimal(1), SourceRef("S", "S0", "1")
    )
    regs = Cp1Registers(periods, (), (addback,), (), (), (), (), "USD", "MILLIONS")

    frame = _frame(regs)

    # Each longer period's cover is S0 then a gap: a part with a figure, not
    # tiling it.
    assert frame[f"YTD:L{MAX_PERIODS - 2}"]["addback:a0"] == Cell(
        None, "COMPONENT_MISSING", note=UNSPANNED
    )
    assert frame["Q:S0"]["addback:a0"].value == 1


def test_covers_nested_by_their_starts_at_the_period_cap_never_exhaust_it() -> None:
    """`MAX_PERIODS` periods ending on one day, each starting a day before
    the next, listed longest first: each period's cover is a gap, then the
    next shorter one, 199 deep; the shortest has the only row."""
    last = date(2012, 12, 31)

    def period(period_id: str, days: int) -> PeriodRow:
        first = last - timedelta(days=days - 1)
        return PeriodRow(
            period_id,
            "2012",
            None,
            "YTD",
            first.isoformat(),
            last.isoformat(),
            days,
            "USD",
            "MILLIONS",
            (),
        )

    periods = tuple(period(f"P{n}", n) for n in range(MAX_PERIODS + 9, 9, -1))
    addback = AddbackRow(
        "a0", "a0", "SBC", "REALIZED", 0, "P10", Decimal(1), SourceRef("S", "P", "1")
    )
    regs = Cp1Registers(periods, (), (addback,), (), (), (), (), "USD", "MILLIONS")
    register = history._register(regs)
    series = history._series(regs)["addback:a0"]

    with localcontext(CONTEXT):
        longest = history._resolved(series, register, f"P{MAX_PERIODS + 9}")

    assert longest == Cell(None, "COMPONENT_MISSING", note=UNSPANNED)
    assert series.resolved["P10"].value == 1
    assert len(series.resolved) == MAX_PERIODS


def test_twins_of_a_period_at_the_cap_never_nest_past_max_nesting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The re-verify's L3 (p13): FY2025 and 199 LTM periods on its exact
    dates, an add-back on every third. A period of equal span stops
    `_resolve_within`, so working out one twin never works out the next
    inside it: `_resolved` nests at most `MAX_NESTING` + 1 deep (once per
    period, where without the stop it nests once per twin, 201 deep)."""
    year = _period("FY2025", ())
    periods = (
        year,
        *(
            replace(year, period_id=f"L{n}", period_type="LTM")
            for n in range(MAX_PERIODS - 1)
        ),
    )
    addbacks = tuple(
        AddbackRow("x", "x", "SBC", "REALIZED", 1, p.period_id, Decimal(1), None)
        for p in periods[1::3]
    )
    regs = Cp1Registers(periods, (), addbacks, (), (), (), (), "USD", "MILLIONS")
    real = history._resolved
    depth = [0, 0]  # now, deepest

    def counted(
        series: history._Series, register: history._Register, period_id: str | None
    ) -> Cell:
        depth[0] += 1
        depth[1] = max(depth)
        try:
            return real(series, register, period_id)
        finally:
            depth[0] -= 1

    monkeypatch.setattr(history, "_resolved", counted)
    frame = _frame(regs)

    assert 1 <= depth[1] <= MAX_NESTING + 1
    # FY2025 has no row: its twin L0's own row is its figure.
    assert frame["FY:FY2025"]["addback:x"].value == 1


def _footing(
    regs: Cp1Registers, **others: tuple[str | None, str | None]
) -> Cp1Registers:
    """`regs` with every period on US GAAP, consolidated, except the named
    periods' (basis, perimeter)."""

    def footed(period: PeriodRow) -> PeriodRow:
        basis, perimeter = others.get(period.period_id, ("US GAAP", "Consolidated"))
        return replace(period, accounting_basis=basis, entity_perimeter=perimeter)

    return replace(regs, periods=tuple(footed(p) for p in regs.periods))


def test_off_footing_names_the_periods_on_another_basis_or_perimeter() -> None:
    regs = _footing(
        example_registers(),
        FY2023=("IFRS", "Consolidated"),
        Q1_2024=("US GAAP", "Continuing operations"),
        Q2_2024=("us-gaap", "consolidated"),  # spelling aside, the same
        Q1_2025=("US_GAAP", " Consolidated "),
        Q3_2024=(None, "Continuing operations"),
        Q4_2024=("IFRS", None),
        FY2024=(None, None),  # not stated combines with anything
    )
    anchor = anchor_period(regs)
    assert anchor is not None and anchor.period_id == "H1_2026"
    assert off_footing(regs) == {"FY2023", "Q1_2024", "Q3_2024", "Q4_2024"}
    limits = credit_model(_model_inputs(regs)).limitations
    assert f"{NOT_COMBINED}: FY2023, Q1_2024, Q3_2024, Q4_2024" in limits
    # An anchor that states neither: nothing differs from it.
    unstated = _footing(regs, H1_2026=(None, None), FY2023=("IFRS", "X"))
    assert off_footing(unstated) == frozenset()
    assert off_footing(replace(regs, periods=())) == frozenset()
    # The anchor is the latest end; an FY before a YTD before a quarter.
    halves = anchor_period(_halves())
    assert halves is not None and halves.period_id == "H1_2026"


def test_periods_on_another_basis_or_perimeter_are_never_combined() -> None:
    """The adversary's MAJOR-4: H1 2025 recast for a disposal (continuing
    operations) beside the consolidated 10-Qs and 10-K."""
    off = Cell(None, "COMPONENT_MISSING", note=OTHER_FOOTING)
    regs = _footing(example_registers(), H1_2025=("US GAAP", "Continuing ops"))
    columns = historical_columns(regs)
    frame = account_frame(regs, columns)
    ltm = frame["LTM:LTM_Q2_2026"]["acct:revenue"]
    assert (ltm.value, ltm.reason, ltm.note) == (
        None,
        "COMPONENT_MISSING",
        OTHER_FOOTING,
    )
    # Not even its own components are summed into it; the YTD, on the
    # anchor's footing, is.
    assert frame["PYTD:H1_2025"]["acct:revenue"] == replace(off, stated=Decimal(5750))
    assert frame["YTD:H1_2026"]["acct:revenue"].value == 2877 + 3008
    model = credit_model(_model_inputs(regs))
    assert f"{NOT_COMBINED}: H1_2025" in model.limitations
    assert _line_cell(model, "adjusted_ebitda", "LTM:LTM_Q2_2026").value is None

    # A quarter on another basis: in no sum of quarters, and no balance read
    # at its date for another period; its own column is CP-1's figures.
    q2 = _footing(example_registers(), Q2_2026=("IFRS", None))
    columns = historical_columns(q2)
    frames = ltm_frames(q2, columns)
    assert frames["Q:Q2_2026"]["acct:revenue"] == off
    assert frames["Q:Q1_2026"]["acct:revenue"].value is not None
    frame = account_frame(q2, columns)
    assert frame["Q:Q2_2026"]["acct:revenue"].value == 3008
    assert frame["YTD:H1_2026"]["acct:revenue"] == replace(off, stated=Decimal(5885))
    debt = debt_frame(q2, columns, frame)
    assert debt["Q:Q2_2026"]["debt_closing"].value == 14106
    assert "fac:tlb" not in debt["LTM:LTM_Q2_2026"]
    assert debt["LTM:LTM_Q2_2026"]["debt_closing"] == Cell(None, "NOT_SOURCED")
    # The opening stack of the quarter after it is not read from it either.
    q3 = _footing(example_registers(), Q2_2025=("IFRS", None))
    columns = historical_columns(q3)
    debt = debt_frame(q3, columns, account_frame(q3, columns))
    assert debt["Q:Q3_2025"]["debt_opening"] == Cell(None, "NOT_SOURCED")
    # An off column reads only its own row; others read none from it.
    assert account_frame(q3, columns)["Q:Q2_2025"]["acct:total_debt"].value == 13870
    assert account_frame(q3, columns)["PYTD:H1_2025"]["acct:total_debt"].value == (
        13870
    )  # H1 2025's own row

    # A calculated quarter whose subtrahend is on another footing.
    no_q2 = _footing(
        replace(
            example_registers(),
            periods=tuple(
                replace(p, component_period_ids=()) if p.period_id == "H1_2026" else p
                for p in example_registers().periods
                if p.period_id != "Q2_2026"
            ),
        ),
        Q1_2026=("IFRS", None),
    )
    assert _frame(no_q2)["Q:H1_2026-Q1_2026"]["acct:revenue"] == off

    # Not stated combines with anything: a run before the columns, or a null.
    for unstated in (
        example_registers(),
        _footing(example_registers(), H1_2025=(None, None)),
    ):
        frame = _frame(unstated)
        assert frame["LTM:LTM_Q2_2026"]["acct:revenue"].value == 11654
        assert not any(
            t.startswith(NOT_COMBINED)
            for t in credit_model(_model_inputs(unstated)).limitations
        )


def test_a_sparse_calculated_quarter_names_the_part_it_took_as_nothing() -> None:
    regs = _interest(
        _regs(quarters={"Q1_2025": {"revenue": 1}}, ytd={"H1_2025": {"revenue": 2}}),
        {"H1_2025": -8},
    )
    cell = _frame(regs)["Q:H1_2025-Q1_2025"]["acct:interest_paid_in_financing"]
    assert (cell.value, cell.note) == (Decimal(-8), treated_as_zero("Q1_2025"))


def test_a_quarter_of_other_months_never_tiles() -> None:
    """A quarter of 50 days, or of two months, ends no sum of quarters."""
    regs = _regs(
        quarters={
            "Q1_2026": {"revenue": 100},
            "Q2_2026": {"revenue": 110},
            "Q1_2025": {"revenue": 90},
            "Q2_2025": {"revenue": 95},
        },
        fy={"FY2025": {"revenue": 400}},
    )
    unspanned = Cell(None, "COMPONENT_MISSING", note=UNSPANNED)
    for end, days in (("2026-05-20", 50), ("2026-05-31", 61)):
        short = replace(
            regs,
            periods=tuple(
                replace(p, end_date=end, day_count=days)
                if p.period_id == "Q2_2026"
                else p
                for p in regs.periods
            ),
        )
        assert _frame(short)["YTD:Q2_2026"]["acct:revenue"] == unspanned, end
    # Adjacent quarters of three months each tile, one a day apart does not.
    periods: dict[str | None, PeriodRow] = {p.period_id: p for p in regs.periods}
    specs = [
        history._period_spec(periods[pid], "YTD") for pid in ("Q1_2026", "Q2_2026")
    ]
    assert history._tiles(specs, periods)
    late = replace(periods["Q2_2026"], start_date="2026-04-02", day_count=90)
    gap: dict[str | None, PeriodRow] = {**periods, "Q2_2026": late}
    specs[1] = history._period_spec(late, "YTD")
    assert not history._tiles(specs, gap)


def _days_period(
    period_id: str, kind: str, first: date, days: int, quarter: str | None
) -> PeriodRow:
    """A fiscal-2025 or -2026 period (by its id's last four characters) of
    `days` days from `first`."""
    return PeriodRow(
        period_id=period_id,
        fiscal_year=period_id[-4:],
        fiscal_quarter=quarter,
        period_type=kind,
        start_date=first.isoformat(),
        end_date=(first + timedelta(days=days - 1)).isoformat(),
        day_count=days,
        currency="USD",
        unit="MILLIONS",
        component_period_ids=(),
    )


def _revenue_on(periods: tuple[PeriodRow, ...], per_day: bool) -> Cp1Registers:
    """`periods` with revenue on each: 1 a day, else 100 a period."""
    accounts = tuple(
        AccountRow(
            "revenue",
            p.period_id,
            Decimal(p.day_count if per_day and p.day_count else 100),
            "VERIFIED",
            None,
        )
        for p in periods
    )
    return Cp1Registers(periods, accounts, (), (), (), (), (), "USD", "MILLIONS")


def _four_quarters(lengths: list[int], first: date = date(2025, 1, 1)) -> Cell:
    """The trailing revenue ending the fourth of four fiscal-2025 quarters of
    `lengths` days, each starting the day after the one before ends, revenue
    100 each."""
    periods = []
    for n, days in enumerate(lengths, start=1):
        periods.append(_days_period(f"Q{n}_2025", "QUARTER", first, days, str(n)))
        first += timedelta(days=days)
    regs = _revenue_on(tuple(periods), per_day=False)
    return ltm_frames(regs, historical_columns(regs))["Q:Q4_2025"]["acct:revenue"]


def test_four_quarters_must_span_twelve_months_as_one_span() -> None:
    """The re-verify's M1 (p1): each quarter within its slack of three
    months, four 14-week quarters are 392 days, 27 over twelve months."""
    unspanned = Cell(None, "COMPONENT_MISSING", note=UNSPANNED)
    assert _four_quarters([98] * 4) == unspanned
    assert _four_quarters([97] * 4) == unspanned  # 388 days, 23 over
    # A 53-week year (one 14-week quarter, 371 days) and a calendar year.
    assert _four_quarters([91, 91, 91, 98]).value == 400
    assert _four_quarters([90, 91, 92, 92]).value == 400


@settings(deadline=None, max_examples=200)
@given(
    first=st.dates(min_value=date(1990, 1, 1), max_value=date(2100, 12, 31)),
    lengths=st.lists(st.integers(min_value=77, max_value=105), min_size=4, max_size=4),
)
@example(first=date(2025, 1, 1), lengths=[98, 98, 98, 98])
def test_an_accepted_twelve_months_spans_them_within_the_slack(
    first: date, lengths: list[int]
) -> None:
    """Four adjacent quarters summed as twelve months span twelve months:
    the day after the last ends lies within `SLACK_DAYS` of the first's
    start plus twelve months (`WEEK_SLACK_DAYS` where the span is whole
    weeks), however each quarter's own slack adds up."""
    cell = _four_quarters(lengths, first)
    span = sum(lengths)
    slack = history.WEEK_SLACK_DAYS if span % 7 == 0 else history.SLACK_DAYS
    year_later = history._plus_months(first, 12)
    assert year_later is not None
    if cell.value is not None:
        assert abs(first.toordinal() + span - year_later.toordinal()) <= slack
    else:
        assert cell == Cell(None, "COMPONENT_MISSING", note=UNSPANNED)


def _rolled_ltm(ytd_weeks: int, pytd_weeks: int) -> Cell:
    """LTM revenue, at 1 a day, of calendar FY2025 + a YTD of `ytd_weeks`
    from 1 January 2026 - a PYTD of `pytd_weeks` from 1 January 2025."""
    periods = (
        _days_period("FY2025", "FY", date(2025, 1, 1), 365, None),
        _days_period("H1_2025", "YTD", date(2025, 1, 1), 7 * pytd_weeks, None),
        _days_period("H1_2026", "YTD", date(2026, 1, 1), 7 * ytd_weeks, None),
    )
    regs = _revenue_on(periods, per_day=True)
    columns = historical_columns(regs)
    ltm = next(c for c in columns if c.kind == "LTM")
    return account_frame(regs, columns)[ltm.column_id]["acct:revenue"]


def test_an_ltm_needs_its_ytd_and_pytd_within_a_week_of_each_other() -> None:
    """The re-verify's M1 (p9): a 27-week YTD and a 25-week PYTD are each
    six months within the 14-day slack, but FY + YTD - PYTD is 379 days."""
    assert _rolled_ltm(27, 25) == Cell(None, "COMPONENT_MISSING", note=UNSPANNED)
    assert _rolled_ltm(25, 27) == Cell(None, "COMPONENT_MISSING", note=UNSPANNED)
    # A 53rd week in the YTD's first quarter: a week apart, still read.
    assert _rolled_ltm(27, 26).value == 365 + 189 - 182
    assert _rolled_ltm(26, 26).value == 365


def _bases(regs: Cp1Registers, **bases: tuple[str | None, str | None]) -> Cp1Registers:
    """`regs` with no period stating a basis or perimeter, except the named
    periods' (basis, perimeter)."""
    return replace(
        regs,
        periods=tuple(
            replace(
                p,
                accounting_basis=bases.get(p.period_id, (None, None))[0],
                entity_perimeter=bases.get(p.period_id, (None, None))[1],
            )
            for p in regs.periods
        ),
    )


_OFF = Cell(None, "COMPONENT_MISSING", note=OTHER_FOOTING)


def test_two_stated_footings_that_differ_are_never_combined() -> None:
    """The re-verify's M2 (p2): the anchor H1 2026 states no basis, FY2025
    is as reported and H1 2025 restated. FY + YTD - PYTD would combine
    them; each column alone is its own figure."""
    regs = _bases(
        example_registers(),
        FY2025=("AS_REPORTED", None),
        H1_2025=("RESTATED", None),
    )
    frame = _frame(regs)
    assert frame["LTM:LTM_Q2_2026"]["acct:revenue"] == replace(
        _OFF, stated=Decimal(11654)
    )
    assert frame["FY:FY2025"]["acct:revenue"].value == 11519
    assert frame["PYTD:H1_2025"]["acct:revenue"].value == 5750
    assert frame["YTD:H1_2026"]["acct:revenue"].value == 5885
    model = credit_model(_model_inputs(regs))
    assert f"{NOT_COMBINED}: H1_2025, FY2025" in model.limitations
    assert _line_cell(model, "adjusted_ebitda", "LTM:LTM_Q2_2026").value is None

    # A perimeter the anchor states none of, stated two ways.
    regs = _bases(
        example_registers(),
        H1_2026=("US GAAP", None),
        FY2025=("US GAAP", "Consolidated"),
        H1_2025=("US GAAP", "Continuing operations"),
    )
    assert _frame(regs)["LTM:LTM_Q2_2026"]["acct:revenue"].note == OTHER_FOOTING


def test_components_and_quarters_on_two_footings_are_never_summed() -> None:
    """Pairwise within a sum, whatever the anchor states: H1 2025's
    quarters, the twelve months ending Q2 2026, and a sparse cover."""
    regs = _bases(example_registers(), Q1_2025=("IFRS", None), Q2_2025=("GAAP", None))
    assert _frame(regs)["PYTD:H1_2025"]["acct:revenue"] == replace(
        _OFF, stated=Decimal(5750)
    )
    regs = _bases(example_registers(), Q3_2025=("IFRS", None), Q4_2025=("GAAP", None))
    frames = ltm_frames(regs, historical_columns(regs))
    assert frames["Q:Q2_2026"]["acct:revenue"] == _OFF
    assert frames["Q:Q2_2026"]["addback:restructuring"] == _OFF
    assert frames["Q:Q3_2025"]["acct:revenue"].value is not None  # no Q4 2025
    # FY2024 states none and has no restructuring row: its cover, two
    # quarters on each footing, is no figure.
    regs = _bases(
        _without_addback(example_registers(), "FY2024"),
        Q1_2024=("IFRS", None),
        Q2_2024=("IFRS", None),
        Q3_2024=("GAAP", None),
        Q4_2024=("GAAP", None),
    )
    assert _frame(regs)["FY:FY2024"]["addback:restructuring"] == _OFF


def _without_addback(regs: Cp1Registers, period_id: str) -> Cp1Registers:
    """`regs` without the restructuring add-back's row for `period_id`."""
    return replace(
        regs,
        addbacks=tuple(
            b
            for b in regs.addbacks
            if (b.addback_id, b.period_id) != ("restructuring", period_id)
        ),
    )


def test_a_period_on_another_footing_never_takes_its_parts_figure() -> None:
    """The re-verify's L1 (p3, p6 b): FY2024 restated, its quarters as
    reported, no FY2024 restructuring row: never 32 from the quarters, and
    adjusted EBITDA never adds as-reported add-backs to restated EBITDA."""
    regs = _without_addback(
        _footing(example_registers(), FY2024=("RESTATED", "Consolidated")),
        "FY2024",
    )
    assert off_footing(regs) == {"FY2024"}
    assert _frame(regs)["FY:FY2024"]["addback:restructuring"] == _OFF
    model = credit_model(_model_inputs(regs))
    adjusted = _line_cell(model, "adjusted_ebitda", "FY:FY2024")
    assert (adjusted.value, adjusted.reason) == (None, "COMPONENT_MISSING")
    assert OTHER_FOOTING in (adjusted.note or "")
    # Its quarters stating none still make no figure for it.
    unstated = _footing(
        regs, **{f"Q{n}_2024": (None, None) for n in range(1, 5)}, FY2024=("X", None)
    )
    assert _frame(unstated)["FY:FY2024"]["addback:restructuring"] == _OFF
    # With its own row, it is its own figure.
    own = _footing(example_registers(), FY2024=("RESTATED", "Consolidated"))
    assert _frame(own)["FY:FY2024"]["addback:restructuring"].value == 32

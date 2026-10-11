"""Historical columns and derived periods: quarters, PYTD, YTD, FY and LTM."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from datetime import date
from decimal import Decimal

from credit_model_fixture import (
    example_registers,
)
from hypothesis import given, settings
from hypothesis import strategies as st

from caos.calculators.credit_model import history
from caos.calculators.credit_model._cells import SIGN_NORMALISED, UNSPANNED
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
    AccountRow,
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
        "YTD H1 26",
        "LTM Q2 26",
    ]
    # No year to count back from: no PYTD, and no trailing quarters.
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


def test_a_ytd_without_a_fiscal_quarter_is_labelled_by_its_id() -> None:
    regs = _regs(fy={"FY2025": {"revenue": 12}}, ytd={"H1_2026": {"revenue": 6}})
    fy, h1 = regs.periods
    regs = replace(regs, periods=(fy, replace(h1, fiscal_quarter=None)))

    columns = historical_columns(regs)

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
    assert ltm_frames(regs, columns)["Q:Q2_2026"][key].value == 12 + 3 + 3
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
    # (a) rows only for Q1 2025 and H1 2025: FY2025 is its quarters (3), the
    # LTM is 3 + nothing - 3.
    probe = _costs(_sparse_rows(regs, {"Q1_2025": 3, "H1_2025": 3}))
    assert probe["FY:FY2025"] == Cell(
        Decimal(3), basis="CALCULATED", sources=probe["Q:Q1_2025"].sources
    )
    assert probe["LTM:LTM_Q2_2026"].value == 0
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
    # within the year.
    undated = _periods_changed(
        regs, replace(periods["Q3_2025"], start_date=None, day_count=None)
    )
    assert _costs(undated)["FY:FY2025"].value == 8
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
    # (a) H1 2025 and Q3 2025 only: FY2025 is H1 + Q3 + nothing for Q4.
    probe = _costs(_sparse_rows(regs, {"H1_2025": 6, "Q3_2025": 12}))
    assert probe["FY:FY2025"].value == 18
    assert probe["PYTD:H1_2025"].value == 6
    assert probe["LTM:LTM_Q2_2026"].value == 12
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
    # (c) round 2's probe: rows for Q1 2025 and H1 2025 only, LTM nothing.
    first = _costs(_sparse_rows(regs, {"Q1_2025": 3, "H1_2025": 3}))
    assert first["FY:FY2025"].value == 3
    assert first["LTM:LTM_Q2_2026"].value == 0


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

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

"""CP-1, CP-2G and CP-CF tagged tables read into typed credit-model inputs.

Each register becomes typed rows whose figures are the host's parsed `Decimal`
(invariant 7) and whose source keeps the cell text verbatim, `[C<n>]` markers
and all (D107). An older run's debt register without the rate columns reads
them as not stated; a present table missing a column it needs is refused.
"""

from __future__ import annotations

import ast
from datetime import date
from decimal import Decimal

import pytest
from canonical_fixtures import BUNDLE

from caos.calculators.credit_model.frame import Cell, Column, SourceRef
from caos.methodology import model_inputs
from caos.methodology.bundle import verified_bytes
from caos.methodology.model_inputs import (
    AccountRow,
    AddbackRow,
    Cp1Registers,
    DivisionGrowth,
    FacilityRow,
    KpiRow,
    PeriodRow,
    PfAdjustmentRow,
    SegmentRow,
    SlotAllocation,
    cp1_registers,
    division_growth,
    slot_allocation,
)
from caos.methodology.tables import HandoffTable, TableCell
from caos.refusals import Refusal, RefusalCode

PERIOD_COLUMNS = (
    "period_id",
    "fiscal_year",
    "fiscal_quarter",
    "period_type",
    "start_date",
    "end_date",
    "day_count",
    "audit_status",
    "currency",
    "unit",
    "accounting_basis",
    "entity_perimeter",
    "source_id",
    "source_locator",
    "component_period_ids",
)
DEBT_COLUMNS_BEFORE_RATES = (
    "facility_id",
    "facility_name",
    "period_id",
    "facility_type",
    "carrying_value",
    "principal",
    "drawn_amount",
    "commitment",
    "secured_status",
    "seniority",
    "currency",
    "margin_or_coupon",
    "maturity_date",
    "lease_classification",
)
RATE_COLUMNS = (
    "rate_type",
    "reference_rate",
    "spread_bps",
    "floor_bps",
    "fixed_rate",
    "annual_amortisation",
)
SOURCE_COLUMNS = ("source_id", "source_locator")


def cell(text: str, value: str | None = None) -> TableCell:
    return TableCell(text, value)


def figure(text: str, value: str) -> TableCell:
    return TableCell(text, value)


NULL = cell("null")


def period_row(period_id: str, currency: str = "USD") -> tuple[TableCell, ...]:
    return (
        cell(period_id),
        figure("2026", "2026"),
        figure("2", "2"),
        cell("quarter"),
        cell("2026-04-01"),
        cell("2026-06-30"),
        figure("91", "91"),
        cell("UNAUDITED"),
        cell(currency),
        cell("millions"),
        cell("US GAAP"),
        cell("Consolidated"),
        cell("S2"),
        cell("10-Q p. 4"),
        cell("Q1_2026; H1_2026"),
    )


def period_table(*rows: tuple[TableCell, ...]) -> HandoffTable:
    return HandoffTable("cp1.model_period_register", PERIOD_COLUMNS, rows)


def account_table() -> HandoffTable:
    return HandoffTable(
        "cp1.model_account_register",
        (
            "metric_id",
            "period_id",
            "value",
            "sign_convention",
            "value_class",
            "calculation_status",
            "source_id",
            "source_locator",
            "conflict_refs",
            "limitation_refs",
        ),
        (
            (
                cell("revenue"),
                cell("Q2_2026"),
                figure("1,250.0 [C3]", "1250.0"),
                cell("POSITIVE"),
                cell("FLOW"),
                cell("reported"),
                cell("S2"),
                cell("10-Q p. 4"),
                NULL,
                NULL,
            ),
            (
                cell("cash_taxes_paid"),
                cell("Q2_2026"),
                NULL,
                cell("NEGATIVE"),
                cell("FLOW"),
                cell("REPORTED"),
                NULL,
                NULL,
                NULL,
                NULL,
            ),
        ),
    )


def bridge_table() -> HandoffTable:
    return HandoffTable(
        "cp1.adjusted_ebitda_bridge",
        (
            "addback_id",
            "addback_label",
            "addback_classification",
            "realization_status",
            "display_priority",
            "period_id",
            "value",
            "status",
            "source_definition",
            *SOURCE_COLUMNS,
        ),
        (
            (
                cell("SBC"),
                cell("Share-based compensation"),
                cell("sbc"),
                cell("not_stated"),
                figure("1", "1"),
                cell("Q2_2026"),
                figure("(45) [C1]", "-45"),
                cell("Verified"),
                cell("Non-cash"),
                cell("S3"),
                cell("p.12"),
            ),
        ),
    )


def segment_table() -> HandoffTable:
    return HandoffTable(
        "cp1.segment_revenue_schedule",
        (
            "segment_id",
            "segment_name",
            "segment_type",
            "display_priority",
            "period_id",
            "revenue",
            "status",
            *SOURCE_COLUMNS,
        ),
        (
            (
                cell("RETAIL"),
                cell("Retail vehicle sales"),
                cell("operating_segment"),
                figure("1", "1"),
                cell("Q2_2026"),
                figure("3,842 [C4]", "3842"),
                cell("Verified"),
                cell("S2"),
                cell("p.12"),
            ),
        ),
    )


def kpi_table() -> HandoffTable:
    return HandoffTable(
        "cp1.operating_kpi_schedule",
        (
            "kpi_id",
            "kpi_label",
            "business_unit",
            "kpi_category",
            "display_priority",
            "period_id",
            "value",
            "unit",
            "value_type",
            "status",
            *SOURCE_COLUMNS,
        ),
        (
            (
                cell("retail_units_sold"),
                cell("Retail units"),
                cell("Retail"),
                cell("Volume"),
                figure("1", "1"),
                cell("Q2_2026"),
                figure("143,280 [C5]", "143280"),
                cell("units"),
                cell("period_flow"),
                cell("Verified"),
                cell("S4"),
                cell("p.3"),
            ),
        ),
    )


def debt_row_before_rates() -> tuple[TableCell, ...]:
    return (
        cell("TLB"),
        cell("Term Loan B"),
        cell("Q2_2026"),
        cell("term_loan"),
        figure("996 [C6]", "996"),
        figure("1,005", "1005"),
        figure("1,005", "1005"),
        cell("Not applicable"),
        cell("secured"),
        cell("senior"),
        cell("USD"),
        cell("SOFR + 3.20%"),
        cell("2028-12-01"),
        cell("not_lease"),
    )


def debt_table() -> HandoffTable:
    rates = (
        cell("floating"),
        cell("term_sofr"),
        figure("320", "320"),
        figure("50", "50"),
        NULL,
        figure("10", "10"),
    )
    return HandoffTable(
        "cp1.debt_facility_register",
        (*DEBT_COLUMNS_BEFORE_RATES, *RATE_COLUMNS, *SOURCE_COLUMNS),
        ((*debt_row_before_rates(), *rates, cell("S2"), cell("p.21")),),
    )


def pro_forma_table() -> HandoffTable:
    return HandoffTable(
        "cp1.pro_forma_adjustment_register",
        (
            "adjustment_id",
            "label",
            "period_id",
            "effective_date",
            "classification",
            "metric_id",
            "value",
            *SOURCE_COLUMNS,
        ),
        (
            (
                cell("ACQ_1"),
                cell("Acquired dealer group"),
                cell("LTM_Q2_2026"),
                cell("2026-08-01"),
                cell("acquisition"),
                cell("ebitda"),
                figure("12.5 [C7]", "12.5"),
                cell("S5"),
                cell("Lender presentation p.8"),
            ),
        ),
    )


def full_set() -> list[HandoffTable]:
    return [
        period_table(period_row("Q2_2026")),
        account_table(),
        bridge_table(),
        segment_table(),
        kpi_table(),
        debt_table(),
        pro_forma_table(),
    ]


def test_cp1_registers_reads_each_register_into_typed_rows() -> None:
    registers = cp1_registers(full_set())

    assert isinstance(registers, Cp1Registers)
    assert registers.currency == "USD"
    assert registers.unit == "MILLIONS"
    assert registers.periods == (
        PeriodRow(
            period_id="Q2_2026",
            fiscal_year="2026",
            fiscal_quarter="2",
            period_type="QUARTER",
            start_date="2026-04-01",
            end_date="2026-06-30",
            day_count=91,
            currency="USD",
            unit="MILLIONS",
            component_period_ids=("Q1_2026", "H1_2026"),
        ),
    )
    assert registers.accounts == (
        AccountRow(
            metric_id="revenue",
            period_id="Q2_2026",
            value=Decimal("1250.0"),
            calculation_status="REPORTED",
            source=SourceRef("S2", "10-Q p. 4", "1,250.0 [C3]"),
        ),
        AccountRow(
            metric_id="cash_taxes_paid",
            period_id="Q2_2026",
            value=None,
            calculation_status="REPORTED",
            source=None,
        ),
    )
    assert registers.addbacks == (
        AddbackRow(
            addback_id="SBC",
            label="Share-based compensation",
            classification="SBC",
            realization_status="NOT_STATED",
            display_priority=1,
            period_id="Q2_2026",
            value=Decimal("-45"),
            source=SourceRef("S3", "p.12", "(45) [C1]"),
        ),
    )
    assert registers.segments == (
        SegmentRow(
            segment_id="RETAIL",
            segment_name="Retail vehicle sales",
            segment_type="OPERATING_SEGMENT",
            display_priority=1,
            period_id="Q2_2026",
            revenue=Decimal("3842"),
            source=SourceRef("S2", "p.12", "3,842 [C4]"),
        ),
    )
    assert registers.kpis == (
        KpiRow(
            kpi_id="retail_units_sold",
            kpi_label="Retail units",
            display_priority=1,
            period_id="Q2_2026",
            value=Decimal("143280"),
            unit="UNITS",
            value_type="PERIOD_FLOW",
            source=SourceRef("S4", "p.3", "143,280 [C5]"),
        ),
    )
    assert registers.facilities == (
        FacilityRow(
            facility_id="TLB",
            facility_name="Term Loan B",
            period_id="Q2_2026",
            facility_type="TERM_LOAN",
            currency="USD",
            carrying_value=Decimal("996"),
            commitment=None,
            drawn_amount=Decimal("1005"),
            secured_status="SECURED",
            seniority="SENIOR",
            lease_classification="NOT_LEASE",
            maturity_date="2028-12-01",
            margin_or_coupon="SOFR + 3.20%",
            rate_type="FLOATING",
            reference_rate="TERM_SOFR",
            spread_bps=Decimal("320"),
            floor_bps=Decimal("50"),
            fixed_rate=None,
            annual_amortisation=Decimal("10"),
            source=SourceRef("S2", "p.21", "996 [C6]"),
        ),
    )
    assert registers.pro_forma == (
        PfAdjustmentRow(
            adjustment_id="ACQ_1",
            label="Acquired dealer group",
            period_id="LTM_Q2_2026",
            classification="ACQUISITION",
            metric_id="ebitda",
            value=Decimal("12.5"),
            source=SourceRef("S5", "Lender presentation p.8", "12.5 [C7]"),
        ),
    )


def test_a_debt_register_without_the_rate_columns_reads_them_as_not_stated() -> None:
    older = HandoffTable(
        "cp1.debt_facility_register",
        (*DEBT_COLUMNS_BEFORE_RATES, *SOURCE_COLUMNS),
        ((*debt_row_before_rates(), cell("S2"), cell("p.21")),),
    )
    tables = [t for t in full_set() if t.table_id != older.table_id] + [older]

    (facility,) = cp1_registers(tables).facilities

    assert facility.rate_type == "NOT_STATED"
    assert facility.reference_rate == "NOT_STATED"
    assert facility.spread_bps is None
    assert facility.floor_bps is None
    assert facility.fixed_rate is None
    assert facility.annual_amortisation is None
    assert facility.carrying_value == Decimal("996")


def test_a_reference_rate_of_none_is_kept_and_not_read_as_null() -> None:
    table = debt_table()
    row = list(table.rows[0])
    row[table.columns.index("reference_rate")] = cell("none")
    fixed = HandoffTable(table.table_id, table.columns, (tuple(row),))
    tables = [t for t in full_set() if t.table_id != table.table_id] + [fixed]

    (facility,) = cp1_registers(tables).facilities

    assert facility.reference_rate == "NONE"


def test_a_missing_pro_forma_register_is_empty() -> None:
    optional = {"cp1.pro_forma_adjustment_register", "cp1.operating_kpi_schedule"}
    registers = cp1_registers([t for t in full_set() if t.table_id not in optional])

    assert registers.pro_forma == ()
    assert registers.kpis == ()
    assert len(registers.facilities) == 1


def test_a_present_table_missing_a_required_column_is_refused() -> None:
    table = account_table()
    dropped = table.columns.index("value")
    narrowed = HandoffTable(
        table.table_id,
        table.columns[:dropped] + table.columns[dropped + 1 :],
        tuple(row[:dropped] + row[dropped + 1 :] for row in table.rows),
    )
    tables = [t for t in full_set() if t.table_id != table.table_id] + [narrowed]

    with pytest.raises(Refusal) as caught:
        cp1_registers(tables)
    assert caught.value.code == RefusalCode.HANDOFF_MALFORMED


def test_a_row_wider_than_its_header_is_refused() -> None:
    table = segment_table()
    wide = HandoffTable(table.table_id, table.columns, ((*table.rows[0], NULL),))
    tables = [t for t in full_set() if t.table_id != table.table_id] + [wide]

    with pytest.raises(Refusal) as caught:
        cp1_registers(tables)
    assert caught.value.code == RefusalCode.HANDOFF_MALFORMED


_REGISTERS = (
    "cp1.model_period_register",
    "cp1.model_account_register",
    "cp1.adjusted_ebitda_bridge",
    "cp1.segment_revenue_schedule",
    "cp1.operating_kpi_schedule",
    "cp1.debt_facility_register",
    "cp1.pro_forma_adjustment_register",
)


def _with_second_row(table_id: str, period_id: str | None) -> list[HandoffTable]:
    """`full_set()` with `table_id`'s first row written again, its period
    id set to `period_id` (None: kept)."""
    tables = []
    for table in full_set():
        if table.table_id == table_id:
            first = list(table.rows[0])
            if period_id is not None:
                first[table.columns.index("period_id")] = cell(period_id)
                if table_id == "cp1.model_period_register":
                    first[table.columns.index("fiscal_quarter")] = figure("1", "1")
                    # Q2's components name Q1: Q1 naming them too is a cycle.
                    first[table.columns.index("component_period_ids")] = NULL
            table = HandoffTable(
                table.table_id, table.columns, (*table.rows, tuple(first))
            )
        tables.append(table)
    return tables


@pytest.mark.parametrize("table_id", _REGISTERS)
def test_a_register_naming_one_row_twice_is_refused(table_id: str) -> None:
    with pytest.raises(Refusal) as caught:
        cp1_registers(_with_second_row(table_id, None))
    assert caught.value.code == RefusalCode.HANDOFF_MALFORMED


@pytest.mark.parametrize("table_id", _REGISTERS)
def test_one_id_in_two_periods_is_two_rows(table_id: str) -> None:
    registers = cp1_registers(_with_second_row(table_id, "Q1_2026"))

    assert "Q1_2026" in {
        row.period_id
        for rows in (
            registers.periods,
            registers.accounts,
            registers.addbacks,
            registers.segments,
            registers.kpis,
            registers.facilities,
            registers.pro_forma,
        )
        for row in rows
    }


def _period(
    period_id: str, period_type: str, year: str, quarter: str | None
) -> tuple[TableCell, ...]:
    row = list(period_row(period_id))
    row[PERIOD_COLUMNS.index("period_type")] = cell(period_type)
    row[PERIOD_COLUMNS.index("fiscal_year")] = cell(year)
    row[PERIOD_COLUMNS.index("fiscal_quarter")] = (
        NULL if quarter is None else cell(quarter)
    )
    row[PERIOD_COLUMNS.index("component_period_ids")] = NULL
    return tuple(row)


def _with_periods(*rows: tuple[TableCell, ...]) -> list[HandoffTable]:
    return [period_table(*rows), *full_set()[1:]]


@pytest.mark.parametrize(
    ("period_type", "first", "second"),
    [
        ("quarter", ("2026", "2"), ("2026", "Q2")),
        ("ytd", ("2026", "2"), ("FY2026", "2")),
        ("fy", ("2025", None), ("FY 2025", None)),
    ],
)
def test_two_periods_for_one_fiscal_period_are_refused(
    period_type: str, first: tuple[str, str | None], second: tuple[str, str | None]
) -> None:
    tables = _with_periods(
        period_row("Q2_2026"),
        _period("A", period_type, *first),
        _period("B", period_type, *second),
    )

    with pytest.raises(Refusal) as caught:
        cp1_registers(tables)
    assert caught.value.code == RefusalCode.HANDOFF_MALFORMED


def test_periods_of_other_types_or_years_may_share_a_quarter() -> None:
    registers = cp1_registers(
        _with_periods(
            period_row("Q2_2026"),
            _period("H1_2026", "ytd", "2026", "2"),
            _period("Q2_2025", "quarter", "FY2025", "2"),
            _period("Q_NULL_A", "quarter", "2026", None),
            _period("Q_NULL_B", "quarter", "2026", None),
        )
    )

    assert [p.fiscal_year for p in registers.periods] == [
        "2026",
        "2026",
        "FY2025",
        "2026",
        "2026",
    ]


@pytest.mark.parametrize("year", ["FY25", "Fiscal year", "20256", ""])
def test_a_fiscal_year_without_a_four_digit_year_is_refused(year: str) -> None:
    with pytest.raises(Refusal) as caught:
        cp1_registers(_with_periods(_period("FY_X", "fy", year, None)))
    assert caught.value.code == RefusalCode.HANDOFF_MALFORMED


@pytest.mark.parametrize(
    ("text", "year"),
    [
        ("2025", 2025),
        ("FY2025", 2025),
        ("FY 2025/26", 2026),
        ("FY2025/26", 2026),
        ("FY2025/2026", 2026),
        ("2025-26", 2026),
        ("FY 2025 - 26", 2026),
        ("FY1999/00", 2000),
        ("FY2025-12", 2025),
        ("FY2024/2025 (was 2026/2028)", 2025),
        ("FY25", None),
        ("20256", None),
    ],
)
def test_fiscal_year_number_reads_a_two_year_spelling_as_its_end_year(
    text: str, year: int | None
) -> None:
    assert model_inputs.fiscal_year_number(text) == year


def test_a_missing_period_register_is_refused() -> None:
    tables = [t for t in full_set() if t.table_id != "cp1.model_period_register"]

    with pytest.raises(Refusal) as caught:
        cp1_registers(tables)
    assert caught.value.code == RefusalCode.HANDOFF_MALFORMED


def replaced(table: HandoffTable, column: str, new: TableCell) -> HandoffTable:
    """`table` with `column` set to `new` in every row."""
    at = table.columns.index(column)
    rows = tuple((*row[:at], new, *row[at + 1 :]) for row in table.rows)
    return HandoffTable(table.table_id, table.columns, rows)


def with_table(table: HandoffTable) -> list[HandoffTable]:
    return [t for t in full_set() if t.table_id != table.table_id] + [table]


REQUIRED_ENUMERATIONS = [
    ("cp1.model_period_register", "currency"),
    ("cp1.model_period_register", "unit"),
    ("cp1.model_period_register", "period_type"),
    ("cp1.model_account_register", "calculation_status"),
    ("cp1.adjusted_ebitda_bridge", "addback_classification"),
    ("cp1.adjusted_ebitda_bridge", "realization_status"),
    ("cp1.segment_revenue_schedule", "segment_type"),
    ("cp1.operating_kpi_schedule", "unit"),
    ("cp1.operating_kpi_schedule", "value_type"),
    ("cp1.debt_facility_register", "facility_type"),
    ("cp1.debt_facility_register", "currency"),
    ("cp1.debt_facility_register", "secured_status"),
    ("cp1.debt_facility_register", "seniority"),
    ("cp1.debt_facility_register", "lease_classification"),
    ("cp1.pro_forma_adjustment_register", "classification"),
]


@pytest.mark.parametrize("null", ["null", "N/A", "\u2014", ""])
@pytest.mark.parametrize(("table_id", "column"), REQUIRED_ENUMERATIONS)
def test_a_null_in_a_required_enumeration_is_refused(
    table_id: str, column: str, null: str
) -> None:
    [table] = [t for t in full_set() if t.table_id == table_id]

    with pytest.raises(Refusal) as caught:
        cp1_registers(with_table(replaced(table, column, cell(null))))
    assert caught.value.code == RefusalCode.HANDOFF_MALFORMED


@pytest.mark.parametrize("column", ["rate_type", "reference_rate"])
def test_a_null_rate_term_reads_as_not_stated(column: str) -> None:
    table = replaced(debt_table(), column, NULL)

    (facility,) = cp1_registers(with_table(table)).facilities

    assert getattr(facility, column) == "NOT_STATED"


@pytest.mark.parametrize("status", ["Not Available", "Not Calculable", "not available"])
def test_a_calculation_status_of_not_available_is_a_status_not_a_null(
    status: str,
) -> None:
    table = replaced(account_table(), "calculation_status", cell(status))

    accounts = cp1_registers(with_table(table)).accounts

    assert [(row.calculation_status, row.value) for row in accounts] == [
        (status.upper(), Decimal("1250.0")),
        (status.upper(), None),
    ]


def _validator_constant(name: str) -> object:
    source = verified_bytes(BUNDLE, "CP-MODEL", "scripts/validate_cp_model_inputs.py")
    [value] = [
        ast.literal_eval(node.value)
        for node in ast.parse(source).body
        if isinstance(node, ast.Assign)
        and any(isinstance(t, ast.Name) and t.id == name for t in node.targets)
    ]
    return value


def test_the_null_text_is_the_cp_model_validators_own() -> None:
    assert model_inputs._NULL_TEXT == _validator_constant("NULL_TEXT")


def test_the_vocabularies_are_the_cp_model_validators_own() -> None:
    pairs = {
        "PERIOD_TYPES": model_inputs._PERIOD_TYPES,
        "PERIOD_UNITS": model_inputs._PERIOD_UNITS,
        "ADDBACK_CLASSIFICATIONS": model_inputs._ADDBACK_CLASSIFICATIONS,
        "ADDBACK_REALIZATION_STATUSES": model_inputs._REALIZATION_STATUSES,
        "SEGMENT_TYPES": model_inputs._SEGMENT_TYPES,
        "OPERATING_KPI_VALUE_TYPES": model_inputs._KPI_VALUE_TYPES,
        "FORECAST_CASES": model_inputs._DRIVER_CASES,
        "FORECAST_STATUSES": model_inputs._DRIVER_STATUSES,
    }

    for name, vocabulary in pairs.items():
        assert vocabulary == _validator_constant(name), name


def test_the_calculation_statuses_are_cp1s_own_and_two_are_null_text() -> None:
    steps = verified_bytes(BUNDLE, "CP-1", "references/REF_CP-1_STEPS.md").decode()
    [line] = [x for x in steps.splitlines() if x.startswith("3. Calculation status")]
    written = {part.strip(" `") for part in line.split(":", 1)[1].split("|")}

    assert {s.upper() for s in written} == model_inputs._CALCULATION_STATUSES
    assert {s.casefold() for s in written} & model_inputs._NULL_TEXT == {
        "not available",
        "not calculable",
    }


def test_a_debt_adjustment_written_with_an_underscore_is_the_adjustment_row() -> None:
    table = replaced(
        replaced(debt_table(), "facility_type", cell("DEBT_ADJUSTMENT")),
        "carrying_value",
        figure("-6", "-6"),
    )

    (facility,) = cp1_registers(with_table(table)).facilities

    assert facility.facility_type == "DEBT ADJUSTMENT"
    assert facility.carrying_value == Decimal(-6)


_REGISTER_OF = {
    "cp1.model_period_register": "periods",
    "cp1.model_account_register": "accounts",
    "cp1.adjusted_ebitda_bridge": "addbacks",
    "cp1.segment_revenue_schedule": "segments",
    "cp1.operating_kpi_schedule": "kpis",
    "cp1.debt_facility_register": "facilities",
    "cp1.pro_forma_adjustment_register": "pro_forma",
}


@pytest.mark.parametrize(
    ("table_id", "column", "written", "canonical"),
    [
        ("cp1.model_period_register", "period_type", "Quarter", "QUARTER"),
        ("cp1.model_period_register", "unit", " Millions ", "MILLIONS"),
        (
            "cp1.model_account_register",
            "calculation_status",
            "not_calculable",
            "NOT CALCULABLE",
        ),
        (
            "cp1.adjusted_ebitda_bridge",
            "addback_classification",
            "Transaction  Costs",
            "TRANSACTION_COSTS",
        ),
        (
            "cp1.adjusted_ebitda_bridge",
            "realization_status",
            "not-stated",
            "NOT_STATED",
        ),
        (
            "cp1.segment_revenue_schedule",
            "segment_type",
            "Corporate Elimination",
            "CORPORATE_ELIMINATION",
        ),
        ("cp1.operating_kpi_schedule", "value_type", "period end", "PERIOD_END"),
        (
            "cp1.debt_facility_register",
            "facility_type",
            "debt-adjustment",
            "DEBT ADJUSTMENT",
        ),
        ("cp1.debt_facility_register", "secured_status", "Not Stated", "NOT_STATED"),
        ("cp1.debt_facility_register", "seniority", "super senior", "SUPER_SENIOR"),
        (
            "cp1.debt_facility_register",
            "lease_classification",
            "operating lease",
            "OPERATING_LEASE",
        ),
        ("cp1.debt_facility_register", "rate_type", "not stated", "NOT_STATED"),
        ("cp1.debt_facility_register", "reference_rate", "Term SOFR", "TERM_SOFR"),
        (
            "cp1.pro_forma_adjustment_register",
            "classification",
            "subsequent event",
            "SUBSEQUENT_EVENT",
        ),
    ],
)
def test_a_vocabulary_member_matches_on_case_and_separators(
    table_id: str, column: str, written: str, canonical: str
) -> None:
    [table] = [t for t in full_set() if t.table_id == table_id]

    registers = cp1_registers(with_table(replaced(table, column, cell(written))))

    [row, *_] = getattr(registers, _REGISTER_OF[table_id])
    assert getattr(row, column.removeprefix("addback_")) == canonical


def test_a_driver_vocabulary_matches_on_case_and_separators() -> None:
    row = list(driver("division_growth", "D1", "Base", "Ready", figure("0.08", "0.08")))
    row[6] = cell("percent-decimal")
    table = HandoffTable(
        "cp2g.cp_model_forecast_drivers", DRIVER_COLUMNS, (tuple(row),)
    )

    (growth,) = division_growth([table])

    assert (growth.case, growth.value) == ("BASE", Decimal("0.08"))


def test_mixed_units_in_the_period_register_are_refused() -> None:
    other = replaced(period_table(period_row("Q2_2026")), "unit", cell("THOUSANDS"))
    mixed = period_table(period_row("Q1_2026"), *other.rows)

    with pytest.raises(Refusal) as caught:
        cp1_registers([mixed, *full_set()[1:]])
    assert caught.value.code == RefusalCode.HANDOFF_MALFORMED


def test_mixed_currencies_in_the_period_register_are_refused() -> None:
    mixed = period_table(period_row("Q1_2026"), period_row("Q2_2026", currency="EUR"))
    tables = [mixed, *full_set()[1:]]

    with pytest.raises(Refusal) as caught:
        cp1_registers(tables)
    assert caught.value.code == RefusalCode.HANDOFF_MALFORMED


DRIVER_COLUMNS = (
    "driver_id",
    "slot_id",
    "case",
    "period_id",
    "fiscal_year",
    "value",
    "unit",
    "assumption_id",
    "status",
    "source_id",
    "source_locator",
    "as_of",
)


def driver(
    driver_id: str, slot: str, case: str, status: str, value: TableCell
) -> tuple[TableCell, ...]:
    return (
        cell(driver_id),
        cell(slot),
        cell(case),
        cell("FY2027"),
        figure("2027", "2027"),
        value,
        cell("PERCENT_DECIMAL"),
        cell("A-1"),
        cell(status),
        cell("S1"),
        cell("p.31"),
        cell("2026-09-08"),
    )


def test_division_growth_keeps_ready_rows_only() -> None:
    table = HandoffTable(
        "cp2g.cp_model_forecast_drivers",
        DRIVER_COLUMNS,
        (
            driver(
                "division_growth", "division_1", "base", "ready", figure("0.08", "0.08")
            ),
            driver(
                "division_growth",
                "DIVISION_2",
                "DOWNSIDE",
                "READY",
                figure("-0.02", "-0.02"),
            ),
            driver("division_growth", "DIVISION_3", "BASE", "NOT_APPLICABLE", cell("")),
            driver("dividends_paid", "", "BASE", "READY", figure("(10)", "-10")),
            driver(
                "division_growth",
                "DIVISION_1",
                "UPSIDE",
                "READY",
                figure("0.12", "0.12"),
            ),
        ),
    )

    assert division_growth([table]) == (
        DivisionGrowth("BASE", "2027", "DIVISION_1", Decimal("0.08")),
        DivisionGrowth("DOWNSIDE", "2027", "DIVISION_2", Decimal("-0.02")),
    )
    assert division_growth([]) == ()


def test_a_ready_division_growth_row_without_a_value_is_refused() -> None:
    table = HandoffTable(
        "cp2g.cp_model_forecast_drivers",
        DRIVER_COLUMNS,
        (driver("division_growth", "DIVISION_1", "BASE", "READY", NULL),),
    )

    with pytest.raises(Refusal) as caught:
        division_growth([table])
    assert caught.value.code == RefusalCode.HANDOFF_MALFORMED


def drivers(*rows: tuple[TableCell, ...]) -> HandoffTable:
    return HandoffTable("cp2g.cp_model_forecast_drivers", DRIVER_COLUMNS, rows)


def test_a_percent_division_growth_cell_reads_as_a_fraction() -> None:
    table = drivers(
        driver(
            "division_growth", "DIVISION_1", "BASE", "READY", figure("8% [C2]", "8")
        ),
        driver(
            "division_growth", "DIVISION_2", "BASE", "READY", figure("(2.5%)", "-2.5")
        ),
    )

    assert division_growth([table]) == (
        DivisionGrowth("BASE", "2027", "DIVISION_1", Decimal("0.08")),
        DivisionGrowth("BASE", "2027", "DIVISION_2", Decimal("-0.025")),
    )


def test_a_ready_division_growth_row_in_another_unit_is_refused() -> None:
    row = driver("division_growth", "DIVISION_1", "BASE", "READY", figure("8", "8"))
    table = replaced(drivers(row), "unit", cell("PERCENT"))

    with pytest.raises(Refusal) as caught:
        division_growth([table])
    assert caught.value.code == RefusalCode.HANDOFF_MALFORMED


@pytest.mark.parametrize("column", ["case", "status"])
def test_a_null_driver_case_or_status_is_refused(column: str) -> None:
    row = driver(
        "division_growth", "DIVISION_1", "BASE", "READY", figure("0.08", "0.08")
    )
    table = replaced(drivers(row), column, NULL)

    with pytest.raises(Refusal) as caught:
        division_growth([table])
    assert caught.value.code == RefusalCode.HANDOFF_MALFORMED


def test_slot_allocation_reads_each_slot_and_its_segments() -> None:
    table = HandoffTable(
        "cp1.cp_model_segment_allocation",
        ("slot_id", "slot_label", "component_segment_ids"),
        (
            (cell("division_1"), cell("Retail"), cell("RETAIL, OTHER")),
            (cell("DIVISION_2"), cell("Wholesale"), cell("WHOLESALE")),
        ),
    )

    assert slot_allocation([table]) == (
        SlotAllocation("DIVISION_1", ("RETAIL", "OTHER")),
        SlotAllocation("DIVISION_2", ("WHOLESALE",)),
    )
    assert slot_allocation([]) == ()


def test_frame_types_hold_their_fields() -> None:
    source = SourceRef("S1", "p.1", "10 [C1]")
    held = Cell(Decimal("10"), basis="REPORTED", sources=(source,))
    missing = Cell(None, reason="NOT_SOURCED")
    column = Column(
        column_id="Q:Q2_2026",
        kind="QUARTER",
        label="Q2 26",
        period_id="Q2_2026",
        fiscal_year="2026",
        end_date="2026-06-30",
        days=91,
        case=None,
    )

    assert held.reason is None and held.sources == (source,)
    assert missing.value is None and missing.basis is None and missing.note is None
    assert column.kind == "QUARTER" and column.case is None


def test_another_driver_with_a_null_case_or_status_does_not_abort_the_growth_read() -> (
    None
):
    table = drivers(
        driver("dividends_paid", "", "", "", figure("(10)", "-10")),
        driver(
            "division_growth", "DIVISION_1", "BASE", "READY", figure("0.08", "0.08")
        ),
    )

    assert division_growth([table]) == (
        DivisionGrowth("BASE", "2027", "DIVISION_1", Decimal("0.08")),
    )


def test_a_segment_in_two_slots_is_refused() -> None:
    table = HandoffTable(
        "cp1.cp_model_segment_allocation",
        ("slot_id", "slot_label", "component_segment_ids"),
        (
            (cell("DIVISION_1"), cell("Retail"), cell("RETAIL")),
            (cell("DIVISION_2"), cell("Mixed"), cell("WHOLESALE; RETAIL")),
        ),
    )

    with pytest.raises(Refusal) as caught:
        slot_allocation([table])
    assert caught.value.code == RefusalCode.HANDOFF_MALFORMED


def _dated(
    start: str | None, end: str | None, days: str | None
) -> tuple[TableCell, ...]:
    """Q2 2026's period row with its start, end and day count replaced, its
    fiscal year the end's where the end is a date."""
    row = list(period_row("Q2_2026"))
    for column, text in (("start_date", start), ("end_date", end)):
        row[PERIOD_COLUMNS.index(column)] = NULL if text is None else cell(text)
    if end is not None and model_inputs.iso_date(end) is not None:
        row[PERIOD_COLUMNS.index("fiscal_year")] = cell(end[:4])
    row[PERIOD_COLUMNS.index("day_count")] = (
        NULL if days is None else figure(days, days)
    )
    return tuple(row)


@pytest.mark.parametrize(
    ("start", "end", "days"),
    [
        ("2026-04-01", "31/12/2025", None),
        ("2026-04-01", "2026-06-30T00:00:00", None),
        ("2026-04-01", "20260630", None),
        ("20260401", "2026-06-30", None),
        ("2026-04-01", "2026-06-31", None),
        ("2026-04-01", "9999-12-31", None),
        ("1899-12-31", "2026-06-30", None),
        ("2026-04-01", "2201-01-01", None),
        ("2026-04-01", "2026-06-30", "800000"),
        ("2026-04-01", "2026-06-30", "-90"),
        ("2026-04-01", "2026-06-30", "90"),
        ("2026-06-30", "2026-04-01", None),
        ("2026-06-30", "2026-04-01", "-89"),
        (None, None, "0"),
        (None, None, "-90"),
        (None, None, "800000"),
        (None, "9999-12-31", None),
    ],
)
def test_a_period_date_or_day_count_that_is_not_a_calendar_span_is_refused(
    start: str | None, end: str | None, days: str | None
) -> None:
    with pytest.raises(Refusal) as caught:
        cp1_registers(_with_periods(_dated(start, end, days)))
    assert caught.value.code == RefusalCode.HANDOFF_MALFORMED


@pytest.mark.parametrize(
    ("start", "end", "days"),
    [
        ("2026-04-01", "2026-06-30", "91"),
        ("2026-04-01", "2026-06-30", None),
        ("1900-01-01", "2200-12-31", "109938"),
        (None, "2026-06-30", "91"),
        ("2026-04-01", None, None),
        (None, None, None),
        ("2026-06-30", "2026-06-30", "1"),
    ],
)
def test_a_period_with_iso_dates_and_a_matching_day_count_reads(
    start: str | None, end: str | None, days: str | None
) -> None:
    (period,) = cp1_registers(_with_periods(_dated(start, end, days))).periods

    assert (period.start_date, period.end_date) == (start, end)
    assert period.day_count == (None if days is None else int(days))


def test_iso_date_reads_only_a_strict_calendar_date() -> None:
    assert model_inputs.iso_date("2024-02-29") == date(2024, 2, 29)
    for text in ("2025-02-29", "20250101", "2025-1-01", "2025-01-01T00:00", None):
        assert model_inputs.iso_date(text) is None
    assert model_inputs.iso_date("0000-01-01") is None
    assert model_inputs.iso_date("١٩٠٠-01-01") is None


def _chained(*links: tuple[str, str]) -> list[HandoffTable]:
    """A register of PERIOD_END rows, each naming its components."""
    rows = []
    for period_id, components in links:
        row = list(_period(period_id, "period_end", "2026", None))
        row[PERIOD_COLUMNS.index("component_period_ids")] = cell(components)
        rows.append(tuple(row))
    return _with_periods(*rows)


def test_a_period_naming_one_component_twice_is_refused() -> None:
    with pytest.raises(Refusal) as caught:
        cp1_registers(_chained(("H1", "Q1; Q1; Q2"), ("Q1", ""), ("Q2", "")))
    assert caught.value.code == RefusalCode.HANDOFF_MALFORMED


def test_at_most_two_hundred_periods_are_read() -> None:
    rows = [_period(f"P{n}", "period_end", "2026", None) for n in range(201)]

    assert len(cp1_registers(_with_periods(*rows[:200])).periods) == 200
    with pytest.raises(Refusal) as caught:
        cp1_registers(_with_periods(*rows))
    assert caught.value.code == RefusalCode.HANDOFF_MALFORMED


@pytest.mark.parametrize("facility_type", ["term_loan", "debt adjustments"])
def test_a_negative_carrying_value_is_refused_except_a_debt_adjustment(
    facility_type: str,
) -> None:
    table = replaced(debt_table(), "carrying_value", figure("(996)", "-996"))
    table = replaced(table, "facility_type", cell(facility_type))

    with pytest.raises(Refusal) as caught:
        cp1_registers(with_table(table))
    assert caught.value.code == RefusalCode.HANDOFF_MALFORMED
    zero = replaced(table, "carrying_value", figure("0", "0"))
    assert cp1_registers(with_table(zero)).facilities[0].carrying_value == 0
    adjustment = replaced(table, "facility_type", cell("debt adjustment"))
    (row,) = cp1_registers(with_table(adjustment)).facilities
    assert row.carrying_value == Decimal(-996)
    assert row.facility_type == "DEBT ADJUSTMENT"


@pytest.mark.parametrize("metric_id", ["rcf_drawn", "rcf_commitment"])
def test_a_negative_rcf_balance_is_refused(metric_id: str) -> None:
    first = account_table()
    table = HandoffTable(first.table_id, first.columns, first.rows[:1])
    table = replaced(table, "metric_id", cell(metric_id))
    negative = replaced(table, "value", figure("(5)", "-5"))

    with pytest.raises(Refusal) as caught:
        cp1_registers(with_table(negative))
    assert caught.value.code == RefusalCode.HANDOFF_MALFORMED
    zero = replaced(table, "value", figure("0", "0"))
    assert {a.value for a in cp1_registers(with_table(zero)).accounts} == {Decimal(0)}
    revenue = HandoffTable(first.table_id, first.columns, first.rows[:1])
    other = replaced(revenue, "value", figure("(5)", "-5"))
    assert {a.value for a in cp1_registers(with_table(other)).accounts} == {Decimal(-5)}


def _in_year(row: tuple[TableCell, ...], year: str) -> tuple[TableCell, ...]:
    at = DRIVER_COLUMNS.index("fiscal_year")
    return (*row[:at], figure(year, year), *row[at + 1 :])


def test_a_growth_row_written_twice_for_one_case_year_and_slot_is_refused() -> None:
    first = driver(
        "division_growth", "DIVISION_1", "BASE", "READY", figure("0.025", "0.025")
    )
    again = _in_year(
        driver(
            "division_growth", "division_1", "base", "ready", figure("0.25", "0.25")
        ),
        "FY2027",
    )

    with pytest.raises(Refusal) as caught:
        division_growth([drivers(first, again)])
    assert caught.value.code == RefusalCode.HANDOFF_MALFORMED
    # Another year, case or slot, or a row not READY, is no second figure.
    kept = (
        first,
        _in_year(first, "2028"),
        driver("division_growth", "DIVISION_1", "DOWNSIDE", "READY", figure("0", "0")),
        driver("division_growth", "DIVISION_2", "BASE", "READY", figure("0", "0")),
        driver("division_growth", "DIVISION_1", "BASE", "NOT_APPLICABLE", cell("")),
    )
    assert len(division_growth([drivers(*kept)])) == 4


@pytest.mark.parametrize(
    ("column", "written"),
    [
        ("spread_bps", figure("2.25% [C8]", "2.25")),  # a percent in a bp column
        ("spread_bps", figure("2%", "2")),  # whole, but still a percent
        ("spread_bps", figure("212.5", "212.5")),  # not a whole basis point
        ("floor_bps", figure("0.50%", "0.50")),
        ("floor_bps", figure("12.5", "12.5")),
        ("fixed_rate", figure("0.065", "0.065")),  # a decimal, not a percent
        ("fixed_rate", figure("0.49", "0.49")),
        ("fixed_rate", figure("30.01%", "30.01")),
    ],
)
def test_a_rate_term_in_the_wrong_unit_is_flagged_out_of_range(
    column: str, written: TableCell
) -> None:
    table = replaced(debt_table(), column, written)

    (facility,) = cp1_registers(with_table(table)).facilities

    assert facility.terms_out_of_range
    assert getattr(facility, column) == Decimal(str(written.value))


@pytest.mark.parametrize(
    ("column", "written"),
    [
        ("spread_bps", figure("320", "320")),
        ("spread_bps", figure("275.00", "275.00")),
        ("floor_bps", NULL),
        ("fixed_rate", figure("6.5% [C8]", "6.5")),
        ("fixed_rate", figure("0.5", "0.5")),
        ("fixed_rate", figure("30", "30")),
    ],
)
def test_a_rate_term_in_its_unit_is_not_flagged(
    column: str, written: TableCell
) -> None:
    table = replaced(debt_table(), column, written)

    (facility,) = cp1_registers(with_table(table)).facilities

    assert not facility.terms_out_of_range


@pytest.mark.parametrize("year", ["FY1000", "FY2201"])
def test_an_undated_fiscal_year_outside_1900_to_2200_is_refused(year: str) -> None:
    row = list(_period("FY_X", "fy", year, None))
    for column in ("start_date", "end_date", "day_count"):
        row[PERIOD_COLUMNS.index(column)] = NULL

    with pytest.raises(Refusal) as caught:
        cp1_registers(_with_periods(tuple(row)))
    assert caught.value.code == RefusalCode.HANDOFF_MALFORMED


@pytest.mark.parametrize("column", ["commitment", "drawn_amount"])
@pytest.mark.parametrize("facility_type", ["term_loan", "debt adjustment"])
def test_a_negative_commitment_or_drawing_is_refused(
    column: str, facility_type: str
) -> None:
    table = replaced(debt_table(), "facility_type", cell(facility_type))

    with pytest.raises(Refusal) as caught:
        cp1_registers(with_table(replaced(table, column, figure("(5)", "-5"))))
    assert caught.value.code == RefusalCode.HANDOFF_MALFORMED
    (row,) = cp1_registers(
        with_table(replaced(table, column, figure("0", "0")))
    ).facilities
    assert getattr(row, column) == Decimal(0)


def _revenue(written: TableCell) -> list[HandoffTable]:
    first = account_table()
    table = HandoffTable(first.table_id, first.columns, first.rows[:1])
    return with_table(replaced(table, "value", written))


@pytest.mark.parametrize(
    "value",
    [
        "1" * 45,
        "-" + "1" * 45,
        "1000000000000000000",
        "-1000000000000000000",
        "0.12345678901",
        "1.00000000000",
        "NaN",
        "Infinity",
    ],
)
def test_a_figure_out_of_bounds_is_refused_not_rounded(value: str) -> None:
    with pytest.raises(Refusal) as caught:
        cp1_registers(_revenue(figure(value, value)))
    assert caught.value.code == RefusalCode.HANDOFF_MALFORMED


@pytest.mark.parametrize(
    "value", ["999999999999999999", "-999999999999999999", "0.1234567890", "0"]
)
def test_a_figure_inside_its_bounds_reads_exactly(value: str) -> None:
    (row,) = cp1_registers(_revenue(figure(value, value))).accounts

    assert row.value == Decimal(value)
    assert str(row.value) == value


def test_a_parenthesised_zero_reads_as_zero() -> None:
    (row,) = cp1_registers(_revenue(figure("(0)", "-0"))).accounts

    assert row.value is not None
    assert (str(row.value), row.value.is_signed()) == ("0", False)


def test_a_floor_written_as_a_percent_is_flagged_without_a_spread() -> None:
    table = replaced(debt_table(), "spread_bps", NULL)
    table = replaced(table, "floor_bps", figure("0.50%", "0.50"))

    (facility,) = cp1_registers(with_table(table)).facilities

    assert facility.terms_out_of_range


@pytest.mark.parametrize("second", [("2026", "2"), ("FY2026", "Q2"), ("2026", "q2")])
def test_one_fiscal_quarter_written_two_ways_is_refused(
    second: tuple[str, str],
) -> None:
    first = _period("A", "quarter", "2026", "1")
    tables = _with_periods(first, _period("B", "quarter", "2026", "Q1"))
    with pytest.raises(Refusal) as caught:
        cp1_registers(tables)
    assert caught.value.code == RefusalCode.HANDOFF_MALFORMED
    # Another quarter of the same year is no second figure.
    other = _period("B", "quarter", *second)
    assert len(cp1_registers(_with_periods(first, other)).periods) == 2


def test_a_source_without_a_locator_reads_an_empty_locator() -> None:
    table = replaced(debt_table(), "source_locator", NULL)

    (facility,) = cp1_registers(with_table(table)).facilities

    assert facility.source == SourceRef("S2", "", "996 [C6]")


def test_growth_in_two_years_without_four_digits_is_two_figures() -> None:
    first = driver(
        "division_growth", "DIVISION_1", "BASE", "READY", figure("0.02", "0.02")
    )
    rows = (_in_year(first, "next year"), _in_year(first, "year after"))

    assert len(division_growth([drivers(*rows)])) == 2

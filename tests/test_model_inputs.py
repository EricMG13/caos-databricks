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
    FacilityRow,
    KpiRow,
    PeriodRow,
    PfAdjustmentRow,
    SegmentRow,
    cp1_registers,
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


@pytest.mark.parametrize("column", ["rate_type", "reference_rate"])
def test_a_null_rate_term_reads_as_not_stated(column: str) -> None:
    table = replaced(debt_table(), column, NULL)

    (facility,) = cp1_registers(with_table(table)).facilities

    assert getattr(facility, column) == "NOT_STATED"


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


def test_iso_date_reads_only_a_strict_calendar_date() -> None:
    assert model_inputs.iso_date("2024-02-29") == date(2024, 2, 29)
    for text in ("2025-02-29", "20250101", "2025-1-01", "2025-01-01T00:00", None):
        assert model_inputs.iso_date(text) is None
    assert model_inputs.iso_date("0000-01-01") is None
    assert model_inputs.iso_date("١٩٠٠-01-01") is None

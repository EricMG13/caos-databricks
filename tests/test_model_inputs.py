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
from caos.methodology.tables import HandoffTable, TableCell

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

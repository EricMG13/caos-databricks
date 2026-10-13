"""The public owner-input facade preserves historical selection and purity."""

from __future__ import annotations

import subprocess
import sys
from copy import deepcopy
from dataclasses import replace
from decimal import Decimal

import pytest
from credit_model_fixture import example_registers

from caos.calculators.credit_model._cells import UNSPANNED
from caos.calculators.credit_model.owner_inputs import (
    facility_stack_at,
    fiscal_year_note,
)


def test_facility_stack_at_preserves_anchor_priority_identity_and_inputs() -> None:
    original = example_registers()
    base = original.facilities[0]
    missing = replace(base, facility_id="loan", period_id="FY", carrying_value=None)
    prior = replace(missing, period_id="PE", carrying_value=Decimal("75"))
    zero = replace(base, facility_id="zero", period_id="FY", carrying_value=Decimal(0))
    later = replace(zero, period_id="PE", carrying_value=Decimal("90"))
    absent = replace(missing, facility_id="absent")
    regs = replace(original, facilities=(missing, zero, absent, prior, later))
    periods: list[str | None] = ["FY", "PE", None]
    before = deepcopy((regs, periods))
    stack = facility_stack_at(regs, periods)
    assert list(stack) == ["loan", "zero", "absent"]
    assert stack["loan"] is prior
    assert stack["zero"] is zero
    assert stack["absent"] is absent
    assert (regs, periods) == before
    assert facility_stack_at(regs, []) == {}
    assert facility_stack_at(regs, ["unknown"]) == {}
    assert facility_stack_at(regs, ["PE", "FY"])["zero"] is later


@pytest.mark.parametrize(
    ("start", "end", "days", "expected"),
    [
        ("2024-01-01", "2024-12-31", 366, None),
        ("2024-07-01", "2025-06-30", 365, None),
        ("2024-01-01", "2024-06-30", 182, "short fiscal year (FY)"),
        ("2024-01-01", "2025-06-30", 547, "long fiscal year (FY)"),
        (None, None, None, UNSPANNED),
    ],
)
def test_fiscal_year_note_preserves_classification_and_input(
    start: str | None, end: str | None, days: int | None, expected: str | None
) -> None:
    period = replace(
        example_registers().periods[0],
        period_id="FY",
        start_date=start,
        end_date=end,
        day_count=days,
    )
    before = deepcopy(period)
    assert fiscal_year_note(period) == expected
    assert period == before


@pytest.mark.parametrize(
    "first",
    [
        "caos.methodology.model_inputs",
        "caos.methodology.forecast",
        "caos.methodology.forecast_debt_service",
        "caos.methodology.forecast_segments",
        "caos.calculators.credit_model.owner_inputs",
        "caos.calculators.credit_model.assemble",
        "caos.api.app",
        "caos.methodology.canonical",
    ],
)
def test_owner_inputs_cold_import_order(first: str) -> None:
    modules = [
        first,
        "caos.methodology.model_inputs",
        "caos.methodology.forecast",
        "caos.methodology.forecast_debt_service",
        "caos.methodology.forecast_segments",
        "caos.calculators.credit_model.owner_inputs",
        "caos.calculators.credit_model.assemble",
        "caos.api.app",
        "caos.methodology.canonical",
    ]
    result = subprocess.run(
        [
            sys.executable,
            "-B",
            "-c",
            "import importlib, sys; "
            "[importlib.import_module(name) for name in sys.argv[1:]]",
            *modules,
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr

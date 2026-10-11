"""Projections: business-unit revenue, the amortisation schedule and
rate-deck interest, Base and Downside, chained year to year."""

from __future__ import annotations

from dataclasses import replace
from decimal import Decimal
from typing import Any

import pytest
from credit_model_fixture import (
    example_deck,
    example_growth,
    example_registers,
    example_request,
    example_slots,
)

from caos.calculators.cash_flow import cash_flow_forecast
from caos.calculators.credit_model._cells import CONTEXT
from caos.calculators.credit_model.frame import Column, Frame
from caos.calculators.credit_model.history import account_frame, historical_columns
from caos.calculators.credit_model.projection import (
    ProjectionInputs,
    RateDeck,
    RateDeckYear,
    facility_rate,
    projection,
    rate_for,
)
from caos.calculators.credit_model.statements import statement_frame
from caos.methodology.model_inputs import Cp1Registers, FacilityRow

# CP-CF opens at FY2025, the balances' column. Its stack,
# finance lease and discount aside, is 14,028.
_FIXED = {"ssn29": "0.065", "ssn31": "0.07", "sun29": "0.04625", "sun32": "0.06"}


def _history(regs: Cp1Registers) -> Frame:
    columns = historical_columns(regs)
    return statement_frame(account_frame(regs, columns), columns, regs)


def _inputs(
    regs: Cp1Registers | None = None,
    request: dict[str, Any] | None = None,
    deck: RateDeck | None = None,
    *,
    no_deck: bool = False,
) -> ProjectionInputs:
    regs = regs or example_registers()
    return ProjectionInputs(
        regs=regs,
        request=request or example_request(),
        growth=example_growth(),
        slots=example_slots(),
        deck=None if no_deck else deck or example_deck(),
        history=_history(regs),
    )


def _frame(inputs: ProjectionInputs) -> Frame:
    return projection(inputs)[1]


def _row(facility_id: str) -> FacilityRow:
    regs = example_registers()
    return next(r for r in regs.facilities if r.facility_id == facility_id)


def test_the_example_request_is_one_cash_flow_accepts() -> None:
    assert cash_flow_forecast(example_request())["status"] == "complete"


def test_columns_are_one_per_case_and_projected_year() -> None:
    columns, frame = projection(_inputs())

    assert [(c.column_id, c.label, c.case, c.kind) for c in columns] == [
        ("BASE:2026", "FY26E", "BASE", "PROJECTED"),
        ("BASE:2027", "FY27E", "BASE", "PROJECTED"),
        ("BASE:2028", "FY28E", "BASE", "PROJECTED"),
        ("DOWNSIDE:2026", "FY26E", "DOWNSIDE", "PROJECTED"),
        ("DOWNSIDE:2027", "FY27E", "DOWNSIDE", "PROJECTED"),
        ("DOWNSIDE:2028", "FY28E", "DOWNSIDE", "PROJECTED"),
    ]
    assert columns[0] == Column(
        column_id="BASE:2026",
        kind="PROJECTED",
        label="FY26E",
        period_id="FY2026",
        fiscal_year="2026",
        end_date="2026-12-31",
        days=365,
        case="BASE",
    )
    assert list(frame) == [c.column_id for c in columns]


def test_a_floating_facility_uses_deck_rate_floor_and_spread() -> None:
    deck = example_deck()
    low = RateDeck(
        "low",
        "2026-10-01",
        (RateDeckYear("SOFR", 1, Decimal("0.003"), Decimal("0.004")),),
    )

    assert facility_rate(_row("tlb"), deck, "BASE", 1, None) == (
        Decimal("0.0655"),
        None,
    )
    assert facility_rate(_row("tlb"), deck, "DOWNSIDE", 2, None) == (
        Decimal("0.0815"),
        None,
    )
    # Below the 50 bp floor the floor applies; the revolver has no floor.
    assert facility_rate(_row("tlb"), low, "BASE", 1, None) == (Decimal("0.0325"), None)
    assert facility_rate(_row("rcf"), low, "BASE", 1, None) == (Decimal("0.0255"), None)
    assert facility_rate(_row("rcf"), low, "DOWNSIDE", 1, None) == (
        Decimal("0.0265"),
        None,
    )
    # A fixed coupon is its percent as a decimal.
    for facility_id, rate in _FIXED.items():
        assert facility_rate(_row(facility_id), deck, "BASE", 1, None) == (
            Decimal(rate),
            None,
        )


def test_a_year_beyond_the_deck_holds_the_last_rate() -> None:
    deck = example_deck()

    assert rate_for(deck, "SOFR", "BASE", 3) == Decimal("0.0325")
    assert rate_for(deck, "SOFR", "BASE", 5) == Decimal("0.0325")
    assert rate_for(deck, "SOFR", "DOWNSIDE", 5) == Decimal("0.0525")
    assert rate_for(deck, "SOFR", "DOWNSIDE", 2) == Decimal("0.0540")
    assert rate_for(deck, "SOFR", "BASE", 0) is None
    assert rate_for(deck, "SONIA", "BASE", 1) is None
    assert rate_for(None, "SOFR", "BASE", 1) is None


def test_zero_and_fractional_terms_are_in_range_and_exact() -> None:
    deck = example_deck()
    rcf = _row("rcf")
    zero = replace(rcf, spread_bps=Decimal(0), floor_bps=Decimal(0))

    assert facility_rate(zero, deck, "BASE", 1, None) == (Decimal("0.0380"), None)
    half = replace(_row("ssn29"), fixed_rate=Decimal("0.5"))
    assert facility_rate(half, deck, "BASE", 1, None) == (Decimal("0.005"), None)
    # A coupon to 31 digits is divided at 38, never rounded to 28.
    coupon = Decimal("6.234567890123456789012345678901")
    fixed = replace(_row("ssn29"), fixed_rate=coupon)
    rate, _ = facility_rate(fixed, deck, "BASE", 1, None)
    assert rate == CONTEXT.divide(coupon, Decimal(100))


# Fix wave B (the adversary audit of b64facb7): H4, H5, H6, M1, M4, M5, L1-L4.

_WRONG_UNIT_IMPLIED = Decimal("0.061")


@pytest.mark.parametrize(
    ("facility_id", "terms"),
    [
        ("tlb", {"spread_bps": Decimal("2.25")}),  # "2.25%" read as 2.25 bp
        ("tlb", {"spread_bps": Decimal(2001)}),
        ("tlb", {"floor_bps": Decimal("0.5")}),  # "0.50%" read as 0.5 bp
        ("tlb", {"floor_bps": Decimal(1001)}),
        ("ssn29", {"fixed_rate": Decimal("0.065")}),  # a decimal, not a percent
        ("ssn29", {"fixed_rate": Decimal("0.49")}),
        ("ssn29", {"fixed_rate": Decimal("30.01")}),
    ],
)
def test_a_rate_term_in_the_wrong_unit_is_out_of_range(
    facility_id: str, terms: dict[str, Any]
) -> None:
    row = replace(_row(facility_id), **terms)
    rate = facility_rate(row, example_deck(), "BASE", 1, _WRONG_UNIT_IMPLIED)

    assert rate == (_WRONG_UNIT_IMPLIED, "term out of range")


def test_rate_term_bounds_are_inclusive() -> None:
    deck = example_deck()
    widest = replace(_row("tlb"), spread_bps=Decimal(2000), floor_bps=Decimal(1000))
    # The 10% floor is above the deck's 3.80%: 10% + 20%.
    assert facility_rate(widest, deck, "BASE", 1, None) == (Decimal("0.3"), None)
    whole = replace(_row("tlb"), spread_bps=Decimal("275.00"))
    assert facility_rate(whole, deck, "BASE", 1, None) == (Decimal("0.0655"), None)
    for coupon in ("0.5", "30"):
        row = replace(_row("ssn29"), fixed_rate=Decimal(coupon))
        expected = Decimal(coupon) / 100
        assert facility_rate(row, deck, "BASE", 1, None) == (expected, None)

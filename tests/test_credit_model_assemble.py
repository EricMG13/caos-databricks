"""The assembled credit model: columns in the spec's order, the worked
layout's bands and lines, its limitations, and every bridge closing."""

from __future__ import annotations

from dataclasses import replace
from decimal import Decimal

from credit_model_fixture import (
    example_registers,
)

from caos.calculators.credit_model.layout import (
    FacilityTerms,
    facility_terms,
)

_PF = "PF:LTM_Q2_2026"
_LTM = "LTM:LTM_Q2_2026"
_BASE = "BASE:2026"


def test_facility_terms_are_shown_as_stated_never_rounded() -> None:
    row = next(f for f in example_registers().facilities if f.facility_id == "tlb")
    odd = replace(
        row,
        reference_rate="TERM_SOFR",
        spread_bps=Decimal("262.5"),
        floor_bps=Decimal("12.5"),
        annual_amortisation=Decimal("0.0001"),
    )
    assert facility_terms(odd) == FacilityTerms(
        "Term SOFR", "+262.5 bp", "0.125%", "2030-02-28", "0.0001 p.a."
    )
    assert (
        facility_terms(replace(odd, reference_rate="LIBOR")).reference_rate == "LIBOR"
    )
    assert (
        facility_terms(replace(odd, spread_bps=None)).spread_or_coupon == "not stated"
    )
    assert facility_terms(replace(odd, rate_type="FIXED")).spread_or_coupon == (
        "not stated"
    )
    fixed = replace(odd, rate_type="FIXED", fixed_rate=Decimal("7.125"), floor_bps=None)
    assert (facility_terms(fixed).spread_or_coupon, facility_terms(fixed).floor) == (
        "7.125%",
        "n.a.",
    )
    assert (
        facility_terms(replace(odd, rate_type="NOT_STATED", floor_bps=None)).floor
        == "n.a."
    )
    assert (
        facility_terms(
            replace(odd, rate_type="FIXED", fixed_rate=Decimal("1E+1"))
        ).spread_or_coupon
        == "10%"
    )

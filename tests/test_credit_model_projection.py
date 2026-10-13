"""Projections: business-unit revenue, the amortisation schedule and
rate-deck interest, Base and Downside, chained year to year."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from decimal import Decimal, localcontext
from typing import Any

import pytest
from credit_model_fixture import (
    example_deck,
    example_growth,
    example_registers,
    example_request,
    example_slots,
)
from hypothesis import given, settings
from hypothesis import strategies as st

from caos.calculators.cash_flow import cash_flow_forecast
from caos.calculators.credit_model import projection as projection_module
from caos.calculators.credit_model._cells import CONTEXT, UNSPANNED
from caos.calculators.credit_model.assemble import ModelInputs, credit_model
from caos.calculators.credit_model.debt import COUPON_AS_FRACTION, HISTORY_INCOMPLETE
from caos.calculators.credit_model.frame import Cell, Column, Frame
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
from caos.methodology.model_inputs import (
    Cp1Registers,
    FacilityRow,
    SlotAllocation,
    coupon_percent,
)
from caos.refusals import Refusal, RefusalCode

# CP-CF opens at FY2025, the balances' column. Its stack,
# finance lease and discount aside, is 14,028.
_FIXED = {"ssn29": "0.065", "ssn31": "0.07", "sun29": "0.04625", "sun32": "0.06"}
_FIXED_INTEREST = Decimal("130") + 70 + Decimal("166.5") + 210 + 130  # + sub27
# LTM to Q2 2026: cash interest 862 over the average of total debt (finance
# lease included) at 30 June 2025 (14,130) and 30 June 2026 (14,106).
_IMPLIED = CONTEXT.divide(Decimal(862), (Decimal(14130) + Decimal(14106)) / 2)
# No implied rate (`facility_rate`'s fallback), as `_implied` gives it.
_NO_IMPLIED = Cell(None, "COMPONENT_MISSING")


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


def _terms(regs: Cp1Registers, facility_id: str, terms: dict[str, Any]) -> Cp1Registers:
    """`regs` with every row of the facility carrying `terms`."""
    return replace(
        regs,
        facilities=tuple(
            replace(row, **terms) if row.facility_id == facility_id else row
            for row in regs.facilities
        ),
    )


def _about(cell: Cell, expected: Decimal) -> bool:
    """`cell`'s figure is `expected` to 20 places: interest is the weighted
    rate, a 38-digit quotient, times the debt."""
    return cell.value is not None and abs(cell.value - expected) < Decimal("1e-20")


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


def test_interest_is_weighted_rate_times_opening_interest_bearing_debt() -> None:
    frame = _frame(_inputs())

    # FY2026 Base: SOFR 3.80%; the term loan 2,328 at 3.80% + 2.75%.
    first = frame["BASE:2026"]
    interest = Decimal(2328) * Decimal("0.0655") + _FIXED_INTEREST
    assert first["interest_bearing_debt_opening"].value == 14028
    assert first["interest_bearing_debt_opening"].basis == "CALCULATED"
    assert first["wa_rate"].value == CONTEXT.divide(interest, Decimal(14028))
    # The weights cancel: interest is exact, not the rounded rate times 14,028.
    assert first["cash_interest"].value == -interest
    assert first["reference_rate"].value == Decimal("0.0380")
    # FY2027's rate weights the amortised term loan, 2,304, at 3.40% + 2.75%;
    # its base is CP-CF's opening debt, after FY2026's 822 sweep, less the
    # finance lease (260) and the discount (-170).
    second = frame["BASE:2027"]
    weighted = Decimal(2304) * Decimal("0.0615") + _FIXED_INTEREST
    base = _value(second["debt_opening"]) - 260 + 170
    assert base == 14118 - 846 - 90
    assert second["interest_bearing_debt_opening"].value == base
    assert second["wa_rate"].value == CONTEXT.divide(weighted, Decimal(14004))
    assert second["cash_interest"].value == CONTEXT.minus(
        CONTEXT.divide(CONTEXT.multiply(weighted, base), Decimal(14004))
    )
    # Downside FY2026: SOFR 4.80%.
    interest = Decimal(2328) * Decimal("0.0755") + _FIXED_INTEREST
    assert _about(frame["DOWNSIDE:2026"]["cash_interest"], -interest)


def test_a_floating_facility_uses_deck_rate_floor_and_spread() -> None:
    deck = example_deck()
    low = RateDeck(
        "low",
        "2026-10-01",
        (RateDeckYear("SOFR", 1, Decimal("0.003"), Decimal("0.004")),),
    )

    assert facility_rate(_row("tlb"), deck, "BASE", 1, _NO_IMPLIED) == (
        Decimal("0.0655"),
        None,
    )
    assert facility_rate(_row("tlb"), deck, "DOWNSIDE", 2, _NO_IMPLIED) == (
        Decimal("0.0815"),
        None,
    )
    # Below the 50 bp floor the floor applies; the revolver has no floor.
    assert facility_rate(_row("tlb"), low, "BASE", 1, _NO_IMPLIED) == (
        Decimal("0.0325"),
        None,
    )
    assert facility_rate(_row("rcf"), low, "BASE", 1, _NO_IMPLIED) == (
        Decimal("0.0255"),
        None,
    )
    assert facility_rate(_row("rcf"), low, "DOWNSIDE", 1, _NO_IMPLIED) == (
        Decimal("0.0265"),
        None,
    )
    # A fixed coupon is its percent as a decimal.
    for facility_id, rate in _FIXED.items():
        assert facility_rate(_row(facility_id), deck, "BASE", 1, _NO_IMPLIED) == (
            Decimal(rate),
            None,
        )


def test_terms_not_stated_fall_back_to_the_implied_rate_with_a_note() -> None:
    deck = example_deck()
    implied = Decimal("0.061")
    tlb = _row("tlb")
    implied_terms: list[dict[str, Any]] = [
        {"rate_type": "NOT_STATED"},
        {"reference_rate": "NOT_STATED"},
        {"reference_rate": "NONE"},
        {"spread_bps": None},
    ]
    for terms in implied_terms:
        assert facility_rate(replace(tlb, **terms), deck, "BASE", 1, Cell(implied)) == (
            implied,
            "implied rate",
        )
    assert facility_rate(
        replace(_row("ssn29"), fixed_rate=None), deck, "BASE", 1, Cell(implied)
    ) == (
        implied,
        "implied rate",
    )
    out_of_range: list[tuple[FacilityRow, dict[str, Any]]] = [
        (tlb, {"rate_type": "SWAP"}),
        (tlb, {"reference_rate": "LIBOR"}),
        (tlb, {"spread_bps": Decimal(-1)}),
        (tlb, {"floor_bps": Decimal(-1)}),
        (_row("ssn29"), {"fixed_rate": Decimal("-0.5")}),
    ]
    for row, terms in out_of_range:
        assert facility_rate(replace(row, **terms), deck, "BASE", 1, Cell(implied)) == (
            implied,
            "term out of range",
        )
    # With no implied rate there is no rate, the note kept.
    assert facility_rate(
        replace(tlb, rate_type="NOT_STATED"), deck, "BASE", 1, _NO_IMPLIED
    ) == (
        None,
        "implied rate",
    )

    regs = _terms(example_registers(), "tlb", {"rate_type": "NOT_STATED"})
    first = _frame(_inputs(regs))["BASE:2026"]
    interest = CONTEXT.multiply(Decimal(2328), _IMPLIED) + _FIXED_INTEREST
    assert _about(first["cash_interest"], -interest)
    assert first["fac:tlb"].note == "implied rate"


def test_an_out_of_range_amortisation_is_not_stated_and_noted() -> None:
    regs = _terms(example_registers(), "tlb", {"annual_amortisation": Decimal(-24)})
    frame = _frame(_inputs(regs))

    assert frame["BASE:2026"]["fac:tlb"] == Cell(
        Decimal(2328), basis="PROJECTED", note="term out of range"
    )
    unstated = _terms(example_registers(), "tlb", {"annual_amortisation": None})
    frame = _frame(_inputs(unstated))
    assert frame["BASE:2026"]["fac:tlb"] == Cell(
        Decimal(2328), basis="PROJECTED", note="amortisation not stated"
    )
    assert frame["BASE:2026"]["debt_raised_net"].value == -822


def test_no_rate_deck_uses_the_implied_rate_for_floating_facilities() -> None:
    assert facility_rate(_row("rcf"), None, "BASE", 1, Cell(Decimal("0.06"))) == (
        Decimal("0.06"),
        "no rate deck",
    )
    # A fixed coupon needs no deck.
    assert facility_rate(_row("ssn29"), None, "BASE", 1, Cell(Decimal("0.06"))) == (
        Decimal("0.065"),
        None,
    )

    first = _frame(_inputs(no_deck=True))["BASE:2026"]
    interest = CONTEXT.multiply(Decimal(2328), _IMPLIED) + _FIXED_INTEREST
    assert _about(first["cash_interest"], -interest)
    assert first["fac:tlb"].note == "no rate deck"
    assert first["fac:rcf"].note == "no rate deck"
    assert first["reference_rate"] == Cell(None, "NOT_SOURCED", note="no rate deck")


def test_a_year_beyond_the_deck_holds_the_last_rate() -> None:
    deck = example_deck()

    assert rate_for(deck, "SOFR", "BASE", 3) == Decimal("0.0325")
    assert rate_for(deck, "SOFR", "BASE", 5) == Decimal("0.0325")
    assert rate_for(deck, "SOFR", "DOWNSIDE", 5) == Decimal("0.0525")
    assert rate_for(deck, "SOFR", "DOWNSIDE", 2) == Decimal("0.0540")
    assert rate_for(deck, "SOFR", "BASE", 0) is None
    assert rate_for(deck, "SONIA", "BASE", 1) is None
    assert rate_for(None, "SOFR", "BASE", 1) is None

    one_year = replace(deck, years=deck.years[:1])
    frame = _frame(_inputs(deck=one_year))
    assert frame["BASE:2026"]["reference_rate"] == Cell(
        Decimal("0.0380"), basis="DRIVER"
    )
    assert frame["BASE:2027"]["reference_rate"] == Cell(
        Decimal("0.0380"), basis="DRIVER", note="last deck rate held flat"
    )
    weighted = Decimal(2304) * Decimal("0.0655") + _FIXED_INTEREST
    base = _value(frame["BASE:2027"]["interest_bearing_debt_opening"])
    expected = -CONTEXT.multiply(CONTEXT.divide(weighted, Decimal(14004)), base)
    assert _about(frame["BASE:2027"]["cash_interest"], expected)


def test_amortisation_stops_at_zero_balance() -> None:
    regs = example_registers()
    regs = replace(
        regs,
        facilities=tuple(
            replace(row, carrying_value=Decimal(30))
            if row.facility_id == "tlb" and row.period_id in {"Q4_2025", "FY2025"}
            else row
            for row in regs.facilities
        ),
    )
    frame = _frame(_inputs(regs))

    assert [frame[f"BASE:{y}"]["fac:tlb"].value for y in (2026, 2027, 2028)] == [
        6,
        0,
        0,
    ]
    assert [
        frame[f"BASE:{y}"]["debt_raised_net"].value for y in (2026, 2027, 2028)
    ] == [-822 - 24, -1097 - 6, -337]
    assert _value(frame["BASE:2026"]["debt_closing"]) == (
        _value(frame["BASE:2026"]["debt_opening"]) - 846
    )


def test_a_maturity_in_the_horizon_is_assumed_refinanced() -> None:
    frame = _frame(_inputs())

    # The 8.125% notes mature 1 July 2027, in FY2027.
    assert frame["BASE:2027"]["fac:sub27"] == Cell(
        Decimal(1600), basis="PROJECTED", note="assumed refinanced"
    )
    assert frame["BASE:2026"]["fac:sub27"].note is None
    assert frame["BASE:2028"]["fac:sub27"].value == 1600
    assert frame["DOWNSIDE:2027"]["fac:sub27"].note == "assumed refinanced"
    # The finance lease and the discount are held flat; the lease is no
    # interest-bearing debt.
    assert frame["BASE:2028"]["fac:finl"] == Cell(
        Decimal(260), basis="PROJECTED", note="held flat"
    )
    assert frame["BASE:2028"]["fac:disc"].value == -170


def test_bu_revenue_compounds_the_slot_growth_and_sums_to_revenue() -> None:
    frame = _frame(_inputs())

    las_vegas = Decimal(4213) * Decimal("1.025")
    assert frame["BASE:2026"]["bu:las_vegas"] == Cell(las_vegas, basis="PROJECTED")
    las_vegas *= Decimal("1.030")
    assert frame["BASE:2027"]["bu:las_vegas"].value == las_vegas
    downside = Decimal(5746) * Decimal("0.96") * Decimal("0.98") * Decimal("1.01")
    assert frame["DOWNSIDE:2028"]["bu:regional"].value == downside
    # In no slot, or corporate: held flat.
    assert frame["BASE:2028"]["bu:managed_other"] == Cell(
        Decimal(343), basis="PROJECTED", note="held flat"
    )
    assert frame["BASE:2028"]["bu:corporate_eliminations"].value == -60
    revenue = (
        Decimal(4213) * Decimal("1.025")
        + Decimal(5746) * Decimal("1.010")
        + Decimal(1277) * Decimal("1.10")
        + 343
        - 60
    )
    # Revenue is CP-CF's own (H5); the units sum to it within its rounding.
    assert revenue == Decimal("11809.485")
    assert frame["BASE:2026"]["revenue"] == Cell(Decimal(11809), basis="DRIVER")

    request = example_request()
    request["drivers"][0]["revenue"] = "12000"
    frame = _frame(_inputs(request=request))
    assert frame["BASE:2026"]["revenue"] == Cell(Decimal(12000), basis="DRIVER")


def test_drivers_sign_into_the_frame_and_the_cash_flow_follows() -> None:
    first = _frame(_inputs())["BASE:2026"]
    interest = Decimal(2328) * Decimal("0.0655") + _FIXED_INTEREST

    assert first["adjusted_ebitda"].value == 4136
    assert first["capex"].value == -1700
    assert first["cash_taxes"].value == -170
    assert first["other_operating"] == Cell(
        Decimal(4025 - 4136), basis="CALCULATED", note="includes working capital"
    )
    assert _about(first["cfo_adjusted"], 4025 - interest - 170)
    assert _about(first["fcf"], 4025 - interest - 170 - 1700)
    assert first["dividends"].value == -400
    assert first["acquisitions_net"].value == 0
    assert first["equity_raised_net"].value == 0
    assert first["debt_raised_net"].value == -822 - 24
    ncf = 4025 - interest - 170 - 1700 - 846 - 400
    assert _about(first["ncf"], ncf)
    # Cash and debt open at CP-CF's opening, FY2025.
    assert first["cash_opening"].value == 980
    assert _about(first["cash_closing"], 980 + ncf)
    assert first["debt_opening"].value == 13858 + 260
    assert first["total_debt"].value == 13858 + 260 - 846
    for key in ("lease_cash_not_in_ebitda", "ffo", "working_capital_change", "dso"):
        assert first[key] == Cell(None, "NOT_PROJECTED")
    assert first["kpi:lv_occupancy"] == Cell(None, "NOT_PROJECTED")
    assert first["lease_liabilities"] == Cell(None, "NOT_PROJECTED")


def test_an_acquisition_is_a_cash_outflow() -> None:
    request = example_request()
    request["drivers"][0]["acquisitions_disposals"] = "250"
    first = _frame(_inputs(request=request))["BASE:2026"]

    assert first["acquisitions_net"].value == -250


def test_a_driver_missing_or_not_ready_leaves_its_lines_without_a_figure() -> None:
    request = example_request()
    del request["drivers"][0]["capex"]
    request["drivers"][3]["status"] = "NOT_READY"
    frame = _frame(_inputs(request=request))

    assert frame["BASE:2026"]["capex"] == Cell(None, "NOT_SOURCED")
    assert frame["BASE:2026"]["fcf"] == Cell(None, "COMPONENT_MISSING")
    assert frame["BASE:2027"]["cash_opening"] == Cell(None, "COMPONENT_MISSING")
    assert frame["DOWNSIDE:2026"]["adjusted_ebitda"] == Cell(
        None, "NOT_STATED", note="driver not ready"
    )


def test_a_foreign_currency_facility_bears_no_interest_here() -> None:
    regs = _terms(example_registers(), "ssn29", {"currency": "EUR"})
    first = _frame(_inputs(regs))["BASE:2026"]

    assert first["interest_bearing_debt_opening"].value == 14028 - 2000
    assert first["fac:ssn29"].note == "different currency, not converted"


def test_a_case_or_period_the_model_does_not_read_is_skipped() -> None:
    request = example_request()
    upside = {"case": "UPSIDE", "period_id": "FY2026", "fiscal_year": "2026"}
    request["periods"].insert(0, upside | {"days": "365"})
    columns, _ = projection(_inputs(request=request))

    assert all(column.case in {"BASE", "DOWNSIDE"} for column in columns)
    assert len(columns) == 6
    request["periods"] = request["periods"][:1]
    assert projection(_inputs(request=request)) == ((), {})


def _value(cell: Cell) -> Decimal:
    assert cell.value is not None, cell
    return cell.value


_AMOUNT = st.integers(min_value=0, max_value=10**6).map(Decimal)
_SIGNED = st.integers(min_value=-(10**6), max_value=10**6).map(Decimal)


@settings(max_examples=40, deadline=None)
@given(
    st.lists(
        st.tuples(*([_AMOUNT] * 11), _SIGNED),
        min_size=6,
        max_size=6,
    )
)
def test_projected_cash_and_debt_roll_forward_for_any_drivers(
    figures: list[tuple[Decimal, ...]],
) -> None:
    request = example_request()
    names = (
        "ebitda",
        "cfo",
        "capex",
        "cash_taxes",
        "distributions",
        "issuance",
        "optional_repayment",
        "acquisitions_disposals",
        "revenue",
        "pik",
        "capitalised_interest",
        "fx_perimeter",
    )
    for driver, values in zip(request["drivers"], figures, strict=True):
        driver.update(
            {name: str(value) for name, value in zip(names, values, strict=True)}
        )
    columns, frame = projection(_inputs(request=request))

    for column, values in zip(columns, figures, strict=True):
        assert _value(frame[column.column_id]["debt_non_cash"]) == sum(values[9:])
    with localcontext(CONTEXT):
        _rolls_forward(columns, frame)


def _closes(total: Cell, parts: list[Cell]) -> None:
    """`total` is the sum of `parts`, or has no figure when one of them has
    none: the identity holds on every example."""
    if any(part.value is None for part in parts):
        assert total.value is None, total
    else:
        assert total.value == sum(_value(part) for part in parts)


def _unit(value: Decimal) -> Decimal:
    """A unit in the 38th significant digit of `value`."""
    return Decimal(1).scaleb(value.adjusted() - 37)


def _rolls_forward(columns: tuple[Column, ...], frame: Frame) -> None:
    flows = ("fcf", "acquisitions_net", "debt_raised_net", "equity_raised_net")
    for case in ("BASE", "DOWNSIDE"):
        prior: dict[str, Cell] | None = None
        for column in (c for c in columns if c.case == case):
            cells = frame[column.column_id]
            _closes(cells["cash_closing"], [cells["cash_opening"], cells["ncf"]])
            _closes(cells["ncf"], [cells[key] for key in (*flows, "dividends")])
            debt = ("debt_opening", "debt_raised_net", "debt_non_cash")
            _closes(cells["debt_closing"], [cells[key] for key in debt])
            assert cells["debt_closing"].value is not None
            assert cells["total_debt"] == cells["debt_closing"]
            base = _value(cells["interest_bearing_debt_opening"])
            if base > 0:
                # To the weighted rate's 38 digits: interest is computed from
                # the weights, never through the rounded rate.
                rate, interest = (
                    _value(cells["wa_rate"]),
                    _value(cells["cash_interest"]),
                )
                gap = abs(interest + rate * base)
                rounding = abs(interest).scaleb(-37)
                assert gap <= base * _unit(rate) + rounding + _unit(interest)
            if prior is not None:
                assert cells["cash_opening"] == prior["cash_closing"]
                assert cells["debt_opening"].value == prior["debt_closing"].value
            prior = cells


def _at_anchor(
    regs: Cp1Registers, balances: Mapping[str, Decimal | None]
) -> Cp1Registers:
    """`regs` with the facilities' carrying values at 31 December 2025 (Q4 and
    FY2025) in `balances`."""
    return replace(
        regs,
        facilities=tuple(
            replace(row, carrying_value=balances[row.facility_id])
            if row.period_id in {"Q4_2025", "FY2025"} and row.facility_id in balances
            else row
            for row in regs.facilities
        ),
    )


_INTEREST_BEARING = ("rcf", "tlb", "ssn29", "ssn31", "sun29", "sun32", "sub27")


def test_a_malformed_cp_cf_figure_or_period_is_refused() -> None:
    bad_figure = example_request()
    bad_figure["drivers"][0]["capex"] = "1,700"
    bad_days = example_request()
    bad_days["periods"][0]["days"] = "365.0"
    bad_year = example_request()
    bad_year["periods"][0]["fiscal_year"] = "FY"

    for request in (bad_figure, bad_days, bad_year):
        with pytest.raises(Refusal) as caught:
            projection(_inputs(request=request))
        assert caught.value.code == RefusalCode.METHODOLOGY_INPUT_INVALID


def test_a_maturity_that_is_no_iso_date_is_not_placed() -> None:
    for maturity in ("Jul 2027", None):
        regs = _terms(example_registers(), "sub27", {"maturity_date": maturity})
        frame = _frame(_inputs(regs))
        assert frame["BASE:2027"]["fac:sub27"].note is None


def test_a_missing_balance_leaves_no_interest() -> None:
    regs = _at_anchor(example_registers(), {"tlb": None, "sub27": None})
    frame = _frame(_inputs(regs))
    first = frame["BASE:2026"]

    assert first["fac:tlb"] == Cell(None, "COMPONENT_MISSING")
    assert frame["BASE:2027"]["fac:sub27"] == Cell(
        None, "COMPONENT_MISSING", note="assumed refinanced"
    )
    for key in ("interest_bearing_debt_opening", "wa_rate", "cash_interest"):
        assert first[key] == Cell(None, "COMPONENT_MISSING")
    assert first["debt_raised_net"] == Cell(None, "COMPONENT_MISSING")


def _ltm(inputs: ProjectionInputs, key: str, cell: Cell) -> ProjectionInputs:
    """`inputs` with the LTM's `key` cell replaced."""
    history = {column_id: dict(cells) for column_id, cells in inputs.history.items()}
    history["LTM:LTM_Q2_2026"][key] = cell
    return replace(inputs, history=history)


def _at_opening(inputs: ProjectionInputs, key: str, cell: Cell) -> ProjectionInputs:
    """`inputs` with CP-CF's opening column's (FY2025) `key` cell replaced."""
    history = {column_id: dict(cells) for column_id, cells in inputs.history.items()}
    history["FY:FY2025"][key] = cell
    return replace(inputs, history=history)


def test_a_drawn_facility_without_a_rate_leaves_no_interest() -> None:
    regs = _terms(example_registers(), "tlb", {"rate_type": "NOT_STATED"})
    no_interest = Cell(None, "NOT_STATED")
    first = _frame(_ltm(_inputs(regs), "cash_interest", no_interest))["BASE:2026"]

    assert first["interest_bearing_debt_opening"].value == 14028
    assert first["wa_rate"] == Cell(None, "COMPONENT_MISSING")
    assert first["cash_interest"] == Cell(None, "COMPONENT_MISSING")
    # An undrawn facility needs no rate.
    undrawn = _inputs(_at_anchor(regs, {"tlb": Decimal(0)}))
    first = _frame(_ltm(undrawn, "cash_interest", no_interest))["BASE:2026"]
    assert first["wa_rate"].value == CONTEXT.divide(_FIXED_INTEREST, Decimal(11700))


def test_no_average_debt_gives_no_implied_rate() -> None:
    regs = _terms(example_registers(), "tlb", {"rate_type": "NOT_STATED"})
    negative = Cell(Decimal(-14106), basis="CALCULATED")
    first = _frame(_ltm(_inputs(regs), "debt_opening", negative))["BASE:2026"]

    assert first["wa_rate"] == Cell(None, "ZERO_OR_NEGATIVE_DENOMINATOR")
    assert first["cash_interest"] == Cell(None, "ZERO_OR_NEGATIVE_DENOMINATOR")


def test_no_interest_bearing_debt_bears_no_interest() -> None:
    zero = dict.fromkeys(_INTEREST_BEARING, Decimal(0))
    first = _frame(_inputs(_at_anchor(example_registers(), zero)))["BASE:2026"]

    assert first["interest_bearing_debt_opening"].value == 0
    assert first["wa_rate"] == Cell(None, "ZERO_OR_NEGATIVE_DENOMINATOR")
    assert first["cash_interest"] == Cell(Decimal(0), basis="CALCULATED")

    negative = zero | {"tlb": Decimal(-10)}
    first = _frame(_inputs(_at_anchor(example_registers(), negative)))["BASE:2026"]
    assert first["cash_interest"] == Cell(
        None, "COMPONENT_MISSING", note="negative interest base"
    )


def test_an_operating_lease_is_not_projected() -> None:
    regs = _terms(
        example_registers(), "finl", {"lease_classification": "OPERATING_LEASE"}
    )
    first = _frame(_inputs(regs))["BASE:2026"]

    assert first["fac:finl"] == Cell(None, "NOT_PROJECTED")
    assert first["interest_bearing_debt_opening"].value == 14028


def test_with_no_floating_facility_the_reference_rate_does_not_apply() -> None:
    regs = example_registers()
    for facility_id in ("rcf", "tlb"):
        fixed = {
            "rate_type": "FIXED",
            "reference_rate": "NONE",
            "fixed_rate": Decimal(7),
        }
        regs = _terms(regs, facility_id, fixed)
    first = _frame(_inputs(regs))["BASE:2026"]

    assert first["reference_rate"] == Cell(None, "NOT_APPLICABLE")
    assert first["fac:tlb"].note is None


def test_a_segment_without_a_prior_or_a_growth_has_no_revenue() -> None:
    regs = example_registers()
    regs = replace(
        regs,
        segments=tuple(
            replace(row, revenue=None)
            if row.segment_id == "digital" and row.period_id == "FY2025"
            else row
            for row in regs.segments
        ),
    )
    first = _frame(_inputs(regs))["BASE:2026"]
    assert first["bu:digital"] == Cell(None, "COMPONENT_MISSING")
    # Revenue is CP-CF's; the business units' sum only without it.
    assert first["revenue"] == Cell(Decimal(11809), basis="DRIVER")
    request = example_request()
    for driver in request["drivers"]:
        del driver["revenue"]
    first = _frame(_inputs(regs, request))["BASE:2026"]
    assert first["revenue"] == Cell(None, "COMPONENT_MISSING")

    inputs = _inputs()
    growth = tuple(
        g
        for g in inputs.growth
        if not (g.slot_id == "DIVISION_3" and g.fiscal_year == "2027")
    )
    frame = _frame(replace(inputs, growth=growth))
    assert frame["BASE:2027"]["bu:digital"] == Cell(None, "NOT_SOURCED")
    assert frame["BASE:2026"]["bu:digital"].value == Decimal(1277) * Decimal("1.10")


def test_a_segment_the_last_fy_does_not_report_is_not_projected() -> None:
    regs = example_registers()
    legacy = replace(regs.segments[0], segment_id="legacy", period_id="FY2023")
    frame = _frame(_inputs(replace(regs, segments=(*regs.segments, legacy))))

    assert "bu:legacy" not in frame["BASE:2026"]


def test_with_no_segments_revenue_is_cp_cf_revenue() -> None:
    first = _frame(_inputs(replace(example_registers(), segments=())))["BASE:2026"]

    assert first["revenue"] == Cell(Decimal(11809), basis="DRIVER")
    assert not any(key.startswith("bu:") for key in first)


def test_zero_and_fractional_terms_are_in_range_and_exact() -> None:
    deck = example_deck()
    rcf = _row("rcf")
    zero = replace(rcf, spread_bps=Decimal(0), floor_bps=Decimal(0))

    assert facility_rate(zero, deck, "BASE", 1, _NO_IMPLIED) == (
        Decimal("0.0380"),
        None,
    )
    half = replace(_row("ssn29"), fixed_rate=Decimal("0.5"))
    assert facility_rate(half, deck, "BASE", 1, _NO_IMPLIED) == (Decimal("0.005"), None)
    # A coupon to 31 digits is divided at 38, never rounded to 28.
    coupon = Decimal("6.234567890123456789012345678901")
    fixed = replace(_row("ssn29"), fixed_rate=coupon)
    rate, _ = facility_rate(fixed, deck, "BASE", 1, _NO_IMPLIED)
    assert rate == CONTEXT.divide(coupon, Decimal(100))


def test_a_maturity_on_a_year_end_falls_in_the_year_it_ends() -> None:
    regs = _terms(example_registers(), "sub27", {"maturity_date": "2026-12-31"})
    frame = _frame(_inputs(regs))

    assert frame["BASE:2026"]["fac:sub27"].note == "assumed refinanced"
    assert frame["BASE:2027"]["fac:sub27"].note is None


def test_a_facility_with_two_notes_carries_both() -> None:
    regs = _terms(
        example_registers(),
        "tlb",
        {"rate_type": "NOT_STATED", "annual_amortisation": None},
    )
    first = _frame(_inputs(regs))["BASE:2026"]

    assert first["fac:tlb"].note == "implied rate; amortisation not stated"


def test_the_reference_rate_is_the_first_floating_facilitys() -> None:
    fixed = {
        "rate_type": "FIXED",
        "reference_rate": "TERM_SOFR",
        "fixed_rate": Decimal(6),
    }
    regs = _terms(example_registers(), "rcf", fixed)
    first = _frame(_inputs(regs))["BASE:2026"]
    assert first["reference_rate"] == Cell(Decimal("0.0380"), basis="DRIVER")

    sonia = RateDeck(
        "sonia",
        "2026-10-01",
        (RateDeckYear("SONIA", 1, Decimal("0.04"), Decimal("0.05")),),
    )
    first = _frame(_inputs(deck=sonia))["BASE:2026"]
    assert first["reference_rate"] == Cell(
        None, "NOT_SOURCED", note="reference rate not in deck"
    )
    assert first["fac:tlb"].note == "reference rate not in deck"


def test_interest_on_a_fraction_of_a_unit_of_debt_is_weighted() -> None:
    debt = dict.fromkeys(_INTEREST_BEARING, Decimal(0)) | {"tlb": Decimal("0.5")}
    first = _frame(_inputs(_at_anchor(example_registers(), debt)))["BASE:2026"]

    assert first["wa_rate"] == Cell(Decimal("0.0655"), basis="CALCULATED")
    assert first["cash_interest"] == Cell(Decimal("-0.03275"), basis="CALCULATED")

    none = _frame(_inputs(replace(example_registers(), facilities=())))["BASE:2026"]
    # With no debt register there is no total debt to take a base from.
    assert none["interest_bearing_debt_opening"] == Cell(None, "COMPONENT_MISSING")
    assert none["cash_interest"] == Cell(None, "COMPONENT_MISSING")


def test_issuance_raises_debt_and_equity_is_no_cp_cf_movement() -> None:
    request = example_request()
    request["drivers"][0]["issuance"] = "100"
    first = _frame(_inputs(request=request))["BASE:2026"]

    assert first["debt_raised_net"] == Cell(Decimal(100 - 822 - 24), basis="CALCULATED")
    assert first["equity_raised_net"] == Cell(
        Decimal(0), basis="CALCULATED", note="not a CP-CF movement"
    )


def test_cash_and_debt_open_at_the_anchor_with_its_sources() -> None:
    regs = example_registers()
    ltm = _history(regs)["FY:FY2025"]
    first = _frame(_inputs(regs))["BASE:2026"]

    assert first["cash_opening"] == Cell(
        Decimal(980), basis="CALCULATED", sources=ltm["cash_closing"].sources
    )
    assert first["debt_opening"] == Cell(
        Decimal(14118), basis="CALCULATED", sources=ltm["total_debt"].sources
    )
    assert ltm["total_debt"].sources

    first = _frame(_at_opening(_inputs(), "cash_closing", Cell(None, "NOT_STATED")))[
        "BASE:2026"
    ]
    assert first["cash_opening"] == Cell(None, "COMPONENT_MISSING")


def _without(inputs: ProjectionInputs, column_id: str, key: str) -> ProjectionInputs:
    """`inputs` with the history column's `key` cell gone."""
    history = {column: dict(cells) for column, cells in inputs.history.items()}
    del history[column_id][key]
    return replace(inputs, history=history)


def test_an_absent_history_cell_is_no_figure() -> None:
    regs = _terms(example_registers(), "tlb", {"rate_type": "NOT_STATED"})
    for key in ("cash_interest", "debt_opening", "total_debt"):
        first = _frame(_without(_inputs(regs), "LTM:LTM_Q2_2026", key))["BASE:2026"]
        assert first["cash_interest"] == Cell(None, "COMPONENT_MISSING")
    first = _frame(_without(_inputs(), "FY:FY2025", "cash_closing"))["BASE:2026"]
    assert first["cash_opening"] == Cell(None, "COMPONENT_MISSING")
    first = _frame(_without(_inputs(), "FY:FY2025", "total_debt"))["BASE:2026"]
    assert first["debt_opening"] == Cell(None, "COMPONENT_MISSING")
    first = _frame(_without(_inputs(), "FY:FY2025", "bu:digital"))["BASE:2026"]
    assert "bu:digital" not in first

    bare = _frame(replace(_inputs(), history={}))["BASE:2026"]
    assert bare["cash_opening"] == Cell(None, "COMPONENT_MISSING")
    assert bare["revenue"] == Cell(Decimal(11809), basis="DRIVER")
    assert not any(key.startswith("fac:") for key in bare)


def test_an_average_debt_below_one_still_implies_a_rate() -> None:
    regs = _terms(example_registers(), "tlb", {"rate_type": "NOT_STATED"})
    low = Cell(Decimal("-14105.5"), basis="CALCULATED")
    first = _frame(_ltm(_inputs(regs), "debt_opening", low))["BASE:2026"]

    assert _about(first["cash_interest"], -(2328 * Decimal(3448) + _FIXED_INTEREST))


def test_terms_are_read_at_the_anchor() -> None:
    regs = example_registers()
    regs = replace(
        regs,
        facilities=tuple(
            replace(row, spread_bps=Decimal(300))
            if row.facility_id == "tlb" and row.period_id == "FY2025"
            else row
            for row in regs.facilities
        ),
    )
    first = _frame(_inputs(regs))["BASE:2026"]

    assert _about(first["cash_interest"], -(2328 * Decimal("0.068") + _FIXED_INTEREST))


def _drop_year(request: dict[str, Any], year: str) -> dict[str, Any]:
    """`request` without the periods, drivers and amortisation of `year`."""
    period_id = f"FY{year}"
    return request | {
        "periods": [p for p in request["periods"] if p["period_id"] != period_id],
        "drivers": [d for d in request["drivers"] if d["period_id"] != period_id],
    }


def test_the_deck_offset_counts_from_the_last_historical_fy() -> None:
    first = _frame(_inputs(request=_drop_year(example_request(), "2026")))

    assert first["BASE:2027"]["reference_rate"].value == Decimal("0.0340")


def test_without_a_historical_fy_the_year_before_the_first_is_the_base() -> None:
    regs = example_registers()
    fiscal = {"FY2023", "FY2024", "FY2025"}
    regs = replace(
        regs,
        periods=tuple(p for p in regs.periods if p.period_id not in fiscal),
        accounts=tuple(a for a in regs.accounts if a.period_id not in fiscal),
        segments=tuple(g for g in regs.segments if g.period_id not in fiscal),
        addbacks=tuple(b for b in regs.addbacks if b.period_id not in fiscal),
        kpis=tuple(k for k in regs.kpis if k.period_id not in fiscal),
        facilities=tuple(f for f in regs.facilities if f.period_id not in fiscal),
    )
    request = _drop_year(example_request(), "2026")
    columns, frame = projection(_inputs(regs, request))

    assert columns[0].end_date == "2027-12-31"
    assert frame["BASE:2027"]["reference_rate"].value == Decimal("0.0380")
    interest = 2316 * Decimal("0.0655") + _FIXED_INTEREST
    assert _about(frame["BASE:2027"]["cash_interest"], -interest)


def test_a_fiscal_year_ending_in_september_projects_to_september() -> None:
    regs = example_registers()
    regs = replace(
        regs,
        periods=tuple(
            replace(p, start_date="2024-10-01", end_date="2025-09-30")
            if p.period_id == "FY2025"
            else p
            for p in regs.periods
        ),
    )
    columns, _ = projection(_inputs(regs))

    assert columns[0].end_date == "2026-09-30"


def test_corporate_and_eliminations_are_held_flat_even_in_a_slot() -> None:
    inputs = _inputs()
    slots = (SlotAllocation("DIVISION_1", ("las_vegas", "corporate_eliminations")),)
    first = _frame(replace(inputs, slots=slots))["BASE:2026"]

    assert first["bu:corporate_eliminations"] == Cell(
        Decimal(-60), basis="PROJECTED", note="held flat"
    )


def test_with_no_history_nothing_opens() -> None:
    regs = replace(example_registers(), periods=(), facilities=())
    columns, frame = projection(_inputs(regs))
    first = frame["BASE:2026"]

    assert columns[0].end_date == "2026-12-31"
    assert first["cash_opening"] == Cell(None, "COMPONENT_MISSING")
    assert first["debt_opening"] == Cell(None, "COMPONENT_MISSING")
    assert first["revenue"] == Cell(Decimal(11809), basis="DRIVER")


def _opening_at(as_of: str) -> dict[str, Any]:
    request = example_request()
    request["opening"]["as_of_period_id"] = as_of
    return request


def test_the_projection_opens_at_cp_cf_s_opening_period() -> None:
    # CP-CF opens at FY2025: the term loan's 2,328 then, not Q2 2026's 2,316.
    first = _frame(_inputs())["BASE:2026"]

    assert first["fac:tlb"].value == 2328 - 24
    assert first["interest_bearing_debt_opening"].value == 14028
    assert first["cash_opening"].value == 980
    assert first["debt_opening"].value == 13858 + 260
    # A quarter CP-CF names is used; a period no column has falls back to
    # the latest FY end.
    quarter = _frame(_inputs(request=_opening_at("Q2_2026")))["BASE:2026"]
    assert quarter["fac:tlb"].value == 2316 - 24
    assert quarter["cash_opening"].value == 1000
    unknown = _frame(_inputs(request=_opening_at("FY2099")))["BASE:2026"]
    assert unknown["fac:tlb"].value == 2328 - 24


def test_debt_rolls_forward_with_cp_cf_non_cash_movements() -> None:
    request = example_request()
    request["drivers"][0].update(
        {"pik": "10", "capitalised_interest": "5", "fx_perimeter": "-3"}
    )
    del request["drivers"][1]["pik"]
    frame = _frame(_inputs(request=request))
    first = frame["BASE:2026"]

    assert first["debt_non_cash"] == Cell(Decimal(12), basis="CALCULATED")
    assert first["debt_raised_net"].value == -822 - 24
    assert first["debt_closing"].value == 13858 + 260 - 846 + 12
    assert first["total_debt"] == first["debt_closing"]
    # An absent movement is none.
    assert frame["BASE:2027"]["debt_non_cash"].value == 0


def test_projected_columns_carry_the_debt_totals_and_liquidity() -> None:
    first = _frame(_inputs())["BASE:2026"]
    cash = _value(first["cash_closing"])

    # Super senior and senior secured: the revolver, the term loan, the
    # 6.500% and 7.000% notes.
    assert first["secured_debt"].value == 0 + 2304 + 2000 + 1000
    assert first["net_debt"].value == _value(first["total_debt"]) - cash
    assert first["undrawn_rcf"].value == 2200
    assert first["undrawn_rcf"].note == "RCF drawing held at opening"
    assert first["liquidity"].value == cash + 2200
    assert first["ebitda"] == Cell(None, "NOT_PROJECTED")

    # CP-1's accounts at the opening come first.
    inputs = _at_opening(_inputs(), "acct:rcf_commitment", Cell(Decimal(2600)))
    inputs = _at_opening(inputs, "acct:rcf_drawn", Cell(Decimal(300)))
    assert _frame(inputs)["BASE:2027"]["undrawn_rcf"].value == 2300


def test_without_rcf_accounts_the_revolver_row_gives_undrawn() -> None:
    regs = example_registers()
    rcf = next(
        r for r in regs.facilities if r.facility_id == "rcf" and r.period_id == "FY2025"
    )
    assert rcf.source is not None
    inputs = _without(_inputs(), "FY:FY2025", "acct:rcf_commitment")
    first = _frame(inputs)["BASE:2026"]
    assert first["undrawn_rcf"] == Cell(
        Decimal(2200),
        basis="CALCULATED",
        sources=(rcf.source,),
        note="RCF drawing held at opening",
    )

    named = _terms(regs, "rcf", {"facility_type": "RCF", "drawn_amount": Decimal(50)})
    inputs = _without(_inputs(named), "FY:FY2025", "acct:rcf_drawn")
    assert _frame(inputs)["BASE:2026"]["undrawn_rcf"].value == 2150

    unstated = _terms(regs, "rcf", {"commitment": None})
    inputs = _without(_inputs(unstated), "FY:FY2025", "acct:rcf_drawn")
    first = _frame(inputs)["BASE:2026"]
    assert first["undrawn_rcf"] == Cell(None, "COMPONENT_MISSING")
    assert first["liquidity"] == Cell(None, "COMPONENT_MISSING")

    none = replace(regs, facilities=())
    inputs = _without(_inputs(none), "FY:FY2025", "acct:rcf_drawn")
    assert _frame(inputs)["BASE:2026"]["undrawn_rcf"] == Cell(None, "NOT_SOURCED")


def _deck(*years: tuple[str, int, str]) -> RateDeck:
    return RateDeck(
        "d",
        "2026-10-01",
        tuple(
            RateDeckYear(ref, offset, Decimal(r), Decimal(r))
            for ref, offset, r in years
        ),
    )


def test_a_deck_without_the_reference_rate_falls_back_to_the_implied_rate() -> None:
    deck = _deck(("SONIA", 1, "0.04"))

    assert facility_rate(_row("tlb"), deck, "BASE", 1, Cell(Decimal("0.06"))) == (
        Decimal("0.06"),
        "reference rate not in deck",
    )
    first = _frame(_inputs(deck=deck))["BASE:2026"]
    assert first["fac:tlb"].note == "reference rate not in deck"
    assert first["reference_rate"] == Cell(
        None, "NOT_SOURCED", note="reference rate not in deck"
    )


def test_deck_notes_tell_a_held_year_from_a_missing_one() -> None:
    deck = _deck(("SOFR", 1, "0.03"), ("SOFR", 3, "0.05"))
    tlb = _row("tlb")

    assert facility_rate(tlb, deck, "BASE", 1, _NO_IMPLIED) == (Decimal("0.0575"), None)
    assert facility_rate(tlb, deck, "BASE", 2, _NO_IMPLIED) == (
        Decimal("0.0575"),
        "deck year missing",
    )
    assert facility_rate(tlb, deck, "BASE", 3, _NO_IMPLIED) == (Decimal("0.0775"), None)
    assert facility_rate(tlb, deck, "BASE", 4, _NO_IMPLIED) == (
        Decimal("0.0775"),
        "last deck rate held flat",
    )
    late = _deck(("SOFR", 2, "0.03"))
    assert facility_rate(tlb, late, "BASE", 1, Cell(Decimal("0.06"))) == (
        Decimal("0.06"),
        "deck year missing",
    )
    frame = _frame(_inputs(deck=deck))
    assert frame["BASE:2027"]["reference_rate"] == Cell(
        Decimal("0.03"), basis="DRIVER", note="deck year missing"
    )
    assert frame["BASE:2027"]["fac:tlb"].note == "deck year missing"
    assert frame["BASE:2028"]["reference_rate"] == Cell(Decimal("0.05"), basis="DRIVER")


def test_a_revolver_in_another_currency_gives_no_undrawn() -> None:
    regs = _terms(example_registers(), "rcf", {"currency": "EUR"})
    inputs = _without(_inputs(regs), "FY:FY2025", "acct:rcf_drawn")

    assert _frame(inputs)["BASE:2026"]["undrawn_rcf"] == Cell(None, "NOT_SOURCED")


def test_two_periods_for_one_case_and_year_are_refused() -> None:
    request = example_request()
    request["periods"].append(
        {"case": "BASE", "period_id": "FY2026b", "fiscal_year": "2026", "days": "365"}
    )

    with pytest.raises(Refusal) as caught:
        projection(_inputs(request=request))
    assert caught.value.code == RefusalCode.HANDOFF_MALFORMED


def test_debt_cp_cf_issues_on_no_facility_mix_bears_the_implied_rate() -> None:
    zero = dict.fromkeys(_INTEREST_BEARING, Decimal(0))
    regs = _at_anchor(example_registers(), zero)
    request = example_request()
    request["drivers"][0]["issuance"] = "5000"
    frame = _frame(_inputs(regs, request))
    second = frame["BASE:2027"]

    assert _value(second["interest_bearing_debt_opening"]) == 4178
    assert second["wa_rate"] == Cell(
        _IMPLIED, basis="CALCULATED", note="no facility mix, implied rate"
    )
    assert second["cash_interest"].value == CONTEXT.minus(
        CONTEXT.multiply(_IMPLIED, Decimal(4178))
    )
    # The no-mix note reaches the rate, not the interest: that carries the
    # base's own note, as before the coupon reading.
    for column in ("BASE:2027", "BASE:2028"):
        cells = frame[column]
        assert (
            cells["cash_interest"].note == cells["interest_bearing_debt_opening"].note
        )
    assert second["cash_closing"].value is not None
    assert frame["BASE:2028"]["cash_closing"].value is not None
    # With the implied rate refused too, its reason is carried.
    negative = Cell(Decimal(-14106), basis="CALCULATED")
    second = _frame(_ltm(_inputs(regs, request), "debt_opening", negative))["BASE:2027"]
    assert second["wa_rate"] == Cell(None, "ZERO_OR_NEGATIVE_DENOMINATOR")
    # Half a unit issued is still debt to bear interest.
    request["drivers"][0].update({"issuance": "0.5", "optional_repayment": "0"})
    second = _frame(_inputs(regs, request))["BASE:2027"]
    assert _value(second["interest_bearing_debt_opening"]) == Decimal("0.5")
    assert second["wa_rate"].note == "no facility mix, implied rate"


# Fix wave B (the adversary audit of b64facb7): H4, H5, H6, M1, M4, M5, L1-L4.

_WRONG_UNIT_IMPLIED = Decimal("0.061")


@pytest.mark.parametrize(
    ("facility_id", "terms"),
    [
        ("tlb", {"spread_bps": Decimal("2.25")}),  # "2.25%" read as 2.25 bp
        ("tlb", {"spread_bps": Decimal(2001)}),
        ("tlb", {"floor_bps": Decimal("0.5")}),  # "0.50%" read as 0.5 bp
        ("tlb", {"floor_bps": Decimal(1001)}),
        ("ssn29", {"fixed_rate": Decimal("-0.01")}),
        ("ssn29", {"fixed_rate": Decimal("30.01")}),
        # Read as a fraction (0.001 and 0.004999) and still below half a
        # percent, or over 30.
        ("ssn29", {"fixed_rate": Decimal("0.1"), "coupon_as_fraction": True}),
        ("ssn29", {"fixed_rate": Decimal("0.4999"), "coupon_as_fraction": True}),
        ("ssn29", {"fixed_rate": Decimal("30.01"), "coupon_as_fraction": True}),
    ],
)
def test_a_rate_term_in_the_wrong_unit_is_out_of_range(
    facility_id: str, terms: dict[str, Any]
) -> None:
    row = replace(_row(facility_id), **terms)
    rate = facility_rate(row, example_deck(), "BASE", 1, Cell(_WRONG_UNIT_IMPLIED))

    assert rate == (_WRONG_UNIT_IMPLIED, "term out of range")


def test_rate_term_bounds_are_inclusive() -> None:
    deck = example_deck()
    widest = replace(_row("tlb"), spread_bps=Decimal(2000), floor_bps=Decimal(1000))
    # The 10% floor is above the deck's 3.80%: 10% + 20%.
    assert facility_rate(widest, deck, "BASE", 1, _NO_IMPLIED) == (Decimal("0.3"), None)
    whole = replace(_row("tlb"), spread_bps=Decimal("275.00"))
    assert facility_rate(whole, deck, "BASE", 1, _NO_IMPLIED) == (
        Decimal("0.0655"),
        None,
    )
    # MINOR-10: a zero-coupon convertible is priced at its stated 0%; a
    # coupon below half a percent the reader kept (written with `%`) is as
    # stated.
    for coupon in ("0", "0.001", "0.065", "0.4999", "0.5", "30"):
        row = replace(_row("ssn29"), fixed_rate=Decimal(coupon))
        expected = Decimal(coupon) / 100
        assert facility_rate(row, deck, "BASE", 1, _NO_IMPLIED) == (expected, None)


@pytest.mark.parametrize(
    ("written", "text", "expected"),
    [
        ("0.065", "6.5%", (Decimal("0.065"), "coupon read as a fraction")),
        ("0.250", "0.250%", (Decimal("0.0025"), None)),
        ("0.065", "Senior notes", (_WRONG_UNIT_IMPLIED, "term out of range")),
        ("0", "", (Decimal(0), None)),
        ("0.4", "40%", (_WRONG_UNIT_IMPLIED, "term out of range")),
        ("0.5", "", (Decimal("0.005"), None)),
        ("30", "", (Decimal("0.3"), None)),
        ("30.01", "", (_WRONG_UNIT_IMPLIED, "term out of range")),
        ("-0.01", "", (_WRONG_UNIT_IMPLIED, "term out of range")),
    ],
)
def test_a_coupon_prices_in_percent_as_the_reader_reads_it(
    written: str, text: str, expected: tuple[Decimal, str | None]
) -> None:
    coupon, as_fraction, decided = coupon_percent(Decimal(written), text)
    row = replace(
        _row("ssn29"),
        fixed_rate=coupon,
        coupon_as_fraction=as_fraction,
        terms_out_of_range=not decided,
    )

    assert facility_rate(row, example_deck(), "BASE", 1, Cell(_WRONG_UNIT_IMPLIED)) == (
        expected
    )


def test_a_coupon_read_as_a_fraction_prices_from_half_a_percent() -> None:
    deck = example_deck()
    for coupon in ("0.5", "30"):
        row = replace(
            _row("ssn29"), fixed_rate=Decimal(coupon), coupon_as_fraction=True
        )
        assert facility_rate(row, deck, "BASE", 1, _NO_IMPLIED) == (
            Decimal(coupon) / 100,
            "coupon read as a fraction",
        )


def test_a_coupon_on_a_floating_row_never_moves_its_rate() -> None:
    deck = example_deck()
    tlb = _row("tlb")
    priced = facility_rate(tlb, deck, "BASE", 1, _NO_IMPLIED)

    for coupon in ("0.065", "0.4", "0", "30"):
        row = replace(tlb, fixed_rate=Decimal(coupon))
        assert facility_rate(row, deck, "BASE", 1, _NO_IMPLIED) == priced, coupon
    assert priced[1] is None


def _read_coupon(written: str, text: str) -> dict[str, Any]:
    """ssn29's terms as the reader reads a coupon `written` beside `text`."""
    coupon, as_fraction, decided = coupon_percent(Decimal(written), text)
    return {
        "fixed_rate": coupon,
        "coupon_as_fraction": as_fraction,
        "terms_out_of_range": not decided,
    }


def test_a_coupon_read_as_a_fraction_is_noted_on_the_facility() -> None:
    terms = _read_coupon("0.065", "6.500%")
    first = _frame(_inputs(_terms(example_registers(), "ssn29", terms)))["BASE:2026"]
    stated = _frame(_inputs())["BASE:2026"]

    assert first["fac:ssn29"].note == COUPON_AS_FRACTION
    assert COUPON_AS_FRACTION == "coupon read as a fraction"
    assert first["fac:ssn31"].note is None
    # 6.5%, as the register's 6.500 prices.
    assert first["cash_interest"].value == stated["cash_interest"].value
    assert first["wa_rate"].value == stated["wa_rate"].value


def test_a_coupon_read_as_a_fraction_is_noted_on_the_weighted_rate_and_interest() -> (
    None
):
    terms = _read_coupon("0.065", "6.500%")
    first = _frame(_inputs(_terms(example_registers(), "ssn29", terms)))["BASE:2026"]
    stated = _frame(_inputs())["BASE:2026"]

    assert first["wa_rate"].note == COUPON_AS_FRACTION
    assert COUPON_AS_FRACTION in (first["cash_interest"].note or "")
    assert stated["wa_rate"].note is None
    assert stated["cash_interest"].note is None


def test_a_fraction_coupon_on_a_balance_under_one_unit_still_notes_the_interest() -> (
    None
):
    # The facility weight is any positive balance, however small.
    zero = dict.fromkeys(_INTEREST_BEARING, Decimal(0)) | {"ssn29": Decimal("0.5")}
    terms = _read_coupon("0.065", "6.500%")
    regs = _terms(_at_anchor(example_registers(), zero), "ssn29", terms)
    first = _frame(_inputs(regs))["BASE:2026"]

    assert first["wa_rate"].note == COUPON_AS_FRACTION
    assert first["cash_interest"].value is not None
    assert COUPON_AS_FRACTION in (first["cash_interest"].note or "")


def test_a_coupon_stated_beside_its_text_prices_at_that_percent_unnoted() -> None:
    terms = _read_coupon("0.250", "0.250%")
    first = _frame(_inputs(_terms(example_registers(), "ssn29", terms)))["BASE:2026"]

    assert first["fac:ssn29"].note is None
    assert first["wa_rate"].note is None
    assert first["cash_interest"].note is None


def test_only_the_fraction_note_reaches_the_weighted_rate_and_interest() -> None:
    # A coupon with no deciding text prices at the implied rate, noted "term
    # out of range" on the facility alone, as every other facility-rate note.
    terms = _read_coupon("0.065", "Senior notes")
    first = _frame(_inputs(_terms(example_registers(), "ssn29", terms)))["BASE:2026"]

    assert first["fac:ssn29"].note is not None
    assert projection_module.OUT_OF_RANGE in first["fac:ssn29"].note
    assert COUPON_AS_FRACTION not in (first["wa_rate"].note or "")
    assert COUPON_AS_FRACTION not in (first["cash_interest"].note or "")
    assert projection_module.OUT_OF_RANGE not in (first["wa_rate"].note or "")


def test_an_undrawn_fraction_coupon_leaves_the_weighted_rate_unnoted() -> None:
    terms = _read_coupon("0.065", "6.500%")
    regs = _terms(example_registers(), "ssn29", terms)
    regs = replace(
        regs,
        facilities=tuple(
            replace(f, drawn_amount=Decimal(0), carrying_value=Decimal(0))
            if f.facility_id == "ssn29"
            else f
            for f in regs.facilities
        ),
    )
    first = _frame(_inputs(regs))["BASE:2026"]

    assert first["wa_rate"].note is None


def test_terms_in_the_wrong_unit_price_at_the_implied_rate_noted() -> None:
    wrong = {"spread_bps": Decimal("2.25"), "floor_bps": Decimal("0.5")}
    regs = _terms(example_registers(), "tlb", wrong)
    regs = _terms(regs, "ssn29", {"fixed_rate": Decimal("30.5")})
    first = _frame(_inputs(regs))["BASE:2026"]

    assert first["fac:tlb"].note == "term out of range"
    assert first["fac:ssn29"].note == "term out of range"
    interest = CONTEXT.multiply(Decimal(4328), _IMPLIED) + _FIXED_INTEREST - 130
    assert _about(first["cash_interest"], -interest)


def test_projected_revenue_is_cp_cfs_with_the_business_units_kept() -> None:
    regs = example_registers()
    partial = replace(
        regs,
        segments=tuple(
            s for s in regs.segments if s.segment_id in {"las_vegas", "regional"}
        ),
    )
    first = _frame(_inputs(partial))["BASE:2026"]

    assert first["revenue"] == Cell(Decimal(11809), basis="DRIVER")
    las_vegas = Decimal(4213) * Decimal("1.025")
    assert first["bu:las_vegas"] == Cell(las_vegas, basis="PROJECTED")
    assert first["bu:regional"].value == Decimal(5746) * Decimal("1.010")


def test_without_cp_cf_revenue_projected_revenue_is_the_business_units() -> None:
    request = example_request()
    for driver in request["drivers"]:
        del driver["revenue"]
    first = _frame(_inputs(request=request))["BASE:2026"]

    revenue = sum(
        (first[key].value or Decimal(0) for key in first if key.startswith("bu:")),
        Decimal(0),
    )
    assert first["revenue"] == Cell(revenue, basis="CALCULATED")


_FOREIGN = "excludes facility in another currency"
_FOREIGN_KEYS = (
    "total_debt",
    "net_debt",
    "debt_opening",
    "debt_closing",
    "interest_bearing_debt_opening",
    "cash_interest",
)


def test_a_foreign_facility_is_noted_on_projected_debt_and_interest() -> None:
    regs = _terms(example_registers(), "sun29", {"currency": "EUR"})
    frame = _frame(_inputs(regs))

    for column_id in ("BASE:2026", "BASE:2027", "DOWNSIDE:2028"):
        for key in _FOREIGN_KEYS:
            assert frame[column_id][key].note == _FOREIGN, (column_id, key)
    # Unsecured: secured debt leaves out only CP-CF's unallocated movements.
    assert frame["BASE:2026"]["secured_debt"].note == (
        "excludes unallocated CP-CF movements"
    )
    assert frame["DOWNSIDE:2026"]["secured_debt"].note is None
    secured = _terms(example_registers(), "ssn29", {"currency": "EUR"})
    first = _frame(_inputs(secured))["BASE:2026"]
    assert (
        first["secured_debt"].note
        == f"{_FOREIGN}; excludes unallocated CP-CF movements"
    )
    clean = _frame(_inputs())["BASE:2026"]
    assert all(clean[key].note is None for key in _FOREIGN_KEYS)


def test_projected_secured_debt_notes_unallocated_movements() -> None:
    frame = _frame(_inputs())
    unallocated = "excludes unallocated CP-CF movements"

    # Base repays 822 optionally in 2026: total debt moves off the schedule.
    assert frame["BASE:2026"]["secured_debt"] == Cell(
        Decimal(0 + 2304 + 2000 + 1000), basis="CALCULATED", note=unallocated
    )
    # Downside moves only the scheduled amortisation: nothing unallocated.
    assert frame["DOWNSIDE:2026"]["secured_debt"].note is None


def _division_1_growth(value: str) -> ProjectionInputs:
    """The example with DIVISION_1's (Las Vegas) Base FY2026 growth `value`."""
    growth = tuple(
        replace(g, value=Decimal(value))
        if (g.case, g.fiscal_year, g.slot_id) == ("BASE", "2026", "DIVISION_1")
        else g
        for g in example_growth()
    )
    return replace(_inputs(), growth=growth)


def test_a_growth_outside_100_percent_is_noted_on_the_business_unit() -> None:
    frame = _frame(_division_1_growth("8"))  # 8 read as 800%

    assert frame["BASE:2026"]["bu:las_vegas"] == Cell(
        Decimal(4213) * 9, basis="PROJECTED", note="growth outside ±100%"
    )
    assert frame["BASE:2027"]["bu:las_vegas"].note is None
    for value, note in (
        ("1", None),
        ("-1", None),
        ("1.01", "growth outside ±100%"),
        ("-1.01", "growth outside ±100%"),
    ):
        first = _frame(_division_1_growth(value))["BASE:2026"]
        assert first["bu:las_vegas"].note == note, value


def _malformed(request: dict[str, Any]) -> None:
    with pytest.raises(Refusal) as caught:
        projection(_inputs(request=request))
    assert caught.value.code == RefusalCode.HANDOFF_MALFORMED


def test_a_request_missing_a_precondition_is_refused_typed() -> None:
    for top in ("opening", "periods", "drivers"):
        request = example_request()
        del request[top]
        _malformed(request)
    for field in ("case", "period_id", "fiscal_year", "days"):
        request = example_request()
        del request["periods"][0][field]
        _malformed(request)
    for field in ("case", "period_id"):
        request = example_request()
        del request["drivers"][0][field]
        _malformed(request)
    request = example_request()
    del request["opening"]["as_of_period_id"]
    _malformed(request)


def test_a_request_of_the_wrong_shape_is_refused_typed() -> None:
    shapes: list[tuple[str, Any]] = [
        ("opening", "FY2025"),
        ("periods", {"case": "BASE"}),
        ("periods", ["FY2026"]),
        ("drivers", [None]),
    ]
    for top, value in shapes:
        request = example_request()
        request[top] = value
        _malformed(request)
    for field, value in (("case", ["BASE"]), ("fiscal_year", 2026)):
        request = example_request()
        request["periods"][0][field] = value
        _malformed(request)
    request = example_request()
    request["drivers"][0]["period_id"] = {"FY2026"}
    _malformed(request)


def test_an_outflow_driver_of_zero_is_no_negative_zero() -> None:
    request = example_request()
    request["drivers"][0]["acquisitions_disposals"] = "-0"
    frame = _frame(_inputs(request=request))

    for column_id, key in (
        ("DOWNSIDE:2026", "dividends"),
        ("DOWNSIDE:2026", "acquisitions_net"),
        ("BASE:2026", "acquisitions_net"),
    ):
        value = _value(frame[column_id][key])
        assert value == 0 and not value.is_signed(), (column_id, key)


def test_a_negative_interest_base_has_no_interest_noted() -> None:
    request = example_request()
    request["drivers"][0]["optional_repayment"] = "20000"
    second = _frame(_inputs(request=request))["BASE:2027"]

    assert _value(second["interest_bearing_debt_opening"]) < 0
    assert second["cash_interest"] == Cell(
        None, "COMPONENT_MISSING", note="negative interest base"
    )


def test_interest_is_not_rounded_through_the_weighted_rate() -> None:
    first = _frame(_inputs())["BASE:2026"]

    # 2,328 at 6.55% and the fixed coupons: 858.984 exactly, not the
    # 38-digit weighted rate times 14,028.
    assert first["cash_interest"] == Cell(Decimal("-858.984"), basis="CALCULATED")
    with localcontext(CONTEXT):
        rounded = -(_value(first["wa_rate"]) * 14028)
    assert rounded != Decimal("-858.984")


def test_an_incomplete_opening_stack_leaves_no_implied_rate_noted() -> None:
    regs = example_registers()
    regs = replace(
        regs,
        facilities=tuple(
            f
            for f in regs.facilities
            if not (f.facility_id == "ssn29" and f.period_id == "Q2_2025")
        ),
    )
    regs = _terms(regs, "tlb", {"rate_type": "NOT_STATED"})
    first = _frame(_inputs(regs))["BASE:2026"]

    incomplete = "opening stack incomplete"
    assert first["wa_rate"] == Cell(None, "COMPONENT_MISSING", note=incomplete)
    assert first["cash_interest"] == Cell(None, "COMPONENT_MISSING", note=incomplete)


def test_interest_on_weights_below_one_is_not_rounded_through_the_rate() -> None:
    debt = dict.fromkeys(_INTEREST_BEARING, Decimal(0)) | {
        "tlb": Decimal("0.25"),
        "ssn29": Decimal("0.5"),
    }
    first = _frame(_inputs(_at_anchor(example_registers(), debt)))["BASE:2026"]

    # 0.25 at 6.55% and 0.5 at 6.5% on a base of 0.75: the rate does not
    # terminate, the interest does.
    assert _value(first["interest_bearing_debt_opening"]) == Decimal("0.75")
    assert first["cash_interest"].value == Decimal("-0.048875")


def test_with_no_facility_mix_an_incomplete_opening_says_why() -> None:
    zero = dict.fromkeys(_INTEREST_BEARING, Decimal(0))
    regs = _at_anchor(example_registers(), zero)
    request = example_request()
    request["drivers"][0]["issuance"] = "5000"
    incomplete = Cell(None, "COMPONENT_MISSING", note="opening stack incomplete")
    inputs = _ltm(_inputs(regs, request), "debt_opening", incomplete)

    second = _frame(inputs)["BASE:2027"]
    assert second["wa_rate"] == incomplete


def test_interest_from_weights_below_one_on_a_larger_base_is_exact() -> None:
    debt = dict.fromkeys(_INTEREST_BEARING, Decimal(0)) | {
        "ssn29": Decimal("0.25"),
        "ssn31": Decimal("0.5"),
    }
    request = example_request()
    request["drivers"][0].update({"issuance": "5000", "optional_repayment": "0"})
    second = _frame(_inputs(_at_anchor(example_registers(), debt), request))[
        "BASE:2027"
    ]

    weighted = Decimal("0.25") * Decimal("0.065") + Decimal("0.5") * Decimal("0.07")
    base = Decimal("5000.75")
    assert _value(second["interest_bearing_debt_opening"]) == base
    exact = CONTEXT.divide(CONTEXT.multiply(weighted, base), Decimal("0.75"))
    rounded = CONTEXT.multiply(_value(second["wa_rate"]), base)
    assert exact != rounded
    assert second["cash_interest"].value == exact.copy_negate()


def test_a_facility_whose_terms_were_written_out_of_range_prices_implied() -> None:
    # In range as read (225 bp), but CP-1 wrote it out of its unit.
    flagged = replace(_row("tlb"), terms_out_of_range=True)
    assert facility_rate(
        flagged, example_deck(), "BASE", 1, Cell(_WRONG_UNIT_IMPLIED)
    ) == (
        _WRONG_UNIT_IMPLIED,
        "term out of range",
    )
    assert facility_rate(_row("tlb"), example_deck(), "BASE", 1, _NO_IMPLIED)[1] is None

    regs = _terms(example_registers(), "tlb", {"terms_out_of_range": True})
    first = _frame(_inputs(regs))["BASE:2026"]
    assert first["fac:tlb"].note == "term out of range"


def _named_for_start_year(regs: Cp1Registers) -> Cp1Registers:
    """`regs` with each fiscal year named for the year it starts in, a year
    before its end (FY2025, ending 2025-12-31, is "2024")."""
    return replace(
        regs,
        periods=tuple(
            replace(p, fiscal_year=str(int(p.fiscal_year) - 1))
            if p.period_type == "FY"
            else p
            for p in regs.periods
        ),
    )


@pytest.mark.parametrize("year", ["9999", "2201", "1899", "2035", "2013"])
def test_a_request_year_out_of_range_is_refused_not_raised(year: str) -> None:
    regs = _named_for_start_year(example_registers())
    request = example_request()
    request["periods"][-1]["fiscal_year"] = year

    with pytest.raises(Refusal) as caught:
        projection(_inputs(regs, request))
    assert caught.value.code == RefusalCode.HANDOFF_MALFORMED


def test_a_request_year_ten_from_the_base_year_is_placed() -> None:
    regs = _named_for_start_year(example_registers())
    request = example_request()
    request["periods"][-1]["fiscal_year"] = "2034"  # the base year, 2024, + 10

    columns, _ = projection(_inputs(regs, request))

    assert columns[-1].end_date == "2035-12-31"


def test_a_projection_names_why_its_anchor_figure_is_missing() -> None:
    """The audit's M1 projection sites: an anchor figure missing with a
    reason keeps it on what is built from it."""
    why = Cell(None, "COMPONENT_MISSING", note=UNSPANNED)
    assert projection_module._opening_cell(why) == why
    one = Cell(Decimal(1))
    cells = {"cash_interest": why, "debt_opening": one, "total_debt": one}
    assert projection_module._implied(cells) == why
    cells = {"cash_interest": one, "debt_opening": one, "total_debt": why}
    assert projection_module._implied(cells) == why
    # FY2025's components do not span it: its business units' revenue, the
    # anchor CP-CF grows from, is missing with that reason, and so is the
    # projection.
    regs = example_registers()
    regs = replace(
        regs,
        periods=tuple(
            replace(p, component_period_ids=("Q1_2025", "Q2_2025", "GHOST"))
            if p.period_id == "FY2025"
            else p
            for p in regs.periods
        ),
    )
    assert _frame(_inputs(regs))["BASE:2026"]["bu:las_vegas"] == why


def test_the_implied_rate_carries_an_opening_whose_history_is_incomplete() -> None:
    """The re-verify's L2 (p14): the term loan's rows before Q3 2025
    removed, so the LTM's opening debt is CP-1's stated total, noted; ssn29
    with no rate type prices at the implied rate built from it."""
    regs = example_registers()
    early = {"FY2023", "FY2024", "Q1_2025", "Q2_2025", "H1_2025"}
    early |= {f"Q{n}_2024" for n in range(1, 5)}
    regs = replace(
        regs,
        facilities=tuple(
            replace(f, rate_type="NOT_STATED", fixed_rate=None)
            if f.facility_id == "ssn29"
            else f
            for f in regs.facilities
            if not (f.facility_id == "tlb" and f.period_id in early)
        ),
    )
    model = credit_model(
        ModelInputs(
            registers=regs,
            request=example_request(),
            growth=example_growth(),
            slots=example_slots(),
            deck=example_deck(),
        )
    )
    ids = [c.column_id for c in model.columns]

    def cell(line_id: str, column_id: str) -> Cell:
        line = next(line for line in model.lines if line.line_id == line_id)
        return line.cells[ids.index(column_id)]

    opening = cell("debt_opening", "LTM:LTM_Q2_2026")
    assert (opening.value, opening.note) == (Decimal(14130), HISTORY_INCOMPLETE)
    assert cell("fac:ssn29", "BASE:2026").note == f"implied rate; {HISTORY_INCOMPLETE}"
    # The implied rate itself, and facility_rate's note on it.
    one = Cell(Decimal(1))
    noted = Cell(Decimal(1), note=HISTORY_INCOMPLETE)
    cells = {
        "cash_interest": Cell(Decimal(-1)),
        "debt_opening": noted,
        "total_debt": one,
    }
    assert projection_module._implied(cells) == Cell(
        Decimal(1), note=HISTORY_INCOMPLETE
    )
    cells = {**cells, "debt_opening": one}
    assert projection_module._implied(cells) == Cell(Decimal(1))
    ssn29 = next(f for f in regs.facilities if f.facility_id == "ssn29")
    rate = Cell(Decimal("0.06"), note=HISTORY_INCOMPLETE)
    assert facility_rate(ssn29, None, "BASE", 1, rate) == (
        Decimal("0.06"),
        f"implied rate; {HISTORY_INCOMPLETE}",
    )
    # The weighted rate with no facility mix is the implied rate, as noted.
    assert projection_module._unweighted(rate, Cell(Decimal(1))) == Cell(
        Decimal("0.06"),
        basis="CALCULATED",
        note=f"no facility mix, implied rate; {HISTORY_INCOMPLETE}",
    )
    # No implied rate: its reason is the weighted rate's, not the facility's.
    missing = Cell(None, "COMPONENT_MISSING", note=HISTORY_INCOMPLETE)
    assert facility_rate(ssn29, None, "BASE", 1, missing) == (None, "implied rate")


@pytest.mark.parametrize(
    ("start", "end", "days", "why"),
    [
        ("2025-04-01", "2025-12-31", 275, "short fiscal year (FY2025)"),
        ("2024-10-01", "2025-12-31", 457, "long fiscal year (FY2025)"),
        (None, "2025-12-31", None, UNSPANNED),
        ("2025-01-01", None, 365, UNSPANNED),
    ],
)
@pytest.mark.parametrize("driver_revenue", [True, False])
def test_an_incomplete_base_fy_withholds_every_projected_figure(
    start: str | None,
    end: str | None,
    days: int | None,
    why: str,
    driver_revenue: bool,
) -> None:
    regs = example_registers()
    regs = replace(
        regs,
        periods=tuple(
            replace(p, start_date=start, end_date=end, day_count=days)
            if p.period_id == "FY2025"
            else p
            for p in regs.periods
        ),
    )
    request = example_request()
    if not driver_revenue:
        for driver in request["drivers"]:
            del driver["revenue"]
    inputs = _inputs(regs, request)
    columns, frame = projection(inputs)
    assert [(c.column_id, c.end_date) for c in columns] == [
        (f"{case}:{year}", f"{year}-12-31")
        for case in ("BASE", "DOWNSIDE")
        for year in (2026, 2027, 2028)
    ]
    expected = Cell(None, "COMPONENT_MISSING", note=f"projection base: {why}")
    for column in columns:
        for key, cell in frame[column.column_id].items():
            if cell.reason not in {"NOT_PROJECTED", "NOT_APPLICABLE"}:
                assert cell == expected, (column.column_id, key)
    assert inputs.history["FY:FY2025"]["revenue"].value == 11519
    assert frame["BASE:2026"]["ebitda"] == Cell(None, "NOT_PROJECTED")


@pytest.mark.parametrize(
    ("start", "end", "days"),
    [
        ("2025-01-01", "2025-12-31", 365),
        ("2024-03-01", "2025-02-28", 365),
        ("2024-01-01", "2024-12-31", 366),
        ("2024-02-04", "2025-02-01", 364),
        ("2024-02-04", "2025-02-08", 371),
        (None, "2025-12-31", 365),
        ("2025-01-01", "2026-01-07", 372),
    ],
)
def test_a_complete_base_fy_preserves_projection_compounding(
    start: str | None,
    end: str,
    days: int,
) -> None:
    regs = example_registers()
    regs = replace(
        regs,
        periods=tuple(
            replace(p, start_date=start, end_date=end, day_count=days)
            if p.period_id == "FY2025"
            else p
            for p in regs.periods
        ),
    )
    frame = _frame(_inputs(regs))
    assert frame["BASE:2028"]["bu:las_vegas"].value == (
        Decimal(4213) * Decimal("1.025") * Decimal("1.030") * Decimal("1.030")
    )
    assert frame["DOWNSIDE:2026"]["revenue"].value is not None


def test_an_incomplete_base_preserves_no_floating_reference_rate() -> None:
    regs = example_registers()
    regs = replace(
        regs,
        facilities=tuple(row for row in regs.facilities if row.rate_type != "FLOATING"),
    )
    # The actual facility mix has no floating reference rate before applying
    # the base-FY refusal; the refusal must preserve that structural reason.
    valid_columns, valid_frame = projection(_inputs(regs))
    assert len(valid_columns) == 6
    for column in valid_columns:
        assert valid_frame[column.column_id]["reference_rate"] == Cell(
            None, "NOT_APPLICABLE"
        )
        assert valid_frame[column.column_id]["revenue"].value is not None
    regs = replace(
        regs,
        periods=tuple(
            replace(p, start_date="2025-04-01", day_count=275)
            if p.period_id == "FY2025"
            else p
            for p in regs.periods
        ),
    )
    columns, frame = projection(_inputs(regs))
    assert columns == valid_columns
    for column in columns:
        cells = frame[column.column_id]
        assert cells["reference_rate"] == Cell(None, "NOT_APPLICABLE")
        assert cells["revenue"] == Cell(
            None,
            "COMPONENT_MISSING",
            note="projection base: short fiscal year (FY2025)",
        )
        assert cells["ebitda"] == Cell(None, "NOT_PROJECTED")


def test_an_incomplete_base_fy_still_refuses_a_malformed_driver() -> None:
    regs = example_registers()
    regs = replace(
        regs,
        periods=tuple(
            replace(p, start_date="2025-04-01", day_count=275)
            if p.period_id == "FY2025"
            else p
            for p in regs.periods
        ),
    )
    request = example_request()
    request["drivers"][0]["capex"] = "1,700"
    with pytest.raises(Refusal) as caught:
        projection(_inputs(regs, request))
    assert caught.value.code == RefusalCode.METHODOLOGY_INPUT_INVALID


def test_optional_cash_movements_preserve_first_year_interest_and_fcf() -> None:
    request = example_request()
    baseline = _frame(_inputs())["BASE:2026"]
    request["drivers"][0].update(
        net_equity_issue_repay="5",
        other_investing_financing="-24",
        restricted_cash_change="15",
        carrying_value_change="26",
    )
    actual = _frame(_inputs(request=request))["BASE:2026"]
    assert actual["cash_interest"] == baseline["cash_interest"]
    assert actual["fcf"] == baseline["fcf"]
    assert actual["cash_closing"].value == _value(baseline["cash_closing"]) - 34
    assert actual["total_debt"].value == _value(baseline["total_debt"]) + 26
    assert actual["equity_raised_net"].value == 5
    assert actual["other_investing_financing"].value == -24
    assert actual["fx_and_other_cash"].value == -15
    assert actual["equity_raised_net"].sources == ()


def test_explicit_segment_levels_override_shared_slot_growth() -> None:
    from test_forecast_segments import segment_inputs

    request, regs = segment_inputs()
    inputs = _inputs(regs=regs, request=request)
    inputs = replace(
        inputs, slots=(SlotAllocation("shared", ("las_vegas", "regional")),)
    )
    frame = _frame(inputs)
    for cells in frame.values():
        assert cells["bu:las_vegas"].value == 4300
        assert cells["bu:regional"].value == 5800
        assert cells["bu:corporate_eliminations"].value == -60
        assert cells["bu:las_vegas"].sources == ()
        assert "explicit CP-2G" in (cells["bu:las_vegas"].note or "")


@pytest.mark.parametrize("amount", ["0", "-5", "5"])
def test_optional_movements_preserve_explicit_zero_and_sign(amount: str) -> None:
    request = example_request()
    request["drivers"][0].update(
        net_equity_issue_repay=amount,
        other_investing_financing=amount,
        restricted_cash_change=amount,
        carrying_value_change=amount,
    )
    actual = _frame(_inputs(request=request))["BASE:2026"]
    baseline = _frame(_inputs())["BASE:2026"]
    value = Decimal(amount)
    assert actual["cash_closing"].value == _value(baseline["cash_closing"]) + value
    assert actual["total_debt"].value == _value(baseline["total_debt"]) + value
    assert actual["equity_raised_net"].value == value
    assert actual["other_investing_financing"].value == value
    assert actual["fx_and_other_cash"].value == -value
    assert actual["equity_raised_net"].note is None
    assert "restricted-cash transfer" in (actual["fx_and_other_cash"].note or "")


@pytest.mark.parametrize("defect", ["corporate", "sum", "missing"])
def test_explicit_segment_model_contract_refuses_invalid_input(defect: str) -> None:
    from test_forecast_segments import segment_inputs

    request, regs = segment_inputs()
    values = request["drivers"][0]["segment_revenue"]
    if defect == "corporate":
        values["corporate_eliminations"] = "-59"
        values["las_vegas"] = "4299"
    elif defect == "sum":
        values["las_vegas"] = "4300.000001"
    else:
        del values["regional"]
    with pytest.raises(Refusal) as caught:
        _frame(_inputs(regs=regs, request=request))
    assert caught.value.code is RefusalCode.HANDOFF_MALFORMED


def test_explicit_segments_do_not_call_native_growth(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from test_forecast_segments import segment_inputs

    def unexpected(*args: object) -> Cell:
        raise AssertionError

    request, regs = segment_inputs()
    monkeypatch.setattr(projection_module, "_grown", unexpected)
    _frame(_inputs(regs=regs, request=request))

"""Forecast contract regressions and independent hand-calculated answer keys."""

from __future__ import annotations

import json
from copy import deepcopy
from decimal import ROUND_DOWN, Decimal, Inexact, localcontext
from typing import Any

import pytest
from forecast_fixtures import forecast_request

from caos.calculators import cash_flow
from caos.calculators.cash_flow import cash_flow_forecast, forecast_bytes
from caos.refusals import Refusal, RefusalCode


def refused(request: dict[str, Any]) -> None:
    with pytest.raises(Refusal) as caught:
        cash_flow_forecast(request)
    assert caught.value.code == RefusalCode.METHODOLOGY_INPUT_INVALID


def test_annual_base_and_downside_reconcile_to_hand_calculated_values() -> None:
    """Hand table, USD millions. Opening debt=700+300=1000, cash=100.
    Debt movement=30+2+3-20-10-5=0; financing=30-20-10-15=-15.
    Base FCF=80-20-10-5=45; cash movement=45-4-15=26.
    Downside FCF=40-20-10-5=5; cash movement=5-4-15=-14.
    case/year | debt | cash | FCF | gross | net   | coverage | FCF/debt
    BASE 26   | 1000 | 126  | 45  | 10    | 8.74  | 10       | .045
    BASE 27   | 1000 | 152  | 45  | 10    | 8.48  | 10       | .045
    DOWN 26   | 1000 | 86   | 5   | 20    | 18.28 | 5        | .005
    DOWN 27   | 1000 | 72   | 5   | 20    | 18.56 | 5        | .005
    """
    result = cash_flow_forecast(forecast_request())
    assert result["status"] == "complete"
    expected = [
        ("126", "45", "10.0000", "8.7400", "10.0000", "0.0450"),
        ("152", "45", "10.0000", "8.4800", "10.0000", "0.0450"),
        ("86", "5", "20.0000", "18.2800", "5.0000", "0.0050"),
        ("72", "5", "20.0000", "18.5600", "5.0000", "0.0050"),
    ]
    for row, (cash, fcf, gross, net, coverage, fcf_debt) in zip(
        result["rows"], expected, strict=True
    ):
        assert row["debt"]["closing"] == "1000.000000"
        assert row["cash"]["closing"] == row["cash"]["accessible"] == cash + ".000000"
        assert row["fcf"] == fcf + ".000000"
        assert row["financing"]["financing_investing"] == "-15.000000"
        assert row["residual_debt"] == row["residual_cash"] == "0.000000"
        assert row["metrics"] == dict(
            zip(
                ("gross_leverage", "net_leverage", "interest_coverage", "fcf_to_debt"),
                [
                    {"value": value, "reason": None}
                    for value in (gross, net, coverage, fcf_debt)
                ],
                strict=True,
            )
        )


def test_quarterly_base_case_reconciles_to_hand_calculated_values() -> None:
    """Debt movement=5+1-2-1=3; financing=5-2-1-(-2)=4.
    FCF=20-5-2-1=12; cash movement=12+4=16; coverage=25/2=12.5.
    quarter | opening debt/cash | closing debt/cash | gross | net | FCF/debt
    Q1      | 1000/100          | 1003/116          | 40.12 | 35.48 | .0120
    Q2      | 1003/116          | 1006/132          | 40.24 | 34.96 | .0119
    FCF/debt: 12/1003=.011964...; 12/1006=.011928..., rounded half even.
    """
    result = cash_flow_forecast(forecast_request(quarterly=True))
    assert result["status"] == "complete"
    for row, values in zip(
        result["rows"],
        [
            ("1003", "116", "40.1200", "35.4800", "0.0120"),
            ("1006", "132", "40.2400", "34.9600", "0.0119"),
        ],
        strict=True,
    ):
        debt, cash, gross, net, ratio = values
        assert row["debt"]["closing"] == debt + ".000000"
        assert row["cash"]["closing"] == cash + ".000000"
        assert row["fcf"] == "12.000000"
        assert row["metrics"] == dict(
            zip(
                ("gross_leverage", "net_leverage", "interest_coverage", "fcf_to_debt"),
                [
                    {"value": value, "reason": None}
                    for value in (gross, net, "12.5000", ratio)
                ],
                strict=True,
            )
        )
    assert result["rows"][1]["debt"]["opening"] == "1003.000000"
    assert result["rows"][1]["cash"]["opening"] == "116.000000"


def test_missing_driver_field_is_unavailable_and_propagates_not_zero() -> None:
    request = forecast_request()
    del request["drivers"][0]["cfo"]
    result = cash_flow_forecast(request)
    assert result["status"] == "incomplete"
    assert [row["unavailable_reason"] for row in result["rows"]] == [
        "DRIVER_FIELD_MISSING",
        "PRIOR_PERIOD_UNAVAILABLE",
        None,
        None,
    ]
    request["drivers"].pop(0)
    assert (
        cash_flow_forecast(request)["rows"][0]["unavailable_reason"] == "DRIVER_MISSING"
    )


def test_explicit_zero_is_zero_and_missing_is_unavailable() -> None:
    request = forecast_request(quarterly=True)
    assert (
        cash_flow_forecast(request)["rows"][0]["financing"]["distributions"]
        == "0.000000"
    )
    del request["drivers"][0]["distributions"]
    assert (
        cash_flow_forecast(request)["rows"][0]["unavailable_reason"]
        == "DRIVER_FIELD_MISSING"
    )


def test_unready_driver_makes_its_case_unavailable_and_other_cases_compute() -> None:
    request = forecast_request()
    request["drivers"][0]["status"] = "DRAFT"
    assert [
        row["unavailable_reason"] for row in cash_flow_forecast(request)["rows"]
    ] == ["DRIVER_NOT_READY", "PRIOR_PERIOD_UNAVAILABLE", None, None]


@pytest.mark.parametrize("collection", ["periods", "drivers", "amortisation"])
def test_duplicate_or_extraneous_periods_drivers_and_amortisation_are_refused(
    collection: str,
) -> None:
    request = forecast_request()
    rows = (
        request["contractual"][collection]
        if collection == "amortisation"
        else request[collection]
    )
    rows.append(deepcopy(rows[0]))
    refused(request)
    rows.pop()
    if collection != "periods":
        rows[0]["period_id"] = "UNKNOWN"
    else:
        request["opening"]["debt_by_facility"].append(
            {"facility_id": "TERM", "amount": "1"}
        )
    refused(request)


@pytest.mark.parametrize(
    "target,key",
    [
        ("top", "policy"),
        ("top", "unknown"),
        ("contractual", "maturities"),
        ("contractual", "coupons"),
        ("opening", "unknown"),
        ("units", "unknown"),
        ("drivers", "financing_investing"),
        ("periods", "unknown"),
        ("amortisation", "unknown"),
        ("debt_by_facility", "unknown"),
    ],
)
def test_policy_maturities_coupons_and_unknown_keys_are_refused(
    target: str, key: str
) -> None:
    request = forecast_request()
    targets = {
        "top": request,
        **request,
        "drivers": request["drivers"][0],
        "periods": request["periods"][0],
        "amortisation": request["contractual"]["amortisation"][0],
        "debt_by_facility": request["opening"]["debt_by_facility"][0],
    }
    targets[target][key] = "0"
    refused(request)


@pytest.mark.parametrize(
    "value",
    [
        1.5,
        1,
        True,
        None,
        "1e4",
        "1e1000000",
        "1" * 19,
        "0.1234567",
        "+1",
        " 1",
        "01",
        "NaN",
        "Infinity",
        Decimal("1"),
        "-1",
        "1\n",
    ],
)
def test_float_int_bool_exponent_and_oversized_numbers_are_refused_before_arithmetic(
    value: object,
) -> None:
    request = forecast_request()
    request["drivers"][0]["cfo"] = value
    refused(request)


def test_zero_denominator_ratio_is_null_with_its_reason() -> None:
    request = forecast_request()
    request["drivers"][0]["ebitda"] = "0"
    assert cash_flow_forecast(request)["rows"][0]["metrics"]["gross_leverage"] == {
        "value": None,
        "reason": "ZERO_OR_NEGATIVE_DENOMINATOR",
    }


def test_residual_over_tolerance_is_unavailable_with_reason() -> None:
    request = forecast_request()
    request["drivers"][0]["stated_closing_cash"] = "126.001"
    assert cash_flow_forecast(request)["status"] == "complete"
    request["drivers"][0]["stated_closing_cash"] = "125.998999"
    rows = cash_flow_forecast(request)["rows"]
    assert rows[0]["residual_cash"] == "-0.001001"
    assert rows[0]["unavailable_reason"] == "RESIDUAL_UNRECONCILED"
    assert rows[1]["unavailable_reason"] == "PRIOR_PERIOD_UNAVAILABLE"


def test_same_request_is_byte_identical_under_changed_ambient_context() -> None:
    request = forecast_request(quarterly=True)
    expected = forecast_bytes(request)
    assert (
        expected
        == json.dumps(
            cash_flow_forecast(request), sort_keys=True, separators=(",", ":")
        ).encode()
    )
    with localcontext() as context:
        context.prec = 2
        context.rounding = ROUND_DOWN
        context.Emax = 2
        context.traps[Inexact] = True
        assert forecast_bytes(request) == expected
        assert context.prec == 2 and context.traps[Inexact]


def test_units_and_perimeter_are_required_and_carried() -> None:
    for field in ("units", "perimeter"):
        request = forecast_request()
        assert cash_flow_forecast(request)[field] == request[field]
        del request[field]
        refused(request)


@pytest.mark.parametrize("ceiling", ["periods", "cases", "facilities", "amortisation"])
def test_work_factor_refuses_before_any_numeric_is_parsed(
    monkeypatch: pytest.MonkeyPatch,
    ceiling: str,
) -> None:
    """The collection ceilings bound the whole of the work -- at most 40
    periods in each of 6 cases over 41 balances, 9,840 -- so no product bound
    stands beside them (FP-36: one did, at 100,000, and could never fire)."""
    request = forecast_request()
    if ceiling == "periods":
        request["periods"] = [
            {"case": "BASE", "period_id": str(n), "fiscal_year": "2026", "days": "bad"}
            for n in range(41)
        ]
    elif ceiling == "cases":
        request["periods"] = [{"case": str(n), "days": "bad"} for n in range(7)]
    elif ceiling == "facilities":
        request["opening"]["debt_by_facility"] = [{}] * 41
    else:
        request["contractual"]["amortisation"] = [{}] * 2001

    def numeric_was_parsed(*args: object, **kwargs: object) -> None:
        pytest.fail("work factor must precede numeric parsing")

    monkeypatch.setattr(cash_flow, "_decimal", numeric_was_parsed)
    refused(request)


def test_forecast_complete_requires_every_requested_period() -> None:
    test_missing_driver_field_is_unavailable_and_propagates_not_zero()


def test_forecast_residual_is_not_forced_to_zero() -> None:
    test_residual_over_tolerance_is_unavailable_with_reason()


def test_forecast_unavailability_propagates() -> None:
    test_unready_driver_makes_its_case_unavailable_and_other_cases_compute()


@pytest.mark.parametrize(
    "field,value",
    [
        ("perimeter", ""),
        ("perimeter", "x" * 65),
        ("perimeter", "x" + chr(0x202E) + "y"),
        ("units", {"currency": "usd", "scale": "millions"}),
        ("units", {"currency": "USD", "scale": []}),
        ("opening", None),
        ("drivers", None),
        ("periods", []),
        ("tolerance", "-0.001"),
        ("contractual", {"amortisation": None}),
    ],
)
def test_malformed_forecast_boundaries_refuse(field: str, value: object) -> None:
    request = forecast_request()
    request[field] = value
    refused(request)


@pytest.mark.parametrize("days", ["0", "367", "1.0", "-1", 90])
def test_days_are_bounded_integer_strings(days: object) -> None:
    request = forecast_request()
    request["periods"][0]["days"] = days
    refused(request)


def test_case_chain_uses_request_order_and_bad_hidden_values_still_refuse() -> None:
    request = forecast_request()
    request["periods"] = [request["periods"][i] for i in [2, 0, 3, 1]]
    assert [
        (row["case"], row["period_id"]) for row in cash_flow_forecast(request)["rows"]
    ] == [
        ("DOWNSIDE", "FY26"),
        ("BASE", "FY26"),
        ("DOWNSIDE", "FY27"),
        ("BASE", "FY27"),
    ]
    request["drivers"][0]["status"] = "DRAFT"
    request["drivers"][1]["capex"] = "NaN"
    refused(request)


def test_negative_closing_debt_has_an_unavailable_ratio() -> None:
    request = forecast_request(quarterly=True)
    request["drivers"][0].update(
        optional_repayment="1005", stated_closing_debt="-1", stated_closing_cash="-888"
    )
    row = cash_flow_forecast(request)["rows"][0]
    assert row["unavailable_reason"] is None
    assert row["metrics"]["fcf_to_debt"] == {
        "value": None,
        "reason": "ZERO_OR_NEGATIVE_DENOMINATOR",
    }


def test_largest_numbers_remain_finite_under_fixed_precision() -> None:
    request = forecast_request(quarterly=True)
    request["opening"]["cash"] = "999999999999999999.999999"
    request["drivers"][0]["stated_closing_cash"] = "999999999999999999.999999"
    request["drivers"][0]["ebitda"] = "0.000001"
    row = cash_flow_forecast(request)["rows"][0]
    assert row["cash"]["closing"] == "1000000000000000015.999999"
    assert row["residual_cash"] == "-16.000000"
    assert row["metrics"]["net_leverage"]["value"] == "-999999999999999012999999.0000"


def test_amortisation_sums_opened_facilities_and_distinct_payments() -> None:
    request = forecast_request()
    payments = request["contractual"]["amortisation"]
    payments.extend(
        [
            {"case": "BASE", "period_id": "FY26", "facility_id": "BOND", "amount": "5"},
            {"case": "BASE", "period_id": "FY26", "facility_id": "TERM", "amount": "3"},
        ]
    )
    request["drivers"][0].update(stated_closing_debt="992", stated_closing_cash="118")
    row = cash_flow_forecast(request)["rows"][0]
    assert row["unavailable_reason"] is None
    assert row["financing"]["contractual_repayment"] == "28.000000"
    payments[-1]["facility_id"] = "UNKNOWN"
    refused(request)


def test_every_case_may_have_its_own_forty_period_ids() -> None:
    request = forecast_request()
    request["drivers"] = []
    request["contractual"]["amortisation"] = []
    request["periods"] = [
        {
            "case": str(case),
            "period_id": f"{case}-{period}",
            "fiscal_year": "2026",
            "days": "366",
        }
        for case in range(6)
        for period in range(40)
    ]
    result = cash_flow_forecast(request)
    assert len(result["rows"]) == len(result["checks"]) == 240
    assert result["status"] == "incomplete"


def test_signed_opening_balances_are_preserved_without_a_policy_plug() -> None:
    """Debt=-700+300=-400; debt movement=0. Cash=-100+45-4-15=-74."""
    request = forecast_request()
    request["opening"]["debt_by_facility"][0]["amount"] = "-700"
    request["opening"]["cash"] = "-100"
    request["drivers"][0].update(stated_closing_debt="-400", stated_closing_cash="-74")
    row = cash_flow_forecast(request)["rows"][0]
    assert row["unavailable_reason"] is None
    assert row["debt"]["closing"] == "-400.000000"
    assert row["cash"]["closing"] == "-74.000000"


def test_a_facility_s_instalments_in_one_period_sum_and_only_a_repeat_refuses() -> None:
    """The legacy rule the parity goldens hold: two rows for one facility and
    period are two instalments, and only an exact repeat is refused."""
    request = forecast_request()
    first = request["contractual"]["amortisation"][0]
    request["contractual"]["amortisation"].append(
        {**first, "amount": str(Decimal(first["amount"]) + 1)}
    )
    assert cash_flow_forecast(request)["status"] in ("complete", "incomplete")
    request["contractual"]["amortisation"].append(dict(first))
    with pytest.raises(Refusal, match=r"^METHODOLOGY_INPUT_INVALID$"):
        cash_flow_forecast(request)


def test_the_reconciliation_tolerance_is_bounded() -> None:
    """F62: a tolerance wide enough to pass any residual switches the one
    arithmetic check off."""
    request = forecast_request()
    request["tolerance"] = str(cash_flow.MAX_TOLERANCE)
    assert cash_flow_forecast(request)["status"] in ("complete", "incomplete")
    for outside in (str(cash_flow.MAX_TOLERANCE + Decimal("0.000001")), "-0.5"):
        request["tolerance"] = outside
        with pytest.raises(Refusal, match=r"^METHODOLOGY_INPUT_INVALID$"):
            cash_flow_forecast(request)


def test_the_reconciliation_tolerance_is_relative_to_the_opening_balances() -> None:
    """N20 (FP-23): a tolerance capped only at `MAX_TOLERANCE`, in the request's
    own unit, passed a 999m residual on 1,100m of openings. Each residual's is
    now never wider than one part in a thousand of its own opening balance --
    debt of the opening debt, cash of the opening cash (N10) -- nor than
    `MAX_TOLERANCE`; a stated tolerance tighter than that is the one applied,
    and a stated one outside the absolute bound is still refused (F62)."""
    request = forecast_request()  # openings: debt 700 + 300, cash 100
    request["tolerance"] = str(cash_flow.MAX_TOLERANCE)
    request["drivers"][0]["stated_closing_cash"] = "1125"  # residual 999
    row = cash_flow_forecast(request)["rows"][0]
    assert row["unavailable_reason"] == "RESIDUAL_UNRECONCILED"
    # One part in a thousand of the cash's 100 is 0.1, of the debt's 1,000 is 1.
    request["tolerance"] = "5"
    for stated, reason in (("126.1", None), ("126.100001", "RESIDUAL_UNRECONCILED")):
        request["drivers"][0]["stated_closing_cash"] = stated
        assert cash_flow_forecast(request)["rows"][0]["unavailable_reason"] == reason
    request["drivers"][0]["stated_closing_cash"] = "126"
    for stated, reason in (("1001", None), ("1001.000001", "RESIDUAL_UNRECONCILED")):
        request["drivers"][0]["stated_closing_debt"] = stated
        assert cash_flow_forecast(request)["rows"][0]["unavailable_reason"] == reason
    # A stated tolerance tighter than the debt's share is the one applied.
    request["tolerance"] = "0.5"
    for stated, reason in (("1000.5", None), ("1000.500001", "RESIDUAL_UNRECONCILED")):
        request["drivers"][0]["stated_closing_debt"] = stated
        assert cash_flow_forecast(request)["rows"][0]["unavailable_reason"] == reason
    # A negative opening counts by its size (debt -400: 0.4; cash -100: 0.1).
    signed = forecast_request()
    signed["opening"]["debt_by_facility"][0]["amount"] = "-700"
    signed["opening"]["cash"] = "-100"
    signed["tolerance"] = "5"
    signed["drivers"][0].update(
        stated_closing_debt="-399.6", stated_closing_cash="-73.9"
    )
    assert cash_flow_forecast(signed)["rows"][0]["unavailable_reason"] is None
    for moved in (
        {"stated_closing_debt": "-399.599999"},
        {"stated_closing_cash": "-73.899999"},
    ):
        wrong = deepcopy(signed)
        wrong["drivers"][0].update(moved)
        row = cash_flow_forecast(wrong)["rows"][0]
        assert row["unavailable_reason"] == "RESIDUAL_UNRECONCILED"
    # Nothing opened, nothing to be approximate about: the close must be exact.
    empty = forecast_request()
    empty["opening"]["debt_by_facility"] = [
        {"facility_id": "TERM", "amount": "0"},
        {"facility_id": "BOND", "amount": "0"},
    ]
    empty["opening"]["cash"] = "0"
    empty["drivers"][0].update(stated_closing_debt="0", stated_closing_cash="26")
    assert cash_flow_forecast(empty)["rows"][0]["unavailable_reason"] is None
    empty["drivers"][0]["stated_closing_cash"] = "26.000001"
    row = cash_flow_forecast(empty)["rows"][0]
    assert row["unavailable_reason"] == "RESIDUAL_UNRECONCILED"


@pytest.mark.parametrize(
    ("debt", "cash", "residual"),
    [
        pytest.param("100000", "10", "cash", id="small-cash-beside-large-debt"),
        pytest.param("10", "100000", "debt", id="small-debt-beside-large-cash"),
    ],
)
def test_each_residual_is_held_to_its_own_opening_balance(
    debt: str, cash: str, residual: str
) -> None:
    """N10: D44's tolerance was one number for both residuals, one part in a
    thousand of the two balances together, so with debt 100,000 and cash 10 a
    cash residual of 90 -- nine times the cash it opened with -- reconciled.
    Each residual now answers to its own balance: 0.01 for that cash, 100 for
    that debt, and the same the other way round."""
    request = forecast_request()
    request["periods"] = request["periods"][:1]
    request["drivers"] = request["drivers"][:1]
    request["contractual"]["amortisation"] = []
    request["opening"]["debt_by_facility"] = [{"facility_id": "TERM", "amount": debt}]
    request["opening"]["cash"] = cash
    request["tolerance"] = "1000"
    first = cash_flow_forecast(request)["rows"][0]
    driver = request["drivers"][0]
    driver["stated_closing_debt"] = first["debt"]["closing"]
    driver["stated_closing_cash"] = first["cash"]["closing"]
    assert cash_flow_forecast(request)["rows"][0]["unavailable_reason"] is None
    small = Decimal(debt if residual == "debt" else cash) * cash_flow.RELATIVE_TOLERANCE
    large = Decimal(cash if residual == "debt" else debt) * cash_flow.RELATIVE_TOLERANCE
    field = f"stated_closing_{residual}"
    chain = Decimal(first[residual]["closing"])
    for off, reason in (
        (small, None),
        (small + Decimal("0.000001"), "RESIDUAL_UNRECONCILED"),
        (Decimal(90), "RESIDUAL_UNRECONCILED"),
        (large, "RESIDUAL_UNRECONCILED"),
    ):
        moved = deepcopy(request)
        moved["drivers"][0][field] = format(chain + off, "f")
        row = cash_flow_forecast(moved)["rows"][0]
        assert row["unavailable_reason"] == reason, (off, row[f"residual_{residual}"])


def test_each_period_is_held_to_its_own_opening_balances() -> None:
    """N75: the tolerance was fixed from the chain's first openings, so once a
    year repaid 99,990 of 100,000 of debt the next year's stated debt of 110
    against the chain's 10 (and cash of 108 against 8) reconciled, and leverage
    read 2x on the computed debt where the stated one implies 22x. Each period
    now answers to the balances it opened with."""
    request = forecast_request()
    request["opening"]["debt_by_facility"] = [
        {"facility_id": "TERM", "amount": "100000"}
    ]
    request["opening"]["cash"] = "100000"
    request["tolerance"] = "1000"
    request["contractual"]["amortisation"] = []
    request["periods"] = request["periods"][:2]
    first, second = request["drivers"][:2]
    request["drivers"] = [first, second]
    for driver in (first, second):
        for name in cash_flow._MOVEMENTS:
            if name not in ("revenue", "ebitda"):
                driver[name] = "0"
    first["optional_repayment"] = "99990"
    first["stated_closing_debt"] = "10"
    first["stated_closing_cash"] = "10"
    second["stated_closing_debt"] = "10"
    second["stated_closing_cash"] = "10"
    result = cash_flow_forecast(request)
    assert [row["unavailable_reason"] for row in result["rows"]] == [None, None]
    for field, stated in (
        ("stated_closing_debt", "110"),
        ("stated_closing_cash", "110"),
    ):
        moved = deepcopy(request)
        moved["drivers"][1][field] = stated
        rows = cash_flow_forecast(moved)["rows"]
        assert rows[0]["unavailable_reason"] is None
        assert rows[1]["unavailable_reason"] == "RESIDUAL_UNRECONCILED", field


def test_a_case_s_periods_run_in_fiscal_year_order_after_the_opening() -> None:
    """FP-37: the calculator chains a case's periods in the order given, so a
    period out of order opened from the wrong closing and only an independent
    stated close could catch it; and `opening.as_of_period_id` was validated
    and then ignored. A case's fiscal years may not fall -- quarters share
    one -- a fiscal year is a year number, and the opening's period is none of
    the forecast's own."""
    request = forecast_request()
    request["periods"] = [request["periods"][i] for i in (1, 0, 2, 3)]
    refused(request)
    for fiscal_year in ("FY2026", "26", "2026.0", ""):
        request = forecast_request()
        request["periods"][0]["fiscal_year"] = fiscal_year
        refused(request)
    request = forecast_request()
    request["opening"]["as_of_period_id"] = "FY26"
    refused(request)
    # Interleaved cases keep each case's own order, and quarters one year.
    interleaved = forecast_request()
    interleaved["periods"] = [interleaved["periods"][i] for i in (2, 0, 3, 1)]
    assert cash_flow_forecast(interleaved)["status"] == "complete"
    assert cash_flow_forecast(forecast_request(quarterly=True))["status"] == "complete"


def test_cfo_is_named_as_before_interest_and_taxes_where_the_model_reads() -> None:
    """FP-39: `fcf = cfo - capex - cash_interest - cash_taxes` deducts interest
    and taxes itself, so a reported CFO that already did would count both
    twice; CP-CF's SKILL.md and the calculator it is delivered say so."""
    from caos.methodology.host import verified_host_bytes

    for name in ("SKILL.md", "scripts/cash_flow.py"):
        text = " ".join(verified_host_bytes(name).decode().split())
        assert "before cash interest and cash taxes" in text, name


def test_the_brief_holds_each_close_to_its_own_opening_balance() -> None:
    """N10: CP-CF's brief states the per-residual rule the calculator applies,
    so a model is not told one share of both balances together."""
    from caos.methodology.host import verified_host_bytes

    brief = " ".join(verified_host_bytes("SKILL.md").decode().split())
    assert (
        "each stated close reconciles within the tolerance, never wider than one"
        " part in a thousand of its own opening balance: debt of the opening"
        " debt, cash of the opening cash" in brief
    )


def test_explicit_cash_and_carrying_movements_are_distinct() -> None:
    request = forecast_request()
    request["periods"] = request["periods"][:1]
    request["drivers"] = request["drivers"][:1]
    request["contractual"]["amortisation"] = request["contractual"]["amortisation"][:1]
    request["drivers"][0].update(
        net_equity_issue_repay="5",
        other_investing_financing="-24",
        restricted_cash_change="15",
        carrying_value_change="26",
        stated_closing_cash="92",
        stated_closing_debt="1026",
    )
    result = cash_flow_forecast(request)
    assert result["status"] == "complete"
    row = result["rows"][0]
    assert row["cash"]["closing"] == "92.000000"
    assert row["debt"]["closing"] == "1026.000000"
    assert row["fcf"] == "45.000000"
    assert row["financing"]["financing_investing"] == "-15.000000"


@pytest.mark.parametrize(
    ("field", "location", "cash_closes", "debt_closes"),
    [
        ("net_equity_issue_repay", "financing", ("133", "119"), ("1000", "1000")),
        ("other_investing_financing", "financing", ("133", "119"), ("1000", "1000")),
        ("restricted_cash_change", "cash", ("119", "133"), ("1000", "1000")),
        ("carrying_value_change", "debt", ("126", "126"), ("1007", "993")),
    ],
)
@pytest.mark.parametrize("negative", [False, True])
def test_optional_movements_have_independent_signed_effects(
    field: str,
    location: str,
    cash_closes: tuple[str, str],
    debt_closes: tuple[str, str],
    negative: bool,
) -> None:
    request = forecast_request()
    cash = cash_closes[int(negative)]
    debt = debt_closes[int(negative)]
    value = "-7" if negative else "7"
    request["drivers"][0].update(
        {field: value, "stated_closing_cash": cash, "stated_closing_debt": debt}
    )
    row = cash_flow_forecast(request)["rows"][0]
    assert row["unavailable_reason"] is None
    assert row["cash"]["closing"] == row["cash"]["accessible"] == cash + ".000000"
    assert row["debt"]["closing"] == debt + ".000000"
    assert row[location][field] == value + ".000000"
    assert row["fcf"] == "45.000000"
    assert row["financing"]["financing_investing"] == "-15.000000"


@pytest.mark.parametrize(
    ("field", "location"),
    [
        ("net_equity_issue_repay", "financing"),
        ("other_investing_financing", "financing"),
        ("restricted_cash_change", "cash"),
        ("carrying_value_change", "debt"),
    ],
)
def test_optional_zero_is_visible_and_absence_preserves_legacy_shape(
    field: str, location: str
) -> None:
    request = forecast_request()
    legacy = cash_flow_forecast(request)
    assert all(field not in row[location] for row in legacy["rows"])
    request["drivers"][0][field] = "-0.000000"
    explicit = cash_flow_forecast(request)
    assert explicit["rows"][0][location].pop(field) == "0.000000"
    assert explicit == legacy


@pytest.mark.parametrize(
    "field",
    [
        "net_equity_issue_repay",
        "other_investing_financing",
        "restricted_cash_change",
        "carrying_value_change",
        "segment_revenue",
    ],
)
@pytest.mark.parametrize(
    "value",
    [
        None,
        True,
        False,
        1,
        1.5,
        Decimal("1"),
        "NaN",
        "Infinity",
        "-Infinity",
        "1e2",
        "+1",
        "01",
        "1\n",
        "1" * 10000,
        "0.1234567",
        [],
        {},
    ],
)
def test_optional_scalar_grammar_refuses_hidden_bad_values(
    field: str, value: object
) -> None:
    request = forecast_request()
    request["drivers"][-1]["status"] = "DRAFT"
    request["drivers"][-1][field] = (
        {"SEG": value} if field == "segment_revenue" else value
    )
    refused(request)


@pytest.mark.parametrize("count", [1, 40])
def test_segment_revenue_is_exact_signed_and_canonical(count: int) -> None:
    request = forecast_request()
    segments = {f"SEG_{index}": "0" for index in range(count)}
    segments["SEG_0"] = "500"
    if count > 1:
        segments["SEG_0"] = "512.125001"
        segments["SEG_1"] = "-12.125001"
    request["drivers"][0]["segment_revenue"] = segments
    result = cash_flow_forecast(request)
    assert result["status"] == "complete"
    expected = {key: "0.000000" for key in segments}
    expected["SEG_0"] = "500.000000" if count == 1 else "512.125001"
    if count > 1:
        expected["SEG_1"] = "-12.125001"
    assert result["rows"][0]["operating"]["segment_revenue"] == expected
    assert "segment_revenue" not in result["rows"][1]["operating"]


@pytest.mark.parametrize("status", ["READY", "DRAFT"])
@pytest.mark.parametrize("amount", ["499.999999", "500.000001"])
def test_segment_sum_requires_exact_equality_even_when_unready(
    status: str, amount: str
) -> None:
    request = forecast_request()
    request["tolerance"] = "1000"
    request["drivers"][0].update(status=status, segment_revenue={"SEG": amount})
    refused(request)


@pytest.mark.parametrize(
    "segments",
    [
        None,
        [],
        "500",
        {},
        {f"S{i}": "0" for i in range(41)},
        {"SEG": []},
        {"SEG": {"nested": "500"}},
        {"SEG": "NaN"},
    ],
)
@pytest.mark.parametrize("status", ["READY", "DRAFT"])
def test_every_segment_map_is_bounded_before_any_numeric_work(
    monkeypatch: pytest.MonkeyPatch,
    segments: object,
    status: str,
) -> None:
    request = forecast_request()
    request["drivers"][0]["segment_revenue"] = {"SAFE": "500"}
    request["drivers"][-1].update(status=status, segment_revenue=segments)

    def no_decimal(*args: object, **kwargs: object) -> None:
        pytest.fail("a malformed later segment map reached Decimal work")

    monkeypatch.setattr(cash_flow, "_decimal", no_decimal)
    monkeypatch.setattr(cash_flow, "Decimal", no_decimal)
    refused(request)


@pytest.mark.parametrize(
    "key",
    [
        None,
        1,
        "",
        "a" * 65,
        "a/b",
        "a~b",
        "a b",
        "a\n",
        "a\x00",
        "a\u202e",
        "é",
        "e\u0301",
        "_SEG",
        "-SEG",
    ],
)
def test_segment_keys_refuse_unsafe_or_normalized_aliases_before_numbers(
    monkeypatch: pytest.MonkeyPatch, key: object
) -> None:
    request = forecast_request()
    request["drivers"][-1]["segment_revenue"] = {key: "500"}

    def no_decimal(*args: object, **kwargs: object) -> None:
        pytest.fail("an unsafe segment identifier reached numeric work")

    monkeypatch.setattr(cash_flow, "_decimal", no_decimal)
    refused(request)


def test_segment_identifier_boundary_and_missing_required_revenue() -> None:
    request = forecast_request()
    request["drivers"][0]["segment_revenue"] = {"A" + "a_.-0" * 12 + "end": "500"}
    assert cash_flow_forecast(request)["status"] == "complete"
    del request["drivers"][0]["revenue"]
    assert (
        cash_flow_forecast(request)["rows"][0]["unavailable_reason"]
        == "DRIVER_FIELD_MISSING"
    )
    request["drivers"][0]["segment_revenue"]["BAD"] = "1e2"
    refused(request)


def test_optional_movements_chain_separately_in_interleaved_cases() -> None:
    request = forecast_request()
    # BASE: +5 equity -24 otherFI -15 restricted; next year +10 release.
    # DOWN: -7 equity -3 carrying; next year +9 otherFI +4 carrying.
    updates = [
        dict(
            net_equity_issue_repay="5",
            other_investing_financing="-24",
            restricted_cash_change="15",
            carrying_value_change="26",
            stated_closing_cash="92",
            stated_closing_debt="1026",
        ),
        dict(
            restricted_cash_change="-10",
            stated_closing_cash="128",
            stated_closing_debt="1026",
        ),
        dict(
            net_equity_issue_repay="-7",
            carrying_value_change="-3",
            stated_closing_cash="79",
            stated_closing_debt="997",
        ),
        dict(
            other_investing_financing="9",
            carrying_value_change="4",
            stated_closing_cash="74",
            stated_closing_debt="1001",
        ),
    ]
    for driver, update in zip(request["drivers"], updates, strict=True):
        driver.update(update)
    request["periods"] = [request["periods"][i] for i in (0, 2, 1, 3)]
    result = cash_flow_forecast(request)
    assert result["status"] == "complete"
    assert [
        (row["debt"]["closing"], row["cash"]["closing"]) for row in result["rows"]
    ] == [
        ("1026.000000", "92.000000"),
        ("997.000000", "79.000000"),
        ("1026.000000", "128.000000"),
        ("1001.000000", "74.000000"),
    ]
    request["drivers"][0]["stated_closing_cash"] = "93"
    assert [
        row["unavailable_reason"] for row in cash_flow_forecast(request)["rows"]
    ] == ["RESIDUAL_UNRECONCILED", None, "PRIOR_PERIOD_UNAVAILABLE", None]


def test_optional_fields_remain_exact_under_hostile_decimal_context() -> None:
    request = forecast_request()
    request["drivers"][0].update(
        net_equity_issue_repay="5",
        other_investing_financing="-24",
        restricted_cash_change="15",
        carrying_value_change="26",
        segment_revenue={
            "OPERATING": "999999999999999999.999999",
            "CORPORATE": "-999999999999999499.999999",
        },
        stated_closing_cash="92",
        stated_closing_debt="1026",
    )
    with localcontext() as context:
        context.prec = 2
        context.rounding = ROUND_DOWN
        context.Emax = 2
        context.Emin = -2
        for trap in context.traps:
            context.traps[trap] = True
        result = cash_flow_forecast(request)
    assert result["rows"][0]["unavailable_reason"] is None
    assert result["rows"][0]["cash"]["closing"] == "92.000000"
    assert result["rows"][0]["debt"]["closing"] == "1026.000000"
    assert (
        result["rows"][0]["operating"]["segment_revenue"]
        == request["drivers"][0]["segment_revenue"]
    )


@pytest.mark.parametrize("residual", ["debt", "cash"])
@pytest.mark.parametrize("sign", [1, -1])
@pytest.mark.parametrize(
    ("opening", "tolerance", "boundary"),
    [
        ("1000", "5", "1"),
        ("-1000", "5", "1"),
        ("1000", "0.5", "0.5"),
        ("10000000", "1000", "1000"),
        ("0", "1000", "0"),
    ],
)
def test_optional_movements_preserve_each_residual_cap_in_both_directions(
    residual: str,
    sign: int,
    opening: str,
    tolerance: str,
    boundary: str,
) -> None:
    request = forecast_request()
    request["opening"]["debt_by_facility"] = [
        {"facility_id": "TERM", "amount": opening}
    ]
    request["opening"]["cash"] = opening
    request["tolerance"] = tolerance
    # Debt's existing net movement is 0, cash's is +26; explicit effects +9/+7.
    debt = Decimal(opening) + 9
    cash = Decimal(opening) + 33
    request["drivers"][0].update(
        net_equity_issue_repay="7",
        carrying_value_change="9",
        stated_closing_debt=str(debt),
        stated_closing_cash=str(cash),
    )
    closing = debt if residual == "debt" else cash
    for delta, reason in [
        (Decimal(boundary), None),
        (Decimal(boundary) + Decimal("0.000001"), "RESIDUAL_UNRECONCILED"),
    ]:
        request["drivers"][0][f"stated_closing_{residual}"] = str(
            closing + sign * delta
        )
        assert cash_flow_forecast(request)["rows"][0]["unavailable_reason"] == reason


@pytest.mark.parametrize("field", list(cash_flow._MOVEMENTS))
def test_optional_fields_never_replace_a_missing_required_movement(field: str) -> None:
    request = forecast_request()
    request["drivers"][0].update(
        net_equity_issue_repay="0",
        other_investing_financing="0",
        restricted_cash_change="0",
        carrying_value_change="0",
        segment_revenue={"SEG": "500"},
    )
    del request["drivers"][0][field]
    assert (
        cash_flow_forecast(request)["rows"][0]["unavailable_reason"]
        == "DRIVER_FIELD_MISSING"
    )

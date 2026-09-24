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


@pytest.mark.parametrize(
    "ceiling", ["periods", "cases", "facilities", "amortisation", "work"]
)
def test_work_factor_refuses_before_any_numeric_is_parsed(
    monkeypatch: pytest.MonkeyPatch,
    ceiling: str,
) -> None:
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
    elif ceiling == "amortisation":
        request["contractual"]["amortisation"] = [{}] * 2001
    else:
        monkeypatch.setattr(cash_flow, "MAX_WORK", 1)

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

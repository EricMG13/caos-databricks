"""Selected aggregate principal has a dated, exact accepted CP-1 opening."""

from dataclasses import replace
from decimal import Decimal
from typing import Any

import pytest
from credit_model_fixture import example_registers
from forecast_fixtures import forecast_request

from caos.methodology.forecast_debt_service import validate_owned_debt_service
from caos.methodology.model_inputs import Cp1Registers
from caos.refusals import Refusal, RefusalCode


def debt_inputs() -> tuple[dict[str, Any], Cp1Registers]:
    regs = example_registers()
    periods = tuple(
        replace(
            p,
            accounting_basis="GAAP",
            entity_perimeter="Consolidated",
            component_period_ids=(),
        )
        for p in regs.periods
        if p.period_id in {"FY2025", "H1_2026"}
    )
    accounts = tuple(
        replace(
            a,
            value=Decimal("-98")
            if a.metric_id == "net_debt_issue_repay" and a.period_id == "H1_2026"
            else Decimal("887")
            if a.metric_id == "cash_and_equivalents"
            else a.value,
        )
        for a in regs.accounts
        if a.period_id in {"FY2025", "H1_2026"}
    )
    facilities = tuple(
        r
        for r in regs.facilities
        if r.period_id == "FY2025" and r.facility_id != "finl"
    )
    regs = replace(
        regs,
        periods=periods,
        accounts=accounts,
        facilities=facilities,
        segments=(),
        kpis=(),
        addbacks=(),
        pro_forma=(),
    )
    request = forecast_request()
    request["projection_basis"] = "OWNED_CASH_DEBT_SERVICE"
    request["opening"] = {
        "as_of_period_id": "FY2025",
        "cash": "887",
        "debt_by_facility": [
            {"facility_id": r.facility_id, "amount": str(r.carrying_value)}
            for r in facilities
        ],
    }
    request["actuals"] = {
        "debt_cash_movements": [
            {"period_id": "FY26", "historical_period_id": "H1_2026", "amount": "-98"}
        ]
    }
    aggregate = []
    for period in request["periods"]:
        year = period["fiscal_year"]
        period.update(start_date=f"{year}-01-01", end_date=f"{year}-12-31")
        aggregate.append(
            {
                "case": period["case"],
                "period_id": period["period_id"],
                "start_date": f"{year}-07-01" if year == "2026" else f"{year}-01-01",
                "end_date": f"{year}-12-31",
                "amount": "55" if year == "2026" else "114",
            }
        )
    request["contractual"] = {"amortisation": [], "aggregate_amortisation": aggregate}
    return request, regs


def test_validate_owned_debt_service_accepts_signed_ytd_and_future_schedule() -> None:
    request, regs = debt_inputs()
    validate_owned_debt_service(request, regs)


@pytest.mark.parametrize("amount", ["-983", "-43", "98"])
def test_validate_owned_debt_service_requires_actual_net_account(amount: str) -> None:
    request, regs = debt_inputs()
    request["actuals"]["debt_cash_movements"][0]["amount"] = amount
    with pytest.raises(Refusal) as caught:
        validate_owned_debt_service(request, regs)
    assert caught.value.code is RefusalCode.HANDOFF_MALFORMED


@pytest.mark.parametrize(
    "defect",
    [
        "type",
        "date",
        "days",
        "basis",
        "perimeter",
        "currency",
        "unit",
        "missing",
        "unavailable",
        "duplicate",
        "nonfinite",
        "cash",
        "debt",
        "asof",
        "aggregate",
        "actuals",
        "selector",
        "null",
        "reserved",
        "later",
    ],
)
def test_validate_owned_debt_service_refuses_owner_mismatch(defect: str) -> None:
    request, regs = debt_inputs()
    changes: dict[str, dict[str, Any]] = {
        "type": {"period_type": "QUARTER"},
        "date": {"start_date": "2026-02-01"},
        "days": {"day_count": 180},
        "basis": {"accounting_basis": "IFRS"},
        "perimeter": {"entity_perimeter": "Other"},
        "currency": {"currency": "EUR"},
        "unit": {"unit": "THOUSANDS"},
    }
    if defect in changes:
        regs = replace(
            regs,
            periods=tuple(
                replace(p, **changes[defect]) if p.period_id == "H1_2026" else p
                for p in regs.periods
            ),
        )
    elif defect in {"missing", "unavailable", "duplicate", "nonfinite"}:
        regs = _bad_account(regs, defect)
    else:
        _bad_request(request, defect)
    with pytest.raises(Refusal) as caught:
        validate_owned_debt_service(request, regs)
    assert caught.value.code is RefusalCode.HANDOFF_MALFORMED


def test_validate_owned_debt_service_legacy_needs_no_history() -> None:
    validate_owned_debt_service(
        forecast_request(), replace(example_registers(), periods=(), accounts=())
    )


def _bad_request(request: dict[str, Any], defect: str) -> None:
    if defect == "cash":
        request["opening"]["cash"] = "888"
    elif defect == "debt":
        request["opening"]["debt_by_facility"][0]["amount"] = "1"
    elif defect == "asof":
        request["opening"]["as_of_period_id"] = "PE2025"
    elif defect == "aggregate":
        request["contractual"]["aggregate_amortisation"][0]["start_date"] = "2026-07-02"
    elif defect == "actuals":
        del request["actuals"]
    elif defect == "selector":
        request["projection_basis"] = "OTHER"
    elif defect == "null":
        request["projection_basis"] = None
    elif defect == "reserved":
        del request["projection_basis"]
    elif defect == "later":
        request["actuals"]["debt_cash_movements"][0]["period_id"] = "FY27"


def _bad_account(regs: Cp1Registers, defect: str) -> Cp1Registers:
    account = next(
        a
        for a in regs.accounts
        if a.metric_id == "net_debt_issue_repay" and a.period_id == "H1_2026"
    )
    if defect == "duplicate":
        return replace(regs, accounts=(*regs.accounts, account))
    if defect == "missing":
        return replace(regs, accounts=tuple(a for a in regs.accounts if a != account))
    changed = (
        replace(account, calculation_status="NOT AVAILABLE")
        if defect == "unavailable"
        else replace(account, value=Decimal("NaN"))
    )
    return replace(
        regs, accounts=tuple(changed if a == account else a for a in regs.accounts)
    )


def test_validate_owned_debt_service_reads_same_date_balance_anchor() -> None:
    request, regs = debt_inputs()
    fy = regs.periods[0]
    pe = replace(
        fy,
        period_id="PE2025",
        period_type="PERIOD_END",
        start_date="2025-12-31",
        day_count=1,
    )
    regs = replace(
        regs,
        periods=(*regs.periods, pe),
        accounts=tuple(
            replace(a, period_id="PE2025")
            if a.period_id == "FY2025" and a.metric_id == "cash_and_equivalents"
            else a
            for a in regs.accounts
        ),
        facilities=tuple(replace(r, period_id="PE2025") for r in regs.facilities),
    )
    validate_owned_debt_service(request, regs)
    request["opening"]["as_of_period_id"] = "PE2025"
    with pytest.raises(Refusal) as caught:
        validate_owned_debt_service(request, regs)
    assert caught.value.code is RefusalCode.HANDOFF_MALFORMED


def test_validate_owned_debt_service_explicit_empty_actuals_is_wholly_future() -> None:
    request, regs = debt_inputs()
    request["actuals"]["debt_cash_movements"] = []
    for row in request["contractual"]["aggregate_amortisation"]:
        row["start_date"] = row["end_date"][:4] + "-01-01"
    validate_owned_debt_service(request, regs)


@pytest.mark.parametrize("reserved", ["actuals", "dates", "aggregate"])
def test_validate_owned_debt_service_refuses_each_reserved_structure_without_selector(
    reserved: str,
) -> None:
    request, regs = debt_inputs()
    legacy = forecast_request()
    if reserved == "actuals":
        legacy["actuals"] = request["actuals"]
    elif reserved == "dates":
        legacy["periods"][0]["start_date"] = "2026-01-01"
    else:
        legacy["contractual"]["aggregate_amortisation"] = []
    with pytest.raises(Refusal) as caught:
        validate_owned_debt_service(legacy, regs)
    assert caught.value.code is RefusalCode.HANDOFF_MALFORMED


@pytest.mark.parametrize("defect", ["hidden-nan", "anchor-days", "anchor-basis"])
def test_validate_owned_debt_service_refuses_hidden_history_faults(defect: str) -> None:
    request, regs = debt_inputs()
    if defect == "hidden-nan":
        regs = replace(
            regs,
            accounts=tuple(
                replace(a, value=Decimal("NaN")) if a.metric_id == "revenue" else a
                for a in regs.accounts
            ),
        )
    else:
        pe = replace(
            regs.periods[0],
            period_id="PE2025",
            period_type="PERIOD_END",
            start_date="2025-12-31",
            day_count=2 if defect == "anchor-days" else 1,
            accounting_basis="IFRS" if defect == "anchor-basis" else "GAAP",
        )
        regs = replace(
            regs,
            periods=(*regs.periods, pe),
            facilities=tuple(replace(r, period_id="PE2025") for r in regs.facilities),
        )
    with pytest.raises(Refusal) as caught:
        validate_owned_debt_service(request, regs)
    assert caught.value.code is RefusalCode.HANDOFF_MALFORMED

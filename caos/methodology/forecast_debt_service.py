"""Pure accepted CP-1 contract for owned aggregate cash debt service."""

from collections.abc import Mapping
from datetime import date, timedelta
from decimal import Decimal, localcontext
from typing import Any

from caos.calculators.credit_model._cells import CONTEXT, periods_at
from caos.calculators.credit_model.debt import facility_keys
from caos.calculators.credit_model.history import account_frame, historical_columns
from caos.calculators.credit_model.owner_inputs import facility_stack_at
from caos.calculators.credit_model.statements import statement_frame
from caos.methodology.forecast_segments import _check_request, _footing, _malformed
from caos.methodology.model_inputs import (
    MAX_DECIMALS,
    MAX_FIGURE,
    Cp1Registers,
    PeriodRow,
    fiscal_year_number,
    iso_date,
)


def _selected(request: Mapping[str, Any]) -> bool:
    """Legacy returns early only when the reserved new structure is absent."""
    if "projection_basis" in request:
        if request["projection_basis"] != "OWNED_CASH_DEBT_SERVICE":
            raise _malformed()
        return True
    contractual = request.get("contractual")
    periods = request.get("periods", [])
    if (
        "actuals" in request
        or (
            isinstance(contractual, Mapping) and "aggregate_amortisation" in contractual
        )
        or (
            isinstance(periods, list)
            and any(
                isinstance(row, Mapping) and {"start_date", "end_date"} & row.keys()
                for row in periods
            )
        )
    ):
        raise _malformed()
    return False


def _dated(period: PeriodRow) -> tuple[date, date]:
    start, end = iso_date(period.start_date), iso_date(period.end_date)
    if (
        start is None
        or end is None
        or start > end
        or period.day_count != (end - start).days + 1
        or fiscal_year_number(period.fiscal_year) != end.year
    ):
        raise _malformed()
    if period.period_type not in {"FY", "YTD", "QUARTER", "PERIOD_END", "LTM"}:
        raise _malformed()
    if period.period_type == "PERIOD_END" and start != end:
        raise _malformed()
    return start, end


def _same_footing(
    request: Mapping[str, Any],
    regs: Cp1Registers,
    period: PeriodRow,
    opening: PeriodRow,
) -> None:
    _footing(request, regs, period)
    if (
        not opening.accounting_basis
        or period.accounting_basis != opening.accounting_basis
    ):
        raise _malformed()


def _account(regs: Cp1Registers, period_id: str, metric: str) -> Decimal:
    row = None
    count = 0
    for candidate in regs.accounts:
        if candidate.period_id == period_id and candidate.metric_id == metric:
            row = candidate
            count += 1
    if count != 1 or row is None:
        raise _malformed()
    if (
        row.calculation_status not in {"VERIFIED", "CALCULATED", "ESTIMATED", "PROXY"}
        or row.value is None
        or not row.value.is_finite()
    ):
        raise _malformed()
    return row.value


def _opening(
    request: Mapping[str, Any], regs: Cp1Registers, periods: dict[str, PeriodRow]
) -> PeriodRow:
    as_of = request["opening"]["as_of_period_id"]
    opening = periods.get(as_of)
    first = date.fromisoformat(request["periods"][0]["start_date"])
    if opening is None or opening.period_type != "FY":
        raise _malformed()
    start, end = _dated(opening)
    if start != date(first.year - 1, 1, 1) or end != date(first.year - 1, 12, 31):
        raise _malformed()
    _same_footing(request, regs, opening, opening)
    columns = historical_columns(regs)
    matches = [
        column
        for column in columns
        if column.period_id == as_of and column.kind == "FY"
    ]
    if len(matches) != 1:
        raise _malformed()
    column = matches[0]
    amounts = _opening_stack(request, regs, opening)
    anchors = periods_at(regs, as_of, column.end_date)
    for row in regs.accounts:
        if row.period_id in anchors and row.metric_id == "cash_and_equivalents":
            _account(regs, row.period_id, row.metric_id)
    frame = statement_frame(account_frame(regs, (column,)), (column,), regs)[
        column.column_id
    ]
    cash, debt = frame["cash_closing"], frame["total_debt"]
    if (
        cash.value is None
        or not cash.value.is_finite()
        or cash.value != Decimal(request["opening"]["cash"])
        or debt.value != sum(amounts.values(), Decimal(0))
    ):
        raise _malformed()
    return opening


def _opening_stack(
    request: Mapping[str, Any], regs: Cp1Registers, opening: PeriodRow
) -> dict[str, Decimal]:
    as_of = opening.period_id
    anchors = periods_at(regs, as_of, opening.end_date)
    # Reject mismatched anchor rows instead of silently dropping their debt.
    for period in regs.periods:
        if period.period_id == as_of or period.end_date == opening.end_date:
            _dated(period)
            _same_footing(request, regs, period, opening)
    stack = facility_stack_at(regs, anchors)
    amounts = {}
    for key, row in stack.items():
        if "total_debt" in facility_keys(row, regs.currency):
            if row.carrying_value is None or not row.carrying_value.is_finite():
                raise _malformed()
            amounts[key] = row.carrying_value
    supplied = {
        row["facility_id"]: Decimal(row["amount"])
        for row in request["opening"]["debt_by_facility"]
    }
    if not amounts or supplied != amounts:
        raise _malformed()
    return amounts


def _actual_end(
    request: Mapping[str, Any],
    regs: Cp1Registers,
    periods: dict[str, PeriodRow],
    opening: PeriodRow,
) -> date | None:
    bridges = request["actuals"]["debt_cash_movements"]
    if not bridges:
        return None
    bridge = bridges[0]
    actual = periods.get(bridge["historical_period_id"])
    if actual is None or actual.period_type != "YTD":
        raise _malformed()
    start, end = _dated(actual)
    first = date.fromisoformat(request["periods"][0]["start_date"])
    if start != first or end >= date(first.year, 12, 31):
        raise _malformed()
    _same_footing(request, regs, actual, opening)
    if _account(regs, actual.period_id, "net_debt_issue_repay") != Decimal(
        bridge["amount"]
    ):
        raise _malformed()
    return end


def _finite_registers(regs: Cp1Registers) -> None:
    """Direct callers cannot send hidden NaN into historical frame arithmetic."""
    groups = (
        (r.value for r in regs.accounts),
        (r.value for r in regs.addbacks),
        (r.value for r in regs.kpis),
        (r.value for r in regs.pro_forma),
        (r.revenue for r in regs.segments),
        (r.carrying_value for r in regs.facilities),
    )
    if any(
        value is not None
        and (
            not value.is_finite()
            or value.copy_abs() >= MAX_FIGURE
            or -int(value.as_tuple().exponent) > MAX_DECIMALS
        )
        for values in groups
        for value in values
    ):
        raise _malformed()
    if len({(r.metric_id, r.period_id) for r in regs.accounts}) != len(regs.accounts):
        raise _malformed()


def validate_owned_debt_service(request: Mapping[str, Any], regs: Cp1Registers) -> None:
    """No-op for legacy; HANDOFF_MALFORMED for an invalid selected owner contract."""
    if not _selected(request):
        return
    _check_request(request)
    _finite_registers(regs)
    periods = {period.period_id: period for period in regs.periods}
    if len(periods) != len(regs.periods):
        raise _malformed()
    # Direct pure callers can construct rows without cp1_registers' uniqueness gate.
    if len({(r.facility_id, r.period_id) for r in regs.facilities}) != len(
        regs.facilities
    ):
        raise _malformed()
    with localcontext(CONTEXT):
        opening = _opening(request, regs, periods)
        actual_end = _actual_end(request, regs, periods, opening)
        first_period_id = request["periods"][0]["period_id"]
        calendar = {(p["case"], p["period_id"]): p for p in request["periods"]}
        for row in request["contractual"]["aggregate_amortisation"]:
            period = calendar[(row["case"], row["period_id"])]
            expected_start = (
                (actual_end + timedelta(days=1)).isoformat()
                if actual_end is not None and row["period_id"] == first_period_id
                else period["start_date"]
            )
            if (
                row["start_date"] != expected_start
                or row["end_date"] != period["end_date"]
            ):
                raise _malformed()

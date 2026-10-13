"""Pure CP-1 owner contract for explicitly forecast segment revenue."""

from collections.abc import Mapping
from decimal import Decimal, localcontext
from typing import Any

from caos.calculators.cash_flow import cash_flow_forecast
from caos.calculators.credit_model._cells import CONTEXT
from caos.calculators.credit_model.history import historical_columns
from caos.calculators.credit_model.owner_inputs import fiscal_year_note
from caos.methodology.model_inputs import Cp1Registers, PeriodRow, fiscal_year_number
from caos.refusals import Refusal, RefusalCode


def _malformed() -> Refusal:
    return Refusal(RefusalCode.HANDOFF_MALFORMED)


def _check_request(request: Mapping[str, Any]) -> None:
    """Reuse bounded pure parsing, translating only its input-contract refusal."""
    try:
        cash_flow_forecast(request)
    except Refusal as exc:
        if exc.code is RefusalCode.METHODOLOGY_INPUT_INVALID:
            raise _malformed() from None
        raise


def _footing(request: Mapping[str, Any], regs: Cp1Registers, period: PeriodRow) -> None:
    if (
        request["units"]["scale"] != "millions"
        or regs.unit != "MILLIONS"
        or period.unit != "MILLIONS"
        or request["units"]["currency"] != regs.currency
        or period.currency != regs.currency
        or period.entity_perimeter != request["perimeter"]
    ):
        raise _malformed()


def _base_period(regs: Cp1Registers) -> PeriodRow:
    columns = historical_columns(regs)
    latest = max(
        (column for column in reversed(columns) if column.kind == "FY"),
        key=lambda column: fiscal_year_number(column.fiscal_year) or 0,
        default=None,
    )
    periods = {period.period_id: period for period in regs.periods}
    if (
        latest is None
        or latest.period_id not in periods
        or len(periods) != len(regs.periods)
    ):
        raise _malformed()
    year = fiscal_year_number(latest.fiscal_year)
    if (
        year is None
        or sum(
            column.kind == "FY" and fiscal_year_number(column.fiscal_year) == year
            for column in columns
        )
        != 1
    ):
        raise _malformed()
    base = periods[latest.period_id]
    if fiscal_year_note(base) is not None:
        raise _malformed()
    return base


def _segment_types(request: Mapping[str, Any], regs: Cp1Registers) -> dict[str, str]:
    periods = {period.period_id: period for period in regs.periods}
    types: dict[str, str] = {}
    seen: set[tuple[str, str]] = set()
    for row in regs.segments:
        pair = (row.segment_id, row.period_id)
        if row.period_id not in periods or pair in seen:
            raise _malformed()
        seen.add(pair)
        _footing(request, regs, periods[row.period_id])
        if row.segment_type not in {"OPERATING_SEGMENT", "CORPORATE_ELIMINATION"}:
            raise _malformed()
        if types.setdefault(row.segment_id, row.segment_type) != row.segment_type:
            raise _malformed()
    return types


def _segment_base(request: Mapping[str, Any], regs: Cp1Registers) -> dict[str, Decimal]:
    base = _base_period(regs)
    _footing(request, regs, base)
    types = _segment_types(request, regs)
    values: dict[str, Decimal] = {}
    for row in regs.segments:
        if row.period_id == base.period_id:
            if row.revenue is None or not row.revenue.is_finite():
                raise _malformed()
            values[row.segment_id] = row.revenue
    if not values or values.keys() != types.keys():
        raise _malformed()
    return values


def validate_segment_revenue(request: Mapping[str, Any], regs: Cp1Registers) -> None:
    """Refuse invalid explicit segment forecasts with HANDOFF_MALFORMED."""
    drivers = request.get("drivers", [])
    if not isinstance(drivers, list) or not any(
        isinstance(row, dict) and "segment_revenue" in row for row in drivers
    ):
        return
    _check_request(request)
    base = _segment_base(request, regs)
    corporate = {
        row.segment_id
        for row in regs.segments
        if row.segment_type == "CORPORATE_ELIMINATION"
    }
    with localcontext(CONTEXT):
        for driver in drivers:
            if "segment_revenue" not in driver:
                continue
            values = {
                key: Decimal(amount)
                for key, amount in driver["segment_revenue"].items()
            }
            if values.keys() != base.keys() or any(
                values[key] != base[key] for key in corporate
            ):
                raise _malformed()
            if "revenue" not in driver or sum(values.values(), Decimal(0)) != Decimal(
                driver["revenue"]
            ):
                raise _malformed()

"""Bounded, deterministic forecast contract (decision §54).

Money is parsed only after collection ceilings, and computed under one explicit
Decimal context. Missing drivers and failed reconciliation remain unavailable.
The dictionary API is serialized as sorted, compact JSON by forecast_bytes.

A case's periods chain in the order given, which must be fiscal-year order,
from an opening that is none of them. `cfo` is operating cash flow before cash
interest and cash taxes: free cash flow is `cfo - capex - cash_interest -
cash_taxes`, so a reported CFO that already deducted interest and taxes paid
counts both twice (FP-39). A period reconciles when its stated closing debt and
cash are each within the tolerance of the chain's own, and each residual's
tolerance is never wider than one part in a thousand of its own opening
balance -- debt of the period's opening debt, cash of its opening cash -- nor
than `MAX_TOLERANCE` (N20, N10, N75).
"""

from __future__ import annotations

import json
import re
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from decimal import (
    ROUND_HALF_EVEN,
    Context,
    Decimal,
    DivisionByZero,
    InvalidOperation,
    Overflow,
    localcontext,
)
from typing import Any

from caos.boundary_text import BoundaryText
from caos.refusals import Refusal, RefusalCode

# The collection ceilings bound the whole of the work: at most 40 periods in
# each of 6 cases over 41 balances (FP-36).
MAX_FORECAST_PERIODS = 40
MAX_FORECAST_CASES = 6
MAX_FORECAST_FACILITIES = 40
MAX_FORECAST_SEGMENTS = 40
MAX_AMORTISATION = 2_000
# In the request's own unit: a residual past this is unreconciled, whatever the
# request says (F62).
MAX_TOLERANCE = Decimal("1000")
# And past this share of its own opening balance, debt by the opening debt and
# cash by the opening cash (N20, FP-23, N10): with scale in millions an
# absolute cap alone passed a 999m residual on a 1,000m balance, which switches
# the one arithmetic check off, and one share of both balances together passed
# a cash residual of 90 on an opening cash of 10 beside 100,000 of debt.
RELATIVE_TOLERANCE = Decimal("0.001")
# A fiscal year as the chain orders it: a year number.
_FISCAL_YEAR = re.compile(r"[1-9][0-9]{3}")
_NUMBER = re.compile(r"-?(0|[1-9][0-9]{0,17})(\.[0-9]{1,6})?")
_SEGMENT_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}")
_MOVEMENTS = (
    "revenue",
    "ebitda",
    "cfo",
    "capex",
    "acquisitions_disposals",
    "cash_interest",
    "cash_taxes",
    "distributions",
    "issuance",
    "optional_repayment",
    "pik",
    "capitalised_interest",
    "fx_perimeter",
)
_SIGNED = {"acquisitions_disposals", "fx_perimeter"}
_OPTIONAL_MOVEMENTS = (
    "net_equity_issue_repay",
    "other_investing_financing",
    "restricted_cash_change",
    "carrying_value_change",
)
_STATED = {"stated_closing_debt", "stated_closing_cash"}
_PAIR = {"case", "period_id"}
_OWNED_BASIS = "OWNED_CASH_DEBT_SERVICE"
_CALENDAR = {"start_date", "end_date"}


@dataclass(frozen=True, slots=True)
class _Inputs:
    periods: list[dict[str, Any]]
    drivers: dict[tuple[str, str], dict[str, Any]]
    # Future aggregate principal when selected; facility totals otherwise.
    repayments: dict[tuple[str, str], Decimal]
    opening: tuple[Decimal, Decimal]
    # The stated tolerance; each period caps it by its own openings (N75).
    tolerance: Decimal
    units: dict[str, Any]
    perimeter: str
    projection_basis: str | None
    # A shared first-period bridge, applied independently to each case once.
    actual_debt_cash: dict[str, Decimal]


def cash_flow_forecast(request: Mapping[str, Any]) -> dict[str, Any]:
    """Return one row per requested pair, preserving caller order."""
    _enforce_work_factor(request)
    # A fresh Context also isolates exponent limits, flags and traps.
    with localcontext(
        Context(
            prec=38,
            rounding=ROUND_HALF_EVEN,
            traps=[InvalidOperation, DivisionByZero, Overflow],
        )
    ):
        inputs = _parse(request)
        rows: list[dict[str, Any]] = []
        checks = []
        openings: dict[str, tuple[Decimal, Decimal]] = {}
        unavailable: set[str] = set()
        for period in inputs.periods:
            case = period["case"]
            opening = openings.get(case, inputs.opening)
            reason = _unavailable_reason(period, inputs, case in unavailable)
            if reason is not None:
                row = {**period, "unavailable_reason": reason}
            else:
                row, debt, cash = _project_period(period, inputs, opening)
                openings[case] = (debt, cash)
            if row["unavailable_reason"] is not None:
                unavailable.add(case)
            rows.append(row)
            checks.append(
                {
                    "check_id": f"residual:{case}:{period['period_id']}",
                    "outcome": "PASS" if row["unavailable_reason"] is None else "FAIL",
                    "reason": row["unavailable_reason"],
                }
            )
        result = {
            "status": "incomplete" if unavailable else "complete",
            "units": inputs.units,
            "perimeter": inputs.perimeter,
            "rows": rows,
            "checks": checks,
        }
        if inputs.projection_basis is not None:
            result["projection_basis"] = inputs.projection_basis
        return result


def forecast_bytes(request: Mapping[str, Any]) -> bytes:
    """Canonical UTF-8 forecast output for the host calculator boundary."""
    return json.dumps(
        cash_flow_forecast(request),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode()


def _object(
    value: object, required: set[str], optional: set[str] | None = None
) -> dict[str, Any]:
    if (
        not isinstance(value, dict)
        or not required <= value.keys()
        or value.keys() - required - (optional or set())
    ):
        raise Refusal(RefusalCode.METHODOLOGY_INPUT_INVALID)
    return value


def _rows(value: object, limit: int) -> list[dict[str, Any]]:
    if (
        not isinstance(value, list)
        or len(value) > limit
        or any(not isinstance(row, dict) for row in value)
    ):
        raise Refusal(RefusalCode.METHODOLOGY_INPUT_INVALID)
    return value


def _text(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise Refusal(RefusalCode.METHODOLOGY_INPUT_INVALID)
    try:
        return BoundaryText.of(value, limit=64).value
    except Refusal:
        raise Refusal(RefusalCode.METHODOLOGY_INPUT_INVALID) from None


def _pair(row: Mapping[str, Any]) -> tuple[str, str]:
    return _text(row.get("case")), _text(row.get("period_id"))


def _number_shape(value: object, *, signed: bool = False) -> str:
    """Validate the entire bounded money grammar without constructing Decimal."""
    if (
        not isinstance(value, str)
        or len(value) > 26
        or _NUMBER.fullmatch(value) is None
    ):
        raise Refusal(RefusalCode.METHODOLOGY_INPUT_INVALID)
    if not signed and value.startswith("-") and any(c in "123456789" for c in value):
        raise Refusal(RefusalCode.METHODOLOGY_INPUT_INVALID)
    return value


def _decimal(value: object, *, signed: bool = False) -> Decimal:
    return Decimal(_number_shape(value, signed=signed))


def _enforce_work_factor(request: Mapping[str, Any]) -> None:
    """Bound all collections and scalar shapes before any request Decimal work."""
    _object(
        request,
        {"opening", "periods", "drivers", "contractual", "units", "perimeter"},
        {"tolerance", "projection_basis", "actuals"},
    )
    selected = "projection_basis" in request
    if selected and request["projection_basis"] != _OWNED_BASIS:
        raise Refusal(RefusalCode.METHODOLOGY_INPUT_INVALID)
    if not selected and "actuals" in request:
        raise Refusal(RefusalCode.METHODOLOGY_INPUT_INVALID)
    periods = _rows(request["periods"], MAX_FORECAST_PERIODS * MAX_FORECAST_CASES)
    drivers = _rows(request["drivers"], len(periods))
    contractual = _object(
        request["contractual"],
        {"amortisation", "aggregate_amortisation"} if selected else {"amortisation"},
    )
    amortisation = _rows(contractual["amortisation"], MAX_AMORTISATION)
    _request_shapes(request, periods, drivers, amortisation, selected)
    counts = Counter(_text(row.get("case")) for row in periods)
    if (
        not counts
        or len(counts) > MAX_FORECAST_CASES
        or max(counts.values()) > MAX_FORECAST_PERIODS
    ):
        raise Refusal(RefusalCode.METHODOLOGY_INPUT_INVALID)
    if selected:
        _owned_shape(request, periods)


def _request_shapes(
    request: Mapping[str, Any],
    periods: list[dict[str, Any]],
    drivers: list[dict[str, Any]],
    amortisation: list[dict[str, Any]],
    selected: bool,
) -> None:
    opening = _object(
        request["opening"], {"cash", "as_of_period_id", "debt_by_facility"}
    )
    _text(opening["as_of_period_id"])
    _number_shape(opening["cash"], signed=True)
    for row in _rows(opening["debt_by_facility"], MAX_FORECAST_FACILITIES):
        _object(row, {"facility_id", "amount"})
        _text(row["facility_id"])
        _number_shape(row["amount"], signed=True)
    period_fields = _PAIR | {"fiscal_year", "days"} | (_CALENDAR if selected else set())
    for row in periods:
        _object(row, period_fields)
        _pair(row)
        _text(row["fiscal_year"])
        _number_shape(row["days"])
    for row in drivers:
        _driver_shape(row)
    amortisation_fields = _PAIR | {"facility_id", "amount"}
    for row in amortisation:
        _object(row, amortisation_fields)
        _pair(row)
        _text(row["facility_id"])
        _number_shape(row["amount"])
    units = _object(request["units"], {"currency", "scale"})
    _text(units["currency"])
    _text(units["scale"])
    _text(request["perimeter"])
    _number_shape(request.get("tolerance", "0.001"))


def _driver_shape(row: dict[str, Any]) -> None:
    _object(
        row,
        {*_PAIR, *_STATED, "status"},
        {*_MOVEMENTS, *_OPTIONAL_MOVEMENTS, "segment_revenue"},
    )
    _pair(row)
    _text(row["status"])
    for name in (*_MOVEMENTS, *_STATED, *_OPTIONAL_MOVEMENTS):
        if name in row:
            _number_shape(
                row[name],
                signed=name in _SIGNED
                or name in _STATED
                or name in _OPTIONAL_MOVEMENTS,
            )
    if "segment_revenue" in row:
        _segment_shape(row["segment_revenue"])


def _date(value: object) -> date:
    if not isinstance(value, str) or len(value) != 10:
        raise Refusal(RefusalCode.METHODOLOGY_INPUT_INVALID)
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        raise Refusal(RefusalCode.METHODOLOGY_INPUT_INVALID) from None
    if parsed.isoformat() != value:
        raise Refusal(RefusalCode.METHODOLOGY_INPUT_INVALID)
    return parsed


def _owned_calendars(
    periods: list[dict[str, Any]],
) -> dict[tuple[str, str], tuple[date, date]]:
    calendars = {}
    latest: dict[str, int] = {}
    first: tuple[str, int] | None = None
    for row in periods:
        pair = _pair(row)
        start, end = _date(row["start_date"]), _date(row["end_date"])
        if (
            start != date(start.year, 1, 1)
            or end != date(start.year, 12, 31)
            or row["fiscal_year"] != str(start.year)
            or row["days"] != str((end - start).days + 1)
            or pair in calendars
        ):
            raise Refusal(RefusalCode.METHODOLOGY_INPUT_INVALID)
        if pair[0] in latest:
            if start.year != latest[pair[0]] + 1:
                raise Refusal(RefusalCode.METHODOLOGY_INPUT_INVALID)
        else:
            identity = (pair[1], start.year)
            if first is not None and first != identity:
                raise Refusal(RefusalCode.METHODOLOGY_INPUT_INVALID)
            first = identity
        latest[pair[0]] = start.year
        calendars[pair] = (start, end)
    return calendars


def _owned_shape(request: Mapping[str, Any], periods: list[dict[str, Any]]) -> None:
    contractual = request["contractual"]
    if contractual["amortisation"]:
        raise Refusal(RefusalCode.METHODOLOGY_INPUT_INVALID)
    actuals = _object(request.get("actuals"), {"debt_cash_movements"})
    bridges = _rows(actuals["debt_cash_movements"], 1)
    first_period = _pair(periods[0])[1]
    for row in bridges:
        _object(row, {"period_id", "historical_period_id", "amount"})
        if _text(row["period_id"]) != first_period:
            raise Refusal(RefusalCode.METHODOLOGY_INPUT_INVALID)
        _text(row["historical_period_id"])
        _number_shape(row["amount"], signed=True)
    calendars = _owned_calendars(periods)
    aggregate_rows = _rows(contractual["aggregate_amortisation"], len(periods))
    _aggregate_shape(aggregate_rows, calendars, first_period, bool(bridges))


def _aggregate_shape(
    rows: list[dict[str, Any]],
    calendars: dict[tuple[str, str], tuple[date, date]],
    first_period: str,
    has_bridge: bool,
) -> None:
    seen: set[tuple[str, str]] = set()
    first_starts: set[date] = set()
    required = _PAIR | _CALENDAR | {"amount"}
    for row in rows:
        _object(row, required)
        pair = _pair(row)
        if pair not in calendars or pair in seen:
            raise Refusal(RefusalCode.METHODOLOGY_INPUT_INVALID)
        seen.add(pair)
        _number_shape(row["amount"])
        start, end = _date(row["start_date"]), _date(row["end_date"])
        year_start, year_end = calendars[pair]
        if not year_start <= start <= end == year_end:
            raise Refusal(RefusalCode.METHODOLOGY_INPUT_INVALID)
        if pair[1] == first_period and has_bridge:
            if start == year_start:
                raise Refusal(RefusalCode.METHODOLOGY_INPUT_INVALID)
            first_starts.add(start)
        elif start != year_start:
            raise Refusal(RefusalCode.METHODOLOGY_INPUT_INVALID)
    if seen != calendars.keys() or len(first_starts) > 1:
        raise Refusal(RefusalCode.METHODOLOGY_INPUT_INVALID)


def _segment_shape(value: object) -> None:
    """Refuse unbounded or unsafe maps before any request Decimal work."""
    if not isinstance(value, dict) or not 1 <= len(value) <= MAX_FORECAST_SEGMENTS:
        raise Refusal(RefusalCode.METHODOLOGY_INPUT_INVALID)
    for key, amount in value.items():
        if not isinstance(key, str) or _SEGMENT_ID.fullmatch(key) is None:
            raise Refusal(RefusalCode.METHODOLOGY_INPUT_INVALID)
        _number_shape(amount, signed=True)


def _parse(request: Mapping[str, Any]) -> _Inputs:
    units = _object(request["units"], {"currency", "scale"})
    if (
        not isinstance(units["currency"], str)
        or re.fullmatch("[A-Z]{3}", units["currency"]) is None
    ):
        raise Refusal(RefusalCode.METHODOLOGY_INPUT_INVALID)
    if not isinstance(units["scale"], str) or units["scale"] not in {
        "units",
        "thousands",
        "millions",
        "billions",
    }:
        raise Refusal(RefusalCode.METHODOLOGY_INPUT_INVALID)
    selected = "projection_basis" in request
    periods = _periods(request["periods"], selected=selected)
    pairs = {_pair(period) for period in periods}
    facilities = {}
    for row in request["opening"]["debt_by_facility"]:
        _object(row, {"facility_id", "amount"})
        facility = _text(row["facility_id"])
        if facility in facilities:
            raise Refusal(RefusalCode.METHODOLOGY_INPUT_INVALID)
        facilities[facility] = _decimal(row["amount"], signed=True)
    _chronological(periods, _text(request["opening"]["as_of_period_id"]))
    opening = (
        sum(facilities.values(), Decimal(0)),
        _decimal(request["opening"]["cash"], signed=True),
    )
    return _Inputs(
        periods=periods,
        drivers=_drivers(request["drivers"], pairs),
        repayments={
            _pair(row): _decimal(row["amount"])
            for row in request["contractual"]["aggregate_amortisation"]
        }
        if selected
        else _contractual(
            request["contractual"]["amortisation"], pairs, set(facilities)
        ),
        opening=opening,
        tolerance=_tolerance(request.get("tolerance", "0.001")),
        units=dict(units),
        perimeter=_text(request["perimeter"]),
        projection_basis=_OWNED_BASIS if selected else None,
        actual_debt_cash={
            _text(row["period_id"]): _decimal(row["amount"], signed=True)
            for row in request["actuals"]["debt_cash_movements"]
        }
        if selected
        else {},
    )


def _chronological(periods: list[dict[str, Any]], as_of: str) -> None:
    """Each case's periods in fiscal-year order, after an opening that is none
    of them (FP-37). The chain opens each period from the one before it in the
    request, so a period out of order opened from the wrong closing, and only
    an independent stated close could catch it. Quarters share a year."""
    latest: dict[str, int] = {}
    for period in periods:
        if _FISCAL_YEAR.fullmatch(period["fiscal_year"]) is None:
            raise Refusal(RefusalCode.METHODOLOGY_INPUT_INVALID)
        year = int(period["fiscal_year"])
        case = period["case"]
        if period["period_id"] == as_of or year < latest.get(case, year):
            raise Refusal(RefusalCode.METHODOLOGY_INPUT_INVALID)
        latest[case] = year


def _periods(
    rows: list[dict[str, Any]], *, selected: bool = False
) -> list[dict[str, Any]]:
    periods = []
    seen = set()
    required = _PAIR | {"fiscal_year", "days"} | (_CALENDAR if selected else set())
    for row in rows:
        _object(row, required)
        pair = _pair(row)
        case, period_id = pair
        if pair in seen:
            raise Refusal(RefusalCode.METHODOLOGY_INPUT_INVALID)
        seen.add(pair)
        days = _decimal(row["days"])
        if "." in row["days"] or not 1 <= days <= 366:
            raise Refusal(RefusalCode.METHODOLOGY_INPUT_INVALID)
        periods.append(
            {
                "case": case,
                "period_id": period_id,
                "fiscal_year": _text(row["fiscal_year"]),
                "days": row["days"],
            }
        )
    return periods


def _drivers(
    rows: list[dict[str, Any]], pairs: set[tuple[str, str]]
) -> dict[tuple[str, str], dict[str, Any]]:
    drivers = {}
    required = _PAIR | _STATED | {"status"}
    optional = set(_MOVEMENTS) | set(_OPTIONAL_MOVEMENTS) | {"segment_revenue"}
    names = (*_MOVEMENTS, *_STATED, *_OPTIONAL_MOVEMENTS)
    signed = _SIGNED | _STATED | set(_OPTIONAL_MOVEMENTS)
    for row in rows:
        _object(row, required, optional)
        pair = _pair(row)
        if pair not in pairs or pair in drivers:
            raise Refusal(RefusalCode.METHODOLOGY_INPUT_INVALID)
        driver: dict[str, Any] = {"status": _text(row["status"])}
        for name in names:
            if name in row:
                driver[name] = _decimal(
                    row[name],
                    signed=name in signed,
                )
        if "segment_revenue" in row:
            driver["segment_revenue"] = _segment_revenue(row["segment_revenue"], driver)
        drivers[pair] = driver
    return drivers


def _segment_revenue(
    segments: dict[str, str], driver: dict[str, Any]
) -> dict[str, Decimal]:
    amounts = {key: _decimal(value, signed=True) for key, value in segments.items()}
    # Missing required revenue still yields DRIVER_FIELD_MISSING, but every
    # present segment is parsed even for an incomplete or unready driver.
    if "revenue" in driver and sum(amounts.values(), Decimal(0)) != driver["revenue"]:
        raise Refusal(RefusalCode.METHODOLOGY_INPUT_INVALID)
    return amounts


def _contractual(
    rows: list[dict[str, Any]], pairs: set[tuple[str, str]], facilities: set[str]
) -> dict[tuple[str, str], Decimal]:
    totals: dict[tuple[str, str], Decimal] = {}
    seen = set()
    for row in rows:
        _object(row, _PAIR | {"facility_id", "amount"})
        pair, facility = _pair(row), _text(row["facility_id"])
        amount = _decimal(row["amount"])
        # A facility may state more than one instalment in a period and they
        # sum (the legacy rule, held by the cash_flow parity goldens); only a
        # row repeated exactly is refused.
        key = (*pair, facility, amount)
        if pair not in pairs or facility not in facilities or key in seen:
            raise Refusal(RefusalCode.METHODOLOGY_INPUT_INVALID)
        seen.add(key)
        totals[pair] = totals.get(pair, Decimal(0)) + amount
    return totals


def _tolerance(value: object) -> Decimal:
    """The reconciliation tolerance stated, or 0.001, within `MAX_TOLERANCE`
    or refused (F62). Each period narrows it per residual (`_project_period`)."""
    tolerance = _decimal(value)
    if tolerance < 0 or tolerance > MAX_TOLERANCE:
        raise Refusal(RefusalCode.METHODOLOGY_INPUT_INVALID)
    return tolerance


def _unavailable_reason(
    period: dict[str, Any], inputs: _Inputs, prior: bool
) -> str | None:
    if prior:
        return "PRIOR_PERIOD_UNAVAILABLE"
    driver = inputs.drivers.get(_pair(period))
    if driver is None:
        return "DRIVER_MISSING"
    if driver["status"] != "READY":
        return "DRIVER_NOT_READY"
    if not set(_MOVEMENTS) <= driver.keys():
        return "DRIVER_FIELD_MISSING"
    return None


def _amount(value: Decimal) -> str:
    return format((value if value else Decimal(0)).quantize(Decimal("0.000001")), "f")


def _ratio(numerator: Decimal, denominator: Decimal) -> dict[str, str | None]:
    if denominator <= 0:
        return {"value": None, "reason": "ZERO_OR_NEGATIVE_DENOMINATOR"}
    value = (numerator / denominator).quantize(Decimal("0.0001"))
    return {"value": format(value if value else abs(value), "f"), "reason": None}


def _project_period(
    period: dict[str, Any], inputs: _Inputs, opening: tuple[Decimal, Decimal]
) -> tuple[dict[str, Any], Decimal, Decimal]:
    moves = inputs.drivers[_pair(period)]
    repayment = inputs.repayments.get(_pair(period), Decimal(0))
    opening_debt, opening_cash = opening
    actual = inputs.actual_debt_cash.get(period["period_id"], Decimal(0))
    closing_debt = (
        opening_debt
        + moves["issuance"]
        + moves["pik"]
        + moves["capitalised_interest"]
        - repayment
        - moves["optional_repayment"]
        + moves["fx_perimeter"]
        + moves.get("carrying_value_change", Decimal(0))
    )
    financing = (
        moves["issuance"]
        - repayment
        - moves["optional_repayment"]
        - moves["acquisitions_disposals"]
    )
    if inputs.projection_basis is not None:
        closing_debt += actual
        financing += actual
    # `cfo` is before cash interest and cash taxes, deducted here (FP-39).
    fcf = moves["cfo"] - moves["capex"] - moves["cash_interest"] - moves["cash_taxes"]
    closing_cash = (
        opening_cash
        + fcf
        - moves["distributions"]
        + financing
        + moves.get("net_equity_issue_repay", Decimal(0))
        + moves.get("other_investing_financing", Decimal(0))
        - moves.get("restricted_cash_change", Decimal(0))
    )
    residual_debt = moves["stated_closing_debt"] - closing_debt
    residual_cash = moves["stated_closing_cash"] - closing_cash
    # Each residual is held to `RELATIVE_TOLERANCE` of its own balance as this
    # period opened -- debt of the opening debt, cash of the opening cash
    # (N20, FP-23, N10) -- never the chain's first: after a deleveraging year
    # the first year's debt would pass a residual ten times the debt left
    # (N75). A balance that opened at nothing reconciles exactly.
    debt_tolerance = min(inputs.tolerance, abs(opening_debt) * RELATIVE_TOLERANCE)
    cash_tolerance = min(inputs.tolerance, abs(opening_cash) * RELATIVE_TOLERANCE)
    reason = (
        "RESIDUAL_UNRECONCILED"
        if abs(residual_debt) > debt_tolerance or abs(residual_cash) > cash_tolerance
        else None
    )
    row = {
        **period,
        "operating": {
            **{name: _amount(moves[name]) for name in ("revenue", "ebitda", "cfo")},
            "margin": _ratio(moves["ebitda"], moves["revenue"]),
        },
        "investing": {
            name: _amount(moves[name]) for name in ("capex", "acquisitions_disposals")
        },
        "financing": {
            **{
                name: _amount(moves[name])
                for name in (
                    "cash_interest",
                    "cash_taxes",
                    "distributions",
                    "issuance",
                    "optional_repayment",
                )
            },
            "contractual_repayment": _amount(repayment),
            "financing_investing": _amount(financing),
        },
        "fcf": _amount(fcf),
        "debt": {
            "opening": _amount(opening_debt),
            "closing": _amount(closing_debt),
            **{
                name: _amount(moves[name])
                for name in ("pik", "capitalised_interest", "fx_perimeter")
            },
        },
        "cash": {
            "opening": _amount(opening_cash),
            "closing": _amount(closing_cash),
            "accessible": _amount(closing_cash),
        },
        "residual_debt": _amount(residual_debt),
        "residual_cash": _amount(residual_cash),
        "metrics": {
            "gross_leverage": _ratio(closing_debt, moves["ebitda"]),
            "net_leverage": _ratio(closing_debt - closing_cash, moves["ebitda"]),
            "interest_coverage": _ratio(moves["ebitda"], moves["cash_interest"]),
            "fcf_to_debt": _ratio(fcf, closing_debt),
        },
        "unavailable_reason": reason,
    }
    if inputs.projection_basis is not None:
        row["financing"]["actual_debt_cash_movement"] = _amount(actual)
    _optional_results(row, moves)
    return row, closing_debt, closing_cash


def _optional_results(row: dict[str, Any], moves: dict[str, Any]) -> None:
    """Expose explicit components without adding absent-field claims."""
    for name, location in (
        ("net_equity_issue_repay", "financing"),
        ("other_investing_financing", "financing"),
        ("restricted_cash_change", "cash"),
        ("carrying_value_change", "debt"),
    ):
        if name in moves:
            row[location][name] = _amount(moves[name])
    if "segment_revenue" in moves:
        row["operating"]["segment_revenue"] = {
            key: _amount(value) for key, value in moves["segment_revenue"].items()
        }

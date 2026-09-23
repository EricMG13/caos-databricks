"""Bounded, deterministic forecast contract (decision §54).

Money is parsed only after collection ceilings, and computed under one explicit
Decimal context. Missing drivers and failed reconciliation remain unavailable.
The dictionary API is serialized as sorted, compact JSON by forecast_bytes.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
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

MAX_FORECAST_PERIODS = 40
MAX_FORECAST_CASES = 6
MAX_FORECAST_FACILITIES = 40
MAX_WORK = 100_000
MAX_AMORTISATION = 2_000
# In the request's own unit: a residual past this is unreconciled, whatever the
# request says (F62).
MAX_TOLERANCE = Decimal("1000")
_NUMBER = re.compile(r"-?(0|[1-9][0-9]{0,17})(\.[0-9]{1,6})?")
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
_STATED = {"stated_closing_debt", "stated_closing_cash"}
_PAIR = {"case", "period_id"}


@dataclass(frozen=True, slots=True)
class _Inputs:
    periods: list[dict[str, Any]]
    drivers: dict[tuple[str, str], dict[str, Any]]
    repayments: dict[tuple[str, str], Decimal]
    opening: tuple[Decimal, Decimal]
    tolerance: Decimal
    units: dict[str, Any]
    perimeter: str


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
        previous: dict[str, dict[str, Any]] = {}
        unavailable: set[str] = set()
        for period in inputs.periods:
            case = period["case"]
            opening = openings.get(case, inputs.opening)
            reason = _unavailable_reason(period, inputs, case in unavailable)
            if reason is not None:
                row = {**period, "unavailable_reason": reason}
            else:
                if case in previous:
                    _check_chain(previous[case], opening)
                row, debt, cash = _project_period(period, inputs, opening)
                openings[case] = (debt, cash)
                previous[case] = row
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
        return {
            "status": "incomplete" if unavailable else "complete",
            "units": inputs.units,
            "perimeter": inputs.perimeter,
            "rows": rows,
            "checks": checks,
        }


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


def _decimal(value: object, *, signed: bool = False) -> Decimal:
    if (
        not isinstance(value, str)
        or len(value) > 26
        or _NUMBER.fullmatch(value) is None
    ):
        raise Refusal(RefusalCode.METHODOLOGY_INPUT_INVALID)
    amount = Decimal(value)
    if not signed and amount < 0:
        raise Refusal(RefusalCode.METHODOLOGY_INPUT_INVALID)
    return amount


def _enforce_work_factor(request: Mapping[str, Any]) -> None:
    """Bound every collection before parsing even the first days or amount."""
    _object(
        request,
        {"opening", "periods", "drivers", "contractual", "units", "perimeter"},
        {"tolerance"},
    )
    opening = _object(
        request["opening"], {"cash", "as_of_period_id", "debt_by_facility"}
    )
    facilities = _rows(opening["debt_by_facility"], MAX_FORECAST_FACILITIES)
    periods = _rows(request["periods"], MAX_FORECAST_PERIODS * MAX_FORECAST_CASES)
    _rows(request["drivers"], len(periods))
    contractual = _object(request["contractual"], {"amortisation"})
    _rows(contractual["amortisation"], MAX_AMORTISATION)
    counts = Counter(_text(row.get("case")) for row in periods)
    if (
        not counts
        or len(counts) > MAX_FORECAST_CASES
        or max(counts.values()) > MAX_FORECAST_PERIODS
    ):
        raise Refusal(RefusalCode.METHODOLOGY_INPUT_INVALID)
    if max(counts.values()) * len(counts) * (1 + len(facilities)) > MAX_WORK:
        raise Refusal(RefusalCode.METHODOLOGY_INPUT_INVALID)


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
    periods = _periods(request["periods"])
    pairs = {_pair(period) for period in periods}
    facilities = {}
    for row in request["opening"]["debt_by_facility"]:
        _object(row, {"facility_id", "amount"})
        facility = _text(row["facility_id"])
        if facility in facilities:
            raise Refusal(RefusalCode.METHODOLOGY_INPUT_INVALID)
        facilities[facility] = _decimal(row["amount"], signed=True)
    _text(request["opening"]["as_of_period_id"])
    return _Inputs(
        periods,
        _drivers(request["drivers"], pairs),
        _contractual(request["contractual"]["amortisation"], pairs, set(facilities)),
        (
            sum(facilities.values(), Decimal(0)),
            _decimal(request["opening"]["cash"], signed=True),
        ),
        _tolerance(request.get("tolerance", "0.001")),
        dict(units),
        _text(request["perimeter"]),
    )


def _periods(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    periods = []
    seen = set()
    for row in rows:
        _object(row, _PAIR | {"fiscal_year", "days"})
        case, period_id = _pair(row)
        if (case, period_id) in seen:
            raise Refusal(RefusalCode.METHODOLOGY_INPUT_INVALID)
        seen.add((case, period_id))
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
    for row in rows:
        _object(row, _PAIR | _STATED | {"status"}, set(_MOVEMENTS))
        pair = _pair(row)
        if pair not in pairs or pair in drivers:
            raise Refusal(RefusalCode.METHODOLOGY_INPUT_INVALID)
        driver: dict[str, Any] = {"status": _text(row["status"])}
        for name in (*_MOVEMENTS, *_STATED):
            if name in row:
                driver[name] = _decimal(
                    row[name], signed=name in _SIGNED or name in _STATED
                )
        drivers[pair] = driver
    return drivers


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
    """The reconciliation tolerance, within `MAX_TOLERANCE` (F62): a tolerance
    wide enough to pass any residual switches the one arithmetic check off."""
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


def _check_chain(previous: dict[str, Any], opening: tuple[Decimal, Decimal]) -> None:
    if opening != (
        Decimal(previous["debt"]["closing"]),
        Decimal(previous["cash"]["closing"]),
    ):
        raise Refusal(RefusalCode.FORECAST_CHAIN_BROKEN)


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
    debt = (
        opening_debt
        + moves["issuance"]
        + moves["pik"]
        + moves["capitalised_interest"]
        - repayment
        - moves["optional_repayment"]
        + moves["fx_perimeter"]
    )
    financing = (
        moves["issuance"]
        - repayment
        - moves["optional_repayment"]
        - moves["acquisitions_disposals"]
    )
    fcf = moves["cfo"] - moves["capex"] - moves["cash_interest"] - moves["cash_taxes"]
    cash = opening_cash + fcf - moves["distributions"] + financing
    residual_debt = moves["stated_closing_debt"] - debt
    residual_cash = moves["stated_closing_cash"] - cash
    reason = (
        "RESIDUAL_UNRECONCILED"
        if max(abs(residual_debt), abs(residual_cash)) > inputs.tolerance
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
            "closing": _amount(debt),
            **{
                name: _amount(moves[name])
                for name in ("pik", "capitalised_interest", "fx_perimeter")
            },
        },
        "cash": {
            "opening": _amount(opening_cash),
            "closing": _amount(cash),
            "accessible": _amount(cash),
        },
        "residual_debt": _amount(residual_debt),
        "residual_cash": _amount(residual_cash),
        "metrics": {
            "gross_leverage": _ratio(debt, moves["ebitda"]),
            "net_leverage": _ratio(debt - cash, moves["ebitda"]),
            "interest_coverage": _ratio(moves["ebitda"], moves["cash_interest"]),
            "fcf_to_debt": _ratio(fcf, debt),
        },
        "unavailable_reason": reason,
    }
    return row, debt, cash

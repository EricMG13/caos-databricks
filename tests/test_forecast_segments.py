"""Explicit forecast segments retain accepted CP-1 identity and perimeter."""

from dataclasses import replace
from decimal import Decimal, Inexact, localcontext
from typing import Any

import pytest
from credit_model_fixture import example_registers
from forecast_fixtures import forecast_request

from caos.methodology.forecast_segments import validate_segment_revenue
from caos.methodology.model_inputs import Cp1Registers
from caos.refusals import Refusal, RefusalCode


def segment_inputs() -> tuple[dict[str, Any], Cp1Registers]:
    regs = example_registers()
    regs = replace(
        regs,
        periods=tuple(
            replace(p, entity_perimeter="Consolidated", accounting_basis="GAAP")
            for p in regs.periods
        ),
    )
    request = forecast_request()
    segments = {
        r.segment_id: str(r.revenue) for r in regs.segments if r.period_id == "FY2025"
    }
    # Same-slot operating segments may move independently; corporate stays -60.
    segments.update(las_vegas="4300", regional="5800")
    for driver in request["drivers"]:
        driver.update(segment_revenue=dict(segments), revenue="11660")
    return request, regs


def test_validate_segment_revenue_accepts_exact_full_map_and_hostile_context() -> None:
    request, regs = segment_inputs()
    with localcontext() as context:
        context.prec = 2
        context.traps[Inexact] = True
        validate_segment_revenue(request, regs)


@pytest.mark.parametrize(
    "defect",
    [
        "unknown",
        "omitted",
        "corporate",
        "sum",
        "unsafe",
        "large",
        "null",
        "nonfinite",
        "base",
        "type",
        "period",
        "currency",
        "unit",
        "perimeter",
        "short",
        "duplicate",
    ],
)
def test_validate_segment_revenue_refuses_invalid_contract(defect: str) -> None:
    request, regs = segment_inputs()
    values = request["drivers"][0]["segment_revenue"]
    if defect == "unknown":
        values["alien"] = values.pop("digital")
    elif defect == "omitted":
        del values["digital"]
    elif defect == "corporate":
        values.update(corporate_eliminations="-59", digital="1276")
    elif defect == "sum":
        values["digital"] = "1277.000001"
    elif defect == "unsafe":
        values["bad/id"] = values.pop("digital")
    elif defect == "large":
        request["drivers"][0]["segment_revenue"] = {f"s{i}": "0" for i in range(41)}
    elif defect == "null":
        request["drivers"][0]["segment_revenue"] = None
    else:
        regs = _invalid_registers(regs, request, defect)
    with pytest.raises(Refusal) as caught:
        validate_segment_revenue(request, regs)
    assert caught.value.code is RefusalCode.HANDOFF_MALFORMED


def test_validate_segment_revenue_legacy_no_map_needs_no_history() -> None:
    validate_segment_revenue(
        forecast_request(), replace(example_registers(), periods=(), segments=())
    )


def _invalid_registers(
    regs: Cp1Registers, request: dict[str, Any], defect: str
) -> Cp1Registers:
    if defect == "nonfinite":
        regs = replace(
            regs,
            segments=tuple(
                replace(r, revenue=Decimal("NaN")) if r.period_id == "FY2025" else r
                for r in regs.segments
            ),
        )
    elif defect == "base":
        regs = replace(
            regs,
            segments=tuple(
                r
                for r in regs.segments
                if not (r.period_id == "FY2025" and r.segment_id == "digital")
            ),
        )
    elif defect == "type":
        regs = replace(
            regs,
            segments=(
                replace(regs.segments[0], segment_type="CORPORATE_ELIMINATION"),
                *regs.segments[1:],
            ),
        )
    elif defect == "period":
        regs = replace(
            regs,
            segments=(
                replace(regs.segments[0], period_id="unknown"),
                *regs.segments[1:],
            ),
        )
    elif defect == "currency":
        regs = replace(regs, currency="EUR")
    elif defect == "unit":
        regs = replace(regs, unit="THOUSANDS")
    elif defect == "perimeter":
        request["perimeter"] = "Other"
    elif defect == "short":
        regs = replace(
            regs,
            periods=tuple(
                replace(p, start_date="2025-02-01", day_count=334)
                if p.period_id == "FY2025"
                else p
                for p in regs.periods
            ),
        )
    elif defect == "duplicate":
        regs = replace(regs, segments=(*regs.segments, regs.segments[0]))
    return regs


def test_validate_segment_revenue_refuses_ambiguous_latest_fiscal_year() -> None:
    request, regs = segment_inputs()
    base = next(p for p in regs.periods if p.period_id == "FY2025")
    regs = replace(
        regs, periods=(replace(base, period_id="FY2025_OTHER"), *regs.periods)
    )
    with pytest.raises(Refusal) as caught:
        validate_segment_revenue(request, regs)
    assert caught.value.code is RefusalCode.HANDOFF_MALFORMED

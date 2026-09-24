"""Model values are projections of the accepted CP-CF pair, never UI calculations."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from caos.api.deps import (
    IDENTITY_FIRST,
    Blobs,
    Caller,
    CasePath,
    Methodology,
    RunQuery,
    Store,
    VisibleCase,
)
from caos.api.reads import analysis
from caos.api.reads.analysis import AnalysisQuery, read_analysis_without_tables
from caos.api.wire import (
    AnalysisBody,
    ModelBody,
    ModelDocument,
    ModelForecast,
    ModelPeriod,
    ModelUnit,
    ModelValue,
)
from caos.graph.route import MODEL_MODULE
from caos.methodology.forecast import forecast_projection
from caos.refusals import Refusal, RefusalCode
from caos.store import StoreConnection
from caos.store.source_sets import pinned_live_sources

# Analysis' own budget, which this route pays in full before adding to it,
# plus the live source pin. Derived rather than written out: a literal 150 was
# Analysis' ten-node forecast route, not the longest route a run can pin
# (ED-7). Measured on that route by test_model_http_actor_matrix_and_declared_io
# (194 before each proof's delivered blocks became one read instead of one per
# block). The blobs are Analysis' and nothing more.
PIN_IO = 1
IO_BUDGET = analysis.IO_BUDGET + PIN_IO
BLOB_BUDGET = analysis.BLOB_BUDGET
router = APIRouter()


@router.get(
    "/api/v1/cases/{case_id}/model",
    response_model=ModelDocument,
    dependencies=[IDENTITY_FIRST],
)
def read_model(  # noqa: PLR0913 -- authenticated case/run before dependencies
    actor: Caller,
    case_id: CasePath,
    run: RunQuery,
    standing: VisibleCase,
    conn: Store,
    blobs: Blobs,
    bundle: Methodology,
) -> ModelDocument:
    analysis = read_analysis_without_tables(
        AnalysisQuery(actor, case_id, run, standing, conn, blobs, bundle)
    )
    body = analysis.body
    forecast = accepted_forecast(conn, body)
    return ModelDocument(
        **analysis.model_dump(exclude={"body", "status", "observed_empty"}),
        body=ModelBody(
            # The run's own status and the node that ended it travel with the
            # forecast: "no accepted forecast" is a fact about now, and only
            # those two say whether one is still coming. They are Analysis'
            # own fields, unchanged -- this section derives, it does not judge.
            **body.model_dump(exclude={"handoffs", "pending"}),
            forecast=forecast,
            unavailable_reason="NO_ACCEPTED_FORECAST" if forecast is None else None,
        ),
        observed_empty=forecast is None,
        status="partial" if forecast is None else "complete",
    )


def accepted_forecast(
    conn: StoreConnection, body: AnalysisBody
) -> ModelForecast | None:
    """The run's accepted CP-CF projection, re-derived, or None when there is
    none. Shared with the Book, which reads the same accepted pair across
    several credits and must read it the one way this section does.
    """
    accepted = next((h for h in body.handoffs if h.module_id == MODEL_MODULE), None)
    if accepted is None or body.displayed_run_id is None:
        return None
    live = pinned_live_sources(conn, body.displayed_run_id)
    if any(
        c.document_sha256 not in live for h in body.handoffs for c in h.source_facts
    ):
        raise Refusal(RefusalCode.ARTIFACT_RECORD_MISMATCH)
    result = forecast_projection(accepted.model_analysis.encode("utf-8"))
    return ModelForecast(
        **accepted.model_dump(
            include={
                "route_node_id",
                "artifact_sha256",
                "record_sha256",
                "accepted_at",
                "qa_status",
                "limitation_flags",
                "validation_warnings",
            }
        ),
        **result["units"],
        perimeter=result["perimeter"],
        periods=[_period(row) for row in result["rows"]],
    )


# The two ratios the calculator computes as a fraction of a whole
# (`caos/calculators/cash_flow.py`): the margin, `_ratio(ebitda, revenue)`,
# and FCF over debt, `_ratio(fcf, debt)` -- each a share its reader states as
# a percentage, never a multiple (R24-12; N3 moved FCF/debt, which was labelled
# a multiple and read as "0.0450x"). Both stay unscaled: a Model reader
# performs no arithmetic on the server's decimal strings, so "a percentage"
# would mean host-side scaling, and the label says what the figure is. The
# Book shows the margin as a percent column moved on its digits (N60), which
# is the same figure under its own explicit unit. Every other `_ratio`-shaped
# leaf (gross and net leverage, interest coverage) is a multiple; a leaf that
# is not ratio-shaped -- came from `_amount`, not `_ratio` -- is money, in the
# forecast's own currency and scale.
_RATIO_UNITS = {
    "operating.margin": ModelUnit.RATIO,
    "metrics.fcf_to_debt": ModelUnit.RATIO,
}


def _unit(name: str, *, is_ratio: bool) -> ModelUnit:
    if not is_ratio:
        return ModelUnit.MONEY
    return _RATIO_UNITS.get(name, ModelUnit.MULTIPLE)


def _period(row: dict[str, Any]) -> ModelPeriod:
    """Flatten named result groups without arithmetic, preserving ratio
    reasons and each leaf's own dimension (R24-12)."""
    identity = {
        k: row[k]
        for k in ("case", "period_id", "fiscal_year", "days", "unavailable_reason")
    }
    values = []
    for group, data in row.items():
        if group in identity:
            continue
        for name, value in data.items() if isinstance(data, dict) else [("", data)]:
            is_ratio = isinstance(value, dict)
            full_name = f"{group}.{name}" if name else group
            values.append(
                ModelValue(
                    name=full_name,
                    unit=_unit(full_name, is_ratio=is_ratio),
                    value=value["value"] if is_ratio else value,
                    unavailable_reason=value["reason"] if is_ratio else None,
                )
            )
    return ModelPeriod(**identity, values=values)

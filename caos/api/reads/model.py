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
from caos.api.reads.analysis import read_analysis
from caos.api.wire import (
    AnalysisBody,
    ModelBody,
    ModelDocument,
    ModelForecast,
    ModelPeriod,
    ModelValue,
)
from caos.graph.route import MODEL_MODULE
from caos.methodology.forecast import forecast_projection
from caos.refusals import Refusal, RefusalCode
from caos.store import StoreConnection
from caos.store.source_sets import pinned_live_sources

# Analysis' ten-node forecast route, including CP-CF's four owner proofs,
# plus the live source pin. Moves with Analysis' own budget, which this route
# pays in full before adding to it. Measured by
# test_model_http_actor_matrix_and_declared_io; 194 before each proof's
# delivered blocks became one read instead of one per block.
IO_BUDGET = 150
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
    analysis = read_analysis(actor, case_id, run, standing, conn, blobs, bundle)
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


def _period(row: dict[str, Any]) -> ModelPeriod:
    """Flatten named result groups without arithmetic, preserving ratio reasons."""
    identity = {
        k: row[k]
        for k in ("case", "period_id", "fiscal_year", "days", "unavailable_reason")
    }
    values = []
    for group, data in row.items():
        if group in identity:
            continue
        for name, value in data.items() if isinstance(data, dict) else [("", data)]:
            values.append(
                ModelValue(
                    name=f"{group}.{name}" if name else group,
                    value=value["value"] if isinstance(value, dict) else value,
                    unavailable_reason=value["reason"]
                    if isinstance(value, dict)
                    else None,
                )
            )
    return ModelPeriod(**identity, values=values)

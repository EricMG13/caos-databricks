"""Model values are projections of the accepted CP-CF pair, never UI calculations."""

from __future__ import annotations

import re
import sys
from collections.abc import Mapping
from dataclasses import dataclass, replace
from decimal import Decimal
from typing import Any
from uuid import UUID

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
    MODEL_SOURCES_MAX,
    AnalysisBody,
    CitationView,
    HandoffView,
    ModelBody,
    ModelCellView,
    ModelColumnView,
    ModelDocument,
    ModelForecast,
    ModelLineView,
    ModelPeriod,
    ModelSourceView,
    ModelTermsView,
    ModelUnit,
    ModelValue,
)
from caos.calculators.credit_model.assemble import (
    CreditModel,
    ModelInputs,
    reconciliation_faults,
)
from caos.calculators.credit_model.frame import Cell, Column, SourceRef
from caos.calculators.credit_model.layout import Line
from caos.calculators.credit_model.projection import RateDeck
from caos.graph.route import MODEL_MODULE
from caos.methodology.bundle import Bundle
from caos.methodology.citation_markers import ESCAPE, MARKER
from caos.methodology.forecast import forecast_inputs, forecast_projection
from caos.methodology.model_inputs import (
    Cp1Registers,
    DivisionGrowth,
    SlotAllocation,
    cp1_registers,
    division_growth,
    slot_allocation,
)
from caos.methodology.tables import FIGURE_CHARS, HandoffTable, handoff_tables
from caos.methodology.vendor import cached_contract
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

_CP2G = "CP-2G"
PIK_LIMITATION = (
    "PIK notes carry only their cash coupon in the rate terms;"
    " PIK interest is not modelled"
)
RECONCILIATION = "reconciliation: "
CP1_UNREADABLE = "CP-1 model tables unreadable"
# A figure whose plain decimal runs past the wire's `DecimalText`.
TOO_LARGE = "figure too large to serve"
WITHHELD = "figures too large to serve were withheld"
GROWTH_UNAVAILABLE = "CP-2G growth drivers unavailable: business units held flat"
SOURCES_CUT = (
    f"Some cells name more than {MODEL_SOURCES_MAX} source rows;"
    f" each shows its first {MODEL_SOURCES_MAX}"
)
_PIK = re.compile(r"\bPIK\b", re.IGNORECASE)


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


def _accepted(body: AnalysisBody, module_id: str) -> HandoffView | None:
    return next((h for h in body.handoffs if h.module_id == module_id), None)


def _tables(bundle: Bundle, handoff: HandoffView | None) -> tuple[HandoffTable, ...]:
    """The handoff's tagged tables, read from its accepted Markdown by the
    bundle's reader; none for a handoff the route did not accept. Tables the
    reader refused or withheld past a bound are `HANDOFF_MALFORMED`, never
    silently none: the read states what it then goes without."""
    if handoff is None:
        return ()
    derived = handoff_tables(cached_contract(bundle), handoff.model_analysis)
    if derived.unavailable_reason is not None:
        raise Refusal(RefusalCode.HANDOFF_MALFORMED)
    return derived.tables


@dataclass(frozen=True, slots=True)
class _Where:
    """The case and run a log line names; never document text."""

    case_id: UUID
    run_id: UUID


def _unreadable(where: _Where, module: str, refusal: Refusal) -> None:
    """Log a handoff whose model tables the read could not use, by its code,
    and let the read go on without them; any refusal but
    `HANDOFF_MALFORMED` (the tables' own) is re-raised."""
    if refusal.code != RefusalCode.HANDOFF_MALFORMED:
        raise refusal
    print(
        f"model_tables_unreadable case={where.case_id} run={where.run_id}"
        f" module={module} code={refusal.code.value}",
        file=sys.stderr,
    )


def _cp1_inputs(
    bundle: Bundle, cp1: HandoffView
) -> tuple[Cp1Registers, tuple[SlotAllocation, ...]]:
    """CP-1's registers and forecast slots; `HANDOFF_MALFORMED` where its
    model tables do not parse, as an older run's, written before the CP-1
    fork, do not."""
    tables = _tables(bundle, cp1)
    return cp1_registers(tables), slot_allocation(tables)


def _growth(
    body: AnalysisBody, bundle: Bundle, where: _Where
) -> tuple[tuple[DivisionGrowth, ...], tuple[str, ...]]:
    """CP-2G's division growth drivers; none where the route did not accept
    CP-2G. Drivers unreadable or withheld past a bound are none too, logged
    and stated: the business units are then held flat, as the calculator
    holds a segment with no slot."""
    try:
        return division_growth(_tables(bundle, _accepted(body, _CP2G))), ()
    except Refusal as refusal:
        _unreadable(where, _CP2G, refusal)
        return (), (GROWTH_UNAVAILABLE,)


def _request(body: AnalysisBody) -> Mapping[str, Any] | None:
    """CP-CF's accepted request; None where the route did not accept CP-CF."""
    cpcf = _accepted(body, MODEL_MODULE)
    if cpcf is None:
        return None
    return forecast_inputs(cpcf.model_analysis.encode("utf-8"))[0]


def _citations(cp1: HandoffView) -> dict[int, CitationView]:
    """CP-1's host-verified citations by the marker its body cites each by."""
    return {fact.marker: fact for fact in cp1.source_facts if fact.marker is not None}


def _citation(
    source: SourceRef, citations: Mapping[int, CitationView]
) -> CitationView | None:
    """The CP-1 citation the cell's first `[C<n>]` names, else None."""
    found = MARKER.search(ESCAPE.sub(r"\1", source.cell_text))
    if found is None:
        return None
    first = found.group(1).split(",")[0].strip()
    return citations.get(int(first.removeprefix("C")))


def _decimal(value: Decimal | None) -> str | None:
    """Plain notation, never an exponent (invariant 7)."""
    return None if value is None else f"{value:f}"


def _cell(cell: Cell, citations: Mapping[int, CitationView]) -> ModelCellView:
    """The cell on the wire; one whose figure runs past `DecimalText` is
    withheld as `NOT_APPLICABLE`, noted, its sources kept."""
    if not _servable(cell):
        cell = Cell(None, "NOT_APPLICABLE", sources=cell.sources, note=TOO_LARGE)
    return ModelCellView(
        value=_decimal(cell.value),
        reason=cell.reason,
        basis=cell.basis,
        stated=_decimal(cell.stated),
        note=cell.note,
        sources=[
            ModelSourceView(
                source_id=source.source_id,
                source_locator=source.source_locator,
                citation=_citation(source, citations),
            )
            for source in cell.sources[:MODEL_SOURCES_MAX]
        ],
    )


def _column(column: Column) -> ModelColumnView:
    return ModelColumnView(
        column_id=column.column_id,
        kind=column.kind,
        label=column.label,
        period_id=column.period_id,
        fiscal_year=column.fiscal_year,
        end_date=column.end_date,
        days=column.days,
        case=column.case,
    )


def _line(line: Line, citations: Mapping[int, CitationView]) -> ModelLineView:
    terms = line.terms
    return ModelLineView(
        line_id=line.line_id,
        band=line.band,
        label=line.label,
        kind=line.kind,
        unit=line.unit,
        unit_label=line.unit_label,
        rank=line.rank,
        terms=None
        if terms is None
        else ModelTermsView(
            reference_rate=terms.reference_rate,
            spread_or_coupon=terms.spread_or_coupon,
            floor=terms.floor,
            maturity=terms.maturity,
            amortisation=terms.amortisation,
        ),
        cells=[_cell(cell, citations) for cell in line.cells],
    )


@dataclass(frozen=True, slots=True)
class _Served:
    """What the model read adds to Analysis' body: the inputs and the model
    of them, its open bridges, the accepted CP-CF record and the deck."""

    inputs: ModelInputs
    model: CreditModel
    faults: tuple[str, ...]
    forecast: ModelForecast | None
    deck: RateDeck | None
    noted: tuple[str, ...]  # the read's own: CP-2G growth unavailable
    unservable: int  # cells withheld as too large to serve


def _servable(cell: Cell) -> bool:
    """Whether the cell's figures fit the wire's `DecimalText` in plain
    notation."""
    return all(
        value is None or len(f"{value:f}") <= FIGURE_CHARS
        for value in (cell.value, cell.stated)
    )


def _served(where: _Where, served: _Served) -> _Served:
    """The model's open bridges and its cells too large to serve, each
    counted and logged by case and run, never with a figure."""
    model = served.model
    faults = reconciliation_faults(model)
    if faults:
        print(
            f"model_reconciliation_fault case={where.case_id}"
            f" run={where.run_id} count={len(faults)}",
            file=sys.stderr,
        )
    unservable = sum(not _servable(cell) for line in model.lines for cell in line.cells)
    if unservable:
        print(
            f"model_figure_unservable case={where.case_id}"
            f" run={where.run_id} count={unservable}",
            file=sys.stderr,
        )
    return replace(served, faults=faults, unservable=unservable)


def _limitations(served: _Served) -> list[str]:
    """The model's own; the PIK limitation where a facility's coupon names
    PIK; a cell past its sources bound; then each open bridge."""
    model = served.model
    facilities = served.inputs.registers.facilities
    pik = any(_PIK.search(row.margin_or_coupon) for row in facilities)
    cut = any(
        len(cell.sources) > MODEL_SOURCES_MAX
        for line in model.lines
        for cell in line.cells
    )
    return [
        *model.limitations,
        *served.noted,
        *([PIK_LIMITATION] if pik else []),
        *([SOURCES_CUT] if cut else []),
        *([WITHHELD] if served.unservable else []),
        *(RECONCILIATION + fault for fault in served.faults),
    ]


def accepted_forecast(
    conn: StoreConnection, body: AnalysisBody
) -> ModelForecast | None:
    """The run's accepted CP-CF projection, re-derived, or None when there is
    none. Shared with the Book, which reads the same accepted pair across
    several credits and must read it the one way this section does.
    """
    accepted = _accepted(body, MODEL_MODULE)
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

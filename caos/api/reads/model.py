"""The Model section: the credit model of the displayed run's accepted CP-1,
with CP-2G and CP-CF's projections where the route ran them, on the v1 wire.

Every figure is the host calculator's (`caos.calculators.credit_model`), read
from the accepted handoffs' tagged tables at request time and served 1:1:
the columns, the lines in their bands, each cell an exact decimal string or
the reason it has none, and the limitations the cells note. A projection
reads the rate deck the run pinned at its creation, never a newer one. A
CP-1 cell's `[C<n>]` marker resolves to CP-1's own citation (D107).

Before CP-1 is accepted the body is empty and says the handoffs are pending
(spec M1). The accepted CP-CF record stays beside the model for comparison,
re-derived as the Book reads it. A source withdrawn from any accepted
handoff's citations refuses the whole read (spec B8). A bridge the
calculator's own check finds open does not refuse an assist model: it is a
visible limitation, and a log line with the case, the run and the count.
Nor do model tables it cannot use (logged by module and code): unreadable
CP-1 tables, as an older run's, serve the accepted CP-CF record without a
model; unreadable or withheld CP-2G drivers hold the business units flat;
a model past the grid's bounds serves the record without a grid; and a cell
whose figure runs past the wire's 64 characters is withheld. Each is a
stated limitation and a log line with no figure.

In its default view the body carries the snapshot digest Add to Book is
bound to (invariant 5; `caos.store.book.snapshot_sha256`): the handoffs it
shows and every figure an entry stores of it (`entry_figures`: the pinned
deck, the currency and unit, the book metrics and the limitations); with
unrealised add-backs excluded, or with no grid, it carries none. `model_grid`
and `entry_figures` are how that command assembles and stores the same model
(spec B10).
"""

from __future__ import annotations

import re
import sys
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from decimal import Decimal
from functools import cache
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends

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
    MODEL_COLUMNS_MAX,
    MODEL_LINES_MAX,
    MODEL_SOURCES_MAX,
    AnalysisBody,
    AnalysisDocument,
    BookMetricView,
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
    RateDeckRefView,
    SectionNote,
)
from caos.calculators.credit_model.assemble import (
    CreditModel,
    ModelInputs,
    credit_model,
    reconciliation_faults,
)
from caos.calculators.credit_model.frame import Cell, Column, SourceRef
from caos.calculators.credit_model.layout import Line, layout
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
    fiscal_year_number,
    slot_allocation,
)
from caos.methodology.tables import FIGURE_CHARS, HandoffTable, handoff_tables
from caos.methodology.vendor import cached_contract
from caos.refusals import Refusal, RefusalCode
from caos.store import StoreConnection
from caos.store.book import EntryFigures, snapshot_sha256
from caos.store.rate_decks import deck_for_run
from caos.store.source_sets import pinned_live_sources

# Analysis' own budget, which this route pays in full before adding to it;
# the live-source pin, once, whether the accepted CP-CF record or the model
# asks for it; and the run's pinned rate deck, read once where CP-1 is
# accepted. Derived rather than written out: a literal 150 was Analysis'
# ten-node forecast route, not the longest route a run can pin (ED-7).
# Measured on that route by test_the_model_reads_within_its_declared_io_budget.
# The blobs are Analysis' and nothing more: the tables are read from the
# Markdown Analysis already verified.
PIN_IO = 1
DECK_IO = 1
IO_BUDGET = analysis.IO_BUDGET + PIN_IO + DECK_IO
BLOB_BUDGET = analysis.BLOB_BUDGET
router = APIRouter()

_CP1 = "CP-1"
_CP2G = "CP-2G"
# Analysis' body fields the model body carries as they are.
_RUN_FIELDS = frozenset(
    {"case_id", "latest_run_id", "displayed_run_id", "displayed_run_status", "subject"}
)
PIK_LIMITATION = (
    "PIK notes carry only their cash coupon in the rate terms;"
    " PIK interest is not modelled"
)
RECONCILIATION = "reconciliation: "
CP1_UNREADABLE = "CP-1 model tables unreadable"
GRID_OVERSIZE = "model exceeds the grid bounds"
# A figure whose plain decimal runs past the wire's `DecimalText`.
TOO_LARGE = "figure too large to serve"
WITHHELD = "figures too large to serve were withheld"
GROWTH_UNAVAILABLE = "CP-2G growth drivers unavailable: business units held flat"
SOURCES_CUT = (
    f"Some cells name more than {MODEL_SOURCES_MAX} source rows;"
    f" each shows its first {MODEL_SOURCES_MAX}"
)
_PIK = re.compile(r"\bPIK\b", re.IGNORECASE)
# How `exclude_unrealised` may be spelled; anything else is refused.
_ON = frozenset({"1", "true"})
_OFF = frozenset({"0", "false"})


def exclude_unrealised_query(exclude_unrealised: str | None = None) -> bool:
    """The `exclude_unrealised` query: `1` or `true` leaves unrealised
    add-backs out of adjusted EBITDA; absent, `0` or `false` keeps them.
    Anything else is `REQUEST_INVALID`, answered before the store opens."""
    if exclude_unrealised is None or exclude_unrealised in _OFF:
        return False
    if exclude_unrealised in _ON:
        return True
    raise Refusal(RefusalCode.REQUEST_INVALID)


ExcludeUnrealised = Annotated[bool, Depends(exclude_unrealised_query)]


@router.get(
    "/api/v1/cases/{case_id}/model",
    response_model=ModelDocument,
    dependencies=[IDENTITY_FIRST],
)
def read_model(  # noqa: PLR0913 -- authenticated case/run before dependencies
    actor: Caller,
    case_id: CasePath,
    run: RunQuery,
    exclude_unrealised: ExcludeUnrealised,
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
    accepted = accepted_cp1(body)
    if accepted is None:
        pending = _empty(body, forecast, exclude_unrealised, [])
        return _document(analysis, pending, pending=True)
    if forecast is None:
        require_live_sources(conn, body)
    grid = model_grid(conn, bundle, accepted, exclude_unrealised=exclude_unrealised)
    if isinstance(grid, NoGrid):
        empty = _empty(body, forecast, exclude_unrealised, [grid.limitation])
        return _document(analysis, empty, pending=False)
    served = replace(grid, forecast=forecast)
    return _document(
        analysis, _body(body, served, _citations(accepted.cp1)), pending=False
    )


@dataclass(frozen=True, slots=True)
class AcceptedCp1:
    """A displayed run whose CP-1 is accepted: the Analysis body read for it,
    CP-1's handoff and the run."""

    body: AnalysisBody
    cp1: HandoffView
    run_id: UUID


def accepted_cp1(body: AnalysisBody) -> AcceptedCp1 | None:
    """The displayed run with its accepted CP-1, or None before CP-1 is
    accepted or with no run displayed (spec M1)."""
    cp1 = _accepted(body, _CP1)
    if cp1 is None or body.displayed_run_id is None:
        return None
    return AcceptedCp1(body, cp1, body.displayed_run_id)


@dataclass(frozen=True, slots=True)
class RunModel:
    """The credit model's inputs for one run, the deck the run pinned, and
    the read's own limitations of them (CP-2G growth unavailable)."""

    inputs: ModelInputs
    deck: RateDeck | None
    noted: tuple[str, ...]


def run_model(
    conn: StoreConnection,
    bundle: Bundle,
    accepted: AcceptedCp1,
    *,
    exclude_unrealised: bool,
) -> RunModel | None:
    """The inputs `credit_model` takes for the run, assembled the one way the
    Model section and the Book's Add to Book both read them (spec B10): CP-1's
    registers and slots, CP-2G's growth, CP-CF's accepted request and the
    run's pinned deck. None, logged, where CP-1's model tables are
    unreadable; the deck is then not read."""
    where = _Where(accepted.body.case_id, accepted.run_id)
    try:
        registers, slots = _cp1_inputs(bundle, accepted.cp1)
    except Refusal as refusal:
        _unreadable(where, _CP1, refusal)
        return None
    growth, noted = _growth(accepted.body, bundle, where)
    deck = deck_for_run(conn, accepted.run_id)
    inputs = ModelInputs(
        registers=registers,
        request=_request(accepted.body),
        growth=growth,
        slots=slots,
        deck=deck,
        exclude_unrealised=exclude_unrealised,
    )
    return RunModel(inputs, deck, noted)


@dataclass(frozen=True, slots=True)
class NoGrid:
    """The Model serves no grid for the run, and says why: CP-1's model
    tables unreadable, or a model past the grid's bounds."""

    limitation: str


def model_grid(
    conn: StoreConnection,
    bundle: Bundle,
    accepted: AcceptedCp1,
    *,
    exclude_unrealised: bool,
) -> ServedModel | NoGrid:
    """The grid the Model serves for the run, or why it serves none: the one
    check the read and Add to Book share (fix round 1, M2), so the Book never
    stores a figure the Model withheld. Each `NoGrid` is logged by case and
    run, never with a figure; the served model's open bridges and figures
    too large to serve are counted and logged as the read always has."""
    where = _Where(accepted.body.case_id, accepted.run_id)
    built = run_model(conn, bundle, accepted, exclude_unrealised=exclude_unrealised)
    if built is None:
        return NoGrid(CP1_UNREADABLE)
    model = credit_model(built.inputs)
    if len(model.columns) > MODEL_COLUMNS_MAX or len(model.lines) > MODEL_LINES_MAX:
        print(
            f"model_grid_oversize case={where.case_id} run={where.run_id}"
            f" columns={len(model.columns)} lines={len(model.lines)}",
            file=sys.stderr,
        )
        return NoGrid(GRID_OVERSIZE)
    return _served(
        where,
        ServedModel(built.inputs, model, (), None, built.deck, built.noted, 0),
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


def served_value(cell: Cell) -> str | None:
    """The cell's figure exactly as this read serves it: plain notation, or
    None where it has none or is withheld past the wire's bound. The Book
    stores each metric this way, so its entry is the Model (spec B10)."""
    return _decimal(cell.value) if _servable(cell) else None


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
class ServedModel:
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


def _served(where: _Where, served: ServedModel) -> ServedModel:
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


def served_limitations(served: ServedModel) -> list[str]:
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


def _body(
    body: AnalysisBody, served: ServedModel, citations: Mapping[int, CitationView]
) -> ModelBody:
    """The model on the wire, 1:1 (`read_model` has checked its bounds)."""
    model = served.model
    deck = served.deck if model.rate_deck_id is not None else None
    return ModelBody(
        **body.model_dump(include=set(_RUN_FIELDS)),
        snapshot_sha256=None
        if served.inputs.exclude_unrealised
        else entry_snapshot(
            ((h.route_node_id, h.artifact_sha256) for h in body.handoffs), served
        ),
        currency=model.currency,
        unit=model.unit,
        exclude_unrealised=served.inputs.exclude_unrealised,
        rate_deck=None
        if deck is None
        else RateDeckRefView(deck_id=UUID(deck.deck_id), as_of=deck.as_of),
        columns=[_column(column) for column in model.columns],
        lines=[_line(line, citations) for line in model.lines],
        limitations=served_limitations(served),
        forecast=served.forecast,
    )


def _empty(
    body: AnalysisBody,
    forecast: ModelForecast | None,
    exclude: bool,
    limitations: list[str],
) -> ModelBody:
    """No model: no accepted CP-1 yet (spec M1), or CP-1's model tables
    unreadable. The accepted CP-CF record is still served."""
    return ModelBody(
        **body.model_dump(include=set(_RUN_FIELDS)),
        snapshot_sha256=None,
        currency=None,
        unit=None,
        exclude_unrealised=exclude,
        rate_deck=None,
        columns=[],
        lines=[],
        limitations=limitations,
        forecast=forecast,
    )


def entry_figures(served: ServedModel) -> EntryFigures:
    """Every figure an entry stores of the served model: the deck the run
    pinned (fix round 2, N2: the pin, so a run without CP-CF names it too),
    the model's currency and unit, its book metrics and the limitations
    this read serves (N3)."""
    model = served.model
    return EntryFigures(
        rate_deck_id=None if served.deck is None else served.deck.deck_id,
        currency=model.currency,
        unit=model.unit,
        metrics=book_metrics(model),
        limitations=tuple(served_limitations(served)),
    )


def entry_snapshot(artifacts: Iterable[tuple[str, str]], served: ServedModel) -> str:
    """The digest an Add to Book binds (invariant 5): the accepted artifacts
    and `entry_figures` -- served by the default view only, since the entry
    stores the default add-backs, and recomputed by the add under the case
    lock."""
    return snapshot_sha256(artifacts, entry_figures(served))


# The Book's metric set (spec M5, B11): every `metric:` line and these, each
# basis the LTM, the PF-LTM and FY+1 to FY+3 of each case, keyed by the
# offset from the model's base year with that year stored beside the lines.
BOOK_LINES = frozenset(
    {
        "revenue",
        "adjusted_ebitda",
        "total_debt",
        "net_debt",
        "liquidity",
        "fcf",
        "ffo",
        "cash_closing",
        "lease_adjusted_net_debt",
    }
)
_METRIC = "metric:"
PROJECTED_YEARS = 3
FISCAL_YEAR = "fiscal_year"


def _base_year(columns: Sequence[Column], first: int) -> int:
    """The projection's base year: the last historical FY, else the year
    before the first projected one (`projection._context`'s rule)."""
    fiscal = [column for column in columns if column.kind == "FY"]
    last = fiscal_year_number(fiscal[-1].fiscal_year) if fiscal else None
    return last or first - 1


def book_bases(columns: Sequence[Column]) -> dict[str, tuple[int, int | None]]:
    """Each stored basis, its column and, for a projected one, its fiscal
    year: the first LTM, the PF-LTM, and `<CASE>_FY<n>` for the projected
    year n years after the base year, n in 1-3 (fix round 1, L2). A missing
    offset is omitted, never filled by the next year along."""
    indexed = list(enumerate(columns))
    found: dict[str, tuple[int, int | None]] = {}
    for kind in ("LTM", "PF_LTM"):
        index = next((i for i, column in indexed if column.kind == kind), None)
        if index is not None:
            found[kind] = (index, None)
    placed = [
        (i, column.case, year)
        for i, column in indexed
        if column.kind == "PROJECTED"
        and (year := fiscal_year_number(column.fiscal_year)) is not None
    ]
    if not placed:
        return found
    base = _base_year(columns, min(year for _i, _case, year in placed))
    for index, case, year in placed:
        basis = f"{case}_FY{year - base}"
        if 1 <= year - base <= PROJECTED_YEARS and basis not in found:
            found[basis] = (index, year)
    return found


def _book_line(line_id: str) -> bool:
    """Whether the Book stores the line: a `metric:` line or a `BOOK_LINES`."""
    return line_id.startswith(_METRIC) or line_id in BOOK_LINES


@cache
def book_catalogue() -> tuple[BookMetricView, ...]:
    """The lines `book_metrics` stores, as the Model's layout defines them:
    in its order, with its labels and units (spec B12's column chooser).
    None of them is a register's row, so the layout over registers with no
    rows and no columns draws every one. Pure."""
    empty = Cp1Registers((), (), (), (), (), (), (), "", "")
    return tuple(
        BookMetricView(line_id=line.line_id, label=line.label, unit=line.unit)
        for line in layout(empty, (), {}, exclude_unrealised=False, deck_as_of=None)
        if _book_line(line.line_id)
    )


def book_metrics(model: CreditModel) -> dict[str, dict[str, str | None]]:
    """`{basis: {line_id: figure}}` for every `metric:` line and each of
    `BOOK_LINES`, each figure as this read serves that cell (spec B10), and
    a projected basis' `fiscal_year`."""
    lines = [line for line in model.lines if _book_line(line.line_id)]
    metrics: dict[str, dict[str, str | None]] = {}
    for basis, (index, year) in book_bases(model.columns).items():
        figures = {line.line_id: served_value(line.cells[index]) for line in lines}
        if year is not None:
            figures[FISCAL_YEAR] = str(year)
        metrics[basis] = figures
    return metrics


def _document(
    analysis: AnalysisDocument, body: ModelBody, *, pending: bool
) -> ModelDocument:
    """Analysis' envelope around the model: `pending` (no accepted CP-1),
    its handoffs pending (spec M1). Without a line the document is partial,
    and observed empty unless it serves the accepted forecast."""
    notes = list(analysis.notes)
    if pending and SectionNote.HANDOFFS_PENDING not in notes:
        notes.append(SectionNote.HANDOFFS_PENDING)
    empty = not body.lines
    return ModelDocument(
        chrome=analysis.chrome,
        body=body,
        observed_at=analysis.observed_at,
        observed_empty=empty and body.forecast is None,
        status="partial" if notes or empty else "complete",
        notes=notes,
    )


def require_live_sources(conn: StoreConnection, body: AnalysisBody) -> None:
    """Every accepted handoff's citations still name a live source pinned to
    the run, or `ARTIFACT_RECORD_MISMATCH` (spec B8). One round trip."""
    if body.displayed_run_id is None:
        return
    live = pinned_live_sources(conn, body.displayed_run_id)
    if any(
        c.document_sha256 not in live for h in body.handoffs for c in h.source_facts
    ):
        raise Refusal(RefusalCode.ARTIFACT_RECORD_MISMATCH)


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
    require_live_sources(conn, body)
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

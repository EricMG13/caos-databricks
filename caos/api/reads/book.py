"""Book, `/api/v1/book` (IA_SPEC.md 4.4): the credit, across the portfolio.

Portfolio-scoped, so the path names no case. The rows are the cases the caller
holds live standing on, read exactly as Directory reads them, and each row's
cells are values the accepted CP-CF projection already carries -- re-derived by
`caos.api.reads.model.accepted_forecast`, the one reader the Model section
uses too. This module computes no figure and reaches no verdict: it names the
columns its own calculator declares, and answers each passport field from the
accepted record, the pinned run subject, or the host's declaration of its own
arithmetic.

A credit whose projection read refuses does not decide the others: the typed
code and its host `clears` constant become that row's `refusal`, while
`unavailable_reason` says only that no forecast was accepted. The two are
separate fields because a refusal and an unrun forecast are different answers.
No document-derived text is carried.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from fastapi import APIRouter

from caos.api.deps import IDENTITY_FIRST, Blobs, Caller, Methodology, Store
from caos.api.identity import Actor
from caos.api.reads.analysis import AnalysisQuery, read_analysis_without_tables
from caos.api.reads.model import BLOB_BUDGET as MODEL_BLOBS
from caos.api.reads.model import IO_BUDGET as MODEL_IO
from caos.api.reads.model import accepted_forecast
from caos.api.wire import (
    BOOK_CASES_MAX,
    BOOK_PERIODS_MAX,
    CLEARS,
    AnalysisBody,
    BookBasis,
    BookBody,
    BookCell,
    BookColumn,
    BookDocument,
    BookPassport,
    BookPeriod,
    BookResearch,
    BookRow,
    Chrome,
    CitationView,
    ModelForecast,
    ModelPeriod,
    ModelValue,
    RefusalBody,
    SectionNote,
    ServedRole,
)
from caos.blobs import BlobStore
from caos.methodology.bundle import Bundle
from caos.methodology.forecast import forecast_inputs
from caos.refusals import Refusal, RefusalCode
from caos.store import StoreConnection
from caos.store.members import CaseListing, cases_for_member

# The store's `now()` and the one listing query, then per credit exactly what
# the Model section pays -- it is the same Analysis read and the same
# live-source pin -- less the `visible_case` query the Model route makes and
# this one does not, because standing comes from the listing. Linear in the
# credits served, which `BOOK_CASES_MAX` bounds. Measured per credit in
# `tests/test_book_section.py`.
FIXED_IO = 2
PER_ROW_IO = MODEL_IO - 1
IO_BUDGET = FIXED_IO + BOOK_CASES_MAX * PER_ROW_IO
# Each credit's Analysis blobs, once each: the request's store remembers what
# it verified, so no record is downloaded twice within a credit (ED-7).
BLOB_BUDGET = BOOK_CASES_MAX * MODEL_BLOBS

router = APIRouter()

# The spelling the prompt builder uses for a field the authority does not
# declare. The scenario is not one of them -- `caos-forecast-v1` declares
# scenarios under the name `case`, which this repository's own qualification
# reader already matches `ExpectedForecast.scenario` against -- so a cell names
# its period's `case` and this constant is left to the fields that earn it.
NOT_DECLARED = "NOT_DECLARED"
STANDARD = "caos-forecast-v1"
# `forecast_projection` re-derives the whole result and refuses on any
# difference, so a value that reaches a cell was verified to reach it.
METHOD = "cash_flow_forecast · VERIFIED"


@dataclass(frozen=True)
class _Column:
    """A column of the book, and the host's account of its own arithmetic.

    `drivers` are the fields of the period's accepted driver row the
    expression reads, which is what lets a cell name the driver behind it and
    that driver's evidence (IA_SPEC.md 4.6). A column whose operands are not
    that period's own drivers is not declared here: the roll-forward's closing
    balances reduce to every earlier period, and a passport that named only
    the local drivers for them would understate the lineage.
    """

    key: str
    label: str
    definition: str
    expression: str
    drivers: tuple[str, ...]
    # What the cell's own figure is (N60): the calculator's `_ratio` returns
    # the same plain fraction for a margin and for a leverage multiple, so
    # the unit is what this column names, never a guess from the figure.
    unit: Literal["percent", "currency", "multiple", "count", "none"]


def _stated(what: str) -> str:
    """A driver-backed column's definition in words, plus the standard it follows."""
    return f"{what}, as the accepted driver row for the period states it ({STANDARD})."


COLUMNS: tuple[_Column, ...] = (
    _Column(
        "operating.revenue",
        "Revenue",
        _stated("Revenue for the period"),
        "drivers[period].revenue",
        ("revenue",),
        "currency",
    ),
    _Column(
        "operating.ebitda",
        "EBITDA",
        _stated("Earnings before interest, tax, depreciation and amortisation"),
        "drivers[period].ebitda",
        ("ebitda",),
        "currency",
    ),
    _Column(
        "operating.cfo",
        "Cash flow from operations",
        _stated("Cash generated by operations"),
        "drivers[period].cfo",
        ("cfo",),
        "currency",
    ),
    _Column(
        "investing.capex",
        "Capital expenditure",
        _stated("Cash spent on capital expenditure"),
        "drivers[period].capex",
        ("capex",),
        "currency",
    ),
    _Column(
        "financing.cash_interest",
        "Cash interest",
        _stated("Interest paid in cash"),
        "drivers[period].cash_interest",
        ("cash_interest",),
        "currency",
    ),
    _Column(
        "operating.margin",
        "EBITDA margin",
        "EBITDA margin: EBITDA over revenue, as `cash_flow_forecast`"
        f" computes it ({STANDARD}).",
        "operating.ebitda / operating.revenue",
        ("ebitda", "revenue"),
        "percent",
    ),
)


@router.get("/api/v1/book", response_model=BookDocument, dependencies=[IDENTITY_FIRST])
def read_book(
    actor: Caller, conn: Store, blobs: Blobs, bundle: Methodology
) -> BookDocument:
    """`actor` is declared before `conn`: an anonymous request is refused
    before a connection opens, as Directory's read is."""
    [observed_at] = conn.execute("SELECT now()").fetchall()[0]
    listed = cases_for_member(conn, user_id=actor.user_id, limit=BOOK_CASES_MAX + 1)
    truncated = len(listed) > BOOK_CASES_MAX
    rows = []
    for listing in listed[:BOOK_CASES_MAX]:
        row, row_truncated = _row(actor, listing, conn, blobs, bundle)
        rows.append(row)
        truncated = truncated or row_truncated
    # A member holding no credits holds nothing incomplete: Directory answers
    # `complete` for the same state, and a warning strip over an empty page
    # tells a reader something is wrong when nothing is.
    complete = all(_stated_row(row) for row in rows)
    return BookDocument(
        chrome=Chrome(
            subject=None,
            served_role=ServedRole(global_role=actor.role, standing=None),
            actions=[],
        ),
        body=BookBody(
            basis=BookBasis(
                period="EVERY_ACCEPTED_PERIOD",
                scenario="EVERY_ACCEPTED_CASE",
                accepted_only=True,
            ),
            columns=[
                BookColumn(key=c.key, label=c.label, unit=c.unit) for c in COLUMNS
            ],
            rows=rows,
        ),
        observed_at=observed_at,
        observed_empty=not rows,
        status="complete" if complete and not truncated else "partial",
        notes=[SectionNote.LIST_TRUNCATED] if truncated else [],
    )


def _stated_row(row: BookRow) -> bool:
    """A credit whose cells are all there: nothing refused and a forecast accepted."""
    return row.unavailable_reason is None and row.refusal is None


@dataclass(frozen=True)
class _Lineage:
    """What every cell of one credit answers its passport from."""

    request: dict[str, Any]
    bindings: dict[str, Any]
    facts: dict[str, list[CitationView]]
    research: list[BookResearch]
    forecast: ModelForecast
    reporting_period: str


def _row(
    actor: Actor,
    listing: CaseListing,
    conn: StoreConnection,
    blobs: BlobStore,
    bundle: Bundle,
) -> tuple[BookRow, bool]:
    """One credit, and whether its periods were cut at `BOOK_PERIODS_MAX`."""
    try:
        analysis = read_analysis_without_tables(
            AnalysisQuery(
                actor, listing.case_id, None, listing.standing, conn, blobs, bundle
            )
        ).body
        forecast = accepted_forecast(conn, analysis)
    except Refusal as refusal:
        # The typed code and its host `clears`, both host constants -- nothing
        # a document supplied reaches a row a reader compares credits across.
        return _bare(listing, None, refusal=_body(refusal.code)), False
    if forecast is None:
        return _bare(listing, analysis, reason="NO_ACCEPTED_FORECAST"), False
    periods = _periods(analysis, forecast)
    return (
        BookRow(
            case_id=listing.case_id,
            title=listing.title,
            standing=listing.standing,
            subject=analysis.subject,
            displayed_run_id=analysis.displayed_run_id,
            displayed_run_status=analysis.displayed_run_status,
            snapshot=forecast.record_sha256,
            currency=forecast.currency,
            scale=forecast.scale,
            periods=periods[:BOOK_PERIODS_MAX],
            unavailable_reason=None,
            refusal=None,
        ),
        len(periods) > BOOK_PERIODS_MAX,
    )


def _body(code: RefusalCode) -> RefusalBody:
    return RefusalBody(code=code, clears=CLEARS[code])


def _bare(
    listing: CaseListing,
    analysis: AnalysisBody | None,
    *,
    reason: Literal["NO_ACCEPTED_FORECAST"] | None = None,
    refusal: RefusalBody | None = None,
) -> BookRow:
    """A credit with no cells, and the typed reason it has none."""
    return BookRow(
        case_id=listing.case_id,
        title=listing.title,
        standing=listing.standing,
        subject=None if analysis is None else analysis.subject,
        displayed_run_id=None if analysis is None else analysis.displayed_run_id,
        displayed_run_status=(
            None if analysis is None else analysis.displayed_run_status
        ),
        snapshot=None,
        currency=None,
        scale=None,
        periods=[],
        unavailable_reason=reason,
        refusal=refusal,
    )


def _periods(analysis: AnalysisBody, forecast: ModelForecast) -> list[BookPeriod]:
    accepted = next(
        h for h in analysis.handoffs if h.route_node_id == forecast.route_node_id
    )
    request, bindings = forecast_inputs(accepted.model_analysis.encode("utf-8"))
    lineage = _Lineage(
        request=request,
        bindings=bindings,
        facts={h.module_id: list(h.source_facts) for h in analysis.handoffs},
        research=[
            BookResearch(
                route_node_id=h.route_node_id,
                module_id=h.module_id,
                qa_status=h.qa_status,
            )
            for h in analysis.handoffs
        ],
        forecast=forecast,
        # The pinned subject's reporting period, which the analyst declared
        # when the run was created. Named as that rather than as IA_SPEC 4.4's
        # "evidence date": the host derives no date from any admitted document,
        # so a field claiming one would be a host fact it does not hold.
        reporting_period=(
            analysis.subject.reporting_period if analysis.subject else "NOT_DECLARED"
        ),
    )
    return [_period(period, lineage) for period in forecast.periods]


def _period(period: ModelPeriod, lineage: _Lineage) -> BookPeriod:
    values = {value.name: value for value in period.values}
    index = _driver_index(lineage.request, period.case, period.period_id)
    return BookPeriod(
        case=period.case,
        period_id=period.period_id,
        fiscal_year=period.fiscal_year,
        days=period.days,
        unavailable_reason=period.unavailable_reason,
        cells=[
            _cell(column, values[column.key], period, index, lineage)
            for column in COLUMNS
            if column.key in values
        ],
    )


def _driver_index(request: dict[str, Any], case: str, period_id: str) -> int | None:
    """Which accepted driver row is this period's, by the pair that keys it."""
    for index, driver in enumerate(request.get("drivers", [])):
        if (driver.get("case"), driver.get("period_id")) == (case, period_id):
            return index
    return None


def _cell(
    column: _Column,
    value: ModelValue,
    period: ModelPeriod,
    index: int | None,
    lineage: _Lineage,
) -> BookCell:
    operands = _operands(lineage.request, index, column)
    return BookCell(
        column=column.key,
        value=value.value,
        unavailable_reason=value.unavailable_reason,
        passport=BookPassport(
            definition=column.definition,
            period=f"{period.period_id} · FY{period.fiscal_year} · {period.days} days",
            scenario=period.case,
            reporting_period=lineage.reporting_period,
            computed_at=lineage.forecast.accepted_at,
            snapshot=lineage.forecast.record_sha256,
            method=METHOD,
            derivation=_derivation(column, operands),
            citations=_citations(column, index, lineage),
            supporting_research=lineage.research,
        ),
    )


def _operands(
    request: dict[str, Any], index: int | None, column: _Column
) -> dict[str, str]:
    if index is None:
        return {}
    driver = request["drivers"][index]
    return {name: str(driver[name]) for name in column.drivers if name in driver}


def _derivation(column: _Column, operands: dict[str, str]) -> str:
    """The expression, with its operands (IA_SPEC.md 4.4)."""
    if not operands:
        return f"{column.expression} \u2014 operands not stated by the accepted request"
    stated = ", ".join(f"{name} = {value}" for name, value in operands.items())
    return f"{column.expression} \u2014 {stated}"


def _citations(
    column: _Column, index: int | None, lineage: _Lineage
) -> list[CitationView]:
    """The evidence of the drivers this cell reads: for each operand, the
    citation its accepted owner binding names. A binding whose quote no
    citation of that module carries contributes nothing, rather than a
    rectangle nobody anchored."""
    if index is None:
        return []
    found: list[CitationView] = []
    for name in column.drivers:
        binding = lineage.bindings.get(f"/drivers/{index}/{name}")
        if not isinstance(binding, dict):
            continue
        module = binding.get("module_id")
        if not isinstance(module, str):
            continue
        for fact in lineage.facts.get(module, []):
            if fact.matched_text == binding.get("quote") and fact not in found:
                found.append(fact)
    return found

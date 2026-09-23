"""The Book over real accepted CP-CF projections: cells, passports, visibility.

Portfolio-scoped, so it names no case in its path and reads only the cases the
caller holds live standing on. Every cell is a value the accepted, re-derived
projection already carries; this reader computes no figure of its own.
"""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from test_analysis_section import _as, _CountingConnection, _serving, client
from test_execution_freshness import _Harness
from test_forecast_route import ForecastCompletions, harness
from test_forecast_route import route as forecast_route
from test_model_section import _complete, route

from caos.api.app import app, store_connection
from caos.api.identity import Actor, GlobalRole
from caos.api.reads import analysis as analysis_read
from caos.api.reads import book as book_read
from caos.api.reads.analysis import read_analysis
from caos.api.reads.model import accepted_forecast
from caos.api.wire import CLEARS, BookDocument
from caos.boundary_text import BoundaryText
from caos.methodology.forecast import forecast_inputs
from caos.refusals import RefusalCode
from caos.store.gates import withdraw_source
from caos.store.members import Standing, grant
from caos.store.run_inputs import load_run_input
from caos.store.runs import create_case

__all__ = ["ForecastCompletions", "client", "forecast_route", "harness", "route"]

PATH = "/api/v1/book"


def _book(client: TestClient, harness: _Harness, user: UUID) -> BookDocument:
    response = client.get(PATH, headers=_as(user))
    harness.conn.rollback()
    assert response.status_code == 200, response.json()
    return BookDocument.model_validate(response.json())


def test_the_book_row_carries_the_accepted_projection_cells_and_their_passports(
    client: TestClient, harness: _Harness
) -> None:
    _complete(harness)
    document = _book(client, harness, harness.approver)

    assert document.chrome.subject is None
    assert document.status == "complete" and document.observed_empty is False
    assert [column.key for column in document.body.columns] == [
        "operating.revenue",
        "operating.ebitda",
        "operating.cfo",
        "investing.capex",
        "financing.cash_interest",
        "operating.margin",
    ]
    [row] = document.body.rows
    assert row.case_id == harness.case_id
    assert row.displayed_run_id == harness.run_id
    assert row.unavailable_reason is None
    assert row.snapshot is not None
    assert (row.currency, row.scale) == ("USD", "millions")
    [period] = row.periods
    assert (period.case, period.period_id, period.fiscal_year) == (
        "BASE",
        "FY2026",
        "2026",
    )
    cells = {cell.column: cell for cell in period.cells}
    assert cells["operating.ebitda"].value == "100.000000"
    assert cells["operating.margin"].value == "0.2000"

    # The ten fields of IA_SPEC 4.4, each answered from what the record says.
    passport = cells["operating.margin"].passport
    assert passport.period == "FY2026 · FY2026 · 365 days"
    # The scenario is the record's own `case`, not a constant: two cases
    # produce two tables and a reader tells them apart here.
    assert passport.scenario == period.case == "BASE"
    assert document.body.basis.scenario == "EVERY_ACCEPTED_CASE"
    assert passport.snapshot == row.snapshot
    # The analyst's declared reporting period, named as what it is: the host
    # derives no date from any admitted document, so the field does not claim
    # to be one.
    pinned = load_run_input(harness.conn, harness.run_id)
    harness.conn.rollback()
    assert pinned is not None and pinned.subject is not None
    assert passport.reporting_period == pinned.subject.reporting_period
    assert "evidence_date" not in type(passport).model_fields
    assert passport.method == "cash_flow_forecast · VERIFIED"
    assert passport.derivation == (
        "operating.ebitda / operating.revenue — ebitda = 100, revenue = 500"
    )
    assert "EBITDA margin" in passport.definition
    assert "caos-forecast-v1" in passport.definition
    # The driver's own evidence: the CP-2G quote the accepted binding names,
    # anchored where that module cited it, all from the one source document.
    assert passport.citations, "a projected cell names the evidence of its driver"
    assert len({citation.document_sha256 for citation in passport.citations}) == 1
    for citation in passport.citations:
        assert "/drivers/0/ebitda = " in citation.matched_text
    assert {research.module_id for research in passport.supporting_research} >= {
        "CP-1",
        "CP-2G",
        "CP-4",
        "CP-CF",
    }


def test_the_book_lists_only_the_cases_the_caller_holds_standing_on(
    client: TestClient, harness: _Harness
) -> None:
    _complete(harness)
    stranger = uuid4()
    assert _book(client, harness, stranger).body.rows == []
    assert _book(client, harness, stranger).observed_empty is True

    other = create_case(harness.conn, BoundaryText.of("A second credit"))
    grant(
        harness.conn,
        case_id=other,
        user_id=harness.approver,
        standing=Standing.READER,
    )
    harness.conn.commit()
    rows = _book(client, harness, harness.approver).body.rows
    assert {row.case_id for row in rows} == {harness.case_id, other}


def test_a_case_with_no_accepted_forecast_is_a_row_that_says_so(
    client: TestClient, harness: _Harness
) -> None:
    document = _book(client, harness, harness.approver)
    [row] = document.body.rows
    assert row.periods == []
    assert row.snapshot is None
    assert row.unavailable_reason == "NO_ACCEPTED_FORECAST"
    assert document.status == "partial"


def test_the_book_reads_within_its_declared_io_budget(
    client: TestClient, harness: _Harness
) -> None:
    _complete(harness)
    counter = _CountingConnection(harness.conn)
    app.dependency_overrides[store_connection] = _serving(counter)
    response = client.get(PATH, headers=_as(harness.approver))
    harness.conn.rollback()
    assert response.status_code == 200, response.json()
    # Exact for the one credit served: a ceiling four times this size would
    # pass whatever one credit cost. The credit is the forecast route's ten
    # handoffs, inside a per-credit share declared for the longest route
    # (ED-7).
    one_credit = (
        analysis_read.FIXED_IO
        + len(harness.route.nodes) * analysis_read.PER_HANDOFF_IO
        + analysis_read.MODEL_PROOFS_IO
    )
    assert counter.executed == book_read.FIXED_IO + one_credit
    assert one_credit <= book_read.PER_ROW_IO == analysis_read.IO_BUDGET
    assert book_read.IO_BUDGET == book_read.FIXED_IO + 4 * book_read.PER_ROW_IO
    assert book_read.BLOB_BUDGET == 4 * analysis_read.BLOB_BUDGET


@pytest.mark.parametrize("path", [PATH, f"{PATH}?case=x"])
def test_the_book_refuses_an_anonymous_request(client: TestClient, path: str) -> None:
    assert client.get(path).status_code == 401


def test_a_credit_whose_projection_refuses_names_its_code_and_spares_the_others(
    client: TestClient, harness: _Harness
) -> None:
    """One credit's refusal is stated on its row, never on the portfolio."""
    _complete(harness)
    other = create_case(harness.conn, BoundaryText.of("A second credit"))
    grant(
        harness.conn, case_id=other, user_id=harness.approver, standing=Standing.READER
    )
    withdraw_source(
        harness.conn,
        case_id=harness.case_id,
        source_id=harness.source_id,
        actor_id=harness.approver,
    )
    harness.conn.commit()

    document = _book(client, harness, harness.approver)
    rows = {row.case_id: row for row in document.body.rows}
    refused = rows[harness.case_id]
    assert refused.periods == []
    assert refused.unavailable_reason is None
    assert refused.refusal is not None
    # Withdrawal is checked live (invariant 1), so this credit's own read
    # refuses before its projection is re-derived.
    assert refused.refusal.code is RefusalCode.EVIDENCE_NOT_AVAILABLE
    assert refused.refusal.clears == CLEARS[RefusalCode.EVIDENCE_NOT_AVAILABLE]
    assert rows[other].unavailable_reason == "NO_ACCEPTED_FORECAST"
    assert document.status == "partial"


def test_the_book_reads_the_accepted_forecast_and_its_bindings_the_model_way(
    client: TestClient, harness: _Harness
) -> None:
    """`accepted_forecast` is the Model section's reader, and `forecast_inputs`
    the accepted request and bindings behind it: the book states lineage from
    the same bytes rather than reading the store a second way."""
    _complete(harness)
    analysis = read_analysis(
        Actor(harness.approver, GlobalRole.ANALYST),
        harness.case_id,
        None,
        Standing.APPROVER,
        harness.conn,
        harness.blobs,
        harness.bundle,
    ).body
    forecast = accepted_forecast(harness.conn, analysis)
    assert forecast is not None
    accepted = next(h for h in analysis.handoffs if h.module_id == "CP-CF")
    request, bindings = forecast_inputs(accepted.model_analysis.encode("utf-8"))
    assert request["drivers"][0]["ebitda"] == "100"
    assert bindings["/drivers/0/ebitda"]["module_id"] == "CP-2G"

    row = _book(client, harness, harness.approver).body.rows[0]
    assert row.snapshot == forecast.record_sha256

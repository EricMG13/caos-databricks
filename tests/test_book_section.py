"""The Book over real accepted CP-CF projections: cells, passports, visibility.

Portfolio-scoped, so it names no case in its path and reads only the cases the
caller holds live standing on. Every cell is a value the accepted, re-derived
projection already carries; this reader computes no figure of its own.
"""

from __future__ import annotations

from datetime import date
from uuid import UUID, uuid4

import pytest
from command_fixtures import member
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
from caos.api.reads import model as model_read
from caos.api.wire import CLEARS, BookDocument, BookIssuerView
from caos.boundary_text import BoundaryText
from caos.methodology import tables
from caos.methodology.vendor import VendorContract
from caos.refusals import RefusalCode
from caos.store.book import (
    Classification,
    EntryFigures,
    EntrySubject,
    NewEntry,
    Withdrawal,
    insert_entry,
    withdraw_entry,
)
from caos.store.gates import withdraw_source
from caos.store.members import Standing, grant
from caos.store.run_inputs import load_run_input
from caos.store.runs import create_case, start_run

__all__ = ["ForecastCompletions", "client", "forecast_route", "harness", "route"]

PATH = "/api/v1/book"
STATED = Classification(
    sector="Energy",
    industry_group=None,
    domicile="US",
    moodys="Baa3",
    moodys_outlook="STABLE",
    sp=None,
    sp_outlook=None,
    fitch=None,
    fitch_outlook=None,
    composite_notch=10,
)
FIGURES = EntryFigures(
    rate_deck_id=None,
    currency="USD",
    unit="MILLIONS",
    metrics={
        "LTM": {"revenue": "1200", "metric:net_leverage_adjusted": "3.1"},
        "BASE_FY1": {
            "revenue": "1260",
            "metric:net_leverage_adjusted": None,
            "fiscal_year": "2027",
        },
    },
    limitations=("no rate deck: BASE:2027",),
)


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
    # N60: a plain fraction and a currency amount are the same shape of
    # Decimal, so the cell is told which the column is.
    assert {column.key: column.unit for column in document.body.columns} == {
        "operating.revenue": "currency",
        "operating.ebitda": "currency",
        "operating.cfo": "currency",
        "investing.capex": "currency",
        "financing.cash_interest": "currency",
        "operating.margin": "percent",
    }
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

    # The ten passport fields, each answered from what the record says.
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
    # One anchored line per driver the cell reads (N28: a quote is one line).
    assert sorted(
        citation.matched_text.split(" = ")[0] for citation in passport.citations
    ) == ["/drivers/0/ebitda", "/drivers/0/revenue"]
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


def test_the_book_does_not_derive_the_tagged_tables_analysis_drops_for_it(
    client: TestClient, harness: _Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    """N58: the Book reads every accepted handoff through
    `read_analysis_without_tables`, not `read_analysis` -- `BookResearch`
    carries no `tables` field, so deriving each handoff's tagged tables for
    this row only ever produced a value the wire then dropped."""
    _complete(harness)
    calls: list[None] = []

    def counting(contract: VendorContract, markdown: str) -> tables.HandoffTables:
        calls.append(None)
        return tables.handoff_tables(contract, markdown)

    monkeypatch.setattr(analysis_read, "handoff_tables", counting)
    document = _book(client, harness, harness.approver)
    assert document.body.rows[0].unavailable_reason is None
    assert calls == []


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


def _entry(
    harness: _Harness,
    issuer_id: str,
    analysis_date: str,
    *,
    case_id: UUID | None = None,
    run_id: UUID | None = None,
) -> UUID:
    """A stored entry for a new run of `case_id` (the harness's case by
    default), committed: what the Add command writes, written directly."""
    conn = harness.conn
    case = case_id or harness.case_id
    run = run_id or start_run(conn, case)
    entry_id = uuid4()
    insert_entry(
        conn,
        NewEntry(
            entry_id=entry_id,
            case_id=case,
            run_id=run,
            subject=EntrySubject(
                issuer_id=issuer_id,
                issuer_name=f"{issuer_id.strip()} Holdings",
                reporting_period="FY2026",
                analysis_date=analysis_date,
                route="FULL_CREDIT_32/RELATIVE_VALUE",
            ),
            classification=STATED,
            snapshot_sha256="c" * 64,
            figures=FIGURES,
            added_by=harness.approver,
        ),
    )
    conn.commit()
    return entry_id


def _prepared(
    harness: _Harness, user: UUID, role: GlobalRole = GlobalRole.ANALYST
) -> tuple[list[BookIssuerView], bool]:
    issuers, truncated = book_read._issuers(harness.conn, Actor(user, role))
    harness.conn.rollback()
    return issuers, truncated


def _prepared_issuer(harness: _Harness, key: str) -> BookIssuerView:
    issuers, _ = _prepared(harness, uuid4())
    [issuer] = [issuer for issuer in issuers if issuer.issuer_key == key]
    return issuer


def test_an_issuers_row_is_its_newest_live_entry_by_analysis_date(
    harness: _Harness,
) -> None:
    """Spec B1, B4: one row per issuer key, whatever the spelling; the newest
    analysis date displays, then the later add, and the rest are history,
    newest first."""
    march = _entry(harness, "acme ", "2026-03-31")
    june = _entry(harness, "ACME", "2026-06-30")
    june_later = _entry(harness, " Acme", "2026-06-30")
    # Added last, but analysed earliest: it never displays.
    december = _entry(harness, "ACME", "2025-12-31")

    [issuer] = _prepared(harness, uuid4())[0]
    assert issuer.issuer_key == "ACME"
    assert issuer.displayed.entry_id == june_later
    assert issuer.displayed.issuer_id == " Acme"
    assert [entry.entry_id for entry in issuer.history] == [june, march, december]
    assert [entry.analysis_date for entry in issuer.history] == [
        "2026-06-30",
        "2026-03-31",
        "2025-12-31",
    ]
    assert date.fromisoformat(issuer.displayed.analysis_date) == date(2026, 6, 30)
    # The served figures are the stored ones, the year apart from the leaves.
    assert issuer.displayed.metrics["BASE_FY1"] == {
        "revenue": "1260",
        "metric:net_leverage_adjusted": None,
    }
    assert issuer.displayed.fiscal_years == {"BASE_FY1": "2027"}
    assert issuer.displayed.limitations == ["no rate deck: BASE:2027"]
    assert issuer.displayed.snapshot_sha256 == "c" * 64
    assert (issuer.displayed.composite, issuer.displayed.composite_bucket) == (
        "BBB-",
        "IG",
    )


def test_issuers_past_the_bound_are_cut_and_said_so(
    harness: _Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    for issuer in ("ALPHA", "BRAVO", "CHARLIE"):
        _entry(harness, issuer, "2026-06-30")
    monkeypatch.setattr(book_read, "BOOK_ISSUERS_MAX", 2)
    issuers, truncated = _prepared(harness, uuid4())
    assert [i.issuer_key for i in issuers] == ["ALPHA", "BRAVO"]
    assert truncated is True


def test_history_past_the_bound_is_cut_and_said_so(
    harness: _Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(book_read, "BOOK_HISTORY_MAX", 1)
    newest = _entry(harness, "ACME", "2026-06-30")
    middle = _entry(harness, "ACME", "2026-03-31")
    issuers, truncated = _prepared(harness, uuid4())
    [issuer] = issuers
    assert (issuer.displayed.entry_id, [e.entry_id for e in issuer.history]) == (
        newest,
        [middle],
    )
    assert truncated is False

    _entry(harness, "ACME", "2025-12-31")
    issuers, truncated = _prepared(harness, uuid4())
    [issuer] = issuers
    assert [entry.entry_id for entry in issuer.history] == [middle]
    assert truncated is True


def test_a_withdrawn_entry_moves_to_history_and_the_previous_one_displays(
    harness: _Harness,
) -> None:
    """Spec B7: withdrawn, never deleted; the previous live entry is the row
    again, and an issuer with no live entry has no row."""
    older = _entry(harness, "ACME", "2026-03-31")
    newer = _entry(harness, "ACME", "2026-06-30")
    withdrawn = withdraw_entry(
        harness.conn,
        Withdrawal(newer, harness.approver, "OTHER", "Restated after the audit"),
    )
    harness.conn.commit()
    assert withdrawn

    [issuer] = _prepared(harness, uuid4())[0]
    assert issuer.displayed.entry_id == older
    [history] = issuer.history
    assert history.entry_id == newer
    assert history.withdrawn_at is not None
    assert (history.withdrawal_reason, history.withdrawal_note) == (
        "OTHER",
        "Restated after the audit",
    )

    assert withdraw_entry(
        harness.conn, Withdrawal(older, harness.approver, "DATA_ERROR", None)
    )
    harness.conn.commit()
    issuers, truncated = _prepared(harness, uuid4())
    assert (issuers, truncated) == ([], False)


def test_the_filed_badge_follows_the_deliverable_publication(harness: _Harness) -> None:
    """Spec B4: Filed once the run's deliverable is filed, not when it is
    saved or frozen."""
    conn = harness.conn
    run = start_run(conn, harness.case_id)
    _entry(harness, "ACME", "2026-06-30", run_id=run)
    # Another run of the same case, never filed: the badge is the run's own.
    _entry(harness, "ZETA", "2026-06-30")

    def filed() -> bool:
        assert _prepared_issuer(harness, "ZETA").displayed.filed is False
        return _prepared_issuer(harness, "ACME").displayed.filed

    revision = uuid4()
    conn.execute(
        "INSERT INTO deliverable_revisions"
        " (revision_id, case_id, run_id, payload_sha256, saved_by)"
        " VALUES (%s, %s, %s, %s, %s)",
        (revision, harness.case_id, run, "a" * 64, harness.approver),
    )
    conn.commit()
    assert filed() is False
    conn.execute(
        "INSERT INTO deliverable_publications"
        " (revision_id, case_id, payload_sha256, frozen_by) VALUES (%s, %s, %s, %s)",
        (str(revision), harness.case_id, "a" * 64, harness.approver),
    )
    conn.commit()
    assert filed() is False
    conn.execute(
        "UPDATE deliverable_publications SET filed_by = %s, filed_at = now()"
        " WHERE revision_id = %s",
        (uuid4(), str(revision)),
    )
    conn.commit()
    assert filed() is True


def test_a_withdrawn_pinned_source_flags_the_entry(harness: _Harness) -> None:
    """Spec B8: a source pinned to the entry's run and withdrawn from the case
    flags the entry; the entry itself is not withdrawn."""
    pinned = _entry(harness, "ACME", "2026-06-30", run_id=harness.run_id)
    # A run with no pinned source set has nothing to withdraw.
    unpinned = _entry(harness, "ZETA", "2026-06-30")

    def flags() -> dict[UUID, bool]:
        issuers, _ = _prepared(harness, uuid4())
        return {
            issuer.displayed.entry_id: issuer.displayed.sources_withdrawn
            for issuer in issuers
        }

    assert flags() == {pinned: False, unpinned: False}
    withdraw_source(
        harness.conn,
        case_id=harness.case_id,
        source_id=harness.source_id,
        actor_id=harness.approver,
    )
    harness.conn.commit()
    assert flags() == {pinned: True, unpinned: False}
    acme = _prepared_issuer(harness, "ACME")
    assert acme.displayed.withdrawn_at is None


def test_prepared_entry_actions_follow_live_case_standing_and_global_role(
    harness: _Harness,
) -> None:
    older = _entry(harness, "ACME", "2026-03-31")
    newer = _entry(harness, "ACME", "2026-06-30")
    writer = member(harness.conn, harness.case_id)
    reader = member(harness.conn, harness.case_id, Standing.READER)

    def actions(user: UUID, role: GlobalRole = GlobalRole.ANALYST) -> list[str]:
        [issuer], _ = _prepared(harness, user, role)
        return [str(action) for action in issuer.displayed.actions]

    assert actions(writer) == ["WITHDRAW_BOOK_ENTRY"]
    assert actions(harness.approver) == ["WITHDRAW_BOOK_ENTRY"]
    assert actions(reader) == []
    assert actions(writer, GlobalRole.READER) == []
    assert actions(uuid4()) == []
    assert withdraw_entry(harness.conn, Withdrawal(newer, writer, "DATA_ERROR", None))
    harness.conn.commit()
    [issuer], _ = _prepared(harness, writer)
    assert issuer.displayed.entry_id == older
    assert issuer.displayed.actions == ["WITHDRAW_BOOK_ENTRY"]
    assert issuer.history[0].entry_id == newer
    assert issuer.history[0].actions == []


def test_book_catalogue_matches_the_model_lines_and_stored_entry_metrics(
    client: TestClient,
    harness: _Harness,
) -> None:
    _complete(harness)
    _entry(harness, "ACME", "2026-06-30", run_id=harness.run_id)
    response = client.get(
        f"/api/v1/cases/{harness.case_id}/model?run={harness.run_id}",
        headers=_as(harness.approver),
    )
    harness.conn.rollback()
    assert response.status_code == 200
    catalogue = model_read.book_catalogue()
    selected = [
        line
        for line in response.json()["body"]["lines"]
        if line["line_id"].startswith("metric:")
        or line["line_id"] in model_read.BOOK_LINES
    ]
    assert [(m.line_id, m.label, m.unit) for m in catalogue] == [
        (line["line_id"], line["label"], line["unit"]) for line in selected
    ]
    entry = _prepared_issuer(harness, "ACME").displayed
    assert set(entry.metrics["LTM"]) <= {m.line_id for m in catalogue}
    assert {(m.line_id, m.label, m.unit) for m in catalogue} >= {
        ("revenue", "Total revenue", "MONEY"),
        ("metric:net_leverage_adjusted", "Net leverage, adjusted EBITDA", "MULTIPLE"),
    }

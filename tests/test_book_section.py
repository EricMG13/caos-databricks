"""The Book read v2 over stored book entries (Plan 3 Task 3; spec B1, B2, B4,
B7, B8, B15).

Desk-wide: every signed-in viewer sees every issuer, standing or none. An
issuer's row is its newest live entry by `(analysis_date, added_at,
entry_seq)`; every other entry of the issuer, withdrawn ones included, is its
history, newest first. The read computes no figure: each entry serves what
the Add to Book command stored.
"""

from __future__ import annotations

from datetime import date
from uuid import UUID, uuid4

import pytest
from command_fixtures import command_headers, member
from fastapi.testclient import TestClient
from test_analysis_section import _as, _CountingConnection, _serving
from test_book_entries import CLASSIFIED, added, client, harness
from test_execution_freshness import _Harness
from test_model_section import forecast_route, route

from caos.api.app import app, store_connection
from caos.api.reads import book as book_read
from caos.api.reads import model as model_read
from caos.api.wire import (
    BookDocument,
    BookEntryView,
    BookIssuerView,
    BookMetricView,
    SectionNote,
)
from caos.boundary_text import BoundaryText
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
from caos.store.members import Standing
from caos.store.runs import create_case, start_run

__all__ = ["added", "client", "forecast_route", "harness", "route"]

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


def _issuer(document: BookDocument, key: str) -> BookIssuerView:
    [issuer] = [issuer for issuer in document.body.issuers if issuer.issuer_key == key]
    return issuer


def test_every_viewer_sees_every_issuer(
    added: tuple[UUID, str, UUID], client: TestClient, harness: _Harness
) -> None:
    """Spec B2: a viewer with no standing on either case sees both issuers,
    and the entry the command stored is served as it was stored."""
    entry_id, digest, writer = added
    other = create_case(harness.conn, BoundaryText.of("Another desk's credit"))
    harness.conn.commit()
    _entry(harness, "ZETA", "2026-06-30", case_id=other)
    stranger = uuid4()

    document = _book(client, harness, stranger)
    assert document.chrome.subject is None
    assert (document.status, document.observed_empty, document.notes) == (
        "complete",
        False,
        [],
    )
    assert [issuer.issuer_key for issuer in document.body.issuers] == ["ACME", "ZETA"]
    acme = _issuer(document, "ACME")
    assert acme.history == []
    shown: BookEntryView = acme.displayed
    assert (shown.entry_id, shown.case_id, shown.run_id) == (
        entry_id,
        harness.case_id,
        harness.run_id,
    )
    assert (shown.issuer_id, shown.issuer_name) == ("ACME", "Acme Holdings plc")
    assert (shown.reporting_period, shown.analysis_date) == ("FY2025", "2026-09-08")
    assert shown.route == "FULL_CREDIT_32/RELATIVE_VALUE"
    assert (shown.filed, shown.sources_withdrawn) == (False, False)
    stated = {name: getattr(shown, name) for name in CLASSIFIED}
    assert stated == CLASSIFIED
    # Ba2, BB and BB-: the middle notch, 12, is BB (spec B6).
    assert (shown.composite, shown.composite_bucket, shown.composite_notch) == (
        "BB",
        "BB",
        12,
    )
    # Audit N1: the entry's own stored digest, which Withdraw is bound to.
    assert shown.snapshot_sha256 == digest
    row = harness.conn.execute(
        "SELECT metrics, limitations, added_at FROM book_entries WHERE entry_id = %s",
        (entry_id,),
    ).fetchone()
    harness.conn.rollback()
    assert row is not None
    stored, limitations, added_at = row
    # Every metrics leaf is a figure; a projected basis' year is served apart.
    year = stored["BASE_FY1"].pop("fiscal_year")
    assert shown.fiscal_years == {"BASE_FY1": year}
    assert shown.metrics == stored
    assert shown.limitations == limitations
    assert (shown.currency, shown.unit) == ("USD", "MILLIONS")
    # The store holds no person's name, so the entry serves none.
    assert "added_by_name" not in BookEntryView.model_fields
    assert shown.added_at == added_at
    assert (shown.withdrawn_at, shown.withdrawal_reason, shown.withdrawal_note) == (
        None,
        None,
        None,
    )
    assert writer != stranger

    # The column chooser's metrics are the Model's own book lines, in the
    # Model's order, with its labels and units.
    model = client.get(
        f"/api/v1/cases/{harness.case_id}/model?run={harness.run_id}",
        headers=_as(harness.approver),
    ).json()["body"]
    harness.conn.rollback()
    catalogue: list[BookMetricView] = document.body.metric_catalogue
    assert [metric.line_id for metric in catalogue] == [
        line["line_id"] for line in model["lines"] if line["line_id"] in stored["LTM"]
    ]
    assert [metric.line_id for metric in catalogue] == [
        metric.line_id for metric in model_read.book_catalogue()
    ]
    assert {(m.line_id, m.label, m.unit) for m in catalogue} >= {
        ("revenue", "Total revenue", "MONEY"),
        ("metric:net_leverage_adjusted", "Net leverage, adjusted EBITDA", "MULTIPLE"),
    }


def test_an_issuers_row_is_its_newest_live_entry_by_analysis_date(
    client: TestClient, harness: _Harness
) -> None:
    """Spec B1, B4: one row per issuer key, whatever the spelling; the newest
    analysis date displays, then the later add, and the rest are history,
    newest first."""
    march = _entry(harness, "acme ", "2026-03-31")
    june = _entry(harness, "ACME", "2026-06-30")
    june_later = _entry(harness, " Acme", "2026-06-30")
    # Added last, but analysed earliest: it never displays.
    december = _entry(harness, "ACME", "2025-12-31")

    [issuer] = _book(client, harness, uuid4()).body.issuers
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
    client: TestClient, harness: _Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    for issuer in ("ALPHA", "BRAVO", "CHARLIE"):
        _entry(harness, issuer, "2026-06-30")
    monkeypatch.setattr(book_read, "BOOK_ISSUERS_MAX", 2)
    document = _book(client, harness, uuid4())
    assert [i.issuer_key for i in document.body.issuers] == ["ALPHA", "BRAVO"]
    assert (document.status, document.notes) == (
        "partial",
        [SectionNote.LIST_TRUNCATED],
    )


def test_history_past_the_bound_is_cut_and_said_so(
    client: TestClient, harness: _Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(book_read, "BOOK_HISTORY_MAX", 1)
    newest = _entry(harness, "ACME", "2026-06-30")
    middle = _entry(harness, "ACME", "2026-03-31")
    document = _book(client, harness, uuid4())
    [issuer] = document.body.issuers
    assert (issuer.displayed.entry_id, [e.entry_id for e in issuer.history]) == (
        newest,
        [middle],
    )
    assert (document.status, document.notes) == ("complete", [])

    _entry(harness, "ACME", "2025-12-31")
    document = _book(client, harness, uuid4())
    [issuer] = document.body.issuers
    assert [entry.entry_id for entry in issuer.history] == [middle]
    assert (document.status, document.notes) == (
        "partial",
        [SectionNote.LIST_TRUNCATED],
    )


def test_a_withdrawn_entry_moves_to_history_and_the_previous_one_displays(
    client: TestClient, harness: _Harness
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

    [issuer] = _book(client, harness, uuid4()).body.issuers
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
    document = _book(client, harness, uuid4())
    assert (document.body.issuers, document.observed_empty) == ([], True)


def test_the_filed_badge_follows_the_deliverable_publication(
    client: TestClient, harness: _Harness
) -> None:
    """Spec B4: Filed once the run's deliverable is filed, not when it is
    saved or frozen."""
    conn = harness.conn
    run = start_run(conn, harness.case_id)
    _entry(harness, "ACME", "2026-06-30", run_id=run)
    # Another run of the same case, never filed: the badge is the run's own.
    _entry(harness, "ZETA", "2026-06-30")

    def filed() -> bool:
        document = _book(client, harness, uuid4())
        assert _issuer(document, "ZETA").displayed.filed is False
        return _issuer(document, "ACME").displayed.filed

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


def test_a_withdrawn_pinned_source_flags_the_entry(
    client: TestClient, harness: _Harness
) -> None:
    """Spec B8: a source pinned to the entry's run and withdrawn from the case
    flags the entry; the entry itself is not withdrawn."""
    pinned = _entry(harness, "ACME", "2026-06-30", run_id=harness.run_id)
    # A run with no pinned source set has nothing to withdraw.
    unpinned = _entry(harness, "ZETA", "2026-06-30")

    def flags() -> dict[UUID, bool]:
        document = _book(client, harness, uuid4())
        return {
            issuer.displayed.entry_id: issuer.displayed.sources_withdrawn
            for issuer in document.body.issuers
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
    acme = _issuer(_book(client, harness, uuid4()), "ACME")
    assert acme.displayed.withdrawn_at is None


def test_the_book_reads_within_its_declared_io_budget(
    client: TestClient, harness: _Harness
) -> None:
    """The store's `now()` and one query over every entry: constant in the
    issuers and entries served, and no blob."""
    for issuer, day in (("ACME", "03-31"), ("ACME", "06-30"), ("ZETA", "06-30")):
        _entry(harness, issuer, f"2026-{day}")
    counter = _CountingConnection(harness.conn)
    app.dependency_overrides[store_connection] = _serving(counter)
    response = client.get(PATH, headers=_as(uuid4()))
    harness.conn.rollback()
    assert response.status_code == 200, response.json()
    assert len(response.json()["body"]["issuers"]) == 2
    assert counter.executed == book_read.IO_BUDGET == 2
    assert not hasattr(book_read, "BLOB_BUDGET")


@pytest.mark.parametrize("path", [PATH, f"{PATH}?case=x"])
def test_the_book_refuses_an_anonymous_request(client: TestClient, path: str) -> None:
    assert client.get(path).status_code == 401


def test_an_entry_offers_withdraw_only_to_a_writer_member_of_its_case(
    added: tuple[UUID, str, UUID], client: TestClient, harness: _Harness
) -> None:
    """Ruling: `actions` on a live entry names WITHDRAW_BOOK_ENTRY for a
    WRITER-or-above member of the entry's case with a global role that may
    write; a READER member, a stranger and a withdrawn entry get none."""
    entry_id, digest, writer = added
    reader = member(harness.conn, harness.case_id, Standing.READER)

    def actions(user: UUID, role: str = "ANALYST") -> list[str]:
        response = client.get(PATH, headers=_as(user, role))
        harness.conn.rollback()
        document = BookDocument.model_validate(response.json())
        return [str(a) for a in _issuer(document, "ACME").displayed.actions]

    assert actions(writer) == ["WITHDRAW_BOOK_ENTRY"]
    assert actions(harness.approver) == ["WITHDRAW_BOOK_ENTRY"]
    assert actions(reader) == []
    assert actions(writer, "READER") == []
    assert actions(uuid4()) == []
    body = {"snapshot_sha256": digest, "reason": "DATA_ERROR", "note": None}
    answer = client.post(
        f"/api/v1/cases/{harness.case_id}/book-entries/{entry_id}/withdrawal",
        headers=command_headers(writer),
        json=body,
    )
    harness.conn.rollback()
    assert answer.status_code == 200, answer.text
    document = BookDocument.model_validate(
        client.get(PATH, headers=_as(writer, "ANALYST")).json()
    )
    harness.conn.rollback()
    assert document.body.issuers == []


@pytest.mark.parametrize("route", ["owned-model"], indirect=True)
def test_owned_model_real_add_replay_stale_and_stored_book_equality(
    client: TestClient,
    harness: _Harness,
) -> None:
    from copy import deepcopy

    from test_book_entries import _actions, _add, _entries
    from test_model_section import _complete, _get, _OwnedModelCompletions, _path

    _complete(harness, _OwnedModelCompletions(harness.source_id))
    writer = member(harness.conn, harness.case_id, Standing.WRITER)
    body = _get(client, harness)["body"]
    stale = _add(client, harness, writer, {**CLASSIFIED, "snapshot_sha256": "0" * 64})
    assert stale.status_code == 409
    assert _entries(harness.conn, harness.run_id) == 0
    assert _actions(harness.conn, harness.case_id).count("BOOK_ENTRY_ADDED") == 0
    request = {**CLASSIFIED, "snapshot_sha256": body["snapshot_sha256"]}
    headers = command_headers(writer, key=uuid4())
    added = _add(client, harness, writer, request, headers)
    assert added.status_code == 201, added.json()
    replayed = _add(client, harness, writer, request, headers)
    assert replayed.status_code == 201
    assert replayed.headers["idempotency-replayed"] == "true"
    assert replayed.json() == added.json()
    assert _entries(harness.conn, harness.run_id) == 1
    assert _actions(harness.conn, harness.case_id).count("BOOK_ENTRY_ADDED") == 1
    receipts = harness.conn.execute(
        "SELECT count(*) FROM command_requests"
        " WHERE scope=%s AND command='ADD_TO_BOOK'",
        (harness.case_id,),
    ).fetchone()
    harness.conn.rollback()
    assert receipts == (1,)
    row = harness.conn.execute(
        "SELECT metrics, limitations, snapshot_sha256 FROM book_entries"
        " WHERE run_id=%s",
        (harness.run_id,),
    ).fetchone()
    harness.conn.rollback()
    assert row is not None
    metrics, limitations, digest = row
    assert (
        metrics["BASE_FY1"]["cash_closing"],
        metrics["DOWNSIDE_FY1"]["cash_closing"],
    ) == ("-22.000000", "-23.000000")
    assert (metrics["BASE_FY1"]["fcf"], metrics["DOWNSIDE_FY1"]["fcf"]) == (
        "45.000000",
        "44.000000",
    )
    assert limitations == body["limitations"]
    assert digest == body["snapshot_sha256"]
    for case in ("BASE", "DOWNSIDE"):
        index = [c["column_id"] for c in body["columns"]].index(f"{case}:2026")
        served = {
            line["line_id"]: line["cells"][index]["value"]
            for line in body["lines"]
            if line["line_id"] in model_read.BOOK_LINES
            or line["line_id"].startswith("metric:")
        }
        assert metrics[f"{case}_FY1"] == {**served, "fiscal_year": "2026"}
    stranger = uuid4()
    shown = _book(client, harness, stranger).body.issuers[0].displayed
    expected = deepcopy(metrics)
    years = {
        basis: values.pop("fiscal_year")
        for basis, values in expected.items()
        if "fiscal_year" in values
    }
    assert shown.metrics == expected
    assert shown.fiscal_years == years
    assert shown.limitations == limitations
    readonly = client.get(_path(harness), headers=_as(stranger))
    harness.conn.rollback()
    assert readonly.status_code == 200
    read_body = readonly.json()["body"]
    assert read_body["lines"] == body["lines"]
    assert read_body["limitations"] == body["limitations"]
    assert read_body["snapshot_sha256"] is None
    assert readonly.json()["chrome"]["actions"] == []

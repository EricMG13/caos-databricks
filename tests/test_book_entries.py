"""Book entries (Plan 3 Task 2): the `book_entries` store, and the Add to Book
and Withdraw commands -- digest-bound (invariant 5), exactly once per run
(invariant 6), WRITER+ on the case, and on the case's audit chain.

The run under test is the forecast route's (CP-1, CP-2G and CP-CF accepted),
the same one the Model section reads, so the entry's metrics are compared to
the Model read's cells for the same run (spec B10).
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, LiteralString
from uuid import UUID, uuid4

import psycopg
import pytest
from command_fixtures import command_headers, member
from fastapi.testclient import TestClient
from httpx2 import Response
from test_analysis_section import _as, client
from test_execution_freshness import _Harness
from test_forecast_route import harness, route
from test_model_section import _complete, pinned_deck
from test_run_commands import _Counting

from caos.api.app import app, store_connection
from caos.api.commands import book as book_command
from caos.api.identity import Actor, GlobalRole
from caos.api.reads import model as model_read
from caos.api.wire import (
    CLEARS,
    BookEntryAdded,
)
from caos.book.classification import notch
from caos.boundary_text import BoundaryText
from caos.calculators.credit_model.assemble import (
    credit_model,
)
from caos.calculators.credit_model.frame import Cell
from caos.digest import canonical_digest
from caos.refusals import RefusalCode
from caos.store import StoreConnection
from caos.store.audit import audit_trail, digest_of, verify_chain
from caos.store.book import (
    WITHDRAWAL_REASONS,
    Classification,
    EntryFigures,
    EntryState,
    EntrySubject,
    NewEntry,
    Withdrawal,
    accepted_artifacts,
    entry_in_case,
    entry_of_run,
    insert_entry,
    snapshot_sha256,
    withdraw_entry,
)
from caos.store.commands import payload_digests
from caos.store.members import Standing
from caos.store.runs import create_case, start_run

__all__ = ["client", "harness", "pinned_deck", "route"]


CLASSIFIED = {
    "sector": "Industrials",
    "industry_group": "Capital Goods",
    "domicile": "GB",
    "moodys": "Ba2",
    "moodys_outlook": "STABLE",
    "sp": "BB",
    "sp_outlook": "NEGATIVE",
    "fitch": "BB-",
    "fitch_outlook": None,
}


NAMED = (
    "revenue",
    "adjusted_ebitda",
    "total_debt",
    "net_debt",
    "liquidity",
    "fcf",
    "ffo",
    "cash_closing",
    "lease_adjusted_net_debt",
    "metric:adjusted_ebitda_margin",
)


def _add_path(harness: _Harness, run: object = None) -> str:
    return f"/api/v1/cases/{harness.case_id}/runs/{run or harness.run_id}/book-entry"


def _withdraw_path(case_id: object, entry_id: object) -> str:
    return f"/api/v1/cases/{case_id}/book-entries/{entry_id}/withdrawal"


def _model(client: TestClient, harness: _Harness) -> dict[str, Any]:
    response = client.get(
        f"/api/v1/cases/{harness.case_id}/model?run={harness.run_id}",
        headers=_as(harness.approver),
    )
    harness.conn.rollback()
    assert response.status_code == 200, response.text
    return dict(response.json()["body"])


def _add(
    client: TestClient,
    harness: _Harness,
    actor: UUID,
    body: dict[str, Any],
    headers: dict[str, str] | None = None,
) -> Response:
    """POST the add as `actor` (an ANALYST with a fresh key unless `headers`
    say otherwise)."""
    answer = client.post(
        _add_path(harness), headers=headers or command_headers(actor), json=body
    )
    harness.conn.rollback()
    return answer


def _withdraw(
    client: TestClient,
    harness: _Harness,
    actor: UUID,
    entry_id: object,
    body: dict[str, Any],
) -> Response:
    answer = client.post(
        _withdraw_path(harness.case_id, entry_id),
        headers=command_headers(actor),
        json=body,
    )
    harness.conn.rollback()
    return answer


def _refused(answer: Response, status: int, code: RefusalCode) -> None:
    assert (answer.status_code, answer.json()) == (
        status,
        {"code": code.value, "clears": CLEARS[code]},
    ), answer.text


def _entries(conn: StoreConnection, run_id: UUID) -> int:
    row = conn.execute(
        "SELECT count(*) FROM book_entries WHERE run_id = %s", (run_id,)
    ).fetchone()
    conn.rollback()
    assert row is not None
    return int(row[0])


def _actions(conn: StoreConnection, case_id: UUID) -> list[str]:
    actions = [entry.action for entry in audit_trail(conn, case_id)]
    conn.rollback()
    return actions


@pytest.fixture
def added(client: TestClient, harness: _Harness) -> tuple[UUID, str, UUID]:
    """A complete forecast run added by a WRITER: the entry, the digest and
    the writer."""
    _complete(harness)
    writer = member(harness.conn, harness.case_id, Standing.WRITER)
    digest = _model(client, harness)["snapshot_sha256"]
    answer = _add(client, harness, writer, {**CLASSIFIED, "snapshot_sha256": digest})
    assert answer.status_code == 201, answer.text
    return UUID(answer.json()["entry_id"]), str(digest), writer


def test_the_snapshot_digest_binds_the_artifacts_and_every_stored_figure() -> None:
    """Fix rounds 1 and 2 (M1, N3): the canonical JSON of the sorted
    `node:artifact` lines, the pinned deck, the currency and unit, the
    metrics and the limitations; each moves it."""
    pairs = [("b-node", "2" * 64), ("a-node", "1" * 64)]
    figures = EntryFigures(
        rate_deck_id=None,
        currency="USD",
        unit="MILLIONS",
        metrics={"LTM": {"revenue": "1000", "metric:net_leverage": None}},
        limitations=("no rate deck: BASE:2026",),
    )
    digest = snapshot_sha256(pairs, figures)
    assert digest == snapshot_sha256(reversed(pairs), figures)
    assert digest == canonical_digest(
        {
            "artifacts": [f"a-node:{'1' * 64}", f"b-node:{'2' * 64}"],
            "rate_deck_id": None,
            "currency": "USD",
            "unit": "MILLIONS",
            "metrics": {"LTM": {"revenue": "1000", "metric:net_leverage": None}},
            "limitations": ["no rate deck: BASE:2026"],
        }
    )
    moved = {
        snapshot_sha256(pairs[:1], figures),
        snapshot_sha256(pairs, replace(figures, rate_deck_id=str(uuid4()))),
        snapshot_sha256(pairs, replace(figures, currency="EUR")),
        snapshot_sha256(pairs, replace(figures, unit="THOUSANDS")),
        snapshot_sha256(pairs, replace(figures, metrics={"LTM": {"revenue": "1"}})),
        snapshot_sha256(pairs, replace(figures, limitations=())),
    }
    assert digest not in moved and len(moved) == 6


def test_a_writer_adds_a_complete_run_with_cp1_and_the_entry_stores_its_metrics(
    client: TestClient, harness: _Harness
) -> None:
    _complete(harness)
    conn = harness.conn
    writer = member(conn, harness.case_id, Standing.WRITER)
    body = _model(client, harness)
    digest = body["snapshot_sha256"]
    artifacts = accepted_artifacts(conn, harness.run_id)
    assert len(artifacts) == len(harness.route.nodes)
    conn.rollback()

    key = uuid4()
    request = {**CLASSIFIED, "snapshot_sha256": digest}
    answer = _add(client, harness, writer, request, command_headers(writer, key=key))
    assert answer.status_code == 201, answer.text
    entry_id = BookEntryAdded.model_validate(answer.json()).entry_id

    row = conn.execute(
        "SELECT case_id, run_id, issuer_key, issuer_id, issuer_name,"
        " reporting_period, analysis_date::text, route, sector, industry_group,"
        " domicile, moodys, moodys_outlook, sp, sp_outlook, fitch, fitch_outlook,"
        " composite_notch, snapshot_sha256, rate_deck_id, currency, unit, metrics,"
        " added_by, withdrawn_at, limitations FROM book_entries"
        " WHERE entry_id = %s",
        (entry_id,),
    ).fetchone()
    conn.rollback()
    assert row is not None
    (case_id, run_id, *subject, route_name) = row[:8]
    assert (case_id, run_id) == (harness.case_id, harness.run_id)
    # The run's pinned subject, as the Model shows it; the key upper-cased.
    shown = body["subject"]
    assert subject == [
        shown["issuer_id"].strip().upper(),
        *(
            shown[k]
            for k in ("issuer_id", "issuer_name", "reporting_period", "analysis_date")
        ),
    ]
    assert route_name == "FULL_CREDIT_32/RELATIVE_VALUE"
    assert list(row[8:17]) == [CLASSIFIED[k] for k in list(CLASSIFIED)]
    # Ba2 (12), BB (12) and BB- (13): the middle of three is 12.
    assert row[17] == 12 == notch("MOODYS", "Ba2")
    assert row[18] == digest
    assert (row[19], row[20], row[21]) == (None, "USD", "MILLIONS")
    metrics = row[22]
    assert (row[23], row[24]) == (writer, None)
    # The digest the Model served binds the store's artifacts, the run's
    # (absent) deck and exactly the figures stored (fix round 1, M1).
    assert digest == snapshot_sha256(
        artifacts, EntryFigures(None, "USD", "MILLIONS", metrics, tuple(row[25]))
    )
    # The Model's served limitations, kept with the figures (M3).
    assert row[25] == body["limitations"]

    # One basis per column the Model has: the LTM and the first Base year,
    # which names its fiscal year (L2).
    assert set(metrics) == {"LTM", "BASE_FY1"}
    assert metrics["BASE_FY1"].pop("fiscal_year") == "2026"
    columns = [c["column_id"] for c in body["columns"]]
    for basis, column_id in (("LTM", "LTM:FY2025"), ("BASE_FY1", "BASE:2026")):
        index = columns.index(column_id)
        served = {
            line["line_id"]: line["cells"][index]["value"]
            for line in body["lines"]
            if line["line_id"].startswith("metric:") or line["line_id"] in NAMED
        }
        # Spec B10: the entry is the run's Model, line for line.
        assert metrics[basis] == served, basis
    assert set(NAMED) <= set(metrics["LTM"])
    assert metrics["LTM"]["revenue"] == "1000"
    assert all(
        value is None or "E" not in value
        for basis in metrics.values()
        for value in basis.values()
    )

    # The same request under the same key replays the receipt, writing nothing.
    again = _add(client, harness, writer, request, command_headers(writer, key=key))
    assert again.status_code == 201
    assert again.headers["idempotency-replayed"] == "true"
    assert again.json() == answer.json()
    # A new key for a run that already has a live entry is stale.
    _refused(
        _add(client, harness, writer, request),
        409,
        RefusalCode.COMMAND_EXPECTATION_STALE,
    )
    assert _entries(conn, harness.run_id) == 1
    assert _actions(conn, harness.case_id).count("BOOK_ENTRY_ADDED") == 1


def test_a_reader_cannot_add(client: TestClient, harness: _Harness) -> None:
    _complete(harness)
    conn = harness.conn
    digest = _model(client, harness)["snapshot_sha256"]
    request = {**CLASSIFIED, "snapshot_sha256": digest}
    reader = member(conn, harness.case_id, Standing.READER)
    _refused(_add(client, harness, reader, request), 403, RefusalCode.NOT_AUTHORISED)
    # A WRITER on the case whose global role cannot write.
    writer = member(conn, harness.case_id, Standing.WRITER)
    _refused(
        _add(client, harness, writer, request, command_headers(writer, role="READER")),
        403,
        RefusalCode.NOT_AUTHORISED,
    )
    # No standing at all: the case is not there.
    _refused(_add(client, harness, uuid4(), request), 404, RefusalCode.CASE_NOT_FOUND)
    assert _entries(conn, harness.run_id) == 0
    assert "BOOK_ENTRY_ADDED" not in _actions(conn, harness.case_id)


def test_a_stale_snapshot_digest_is_refused(
    client: TestClient, harness: _Harness
) -> None:
    _complete(harness)
    conn = harness.conn
    writer = member(conn, harness.case_id, Standing.WRITER)
    digest = _model(client, harness)["snapshot_sha256"]
    other = EntryFigures(None, None, None, {}, ())
    for stale in ("0" * 64, snapshot_sha256([("CP-1", "f" * 64)], other)):
        _refused(
            _add(client, harness, writer, {**CLASSIFIED, "snapshot_sha256": stale}),
            409,
            RefusalCode.COMMAND_EXPECTATION_STALE,
        )
    # Not a digest at all is not a request.
    _refused(
        _add(client, harness, writer, {**CLASSIFIED, "snapshot_sha256": "x"}),
        400,
        RefusalCode.REQUEST_INVALID,
    )
    assert _entries(conn, harness.run_id) == 0
    assert "BOOK_ENTRY_ADDED" not in _actions(conn, harness.case_id)
    # The digest the actor reviewed is the one that adds.
    request = {**CLASSIFIED, "snapshot_sha256": digest}
    assert _add(client, harness, writer, request).status_code == 201


def _refuses(conn: StoreConnection, statement: LiteralString, *params: object) -> None:
    with pytest.raises(psycopg.Error):
        conn.execute(statement, params)
    conn.rollback()


def test_an_entry_cannot_be_deleted_or_edited_except_withdrawn_once(
    added: tuple[UUID, str, UUID], harness: _Harness
) -> None:
    entry_id, _digest, writer = added
    conn = harness.conn
    _refuses(conn, "DELETE FROM book_entries WHERE entry_id = %s", entry_id)
    _refuses(conn, "TRUNCATE book_entries")
    _refuses(
        conn,
        "UPDATE book_entries SET sector = 'Energy' WHERE entry_id = %s",
        entry_id,
    )
    _refuses(
        conn,
        "UPDATE book_entries SET metrics = '{}'::jsonb WHERE entry_id = %s",
        entry_id,
    )
    # A withdrawal that also edits the entry is not a withdrawal.
    _refuses(
        conn,
        "UPDATE book_entries SET withdrawn_at = now(), withdrawn_by = %s,"
        " withdrawal_reason = 'DATA_ERROR', domicile = 'US' WHERE entry_id = %s",
        writer,
        entry_id,
    )
    # Half a withdrawal: no reason, or no one who withdrew it.
    _refuses(
        conn,
        "UPDATE book_entries SET withdrawn_at = now(), withdrawn_by = %s"
        " WHERE entry_id = %s",
        writer,
        entry_id,
    )
    _refuses(
        conn,
        "UPDATE book_entries SET withdrawn_at = now(),"
        " withdrawal_reason = 'DATA_ERROR' WHERE entry_id = %s",
        entry_id,
    )
    # A reason the store does not know.
    _refuses(
        conn,
        "UPDATE book_entries SET withdrawn_at = now(), withdrawn_by = %s,"
        " withdrawal_reason = 'TIRED' WHERE entry_id = %s",
        writer,
        entry_id,
    )
    stamp = (
        "UPDATE book_entries SET withdrawn_at = now(), withdrawn_by = %s,"
        " withdrawal_reason = 'DATA_ERROR', withdrawal_note = %s"
        " WHERE entry_id = %s"
    )
    assert conn.execute(stamp, (writer, None, entry_id)).rowcount == 1
    conn.commit()
    # Once: a second stamp, or a change to the first, is refused.
    _refuses(conn, stamp, writer, "again", entry_id)
    _refuses(
        conn,
        "UPDATE book_entries SET withdrawal_note = 'later' WHERE entry_id = %s",
        entry_id,
    )
    _refuses(
        conn,
        "UPDATE book_entries SET withdrawn_at = NULL, withdrawn_by = NULL,"
        " withdrawal_reason = NULL WHERE entry_id = %s",
        entry_id,
    )
    _refuses(conn, "DELETE FROM book_entries WHERE entry_id = %s", entry_id)
    # An entry is inserted live, never already withdrawn: the same row for
    # another run inserts live and is refused withdrawn.
    other_run = start_run(conn, harness.case_id)
    conn.commit()
    insert: LiteralString = (
        "INSERT INTO book_entries (entry_id, case_id, run_id, issuer_key,"
        " issuer_id, issuer_name, reporting_period, analysis_date, route, sector,"
        " domicile, snapshot_sha256, metrics, added_by, withdrawn_at, withdrawn_by,"
        " withdrawal_reason) VALUES (%s, %s, %s, 'EXAMPLE', 'EXAMPLE',"
        " 'Example plc', 'FY2025', '2026-06-30', 'P/S', 'Energy', 'GB', %s,"
        " '{}'::jsonb, %s, %s, %s, %s)"
    )
    live = (uuid4(), harness.case_id, other_run, "a" * 64, writer)
    assert conn.execute(insert, (*live, None, None, None)).rowcount == 1
    conn.rollback()
    _refuses(conn, insert, *live, datetime.now(UTC), writer, "DATA_ERROR")
    row = conn.execute(
        "SELECT withdrawal_reason, withdrawn_by FROM book_entries WHERE entry_id = %s",
        (entry_id,),
    ).fetchone()
    conn.rollback()
    assert row == ("DATA_ERROR", writer)


def test_withdrawal_needs_a_note_for_other(
    added: tuple[UUID, str, UUID], client: TestClient, harness: _Harness
) -> None:
    entry_id, digest, writer = added
    conn = harness.conn
    for note in (None, "", "   "):
        body = {"snapshot_sha256": digest, "reason": "OTHER", "note": note}
        _refused(
            _withdraw(client, harness, writer, entry_id, body),
            400,
            RefusalCode.REQUEST_INVALID,
        )
    # The store holds the rule too: no OTHER without a note.
    _refuses(
        conn,
        "UPDATE book_entries SET withdrawn_at = now(), withdrawn_by = %s,"
        " withdrawal_reason = 'OTHER', withdrawal_note = ' ' WHERE entry_id = %s",
        writer,
        entry_id,
    )
    _refused(
        _withdraw(
            client,
            harness,
            writer,
            entry_id,
            {"snapshot_sha256": digest, "reason": "LATER", "note": None},
        ),
        400,
        RefusalCode.REQUEST_INVALID,
    )
    body = {"snapshot_sha256": digest, "reason": "OTHER", "note": "Wrong issuer id"}
    answer = _withdraw(client, harness, writer, entry_id, body)
    assert answer.status_code == 200, answer.text
    assert answer.json() == {"entry_id": str(entry_id)}
    row = conn.execute(
        "SELECT withdrawal_reason, withdrawal_note, withdrawn_by,"
        " withdrawn_at IS NOT NULL FROM book_entries WHERE entry_id = %s",
        (entry_id,),
    ).fetchone()
    conn.rollback()
    assert row == ("OTHER", "Wrong issuer id", writer, True)
    assert set(WITHDRAWAL_REASONS) == {
        "ADDED_IN_ERROR",
        "DATA_ERROR",
        "SUPERSEDED_SOURCES",
        "OTHER",
    }


def test_add_and_withdraw_write_the_case_audit_chain(
    added: tuple[UUID, str, UUID], client: TestClient, harness: _Harness
) -> None:
    entry_id, digest, writer = added
    conn = harness.conn
    body = {"snapshot_sha256": digest, "reason": "SUPERSEDED_SOURCES", "note": None}
    # Digest-bound: the entry the actor reviewed, or nothing.
    _refused(
        _withdraw(
            client, harness, writer, entry_id, {**body, "snapshot_sha256": "0" * 64}
        ),
        409,
        RefusalCode.COMMAND_EXPECTATION_STALE,
    )
    reader = member(conn, harness.case_id, Standing.READER)
    _refused(
        _withdraw(client, harness, reader, entry_id, body),
        403,
        RefusalCode.NOT_AUTHORISED,
    )
    for unknown in (uuid4(), "malformed"):
        _refused(
            _withdraw(client, harness, writer, unknown, body),
            404,
            RefusalCode.BOOK_ENTRY_NOT_FOUND,
        )
    # Another case's member cannot reach this case's entry through their case.
    other = create_case(conn, BoundaryText.of("Another issuer"))
    conn.commit()
    stranger = member(conn, other, Standing.ADMIN)
    answer = client.post(
        _withdraw_path(other, entry_id), headers=command_headers(stranger), json=body
    )
    conn.rollback()
    _refused(answer, 404, RefusalCode.BOOK_ENTRY_NOT_FOUND)

    answer = _withdraw(client, harness, writer, entry_id, body)
    assert answer.status_code == 200, answer.text
    _refused(
        _withdraw(client, harness, writer, entry_id, body),
        409,
        RefusalCode.BOOK_ENTRY_ALREADY_WITHDRAWN,
    )
    # One entry per run, for good: a withdrawn run is not added again.
    _refused(
        _add(client, harness, writer, {**CLASSIFIED, "snapshot_sha256": digest}),
        409,
        RefusalCode.BOOK_ENTRY_ALREADY_WITHDRAWN,
    )

    trail = audit_trail(conn, harness.case_id)
    conn.rollback()
    book = [entry for entry in trail if entry.action.startswith("BOOK_ENTRY_")]
    assert [(entry.action, entry.actor_id) for entry in book] == [
        ("BOOK_ENTRY_ADDED", writer),
        ("BOOK_ENTRY_WITHDRAWN", writer),
    ]
    assert verify_chain(conn, harness.case_id)
    added_payload = {"entry_id": str(entry_id), "snapshot_sha256": digest}
    withdrawn_payload = {**added_payload, "reason": "SUPERSEDED_SOURCES"}
    for entry, payload, command in (
        (book[0], added_payload, "ADD_TO_BOOK"),
        (book[1], withdrawn_payload, "WITHDRAW_BOOK_ENTRY"),
    ):
        digests = payload_digests(
            conn,
            scope=harness.case_id,
            actor_id=writer,
            payload=payload,
            commands=[command],
        )
        assert entry.payload_sha256 in digests - {digest_of(payload)}
    conn.rollback()


def test_add_and_withdraw_meet_their_declared_budgets(
    client: TestClient, harness: _Harness
) -> None:
    """The add reads what the Model read reads -- Analysis, the live-source
    pin and the deck -- plus its own fixed statements; the declaration is the
    Model's for the longest route plus those."""
    _complete(harness)
    conn = harness.conn
    writer = member(conn, harness.case_id, Standing.WRITER)
    counted = _Counting(conn)
    app.dependency_overrides[store_connection] = lambda: counted
    digest = _model(client, harness)["snapshot_sha256"]
    model_measured = counted.executed
    assert model_measured <= model_read.IO_BUDGET
    counted.executed = 0
    answer = _add(client, harness, writer, {**CLASSIFIED, "snapshot_sha256": digest})
    assert answer.status_code == 201, answer.text
    assert counted.executed == book_command.ADD_FIXED_IO + model_measured
    assert book_command.ADD_IO == book_command.ADD_FIXED_IO + model_read.IO_BUDGET
    counted.executed = 0
    entry_id = answer.json()["entry_id"]
    body = {"snapshot_sha256": digest, "reason": "ADDED_IN_ERROR", "note": None}
    assert _withdraw(client, harness, writer, entry_id, body).status_code == 200
    assert counted.executed == book_command.WITHDRAW_IO
    assert book_command.IO_BUDGET == max(book_command.ADD_IO, book_command.WITHDRAW_IO)
    assert book_command.BLOB_BUDGET == model_read.BLOB_BUDGET


def test_the_add_assembles_the_model_the_read_serves(
    added: tuple[UUID, str, UUID],
    harness: _Harness,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The entry's metrics are `book_metrics` of the model `run_model`
    assembles from the accepted CP-1 the Model read finds, with the default
    add-backs; a run with nothing accepted has no CP-1 to model."""
    from caos.api.reads.analysis import AnalysisQuery, read_analysis_without_tables

    entry_id, _digest, writer = added
    conn = harness.conn
    body = read_analysis_without_tables(
        AnalysisQuery(
            Actor(writer, GlobalRole.ANALYST),
            harness.case_id,
            harness.run_id,
            Standing.WRITER,
            conn,
            harness.blobs,
            harness.bundle,
        )
    ).body
    accepted = model_read.accepted_cp1(body)
    assert isinstance(accepted, model_read.AcceptedCp1)
    assert (accepted.run_id, accepted.cp1.module_id) == (harness.run_id, "CP-1")
    model_read.require_live_sources(conn, body)
    built = model_read.run_model(
        conn, harness.bundle, accepted, exclude_unrealised=False
    )
    assert isinstance(built, model_read.RunModel)
    assert built.inputs.exclude_unrealised is False
    served = model_read.model_grid(
        conn, harness.bundle, accepted, exclude_unrealised=False
    )
    assert isinstance(served, model_read.ServedModel)
    assert served.model == credit_model(built.inputs)
    stored = conn.execute(
        "SELECT metrics, limitations, snapshot_sha256 FROM book_entries"
        " WHERE entry_id = %s",
        (entry_id,),
    ).fetchone()
    artifacts = accepted_artifacts(conn, harness.run_id)
    conn.rollback()
    figures = model_read.entry_figures(served)
    assert figures.metrics == model_read.book_metrics(served.model)
    assert figures.limitations == tuple(model_read.served_limitations(served))
    assert stored == (
        figures.metrics,
        list(figures.limitations),
        model_read.entry_snapshot(artifacts, served),
    )
    assert stored[2] == snapshot_sha256(artifacts, figures)
    assert model_read.accepted_cp1(body.model_copy(update={"handoffs": []})) is None
    # Past the grid's bounds the shared check serves no grid, and says why.
    monkeypatch.setattr(model_read, "MODEL_LINES_MAX", 1)
    assert model_read.model_grid(
        conn, harness.bundle, accepted, exclude_unrealised=False
    ) == model_read.NoGrid(model_read.GRID_OVERSIZE)
    conn.rollback()


def test_a_served_value_is_plain_or_withheld_past_the_wire_bound() -> None:
    assert model_read.served_value(Cell(Decimal("1.50"))) == "1.50"
    assert model_read.served_value(Cell(Decimal("1E+3"))) == "1000"
    assert model_read.served_value(Cell(None, "NOT_SOURCED")) is None
    assert model_read.served_value(Cell(Decimal("9" * 65))) is None


def test_the_store_inserts_an_entry_live_and_withdraws_it_once(
    case: tuple[StoreConnection, UUID],
) -> None:
    conn, case_id = case
    run_id = start_run(conn, case_id)
    conn.commit()
    entry_id, adder = uuid4(), uuid4()
    insert_entry(
        conn,
        NewEntry(
            entry_id=entry_id,
            case_id=case_id,
            run_id=run_id,
            subject=EntrySubject(" acme ", "Acme plc", "FY2025", "2026-09-08", "R/S"),
            classification=Classification(
                "Energy", "Energy", "US", None, None, "BB", "STABLE", None, None, 12
            ),
            snapshot_sha256="a" * 64,
            figures=EntryFigures(
                rate_deck_id=None,
                currency="USD",
                unit="MILLIONS",
                metrics={"LTM": {"revenue": "1000", "metric:net_leverage": None}},
                limitations=("no rate deck: BASE:2026",),
            ),
            added_by=adder,
        ),
    )
    conn.commit()
    live = EntryState(entry_id, "a" * 64, withdrawn=False)
    assert entry_of_run(conn, run_id) == live
    assert entry_in_case(conn, case_id, entry_id) == live
    assert entry_in_case(conn, uuid4(), entry_id) is None
    assert entry_of_run(conn, uuid4()) is None
    row = conn.execute(
        "SELECT issuer_key, issuer_id, metrics, limitations FROM book_entries"
        " WHERE entry_id = %s",
        (entry_id,),
    ).fetchone()
    assert row == (
        "ACME",
        " acme ",
        {"LTM": {"revenue": "1000", "metric:net_leverage": None}},
        ["no rate deck: BASE:2026"],
    )
    conn.rollback()
    withdrawal = Withdrawal(entry_id, adder, "ADDED_IN_ERROR", None)
    assert withdraw_entry(conn, withdrawal) is True
    conn.commit()
    assert withdraw_entry(conn, withdrawal) is False
    conn.rollback()
    assert entry_of_run(conn, run_id) == EntryState(entry_id, "a" * 64, withdrawn=True)
    conn.rollback()


def test_an_other_withdrawal_needs_a_note_a_reader_can_see(
    added: tuple[UUID, str, UUID], client: TestClient, harness: _Harness
) -> None:
    """L3: zero-width characters are no note; nor, in the store, is a tab."""
    entry_id, digest, writer = added
    conn = harness.conn
    for note in ("​⁠", "​ \t"):
        _refused(
            _withdraw(
                client,
                harness,
                writer,
                entry_id,
                {"snapshot_sha256": digest, "reason": "OTHER", "note": note},
            ),
            400,
            RefusalCode.REQUEST_INVALID,
        )
    _refuses(
        conn,
        "UPDATE book_entries SET withdrawn_at = now(), withdrawn_by = %s,"
        " withdrawal_reason = 'OTHER', withdrawal_note = E'\\t\\n' WHERE entry_id = %s",
        writer,
        entry_id,
    )


_RAW: LiteralString = (
    "INSERT INTO book_entries (entry_id, case_id, run_id, issuer_key, issuer_id,"
    " issuer_name, reporting_period, analysis_date, route,"
    " sector, domicile, snapshot_sha256, metrics, added_by, added_at)"
    " VALUES (%s, %s, %s, upper(trim(%s)), %s,"
    " 'Example plc', 'FY2025', '2026-06-30', 'P/S',"
    " 'Energy', 'US', %s, %s::jsonb, %s, %s::timestamptz)"
)

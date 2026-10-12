"""Book entries (Plan 3 Task 2): the `book_entries` store, and the Add to Book
and Withdraw commands -- digest-bound (invariant 5), exactly once per run
(invariant 6), WRITER+ on the case, and on the case's audit chain.

The run under test is the forecast route's (CP-1, CP-2G and CP-CF accepted),
the same one the Model section reads, so the entry's metrics are compared to
the Model read's cells for the same run (spec B10).
"""

from __future__ import annotations

import inspect
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, LiteralString, NoReturn, cast
from uuid import UUID, uuid4

import psycopg
import pytest
from command_fixtures import command_headers, member
from fastapi.testclient import TestClient
from httpx2 import Response
from psycopg import sql
from psycopg.errors import CheckViolation
from run_terminals import fail_run
from test_analysis_section import _as, client
from test_execution_freshness import _Harness
from test_forecast_route import harness, route
from test_model_section import _complete, pinned_deck
from test_run_commands import _Counting

from caos.api.app import app, store_connection
from caos.api.commands import book as book_command
from caos.api.identity import Actor, GlobalRole
from caos.api.reads import analysis as analysis_read
from caos.api.reads import model as model_read
from caos.api.wire import (
    CLEARS,
    MODEL_LINES_MAX,
    AddToBook,
    BookEntryAdded,
    WithdrawBookEntry,
)
from caos.book.classification import OUTLOOKS, notch
from caos.boundary_text import BoundaryText
from caos.calculators.credit_model.assemble import (
    CreditModel,
    ModelInputs,
    credit_model,
)
from caos.calculators.credit_model.frame import Case, Cell, Column, ColumnKind
from caos.digest import canonical_digest
from caos.graph.route import ResolvedRoute
from caos.refusals import Refusal, RefusalCode
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
    WithdrawalReason,
    accepted_artifacts,
    entry_in_case,
    entry_of_run,
    insert_entry,
    snapshot_sha256,
    withdraw_entry,
)
from caos.store.commands import payload_digests
from caos.store.gates import withdraw_source
from caos.store.members import Standing
from caos.store.runs import complete_run, create_case, start_run

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
# Each metric the brief names beside the `metric:` lines; the margin is the
# model's `metric:` line of that name.
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


def _lite_complete_run(harness: _Harness, tmp_path: Path) -> tuple[UUID, UUID]:
    """A COMPLETE LITE run of a second case, on the same connection: its
    route carries no CP-1, so nothing of it can join the Book."""
    from test_deliverable_canonical import LITE, _accept
    from test_execution_freshness import harness as make

    builder = cast(
        Callable[[tuple[StoreConnection, UUID], Path, ResolvedRoute], _Harness],
        inspect.unwrap(make),
    )
    case_id = create_case(harness.conn, BoundaryText.of("A screening"))
    harness.conn.commit()
    lite = builder((harness.conn, case_id), tmp_path / "lite", LITE)
    for module in ("CP-0", "CP-L10", "CP-5"):
        _accept(lite, module)
    assert complete_run(harness.conn, lite.run_id)
    harness.conn.commit()
    return case_id, lite.run_id


def test_a_running_or_failed_run_cannot_be_added(
    client: TestClient, harness: _Harness, tmp_path: Path
) -> None:
    conn = harness.conn
    writer = member(conn, harness.case_id, Standing.WRITER)
    # The harness run has not run: RUNNING, with nothing accepted.
    request = {**CLASSIFIED, "snapshot_sha256": "0" * 64}
    _refused(
        _add(client, harness, writer, request),
        409,
        RefusalCode.RUN_NOT_COMPLETE_FOR_BOOK,
    )
    failed = start_run(conn, harness.case_id)
    conn.commit()
    assert fail_run(conn, failed)
    conn.commit()
    answer = client.post(
        _add_path(harness, failed), headers=command_headers(writer), json=request
    )
    conn.rollback()
    _refused(answer, 409, RefusalCode.RUN_NOT_COMPLETE_FOR_BOOK)
    # A run of another case, or none at all, is not this case's run.
    other_case, lite_run = _lite_complete_run(harness, tmp_path)
    for run in (lite_run, uuid4(), "malformed"):
        answer = client.post(
            _add_path(harness, run), headers=command_headers(writer), json=request
        )
        conn.rollback()
        _refused(answer, 404, RefusalCode.RUN_NOT_FOUND)
    # COMPLETE, but with no CP-1 accepted (a LITE route carries none).
    lite_writer = member(conn, other_case, Standing.WRITER)
    answer = client.post(
        f"/api/v1/cases/{other_case}/runs/{lite_run}/book-entry",
        headers=command_headers(lite_writer),
        json=request,
    )
    conn.rollback()
    _refused(answer, 409, RefusalCode.RUN_NOT_COMPLETE_FOR_BOOK)
    count = conn.execute("SELECT count(*) FROM book_entries").fetchone()
    conn.rollback()
    assert count == (0,)


def test_an_industry_group_outside_its_sector_is_refused(
    client: TestClient, harness: _Harness
) -> None:
    _complete(harness)
    conn = harness.conn
    writer = member(conn, harness.case_id, Standing.WRITER)
    digest = _model(client, harness)["snapshot_sha256"]
    valid = {**CLASSIFIED, "snapshot_sha256": digest}
    for fault in (
        {"industry_group": "Banks"},  # a Financials group under Industrials
        {"sector": "Shipping"},
        {"sector": "Shipping", "industry_group": None},
        {"domicile": "gb"},
        {"domicile": "G1"},
        {"moodys": "BB"},  # S&P's spelling on Moody's scale
        {"sp": "Ba2"},
        {"fitch": "D-"},
        {"fitch": None, "fitch_outlook": "STABLE"},  # an outlook, no rating
        {"moodys": None},  # Moody's outlook left without its rating
        {"sp_outlook": "BRIGHT"},
    ):
        _refused(
            _add(client, harness, writer, {**valid, **fault}),
            400,
            RefusalCode.REQUEST_INVALID,
        )
    # An undeclared field -- an adder, a metric -- is not a request either.
    _refused(
        _add(client, harness, writer, {**valid, "added_by": str(writer)}),
        400,
        RefusalCode.REQUEST_INVALID,
    )
    assert _entries(conn, harness.run_id) == 0
    # Unrated, no group: the least an analyst states.
    least = {
        **valid,
        **dict.fromkeys(
            ("industry_group", "moodys", "moodys_outlook", "sp", "sp_outlook"), None
        ),
    }
    assert _add(client, harness, writer, least).status_code == 201
    row = conn.execute(
        "SELECT composite_notch, industry_group FROM book_entries WHERE run_id = %s",
        (harness.run_id,),
    ).fetchone()
    conn.rollback()
    # Fitch's BB- alone is the composite.
    assert row == (13, None)


def test_every_agency_outlook_is_accepted_and_no_other(
    client: TestClient, harness: _Harness
) -> None:
    """Fix round 1 (Task 3): the outlook fields take the whole agency outlook
    vocabulary (spec B5), the longest of them included; anything else is
    refused."""
    for outlook in OUTLOOKS:
        for field in ("moodys_outlook", "sp_outlook", "fitch_outlook"):
            stated = {**CLASSIFIED, "fitch": "BB-", field: outlook}
            assert (
                getattr(
                    AddToBook.model_validate({**stated, "snapshot_sha256": "0" * 64}),
                    field,
                )
                == outlook
            )
    _complete(harness)
    conn = harness.conn
    writer = member(conn, harness.case_id, Standing.WRITER)
    digest = _model(client, harness)["snapshot_sha256"]
    valid = {**CLASSIFIED, "snapshot_sha256": digest, "fitch_outlook": "WATCH_POS"}
    for unknown in ("WATCH_UP", "DEVELOPING_X"):
        _refused(
            _add(client, harness, writer, {**valid, "sp_outlook": unknown}),
            400,
            RefusalCode.REQUEST_INVALID,
        )
    stated = {**valid, "moodys_outlook": "DEVELOPING", "sp_outlook": "WATCH_NEG"}
    assert _add(client, harness, writer, stated).status_code == 201
    row = conn.execute(
        "SELECT moodys_outlook, sp_outlook, fitch_outlook FROM book_entries"
        " WHERE run_id = %s",
        (harness.run_id,),
    ).fetchone()
    conn.rollback()
    assert row == ("DEVELOPING", "WATCH_NEG", "WATCH_POS")


def _refuses(
    conn: StoreConnection, statement: LiteralString | sql.Composed, *params: object
) -> None:
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
    # This reader is offered nothing, so the read paid no lookup of the run's
    # entry (`ENTRY_IO`, a writer's): the add pays the read as it stands.
    assert model_measured <= model_read.READ_IO
    counted.executed = 0
    answer = _add(client, harness, writer, {**CLASSIFIED, "snapshot_sha256": digest})
    assert answer.status_code == 201, answer.text
    assert counted.executed == book_command.ADD_FIXED_IO + model_measured
    assert book_command.ADD_IO == book_command.ADD_FIXED_IO + model_read.READ_IO
    counted.executed = 0
    entry_id = answer.json()["entry_id"]
    body = {"snapshot_sha256": digest, "reason": "ADDED_IN_ERROR", "note": None}
    assert _withdraw(client, harness, writer, entry_id, body).status_code == 200
    assert counted.executed == book_command.WITHDRAW_IO
    assert book_command.IO_BUDGET == max(book_command.ADD_IO, book_command.WITHDRAW_IO)
    assert book_command.BLOB_BUDGET == model_read.BLOB_BUDGET


def test_the_wire_names_no_authority_and_bounds_every_field() -> None:
    fields = set(AddToBook.model_fields)
    assert not fields & {"actor_id", "added_by", "case_id", "run_id", "metrics"}
    assert set(WithdrawBookEntry.model_fields) == {
        "snapshot_sha256",
        "reason",
        "note",
    }
    with pytest.raises(ValueError, match="note"):
        WithdrawBookEntry.model_validate(
            {"snapshot_sha256": "0" * 64, "reason": "OTHER", "note": "x" * 1001}
        )


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


def test_a_withdrawn_cited_source_refuses_the_add_as_the_model_does(
    client: TestClient, harness: _Harness
) -> None:
    _complete(harness)
    conn = harness.conn
    writer = member(conn, harness.case_id, Standing.WRITER)
    digest = _model(client, harness)["snapshot_sha256"]
    withdraw_source(
        conn,
        case_id=harness.case_id,
        source_id=harness.source_id,
        actor_id=harness.approver,
    )
    conn.commit()
    shown = client.get(
        f"/api/v1/cases/{harness.case_id}/model?run={harness.run_id}",
        headers=_as(harness.approver),
    )
    conn.rollback()
    assert shown.status_code != 200
    added = _add(client, harness, writer, {**CLASSIFIED, "snapshot_sha256": digest})
    # The add refuses with exactly the Model's refusal: no Model, no entry.
    assert (added.status_code, added.json()) == (shown.status_code, shown.json())
    assert _entries(conn, harness.run_id) == 0


@pytest.mark.parametrize(
    ("reason", "note"),
    [("ADDED_IN_ERROR", None), ("OTHER", "The analyst withdrew this entry.")],
)
def test_the_store_inserts_an_entry_live_and_withdraws_it_once(
    case: tuple[StoreConnection, UUID],
    reason: WithdrawalReason,
    note: str | None,
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
    for invalid_note in (None, "", " \t\n"):
        with pytest.raises(CheckViolation):
            conn.execute(
                "UPDATE book_entries SET withdrawn_at = now(), withdrawn_by = %s,"
                " withdrawal_reason = 'OTHER', withdrawal_note = %s"
                " WHERE entry_id = %s",
                (adder, invalid_note, entry_id),
            )
        conn.rollback()
        assert entry_of_run(conn, run_id) == live
        conn.rollback()
    withdrawal = Withdrawal(entry_id, adder, reason, note)
    assert withdraw_entry(conn, withdrawal) is True
    conn.commit()
    assert withdraw_entry(conn, withdrawal) is False
    conn.rollback()
    assert entry_of_run(conn, run_id) == EntryState(entry_id, "a" * 64, withdrawn=True)
    conn.rollback()


# Fix round 1 (task-2-review.md, task-2-audit.md): one test per finding.


def _cell(body: dict[str, Any], line_id: str, column_id: str) -> object:
    index = [c["column_id"] for c in body["columns"]].index(column_id)
    [line] = [line for line in body["lines"] if line["line_id"] == line_id]
    return line["cells"][index]["value"]


def test_the_digest_binds_the_default_views_figures_and_the_calculator(
    client: TestClient, harness: _Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    """M1: the excluded view shows other figures, so it serves no digest; a
    digest over the artifacts alone binds nothing the analyst saw; and a
    calculator that moved between the read and the add moves the figures,
    so the digest the analyst reviewed is stale."""
    _complete(harness)
    conn = harness.conn
    writer = member(conn, harness.case_id, Standing.WRITER)
    default = _model(client, harness)
    excluded = client.get(
        f"/api/v1/cases/{harness.case_id}/model?run={harness.run_id}"
        "&exclude_unrealised=1",
        headers=_as(harness.approver),
    ).json()["body"]
    conn.rollback()
    assert _cell(default, "adjusted_ebitda", "LTM:FY2025") != _cell(
        excluded, "adjusted_ebitda", "LTM:FY2025"
    )
    assert excluded["snapshot_sha256"] is None
    assert default["snapshot_sha256"] is not None
    from hashlib import sha256

    lines = sorted(f"{n}:{a}" for n, a in accepted_artifacts(conn, harness.run_id))
    conn.rollback()
    artifacts_only = sha256("\n".join(lines).encode()).hexdigest()
    real = credit_model

    def drifted(inputs: ModelInputs) -> CreditModel:
        model = real(inputs)
        return replace(
            model,
            lines=tuple(
                replace(
                    line,
                    cells=tuple(
                        cell
                        if cell.value is None
                        else replace(cell, value=cell.value * 2)
                        for cell in line.cells
                    ),
                )
                if line.line_id == "revenue"
                else line
                for line in model.lines
            ),
        )

    monkeypatch.setattr(model_read, "credit_model", drifted)
    for stale in (artifacts_only, default["snapshot_sha256"]):
        _refused(
            _add(client, harness, writer, {**CLASSIFIED, "snapshot_sha256": stale}),
            409,
            RefusalCode.COMMAND_EXPECTATION_STALE,
        )
    assert _entries(conn, harness.run_id) == 0


def test_the_add_refuses_where_the_model_serves_no_grid(
    client: TestClient, harness: _Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    """M2 / review Minor 1: past the grid's bounds the Model serves no grid
    and no digest, and the add refuses rather than store figures nobody saw;
    CP-1 tables the model cannot read are refused the same way."""
    _complete(harness)
    conn = harness.conn
    writer = member(conn, harness.case_id, Standing.WRITER)
    digest = _model(client, harness)["snapshot_sha256"]
    bound = MODEL_LINES_MAX
    monkeypatch.setattr(model_read, "MODEL_LINES_MAX", 1)
    shown = _model(client, harness)
    assert (shown["lines"], shown["snapshot_sha256"]) == ([], None)
    assert model_read.GRID_OVERSIZE in shown["limitations"]
    request = {**CLASSIFIED, "snapshot_sha256": digest}
    _refused(
        _add(client, harness, writer, request),
        409,
        RefusalCode.RUN_NOT_COMPLETE_FOR_BOOK,
    )
    monkeypatch.setattr(model_read, "MODEL_LINES_MAX", bound)

    def unreadable(*_args: object) -> NoReturn:
        raise Refusal(RefusalCode.HANDOFF_MALFORMED)

    monkeypatch.setattr(model_read, "cp1_registers", unreadable)
    assert _model(client, harness)["snapshot_sha256"] is None
    _refused(
        _add(client, harness, writer, request),
        409,
        RefusalCode.RUN_NOT_COMPLETE_FOR_BOOK,
    )
    assert _entries(conn, harness.run_id) == 0


def test_the_entry_keeps_the_limitations_the_model_serves(
    client: TestClient, harness: _Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    """M3: CP-2G's drivers unreadable hold the units flat; the Model says so,
    and so does the entry, beside the figures it qualifies."""
    _complete(harness)
    conn = harness.conn
    writer = member(conn, harness.case_id, Standing.WRITER)

    def unreadable(*_args: object) -> NoReturn:
        raise Refusal(RefusalCode.HANDOFF_MALFORMED)

    monkeypatch.setattr(model_read, "division_growth", unreadable)
    body = _model(client, harness)
    assert model_read.GROWTH_UNAVAILABLE in body["limitations"]
    answer = _add(
        client,
        harness,
        writer,
        {**CLASSIFIED, "snapshot_sha256": body["snapshot_sha256"]},
    )
    assert answer.status_code == 201, answer.text
    row = conn.execute(
        "SELECT limitations FROM book_entries WHERE run_id = %s", (harness.run_id,)
    ).fetchone()
    conn.rollback()
    assert row == (body["limitations"],)


def _column(
    kind: ColumnKind, year: int, case: Case | None = None, tag: str = ""
) -> Column:
    return Column(
        column_id=f"{case or kind}:{year}{tag}",
        kind=kind,
        label=f"{kind} {year}",
        period_id=f"FY{year}{tag}",
        fiscal_year=str(year),
        end_date=f"{year}-12-31",
        days=365,
        case=case,
    )


def test_the_bases_are_keyed_by_their_offset_from_the_base_year() -> None:
    """L2 / review Minor 3: FY+n counts from the last historical FY (the
    year before the first projected one without one), at most three each;
    a missing offset is omitted, never filled by the next year."""
    history = [
        _column("FY", 2023),
        _column("FY", 2024),
        _column("LTM", 2024),
        _column("LTM", 2025, tag="later"),
        _column("PF_LTM", 2024),
    ]
    projected = [
        _column("PROJECTED", year, case)
        for case in cast(tuple[Case, ...], ("BASE", "DOWNSIDE"))
        for year in (2025, 2026, 2027, 2028)
    ]
    columns = [*history, *projected]
    found = model_read.book_bases(columns)
    picked = {
        basis: columns[index].column_id for basis, (index, _year) in found.items()
    }
    assert picked == {
        "LTM": "LTM:2024",
        "PF_LTM": "PF_LTM:2024",
        "BASE_FY1": "BASE:2025",
        "BASE_FY2": "BASE:2026",
        "BASE_FY3": "BASE:2027",
        "DOWNSIDE_FY1": "DOWNSIDE:2025",
        "DOWNSIDE_FY2": "DOWNSIDE:2026",
        "DOWNSIDE_FY3": "DOWNSIDE:2027",
    }
    assert found["BASE_FY3"][1] == 2027 and found["LTM"][1] is None
    # A gap: FY+2, FY+4 and FY+6 are not FY+1 to FY+3.
    gapped = [
        _column("FY", 2024),
        *(_column("PROJECTED", y, "BASE") for y in (2026, 2028, 2030)),
    ]
    assert {
        basis: gapped[index].column_id
        for basis, (index, _y) in model_read.book_bases(gapped).items()
    } == {"BASE_FY2": "BASE:2026"}
    # No historical FY: the base is the year before the first projected one.
    bare = [_column("PROJECTED", y, "DOWNSIDE") for y in (2027, 2028)]
    assert set(model_read.book_bases(bare)) == {"DOWNSIDE_FY1", "DOWNSIDE_FY2"}


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


def _raw(
    conn: StoreConnection, case_id: UUID, issuer: str | None, metrics: str
) -> tuple[object, ...]:
    run_id = start_run(conn, case_id)
    conn.commit()
    return (uuid4(), case_id, run_id, issuer, issuer, "a" * 64, metrics, uuid4())


def test_the_store_holds_only_truthful_entries(
    case: tuple[StoreConnection, UUID],
) -> None:
    """L1, L4 and review Minor 2: the store stamps its own times, in order,
    and its own sequence; its figures are decimal text or null by basis; an
    entry names its issuer; and a withdrawal changes nothing else, however
    many columns the table later gains."""
    conn, case_id = case
    for metrics in (
        '{"LTM": {"revenue": 1.5}}',
        '{"LTM": {"fcf": "NaN"}}',
        '{"LTM": {"fcf": "1e3"}}',
        '{"LTM": [1, 2]}',
        '{"LTM": {"x": {"y": "1"}}}',
        "[]",
    ):
        _refuses(conn, _RAW, *_raw(conn, case_id, "X", metrics), "now")
    _refuses(conn, _RAW, *_raw(conn, case_id, None, "{}"), "now")
    # Review Minor 2 / fix round 2, N4: an entry names its issuer. A key
    # written as a literal beside no issuer id passes the key's own CHECK
    # (NULL), so only `issuer_id NOT NULL` refuses it.
    _refuses(
        conn,
        "INSERT INTO book_entries (entry_id, case_id, run_id, issuer_key,"
        " issuer_id, issuer_name, reporting_period, analysis_date, route,"
        " sector, domicile, snapshot_sha256, metrics, added_by)"
        " VALUES (%s, %s, %s, 'ANYTHING', NULL,"
        " 'Example plc', 'FY2025', '2026-06-30', 'P/S', 'Energy', 'US', %s,"
        " '{}'::jsonb, %s)",
        *_raw(conn, case_id, "X", "{}")[:3],
        "a" * 64,
        uuid4(),
    )
    # Fix round 1 (Task 3): an entry states its subject's name, period,
    # analysis date and route, as every add does; none may be missing.
    for column in ("issuer_name", "reporting_period", "analysis_date", "route"):
        _refuses(
            conn,
            sql.SQL(
                "INSERT INTO book_entries (entry_id, case_id, run_id, issuer_key,"
                " issuer_id, issuer_name, reporting_period, analysis_date, route,"
                " sector, domicile, snapshot_sha256, metrics, added_by)"
                " VALUES (%s, %s, %s, 'X', 'X', {}, 'Energy', 'US', %s,"
                " '{{}}'::jsonb, %s)"
            ).format(
                sql.SQL(", ").join(
                    sql.NULL if name == column else sql.Literal(value)
                    for name, value in (
                        ("issuer_name", "Example plc"),
                        ("reporting_period", "FY2025"),
                        ("analysis_date", "2026-06-30"),
                        ("route", "P/S"),
                    )
                )
            ),
            *_raw(conn, case_id, "X", "{}")[:3],
            "a" * 64,
            uuid4(),
        )
    first = _raw(conn, case_id, "X", '{"LTM": {"revenue": "-1.5", "fcf": null}}')
    conn.execute(_RAW, (*first, "2999-01-01"))
    conn.commit()
    second = _raw(conn, case_id, "X", "{}")
    conn.execute(_RAW, (*second, "1970-01-01"))
    conn.commit()
    rows = conn.execute(
        "SELECT entry_seq, added_at <= clock_timestamp(),"
        " added_at > clock_timestamp() - interval '1 minute'"
        " FROM book_entries WHERE entry_id = ANY(%s) ORDER BY added_at",
        ([first[0], second[0]],),
    ).fetchall()
    conn.rollback()
    assert [row[1:] for row in rows] == [(True, True), (True, True)]
    assert rows[0][0] < rows[1][0]
    # A sequence of its own choosing is not the one its insert drew.
    _refuses(
        conn,
        "INSERT INTO book_entries (entry_id, case_id, run_id, issuer_key, issuer_id,"
        " issuer_name, reporting_period, analysis_date, route,"
        " sector, domicile, snapshot_sha256, metrics, added_by, entry_seq)"
        " OVERRIDING SYSTEM VALUE VALUES (%s, %s, %s, 'X', 'X',"
        " 'Example plc', 'FY2025', '2026-06-30', 'P/S', 'Energy', 'US',"
        " %s, '{}'::jsonb, %s, 0)",
        *_raw(conn, case_id, "X", "{}")[:3],
        "a" * 64,
        uuid4(),
    )
    # A backdated stamp is the store's own time, after the entry's.
    conn.execute(
        "UPDATE book_entries SET withdrawn_at = '1970-01-01', withdrawn_by = %s,"
        " withdrawal_reason = 'DATA_ERROR' WHERE entry_id = %s",
        (uuid4(), first[0]),
    )
    conn.commit()
    stamped = conn.execute(
        "SELECT withdrawn_at >= added_at FROM book_entries WHERE entry_id = %s",
        (first[0],),
    ).fetchone()
    conn.rollback()
    assert stamped == (True,)
    # A column added later is still not the withdrawal's to change.
    conn.execute("ALTER TABLE book_entries ADD COLUMN later_flag text")
    with pytest.raises(psycopg.Error):
        conn.execute(
            "UPDATE book_entries SET withdrawn_at = now(), withdrawn_by = %s,"
            " withdrawal_reason = 'DATA_ERROR', later_flag = 'x' WHERE entry_id = %s",
            (uuid4(), second[0]),
        )
    conn.rollback()


# Fix round 2 (task-2-fix1-verify.md N2, N3).


def _stored_digest_recomputes(
    conn: StoreConnection, run_id: UUID
) -> tuple[object, bool]:
    """The entry's stored deck, and whether its stored digest is the digest
    of its own row: the run's artifacts and every figure it stores."""
    row = conn.execute(
        "SELECT rate_deck_id, currency, unit, metrics, limitations, snapshot_sha256"
        " FROM book_entries WHERE run_id = %s",
        (run_id,),
    ).fetchone()
    assert row is not None
    deck, currency, unit, metrics, limitations, digest = row
    figures = EntryFigures(
        None if deck is None else str(deck), currency, unit, metrics, tuple(limitations)
    )
    recomputed = snapshot_sha256(accepted_artifacts(conn, run_id), figures)
    conn.rollback()
    return deck, recomputed == digest


@pytest.mark.parametrize("projected", [True, False], ids=["with-cp-cf", "without"])
def test_the_entry_stores_the_runs_pinned_deck_and_its_digest_binds_it(
    pinned_deck: UUID,
    client: TestClient,
    harness: _Harness,
    monkeypatch: pytest.MonkeyPatch,
    projected: bool,
) -> None:
    """N2: the entry's deck is the run's pin, whether or not a projection
    read it (a route without CP-CF still pins the latest deck), and the
    digest it stores is the digest of its own row."""
    _complete(harness)
    if not projected:
        monkeypatch.setattr(model_read, "_request", lambda _body: None)
    writer = member(harness.conn, harness.case_id, Standing.WRITER)
    body = _model(client, harness)
    assert (body["rate_deck"] is None) is not projected
    answer = _add(
        client,
        harness,
        writer,
        {**CLASSIFIED, "snapshot_sha256": body["snapshot_sha256"]},
    )
    assert answer.status_code == 201, answer.text
    assert _stored_digest_recomputes(harness.conn, harness.run_id) == (
        pinned_deck,
        True,
    )


@pytest.mark.parametrize("moved", ["currency", "unit", "limitations"])
def test_a_calculator_that_moves_the_currency_unit_or_limitations_is_stale(
    client: TestClient,
    harness: _Harness,
    monkeypatch: pytest.MonkeyPatch,
    moved: str,
) -> None:
    """N3: a figure stored in another currency or unit, or under other
    limitations, is another figure: the digest the analyst reviewed no
    longer adds it."""
    _complete(harness)
    conn = harness.conn
    writer = member(conn, harness.case_id, Standing.WRITER)
    digest = _model(client, harness)["snapshot_sha256"]
    if moved == "limitations":
        served = model_read.served_limitations
        monkeypatch.setattr(
            model_read, "served_limitations", lambda grid: [*served(grid), "moved"]
        )
    else:
        real = credit_model

        def drifted(inputs: ModelInputs) -> CreditModel:
            model = real(inputs)
            if moved == "currency":
                return replace(model, currency="EUR")
            return replace(model, unit="THOUSANDS")

        monkeypatch.setattr(model_read, "credit_model", drifted)
    _refused(
        _add(client, harness, writer, {**CLASSIFIED, "snapshot_sha256": digest}),
        409,
        RefusalCode.COMMAND_EXPECTATION_STALE,
    )
    assert _entries(conn, harness.run_id) == 0


def _offered(
    client: TestClient,
    harness: _Harness,
    user: UUID,
    *,
    role: str = "ANALYST",
    query: str = "",
) -> list[str]:
    """The Model read's `chrome.actions` names for `user` holding `role`."""
    response = client.get(
        f"/api/v1/cases/{harness.case_id}/model?run={harness.run_id}{query}",
        headers=_as(user, role),
    )
    harness.conn.rollback()
    assert response.status_code == 200, response.text
    return [view["action"] for view in response.json()["chrome"]["actions"]]


def test_the_model_offers_add_to_book_only_where_an_add_would_be_judged(
    client: TestClient, harness: _Harness
) -> None:
    """Ruling: WRITER+ members, a COMPLETE run with an accepted CP-1, no
    entry, the default view -- and no one else."""
    conn = harness.conn
    writer = member(conn, harness.case_id, Standing.WRITER)
    # The run has not run: nothing to add.
    assert _offered(client, harness, writer) == []
    _complete(harness)
    reader = member(conn, harness.case_id, Standing.READER)
    assert _offered(client, harness, writer) == ["ADD_TO_BOOK"]
    assert _offered(client, harness, harness.approver) == ["ADD_TO_BOOK"]
    assert _offered(client, harness, reader) == []
    # A writer-standing member whose global role may not write.
    assert _offered(client, harness, writer, role="READER") == []
    # Not the view the entry would store.
    assert _offered(client, harness, writer, query="&exclude_unrealised=1") == []


def test_the_model_offers_no_add_where_the_run_pins_no_issuer_subject(
    client: TestClient, harness: _Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Audit L1: the command refuses a run with no issuer subject, so the read
    does not offer the add (a format-1 pin from before migration 0011)."""
    _complete(harness)
    writer = member(harness.conn, harness.case_id, Standing.WRITER)
    assert _offered(client, harness, writer) == ["ADD_TO_BOOK"]
    monkeypatch.setattr(analysis_read, "_subject", lambda *_args: None)
    assert _offered(client, harness, writer) == []


def test_the_model_offers_no_add_once_the_run_has_an_entry(
    added: tuple[UUID, str, UUID], client: TestClient, harness: _Harness
) -> None:
    """A live entry, and a withdrawn one (one entry per run, for good)."""
    entry_id, digest, writer = added
    assert _offered(client, harness, writer) == []
    body = {"snapshot_sha256": digest, "reason": "DATA_ERROR", "note": None}
    assert _withdraw(client, harness, writer, entry_id, body).status_code == 200
    assert _offered(client, harness, writer) == []


def test_a_granted_model_read_is_offered_no_add(
    added: tuple[UUID, str, UUID], client: TestClient, harness: _Harness
) -> None:
    """The desk-wide grant is read-only: no standing, no actions."""
    assert _offered(client, harness, uuid4(), role="ANALYST") == []


def test_the_offer_costs_a_writers_model_read_one_lookup_within_its_budget(
    client: TestClient, harness: _Harness
) -> None:
    """The run's entry is looked up only where an add could be offered: a
    reader of the same document pays the read alone."""
    _complete(harness)
    counted = _Counting(harness.conn)
    app.dependency_overrides[store_connection] = lambda: counted
    path = f"/api/v1/cases/{harness.case_id}/model?run={harness.run_id}"
    paid = []
    for role in ("READER", "ANALYST"):
        counted.executed = 0
        answer = client.get(path, headers=_as(harness.approver, role))
        harness.conn.rollback()
        assert answer.status_code == 200, answer.text
        paid.append(counted.executed)
    assert paid[1] == paid[0] + model_read.ENTRY_IO
    assert paid[0] <= model_read.READ_IO and paid[1] <= model_read.IO_BUDGET

"""Book entries (Plan 3 Task 2): the `book_entries` store, and the Add to Book
and Withdraw commands -- digest-bound (invariant 5), exactly once per run
(invariant 6), WRITER+ on the case, and on the case's audit chain.

The run under test is the forecast route's (CP-1, CP-2G and CP-CF accepted),
the same one the Model section reads, so the entry's metrics are compared to
the Model read's cells for the same run (spec B10).
"""

from __future__ import annotations

from dataclasses import replace
from decimal import Decimal
from typing import Any, LiteralString
from uuid import UUID, uuid4

import pytest
from command_fixtures import command_headers, member
from fastapi.testclient import TestClient
from httpx2 import Response
from psycopg.errors import CheckViolation
from test_analysis_section import _as, client
from test_execution_freshness import _Harness
from test_forecast_route import harness, route
from test_model_section import _complete, pinned_deck

from caos.api.identity import Actor, GlobalRole
from caos.api.reads import model as model_read
from caos.calculators.credit_model.assemble import (
    credit_model,
)
from caos.calculators.credit_model.frame import Cell
from caos.digest import canonical_digest
from caos.store import StoreConnection
from caos.store.book import (
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
from caos.store.members import Standing
from caos.store.runs import start_run

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


_RAW: LiteralString = (
    "INSERT INTO book_entries (entry_id, case_id, run_id, issuer_key, issuer_id,"
    " issuer_name, reporting_period, analysis_date, route,"
    " sector, domicile, snapshot_sha256, metrics, added_by, added_at)"
    " VALUES (%s, %s, %s, upper(trim(%s)), %s,"
    " 'Example plc', 'FY2025', '2026-06-30', 'P/S',"
    " 'Energy', 'US', %s, %s::jsonb, %s, %s::timestamptz)"
)

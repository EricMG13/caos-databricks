"""Book entries (Plan 3 Task 2): the `book_entries` store, and the Add to Book
and Withdraw commands -- digest-bound (invariant 5), exactly once per run
(invariant 6), WRITER+ on the case, and on the case's audit chain.

The run under test is the forecast route's (CP-1, CP-2G and CP-CF accepted),
the same one the Model section reads, so the entry's metrics are compared to
the Model read's cells for the same run (spec B10).
"""

from __future__ import annotations

from dataclasses import replace
from uuid import UUID, uuid4

from caos.digest import canonical_digest
from caos.store import StoreConnection
from caos.store.book import (
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
from caos.store.runs import start_run


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


def test_the_store_inserts_an_entry_live_and_withdraws_it_once(
    case: tuple[StoreConnection, UUID],
) -> None:
    conn, case_id = case
    run_id = start_run(conn, case_id)
    conn.commit()
    assert accepted_artifacts(conn, run_id) == ()
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

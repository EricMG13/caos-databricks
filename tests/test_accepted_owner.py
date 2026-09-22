"""One accepted result owner per run node (Phase 2 generation fencing).

`accepted_owner` is the store read every guard below goes through.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from time import monotonic
from uuid import UUID

import psycopg
import pytest
from conftest import reserve_at as reserve
from test_execution_freshness import (
    _DuringCompletion,
    _Harness,
    _provider,
    harness,
)
from test_loop_charges import ESTIMATE, MODEL, REPORTED, _Completions, route

import caos.store as store
from caos.boundary_text import BoundaryText
from caos.refusals import Refusal, RefusalCode
from caos.store import StoreConnection, apply_schema, connect
from caos.store.outcomes import (
    CallOutcome,
    accepted_owner,
    record_outcome,
    require_idle,
)
from caos.store.runs import (
    Accepted,
    accept_attempt,
    create_case,
    start_attempt,
    start_run,
)

__all__ = ["harness", "route"]


def _billed(harness: _Harness, conn: StoreConnection | None = None) -> UUID:
    conn = conn or harness.conn
    node = harness.route.nodes[0].route_node_id
    attempt = start_attempt(conn, harness.run_id, node)
    reserve(conn, attempt, ESTIMATE)
    record_outcome(
        conn,
        attempt_id=attempt,
        outcome=CallOutcome(REPORTED, MODEL, f"g{attempt.hex}"),
    )
    return attempt


def _accept(
    harness: _Harness, attempt: UUID, conn: StoreConnection | None = None
) -> object:
    # The canonical LITE pin accepts only with a record (§42.1).
    accepted = Accepted(
        harness.blobs.put(attempt.bytes),
        REPORTED,
        MODEL,
        f"g{attempt.hex}",
        record_sha256=harness.blobs.put(b"record" + attempt.bytes),
    )
    try:
        return accept_attempt(
            conn or harness.conn, attempt_id=attempt, accepted=accepted
        )
    except Refusal as refused:
        assert refused.__cause__ is None
        return refused.code


def _count(harness: _Harness, table: str) -> int:
    with connect(harness.url) as observer:
        row = observer.execute(f"SELECT count(*) FROM {table}").fetchone()
    assert row is not None
    return int(row[0])


def test_a_second_attempt_cannot_accept_an_already_accepted_node(
    harness: _Harness,
) -> None:
    first, second = _billed(harness), _billed(harness)
    assert _accept(harness, first) is True
    assert _accept(harness, second) == RefusalCode.NODE_ALREADY_ACCEPTED
    assert [_count(harness, t) for t in ("artifacts", "budget_ledger")] == [1, 2]


def test_a_completed_node_refuses_a_new_attempt(harness: _Harness) -> None:
    assert _accept(harness, _billed(harness)) is True
    with pytest.raises(Refusal, match=r"^NODE_ALREADY_ACCEPTED$"):
        start_attempt(
            harness.conn, harness.run_id, harness.route.nodes[0].route_node_id
        )
    assert _count(harness, "run_attempts") == 1


def test_an_attempt_whose_node_was_accepted_meanwhile_makes_no_call(
    harness: _Harness,
) -> None:
    node = harness.route.nodes[0]
    waiting = start_attempt(harness.conn, harness.run_id, node.route_node_id)
    reserve(harness.conn, waiting, ESTIMATE)
    assert _accept(harness, _billed(harness)) is True
    completion = _DuringCompletion(_Completions(harness.source_id), lambda: None)
    with pytest.raises(Refusal) as refused:
        _provider(harness, completion).execute(
            node.route_node_id, node.module_id, attempt_id=waiting
        )
    assert (refused.value.code, completion.calls) == (
        RefusalCode.NODE_ALREADY_ACCEPTED,
        0,
    )


def _waiting_on_locks(holder: StoreConnection, *waiters: StoreConnection) -> None:
    deadline = monotonic() + 3
    pids = [waiter.info.backend_pid for waiter in waiters]
    while monotonic() < deadline:
        row = holder.execute(
            "SELECT count(*) FROM pg_stat_activity"
            " WHERE pid = ANY(%s) AND wait_event_type = 'Lock'",
            (pids,),
        ).fetchone()
        if row == (len(pids),):
            return
    pytest.fail("acceptors did not both wait on the run lock")


def test_two_racing_connections_accept_exactly_one_result_and_keep_both_bills(
    harness: _Harness,
) -> None:
    """Both acceptors are provably waiting on the run lock before either runs."""
    from caos.store.events import lock_run

    attempts = [_billed(harness), _billed(harness)]
    with (
        connect(harness.url) as holder,
        connect(harness.url) as left,
        connect(harness.url) as right,
        ThreadPoolExecutor(max_workers=2) as pool,
    ):
        lock_run(holder, harness.run_id)
        futures = [
            pool.submit(_accept, harness, attempt, conn)
            for attempt, conn in zip(attempts, (left, right), strict=True)
        ]
        try:
            _waiting_on_locks(holder, left, right)
        finally:
            holder.commit()
        results = sorted(str(future.result(timeout=6)) for future in futures)
    assert results == ["NODE_ALREADY_ACCEPTED", "True"]
    assert [_count(harness, t) for t in ("artifacts", "budget_ledger")] == [1, 2]


def test_an_artifact_node_must_match_its_attempt(harness: _Harness) -> None:
    attempt = _billed(harness)
    with pytest.raises(psycopg.errors.IntegrityError):
        harness.conn.execute(
            "INSERT INTO artifacts (attempt_id, artifact_sha256, run_id, case_id,"
            " model, generation_id, route_node_id)"
            " VALUES (%s, %s, %s, %s, 'm', 'g', 'NOT-THE-ATTEMPTS-NODE')",
            (attempt, "a" * 64, harness.run_id, harness.case_id),
        )
    harness.conn.rollback()


def test_populated_upgrade_with_duplicate_node_artifacts_refuses_atomically(
    empty_database: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    with connect(empty_database) as conn:
        with monkeypatch.context() as patch:
            patch.setattr(store, "MIGRATIONS", store.MIGRATIONS[:8])
            apply_schema(conn)
        case_id = create_case(conn, BoundaryText.of("duplicate owners"))
        run = start_run(conn, case_id)
        conn.commit()
        for _ in range(2):
            attempt = conn.execute(
                "INSERT INTO run_attempts (attempt_id, run_id, route_node_id)"
                " VALUES (gen_random_uuid(), %s, 'RN-1') RETURNING attempt_id",
                (run,),
            ).fetchone()[0]  # type: ignore[index]
            conn.execute(
                "INSERT INTO artifacts (attempt_id, artifact_sha256, run_id, case_id,"
                " model, generation_id) VALUES (%s, %s, %s, %s, 'm', 'g')",
                (attempt, "a" * 64, run, case_id),
            )
        conn.commit()
        versions = conn.execute("SELECT count(*) FROM store_migrations").fetchone()
        with pytest.raises(Refusal, match=r"^STORE_SCHEMA_DRIFT$"):
            apply_schema(conn)
        assert (
            conn.execute("SELECT count(*) FROM store_migrations").fetchone() == versions
        )
        assert conn.execute("SELECT count(*) FROM artifacts").fetchone() == (2,)


def test_accepted_owner_names_the_attempt_that_owns_the_nodes_result(
    harness: _Harness,
) -> None:
    """The read every guard in this file goes through, asserted directly
    rather than only through the guards it serves. The file's own docstring
    has said so since it was written, and a docstring is not a test: this gate
    passed on that sentence until `check_tested.py` began resolving references
    through the AST.

    Joined through the attempt rather than `artifacts.route_node_id`, so an
    unaccepted node answers `None` and an accepted one answers the attempt
    that actually paid for it -- not merely some attempt of the run.
    """
    node = harness.route.nodes[0].route_node_id
    assert accepted_owner(harness.conn, harness.run_id, node) is None

    refused, owner = _billed(harness), _billed(harness)
    assert _accept(harness, owner) is True

    assert accepted_owner(harness.conn, harness.run_id, node) == owner
    assert owner != refused


def test_require_idle_refuses_a_caller_transaction_even_a_read_only_one(
    harness: _Harness,
) -> None:
    """Execution never adopts an active caller transaction. The read-only case
    is the one worth naming: a caller that has only *read* still holds a
    snapshot, and running an attempt inside it would pin execution to a view
    of the store taken before the attempt began.
    """
    idle = connect(harness.url)
    try:
        require_idle(idle)  # an idle connection passes by returning at all

        idle.execute("SELECT 1")  # a read alone opens the transaction
        with pytest.raises(Refusal) as caught:
            require_idle(idle)
        assert caught.value.code is RefusalCode.STORE_NOT_TRANSACTIONAL

        idle.rollback()
        idle.autocommit = True
        with pytest.raises(Refusal, match=r"^STORE_NOT_TRANSACTIONAL$"):
            require_idle(idle)
    finally:
        idle.close()

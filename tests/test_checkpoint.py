"""The checkpointer factory's guards: a strict serializer (SA-C2), set-up
serialised across processes (AR-20), a pool that is closed when set-up fails
(CR-2), pooled connections checked before use (DL-9) and a failed pooled
connect dropping the cached credential (AR-02)."""

from __future__ import annotations

import os
import threading
from pathlib import Path

import ormsgpack
import psycopg
import pytest
from langgraph.checkpoint.base import BaseCheckpointSaver
from psycopg_pool import ConnectionPool, PoolTimeout

from caos.graph import checkpoint
from caos.graph.build import initial_state
from caos.graph.checkpoint import (
    ALLOWED_TYPES,
    SETUP_LOCK_KEY,
    MintedConnection,
    checkpointer,
    close_checkpointer,
    serializer,
)
from caos.refusals import Refusal
from caos.store import lakebase

EXT_CONSTRUCTOR_SINGLE_ARG = 0  # LangGraph's tag for "import and call this"


def test_the_serializer_never_imports_what_a_checkpoint_row_names(
    tmp_path: Path,
) -> None:
    """SA-C2: the default serializer imports and calls any callable a row
    names. Ours allows the graph's own state and nothing else, so a crafted
    row loads as inert data."""
    serde = serializer()
    state = initial_state("run-1")
    assert serde.loads_typed(serde.dumps_typed(state)) == state
    assert ALLOWED_TYPES == (("caos.graph.build", "RunState"),)
    marker = tmp_path / "executed-by-checkpoint-load"
    crafted = ormsgpack.packb(
        ormsgpack.Ext(
            EXT_CONSTRUCTOR_SINGLE_ARG,
            ormsgpack.packb(("os", "system", f"touch {marker}")),
        )
    )
    with pytest.raises(Refusal, match=r"^INTERNAL_FAULT$"):
        serde.loads_typed(("msgpack", crafted))
    assert not marker.exists(), "the named callable never ran"


def test_concurrent_set_up_on_a_fresh_database_all_succeed(
    empty_database: str,
) -> None:
    """AR-20: two processes setting the checkpoint schema up used to race on
    the migration version and one lost its worker. The advisory lock
    serialises them."""
    assert SETUP_LOCK_KEY > 0
    savers: list[BaseCheckpointSaver[str]] = []
    failures: list[Exception] = []

    def one() -> None:
        try:
            savers.append(checkpointer(empty_database))
        except (psycopg.Error, Refusal) as failed:
            failures.append(failed)

    threads = [threading.Thread(target=one) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(60)
    for saver in savers:
        close_checkpointer(saver)
    assert failures == [] and len(savers) == 4


def test_a_pool_whose_set_up_fails_is_closed_before_the_refusal_leaves(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CR-2: the orphaned pool used to keep reconnecting, and minting, for the
    life of the process."""
    monkeypatch.setenv(lakebase.LAKEBASE_INSTANCE, "caos-lb")
    monkeypatch.setattr(
        checkpoint, "store_url", lambda: "postgresql://u:p@127.0.0.1:1/db"
    )
    monkeypatch.setattr(checkpoint, "POOL_TIMEOUT_SECONDS", 1.0)
    with pytest.raises(PoolTimeout):
        checkpointer()
    for thread in threading.enumerate():
        if thread.name.startswith("pool-"):
            thread.join(5)
    assert not [t.name for t in threading.enumerate() if t.name.startswith("pool-")]


def test_the_platform_pool_checks_connections_and_a_refused_connect_drops_the_token(
    empty_database: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """DL-9 and AR-02 on the pooled path."""
    monkeypatch.setenv(lakebase.LAKEBASE_INSTANCE, "caos-lb")
    monkeypatch.setattr(checkpoint, "store_url", lambda: empty_database)
    checked: list[int] = []
    real_check = ConnectionPool.check_connection

    def recording(conn: psycopg.Connection[object]) -> None:
        checked.append(1)
        real_check(conn)

    monkeypatch.setattr(ConnectionPool, "check_connection", staticmethod(recording))
    saver = checkpointer()
    try:
        pool = getattr(saver, "conn", None)
        assert isinstance(pool, ConnectionPool)
        with pool.connection() as conn:
            assert conn.execute("SELECT 1").fetchone() is not None
        assert checked, "a pooled connection is checked before it is handed out"
        assert os.environ.get(lakebase.LAKEBASE_INSTANCE) == "caos-lb"
    finally:
        close_checkpointer(saver)
    held = lakebase._Credential("token", float("inf"), float("inf"))
    monkeypatch.setattr(lakebase, "_CACHED", held)
    monkeypatch.setattr(
        checkpoint, "store_url", lambda: "postgresql://u:p@127.0.0.1:1/db"
    )
    with pytest.raises(psycopg.OperationalError):
        MintedConnection.connect(connect_timeout=1)
    assert lakebase._CACHED is None, "the failed connect dropped the credential"


def test_a_set_up_held_by_an_old_snapshot_refuses_in_time_and_heals(
    empty_database: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ST-4: LangGraph builds its indexes `CONCURRENTLY`, which waits on every
    older snapshot in the database. One open REPEATABLE READ session held
    set-up with no deadline, before uvicorn bound its port. The statement is
    bounded now, the refusal is typed, and the index build it cancelled is
    dropped and rebuilt valid by the next set-up."""
    import time

    monkeypatch.setattr(checkpoint, "SETUP_STATEMENT_SECONDS", 1.0)
    reader = psycopg.connect(empty_database, autocommit=False)
    try:
        reader.execute("BEGIN ISOLATION LEVEL REPEATABLE READ")
        reader.execute("SELECT 1")  # the snapshot is taken and held
        started = time.monotonic()
        with pytest.raises(Refusal, match=r"^STORE_UNAVAILABLE$"):
            checkpointer(empty_database)
        assert time.monotonic() - started < 10
    finally:
        reader.rollback()
        reader.close()


def test_a_set_up_lock_held_by_another_process_refuses_in_time(
    empty_database: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """CF-071: the sibling test above exercises _bounded_set_up's statement
    timeout, once inside the advisory lock. _set_up's own deadline -- polling
    for a lock another process already holds, never reaching the index build
    at all -- was the one STORE_UNAVAILABLE branch no test reached."""
    import time

    monkeypatch.setattr(checkpoint, "SETUP_LOCK_SECONDS", 0.3)
    monkeypatch.setattr(checkpoint, "SETUP_LOCK_POLL_SECONDS", 0.05)
    holder = psycopg.connect(empty_database, autocommit=True)
    try:
        holder.execute("SELECT pg_advisory_lock(%s)", (SETUP_LOCK_KEY,))
        started = time.monotonic()
        with pytest.raises(Refusal, match=r"^STORE_UNAVAILABLE$"):
            checkpointer(empty_database)
        assert time.monotonic() - started < 5
    finally:
        holder.execute("SELECT pg_advisory_unlock(%s)", (SETUP_LOCK_KEY,))
        holder.close()
    with psycopg.connect(empty_database, autocommit=True) as conn:
        held = conn.execute(
            # `pg_locks` is the whole server's: under `-n auto` other tests'
            # databases hold advisory locks of their own, so count this one's.
            "SELECT count(*) FROM pg_locks WHERE locktype = 'advisory'"
            " AND database = (SELECT oid FROM pg_database"
            " WHERE datname = current_database())"
        ).fetchone()
        assert held == (0,), "the refusal released the set-up lock"
    saver = checkpointer(empty_database)
    close_checkpointer(saver)
    with psycopg.connect(empty_database, autocommit=True) as conn:
        indexes = conn.execute(
            "SELECT c.relname, i.indisvalid FROM pg_index i"
            " JOIN pg_class c ON c.oid = i.indexrelid"
            " JOIN pg_namespace n ON n.oid = c.relnamespace"
            " WHERE n.nspname = %s AND c.relname LIKE %s ORDER BY 1",
            (checkpoint.SCHEMA, "%thread_id_idx"),
        ).fetchall()
    assert [valid for _name, valid in indexes] == [True, True, True]


def test_the_local_checkpointer_replaces_a_connection_the_server_ended(
    empty_database: str,
) -> None:
    """ST-13: off the platform the saver held one connection for the life of
    the process, so one ended session failed every later claim. It is a
    checked pool now, as on the platform."""
    from caos.graph.build import thread_config

    saver = checkpointer(empty_database)
    try:
        pool = getattr(saver, "conn", None)
        assert isinstance(pool, ConnectionPool)
        with psycopg.connect(empty_database, autocommit=True) as admin:
            admin.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity"
                " WHERE datname = current_database() AND pid <> pg_backend_pid()"
            )
        assert saver.get(thread_config("nobody")) is None, "a fresh session answers"
    finally:
        close_checkpointer(saver)


def test_a_checkpoint_row_the_host_never_writes_is_refused_not_loaded(
    empty_database: str,
) -> None:
    """ST-14: the allowlisted serializer still built LangGraph's "safe" types
    from a crafted row and LangChain objects from a `json` row; a row outside
    what the graph writes refuses `INTERNAL_FAULT`. And a node's failure is
    persisted as its class, never its message, which may quote a document."""
    import re

    from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer

    from caos.graph.build import RunState, build_graph, thread_config
    from caos.graph.route import ResolvedRoute, RouteNode
    from caos.graph.runtime import message_free

    serde = serializer()
    permissive = JsonPlusSerializer()
    for crafted in (re.compile("x"), {1, 2}, frozenset({3})):
        with pytest.raises(Refusal, match=r"^INTERNAL_FAULT$"):
            serde.loads_typed(permissive.dumps_typed(crafted))
    for kind in ("json", "pickle"):
        with pytest.raises(Refusal, match=r"^INTERNAL_FAULT$"):
            serde.loads_typed((kind, b"{}"))
    kept: list[object] = [None, b"raw", "text", 7, ["a", {"b": "c"}]]
    kept.append(RunState("r", {"n": "x"}))
    for value in kept:
        assert serde.loads_typed(serde.dumps_typed(value)) == value

    saver = checkpointer(empty_database)
    try:
        route = ResolvedRoute("p", "s", (RouteNode("CP-0", "CP-0", 0),), ())
        document = "EBITDA of USD 1,240.0m per page 3 of the borrower's accounts"

        def failing(route_node_id: str) -> str:
            with message_free():
                raise ValueError(document, route_node_id)

        graph = build_graph(
            route, node_pass=failing, finish=lambda: "COMPLETE", checkpointer=saver
        )
        with pytest.raises(ValueError) as raised:
            graph.invoke(RunState("run-1"), config=thread_config("run-1"))
        assert raised.value.args == (), "the class travels, the message does not"
        with psycopg.connect(empty_database, autocommit=True) as conn:
            written = conn.execute(
                f"SELECT blob FROM {checkpoint.SCHEMA}.checkpoint_writes"
            ).fetchall()
        assert written, "the failed node's write is there"
        assert not [row for row in written if b"EBITDA" in bytes(row[0])]
    finally:
        close_checkpointer(saver)

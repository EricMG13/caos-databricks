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
    loaded = serde.loads_typed(("msgpack", crafted))
    assert not callable(loaded)
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

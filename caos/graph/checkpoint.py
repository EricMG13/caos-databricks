"""The LangGraph checkpointer: Lakebase on Databricks, the store's Postgres locally.

Spec section 4. Checkpoints live in their own schema (`caos_graph`) so the
store's verified migration prefix never sees them: the ledger is the host's
schema, the checkpoint tables are LangGraph's, and neither audits the other.

On Databricks the saver runs over a small pool whose every new connection
carries a credential minted at that moment through `store_url()` -- the same
`PG*` values and the same minting the store itself uses (F30). The vendor
`CheckpointSaver` was tried first: its pool fixes `port=5432 sslmode=require`
in its own connection string and offers no override, so the platform's
`PGPORT`/`PGSSLMODE`, and any stand-in database, could never reach it.

The saver deserialises with an allowlist of exactly one type, the graph's own
`RunState` (SA-C2): LangGraph's default serializer imports and calls any
callable a checkpoint row names, so a crafted row would run code in the
worker. Set-up is serialised across processes under an advisory lock (AR-20),
and a pool or connection that fails to set up is closed before the refusal
leaves (CR-2).
"""

from __future__ import annotations

import os
import time
from typing import Any, Self, cast

import psycopg
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from psycopg.rows import DictRow, dict_row
from psycopg_pool import ConnectionPool

from caos.refusals import Refusal, RefusalCode
from caos.store.lakebase import (
    AUTOSCALING_ENDPOINT,
    LAKEBASE_INSTANCE,
    TOKEN_SECONDS,
    note_connect_failure,
    store_url,
)

SCHEMA = "caos_graph"
POOL_MIN, POOL_MAX = 1, 4
# How long a caller waits for a pooled connection before the pool refuses.
POOL_TIMEOUT_SECONDS = 30.0
# The one type a checkpoint may name; everything else is refused unloaded.
ALLOWED_TYPES = (("caos.graph.build", "RunState"),)
# One key for every process setting the checkpoint schema up (AR-20), how
# long a process waits its turn, and how often it asks.
SETUP_LOCK_KEY = 7_355_608_101
SETUP_LOCK_SECONDS = 120.0
SETUP_LOCK_POLL_SECONDS = 0.2


class MintedConnection(psycopg.Connection[DictRow]):
    """A connection whose URL is built when it opens, so a pool that reconnects
    after the hour-long Lakebase token aged out gets a fresh one (D17)."""

    @classmethod
    def connect(cls, conninfo: str = "", **kwargs: object) -> Self:
        try:
            return super().connect(store_url(), **cast("dict[str, Any]", kwargs))
        except psycopg.OperationalError as failed:
            note_connect_failure(failed)  # the pool re-mints on its retry (AR-02)
            raise


def serializer() -> JsonPlusSerializer:
    """The strict serializer: `RunState` and the primitives, nothing imported."""
    return JsonPlusSerializer(allowed_msgpack_modules=list(ALLOWED_TYPES))


def _search_path(conn: psycopg.Connection[DictRow]) -> None:
    conn.execute(f"SET search_path TO {SCHEMA}")


def _set_up(conn: psycopg.Connection[DictRow], saver: PostgresSaver) -> None:
    """Create the schema and LangGraph's tables, one process at a time.

    The lock is polled, not waited on: LangGraph's set-up builds an index
    `CONCURRENTLY`, which waits for every open transaction, and a session
    blocked inside `pg_advisory_lock` is one -- the two deadlocked. A session
    between tries holds nothing.
    """
    deadline = time.monotonic() + SETUP_LOCK_SECONDS
    while True:
        row = conn.execute(
            "SELECT pg_try_advisory_lock(%s) AS held", (SETUP_LOCK_KEY,)
        ).fetchone()
        if row is not None and row["held"]:
            break
        if time.monotonic() > deadline:
            raise Refusal(RefusalCode.STORE_UNAVAILABLE)
        time.sleep(SETUP_LOCK_POLL_SECONDS)
    try:
        conn.execute(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}")
        _search_path(conn)
        saver.setup()
    finally:
        conn.execute("SELECT pg_advisory_unlock(%s)", (SETUP_LOCK_KEY,))


def checkpointer(url: str | None = None) -> BaseCheckpointSaver[str]:
    """A ready checkpointer, its tables created, for this environment.

    On Databricks (`CAOS_LAKEBASE_INSTANCE` or the autoscaling endpoint set)
    a pool of `MintedConnection`s over the platform's `PG*` values. Anywhere
    else the plain `PostgresSaver` over the store's own database, on a
    dedicated autocommit connection whose search path is the checkpoint schema.
    """
    instance = os.environ.get(LAKEBASE_INSTANCE)
    endpoint = os.environ.get(AUTOSCALING_ENDPOINT)
    if instance or endpoint:
        return _pooled()
    conn = psycopg.connect(url or store_url(), autocommit=True, row_factory=dict_row)
    try:
        local = PostgresSaver(conn, serde=serializer())
        _set_up(conn, local)
    except BaseException:
        conn.close()
        raise
    return local


def _pooled() -> BaseCheckpointSaver[str]:
    pool: ConnectionPool[psycopg.Connection[DictRow]] = ConnectionPool(
        conninfo="",
        connection_class=MintedConnection,
        kwargs={"autocommit": True, "row_factory": dict_row},
        configure=_search_path,
        min_size=POOL_MIN,
        max_size=POOL_MAX,
        # A connection is retired within the credential's life, so the
        # pool never holds one whose password has since been rotated.
        max_lifetime=TOKEN_SECONDS,
        timeout=POOL_TIMEOUT_SECONDS,
        # A pooled connection the server ended (a Lakebase failover or
        # restart) is replaced before it is handed out, not after it fails
        # a checkpoint write (DL-9).
        check=ConnectionPool.check_connection,
        open=True,
    )
    try:
        pooled = PostgresSaver(pool, serde=serializer())
        with pool.connection() as conn:
            _set_up(conn, pooled)
    except BaseException:
        pool.close()  # its workers would otherwise reconnect forever (CR-2)
        raise
    return pooled


def close_checkpointer(saver: BaseCheckpointSaver[str]) -> None:
    """Release what `checkpointer` opened: the pool, or the one connection."""
    held = getattr(saver, "conn", None)
    if isinstance(held, ConnectionPool | psycopg.Connection):
        held.close()

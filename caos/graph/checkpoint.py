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

The saver deserialises exactly one extension type, the graph's own `RunState`
(SA-C2, ST-14): LangGraph's default serializer imports and calls any callable a
checkpoint row names, so a crafted row would run code in the worker, and its
allowlisted form still builds LangGraph's "safe" types and `json` rows'
LangChain objects. Anything else a row names refuses `INTERNAL_FAULT`.
Set-up is serialised across processes under an advisory lock (AR-20), bounded
by a statement and lock timeout (ST-4), and a pool that fails to set up is
closed before the refusal leaves (CR-2). Off the platform the saver runs over
the same small checked pool, so a session the server ended is replaced rather
than failing every later claim (ST-13).
"""

from __future__ import annotations

import time
from typing import Any, Self, cast

import psycopg
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.checkpoint.serde.jsonplus import (
    EXT_CONSTRUCTOR_KW_ARGS,
    JsonPlusSerializer,
)
from psycopg import sql
from psycopg.rows import DictRow, dict_row
from psycopg_pool import ConnectionPool

from caos.graph.build import RunState
from caos.refusals import Refusal, RefusalCode
from caos.store import SOCKET_BOUNDS, owned_schema
from caos.store.lakebase import (
    TOKEN_SECONDS,
    lakebase_database,
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
# The most one set-up statement may wait (ST-4): LangGraph builds its indexes
# `CONCURRENTLY`, which waits on every older snapshot in the database, and a
# backup or an analyst's session would otherwise hold boot with no limit.
SETUP_STATEMENT_SECONDS = 30.0
# The most any other checkpoint statement may take (W4): a write is a handful
# of small rows, and it runs between two nodes of the worker's run, whose own
# connection is bounded the same (`caos.graph.worker.STATEMENT_TIMEOUT_MS`,
# CF-041), so a wedged write cannot hold the worker past the lease it drives
# under. Set-up raises and then resets its own bound over this one.
STATEMENT_TIMEOUT_MS = 30_000
# What a checkpoint row may say it is, by LangGraph's own serde tags.
_LOADABLE = frozenset({"null", "bytes", "bytearray", "msgpack"})


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


class _RunStateOnly(JsonPlusSerializer):
    """LangGraph's serializer, loading exactly `RunState` and the primitives."""

    def __init__(self) -> None:
        super().__init__(
            allowed_msgpack_modules=list(ALLOWED_TYPES),
            __unpack_ext_hook__=_run_state_only,
        )

    def loads_typed(self, data: tuple[str, bytes]) -> object:
        """A row this host could have written, or `INTERNAL_FAULT` (ST-14)."""
        if data[0] not in _LOADABLE:
            raise Refusal(RefusalCode.INTERNAL_FAULT)
        try:
            return super().loads_typed(data)
        except ValueError:  # the decoder reports any refused extension as this
            raise Refusal(RefusalCode.INTERNAL_FAULT) from None


def _run_state_only(code: int, data: bytes) -> RunState:
    """The one extension a checkpoint may carry: `RunState`, by keyword."""
    if code != EXT_CONSTRUCTOR_KW_ARGS:
        raise ValueError
    # The payload is msgpack too, read by this same strict serializer.
    named = serializer().loads_typed(("msgpack", data))
    if (
        not isinstance(named, list | tuple)
        or len(named) != 3
        or tuple(named[:2]) not in ALLOWED_TYPES
        or not isinstance(named[2], dict)
    ):
        raise ValueError
    return RunState(**named[2])


def serializer() -> JsonPlusSerializer:
    """The strict serializer: `RunState` and the primitives, nothing imported,
    and anything else a row names refused rather than loaded (ST-14)."""
    return _RunStateOnly()


def _search_path(conn: psycopg.Connection[DictRow]) -> None:
    conn.execute(f"SET search_path TO {SCHEMA}")


def _set_up(conn: psycopg.Connection[DictRow]) -> None:
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
        _bounded_set_up(conn)
    finally:
        conn.execute("SELECT pg_advisory_unlock(%s)", (SETUP_LOCK_KEY,))


def _bounded_set_up(conn: psycopg.Connection[DictRow]) -> None:
    """LangGraph's set-up on this one session, every statement bounded (ST-4).

    A statement that waits past `SETUP_STATEMENT_SECONDS` refuses
    `STORE_UNAVAILABLE`, which the worker's boot asks again under back-off.
    An index build it cancelled is left invalid, and LangGraph's `IF NOT
    EXISTS` would then skip it for good, so any invalid index in the schema
    (only set-up builds one, and only under the lock held here) is dropped
    first.
    """
    bound = int(SETUP_STATEMENT_SECONDS * 1000)
    conn.execute(sql.SQL("SET statement_timeout = {}").format(bound))
    conn.execute(sql.SQL("SET lock_timeout = {}").format(bound))
    try:
        # W2: a schema another role created first, or holds anything in, is
        # refused `STORE_SCHEMA_DRIFT` before a table of it is read or written;
        # one this role owns is not created again (N3), which would take
        # CREATE on the database, and a least-privilege role holds only CONNECT.
        if not owned_schema(conn, SCHEMA):
            conn.execute(f"CREATE SCHEMA {SCHEMA}")
        _search_path(conn)
        _drop_invalid_indexes(conn)
        PostgresSaver(conn, serde=serializer()).setup()
    except (psycopg.errors.QueryCanceled, psycopg.errors.LockNotAvailable):
        raise Refusal(RefusalCode.STORE_UNAVAILABLE) from None
    finally:
        conn.execute("RESET statement_timeout")
        conn.execute("RESET lock_timeout")


def _drop_invalid_indexes(conn: psycopg.Connection[DictRow]) -> None:
    rows = conn.execute(
        "SELECT c.relname AS name FROM pg_index i"
        " JOIN pg_class c ON c.oid = i.indexrelid"
        " JOIN pg_namespace n ON n.oid = c.relnamespace"
        " WHERE n.nspname = %s AND NOT i.indisvalid",
        (SCHEMA,),
    ).fetchall()
    for row in rows:
        conn.execute(
            sql.SQL("DROP INDEX IF EXISTS {}.{}").format(
                sql.Identifier(SCHEMA), sql.Identifier(str(row["name"]))
            )
        )


def checkpointer(url: str | None = None) -> BaseCheckpointSaver[str]:
    """A ready checkpointer, its tables created, for this environment.

    On Databricks (the one Lakebase `caos.store.lakebase.lakebase_database`
    names: an Autoscaling endpoint or a Provisioned instance, both refused
    `STORE_NOT_CONFIGURED`) a pool of `MintedConnection`s over the platform's
    `PG*` values. Anywhere else the same pool of plain connections to the
    store's own database (ST-13): one held connection, once the server ended
    it, failed every later claim for the life of the process.
    """
    if lakebase_database() is not None:
        return _pooled(MintedConnection, "")
    return _pooled(psycopg.Connection, url or store_url())


def _pooled(
    connection_class: type[psycopg.Connection[DictRow]], conninfo: str
) -> BaseCheckpointSaver[str]:
    pool: ConnectionPool[psycopg.Connection[DictRow]] = ConnectionPool(
        conninfo=conninfo,
        connection_class=connection_class,
        # `connect`'s socket bounds (W4): a half-open socket otherwise stalls a
        # checkpoint write, or the pool's own check, for the kernel's timeout.
        kwargs={
            "autocommit": True,
            "row_factory": dict_row,
            **SOCKET_BOUNDS,
            "options": f"-c statement_timeout={STATEMENT_TIMEOUT_MS}",
        },
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
            _set_up(conn)
    except BaseException:
        pool.close()  # its workers would otherwise reconnect forever (CR-2)
        raise
    return pooled


def close_checkpointer(saver: BaseCheckpointSaver[str]) -> None:
    """Release what `checkpointer` opened: the pool, or the one connection."""
    held = getattr(saver, "conn", None)
    if isinstance(held, ConnectionPool | psycopg.Connection):
        held.close()

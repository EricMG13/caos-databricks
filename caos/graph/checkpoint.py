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
"""

from __future__ import annotations

import os
from typing import Any, Self, cast

import psycopg
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.postgres import PostgresSaver
from psycopg.rows import DictRow, dict_row
from psycopg_pool import ConnectionPool

from caos.store.lakebase import LAKEBASE_INSTANCE, TOKEN_SECONDS, store_url

SCHEMA = "caos_graph"
# The autoscaling endpoint path a Databricks App resource injects (R11, R12).
AUTOSCALING_ENDPOINT = "LAKEBASE_AUTOSCALING_ENDPOINT"
POOL_MIN, POOL_MAX = 1, 4


class MintedConnection(psycopg.Connection[DictRow]):
    """A connection whose URL is built when it opens, so a pool that reconnects
    after the hour-long Lakebase token aged out gets a fresh one (D17)."""

    @classmethod
    def connect(cls, conninfo: str = "", **kwargs: object) -> Self:
        return super().connect(store_url(), **cast("dict[str, Any]", kwargs))


def _search_path(conn: psycopg.Connection[DictRow]) -> None:
    conn.execute(f"SET search_path TO {SCHEMA}")


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
            open=True,
        )
        with pool.connection() as conn:
            conn.execute(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}")
        pooled = PostgresSaver(pool)
        pooled.setup()
        return pooled
    conn = psycopg.connect(url or store_url(), autocommit=True, row_factory=dict_row)
    conn.execute(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}")
    conn.execute(f"SET search_path TO {SCHEMA}")
    local = PostgresSaver(conn)
    local.setup()
    return local


def close_checkpointer(saver: BaseCheckpointSaver[str]) -> None:
    """Release what `checkpointer` opened: the pool, or the one connection."""
    held = getattr(saver, "conn", None)
    if isinstance(held, ConnectionPool | psycopg.Connection):
        held.close()

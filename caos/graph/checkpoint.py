"""The LangGraph checkpointer: Lakebase on Databricks, the store's Postgres locally.

Spec section 4. Checkpoints live in their own schema (`caos_graph`) so the
store's verified migration prefix never sees them: the ledger is the host's
schema, the checkpoint tables are LangGraph's, and neither audits the other.
"""

from __future__ import annotations

import os

import psycopg
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.postgres import PostgresSaver
from psycopg.rows import dict_row

from caos.store.lakebase import LAKEBASE_INSTANCE, store_url

SCHEMA = "caos_graph"
# The autoscaling endpoint path a Databricks App resource injects (R11, R12).
AUTOSCALING_ENDPOINT = "LAKEBASE_AUTOSCALING_ENDPOINT"


def checkpointer(url: str | None = None) -> BaseCheckpointSaver[str]:
    """A ready checkpointer, its tables created, for this environment.

    On Databricks (`CAOS_LAKEBASE_INSTANCE` or the autoscaling endpoint set)
    the `databricks_langchain` saver mints its own short-lived credentials.
    Anywhere else the plain `PostgresSaver` over the store's own database, on a
    dedicated autocommit connection whose search path is the checkpoint schema.
    """
    instance = os.environ.get(LAKEBASE_INSTANCE)
    endpoint = os.environ.get(AUTOSCALING_ENDPOINT)
    if instance or endpoint:
        from databricks_langchain import CheckpointSaver

        saver = CheckpointSaver(
            instance_name=instance or None,
            autoscaling_endpoint=endpoint or None,
            schema=SCHEMA,
        )
        saver.setup()
        return saver
    conn = psycopg.connect(url or store_url(), autocommit=True, row_factory=dict_row)
    conn.execute(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}")
    conn.execute(f"SET search_path TO {SCHEMA}")
    local = PostgresSaver(conn)
    local.setup()
    return local

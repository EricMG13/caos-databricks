"""Where the store's connection string comes from: an explicit URL, or Lakebase.

Spec section 4 (R11). Locally and in tests `CAOS_DATABASE_URL` is the whole
answer. On Databricks Apps the platform injects `PGHOST`, `PGPORT`,
`PGDATABASE`, `PGUSER` and `PGSSLMODE` for the app's database resource, and
the password is a short-lived credential the SDK mints for the app's service
principal. Tokens live about an hour, so one is cached for less than that and
every new connection gets a fresh one after it ages out.

No credential is ever printed, logged or written; the URL this returns is
handed straight to the driver.
"""

from __future__ import annotations

import os
import threading
import time
from urllib.parse import quote
from uuid import uuid4

import psycopg
from psycopg import errors

from caos.refusals import Refusal, RefusalCode

DATABASE_URL = "CAOS_DATABASE_URL"
LAKEBASE_INSTANCE = "CAOS_LAKEBASE_INSTANCE"
# Databricks Apps inject these for the first database resource (R11).
PG_ENV = ("PGHOST", "PGPORT", "PGDATABASE", "PGUSER")
# Below the credential life the vendor library plans for (a 15-minute cache
# and a 14-minute pool recycle in `databricks_ai_bridge.lakebase`, the same
# figure the build contract names), with room for a slow connect. F37.
TOKEN_SECONDS = 14 * 60

_LOCK = threading.Lock()
_CACHED: tuple[str, float] | None = None


def store_url() -> str:
    """The connection string for this environment, or `STORE_NOT_CONFIGURED`."""
    url = os.environ.get(DATABASE_URL)
    if url:
        return url
    values = {name: os.environ.get(name) for name in PG_ENV}
    if not all(values.values()):
        raise Refusal(RefusalCode.STORE_NOT_CONFIGURED)
    port = str(values["PGPORT"])
    if not (port.isascii() and port.isdigit()):
        raise Refusal(RefusalCode.STORE_NOT_CONFIGURED)
    user = quote(str(values["PGUSER"]), safe="")
    password = quote(_credential(), safe="")
    host = quote(str(values["PGHOST"]), safe="")
    database = quote(str(values["PGDATABASE"]), safe="")
    sslmode = quote(os.environ.get("PGSSLMODE", "require"), safe="")
    return f"postgresql://{user}:{password}@{host}:{port}/{database}?sslmode={sslmode}"


def invalidate_credential() -> None:
    """Forget the cached credential; the next connection mints a fresh one."""
    global _CACHED
    with _LOCK:
        _CACHED = None


def note_connect_failure(failed: psycopg.OperationalError) -> None:
    """An authentication failure drops the cached credential (F37): a token
    revoked or rotated early would otherwise be handed to the driver until the
    clock said otherwise. Any other failure leaves the cache alone."""
    if isinstance(
        failed, (errors.InvalidPassword, errors.InvalidAuthorizationSpecification)
    ):
        invalidate_credential()


def _credential() -> str:
    """A Lakebase credential for the app's service principal, cached briefly."""
    global _CACHED
    with _LOCK:
        if _CACHED is not None and _CACHED[1] > time.monotonic():
            return _CACHED[0]
        token = _mint()
        _CACHED = (token, time.monotonic() + TOKEN_SECONDS)
        return token


def _mint() -> str:
    """One credential from the SDK's unified auth: instance or endpoint form."""
    from caos.workspace import workspace_client

    client = workspace_client()
    instance = os.environ.get(LAKEBASE_INSTANCE)
    endpoint = os.environ.get("LAKEBASE_AUTOSCALING_ENDPOINT")
    token: str | None = None
    try:
        if instance:
            token = client.database.generate_database_credential(
                request_id=str(uuid4()), instance_names=[instance]
            ).token
        elif endpoint:
            token = client.postgres.generate_database_credential(
                endpoint=endpoint
            ).token
        else:
            raise Refusal(RefusalCode.STORE_NOT_CONFIGURED)
    except OSError:
        # `DatabricksError` is an `IOError`; its message may name the host.
        raise Refusal(RefusalCode.STORE_UNAVAILABLE) from None
    if not isinstance(token, str) or not token:
        raise Refusal(RefusalCode.STORE_UNAVAILABLE)
    return token

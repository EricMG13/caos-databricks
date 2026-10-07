"""Reap disposable test databases a killed pytest process leaked (F588).

`tests/conftest.py` creates `caos_test_<second>_<hex>` and
`caos_test_template_<second>_<hex>` and drops them in `finally`; a process
killed mid-test never gets there, and the shared test server is a small
tmpfs. At a session's start the controller drops the ones nobody is
connected to and that are over two hours old, or carry no timestamp (the
format before F588). It never forces a drop, and never touches another name.
"""

from __future__ import annotations

import contextlib
import os
import re
import sys
import time
from urllib.parse import urlsplit
from uuid import uuid4

import psycopg

MAX_AGE_SECONDS = 2 * 60 * 60
_PATTERN = re.compile(r"^caos_test_(?:template_)?(?:(\d{10})_)?[0-9a-f]{32}$")
TEST_PORT = 55437
QUALIFICATION_PORT = 55436
ALLOW_ENV = "CAOS_TEST_REAPER_ALLOW"
_SUGGESTS_LIVE = ("dev", "prod", "databricks", "lakebase")


def database_name(prefix: str, now: int | None = None) -> str:
    """`<prefix><unix second>_<uuid hex>`: 52 or 62 bytes, under Postgres's 63."""
    return f"{prefix}{int(time.time() if now is None else now)}_{uuid4().hex}"


def _timestamped(name: str) -> bool:
    match = _PATTERN.match(name)
    return match is not None and match.group(1) is not None


def is_reapable(name: str, now: int) -> bool:
    """A name this suite minted that is untimestamped or over two hours old."""
    match = _PATTERN.match(name)
    if match is None:
        return False
    stamp = match.group(1)
    return stamp is None or now - int(stamp) > MAX_AGE_SECONDS


def refused_server(url: str) -> str | None:
    """A typed code unless the URL is positively the shared test server.

    Always refused: a host or database naming dev, prod, databricks or lakebase,
    port 55436 (the qualification server), and any database other than
    `postgres` or a `caos_test` one. Then it must be the test server's port,
    55437, or be allowed by `CAOS_TEST_REAPER_ALLOW=1` in the environment (for
    a test server on another port; it never overrides the refusals above).
    """
    parts = urlsplit(url)
    database = parts.path.lstrip("/")
    named = f"{parts.hostname or ''} {database}".lower()
    if any(word in named for word in _SUGGESTS_LIVE):
        return "server_suggests_live_store"
    try:
        port = parts.port
    except ValueError:
        return "port_unreadable"
    if port == QUALIFICATION_PORT:
        return "qualification_server"
    if database != "postgres" and not database.startswith("caos_test"):
        return "database_not_a_test_database"
    if port != TEST_PORT and os.environ.get(ALLOW_ENV) != "1":
        return "server_not_the_test_server"
    return None


def reap(
    admin: psycopg.Connection,
    now: int | None = None,
    other_sessions: int | None = None,
) -> list[str]:
    """Drop the reapable databases with no connection; return those dropped.

    A timestamped name is dropped when over two hours old. An old-format name
    (no timestamp) could be a connection-free template or a concurrent
    session's fresh database, so it is dropped only when no session at all is
    running any `caos_test_*` database. All new names carry a timestamp, so
    this rule is transitional: it goes with the last old-format leak.
    `other_sessions` overrides the server's count, for a test.
    """
    moment = int(time.time() if now is None else now)
    if other_sessions is None:
        row = admin.execute(
            "SELECT count(*) FROM pg_stat_activity WHERE datname LIKE 'caos\\_test\\_%'"
        ).fetchone()
        other_sessions = 0 if row is None else int(row[0])
    rows = admin.execute(
        "SELECT datname FROM pg_database d WHERE datname LIKE 'caos\\_test\\_%'"
        " AND NOT EXISTS (SELECT 1 FROM pg_stat_activity a"
        " WHERE a.datname = d.datname)"
    ).fetchall()
    dropped: list[str] = []
    for (name,) in rows:
        if not is_reapable(name, moment):
            continue
        if other_sessions and not _timestamped(name):
            continue
        try:
            # The name matched `_PATTERN`: lowercase hex and digits only.
            admin.execute(f'DROP DATABASE IF EXISTS "{name}"')
        except psycopg.Error:
            continue  # connected since the read, or gone: leave it
        dropped.append(name)
    return dropped


def reap_session(url: str) -> None:
    """Once per session. Fail-open by design: whatever the reaper raises, the
    session goes on and one typed line says it did not run to the end."""
    code = refused_server(url)
    if code is not None:
        print(f"pg_reaper: refused code={code}", file=sys.stderr)
        return
    dropped: list[str] | None = None
    with contextlib.suppress(Exception):  # the documented fail-open
        with psycopg.connect(url, autocommit=True) as admin:
            dropped = reap(admin)
    if dropped is None:
        print("pg_reaper: failed code=reaper_failed", file=sys.stderr)
    elif dropped:
        print(f"pg_reaper: reaped count={len(dropped)}", file=sys.stderr)

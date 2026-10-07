"""Reap disposable test databases a killed pytest process leaked (F588).

`tests/conftest.py` creates `caos_test_<second>_<hex>` and
`caos_test_template_<second>_<hex>` and drops them in `finally`; a process
killed mid-test never gets there, and the shared test server is a small
tmpfs. At a session's start the controller drops the ones nobody is
connected to and that are over two hours old, or carry no timestamp (the
format before F588). It never forces a drop, and never touches another name.
"""

from __future__ import annotations

import re
import sys
import time
from urllib.parse import urlsplit
from uuid import uuid4

import psycopg

MAX_AGE_SECONDS = 2 * 60 * 60
_PATTERN = re.compile(r"^caos_test_(?:template_)?(?:(\d{10})_)?[0-9a-f]{32}$")
_SUGGESTS_LIVE = ("dev", "prod", "databricks", "lakebase")


def database_name(prefix: str, now: int | None = None) -> str:
    """`<prefix><unix second>_<uuid hex>`: 52 or 62 bytes, under Postgres's 63."""
    return f"{prefix}{int(time.time() if now is None else now)}_{uuid4().hex}"


def is_reapable(name: str, now: int) -> bool:
    """A name this suite minted that is untimestamped or over two hours old."""
    match = _PATTERN.match(name)
    if match is None:
        return False
    stamp = match.group(1)
    return stamp is None or now - int(stamp) > MAX_AGE_SECONDS


def refused_server(url: str) -> str | None:
    """A typed code when the URL's host or database suggests a real store."""
    parts = urlsplit(url)
    named = f"{parts.hostname or ''} {parts.path.lstrip('/')}".lower()
    if any(word in named for word in _SUGGESTS_LIVE):
        return "server_suggests_live_store"
    return None


def reap(admin: psycopg.Connection, now: int | None = None) -> list[str]:
    """Drop the reapable databases with no connection; return those dropped."""
    moment = int(time.time() if now is None else now)
    rows = admin.execute(
        "SELECT datname FROM pg_database d WHERE datname LIKE 'caos\\_test\\_%'"
        " AND NOT EXISTS (SELECT 1 FROM pg_stat_activity a"
        " WHERE a.datname = d.datname)"
    ).fetchall()
    dropped: list[str] = []
    for (name,) in rows:
        if not is_reapable(name, moment):
            continue
        try:
            # The name matched `_PATTERN`: lowercase hex and digits only.
            admin.execute(f'DROP DATABASE IF EXISTS "{name}"')
        except psycopg.Error:
            continue  # connected since the read, or gone: leave it
        dropped.append(name)
    return dropped


def reap_session(url: str) -> None:
    """Once per session; its own failure is one typed line, never the session's."""
    code = refused_server(url)
    if code is not None:
        print(f"pg_reaper: refused code={code}", file=sys.stderr)
        return
    try:
        with psycopg.connect(url, autocommit=True) as admin:
            dropped = reap(admin)
    except (psycopg.Error, OSError) as exc:  # fail-open, logged (F588)
        print(f"pg_reaper: failed code={type(exc).__name__}", file=sys.stderr)
        return
    if dropped:
        print(f"pg_reaper: reaped count={len(dropped)}", file=sys.stderr)

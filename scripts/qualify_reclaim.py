#!/usr/bin/env python3
"""List the qualification run databases a capture already holds, and the
statement that would drop each (F521). It drops nothing.

`scripts/qualify.py` creates one `caos_qualify_<hex>` database for each set it
performs and keeps it as that run's evidence; nothing reclaims one. Each holds
30 to 120 MB, most of it the run's token index, and on 5 October 2026 the 27
kept on the local server (2.2 GB) were part of what filled the Docker VM's
disk: live run R6 stopped `STORE_UNAVAILABLE` between two nodes. Which to drop
is the owner's decision, so this prints, for every such database, its size,
its runs and whether a capture JSON (its `run_ids`) in one of the named
directories holds every run, and a `DROP DATABASE` statement only for those
that are held. A database with no runs, or a run no capture names, is never
offered.

    CAOS_QUALIFY_POSTGRES_URL=... uv run python scripts/qualify_reclaim.py \\
        docs/rebuild/runs/live-2026-10-03
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import psycopg

# Run as a script: the repository root makes `caos` importable.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from caos.refusals import RefusalCode

# The names `qualify._create_database` mints, and nothing else: a database the
# harness did not create is never listed, let alone offered for dropping.
RUN_DATABASE = re.compile(r"caos_qualify_[0-9a-f]{32}")


@dataclass(frozen=True, slots=True)
class RunDatabase:
    """One harness database: its name, its size on disk and its run ids."""

    name: str
    size_bytes: int
    run_ids: frozenset[str]


def captured_run_ids(roots: Iterable[Path]) -> frozenset[str]:
    """Every run id a capture JSON directly under one of `roots` names.

    A file that is not a JSON object with a `run_ids` list of strings is not a
    capture and adds nothing: the error can only make fewer databases look
    held, never more."""
    return frozenset(
        run_id
        for root in roots
        for path in sorted(root.glob("*.json"))
        for run_id in _run_ids_of(path)
    )


def _run_ids_of(path: Path) -> list[str]:
    """The string run ids of one capture, or none when it is not one."""
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError):
        return []
    ids = document.get("run_ids") if isinstance(document, dict) else None
    return (
        [item for item in ids if isinstance(item, str)] if isinstance(ids, list) else []
    )


def run_databases(admin_url: str) -> list[RunDatabase]:
    """Every harness database on the server, by name, with its runs."""
    with psycopg.connect(admin_url, autocommit=True) as admin:
        rows = admin.execute(
            "SELECT datname, pg_database_size(datname) FROM pg_database"
            " WHERE datname LIKE 'caos\\_qualify\\_%' ORDER BY datname"
        ).fetchall()
    parts = urlsplit(admin_url)
    out = []
    for name, size in rows:
        if RUN_DATABASE.fullmatch(name) is None:
            continue
        url = urlunsplit(parts._replace(path=f"/{name}"))
        with psycopg.connect(url, autocommit=True) as conn:
            # A database the run never reached `apply_schema` in holds no runs.
            held = conn.execute("SELECT to_regclass('caos_store.runs')").fetchone()
            ids = (
                conn.execute("SELECT run_id::text FROM caos_store.runs").fetchall()
                if held and held[0] is not None
                else []
            )
        out.append(RunDatabase(name, int(size), frozenset(row[0] for row in ids)))
    return out


def reclaimable(
    databases: Sequence[RunDatabase], captured: frozenset[str]
) -> list[RunDatabase]:
    """The databases with at least one run, every one of them captured."""
    return [db for db in databases if db.run_ids and db.run_ids <= captured]


def drop_statement(database: RunDatabase) -> str:
    """The statement the owner may run; the name is one the harness minted."""
    if RUN_DATABASE.fullmatch(database.name) is None:
        raise ValueError
    return f'DROP DATABASE "{database.name}";'


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "captures", nargs="+", type=Path, help="directories holding capture JSON"
    )
    args = parser.parse_args(argv)
    admin_url = os.environ.get("CAOS_QUALIFY_POSTGRES_URL")
    if not admin_url:
        print("CAOS_QUALIFY_POSTGRES_URL is unset: name the server", file=sys.stderr)
        return 2
    try:
        databases = run_databases(admin_url)
    except psycopg.Error:
        # Only the code: a DSN psycopg refuses is quoted whole in its message,
        # password and all (CF-078).
        print(RefusalCode.STORE_UNAVAILABLE.value, file=sys.stderr)
        return 2
    held = reclaimable(databases, captured_run_ids(args.captures))
    report = {
        "databases": [
            {
                "database": db.name,
                "bytes": db.size_bytes,
                "runs": sorted(db.run_ids),
                "captured": db in held,
            }
            for db in databases
        ],
        "reclaimable_bytes": sum(db.size_bytes for db in held),
        "statements": [drop_statement(db) for db in held],
    }
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

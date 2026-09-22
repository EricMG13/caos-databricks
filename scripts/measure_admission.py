#!/usr/bin/env python3
"""Time one large plain-text admission, so a performance change has a number.

Not a gate: nothing fails here and no threshold is asserted. It exists so that
the question "is the per-row seal trigger worth a migration?" is answered by a
measurement against a real PostgreSQL rather than by reading the trigger and
guessing. Extraction and the store write are reported apart, because only the
second is what a trigger or a bulk-insert path could move.

    python scripts/measure_admission.py [--tokens 100000] [--per-line 10]

Reads `CAOS_TEST_POSTGRES_URL`, creates a database of its own, applies the
schema, admits the synthetic pack into a fresh case, and drops the database.
"""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
import time
from pathlib import Path
from uuid import uuid4

# Run as a script, not as a package module: the repository root is what makes
# `server` importable.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import psycopg

from caos.blobs import BlobStore
from caos.boundary_text import BoundaryText
from caos.evidence.ingest import (
    Document,
    admit_prepared,
    prepare_pack,
)
from caos.store import apply_schema, connect
from caos.store.runs import create_case


def _document(tokens: int, per_line: int) -> Document:
    """`tokens` whitespace-separated words over `tokens // per_line` lines."""
    lines = [
        " ".join(f"w{index * per_line + offset:06d}" for offset in range(per_line))
        for index in range(tokens // per_line)
    ]
    return Document(BoundaryText.of("measure.txt"), "\n".join(lines).encode("utf-8"))


def _admin_url(url: str, name: str) -> str:
    head, _, _ = url.rpartition("/")
    return f"{head}/{name}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tokens", type=int, default=100_000)
    parser.add_argument("--per-line", type=int, default=10)
    arguments = parser.parse_args()

    url = os.environ.get("CAOS_TEST_POSTGRES_URL")
    if not url:
        print("CAOS_TEST_POSTGRES_URL is not set", file=sys.stderr)
        return 2

    document = _document(arguments.tokens, arguments.per_line)
    name = f"caos_measure_{uuid4().hex}"
    with psycopg.connect(url, autocommit=True) as admin:
        admin.execute(f'CREATE DATABASE "{name}"')
    try:
        with (
            tempfile.TemporaryDirectory() as blob_root,
            connect(_admin_url(url, name)) as conn,
        ):
            apply_schema(conn)
            case_id = create_case(conn, BoundaryText.of("measurement"))
            conn.commit()

            started = time.monotonic()
            pack = prepare_pack([document])
            extracted = time.monotonic()
            admit_prepared(conn, BlobStore(Path(blob_root)), case_id, pack)
            conn.commit()
            done = time.monotonic()

        print(
            f"tokens={arguments.tokens} lines={arguments.tokens // arguments.per_line}"
            f" bytes={len(document.data)}"
            f" extract={extracted - started:.3f}s"
            f" write={done - extracted:.3f}s"
            f" total={done - started:.3f}s"
        )
    finally:
        with psycopg.connect(url, autocommit=True) as admin:
            admin.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

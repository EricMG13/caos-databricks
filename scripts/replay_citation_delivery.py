#!/usr/bin/env python3
"""Replay a store's accepted records against D152's R2 delivery rule, read only.

F677 binds a stored citation to the blocks its own node was handed
(`caos.methodology.canonical.node_delivery`); records accepted before it were
judged against every block the run captured. This reads each accepted run of
the named databases, rebuilds every node's delivery, and counts the stored
citations whose block the node was not handed (N231 (3)). It writes nothing:
every connection starts with `default_transaction_read_only=on` and the script
refuses to go on if the server does not report it, so no statement it runs can
change a row, and it runs no DDL.

For each citation of each accepted record, three answers:

- `handed`: located in the node's own delivery, the rule's verdict;
- `not_handed`: refused by the node's delivery but located in the run's whole
  capture, the case the rule exists to refuse;
- `not_located`: refused by both, a quote the capture no longer holds (a
  different defect, kept apart so it is not counted as the first).

A citation whose document is not a live pinned source now is `source_not_live`.
The report is counts and ids (run, route node, the citation's place in its
record, the refusal code): never document text. A run that cannot be replayed
(no pin, an unreadable record or upstream blob) is counted under its typed code.

    CAOS_QUALIFY_POSTGRES_URL=... uv run python scripts/replay_citation_delivery.py \\
        --blob-root .dev-data/qualification-blobs caos_dev --qualify
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import Counter
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit
from uuid import UUID

import psycopg

# Run as a script: the repository root makes `caos` importable.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from caos.api.deps import methodology_bundle
from caos.blobs import BlobStore
from caos.evidence.citations import Citation, TokenIndex, verify_stored_citations
from caos.methodology.bundle import Bundle
from caos.methodology.canonical import node_delivery
from caos.methodology.executor import captured_blocks
from caos.methodology.handoff import CanonicalRecord, _decoded_record
from caos.refusals import Refusal, RefusalCode
from caos.store import SEARCH_PATH_OPTION, SOCKET_BOUNDS, StoreConnection
from caos.store import startup_options as with_startup_options
from caos.store.routes import resolved_route
from caos.store.source_sets import pinned_live_sources

READ_ONLY_OPTION = "-c default_transaction_read_only=on"
QUALIFY_DATABASE = re.compile(r"caos_qualify_[0-9a-f]{32}")
HANDED = "handed"
NOT_HANDED = "not_handed"
NOT_LOCATED = "not_located"
SOURCE_NOT_LIVE = "source_not_live"
# The failures a stored record or blob can have that this reads past, each
# counted by its typed code or its class: a refusal, a file the blob root does
# not hold, or a record that does not decode. Anything else is a defect in
# this tool or the store and ends the run.
UNREADABLE = (Refusal, OSError, ValueError)


class NotReadOnly(Exception):
    """The server did not report `default_transaction_read_only` as on."""


@dataclass(slots=True)
class RunReplay:
    """One run's counts and the ids of what its nodes were not handed."""

    run_id: str
    skipped: str | None = None
    nodes: int = 0
    citations: Counter[str] = field(default_factory=Counter)
    not_handed: list[dict[str, object]] = field(default_factory=list)
    unreadable: Counter[str] = field(default_factory=Counter)


@contextmanager
def read_only(url: str) -> Iterator[StoreConnection]:
    """A connection that cannot write, verified, never opened otherwise."""
    bounds: dict[str, Any] = dict(SOCKET_BOUNDS)
    options = with_startup_options(url, [SEARCH_PATH_OPTION, READ_ONLY_OPTION])
    conn: StoreConnection = psycopg.connect(
        url, autocommit=False, options=options, **bounds
    )
    try:
        shown = conn.execute("SHOW default_transaction_read_only").fetchone()
        if shown is None or shown[0] != "on":
            raise NotReadOnly
        yield conn
    finally:
        conn.close()


def accepted_run_ids(conn: StoreConnection) -> list[UUID]:
    """Every run that has an accepted artifact; none in a database whose store
    schema was never applied."""
    held = conn.execute("SELECT to_regclass('artifacts')").fetchone()
    if held is None or held[0] is None:
        return []
    rows = conn.execute(
        "SELECT DISTINCT run_id FROM artifacts ORDER BY run_id"
    ).fetchall()
    conn.rollback()
    return [UUID(str(row[0])) for row in rows]


@dataclass(slots=True)
class _Locator:
    """One run's reads: the store, one token index, the pinned sources still
    live and the blocks the run's whole pin captured."""

    conn: StoreConnection
    index: TokenIndex
    live: Mapping[str, UUID]
    whole: Mapping[UUID, frozenset[str]]

    def refused(
        self,
        record: CanonicalRecord,
        place: int,
        source_id: UUID,
        delivered: Mapping[UUID, frozenset[str]],
    ) -> str | None:
        """The code `verify_stored_citations` refuses citation `place` with
        against `delivered`, or None when it is located there."""
        citation = record.citations[place - 1]
        try:
            verify_stored_citations(
                self.conn,
                delivered=delivered,
                citations=[
                    (
                        Citation(source_id, citation.page, citation.matched_text),
                        citation.cited_page,
                    )
                ],
                index=self.index,
                rule=record.citation_rule,
            )
        except Refusal as refused:
            return refused.code.value
        return None

    def verdict(
        self,
        record: CanonicalRecord,
        place: int,
        handed: Mapping[UUID, frozenset[str]],
    ) -> tuple[str, str | None]:
        """Citation `place`'s verdict, and the code the node's delivery refused
        it with when it did."""
        source_id = self.live.get(record.citations[place - 1].document_sha256)
        if source_id is None:
            return SOURCE_NOT_LIVE, None
        code = self.refused(record, place, source_id, handed)
        if code is None:
            return HANDED, None
        elsewhere = self.refused(record, place, source_id, self.whole)
        return (NOT_HANDED if elsewhere is None else NOT_LOCATED), code


def replay_run(
    conn: StoreConnection, blobs: BlobStore, bundle: Bundle, run_id: UUID
) -> RunReplay:
    """Rebuild each accepted node's delivery of `run_id` and locate every stored
    citation in it, then in the run's whole capture."""
    result = RunReplay(str(run_id))
    route = resolved_route(conn, run_id)
    if route is None:
        result.skipped = RefusalCode.ORCHESTRATION_ROUTE_NOT_PINNED.value
        return result
    accepted = conn.execute(
        "SELECT t.route_node_id, a.record_sha256 FROM artifacts a"
        " JOIN run_attempts t ON t.attempt_id = a.attempt_id"
        " WHERE a.run_id = %s ORDER BY a.created_at",
        (run_id,),
    ).fetchall()
    locator = _Locator(
        conn,
        TokenIndex(),
        pinned_live_sources(conn, run_id),
        captured_blocks(conn, run_id),
    )
    delivery = node_delivery(conn, blobs, bundle, run_id)
    nodes = {node.route_node_id: node for node in route.nodes}
    for route_node_id, record_sha256 in accepted:
        node = nodes.get(str(route_node_id))
        if node is None or record_sha256 is None:
            result.unreadable["no_record_or_node"] += 1
            continue
        try:
            record = _decoded_record(blobs.get(str(record_sha256)))
            result.nodes += 1
            handed = delivery(node, record.identity) if record.citations else {}
        except UNREADABLE as failed:
            result.unreadable[_name(failed)] += 1
            continue
        _count(result, locator, str(route_node_id), record, handed)
    conn.rollback()
    return result


def _count(
    result: RunReplay,
    locator: _Locator,
    route_node_id: str,
    record: CanonicalRecord,
    handed: Mapping[UUID, frozenset[str]],
) -> None:
    for place in range(1, len(record.citations) + 1):
        verdict, code = locator.verdict(record, place, handed)
        result.citations[verdict] += 1
        if verdict == NOT_HANDED:
            result.not_handed.append(
                {"route_node_id": route_node_id, "citation": place, "code": code}
            )


def _name(failed: Exception) -> str:
    """The typed code of a refusal, else the class of the fault: never its text."""
    return failed.code.value if isinstance(failed, Refusal) else type(failed).__name__


@dataclass(slots=True)
class DatabaseReplay:
    """One database's runs, replayed."""

    database: str
    runs: list[RunReplay] = field(default_factory=list)

    def report(self) -> dict[str, object]:
        citations: Counter[str] = Counter()
        skipped: Counter[str] = Counter()
        unreadable: Counter[str] = Counter()
        for run in self.runs:
            citations += run.citations
            unreadable += run.unreadable
            if run.skipped is not None:
                skipped[run.skipped] += 1
        return {
            "database": self.database,
            "accepted_runs": len(self.runs),
            "runs_skipped": dict(sorted(skipped.items())),
            "nodes": sum(run.nodes for run in self.runs),
            "citations": {
                key: citations[key]
                for key in (HANDED, NOT_HANDED, NOT_LOCATED, SOURCE_NOT_LIVE)
            },
            "unreadable": dict(sorted(unreadable.items())),
            "runs_with_not_handed": [
                {"run_id": run.run_id, "not_handed": run.not_handed}
                for run in self.runs
                if run.not_handed
            ],
        }


def replay_database(
    url: str, name: str, blobs: BlobStore, bundle: Bundle
) -> DatabaseReplay:
    """Every accepted run of the database at `url`, replayed."""
    replayed = DatabaseReplay(name)
    with read_only(url) as conn:
        for run_id in accepted_run_ids(conn):
            replayed.runs.append(replay_run(conn, blobs, bundle, run_id))
    return replayed


def database_url(server_url: str, name: str) -> str:
    return urlunsplit(urlsplit(server_url)._replace(path=f"/{name}"))


def qualify_databases(server_url: str) -> list[str]:
    """The harness databases on the server, by the names `qualify` mints."""
    with read_only(server_url) as conn:
        rows = conn.execute(
            "SELECT datname FROM pg_database WHERE datname LIKE 'caos\\_qualify\\_%'"
            " ORDER BY datname"
        ).fetchall()
    return [row[0] for row in rows if QUALIFY_DATABASE.fullmatch(row[0])]


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("databases", nargs="*", help="database names on the server")
    parser.add_argument(
        "--qualify", action="store_true", help="also every caos_qualify_* database"
    )
    parser.add_argument(
        "--blob-root", type=Path, help="directory the records' blobs are kept in"
    )
    args = parser.parse_args(argv)
    server_url = os.environ.get("CAOS_QUALIFY_POSTGRES_URL")
    if not server_url or args.blob_root is None:
        print("CAOS_QUALIFY_POSTGRES_URL and --blob-root are required", file=sys.stderr)
        return 2
    blobs = BlobStore(args.blob_root)
    try:
        bundle = methodology_bundle()
        names = [
            *args.databases,
            *(qualify_databases(server_url) if args.qualify else []),
        ]
        reports = [
            replay_database(
                database_url(server_url, name), name, blobs, bundle
            ).report()
            for name in names
        ]
    except psycopg.Error:
        # Only the code: a DSN psycopg refuses is quoted whole in its message,
        # password and all (CF-078).
        print(RefusalCode.STORE_UNAVAILABLE.value, file=sys.stderr)
        return 2
    except NotReadOnly:
        print("DEFAULT_TRANSACTION_READ_ONLY_NOT_ON", file=sys.stderr)
        return 2
    print(json.dumps({"databases": reports}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

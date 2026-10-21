"""N231 (2): the bytes N130's delivery rebuild reads, measured and bounded.

`node_delivery` rebuilds what each node was handed from the pinned blocks
(every block of the pin, text included), the pinned members and the node's
accepted upstream Markdown. The round-trip counts were always asserted
(`IO_BUDGET`); the bytes were not, so a larger pin or a larger upstream
could cost many times more per request while every statement count held.

This measures them on the existing LITE fixtures: the bytes of the rows the
two pinned statements return, and the bytes of upstream Markdown the rebuild
reads from the blob store (every read, counted at the call, whether the
request's store remembered it or not). The bound each read and the freeze
declare is asserted as a ceiling, and the measured value as at least half of
it, so a bound left far above what it measures is refused as well.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

import psycopg
import pytest
from command_fixtures import command_client, command_headers
from fastapi.testclient import TestClient
from httpx2 import Response
from test_deliverable_canonical import harness, lite, route
from test_execution_freshness import _Harness
from test_filed_receipts import _file
from test_filing_chain import _freeze, _sign
from test_governed_write_routes import (
    _approver,
    _case,
    _digest,
    _post,
    _unsaved,
    filing_client,
)
from test_revisions import _save

from caos.api.app import app, store_connection
from caos.api.commands import deliverable
from caos.api.reads import reports
from caos.blobs import BlobStore
from caos.methodology import canonical, invocation
from caos.methodology.handoff import UpstreamRef
from caos.store import StoreConnection

__all__ = ["command_client", "filing_client", "harness", "lite", "route"]


@dataclass
class Rebuild:
    """What the delivery rebuild read during one request."""

    store_bytes: int = 0
    blob_bytes: int = 0
    rebuilds: int = 0

    @property
    def total(self) -> int:
        return self.store_bytes + self.blob_bytes


def _value_bytes(value: object) -> int:
    """The size of one column as it reads: bytes by their length, any other
    value (a string, an identifier, a number, a time) by the length of its text."""
    if isinstance(value, bytes):
        return len(value)
    return len(str(value).encode())


class _Rows:
    def __init__(self, rows: Sequence[Sequence[object]], seen: Rebuild) -> None:
        self._rows = rows
        self._seen = seen

    def fetchall(self) -> Sequence[Sequence[object]]:
        self._seen.store_bytes += sum(
            _value_bytes(value) for row in self._rows for value in row
        )
        return self._rows


class _Metered:
    """The request's connection, counting the bytes of the rows the two pinned
    statements return (`_PINNED_DELIVERIES`, `_PINNED_MEMBERS`)."""

    def __init__(self, conn: StoreConnection, seen: Rebuild) -> None:
        self._conn = conn
        self._seen = seen

    def execute(
        self, sql: str, params: tuple[Any, ...] = ()
    ) -> psycopg.Cursor[tuple[Any, ...]] | _Rows:
        answer = self._conn.execute(sql, params)
        if sql in (canonical._PINNED_DELIVERIES, canonical._PINNED_MEMBERS):
            return _Rows(answer.fetchall(), self._seen)
        return answer

    def __getattr__(self, name: str) -> object:
        return getattr(self._conn, name)


@contextmanager
def _measured(lite: _Harness, monkeypatch: pytest.MonkeyPatch) -> Iterator[Rebuild]:
    seen = Rebuild()
    real = invocation.upstream_markdown

    def upstream(
        blobs: BlobStore, refs: Sequence[UpstreamRef]
    ) -> tuple[tuple[UpstreamRef, bytes], ...]:
        read = real(blobs, refs)
        seen.rebuilds += 1
        seen.blob_bytes += sum(len(markdown) for _, markdown in read)
        return read

    monkeypatch.setattr(canonical, "upstream_markdown", upstream)
    metered = _Metered(lite.conn, seen)
    app.dependency_overrides[store_connection] = lambda: metered
    yield seen


def _within(seen: Rebuild, bound: int) -> None:
    assert seen.rebuilds, "the request never rebuilt a delivery"
    assert seen.total <= bound, (seen, bound)
    assert seen.total * 2 >= bound, (seen, bound)


def _report(client: TestClient, lite: _Harness, revision: object | None) -> Response:
    approver = _approver(lite)
    if revision is None:
        return _unsaved(client, lite, approver)
    answer: Response = client.get(
        f"{_case(lite)}/report?run={lite.run_id}&revision={revision}",
        headers=command_headers(approver),
    )
    return answer


def test_the_report_reads_a_bounded_number_of_delivery_bytes(
    filing_client: TestClient, lite: _Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    filed = _file(lite).revision_id
    with _measured(lite, monkeypatch) as seen:
        answer = _report(filing_client, lite, filed)
    assert answer.status_code == 200, answer.text
    _within(seen, reports.DELIVERY_BYTES["report"])


def test_the_report_of_a_frozen_revision_reads_a_bounded_number_of_delivery_bytes(
    filing_client: TestClient, lite: _Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    revision = _save(lite)
    _sign(lite, revision)
    _freeze(lite, revision)
    with _measured(lite, monkeypatch) as seen:
        answer = _report(filing_client, lite, revision)
    assert answer.status_code == 200, answer.text
    _within(seen, reports.DELIVERY_BYTES["frozen"])


def test_the_report_of_an_unsaved_run_reads_a_bounded_number_of_delivery_bytes(
    filing_client: TestClient, lite: _Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    with _measured(lite, monkeypatch) as seen:
        answer = _report(filing_client, lite, None)
    assert answer.status_code == 200, answer.text
    _within(seen, reports.DELIVERY_BYTES["unsaved"])


def test_a_freeze_reads_a_bounded_number_of_delivery_bytes(
    filing_client: TestClient, lite: _Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    revision = _save(lite)
    lite.conn.commit()
    digest = _digest(lite, revision)
    signed = _post(
        filing_client,
        f"{_case(lite)}/revisions/{revision}/signature",
        _approver(lite),
        {"payload_sha256": digest},
    )
    assert signed.status_code == 200, signed.text
    with _measured(lite, monkeypatch) as seen:
        frozen = _post(
            filing_client,
            f"{_case(lite)}/revisions/{revision}/freeze",
            _approver(lite),
            {"payload_sha256": digest},
        )
    assert frozen.status_code == 200, frozen.text
    _within(seen, deliverable.FREEZE_DELIVERY_BYTES)

"""The evidence page endpoint (Phase 4 Task 4.4, slice 4.4c; decision 7).

`GET /api/v1/cases/{case}/runs/{run}/sources/{source}/pages/{page}` serves
`read_page` over HTTP: identity first, then READER standing, then the run of
the case; everything about the source or the page that cannot be served is one
private 404 with no text. The read itself is `tests/test_evidence_page_read.py`.
"""

from __future__ import annotations

from collections.abc import Iterator
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from httpx2 import Response
from psycopg import pq
from test_evidence_page_read import (
    Pinned,
    blobs,
    corrupt_extraction,
    forget_frames,
    long_page,
    pin,
    report,
)
from test_pdf_extraction import FIRST_LINE, REPORT, SECOND_LINE

from caos.api import app as app_module
from caos.api.app import app, blob_store, store_connection
from caos.api.identity import ROLE_HEADER, TRUST_SWITCH, TRUSTED
from caos.api.reads import evidence as evidence_read
from caos.api.wire import CLEARS, PAGE_LINES_MAX, PageDocument, SectionNote
from caos.blobs import BlobStore
from caos.boundary_text import BoundaryText
from caos.evidence import pdf as pdf_module
from caos.evidence.extract import AdmissionLimits
from caos.refusals import RefusalCode
from caos.store import StoreConnection
from caos.store.gates import withdraw_source
from caos.store.members import Standing, grant, revoke
from caos.store.runs import create_case, start_run

__all__ = ["blobs", "forget_frames", "report"]


@pytest.fixture
def client(
    case: tuple[StoreConnection, UUID],
    blobs: BlobStore,
    empty_database: str,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[TestClient]:
    conn, _ = case
    monkeypatch.setenv(app_module.DATABASE_URL, empty_database)
    # Tokenless, so no groups header is read: the development switch is how a
    # test here asserts a global role above the floor.
    monkeypatch.setenv(TRUST_SWITCH, TRUSTED)
    app.dependency_overrides[store_connection] = lambda: conn
    app.dependency_overrides[blob_store] = lambda: blobs
    try:
        with TestClient(app) as opened:
            yield opened
    finally:
        app.dependency_overrides.clear()


class _CountingConnection:
    def __init__(self, conn: StoreConnection) -> None:
        self._conn = conn
        self.executed = 0
        self.ended = 0

    def execute(self, *args: object, **kwargs: object) -> object:
        self.executed += 1
        return self._conn.execute(*args, **kwargs)  # type: ignore[arg-type]

    def rollback(self) -> None:
        self.ended += 1
        self._conn.rollback()


def _as(user_id: UUID, role: str | None = None) -> dict[str, str]:
    headers = {"x-caos-user": str(user_id)}
    if role is not None:
        headers[ROLE_HEADER] = role
    return headers


def _refused(code: RefusalCode) -> dict[str, str]:
    return {"code": code.value, "clears": CLEARS[code]}


def _path(pinned: Pinned, source: object, page: object = 1, **ids: object) -> str:
    case_id, run_id = ids.get("case", pinned.case_id), ids.get("run", pinned.run_id)
    return f"/api/v1/cases/{case_id}/runs/{run_id}/sources/{source}/pages/{page}"


def _member(pinned: Pinned, standing: Standing) -> UUID:
    user = uuid4()
    grant(pinned.conn, case_id=pinned.case_id, user_id=user, standing=standing)
    pinned.conn.commit()
    return user


def _get(client: TestClient, pinned: Pinned, path: str, user: UUID | None) -> Response:
    try:
        response: Response = client.get(path, headers={} if user is None else _as(user))
        return response
    finally:
        pinned.conn.rollback()


def _answer(response: Response) -> tuple[int, object]:
    return response.status_code, response.json()


def test_a_page_request_across_anonymous_nonmember_reader_writer_approver_revoked_and_admin(  # noqa: E501
    client: TestClient, report: Pinned
) -> None:
    [source] = report.sources
    path = _path(report, source)
    allowed = [
        _member(report, s)
        for s in (Standing.READER, Standing.WRITER, Standing.APPROVER)
    ]
    revoked = _member(report, Standing.WRITER)
    revoke(report.conn, case_id=report.case_id, user_id=revoked)
    report.conn.commit()

    assert _answer(_get(client, report, path, None)) == (
        401,
        _refused(RefusalCode.NOT_AUTHENTICATED),
    )
    for user in allowed:
        response = _get(client, report, path, user)
        assert response.status_code == 200, user
        assert response.headers["cache-control"] == "no-store"
        document = PageDocument.model_validate(response.json())
        assert (document.status, document.notes) == ("complete", [])
        assert (document.body.source_id, document.body.page) == (source, 1)
        assert [line.text for line in document.body.lines] == [FIRST_LINE, SECOND_LINE]

    reader = allowed[0]
    for user, role, case_id in (
        (uuid4(), None, report.case_id),
        (revoked, None, report.case_id),
        (uuid4(), "ADMIN", report.case_id),
        (reader, None, uuid4()),
        (reader, None, "not-a-case"),
    ):
        response = client.get(
            _path(report, source, case=case_id), headers=_as(user, role)
        )
        report.conn.rollback()
        assert _answer(response) == (404, _refused(RefusalCode.CASE_NOT_FOUND))

    foreign = start_run(report.conn, create_case(report.conn, BoundaryText.of("B")))
    report.conn.commit()
    for run_id in (foreign, uuid4(), "not-a-run"):
        response = _get(client, report, _path(report, source, run=run_id), reader)
        assert _answer(response) == (404, _refused(RefusalCode.RUN_NOT_FOUND))


def test_every_unavailable_page_is_one_http_404_with_no_text(
    client: TestClient, report: Pinned, empty_database: str
) -> None:
    """Outside the pinned version, an unknown or malformed source or page, a
    moved blob, a re-extracted or withdrawn source: one body, naming nothing."""
    [source] = report.sources
    reader = _member(report, Standing.READER)
    later = pin(report.conn, report.case_id, report.blobs, [("l.txt", b"later")])
    unavailable = [
        _path(report, later.sources[0]),
        *(_path(report, source, page) for page in (2, 0, 501, "01", "x")),
        _path(report, uuid4()),
        _path(report, "not-a-source"),
    ]

    def answers() -> set[str]:
        bodies = set()
        for path in unavailable:
            response = _get(client, report, path, reader)
            assert _answer(response) == (
                404,
                _refused(RefusalCode.PAGE_NOT_AVAILABLE),
            ), path
            bodies.add(response.text)
        return bodies

    assert _get(client, report, _path(report, source), reader).status_code == 200
    before = answers()
    document = client.get(_path(report, source), headers=_as(reader)).json()
    report.conn.rollback()
    moved = report.blobs.path_of(document["body"]["document_sha256"])
    moved.write_bytes(REPORT.replace(b"Total", b"Fraud"))
    unavailable.append(_path(report, source))
    after_blob = answers()
    moved.write_bytes(REPORT)
    corrupt_extraction(report, source, empty_database)
    after_extraction = answers()
    withdrawn = _path(report, later.sources[0], run=later.run_id)
    assert _get(client, report, withdrawn, reader).status_code == 200
    writer = _member(report, Standing.WRITER)
    withdraw_source(
        report.conn, case_id=report.case_id, source_id=later.sources[0], actor_id=writer
    )
    report.conn.commit()
    unavailable.append(withdrawn)

    assert before == after_blob == after_extraction == answers()
    assert not any(
        word in body for body in before for word in ("Total", "Fraud", "later")
    )


def test_a_page_over_its_line_bound_is_partial_list_truncated(
    client: TestClient, case: tuple[StoreConnection, UUID], blobs: BlobStore
) -> None:
    pinned = long_page(case, blobs)
    user = _member(pinned, Standing.READER)

    response = _get(client, pinned, _path(pinned, pinned.sources[0]), user)

    document = PageDocument.model_validate(response.json())
    assert (document.status, document.notes) == (
        "partial",
        [SectionNote.LIST_TRUNCATED],
    )
    assert len(document.body.lines) == PAGE_LINES_MAX


def test_the_page_read_declares_its_store_budget(
    client: TestClient, report: Pinned, monkeypatch: pytest.MonkeyPatch
) -> None:
    reader = _member(report, Standing.READER)
    counter = _CountingConnection(report.conn)
    app.dependency_overrides[store_connection] = lambda: counter
    path = _path(report, report.sources[0])
    # N35's remainder: the one document `read_page` downloads.
    downloaded: list[str] = []
    real_get = BlobStore.get

    def counted_get(store: BlobStore, digest: str) -> bytes:
        if store.verified is None or digest not in store.verified:
            downloaded.append(digest)
        return real_get(store, digest)

    monkeypatch.setattr(BlobStore, "get", counted_get)

    assert _get(client, report, path, reader).status_code == 200
    assert counter.executed == evidence_read.IO_BUDGET == 2
    # The read unit is ended once, where the connection's own exit would
    # otherwise have sent its COMMIT, so the round trips do not move.
    assert counter.ended == 1
    assert len(downloaded) == evidence_read.BLOB_BUDGET == 1

    opened: list[str] = []

    def counted() -> StoreConnection:
        opened.append("store")
        return report.conn

    app.dependency_overrides[store_connection] = counted
    assert client.get(path).status_code == 401
    for malformed in (
        _path(report, report.sources[0], case="not-a-case"),
        _path(report, report.sources[0], run="not-a-run"),
    ):
        assert client.get(malformed, headers=_as(reader)).status_code == 404
    assert opened == []


def test_no_transaction_is_open_while_the_page_frame_is_extracted(
    client: TestClient, report: Pinned, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The store reads end before the document is read and before the §47
    child runs, so a slow or large PDF holds no read transaction (and no
    snapshot) on the request's connection while it is extracted."""
    reader = _member(report, Standing.READER)
    seen: list[tuple[str, pq.TransactionStatus]] = []
    real_get, real_frame = BlobStore.get, pdf_module.page_frame

    def watched_get(store: BlobStore, digest: str) -> bytes:
        seen.append(("blob", report.conn.info.transaction_status))
        return real_get(store, digest)

    def watched_frame(
        data: bytes, page: int, *, limits: AdmissionLimits, deadline: float
    ) -> pdf_module.Frame:
        seen.append(("frame", report.conn.info.transaction_status))
        return real_frame(data, page, limits=limits, deadline=deadline)

    monkeypatch.setattr(BlobStore, "get", watched_get)
    monkeypatch.setattr(pdf_module, "page_frame", watched_frame)

    response = _get(client, report, _path(report, report.sources[0]), reader)

    assert response.status_code == 200
    assert seen == [
        ("blob", pq.TransactionStatus.IDLE),
        ("frame", pq.TransactionStatus.IDLE),
    ]

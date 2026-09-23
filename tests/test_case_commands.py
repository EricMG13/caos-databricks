"""Task 4.2 slice 4.2d: create case and source admission over the real app.

Create case is one nil-scope unit: the case, the creator's ADMIN standing, the
`CASE_CREATED` event and the receipt. Admission checks the envelope and the
caller before it reads a byte of the pack, parses and extracts with no
transaction open and no case lock held, then writes rows, event and receipt in
one governed unit (decisions 2, 4 and 6).
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Iterator
from typing import Any
from uuid import UUID, uuid4

import anyio
import psycopg
import pytest
from command_fixtures import command_client, command_headers, member
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from httpx2 import Response
from journey.pack import PDF_NAME, TEXT_NAME, journey_pack
from psycopg.pq import TransactionStatus
from starlette.datastructures import FormData
from starlette.requests import Request

from caos.api.app import app
from caos.api.commands import cases
from caos.api.deps import store_connection
from caos.blobs import BlobStore
from caos.evidence import ingest
from caos.evidence.extract import DEFAULT_LIMITS
from caos.store import StoreConnection, connect
from caos.store import commands as store_commands
from caos.store.audit import audit_trail, verify_chain
from caos.store.members import Standing, revoke, standing_of

__all__ = ["command_client"]

TEXT = b"Supplied quarterly report text.\n"


def _count(conn: StoreConnection, sql: str, *params: object) -> int:
    row = conn.execute(sql, params).fetchone()
    conn.rollback()
    assert row is not None
    return int(row[0])


def _sources(conn: StoreConnection, case_id: UUID) -> int:
    return _count(conn, "SELECT count(*) FROM sources WHERE case_id = %s", case_id)


def _receipts(conn: StoreConnection) -> int:
    return _count(conn, "SELECT count(*) FROM command_requests")


def _admit(  # noqa: PLR0913 -- one upload, its actor and its key
    client: TestClient,
    case_id: UUID,
    user: UUID,
    files: list[tuple[str, bytes]],
    *,
    role: str = "ANALYST",
    key: UUID | None = None,
) -> Response:
    answer: Response = client.post(
        f"/api/v1/cases/{case_id}/sources",
        headers=command_headers(user, role=role, key=key),
        files=[
            ("document", (name, data, "application/octet-stream"))
            for name, data in files
        ],
    )
    return answer


def _create(
    client: TestClient, user: UUID, title: str = "Acme 2027", role: str = "ANALYST"
) -> Response:
    answer: Response = client.post(
        "/api/v1/cases", headers=command_headers(user, role=role), json={"title": title}
    )
    return answer


@pytest.fixture
def seen(monkeypatch: pytest.MonkeyPatch) -> Iterator[dict[str, int]]:
    """How often the route parsed a form and prepared (extracted) a pack."""
    counts = {"form": 0, "prepare": 0}
    real_form = Request._get_form

    async def form(self: Request, **kwargs: int) -> FormData:
        counts["form"] += 1
        return await real_form(self, **kwargs)

    def prepare(documents: list[ingest.Document]) -> ingest.PreparedPack:
        counts["prepare"] += 1
        return ingest.prepare_pack(documents)

    monkeypatch.setattr(Request, "_get_form", form)
    monkeypatch.setattr(cases, "prepare_pack", prepare)
    yield counts


def test_create_case_grants_the_creator_admin_in_one_audited_unit(
    case: tuple[StoreConnection, UUID],
    command_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn, _ = case
    creator = uuid4()

    created = _create(command_client, creator, "Acme 2027 refinancing")

    assert created.status_code == 201
    case_id = UUID(created.json()["case_id"])
    assert created.json() == {"case_id": str(case_id)}
    title = conn.execute("SELECT title FROM cases WHERE case_id = %s", (case_id,))
    assert title.fetchone() == ("Acme 2027 refinancing",)
    assert standing_of(conn, case_id=case_id, user_id=creator) is Standing.ADMIN
    [event] = audit_trail(conn, case_id)
    assert (event.action, event.actor_id) == ("CASE_CREATED", creator)
    assert verify_chain(conn, case_id)
    conn.rollback()
    assert _receipts(conn) == 1

    # A failure at the unit's last statement leaves no case and no standing.
    def lost(*_args: object, **_kwargs: object) -> bool:
        raise psycopg.OperationalError

    monkeypatch.setattr(store_commands, "record_receipt", lost)
    before = _count(conn, "SELECT count(*) FROM cases")
    failed = _create(command_client, uuid4(), "Never lands")
    assert (failed.status_code, failed.json()["code"]) == (503, "STORE_UNAVAILABLE")
    assert _count(conn, "SELECT count(*) FROM cases") == before
    assert _count(conn, "SELECT count(*) FROM case_members") == 1
    assert _count(conn, "SELECT count(*) FROM audit_events") == 1


def test_create_case_title_crosses_boundary_text(
    case: tuple[StoreConnection, UUID], command_client: TestClient
) -> None:
    conn, _ = case
    refused = _create(command_client, uuid4(), "Acme \u202e7202")
    assert (refused.status_code, refused.json()["code"]) == (
        400,
        "BOUNDARY_TEXT_INVALID",
    )
    assert _count(conn, "SELECT count(*) FROM cases") == 1
    created = _create(command_client, uuid4(), "Café")
    stored = conn.execute(
        "SELECT title FROM cases WHERE case_id = %s", (created.json()["case_id"],)
    ).fetchone()
    conn.rollback()
    assert stored == ("Café",)


def test_a_replayed_create_case_makes_one_case(
    case: tuple[StoreConnection, UUID], command_client: TestClient
) -> None:
    conn, _ = case
    user, key = uuid4(), uuid4()
    headers = command_headers(user, key=key)
    first = command_client.post("/api/v1/cases", headers=headers, json={"title": "A"})
    again = command_client.post("/api/v1/cases", headers=headers, json={"title": "A"})
    other = command_client.post("/api/v1/cases", headers=headers, json={"title": "B"})

    assert (first.status_code, again.status_code) == (201, 201)
    assert again.json() == first.json()
    assert again.headers["idempotency-replayed"] == "true"
    assert (other.status_code, other.json()["code"]) == (409, "IDEMPOTENCY_KEY_REUSED")
    assert _count(conn, "SELECT count(*) FROM cases") == 2


@pytest.mark.parametrize(
    ("role", "status"), [("READER", 403), ("ANALYST", 201), ("ADMIN", 201)]
)
def test_create_case_actor_matrix(
    case: tuple[StoreConnection, UUID],
    command_client: TestClient,
    role: str,
    status: int,
) -> None:
    conn, _ = case
    answer = _create(command_client, uuid4(), role=role)
    assert answer.status_code == status
    if status == 403:
        assert answer.json()["code"] == "NOT_AUTHORISED"
        assert _count(conn, "SELECT count(*) FROM cases") == 1
    anonymous = command_client.post("/api/v1/cases", json={"title": "x"})
    assert (anonymous.status_code, anonymous.json()["code"]) == (
        401,
        "NOT_AUTHENTICATED",
    )


def test_admission_is_whole_or_nothing_for_a_mixed_text_and_pdf_pack(
    case: tuple[StoreConnection, UUID], command_client: TestClient
) -> None:
    conn, case_id = case
    writer = member(conn, case_id)

    admitted = _admit(command_client, case_id, writer, journey_pack())

    assert admitted.status_code == 201, admitted.json()
    body = admitted.json()
    assert body["case_id"] == str(case_id) and len(body["source_ids"]) == 2
    rows = conn.execute(
        "SELECT s.source_id, s.filename, count(b.block_id) FROM sources s"
        " JOIN source_blocks b USING (source_id) WHERE s.case_id = %s"
        " GROUP BY s.source_id, s.filename",
        (case_id,),
    ).fetchall()
    conn.rollback()
    assert {str(r[0]) for r in rows} == set(body["source_ids"])
    assert {r[1] for r in rows} == {TEXT_NAME, PDF_NAME}
    assert all(r[2] > 0 for r in rows)
    [event] = audit_trail(conn, case_id)
    conn.rollback()
    assert event.action == "SOURCES_ADMITTED"

    # A readable text beside a PDF that will not read: nothing of either lands.
    refused = _admit(
        command_client,
        case_id,
        writer,
        [("fine.txt", TEXT), ("broken.pdf", b"%PDF-1.4\nnot a document")],
    )
    assert refused.status_code == 400
    assert refused.json()["code"] == "SOURCE_NOT_READABLE"
    assert _sources(conn, case_id) == 2
    assert _count(conn, "SELECT count(*) FROM audit_events") == 1
    assert _receipts(conn) == 1


def test_a_replayed_admission_returns_the_original_receipt_and_no_second_rows(
    case: tuple[StoreConnection, UUID],
    command_client: TestClient,
    seen: dict[str, int],
) -> None:
    conn, case_id = case
    writer, key = member(conn, case_id), uuid4()

    first = _admit(command_client, case_id, writer, [("a.txt", TEXT)], key=key)
    again = _admit(command_client, case_id, writer, [("a.txt", TEXT)], key=key)
    renamed = _admit(command_client, case_id, writer, [("b.txt", TEXT)], key=key)

    assert (first.status_code, again.status_code) == (201, 201)
    assert again.json() == first.json()
    assert again.headers["idempotency-replayed"] == "true"
    assert (renamed.status_code, renamed.json()["code"]) == (
        409,
        "IDEMPOTENCY_KEY_REUSED",
    )
    assert seen["prepare"] == 1, "a replay or a reused key extracts nothing"
    assert _sources(conn, case_id) == 1
    assert _receipts(conn) == 1


@pytest.mark.parametrize(
    ("name", "code"),
    [
        ("evil\u202etxt.pdf", "BOUNDARY_TEXT_INVALID"),
        ("   ", "BOUNDARY_TEXT_INVALID"),
        ("n" * 256, "BOUNDARY_TEXT_TOO_LONG"),
    ],
)
def test_filenames_cross_boundary_text(
    case: tuple[StoreConnection, UUID],
    command_client: TestClient,
    seen: dict[str, int],
    name: str,
    code: str,
) -> None:
    conn, case_id = case
    writer = member(conn, case_id)

    refused = _admit(command_client, case_id, writer, [("ok.txt", TEXT), (name, TEXT)])

    assert (refused.status_code, refused.json()["code"]) == (400, code)
    assert seen["prepare"] == 0, "refused before extraction"
    assert _sources(conn, case_id) == 0

    admitted = _admit(command_client, case_id, writer, [("../Résumé.txt", TEXT)])
    assert admitted.status_code == 201
    stored = conn.execute("SELECT filename FROM sources WHERE case_id = %s", (case_id,))
    assert stored.fetchone() == ("../Résumé.txt",), "NFC, display only"
    conn.rollback()


def test_parts_other_than_named_documents_are_request_invalid(
    case: tuple[StoreConnection, UUID],
    command_client: TestClient,
    seen: dict[str, int],
) -> None:
    conn, case_id = case
    writer = member(conn, case_id)
    path = f"/api/v1/cases/{case_id}/sources"

    answers = [
        command_client.post(
            path,
            headers=command_headers(writer),
            files=[("attachment", ("a.txt", TEXT, "text/plain"))],
        ),
        command_client.post(
            path,
            headers=command_headers(writer),
            files=[("document", ("a.txt", TEXT, "text/plain"))],
            data={"note": "a field"},
        ),
        command_client.post(
            path,
            headers=command_headers(writer),
            files=[("document", ("a.txt", TEXT))] * 51,
        ),
        command_client.post(
            path,
            headers={**command_headers(writer), "content-type": "multipart/form-data"},
            content=b"no boundary",
        ),
    ]

    assert [(a.status_code, a.json()["code"]) for a in answers] == [
        (400, "REQUEST_INVALID")
    ] * 4
    assert seen["prepare"] == 0
    assert _sources(conn, case_id) == 0


def test_an_oversized_or_chunked_pack_is_refused_before_parsing(
    case: tuple[StoreConnection, UUID],
    command_client: TestClient,
    seen: dict[str, int],
) -> None:
    conn, case_id = case
    writer = member(conn, case_id)
    path = f"/api/v1/cases/{case_id}/sources"
    multipart = "multipart/form-data; boundary=x"

    def post(
        headers: dict[str, str], content: str | bytes | Iterator[bytes]
    ) -> tuple[int, str]:
        answer = command_client.post(
            path,
            headers={**command_headers(writer), **headers},
            content=content,
        )
        return answer.status_code, answer.json()["code"]

    ceiling = DEFAULT_LIMITS.max_pack_bytes + 1024 * 1024
    assert post(
        {"content-type": multipart, "content-length": str(ceiling + 1)}, b"--x--"
    ) == (413, "SOURCE_TOO_LARGE")
    assert post({"content-type": multipart}, iter([b"--x", b"--\r\n"])) == (
        400,
        "REQUEST_INVALID",
    ), "chunked: no declared length"
    assert post({"content-type": "application/json"}, b"{}") == (400, "REQUEST_INVALID")
    assert post({"content-type": multipart, "content-length": "1e3"}, b"--x--") == (
        400,
        "REQUEST_INVALID",
    )
    assert seen["form"] == 0, "no envelope refusal parsed a byte"

    # A body longer than its declared length is refused as it streams.
    lying = post({"content-type": multipart, "content-length": "10"}, b"-" * 5000)
    assert lying == (400, "REQUEST_INVALID")
    assert seen["prepare"] == 0
    assert _sources(conn, case_id) == 0


def test_a_nonmember_upload_is_404_without_extraction(
    case: tuple[StoreConnection, UUID],
    command_client: TestClient,
    seen: dict[str, int],
) -> None:
    conn, case_id = case
    revoked = member(conn, case_id)
    revoke(conn, case_id=case_id, user_id=revoked)
    conn.commit()

    for user, role in ((uuid4(), "ANALYST"), (uuid4(), "ADMIN"), (revoked, "ANALYST")):
        answer = _admit(command_client, case_id, user, journey_pack(), role=role)
        assert (answer.status_code, answer.json()["code"]) == (404, "CASE_NOT_FOUND")
    unknown = _admit(command_client, uuid4(), uuid4(), [("a.txt", TEXT)])
    assert unknown.status_code == 404

    assert seen == {"form": 0, "prepare": 0}, (
        "no stranger's pack is parsed or extracted"
    )
    assert _sources(conn, case_id) == 0


@pytest.mark.parametrize(
    ("standing", "role", "status"),
    [
        (Standing.READER, "ANALYST", 403),
        (Standing.WRITER, "READER", 403),
        (Standing.WRITER, "ANALYST", 201),
        (Standing.APPROVER, "ANALYST", 201),
        (Standing.ADMIN, "ADMIN", 201),
    ],
)
def test_admission_actor_matrix(  # noqa: PLR0913 -- one matrix row
    case: tuple[StoreConnection, UUID],
    command_client: TestClient,
    seen: dict[str, int],
    standing: Standing,
    role: str,
    status: int,
) -> None:
    conn, case_id = case
    user = member(conn, case_id, standing)

    answer = _admit(command_client, case_id, user, [("a.txt", TEXT)], role=role)

    assert answer.status_code == status
    if status == 403:
        assert answer.json()["code"] == "NOT_AUTHORISED"
        assert seen == {"form": 0, "prepare": 0}
    anonymous = command_client.post(
        f"/api/v1/cases/{case_id}/sources",
        files=[("document", ("a.txt", TEXT, "text/plain"))],
    )
    assert (anonymous.status_code, anonymous.json()["code"]) == (
        401,
        "NOT_AUTHENTICATED",
    )


def _one_slot(monkeypatch: pytest.MonkeyPatch) -> threading.BoundedSemaphore:
    """The process's admission slots, narrowed to one the test can hold."""
    slots = threading.BoundedSemaphore(1)
    monkeypatch.setattr(cases, "_SLOTS", slots)
    return slots


def _in_thread(send: Callable[[], Response]) -> tuple[threading.Thread, list[Response]]:
    answers: list[Response] = []
    thread = threading.Thread(target=lambda: answers.append(send()), daemon=True)
    thread.start()
    return thread, answers


def test_an_admission_waits_for_a_slot_before_it_reads_its_pack(
    case: tuple[StoreConnection, UUID],
    command_client: TestClient,
    seen: dict[str, int],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """N5: an admission holds its pack twice -- spooled by the form parser and
    read into memory -- then its extraction, for up to fifty documents, in the
    process that also runs the worker. Only `ADMISSION_SLOTS` do at once; the
    rest wait before a byte of their pack is read, holding no thread."""
    conn, case_id = case
    writer = member(conn, case_id)
    slots = _one_slot(monkeypatch)
    waiting = threading.Event()

    async def watched(seconds: float) -> None:
        waiting.set()
        await anyio.sleep(seconds)

    monkeypatch.setattr("caos.api.commands.cases.sleep", watched)
    assert slots.acquire(blocking=False), "the one slot, held by another admission"
    thread, answers = _in_thread(
        lambda: _admit(command_client, case_id, writer, [("a.txt", TEXT)])
    )
    try:
        assert waiting.wait(timeout=30), "the admission never waited for a slot"
        assert seen == {"form": 0, "prepare": 0}, "no byte of a waiting pack is read"
    finally:
        slots.release()
        thread.join(timeout=60)
    assert [answer.status_code for answer in answers] == [201]
    assert seen == {"form": 1, "prepare": 1}
    assert slots.acquire(blocking=False), "the slot is given back"
    slots.release()


def test_a_refused_admission_gives_its_slot_back(
    case: tuple[StoreConnection, UUID],
    command_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A refusal after the slot was taken -- here the document itself -- keeps
    its code and releases the slot, so the next admission is not left waiting."""
    conn, case_id = case
    writer = member(conn, case_id)
    slots = _one_slot(monkeypatch)
    broken = [("broken.pdf", b"%PDF-1.4\nnot a document")]

    refused = _admit(command_client, case_id, writer, broken)

    assert (refused.status_code, refused.json()["code"]) == (400, "SOURCE_NOT_READABLE")
    assert slots.acquire(blocking=False)
    slots.release()
    admitted = _admit(command_client, case_id, writer, [("a.txt", TEXT)])
    assert admitted.status_code == 201


def test_a_stranger_is_answered_without_waiting_for_a_slot(
    case: tuple[StoreConnection, UUID],
    command_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The slots are a writer's cost: identity, the envelope and standing are
    answered before one is asked for, so a stranger's upload never queues."""
    _conn, case_id = case
    slots = _one_slot(monkeypatch)
    assert slots.acquire(blocking=False)
    try:
        thread, answers = _in_thread(
            lambda: _admit(command_client, case_id, uuid4(), [("a.txt", TEXT)])
        )
        thread.join(timeout=30)
        assert not thread.is_alive(), "a stranger's upload waited for a slot"
    finally:
        slots.release()
    [answer] = answers
    assert (answer.status_code, answer.json()["code"]) == (404, "CASE_NOT_FOUND")


def test_extraction_holds_no_case_lock(
    case: tuple[StoreConnection, UUID],
    command_client: TestClient,
    empty_database: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn, case_id = case
    writer = member(conn, case_id)
    observed: list[tuple[bool, bool]] = []

    def prepare(documents: list[ingest.Document]) -> ingest.PreparedPack:
        idle = conn.info.transaction_status is TransactionStatus.IDLE
        with connect(empty_database) as other:
            locked = other.execute(
                "SELECT case_id FROM cases WHERE case_id = %s FOR UPDATE NOWAIT",
                (case_id,),
            ).fetchone()
            other.rollback()
        observed.append((idle, locked is not None))
        return ingest.prepare_pack(documents)

    monkeypatch.setattr(cases, "prepare_pack", prepare)

    assert _admit(command_client, case_id, writer, journey_pack()).status_code == 201
    assert observed == [(True, True)], "no open unit and the case lock is free"


def _free(other: StoreConnection, statement: str, case_id: UUID) -> str:
    try:
        row = other.execute(statement, (case_id,)).fetchone()
    except psycopg.errors.LockNotAvailable:
        return "locked"
    finally:
        other.rollback()
    return "free" if row is not None else "absent"


def test_the_admission_route_uploads_before_it_holds_the_case_or_the_chain(
    case: tuple[StoreConnection, UUID],
    command_client: TestClient,
    empty_database: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ED-5. F104 moved the puts ahead of `admit_prepared`'s own case lock,
    but the route calls it from inside the governed unit, and
    `governed_write` has taken the case row and the audit chain head by then:
    every Files API upload of up to fifty documents held both, so every
    fenced write of every run in the case and every governed command on it
    waited behind the uploads. The route puts the pack before the unit opens.
    """
    conn, case_id = case
    writer = member(conn, case_id)
    # An earlier governed act, so the case has a chain head to hold.
    assert _admit(command_client, case_id, writer, [("a.txt", TEXT)]).status_code == 201
    seen: list[tuple[str, str]] = []
    real_put = BlobStore.put

    def probing(store: BlobStore, data: bytes) -> str:
        with connect(empty_database) as other:
            seen.append(
                (
                    _free(
                        other,
                        "SELECT 1 FROM cases WHERE case_id = %s FOR UPDATE NOWAIT",
                        case_id,
                    ),
                    _free(
                        other,
                        "SELECT 1 FROM audit_chain_heads WHERE case_id = %s"
                        " FOR UPDATE NOWAIT",
                        case_id,
                    ),
                )
            )
        return real_put(store, data)

    monkeypatch.setattr(BlobStore, "put", probing)

    answer = _admit(command_client, case_id, writer, journey_pack())

    assert answer.status_code == 201, answer.json()
    assert seen == [("free", "free")] * 2, "an upload held the case or the chain"
    assert _sources(conn, case_id) == 3


class _Counting:
    """Counts store round trips (statements and cursors) on the request's
    connection, so each declared budget is measured rather than asserted."""

    def __init__(self, conn: StoreConnection) -> None:
        self._conn = conn
        self.executed = 0

    def execute(self, *args: Any, **kwargs: Any) -> object:  # noqa: ANN401
        self.executed += 1
        return self._conn.execute(*args, **kwargs)

    def cursor(self, *args: Any, **kwargs: Any) -> object:  # noqa: ANN401
        self.executed += 1
        return self._conn.cursor(*args, **kwargs)

    def __getattr__(self, name: str) -> object:
        return getattr(self._conn, name)


def test_each_case_command_declares_and_meets_its_store_budget(
    case: tuple[StoreConnection, UUID], command_client: TestClient
) -> None:
    conn, case_id = case
    writer = member(conn, case_id)

    def measured(send: Callable[[], Response]) -> tuple[int, int]:
        counter = _Counting(conn)
        app.dependency_overrides[store_connection] = lambda: counter
        answer = send()
        app.dependency_overrides[store_connection] = lambda: conn
        return answer.status_code, counter.executed

    user, key = uuid4(), uuid4()
    create = lambda: command_client.post(  # noqa: E731
        "/api/v1/cases", headers=command_headers(user, key=key), json={"title": "A"}
    )
    assert measured(create) == (201, cases.CREATE_CASE_IO)
    assert measured(create)[1] <= cases.REPLAY_IO

    one = measured(lambda: _admit(command_client, case_id, writer, [("a.txt", TEXT)]))
    two = measured(lambda: _admit(command_client, case_id, writer, journey_pack()))
    per_document = cases.ADMISSION_PER_DOCUMENT_IO
    assert one == (201, cases.ADMISSION_FIXED_IO + per_document)
    assert two == (201, cases.ADMISSION_FIXED_IO + 2 * per_document)
    key = uuid4()
    measured(
        lambda: _admit(command_client, case_id, writer, [("r.txt", TEXT)], key=key)
    )
    replay = measured(
        lambda: _admit(command_client, case_id, writer, [("r.txt", TEXT)], key=key)
    )
    assert replay[0] == 201 and replay[1] <= cases.REPLAY_IO
    assert cases.IO_BUDGET >= cases.ADMISSION_FIXED_IO + 50 * per_document


def test_the_case_commands_are_the_two_routes_of_their_router() -> None:
    served = {
        (route.path, route.endpoint)
        for route in cases.router.routes
        if isinstance(route, APIRoute)
    }
    assert served == {
        ("/api/v1/cases", cases.create_case_command),
        ("/api/v1/cases/{case_id}/sources", cases.admit_sources),
    }

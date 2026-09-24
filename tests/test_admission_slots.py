"""W3: an admission holds its slot only once its pack has arrived.

Review 3 found the admission slot taken before a byte of the pack was read,
and nothing bounding how long reading it could take: two uploads whose bodies
stalled held both slots, and every other writer's complete pack waited and was
refused `CONCURRENCY_LIMIT_REACHED`. Each waiter also held a store connection
and an in-flight place. These drive the real app over raw ASGI, the only way
to hold a body half-sent.
"""

from __future__ import annotations

import json
import time
from collections.abc import AsyncGenerator, Awaitable, Callable, Iterator
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import anyio
import pytest
from command_fixtures import Borrowed, member
from starlette.datastructures import Headers, UploadFile
from starlette.requests import ClientDisconnect

from caos.api import edge
from caos.api.app import app, blob_store, store_connection
from caos.api.commands import cases
from caos.api.edge import EdgeGuard
from caos.api.identity import TRUST_SWITCH, TRUSTED
from caos.api.wire import CLEARS
from caos.blobs import BlobStore
from caos.evidence.extract import DEFAULT_LIMITS
from caos.refusals import Refusal, RefusalCode
from caos.store import StoreConnection

BOUNDARY = "w3boundary"
# Past this a test fails rather than waiting on: a stalled body that nothing
# bounds is exactly the defect these tests pin, and it would otherwise hang.
TEST_SECONDS = 10
MULTIPART = Headers(
    raw=[(b"content-type", f"multipart/form-data; boundary={BOUNDARY}".encode())]
)
Message = dict[str, Any]
Answer = dict[str, object]


def _head() -> bytes:
    return (
        f"--{BOUNDARY}\r\n"
        'Content-Disposition: form-data; name="document"; filename="a.txt"\r\n'
        "Content-Type: text/plain\r\n\r\n"
    ).encode()


def _complete() -> bytes:
    return _head() + b"Quarterly text.\n\r\n" + f"--{BOUNDARY}--\r\n".encode()


def _scope(
    case_id: UUID, user: UUID, declared: int, method: str = "POST"
) -> dict[str, object]:
    path = (
        f"/api/v1/cases/{case_id}/sources" if method == "POST" else "/api/v1/directory"
    )
    return {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.4"},
        "http_version": "1.1",
        "method": method,
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "root_path": "",
        "headers": [
            (b"host", b"127.0.0.1:8000"),
            (b"x-caos-user", str(user).encode()),
            (b"x-caos-role", b"ANALYST"),
            (b"idempotency-key", str(uuid4()).encode()),
            (b"content-type", f"multipart/form-data; boundary={BOUNDARY}".encode()),
            (b"content-length", str(declared).encode()),
            (b"sec-fetch-site", b"same-origin"),
        ],
        "client": ("127.0.0.1", 50000),
        "server": ("127.0.0.1", 8000),
    }


async def _ask(
    guard: Callable[..., Awaitable[None]],
    scope: dict[str, object],
    receive: Callable[[], Awaitable[Message]],
) -> Answer:
    """One request through `guard`: its status and JSON body."""
    sent: list[Message] = []

    async def send(message: Message) -> None:
        sent.append(message)

    await guard(scope, receive, send)
    return {"status": sent[0]["status"], "body": json.loads(sent[1]["body"])}


def _stalling(started: anyio.Event, release: anyio.Event) -> Callable[..., Any]:
    """A client that sends the pack's first part header, then nothing."""
    calls = 0

    async def receive() -> Message:
        nonlocal calls
        calls += 1
        if calls == 1:
            return {"type": "http.request", "body": _head(), "more_body": True}
        started.set()
        await release.wait()
        return {"type": "http.disconnect"}

    return receive


def _sending(body: bytes) -> Callable[..., Any]:
    sent = False

    async def receive() -> Message:
        nonlocal sent
        if not sent:
            sent = True
            return {"type": "http.request", "body": body, "more_body": False}
        await anyio.sleep_forever()
        return {"type": "http.disconnect"}

    return receive


async def _stalled_upload(
    guard: Callable[..., Awaitable[None]],
    scope: dict[str, object],
    started: anyio.Event,
    release: anyio.Event,
) -> None:
    """A stalled upload, answered or abandoned; either ends it here."""
    try:
        await _ask(guard, scope, _stalling(started, release))
    except (ClientDisconnect, IndexError):
        pass


async def _once(body: bytes) -> AsyncGenerator[bytes]:
    yield body


def _slots_free() -> int:
    """How many admission slots nobody holds, read by taking them."""
    taken = 0
    while cases._SLOTS.acquire(blocking=False):
        taken += 1
    for _ in range(taken):
        cases._SLOTS.release()
    return taken


@pytest.fixture
def served(
    case: tuple[StoreConnection, UUID],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[list[Borrowed]]:
    """The app on the case's connection, one hold per resolution, as
    production opens one connection per resolution; every hold handed out."""
    conn, _case_id = case
    handed: list[Borrowed] = []

    def hold() -> Borrowed:
        handed.append(Borrowed(conn))
        return handed[-1]

    monkeypatch.setenv(TRUST_SWITCH, TRUSTED)
    app.dependency_overrides[store_connection] = hold
    app.dependency_overrides[blob_store] = lambda: BlobStore(tmp_path / "blobs")
    yield handed
    app.dependency_overrides.clear()


def test_stalled_uploads_hold_no_slot_and_another_pack_is_admitted(
    case: tuple[StoreConnection, UUID], served: list[Borrowed]
) -> None:
    """Two uploads whose bodies stall hold neither admission slot, so a third
    writer's complete pack is admitted while they stall."""
    conn, case_id = case
    slow_a, slow_b, other = (member(conn, case_id) for _ in range(3))
    declared = len(_head()) + 4096
    seen: dict[str, object] = {}

    async def main() -> None:
        release = anyio.Event()
        started = [anyio.Event(), anyio.Event()]
        with anyio.fail_after(TEST_SECONDS):
            await _admitted_while_stalled(release, started)

    async def _admitted_while_stalled(
        release: anyio.Event, started: list[anyio.Event]
    ) -> None:
        async with anyio.create_task_group() as group:
            for user, event in zip((slow_a, slow_b), started, strict=True):
                scope = _scope(case_id, user, declared)
                group.start_soon(_stalled_upload, app, scope, event, release)
            for event in started:
                await event.wait()
            seen["free_while_stalled"] = _slots_free()
            seen["admitted"] = await _ask(
                app, _scope(case_id, other, len(_complete())), _sending(_complete())
            )
            release.set()

    anyio.run(main)
    assert seen["free_while_stalled"] == cases.ADMISSION_SLOTS
    admitted = seen["admitted"]
    assert isinstance(admitted, dict)
    assert admitted["status"] == 201, admitted
    assert _slots_free() == cases.ADMISSION_SLOTS


def test_an_admission_waiting_for_a_slot_holds_no_store_connection(
    case: tuple[StoreConnection, UUID], served: list[Borrowed]
) -> None:
    """The standing read's connection is closed before the pack is received,
    and the admission's own is opened only once it holds a slot."""
    conn, case_id = case
    writer = member(conn, case_id)
    seen: dict[str, object] = {}

    async def main() -> None:
        for _ in range(cases.ADMISSION_SLOTS):
            assert cases._SLOTS.acquire(blocking=False)
        with anyio.fail_after(TEST_SECONDS):
            await _waiting()

    async def _waiting() -> None:
        async with anyio.create_task_group() as group:

            async def upload() -> None:
                seen["answer"] = await _ask(
                    app,
                    _scope(case_id, writer, len(_complete())),
                    _sending(_complete()),
                )

            group.start_soon(upload)
            while not served or not served[0].closed:
                await anyio.sleep(0.01)
            await anyio.sleep(cases.SLOT_POLL_SECONDS * 4)
            seen["waiting"] = "answer" not in seen
            seen["held_while_waiting"] = [not hold.closed for hold in served]
            for _ in range(cases.ADMISSION_SLOTS):
                cases._SLOTS.release()

    anyio.run(main)
    assert seen["waiting"] is True
    assert seen["held_while_waiting"] == [False]
    answer = seen["answer"]
    assert isinstance(answer, dict)
    assert answer["status"] == 201, answer
    assert len(served) == 2


def test_a_stalled_body_is_refused_at_its_deadline_and_frees_its_place(
    case: tuple[StoreConnection, UUID],
    served: list[Borrowed],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """uvicorn arms no timer while a body arrives, so the edge bounds it: a
    body past its deadline is refused `REQUEST_INVALID`, and the in-flight
    places stalled uploads held are free for another member's read."""
    conn, case_id = case
    writer, reader = member(conn, case_id), member(conn, case_id)
    monkeypatch.setattr(edge, "BODY_GRACE_SECONDS", 0.5)
    monkeypatch.setattr(edge, "BODY_MIN_BYTES_PER_SECOND", 10**12)
    guard = EdgeGuard(app, in_flight_limit=2)
    seen: dict[str, object] = {}
    answers: list[tuple[Answer, float]] = []

    async def stalled() -> None:
        started, release = anyio.Event(), anyio.Event()
        scope = _scope(case_id, writer, len(_head()) + 4096)
        began = time.monotonic()
        answer = await _ask(guard, scope, _stalling(started, release))
        answers.append((answer, time.monotonic() - began))

    async def main() -> None:
        with anyio.fail_after(TEST_SECONDS):
            async with anyio.create_task_group() as group:
                group.start_soon(stalled)
                group.start_soon(stalled)
        seen["read"] = await _ask(
            guard, _scope(case_id, reader, 0, method="GET"), _sending(b"")
        )

    anyio.run(main)
    assert len(answers) == 2
    for answer, elapsed in answers:
        assert answer["status"] == 400
        assert answer["body"] == {
            "code": "REQUEST_INVALID",
            "clears": CLEARS[RefusalCode.REQUEST_INVALID],
        }
        assert elapsed < 5
    read = seen["read"]
    assert isinstance(read, dict)
    assert read["status"] == 200


def test_a_received_pack_is_held_on_disk_until_its_slot() -> None:
    """N5's bound survives receiving the pack first: every part is spooled
    to a file from its first bytes, never held in memory while it waits."""

    async def main() -> list[bool]:
        parser = cases._PackParser(MULTIPART, _once(_complete()), max_fields=0)
        form = await parser.parse()
        try:
            return [
                isinstance(part, UploadFile) and not part._in_memory
                for _name, part in form.multi_items()
            ]
        finally:
            await form.close()

    assert anyio.run(main) == [True]


def test_one_document_past_the_ceiling_is_source_too_large() -> None:
    """N2 (CF-075): the parser's own file limit answered a generic
    `REQUEST_INVALID` for a pack more than one document past the ceiling."""
    parts = _head() + b"x\r\n"
    ceiling = DEFAULT_LIMITS.max_documents
    for count in (ceiling + 1, ceiling + 2, ceiling + 9):
        body = parts * count + f"--{BOUNDARY}--\r\n".encode()

        async def parse(body: bytes = body) -> None:
            await cases._PackParser(
                MULTIPART, _once(body), max_files=ceiling + 1
            ).parse()

        with pytest.raises(Refusal) as caught:
            anyio.run(parse)
        assert caught.value.code is RefusalCode.SOURCE_TOO_LARGE, count

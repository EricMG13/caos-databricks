"""The case event stream, over a real socket (brief 4.4, decisions 1-4 and 11).

`GET /api/v1/cases/{case_id}/events?run=` is served here by uvicorn on an
ephemeral port against PostgreSQL, because `TestClient` buffers a response
until it ends -- and every rule about an *open* stream (a withdrawal reaching
it, a revocation closing it) is exactly what a buffered body cannot show. The
test thread writes through its own connection while the server reads through
the one each request opens.
"""

from __future__ import annotations

import socket
import threading
import time
import weakref
from collections.abc import Callable, Generator, Iterator, Mapping
from pathlib import Path
from typing import cast
from uuid import UUID, uuid4

import httpx2 as httpx
import psycopg
import pytest
import uvicorn

from caos.api import app as app_module
from caos.api import stream, wire
from caos.api.app import app, store_connection
from caos.api.identity import ROLE_HEADER, TRUST_SWITCH, TRUSTED
from caos.api.stream import (
    CONNECT_IO,
    CURSOR_IO,
    FRAME_IO,
    POLL_IO,
    case_tail,
    take_stream_slot,
)
from caos.api.wire import CLEARS
from caos.blobs import BlobStore
from caos.boundary_text import BoundaryText
from caos.evidence.ingest import Document, admit_pack
from caos.refusals import Refusal, RefusalCode
from caos.store import StoreConnection, connect
from caos.store.audit import GovernedAction, actions_after, governed_write
from caos.store.events import RunEvent
from caos.store.gates import withdraw_source
from caos.store.members import Standing, grant, revoke
from caos.store.runs import create_case, fail_run, start_attempt, start_run

Frame = dict[str, str]
Headers = Mapping[str, str] | httpx.Headers
# Read at collection, before any test patches them.
REPO = Path(__file__).resolve().parents[1]
SHIPPED = (app_module.TAIL_DEADLINE, app_module.POLL_INTERVAL)


@pytest.fixture
def served(
    case: tuple[StoreConnection, UUID],
    empty_database: str,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[str]:
    """The app on a real socket, reading the test's database per request.

    Lifespan is off: `case` already applied the schema, and the health probe
    task is not this suite's subject. The deadline is short so that no stream a
    test abandons outlives it by much.
    """
    monkeypatch.setenv(app_module.DATABASE_URL, empty_database)
    # Tokenless, so no groups header is read: the development switch is how a
    # test here asserts a global role above the floor.
    monkeypatch.setenv(TRUST_SWITCH, TRUSTED)
    monkeypatch.setattr(app_module, "TAIL_DEADLINE", 0.0)
    monkeypatch.setattr(app_module, "POLL_INTERVAL", 0.02)
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    port = listener.getsockname()[1]
    server = uvicorn.Server(
        uvicorn.Config(
            app, lifespan="off", log_level="warning", timeout_graceful_shutdown=2
        )
    )
    thread = threading.Thread(
        target=server.run, kwargs={"sockets": [listener]}, daemon=True
    )
    thread.start()
    started = time.monotonic()
    while not server.started:
        assert time.monotonic() - started < 10, "the server did not start"
        time.sleep(0.01)
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        app.dependency_overrides.clear()
        server.should_exit = True
        thread.join(10)
        listener.close()


def _as(user: UUID | None, role: str | None = None) -> dict[str, str]:
    headers = {} if user is None else {"x-caos-user": str(user)}
    return headers if role is None else {**headers, ROLE_HEADER: role}


def _path(case_id: UUID | str, run_id: UUID | str | None = None) -> str:
    query = "" if run_id is None else f"?run={run_id}"
    return f"/api/v1/cases/{case_id}/events{query}"


def _refused(code: RefusalCode) -> dict[str, str]:
    return {"code": code.value, "clears": CLEARS[code]}


def _frames(response: httpx.Response) -> Iterator[Frame]:
    """Each SSE frame as its fields, in order, as they arrive.

    `retry` is dropped: it is on every cursor frame (N48,
    `test_the_cursor_frame_carries_a_short_reconnect_retry` names it
    directly), transport-level like the keepalive comment below it, and
    asserting it on every other cursor-frame check in this file would be
    noise repeated for no reason.
    """
    fields: Frame = {}
    for line in response.iter_lines():
        if line == "":
            if fields:
                yield fields
            fields = {}
            continue
        if line.startswith(":"):  # an SSE comment: the keepalive, not a field
            continue
        key, _, value = line.partition(": ")
        if key == "retry":
            continue
        fields[key] = value
    if fields:
        yield fields


def _stream(base: str, path: str, headers: Headers) -> list[Frame] | httpx.Response:
    """A whole (short) stream's frames, or the refused response."""
    with (
        httpx.Client(base_url=base, timeout=10) as http,
        http.stream("GET", path, headers=headers) as response,
    ):
        if response.status_code != 200:
            response.read()
            return response
        assert response.headers["content-type"].startswith("text/event-stream")
        assert response.headers["cache-control"] == "no-store"
        return list(_frames(response))


def _frames_of(base: str, path: str, headers: Headers) -> list[Frame]:
    answer = _stream(base, path, headers)
    assert isinstance(answer, list), (answer.status_code, answer.text)
    return answer


def _reader(conn: StoreConnection, case_id: UUID, standing: Standing) -> UUID:
    user = uuid4()
    grant(conn, case_id=case_id, user_id=user, standing=standing)
    conn.commit()
    return user


def _audit(conn: StoreConnection, case_id: UUID, action: str) -> None:
    """One audit entry with no state behind it: the stream reads the action
    name only, so the write it would record is not this suite's subject."""
    actor = _reader(conn, case_id, Standing.ADMIN)
    governed_write(
        conn,
        GovernedAction(case_id, actor, action, Standing.READER, {}),
        lambda _conn: None,
    )


def _source(conn: StoreConnection, case_id: UUID, tmp_path: Path) -> UUID:
    [source_id] = admit_pack(
        conn,
        BlobStore(tmp_path / "blobs"),
        case_id=case_id,
        documents=[
            Document(
                filename=BoundaryText.of("report.txt"),
                data=b"Total debt at 31 December 2026 was USD 1,240.0m\n",
            )
        ],
    )
    conn.commit()
    return source_id


def test_case_events_across_anonymous_nonmember_reader_writer_approver_revoked_and_admin(  # noqa: E501 -- the brief's name
    served: str, case: tuple[StoreConnection, UUID]
) -> None:
    conn, case_id = case
    members = {standing: _reader(conn, case_id, standing) for standing in Standing}
    revoked = _reader(conn, case_id, Standing.WRITER)
    revoke(conn, case_id=case_id, user_id=revoked)
    conn.commit()

    anonymous = _stream(served, _path(case_id), {})
    assert isinstance(anonymous, httpx.Response)
    assert (anonymous.status_code, anonymous.json()) == (
        401,
        _refused(RefusalCode.NOT_AUTHENTICATED),
    )

    for standing, user in members.items():
        assert _frames_of(served, _path(case_id), _as(user)) == [{"id": "0.0"}], (
            standing
        )

    refused = [
        (_path(case_id), _as(uuid4())),
        (_path(case_id), _as(revoked)),
        (_path(case_id), _as(uuid4(), "ADMIN")),
        (_path(uuid4()), _as(members[Standing.ADMIN])),
        (_path("not-a-case"), _as(members[Standing.ADMIN])),
    ]
    for path, headers in refused:
        answer = _stream(served, path, headers)
        assert isinstance(answer, httpx.Response), path
        assert (answer.status_code, answer.json()) == (
            404,
            _refused(RefusalCode.CASE_NOT_FOUND),
        ), path


def test_an_anonymous_event_request_is_401_and_opens_no_store_connection(
    served: str, case: tuple[StoreConnection, UUID]
) -> None:
    _conn, case_id = case
    opened: list[str] = []

    def counted() -> Iterator[StoreConnection]:
        opened.append(store_connection.__name__)
        raise AssertionError  # never reached before identity
        yield  # pragma: no cover

    app.dependency_overrides[store_connection] = counted

    for path in (_path(case_id), _path(case_id, uuid4()), _path("x", "y")):
        answer = _stream(served, path, {})
        assert isinstance(answer, httpx.Response)
        assert answer.status_code == 401, path
    assert opened == []


def test_a_run_of_another_case_is_run_not_found_on_the_event_stream(
    served: str, case: tuple[StoreConnection, UUID]
) -> None:
    conn, case_id = case
    reader = _reader(conn, case_id, Standing.READER)
    other = create_case(conn, BoundaryText.of("Another case"))
    elsewhere = start_run(conn, other)
    own = start_run(conn, case_id)
    conn.commit()

    for run_id in (elsewhere, uuid4(), "not-a-run"):
        answer = _stream(served, _path(case_id, run_id), _as(reader))
        assert isinstance(answer, httpx.Response), run_id
        assert (answer.status_code, answer.json()) == (
            404,
            _refused(RefusalCode.RUN_NOT_FOUND),
        ), run_id
    assert _frames_of(served, _path(case_id, own), _as(reader)) == [{"id": "0.0"}]


def test_the_retired_run_event_route_is_absent(
    served: str, case: tuple[StoreConnection, UUID]
) -> None:
    conn, case_id = case
    reader = _reader(conn, case_id, Standing.READER)
    run_id = start_run(conn, case_id)
    conn.commit()

    answer = _stream(served, f"/api/runs/{run_id}/events", _as(reader))

    assert isinstance(answer, httpx.Response)
    assert (answer.status_code, answer.json()) == (
        404,
        _refused(RefusalCode.ENDPOINT_NOT_FOUND),
    )
    assert not hasattr(app_module, "read_run_events")


def test_the_first_frame_is_a_cursor_at_the_current_heads(
    served: str, case: tuple[StoreConnection, UUID]
) -> None:
    """A fresh connection starts at the heads: the browser fetches documents on
    `open`, so replaying history would only refetch them again."""
    conn, case_id = case
    reader = _reader(conn, case_id, Standing.READER)
    run_id = start_run(conn, case_id)
    _audit(conn, case_id, "SOURCE_WITHDRAWN")
    _audit(conn, case_id, "OPINION_SIGNED")
    start_attempt(conn, run_id, "CP-1")
    conn.commit()

    frames = _frames_of(served, _path(case_id, run_id), _as(reader))
    audit_only = _frames_of(served, _path(case_id), _as(reader))

    assert frames == [{"id": "2.1"}]
    assert audit_only == [{"id": "2.0"}]


def test_the_cursor_frame_carries_a_short_reconnect_retry(
    served: str, case: tuple[StoreConnection, UUID]
) -> None:
    """N48. `TAIL_DEADLINE` (300 s) closes every tail, expected reconnect
    included; with no `retry` ever sent, the browser's own default reconnect
    delay is what a watcher saw as the gap, and a UI that reads a dropped
    connection as "paused" had no way to tell the two apart. Every cursor
    frame -- the first of any connection, this reconnect's included -- now
    carries one explicitly, short enough that the gap is not the read."""
    conn, case_id = case
    reader = _reader(conn, case_id, Standing.READER)
    with (
        httpx.Client(base_url=served, timeout=10) as http,
        http.stream("GET", _path(case_id), headers=_as(reader)) as response,
    ):
        lines = list(response.iter_lines())
    cursor = lines[: lines.index("")]
    assert f"retry: {int(app_module.POLL_INTERVAL * 1000)}" in cursor
    assert any(line.startswith("id: ") for line in cursor)


def test_frames_carry_only_a_cursor_a_name_and_empty_data(
    served: str, case: tuple[StoreConnection, UUID]
) -> None:
    conn, case_id = case
    reader = _reader(conn, case_id, Standing.READER)
    run_id = start_run(conn, case_id)
    _audit(conn, case_id, "SOURCE_WITHDRAWN")
    _audit(conn, case_id, "DELIVERABLE_FROZEN")
    start_attempt(conn, run_id, "CP-1")
    conn.commit()

    frames = _frames_of(
        served, _path(case_id, run_id), {**_as(reader), "last-event-id": "0.0"}
    )

    assert frames == [
        {"id": "0.0"},
        {"id": "1.0", "event": "sources_changed", "data": "{}"},
        {"id": "2.0", "event": "filing_changed", "data": "{}"},
        {"id": "2.1", "event": "run_progress", "data": "{}"},
    ]


def test_resume_delivers_strictly_after_the_composite_marker(
    served: str, case: tuple[StoreConnection, UUID]
) -> None:
    conn, case_id = case
    reader = _reader(conn, case_id, Standing.READER)
    run_id = start_run(conn, case_id)
    _audit(conn, case_id, "SOURCE_WITHDRAWN")
    _audit(conn, case_id, "GATE_RELEASED:SOURCE_SET")
    start_attempt(conn, run_id, "CP-0")
    start_attempt(conn, run_id, "CP-1")
    conn.commit()

    def resumed(marker: str) -> list[tuple[str, str]]:
        frames = _frames_of(
            served, _path(case_id, run_id), {**_as(reader), "last-event-id": marker}
        )
        assert frames[0] == {"id": marker}
        return [(frame["id"], frame["event"]) for frame in frames[1:]]

    assert resumed("1.1") == [("2.1", "runs_changed"), ("2.2", "run_progress")]
    assert resumed("2.1") == [("2.2", "run_progress")]
    assert resumed("0.2") == [("1.2", "sources_changed"), ("2.2", "runs_changed")]
    assert resumed("2.2") == []


def test_a_marker_that_cannot_be_used_resumes_from_the_heads_over_http(
    served: str, case: tuple[StoreConnection, UUID]
) -> None:
    conn, case_id = case
    reader = _reader(conn, case_id, Standing.READER)
    run_id = start_run(conn, case_id)
    _audit(conn, case_id, "SOURCE_WITHDRAWN")
    start_attempt(conn, run_id, "CP-1")
    conn.commit()

    for marker in (b"0.9", b"9.0", "\u00b9.0".encode(), b"; DROP TABLE runs"):
        headers = httpx.Headers(
            [(b"x-caos-user", str(reader).encode()), (b"last-event-id", marker)]
        )
        frames = _frames_of(served, _path(case_id, run_id), headers)
        assert frames == [{"id": "1.1"}], marker


def _open(
    base: str, path: str, headers: dict[str, str]
) -> tuple[httpx.Client, httpx.Response, Iterator[Frame]]:
    http = httpx.Client(base_url=base, timeout=10)
    response = http.send(http.build_request("GET", path, headers=headers), stream=True)
    assert response.status_code == 200
    return http, response, _frames(response)


def _held(
    monkeypatch: pytest.MonkeyPatch, deadline: float = 8.0, poll: float = 0.02
) -> None:
    monkeypatch.setattr(app_module, "TAIL_DEADLINE", deadline)
    monkeypatch.setattr(app_module, "POLL_INTERVAL", poll)


def test_withdrawal_reaches_an_open_http_stream_as_sources_changed(
    served: str,
    case: tuple[StoreConnection, UUID],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Withdrawal is recorded in `audit_events`, not `run_events`: a run tail
    alone never heard of it, which is why the stream is the case's."""
    conn, case_id = case
    source_id = _source(conn, case_id, tmp_path)
    writer = _reader(conn, case_id, Standing.WRITER)
    run_id = start_run(conn, case_id)
    conn.commit()
    _held(monkeypatch)

    http, response, frames = _open(served, _path(case_id, run_id), _as(writer))
    try:
        assert next(frames) == {"id": "0.0"}
        withdraw_source(conn, case_id=case_id, source_id=source_id, actor_id=writer)

        assert next(frames) == {"id": "1.0", "event": "sources_changed", "data": "{}"}
    finally:
        response.close()
        http.close()


def test_membership_revoked_mid_stream_closes_before_the_next_frame(
    served: str,
    case: tuple[StoreConnection, UUID],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two frames are pending in one poll; revocation lands between them, and
    the second is never written. The generator is where that pause can be
    held exactly; the socket shows the same close from outside."""
    conn, case_id = case
    reader = _reader(conn, case_id, Standing.READER)
    run_id = start_run(conn, case_id)
    conn.commit()

    stream = case_tail(
        conn, case_id=case_id, run_id=run_id, actor_id=reader, after=None
    )
    assert next(stream).name is None
    _audit(conn, case_id, "SOURCE_WITHDRAWN")
    start_attempt(conn, run_id, "CP-1")
    conn.commit()
    assert next(stream).name == "sources_changed"
    revoke(conn, case_id=case_id, user_id=reader)
    conn.commit()
    assert list(stream) == []

    other = _reader(conn, case_id, Standing.READER)
    _held(monkeypatch)
    http, response, frames = _open(served, _path(case_id, run_id), _as(other))
    try:
        started = time.monotonic()
        assert next(frames) == {"id": "1.1"}
        revoke(conn, case_id=case_id, user_id=other)
        conn.commit()
        _audit(conn, case_id, "SOURCE_WITHDRAWN")
        assert list(frames) == []
        assert time.monotonic() - started < 4
    finally:
        response.close()
        http.close()


def test_an_idle_stream_closes_when_standing_is_revoked(
    served: str, case: tuple[StoreConnection, UUID], monkeypatch: pytest.MonkeyPatch
) -> None:
    conn, case_id = case
    reader = _reader(conn, case_id, Standing.READER)
    conn.commit()
    _held(monkeypatch)

    http, response, frames = _open(served, _path(case_id), _as(reader))
    try:
        started = time.monotonic()
        assert next(frames) == {"id": "0.0"}
        time.sleep(0.1)  # idle polls, standing intact: still open
        revoke(conn, case_id=case_id, user_id=reader)
        conn.commit()

        assert list(frames) == []
        assert time.monotonic() - started < 4, "closed by the recheck, not the deadline"
    finally:
        response.close()
        http.close()


def test_an_idle_stream_hands_back_control_every_poll(
    case: tuple[StoreConnection, UUID],
) -> None:
    """An idle tail yields a keepalive after each poll, so the server notices a
    disconnected browser within one poll instead of holding a worker thread,
    a connection and a concurrency slot until the deadline."""
    conn, case_id = case
    reader = _reader(conn, case_id, Standing.READER)
    conn.commit()
    stream = case_tail(
        conn,
        case_id=case_id,
        run_id=None,
        actor_id=reader,
        after=None,
        deadline=60.0,
        poll=0.01,
        heartbeat=True,
    )
    started = time.monotonic()
    first = next(stream)
    assert first is not None and first.name is None
    assert next(stream) is None
    assert next(stream) is None
    del stream
    assert time.monotonic() - started < 2


def test_the_http_stream_writes_the_keepalive_as_a_comment(
    served: str, case: tuple[StoreConnection, UUID], monkeypatch: pytest.MonkeyPatch
) -> None:
    conn, case_id = case
    reader = _reader(conn, case_id, Standing.READER)
    conn.commit()
    _held(monkeypatch)
    with (
        httpx.Client(base_url=served, timeout=10) as http,
        http.stream("GET", _path(case_id), headers=_as(reader)) as response,
    ):
        lines = response.iter_lines()
        assert next(lines) == f"retry: {int(app_module.POLL_INTERVAL * 1000)}"
        assert next(lines) == "id: 0.0"
        assert next(lines) == ""
        assert next(lines) == ":"


class _Recording:
    """A store connection that records each statement it is asked to run."""

    def __init__(self, conn: StoreConnection, log: list[str]) -> None:
        self._conn = conn
        self._log = log

    def execute(self, *args: object, **kwargs: object) -> object:
        self._log.append(str(args[0]))
        return self._conn.execute(*args, **kwargs)  # type: ignore[arg-type]


def _record(url: str, log: list[str]) -> Callable[[], Iterator[_Recording]]:
    def recorded() -> Iterator[_Recording]:
        with connect(url) as conn:
            yield _Recording(conn, log)

    return recorded


def test_a_consumed_terminal_marker_never_rereads_or_redelivers_the_run_tail(
    served: str,
    case: tuple[StoreConnection, UUID],
    empty_database: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """F16. A late billing event after the terminal one is durable, but no
    stream delivers it, and once the terminal is behind the marker the tail
    rows are never read -- only the heads' aggregate touches `run_events`."""
    conn, case_id = case
    reader = _reader(conn, case_id, Standing.READER)
    run_id = start_run(conn, case_id)
    start_attempt(conn, run_id, "CP-1")
    fail_run(conn, run_id)
    conn.execute(
        "INSERT INTO run_events (run_id, seq, name) VALUES (%s, 3, %s)",
        (run_id, RunEvent.CALL_OUTCOME_RECORDED.value),
    )
    conn.commit()
    _held(monkeypatch, deadline=0.2)

    def streamed(marker: str | None) -> tuple[list[Frame], list[str]]:
        log: list[str] = []
        app.dependency_overrides[store_connection] = _record(empty_database, log)
        headers = _as(reader)
        if marker is not None:
            headers = {**headers, "last-event-id": marker}
        frames = _frames_of(served, _path(case_id, run_id), headers)
        return frames, [sql for sql in log if "run_events" in sql]

    delivered, reads = streamed("0.0")
    assert delivered[1:] == [
        {"id": "0.1", "event": "run_progress", "data": "{}"},
        {"id": "0.2", "event": "run_terminal", "data": "{}"},
    ]
    assert len(reads) == 2, "the heads, then one tail read up to the terminal"

    for marker in ("0.2", None):
        frames, reads = streamed(marker)
        assert frames == [{"id": "0.2" if marker else "0.3"}]
        assert len(reads) == 1 and "max(seq)" in reads[0], "the heads alone"


def test_the_stream_closes_at_its_deadline(
    served: str, case: tuple[StoreConnection, UUID], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The run never goes terminal and nobody is revoked, so the deadline is
    the only thing that ends the stream -- and the idle polls between are
    spaced, not spun."""
    conn, case_id = case
    reader = _reader(conn, case_id, Standing.READER)
    run_id = start_run(conn, case_id)
    start_attempt(conn, run_id, "CP-1")
    conn.commit()
    _held(monkeypatch, deadline=0.3, poll=0.05)
    polled: list[int] = []
    real = actions_after

    def counted(
        conn: StoreConnection, *, case_id: UUID, seq: int
    ) -> list[tuple[int, str]]:
        polled.append(seq)
        return real(conn, case_id=case_id, seq=seq)

    monkeypatch.setattr("caos.api.stream.actions_after", counted)

    started = time.monotonic()
    frames = _frames_of(served, _path(case_id, run_id), _as(reader))
    elapsed = time.monotonic() - started

    assert frames == [{"id": "0.1"}]
    assert 0.3 <= elapsed < 3
    assert 3 <= len(polled) <= 9
    assert SHIPPED == (300.0, 0.5), "five minutes, polled twice a second"


def test_the_event_stream_costs_its_declared_budget(
    served: str,
    case: tuple[StoreConnection, UUID],
    empty_database: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Counted, not described: the route's two reads, the heads, the cursor's
    recheck, then `POLL_IO` per poll and one recheck per frame."""
    conn, case_id = case
    reader = _reader(conn, case_id, Standing.READER)
    run_id = start_run(conn, case_id)
    _audit(conn, case_id, "SOURCE_WITHDRAWN")
    start_attempt(conn, run_id, "CP-1")
    conn.commit()
    _held(monkeypatch, deadline=0.1)
    log: list[str] = []
    app.dependency_overrides[store_connection] = _record(empty_database, log)

    frames = _frames_of(
        served, _path(case_id, run_id), {**_as(reader), "last-event-id": "0.0"}
    )

    polls = sum("FROM audit_events" in sql for sql in log) - 1  # minus the heads
    assert polls >= 1
    named = len(frames) - 1
    assert named == 2
    assert len(log) == 2 + CONNECT_IO + CURSOR_IO + polls * POLL_IO + named * FRAME_IO
    # The stream's own connect, cursor recheck and first poll are what it
    # declares; the cursor's recheck was once left out (ED-7).
    first_poll = len(log) - 2 - (polls - 1) * POLL_IO - named * FRAME_IO
    assert first_poll == stream.IO_BUDGET == CONNECT_IO + CURSOR_IO + POLL_IO
    assert app_module.EVENTS_IO_BUDGET == 2 + stream.IO_BUDGET
    assert app_module.IO_BUDGET == app_module.EVENTS_IO_BUDGET


def test_guarded_case_tail_refuses_a_post_connect_fault_as_store_unavailable(
    case: tuple[StoreConnection, UUID],
) -> None:
    """CF-022: a store fault mid-poll -- a dropped session, a statement
    timeout -- refuses `STORE_UNAVAILABLE` rather than escaping as the bare
    `psycopg.Error` an unhandled exception elsewhere would be logged with,
    its own message included. The response has long since started by the
    time any query here runs, so no fresh status reaches the wire either
    way; what changes is what is safe to raise and to log. `case_tail` itself
    is left as the bare generator this same file's other tests drive
    directly; `guarded(case_tail(...))` is what `app.py` and every other
    caller hold instead.
    """
    conn, case_id = case
    reader = _reader(conn, case_id, Standing.READER)
    conn.commit()
    tail = stream.guarded(
        stream.case_tail(
            conn,
            case_id=case_id,
            run_id=None,
            actor_id=reader,
            after=None,
            deadline=5.0,
            poll=0.01,
            heartbeat=True,
        )
    )

    assert next(tail) is not None  # the cursor frame

    with pytest.raises(Refusal) as caught:
        cast("Generator[object]", tail).throw(
            psycopg.OperationalError("server closed the connection")
        )

    assert caught.value.code is RefusalCode.STORE_UNAVAILABLE


def test_a_tail_slot_is_returned_however_the_stream_ends() -> None:
    """A leaked slot is capacity only a restart returns, so every way a tail
    can end has to give it back -- and there are three, not one.

    The `finally` covers a stream that runs out and one closed mid-flight,
    which is what a browser going away looks like to a generator. It does
    **not** cover a generator that is never started: a generator that has not
    reached its first `yield` has nothing to unwind, so its `finally` never
    runs. That case is measured here rather than reasoned about, because the
    first version of this code had exactly that hole and the journey could not
    see it -- Starlette always starts the body, so the leak needed a response
    that was built and then dropped.
    """
    slots = stream._Slots()

    def tail(slot: stream.StreamSlot) -> Generator[int]:
        try:
            yield 1
            yield 2
        finally:
            slot.release()

    for ending in ("never started", "closed mid-stream", "run to the end"):
        slot = take_stream_slot(slots, limit=5)
        opened = tail(slot)
        weakref.finalize(opened, slot.release)
        assert slots.open == 1, ending
        if ending == "closed mid-stream":
            next(opened)
            opened.close()
        elif ending == "run to the end":
            list(opened)
        # No collection: the last reference going is what returns the slot,
        # never a collector that may not run for hours (ED-1).
        del opened
        assert slots.open == 0, ending


def test_a_slot_is_given_back_once_even_though_two_things_release_it() -> None:
    """Both the `finally` and the finalizer run for an ordinary stream, and a
    counter that took both would drift *upward* in capacity with every tail --
    a cap that quietly stops capping, which is worse than no cap because it
    still reads like one."""
    slots = stream._Slots()
    slot = take_stream_slot(slots, limit=1)

    slot.release()
    slot.release()
    slot.release()

    assert slots.open == 0


def test_the_twenty_fifth_tail_is_refused_rather_than_the_next_ordinary_request() -> (
    None
):
    """The defect this closes. Uvicorn counts an open stream like any other
    request against `--limit-concurrency`, so without a cap of its own the
    watchers' pressure lands on an unrelated reader, with a 503 that names
    nothing they can act on. Refused here, it names the streams.

    The cap is asserted to sit *below* the process's limit, because a cap at or
    above it would leave no headroom and would change nothing.
    """
    slots = stream._Slots()
    for _ in range(stream.STREAM_LIMIT):
        take_stream_slot(slots)

    with pytest.raises(Refusal) as caught:
        take_stream_slot(slots)

    assert caught.value.code is RefusalCode.STREAM_LIMIT_REACHED
    from caos import serve

    assert stream.STREAM_LIMIT < serve.LIMIT_CONCURRENCY, "the cap leaves no headroom"


def test_a_refused_tail_answers_503_with_a_retry_after_and_its_clearance() -> None:
    """`STREAM_LIMIT_REACHED` is transient by the D3 question -- the identical
    request later, with nobody doing anything in between, plausibly succeeds,
    because a watcher only has to close a tab. So it answers 503 with
    `Retry-After`, where a fault only an operator can repair answers 500."""
    assert RefusalCode.STREAM_LIMIT_REACHED in app_module.TRANSIENT
    assert app_module._STATUS[RefusalCode.STREAM_LIMIT_REACHED] == 503
    assert wire.CLEARS[RefusalCode.STREAM_LIMIT_REACHED]

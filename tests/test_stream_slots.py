"""Who may hold the event-stream tails, and how many (MX-2, merging AS-3/TM-4).

The global cap answers the process: an open tail costs an AnyIO thread and an
unpooled store connection for up to `TAIL_DEADLINE`, and uvicorn counts it
against `--limit-concurrency` like any other request. It does not answer the
*tenant*: one authenticated reader with standing on one case could take all 24
and reopen each as it closed, and every other watcher was refused until that
reader stopped. The per-actor cap is what makes the global one a share.
"""

from __future__ import annotations

import gc
import socket
import threading
import time
from typing import Any
from uuid import UUID, uuid4

import pytest
import uvicorn
from starlette.requests import Request

from caos.api import stream
from caos.api.identity import TRUST_SWITCH, TRUSTED, Actor, GlobalRole
from caos.api.stream import ACTOR_STREAM_LIMIT, STREAM_LIMIT, take_stream_slot
from caos.refusals import Refusal, RefusalCode
from caos.store import StoreConnection
from caos.store.members import Standing, grant


def test_one_actor_cannot_take_every_tail_while_another_waits() -> None:
    """The defect MX-2 names. Four tails is a person watching a case and a run
    in two tabs; the fifth is refused, and the refusal lands on the actor who
    caused it rather than on the next reader to arrive.

    The global cap still has to be the backstop, so it is asserted to leave
    room for more than one such watcher: a per-actor share nobody else can
    reach is the same denial with extra steps.
    """
    slots = stream._Slots()
    greedy, other = uuid4(), uuid4()

    held = [take_stream_slot(slots, actor_id=greedy) for _ in range(ACTOR_STREAM_LIMIT)]

    with pytest.raises(Refusal) as caught:
        take_stream_slot(slots, actor_id=greedy)
    assert caught.value.code is RefusalCode.STREAM_LIMIT_REACHED

    # The fleet is not full, and the other watcher is served.
    take_stream_slot(slots, actor_id=other)
    assert slots.open == ACTOR_STREAM_LIMIT + 1

    # A closed tail returns the share it held.
    held[0].release()
    take_stream_slot(slots, actor_id=greedy)
    assert slots.held[greedy] == ACTOR_STREAM_LIMIT

    assert ACTOR_STREAM_LIMIT * 2 <= STREAM_LIMIT, "one watcher is not the fleet"


def test_the_global_cap_still_refuses_before_any_actor_reaches_their_share() -> None:
    """Whichever cap is met first answers, with the one code: to the refused
    watcher the two are the same fact, and a code that told them apart would
    tell a caller how much of the fleet they had taken."""
    slots = stream._Slots()
    watchers = [uuid4() for _ in range(STREAM_LIMIT)]
    for watcher in watchers:
        take_stream_slot(slots, actor_id=watcher)

    with pytest.raises(Refusal) as caught:
        take_stream_slot(slots, actor_id=uuid4())

    assert caught.value.code is RefusalCode.STREAM_LIMIT_REACHED
    assert slots.open == STREAM_LIMIT


def test_a_released_tail_leaves_no_row_behind_for_its_actor() -> None:
    """The per-actor count is memory the caller decides the size of, so it has
    to be bounded by the tails that are open and not by how many people have
    ever watched -- otherwise the cap that closes a denial opens a slower one."""
    slots = stream._Slots()

    for _ in range(50):
        slot = take_stream_slot(slots, actor_id=uuid4())
        slot.release()
        slot.release()  # one-shot: the finalizer runs after the `finally`

    assert (slots.held, slots.open) == ({}, 0)


def test_the_route_names_the_actor_it_takes_the_slot_for(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The cap is only a share if the route says whose it is. Asserted at the
    call rather than through a live stream, because what can silently regress
    here is one missing keyword, not the counting."""
    from caos.api import app as app_module

    named: list[UUID | None] = []

    def recorder(
        slots: stream._Slots = stream.SLOTS,
        limit: int = STREAM_LIMIT,
        *,
        actor_id: UUID | None = None,
        actor_limit: int = ACTOR_STREAM_LIMIT,
    ) -> stream.StreamSlot:
        named.append(actor_id)
        return stream.StreamSlot(stream._Slots())

    monkeypatch.setattr(app_module, "take_stream_slot", recorder)
    actor = Actor(user_id=uuid4(), role=GlobalRole.READER)
    request = Request({"type": "http", "method": "GET", "path": "/", "headers": []})
    # Neither is read on this path: no run means no ownership query, and the
    # tail is a generator whose body has not started.
    unread: Any = None

    app_module.read_case_events(
        actor=actor,
        case_id=uuid4(),
        run=None,
        _standing=unread,
        request=request,
        conn=unread,
    )

    assert named == [actor.user_id]


def _served_like_the_process() -> uvicorn.Server:
    """`caos.api.site:application` as `caos.serve` starts it: the guard
    outermost, the connection bound, the grace, no proxy headers and the log
    filter installed. Lifespan is off: the test's database already carries the
    schema, and the health loop is not this test's subject."""
    from caos import serve
    from caos.api.site import application

    serve.install_log_filter()
    return uvicorn.Server(
        uvicorn.Config(
            application,
            lifespan="off",
            log_level="warning",
            limit_concurrency=serve.LIMIT_CONCURRENCY,
            timeout_graceful_shutdown=serve.GRACEFUL_SECONDS,
            proxy_headers=False,
        )
    )


def _open_tail(port: int, path: str, user: UUID) -> socket.socket:
    """One raw `GET` of the tail, read up to its first frame."""
    sock = socket.create_connection(("127.0.0.1", port), timeout=10)
    sock.sendall(
        (
            f"GET {path} HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\n"
            f"x-caos-user: {user}\r\nsec-fetch-site: same-origin\r\n\r\n"
        ).encode("latin-1")
    )
    got = b""
    while b"id: " not in got:
        received = sock.recv(65536)
        if not received:
            break
        got += received
    assert got.startswith(b"HTTP/1.1 200"), got[:200]
    return sock


def _held_by(user: UUID) -> int:
    with stream.SLOTS.lock:
        return stream.SLOTS.held.get(user, 0)


def test_a_closed_tail_gives_its_slot_back_without_the_garbage_collector(
    case: tuple[StoreConnection, UUID],
    empty_database: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ED-1. A browser that closed its tail left the slot held until CPython's
    next *full* collection: Starlette cancels the body on the disconnect, the
    cancellation's traceback keeps `iterate_in_threadpool`'s frame alive in a
    cycle, and that frame held the sync generator whose `finally` gives the
    slot back. Four section changes spent an actor's share on dead tails, and
    every later tail answered 503 for minutes or hours.

    Served the way `caos.serve` serves it and with the collector off, so the
    test cannot pass by a collection happening to run: the slot comes back
    because the response ended, within the one poll the tail's thread may be
    sleeping through.
    """
    from caos.api import app as app_module

    conn, case_id = case
    user = uuid4()
    grant(conn, case_id=case_id, user_id=user, standing=Standing.READER)
    conn.commit()
    monkeypatch.setenv(app_module.DATABASE_URL, empty_database)
    monkeypatch.setenv(TRUST_SWITCH, TRUSTED)
    path = f"/api/v1/cases/{case_id}/events"
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    port = listener.getsockname()[1]
    server = _served_like_the_process()
    thread = threading.Thread(
        target=server.run, kwargs={"sockets": [listener]}, daemon=True
    )
    thread.start()
    started = time.monotonic()
    while not server.started:
        assert time.monotonic() - started < 10, "the server did not start"
        time.sleep(0.01)
    gc.disable()
    try:
        tails = [_open_tail(port, path, user) for _ in range(ACTOR_STREAM_LIMIT)]
        assert _held_by(user) == ACTOR_STREAM_LIMIT
        for tail in tails:
            tail.close()
        closed = time.monotonic()
        while _held_by(user) and time.monotonic() - closed < 1.0:
            time.sleep(0.02)
        assert _held_by(user) == 0, "a closed tail still holds its slot"
        fifth = _open_tail(port, path, user)
        assert time.monotonic() - closed < 1.0
        fifth.close()
    finally:
        gc.enable()
        server.should_exit = True
        thread.join(10)
        listener.close()

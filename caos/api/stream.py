"""The case stream: what the browser is told, and when it stops being told it.

One stream per case carries the case's audit actions and, for a named run,
that run's events -- because withdrawal is recorded in `audit_events`, which
a run tail never read.

A stream event carries a cursor and a name. Nothing else: the client never
reads payloads, and a payload would be a second copy of state the client is
about to fetch properly. The rules, each a decision rather than a detail:

*The first frame is a cursor.* It sets the browser's `lastEventId` to the
resume position and dispatches nothing.

*Resume excludes the marker.* Delivery starts strictly after it in both
sequences.

*Standing is rechecked before each frame and on each poll.* An SSE connection
is exactly the thing that stays open across a revocation, and losing standing
closes the stream rather than idling it.

*An idle stream still hands back control.* With `heartbeat`, each poll ends
in `None`, which the route writes as an SSE comment: the thread driving this
generator returns to the server every poll, so a browser that went away is
noticed within one poll rather than at the deadline.

*A delivered terminal ends the run half.* Once the run's terminal event has
been delivered, or the marker is already past it, `run_events` is never read
again for this stream -- late billing after a terminal stays durable and is not
redelivered (F16). The audit half polls on until the deadline.

The HTTP binding is `caos/api/app.py`'s: this module yields, it does not
frame.
"""

from __future__ import annotations

from collections.abc import Generator, Iterator
from dataclasses import dataclass, field
from threading import Lock
from time import monotonic, sleep
from uuid import UUID

import psycopg

from caos.api.events import STREAM_NAMES, Marker, parse_marker
from caos.api.wire import EventName
from caos.refusals import Refusal, RefusalCode
from caos.store import StoreConnection
from caos.store.audit import actions_after
from caos.store.events import RunEvent
from caos.store.members import Standing, satisfies, standing_of

# Once per connection: the heads and the run's terminal position, one query.
CONNECT_IO = 1
# And the standing recheck before the cursor frame, which the declared budget
# left out: the generator's connect and first poll cost five, not four (ED-7).
CURSOR_IO = 1
# Per poll: the audit actions after the cursor, the run events after it (until
# the terminal is delivered), and the standing recheck. Each named frame then
# costs one more recheck -- the N+1 §9 mandates, spread across the stream's
# life, and at most `ACTIONS_PAGE + RUN_PAGE` of them in one poll.
POLL_IO = 3
FRAME_IO = 1
IO_BUDGET = CONNECT_IO + CURSOR_IO + POLL_IO

# How many run events one poll reads; the next poll continues after the last.
RUN_PAGE = 500

# How many tails may be open at once, against the image's
# `--limit-concurrency 32` (`Dockerfile`). Uvicorn counts an open stream like
# any other request, so without a cap of its own 32 watching tabs refuse the
# 33rd *ordinary* request with a 503 that says nothing about streams -- the
# failure lands on a reader who did nothing wrong and names nothing they can
# act on. Capped below the limit, the pressure is answered where it is caused:
# the 25th tail is refused `STREAM_LIMIT_REACHED`, and the eight slots left
# over are what keep the rest of the surface answering.
#
# Deliberately not derived from the uvicorn setting at run time. The image's
# CMD and `make dev-api` start the server with different values, and a cap that
# silently followed whichever was in force would be a bound no reader could
# find in the source.
STREAM_LIMIT = 24

# And how many of them any one actor may hold. The global cap alone is a cap on
# the fleet, not a share of it: one authenticated reader with standing on one
# case could open all 24 tails and reopen each as it closed, and every other
# watcher in the tenant was refused `STREAM_LIMIT_REACHED` until that reader
# stopped (MX-2, merging AS-3 and TM-4). Four is what a person plausibly
# watches at once -- a case and a run in two tabs -- and six such people still
# fit inside the global cap, which stays as the backstop the thread pool and
# the connection count actually need.
ACTOR_STREAM_LIMIT = 4


@dataclass
class _Slots:
    """How many tails are open, in total and per actor. Guarded, because
    uvicorn runs this route in a thread pool and two watchers can arrive at
    once. `held` carries an entry only while an actor holds a tail, so it is
    bounded by `open` and never by how many people have ever watched."""

    lock: Lock = field(default_factory=Lock)
    open: int = 0
    held: dict[UUID, int] = field(default_factory=dict)


SLOTS = _Slots()


class StreamSlot:
    """One held tail slot, given back exactly once however the stream ends.

    One-shot because it is released from three places and none may double
    count. The ordinary path is the route's response, whose `__call__` gives
    it back in a `finally` when the tail is delivered, hits its deadline,
    loses standing, or the browser goes away -- not the generator's own
    `finally`, which a disconnect's cancellation used to leave waiting for a
    full garbage collection (ED-1). The generator's `finally` still releases
    for anyone iterating it directly. The third is a `weakref.finalize` on the
    generator, for the one case neither can reach: **a generator that is
    never started never unwinds**, so a response built and then never sent
    would hold its slot until the process restarted. Measured rather than
    assumed -- a generator dropped before its first `next()` leaves the counter
    raised, and that slot is capacity only a restart returns.
    """

    __slots__ = ("_actor_id", "_held", "_slots")

    def __init__(self, slots: _Slots, actor_id: UUID | None = None) -> None:
        self._slots, self._held, self._actor_id = slots, True, actor_id

    def release(self) -> None:
        with self._slots.lock:
            if not self._held:
                return
            self._slots.open -= 1
            self._held = False
            if self._actor_id is None:
                return
            remaining = self._slots.held.get(self._actor_id, 0) - 1
            if remaining > 0:
                self._slots.held[self._actor_id] = remaining
            else:
                self._slots.held.pop(self._actor_id, None)


def take_stream_slot(
    slots: _Slots = SLOTS,
    limit: int = STREAM_LIMIT,
    *,
    actor_id: UUID | None = None,
    actor_limit: int = ACTOR_STREAM_LIMIT,
) -> StreamSlot:
    """Take one of the tail slots, or refuse `STREAM_LIMIT_REACHED`.

    Two caps, one code. The global one is what the thread pool and the
    unpooled connections need; the per-actor one is what keeps the global one
    from being spent by a single caller. Both refuse the same way, because to
    the refused watcher they are the same fact -- the stream is not available
    now, try again -- and a code that distinguished them would tell a caller
    how much of the fleet they had taken.

    Taken in the route rather than in the generator, because the response does
    not exist there yet and a refusal can still be an ordinary refusal body
    with a status and a `Retry-After`. What it hands back is the thing the
    stream gives up when the tail is over.
    """
    with slots.lock:
        if slots.open >= limit:
            raise Refusal(RefusalCode.STREAM_LIMIT_REACHED)
        if actor_id is not None and slots.held.get(actor_id, 0) >= actor_limit:
            raise Refusal(RefusalCode.STREAM_LIMIT_REACHED)
        slots.open += 1
        if actor_id is not None:
            slots.held[actor_id] = slots.held.get(actor_id, 0) + 1
    return StreamSlot(slots, actor_id)


# The events that end the run half of a stream.
TERMINAL = frozenset(
    {
        RunEvent.RUN_COMPLETE.value,
        RunEvent.RUN_FAILED.value,
        RunEvent.RUN_BLOCKED.value,
        RunEvent.RUN_CANCELLED.value,
    }
)

# Watching a case is reading it. Anything a stream can reveal, the section
# documents reveal to the same person.
WATCH_REQUIRES = Standing.READER


@dataclass(frozen=True, slots=True)
class StreamEvent:
    """One frame: the position to resume from, and the name that triggers a
    refetch -- `None` for the cursor-only frame."""

    id: Marker
    name: EventName | None


def case_tail(  # noqa: PLR0913 -- the stream's identity, then its lifetime
    conn: StoreConnection,
    *,
    case_id: UUID,
    run_id: UUID | None,
    actor_id: UUID,
    after: str | None,
    deadline: float = 0.0,
    poll: float = 0.0,
    heartbeat: bool = False,
) -> Iterator[StreamEvent | None]:
    """The cursor frame, then named frames after `after`, polling every `poll`
    seconds until `deadline` seconds have passed or standing is lost.

    `after` is the raw `Last-Event-ID`; it is parsed against the heads read
    here. A deadline of zero is one poll. Yields nothing at all to an actor
    who cannot read the case.

    A store fault reaches a caller here as the bare `psycopg.Error` it is;
    `guarded(case_tail(...))` is what every caller outside this module and
    its own tests should hold instead (CF-022). Kept apart from this
    function's own body -- rather than a `try` wrapped around it -- so the
    fix costs this function no added nesting (C901).
    """
    started = monotonic()
    audit_head, run_head, terminal = _heads(conn, case_id, run_id)
    at = parse_marker(after, Marker(audit_head, run_head))
    run_open = run_id is not None and (terminal is None or at.run_seq < terminal)
    cursor = _Cursor(at, run_open)

    if not _may_watch(conn, case_id, actor_id):
        return
    yield StreamEvent(at, None)

    while True:
        standing = yield from _poll(conn, case_id, run_id, actor_id, cursor)
        if not standing or monotonic() - started >= deadline:
            return
        sleep(poll)
        if heartbeat:
            yield None


@dataclass(slots=True)
class _Cursor:
    """Where a tail has read to, and whether its run half is still open."""

    at: Marker
    run_open: bool


def _poll(
    conn: StoreConnection,
    case_id: UUID,
    run_id: UUID | None,
    actor_id: UUID,
    cursor: _Cursor,
) -> Generator[StreamEvent, None, bool]:
    """One poll's named frames after the cursor, moving it past every row,
    silent ones included; whether the actor may still watch afterwards.
    Standing is read again before each named frame, and a frame is never
    sent once it is lost."""
    for event, closes in _pending(
        conn, case_id, run_id if cursor.run_open else None, cursor.at
    ):
        cursor.at = event.id
        if event.name is not None:
            if not _may_watch(conn, case_id, actor_id):
                return False
            yield event
        cursor.run_open = cursor.run_open and not closes
    return _may_watch(conn, case_id, actor_id)


def guarded(tail: Iterator[StreamEvent | None]) -> Iterator[StreamEvent | None]:
    """Any `case_tail(...)`-shaped generator, with a store fault (CF-022)
    refused `STORE_UNAVAILABLE` rather than left to escape as the bare
    `psycopg.Error` an unhandled exception elsewhere would be logged with,
    its own message included.

    The response has long since started by the time any query `case_tail`
    makes runs, so no fresh status reaches the wire either way; what changes
    is what is safe to raise and to log. Generic over the generator rather
    than over `case_tail`'s own eight parameters, so it adds no second copy
    of its signature (and no second `PLR0913`) beside it -- every caller
    outside this module's own tests of `case_tail` itself should hold this
    wrapped around it.
    """
    try:
        yield from tail
    except psycopg.Error:
        raise Refusal(RefusalCode.STORE_UNAVAILABLE) from None


def _pending(
    conn: StoreConnection, case_id: UUID, run_id: UUID | None, at: Marker
) -> list[tuple[StreamEvent, bool]]:
    """One poll's rows after `at`, each with its cursor and name (`None` for a
    silent row, which still advances the cursor), and whether it ends the run
    half. The run's rows stop at its terminal; `run_id` is `None` once that has
    been delivered, and the run is not read at all."""
    pending: list[tuple[StreamEvent, bool]] = []
    for seq, action in actions_after(conn, case_id=case_id, seq=at.audit_seq):
        at = Marker(seq, at.run_seq)
        pending.append((StreamEvent(at, STREAM_NAMES.get(action)), False))
    if run_id is None:
        return pending
    for seq, event in _run_events_after(conn, run_id, at.run_seq):
        at = Marker(at.audit_seq, seq)
        closes = event in TERMINAL
        pending.append((StreamEvent(at, STREAM_NAMES.get(event)), closes))
        if closes:
            break
    return pending


def _may_watch(conn: StoreConnection, case_id: UUID, actor_id: UUID) -> bool:
    return satisfies(
        standing_of(conn, case_id=case_id, user_id=actor_id), WATCH_REQUIRES
    )


def _heads(
    conn: StoreConnection, case_id: UUID, run_id: UUID | None
) -> tuple[int, int, int | None]:
    """The case's audit head, the run's event head, and the run's first
    terminal position -- aggregates only, never the tail's rows."""
    row = conn.execute(
        "SELECT"
        " (SELECT coalesce(max(seq), 0) FROM audit_events WHERE case_id = %s),"
        " (SELECT coalesce(max(seq), 0) FROM run_events WHERE run_id = %s),"
        " (SELECT min(seq) FROM run_events WHERE run_id = %s AND name = ANY(%s))",
        (case_id, run_id, run_id, sorted(TERMINAL)),
    ).fetchone()
    if row is None:  # pragma: no cover -- a scalar SELECT always returns a row
        return 0, 0, None
    return int(row[0]), int(row[1]), None if row[2] is None else int(row[2])


def _run_events_after(
    conn: StoreConnection, run_id: UUID, seq: int
) -> list[tuple[int, str]]:
    rows = conn.execute(
        "SELECT seq, name FROM run_events WHERE run_id = %s AND seq > %s"
        " ORDER BY seq LIMIT %s",
        (run_id, seq, RUN_PAGE),
    ).fetchall()
    return [(int(row[0]), str(row[1])) for row in rows]

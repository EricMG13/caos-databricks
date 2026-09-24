"""Phase 6 exit: the stream stops reading a run once its terminal is delivered.

Brief 4.4 decisions 3 and 4 restate it for the case
stream. A frame carries a composite cursor and a name, and nothing else: the
client never reads a payload -- a name triggers a refetch. These tests drive
`case_tail` as a generator, which is where a pause between two frames can be
held exactly; `tests/test_case_events.py` drives the same rules over a socket.
"""

from __future__ import annotations

from collections.abc import Iterator
from decimal import Decimal
from pathlib import Path
from typing import cast
from uuid import UUID, uuid4

import pytest
from run_terminals import fail_run
from test_run_events import RECORD, accept_nodes, approved_nodes

from caos.api.events import Marker
from caos.api.stream import TERMINAL, StreamEvent, case_tail
from caos.refusals import Refusal
from caos.store import StoreConnection
from caos.store.events import RunEvent, events_of
from caos.store.members import Standing, grant, revoke
from caos.store.runs import (
    Accepted,
    block_run,
    complete_attempt,
    complete_run,
    start_attempt,
    start_run,
)
from caos.store.work import enqueue_run, request_cancel

# The producer the store records beside every accepted artifact: what the
# host configured, and the provider's own handle for the call.
MODEL = "a-model/for-the-test"
GENERATION = "gen-for-the-test"

ARTIFACT = "e" * 64
CHARGE = Decimal("0.01")


@pytest.fixture
def watched(
    case: tuple[StoreConnection, UUID],
) -> tuple[StoreConnection, UUID, UUID, UUID]:
    """A run, its case, and a READER entitled to watch it."""
    conn, case_id = case
    run_id = start_run(conn, case_id)
    viewer = uuid4()
    grant(conn, case_id=case_id, user_id=viewer, standing=Standing.READER)
    conn.commit()
    return conn, case_id, run_id, viewer


def _approved(conn: StoreConnection, run_id: UUID, blobs: Path) -> str:
    """Govern the run on the real route and accept all but its last node:
    acceptance requires the pin, completion every other node (brief 4.3 D8)."""
    *others, last = approved_nodes(conn, run_id, blobs).values()
    accept_nodes(conn, run_id, *others)
    return last


def _next_event(stream: Iterator[StreamEvent | None]) -> StreamEvent:
    """`next(stream)`, narrowed: none of this module's tails run with
    `heartbeat`, so no frame is ever `None`."""
    event = next(stream)
    assert event is not None
    return event


def _tail(
    watched: tuple[StoreConnection, UUID, UUID, UUID], after: str | None = "0.0"
) -> list[StreamEvent]:
    """One pass of the stream after `after`, without its cursor frame."""
    conn, case_id, run_id, viewer = watched
    cursor, *events = list(
        case_tail(conn, case_id=case_id, run_id=run_id, actor_id=viewer, after=after)
    )
    assert cursor is not None and cursor.name is None
    assert all(event is not None for event in events)
    return cast(list[StreamEvent], events)


def _run_names(events: list[StreamEvent]) -> list[str | None]:
    """The run's own frames: an audit frame never moves the run cursor."""
    run_frames: list[str | None] = []
    last = 0
    for event in events:
        if event.id.run_seq != last:
            run_frames.append(event.name)
            last = event.id.run_seq
    return run_frames


def _complete(conn: StoreConnection, run_id: UUID, node: str) -> None:
    attempt_id = start_attempt(conn, run_id, node)
    complete_attempt(
        conn,
        attempt_id=attempt_id,
        accepted=Accepted(
            artifact_sha256=ARTIFACT,
            charge=CHARGE,
            model=MODEL,
            generation_id=GENERATION,
            record_sha256=RECORD,
        ),
    )


def test_sse_closes_after_terminal_delivery(
    watched: tuple[StoreConnection, UUID, UUID, UUID], tmp_path: Path
) -> None:
    """The Phase 6 exit test, with F16 closed.

    The terminal event is the last run frame, and a late billing event after
    it is never delivered -- not in this pass, and not to a stream resumed
    after the terminal marker, which does not read the run tail at all.
    """
    conn, _case_id, run_id, _viewer = watched
    _complete(conn, run_id, _approved(conn, run_id, tmp_path))
    conn.execute(
        "INSERT INTO run_events (run_id, seq, name) VALUES (%s, %s, %s)",
        (run_id, 13, RunEvent.CALL_OUTCOME_RECORDED.value),
    )
    conn.commit()

    delivered = _tail(watched)

    accepted = ["run_progress", "run_progress", "handoff_accepted"]
    assert _run_names(delivered) == [
        "run_progress",
        "run_progress",
        *accepted * 3,
        "run_terminal",
    ]
    assert delivered[-1].name == "run_terminal"
    assert delivered[-1].id.run_seq == 12, "delivery stopped at the terminal event"
    resumed = f"{delivered[-1].id.audit_seq}.12"
    assert _tail(watched, after=resumed) == []


@pytest.mark.parametrize("ending", ["failed", "blocked", "cancelled"])
def test_every_terminal_run_ends_the_run_tail_too(
    watched: tuple[StoreConnection, UUID, UUID, UUID], ending: str
) -> None:
    conn, _case_id, run_id, _viewer = watched
    if ending == "failed":
        assert fail_run(conn, run_id)
    elif ending == "blocked":
        assert block_run(conn, run_id)
        assert not block_run(conn, run_id), "the terminal event is exactly-once"
    else:
        enqueue_run(conn, run_id)
        assert request_cancel(conn, run_id)
        conn.commit()
        assert not request_cancel(conn, run_id), "the terminal event is exactly-once"
    conn.commit()

    assert [(e.id, e.name) for e in _tail(watched)] == [(Marker(0, 1), "run_terminal")]
    assert RunEvent.RUN_CANCELLED.value in TERMINAL


def test_a_blocked_run_refuses_new_attempts(
    watched: tuple[StoreConnection, UUID, UUID, UUID],
) -> None:
    conn, _case_id, run_id, _viewer = watched
    block_run(conn, run_id)
    with pytest.raises(Refusal, match=r"^RUN_NOT_RUNNING$"):
        start_attempt(conn, run_id, "CP-1")
    # Blocked is not a way station to success: completion adds nothing.
    assert not complete_run(conn, run_id)
    assert [e.name for e in events_of(conn, run_id)] == [RunEvent.RUN_BLOCKED.value]


def test_a_running_run_delivers_what_there_is_and_stops(
    watched: tuple[StoreConnection, UUID, UUID, UUID],
) -> None:
    """Not terminal, so one pass is caught up rather than closed; the route's
    loop polls again, and nothing here blocks waiting."""
    conn, _case_id, run_id, _viewer = watched
    start_attempt(conn, run_id, "CP-1")
    conn.commit()

    assert [(e.id, e.name) for e in _tail(watched)] == [(Marker(0, 1), "run_progress")]


def test_a_tail_resumes_strictly_after_its_marker(
    watched: tuple[StoreConnection, UUID, UUID, UUID],
) -> None:
    """Re-delivering the marker's own event would make a client that refetches
    on every name do the work twice."""
    conn, _case_id, run_id, _viewer = watched
    for node in ("CP-0", "CP-1", "CP-2"):
        start_attempt(conn, run_id, node)
    conn.commit()

    assert [e.id for e in _tail(watched, after="0.1")] == [Marker(0, 2), Marker(0, 3)]
    assert _tail(watched, after="0.3") == []


def test_the_stream_carries_a_cursor_and_a_name_and_nothing_else(
    watched: tuple[StoreConnection, UUID, UUID, UUID],
) -> None:
    conn, _case_id, run_id, _viewer = watched
    start_attempt(conn, run_id, "CP-1")
    conn.commit()

    [event] = _tail(watched)

    assert isinstance(event, StreamEvent)
    assert (str(event.id), event.name) == ("0.1", "run_progress")
    assert set(StreamEvent.__dataclass_fields__) == {"id", "name"}


def test_a_non_member_is_delivered_nothing(
    watched: tuple[StoreConnection, UUID, UUID, UUID],
) -> None:
    """Not even the cursor: the route answers a stranger 404 before this runs,
    and the generator is silent for one on its own."""
    conn, case_id, run_id, _viewer = watched
    start_attempt(conn, run_id, "CP-1")
    conn.commit()

    assert (
        list(
            case_tail(
                conn, case_id=case_id, run_id=run_id, actor_id=uuid4(), after=None
            )
        )
        == []
    )


def test_membership_is_rechecked_before_each_event(
    watched: tuple[StoreConnection, UUID, UUID, UUID],
) -> None:
    """Not once at the handshake. An SSE connection is exactly the thing that
    stays open across a revocation."""
    conn, case_id, run_id, viewer = watched
    start_attempt(conn, run_id, "CP-0")
    start_attempt(conn, run_id, "CP-1")
    conn.commit()

    stream = case_tail(
        conn, case_id=case_id, run_id=run_id, actor_id=viewer, after="0.0"
    )
    assert _next_event(stream).name is None
    first = _next_event(stream)

    revoke(conn, case_id=case_id, user_id=viewer)
    conn.commit()

    assert first.name == "run_progress"
    assert list(stream) == [], "the second event reached a member who is not one"

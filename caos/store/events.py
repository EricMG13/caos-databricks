"""The run's event stream: append-only, numbered per run, ordered by a row lock.

`SYSTEM_SPEC.md` section 2: `run_events.seq` is per-run monotonic, allocated
under the run row lock, and no event is inserted without the transition it
records. The second half is enforced by the callers in `runs.py`, which append
only on a conditional update that changed a row. The first half is enforced
here: `append` takes the lock itself rather than trusting its caller to have
taken it, because "allocated under the run row lock" is not a comment.

The stream is what the browser tails (`SYSTEM_SPEC.md` section 9) and the client
never reads an event's payload -- a name triggers a refetch. So an event carries
a name and a position, and nothing a document produced.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from caos.refusals import Refusal, RefusalCode
from caos.store import RunStatus, StoreConnection, rollback_or_close
from caos.store.cases import lock_case


class RunEvent(StrEnum):
    """Every event a run can carry. The `run_events_name_is_known` CHECK holds
    the same set; `test_every_run_event_is_one_the_database_accepts` keeps them
    from becoming two."""

    ROUTE_PINNED = "ROUTE_PINNED"
    INPUT_PINNED = "INPUT_PINNED"
    ATTEMPT_STARTED = "ATTEMPT_STARTED"
    CALL_OUTCOME_RECORDED = "CALL_OUTCOME_RECORDED"
    ATTEMPT_ACCEPTED = "ATTEMPT_ACCEPTED"
    RUN_COMPLETE = "RUN_COMPLETE"
    RUN_FAILED = "RUN_FAILED"
    RUN_BLOCKED = "RUN_BLOCKED"
    RUN_CANCELLED = "RUN_CANCELLED"


@dataclass(frozen=True, slots=True)
class Event:
    """One position in one run's stream."""

    seq: int
    name: str
    at: datetime


def lock_run(conn: StoreConnection, run_id: UUID) -> RunStatus:
    """Lock the immutable owner case, then the run; caller owns commit.

    Read status in a new statement after waiting for the case, so a transition
    committed during the wait is visible under READ COMMITTED.

    `RUN_NOT_FOUND` ends the unit first. The first statement opens the caller's
    transaction and takes an `ACCESS SHARE` on `runs`; raising with it open left
    that lock held for as long as the caller went on doing whatever it did next,
    for a run that is not there and that no later statement of that unit could
    make appear. Every other refusal that takes a lock here -- `pin_route`,
    `apply_schema`, `reserve` -- ends its transaction the same way.
    """
    owner = conn.execute(
        "SELECT case_id FROM runs WHERE run_id = %s", (run_id,)
    ).fetchone()
    if owner is None:
        rollback_or_close(conn)
        raise Refusal(RefusalCode.RUN_NOT_FOUND)
    lock_case(conn, UUID(str(owner[0])), missing=RefusalCode.RUN_NOT_FOUND)
    row = conn.execute(
        "SELECT status FROM runs WHERE run_id = %s FOR UPDATE", (run_id,)
    ).fetchone()
    if row is None:
        rollback_or_close(conn)
        raise Refusal(RefusalCode.RUN_NOT_FOUND)
    return RunStatus(row[0])


def append(conn: StoreConnection, run_id: UUID, event: RunEvent) -> None:
    """Append `event` to the run's stream.

    Never call this except beside the transition it records, in that
    transition's transaction.

    The position is allocated by the same statement that takes it. Reading
    `max(seq)` and inserting it back separately is two round trips, and the
    caller would have to be trusted to keep them in one transaction for the
    lock above to mean anything.
    """
    lock_run(conn, run_id)
    conn.execute(
        "INSERT INTO run_events (run_id, seq, name)"
        " SELECT %s::uuid, coalesce(max(seq), 0) + 1, %s::text"
        " FROM run_events WHERE run_id = %s",
        (run_id, event.value, run_id),
    )


def events_of(conn: StoreConnection, run_id: UUID) -> list[Event]:
    """The run's stream in order. The order is the `seq`, never the clock: two
    events can share a timestamp and never share a position."""
    rows = conn.execute(
        "SELECT seq, name, at FROM run_events WHERE run_id = %s ORDER BY seq",
        (run_id,),
    ).fetchall()
    return [Event(seq=int(seq), name=name, at=at) for seq, name, at in rows]

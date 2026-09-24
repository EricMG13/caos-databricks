"""The run work queue: one claim per run, fenced by a token (brief D1-D4).

A run with no `run_work` row is driven by a direct caller (the harness, tests).
Once enqueued, only the holder of its current lease may write to it. The token,
not the clock, is the fence: every claim advances it, so a holder whose lease
expired and was reclaimed carries a token no row still matches.

Lock order is case, then run (`lock_run`), then `run_work`. `claim_run` takes
only the work row and commits alone. Every other function here rides its
caller's transaction and leaves the commit to it, so a command's governed write,
its audit event and its queue effect commit together or not at all.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal, cast
from uuid import UUID

from psycopg import sql

from caos.boundary_text import BoundaryText
from caos.refusals import Refusal, RefusalCode
from caos.store import RunStatus, StoreConnection, committed_unit
from caos.store.events import RunEvent, append, lock_run
from caos.store.outcomes import require_idle

# Renewed by every fenced write; see brief D5 for why it outlives two provider
# call deadlines (`caos.provider.TIMEOUT_SECONDS`, 240 s since MX-4).
LEASE_SECONDS = 600
MAX_WORKER_BYTES = 128
# N15 (D39): the most runs one actor may hold queued or in a worker's hands at
# once. A run is driven one node at a time and holds a worker while it does,
# so a deeper queue buys an actor nothing but other actors' waiting; four
# covers a small batch (one issuer across a few pathways) at once. Each place
# also commits up to one run ceiling of spend, so an actor's outstanding
# exposure is bounded at four ceilings; aggregate spend limits are the AI
# Gateway's, an enterprise setting, and not the host's.
MAX_QUEUED_RUNS_PER_ACTOR = 4
# The class of the advisory lock one actor's queue writes are counted under
# (the two-key form, a space that never overlaps a one-key lock such as
# `apply_schema`'s). Arbitrary and permanent; the actor is the second key.
_ACTOR_QUEUE_LOCK = 0x0CA0_0015


@dataclass(frozen=True, slots=True)
class Lease:
    """The right to write to one run, for as long as `token` is its row's.

    `seconds` is what every renewal grants: the number the claim was made
    with, so a worker configured for a shorter lease is not renewed for the
    module default behind its back."""

    run_id: UUID
    token: int
    seconds: int = LEASE_SECONDS


def enqueue_run(
    conn: StoreConnection, run_id: UUID, *, actor_id: UUID | None = None
) -> bool:
    """Queue a RUNNING run once. Returns whether this call queued it.

    `actor_id` is who asked (N15): the place is theirs, and one past
    `MAX_QUEUED_RUNS_PER_ACTOR` refuses `QUEUED_RUNS_LIMIT_REACHED` with
    nothing written, counted under that actor's lock (`_lock_queue_of`) so two
    requests cannot both take the last place. A run already queued answers
    False first, as it always has. None holds no place: a direct caller, or a
    run Cancel queues only to end it in the same unit.
    """
    if lock_run(conn, run_id) is not RunStatus.RUNNING:
        raise Refusal(RefusalCode.RUN_NOT_RUNNING)
    _lock_queue_of(conn, actor_id)
    queued = conn.execute(
        "INSERT INTO run_work (run_id, state, requested_by)"
        " SELECT %(run)s, 'QUEUED', %(actor)s"
        " WHERE %(actor)s::uuid IS NULL OR (SELECT count(*) FROM run_work"
        "   WHERE requested_by = %(actor)s AND state IN ('QUEUED', 'CLAIMED'))"
        "   < %(cap)s"
        " ON CONFLICT (run_id) DO NOTHING",
        {"run": run_id, "actor": actor_id, "cap": MAX_QUEUED_RUNS_PER_ACTOR},
    ).rowcount
    if not queued and actor_id is not None:
        # Nothing inserted: the run's own row (already started), or the cap.
        _refuse_if_full(
            conn.execute(
                "SELECT 1 FROM run_work WHERE run_id = %s", (run_id,)
            ).fetchone()
            is None
        )
    return bool(queued)


def _lock_queue_of(conn: StoreConnection, actor_id: UUID | None) -> None:
    """Serialise one actor's queue writes until the caller's commit (N15).

    Taken in a statement of its own, before the count: under READ COMMITTED
    the counting statement's snapshot then includes whatever the previous
    holder committed. Always after the case and run locks, and nothing is
    locked after it, so it adds no cycle to the lock order.
    """
    if actor_id is not None:
        conn.execute(
            "SELECT pg_advisory_xact_lock(%s::integer, hashtext(%s))",
            (_ACTOR_QUEUE_LOCK, str(actor_id)),
        )


def _refuse_if_full(full: bool) -> None:
    if full:
        raise Refusal(RefusalCode.QUEUED_RUNS_LIMIT_REACHED)


def claim_run(
    conn: StoreConnection, *, worker: BoundaryText, lease_seconds: int
) -> Lease | None:
    """Claim the oldest queued or expired run, committed alone, or None.

    `SKIP LOCKED` lets two workers poll without waiting on each other; the outer
    predicate re-checks expiry on the locked row, so a holder that renewed while
    this claim waited keeps its lease.
    """
    if not isinstance(worker, BoundaryText) or (
        len(worker.value.encode("utf-8")) > MAX_WORKER_BYTES or not worker.value
    ):
        raise Refusal(RefusalCode.BOUNDARY_TEXT_INVALID)
    _require_seconds(lease_seconds)
    require_idle(conn)
    with committed_unit(conn):
        row = conn.execute(
            "UPDATE run_work w SET state = 'CLAIMED', lease_token = w.lease_token + 1,"
            " worker = %s, stop_code = NULL,"
            " lease_expires_at = clock_timestamp() + make_interval(secs => %s)"
            " WHERE w.run_id = (SELECT run_id FROM run_work"
            "   WHERE state = 'QUEUED'"
            "      OR (state = 'CLAIMED' AND lease_expires_at <= clock_timestamp())"
            "   ORDER BY requested_at, run_id LIMIT 1 FOR UPDATE SKIP LOCKED)"
            " AND (w.state = 'QUEUED' OR (w.state = 'CLAIMED'"
            "      AND w.lease_expires_at <= clock_timestamp()))"
            " RETURNING w.run_id, w.lease_token",
            (worker.value, lease_seconds),
        ).fetchone()
    return None if row is None else Lease(UUID(str(row[0])), int(row[1]), lease_seconds)


def require_running(conn: StoreConnection, run_id: UUID, lease: Lease | None) -> None:
    """The fence for new spend, under the run row lock it takes: the run is
    RUNNING, the lease is held and no cancel was requested (brief 4.3 D3)."""
    if lock_run(conn, run_id) is not RunStatus.RUNNING:
        raise Refusal(RefusalCode.RUN_NOT_RUNNING)
    if require_lease(conn, run_id, lease):
        raise Refusal(RefusalCode.RUN_CANCEL_REQUESTED)


def require_lease(
    conn: StoreConnection,
    run_id: UUID,
    lease: Lease | None,
    *,
    lease_seconds: int | None = None,
) -> bool:
    """Fence one write under the caller's `lock_run`, renewing a live lease.

    Returns whether a cancel was requested. `None` is the direct caller: it may
    write only to a run that was never enqueued. Refuses `LEASE_NOT_HELD`.
    The renewal is the lease's own length unless the caller names one
    (CR-11: a default value is not a sentinel).
    """
    if lease_seconds is None:
        lease_seconds = lease.seconds if lease is not None else LEASE_SECONDS
    _require_seconds(lease_seconds)
    if lease is None:
        queued = conn.execute(
            "SELECT 1 FROM run_work WHERE run_id = %s FOR SHARE", (run_id,)
        ).fetchone()
        if queued is not None:
            raise Refusal(RefusalCode.LEASE_NOT_HELD)
        return False
    if not isinstance(lease, Lease) or lease.run_id != run_id:
        raise Refusal(RefusalCode.LEASE_NOT_HELD)
    row = conn.execute(
        "UPDATE run_work"
        " SET lease_expires_at = clock_timestamp() + make_interval(secs => %s)"
        " WHERE run_id = %s AND state = 'CLAIMED' AND lease_token = %s"
        " RETURNING cancel_requested_at",
        (lease_seconds, run_id, lease.token),
    ).fetchone()
    if row is None:
        raise Refusal(RefusalCode.LEASE_NOT_HELD)
    return row[0] is not None


def holds_lease(conn: StoreConnection, run_id: UUID, lease: Lease | None) -> bool:
    """Whether this caller still holds the run, without renewing or writing.

    `lock_run` answers the same question by renewing, which a read block must
    not do. This exists so a read-only check can put the lease refusal first:
    a caller that lost the run is told that, before it is told anything about
    what the run contains.
    """
    if lease is None:
        return (
            conn.execute(
                "SELECT 1 FROM run_work WHERE run_id = %s", (run_id,)
            ).fetchone()
            is None
        )
    if not isinstance(lease, Lease) or lease.run_id != run_id:
        return False
    return (
        conn.execute(
            "SELECT 1 FROM run_work WHERE run_id = %s AND state = 'CLAIMED'"
            " AND lease_token = %s",
            (run_id, lease.token),
        ).fetchone()
        is not None
    )


def release(conn: StoreConnection, lease: Lease) -> bool:
    """Give a held run back to the queue. False when the lease is not held."""
    return bool(
        conn.execute(
            "UPDATE run_work SET state = 'QUEUED', worker = NULL,"
            " lease_expires_at = NULL"
            " WHERE run_id = %s AND state = 'CLAIMED' AND lease_token = %s",
            (lease.run_id, lease.token),
        ).rowcount
    )


def stop(conn: StoreConnection, lease: Lease, code: RefusalCode) -> bool:
    """Park a held run with the refusal that stopped it, until a retry requeues
    it. False when the lease is not held.

    A run whose cancel was acknowledged while it was held ends CANCELLED here
    instead (MAX-04): `requeue_run` refuses a run with a recorded cancel, so a
    parked one would sit RUNNING with nothing left to end it. Takes `lock_run`
    first, as every move of a run's status does.

    A genuine park appends `RUN_PARKED` (CF-044): the run itself stays
    RUNNING, so nothing else would ever say a worker gave up on it, on the
    stream a watcher tails or in the audit trail read back later.
    """
    if not isinstance(code, RefusalCode):
        raise Refusal(RefusalCode.CALL_OUTCOME_INVALID)
    running = lock_run(conn, lease.run_id) is RunStatus.RUNNING
    row = conn.execute(
        "UPDATE run_work SET state = 'STOPPED', stop_code = %s, worker = NULL,"
        " lease_expires_at = NULL"
        " WHERE run_id = %s AND state = 'CLAIMED' AND lease_token = %s"
        " RETURNING cancel_requested_at IS NOT NULL",
        (code.value, lease.run_id, lease.token),
    ).fetchone()
    if row is None:
        return False
    if running and row[0]:
        _end_cancelled(conn, lease.run_id)
    else:
        append(conn, lease.run_id, RunEvent.RUN_PARKED)
    return True


def require_resendable(
    conn: StoreConnection, run_id: UUID, lease: Lease | None
) -> None:
    """Refuse `LEASE_NOT_HELD` or `RUN_CANCEL_REQUESTED`, reading only.

    What a caller about to send a call again asks first (ST-7), in its own read
    unit: a re-send after the lease was lost or a cancel was recorded is spend
    nobody may still order. `require_lease` answers the same question by
    renewing, which a read unit must not do. `None` is the direct caller, which
    drives only a run that was never enqueued.
    """
    row = conn.execute(
        "SELECT state, lease_token, cancel_requested_at IS NOT NULL"
        " FROM run_work WHERE run_id = %s",
        (run_id,),
    ).fetchone()
    if row is None and lease is None:
        return
    if (
        lease is None
        or row is None
        or lease.run_id != run_id
        or (row[0], row[1]) != ("CLAIMED", lease.token)
    ):
        raise Refusal(RefusalCode.LEASE_NOT_HELD)
    if row[2]:
        raise Refusal(RefusalCode.RUN_CANCEL_REQUESTED)


def requeue_run(
    conn: StoreConnection, run_id: UUID, *, actor_id: UUID | None = None
) -> bool:
    """Retry a stopped RUNNING run with no cancel requested. Returns whether this
    call requeued it.

    The place is then `actor_id`'s, under the same cap and lock as
    `enqueue_run` (N15); a run that is not stopped answers False first.
    """
    if lock_run(conn, run_id) is not RunStatus.RUNNING:
        raise Refusal(RefusalCode.RUN_NOT_RUNNING)
    _lock_queue_of(conn, actor_id)
    requeued = conn.execute(
        "UPDATE run_work SET state = 'QUEUED', stop_code = NULL,"
        " requested_at = now(), requested_by = %(actor)s"
        " WHERE run_id = %(run)s AND state = 'STOPPED'"
        " AND cancel_requested_at IS NULL"
        " AND (%(actor)s::uuid IS NULL OR (SELECT count(*) FROM run_work"
        "   WHERE requested_by = %(actor)s AND state IN ('QUEUED', 'CLAIMED'))"
        "   < %(cap)s)",
        {"run": run_id, "actor": actor_id, "cap": MAX_QUEUED_RUNS_PER_ACTOR},
    ).rowcount
    if not requeued and actor_id is not None:
        # Nothing moved: a run that is not stopped, or the cap.
        _refuse_if_full(
            conn.execute(
                "SELECT 1 FROM run_work WHERE run_id = %s AND state = 'STOPPED'"
                " AND cancel_requested_at IS NULL",
                (run_id,),
            ).fetchone()
            is not None
        )
    return bool(requeued)


def request_cancel(conn: StoreConnection, run_id: UUID) -> bool:
    """Record a cancel once; end a run no worker holds CANCELLED in this unit.

    A claimed run whose lease is still live keeps running: its holder learns
    of the request from `require_lease` and ends the run itself. A CLAIMED row
    whose lease has expired (CF-039) is nobody's -- `claim_run` itself treats
    it exactly like QUEUED -- so waiting for that holder to act would wait
    forever; it is ended now instead. Returns whether this call recorded the
    request or ended the run.
    """
    if lock_run(conn, run_id) is not RunStatus.RUNNING:
        return False
    row = conn.execute(
        "SELECT state, cancel_requested_at IS NULL,"
        " state = 'CLAIMED' AND lease_expires_at <= clock_timestamp(),"
        " lease_token > 0"
        " FROM run_work WHERE run_id = %s FOR UPDATE",
        (run_id,),
    ).fetchone()
    if row is None or row[0] == "DONE":
        return False
    state, unrequested, abandoned, claimed = row
    if unrequested:
        conn.execute(
            "UPDATE run_work SET cancel_requested_at = now() WHERE run_id = %s",
            (run_id,),
        )
    if state not in ("QUEUED", "STOPPED") and not abandoned:
        return bool(unrequested)
    ended = _end_cancelled(conn, run_id)
    if ended and claimed:
        _forget_threads(conn, run_id)
    return ended


# LangGraph's own schema and the tables of it keyed by thread
# (`caos.graph.checkpoint`, `langgraph.checkpoint.postgres.base`). Named here
# rather than imported: the store does not depend on the graph package.
CHECKPOINT_SCHEMA = "caos_graph"
CHECKPOINT_TABLES = ("checkpoints", "checkpoint_blobs", "checkpoint_writes")


def _forget_threads(conn: StoreConnection, run_id: UUID) -> None:
    """Drop the checkpoint thread of a run this unit just ended CANCELLED with
    no worker holding it (N21, DL-8), in the caller's transaction.

    A run is checkpointed only under a claim, so only a claimed run has a
    thread; one released or parked and then cancelled while QUEUED or STOPPED
    was never forgotten by a worker (`caos.graph.worker._forget`). The key is
    the one `run_route` binds, `<run_id>:<route_digest>`, from the pinned
    route. A table the checkpointer never set up is nothing to forget.
    """
    present = conn.execute(
        "SELECT t FROM unnest(%s::text[]) AS t"
        " WHERE to_regclass(quote_ident(%s) || '.' || quote_ident(t)) IS NOT NULL",
        (list(CHECKPOINT_TABLES), CHECKPOINT_SCHEMA),
    ).fetchall()
    for (table,) in present:
        conn.execute(
            sql.SQL(
                "DELETE FROM {} WHERE thread_id = (SELECT run_id::text || ':'"
                " || route_digest FROM run_routes WHERE run_id = %s)"
            ).format(sql.Identifier(CHECKPOINT_SCHEMA, str(table))),
            (run_id,),
        )


def _end_cancelled(conn: StoreConnection, run_id: UUID) -> bool:
    """End a RUNNING run no worker drives any more CANCELLED, with its event and
    its work row closed, under the caller's `lock_run`."""
    changed = conn.execute(
        "UPDATE runs SET status = %s WHERE run_id = %s AND status = %s",
        (RunStatus.CANCELLED.value, run_id, RunStatus.RUNNING.value),
    ).rowcount
    if changed:
        append(conn, run_id, RunEvent.RUN_CANCELLED)
        mark_work_done(conn, run_id)
    return bool(changed)


def mark_work_done(conn: StoreConnection, run_id: UUID) -> None:
    """Close a run's work row, if it has one, in the terminal transition's own
    transaction; the caller holds `lock_run` and owns the commit."""
    conn.execute(
        "UPDATE run_work SET state = 'DONE', worker = NULL, lease_expires_at = NULL,"
        " stop_code = NULL WHERE run_id = %s AND state <> 'DONE'",
        (run_id,),
    )


def _require_seconds(seconds: int) -> None:
    if type(seconds) is not int or not 0 < seconds <= 86_400:
        raise Refusal(RefusalCode.CALL_OUTCOME_INVALID)


# A beat older than this is not evidence that a worker is alive. One full
# provider call plus a minute: `caos.provider.TIMEOUT_SECONDS` (240 s) plus 60.
# A worker beats once per node and not during the node's model call, so at 30 s
# -- three poll intervals -- every call longer than half a minute reported
# `WORKERS_STALE` for a worker that was doing exactly what it is meant to do,
# while its run's lease stayed live (AR-24). The threshold has to cover the
# longest uninterrupted work the host supports, or it measures the work rather
# than the worker. A literal rather than an import, because the store does not
# depend on the provider seam; the rule it follows is named here instead, and
# `tests/test_worker_heartbeat.py` asserts the two stay in that relation.
WORKER_STALE_AFTER = 300.0
type WorkerState = Literal["POLLING", "WORKING", "BACKOFF", "STOPPED"]


@dataclass(frozen=True, slots=True)
class WorkerBeat:
    """One worker's last word about itself, and whether it is recent enough to
    believe."""

    worker_id: str
    state: WorkerState
    consecutive_faults: int
    beat_at: datetime
    fresh: bool


def beat(
    conn: StoreConnection,
    *,
    worker_id: str,
    state: WorkerState,
    faults: int,
) -> None:
    """Record that this worker is alive, and what it is doing.

    One row per worker, overwritten: the table is the size of the fleet rather
    than of the uptime. `beat_at` is the store's clock and never the worker's,
    for the reason every other timestamp here is -- a worker with a skewed
    clock would otherwise read as permanently stale or permanently fresh.

    This is not a fenced write and grants nothing. A worker that beats while
    holding no lease still cannot write a run, so the worst a wrong beat does
    is mislead a person.
    """
    conn.execute(
        "INSERT INTO worker_heartbeats (worker_id, beat_at, state,"
        " consecutive_faults) VALUES (%s, now(), %s, %s)"
        " ON CONFLICT (worker_id) DO UPDATE SET"
        " beat_at = now(), state = EXCLUDED.state,"
        " consecutive_faults = EXCLUDED.consecutive_faults",
        (BoundaryText.of(worker_id).value, state, faults),
    )


def worker_states(conn: StoreConnection) -> list[WorkerBeat]:
    """Every worker that has ever beaten, freshness decided by the store's clock.

    A worker that exited leaves its last beat behind, and that row is more use
    than no row: "worker-a last spoke nine minutes ago, in BACKOFF" names the
    process to go and look at, where an empty table only says nobody is
    working.
    """
    rows = conn.execute(
        "SELECT worker_id, state, consecutive_faults, beat_at,"
        " beat_at > now() - make_interval(secs => %s) FROM worker_heartbeats"
        " ORDER BY worker_id",
        (WORKER_STALE_AFTER,),
    ).fetchall()
    return [
        WorkerBeat(
            str(worker), cast("WorkerState", str(state)), int(faults), when, bool(fresh)
        )
        for worker, state, faults, when, fresh in rows
    ]

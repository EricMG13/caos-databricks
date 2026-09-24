"""Cases and the runs that belong to them.

The two rows every later part of Phase 1 hangs off: a run's events are ordered
under its row lock, its attempts and charges reference it, and its terminal event
is the one `test_terminal_event_is_exactly_once` counts.

Who commits, and why it differs: `create_case` and `start_run` do not, because
they are setup and their caller may want them beside something else. The three
transitions below do, because each one *is* a unit of work in the sense the
pairing rule means (`SYSTEM_SPEC.md` section 2) -- state and its event, together
or not at all. Leaving that commit to a caller would leave the invariant to a
caller.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID, uuid4

import psycopg

from caos import methodology
from caos.boundary_text import BoundaryText
from caos.refusals import Refusal, RefusalCode
from caos.store import RunStatus, StoreConnection, committed_unit, rollback_or_close
from caos.store.budget import CEILING, validate_spend
from caos.store.cases import lock_case
from caos.store.events import RunEvent, append, lock_run
from caos.store.gates import approved_run_input, require_adapter_route
from caos.store.outcomes import (
    CallOutcome,
    _attempt_owner,
    _locked_attempt,
    accepted_owner,
    artifact_digests,
    record_outcome,
)
from caos.store.work import Lease, mark_work_done, require_lease, require_running

# The vendor's `envelope.MAX_ATTEMPT_ORDINAL`: a run folder holds at most 256.
MAX_ATTEMPT_ORDINAL = 256
# `0025_supersedes.sql`: the partial unique index that holds one successor per
# predecessor. A violation is mapped to `RUN_ALREADY_SUPERSEDED` by this name
# and never by the driver's message.
ONE_SUCCESSOR_PER_RUN = "runs_one_successor"


def create_case(conn: StoreConnection, title: BoundaryText) -> UUID:
    """Open a case. Its title crossed the boundary before it got here."""
    case_id = uuid4()
    conn.execute(
        "INSERT INTO cases (case_id, title) VALUES (%s, %s)",
        (case_id, title.value),
    )
    return case_id


def start_run(
    conn: StoreConnection,
    case_id: UUID,
    *,
    budget_ceiling: Decimal | None = None,
    supersedes: UUID | None = None,
) -> UUID:
    """Start a run against a case. RUNNING is the only state a run starts in.

    The ceiling is carried from the first row rather than attached later: a run
    that existed for even one attempt without one is invariant 8 with the number
    left out. `caos.store.budget.CEILING` is what a caller that names none
    gets.

    `supersedes` names the BLOCKED run of this case the new run answers (§72),
    written once with the row and never moved. Inside the caller's unit, under
    the case lock, the target is selected `FOR SHARE` so no transition moves it
    while the link is written: a run of another case is `RUN_NOT_FOUND`, the
    same code an unknown run gets, so neither answer tells a caller the other
    run exists; any status but BLOCKED is `RUN_NOT_BLOCKED`; and a second
    successor is `RUN_ALREADY_SUPERSEDED`, refused by the partial unique index
    in the unit that tried to write it. A refusal leaves the unit failed, and
    the caller rolls it back as it does every other refusal from its unit.
    """
    ceiling = CEILING if budget_ceiling is None else budget_ceiling
    validate_spend(ceiling)
    lock_case(conn, case_id)
    if supersedes is not None:
        _require_answerable(conn, case_id, supersedes)
    run_id = uuid4()
    row = (run_id, case_id, RunStatus.RUNNING.value, ceiling)
    if supersedes is None:
        # The column is named only when it is written: a database at a
        # migration prefix before 0025 still starts an ordinary run, which is
        # what the populated-upgrade tests rely on.
        conn.execute(
            "INSERT INTO runs (run_id, case_id, status, budget_ceiling)"
            " VALUES (%s, %s, %s, %s)",
            row,
        )
        return run_id
    try:
        conn.execute(
            "INSERT INTO runs (run_id, case_id, status, budget_ceiling,"
            " supersedes_run_id) VALUES (%s, %s, %s, %s, %s)",
            (*row, supersedes),
        )
    except psycopg.errors.UniqueViolation as violation:
        if violation.diag.constraint_name != ONE_SUCCESSOR_PER_RUN:
            raise
        raise Refusal(RefusalCode.RUN_ALREADY_SUPERSEDED) from None
    return run_id


def _require_answerable(conn: StoreConnection, case_id: UUID, run_id: UUID) -> None:
    """The run a successor may answer: this case's, and BLOCKED, held `FOR
    SHARE` for the rest of the caller's unit."""
    row = conn.execute(
        "SELECT status FROM runs WHERE run_id = %s AND case_id = %s FOR SHARE",
        (run_id, case_id),
    ).fetchone()
    if row is None:
        raise Refusal(RefusalCode.RUN_NOT_FOUND)
    if RunStatus(row[0]) is not RunStatus.BLOCKED:
        raise Refusal(RefusalCode.RUN_NOT_BLOCKED)


def run_status(conn: StoreConnection, run_id: UUID) -> RunStatus:
    """The run's status, or `RUN_NOT_FOUND` -- the same refusal an unauthorised
    run gets, so that neither answer tells a caller the other one exists."""
    row = conn.execute(
        "SELECT status FROM runs WHERE run_id = %s", (run_id,)
    ).fetchone()
    if row is None:
        raise Refusal(RefusalCode.RUN_NOT_FOUND)
    return RunStatus(row[0])


def start_attempt(
    conn: StoreConnection,
    run_id: UUID,
    route_node_id: str,
    *,
    lease: Lease | None = None,
) -> UUID:
    """Record one try at one node, and say so in the stream.

    The row exists before the work does, because it is the identity the work is
    charged against: a crash after a provider completed still has the attempt it
    completed (`docs/DECISIONS.md` §12, adopting CAOS-Final §21 with Phase 4).
    """
    try:
        require_running(conn, run_id, lease)
    except BaseException:
        rollback_or_close(conn)
        raise
    if accepted_owner(conn, run_id, route_node_id) is not None:
        rollback_or_close(conn)
        raise Refusal(RefusalCode.NODE_ALREADY_ACCEPTED)

    with committed_unit(conn):
        attempt_id = _start(conn, run_id, route_node_id, lease)
    return attempt_id


def _start(
    conn: StoreConnection, run_id: UUID, route_node_id: str, lease: Lease | None
) -> UUID:
    """The attempt row and its event, under the caller's run lock."""
    # Under the run lock, so two starts cannot take one ordinal. Counting rows
    # rather than reading the maximum keeps attempts that predate ordinals.
    counted = conn.execute(
        "SELECT count(*) FROM run_attempts WHERE run_id = %s AND route_node_id = %s",
        (run_id, route_node_id),
    ).fetchone()
    ordinal = (counted[0] if counted else 0) + 1
    if ordinal > MAX_ATTEMPT_ORDINAL:
        raise Refusal(RefusalCode.ATTEMPT_LIMIT_REACHED)
    attempt_id = uuid4()
    conn.execute(
        "INSERT INTO run_attempts"
        " (attempt_id, run_id, route_node_id, ordinal, lease_token)"
        " VALUES (%s, %s, %s, %s, %s)",
        (
            attempt_id,
            run_id,
            route_node_id,
            ordinal,
            None if lease is None else lease.token,
        ),
    )
    append(conn, run_id, RunEvent.ATTEMPT_STARTED)
    return attempt_id


def attempt_ordinal(conn: StoreConnection, attempt_id: UUID) -> int:
    """The stored ordinal the vendor attempt id is derived from, never recovered.

    Refuses `ATTEMPT_NOT_FOUND` for an unknown attempt and for one that predates
    ordinals, which no canonical handoff can name.
    """
    row = conn.execute(
        "SELECT ordinal FROM run_attempts WHERE attempt_id = %s", (attempt_id,)
    ).fetchone()
    if row is None or row[0] is None:
        raise Refusal(RefusalCode.ATTEMPT_NOT_FOUND)
    return int(row[0])


@dataclass(frozen=True, slots=True)
class Accepted:
    """Analysis proposed for acceptance, beside independently durable call facts."""

    artifact_sha256: str
    charge: Decimal
    model: str
    generation_id: str
    diagnostic_sha256: str | None = None
    # The host record blob; present exactly when the run pins the canonical
    # adapter (`docs/DECISIONS.md` §42.1).
    record_sha256: str | None = None


def accept_attempt(
    conn: StoreConnection,
    *,
    attempt_id: UUID,
    accepted: Accepted,
    lease: Lease | None = None,
) -> bool:
    """Commit call facts first, then independently accept eligible analysis.

    A later refusal/rollback cannot erase a committed bill. Each unit derives
    and locks current ownership; no lock or mutable status survives the gap.
    The bill is unfenced; the acceptance is the lease holder's alone, and is
    not gated on a requested cancel (brief 4.3 D3, D4).
    """
    with committed_unit(conn):
        inserted = _accept(conn, attempt_id, accepted, lease)
    return inserted


def _accept(
    conn: StoreConnection,
    attempt: UUID,
    accepted: Accepted,
    lease: Lease | None = None,
) -> bool:
    if not isinstance(accepted, Accepted):
        raise Refusal(RefusalCode.CALL_OUTCOME_INVALID)
    validate_spend(accepted.charge)
    try:
        record_outcome(
            conn,
            attempt_id=attempt,
            outcome=CallOutcome(
                accepted.charge,
                accepted.model,
                accepted.generation_id,
                accepted.diagnostic_sha256,
            ),
        )
    except Refusal as refusal:
        if refusal.code is not RefusalCode.CALL_OUTCOME_LEGACY:
            raise
        _legacy_replay(conn, attempt, accepted)
        return False
    return _accept_artifact(conn, attempt, accepted, lease)


def _accept_artifact(
    conn: StoreConnection,
    attempt: UUID,
    accepted: Accepted,
    lease: Lease | None,
) -> bool:
    run, case, status = _locked_attempt(conn, attempt)
    digests = [accepted.artifact_sha256]
    if accepted.record_sha256 is not None:
        digests.append(accepted.record_sha256)
    if not all(
        isinstance(digest, str) and re.fullmatch(r"[0-9a-f]{64}", digest)
        for digest in digests
    ):
        raise Refusal(RefusalCode.BLOB_ADDRESS_INVALID)
    values = (
        accepted.artifact_sha256,
        run,
        case,
        accepted.model,
        accepted.generation_id,
        accepted.record_sha256,
    )
    row = conn.execute(
        "SELECT artifact_sha256,run_id,case_id,model,generation_id,record_sha256"
        " FROM artifacts WHERE attempt_id = %s",
        (attempt,),
    ).fetchone()
    if row is not None:
        if row != values:
            raise Refusal(RefusalCode.CALL_OUTCOME_CONFLICT)
        return False
    if status is not RunStatus.RUNNING:
        return False
    # Fenced under the run lock taken above; renews a live lease (D3, I4, I7).
    require_lease(conn, run, lease)
    # Fresh authority in this locked unit: governed writes take the case lock
    # first, so nothing can commit between this check and the insert.
    pin, route = approved_run_input(conn, run)
    require_adapter_route(route)
    if pin.adapter_version != methodology.CANONICAL_ADAPTER_VERSION:
        raise Refusal(RefusalCode.RUN_INPUT_INVALID)
    # Every accepted artifact is a canonical Markdown bound by its host record.
    if accepted.record_sha256 is None:
        raise Refusal(RefusalCode.ARTIFACT_RECORD_MISMATCH)
    node = conn.execute(
        "SELECT route_node_id FROM run_attempts WHERE attempt_id = %s", (attempt,)
    ).fetchone()
    if node is None or node[0] not in {n.route_node_id for n in route.nodes}:
        raise Refusal(RefusalCode.ROUTE_IDENTITY_INVALID)
    # One owner per node, under the run lock; the unique constraint backs it.
    if accepted_owner(conn, run, node[0]) is not None:
        raise Refusal(RefusalCode.NODE_ALREADY_ACCEPTED)
    # `route_node_id` is filled from the attempt by the migration 0009 trigger.
    conn.execute(
        "INSERT INTO artifacts (attempt_id, artifact_sha256, run_id, case_id,"
        " model, generation_id, record_sha256)"
        " VALUES (%s, %s, %s, %s, %s, %s, %s)",
        (attempt, *values),
    )
    append(conn, run, RunEvent.ATTEMPT_ACCEPTED)
    return True


def _legacy_replay(conn: StoreConnection, attempt: UUID, accepted: Accepted) -> None:
    run, case, _status = _locked_attempt(conn, attempt)
    row = conn.execute(
        "SELECT a.artifact_sha256,a.run_id,a.case_id,a.model,a.generation_id,"
        " l.run_id,l.amount FROM artifacts a JOIN budget_ledger l USING (attempt_id)"
        " WHERE a.attempt_id=%s",
        (attempt,),
    ).fetchone()
    if (
        accepted.diagnostic_sha256 is not None
        or accepted.record_sha256 is not None
        or row
        != (
            accepted.artifact_sha256,
            run,
            case,
            accepted.model,
            accepted.generation_id,
            run,
            accepted.charge,
        )
    ):
        raise Refusal(RefusalCode.CALL_OUTCOME_LEGACY)


def complete_run(
    conn: StoreConnection,
    run_id: UUID,
    *,
    lease: Lease | None = None,
    accepted: frozenset[str] | None = None,
) -> bool:
    """End a run that finished its route. Returns whether this call ended it.

    Decided under `lock_run`, not trusted from the caller: every node of the
    run's approved pinned route must own an accepted artifact, else
    `RUN_NODES_UNACCEPTED`; an unpinned or unapproved run refuses as
    `approved_run_input` does, so COMPLETE always requires the pin. A caller
    that decided from a snapshot passes `accepted`, and a different set under
    the lock refuses `RUN_TERMINAL_STALE` (brief 4.3 D3, D8)."""
    return _transition(
        conn, run_id, RunStatus.COMPLETE, RunEvent.RUN_COMPLETE, lease, accepted
    )


def complete_attempt(
    conn: StoreConnection,
    *,
    attempt_id: UUID,
    accepted: Accepted,
    lease: Lease | None = None,
) -> bool:
    """Accept the attempt and end the run it belongs to.

    The single-node shape Phase 1 exits on, kept as one call because
    `test_terminal_event_is_exactly_once` is about the two committing as one
    story: a crash in the gap yields one artifact, one charge, one terminal
    event, however many times it is replayed. The acceptance commits on its
    own; completion then refuses `RUN_NODES_UNACCEPTED` while any other pinned
    node is unaccepted (brief 4.3 D8).
    """
    accept_attempt(conn, attempt_id=attempt_id, accepted=accepted, lease=lease)
    return complete_run(conn, _attempt_owner(conn, attempt_id)[0], lease=lease)


def block_run(
    conn: StoreConnection,
    run_id: UUID,
    *,
    lease: Lease | None = None,
    accepted: frozenset[str] | None = None,
    verdict: UUID | None = None,
) -> bool:
    """End a run whose route has required work nothing can release (§39).

    Returns whether this call ended it. No further attempt or reservation is
    possible. Which nodes are unfinished is re-derived from the pins and the
    accepted artifacts; *why* the run ended is not re-derivable and is recorded
    here. `verdict` is the attempt whose validated Blocked answer ended the run,
    written to `run_blocking_verdicts` in the transaction that ends it (§68) --
    it must be an attempt of this run, else `ATTEMPT_NOT_FOUND` and nothing
    moves. None when no node's verdict ended it: an empty frontier with
    required work unfinished is the route's own rule and names no node.
    With `accepted`, the accepted set re-read under the lock must equal it,
    else `RUN_TERMINAL_STALE`.
    """
    return _transition(
        conn, run_id, RunStatus.BLOCKED, RunEvent.RUN_BLOCKED, lease, accepted, verdict
    )


def cancel_run(
    conn: StoreConnection, run_id: UUID, *, lease: Lease | None = None
) -> bool:
    """End a run its lease holder was refused `RUN_CANCEL_REQUESTED` on
    (brief 4.3 D4, I10). Returns whether this call ended it."""
    return _transition(conn, run_id, RunStatus.CANCELLED, RunEvent.RUN_CANCELLED, lease)


def _transition(  # noqa: PLR0913 -- one terminal move and its re-derived decision
    conn: StoreConnection,
    run_id: UUID,
    into: RunStatus,
    event: RunEvent,
    lease: Lease | None,
    accepted: frozenset[str] | None = None,
    verdict: UUID | None = None,
) -> bool:
    """Move a RUNNING run into a terminal status, appending `event` only if the
    move actually happened. Zero rows updated, no event -- the rule that makes a
    terminal event exactly-once (`SYSTEM_SPEC.md` section 2).

    Under `lock_run`, a run already ended is answered False before the fence; a
    RUNNING run is ended only by its lease holder, and its work row closes in
    the same transaction (brief 4.3 D3, I8). A BLOCKED move with a `verdict`
    records it in that transaction too, riding the same conditional update."""
    with committed_unit(conn):
        changed = 0
        if lock_run(conn, run_id) is RunStatus.RUNNING:
            cancelled = require_lease(conn, run_id, lease)
            if cancelled and into is not RunStatus.CANCELLED:
                # A cancel that landed during the last call (AR-13, ST-6):
                # the call's artifact and bill are already committed, and the
                # run ends CANCELLED through the holder's cancel path, not
                # COMPLETE, BLOCKED or FAILED as if nobody had asked.
                raise Refusal(RefusalCode.RUN_CANCEL_REQUESTED)
            _require_terminal_decision(conn, run_id, into, accepted)
            changed = conn.execute(
                "UPDATE runs SET status = %s WHERE run_id = %s AND status = %s",
                (into.value, run_id, RunStatus.RUNNING.value),
            ).rowcount
        if changed:
            append(conn, run_id, event)
            mark_work_done(conn, run_id)
            if verdict is not None:
                _record_blocking_verdict(conn, run_id, into, verdict)
    return bool(changed)


def _record_blocking_verdict(
    conn: StoreConnection, run_id: UUID, into: RunStatus, verdict: UUID
) -> None:
    """Name the attempt whose Blocked answer ended this run, once.

    Only a BLOCKED move carries one, and only an attempt of this run is
    accepted: the insert selects the attempt through its own run, so a foreign
    or unknown id writes nothing and refuses `ATTEMPT_NOT_FOUND` -- raised
    inside the transaction, which the caller then rolls back whole.
    """
    if into is not RunStatus.BLOCKED:
        raise Refusal(RefusalCode.ATTEMPT_NOT_FOUND)
    written = conn.execute(
        "INSERT INTO run_blocking_verdicts (run_id, attempt_id)"
        " SELECT run_id, attempt_id FROM run_attempts"
        " WHERE attempt_id = %s AND run_id = %s",
        (verdict, run_id),
    ).rowcount
    if written != 1:
        raise Refusal(RefusalCode.ATTEMPT_NOT_FOUND)


def _require_terminal_decision(
    conn: StoreConnection,
    run_id: UUID,
    into: RunStatus,
    accepted: frozenset[str] | None,
) -> None:
    """Re-derive the terminal decision under the caller's `lock_run` (D8).

    FAILED (and BLOCKED without a snapshot) needs no decision to re-derive."""
    if accepted is None and into is not RunStatus.COMPLETE:
        return
    held = frozenset(artifact_digests(conn, run_id))
    if accepted is not None and held != accepted:
        raise Refusal(RefusalCode.RUN_TERMINAL_STALE)
    if into is RunStatus.COMPLETE:
        _pin, route = approved_run_input(conn, run_id)
        if not {node.route_node_id for node in route.nodes} <= held:
            raise Refusal(RefusalCode.RUN_NODES_UNACCEPTED)

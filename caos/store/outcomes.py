"""One immutable call outcome; known spend lives only in the original ledger."""

from __future__ import annotations

import re
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING
from uuid import UUID

import psycopg
from psycopg.pq import TransactionStatus

from caos.refusals import Refusal, RefusalCode
from caos.store import RunStatus, StoreConnection, committed_unit, rollback_or_close
from caos.store.budget import reserved_for, validate_spend
from caos.store.events import RunEvent, append, lock_run

if TYPE_CHECKING:
    from caos.store.work import Lease


def require_idle(conn: StoreConnection) -> None:
    """Execution never adopts an active caller transaction, even read-only."""
    if conn.autocommit or conn.info.transaction_status is not TransactionStatus.IDLE:
        raise Refusal(RefusalCode.STORE_NOT_TRANSACTIONAL)


@contextmanager
def execution_reads(conn: StoreConnection) -> Iterator[None]:
    """Own one bounded execution read unit; no transport inside this scope."""
    require_idle(conn)  # Outside cleanup: pending caller writes remain untouched.
    try:
        _read_committed(conn)
        yield
        conn.rollback()
    except psycopg.Error:
        rollback_or_close(conn)
        raise Refusal(RefusalCode.STORE_UNAVAILABLE) from None
    except BaseException:
        rollback_or_close(conn)
        raise


def _read_committed(conn: StoreConnection) -> None:
    if conn.execute("SHOW transaction_isolation").fetchone() != ("read committed",):
        raise Refusal(RefusalCode.STORE_NOT_TRANSACTIONAL)


def accepted_owner(
    conn: StoreConnection, run_id: UUID, route_node_id: str
) -> UUID | None:
    """The attempt that owns this run node's accepted result, if any.

    Joined through the attempt rather than `artifacts.route_node_id`, so the
    check also reads a restored pre-0009 database before it is upgraded.
    """
    row = conn.execute(
        "SELECT a.attempt_id FROM artifacts a JOIN run_attempts t USING (attempt_id)"
        " WHERE a.run_id=%s AND t.route_node_id=%s",
        (run_id, route_node_id),
    ).fetchone()
    return None if row is None else UUID(str(row[0]))


def artifact_digests(conn: StoreConnection, run_id: UUID) -> dict[str, str]:
    """Every accepted artifact of the run, keyed by route node id.

    One query, read in one place: the frontier, the claims executor's upstream
    and the canonical host identity all need exactly this row set. It lives in
    the store so the runtime can import the canonical reader without a cycle.
    """
    # One row per node: `artifacts UNIQUE (run_id, route_node_id)` makes the
    # accepted owner a database fact, so no ordering picks a winner.
    return {
        str(node): str(digest)
        for node, _attempt, digest, _record in accepted_rows(conn, run_id)
    }


def accepted_rows(
    conn: StoreConnection, run_id: UUID
) -> list[tuple[str, UUID, str, str | None]]:
    """(route node, attempt, artifact, record) for every accepted artifact."""
    rows = conn.execute(
        "SELECT route_node_id, attempt_id, artifact_sha256, record_sha256"
        " FROM artifacts WHERE run_id = %s",
        (run_id,),
    ).fetchall()
    return [
        (str(node), UUID(str(attempt)), str(digest), None if rec is None else str(rec))
        for node, attempt, digest, rec in rows
    ]


@dataclass(frozen=True, slots=True)
class NodeAttempt:
    """One attempt at a run node: the refusal that explained it, if one did,
    and the address of the answer it stored, if it stored one."""

    attempt_id: UUID
    refusal: str | None
    diagnostic_sha256: str | None


def node_attempts(
    conn: StoreConnection, run_id: UUID, route_node_id: str
) -> tuple[NodeAttempt, ...]:
    """Every attempt at this run node, oldest first. Caller owns the read."""
    rows = conn.execute(
        "SELECT t.attempt_id, r.code, o.diagnostic_sha256 FROM run_attempts t"
        " LEFT JOIN attempt_refusals r USING (attempt_id)"
        " LEFT JOIN call_outcomes o USING (attempt_id)"
        " WHERE t.run_id = %s AND t.route_node_id = %s"
        " ORDER BY t.ordinal NULLS FIRST, t.started_at, t.attempt_id",
        (run_id, route_node_id),
    ).fetchall()
    return tuple(
        NodeAttempt(
            UUID(str(attempt)),
            None if code is None else str(code),
            None if diagnostic is None else str(diagnostic),
        )
        for attempt, code, diagnostic in rows
    )


def check_attempt(
    conn: StoreConnection, *, attempt_id: UUID, run_id: UUID, route_node_id: str
) -> None:
    """Require the attempt's current run/node identity and RUNNING owner."""
    if not isinstance(attempt_id, UUID) or conn.execute(
        "SELECT run_id,route_node_id FROM run_attempts WHERE attempt_id=%s",
        (attempt_id,),
    ).fetchone() != (run_id, route_node_id):
        raise Refusal(RefusalCode.ATTEMPT_NOT_FOUND)
    owner, _case, status = _locked_attempt(conn, attempt_id)
    if owner != run_id or conn.execute(
        "SELECT route_node_id FROM run_attempts WHERE attempt_id=%s AND run_id=%s",
        (attempt_id, run_id),
    ).fetchone() != (route_node_id,):
        raise Refusal(RefusalCode.ATTEMPT_NOT_FOUND)
    if status is not RunStatus.RUNNING:
        raise Refusal(RefusalCode.RUN_NOT_RUNNING)
    accepted = accepted_owner(conn, run_id, route_node_id)
    if accepted is not None and accepted != attempt_id:
        raise Refusal(RefusalCode.NODE_ALREADY_ACCEPTED)


def check_call(
    conn: StoreConnection,
    *,
    attempt_id: UUID,
    run_id: UUID,
    route_node_id: str,
    lease: Lease | None = None,
) -> None:
    """Require this unused reserved attempt. Caller owns the read transaction.

    Absence checks are not a concurrent call claim or crash/retry certainty.
    The lease check is a non-locking read that stops a knowingly stale call;
    the fenced writes, not this read, are the guarantee (brief 4.3 D3).
    """
    _lease_seen(conn, run_id, lease)
    check_attempt(
        conn,
        attempt_id=attempt_id,
        run_id=run_id,
        route_node_id=route_node_id,
    )
    if reserved_for(conn, attempt_id) is None:
        raise Refusal(RefusalCode.BUDGET_NOT_RESERVED)
    if conn.execute(
        "SELECT 1 FROM call_outcomes WHERE attempt_id=%s", (attempt_id,)
    ).fetchone():
        raise Refusal(RefusalCode.CALL_OUTCOME_CONFLICT)
    if conn.execute(
        "SELECT 1 FROM budget_ledger WHERE attempt_id=%s"
        " UNION ALL SELECT 1 FROM artifacts WHERE attempt_id=%s",
        (attempt_id, attempt_id),
    ).fetchone():
        raise Refusal(RefusalCode.CALL_OUTCOME_LEGACY)


def _lease_seen(conn: StoreConnection, run_id: UUID, lease: Lease | None) -> None:
    row = conn.execute(
        "SELECT state, lease_token FROM run_work WHERE run_id = %s", (run_id,)
    ).fetchone()
    if row is None and lease is None:
        return
    if lease is None or row != ("CLAIMED", lease.token) or lease.run_id != run_id:
        raise Refusal(RefusalCode.LEASE_NOT_HELD)


@dataclass(frozen=True, slots=True)
class CallOutcome:
    """None is unknown, including spend. Diagnostic bytes, when available,
    belong in a bounded blob; only its address belongs here. Model is the
    host's configured identifier; generation_id is the provider's handle.
    """

    charge: Decimal | None
    model: str | None
    generation_id: str | None
    diagnostic_sha256: str | None = None


def record_outcome(
    conn: StoreConnection, *, attempt_id: UUID, outcome: CallOutcome
) -> bool:
    """Commit outcome/known charge/event even after termination; never analysis.

    Owns the caller transaction. Exact replay is a no-op; conflicts and legacy
    rows refuse. Unknown outcomes remain immutable, with no backfill.
    """
    with committed_unit(conn):
        inserted = _record(conn, attempt_id, outcome)
    return inserted


def _record(conn: StoreConnection, attempt: UUID, outcome: CallOutcome) -> bool:
    run, _case, _status = _locked_attempt(conn, attempt)
    row = conn.execute(
        "SELECT l.amount, o.model, o.generation_id, o.diagnostic_sha256"
        " FROM call_outcomes o LEFT JOIN budget_ledger l"
        " ON (l.run_id,l.attempt_id) = (o.run_id,o.charged_attempt_id)"
        " WHERE o.attempt_id = %s",
        (attempt,),
    ).fetchone()
    if row is None:
        if conn.execute(
            "SELECT attempt_id FROM budget_ledger WHERE attempt_id = %s"
            " UNION ALL SELECT attempt_id FROM artifacts WHERE attempt_id = %s",
            (attempt, attempt),
        ).fetchone():
            raise Refusal(RefusalCode.CALL_OUTCOME_LEGACY)
    _validate(outcome)
    if row is not None:
        if row != (
            outcome.charge,
            outcome.model,
            outcome.generation_id,
            outcome.diagnostic_sha256,
        ):
            raise Refusal(RefusalCode.CALL_OUTCOME_CONFLICT)
        return False
    if outcome.charge is not None:
        conn.execute(
            "INSERT INTO budget_ledger (attempt_id,run_id,amount) VALUES (%s,%s,%s)",
            (attempt, run, outcome.charge),
        )
    conn.execute(
        "INSERT INTO call_outcomes (attempt_id,run_id,charged_attempt_id,model,"
        " generation_id,diagnostic_sha256) VALUES (%s,%s,%s,%s,%s,%s)",
        (
            attempt,
            run,
            attempt if outcome.charge is not None else None,
            outcome.model,
            outcome.generation_id,
            outcome.diagnostic_sha256,
        ),
    )
    append(conn, run, RunEvent.CALL_OUTCOME_RECORDED)
    return True


# What the store, the run or its fence said, never what the answer was: a later
# holder may still accept or explain that answer, so none is written down.
_NOT_AN_EXPLANATION = frozenset(
    {
        RefusalCode.BLOB_ADDRESS_INVALID,
        RefusalCode.BLOB_DIGEST_MISMATCH,
        RefusalCode.BLOB_NOT_FOUND,
        RefusalCode.STORE_UNAVAILABLE,
        RefusalCode.STORE_NOT_TRANSACTIONAL,
        RefusalCode.LEASE_NOT_HELD,
        RefusalCode.RUN_NOT_RUNNING,
        RefusalCode.RUN_CANCEL_REQUESTED,
        RefusalCode.RUN_INPUT_INVALID,
        RefusalCode.ATTEMPT_NOT_FOUND,
        RefusalCode.NODE_ALREADY_ACCEPTED,
        RefusalCode.CALL_OUTCOME_CONFLICT,
        RefusalCode.CALL_OUTCOME_LEGACY,
        RefusalCode.HANDOFF_BLOCKED,
    }
)


def record_refusal(
    conn: StoreConnection,
    *,
    attempt_id: UUID,
    code: RefusalCode,
    lease: Lease | None = None,
) -> bool:
    """Write once why an attempt's recorded call was not accepted (brief 4.3 D7).

    Owns the caller transaction. Returns whether a row was written: nothing is
    for an attempt with no recorded call outcome, for a code that describes the
    store, the run or its fence rather than the answer, or for an attempt that
    already has one. Fenced under `lock_run`, as every holder write is.
    """
    if not isinstance(code, RefusalCode):
        raise Refusal(RefusalCode.CALL_OUTCOME_INVALID)
    if code in _NOT_AN_EXPLANATION:
        return False
    require_idle(conn)
    with committed_unit(conn):
        run, _case, _status = _locked_attempt(conn, attempt_id)
        # Imported here: `work` imports this module at its top.
        from caos.store.work import require_lease

        require_lease(conn, run, lease)
        inserted = conn.execute(
            "INSERT INTO attempt_refusals (attempt_id, code)"
            " SELECT attempt_id, %s FROM call_outcomes WHERE attempt_id = %s"
            " ON CONFLICT (attempt_id) DO NOTHING",
            (code.value, attempt_id),
        ).rowcount
    return bool(inserted)


def producer_identifier(value: object, *, limit: int) -> str | None:
    """An exact producer identifier, or unknown; never coerce response fields."""
    if (
        isinstance(value, str)
        and len(value) <= limit
        and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/@+-]*", value) is not None
    ):
        return value
    return None


def _validate(outcome: CallOutcome) -> None:
    if not isinstance(outcome, CallOutcome):
        raise Refusal(RefusalCode.CALL_OUTCOME_INVALID)
    if outcome.charge is not None:
        validate_spend(outcome.charge)
    for value, limit in ((outcome.model, 256), (outcome.generation_id, 512)):
        if value is not None and producer_identifier(value, limit=limit) is None:
            raise Refusal(RefusalCode.CALL_OUTCOME_INVALID)
    digest = outcome.diagnostic_sha256
    if digest is not None and (
        not isinstance(digest, str) or re.fullmatch(r"[0-9a-f]{64}", digest) is None
    ):
        raise Refusal(RefusalCode.CALL_OUTCOME_INVALID)


def _attempt_owner(conn: StoreConnection, attempt_id: UUID) -> tuple[UUID, UUID]:
    if not isinstance(attempt_id, UUID):
        raise Refusal(RefusalCode.ATTEMPT_NOT_FOUND)
    row = conn.execute(
        "SELECT attempts.run_id, runs.case_id FROM run_attempts AS attempts"
        " JOIN runs USING (run_id) WHERE attempts.attempt_id = %s",
        (attempt_id,),
    ).fetchone()
    if row is None:
        raise Refusal(RefusalCode.ATTEMPT_NOT_FOUND)
    return row[0], row[1]


def _locked_attempt(
    conn: StoreConnection, attempt_id: UUID
) -> tuple[UUID, UUID, RunStatus]:
    run, case = _attempt_owner(conn, attempt_id)
    status = lock_run(conn, run)
    _require_attempt(conn, attempt_id, run)
    return run, case, status


def _require_attempt(conn: StoreConnection, attempt_id: UUID, run_id: UUID) -> None:
    """Revalidate after waiting on the run lock, then retain the native owner
    key through commit: a moved attempt must never write under its former run."""
    if (
        conn.execute(
            "SELECT 1 FROM run_attempts WHERE attempt_id = %s AND run_id = %s"
            " FOR KEY SHARE",
            (attempt_id, run_id),
        ).fetchone()
        is None
    ):
        raise Refusal(RefusalCode.ATTEMPT_NOT_FOUND)

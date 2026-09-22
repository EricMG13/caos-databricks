"""The common ordering point for mutations belonging to an existing case."""

from __future__ import annotations

from uuid import UUID

from caos.refusals import Refusal, RefusalCode
from caos.store import StoreConnection


def lock_case(
    conn: StoreConnection,
    case_id: UUID,
    *,
    missing: RefusalCode = RefusalCode.CASE_NOT_FOUND,
) -> None:
    """Lock case first, then membership/run/audit/gate rows; caller owns commit.

    READ COMMITTED gives authority/status reads after waiting a fresh snapshot.
    Reject other isolation even when selected by SQL in an implicit transaction.
    Autocommit cannot retain this lock through its dependent writes.
    """
    if conn.autocommit or conn.execute("SHOW transaction_isolation").fetchone() != (
        "read committed",
    ):
        raise Refusal(RefusalCode.STORE_NOT_TRANSACTIONAL)
    # ponytail: per-case writes serialize; finer locks only for measured throughput.
    row = conn.execute(
        "SELECT case_id FROM cases WHERE case_id = %s FOR UPDATE", (case_id,)
    ).fetchone()
    if row is None:
        raise Refusal(missing)

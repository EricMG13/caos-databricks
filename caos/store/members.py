"""Case standing: who may do what, on which case.

`SYSTEM_SPEC.md` §8. Case standing and global role are separate, and only
standing is rechecked at commit time: `caos/store/audit.py`'s `governed_write`
calls `_require_standing` for the same reason a check anywhere else is a check
at request time wearing a different name. The global role is not re-read
there; it is whatever `caos/api/identity.py` cached for up to `CACHE_SECONDS`
(300 s) when the request began (D10/F13, accepted).

Standing is ordered. An ADMIN can do what a WRITER can, which is why `requires`
is a floor rather than an equality -- an authority model that demanded the exact
standing would refuse an administrator doing an ordinary thing.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from caos.store import StoreConnection
from caos.store.cases import lock_case


class Standing(StrEnum):
    """What a member may do on one case, least to most."""

    READER = "READER"
    WRITER = "WRITER"
    APPROVER = "APPROVER"
    ADMIN = "ADMIN"


# The order the floor is measured against. Written out rather than derived from
# the enum's definition order, so re-ordering the class cannot silently
# re-order authority.
_RANK = {
    Standing.READER: 0,
    Standing.WRITER: 1,
    Standing.APPROVER: 2,
    Standing.ADMIN: 3,
}


def grant(
    conn: StoreConnection, *, case_id: UUID, user_id: UUID, standing: Standing
) -> None:
    """Give or replace standing under the case lock; caller commits."""
    lock_case(conn, case_id)
    conn.execute(
        "INSERT INTO case_members (case_id, user_id, standing)"
        " VALUES (%s, %s, %s)"
        " ON CONFLICT (case_id, user_id) DO UPDATE"
        " SET standing = EXCLUDED.standing, revoked_at = NULL",
        (case_id, user_id, standing.value),
    )


def revoke(conn: StoreConnection, *, case_id: UUID, user_id: UUID) -> bool:
    """End a membership; whether one was live to end. The row stays: a run that
    already cited this actor's approval has to remain explicable.

    The answer is the rowcount rather than None so a command can refuse a
    request that revoked nothing, instead of recording that something happened.
    """
    lock_case(conn, case_id)
    return (
        conn.execute(
            "UPDATE case_members SET revoked_at = now()"
            " WHERE case_id = %s AND user_id = %s AND revoked_at IS NULL",
            (case_id, user_id),
        ).rowcount
        == 1
    )


def standing_of(
    conn: StoreConnection, *, case_id: UUID, user_id: UUID
) -> Standing | None:
    """Live standing, or None for a stranger and for a revoked member alike."""
    row = conn.execute(
        "SELECT standing FROM case_members"
        " WHERE case_id = %s AND user_id = %s AND revoked_at IS NULL",
        (case_id, user_id),
    ).fetchone()
    return None if row is None else Standing(row[0])


def satisfies(held: Standing | None, required: Standing) -> bool:
    """Whether `held` clears the floor `required` sets."""
    return held is not None and _RANK[held] >= _RANK[required]


@dataclass(frozen=True, slots=True)
class RunListing:
    """A case's latest run, as a list names it; the route ids once pinned."""

    run_id: UUID
    status: str
    created_at: datetime
    profile_id: str | None
    selection_id: str | None
    # CF-044: a run a worker parked, or None -- never enqueued, or still
    # being driven -- the one field that tells a list a run stopped RUNNING
    # apart from one that never will on its own.
    stop_code: str | None


@dataclass(frozen=True, slots=True)
class CaseListing:
    """One case a user holds live standing on."""

    case_id: UUID
    title: str
    created_at: datetime
    standing: Standing
    live_sources: int
    latest_run: RunListing | None
    # The case's live members, only where the listed user is its ADMIN and the
    # caller asked for them; at most `members_limit`, so a caller asking one
    # past its bound can tell a truncated list from a full one.
    members: tuple[tuple[UUID, Standing], ...] | None


def cases_for_member(
    conn: StoreConnection,
    *,
    user_id: UUID,
    limit: int,
    members_limit: int | None = None,
) -> list[CaseListing]:
    """The cases `user_id` holds live standing on, newest first, at most `limit`.

    One query whatever the case count: the source count, the latest run and an
    administered case's members are subqueries, not a query per row. A
    revoked membership lists nothing, and a global role is not consulted --
    standing is per case. Caller owns the read transaction.
    """
    # Without `members_limit` no member is read and every row's `members` is
    # `None`, "not served" -- never an empty tuple, which would say "none".
    rows = conn.execute(
        "SELECT c.case_id, c.title, c.created_at, m.standing,"
        " (SELECT count(*) FROM live_sources s WHERE s.case_id = c.case_id),"
        " r.run_id, r.status, r.created_at, rr.profile_id, rr.selection_id,"
        " w.stop_code,"
        " CASE WHEN %s AND m.standing = 'ADMIN' THEN (SELECT coalesce(json_agg("
        "  json_build_array(x.user_id, x.standing) ORDER BY x.user_id), '[]')"
        "  FROM (SELECT o.user_id, o.standing FROM case_members o"
        "   WHERE o.case_id = c.case_id AND o.revoked_at IS NULL"
        "   ORDER BY o.user_id LIMIT %s) x) END"
        " FROM case_members m JOIN cases c ON c.case_id = m.case_id"
        " LEFT JOIN LATERAL (SELECT run_id, status, created_at FROM runs"
        "  WHERE runs.case_id = c.case_id"
        "  ORDER BY created_at DESC, run_id DESC LIMIT 1) r ON true"
        " LEFT JOIN run_routes rr ON rr.run_id = r.run_id"
        " LEFT JOIN run_work w ON w.run_id = r.run_id"
        " WHERE m.user_id = %s AND m.revoked_at IS NULL"
        " ORDER BY c.created_at DESC, c.case_id DESC LIMIT %s",
        (members_limit is not None, members_limit or 0, user_id, limit),
    ).fetchall()
    return [
        CaseListing(
            case_id=row[0],
            title=row[1],
            created_at=row[2],
            standing=Standing(row[3]),
            live_sources=int(row[4]),
            latest_run=None
            if row[5] is None
            else RunListing(row[5], row[6], row[7], row[8], row[9], row[10]),
            members=None
            if row[11] is None
            else tuple((UUID(member), Standing(held)) for member, held in row[11]),
        )
        for row in rows
    ]

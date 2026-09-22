"""Phase 6: authority is checked where the commit is, and the audit chains.

`SYSTEM_SPEC.md` §8 says commit time, and a check at the request is not that.
The distance between them is a real window: a request arrives, standing is
checked, work happens, the actor's membership is revoked, and the commit lands
anyway. So the check lives inside the store call that writes.

`SYSTEM_SPEC.md` §2's audit rule is the other half. A governed write commits its
state and its audit event in one transaction -- or neither. `audit_events` is
hash-chained per case under an `audit_chain_heads` lock row, so a rewrite is
detectable by comparing a retained head against the live one.

Two of the tests here are named in `docs/REBUILD_PLAN.md`: Phase 6's
`test_membership_revocation_refuses_commit`, and the Phase 1 debt Phase 6 owes,
`test_a_governed_write_commits_its_audit_event_or_nothing`.
"""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from pydantic import BaseModel, ConfigDict

import caos.store.audit as audit_module
from caos.boundary_text import BoundaryText
from caos.refusals import Refusal, RefusalCode
from caos.store import StoreConnection
from caos.store.audit import (
    AuditEntry,
    GovernedAction,
    audit_head,
    audit_trail,
    governed_write,
    verify_chain,
)
from caos.store.commands import CommandResult, request_digest, run_command
from caos.store.members import Standing, grant, revoke, satisfies, standing_of
from caos.store.runs import create_case, start_run


class _Died(RuntimeError):
    """A process death between the state and the event that records it."""


@pytest.fixture
def actor(case: tuple[StoreConnection, UUID]) -> tuple[StoreConnection, UUID, UUID]:
    """A case, and a WRITER on it."""
    conn, case_id = case
    user_id = uuid4()
    grant(conn, case_id=case_id, user_id=user_id, standing=Standing.WRITER)
    conn.commit()
    return conn, case_id, user_id


def _action(case_id: UUID, user_id: UUID, **payload: str) -> GovernedAction:
    return GovernedAction(
        case_id=case_id,
        actor_id=user_id,
        action="SOURCE_SET_PINNED",
        requires=Standing.WRITER,
        payload=payload or {"version": "1"},
    )


def test_a_governed_write_commits_its_audit_event_or_nothing(
    actor: tuple[StoreConnection, UUID, UUID],
) -> None:
    """The Phase 1 debt Phase 6 owes. State and audit, together or neither.

    The write raises after its own statement has run. Nothing survives -- not
    the state it wrote, and not an audit event claiming it happened.
    """
    conn, case_id, user_id = actor

    def failing_write(connection: StoreConnection) -> None:
        connection.execute(
            "INSERT INTO cases (case_id, title) VALUES (%s, %s)",
            (uuid4(), "written before the failure"),
        )
        raise _Died

    with pytest.raises(_Died):
        governed_write(conn, _action(case_id, user_id), failing_write)

    row = conn.execute(
        "SELECT count(*) FROM cases WHERE title = %s", ("written before the failure",)
    ).fetchone()
    assert row is not None and row[0] == 0, "the state did not survive"
    assert audit_trail(conn, case_id) == [], "and neither did an event for it"


def test_a_governed_write_records_what_it_did(
    actor: tuple[StoreConnection, UUID, UUID],
) -> None:
    conn, case_id, user_id = actor

    governed_write(conn, _action(case_id, user_id), lambda _conn: None)

    [entry] = audit_trail(conn, case_id)
    assert entry.action == "SOURCE_SET_PINNED"
    assert entry.actor_id == user_id
    assert entry.seq == 1
    assert audit_head(conn, case_id) == entry.entry_sha256


@pytest.mark.parametrize(
    ("held", "required", "allowed"),
    [
        (Standing.ADMIN, Standing.WRITER, True),
        (Standing.APPROVER, Standing.APPROVER, True),
        (Standing.WRITER, Standing.WRITER, True),
        (Standing.READER, Standing.WRITER, False),
        (Standing.WRITER, Standing.APPROVER, False),
        (None, Standing.READER, False),
    ],
)
def test_standing_is_a_floor_not_an_equality(
    held: Standing | None, required: Standing, allowed: bool
) -> None:
    """An ADMIN can do what a WRITER can. A model demanding the exact standing
    would refuse an administrator doing an ordinary thing, and the way round
    that is granting people two memberships -- which is worse."""
    assert satisfies(held, required) is allowed


def test_an_audit_entry_carries_the_link_and_not_the_payload(
    actor: tuple[StoreConnection, UUID, UUID],
) -> None:
    """An audit event records that a decision was made and what it bound to.
    The payload's digest travels; the payload does not, because it is derived
    from a document."""
    conn, case_id, user_id = actor
    governed_write(
        conn, _action(case_id, user_id, version="secret-version"), lambda _c: None
    )

    [entry] = audit_trail(conn, case_id)

    assert isinstance(entry, AuditEntry)
    assert len(entry.payload_sha256) == 64
    assert "secret-version" not in repr(entry)
    assert entry.previous_sha256 == "0" * 64, "the first entry links to genesis"
    assert entry.at.tzinfo is not None


def test_membership_revocation_refuses_commit(
    actor: tuple[StoreConnection, UUID, UUID],
) -> None:
    """The Phase 6 exit test. Standing is rechecked inside the store call.

    The actor was a WRITER when the request arrived. By the time the commit is
    attempted they are not, and the commit is where it matters.
    """
    conn, case_id, user_id = actor
    assert standing_of(conn, case_id=case_id, user_id=user_id) is Standing.WRITER

    revoke(conn, case_id=case_id, user_id=user_id)
    conn.commit()

    with pytest.raises(Refusal) as caught:
        governed_write(conn, _action(case_id, user_id), lambda _conn: None)

    assert caught.value.code is RefusalCode.NOT_AUTHORISED
    assert audit_trail(conn, case_id) == []


def test_a_lesser_standing_cannot_do_a_greater_action(
    case: tuple[StoreConnection, UUID],
) -> None:
    conn, case_id = case
    reader = uuid4()
    grant(conn, case_id=case_id, user_id=reader, standing=Standing.READER)
    conn.commit()

    action = GovernedAction(
        case_id=case_id,
        actor_id=reader,
        action="SOURCE_SET_PINNED",
        requires=Standing.WRITER,
        payload={"version": "1"},
    )

    with pytest.raises(Refusal) as caught:
        governed_write(conn, action, lambda _conn: None)

    assert caught.value.code is RefusalCode.NOT_AUTHORISED


def test_a_greater_standing_can_do_a_lesser_action(
    case: tuple[StoreConnection, UUID],
) -> None:
    conn, case_id = case
    admin = uuid4()
    grant(conn, case_id=case_id, user_id=admin, standing=Standing.ADMIN)
    conn.commit()

    governed_write(conn, _action(case_id, admin), lambda _conn: None)

    assert len(audit_trail(conn, case_id)) == 1


def test_someone_who_is_not_a_member_is_refused(
    case: tuple[StoreConnection, UUID],
) -> None:
    """The same refusal a member of another case gets: neither answer says
    whether the case exists."""
    conn, case_id = case

    with pytest.raises(Refusal) as caught:
        governed_write(conn, _action(case_id, uuid4()), lambda _conn: None)

    assert caught.value.code is RefusalCode.NOT_AUTHORISED


def test_the_chain_links_each_entry_to_the_last(
    actor: tuple[StoreConnection, UUID, UUID],
) -> None:
    conn, case_id, user_id = actor

    for version in ("1", "2", "3"):
        governed_write(
            conn, _action(case_id, user_id, version=version), lambda _c: None
        )

    trail = audit_trail(conn, case_id)
    assert [entry.seq for entry in trail] == [1, 2, 3]
    assert trail[1].previous_sha256 == trail[0].entry_sha256
    assert trail[2].previous_sha256 == trail[1].entry_sha256
    assert verify_chain(conn, case_id) is True


def test_a_rewritten_entry_breaks_the_chain(
    actor: tuple[StoreConnection, UUID, UUID],
) -> None:
    """The chain has no external anchor (`SYSTEM_SPEC.md` §2); what it gives is
    detection. An entry edited in place no longer hashes to what the next one
    says came before it."""
    conn, case_id, user_id = actor
    for version in ("1", "2"):
        governed_write(
            conn, _action(case_id, user_id, version=version), lambda _c: None
        )
    assert verify_chain(conn, case_id) is True

    conn.execute("SET LOCAL session_replication_role = replica")
    conn.execute(
        "UPDATE audit_events SET action = %s WHERE case_id = %s AND seq = 1",
        ("SOMETHING_ELSE", case_id),
    )
    conn.execute("SET LOCAL session_replication_role = origin")

    assert verify_chain(conn, case_id) is False


def test_two_cases_have_two_chains(
    actor: tuple[StoreConnection, UUID, UUID],
) -> None:
    """Chained per case. One case's history cannot be read from another's, and
    a busy case cannot delay a quiet one at the head lock."""
    conn, case_id, user_id = actor
    other = create_case(conn, BoundaryText.of("Beta 2026"))
    grant(conn, case_id=other, user_id=user_id, standing=Standing.WRITER)
    conn.commit()

    governed_write(conn, _action(case_id, user_id), lambda _conn: None)
    governed_write(conn, _action(other, user_id), lambda _conn: None)

    assert len(audit_trail(conn, case_id)) == 1
    assert len(audit_trail(conn, other)) == 1
    assert audit_head(conn, case_id) != audit_head(conn, other)


def test_standing_of_a_stranger_is_none(case: tuple[StoreConnection, UUID]) -> None:
    conn, case_id = case

    assert standing_of(conn, case_id=case_id, user_id=uuid4()) is None


class _Receipt(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    run_id: UUID
    padding: str = ""


def test_a_command_commits_state_audit_and_receipt_together_or_nothing(
    actor: tuple[StoreConnection, UUID, UUID], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Task 4.2 decision 9: the domain write, its audit link and the idempotency
    receipt are one commit. A receipt the store refuses (over its bound) takes
    the state and the audit event with it; an audit link that fails after the
    receipt was written takes the receipt with it."""
    conn, case_id, user_id = actor

    def command(padding: str) -> CommandResult:
        def write(unit: StoreConnection) -> tuple[int, BaseModel]:
            return 201, _Receipt(run_id=start_run(unit, case_id), padding=padding)

        return run_command(
            conn,
            scope=case_id,
            key=uuid4(),
            command="START_RUN",
            request_sha256=request_digest(
                "START_RUN", case_id=case_id, run_id=None, gate=None, body={}
            ),
            action=_action(case_id, user_id),
            write=write,
        )

    def counts() -> tuple[int, int, int]:
        row = conn.execute(
            "SELECT (SELECT count(*) FROM runs), (SELECT count(*) FROM audit_events),"
            " (SELECT count(*) FROM command_requests)"
        ).fetchone()
        conn.rollback()
        assert row is not None
        return int(row[0]), int(row[1]), int(row[2])

    with pytest.raises(Refusal) as oversized:
        command("x" * 70_000)
    assert oversized.value.code is RefusalCode.STORE_UNAVAILABLE
    assert counts() == (0, 0, 0)

    def broken_link(*_args: object) -> str:
        raise _Died

    with monkeypatch.context() as patch:
        patch.setattr(audit_module, "_link", broken_link)
        with pytest.raises(_Died):
            command("")
    assert counts() == (0, 0, 0)

    done = command("")
    assert (done.status, done.replayed) == (201, False)
    assert counts() == (1, 1, 1)
    [entry] = audit_trail(conn, case_id)
    assert entry.action == "SOURCE_SET_PINNED"

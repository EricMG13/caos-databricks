"""Case mutations contend on real PostgreSQL connections, with observed blocking."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from threading import Event
from time import monotonic
from uuid import UUID, uuid4

import pytest
from psycopg.pq import TransactionStatus
from run_terminals import fail_run
from test_gates import _approval, _pin

from caos.blobs import BlobStore
from caos.boundary_text import BoundaryText
from caos.evidence.extract import PlainTextExtractor, Token
from caos.evidence.ingest import Document, admit_pack
from caos.refusals import Refusal, RefusalCode
from caos.store import StoreConnection, connect, gates
from caos.store.audit import GovernedAction, audit_trail, governed_write, verify_chain
from caos.store.cases import lock_case
from caos.store.gates import Gate, GateApproval, approve_gate, withdraw_source
from caos.store.members import Standing, grant, revoke
from caos.store.runs import create_case, start_attempt, start_run


@contextmanager
def _blocked(
    holder: StoreConnection, waiter: StoreConnection, operation: Callable[[], object]
) -> Iterator[None]:
    """Require actual DB blocking; always release our holder before joining."""
    waiter.execute("SET statement_timeout = '5s'")
    waiter.commit()
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(operation)
        try:
            _wait_for_blocking(holder, waiter)
            yield
        finally:
            holder.commit()
            future.result(timeout=6)


def _wait_for_blocking(holder: StoreConnection, waiter: StoreConnection) -> None:
    deadline = monotonic() + 3
    while monotonic() < deadline:
        row = holder.execute(
            "SELECT %s = ANY(pg_blocking_pids(%s))",
            (holder.info.backend_pid, waiter.info.backend_pid),
        ).fetchone()
        if row == (True,):
            return
    pytest.fail("mutation did not wait for the case owner")


def _write_run(conn: StoreConnection, case_id: UUID) -> None:
    start_run(conn, case_id)


@pytest.fixture
def member(
    case: tuple[StoreConnection, UUID],
) -> tuple[StoreConnection, GovernedAction]:
    conn, case_id = case
    actor_id = uuid4()
    grant(conn, case_id=case_id, user_id=actor_id, standing=Standing.APPROVER)
    conn.commit()
    return conn, GovernedAction(case_id, actor_id, "TEST", Standing.APPROVER, {})


@pytest.fixture
def gate_approval(
    member: tuple[StoreConnection, GovernedAction], tmp_path: Path
) -> tuple[StoreConnection, GovernedAction, GateApproval]:
    conn, action = member
    admit_pack(
        conn,
        BlobStore(tmp_path),
        case_id=action.case_id,
        documents=[Document(BoundaryText.of("review.txt"), b"Reviewed source.")],
    )
    run = start_run(conn, action.case_id)
    conn.commit()
    _pin(conn, action.case_id, run)
    return conn, action, _approval(conn, run, action.actor_id)


def test_two_first_approvals_serialize(
    gate_approval: tuple[StoreConnection, GovernedAction, GateApproval],
    empty_database: str,
) -> None:
    conn, action, approval = gate_approval
    conn.execute(
        "SELECT case_id FROM cases WHERE case_id = %s FOR UPDATE", (action.case_id,)
    )
    with connect(empty_database) as other:
        with _blocked(conn, other, lambda: approve_gate(other, approval)):
            approve_gate(conn, approval)
    assert [entry.seq for entry in audit_trail(conn, action.case_id)] == [1, 2]
    assert verify_chain(conn, action.case_id)


@pytest.mark.parametrize("change", ["revoke", "downgrade"])
def test_membership_change_first_refuses_waiting_approval(
    gate_approval: tuple[StoreConnection, GovernedAction, GateApproval],
    empty_database: str,
    change: str,
) -> None:
    conn, action, approval = gate_approval
    if change == "revoke":
        revoke(conn, case_id=action.case_id, user_id=action.actor_id)
    else:
        grant(
            conn,
            case_id=action.case_id,
            user_id=action.actor_id,
            standing=Standing.WRITER,
        )
    with connect(empty_database) as other:

        def refused() -> None:
            with pytest.raises(Refusal, match=r"^NOT_AUTHORISED$"):
                approve_gate(other, approval)
            assert other.info.transaction_status is TransactionStatus.IDLE

        with _blocked(conn, other, refused):
            pass
    assert audit_trail(conn, action.case_id) == []
    assert conn.execute("SELECT count(*) FROM run_gates").fetchone() == (0,)


def test_approval_first_holds_authority_until_commit(
    gate_approval: tuple[StoreConnection, GovernedAction, GateApproval],
    empty_database: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn, action, approval = gate_approval
    ready, release = Event(), Event()
    preview = gates.gate_preview

    def pause(c: StoreConnection, run: UUID, gate: Gate) -> gates.GatePreview:
        result = preview(c, run, gate)
        ready.set()
        assert release.wait(5)
        return result

    monkeypatch.setattr(gates, "gate_preview", pause)
    with connect(empty_database) as other, ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(approve_gate, conn, approval)
        try:
            assert ready.wait(3)
            second = pool.submit(
                revoke, other, case_id=action.case_id, user_id=action.actor_id
            )
            _wait_for_blocking(conn, other)
        finally:
            release.set()
        first.result(timeout=6)
        second.result(timeout=6)
        other.commit()
    assert len(audit_trail(conn, action.case_id)) == 1
    assert verify_chain(conn, action.case_id)
    assert (
        gates.gate_state(conn, approval.run_id, approval.gate) is gates.GateState.OPEN
    )


@pytest.mark.parametrize("change", ["revoke", "downgrade"])
def test_membership_change_first_refuses_waiting_action(
    member: tuple[StoreConnection, GovernedAction], empty_database: str, change: str
) -> None:
    conn, action = member
    if change == "revoke":
        revoke(conn, case_id=action.case_id, user_id=action.actor_id)
    else:
        grant(
            conn,
            case_id=action.case_id,
            user_id=action.actor_id,
            standing=Standing.READER,
        )
    with connect(empty_database) as other:

        def refused() -> None:
            with pytest.raises(Refusal) as caught:
                governed_write(other, action, lambda c: _write_run(c, action.case_id))
            assert caught.value.code is RefusalCode.NOT_AUTHORISED

        with _blocked(conn, other, refused):
            pass
    assert audit_trail(conn, action.case_id) == []
    assert conn.execute("SELECT count(*) FROM runs").fetchone() == (0,)


def test_governed_first_holds_authority_until_commit(
    member: tuple[StoreConnection, GovernedAction], empty_database: str
) -> None:
    conn, action = member
    ready, release = Event(), Event()

    def write(c: StoreConnection) -> None:
        ready.set()
        assert release.wait(5)
        start_run(c, action.case_id)

    with connect(empty_database) as other, ThreadPoolExecutor(max_workers=2) as pool:
        other.execute("SET statement_timeout = '5s'")
        other.commit()
        first = pool.submit(governed_write, conn, action, write)
        try:
            assert ready.wait(3)
            second = pool.submit(
                revoke, other, case_id=action.case_id, user_id=action.actor_id
            )
            _wait_for_blocking(conn, other)
        finally:
            release.set()
        first.result(timeout=6)
        second.result(timeout=6)
        other.commit()
    with pytest.raises(Refusal):
        governed_write(conn, action, lambda c: _write_run(c, action.case_id))
    assert len(audit_trail(conn, action.case_id)) == 1


def test_digest_failure_rolls_back_callback(
    member: tuple[StoreConnection, GovernedAction], empty_database: str
) -> None:
    conn, action = member
    with pytest.raises(TypeError):
        governed_write(
            conn,
            replace(action, payload={"invalid": object()}),
            lambda c: _write_run(c, action.case_id),
        )
    conn.commit()
    assert conn.execute("SELECT count(*) FROM runs").fetchone() == (0,)
    assert audit_trail(conn, action.case_id) == []
    with connect(empty_database) as other:
        other.execute("SET lock_timeout = '1s'")
        grant(
            other,
            case_id=action.case_id,
            user_id=action.actor_id,
            standing=Standing.WRITER,
        )


@pytest.mark.parametrize(
    "isolation", ["repeatable read", "serializable", "read uncommitted"]
)
def test_nondefault_isolation_refuses_before_mutation(
    member: tuple[StoreConnection, GovernedAction], isolation: str
) -> None:
    conn, action = member
    conn.execute(f"SET TRANSACTION ISOLATION LEVEL {isolation}")
    conn.execute("SELECT count(*) FROM case_members")
    with pytest.raises(Refusal) as caught:
        governed_write(conn, action, lambda c: _write_run(c, action.case_id))
    assert caught.value.code is RefusalCode.STORE_NOT_TRANSACTIONAL
    conn.commit()
    assert audit_trail(conn, action.case_id) == []


def test_another_case_does_not_wait(
    member: tuple[StoreConnection, GovernedAction], empty_database: str
) -> None:
    conn, action = member
    second = create_case(conn, BoundaryText.of("Independent case"))
    grant(conn, case_id=second, user_id=action.actor_id, standing=Standing.APPROVER)
    conn.commit()
    revoke(conn, case_id=action.case_id, user_id=action.actor_id)
    with connect(empty_database) as other:
        other.execute("SET lock_timeout = '1s'")
        governed_write(
            other, replace(action, case_id=second), lambda c: _write_run(c, second)
        )
    conn.rollback()


@pytest.mark.parametrize("stage", ["callback", "audit", "head"])
def test_governed_failure_rolls_back_whole_unit_and_releases_lock(
    member: tuple[StoreConnection, GovernedAction], empty_database: str, stage: str
) -> None:
    conn, action = member
    if stage != "callback":
        # Real database-stage errors, after the callback has written its state.
        conn.execute(
            {
                "audit": "ALTER TABLE audit_events ADD CHECK (action <> 'TEST')",
                "head": "ALTER TABLE audit_chain_heads ADD CHECK (seq < 1)",
            }[stage]
        )
        conn.commit()

    def write(c: StoreConnection) -> None:
        start_run(c, action.case_id)
        if stage == "callback":
            raise Refusal(RefusalCode.EVIDENCE_NOT_AVAILABLE)

    with pytest.raises(Refusal) as caught:
        governed_write(conn, action, write)
    expected = (
        RefusalCode.EVIDENCE_NOT_AVAILABLE
        if stage == "callback"
        else RefusalCode.STORE_UNAVAILABLE
    )
    assert caught.value.code is expected
    assert conn.info.transaction_status is TransactionStatus.IDLE
    conn.commit()  # a caller cannot accidentally save orphan state afterwards
    assert conn.execute("SELECT count(*) FROM runs").fetchone() == (0,)
    assert audit_trail(conn, action.case_id) == []
    assert conn.execute("SELECT count(*) FROM audit_chain_heads").fetchone() == (0,)
    with connect(empty_database) as other:
        other.execute("SET lock_timeout = '1s'")
        lock_case(other, action.case_id)


@pytest.mark.parametrize(
    "mutation", ["start", "attempt", "source", "withdraw", "grant"]
)
def test_mutations_lock_case_before_dependent_rows(
    member: tuple[StoreConnection, GovernedAction],
    empty_database: str,
    tmp_path: Path,
    mutation: str,
) -> None:
    conn, action = member
    run = start_run(conn, action.case_id)
    blobs = BlobStore(tmp_path)
    document = Document(BoundaryText.of("source.txt"), b"A supplied source.")
    [source] = admit_pack(conn, blobs, case_id=action.case_id, documents=[document])
    conn.commit()
    # NO KEY UPDATE does not block foreign-key checks. The waiter must take an
    # explicit case lock; inserting a child row is not sufficient evidence.
    conn.execute(
        "SELECT case_id FROM cases WHERE case_id = %s FOR NO KEY UPDATE",
        (action.case_id,),
    )
    with connect(empty_database) as other:
        operations: dict[str, Callable[[], object]] = {
            "start": lambda: start_run(other, action.case_id),
            "attempt": lambda: start_attempt(other, run, "CP-1"),
            "source": lambda: admit_pack(
                other, blobs, case_id=action.case_id, documents=[document]
            ),
            "withdraw": lambda: withdraw_source(
                other,
                case_id=action.case_id,
                source_id=source,
                actor_id=action.actor_id,
            ),
            "grant": lambda: grant(
                other, case_id=action.case_id, user_id=uuid4(), standing=Standing.READER
            ),
        }
        with _blocked(conn, other, operations[mutation]):
            assert conn.execute("SELECT count(*) FROM run_attempts").fetchone() == (0,)
        other.commit()


def test_lock_run_reads_status_after_waiting(
    member: tuple[StoreConnection, GovernedAction], empty_database: str
) -> None:
    conn, action = member
    run = start_run(conn, action.case_id)
    conn.commit()
    lock_case(conn, action.case_id)
    with connect(empty_database) as other:

        def attempt() -> None:
            with pytest.raises(Refusal) as caught:
                start_attempt(other, run, "CP-1")
            assert caught.value.code is RefusalCode.RUN_NOT_RUNNING
            assert other.info.transaction_status is TransactionStatus.IDLE

        with _blocked(conn, other, attempt):
            fail_run(conn, run)
    assert conn.execute("SELECT count(*) FROM run_attempts").fetchone() == (0,)


def test_extraction_precedes_case_lock(
    member: tuple[StoreConnection, GovernedAction], empty_database: str, tmp_path: Path
) -> None:
    conn, action = member
    extracted = Event()

    class Reader:
        identity = PlainTextExtractor().identity

        def extract(self, data: bytes, **_kwargs: object) -> list[Token]:
            extracted.set()
            return PlainTextExtractor().extract(data)

    lock_case(conn, action.case_id)
    with connect(empty_database) as other:
        with _blocked(
            conn,
            other,
            lambda: admit_pack(
                other,
                BlobStore(tmp_path),
                case_id=action.case_id,
                documents=[Document(BoundaryText.of("source.txt"), b"Supplied text.")],
                dispatch=lambda data: Reader(),
            ),
        ):
            assert extracted.is_set()


def test_lock_case_refuses_autocommit_and_missing_case(empty_database: str) -> None:
    from caos.store import apply_schema

    with connect(empty_database) as conn:
        apply_schema(conn)
        with pytest.raises(Refusal) as caught:
            lock_case(conn, uuid4())
        assert caught.value.code is RefusalCode.CASE_NOT_FOUND
        conn.rollback()
        conn.autocommit = True
        with pytest.raises(Refusal) as caught:
            lock_case(conn, uuid4())
        assert caught.value.code is RefusalCode.STORE_NOT_TRANSACTIONAL


def test_governed_missing_case_remains_unauthorised(
    member: tuple[StoreConnection, GovernedAction],
) -> None:
    conn, action = member
    with pytest.raises(Refusal) as caught:
        governed_write(conn, replace(action, case_id=uuid4()), lambda _c: None)
    assert caught.value.code is RefusalCode.NOT_AUTHORISED
    assert conn.info.transaction_status is TransactionStatus.IDLE


@pytest.mark.parametrize("cancelled", [False, True])
def test_governed_broken_connection_preserves_safe_failure(
    member: tuple[StoreConnection, GovernedAction], cancelled: bool
) -> None:
    conn, action = member

    def write(c: StoreConnection) -> None:
        c.close()
        raise KeyboardInterrupt

    if cancelled:
        with pytest.raises(KeyboardInterrupt):
            governed_write(conn, action, write)
    else:
        conn.close()
        with pytest.raises(Refusal) as caught:
            governed_write(conn, action, lambda _c: None)
        assert caught.value.code is RefusalCode.STORE_UNAVAILABLE

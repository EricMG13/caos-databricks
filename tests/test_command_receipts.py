"""Task 4.2 decision 6, store half: receipts, their digest and the twin race.

Nothing here imports `caos/api/`: the runner is exercised on its own, with a
test-only nil-scope "create case" standing in for the command slice 4.2d adds.
The HTTP half (key header, bodies, standing, replay over a route) is
`tests/test_command_idempotency.py`.
"""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict

from caos.boundary_text import BoundaryText
from caos.store import StoreConnection, connect
from caos.store.audit import GovernedAction
from caos.store.commands import (
    NIL_SCOPE,
    CommandResult,
    find_receipt,
    record_receipt,
    request_digest,
    run_command,
)
from caos.store.members import Standing, grant


class _Created(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    case_id: UUID


def _insert_case(
    case_id: UUID, title: str, creator: UUID
) -> Callable[[StoreConnection], None]:
    def prepare(conn: StoreConnection) -> None:
        conn.execute(
            "INSERT INTO cases (case_id, title) VALUES (%s, %s)",
            (case_id, BoundaryText.of(title).value),
        )
        grant(conn, case_id=case_id, user_id=creator, standing=Standing.ADMIN)

    return prepare


def _count(conn: StoreConnection, sql: str, *params: object) -> int:
    row = conn.execute(sql, params).fetchone()
    conn.rollback()
    assert row is not None
    return int(row[0])


def test_concurrent_twins_on_one_key_make_one_case(
    case: tuple[StoreConnection, UUID], empty_database: str
) -> None:
    """Nil scope shares no case lock: the primary key's wait decides it. Both
    twins pass the in-unit lookup before either inserts its receipt, so one of
    them must meet `ON CONFLICT DO NOTHING`, roll back its case and replay."""
    conn, _case_id = case
    actor, key, title = uuid4(), uuid4(), "Twin 2026"
    both_written = Barrier(2, timeout=10)
    digest = request_digest(
        "PROBE_CREATE_CASE", case_id=None, run_id=None, gate=None, body={"title": title}
    )

    def twin() -> CommandResult:
        with connect(empty_database) as own:
            case_id = uuid4()

            def write(_unit: StoreConnection) -> tuple[int, BaseModel]:
                both_written.wait()
                return 201, _Created(case_id=case_id)

            return run_command(
                own,
                scope=NIL_SCOPE,
                key=key,
                command="PROBE_CREATE_CASE",
                request_sha256=digest,
                action=GovernedAction(
                    case_id, actor, "CASE_CREATED", Standing.ADMIN, {}
                ),
                prepare=_insert_case(case_id, title, actor),
                write=write,
            )

    with ThreadPoolExecutor(2) as pool:
        results = [f.result(timeout=30) for f in [pool.submit(twin), pool.submit(twin)]]

    assert sorted(r.replayed for r in results) == [False, True]
    assert results[0].receipt == results[1].receipt
    assert results[0].status == results[1].status == 201
    assert _count(conn, "SELECT count(*) FROM cases WHERE title = %s", title) == 1
    assert _count(conn, "SELECT count(*) FROM command_requests") == 1
    stored = find_receipt(conn, actor_id=actor, scope=NIL_SCOPE, key=key)
    conn.rollback()
    assert stored is not None and stored.request_sha256 == digest


def test_the_digest_is_canonical_and_binds_every_part() -> None:
    body = {"a": 1, "b": "é"}
    base = request_digest(
        "START_RUN", case_id=NIL_SCOPE, run_id=None, gate=None, body=body
    )
    same = request_digest(
        "START_RUN", case_id=NIL_SCOPE, run_id=None, gate=None, body={"b": "é", "a": 1}
    )
    assert base == same and len(base) == 64
    for other in (
        request_digest(
            "RETRY_RUN", case_id=NIL_SCOPE, run_id=None, gate=None, body=body
        ),
        request_digest("START_RUN", case_id=None, run_id=None, gate=None, body=body),
        request_digest(
            "START_RUN", case_id=NIL_SCOPE, run_id=uuid4(), gate=None, body=body
        ),
        request_digest(
            "START_RUN", case_id=NIL_SCOPE, run_id=None, gate="source-set", body=body
        ),
        request_digest("START_RUN", case_id=NIL_SCOPE, run_id=None, gate=None, body={}),
    ):
        assert other != base


def test_record_receipt_inserts_once_and_find_receipt_reads_it_back(
    case: tuple[StoreConnection, UUID],
) -> None:
    """`record_receipt` is the backstop: a taken key inserts nothing."""
    conn, case_id = case
    actor, key = uuid4(), uuid4()
    assert find_receipt(conn, actor_id=actor, scope=case_id, key=key) is None
    for inserted in (True, False):
        assert (
            record_receipt(
                conn,
                actor_id=actor,
                scope=case_id,
                key=key,
                command="START_RUN",
                request_sha256="a" * 64,
                status=202,
                receipt={"ok": True},
            )
            is inserted
        )
    conn.commit()

    stored = find_receipt(conn, actor_id=actor, scope=case_id, key=key)
    conn.rollback()

    assert stored is not None
    assert (stored.command, stored.status, stored.receipt) == (
        "START_RUN",
        202,
        {"ok": True},
    )
    assert find_receipt(conn, actor_id=uuid4(), scope=case_id, key=key) is None
    conn.rollback()

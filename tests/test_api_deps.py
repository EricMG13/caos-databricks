"""Direct unit tests for caos/api/deps.py's id parsers and visibility check."""

from __future__ import annotations

from collections.abc import Generator
from typing import cast
from uuid import UUID, uuid4

import psycopg
import pytest

from caos.api import deps
from caos.api.deps import parse_uuid, visible_case
from caos.api.identity import Actor, GlobalRole
from caos.refusals import Refusal, RefusalCode
from caos.store import StoreConnection
from caos.store.members import Standing, grant


def test_parse_uuid_accepts_a_well_formed_uuid() -> None:
    value = uuid4()
    assert parse_uuid(str(value), RefusalCode.CASE_NOT_FOUND) == value


def test_parse_uuid_refuses_anything_else_with_the_given_code() -> None:
    with pytest.raises(Refusal) as caught:
        parse_uuid("not-a-uuid", RefusalCode.RUN_NOT_FOUND)
    assert caught.value.code is RefusalCode.RUN_NOT_FOUND


def test_deps_reads_no_blob() -> None:
    """N35's remainder: `visible_case` is a store row and `blob_store`/
    `request_blobs` only construct the handle a route reads through, so this
    module's own IO_BUDGET (1) carries no blob dimension."""
    assert deps.BLOB_BUDGET == 0


def test_visible_case_reads_the_callers_own_standing(
    case: tuple[StoreConnection, UUID],
) -> None:
    conn, case_id = case
    user = uuid4()
    grant(conn, case_id=case_id, user_id=user, standing=Standing.WRITER)
    conn.commit()

    standing = visible_case(Actor(user_id=user, role=GlobalRole.READER), case_id, conn)
    conn.rollback()

    assert standing is Standing.WRITER


def test_visible_case_refuses_a_stranger_the_same_as_an_unknown_case(
    case: tuple[StoreConnection, UUID],
) -> None:
    conn, case_id = case
    with pytest.raises(Refusal) as caught:
        visible_case(Actor(user_id=uuid4(), role=GlobalRole.READER), case_id, conn)
    conn.rollback()
    assert caught.value.code is RefusalCode.CASE_NOT_FOUND


def test_store_connection_refuses_a_post_connect_fault_as_store_unavailable(
    empty_database: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """CF-022: a fault after connect -- a dropped session, a statement
    timeout -- is refused `STORE_UNAVAILABLE` the same as a fault at connect,
    rather than escaping this dependency as the bare `psycopg.Error` the edge
    guard would otherwise answer generically `INTERNAL_FAULT`.

    FastAPI throws a route's exception into a `yield` dependency at its
    `yield` (the documented contract for cleanup with `except`), so `.throw`
    here is exactly what a query failing mid-request would do to this
    generator.
    """
    monkeypatch.setenv(deps.DATABASE_URL, empty_database)
    generator = deps.store_connection()
    conn = next(generator)
    assert not conn.closed

    with pytest.raises(Refusal) as caught:
        cast("Generator[object]", generator).throw(
            psycopg.OperationalError("server closed the connection")
        )

    assert caught.value.code is RefusalCode.STORE_UNAVAILABLE
    assert conn.closed, "the connection is not left open past the fault"


@pytest.mark.parametrize(
    "fault",
    [
        psycopg.errors.UndefinedColumn("a route's SQL names column z_secret"),
        psycopg.errors.UniqueViolation("a governed write collided on z_secret"),
        psycopg.errors.RaiseException("z_secret rows are immutable"),
    ],
    ids=["undefined-column", "unique-violation", "trigger-refusal"],
)
def test_store_connection_answers_a_refused_statement_as_an_internal_fault(
    empty_database: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    fault: psycopg.Error,
) -> None:
    """N5: every `psycopg.Error` a route raised was a retryable 503
    `STORE_UNAVAILABLE` with nothing logged, so a SQL bug, a unique violation
    or a trigger's refusal read as an outage and left no trace. Only the
    store not answering is that now (`caos.store.interrupted`, R24-05's own
    classifier); anything else is `INTERNAL_FAULT`, logged as the edge logs an
    unhandled fault -- its class and frame, never its text."""
    monkeypatch.setenv(deps.DATABASE_URL, empty_database)
    generator = deps.store_connection()
    conn = next(generator)
    capsys.readouterr()
    with pytest.raises(Refusal) as caught:
        cast("Generator[object]", generator).throw(fault)
    assert caught.value.code is RefusalCode.INTERNAL_FAULT
    logged = capsys.readouterr().err
    assert logged.startswith(f"{type(fault).__name__} at "), logged
    assert logged.count("\n") == 1 and "z_secret" not in logged
    assert conn.closed


@pytest.mark.parametrize(
    "fault",
    [
        psycopg.errors.QueryCanceled("canceling statement due to z_secret"),
        psycopg.errors.AdminShutdown("terminating connection z_secret"),
        psycopg.errors.SerializationFailure("could not serialize z_secret"),
        psycopg.errors.LockNotAvailable("could not obtain lock on z_secret"),
    ],
    ids=["statement-timeout", "session-ended", "serialization", "lock-timeout"],
)
def test_store_connection_answers_an_interruption_as_store_unavailable(
    empty_database: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    fault: psycopg.Error,
) -> None:
    """N5: the store not answering this time -- a statement bound, an ended
    session, a transaction the server rolled back, a lock wait that timed out
    -- stays the retryable `STORE_UNAVAILABLE` (CF-022), with nothing logged."""
    monkeypatch.setenv(deps.DATABASE_URL, empty_database)
    generator = deps.store_connection()
    next(generator)
    capsys.readouterr()
    with pytest.raises(Refusal) as caught:
        cast("Generator[object]", generator).throw(fault)
    assert caught.value.code is RefusalCode.STORE_UNAVAILABLE
    assert capsys.readouterr().err == ""

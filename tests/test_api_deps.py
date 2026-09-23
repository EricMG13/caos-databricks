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

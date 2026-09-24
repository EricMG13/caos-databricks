"""Shared fixtures for the Task 4.2 command suites: identity headers with an
`Idempotency-Key`, case members, and the real app served on the `case`
fixture's connection (import the fixture by name and list it in `__all__`)."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from pathlib import Path
from uuid import UUID, uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient

from caos.api import app as app_module
from caos.api.app import app, blob_store, store_connection
from caos.api.identity import ROLE_HEADER, TRUST_SWITCH, TRUSTED
from caos.blobs import BlobStore
from caos.store import StoreConnection
from caos.store.members import Standing, grant


def command_headers(
    user: UUID, *, role: str = "ANALYST", key: UUID | str | None = None
) -> dict[str, str]:
    """What the development proxy forwards for `user` holding `role`, and the key.

    The role header, not the groups header: a tokenless API reads no groups at
    all (`caos/api/identity.py`), and these suites serve the app without an
    edge token. `command_client` sets the switch that makes this believed, the
    way `frontend/vite.config.ts` and `.env.example` do for the developer.

    `key=None` mints a fresh one; pass `""` to send the header empty.
    """
    return {
        "x-caos-user": str(user),
        ROLE_HEADER: role,
        "idempotency-key": str(uuid4() if key is None else key),
    }


def member(
    conn: StoreConnection, case_id: UUID, standing: Standing = Standing.WRITER
) -> UUID:
    """A new user holding `standing` on the case, committed."""
    user = uuid4()
    grant(conn, case_id=case_id, user_id=user, standing=standing)
    conn.commit()
    return user


def constant(value: object) -> Callable[[], object]:
    """A dependency override with no parameters FastAPI would read as inputs."""
    return lambda: value


class Borrowed:
    """One resolution's hold on the test's one connection, standing in for the
    connection of its own production's `store_connection` opens for each.

    `close` ends this hold and no other -- the admission closes its standing
    read's connection before it receives the pack (W3) -- and any use after it
    fails as a closed connection's would, while the test's own connection,
    and every other hold on it, stays open.
    """

    def __init__(self, conn: object) -> None:
        self._conn = conn
        self.closed = False

    def close(self) -> None:
        self.closed = True

    def __getattr__(self, name: str) -> object:
        if self.closed:
            raise psycopg.OperationalError
        return getattr(self._conn, name)


def borrowed(conn: object) -> Callable[[], object]:
    """A `store_connection` override handing each resolution its own hold."""
    return lambda: Borrowed(conn)


@pytest.fixture
def command_client(
    case: tuple[StoreConnection, UUID],
    empty_database: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[TestClient]:
    """The real app, booted against the test database, on the case's connection."""
    conn, _case_id = case
    # The development deployment: no edge token, so the role comes from the
    # header only because this asks for it. Without the switch the app grants
    # READER whatever arrives, and an authority matrix would prove nothing.
    monkeypatch.setenv(TRUST_SWITCH, TRUSTED)
    monkeypatch.setenv(app_module.DATABASE_URL, empty_database)
    app.dependency_overrides[store_connection] = borrowed(conn)
    app.dependency_overrides[blob_store] = constant(BlobStore(tmp_path / "blobs"))
    try:
        with TestClient(app) as opened:
            yield opened
    finally:
        app.dependency_overrides.clear()

"""The reaper of leaked disposable test databases (F588)."""

from __future__ import annotations

import time
from uuid import uuid4

import psycopg
import pytest
from conftest import POSTGRES_URL, _url_for
from pg_reaper import (
    MAX_AGE_SECONDS,
    database_name,
    is_reapable,
    reap,
    refused_server,
)

_NOW = 1_800_000_000


def test_a_minted_name_carries_its_second_and_fits_postgres() -> None:
    for prefix in ("caos_test_", "caos_test_template_"):
        name = database_name(prefix, now=_NOW)
        assert name.startswith(prefix + f"{_NOW}_")
        assert len(name.encode()) <= 63


def test_which_names_are_reapable() -> None:
    old = _NOW - MAX_AGE_SECONDS - 1
    young = _NOW - 60
    hexid = uuid4().hex
    assert is_reapable(f"caos_test_{hexid}", _NOW)
    assert is_reapable(f"caos_test_template_{hexid}", _NOW)
    assert is_reapable(f"caos_test_{old}_{hexid}", _NOW)
    assert is_reapable(f"caos_test_template_{old}_{hexid}", _NOW)
    assert not is_reapable(f"caos_test_{young}_{hexid}", _NOW)
    for other in (
        "postgres",
        "caos",
        f"caos_test_{hexid}x",
        "caos_test_x",
        "caos_testy",
    ):
        assert not is_reapable(other, _NOW)
    assert not is_reapable(f"my_caos_test_{hexid}", _NOW)


def test_a_dev_or_production_server_is_refused() -> None:
    assert refused_server("postgresql://u:p@127.0.0.1:55437/postgres") is None
    for url in (
        "postgresql://u:p@127.0.0.1:55436/postgres",
        "postgresql://u:p@127.0.0.1:55438/postgres",
        "postgresql://u:p@127.0.0.1:55437/caos_qualify_abc",
        "postgresql://u:p@127.0.0.1:55437/appdb",
        "postgresql://u:p@127.0.0.1/caos_dev",
        "postgresql://u:p@prod-db.example.com/postgres",
        "postgresql://u:p@x.cloud.databricks.com/postgres",
        "postgresql://u:p@127.0.0.1/production",
    ):
        assert refused_server(url) is not None


def test_the_allow_variable_admits_another_port_but_never_overrides(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    other = "postgresql://u:p@127.0.0.1:5999/postgres"
    monkeypatch.delenv("CAOS_TEST_REAPER_ALLOW", raising=False)
    assert refused_server(other) == "server_not_the_test_server"
    monkeypatch.setenv("CAOS_TEST_REAPER_ALLOW", "1")
    assert refused_server(other) is None
    assert refused_server("postgresql://u:p@127.0.0.1:55436/postgres") is not None
    assert refused_server("postgresql://u:p@prod-host:5999/postgres") is not None


def _make(admin: psycopg.Connection, name: str) -> None:
    admin.execute(f'CREATE DATABASE "{name}"')


def _exists(admin: psycopg.Connection, name: str) -> bool:
    row = admin.execute(
        "SELECT 1 FROM pg_database WHERE datname = %s", (name,)
    ).fetchone()
    return row is not None


def test_reap_drops_only_idle_old_matching_databases(empty_database: str) -> None:
    assert POSTGRES_URL is not None
    now = int(time.time())
    hexid = uuid4().hex
    old = f"caos_test_{now - MAX_AGE_SECONDS - 5}_{hexid}"
    legacy = f"caos_test_{uuid4().hex}"
    legacy_template = f"caos_test_template_{uuid4().hex}"
    young = f"caos_test_{now - 60}_{uuid4().hex}"
    busy = f"caos_test_{now - MAX_AGE_SECONDS - 5}_{uuid4().hex}"
    stranger = f"other_{uuid4().hex}"
    qualify = f"caos_qualify_{uuid4().hex}"
    names = [old, legacy, legacy_template, young, busy, stranger, qualify]
    with psycopg.connect(POSTGRES_URL, autocommit=True) as admin:
        try:
            for name in names:
                _make(admin, name)
            with psycopg.connect(_url_for(busy)):
                # A session is running a caos_test database: old format stays.
                reaped = reap(admin, now=now, other_sessions=1)
                assert old in reaped and not {legacy, legacy_template} & set(reaped)
                reaped = reap(admin, now=now, other_sessions=0)
            assert {legacy, legacy_template} <= set(reaped)
            assert not {young, busy, stranger, qualify} & set(reaped)
            assert [_exists(admin, n) for n in names] == [
                False,
                False,
                False,
                True,
                True,
                True,
                True,
            ]
        finally:
            for name in names:
                admin.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')


def test_the_session_hook_never_fails_the_session(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import pg_reaper

    monkeypatch.setattr(
        pg_reaper, "reap", lambda *a, **k: (_ for _ in ()).throw(KeyError("x"))
    )
    pg_reaper.reap_session("postgresql://postgres:x@127.0.0.1:55437/postgres")
    err = capsys.readouterr().err
    assert err.count("\n") == 1 and "pg_reaper: failed code=" in err
    pg_reaper.reap_session("postgresql://u:p@127.0.0.1/caos_dev")
    assert "pg_reaper: refused code=" in capsys.readouterr().err

"""D120 (amends D117): the idle bound turned off by a session `SET`, not a
startup option, and a server that refuses that `SET`.

Every store session -- `caos.store.connect`'s and the checkpointer pool's --
runs `SET idle_session_timeout = 0` as its first statement, so the server never
ends it for sitting idle while `call_hold` waits out a model call. A startup
option the server refuses arrives with no SQLSTATE, and finding the refusal by
asking again let a process's own connects at a connection limit drop the
option for good (the review's HIGH). A `SET` the server refuses says why: an
unknown parameter (42704), a value it will not take (22023), a feature it does
not support (0A000) or a right the role lacks (42501). On those the session
carries on without it, the process prints `IDLE_SESSION_OPTION_REFUSED` once
and skips the `SET` from then on; any other error closes the session and
refuses `STORE_UNAVAILABLE`. No connect is ever repeated for it.
"""

from __future__ import annotations

import os
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import ExitStack
from typing import Any, cast

import psycopg
import pytest
from conftest import login_role
from psycopg import sql
from psycopg.pq import TransactionStatus
from psycopg_pool import ConnectionPool

import caos.store as store
from caos.api import deps
from caos.graph import checkpoint
from caos.refusals import Refusal, RefusalCode
from caos.store import lakebase

NOTICE = "IDLE_SESSION_OPTION_REFUSED\n"
# A statement that fails with an error that is no refusal of the `SET`: once
# the process skips the `SET`, putting this in its place shows it is skipped.
_WOULD_FAIL = "SELECT 1/0"


@pytest.fixture(autouse=True)
def _fresh_process(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Each test is a process that has not yet found a refusal, with no
    `PGOPTIONS`; a test that leaves it changed fails here. The ambient value is
    restored by `monkeypatch` after this check, which does not undo first."""
    monkeypatch.setattr(store, "_IDLE_SESSION_REFUSED", threading.Event())
    monkeypatch.delenv("PGOPTIONS", raising=False)
    established = os.environ.get("PGOPTIONS")
    yield
    assert os.environ.get("PGOPTIONS") == established


@pytest.fixture
def operator_options(request: pytest.FixtureRequest) -> Iterator[None]:
    """`PGOPTIONS` as the parametrization gives it (indirect), for the test
    body only. Name it after `empty_database` in a signature: it is then torn
    down first, so the admin connection that drops the database never sees it."""
    value = getattr(request, "param", None)
    with pytest.MonkeyPatch.context() as scoped:
        if value is not None:
            scoped.setenv("PGOPTIONS", value)
        yield


def _connects(monkeypatch: pytest.MonkeyPatch) -> list[psycopg.Connection[Any]]:
    """Every connection `caos.store.connect` opened, in order."""
    opened: list[psycopg.Connection[Any]] = []
    real = cast("Callable[..., psycopg.Connection[Any]]", psycopg.connect)

    def spy(url: str, **kwargs: object) -> psycopg.Connection[Any]:
        opened.append(real(url, **kwargs))
        return opened[-1]

    monkeypatch.setattr(psycopg, "connect", spy)
    return opened


def _shown(conn: psycopg.Connection[Any], *names: str) -> list[object]:
    return [conn.execute(f"SHOW {name}").fetchone() for name in names]


@pytest.mark.parametrize(
    "operator_options", ["-c idle_session_timeout=5min"], indirect=True
)
def test_a_store_session_turns_its_idle_bound_off_with_its_first_statement(
    empty_database: str,
    operator_options: None,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """One connect, no idle startup option, and the `SET` committed: the
    session is idle, outside any transaction, as `call_hold` requires, and a
    caller's rollback does not undo it."""
    opened = _connects(monkeypatch)
    with store.connect(empty_database) as conn:
        assert conn.info.transaction_status is TransactionStatus.IDLE
        assert _shown(conn, "idle_session_timeout") == [("0",)], "over PGOPTIONS"
        conn.rollback()
        assert _shown(conn, "idle_session_timeout") == [("0",)]
        assert "idle_session_timeout=0" not in conn.info.dsn, "no startup option"
    assert len(opened) == 1
    assert capsys.readouterr().err == ""


@pytest.mark.parametrize(
    ("statement", "own_role"),
    [
        ("SET caos_no_such_parameter = 0", False),
        ("SET idle_session_timeout = 'never'", False),
        ("SET log_min_duration_statement = 0", True),
    ],
    ids=["42704-unrecognized", "22023-invalid-value", "42501-insufficient-privilege"],
)
def test_a_server_that_refuses_the_set_degrades_with_one_notice(
    empty_database: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    statement: str,
    own_role: bool,
) -> None:
    """The server's own refusals of a `SET` (the last one a parameter only a
    superuser may set, asked by a plain role): the session carries on, idle and
    usable, its search path and statement bound kept; the line is printed once,
    and later sessions skip the `SET` -- one in its place that would fail is
    never run -- each on one connect."""
    with ExitStack() as held:
        url = (
            held.enter_context(login_role(empty_database))
            if own_role
            else (empty_database)
        )
        monkeypatch.setattr(store, "IDLE_SESSION_SET", statement)
        opened = _connects(monkeypatch)
        with store.connect(url, statement_timeout_ms=5000) as conn:
            assert conn.info.transaction_status is TransactionStatus.IDLE
            assert _shown(conn, "search_path", "statement_timeout") == [
                ("caos_store",),
                ("5s",),
            ]
        assert store._IDLE_SESSION_REFUSED.is_set()
        assert capsys.readouterr().err == NOTICE

        monkeypatch.setattr(store, "IDLE_SESSION_SET", _WOULD_FAIL)
        for _ in range(2):
            with store.connect(url) as conn:
                assert conn.execute("SELECT 1").fetchone() == (1,)
        assert len(opened) == 3, "one connect each, none repeated"
        assert capsys.readouterr().err == "", "said once"


class _Session:
    """A session whose first statement fails with `fault`."""

    def __init__(self, fault: psycopg.Error) -> None:
        self.fault = fault
        self.autocommit = False
        self.closed = False
        self.rolled_back = False

    def execute(self, _statement: str) -> None:
        raise self.fault

    def rollback(self) -> None:
        self.rolled_back = True

    def commit(self) -> None:
        raise AssertionError

    def close(self) -> None:
        self.closed = True


@pytest.mark.parametrize(
    ("fault", "refused"),
    [
        (psycopg.errors.FeatureNotSupported("scripted"), True),
        (psycopg.errors.InsufficientPrivilege("scripted"), True),
        (psycopg.errors.AdminShutdown("scripted"), False),
        (psycopg.OperationalError("scripted, no SQLSTATE"), False),
    ],
    ids=["0A000", "42501", "57P01-another-error", "no-sqlstate"],
)
def test_only_the_four_refusals_of_the_set_degrade(
    capsys: pytest.CaptureFixture[str], fault: psycopg.Error, refused: bool
) -> None:
    """0A000 and 42501 as the server would send them; a session ended under
    the `SET`, or a fault with no SQLSTATE at all, is the store not answering:
    the session is closed and `STORE_UNAVAILABLE` refused, nothing remembered."""
    session = _Session(fault)
    turn_off = store.idle_session_off
    if refused:
        turn_off(cast("psycopg.Connection[Any]", session))
        assert session.rolled_back and not session.closed
    else:
        with pytest.raises(Refusal) as raised:
            turn_off(cast("psycopg.Connection[Any]", session))
        assert raised.value.code is RefusalCode.STORE_UNAVAILABLE
        assert session.closed
    assert store._IDLE_SESSION_REFUSED.is_set() is refused
    assert capsys.readouterr().err == (NOTICE if refused else "")


@pytest.mark.parametrize(
    ("statement", "operator_options"),
    [(_WOULD_FAIL, None), ("SELECT pg_sleep(1)", "-c statement_timeout=50")],
    ids=["22012-another-error", "57014-statement-timeout"],
    indirect=["operator_options"],
)
def test_another_set_error_closes_the_session_and_refuses_unavailable(
    empty_database: str,
    operator_options: None,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    statement: str,
) -> None:
    """A first statement the server fails for any other reason closes the
    session and refuses `STORE_UNAVAILABLE`, through the request edge too, on
    one connect each; nothing is remembered and nothing printed."""
    monkeypatch.setattr(store, "IDLE_SESSION_SET", statement)
    opened = _connects(monkeypatch)
    with pytest.raises(Refusal) as refused:
        store.connect(empty_database)
    assert refused.value.code is RefusalCode.STORE_UNAVAILABLE
    monkeypatch.setattr(deps, "_database_url", lambda: empty_database)
    with pytest.raises(Refusal) as at_the_edge:
        next(deps.store_connection())
    assert at_the_edge.value.code is RefusalCode.STORE_UNAVAILABLE
    assert len(opened) == 2 and all(conn.closed for conn in opened)
    assert not store._IDLE_SESSION_REFUSED.is_set()
    assert capsys.readouterr().err == ""


def test_a_connect_failure_is_never_repeated(
    empty_database: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A refused connect (a wrong password here) is one attempt, answered
    `STORE_UNAVAILABLE` at the edge as before D117."""
    attempts: list[str] = []
    real = cast("Callable[..., psycopg.Connection[Any]]", psycopg.connect)

    def counted(url: str, **kwargs: object) -> psycopg.Connection[Any]:
        attempts.append(url)
        return real(url, **kwargs)

    # The URL's own password, whichever database the suite runs against (a
    # developer's compose database and CI's service container differ).
    password = str(psycopg.conninfo.conninfo_to_dict(empty_database)["password"])
    wrong = empty_database.replace(f":{password}@", ":not-the-password@")
    assert wrong != empty_database
    monkeypatch.setattr(psycopg, "connect", counted)
    monkeypatch.setattr(deps, "_database_url", lambda: wrong)
    with pytest.raises(Refusal) as refused:
        next(deps.store_connection())
    assert refused.value.code is RefusalCode.STORE_UNAVAILABLE
    assert attempts == [wrong]


def test_concurrent_connects_at_a_connection_limit_never_drop_the_set(
    empty_database: str, capsys: pytest.CaptureFixture[str]
) -> None:
    """The review's HIGH: four threads of one process opening and closing
    sessions under a role limited to two connections. Connects are refused at
    the limit, as they always were; a refused connect says nothing about the
    `SET`, so every session that opens has its bound off and the process never
    takes the `SET` for refused (it did in 5 of 5 trials under the probe)."""
    shown: list[object] = []
    refused = [0]
    lock = threading.Lock()
    with login_role(empty_database) as url:
        role = str(psycopg.conninfo.conninfo_to_dict(url)["user"])
        with psycopg.connect(empty_database, autocommit=True) as admin:
            admin.execute(
                sql.SQL("ALTER ROLE {} CONNECTION LIMIT 2").format(sql.Identifier(role))
            )
        stop = time.monotonic() + 2.0

        def churn() -> None:
            while time.monotonic() < stop:
                try:
                    with store.connect(url) as conn:
                        seen = conn.execute("SHOW idle_session_timeout").fetchone()
                except psycopg.OperationalError:
                    with lock:
                        refused[0] += 1
                    continue
                with lock:
                    shown.append(seen)

        threads = [threading.Thread(target=churn) for _ in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
    assert refused[0] > 0, "the limit was reached"
    assert shown and set(shown) == {("0",)}
    assert not store._IDLE_SESSION_REFUSED.is_set()
    assert capsys.readouterr().err == ""


@pytest.mark.parametrize("platform", [False, True], ids=["local", "platform"])
def test_a_checkpoint_pool_whose_set_is_refused_degrades_with_one_notice(
    empty_database: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    platform: bool,
) -> None:
    """The pool's sessions run the same `SET` from its configure hook: refused
    (22023 here), each pooled session still works, with the graph's search path
    and its statement bound, and the process says so once. A pool whose `SET`
    is accepted is covered by
    `tests/test_checkpoint.py::test_a_pooled_checkpoint_session_is_never_ended_for_being_idle`."""
    if platform:
        monkeypatch.setenv(lakebase.LAKEBASE_INSTANCE, "caos-lb")
        monkeypatch.setattr(checkpoint, "store_url", lambda: empty_database)
    monkeypatch.setattr(store, "IDLE_SESSION_SET", "SET idle_session_timeout = 'x'")
    saver = checkpoint.checkpointer(None if platform else empty_database)
    try:
        pool = getattr(saver, "conn", None)
        assert isinstance(pool, ConnectionPool)
        assert pool.connection_class is (
            checkpoint.MintedConnection if platform else psycopg.Connection
        )
        with pool.connection() as first, pool.connection() as second:
            shown = [
                conn.execute(f"SHOW {name}").fetchone()
                for conn in (first, second)
                for name in ("search_path", "statement_timeout")
            ]
    finally:
        checkpoint.close_checkpointer(saver)
    assert shown == [{"search_path": "caos_graph"}, {"statement_timeout": "30s"}] * 2
    assert capsys.readouterr().err == NOTICE


def test_a_pooled_session_whose_set_fails_otherwise_is_closed_and_refused(
    empty_database: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The pool's configure hook on a session whose `SET` fails for another
    reason: the session is closed and `STORE_UNAVAILABLE` refused, which the
    pool takes as a failed connection (and opens another), never a session
    handed out without its bound."""
    monkeypatch.setattr(store, "IDLE_SESSION_SET", _WOULD_FAIL)
    conn = psycopg.connect(empty_database, autocommit=True)
    with pytest.raises(Refusal) as refused:
        checkpoint.configure_session(cast("psycopg.Connection[Any]", conn))
    assert refused.value.code is RefusalCode.STORE_UNAVAILABLE
    assert conn.closed
    assert capsys.readouterr().err == ""

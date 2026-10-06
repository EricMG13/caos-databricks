"""D120 (amends D117): a server that refuses `caos.store.IDLE_SESSION_OPTION`.

Every store session -- `caos.store.connect`'s and the checkpointer pool's --
asks the server not to end it for sitting idle. Whether Lakebase accepts the
option is unmeasured (N172), and a server that refused it refused every store
connection, `STORE_UNAVAILABLE`: the whole app down for a safety margin it has
a fallback for. libpq reports a refused startup option as any refused startup,
an `OperationalError` with no SQLSTATE, so the refusal is found by asking
again without the option and once more with it: only a server that lets the
session in without it, and still not with it, is taken to refuse it. Then the
process prints `IDLE_SESSION_OPTION_REFUSED` once and opens every later
session without it. Any other failure is answered as it always was.
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Iterator
from contextlib import ExitStack
from typing import Any, cast
from urllib.parse import urlsplit, urlunsplit

import psycopg
import pytest
from conftest import refuse_idle_session_option
from psycopg_pool import ConnectionPool

import caos.store as store
from caos.api import deps
from caos.graph import checkpoint
from caos.refusals import Refusal, RefusalCode
from caos.store import lakebase

NOTICE = "IDLE_SESSION_OPTION_REFUSED\n"


@pytest.fixture(autouse=True)
def _fresh_process(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Each test is a process that has not yet found a refusal."""
    monkeypatch.setattr(store, "_IDLE_SESSION_REFUSED", threading.Event())
    monkeypatch.delenv("PGOPTIONS", raising=False)
    yield


def _sent(monkeypatch: pytest.MonkeyPatch) -> list[bool]:
    """Whether each `caos.store.connect` attempt carried the option, in order."""
    sent: list[bool] = []
    real = cast("Callable[..., psycopg.Connection[Any]]", psycopg.connect)

    def spy(url: str, **kwargs: object) -> psycopg.Connection[Any]:
        sent.append(store.IDLE_SESSION_OPTION in str(kwargs.get("options", "")))
        return real(url, **kwargs)

    monkeypatch.setattr(psycopg, "connect", spy)
    return sent


def _shown(conn: store.StoreConnection, *names: str) -> list[object]:
    return [conn.execute(f"SHOW {name}").fetchone() for name in names]


def test_a_server_that_refuses_the_idle_option_is_reached_without_it_once(
    empty_database: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A server that accepts the option gets it on the first attempt. One that
    refuses it (a login trigger here, SQLSTATE 22023) lets the session in
    without it, the search path and the statement bound kept; the process
    says so once, and every later session goes without it at the first try."""
    sent = _sent(monkeypatch)
    with store.connect(empty_database) as conn:
        assert _shown(conn, "idle_session_timeout") == [("0",)]
    assert sent == [True], "a server that accepts it gets it, first time"
    assert capsys.readouterr().err == ""

    refuse_idle_session_option(empty_database)
    sent.clear()
    with store.connect(empty_database, statement_timeout_ms=5000) as conn:
        shown = _shown(conn, "idle_session_timeout", "search_path", "statement_timeout")
    assert shown == [("10min",), ("caos_store",), ("5s",)]
    assert sent == [True, False, True, False], "refused, let in, refused, opened"
    assert capsys.readouterr().err == NOTICE

    sent.clear()
    for _ in range(2):
        with store.connect(empty_database) as conn:
            assert _shown(conn, "idle_session_timeout") == [("10min",)]
    assert sent == [False, False], "remembered for the process"
    assert capsys.readouterr().err == "", "said once"


@pytest.mark.parametrize(
    "refused",
    ["-c caos_no_such_parameter=0", "-c idle_session_timeout=never"],
    ids=["42704-unrecognized-parameter", "22023-invalid-value"],
)
def test_a_server_refusing_the_option_by_name_or_value_is_reached_without_it(
    empty_database: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    refused: str,
) -> None:
    """The server's own refusals of a startup option -- a parameter it does not
    know, a value it will not take -- found the same way, by no message."""
    monkeypatch.setattr(store, "IDLE_SESSION_OPTION", refused)
    sent = _sent(monkeypatch)
    with store.connect(empty_database) as conn:
        assert _shown(conn, "search_path") == [("caos_store",)]
    assert sent == [True, False, True, False]
    assert capsys.readouterr().err == NOTICE


def test_a_connect_failure_that_is_not_the_option_still_refuses_unavailable(
    empty_database: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A refusal the option did not cause -- a wrong password here -- fails
    without it too, and is answered `STORE_UNAVAILABLE` as before; nothing is
    remembered, so the next session still asks for it."""
    parts = urlsplit(empty_database)
    wrong = urlunsplit(
        parts._replace(
            netloc=f"{parts.username}:not-the-password@{parts.hostname}:{parts.port}"
        )
    )
    sent = _sent(monkeypatch)
    monkeypatch.setattr(deps, "_database_url", lambda: wrong)
    with pytest.raises(Refusal) as refused:
        next(deps.store_connection())
    assert refused.value.code is RefusalCode.STORE_UNAVAILABLE
    assert sent == [True, False], "asked once without it, then refused as before"
    assert not store._IDLE_SESSION_REFUSED.is_set()
    assert capsys.readouterr().err == ""

    sent.clear()
    with store.connect(empty_database) as conn:
        assert _shown(conn, "idle_session_timeout") == [("0",)]
    assert sent == [True]


class _Opened:
    """A session a scripted attempt opened, and whether it was closed."""

    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


_FAILED = psycopg.OperationalError
_TIMED_OUT = psycopg.errors.ConnectionTimeout


@pytest.mark.parametrize(
    ("script", "sent", "opens", "refused"),
    [
        ([_TIMED_OUT], [True], False, False),
        ([_FAILED, None, None], [True, False, True], True, False),
        ([_FAILED, None, _TIMED_OUT], [True, False, True], False, False),
        ([_FAILED, None, _FAILED, None], [True, False, True, False], True, True),
        ([_FAILED, None, _FAILED, _FAILED], [True, False, True, False], False, True),
    ],
    ids=[
        "a-timeout-is-never-asked-again",
        "a-failure-that-passed-keeps-the-option",
        "a-timeout-on-the-second-ask-fails-closed",
        "refused-twice-let-in-twice",
        "refused-then-down-fails-closed-and-the-refusal-stands",
    ],
)
def test_only_a_refusal_the_option_alone_explains_drops_it(
    capsys: pytest.CaptureFixture[str],
    script: list[type[psycopg.OperationalError] | None],
    sent: list[bool],
    opens: bool,
    refused: bool,
) -> None:
    """A transient failure between two attempts must not cost the process the
    option for good: after a session is let in without it, the option is
    asked for once more, and only a second refusal drops it. A connect that
    timed out is no refusal of anything and is never asked again; the session
    opened without the option is closed before the second ask, so a server at
    its connection limit is not refused by our own spare session."""
    asked: list[bool] = []
    opened: list[_Opened] = []

    def scripted(idle: tuple[str, ...]) -> _Opened:
        asked.append(idle == (store.IDLE_SESSION_OPTION,))
        failure = script[len(asked) - 1]
        if failure is not None:
            raise failure("scripted")
        opened.append(_Opened())
        return opened[-1]

    open_session = cast(
        "Callable[[Callable[..., _Opened]], _Opened]", store.open_session
    )
    if not opens:
        with pytest.raises(psycopg.OperationalError):
            open_session(scripted)
        assert all(spare.closed for spare in opened)
    else:
        assert open_session(scripted) is opened[-1]
        assert not opened[-1].closed
        assert all(spare.closed for spare in opened[:-1])
    assert asked == sent
    assert store._IDLE_SESSION_REFUSED.is_set() is refused
    assert capsys.readouterr().err == (NOTICE if refused else "")


@pytest.mark.parametrize("platform", [False, True], ids=["local", "platform"])
def test_a_checkpoint_pool_reaches_a_server_that_refuses_the_option_without_it(
    empty_database: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    platform: bool,
) -> None:
    """The pool opens its own sessions (D117 round 2) and follows the same
    rule: its first session is let in without the option, the statement bound
    kept, the process says so once, and the next pooled session goes without
    it at the first try. A server that accepts it is covered by
    `tests/test_checkpoint.py::test_a_pooled_checkpoint_session_is_never_ended_for_being_idle`."""
    refuse_idle_session_option(empty_database)
    if platform:
        monkeypatch.setenv(lakebase.LAKEBASE_INSTANCE, "caos-lb")
        monkeypatch.setattr(checkpoint, "store_url", lambda: empty_database)
    sent: list[bool] = []
    real = vars(psycopg.Connection)["connect"].__func__

    def spy(cls: type[Any], /, conninfo: str = "", **kwargs: object) -> object:
        sent.append(store.IDLE_SESSION_OPTION in str(kwargs.get("options", "")))
        return real(cls, conninfo, **kwargs)

    monkeypatch.setattr(psycopg.Connection, "connect", classmethod(spy))
    saver = checkpoint.checkpointer(None if platform else empty_database)
    try:
        pool = getattr(saver, "conn", None)
        assert isinstance(pool, ConnectionPool)
        assert pool.connection_class is (
            checkpoint.MintedConnection if platform else checkpoint.PooledConnection
        )
        assert sent[0] and not all(sent), "asked with it, let in without it"
        assert capsys.readouterr().err == NOTICE
        sent.clear()
        with ExitStack() as held:
            # One more session than the pool holds, so it opens a new one.
            pooled = [
                held.enter_context(pool.connection())
                for _ in range(pool.get_stats().get("pool_size", 0) + 1)
            ]
            shown = [
                conn.execute(f"SHOW {name}").fetchone()
                for conn in pooled
                for name in ("idle_session_timeout", "statement_timeout")
            ]
    finally:
        checkpoint.close_checkpointer(saver)
    assert shown == [
        {"idle_session_timeout": "10min"},
        {"statement_timeout": "30s"},
    ] * len(pooled)
    assert sent and not any(sent), "a later session skips it at the first try"
    assert capsys.readouterr().err == "", "said once"

"""The worker on an analyst's PC (D79): console stop signals, the console close
event, a platform with no `resource` module, and the byte-verified trees checked
out unconverted. No Windows host runs these; the platform is simulated."""

from __future__ import annotations

import ctypes
import signal
import subprocess
import sys
import threading
from collections.abc import Callable
from threading import Event
from types import SimpleNamespace

import pytest

from caos.evidence import pdf
from caos.graph import worker
from caos.graph.worker import STOP_SIGNALS, install_stop_handler


def test_ctrl_c_only_asks_the_worker_to_stop() -> None:
    stopping = Event()
    previous = {stop: signal.getsignal(stop) for stop in STOP_SIGNALS}
    install_stop_handler(stopping)
    try:
        signal.raise_signal(signal.SIGINT)
        assert stopping.is_set()
    finally:
        for stop, handler in previous.items():
            signal.signal(stop, handler)


def test_every_stop_signal_the_platform_has_is_handled() -> None:
    assert signal.SIGTERM in STOP_SIGNALS
    assert signal.SIGINT in STOP_SIGNALS
    if sys.platform == "win32":
        assert signal.SIGBREAK in STOP_SIGNALS


class _Kernel:
    """`kernel32` as far as the worker uses it."""

    def __init__(self, accepts: bool = True) -> None:
        self.routine: Callable[[int], bool] | None = None

        def take(routine: Callable[[int], bool], add: int) -> int:
            assert add == 1
            self.routine = routine
            return 1 if accepts else 0

        self.SetConsoleCtrlHandler = take


def _windows(monkeypatch: pytest.MonkeyPatch, kernel: _Kernel) -> None:
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(
        ctypes, "windll", SimpleNamespace(kernel32=kernel), raising=False
    )
    monkeypatch.setattr(
        ctypes, "WINFUNCTYPE", lambda *_types: lambda fn: fn, raising=False
    )


def _install_on_windows(
    monkeypatch: pytest.MonkeyPatch, stopping: Event, kernel: _Kernel
) -> None:
    _windows(monkeypatch, kernel)
    monkeypatch.setattr(signal, "signal", lambda *_args: None)
    install_stop_handler(stopping)


def test_the_console_close_event_asks_for_the_same_stop_and_waits_to_drain(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stopping = Event()
    kernel = _Kernel()
    _install_on_windows(monkeypatch, stopping, kernel)
    routine = kernel.routine
    assert routine is not None
    monkeypatch.setattr(worker, "CLOSE_GRACE_SECONDS", 5.0)
    answered: list[bool] = []
    closing = threading.Thread(
        target=lambda: answered.append(routine(worker.CTRL_CLOSE_EVENT)),
    )
    closing.start()
    assert stopping.wait(2.0)
    closing.join(0.2)
    assert closing.is_alive()  # held until the lease is released, or the grace ends
    worker.DRAINED.set()
    closing.join(2.0)
    worker.DRAINED.clear()
    assert answered == [True]


def test_the_close_wait_is_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    stopping = Event()
    kernel = _Kernel()
    _install_on_windows(monkeypatch, stopping, kernel)
    assert kernel.routine is not None
    monkeypatch.setattr(worker, "CLOSE_GRACE_SECONDS", 0.05)
    assert kernel.routine(worker.CTRL_SHUTDOWN_EVENT) is True
    assert stopping.is_set()


def test_other_console_events_are_left_to_the_signals(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stopping = Event()
    kernel = _Kernel()
    _install_on_windows(monkeypatch, stopping, kernel)
    assert kernel.routine is not None
    assert kernel.routine(0) is False  # CTRL_C_EVENT: SIGINT already handles it
    assert not stopping.is_set()


def test_a_console_that_refuses_the_handler_is_said_and_not_fatal(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    stopping = Event()
    _install_on_windows(monkeypatch, stopping, _Kernel(accepts=False))
    assert worker.CONSOLE_CLOSE_UNHANDLED in capsys.readouterr().err


def test_a_platform_with_no_resource_module_still_extracts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(sys.modules, "resource", None)
    assert pdf._limit_address_space(pdf._Inflater(1024)) is False


def test_the_cap_is_applied_where_the_platform_has_one() -> None:
    assert pdf.address_space_cap_available() is (sys.platform != "win32")


def test_no_cap_is_said_once_and_the_deadline_still_binds(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setitem(sys.modules, "resource", None)
    monkeypatch.setattr(pdf, "_UNCAPPED_SAID", [False])
    with caplog.at_level("WARNING", logger=pdf.__name__):
        assert pdf.address_space_cap_available() is False
        assert pdf.address_space_cap_available() is False
    assert [r.message for r in caplog.records] == [pdf.UNCAPPED_NOTE]


@pytest.mark.parametrize(
    "path", ["vendor/deploy-v/CANON_SHARED.md", "icm/HOST_INTEGRITY_v1.json"]
)
def test_the_byte_verified_trees_are_never_converted(path: str) -> None:
    attributes = subprocess.run(
        ["git", "check-attr", "text", "--", path],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert attributes.strip() == f"{path}: text: unset"

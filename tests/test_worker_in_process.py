"""The API process runs the worker beside it only when told to (D11)."""

from __future__ import annotations

from pathlib import Path
from threading import Event

import pytest
from fake_chat import fake_completions
from langgraph.checkpoint.memory import MemorySaver

from caos.graph import worker
from caos.graph.worker import Configured, start_in_process
from caos.methodology.bundle import Bundle
from caos.refusals import Refusal, RefusalCode

VENDORED = Path(__file__).resolve().parents[1] / "vendor/deploy-v"


def test_nothing_starts_unless_the_environment_asks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(worker.IN_PROCESS, raising=False)
    monkeypatch.setattr(worker, "_configured", lambda: pytest.fail("not asked"))
    assert start_in_process(Event()) is None


def test_a_refused_configuration_is_printed_and_the_api_still_serves(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv(worker.IN_PROCESS, "1")
    monkeypatch.delenv(worker.MODEL_PRICE, raising=False)

    def refused() -> Configured:
        raise Refusal(RefusalCode.PROVIDER_NOT_CONFIGURED)

    monkeypatch.setattr(worker, "_configured", refused)
    thread = start_in_process(Event())
    assert thread is not None
    thread.join(timeout=5)
    assert not thread.is_alive(), "a refused configuration is not asked again"
    assert capsys.readouterr().err.strip() == (
        "PROVIDER_NOT_CONFIGURED CAOS_MODEL_PRICE unset"
    )


def test_a_configured_worker_runs_on_a_daemon_thread_until_stopped(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv(worker.IN_PROCESS, "1")
    seen: list[str] = []

    def configured() -> Configured:
        return Configured(
            completions=fake_completions(),
            url="postgresql://unused.invalid/none",
            root=str(tmp_path),
            bundle=Bundle(VENDORED),
            saver=MemorySaver(),
        )

    def run(configured_worker: Configured, stopping: Event) -> int:
        seen.append(configured_worker.url)
        stopping.wait(5)
        return 0

    monkeypatch.setattr(worker, "_configured", configured)
    monkeypatch.setattr(worker, "_worker", run)
    stopping = Event()
    thread = start_in_process(stopping)
    assert thread is not None and thread.daemon and thread.name == "caos-worker"
    stopping.set()
    thread.join(timeout=5)
    assert not thread.is_alive()
    assert seen == ["postgresql://unused.invalid/none"]


def test_a_store_that_cannot_answer_at_boot_is_asked_again_off_the_boot_path(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """MAX-20, ST-4: the worker was configured before uvicorn bound its port,
    so a checkpoint set-up waiting on the store held the deploy, and a
    transient failure returned None and left the process with no worker for
    its whole life. The thread configures itself now, under back-off."""
    import time

    import psycopg

    monkeypatch.setenv(worker.IN_PROCESS, "1")
    monkeypatch.setenv(worker.MODEL_PRICE, "set, so only the code is printed")
    monkeypatch.setattr(worker, "pause_seconds", lambda _config, _failures: 0.01)
    gate = Event()
    tries: list[str] = []

    def flaky() -> Configured:
        tries.append("try")
        if len(tries) == 1:
            gate.wait(5)  # the store is slow to answer at first boot
            raise Refusal(RefusalCode.STORE_UNAVAILABLE)
        if len(tries) == 2:
            raise psycopg.OperationalError
        return Configured(
            completions=fake_completions(),
            url="postgresql://unused.invalid/none",
            root=str(tmp_path),
            bundle=Bundle(VENDORED),
            saver=MemorySaver(),
        )

    ran = Event()

    def run(configured_worker: Configured, stopping: Event) -> int:
        ran.set()
        stopping.wait(5)
        return 0

    monkeypatch.setattr(worker, "_configured", flaky)
    monkeypatch.setattr(worker, "_worker", run)
    stopping = Event()
    started = time.monotonic()
    thread = start_in_process(stopping)
    assert time.monotonic() - started < 1.0, "boot never waits on the store"
    assert thread is not None
    gate.set()
    assert ran.wait(5), "configured on the third try"
    assert tries == ["try", "try", "try"]
    stopping.set()
    thread.join(timeout=5)
    assert not thread.is_alive()
    assert capsys.readouterr().err.split() == ["STORE_UNAVAILABLE"] * 2

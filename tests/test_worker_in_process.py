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
    assert start_in_process(Event()) is None
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

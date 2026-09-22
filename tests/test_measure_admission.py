"""scripts/measure_admission.py: not a gate, but its own logic is tested."""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path
from types import ModuleType

import pytest

REPO = Path(__file__).resolve().parents[1]
POSTGRES_URL = os.environ.get("CAOS_TEST_POSTGRES_URL")
POSTGRES_REQUIRED = os.environ.get("CAOS_REQUIRE_POSTGRES") == "1"
_UNSET = "CAOS_TEST_POSTGRES_URL is unset: no database to measure admission against"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "measure_admission", REPO / "scripts" / "measure_admission.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_document_is_whitespace_separated_words_over_bounded_lines() -> None:
    measure = _load()

    document = measure._document(tokens=20, per_line=5)

    lines = document.data.decode("utf-8").split("\n")
    assert len(lines) == 4
    assert lines[0] == "w000000 w000001 w000002 w000003 w000004"
    assert lines[-1] == "w000015 w000016 w000017 w000018 w000019"


def test_the_admin_url_replaces_only_the_database_name() -> None:
    measure = _load()

    assert (
        measure._admin_url("postgres://user@host:5432/postgres", "caos_measure_x")
        == "postgres://user@host:5432/caos_measure_x"
    )


def test_main_refuses_without_a_configured_test_database(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    measure = _load()
    monkeypatch.delenv("CAOS_TEST_POSTGRES_URL", raising=False)
    monkeypatch.setattr("sys.argv", ["measure_admission.py"])

    assert measure.main() == 2


def test_main_admits_a_synthetic_document_and_reports_its_timings(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    if POSTGRES_URL is None:
        if POSTGRES_REQUIRED:
            pytest.fail(_UNSET)
        pytest.skip(_UNSET)

    measure = _load()
    monkeypatch.setattr(
        "sys.argv", ["measure_admission.py", "--tokens", "20", "--per-line", "5"]
    )

    assert measure.main() == 0

    out = capsys.readouterr().out
    assert "tokens=20 lines=4" in out
    assert "extract=" in out and "write=" in out and "total=" in out

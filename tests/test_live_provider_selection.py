"""The live-provider suite is unreachable without an explicit pytest opt-in."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
STUB = REPO / "tests/live_provider_stub.py"
LIVE_ENV = {
    "OPENROUTER_API_KEY": "synthetic-not-a-secret",
    "CAOS_MODEL_PRICE": "synthetic/model,0.000001,0.000004,2026-09-15",
    "CAOS_LIVE_BUDGET_CEILING": "22.00",
    "CAOS_TEST_POSTGRES_URL": "postgresql://unused/unused",
    "CAOS_REQUIRE_PROVIDER": "1",
}


def _pytest(*args: str, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-o", "addopts=-q", *args],
        cwd=REPO,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )


def test_default_collection_is_offline_despite_inherited_configuration() -> None:
    result = _pytest(str(STUB), env={**os.environ, **LIVE_ENV})

    assert result.returncode == 5
    assert "1 deselected" in result.stdout
    assert "1 passed" not in result.stdout


def test_explicit_live_selection_reaches_a_harmless_stub() -> None:
    result = _pytest(str(STUB), "--live-provider", env={**os.environ, **LIVE_ENV})

    assert result.returncode == 0, result.stderr
    assert "1 passed" in result.stdout


def test_explicit_live_selection_fails_when_configuration_is_missing() -> None:
    env = os.environ.copy()
    for name in LIVE_ENV:
        env.pop(name, None)

    result = _pytest(str(STUB), "--live-provider", env=env)

    assert result.returncode != 0
    assert "OPENROUTER_API_KEY" in result.stderr
    assert "CAOS_MODEL_PRICE" in result.stderr
    assert "CAOS_LIVE_BUDGET_CEILING" in result.stderr
    assert "CAOS_TEST_POSTGRES_URL" in result.stderr

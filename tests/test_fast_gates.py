"""The local fast gates execute CI commands and stop at the first failure."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def test_fast_gates_stop_at_a_failure_and_include_guard_budgets(tmp_path: Path) -> None:
    binary = tmp_path / "uv"
    binary.write_text(
        '#!/bin/sh\nprintf "%s\\n" "$*" >> "$CAOS_GATE_LOG"\n'
        'if [ "$*" = "$CAOS_FAIL_COMMAND" ]; then exit 23; fi\n'
        'case "$*" in "run pytest"*) test "$CAOS_REQUIRE_POSTGRES" = 1;; esac\n'
    )
    binary.chmod(0o755)
    log = tmp_path / "calls"
    env = {
        **os.environ,
        "PATH": f"{tmp_path}:{os.environ['PATH']}",
        "CAOS_GATE_LOG": str(log),
        "CAOS_FAIL_COMMAND": "run python scripts/check_gate_config.py",
    }
    command = ["bash", str(REPO / "scripts/fast_gates.sh"), "767d292e"]
    stopped = subprocess.run(command, cwd=tmp_path, env=env, check=False)
    assert stopped.returncode == 23
    assert "run pytest" not in log.read_text()
    log.unlink()
    env["CAOS_FAIL_COMMAND"] = ""
    passed = subprocess.run(command, cwd=tmp_path, env=env, check=False)
    assert passed.returncode == 0
    calls = log.read_text()
    assert "lock --check" in calls
    assert "sync --locked --all-groups" in calls
    assert "run python scripts/check_gate_config.py --against 767d292e" in calls
    assert "run python scripts/check_pr_size.py 767d292e" in calls
    assert "run pytest --no-cov -n 0" in calls
    assert "tests/test_suppression_budget.py" in calls
    assert "tests/test_gate_structure.py" in calls
    assert "tests/test_wire_contract.py" in calls
    assert "tests/test_api_routes.py" in calls

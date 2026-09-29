"""`scripts/gitleaks_tree.sh`: the uncommitted-tree secret scan reads what git
would commit (F466), against a stand-in `gitleaks` that records what it was
given, so the test needs no scanner installed."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "gitleaks_tree.sh"
STAND_IN = """#!/bin/sh
{ pwd; echo "$*"; find . -type f | sort; } > "$STAND_IN_LOG"
exit "${STAND_IN_EXIT:-0}"
"""


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", *args],
        cwd=repo,
        check=True,
        capture_output=True,
    )


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """Tracked `kept.txt` and `gone.txt` (deleted on disk), untracked
    `fresh.txt`, and `local/` ignored."""
    root = tmp_path / "repo"
    (root / "local").mkdir(parents=True)
    _git(root, "init", "-q")
    (root / ".gitignore").write_text("local/\n")
    (root / "kept.txt").write_text("kept\n")
    (root / "gone.txt").write_text("gone\n")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "base")
    (root / "gone.txt").unlink()
    (root / "fresh.txt").write_text("fresh\n")
    (root / "local" / "ignored.txt").write_text("ignored\n")
    return root


def _run(repo: Path, tmp_path: Path, exit_code: int) -> tuple[int, list[str]]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    stand_in = bin_dir / "gitleaks"
    stand_in.write_text(STAND_IN)
    stand_in.chmod(0o755)
    log = tmp_path / "log"
    env = {
        **os.environ,
        "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
        "STAND_IN_LOG": str(log),
        "STAND_IN_EXIT": str(exit_code),
    }
    done = subprocess.run(
        ["bash", str(SCRIPT)],
        cwd=repo / "local",
        env=env,
        capture_output=True,
        check=False,
    )
    return done.returncode, log.read_text().splitlines()


def test_the_scan_reads_tracked_and_untracked_files_but_never_ignored_ones(
    repo: Path, tmp_path: Path
) -> None:
    code, seen = _run(repo, tmp_path, 0)
    scratch, args, files = seen[0], seen[1], seen[2:]
    assert code == 0
    assert args == "dir --no-banner --redact -v ."
    assert files == ["./.gitignore", "./fresh.txt", "./kept.txt"]
    assert Path(scratch) != repo
    assert not Path(scratch).exists()


def test_the_scan_exits_with_the_scanners_code(repo: Path, tmp_path: Path) -> None:
    code, _ = _run(repo, tmp_path, 1)
    assert code == 1

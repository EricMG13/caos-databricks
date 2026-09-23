"""The file set a gate scans: what we wrote, so a gate judges what we can change.

Shared by the vocabulary and untested-definition gates. `git ls-files` rather
than a tree walk, because .gitignore already answers "is this ours" and a walk
would re-answer it differently. Vendored trees are excluded: the methodology
bundle is authority we never edit (DECISIONS.md 6), so a vocabulary or coverage
finding inside it names something no PR is allowed to fix.

The one subprocess call in this repository: resolved executable, no shell,
and pathspecs that are constants in the gates that call it.
"""

from __future__ import annotations

import shutil
import subprocess  # nosec B404
from pathlib import Path

# Read-only upstream. Never edited, so never judged.
VENDOR = "vendor"


def tracked_files(repo: Path, *pathspecs: str) -> list[str]:
    """Repo-relative paths git tracks under `repo` that match `pathspecs`;
    `RuntimeError` when git is missing or cannot list them."""
    git = shutil.which("git")
    if git is None:
        message = "git is not on PATH; the gate cannot determine what a PR carries"
        raise RuntimeError(message)
    listed = subprocess.run(  # nosec B603
        [git, "ls-files", "-z", "--", *pathspecs],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )
    if listed.returncode != 0:
        message = "git could not list the tracked files; the gate cannot judge them"
        raise RuntimeError(message)
    return [name for name in listed.stdout.split("\0") if name]


def tracked_python(repo: Path) -> list[Path]:
    """Absolute paths of the .py files git tracks under `repo`."""
    listed_paths = (
        repo / name
        for name in tracked_files(repo, "*.py")
        if not name.startswith(f"{VENDOR}/")
    )
    return [path for path in listed_paths if _present(path)]


def _present(path: Path) -> bool:
    """True if the file is there. Any other filesystem error propagates.

    A tracked file can be absent mid-rebase or after an unstaged delete, and
    scanning what is not there is a crash rather than a finding. `Path.is_file`
    cannot express that distinction: on Python 3.14 it answers False for every
    OSError, so an unreadable file would leave the scan silently -- a gate that
    scanned less than it should, which is the failure `scan_floors.py` exists to
    catch at the other end.
    """
    try:
        path.stat()
    except FileNotFoundError:
        return False
    return True

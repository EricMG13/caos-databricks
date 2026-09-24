"""The file set a gate scans: what we wrote, so a gate judges what we can change.

Shared by the vocabulary and untested-definition gates. `git ls-files` rather
than a tree walk, because .gitignore already answers "is this ours" and a walk
would re-answer it differently. Vendored trees are excluded: the methodology
bundle is authority we never edit (DECISIONS.md 6), so a vocabulary or coverage
finding inside it names something no PR is allowed to fix.

The home for every call in this repository that shells to git: a resolved
executable, no shell, and pathspecs and revisions that are constants or
caller-supplied strings, never interpolated into a command line.
"""

from __future__ import annotations

import shutil
import subprocess  # nosec B404
from collections.abc import Sequence
from pathlib import Path

# Read-only upstream. Never edited, so never judged.
VENDOR = "vendor"


def _git(repo: Path, args: Sequence[str]) -> subprocess.CompletedProcess[str]:
    """One resolved, shell-less git invocation; every function below goes
    through it, so there is exactly one subprocess call site in this file to
    audit, whichever git subcommand a caller needs (`RuntimeError` when git
    is missing, never a silent empty result)."""
    git = shutil.which("git")
    if git is None:
        message = "git is not on PATH; the gate cannot determine what a PR carries"
        raise RuntimeError(message)
    return subprocess.run(  # nosec B603
        [git, *args], cwd=repo, capture_output=True, text=True, check=False
    )


def tracked_files(repo: Path, *pathspecs: str) -> list[str]:
    """Repo-relative paths git tracks under `repo` that match `pathspecs`;
    `RuntimeError` when git is missing or cannot list them."""
    listed = _git(repo, ("ls-files", "-z", "--", *pathspecs))
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


def tracked_python_at(repo: Path, rev: str) -> dict[str, str]:
    """The tracked .py files' own text as git recorded it at `rev`, by
    repo-relative path; vendor/ excluded. `RuntimeError` when git is
    missing or `rev` cannot be listed.

    Lets a gate re-measure an earlier commit's files under this commit's
    own rules (FP-11) without materialising a second working tree: plumbing
    calls against the one repository already on disk, rather than a
    `git worktree add` or a `git archive | tar -x` that would need its own
    cleanup.
    """
    # No pathspec: `ls-tree`, unlike `ls-files`, supports no glob magic ("*.py"
    # matched nothing), so `.py` is filtered in Python below instead.
    # `--end-of-options`: `rev` is a caller-supplied string (ultimately a PR's
    # `--against` argument); without it, a value shaped like an option (e.g.
    # "--upload-pack=...") could be read as one rather than as a revision.
    listed = _git(repo, ("ls-tree", "-r", "--name-only", "-z", "--end-of-options", rev))
    if listed.returncode != 0:
        message = (
            f"git could not list {rev}'s tracked files; the gate cannot judge them"
        )
        raise RuntimeError(message)
    names = [
        name
        for name in listed.stdout.split("\0")
        if name.endswith(".py") and not name.startswith(f"{VENDOR}/")
    ]
    texts: dict[str, str] = {}
    for name in names:
        blob = _git(repo, ("show", "--end-of-options", f"{rev}:{name}"))
        if blob.returncode == 0:
            texts[name] = blob.stdout
    return texts


def blob_at(repo: Path, rev: str, path: str) -> str | None:
    """One file's text as git recorded it at `rev`; `None` if `rev` never
    had it (a file the base commit predates, e.g. a snapshot added since)."""
    blob = _git(repo, ("show", "--end-of-options", f"{rev}:{path}"))
    return blob.stdout if blob.returncode == 0 else None


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

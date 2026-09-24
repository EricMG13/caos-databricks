"""A rollback is a redeploy only across no migration and no schema move (C1).

The runbook once said a rollback is always "check out the previous commit and
run the same one command": against the store a release had migrated, a
commit from before a migration refuses to start (`STORE_SCHEMA_DRIFT`), and
one from before DL-1 starts on an empty store in `public`. The check reads
both commits through git and names which of the two it would be.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
import rollback_check

STORE_MODULE = """\
from pathlib import Path

SCHEMA = (Path(__file__).with_name("schema.sql")).read_text(encoding="utf-8")
MIGRATIONS = (
    ("0001_legacy", SCHEMA),
    ("0002_extraction", Path(__file__).with_name("0002_extraction.sql").read_text()),
{extra})
{schema}
"""
ADDED = (
    '    ("0003_budget", Path(__file__).with_name("0003_budget.sql").read_text()),\n'
)
MOVED = 'STORE_SCHEMA = "caos_store"'


def _git(root: Path, *args: str) -> str:
    git = shutil.which("git")
    assert git is not None
    done = subprocess.run([git, *args], cwd=root, check=True, capture_output=True)
    return done.stdout.decode().strip()


def _commit(root: Path, files: dict[str, str], message: str) -> str:
    for name, text in files.items():
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_text(text, encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", message)
    return _git(root, "rev-parse", "HEAD")


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "test@example.invalid")
    _git(root, "config", "user.name", "Rollback test")
    return root


def _store(extra: str = "", schema: str = MOVED) -> dict[str, str]:
    return {
        "caos/store/__init__.py": STORE_MODULE.format(extra=extra, schema=schema),
        "caos/store/schema.sql": "CREATE TABLE cases (case_id uuid);\n",
        "caos/store/0002_extraction.sql": "ALTER TABLE cases ADD COLUMN x int;\n",
    }


def test_a_redeploy_across_no_migration_is_a_rollback(repo: Path) -> None:
    older = _commit(repo, {**_store(), "caos/serve.py": "a = 1\n"}, "older")
    release = _commit(repo, {"caos/serve.py": "a = 2\n"}, "release")
    layout = rollback_check.store_layout(release, repo)
    assert layout.schema == "caos_store"
    assert [name for name, _ in layout.migrations] == ["0001_legacy", "0002_extraction"]
    assert rollback_check.rollback_problems(older, release, repo) == []


def test_a_release_that_added_a_migration_cannot_be_rolled_back_by_redeploy(
    repo: Path,
) -> None:
    older = _commit(repo, _store(), "older")
    release = _commit(
        repo,
        {**_store(ADDED), "caos/store/0003_budget.sql": "CREATE TABLE b (x int);\n"},
        "release adds a migration",
    )
    assert rollback_check.rollback_problems(older, release, repo) == [
        f"{release} applied 0003_budget, which {older} does not carry: its app "
        "refuses the store (STORE_SCHEMA_DRIFT)"
    ]


def test_a_migration_whose_bytes_moved_is_not_the_same_history(repo: Path) -> None:
    older = _commit(repo, _store(), "older")
    release = _commit(
        repo,
        {"caos/store/0002_extraction.sql": "ALTER TABLE cases ADD COLUMN y int;\n"},
        "release edits an applied migration",
    )
    [problem] = rollback_check.rollback_problems(older, release, repo)
    assert "in order and byte for byte" in problem


def test_code_from_before_the_schema_move_is_never_a_rollback(repo: Path) -> None:
    """F219 (DL-1): the same migrations, but read from `public`, is an app
    that starts green on an empty store beside the real one."""
    older = _commit(repo, _store(schema=""), "before DL-1")
    release = _commit(repo, _store(), "DL-1")
    assert rollback_check.rollback_problems(older, release, repo) == [
        f"{older} reads the public schema, not caos_store: it would start on an "
        "empty store beside the release's (F219, DL-1)"
    ]


def test_an_unreadable_commit_is_refused_not_passed(repo: Path) -> None:
    release = _commit(repo, _store(), "release")
    missing = "not-a-commit has no caos/store/__init__.py (or is not a commit)"
    assert rollback_check.store_layout("not-a-commit", repo) == (
        rollback_check.StoreLayout("", (), missing)
    )
    assert rollback_check.rollback_problems("not-a-commit", release, repo) == [missing]
    computed = _commit(
        repo,
        {"caos/store/__init__.py": "MIGRATIONS = tuple(load())\n"},
        "a computed list",
    )
    assert rollback_check.rollback_problems(computed, release, repo) == [
        f"{computed}'s MIGRATIONS cannot be read"
    ]


def test_the_reviewed_rollback_targets_are_refused() -> None:
    """The two targets review 4 booted against a store HEAD had migrated:
    the commit before 0040 refused the store, and 84eb06d, from before DL-1,
    started on a new store in `public`."""
    assert rollback_check.rollback_problems("HEAD", "HEAD") == []
    [drift] = rollback_check.rollback_problems("b1c1c83^", "HEAD")
    assert "0040_hidden_painted_over" in drift and "STORE_SCHEMA_DRIFT" in drift
    moved = rollback_check.rollback_problems("84eb06d", "HEAD")
    assert moved[0].startswith("84eb06d reads the public schema, not caos_store")
    assert rollback_check.main(["HEAD"]) == 0
    assert rollback_check.main(["84eb06d"]) == 1

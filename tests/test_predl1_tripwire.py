"""N81: a build from before DL-1 (F219) refuses a post-DL-1 store at boot.

Code from before DL-1 reads `public` through Postgres's default search path
(`"$user", public`), finds no bookkeeping there and, left alone, boots on an
empty store beside the real one. Migration 0052 puts a bookkeeping row that
matches no history in the schema named for the app's own role, which that
default path searches first, so the old build finds a store it cannot account
for and answers `STORE_SCHEMA_DRIFT`. The old build here is the real one, read
from git at the commit before DL-1 and run in a process of its own.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import psycopg
from psycopg import sql

import caos.store as store
from caos.store import apply_schema, connect, verify_schema

REPO = Path(__file__).resolve().parents[1]
# The commit before DL-1 (F219, c443e7d8): the last build that reads `public`.
BEFORE_DL1 = "c443e7d8^"
TRIPWIRE = "0052_pre_dl1_tripwire"

OLD_BOOT = """\
import sys

sys.path.insert(0, sys.argv[1])
from caos.refusals import Refusal
from caos.store import apply_schema, connect

with connect(sys.argv[2]) as conn:
    try:
        apply_schema(conn)
    except Refusal as refused:
        print("REFUSED " + refused.code.name)
    else:
        print("BOOTED")
"""


def _old_build(tmp_path: Path) -> Path:
    git = shutil.which("git")
    assert git is not None
    root = tmp_path / "old"
    root.mkdir()
    archive = subprocess.run(
        [git, "archive", BEFORE_DL1, "caos"],
        cwd=REPO,
        check=True,
        capture_output=True,
    )
    subprocess.run(["tar", "-x", "-C", str(root)], input=archive.stdout, check=True)
    return root


def _boot_old_build(tmp_path: Path, url: str) -> str:
    done = subprocess.run(
        [sys.executable, "-I", "-c", OLD_BOOT, str(_old_build(tmp_path)), url],
        check=True,
        capture_output=True,
        text=True,
    )
    return done.stdout.strip()


def test_a_pre_dl1_build_refuses_a_store_the_current_build_migrated(
    empty_database: str, tmp_path: Path
) -> None:
    with connect(empty_database) as conn:
        apply_schema(conn)
        verify_schema(conn)
    assert _boot_old_build(tmp_path, empty_database) == "REFUSED STORE_SCHEMA_DRIFT"


def test_the_current_build_boots_again_over_its_own_tripwire(
    empty_database: str,
) -> None:
    assert store.MIGRATIONS[-1][0] == TRIPWIRE
    with connect(empty_database) as conn:
        apply_schema(conn)
    with connect(empty_database) as conn:
        apply_schema(conn)
        verify_schema(conn)
        role = conn.execute("SELECT current_user").fetchone()
        assert role is not None
        left = conn.execute(
            sql.SQL("SELECT count(*) FROM {}.store_schema").format(
                sql.Identifier(str(role[0]))
            )
        ).fetchone()
        assert left == (1,)
    with psycopg.connect(empty_database) as plain:
        assert plain.execute(
            "SELECT count(*) FROM pg_class c JOIN pg_namespace n"
            " ON n.oid = c.relnamespace WHERE n.nspname = 'public'"
        ).fetchone() == (0,)

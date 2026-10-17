"""N81: a build from before DL-1 (F219) refuses a post-DL-1 store at boot.

Code from before DL-1 reads `public` through Postgres's default search path
(`"$user", public`), finds no bookkeeping there and, left alone, boots on an
empty store beside the real one. Migration 0052 puts a bookkeeping row that
matches no history in the schema named for the app's own role, which that
default path searches first, so the old build finds a store it cannot account
for and answers `STORE_SCHEMA_DRIFT`. It matters where the old build can create in
`public` (a hand-granted CREATE, F141, or a dev volume); under the bundle grant
alone it is already refused. The old build here is the real one, read
from git at the commit before DL-1 and run in a process of its own.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import quote, urlsplit, urlunsplit
from uuid import uuid4

import psycopg
import pytest
from psycopg import sql

import caos.store as store
from caos.refusals import Refusal, RefusalCode
from caos.store import apply_schema, connect, verify_schema

REPO = Path(__file__).resolve().parents[1]
# The commit before DL-1 (F219, c443e7d8): the last build that reads `public`.
BEFORE_DL1 = "c443e7d8^"
TRIPWIRE = "0052_pre_dl1_tripwire"

OLD_BOOT = """\
import sys

sys.path.insert(0, sys.argv[1])
from caos.refusals import Refusal
from caos.refusals import Refusal, RefusalCode
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


def _fresh_role() -> str:
    """A role name of a UUID's shape: hyphens, so it needs quoting."""
    return str(uuid4())


@contextmanager
def _roles(
    database_url: str, *names: str, public_create: bool = False
) -> Iterator[dict[str, str]]:
    """Non-superuser login roles holding what the bundle's `CAN_CONNECT_AND_CREATE`
    gives (CONNECT and CREATE on the database), `CREATE` on `public` besides
    when `public_create` (F141's hand grant); their URLs by name."""
    parts = urlsplit(database_url)
    database = parts.path.lstrip("/")
    password = uuid4().hex
    urls = {
        name: urlunsplit(
            parts._replace(
                netloc=f"{quote(name, safe='')}:{password}"
                f"@{parts.hostname}:{parts.port}"
            )
        )
        for name in names
    }
    with psycopg.connect(database_url, autocommit=True) as admin:
        for name in names:
            role = sql.Identifier(name)
            admin.execute(
                sql.SQL("CREATE ROLE {} LOGIN PASSWORD {}").format(
                    role, sql.Literal(password)
                )
            )
            admin.execute(
                sql.SQL("GRANT CONNECT, CREATE ON DATABASE {} TO {}").format(
                    sql.Identifier(database), role
                )
            )
        if public_create:
            admin.execute(
                sql.SQL("GRANT CREATE ON SCHEMA public TO {}").format(
                    sql.Identifier(names[0])
                )
            )
    try:
        yield urls
    finally:
        with psycopg.connect(database_url, autocommit=True) as admin:
            for name in names:
                admin.execute(
                    sql.SQL("DROP OWNED BY {} CASCADE").format(sql.Identifier(name))
                )


def test_a_pre_dl1_build_refuses_a_store_the_current_build_migrated(
    empty_database: str, tmp_path: Path
) -> None:
    """Where the old build can create in `public` (a hand-granted CREATE, F141,
    or a dev volume) it would otherwise boot on an empty store; under the
    bundle grant alone it is already refused (42501) and this adds nothing."""
    app_role = _fresh_role()
    with _roles(empty_database, app_role, public_create=True) as urls:
        with connect(urls[app_role]) as conn:
            apply_schema(conn)
            verify_schema(conn)
        booted = _boot_old_build(tmp_path, urls[app_role])
    assert booted == "REFUSED STORE_SCHEMA_DRIFT"


def test_a_squatted_role_schema_is_refused_and_its_trigger_never_runs(
    empty_database: str, capsys: pytest.CaptureFixture[str]
) -> None:
    """W2: the role's name is public, so a co-tenant may make its schema first
    with a trigger on `store_schema`. The migration refuses before the INSERT
    that would run it as the app (the trigger's own SQLSTATE never appears)."""
    app_role, other = _fresh_role(), _fresh_role()
    with _roles(empty_database, app_role, other) as urls:
        with psycopg.connect(urls[other], autocommit=True) as squatter:
            app = sql.Identifier(app_role)
            squatter.execute(sql.SQL("CREATE SCHEMA {}").format(app))
            squatter.execute(
                sql.SQL("GRANT USAGE, CREATE ON SCHEMA {} TO {}").format(app, app)
            )
            squatter.execute(
                sql.SQL(
                    "CREATE TABLE {}.store_schema (only_row boolean PRIMARY KEY"
                    " DEFAULT true CHECK (only_row), applied_digest text NOT NULL)"
                ).format(app)
            )
            squatter.execute(
                sql.SQL("GRANT SELECT, INSERT, UPDATE ON {}.store_schema TO {}").format(
                    app, app
                )
            )
            squatter.execute(
                sql.SQL(
                    "CREATE FUNCTION {}.t() RETURNS trigger LANGUAGE plpgsql AS"
                    " $f$ BEGIN RAISE EXCEPTION 'squatter ran' USING ERRCODE ="
                    " 'ZZ001'; END $f$"
                ).format(app)
            )
            squatter.execute(
                sql.SQL(
                    "CREATE TRIGGER t BEFORE INSERT ON {}.store_schema"
                    " FOR EACH ROW EXECUTE FUNCTION {}.t()"
                ).format(app, app)
            )
        with connect(urls[app_role]) as conn:
            with pytest.raises(Refusal) as refused:
                apply_schema(conn)
    assert refused.value.code is RefusalCode.STORE_SCHEMA_DRIFT
    assert "sqlstate 23000" in capsys.readouterr().err


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


def _rows_written(admin_url: str, role: str) -> int:
    """How many rows the tripwire left in the role's schema, 0 when none."""
    with psycopg.connect(admin_url, autocommit=True) as admin:
        table = f'"{role}".store_schema'
        if admin.execute("SELECT to_regclass(%s)", (table,)).fetchone() == (None,):
            return 0
        row = admin.execute(
            sql.SQL("SELECT count(*) FROM {}.store_schema").format(sql.Identifier(role))
        ).fetchone()
        assert row is not None
        return int(row[0])


@pytest.mark.parametrize(
    "who, grant, premade_table",
    [
        ("squatter", False, False),
        ("squatter", True, False),
        ("squatter", True, True),
        ("app", False, False),
    ],
    ids=["bare-schema", "granted-schema", "granted-schema-and-table", "app-owned-open"],
)
def test_a_role_schema_another_role_can_reach_is_refused_and_nothing_is_written(
    empty_database: str, who: str, grant: bool, premade_table: bool
) -> None:
    """The schema exists before the migration (the gap the create-then-check
    order closes: the check reads what exists after `CREATE ... IF NOT EXISTS`,
    in the migration's own transaction). It is refused and no row is written:
    a schema a co-tenant made, bare or granted to the app, with or without a
    table of its own; and one the app owns in which another role holds CREATE."""
    app_role, other = _fresh_role(), _fresh_role()
    with _roles(empty_database, app_role, other) as urls:
        app = sql.Identifier(app_role)
        maker = urls[other] if who == "squatter" else urls[app_role]
        with psycopg.connect(maker, autocommit=True) as made:
            made.execute(sql.SQL("CREATE SCHEMA {}").format(app))
            if who == "app":
                made.execute(
                    sql.SQL("GRANT CREATE ON SCHEMA {} TO {}").format(
                        app, sql.Identifier(other)
                    )
                )
            if grant:
                made.execute(
                    sql.SQL("GRANT USAGE, CREATE ON SCHEMA {} TO {}").format(app, app)
                )
            if premade_table:
                made.execute(
                    sql.SQL(
                        "CREATE TABLE {}.store_schema (only_row boolean PRIMARY KEY"
                        " DEFAULT true CHECK (only_row), applied_digest text NOT NULL)"
                    ).format(app)
                )
                made.execute(
                    sql.SQL("GRANT ALL ON {}.store_schema TO {}").format(app, app)
                )
        with connect(urls[app_role]) as conn:
            with pytest.raises(Refusal) as refused:
                apply_schema(conn)
        assert refused.value.code is RefusalCode.STORE_SCHEMA_DRIFT
        assert _rows_written(empty_database, app_role) == 0


def test_a_clean_schema_the_app_role_already_owns_still_boots(
    empty_database: str, tmp_path: Path
) -> None:
    """A dev role that made its own schema of that name: adopted, and the old
    build still refuses the store."""
    app_role = _fresh_role()
    with _roles(empty_database, app_role, public_create=True) as urls:
        with psycopg.connect(urls[app_role], autocommit=True) as mine:
            mine.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(app_role)))
        with connect(urls[app_role]) as conn:
            apply_schema(conn)
            verify_schema(conn)
        assert _rows_written(empty_database, app_role) == 1
        assert _boot_old_build(tmp_path, urls[app_role]) == "REFUSED STORE_SCHEMA_DRIFT"

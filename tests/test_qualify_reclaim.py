"""`scripts/qualify_reclaim.py`: which harness databases a capture holds (F521).

Live run R6 (5 October 2026) stopped `STORE_UNAVAILABLE` when the Docker VM's
disk filled; 27 `caos_qualify_*` databases, 2.2 GB, were kept on the server and
nothing reclaims them. The script only lists: a database is offered for
dropping when it holds runs and a capture names every one, and nothing is ever
dropped by it.
"""

from __future__ import annotations

import json
import os
import sys
from collections.abc import Iterator
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest

from caos.boundary_text import BoundaryText
from caos.store import apply_schema, connect
from caos.store.runs import create_case, start_run

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import qualify
import qualify_reclaim
from qualify_reclaim import (
    RunDatabase,
    captured_run_ids,
    drop_statement,
    main,
    reclaimable,
    run_databases,
)


def test_captured_run_ids_reads_only_capture_documents(tmp_path: Path) -> None:
    (tmp_path / "R1.json").write_text(json.dumps({"run_ids": ["a", "b", 3]}))
    (tmp_path / "R2.json").write_text("{ not json")
    (tmp_path / "R3.json").write_text(json.dumps(["a list", "not a capture"]))
    (tmp_path / "R4.log").write_text(json.dumps({"run_ids": ["c"]}))
    assert captured_run_ids([tmp_path]) == {"a", "b"}


def test_reclaimable_needs_runs_and_every_run_captured() -> None:
    whole = RunDatabase("caos_qualify_" + "a" * 32, 10, frozenset({"r1", "r2"}))
    partial = RunDatabase("caos_qualify_" + "b" * 32, 20, frozenset({"r1", "r3"}))
    empty = RunDatabase("caos_qualify_" + "c" * 32, 30, frozenset())
    assert reclaimable([whole, partial, empty], frozenset({"r1", "r2"})) == [whole]


def test_drop_statement_is_only_for_a_name_the_harness_mints() -> None:
    minted = RunDatabase("caos_qualify_" + "d" * 32, 1, frozenset({"r"}))
    assert drop_statement(minted) == f'DROP DATABASE "{minted.name}";'
    with pytest.raises(ValueError):
        drop_statement(RunDatabase('caos_qualify_x"; DROP', 1, frozenset({"r"})))


@pytest.fixture
def server() -> Iterator[tuple[str, list[str]]]:
    """The test server's admin URL, and the harness databases made on it,
    dropped after the test."""
    url = os.environ.get("CAOS_TEST_POSTGRES_URL")
    if url is None:
        reason = "CAOS_TEST_POSTGRES_URL is unset"
        if os.environ.get("CAOS_REQUIRE_POSTGRES") == "1":
            pytest.fail(reason)
        pytest.skip(reason)
    made: list[str] = []
    try:
        yield url, made
    finally:
        with psycopg.connect(url, autocommit=True) as admin:
            for name in made:
                admin.execute(
                    psycopg.sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(
                        psycopg.sql.Identifier(name)
                    )
                )


def test_main_offers_only_a_captured_database_and_drops_none(
    server: tuple[str, list[str]],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    admin_url, made = server
    held, held_url = qualify._create_database(admin_url)
    made.append(held)
    bare, _ = qualify._create_database(admin_url)
    made.append(bare)
    # The script lists the names the harness mints, and these are two.
    assert qualify_reclaim.RUN_DATABASE.fullmatch(held)
    with connect(held_url) as conn:
        apply_schema(conn)
        run = start_run(conn, create_case(conn, BoundaryText.of("Reclaim case")))
        conn.commit()
    (tmp_path / "capture.json").write_text(json.dumps({"run_ids": [str(run)]}))
    monkeypatch.setenv("CAOS_QUALIFY_POSTGRES_URL", admin_url)

    assert main([str(tmp_path)]) == 0

    report = json.loads(capsys.readouterr().out)
    listed = {db["database"]: db for db in report["databases"]}
    assert listed[held]["runs"] == [str(run)] and listed[held]["captured"]
    assert listed[bare]["runs"] == [] and not listed[bare]["captured"]
    assert f'DROP DATABASE "{held}";' in report["statements"]
    assert all(bare not in statement for statement in report["statements"])
    still = {db.name for db in run_databases(admin_url)}
    assert {held, bare} <= still


def test_main_refuses_without_a_server_and_names_only_the_code(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.delenv("CAOS_QUALIFY_POSTGRES_URL", raising=False)
    assert main([str(tmp_path)]) == 2
    secret = uuid4().hex
    monkeypatch.setenv(
        "CAOS_QUALIFY_POSTGRES_URL", f"postgresql://u:{secret}%zz@127.0.0.1:1/x"
    )
    assert main([str(tmp_path)]) == 2
    err = capsys.readouterr().err
    assert "STORE_UNAVAILABLE" in err and secret not in err

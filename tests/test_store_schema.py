"""Phase 1: the store applies the schema it declares, and says so when it cannot.

`docs/REBUILD_PLAN.md` Phase 1 asks for the Postgres schema "in full at startup".
The failure that phrasing invites is `CREATE TABLE IF NOT EXISTS` over a database
an older build created: every statement succeeds, the missing column is never
mentioned, and the first write to it fails in production instead of at boot. So
startup records which declared schema it applied and refuses a database that was
built from a different one.

Invariants protected: `SYSTEM_SPEC.md` section 2 -- PostgreSQL owns everything
transactional, and what it owns is the declared shape rather than whatever the
first deployment happened to create.
"""

from __future__ import annotations

from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from decimal import Decimal
from hashlib import sha256
from pathlib import Path
from threading import Barrier, Event
from typing import cast
from uuid import UUID, uuid4

import psycopg
import pytest
from conftest import _checked_values
from test_case_ordering import _blocked, _wait_for_blocking
from test_extraction_provenance import Reader
from test_run_inputs import Prepared, _prepare, pin_version_one

import caos.store as store
from caos.blobs import BlobStore
from caos.boundary_text import BoundaryText
from caos.evidence.extract import Extractor, ExtractorIdentity, Token
from caos.evidence.ingest import Document, admit_pack
from caos.evidence.read import read_block
from caos.refusals import Refusal, RefusalCode
from caos.store import SCHEMA, RunStatus, StoreConnection, apply_schema, connect
from caos.store.routes import resolved_route
from caos.store.run_inputs import RunInput, load_run_input
from caos.store.runs import block_run, create_case, run_status, start_run

# A declared schema that differs from the repository's by one table -- the shape
# a later build has when it adds one, and the shape `IF NOT EXISTS` hides.
DRIFTED = SCHEMA + "\nCREATE TABLE a_later_build_added_this (case_id uuid);\n"


def _columns(conn: StoreConnection) -> list[tuple[object, ...]]:
    """Every column of every table in the connection's own namespace."""
    with conn.cursor() as cursor:
        cursor.execute(
            "SELECT table_name, column_name, data_type, is_nullable"
            " FROM information_schema.columns"
            " WHERE table_schema = current_schema()"
            " ORDER BY table_name, column_name"
        )
        return cursor.fetchall()


def _catalog(conn: StoreConnection) -> list[object]:
    """Compare native definitions, normalizing only each owned schema's name."""
    schema = conn.execute("SELECT current_schema()").fetchone()
    assert schema is not None
    queries = (
        "SELECT table_name,column_name,column_default,is_identity,is_generated"
        " FROM information_schema.columns WHERE table_schema=current_schema()"
        " ORDER BY table_name,ordinal_position",
        "SELECT c.relname,k.conname,k.contype,k.condeferrable,k.condeferred,"
        " k.convalidated,pg_get_constraintdef(k.oid) FROM pg_constraint k"
        " JOIN pg_class c ON c.oid=k.conrelid"
        " WHERE c.relnamespace=current_schema()::regnamespace"
        " ORDER BY c.relname,k.conname",
        "SELECT tablename,indexname,indexdef FROM pg_indexes"
        " WHERE schemaname=current_schema() ORDER BY tablename,indexname",
        "SELECT c.relname,t.tgname,t.tgenabled,pg_get_triggerdef(t.oid)"
        " FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid"
        " WHERE c.relnamespace=current_schema()::regnamespace AND NOT t.tgisinternal"
        " ORDER BY c.relname,t.tgname",
        "SELECT proname,pg_get_functiondef(oid) FROM pg_proc"
        " WHERE pronamespace=current_schema()::regnamespace ORDER BY proname",
        "SELECT table_name,view_definition FROM information_schema.views"
        " WHERE table_schema=current_schema() ORDER BY table_name",
    )
    return [
        [
            tuple(
                value.replace(schema[0] + ".", "<schema>.")
                if isinstance(value, str)
                else value
                for value in row
            )
            for row in conn.execute(query).fetchall()
        ]
        for query in queries
    ]


def test_the_declared_schema_holds_a_case_and_its_run(empty_database: str) -> None:
    with connect(empty_database) as conn:
        apply_schema(conn)
        case_id = create_case(conn, BoundaryText.of("Acme 2026 refinancing"))
        run_id = start_run(conn, case_id)
        conn.commit()

        assert run_status(conn, run_id) is RunStatus.RUNNING


def test_a_runs_predecessor_is_written_once_and_is_never_itself(
    empty_database: str,
) -> None:
    """`0025_supersedes` (§72): the link is written by the insert that makes
    the successor and by nothing after it. An UPDATE that would move it -- to
    another run, to null, or from null onto a run -- is refused by trigger, so
    a privileged edit cannot re-point which run a run answers; and a run can
    never name itself. Every refusal leaves the link exactly as the insert
    wrote it."""
    with connect(empty_database) as conn:
        apply_schema(conn)
        case_id = create_case(conn, BoundaryText.of("Acme 2026 refinancing"))
        first, other = start_run(conn, case_id), start_run(conn, case_id)
        conn.commit()
        assert block_run(conn, first) and block_run(conn, other)
        successor = start_run(conn, case_id, supersedes=first)
        conn.commit()

        moves = [
            (
                "UPDATE runs SET supersedes_run_id = %s WHERE run_id = %s",
                (other, successor),
            ),
            (
                "UPDATE runs SET supersedes_run_id = NULL WHERE run_id = %s",
                (successor,),
            ),
            (
                "UPDATE runs SET supersedes_run_id = %s WHERE run_id = %s",
                (other, first),
            ),
        ]
        for statement, params in moves:
            with pytest.raises(psycopg.errors.RaiseException):
                conn.execute(statement, params)
            conn.rollback()
        with pytest.raises(psycopg.errors.CheckViolation):
            own = uuid4()
            conn.execute(
                "INSERT INTO runs (run_id, case_id, status, budget_ceiling,"
                " supersedes_run_id) VALUES (%s, %s, 'RUNNING', 1, %s)",
                (own, case_id, own),
            )
        conn.rollback()

        links = conn.execute(
            "SELECT run_id, supersedes_run_id FROM runs WHERE supersedes_run_id"
            " IS NOT NULL"
        ).fetchall()
        assert links == [(successor, first)]


def test_every_run_status_is_one_the_database_accepts(empty_database: str) -> None:
    """`RunStatus` and the `runs_status_is_known` CHECK are two spellings of one
    closed set, checked in both directions (CF-106): the INSERT loop below
    only catches a Python status the database refuses, so a status the CHECK
    still names after `RunStatus` dropped it would pass unnoticed without the
    equality assertion first."""
    with connect(empty_database) as conn:
        apply_schema(conn)
        assert _checked_values(conn, "runs", "runs_status_is_known") == {
            status.value for status in RunStatus
        }
        case_id = create_case(conn, BoundaryText.of("Acme 2026 refinancing"))

        for status in RunStatus:
            conn.execute(
                "INSERT INTO runs (run_id, case_id, status, budget_ceiling)"
                " VALUES (%s, %s, %s, %s)",
                (uuid4(), case_id, status.value, Decimal("1.00")),
            )
        conn.commit()


def test_applying_the_declared_schema_twice_changes_nothing(
    empty_database: str,
) -> None:
    with connect(empty_database) as conn:
        apply_schema(conn)
        after_first = _columns(conn)

        apply_schema(conn)

        assert _columns(conn) == after_first


def test_a_database_built_from_another_schema_is_refused(empty_database: str) -> None:
    with connect(empty_database) as conn:
        apply_schema(conn)

        with pytest.raises(Refusal) as caught:
            apply_schema(conn, sql=DRIFTED)

        assert caught.value.code is RefusalCode.STORE_SCHEMA_DRIFT


def test_an_autocommit_connection_is_refused_rather_than_half_applied(
    empty_database: str,
) -> None:
    """Everything `apply_schema` promises is a property of one transaction.

    Under autocommit the advisory lock is taken and released by its own
    statement, so two processes starting at once both apply; and the DDL commits
    separately from the digest that records it, so a crash between them leaves a
    database whose tables exist and whose bookkeeping says they do not -- which
    the next startup answers by applying the schema again, onto tables that are
    already there. The mode is refused rather than supported.
    """
    with psycopg.connect(empty_database, autocommit=True) as conn:
        with pytest.raises(Refusal) as caught:
            apply_schema(conn)

        assert caught.value.code is RefusalCode.STORE_NOT_TRANSACTIONAL

    with connect(empty_database) as conn:
        assert _columns(conn) == [], "a refused apply must leave nothing behind"


def test_the_drift_refusal_carries_no_schema_text(empty_database: str) -> None:
    """The refusal names the code and nothing else -- a schema body in a log line
    is the vendor and filesystem detail `caos/refusals.py` exists to keep out."""
    with connect(empty_database) as conn:
        apply_schema(conn)

        with pytest.raises(Refusal) as caught:
            apply_schema(conn, sql=DRIFTED)

        assert str(caught.value) == RefusalCode.STORE_SCHEMA_DRIFT.value
        assert "a_later_build_added_this" not in repr(caught.value)


def _legacy(conn: StoreConnection) -> None:
    conn.execute(SCHEMA)
    conn.execute(store._BOOKKEEPING)
    conn.execute(
        "INSERT INTO store_schema (applied_digest) VALUES (%s)",
        (sha256(SCHEMA.encode()).hexdigest(),),
    )
    conn.commit()


def _populate(conn: StoreConnection, blobs: BlobStore) -> str:
    """Synthetic legacy records spanning evidence, route, audit and billing."""
    digest = blobs.put(b"synthetic legacy document and artifact")
    case_id = create_case(conn, BoundaryText.of("legacy evidence"))
    run_id = start_run(conn, case_id)
    attempt_id, source_id = uuid4(), uuid4()
    conn.execute(
        "INSERT INTO sources (source_id, case_id, document_sha256, filename)"
        " VALUES (%s, %s, %s, 'synthetic.txt')",
        (source_id, case_id, digest),
    )
    conn.execute(
        "INSERT INTO source_blocks VALUES (%s, 'b000000', 1, 'synthetic')", (source_id,)
    )
    conn.execute(
        "INSERT INTO source_tokens VALUES (%s, 0, 1, 0, 0, 'synthetic', 1, 2, 3, 4)",
        (source_id,),
    )
    conn.execute(
        "INSERT INTO run_attempts (attempt_id, run_id, route_node_id)"
        " VALUES (%s, %s, 'CP-DR')",
        (attempt_id, run_id),
    )
    conn.execute(
        "INSERT INTO artifacts"
        " (attempt_id, artifact_sha256, run_id, case_id, model, generation_id)"
        " VALUES (%s, %s, %s, %s, 'synthetic', 'synthetic')",
        (attempt_id, digest, run_id, case_id),
    )
    conn.execute(
        "INSERT INTO budget_ledger (attempt_id, run_id, amount) VALUES (%s, %s, 0.25)",
        (attempt_id, run_id),
    )
    # The price columns arrive with `0024_reservation_price`, and this helper
    # populates both a legacy database (before them) and a migrated one (after,
    # where they are NOT NULL with no default). Name them when they exist.
    priced = conn.execute(
        "SELECT 1 FROM information_schema.columns WHERE table_name ="
        " 'budget_reservations' AND column_name = 'price_model'"
    ).fetchone()
    if priced is None:
        conn.execute(
            "INSERT INTO budget_reservations (attempt_id, run_id, amount)"
            " VALUES (%s, %s, 0.50)",
            (attempt_id, run_id),
        )
    else:
        conn.execute(
            "INSERT INTO budget_reservations (attempt_id, run_id, amount,"
            " price_model, price_input, price_output, price_as_of)"
            " VALUES (%s, %s, 0.50, 'synthetic/model', 0, 0.000002, '2026-09-17')",
            (attempt_id, run_id),
        )
    conn.execute(
        "INSERT INTO run_routes"
        " (run_id, profile_id, selection_id, route_digest, resolved)"
        " VALUES (%s, 'synthetic', 'synthetic', %s, '{}')",
        (run_id, digest),
    )
    conn.execute(
        "INSERT INTO run_events (run_id, seq, name) VALUES (%s, 1, 'ROUTE_PINNED')",
        (run_id,),
    )
    conn.execute(
        "INSERT INTO audit_events"
        " (case_id, seq, actor_id, action, payload_sha256,"
        " previous_sha256, entry_sha256)"
        " VALUES (%s, 1, %s, 'synthetic', %s, %s, %s)",
        (case_id, uuid4(), digest, digest, digest),
    )
    conn.commit()
    return digest


def _records(
    conn: StoreConnection, columns: list[tuple[object, ...]] | None = None
) -> dict[str, object]:
    """Compare the original named tables/columns, including all their rows."""
    tables: dict[str, list[str]] = {}
    for table, column, *_ in _columns(conn) if columns is None else columns:
        if table not in {"store_schema", "store_migrations"}:
            tables.setdefault(str(table), []).append(str(column))
    return {
        table: conn.execute(
            psycopg.sql.SQL("SELECT {} FROM {} ORDER BY {}").format(
                psycopg.sql.SQL(", ").join(map(psycopg.sql.Identifier, names)),
                psycopg.sql.Identifier(table),
                psycopg.sql.SQL(", ").join(map(psycopg.sql.Identifier, names)),
            )
        ).fetchall()
        for table, names in tables.items()
    }


def test_real_legacy_upgrade_preserves_evidence_with_unknown_provenance(
    empty_database: str,
    tmp_path: Path,
) -> None:
    with connect(empty_database) as conn:
        _legacy(conn)
        blobs = BlobStore(tmp_path)
        digest = _populate(conn, blobs)
        columns = _columns(conn)
        before = _records(conn, columns)
        apply_schema(conn)
        assert _records(conn, columns) == before
        assert conn.execute("SELECT count(*) FROM source_extractions").fetchone() == (
            0,
        )
        row = conn.execute("SELECT source_id, case_id FROM sources").fetchone()
        assert row is not None
        source, case_id = row
        assert (
            read_block(conn, source_id=source, block_id="b000000").text.value
            == "synthetic"
        )
        assert blobs.get(digest) == b"synthetic legacy document and artifact"
        upgraded = _columns(conn)
        catalog = _catalog(conn)
        apply_schema(conn)
        assert _records(conn, columns) == before
        [new_source] = admit_pack(
            conn,
            blobs,
            case_id=case_id,
            documents=[Document(BoundaryText.of("new.txt"), b"known extraction")],
        )
        assert conn.execute("SELECT source_id FROM source_extractions").fetchall() == [
            (new_source,)
        ]
        conn.commit()
        conn.execute("CREATE SCHEMA real_fresh")
        conn.execute("SET search_path TO real_fresh")
        apply_schema(conn)
        assert _columns(conn) == upgraded
        assert _catalog(conn) == catalog


@pytest.mark.parametrize("prefix", [2, 3, 4, 5, 6, 7])
def test_real_extraction_upgrade_preserves_known_and_unknown_rows(
    empty_database: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, prefix: int
) -> None:
    with connect(empty_database) as conn:
        with monkeypatch.context() as patch:
            patch.setattr(store, "MIGRATIONS", store.MIGRATIONS[:prefix])
            apply_schema(conn)
        blobs = BlobStore(tmp_path)
        digest = _populate(conn, blobs)
        case_id = conn.execute("SELECT case_id FROM cases LIMIT 1").fetchone()
        assert case_id is not None
        admit_pack(
            conn,
            blobs,
            case_id=case_id[0],
            documents=[Document(BoundaryText.of("known.txt"), b"known")],
        )
        conn.commit()
        columns, before = _columns(conn), _records(conn)
        apply_schema(conn)
        assert _records(conn, columns) == before
        apply_schema(conn)
        assert _records(conn, columns) == before
        assert conn.execute("SELECT count(*) FROM run_inputs").fetchone() == (0,)
        assert conn.execute("SELECT count(*) FROM call_outcomes").fetchone() == (0,)
        assert blobs.get(digest) == b"synthetic legacy document and artifact"

        [run] = conn.execute("SELECT run_id FROM runs").fetchone() or ()
        with pytest.raises(Refusal, match=r"^ROUTE_IDENTITY_INVALID$"):
            resolved_route(conn, run)


def test_populated_legacy_advances_and_repeat_preserves_history(
    empty_database: str,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    with connect(empty_database) as conn:
        _legacy(conn)
        blobs = BlobStore(tmp_path)
        digest = _populate(conn, blobs)
        columns = _columns(conn)
        before = _records(conn, columns)
        conn.commit()
        monkeypatch.setattr(
            store,
            "MIGRATIONS",
            (
                ("0001_legacy", SCHEMA),
                (
                    "0002_probe",
                    "ALTER TABLE cases ADD COLUMN migration_probe integer DEFAULT 7",
                ),
            ),
        )
        apply_schema(conn)
        assert conn.execute("SELECT migration_probe FROM cases").fetchone() == (7,)
        assert _records(conn, columns) == before
        assert blobs.get(digest) == b"synthetic legacy document and artifact"
        history = conn.execute(
            "SELECT * FROM store_migrations ORDER BY version"
        ).fetchall()
        assert len(history) == 2
        apply_schema(conn)
        assert (
            conn.execute("SELECT * FROM store_migrations ORDER BY version").fetchall()
            == history
        )
        upgraded_columns = _columns(conn)
        conn.execute("CREATE SCHEMA fresh_equivalence")
        conn.execute("SET search_path TO fresh_equivalence")
        apply_schema(conn)
        assert _columns(conn) == upgraded_columns
        assert conn.execute(
            "SELECT version, name, digest FROM store_migrations ORDER BY version"
        ).fetchall() == [row[:3] for row in history]


@pytest.mark.parametrize(
    "tamper",
    [
        "UPDATE store_migrations SET digest = 'edited' WHERE version = 1",
        "UPDATE store_migrations SET name = 'unknown' WHERE version = 1",
        "UPDATE store_migrations SET version ="
        " (SELECT max(version) + 1 FROM store_migrations) WHERE version = 1",
        "DELETE FROM store_migrations",
        "DROP TABLE store_migrations",
        "DELETE FROM store_schema",
        "UPDATE store_schema SET applied_digest = 'invalid'",
    ],
)
def test_migration_history_tampering_refuses(empty_database: str, tamper: str) -> None:
    with connect(empty_database) as conn:
        apply_schema(conn)
        conn.execute(tamper)
        conn.commit()
        with pytest.raises(Refusal) as caught:
            apply_schema(conn)
        assert str(caught.value) == RefusalCode.STORE_SCHEMA_DRIFT.value
        assert conn.info.transaction_status is psycopg.pq.TransactionStatus.IDLE


@pytest.mark.parametrize("state", ["fresh", "legacy", "versioned"])
def test_failed_migration_rolls_back_and_releases_lock(
    empty_database: str,
    monkeypatch: pytest.MonkeyPatch,
    state: str,
) -> None:
    rollback = store.rollback_or_close
    failed_states = []

    def record_failure(connection: StoreConnection) -> None:
        failed_states.append(connection.info.transaction_status)
        rollback(connection)

    monkeypatch.setattr(store, "rollback_or_close", record_failure)
    with connect(empty_database) as conn:
        if state == "legacy":
            _legacy(conn)
        elif state == "versioned":
            apply_schema(conn)
        before, catalog = _columns(conn), _catalog(conn)
        conn.commit()
        monkeypatch.setattr(
            store,
            "MIGRATIONS",
            (
                *store.MIGRATIONS,
                (
                    "probe_fails",
                    "CREATE TABLE secret_probe (id integer); SELECT missing_secret",
                ),
            ),
            raising=False,
        )
        with pytest.raises(Refusal) as caught:
            apply_schema(conn)
        assert "secret" not in str(caught.value)
        assert failed_states == [psycopg.pq.TransactionStatus.INERROR]
        assert conn.info.transaction_status is psycopg.pq.TransactionStatus.IDLE
        assert _columns(conn) == before
        assert _catalog(conn) == catalog
        with connect(empty_database) as other:
            assert other.execute(
                "SELECT pg_try_advisory_xact_lock(%s)", (store._SCHEMA_LOCK,)
            ).fetchone() == (True,)


@pytest.mark.parametrize("state", ["fresh", "legacy", "prefix"])
def test_concurrent_starters_apply_once(
    empty_database: str,
    state: str,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    if state != "fresh":
        with connect(empty_database) as conn:
            if state == "legacy":
                _legacy(conn)
            else:
                with monkeypatch.context() as patch:
                    patch.setattr(store, "MIGRATIONS", store.MIGRATIONS[:4])
                    apply_schema(conn)
            _populate(conn, BlobStore(tmp_path))
    monkeypatch.setattr(
        store,
        "MIGRATIONS",
        (*store.MIGRATIONS, ("probe_once", "CREATE TABLE once_only (id integer)")),
    )
    ready = Barrier(2)

    def start() -> None:
        with connect(empty_database) as conn:
            ready.wait(timeout=10)
            apply_schema(conn)

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(start) for _ in range(2)]
        for future in futures:
            future.result(timeout=15)
    with connect(empty_database) as conn:
        assert conn.execute("SELECT count(*) FROM store_migrations").fetchone() == (
            len(store.MIGRATIONS),
        )


def test_interruption_before_commit_rolls_back(
    empty_database: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    migrate = store._migrate

    def interrupted(conn: StoreConnection, sql: str) -> None:
        migrate(conn, sql)
        raise KeyboardInterrupt

    monkeypatch.setattr(store, "_migrate", interrupted)
    with connect(empty_database) as conn:
        with pytest.raises(KeyboardInterrupt):
            apply_schema(conn)
        assert conn.info.transaction_status is psycopg.pq.TransactionStatus.IDLE
        assert _columns(conn) == []


@pytest.mark.parametrize("manifest", [(), (("wrong_baseline", SCHEMA),)])
def test_invalid_manifest_refuses_without_mutation(
    empty_database: str,
    monkeypatch: pytest.MonkeyPatch,
    manifest: tuple[tuple[str, str], ...],
) -> None:
    monkeypatch.setattr(store, "MIGRATIONS", manifest)
    with connect(empty_database) as conn:
        with pytest.raises(Refusal):
            apply_schema(conn)
        assert _columns(conn) == []


def test_invalid_legacy_digest_preserves_data(empty_database: str) -> None:
    with connect(empty_database) as conn:
        _legacy(conn)
        case_id = create_case(conn, BoundaryText.of("preserved"))
        conn.execute("UPDATE store_schema SET applied_digest = 'invalid'")
        conn.commit()
        with pytest.raises(Refusal):
            apply_schema(conn)
        assert conn.execute(
            "SELECT title FROM cases WHERE case_id = %s", (case_id,)
        ).fetchone() == ("preserved",)
        assert conn.execute("SELECT to_regclass('store_migrations')").fetchone() == (
            None,
        )


@pytest.mark.parametrize("change", ["older", "edited", "reordered", "missing_tail"])
def test_newer_database_or_changed_applied_prefix_refuses(
    empty_database: str,
    monkeypatch: pytest.MonkeyPatch,
    change: str,
) -> None:
    baseline = store.MIGRATIONS
    later = (*baseline, ("probe_tail", "CREATE TABLE probe (id integer)"))
    monkeypatch.setattr(store, "MIGRATIONS", later)
    with connect(empty_database) as conn:
        apply_schema(conn)
        if change == "older":
            monkeypatch.setattr(store, "MIGRATIONS", baseline)
        elif change == "edited":
            monkeypatch.setattr(
                store, "MIGRATIONS", (*baseline, ("probe_tail", "SELECT 1"))
            )
        elif change == "reordered":
            conn.execute(
                "UPDATE store_migrations SET version = version + %s", (len(later),)
            )
        else:
            conn.execute(
                "DELETE FROM store_migrations WHERE version = %s", (len(later),)
            )
        conn.commit()
        with pytest.raises(Refusal):
            apply_schema(conn)


def test_apply_schema_closed_connection_is_sanitized(empty_database: str) -> None:
    """rollback_or_close must retain the migration's safe refusal code."""
    conn = connect(empty_database)
    conn.close()
    with pytest.raises(Refusal) as caught:
        apply_schema(conn)
    assert caught.value.code is RefusalCode.STORE_SCHEMA_DRIFT


def test_committed_unit_commits_the_body_on_a_clean_exit(empty_database: str) -> None:
    with connect(empty_database) as conn:
        apply_schema(conn)
        with store.committed_unit(conn):
            conn.execute("CREATE TABLE t_committed_unit_ok (id int)")
        assert conn.info.transaction_status is psycopg.pq.TransactionStatus.IDLE
        with connect(empty_database) as probe:
            assert probe.execute(
                "SELECT to_regclass('t_committed_unit_ok')"
            ).fetchone() == ("t_committed_unit_ok",)


def test_committed_unit_answers_a_store_fault_with_no_text(
    empty_database: str,
) -> None:
    conn = connect(empty_database)
    apply_schema(conn)
    conn.close()
    with pytest.raises(Refusal) as caught:
        with store.committed_unit(conn):
            pass
    assert caught.value.code is RefusalCode.STORE_UNAVAILABLE


def test_committed_unit_rolls_back_and_reraises_any_other_failure(
    empty_database: str,
) -> None:
    with connect(empty_database) as conn:
        apply_schema(conn)
        with pytest.raises(ValueError), store.committed_unit(conn):
            conn.execute("CREATE TABLE t_committed_unit_reraise (id int)")
            raise ValueError("boom")
        assert conn.info.transaction_status is psycopg.pq.TransactionStatus.IDLE
        assert conn.execute(
            "SELECT to_regclass('t_committed_unit_reraise')"
        ).fetchone() == (None,)


def test_apply_schema_cleanup_preserves_cancellation(
    empty_database: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    def interrupted(conn: StoreConnection, sql: str) -> None:
        conn.close()
        raise KeyboardInterrupt

    monkeypatch.setattr(store, "_migrate", interrupted)
    with connect(empty_database) as conn, pytest.raises(KeyboardInterrupt):
        apply_schema(conn)


@pytest.mark.parametrize(
    "table,column",
    [
        ("runs", "budget_ceiling"),
        ("budget_reservations", "amount"),
        ("budget_ledger", "amount"),
    ],
)
@pytest.mark.parametrize("value", ["-1", "NaN", "Infinity", "-Infinity"])
def test_native_money_constraints_refuse_malformed_rows(
    empty_database: str, tmp_path: Path, table: str, column: str, value: str
) -> None:
    with connect(empty_database) as conn:
        apply_schema(conn)
        _populate(conn, BlobStore(tmp_path))
        if table == "budget_ledger":
            assert conn.info.dbname.startswith("caos_test_")
            conn.execute("ALTER TABLE budget_ledger DISABLE TRIGGER USER")
        with pytest.raises(psycopg.errors.CheckViolation):
            conn.execute(f"UPDATE {table} SET {column} = %s", (Decimal(value),))
        conn.rollback()


@pytest.mark.parametrize("table", ["budget_reservations", "budget_ledger"])
def test_budget_owner_keys_reject_existing_unrelated_run(
    empty_database: str, tmp_path: Path, table: str
) -> None:
    with connect(empty_database) as conn:
        apply_schema(conn)
        _populate(conn, BlobStore(tmp_path))
        other_case = create_case(conn, BoundaryText.of("unrelated owner"))
        other_run = start_run(conn, other_case)
        conn.commit()
        if table == "budget_ledger":
            assert conn.info.dbname.startswith("caos_test_")
            conn.execute("ALTER TABLE budget_ledger DISABLE TRIGGER USER")
        with pytest.raises(psycopg.errors.ForeignKeyViolation):
            conn.execute(f"UPDATE {table} SET run_id = %s", (other_run,))
        conn.rollback()


@pytest.mark.parametrize("prefix", [0, 5])
@pytest.mark.parametrize(
    "malformed",
    [
        ("runs", "budget_ceiling", "-1"),
        ("runs", "budget_ceiling", "NaN"),
        ("budget_ledger", "amount", "-1"),
        ("budget_ledger", "amount", "Infinity"),
        ("budget_reservations", "amount", "NaN"),
        ("budget_reservations", "amount", "Infinity"),
        ("budget_reservations", "run_id", "unrelated"),
        ("budget_ledger", "run_id", "unrelated"),
    ],
)
def test_invalid_populated_money_upgrade_refuses_atomically(
    empty_database: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    prefix: int,
    malformed: tuple[str, str, str],
) -> None:
    table, column, value = malformed
    with connect(empty_database) as conn:
        if prefix:
            with monkeypatch.context() as patch:
                patch.setattr(store, "MIGRATIONS", store.MIGRATIONS[:prefix])
                apply_schema(conn)
        else:
            _legacy(conn)
        _populate(conn, BlobStore(tmp_path))
        invalid: Decimal | UUID
        if value == "unrelated":
            owner = create_case(conn, BoundaryText.of("unrelated historical owner"))
            invalid = start_run(conn, owner)
        else:
            invalid = Decimal(value)
        conn.execute(f"UPDATE {table} SET {column} = %s", (invalid,))
        conn.commit()
        before, columns, catalog = repr(_records(conn)), _columns(conn), _catalog(conn)
        history = conn.execute("SELECT applied_digest FROM store_schema").fetchall()
        migrations = (
            conn.execute("SELECT * FROM store_migrations ORDER BY version").fetchall()
            if prefix
            else None
        )
        conn.commit()
        with pytest.raises(Refusal, match=r"^STORE_SCHEMA_DRIFT$"):
            apply_schema(conn)
        assert conn.info.transaction_status is psycopg.pq.TransactionStatus.IDLE
        assert repr(_records(conn)) == before
        assert _columns(conn) == columns
        assert _catalog(conn) == catalog
        assert (
            conn.execute("SELECT applied_digest FROM store_schema").fetchall()
            == history
        )
        if prefix:
            assert (
                conn.execute(
                    "SELECT * FROM store_migrations ORDER BY version"
                ).fetchall()
                == migrations
            )


# The version-1 pin each prefix-7 fixture wrote; an older schema cannot be
# read back through today's loader.
_PINNED: dict[UUID, RunInput] = {}


@pytest.fixture
def known_prefix(
    empty_database: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[Prepared]:
    with connect(empty_database) as conn:
        with monkeypatch.context() as patch:
            patch.setattr(store, "MIGRATIONS", store.MIGRATIONS[:7])
            apply_schema(conn)
        case_id = create_case(conn, BoundaryText.of("prefix seven"))
        run, sources, bundle, route = _prepare(conn, case_id, tmp_path)
        _PINNED[run] = pin_version_one(conn, run, sources, bundle, route)
        yield conn, run, sources, bundle, route


@pytest.mark.parametrize(
    "mutation",
    [
        "UPDATE source_blocks SET text = 'changed'",
        "UPDATE source_blocks SET page = 2",
        "UPDATE source_blocks SET block_id = 'b000001'",
        "DELETE FROM source_blocks",
        "INSERT INTO source_blocks SELECT source_id, 'b000001', page, text"
        " FROM source_blocks",
        "UPDATE source_tokens SET token_id = 1",
        "UPDATE source_tokens SET text = 'changed'",
        *[
            f"UPDATE source_tokens SET {field} = {field} + 1"
            for field in ("page", "region_id", "line_id", "x0", "y0", "x1", "y1")
        ],
        "DELETE FROM source_tokens",
        "INSERT INTO source_tokens SELECT source_id, 1, page, region_id, line_id,"
        " text, x0, y0, x1, y1 FROM source_tokens",
        "UPDATE sources SET document_sha256 = repeat('a', 64)",
        "UPDATE source_extractions SET output_sha256 = repeat('a', 64)",
        "UPDATE source_extractions SET extraction_sha256 = repeat('a', 64)",
        "UPDATE source_extractions SET extractor_identity = '{}'",
        "UPDATE source_extractions SET extractor_identity = '[]'",
        "UPDATE source_extractions SET extractor_identity = '{'",
        "UPDATE source_extractions SET extractor_identity ="
        " replace(extractor_identity, 'caos.plain-text', 'retired.writer')",
        # `canonical()` refuses this one itself, with a code of its own that
        # `_verify_extractions_v1` does not catch: a malformed row a migration's
        # verification finds is still a drift finding at the boot boundary.
        "UPDATE source_extractions SET extractor_identity ="
        ' \'{"name": "", "version": "1", "config": {}}\'',
    ],
)
def test_corrupt_known_upgrade_refuses_without_any_change(
    known_prefix: Prepared, empty_database: str, mutation: str
) -> None:
    conn, _, _, _, _ = known_prefix
    assert conn.info.dbname.startswith("caos_test_")
    with conn.transaction():
        if "UPDATE source_extractions" in mutation:
            conn.execute(
                "ALTER TABLE source_extractions DISABLE TRIGGER extraction_is_immutable"
            )
        conn.execute(mutation)
        if "UPDATE source_extractions" in mutation:
            conn.execute(
                "ALTER TABLE source_extractions ENABLE TRIGGER extraction_is_immutable"
            )
    conn.commit()
    before, catalog = repr(_records(conn)), _catalog(conn)
    history = conn.execute("SELECT * FROM store_migrations ORDER BY version").fetchall()
    head = conn.execute("SELECT * FROM store_schema").fetchall()
    conn.commit()
    with pytest.raises(Refusal, match=r"^STORE_SCHEMA_DRIFT$"):
        apply_schema(conn)
    assert conn.info.transaction_status is psycopg.pq.TransactionStatus.IDLE
    assert repr(_records(conn)) == before and _catalog(conn) == catalog
    assert (
        conn.execute("SELECT * FROM store_migrations ORDER BY version").fetchall()
        == history
    )
    assert conn.execute("SELECT * FROM store_schema").fetchall() == head
    with connect(empty_database) as other:
        other.execute("SET lock_timeout = '1s'")
        other.execute(
            "LOCK TABLE sources, source_tokens, source_blocks, source_extractions"
            " IN SHARE ROW EXCLUSIVE MODE"
        )
        assert other.execute(
            "SELECT pg_try_advisory_xact_lock(%s)", (store._SCHEMA_LOCK,)
        ).fetchone() == (True,)


@pytest.mark.parametrize("digits", [3, 0, -15])
def test_exact_historical_unicode_float_output_and_complete_pin_upgrade(
    known_prefix: Prepared, tmp_path: Path, digits: int
) -> None:
    conn, run, sources, _, _ = known_prefix
    pin = _PINNED[run]
    identity = ExtractorIdentity("retired-custom", "historical-v1", {"signed": -0.0})
    coordinate = 0.12345678901234566
    reader = Reader(
        identity,
        [
            Token("e\u0301", 1, 0, 0, -0.0, coordinate, 1.7976931348623157e308, 5e-324),
            Token("雪", 2, 1, 1, -1.7976931348623157e308, 0.0, 0.3, -5e-324),
        ],
    )
    admit_pack(
        conn,
        BlobStore(tmp_path),
        case_id=sources.case_id,
        documents=[Document(BoundaryText.of("custom.txt"), b"custom")],
        dispatch=lambda data: cast(Extractor, reader),
    )
    conn.commit()
    # Later migrations add columns; the rows that existed must not move.
    columns = _columns(conn)
    before = repr(_records(conn, columns))
    conn.execute(f"SET extra_float_digits = {digits}")
    apply_schema(conn)
    conn.execute("SET extra_float_digits = 3")
    assert repr(_records(conn, columns)) == before
    assert load_run_input(conn, run) == pin
    assert conn.execute("SELECT count(*) FROM source_extractions").fetchone() == (2,)
    catalog = _catalog(conn)
    apply_schema(conn)
    conn.execute("CREATE SCHEMA fresh_frozen; SET search_path TO fresh_frozen")
    apply_schema(conn)
    assert _catalog(conn) == catalog


@pytest.mark.parametrize("ordinal", [0, 999999, 1000000, 1000001])
def test_v1_block_ordinals_keep_minted_spelling(ordinal: int) -> None:
    from caos.store.extraction_integrity import _block_ordinal_v1

    assert _block_ordinal_v1(f"b{ordinal:06d}") == ordinal
    assert sorted(["b1000000", "b999999"], key=_block_ordinal_v1) == [
        "b999999",
        "b1000000",
    ]
    with pytest.raises((Refusal, ValueError)):
        _block_ordinal_v1(f"b0{ordinal:06d}")


@pytest.mark.parametrize("commit", [False, True])
def test_migration_reads_only_after_waiting_for_all_old_writers(
    known_prefix: Prepared, empty_database: str, commit: bool
) -> None:
    conn, _, _, _, _ = known_prefix
    conn.execute("UPDATE source_tokens SET text = 'changed'")
    with connect(empty_database) as other:

        def migrate() -> None:
            if commit:
                with pytest.raises(Refusal, match=r"^STORE_SCHEMA_DRIFT$"):
                    apply_schema(other)
            else:
                apply_schema(other)
            assert other.info.transaction_status is psycopg.pq.TransactionStatus.IDLE

        with _blocked(conn, other, migrate):
            if not commit:
                conn.rollback()
    assert conn.execute("SELECT max(version) FROM store_migrations").fetchone() == (
        7 if commit else len(store.MIGRATIONS),
    )


@pytest.mark.parametrize(
    "failure", ["cancel", "closed", "repeatable read", "serializable"]
)
def test_verifier_failure_preserves_cleanup_and_history(
    known_prefix: Prepared, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    from caos.store import extraction_integrity

    conn, _, _, _, _ = known_prefix
    if failure in {"cancel", "closed"}:

        def interrupted(c: StoreConnection, source: UUID) -> str:
            if failure == "closed":
                c.close()
            raise KeyboardInterrupt

        monkeypatch.setattr(extraction_integrity, "_stored_output_v1", interrupted)
    else:
        conn.execute(f"SET TRANSACTION ISOLATION LEVEL {failure}")
    with pytest.raises(
        KeyboardInterrupt if failure in {"cancel", "closed"} else Refusal
    ):
        apply_schema(conn)
    assert (
        conn.closed or conn.info.transaction_status is psycopg.pq.TransactionStatus.IDLE
    )


def test_v1_dispatch_is_exact_and_only_once(
    known_prefix: Prepared, monkeypatch: pytest.MonkeyPatch
) -> None:
    from caos.store import extraction_integrity

    conn, _, _, _, _ = known_prefix
    verify, calls = extraction_integrity._verify_extractions_v1, []

    def counted(c: StoreConnection) -> None:
        calls.append(True)
        verify(c)

    monkeypatch.setattr(extraction_integrity, "_verify_extractions_v1", counted)
    with monkeypatch.context() as patch:
        patch.setattr(
            store,
            "MIGRATIONS",
            (*store.MIGRATIONS[:7], ("synthetic_eight", "SELECT 1")),
        )
        with conn.transaction():
            store._migrate(conn, SCHEMA)
            assert calls == []
            raise psycopg.Rollback
    apply_schema(conn)
    apply_schema(conn)
    assert calls == [True]


def test_migration_holds_writers_until_native_guards_exist(
    known_prefix: Prepared, empty_database: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    from caos.store import extraction_integrity

    conn, _, _, _, _ = known_prefix
    original = extraction_integrity._stored_output_v1
    ready, release = Event(), Event()

    def pause(c: StoreConnection, source: UUID) -> str:
        output = original(c, source)
        ready.set()
        assert release.wait(5)
        return output

    monkeypatch.setattr(extraction_integrity, "_stored_output_v1", pause)
    with connect(empty_database) as writer, ThreadPoolExecutor(max_workers=2) as pool:

        def mutate() -> None:
            with pytest.raises(psycopg.errors.RaiseException, match="immutable"):
                writer.execute("UPDATE source_tokens SET text = 'late'")
            writer.rollback()

        migration = pool.submit(apply_schema, conn)
        try:
            assert ready.wait(3)
            mutation = pool.submit(mutate)
            _wait_for_blocking(conn, writer)
        finally:
            release.set()
        migration.result(timeout=6)
        mutation.result(timeout=6)
    assert conn.execute("SELECT text FROM source_tokens").fetchone() == ("one",)


def test_migration_deadlock_refuses_and_releases_its_partial_locks(
    known_prefix: Prepared, empty_database: str
) -> None:
    conn, _, _, _, _ = known_prefix
    # Writer owns the child table; migration will own sources before waiting for it.
    conn.execute("SET deadlock_timeout = '5s'; UPDATE source_tokens SET text = text")
    with (
        connect(empty_database) as migration,
        ThreadPoolExecutor(max_workers=1) as pool,
    ):
        migration.execute("SET deadlock_timeout = '100ms'")
        migration.commit()

        def upgrade() -> None:
            with pytest.raises(Refusal, match=r"^STORE_SCHEMA_DRIFT$"):
                apply_schema(migration)
            assert (
                migration.info.transaction_status is psycopg.pq.TransactionStatus.IDLE
            )

        future = pool.submit(upgrade)
        try:
            _wait_for_blocking(conn, migration)
            conn.execute("UPDATE sources SET filename = filename")
        finally:
            conn.rollback()
        future.result(timeout=6)
        migration.execute("SET lock_timeout = '1s'")
        apply_schema(migration)
    assert conn.execute("SELECT max(version) FROM store_migrations").fetchone() == (
        len(store.MIGRATIONS),
    )


def test_reordered_contiguous_tokens_refuse_upgrade(
    known_prefix: Prepared, tmp_path: Path
) -> None:
    conn, _, sources, _, _ = known_prefix
    [source] = admit_pack(
        conn,
        BlobStore(tmp_path),
        case_id=sources.case_id,
        documents=[Document(BoundaryText.of("order.txt"), b"first second")],
    )
    conn.execute(
        "UPDATE source_tokens SET token_id = token_id + 2 WHERE source_id = %s",
        (source,),
    )
    conn.execute(
        "UPDATE source_tokens SET token_id = 3 - token_id WHERE source_id = %s",
        (source,),
    )
    conn.commit()
    before = _records(conn)
    with pytest.raises(Refusal, match=r"^STORE_SCHEMA_DRIFT$"):
        apply_schema(conn)
    assert _records(conn) == before


def test_version_fourteen_adds_empty_command_requests_to_a_populated_store(
    empty_database: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Task 4.2 decision 6: migration 0014 advances a version-13 store with
    rows in it, adding an empty receipt table and changing nothing else."""
    with connect(empty_database) as conn:
        with monkeypatch.context() as patch:
            patch.setattr(store, "MIGRATIONS", store.MIGRATIONS[:13])
            apply_schema(conn)
        case_id = create_case(conn, BoundaryText.of("before commands"))
        run_id = start_run(conn, case_id)
        conn.commit()
        before = conn.execute("SELECT case_id, title FROM cases").fetchall()

        apply_schema(conn)

        assert store.MIGRATIONS[13][0] == "0014_command_requests"
        assert conn.execute("SELECT max(version) FROM store_migrations").fetchone() == (
            len(store.MIGRATIONS),
        )
        assert conn.execute("SELECT case_id, title FROM cases").fetchall() == before
        assert run_status(conn, run_id) is RunStatus.RUNNING
        assert conn.execute("SELECT count(*) FROM command_requests").fetchone() == (0,)
        conn.rollback()


def test_version_fifteen_adds_revisions_to_a_populated_store(
    empty_database: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    with connect(empty_database) as conn:
        with monkeypatch.context() as patch:
            patch.setattr(store, "MIGRATIONS", store.MIGRATIONS[:14])
            apply_schema(conn)
        case_id = create_case(conn, BoundaryText.of("Legacy filing"))
        run_id = start_run(conn, case_id)
        signer = uuid4()
        conn.execute(
            "INSERT INTO deliverable_opinions"
            " (case_id,revision_id,payload_sha256,signed_by) VALUES (%s,%s,%s,%s)",
            (case_id, "legacy-label", "a" * 64, signer),
        )
        conn.commit()
        apply_schema(conn)
        assert store.MIGRATIONS[14][0] == "0015_revisions"
        assert run_status(conn, run_id) is RunStatus.RUNNING
        assert conn.execute(
            "SELECT revision_id FROM deliverable_opinions"
        ).fetchone() == ("legacy-label",)
        assert conn.execute(
            "SELECT count(*) FROM deliverable_revisions"
        ).fetchone() == (0,)
        with pytest.raises(psycopg.errors.ForeignKeyViolation):
            conn.execute(
                "INSERT INTO deliverable_opinions"
                " (case_id,revision_id,payload_sha256,signed_by) VALUES (%s,%s,%s,%s)",
                (case_id, str(uuid4()), "a" * 64, signer),
            )
        conn.rollback()


def test_command_requests_are_keyed_bounded_and_immutable(
    case: tuple[StoreConnection, UUID],
) -> None:
    conn, _case_id = case
    columns = conn.execute(
        "SELECT column_name, data_type, is_nullable FROM information_schema.columns"
        " WHERE table_name = 'command_requests' ORDER BY ordinal_position"
    ).fetchall()
    assert columns == [
        ("actor_id", "uuid", "NO"),
        ("scope", "uuid", "NO"),
        ("idempotency_key", "uuid", "NO"),
        ("command", "text", "NO"),
        ("request_sha256", "text", "NO"),
        ("status", "smallint", "NO"),
        ("receipt", "jsonb", "NO"),
        ("created_at", "timestamp with time zone", "NO"),
    ]
    insert = (
        "INSERT INTO command_requests (actor_id, scope, idempotency_key, command,"
        " request_sha256, status, receipt) VALUES (%s, %s, %s, %s, %s, %s, %s)"
    )
    actor, scope, key = uuid4(), uuid4(), uuid4()
    good = (actor, scope, key, "START_RUN", "a" * 64, 202, '{"ok": true}')
    conn.execute(insert, good)
    conn.commit()
    for bad in (
        (actor, scope, key, "START_RUN", "b" * 64, 202, "{}"),  # the primary key
        (actor, scope, uuid4(), "start_run", "a" * 64, 202, "{}"),
        (actor, scope, uuid4(), "START_RUN", "A" * 64, 202, "{}"),
        (actor, scope, uuid4(), "START_RUN", "a" * 64, 409, "{}"),
        (
            actor,
            scope,
            uuid4(),
            "START_RUN",
            "a" * 64,
            200,
            '{"x": "' + "y" * 65_536 + '"}',
        ),
    ):
        with pytest.raises(psycopg.errors.IntegrityError):
            conn.execute(insert, bad)
        conn.rollback()
    for mutation in (
        "UPDATE command_requests SET status = 200",
        "DELETE FROM command_requests",
        "TRUNCATE command_requests",
    ):
        with pytest.raises(psycopg.errors.RaiseException, match="immutable"):
            conn.execute(mutation)
        conn.rollback()
    assert conn.execute("SELECT count(*) FROM command_requests").fetchone() == (1,)
    conn.rollback()


@pytest.mark.parametrize(
    "raised,expected",
    [
        (RefusalCode.STORE_UNAVAILABLE, RefusalCode.STORE_UNAVAILABLE),
        (RefusalCode.STORE_NOT_TRANSACTIONAL, RefusalCode.STORE_NOT_TRANSACTIONAL),
        (RefusalCode.SOURCE_IDENTITY_INVALID, RefusalCode.STORE_SCHEMA_DRIFT),
        (RefusalCode.BOUNDARY_TEXT_INVALID, RefusalCode.STORE_SCHEMA_DRIFT),
    ],
)
def test_apply_schema_keeps_a_store_fault_and_flattens_every_other_refusal(
    empty_database: str,
    monkeypatch: pytest.MonkeyPatch,
    raised: RefusalCode,
    expected: RefusalCode,
) -> None:
    """W6: a store that could not answer is not a database built from another
    schema, and saying `STORE_SCHEMA_DRIFT` sends an operator to the migration
    history for a fault that is not there. Everything else a migration refuses
    -- including a malformed row its own verification finds, which raises codes
    from outside this module -- is a drift finding and keeps saying so
    (`docs/DECISIONS.md` §20a)."""

    def refusing(conn: StoreConnection, sql: str) -> None:
        raise Refusal(raised)

    monkeypatch.setattr(store, "_migrate", refusing)
    with connect(empty_database) as conn, pytest.raises(Refusal) as caught:
        apply_schema(conn)

    assert caught.value.code is expected


def test_the_migration_keeps_existing_reservation_amounts(
    empty_database: str, tmp_path: Path
) -> None:
    """`0024_reservation_price` adds the four price columns to rows that have
    no price to record. The amounts are the money and must not move; the
    migration defaults say plainly that these rows predate the columns.
    """
    with connect(empty_database) as conn:
        _legacy(conn)
        _populate(conn, BlobStore(tmp_path))
        conn.commit()
        before = conn.execute(
            "SELECT attempt_id, amount FROM budget_reservations ORDER BY attempt_id"
        ).fetchall()
        assert before, "a scanner that scanned nothing is a failure"

        apply_schema(conn)

        assert (
            conn.execute(
                "SELECT attempt_id, amount FROM budget_reservations ORDER BY attempt_id"
            ).fetchall()
            == before
        )
        assert conn.execute(
            "SELECT DISTINCT price_model, price_input, price_output, price_as_of"
            " FROM budget_reservations"
        ).fetchall() == [("legacy", Decimal(0), Decimal(0), date(1970, 1, 1))]
        # The defaults migrated the rows that existed; they do not stand in for
        # a price a new reservation failed to name.
        with pytest.raises(psycopg.errors.NotNullViolation):
            conn.execute(
                "INSERT INTO budget_reservations (attempt_id, run_id, amount)"
                " SELECT %s, run_id, 0.10 FROM budget_reservations LIMIT 1",
                (uuid4(),),
            )
        conn.rollback()


@pytest.mark.parametrize(
    "column,value",
    [
        ("price_model", ""),
        ("price_input", "-1"),
        ("price_output", "NaN"),
        ("price_input", "Infinity"),
    ],
)
def test_a_reservation_price_outside_its_constraint_refuses(
    empty_database: str, tmp_path: Path, column: str, value: str
) -> None:
    """A stored price that names no model, or is not finite and nonnegative,
    would be unreadable as the fact the column exists to hold."""
    with connect(empty_database) as conn:
        apply_schema(conn)
        _populate(conn, BlobStore(tmp_path))
        given: object = value if column == "price_model" else Decimal(value)
        with pytest.raises(psycopg.errors.CheckViolation):
            conn.execute(f"UPDATE budget_reservations SET {column} = %s", (given,))
        conn.rollback()


def test_the_directory_listing_uses_an_index_on_case_members(
    empty_database: str,
) -> None:
    """`cases_for_member` joins from `case_members` on the caller's user id, so the
    membership side of that join needs an index of its own: the primary key
    leads with `case_id` and cannot serve it."""
    with connect(empty_database) as conn:
        apply_schema(conn)
        conn.execute("SET enable_seqscan = off")
        plan = "\n".join(
            r[0]
            for r in conn.execute(
                "EXPLAIN SELECT c.case_id FROM case_members m"
                " JOIN cases c ON c.case_id = m.case_id"
                " WHERE m.user_id = %s AND m.revoked_at IS NULL",
                (uuid4(),),
            ).fetchall()
        )
    assert "case_members_by_user" in plan, plan
    # The name alone would hold for an index of that name on any column;
    # the condition is what pins it as a lookup on `user_id`.
    assert "Index Cond: (user_id =" in plan, plan


# Tuple position, not ordinal: `0022` and `0023` are permanent gaps
# (`docs/MIGRATIONS.md`), so `0028` is the 26th migration.
_AT_0028 = [name for name, _ in store.MIGRATIONS].index("0028_worker_heartbeats") + 1


def _two_opinions_at_0028(conn: StoreConnection, *, same_signer: bool) -> None:
    """A store at `0028` holding two signatures of one saved revision."""
    case_id = create_case(conn, BoundaryText.of("Signed twice"))
    run_id = start_run(conn, case_id)
    revision_id = uuid4()
    conn.execute(
        "INSERT INTO deliverable_revisions"
        " (revision_id,case_id,run_id,payload_sha256,saved_by)"
        " VALUES (%s,%s,%s,%s,%s)",
        (revision_id, case_id, run_id, "a" * 64, uuid4()),
    )
    first = uuid4()
    for signer in (first, first if same_signer else uuid4()):
        conn.execute(
            "INSERT INTO deliverable_opinions"
            " (case_id,revision_id,payload_sha256,signed_by,signed_at)"
            " VALUES (%s,%s,%s,%s,clock_timestamp())",
            (case_id, str(revision_id), "a" * 64, signer),
        )
    conn.commit()


def test_migration_0029_holds_one_signature_per_signer_and_revision(
    empty_database: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`0029_one_opinion_per_signer` advances a store whose revisions carry
    distinct signers, and from then on a second signature by the same signer is
    refused by the store under the constraint's own name."""
    with connect(empty_database) as conn:
        with monkeypatch.context() as patch:
            patch.setattr(store, "MIGRATIONS", store.MIGRATIONS[:_AT_0028])
            apply_schema(conn)
        _two_opinions_at_0028(conn, same_signer=False)

        apply_schema(conn)

        assert store.MIGRATIONS[_AT_0028][0] == "0029_one_opinion_per_signer"
        assert conn.execute("SELECT count(*) FROM deliverable_opinions").fetchone() == (
            2,
        )
        with pytest.raises(psycopg.errors.UniqueViolation) as caught:
            conn.execute(
                "INSERT INTO deliverable_opinions"
                " (case_id,revision_id,payload_sha256,signed_by)"
                " SELECT case_id,revision_id,payload_sha256,signed_by"
                " FROM deliverable_opinions LIMIT 1"
            )
        assert caught.value.diag.constraint_name == "one_opinion_per_signer"
        conn.rollback()


def test_migration_0029_refuses_a_store_where_a_signer_signed_twice(
    empty_database: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A doubled signature is governed evidence that an `OPINION_SIGNED` event
    names, so the migration does not choose which of the two to delete. It
    refuses before any DDL, leaving the history at `0028` and both rows in
    place, for an operator to reconcile -- the pattern `0017` set."""
    with connect(empty_database) as conn:
        with monkeypatch.context() as patch:
            patch.setattr(store, "MIGRATIONS", store.MIGRATIONS[:_AT_0028])
            apply_schema(conn)
        _two_opinions_at_0028(conn, same_signer=True)

        with pytest.raises(Refusal, match=r"^STORE_SCHEMA_DRIFT$"):
            apply_schema(conn)
        conn.rollback()

        assert conn.execute("SELECT max(version) FROM store_migrations").fetchone() == (
            _AT_0028,
        )
        assert conn.execute("SELECT count(*) FROM deliverable_opinions").fetchone() == (
            2,
        )
        conn.rollback()

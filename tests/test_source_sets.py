"""Real PostgreSQL immutable source membership and transaction boundaries."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from threading import Event
from typing import Any, cast
from uuid import UUID, uuid4

import psycopg
import pytest
from psycopg.pq import TransactionStatus
from test_case_ordering import _blocked, _wait_for_blocking
from test_extraction_provenance import Reader

from caos.blobs import BlobStore
from caos.boundary_text import BoundaryText
from caos.evidence.extract import (
    Extractor,
    PlainTextExtractor,
    dispatch_by_content,
)
from caos.evidence.ingest import Document, admit_pack
from caos.evidence.read import read_block
from caos.refusals import Refusal, RefusalCode
from caos.store import StoreConnection, apply_schema, connect, source_sets
from caos.store.cases import lock_case
from caos.store.gates import withdraw_source
from caos.store.members import Standing, grant
from caos.store.runs import create_case
from caos.store.source_sets import (
    SourceSet,
    SourceSetMember,
    load_source_set,
    snapshot_source_set,
)


def _admit(
    conn: StoreConnection, case_id: UUID, path: Path, extractor: Extractor | None = None
) -> UUID:
    grant(conn, case_id=case_id, user_id=case_id, standing=Standing.WRITER)
    [source] = admit_pack(
        conn,
        BlobStore(path),
        case_id=case_id,
        documents=[Document(BoundaryText.of("one.txt"), b"one")],
        dispatch=dispatch_by_content if extractor is None else lambda data: extractor,
    )
    return source


def _copy_member(conn: StoreConnection, snapshot: SourceSet, source: UUID) -> None:
    conn.execute(
        "INSERT INTO source_set_members SELECT case_id, version, %s, document_sha256,"
        " filename, admitted_at, extractor_identity, output_sha256, extraction_sha256"
        " FROM source_set_members WHERE case_id = %s AND version = %s LIMIT 1",
        (source, snapshot.case_id, snapshot.version),
    )


def test_snapshot_replays_and_loads_exact_history(
    case: tuple[StoreConnection, UUID], tmp_path: Path
) -> None:
    conn, case_id = case
    ids = admit_pack(
        conn,
        BlobStore(tmp_path),
        case_id=case_id,
        documents=[Document(BoundaryText.of("one.txt"), b"one")],
    )
    conn.commit()
    first = snapshot_source_set(conn, case_id)
    assert first.version == 1
    assert isinstance(first.members[0], SourceSetMember)
    assert [member.source_id for member in first.members] == ids
    assert snapshot_source_set(conn, case_id) == first
    assert load_source_set(conn, case_id, first.version) == first
    assert load_source_set(conn, uuid4(), first.version) is None
    assert load_source_set(conn, case_id, 999) is None
    assert source_sets._fingerprint(case_id, first.members[::-1]) == first.fingerprint


def test_changes_preserve_history_and_returning_state_gets_new_version(
    case: tuple[StoreConnection, UUID], tmp_path: Path
) -> None:
    conn, case_id = case
    source = _admit(conn, case_id, tmp_path)
    conn.commit()
    first = snapshot_source_set(conn, case_id)
    added = _admit(conn, case_id, tmp_path)
    conn.commit()
    second = snapshot_source_set(conn, case_id)
    assert second.version == 2 and len(second.members) == 2
    assert source_sets._fingerprint(case_id, second.members[::-1]) == second.fingerprint
    withdraw_source(conn, case_id=case_id, source_id=added, actor_id=case_id)
    conn.commit()
    third = snapshot_source_set(conn, case_id)
    assert third.version == 3 and third.fingerprint == first.fingerprint
    assert load_source_set(conn, case_id, 2) == second
    with pytest.raises(Refusal):
        read_block(conn, source_id=added, block_id="b000000")
    readmitted = _admit(conn, case_id, tmp_path)
    assert readmitted not in (source, added)
    conn.commit()
    assert snapshot_source_set(conn, case_id).fingerprint != second.fingerprint
    conn.execute(
        "UPDATE sources SET filename = 'renamed.txt' WHERE source_id = %s", (source,)
    )
    conn.commit()
    renamed = snapshot_source_set(conn, case_id)
    assert renamed.version == 5
    assert load_source_set(conn, case_id, 1) == first
    member = first.members[0]
    for changed in (
        replace(member, filename="other"),
        replace(member, source_id=uuid4()),
    ):
        assert source_sets._fingerprint(case_id, (changed,)) != first.fingerprint
    assert source_sets._fingerprint(uuid4(), first.members) != first.fingerprint


@pytest.mark.parametrize("change", ["adapter", "config", "output"])
def test_same_bytes_different_extraction_changes_snapshot(
    case: tuple[StoreConnection, UUID], tmp_path: Path, change: str
) -> None:
    conn, case_id = case
    _admit(conn, case_id, tmp_path)
    conn.commit()
    first = snapshot_source_set(conn, case_id)
    identity = PlainTextExtractor().identity
    reader = Reader(
        replace(identity, name="other")
        if change == "adapter"
        else replace(identity, config={})
        if change == "config"
        else identity,
        PlainTextExtractor().extract(b"different") if change == "output" else None,
    )
    _admit(conn, case_id, tmp_path, cast(Extractor, reader))
    conn.commit()
    second = snapshot_source_set(conn, case_id)
    extra = next(m for m in second.members if m.source_id != first.members[0].source_id)
    assert extra.document_sha256 == first.members[0].document_sha256
    assert extra.extraction_sha256 != first.members[0].extraction_sha256
    assert second.fingerprint != first.fingerprint


@pytest.mark.parametrize(
    "invalid",
    ["empty", "unknown", "json", "nonfinite", "binding", "filename", "timestamp"],
)
def test_invalid_live_set_refuses_without_retaining_lock(
    case: tuple[StoreConnection, UUID],
    tmp_path: Path,
    empty_database: str,
    invalid: str,
) -> None:
    conn, case_id = case
    if invalid not in ("empty", "unknown"):
        _admit(conn, case_id, tmp_path)
    if invalid == "unknown":
        conn.execute(
            "INSERT INTO sources (source_id, case_id, document_sha256, filename)"
            " VALUES (%s, %s, %s, 'legacy')",
            (uuid4(), case_id, "a" * 64),
        )
    if invalid in ("json", "nonfinite", "binding"):
        # Inject malformed historical SQL provenance before its immutable trigger.
        conn.execute(
            "ALTER TABLE source_extractions DISABLE TRIGGER extraction_is_immutable"
        )
        conn.execute(
            "UPDATE source_extractions SET extractor_identity = %s",
            (
                {
                    "json": "private malformed text",
                    "nonfinite": '{"name":"x","version":"1","config":{"x":NaN}}',
                    "binding": '{"name":"x","version":"1","config":{}}',
                }[invalid],
            ),
        )
        conn.execute(
            "ALTER TABLE source_extractions ENABLE TRIGGER extraction_is_immutable"
        )
    if invalid == "filename":
        conn.execute("UPDATE sources SET filename = %s", ("bad\u202e",))
    if invalid == "timestamp":
        conn.execute("SET TIME ZONE 'Europe/Paris'")
        conn.execute(
            "UPDATE sources SET admitted_at ="
            " '0001-01-01 00:00:00+00:09:21'::timestamptz"
        )
    conn.commit()
    with pytest.raises(Refusal) as caught:
        snapshot_source_set(conn, case_id)
    assert caught.value.code is (
        RefusalCode.SOURCE_PACK_EMPTY
        if invalid == "empty"
        else RefusalCode.SOURCE_IDENTITY_INVALID
    )
    assert "private" not in str(caught.value)
    assert conn.info.transaction_status is TransactionStatus.IDLE
    with connect(empty_database) as other:
        other.execute("SET lock_timeout = '1s'")
        lock_case(other, case_id)
    for table in ("source_set_versions", "source_set_members"):
        assert conn.execute("SELECT count(*) FROM " + table).fetchone() == (0,)


@pytest.mark.parametrize("stage", ["header", "member", "commit"])
def test_snapshot_database_failure_is_atomic(
    case: tuple[StoreConnection, UUID], tmp_path: Path, stage: str
) -> None:
    conn, case_id = case
    _admit(conn, case_id, tmp_path)
    if stage == "member":
        _admit(conn, case_id, tmp_path)
        conn.execute(
            "UPDATE sources SET filename = 'bad' WHERE source_id ="
            " (SELECT source_id FROM sources ORDER BY source_id DESC LIMIT 1)"
        )
    if stage == "commit":
        conn.execute(
            "CREATE FUNCTION snapshot_failure() RETURNS trigger LANGUAGE plpgsql AS $$"
            "BEGIN RAISE EXCEPTION 'private'; END; $$"
        )
        conn.execute(
            "CREATE CONSTRAINT TRIGGER fail_commit AFTER INSERT ON source_set_members"
            " DEFERRABLE INITIALLY DEFERRED FOR EACH ROW"
            " EXECUTE FUNCTION snapshot_failure()"
        )
    else:
        conn.execute(
            "ALTER TABLE "
            + ("source_set_versions" if stage == "header" else "source_set_members")
            + (
                " ADD CHECK (filename <> 'bad')"
                if stage == "member"
                else " ADD CHECK (version < 1)"
            )
        )
    conn.commit()
    with pytest.raises(Refusal) as caught:
        snapshot_source_set(conn, case_id)
    assert caught.value.code is RefusalCode.STORE_UNAVAILABLE
    assert conn.info.transaction_status is TransactionStatus.IDLE
    conn.commit()
    for table in ("source_set_versions", "source_set_members"):
        assert conn.execute("SELECT count(*) FROM " + table).fetchone() == (0,)


@pytest.mark.parametrize("table", ["source_set_versions", "source_set_members"])
@pytest.mark.parametrize(
    "mutation",
    ["UPDATE {} SET version = version", "DELETE FROM {}", "TRUNCATE {} CASCADE"],
)
def test_native_immutable_rows(
    case: tuple[StoreConnection, UUID], tmp_path: Path, table: str, mutation: str
) -> None:
    conn, case_id = case
    _admit(conn, case_id, tmp_path)
    conn.commit()
    first = snapshot_source_set(conn, case_id)
    with pytest.raises(psycopg.Error):
        conn.execute(mutation.format(table))
    conn.rollback()
    assert load_source_set(conn, case_id, 1) == first


def test_native_late_concurrent_and_cross_case_members_refuse(
    case: tuple[StoreConnection, UUID], tmp_path: Path, empty_database: str
) -> None:
    conn, case_id = case
    _admit(conn, case_id, tmp_path)
    conn.commit()
    first = snapshot_source_set(conn, case_id)
    additions = [_admit(conn, case_id, tmp_path) for _ in range(2)]
    foreign = create_case(conn, BoundaryText.of("other"))
    outsider = _admit(conn, foreign, tmp_path)
    conn.commit()
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        _copy_member(conn, first, outsider)
    conn.rollback()
    with connect(empty_database) as other:
        _copy_member(conn, first, additions[0])
        _copy_member(other, first, additions[1])
        for connection in (conn, other):
            with pytest.raises(psycopg.Error):
                connection.commit()
            connection.rollback()
    assert load_source_set(conn, case_id, 1) == first
    conn.execute("SET CONSTRAINTS ALL IMMEDIATE")
    with pytest.raises(psycopg.Error):
        _copy_member(conn, first, additions[0])
    conn.rollback()
    conn.execute(
        "INSERT INTO source_set_versions VALUES (%s, 2, 1, %s, 1)", (case_id, "a" * 64)
    )
    with pytest.raises(Refusal):
        load_source_set(conn, case_id, 2)
    with pytest.raises(psycopg.Error):
        conn.commit()
    conn.rollback()


@pytest.mark.parametrize("table", ["source_set_versions", "source_set_members"])
@pytest.mark.parametrize("schema", ["public", "source sets review"])
def test_native_completeness_ignores_temporary_shadows(
    empty_database: str, tmp_path: Path, table: str, schema: str
) -> None:
    with connect(empty_database) as conn:
        if schema != "public":
            conn.execute(
                psycopg.sql.SQL("CREATE SCHEMA {}").format(
                    psycopg.sql.Identifier(schema)
                )
            )
        conn.execute(
            psycopg.sql.SQL("SET search_path TO {}").format(
                psycopg.sql.Identifier(schema)
            )
        )
        apply_schema(conn)
        search_path = conn.execute("SHOW search_path").fetchone()
        case_id = create_case(conn, BoundaryText.of("shadow review"))
        _admit(conn, case_id, tmp_path)
        conn.commit()
        first = snapshot_source_set(conn, case_id)
        assert conn.execute("SHOW search_path").fetchone() == search_path
        extra = _admit(conn, case_id, tmp_path)
        conn.commit()
        conn.execute(
            psycopg.sql.SQL("CREATE TEMP TABLE {} AS TABLE {}.{}").format(
                *map(psycopg.sql.Identifier, (table, schema, table))
            )
        )
        if table == "source_set_versions":
            conn.execute(
                "UPDATE pg_temp.source_set_versions SET member_count = member_count + 1"
            )
        conn.execute(
            psycopg.sql.SQL(
                "INSERT INTO {}.source_set_members SELECT case_id, version, %s,"
                " document_sha256, filename, admitted_at, extractor_identity,"
                " output_sha256, extraction_sha256 FROM {}.source_set_members"
                " WHERE case_id = %s AND version = %s"
            ).format(*[psycopg.sql.Identifier(schema)] * 2),
            (extra, case_id, first.version),
        )
        with pytest.raises(psycopg.Error):
            conn.commit()
        conn.rollback()
        assert load_source_set(conn, case_id, first.version) == first
        assert conn.execute("SHOW search_path").fetchone() == search_path


@pytest.mark.parametrize(
    "field,value",
    [
        ("admitted_at", "2026-01-01"),
        ("admitted_at", "invalid"),
        ("document_sha256", "bad"),
        ("extraction_sha256", "a" * 64),
        ("extractor_identity", "[]"),
        ("extractor_identity", "{}"),
        ("extractor_identity", '{"name":"x","version":"1","config":{"x":1e400}}'),
    ],
)
def test_identity_refuses_unrepresentable_metadata(
    case: tuple[StoreConnection, UUID], tmp_path: Path, field: str, value: str
) -> None:
    conn, case_id = case
    _admit(conn, case_id, tmp_path)
    conn.commit()
    first = snapshot_source_set(conn, case_id)
    with pytest.raises(Refusal):
        source_sets._fingerprint(
            case_id, (replace(first.members[0], **{field: cast(Any, value)}),)
        )
    with pytest.raises(Refusal):
        source_sets._fingerprint(case_id, first.members * 2)


def test_snapshot_cancellation_and_nontransactional_refusal(
    case: tuple[StoreConnection, UUID], monkeypatch: pytest.MonkeyPatch
) -> None:
    conn, case_id = case
    conn.autocommit = True
    with pytest.raises(Refusal) as caught:
        snapshot_source_set(conn, case_id)
    assert caught.value.code is RefusalCode.STORE_NOT_TRANSACTIONAL
    conn.autocommit = False

    def cancelled(c: StoreConnection, target: UUID) -> None:
        lock_case(c, target)
        raise KeyboardInterrupt

    monkeypatch.setattr(source_sets, "lock_case", cancelled)
    with pytest.raises(KeyboardInterrupt):
        snapshot_source_set(conn, case_id)
    assert conn.info.transaction_status is TransactionStatus.IDLE


@pytest.mark.parametrize("mutation", ["admit", "withdraw", "snapshot"])
def test_snapshot_orders_after_case_mutation(
    case: tuple[StoreConnection, UUID],
    tmp_path: Path,
    empty_database: str,
    mutation: str,
) -> None:
    conn, case_id = case
    source = _admit(conn, case_id, tmp_path)
    _admit(conn, case_id, tmp_path)
    conn.commit()
    first = snapshot_source_set(conn, case_id)
    conn.execute(
        "SELECT case_id FROM cases WHERE case_id = %s FOR NO KEY UPDATE", (case_id,)
    )
    if mutation == "admit":
        _admit(conn, case_id, tmp_path)
    results: list[SourceSet] = []
    with connect(empty_database) as other:
        with _blocked(
            conn, other, lambda: results.append(snapshot_source_set(other, case_id))
        ):
            if mutation == "withdraw":
                withdraw_source(
                    conn, case_id=case_id, source_id=source, actor_id=case_id
                )
    assert (
        len(results[0].members) == {"admit": 3, "withdraw": 1, "snapshot": 2}[mutation]
    )
    assert results[0].version == (1 if mutation == "snapshot" else 2)
    assert load_source_set(conn, case_id, 1) == first


@pytest.mark.parametrize("mutation", ["admit", "withdraw", "snapshot"])
def test_snapshot_first_serializes_other_writers(
    case: tuple[StoreConnection, UUID],
    tmp_path: Path,
    empty_database: str,
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
) -> None:
    conn, case_id = case
    source = _admit(conn, case_id, tmp_path)
    independent = create_case(conn, BoundaryText.of("independent"))
    _admit(conn, independent, tmp_path)
    conn.commit()
    ready, release = Event(), Event()

    def pause(c: StoreConnection, target: UUID) -> None:
        lock_case(c, target)
        if c is conn:
            ready.set()
            assert release.wait(5)

    monkeypatch.setattr(source_sets, "lock_case", pause)
    with connect(empty_database) as other, ThreadPoolExecutor(max_workers=2) as pool:
        other.execute("SET statement_timeout = '5s'")
        other.commit()
        first = pool.submit(snapshot_source_set, conn, case_id)
        try:
            assert ready.wait(3)
            assert snapshot_source_set(other, independent).version == 1
            operation = {
                "admit": lambda: _admit(other, case_id, tmp_path),
                "withdraw": lambda: withdraw_source(
                    other, case_id=case_id, source_id=source, actor_id=case_id
                ),
                "snapshot": lambda: snapshot_source_set(other, case_id),
            }[mutation]
            second = pool.submit(operation)
            _wait_for_blocking(conn, other)
        finally:
            release.set()
        result = first.result(timeout=6)
        second.result(timeout=6)
        other.commit()
    assert len(result.members) == 1
    assert load_source_set(conn, case_id, 1) == result

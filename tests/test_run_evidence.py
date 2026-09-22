"""Run membership reads; caller authority integration remains a later task."""

from __future__ import annotations

import json
import traceback
from pathlib import Path
from typing import cast
from urllib.parse import urlsplit
from uuid import UUID, uuid4

import psycopg
import pytest
from psycopg.pq import TransactionStatus
from test_read_evidence import _CountingConnection
from test_route_pinning import CATALOG_PATH, PROFILE
from test_run_inputs import SUBJECT, Prepared, _prepare, prepared
from test_source_sets import _admit

from caos.blobs import BlobStore
from caos.boundary_text import BoundaryText
from caos.evidence import read
from caos.evidence.ingest import Document, admit_pack
from caos.graph.route import resolve_route
from caos.methodology.bundle import Bundle
from caos.refusals import Refusal
from caos.store import StoreConnection
from caos.store.members import Standing, grant
from caos.store.outcomes import execution_reads
from caos.store.routes import pin_route
from caos.store.run_inputs import load_run_input, pin_run_input
from caos.store.runs import create_case, start_run
from caos.store.source_sets import snapshot_source_set

__all__ = ["prepared"]

# The connection, its pinned run, and the two sources the pin captured.
type Delivered = tuple[StoreConnection, UUID, UUID, UUID]


@pytest.fixture
def pinned(prepared: Prepared) -> Prepared:
    conn, run, sources, bundle, _ = prepared
    pin_run_input(conn, run, sources.version, bundle, subject=SUBJECT)
    return prepared


def test_run_read_keeps_captured_membership_after_later_admission(
    pinned: Prepared, tmp_path: Path
) -> None:
    conn, run, sources, _, _ = pinned
    pin = load_run_input(conn, run)
    source = sources.members[0].source_id
    _admit(conn, sources.case_id, tmp_path)
    conn.commit()
    later = snapshot_source_set(conn, sources.case_id)
    assert later.version != sources.version
    counter = _CountingConnection(conn)
    rows = read.read_run_blocks(cast(StoreConnection, counter), run_id=run)
    assert rows == [(source, "b000000", 1, BoundaryText.of("one"))]
    assert counter.executed == 1
    assert load_run_input(conn, run) == pin


@pytest.mark.parametrize("fault", ["missing-run", "missing-input", "withdrawn"])
def test_run_read_refuses_unavailable_membership(pinned: Prepared, fault: str) -> None:
    """A run that captured nothing is the shortest short delivery there is:
    an empty list would be a delivery, so all three refuse."""
    conn, run, sources, _, _ = pinned
    source = sources.members[0].source_id
    if fault == "missing-run":
        run = uuid4()
    elif fault == "missing-input":
        run = start_run(conn, sources.case_id)
    else:
        conn.execute(
            "UPDATE sources SET withdrawn_at = now() WHERE source_id = %s", (source,)
        )
    counter = _CountingConnection(conn)
    with pytest.raises(Refusal, match=r"^EVIDENCE_NOT_AVAILABLE$") as caught:
        read.read_run_blocks(cast(StoreConnection, counter), run_id=run)
    assert caught.value.__cause__ is None
    assert counter.executed == 1


def test_a_run_delivers_only_the_members_its_own_case_pinned(
    pinned: Prepared, tmp_path: Path
) -> None:
    """A source is bound to its case. Both cases admit the same bytes, so only
    the join's `(case_id, source_id)` keeps one run's evidence out of the
    other's -- the property the retired per-block reader held by refusing a
    foreign block, which a whole-run read states as what each run delivers."""
    conn, run, sources, _, _ = pinned
    other = create_case(conn, BoundaryText.of("other"))
    other_run, other_sources, bundle, _ = _prepare(conn, other, tmp_path)
    pin_run_input(conn, other_run, other_sources.version, bundle, subject=SUBJECT)
    mine, theirs = sources.members[0].source_id, other_sources.members[0].source_id
    assert mine != theirs
    assert (
        sources.members[0].document_sha256 == other_sources.members[0].document_sha256
    )
    assert [source for source, *_ in read.read_run_blocks(conn, run_id=run)] == [mine]
    assert [source for source, *_ in read.read_run_blocks(conn, run_id=other_run)] == [
        theirs
    ]


def test_equal_bytes_do_not_admit_a_post_pin_source(
    pinned: Prepared, tmp_path: Path
) -> None:
    conn, run, sources, _, _ = pinned
    # The extractor is immaterial: a source admitted after the pin is not a
    # member of the pinned version, so it never enters the captured set at all.
    added = _admit(conn, sources.case_id, tmp_path)
    assert (
        read.read_block(conn, source_id=added, block_id="b000000").text.value == "one"
    )
    assert conn.execute(
        "SELECT document_sha256 FROM sources WHERE source_id = %s", (added,)
    ).fetchone() == (sources.members[0].document_sha256,)
    # The run delivers its pinned member and never the equal bytes beside it.
    assert [source for source, *_ in read.read_run_blocks(conn, run_id=run)] == [
        sources.members[0].source_id
    ]


@pytest.mark.parametrize(
    "field",
    ["document_sha256", "extractor_identity", "output_sha256", "extraction_sha256"],
)
def test_run_read_compares_each_captured_current_identity(
    pinned: Prepared, empty_database: str, field: str
) -> None:
    conn, run, sources, _, _ = pinned
    source = sources.members[0].source_id
    database = urlsplit(empty_database).path.removeprefix("/")
    assert database == "caos_test_" + UUID(database.removeprefix("caos_test_")).hex
    assert conn.execute("SELECT current_database()").fetchone() == (database,)
    table = "sources" if field == "document_sha256" else "source_extractions"
    with conn.transaction():
        if table == "source_extractions":
            conn.execute(
                "ALTER TABLE source_extractions DISABLE TRIGGER extraction_is_immutable"
            )
        conn.execute(
            psycopg.sql.SQL("UPDATE {} SET {} = %s WHERE source_id = %s").format(
                psycopg.sql.Identifier(table), psycopg.sql.Identifier(field)
            ),
            ("{}" if field == "extractor_identity" else "0" * 64, source),
        )
        if table == "source_extractions":
            conn.execute(
                "ALTER TABLE source_extractions ENABLE TRIGGER extraction_is_immutable"
            )
    with pytest.raises(Refusal, match=r"^EVIDENCE_NOT_AVAILABLE$"):
        read.read_run_blocks(conn, run_id=run)


@pytest.mark.parametrize("invalid", [None, 0, "invalid"])
def test_run_read_validates_arguments_before_sql(
    pinned: Prepared, invalid: object
) -> None:
    conn, *_ = pinned
    counter = _CountingConnection(conn)
    with pytest.raises(Refusal, match=r"^EVIDENCE_NOT_AVAILABLE$"):
        read.read_run_blocks(cast(StoreConnection, counter), run_id=invalid)  # type: ignore[arg-type]
    assert counter.executed == 0


@pytest.mark.parametrize("fault", ["select", "cleanup", "pending"])
def test_run_read_owned_cleanup_never_adopts_pending_work(
    pinned: Prepared, monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    conn, run, sources, _, _ = pinned
    execute = psycopg.Connection.execute

    def fail(c: StoreConnection, query: str, *args: object, **kwargs: object) -> object:
        if "JOIN run_inputs" in query:
            return execute(c, 'SELECT "private evidence"')
        return execute(c, query, *args, **kwargs)  # type: ignore[arg-type]

    def broken(c: StoreConnection) -> None:
        raise psycopg.OperationalError("private")

    if fault == "pending":
        conn.execute(
            "UPDATE cases SET title = 'pending caller work' WHERE case_id = %s",
            (sources.case_id,),
        )
    with monkeypatch.context() as patch:
        patch.setattr(psycopg.Connection, "execute", fail)
        if fault == "cleanup":
            patch.setattr(psycopg.Connection, "rollback", broken)
        code = "STORE_NOT_TRANSACTIONAL" if fault == "pending" else "STORE_UNAVAILABLE"
        with pytest.raises(Refusal, match=f"^{code}$") as caught:
            with execution_reads(conn):
                read.read_run_blocks(conn, run_id=run)
        assert caught.value.__cause__ is None
    if fault == "pending":
        assert conn.info.transaction_status is TransactionStatus.INTRANS
        assert conn.execute(
            "SELECT title FROM cases WHERE case_id = %s", (sources.case_id,)
        ).fetchone() == ("pending caller work",)
        conn.rollback()
    else:
        assert (
            conn.closed
            if fault == "cleanup"
            else conn.info.transaction_status is TransactionStatus.IDLE
        )


@pytest.fixture
def delivered(case: tuple[StoreConnection, UUID], tmp_path: Path) -> Delivered:
    """A pinned run over two sources of several blocks each: enough rows for a
    batched read to come back short without coming back empty."""
    conn, case_id = case
    grant(conn, case_id=case_id, user_id=case_id, standing=Standing.WRITER)
    first, second = admit_pack(
        conn,
        BlobStore(tmp_path),
        case_id=case_id,
        documents=[
            Document(BoundaryText.of("report.txt"), b"one\ntwo\nthree"),
            Document(BoundaryText.of("note.txt"), b"four\nfive"),
        ],
    )
    conn.commit()
    sources = snapshot_source_set(conn, case_id)
    run = start_run(conn, case_id)
    route = resolve_route(
        json.loads(CATALOG_PATH.read_text()), PROFILE, "MARKET_DISLOCATION"
    )
    pin_route(conn, run, route)
    pin_run_input(
        conn, run, sources.version, Bundle(CATALOG_PATH.parents[3]), subject=SUBJECT
    )
    return conn, run, first, second


def test_delivered_blocks_cost_one_query_per_run(delivered: Delivered) -> None:
    conn, run, first, second = delivered
    counter = _CountingConnection(conn)
    rows = read.read_run_blocks(cast(StoreConnection, counter), run_id=run)
    expected = sorted(
        (source, f"b{index:06d}", 1, word)
        for source, words in (
            (first, ("one", "two", "three")),
            (second, ("four", "five")),
        )
        for index, word in enumerate(words)
    )
    assert [
        (source, block, page, text.value) for source, block, page, text in rows
    ] == expected
    assert counter.executed == read.IO_BUDGET == 1


def test_batched_run_blocks_refuse_when_any_captured_block_is_withdrawn(
    delivered: Delivered,
) -> None:
    conn, run, _, second = delivered
    conn.execute(
        "UPDATE sources SET withdrawn_at = now() WHERE source_id = %s", (second,)
    )
    with pytest.raises(Refusal, match=r"^EVIDENCE_NOT_AVAILABLE$") as caught:
        read.read_run_blocks(conn, run_id=run)
    assert caught.value.__cause__ is None
    assert "four" not in "".join(traceback.format_exception(caught.value))


def test_a_store_fault_in_the_batched_read_is_not_an_evidence_verdict(
    delivered: Delivered, monkeypatch: pytest.MonkeyPatch
) -> None:
    conn, run, _, _ = delivered
    execute = psycopg.Connection.execute

    def fail(c: StoreConnection, query: str, *args: object, **kwargs: object) -> object:
        if query.startswith("WITH captured AS ("):
            return execute(c, 'SELECT "private evidence"')
        return execute(c, query, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(psycopg.Connection, "execute", fail)
    with pytest.raises(Refusal, match=r"^STORE_UNAVAILABLE$") as caught:
        read.read_run_blocks(conn, run_id=run)
    assert caught.value.__cause__ is None
    assert "private evidence" not in "".join(traceback.format_exception(caught.value))

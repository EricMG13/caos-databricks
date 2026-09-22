"""Phase 2: bytes enter a case one way, and the whole pack enters or none of it.

`SYSTEM_SPEC.md` section 5: ingestion is the only way bytes enter a case, web
discovery is structurally absent, and a pack is admitted or refused in one
transaction. Invariant 1 is that runs execute against pinned sources; a pack that
half-landed is a source set nobody pinned.

The block shape is the other subject here. `docs/AI_CODE_QUALITY.md` section 1
measures excessive I/O at ~8x, the largest multiple in the report, and the
predecessor had exactly that defect: evidence blocks lived in one JSON column, so
every `read_evidence` parsed every block of a source. Blocks are one row each,
keyed by `(source_id, block_id)`, and `test_a_block_is_one_row_not_a_column`
is what stops that coming back.
"""

from __future__ import annotations

from pathlib import Path
from uuid import UUID, uuid4

import pytest

from caos.blobs import BlobStore
from caos.boundary_text import BoundaryText
from caos.evidence.ingest import Document, admit_pack
from caos.refusals import Refusal, RefusalCode
from caos.store import StoreConnection

REPORT = b"""Acme Holdings plc
Annual report 2026

Total debt at 31 December 2026 was USD 1,240.0m.
Cash and equivalents stood at USD 310.5m.
"""

MEMO = b"""Credit memo
Leverage is 3.4x on a net basis.
"""


@pytest.fixture
def blobs(tmp_path: Path) -> BlobStore:
    return BlobStore(tmp_path / "blobs")


def _document(name: str, data: bytes) -> Document:
    return Document(filename=BoundaryText.of(name), data=data)


def _count(conn: StoreConnection, table: str) -> int:
    # `table` is a literal from this module, never caller input.
    row = conn.execute(f"SELECT count(*) FROM {table}").fetchone()
    assert row is not None
    return int(row[0])


def test_an_admitted_pack_stores_its_sources_blocks_and_tokens(
    case: tuple[StoreConnection, UUID], blobs: BlobStore
) -> None:
    conn, case_id = case

    source_ids = admit_pack(
        conn,
        blobs,
        case_id=case_id,
        documents=[_document("annual-report.txt", REPORT), _document("memo.txt", MEMO)],
    )

    assert len(source_ids) == 2
    assert _count(conn, "live_sources") == 2
    assert _count(conn, "source_blocks") > 0
    assert _count(conn, "source_tokens") > 0
    # The bytes went to the blob store; the row holds the address, never the text.
    row = conn.execute(
        "SELECT document_sha256 FROM live_sources WHERE source_id = %s",
        (source_ids[0],),
    ).fetchone()
    assert row is not None
    assert blobs.get(row[0]) == REPORT


def test_a_pack_is_admitted_whole_or_not_at_all(
    case: tuple[StoreConnection, UUID], blobs: BlobStore
) -> None:
    """One unreadable document refuses the pack. A half-admitted pack is a
    source set that names documents nobody agreed to run against."""
    conn, case_id = case

    with pytest.raises(Refusal) as caught:
        admit_pack(
            conn,
            blobs,
            case_id=case_id,
            documents=[
                _document("annual-report.txt", REPORT),
                _document("scan.txt", b"\xff\xfe\x00 not text at all"),
            ],
        )

    assert caught.value.code is RefusalCode.SOURCE_NOT_READABLE
    assert _count(conn, "live_sources") == 0
    assert _count(conn, "source_blocks") == 0
    assert _count(conn, "source_tokens") == 0


def test_an_empty_pack_is_refused(
    case: tuple[StoreConnection, UUID], blobs: BlobStore
) -> None:
    conn, case_id = case

    with pytest.raises(Refusal) as caught:
        admit_pack(conn, blobs, case_id=case_id, documents=[])

    assert caught.value.code is RefusalCode.SOURCE_PACK_EMPTY


def test_a_document_with_no_extractable_text_is_refused(
    case: tuple[StoreConnection, UUID], blobs: BlobStore
) -> None:
    """A scanned page is readable bytes and no text. Admitting it would put a
    source in the pinned set that can never support a citation -- invariant 11
    would refuse every quote naming it, at artifact time rather than here."""
    conn, case_id = case

    with pytest.raises(Refusal) as caught:
        admit_pack(
            conn,
            blobs,
            case_id=case_id,
            documents=[_document("scan.txt", b"   \n\n  \n")],
        )

    assert caught.value.code is RefusalCode.SOURCE_HAS_NO_TEXT
    assert _count(conn, "sources") == 0


def test_the_refusal_carries_none_of_the_document(
    case: tuple[StoreConnection, UUID], blobs: BlobStore
) -> None:
    """Never log document-derived text (CLAUDE.md). The refusal that names an
    unreadable document must not quote it, or the log line does."""
    conn, case_id = case

    with pytest.raises(Refusal) as caught:
        admit_pack(
            conn,
            blobs,
            case_id=case_id,
            documents=[_document("scan.txt", b"\xff\xfe\x00 not text at all")],
        )

    assert str(caught.value) == RefusalCode.SOURCE_NOT_READABLE.value
    assert "scan.txt" not in repr(caught.value)


def test_a_block_is_one_row_not_a_column(
    case: tuple[StoreConnection, UUID], blobs: BlobStore
) -> None:
    """The ~8x defect, refused structurally rather than by a budget.

    Reading one block must be one row fetch. If blocks lived in a JSON column on
    the source row there would be nothing to fetch one of, so this asserts the
    shape: a primary key of `(source_id, block_id)` that a single-row SELECT can
    use.
    """
    conn, case_id = case
    [source_id] = admit_pack(
        conn, blobs, case_id=case_id, documents=[_document("memo.txt", MEMO)]
    )

    blocks = conn.execute(
        "SELECT block_id FROM source_blocks WHERE source_id = %s ORDER BY block_id",
        (source_id,),
    ).fetchall()

    assert len(blocks) > 1, "a source is many blocks, not one document-shaped row"
    one = conn.execute(
        "SELECT text FROM source_blocks WHERE source_id = %s AND block_id = %s",
        (source_id, blocks[0][0]),
    ).fetchone()
    assert one is not None


def test_every_token_carries_its_page_region_line_and_rectangle(
    case: tuple[StoreConnection, UUID], blobs: BlobStore
) -> None:
    """Invariant 11 rests on these four. A token without a region cannot stop a
    quote being assembled across a column gutter (`SYSTEM_SPEC.md` section 5)."""
    conn, case_id = case
    [source_id] = admit_pack(
        conn, blobs, case_id=case_id, documents=[_document("memo.txt", MEMO)]
    )

    incomplete = conn.execute(
        "SELECT count(*) FROM source_tokens WHERE source_id = %s AND ("
        " page IS NULL OR region_id IS NULL OR line_id IS NULL"
        " OR x0 IS NULL OR y0 IS NULL OR x1 IS NULL OR y1 IS NULL)",
        (source_id,),
    ).fetchone()

    assert incomplete is not None
    assert incomplete[0] == 0


def test_a_withdrawn_source_leaves_the_live_view(
    case: tuple[StoreConnection, UUID], blobs: BlobStore
) -> None:
    """`live_sources` is how sources are read (`docs/DECISIONS.md` §45).

    Withdrawal's full contract -- refused at every use, re-opening the plan gate
    -- is owed by Phase 6 with its own named test. What is here is the view the
    refusal will be read through, so nothing later has to remember to filter.
    """
    conn, case_id = case
    [source_id] = admit_pack(
        conn, blobs, case_id=case_id, documents=[_document("memo.txt", MEMO)]
    )
    assert _count(conn, "live_sources") == 1

    conn.execute(
        "UPDATE sources SET withdrawn_at = now() WHERE source_id = %s", (source_id,)
    )

    assert _count(conn, "live_sources") == 0
    assert _count(conn, "sources") == 1, "withdrawal hides a source, never deletes it"


def test_a_pack_for_a_case_that_does_not_exist_is_refused(
    case: tuple[StoreConnection, UUID], blobs: BlobStore
) -> None:
    conn, _case_id = case

    with pytest.raises(Refusal) as caught:
        admit_pack(
            conn,
            blobs,
            case_id=uuid4(),
            documents=[_document("memo.txt", MEMO)],
        )

    assert caught.value.code is RefusalCode.CASE_NOT_FOUND


@pytest.mark.parametrize(
    ("body", "code"),
    [
        pytest.param(
            "Total debt \N{RIGHT-TO-LEFT OVERRIDE} was USD 1,240.0m",
            RefusalCode.BOUNDARY_TEXT_INVALID,
            id="a line carrying an override control",
        ),
    ],
)
def test_a_document_the_boundary_refuses_never_reaches_the_pinned_set(
    case: tuple[StoreConnection, UUID], tmp_path: Path, body: str, code: RefusalCode
) -> None:
    """`source_blocks.text` is pinned state, so the boundary belongs at the door.

    It was applied on the way out instead: `read_evidence` calls
    `BoundaryText.of` and admission wrote a bare `str`. So text over the
    boundary's limit, and a line carrying the override control the boundary
    exists to refuse, were both admitted -- into the set a SOURCE_SET gate can
    then be approved over -- and refused at every later read. That is
    `admit_pack`'s own argument against admitting a document with no text, one
    run and one provider bill later than here.

    **Only the malformed case is left here, and the change is deliberate.** A
    *line* over the limit is split at `GROUP_WIDTH` (`test_line_groups.py`) and
    a single *word* over it is now split at `MAX_TOKEN_CHARS`
    (`test_long_tokens.py`) -- this docstring used to say a word "has nowhere to
    be split", which the extractor's own bound made false. What the boundary
    still refuses at the door is text it cannot represent rather than text that
    is merely long: an override control in a run of any length still refuses
    here, because each split piece is checked exactly as the whole run was.
    """
    conn, case_id = case
    blobs = BlobStore(tmp_path / "blobs")

    with pytest.raises(Refusal) as caught:
        admit_pack(
            conn,
            blobs,
            case_id=case_id,
            documents=[
                Document(filename=BoundaryText.of("report.txt"), data=body.encode())
            ],
        )

    assert caught.value.code is code
    left = conn.execute(
        "SELECT count(*) FROM sources WHERE case_id = %s", (case_id,)
    ).fetchone()
    assert left is not None and left[0] == 0

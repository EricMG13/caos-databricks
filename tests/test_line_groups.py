"""A line wider than a block, through the paths that admit and cite it.

`SYSTEM_SPEC.md` section 5 packs blocks "one per line while small, bounded line
groups once not, splitting a line at the group width rather than giving it a
block of its own". The width is not a free parameter: `source_blocks.text` is
`BoundaryText`, so a block can carry `boundary_text.DEFAULT_LIMIT` characters
and no more, and a line past that refused the whole pack -- one wide table row
in a text export and no document of it could be admitted at all.

The property these tests hold is the one splitting must not cost: a document
whose lines fit is numbered exactly as it was before there was any splitting,
because `source_blocks` rows are immutable and stored citations name ids that
already exist.
"""

from __future__ import annotations

from pathlib import Path
from uuid import UUID

import pytest

from caos.blobs import BlobStore
from caos.boundary_text import BoundaryText
from caos.evidence.citations import Citation, verify_citations
from caos.evidence.ingest import GROUP_WIDTH, Document, admit_pack
from caos.refusals import Refusal, RefusalCode
from caos.store import StoreConnection

# Six characters a word, so the group boundary falls inside a word rather than
# politely between two: the awkward case is the one worth fixturing.
WIDE_WORDS = [f"w{n:04d}" for n in range(900)]
WIDE_LINE = " ".join(WIDE_WORDS)
DOCUMENT = ("Annual report of the issuer\n" + WIDE_LINE + "\nSigned\n").encode()
NARROW = "\n".join(f"Section {n} of the annual report" for n in range(12)).encode()


def _admit(conn: StoreConnection, case_id: UUID, tmp_path: Path, data: bytes) -> UUID:
    [source_id] = admit_pack(
        conn,
        BlobStore(tmp_path / "blobs"),
        case_id=case_id,
        documents=[Document(filename=BoundaryText.of("wide.txt"), data=data)],
    )
    return source_id


def _blocks(conn: StoreConnection, source_id: UUID) -> list[tuple[str, str]]:
    return [
        (str(block_id), str(text))
        for block_id, text in conn.execute(
            "SELECT block_id, text FROM source_blocks WHERE source_id = %s"
            " ORDER BY block_id",
            (source_id,),
        ).fetchall()
    ]


def test_a_line_wider_than_the_group_is_split_rather_than_refusing_the_pack(
    case: tuple[StoreConnection, UUID], tmp_path: Path
) -> None:
    """The wide line becomes bounded blocks, and nothing of it is lost."""
    conn, case_id = case
    assert len(WIDE_LINE) > GROUP_WIDTH

    source_id = _admit(conn, case_id, tmp_path, DOCUMENT)

    blocks = _blocks(conn, source_id)
    assert blocks[0][1] == "Annual report of the issuer"
    assert all(len(text) <= GROUP_WIDTH for _id, text in blocks)
    # Three lines, and only the wide one is more than one block.
    assert len(blocks) == 4
    assert "".join(text for _id, text in blocks[1:3]) == WIDE_LINE


def test_a_quote_crossing_a_group_boundary_needs_every_block_of_its_line(
    case: tuple[StoreConnection, UUID], tmp_path: Path
) -> None:
    """Anchoring reads tokens, so the quote is found either way; delivery is
    line-granular, so half a split line delivers none of it."""
    conn, case_id = case
    source_id = _admit(conn, case_id, tmp_path, DOCUMENT)
    blocks = _blocks(conn, source_id)
    crossing = " ".join(WIDE_WORDS[681:684])
    citation = Citation(source_id=source_id, page=1, matched_text=crossing)

    [anchored] = verify_citations(
        conn,
        delivered={source_id: frozenset(block_id for block_id, _ in blocks)},
        citations=[citation],
    )
    assert anchored.matched_text == crossing

    halved = frozenset({blocks[1][0]})
    with pytest.raises(Refusal, match=r"^CITATION_NOT_DELIVERED$"):
        verify_citations(conn, delivered={source_id: halved}, citations=[citation])


def test_a_document_whose_lines_fit_the_group_is_numbered_one_block_a_line(
    case: tuple[StoreConnection, UUID], tmp_path: Path
) -> None:
    """The numbering every already-admitted document was written under, and the
    one its stored citations name. Splitting must not move it."""
    conn, case_id = case
    source_id = _admit(conn, case_id, tmp_path, NARROW)

    blocks = _blocks(conn, source_id)
    assert [block_id for block_id, _ in blocks] == [f"b{n:06d}" for n in range(12)]
    assert [text for _id, text in blocks] == NARROW.decode().splitlines()

    [anchored] = verify_citations(
        conn,
        delivered={source_id: frozenset(block_id for block_id, _ in blocks)},
        citations=[Citation(source_id, 1, "Section 7 of the annual report")],
    )
    assert anchored.bboxes


def test_a_packing_that_disagrees_with_the_stored_blocks_refuses(
    case: tuple[StoreConnection, UUID], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The recomputation is a derivation, so it is checked against what
    admission actually wrote rather than trusted.

    `_line_blocks` recomputes the packing only when the stored block count is
    not the line count, and then numbers every block from it. The store cannot
    drift underneath it -- migration 0027 seals extracted evidence, so no row
    is inserted, updated or deleted after admission -- but the *rule* can:
    a changed `GROUP_WIDTH` repacks an already-admitted source into a
    different number of blocks, and the ids the recomputation then produces
    are ids admission never wrote. Anchoring against them would ask whether a
    block that does not exist was delivered. It refuses instead -- with a code
    of its own, because the fault is the host's packing rule and not the
    source's liveness: `EVIDENCE_NOT_AVAILABLE`'s clearance, "Pin a live
    source", names an act that cannot help a source that is live.
    """
    conn, case_id = case
    source_id = _admit(conn, case_id, tmp_path, DOCUMENT)
    # The rule this source was admitted under, moved: a quarter of the width
    # packs the wide line into more groups than admission wrote, so the
    # recomputed total no longer equals the stored count.
    monkeypatch.setattr("caos.evidence.citations.GROUP_WIDTH", GROUP_WIDTH // 4)

    with pytest.raises(Refusal, match=r"^EVIDENCE_PACKING_MISMATCH$"):
        verify_citations(
            conn,
            delivered={source_id: frozenset({"b000000"})},
            citations=[Citation(source_id, 1, "Annual report of the issuer")],
        )


def test_a_packing_mismatch_is_an_operators_fault_with_a_clearance_it_can_act_on() -> (
    None
):
    """The refusal above is the host's rule disagreeing with bytes it wrote, so
    no caller act clears it and no retry does either: a permanent 500 whose
    clearance names the one discharge there is, re-admitting the source."""
    from caos.api.app import _STATUS, PERMANENT
    from caos.api.wire import CLEARS

    code = RefusalCode.EVIDENCE_PACKING_MISMATCH
    assert _STATUS[code] == 500
    assert code in PERMANENT
    assert "re-admit" in CLEARS[code].lower()
    assert CLEARS[code] != CLEARS[RefusalCode.EVIDENCE_NOT_AVAILABLE]


def test_a_source_missing_a_block_still_reads_one_block_a_line(
    case: tuple[StoreConnection, UUID], tmp_path: Path
) -> None:
    """Fewer blocks than lines is not a packing, so the packing is not rebuilt.

    Splitting only ever writes more blocks than lines. A source with fewer is
    one a block was removed from -- which migration 0027 seals against, and
    which the suite does deliberately to narrow a delivery below a whole
    source. The missing block is then simply not among the delivered, which is
    `CITATION_NOT_DELIVERED`: an answer about the citation, and the right one.
    Reading it as a disagreement about the rule instead would make the only
    demonstration of that refusal in the tree unreachable.
    """
    conn, case_id = case
    source_id = _admit(conn, case_id, tmp_path, NARROW)
    blocks = _blocks(conn, source_id)
    with conn.transaction():
        conn.execute("ALTER TABLE source_blocks DISABLE TRIGGER evidence_immutable")
        conn.execute(
            "DELETE FROM source_blocks WHERE source_id = %s AND block_id = %s",
            (source_id, blocks[7][0]),
        )
        conn.execute("ALTER TABLE source_blocks ENABLE TRIGGER evidence_immutable")

    citation = Citation(source_id, 1, "Section 7 of the annual report")
    gone = blocks[7][0]
    delivered = frozenset(block_id for block_id, _ in blocks if block_id != gone)
    with pytest.raises(Refusal, match=r"^CITATION_NOT_DELIVERED$"):
        verify_citations(conn, delivered={source_id: delivered}, citations=[citation])

    other = Citation(source_id, 1, "Section 3 of the annual report")
    [anchored] = verify_citations(
        conn, delivered={source_id: delivered}, citations=[other]
    )
    assert anchored.matched_text == other.matched_text

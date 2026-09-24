"""Phase 2 exit tests: the evidence boundary fails closed and says nothing.

Invariant 2 (CLAUDE.md): every `read_evidence` is validated at the host boundary
and refuses with a typed code. **No text is returned on refusal** -- not in the
exception chain, the delivered set, or the ledger. A refusal that quotes the
document it refused is the leak the whole typed-refusal design exists to stop.

Invariant 11: a citation is re-located in the token index and one that cannot be
located exactly once is refused *before it reaches the artifact*, not after.

Excessive I/O was the largest defect measured against exactly this call: the
predecessor parsed every block of a source on every read.
`test_io_budget_read_evidence` counts the round trips rather than trusting
the shape.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import cast
from uuid import UUID, uuid4

import pytest
from conftest import every_block
from psycopg.pq import TransactionStatus

from caos.blobs import BlobStore
from caos.boundary_text import BoundaryText
from caos.evidence.citations import (
    AnchoredCitation,
    Citation,
    Rect,
    anchor_citation,
    verify_citations,
)
from caos.evidence.extract import LINES_PER_PAGE
from caos.evidence.ingest import Document, admit_pack
from caos.evidence.read import IO_BUDGET, Block, read_block, read_evidence
from caos.refusals import Refusal, RefusalCode
from caos.store import StoreConnection, connect

# Line 0 and line 1 are one paragraph, so a quote may wrap between them.
# Line 3 is a second paragraph -- a region a quote from the first may not enter.
REPORT = b"""Total debt at 31 December
2026 was USD 1,240.0m
"""

TWO_REGIONS = b"""Total debt at 31 December

2026 was USD 1,240.0m
"""

TWICE = b"""Leverage is 3.4x
Leverage is 3.4x
"""


class _CountingConnection:
    """Counts store round trips. The budget is a number, so it is measured."""

    def __init__(self, conn: StoreConnection) -> None:
        self._conn = conn
        self.executed = 0

    def execute(self, *args: object, **kwargs: object) -> object:
        self.executed += 1
        return self._conn.execute(*args, **kwargs)  # type: ignore[arg-type]


def _admit(conn: StoreConnection, case_id: UUID, blobs: BlobStore, body: bytes) -> UUID:
    [source_id] = admit_pack(
        conn,
        blobs,
        case_id=case_id,
        documents=[Document(filename=BoundaryText.of("report.txt"), data=body)],
    )
    return source_id


@pytest.fixture
def blobs(tmp_path: Path) -> BlobStore:
    return BlobStore(tmp_path / "blobs")


def _first_block(conn: StoreConnection, source_id: UUID) -> str:
    row = conn.execute(
        "SELECT block_id FROM source_blocks WHERE source_id = %s ORDER BY block_id",
        (source_id,),
    ).fetchone()
    assert row is not None
    return str(row[0])


def test_a_block_is_returned_as_boundary_text(
    case: tuple[StoreConnection, UUID], blobs: BlobStore
) -> None:
    conn, case_id = case
    source_id = _admit(conn, case_id, blobs, REPORT)

    block = read_evidence(
        conn, source_id=source_id, block_id=_first_block(conn, source_id)
    )

    assert isinstance(block, BoundaryText)
    assert block.value == "Total debt at 31 December"


@pytest.mark.parametrize(
    ("source", "block"),
    [
        ("absent", "b000000"),
        ("present", "b999999"),
        ("present", ""),
        ("present", "../../etc/passwd"),
        ("present", "b000000\x00"),
        ("withdrawn", "b000000"),
    ],
)
def test_evidence_refusals_return_no_text(
    case: tuple[StoreConnection, UUID], blobs: BlobStore, source: str, block: str
) -> None:
    """The whole argument surface. Every refusal carries its code and nothing
    that came out of a document."""
    conn, case_id = case
    present = _admit(conn, case_id, blobs, REPORT)
    if source == "withdrawn":
        conn.execute(
            "UPDATE sources SET withdrawn_at = now() WHERE source_id = %s", (present,)
        )
    source_id = uuid4() if source == "absent" else present

    with pytest.raises(Refusal) as caught:
        read_evidence(conn, source_id=source_id, block_id=block)

    leaked = repr(caught.value) + str(caught.value) + repr(caught.value.__cause__)
    assert "Total" not in leaked
    assert "December" not in leaked
    assert caught.value.code.value in leaked


def test_a_withdrawn_source_refuses_the_read(
    case: tuple[StoreConnection, UUID], blobs: BlobStore
) -> None:
    """Invariant 1: withdrawal is checked live at every use, not at pin time."""
    conn, case_id = case
    source_id = _admit(conn, case_id, blobs, REPORT)
    block_id = _first_block(conn, source_id)
    assert read_evidence(conn, source_id=source_id, block_id=block_id)

    conn.execute(
        "UPDATE sources SET withdrawn_at = now() WHERE source_id = %s", (source_id,)
    )

    with pytest.raises(Refusal) as caught:
        read_evidence(conn, source_id=source_id, block_id=block_id)
    assert caught.value.code is RefusalCode.EVIDENCE_NOT_AVAILABLE


def test_io_budget_read_evidence(
    case: tuple[StoreConnection, UUID], blobs: BlobStore
) -> None:
    """One read is one row fetch, not a whole-source parse.

    The predecessor's blocks lived in one JSON column: 17 ms per read at the
    ceiling, ~1.4 s per run. The budget is declared beside the code and counted
    here, so the shape cannot regress quietly.
    """
    conn, case_id = case
    source_id = _admit(conn, case_id, blobs, REPORT)
    block_id = _first_block(conn, source_id)
    counter = _CountingConnection(conn)

    read_evidence(counter, source_id=source_id, block_id=block_id)  # type: ignore[arg-type]

    assert counter.executed == IO_BUDGET == 1


def test_a_quote_on_one_line_returns_one_rectangle(
    case: tuple[StoreConnection, UUID], blobs: BlobStore
) -> None:
    conn, case_id = case
    source_id = _admit(conn, case_id, blobs, REPORT)

    boxes = anchor_citation(
        conn, source_id=source_id, page=1, matched_text="Total debt"
    )

    assert len(boxes) == 1
    assert boxes[0].x0 < boxes[0].x1


def test_a_quote_that_wraps_gets_one_rectangle_per_line(
    case: tuple[StoreConnection, UUID], blobs: BlobStore
) -> None:
    """The QuadPoints shape, and the reason for it: selected text wraps. One
    enclosing rectangle would cover text the quote does not contain, which is
    the predecessor's line-range defect wearing coordinates."""
    conn, case_id = case
    source_id = _admit(conn, case_id, blobs, REPORT)

    boxes = anchor_citation(
        conn, source_id=source_id, page=1, matched_text="31 December 2026 was"
    )

    assert len(boxes) == 2, "a quote across two lines is two rectangles"
    assert boxes[0].y0 != boxes[1].y0


def test_a_quote_cannot_be_assembled_across_a_region(
    case: tuple[StoreConnection, UUID], blobs: BlobStore
) -> None:
    """The column gutter. The same words, in the same order, on adjacent lines --
    but a blank line made them two regions, so the phrase never forms."""
    conn, case_id = case
    source_id = _admit(conn, case_id, blobs, TWO_REGIONS)

    with pytest.raises(Refusal) as caught:
        anchor_citation(
            conn, source_id=source_id, page=1, matched_text="31 December 2026 was"
        )

    assert caught.value.code is RefusalCode.CITATION_NOT_LOCATED


def test_a_quote_that_appears_twice_is_refused(
    case: tuple[StoreConnection, UUID], blobs: BlobStore
) -> None:
    """ "Cannot locate exactly once" is a refusal, not a choice of the first.
    Highlighting one of two identical sentences asserts a precision the host
    does not have."""
    conn, case_id = case
    source_id = _admit(conn, case_id, blobs, TWICE)

    with pytest.raises(Refusal) as caught:
        anchor_citation(
            conn, source_id=source_id, page=1, matched_text="Leverage is 3.4x"
        )

    assert caught.value.code is RefusalCode.CITATION_AMBIGUOUS


def test_an_empty_quote_is_refused(
    case: tuple[StoreConnection, UUID], blobs: BlobStore
) -> None:
    """`matched_text.split()` on whitespace-only text is an empty run, which is
    not a match of zero words -- it is nothing to search for."""
    conn, case_id = case
    source_id = _admit(conn, case_id, blobs, REPORT)

    with pytest.raises(Refusal) as caught:
        anchor_citation(conn, source_id=source_id, page=1, matched_text="   ")

    assert caught.value.code is RefusalCode.CITATION_NOT_LOCATED


def test_verify_citations_refuses_a_delivered_source_with_no_live_row(
    case: tuple[StoreConnection, UUID],
) -> None:
    """A source_id can be in the caller's `delivered` set and still not name a
    live source: the boundary re-checks it against the store rather than
    trusting the set (invariant 3: the host owns identity)."""
    conn, _case_id = case
    phantom = uuid4()

    with pytest.raises(Refusal) as caught:
        verify_citations(
            conn,
            delivered={phantom: frozenset()},
            citations=[Citation(source_id=phantom, page=1, matched_text="Total debt")],
        )

    assert caught.value.code is RefusalCode.EVIDENCE_NOT_AVAILABLE


def test_a_quote_on_the_wrong_page_is_refused(
    case: tuple[StoreConnection, UUID], blobs: BlobStore
) -> None:
    conn, case_id = case
    source_id = _admit(conn, case_id, blobs, REPORT)

    with pytest.raises(Refusal) as caught:
        anchor_citation(conn, source_id=source_id, page=2, matched_text="Total debt")

    assert caught.value.code is RefusalCode.CITATION_NOT_LOCATED


def test_uncitable_quote_is_refused_before_artifact(
    case: tuple[StoreConnection, UUID], blobs: BlobStore
) -> None:
    """The Phase 2 exit test. Verification happens before the artifact is
    written, so an artifact naming a quote nobody can find never exists."""
    conn, case_id = case
    source_id = _admit(conn, case_id, blobs, REPORT)

    with pytest.raises(Refusal) as caught:
        verify_citations(
            conn,
            delivered=every_block(conn, source_id),
            citations=[
                Citation(source_id=source_id, page=1, matched_text="Total debt"),
                Citation(
                    source_id=source_id,
                    page=1,
                    matched_text="Total equity was USD 4,000.0m",
                ),
            ],
        )

    assert caught.value.code is RefusalCode.CITATION_NOT_LOCATED
    row = conn.execute("SELECT count(*) FROM artifacts").fetchone()
    assert row is not None and row[0] == 0


def test_a_citation_may_only_name_evidence_that_was_delivered(
    case: tuple[StoreConnection, UUID], blobs: BlobStore
) -> None:
    """A module may cite what it was
    given and nothing else -- including a real source in the same case."""
    conn, case_id = case
    delivered = _admit(conn, case_id, blobs, REPORT)
    other = _admit(conn, case_id, blobs, TWICE)

    with pytest.raises(Refusal) as caught:
        verify_citations(
            conn,
            delivered=every_block(conn, delivered),
            citations=[
                Citation(source_id=other, page=1, matched_text="Leverage is 3.4x")
            ],
        )

    assert caught.value.code is RefusalCode.CITATION_NOT_DELIVERED


def test_verified_citations_come_back_with_their_rectangles(
    case: tuple[StoreConnection, UUID], blobs: BlobStore
) -> None:
    conn, case_id = case
    source_id = _admit(conn, case_id, blobs, REPORT)

    anchored = verify_citations(
        conn,
        delivered=every_block(conn, source_id),
        citations=[Citation(source_id=source_id, page=1, matched_text="Total debt")],
    )

    assert len(anchored) == 1
    [citation] = anchored
    assert isinstance(citation, AnchoredCitation)
    assert citation.document_sha256, "the artifact names the document, not the row id"
    [box] = citation.bboxes
    assert isinstance(box, Rect)
    # The host derived these; the module supplied only page and matched_text.
    assert box.page == 1
    assert box.x0 < box.x1 and box.y0 < box.y1


def test_a_block_carries_the_page_it_sits_on(
    case: tuple[StoreConnection, UUID], blobs: BlobStore
) -> None:
    """`read_block` answers with the page as well as the text, in one row fetch.

    The page is the host's to know: a module that is told the wrong one cites
    the wrong one, and invariant 11 then refuses a quote that is really there.
    """
    conn, case_id = case
    body = "\n".join(f"filler line {n}" for n in range(LINES_PER_PAGE))
    source_id = _admit(
        conn, case_id, blobs, f"{body}\nTotal debt at 31 December\n".encode()
    )

    row = conn.execute(
        "SELECT block_id FROM source_blocks WHERE source_id = %s"
        " ORDER BY block_id DESC",
        (source_id,),
    ).fetchone()
    assert row is not None
    counter = _CountingConnection(conn)

    block = read_block(counter, source_id=source_id, block_id=str(row[0]))  # type: ignore[arg-type]

    assert isinstance(block, Block)
    assert block.page == 2
    assert block.text.value == "Total debt at 31 December"
    assert counter.executed == IO_BUDGET == 1


def test_read_block_refuses_what_read_evidence_refuses(
    case: tuple[StoreConnection, UUID], blobs: BlobStore
) -> None:
    """One boundary, not two. A second path to a block is a second place the
    live-source check could be forgotten (invariant 1)."""
    conn, case_id = case
    source_id = _admit(conn, case_id, blobs, REPORT)
    block_id = _first_block(conn, source_id)
    conn.execute(
        "UPDATE sources SET withdrawn_at = now() WHERE source_id = %s", (source_id,)
    )

    with pytest.raises(Refusal) as caught:
        read_block(conn, source_id=source_id, block_id=block_id)

    assert caught.value.code is RefusalCode.EVIDENCE_NOT_AVAILABLE


@pytest.mark.parametrize("reader", [read_block, read_evidence])
@pytest.mark.parametrize(
    "source,block",
    [
        (None, "b000000"),
        (str(UUID(int=0)), "b000000"),
        (1, "b000000"),
        (UUID(int=0), None),
        (UUID(int=0), b"b000000"),
        (UUID(int=0), "b\u0661\u0662\u0663\u0664\u0665\u0666"),
        (UUID(int=0), "b0000000"),
    ],
)
def test_invalid_evidence_arguments_refuse_before_sql(
    case: tuple[StoreConnection, UUID],
    reader: Callable[..., object],
    source: object,
    block: object,
) -> None:
    counter = _CountingConnection(case[0])
    with pytest.raises(Refusal, match=r"^EVIDENCE_NOT_AVAILABLE$") as caught:
        reader(
            cast(StoreConnection, counter),
            source_id=cast(UUID, source),
            block_id=cast(str, block),
        )
    assert caught.value.__cause__ is None
    assert counter.executed == 0


@pytest.mark.parametrize(
    "block_id,text,code",
    [
        ("b000000", "legacy", None),
        ("b999999", "legacy", None),
        ("b1000000", "legacy", None),
        ("b000000", "private\x01", "BOUNDARY_TEXT_INVALID"),
        ("b000000", "private" * 600, "BOUNDARY_TEXT_TOO_LONG"),
    ],
)
def test_unknown_evidence_retains_minted_ids_and_boundary_text_refusals(
    case: tuple[StoreConnection, UUID], block_id: str, text: str, code: str | None
) -> None:
    conn, case_id = case
    source = uuid4()
    conn.execute(
        "INSERT INTO sources (source_id,case_id,document_sha256,filename)"
        " VALUES (%s,%s,%s,%s)",
        (source, case_id, "0" * 64, "legacy"),
    )
    # UNKNOWN historical rows retain native insert/immutability guards.
    conn.execute(
        "INSERT INTO source_blocks VALUES (%s,%s,2,%s)", (source, block_id, text)
    )
    counter = _CountingConnection(conn)
    if code is None:
        block = read_block(
            cast(StoreConnection, counter), source_id=source, block_id=block_id
        )
        assert block == Block(page=2, text=BoundaryText.of(text))
    else:
        with pytest.raises(Refusal, match=f"^{code}$") as caught:
            read_block(
                cast(StoreConnection, counter), source_id=source, block_id=block_id
            )
        assert caught.value.__cause__ is None
        assert caught.value.__suppress_context__
        assert "private" not in repr(caught.value)
    assert counter.executed == IO_BUDGET == 1


@pytest.mark.parametrize("reader", [read_block, read_evidence])
@pytest.mark.parametrize("failure", [False, True])
def test_generic_read_preserves_caller_work_and_sanitizes_native_failure(
    case: tuple[StoreConnection, UUID],
    blobs: BlobStore,
    empty_database: str,
    reader: Callable[..., object],
    failure: bool,
) -> None:
    conn, case_id = case
    source = _admit(conn, case_id, blobs, REPORT)
    conn.commit()
    conn.execute(
        "UPDATE cases SET title = 'pending caller work' WHERE case_id = %s", (case_id,)
    )
    conn.execute("SAVEPOINT evidence_read")
    if failure:
        conn.execute("ALTER TABLE source_blocks RENAME TO private_evidence")
        with pytest.raises(Refusal, match=r"^EVIDENCE_NOT_AVAILABLE$") as caught:
            reader(conn, source_id=source, block_id="b000000")
        assert caught.value.__cause__ is None
        assert caught.value.__suppress_context__
        assert "private" not in repr(caught.value)
        assert conn.info.transaction_status is TransactionStatus.INERROR
        conn.execute("ROLLBACK TO SAVEPOINT evidence_read")
    else:
        assert reader(conn, source_id=source, block_id="b000000")
        assert conn.info.transaction_status is TransactionStatus.INTRANS
    assert conn.execute(
        "SELECT title FROM cases WHERE case_id = %s", (case_id,)
    ).fetchone() == ("pending caller work",)
    with connect(empty_database) as observer:
        assert observer.execute(
            "SELECT title FROM cases WHERE case_id = %s", (case_id,)
        ).fetchone() != ("pending caller work",)
    conn.rollback()
    assert conn.execute(
        "SELECT title FROM cases WHERE case_id = %s", (case_id,)
    ).fetchone() != ("pending caller work",)

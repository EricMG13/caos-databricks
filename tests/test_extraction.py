"""Tokens carry where they were, and a region is what a quote may not leave.

`SYSTEM_SPEC.md` section 5: matching joins tokens within a line and continues
only onto the next line of the same region, so a quote cannot be assembled across
a column gutter -- the two columns are different regions and the phrase never
forms. Everything invariant 11 refuses rests on the region boundary being drawn
here, at extraction, by whatever produced the tokens.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

import pytest

from caos.blobs import BlobStore
from caos.boundary_text import BoundaryText
from caos.evidence.citations import anchor_citation
from caos.evidence.extract import (
    CELL_WIDTH,
    LINES_PER_PAGE,
    MARGIN,
    Extractor,
    ExtractorIdentity,
    PlainTextExtractor,
    Token,
)
from caos.evidence.ingest import Document, admit_pack
from caos.refusals import Refusal, RefusalCode
from caos.store import StoreConnection

TWO_PARAGRAPHS = b"""Total debt at 31 December 2026
was USD 1,240.0m.

Cash stood at USD 310.5m.
"""


def test_a_blank_line_starts_a_new_region() -> None:
    """The boundary a quote may not cross. Two lines of one paragraph share a
    region; a line after a blank one does not."""
    tokens = PlainTextExtractor().extract(TWO_PARAGRAPHS)

    # Words unique to one paragraph. "USD" appears in both, so keying on it
    # would compare the second occurrence with itself and pass either way.
    regions = {token.text: token.region_id for token in tokens}

    assert regions["Total"] == regions["1,240.0m."], (
        "two lines of one paragraph are one region"
    )
    assert regions["Cash"] != regions["Total"], "a blank line closes the region"


def test_lines_of_one_paragraph_keep_their_own_line_ids() -> None:
    tokens = PlainTextExtractor().extract(TWO_PARAGRAPHS)
    lines = {token.text: token.line_id for token in tokens}

    assert lines["Total"] == 0
    assert lines["was"] == 1


def test_a_token_measures_the_columns_it_occupies() -> None:
    """A rectangle that is wider than the word would highlight text the quote
    does not contain, which is the predecessor's line-range defect wearing
    coordinates (`SYSTEM_SPEC.md` section 5)."""
    [token] = PlainTextExtractor().extract(b"Leverage\n")

    assert token.x0 == MARGIN
    assert token.x1 == pytest.approx(MARGIN + len("Leverage") * CELL_WIDTH)
    assert token.page == 1


def test_a_word_after_a_gap_starts_at_its_own_column() -> None:
    tokens = PlainTextExtractor().extract(b"net    leverage\n")
    columns = {token.text: token.x0 for token in tokens}

    assert columns["leverage"] == pytest.approx(MARGIN + len("net    ") * CELL_WIDTH)


def test_a_long_document_runs_onto_a_second_page() -> None:
    body = b"\n".join(b"line %d" % n for n in range(LINES_PER_PAGE + 2))
    pages = {token.page for token in PlainTextExtractor().extract(body)}

    assert pages == {1, 2}


def test_bytes_that_are_not_text_are_refused_without_quoting_them() -> None:
    with pytest.raises(Refusal) as caught:
        PlainTextExtractor().extract(b"\xff\xfe\x00 not text")

    assert caught.value.code is RefusalCode.SOURCE_NOT_READABLE
    assert str(caught.value) == RefusalCode.SOURCE_NOT_READABLE.value


def test_a_leading_byte_order_mark_is_the_encodings_and_never_text(
    tmp_path: Path, case: tuple[StoreConnection, UUID]
) -> None:
    """CF-017: a text exported with a byte order mark kept it as the first
    word's first character, so the document's first line was never quoted as
    it reads and every cell on it sat one column late. v4 decodes
    `utf-8-sig`: the mark is the encoding's, the first word starts at the
    margin, and the first line anchors as it is shown. A U+FEFF anywhere
    else is text, as it always was."""
    tokens = PlainTextExtractor().extract("\ufeff".encode() + TWO_PARAGRAPHS)
    assert tokens == PlainTextExtractor().extract(TWO_PARAGRAPHS)
    assert tokens[0].text == "Total" and tokens[0].x0 == MARGIN
    [inner, after] = PlainTextExtractor().extract("a\ufeffb c".encode())
    assert inner.text == "a\ufeffb" and after.text == "c"
    assert PlainTextExtractor().identity.config["encoding"] == "utf-8-sig"

    conn, case_id = case
    [source_id] = admit_pack(
        conn,
        BlobStore(tmp_path / "blobs"),
        case_id=case_id,
        documents=[
            Document(
                filename=BoundaryText.of("bom.txt"),
                data="\ufeff".encode() + TWO_PARAGRAPHS,
            )
        ],
    )
    [rect] = anchor_citation(
        conn,
        source_id=source_id,
        page=1,
        matched_text="Total debt at 31 December 2026",
    )
    assert rect.x0 == MARGIN


@dataclass(frozen=True, slots=True)
class _OneTokenExtractor:
    """A stand-in for the PDF extractor Phase 6 owes: different bytes, same
    protocol, and nothing above this seam knows the difference."""

    identity = ExtractorIdentity("test.one-token", "1", {})

    def extract(self, data: bytes, **_kwargs: object) -> list[Token]:
        return [
            Token(
                text="Leverage",
                page=7,
                region_id=3,
                line_id=11,
                x0=100.0,
                y0=200.0,
                x1=157.6,
                y1=212.0,
            )
        ]


def test_ingestion_takes_any_extractor(
    tmp_path: Path, case: tuple[StoreConnection, UUID]
) -> None:
    """`Extractor` is a seam, not a formality. The coordinates a different
    extractor reports are the coordinates that reach `source_tokens`."""
    conn, case_id = case
    blobs = BlobStore(tmp_path / "blobs")
    extractor: Extractor = _OneTokenExtractor()

    [source_id] = admit_pack(
        conn,
        blobs,
        case_id=case_id,
        documents=[Document(filename=BoundaryText.of("report.pdf"), data=b"%PDF-1.7")],
        dispatch=lambda data: extractor,
    )

    row = conn.execute(
        "SELECT page, region_id, line_id, x0, x1 FROM source_tokens"
        " WHERE source_id = %s",
        (source_id,),
    ).fetchone()
    assert row is not None
    assert row[:3] == (7, 3, 11)
    assert (row[3], row[4]) == (100.0, 157.6)


def test_a_token_never_holds_the_whitespace_a_quote_is_split_on() -> None:
    """The round trip `read_evidence` promises: text this repository delivered
    can be quoted back to it.

    `caos/evidence/citations.py` splits `matched_text` with `str.split()`,
    which separates every whitespace class. A token holding an interior tab is
    therefore one the index can never be asked for: the line reaches a module
    through `read_evidence` and the verbatim quote of it is refused
    `CITATION_NOT_LOCATED`. The extractor and the matcher have to draw the word
    boundary in the same place, or the evidence a module was handed is evidence
    it cannot cite.
    """
    line = "Total\tdebt\N{NO-BREAK SPACE}was USD 1,240.0m"
    tokens = PlainTextExtractor().extract(line.encode())

    assert [token.text for token in tokens] == line.split()


def test_a_tab_advances_the_column_like_any_other_cell() -> None:
    """The rectangles stay a reproducible fixed-pitch rendering: one cell per
    character, whichever character it is."""
    [_total, debt] = PlainTextExtractor().extract(b"Total\tdebt")

    assert debt.x0 == MARGIN + len("Total\t") * CELL_WIDTH

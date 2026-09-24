"""N28 (CF-016, D39 "Host enforces whole lines"): a citation accepted with an
answer is one whole evidence line as the module was shown it.

The final check tells a module that `matched_text` is "the complete text of one
evidence line" and that the line appears exactly once on its cited page. The
host used to accept any unique run of tokens, so a fragment that dropped a
"not" anchored and reached the committee page as a host-verified source fact
(AI-4, `docs/rebuild/findings-round2.md`). An answer is now held to the rule it
was given (`WHOLE_LINE`), while a record accepted before is re-anchored by the
rule it was accepted under (`ANY_RUN`), which it names.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path
from uuid import UUID

import pytest
from conftest import every_block
from test_pdf_extraction import _assemble, _ingest_pdf, _objects

from caos.blobs import BlobStore
from caos.boundary_text import BoundaryText
from caos.evidence.citations import (
    ANY_RUN,
    CITATION_RULES,
    WHOLE_LINE,
    WHOLE_LINE_AS_STORED,
    Citation,
    CitationRule,
    _line_run,
    _Page,
    _shown,
    _shown_line_run,
    _Token,
    _token_spans,
    _width_spans,
    verify_citations,
)
from caos.evidence.ingest import GROUP_WIDTH, Document, admit_pack
from caos.refusals import Refusal, RefusalCode
from caos.store import StoreConnection

LINE = "The Company did not breach its leverage covenant during FY2025."
PART_OF_LINE = "breach its leverage covenant during FY2025."
DOCUMENT = (
    f"{LINE}\nLiquidity\nLiquidity was USD 310.5m at year end.\n\n"
    "Repeated line\nRepeated line\n"
).encode()


def _admit(conn: StoreConnection, case_id: UUID, tmp_path: Path) -> UUID:
    [source_id] = admit_pack(
        conn,
        BlobStore(tmp_path / "blobs"),
        case_id=case_id,
        documents=[Document(filename=BoundaryText.of("memo.txt"), data=DOCUMENT)],
    )
    return source_id


def _code(
    conn: StoreConnection,
    source_id: UUID,
    quote: str,
    rule: CitationRule = WHOLE_LINE,
) -> RefusalCode | int:
    """The refusal a quote meets under `rule`, or how many rectangles it got."""
    try:
        [anchored] = verify_citations(
            conn,
            delivered=every_block(conn, source_id),
            citations=[Citation(source_id, 1, quote)],
            rule=rule,
        )
    except Refusal as refused:
        return refused.code
    return len(anchored.bboxes)


def test_part_of_a_line_that_drops_a_word_no_longer_anchors(
    case: tuple[StoreConnection, UUID], tmp_path: Path
) -> None:
    """AI-4: the part anchored uniquely and was labelled host-verified,
    stating the opposite of its line. Accepted answers are held to the whole
    line; the run rule a stored record was accepted under still finds it."""
    conn, case_id = case
    source_id = _admit(conn, case_id, tmp_path)

    assert _code(conn, source_id, LINE) == 1
    assert _code(conn, source_id, PART_OF_LINE) is RefusalCode.CITATION_NOT_LOCATED
    assert _code(conn, source_id, "The Company did not breach") is (
        RefusalCode.CITATION_NOT_LOCATED
    )
    # A quote that runs onto the next line is two lines, not one.
    assert _code(conn, source_id, f"{LINE} Liquidity") is (
        RefusalCode.CITATION_NOT_LOCATED
    )
    assert _code(conn, source_id, PART_OF_LINE, ANY_RUN) == 1
    assert CITATION_RULES == {ANY_RUN, WHOLE_LINE_AS_STORED, WHOLE_LINE}


def test_a_whole_line_keeps_the_edge_forgiveness_the_matcher_declares(
    case: tuple[StoreConnection, UUID], tmp_path: Path
) -> None:
    """Only the edge punctuation the normalised pass already forgives: a
    sentence's full stop and quotation marks at either end of the line."""
    conn, case_id = case
    source_id = _admit(conn, case_id, tmp_path)

    assert _code(conn, source_id, LINE.rstrip(".")) == 1
    assert _code(conn, source_id, f"\u201c{LINE}\u201d") == 1
    assert _code(conn, source_id, LINE.replace("did not", "did")) is (
        RefusalCode.CITATION_NOT_LOCATED
    )


def test_a_line_is_one_line_however_often_its_words_recur(
    case: tuple[StoreConnection, UUID], tmp_path: Path
) -> None:
    """ "That line must appear exactly once on its cited page": a heading
    whose word recurs inside another line is one line, and anchors; two lines
    that read the same are two, and refuse. The run rule counted the word."""
    conn, case_id = case
    source_id = _admit(conn, case_id, tmp_path)

    assert _code(conn, source_id, "Liquidity") == 1
    assert _code(conn, source_id, "Liquidity", ANY_RUN) is (
        RefusalCode.CITATION_AMBIGUOUS
    )
    assert _code(conn, source_id, "Repeated line") is RefusalCode.CITATION_AMBIGUOUS


def _line(line_id: int, *words: str, region: int = 0) -> list[_Token]:
    return [
        _Token(word, region, line_id, float(at), 0.0, float(at) + 1.0, 1.0)
        for at, word in enumerate(words)
    ]


@pytest.mark.parametrize("locate", [_line_run, _shown_line_run])
def test_tracked_letters_join_within_their_line_and_never_across_two(
    locate: Callable[..., tuple[list[_Token], str]],
) -> None:
    """A heading tracked into single letters is quoted as the word a reader
    sees, on a tracking extractor only, and only inside its own line -- under
    both whole-line rules."""
    page = _Page([*_line(0, "H", "e", "a", "d"), *_line(1, "i", "n", "g")])
    lines = {0: ("B000000",), 1: ("B000001",)}

    ([joined], block_id) = locate(page, None, lines, "Head", tracking=True)
    assert joined.text == "Head"
    assert block_id == "B000000"
    with pytest.raises(Refusal, match=r"^CITATION_NOT_LOCATED$"):
        locate(page, None, lines, "Head", tracking=False)
    with pytest.raises(Refusal, match=r"^CITATION_NOT_LOCATED$"):
        locate(page, None, lines, "Heading", tracking=True)
    with pytest.raises(Refusal, match=r"^CITATION_NOT_LOCATED$"):
        locate(page, None, lines, "   ", tracking=True)
    # The line as shown comes first: its letters one by one are one line.
    assert locate(page, None, lines, "H e a d", tracking=True)[1] == "B000000"


def test_each_block_of_a_token_cut_line_is_a_line_of_its_own() -> None:
    """Packing 2: a wide line was shown as the blocks admission cut it into,
    each read back by the pieces it holds (`_walk`) and paired with the one
    block id it is; a cut that does not tile the line is the host's own rows
    failing, never the citation's."""
    line = _line(7, "a", "b", "c", "d", "e")
    lines = {7: ("B000000", "B000001")}
    assert _shown(line, {7: (2, 3)}, lines) == [
        (line[:2], "B000000"),
        (line[2:], "B000001"),
    ]
    for cut in ((2, 2), (2, 4), (6,)):
        with pytest.raises(Refusal, match=r"^EVIDENCE_PACKING_MISMATCH$"):
            _token_spans(line, cut)
    with pytest.raises(Refusal, match=r"^EVIDENCE_PACKING_MISMATCH$"):
        _shown(line, {8: (5,)}, lines)
    # A line whose stored blocks are fewer than its spans need is the same
    # failure, read the other way (R24-16).
    with pytest.raises(Refusal, match=r"^EVIDENCE_PACKING_MISMATCH$"):
        _shown(line, {7: (2, 3)}, {7: ("B000000",)})


def test_a_width_cut_line_keeps_only_the_blocks_cut_between_tokens() -> None:
    """Packing 1 (every source admitted before CF-013): a line that fits is
    one line; past `GROUP_WIDTH` it was cut at the width, and a block whose
    edge fell inside a word began or ended with part of one, which no run of
    whole tokens is. Its neighbours cut between tokens are lines of their
    own, each numbered by its `GROUP_WIDTH` bucket -- the index a torn
    neighbour would have carried is simply absent, not renumbered down."""
    assert _width_spans(_line(0, "short", "line")) == [(0, (0, 2))]
    # Seven characters and a space: the width falls exactly between words.
    even = _line(0, *(f"x{n:06d}" for n in range(600)))
    per_block = GROUP_WIDTH // 8
    assert _width_spans(even) == [(0, (0, per_block)), (1, (per_block, 600))]
    # Five and a space: the cut tears a word, and both blocks it touches
    # hold part of one.
    assert _width_spans(_line(0, *(f"w{n:04d}" for n in range(700)))) == []
    # A clean first cut, then a torn second: only the first block is a line,
    # numbered 0 -- the torn second block's index (1) is missing, not reused.
    mixed = _line(
        0, *(f"x{n:06d}" for n in range(per_block)), *(f"w{n:04d}" for n in range(700))
    )
    assert _width_spans(mixed) == [(0, (0, per_block))]


def _pdf(content: bytes, to_unicode: Mapping[int, str] | None = None) -> bytes:
    """One page whose font is not a standard one -- so pdfminer reads its
    declared widths, one per code 32-255, and WinAnsi draws code 0x97 as an
    em dash and 0xE9 as an e with an acute -- with a ToUnicode map for the
    codes `to_unicode` names, which is how a PDF stores a character
    decomposed or maps one glyph to several words."""
    widths = b" ".join([b"600"] * 224)
    objects = _objects(content)
    objects[-1] = (
        b"<< /Type /Font /Subtype /Type1 /BaseFont /ProbeSans /FirstChar 32"
        b" /LastChar 255 /Widths [" + widths + b"] /Encoding /WinAnsiEncoding"
    )
    if not to_unicode:
        objects[-1] += b" >>"
        return _assemble(objects)
    pairs = "".join(
        f"<{code:02X}> <{text.encode('utf-16-be').hex().upper()}>\n"
        for code, text in to_unicode.items()
    )
    cmap = (
        "/CIDInit /ProcSet findresource begin\n12 dict begin\nbegincmap\n"
        "/CMapName /Probe-UCS def\n/CMapType 2 def\n1 begincodespacerange\n"
        f"<00> <FF>\nendcodespacerange\n{len(to_unicode)} beginbfchar\n"
        f"{pairs}endbfchar\nendcmap\n"
        "CMapName currentdict /CMap defineresource pop\nend\nend\n"
    ).encode()
    objects[-1] += b" /ToUnicode 6 0 R >>"
    stream = b"<< /Length %d >>\nstream\n" % len(cmap) + cmap + b"endstream"
    return _assemble([*objects, stream])


E_ACUTE = chr(0xE9)
DECOMPOSED_E_ACUTE = "e" + chr(0x301)
# A table row: three adjacent one-character tokens, `$`, an em dash and `$`,
# which a tracking extractor's joined line reads as one word, and a word with
# an accent.
TABLE_ROW = b"BT /F1 12 Tf 72 700 Td (Total $ \x97 $ 12 caf\xe9) Tj ET"
SHOWN_ROW = f"Total $ {chr(0x2014)} $ 12 caf{E_ACUTE}"


def _block_text(conn: StoreConnection, source_id: UUID) -> str:
    row = conn.execute(
        "SELECT text FROM source_blocks WHERE source_id = %s", (source_id,)
    ).fetchone()
    assert row is not None
    return str(row[0])


@pytest.mark.parametrize(
    ("to_unicode", "as_stored"),
    [
        # Stored composed: the line copied exactly anchored; with a full stop
        # the edge forgiveness was lost to the joined `$--$`.
        ({}, (1, RefusalCode.CITATION_NOT_LOCATED)),
        # Stored decomposed: the NFC text the module was shown did not anchor.
        (
            {0xE9: DECOMPOSED_E_ACUTE},
            (RefusalCode.CITATION_NOT_LOCATED, RefusalCode.CITATION_NOT_LOCATED),
        ),
    ],
)
def test_a_line_is_quoted_as_the_evidence_section_shows_it(
    case: tuple[StoreConnection, UUID],
    tmp_path: Path,
    to_unicode: dict[int, str],
    as_stored: tuple[RefusalCode | int, RefusalCode | int],
) -> None:
    """W6: the answer's rule compares the quote with the line as the evidence
    section showed it -- NFC, word by word, its edges forgiven -- where the
    first whole-line reading tried the stored bytes and then only the line
    with tracked letters joined, which on a PDF table row is no line the
    module saw. A record accepted under that reading is still re-anchored by
    it, and answers as it did."""
    conn, case_id = case
    source_id = _ingest_pdf(conn, case_id, tmp_path, _pdf(TABLE_ROW, to_unicode))
    shown = _block_text(conn, source_id)
    assert shown == SHOWN_ROW

    assert _code(conn, source_id, shown) == 1
    assert _code(conn, source_id, shown + ".") == 1
    assert _code(conn, source_id, f"\u201c{shown}.\u201d") == 1
    assert (
        _code(conn, source_id, shown, WHOLE_LINE_AS_STORED),
        _code(conn, source_id, shown + ".", WHOLE_LINE_AS_STORED),
    ) == as_stored


def test_a_token_of_several_words_is_quoted_as_the_words_it_shows(
    case: tuple[StoreConnection, UUID], tmp_path: Path
) -> None:
    """W6: a glyph mapped to several words is one token holding spaces, and
    the evidence section shows its words; the answer's rule reads the line as
    those words, where the first reading counted tokens and found no line."""
    conn, case_id = case
    content = b"BT /F1 12 Tf 72 700 Td (Total Q) Tj ET"
    source_id = _ingest_pdf(
        conn, case_id, tmp_path, _pdf(content, {ord("Q"): "12.5 million"})
    )
    assert _block_text(conn, source_id) == "Total 12.5 million"

    assert _code(conn, source_id, "Total 12.5 million") == 1
    assert _code(conn, source_id, "Total 12.5") is RefusalCode.CITATION_NOT_LOCATED
    assert _code(conn, source_id, "Total 12.5 million", WHOLE_LINE_AS_STORED) is (
        RefusalCode.CITATION_NOT_LOCATED
    )


def test_two_lines_shown_alike_are_ambiguous_however_each_is_stored(
    case: tuple[StoreConnection, UUID], tmp_path: Path
) -> None:
    """N13: two lines of one page that the evidence section shows alike, one
    stored composed and one decomposed, are one text to the module; the exact
    pass anchored the one whose bytes the quote happened to match. They are
    ambiguous now in either form, and a record accepted under the first
    reading still re-anchors where it did."""
    conn, case_id = case
    data = f"Revenue caf{E_ACUTE}\n\nRevenue caf{DECOMPOSED_E_ACUTE}\n".encode()
    [source_id] = admit_pack(
        conn,
        BlobStore(tmp_path / "blobs"),
        case_id=case_id,
        documents=[Document(filename=BoundaryText.of("memo.txt"), data=data)],
    )

    for quote in (f"Revenue caf{E_ACUTE}", f"Revenue caf{DECOMPOSED_E_ACUTE}"):
        assert _code(conn, source_id, quote) is RefusalCode.CITATION_AMBIGUOUS
    assert _code(conn, source_id, f"Revenue caf{E_ACUTE}", WHOLE_LINE_AS_STORED) == 1

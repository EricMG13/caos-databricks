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

import dataclasses
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
    AnchoredCitation,
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


PAGES = (
    (
        "The Company did not breach its leverage covenant during FY2025 or in"
        " any later quarter of the year",
        "Liquidity was USD 310.5m at year end.",
    ),
    ("Net leverage was 3.4x at year end.",),
    ("Cash interest cover was 2.1x.", "Cash interest cover was 2.1x in FY2024."),
)


def _pages_pdf(pages: tuple[tuple[str, ...], ...] = PAGES) -> bytes:
    """`pages` as a PDF, one page each, each line drawn apart from the next."""
    from test_admission_limits import multi_page_pdf
    from test_pdf_extraction import LEFT_MARGIN

    return multi_page_pdf(
        [
            "".join(
                f"BT\n/F1 12 Tf\n1 0 0 1 {LEFT_MARGIN:.0f} {700 - 40 * n} Tm\n"
                f"({line}) Tj\nET\n"
                for n, line in enumerate(lines)
            ).encode("ascii")
            for lines in pages
        ]
    )


def _blocks_by_page(
    conn: StoreConnection, source_id: UUID
) -> dict[int, dict[str, str]]:
    by_page: dict[int, dict[str, str]] = {}
    for page, block_id, text in conn.execute(
        "SELECT page, block_id, text FROM source_blocks WHERE source_id = %s",
        (source_id,),
    ).fetchall():
        by_page.setdefault(int(page), {})[str(block_id)] = str(text)
    return by_page


def test_find_line_places_a_quote_the_whole_line_rule_refused(
    case: tuple[StoreConnection, UUID], tmp_path: Path
) -> None:
    """D82: with the host's own search -- `ANY_RUN` on the cited page, then
    `WHOLE_LINE` on each other delivered page -- a quote that is part of a
    longer delivered line names that line; one that is a whole line of
    another delivered page names the page; one on no delivered page is
    absent; and one found but not as one line (twice on its page) or only
    on an undelivered line is placed nowhere."""
    from caos.evidence.citations import LineFinding, TokenIndex, find_line

    conn, case_id = case
    source_id = _ingest_pdf(conn, case_id, tmp_path, _pages_pdf())
    by_page = _blocks_by_page(conn, source_id)
    every = frozenset(block for blocks in by_page.values() for block in blocks)
    [covenant] = [b for b, text in by_page[1].items() if text.startswith("The")]

    def found(
        page: int,
        quote: str,
        blocks: frozenset[str] = every,
        pages: set[int] | None = None,
    ) -> LineFinding:
        return find_line(
            conn,
            blocks=blocks,
            pages=set(by_page) if pages is None else pages,
            citation=Citation(source_id, page, quote),
            index=TokenIndex(),
        )

    part = "breach its leverage covenant during FY2025"
    elsewhere = "Net leverage was 3.4x at year end."
    for quote in (part, "Leverage was unchanged"):
        assert _code(conn, source_id, quote) is RefusalCode.CITATION_NOT_LOCATED
    # A whole line of one other delivered page is anchored there (D94); the
    # search below still names that page when asked directly.
    assert _code(conn, source_id, elsewhere) == 1
    assert found(1, part) == LineFinding(block_id=covenant)
    assert found(1, elsewhere) == LineFinding(pages=(2,))
    assert found(1, "Leverage was unchanged") == LineFinding(absent=True)
    # Part of a longer line of another delivered page: found, but not as one
    # line of any page, so never told absent (I1).
    assert found(1, "Net leverage was 3.4x") == LineFinding()
    # Twice on its page as a run: found, but not one line.
    assert found(3, "Cash interest cover was") == LineFinding()
    # The longer line withheld: never shown, so never named, and no line the
    # node was given holds the quote.
    assert found(1, part, every - {covenant}) == LineFinding(absent=True)
    # Page 2 not given: no delivered line holds the quote.
    unpaged = every - frozenset(by_page[2])
    assert found(1, elsewhere, unpaged, {1, 3}) == LineFinding(absent=True)
    # A cited page the node was not given is never read (M2): what it holds
    # cannot change the answer.
    index = TokenIndex()
    cited = Citation(source_id, 2, "Net leverage was 3.4x")
    given = find_line(conn, blocks=unpaged, pages={1, 3}, citation=cited, index=index)
    assert given == LineFinding(absent=True)
    assert (source_id, 2) not in index.pages


def test_a_placed_line_is_shown_by_its_first_words_as_delivered(
    case: tuple[StoreConnection, UUID], tmp_path: Path
) -> None:
    """D82: the longer line's first `HINT_WORDS` words come from the block the
    node was delivered, its own words one space apart; a page found by
    `find_line` passes through as it is."""
    from caos.evidence.citations import TokenIndex
    from caos.methodology.canonical import _line_hint
    from caos.methodology.executor import Delivery
    from caos.methodology.handoff import HINT_WORDS, LineHint

    conn, case_id = case
    source_id = _ingest_pdf(conn, case_id, tmp_path, _pages_pdf())
    by_page = _blocks_by_page(conn, source_id)
    delivered = [
        Delivery(source_id, block_id, page, BoundaryText.of(text))
        for page, blocks in by_page.items()
        for block_id, text in blocks.items()
    ]
    blocks = {source_id: frozenset(d.block_id for d in delivered)}

    def hint(quote: str) -> LineHint:
        citation = Citation(source_id, 1, quote)
        return _line_hint(conn, delivered, blocks, citation, TokenIndex())

    begins = " ".join(PAGES[0][0].split()[:HINT_WORDS])
    assert hint("breach its leverage covenant") == LineHint(begins=begins)
    assert hint("Net leverage was 3.4x at year end.") == LineHint(pages=(2,))
    assert hint("Leverage was unchanged") == LineHint(absent=True)


def test_a_search_that_cannot_read_a_page_leaves_the_citation_unplaced(
    case: tuple[StoreConnection, UUID],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """D82 (M3): the search is help, not a verdict. A page whose blocks no
    longer read as written refuses inside `find_line`; the retry still goes
    out, the citation told by the rule alone."""
    from caos.evidence import citations
    from caos.evidence.citations import TokenIndex
    from caos.methodology.canonical import _line_hint
    from caos.methodology.executor import Delivery
    from caos.methodology.handoff import LineHint

    conn, case_id = case
    source_id = _ingest_pdf(conn, case_id, tmp_path, _pages_pdf())
    delivered = [
        Delivery(source_id, block_id, page, BoundaryText.of(text))
        for page, blocks in _blocks_by_page(conn, source_id).items()
        for block_id, text in blocks.items()
    ]
    blocks = {source_id: frozenset(d.block_id for d in delivered)}

    def unreadable(*_args: object, **_kwargs: object) -> None:
        raise Refusal(RefusalCode.EVIDENCE_PACKING_MISMATCH)

    monkeypatch.setattr(citations, "_verdict", unreadable)
    citation = Citation(source_id, 1, "Net leverage was 3.4x at year end.")
    assert _line_hint(conn, delivered, blocks, citation, TokenIndex()) == LineHint()


REANCHOR_PAGES = (
    ("Revenue grew 4% in FY2025.",),
    ("Net leverage was 3.4x at year end.", "The same line on two pages."),
    ("The same line on two pages.", "Cover was 2.1x."),
    ("Only on page four.",),
)


def test_a_whole_line_cited_on_the_wrong_page_is_anchored_at_its_true_page(
    case: tuple[StoreConnection, UUID], tmp_path: Path
) -> None:
    """D94: a quote that is no line of its cited page but exactly one whole
    delivered evidence line of another delivered page of its source is
    anchored at that page -- the stored page and rectangles are the true
    page's, and the page the module named is kept as `cited_page`. Two such
    lines, one the node was not given, a page it was not given, and part of
    a line all refuse as before; and only `WHOLE_LINE` re-anchors, so a
    record accepted under another rule is located as it always was."""

    from caos.evidence.citations import ANY_RUN, TokenIndex

    conn, case_id = case
    source_id = _ingest_pdf(conn, case_id, tmp_path, _pages_pdf(REANCHOR_PAGES))
    by_page = _blocks_by_page(conn, source_id)
    every = frozenset(block for blocks in by_page.values() for block in blocks)
    leverage = "Net leverage was 3.4x at year end."

    def anchor(
        page: int,
        quote: str,
        blocks: frozenset[str] = every,
        rule: CitationRule = WHOLE_LINE,
        index: TokenIndex | None = None,
    ) -> object:
        try:
            [anchored] = verify_citations(
                conn,
                delivered={source_id: blocks},
                citations=[Citation(source_id, page, quote)],
                rule=rule,
                index=index,
            )
        except Refusal as refused:
            assert refused.__cause__ is None and refused.__context__ is None
            return refused.code
        return anchored

    true, moved = anchor(2, leverage), anchor(1, leverage)
    assert isinstance(true, AnchoredCitation) and true.cited_page is None
    assert moved == dataclasses.replace(true, cited_page=1)
    assert {box.page for box in true.bboxes} == {2}

    not_located = RefusalCode.CITATION_NOT_LOCATED
    # On two delivered pages: which one the module read is not known.
    assert anchor(1, "The same line on two pages.") is not_located
    # Part of the line: no line at all, wherever it is cited.
    assert anchor(1, "Net leverage was 3.4x") is not_located
    # Its one line withheld from the node, its page still delivered.
    [line_block] = [b for b, t in by_page[2].items() if t.startswith("Net")]
    assert anchor(1, leverage, every - {line_block}) is not_located
    # Its page never delivered: never read, so never a place to anchor.
    index = TokenIndex()
    unpaged = every - frozenset(by_page[4])
    assert anchor(1, "Only on page four.", unpaged, index=index) is not_located
    assert (source_id, 4) not in index.pages
    # Under the rules older records name, a wrong page is not located.
    for rule in (WHOLE_LINE_AS_STORED, ANY_RUN):
        assert anchor(1, leverage, rule=rule) is not_located


def test_a_stored_citation_is_checked_where_it_is_stored(
    case: tuple[StoreConnection, UUID], tmp_path: Path
) -> None:
    """D94: a reader re-checks a stored citation at the page it stores, never
    searching the run's capture for it, and keeps its `cited_page` only when
    that page holds no such line -- the one case acceptance re-anchors."""
    from caos.evidence.citations import TokenIndex, verify_stored_citations

    conn, case_id = case
    source_id = _ingest_pdf(conn, case_id, tmp_path, _pages_pdf(REANCHOR_PAGES))
    every = every_block(conn, source_id)
    leverage = "Net leverage was 3.4x at year end."

    def stored(page: int, cited: int | None, quote: str = leverage) -> object:
        try:
            [found] = verify_stored_citations(
                conn,
                delivered=every,
                citations=[(Citation(source_id, page, quote), cited)],
                index=TokenIndex(),
                rule=WHOLE_LINE,
            )
        except Refusal as refused:
            return refused.code
        return found

    [live] = verify_citations(
        conn,
        delivered=every,
        citations=[Citation(source_id, 1, leverage)],
        rule=WHOLE_LINE,
    )
    assert stored(2, 1) == live
    # A cited page that does hold the line: no re-anchoring was due.
    shared = "The same line on two pages."
    found = stored(2, 3, shared)
    assert isinstance(found, AnchoredCitation) and found.cited_page is None
    # A stored page the quote is not on is never searched for elsewhere.
    assert stored(1, None) is RefusalCode.CITATION_NOT_LOCATED


def test_placing_a_quote_reads_each_page_once_and_never_re_anchors(
    case: tuple[StoreConnection, UUID],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """D94 (I1): the retry placement asks each delivered page once, at that
    page; it never runs the re-anchoring search, which would make it
    quadratic in the pages delivered."""
    from caos.evidence import citations
    from caos.evidence.citations import TokenIndex, find_line

    conn, case_id = case
    source_id = _ingest_pdf(conn, case_id, tmp_path, _pages_pdf(REANCHOR_PAGES))
    by_page = _blocks_by_page(conn, source_id)
    every = frozenset(block for blocks in by_page.values() for block in blocks)
    searched: list[int] = []
    shown = citations._shown_line_run

    def counted(
        page: _Page,
        cuts: Mapping[int, tuple[int, ...]] | None,
        lines: Mapping[int, tuple[str, ...]],
        matched_text: str,
        *,
        tracking: bool,
    ) -> tuple[list[_Token], str]:
        searched.append(1)
        return shown(page, cuts, lines, matched_text, tracking=tracking)

    def never(*_args: object, **_kwargs: object) -> None:
        raise AssertionError

    monkeypatch.setattr(citations, "_shown_line_run", counted)
    monkeypatch.setattr(citations, "_true_page", never)
    found = find_line(
        conn,
        blocks=every,
        pages=set(by_page),
        citation=Citation(source_id, 1, "A paraphrase on no page at all."),
        index=TokenIndex(),
    )
    assert found.absent
    assert len(searched) <= len(by_page)

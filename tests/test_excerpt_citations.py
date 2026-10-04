"""D105 (owner, 4 October 2026: "you do not need to display the entire line
verbatim. just allow the user the ability to trace where a statement or
conclusion was derived from"): an answer's citation is an exact excerpt of one
evidence line -- at least `MIN_EXCERPT_WORDS` consecutive whole words of it, or
the whole line when it is shorter -- found once on its page and anchored to that
line, which the record keeps beside the quote (`AnchoredCitation.line_text`).

A record accepted under an earlier rule names it and is re-anchored by it
(`tests/test_whole_line_citations.py`), so nothing stored moves.
"""

from __future__ import annotations

import random
import time
from pathlib import Path
from uuid import UUID

import pytest
from conftest import every_block
from test_pdf_extraction import _ingest_pdf
from test_whole_line_citations import _line, _pages_pdf

from caos.blobs import BlobStore
from caos.boundary_text import BoundaryText
from caos.evidence.citations import (
    EXCERPT,
    MIN_EXCERPT_WORDS,
    WHOLE_LINE,
    AnchoredCitation,
    Citation,
    TokenIndex,
    _excerpt_run,
    _Page,
    _Token,
    overrun_line,
    verify_citations,
    verify_stored_citations,
)
from caos.evidence.ingest import Document, admit_pack
from caos.refusals import Refusal, RefusalCode
from caos.store import StoreConnection

LONG = (
    "The Company did not breach its leverage covenant during FY2025 and expects"
    " to remain in compliance."
)
SHORT = "Liquidity was USD 310.5m at year end."
DECOMPOSED = "The café chain reported revenue growth of four percent this year."
DOCUMENT = "\n".join(
    (
        LONG,
        SHORT,
        "Cash interest cover stayed above the minimum level in FY2025.",
        "Cash interest cover stayed above the minimum level in FY2024.",
        "fees rose to USD 9m in the first half and fees rose to USD 9m in the"
        " first half again",
        DECOMPOSED,
    )
).encode()


def _admit(conn: StoreConnection, case_id: UUID, tmp_path: Path) -> UUID:
    [source_id] = admit_pack(
        conn,
        BlobStore(tmp_path / "blobs"),
        case_id=case_id,
        documents=[Document(filename=BoundaryText.of("memo.txt"), data=DOCUMENT)],
    )
    return source_id


def _anchored(
    conn: StoreConnection, source_id: UUID, quote: str, page: int = 1
) -> AnchoredCitation | RefusalCode:
    """The citation `EXCERPT` anchors, or the code it refuses with."""
    try:
        [anchored] = verify_citations(
            conn,
            delivered=every_block(conn, source_id),
            citations=[Citation(source_id, page, quote)],
            rule=EXCERPT,
        )
    except Refusal as refused:
        return refused.code
    return anchored


def test_an_excerpt_of_eight_words_anchors_to_its_whole_line(
    case: tuple[StoreConnection, UUID], tmp_path: Path
) -> None:
    """Eight consecutive words of a longer line anchor to that line: the
    rectangle is the excerpt's own, narrower than its line's, and the record
    keeps the line whole beside it."""
    conn, case_id = case
    source_id = _admit(conn, case_id, tmp_path)
    excerpt = "did not breach its leverage covenant during FY2025"
    assert len(excerpt.split()) == MIN_EXCERPT_WORDS

    found = _anchored(conn, source_id, excerpt)
    whole = _anchored(conn, source_id, LONG)
    assert isinstance(found, AnchoredCitation) and isinstance(whole, AnchoredCitation)
    assert (found.matched_text, found.line_text) == (excerpt, LONG)
    assert whole.line_text == LONG
    [box], [line_box] = found.bboxes, whole.bboxes
    assert line_box.x0 < box.x0 and box.x1 < line_box.x1
    # The tail of the line, ending where it ends, is an excerpt too.
    tail = "FY2025 and expects to remain in compliance."
    assert isinstance(_anchored(conn, source_id, f"during {tail}"), AnchoredCitation)


def test_a_line_shorter_than_eight_words_anchors_only_whole(
    case: tuple[StoreConnection, UUID], tmp_path: Path
) -> None:
    """A line of fewer than `MIN_EXCERPT_WORDS` words is cited whole; any
    part of it, or of a longer line, under eight words is no excerpt."""
    conn, case_id = case
    source_id = _admit(conn, case_id, tmp_path)

    found = _anchored(conn, source_id, SHORT)
    assert isinstance(found, AnchoredCitation) and found.line_text == SHORT
    for quote in ("Liquidity was USD 310.5m", "breach its leverage covenant during"):
        assert _anchored(conn, source_id, quote) is RefusalCode.CITATION_NOT_LOCATED


def test_an_excerpt_keeps_the_edge_forgiveness_and_reads_the_line_nfc(
    case: tuple[StoreConnection, UUID], tmp_path: Path
) -> None:
    """The declared normalisations, as `WHOLE_LINE` has them: the excerpt's
    first and last word less a sentence's punctuation, and the line as shown,
    NFC -- never an interior word's punctuation."""
    conn, case_id = case
    source_id = _admit(conn, case_id, tmp_path)
    excerpt = "did not breach its leverage covenant during FY2025"

    for quoted in (f"“{excerpt}”", f"{excerpt}.", f"'{excerpt},'"):
        assert isinstance(_anchored(conn, source_id, quoted), AnchoredCitation)
    # A figure keeps its parentheses at an edge (EV-4): `FY2025)` is not it.
    paren = f"({excerpt})"
    assert _anchored(conn, source_id, paren) is RefusalCode.CITATION_NOT_LOCATED
    comma = excerpt.replace("leverage", "leverage,")
    assert _anchored(conn, source_id, comma) is RefusalCode.CITATION_NOT_LOCATED
    composed = "The café chain reported revenue growth of four percent"
    found = _anchored(conn, source_id, composed)
    assert isinstance(found, AnchoredCitation)
    assert found.line_text == DECOMPOSED.replace("é", "é")


def test_an_excerpt_is_refused_across_lines_twice_or_inside_a_word(
    case: tuple[StoreConnection, UUID], tmp_path: Path
) -> None:
    """Refused: a run onto the next line (it is no excerpt of one line), an
    excerpt found twice on its page -- in two lines, or twice in one -- and a
    quote that starts or ends inside a word."""
    conn, case_id = case
    source_id = _admit(conn, case_id, tmp_path)

    across = "to remain in compliance. Liquidity was USD 310.5m"
    assert _anchored(conn, source_id, across) is RefusalCode.CITATION_NOT_LOCATED
    twice = "Cash interest cover stayed above the minimum level"
    assert _anchored(conn, source_id, twice) is RefusalCode.CITATION_AMBIGUOUS
    once = f"{twice} in FY2025."
    assert isinstance(_anchored(conn, source_id, once), AnchoredCitation)
    in_one = "fees rose to USD 9m in the first half"
    assert _anchored(conn, source_id, in_one) is RefusalCode.CITATION_AMBIGUOUS
    for cut in (
        "he Company did not breach its leverage covenant",
        "The Company did not breach its leverage coven",
    ):
        assert _anchored(conn, source_id, cut) is RefusalCode.CITATION_NOT_LOCATED


def test_tracked_letters_join_within_an_excerpt_on_a_tracking_extractor() -> None:
    """The third pass, as `WHOLE_LINE`'s: on a tracking extractor a word
    drawn letter by letter is quoted as the word a reader sees, inside its own
    line only; the line kept is the line as shown."""
    words = ("debt", "at", "31", "December", "2026", "was", "USD")
    page = _Page([*_line(0, "T", "o", "t", "a", "l", *words), *_line(1, "x")])
    lines = {0: ("B000000",), 1: ("B000001",)}
    quote = " ".join(("Total", *words))

    run, block_id, line = _excerpt_run(page, None, lines, quote, tracking=True)
    assert block_id == "B000000" and run[0].text == "Total"
    assert line == " ".join(("T o t a l", *words))
    with pytest.raises(Refusal, match=r"^CITATION_NOT_LOCATED$"):
        _excerpt_run(page, None, lines, quote, tracking=False)


def test_excerpts_of_a_long_page_are_found_in_one_search_each() -> None:
    """N41's shape under `EXCERPT`: 512 excerpts of one 240,000-token page,
    its words drawn from fourteen so every quote meets thousands of partial
    matches, each found by one search of the page's joined keys
    (`_Flat.places`) -- 3.7 s by a Python step per partial match, about 0.3 s
    this way. A word holding the join's separator begins nowhere."""
    vocabulary = (
        *("the", "of", "and", "to", "in", "a", "Company", "debt", "was"),
        *("USD", "net", "revenue", "for", "year"),
    )
    width, count, draw = 20, 12_000, random.Random(7)
    tokens = [
        _Token(
            draw.choice(vocabulary) if at else f"L{line}",
            0,
            line,
            float(at),
            0.0,
            at + 1.0,
            1.0,
        )
        for line in range(count)
        for at in range(width)
    ]
    page = _Page(tokens)
    lines = {line: (f"b{line:06d}",) for line in range(count)}
    quotes = []
    for n in range(512):
        first = draw.randrange(count) * width + draw.randrange(width - 9)
        quotes.append(" ".join(t.text for t in tokens[first : first + 8 + n % 3]))
    started = time.perf_counter()
    for quote in quotes:
        _excerpt_run(page, None, lines, quote, tracking=False)
    assert time.perf_counter() - started < 2.0
    flat = page.flat(None, lines, joined=False)
    assert list(flat.places(["L0", "the\x00of"])) == []


REANCHOR_PAGES = (
    ("Revenue grew four percent in FY2025 on higher volumes in every segment.",),
    ("Net leverage was 3.4x at year end after the refinancing closed in March.",),
    ("Covenant note: Net leverage was 3.4x at year end after the refinancing.",),
)


def test_an_excerpt_cited_on_the_wrong_page_is_anchored_at_its_true_page(
    case: tuple[StoreConnection, UUID], tmp_path: Path
) -> None:
    """D94 under `EXCERPT`: an excerpt of exactly one delivered line of
    another delivered page is anchored there, with its line and the page the
    module named; one found on two other pages refuses as before. A stored
    record re-checks the re-anchoring by the same rule."""
    conn, case_id = case
    source_id = _ingest_pdf(conn, case_id, tmp_path, _pages_pdf(REANCHOR_PAGES))
    only_two = "Net leverage was 3.4x at year end after the refinancing closed"
    on_both = "Net leverage was 3.4x at year end after the"

    moved = _anchored(conn, source_id, only_two)
    assert isinstance(moved, AnchoredCitation)
    assert (moved.page, moved.cited_page) == (2, 1)
    assert moved.line_text == REANCHOR_PAGES[1][0]
    assert {box.page for box in moved.bboxes} == {2}
    assert _anchored(conn, source_id, on_both) is RefusalCode.CITATION_NOT_LOCATED

    request = Citation(source_id, moved.page, only_two)
    again = verify_stored_citations(
        conn,
        delivered=every_block(conn, source_id),
        citations=[(request, moved.cited_page)],
        index=TokenIndex(),
        rule=EXCERPT,
    )
    assert again == [moved]
    # Under the whole-line rule the excerpt is no line of page 2 at all.
    with pytest.raises(Refusal, match=r"^CITATION_NOT_LOCATED$"):
        verify_citations(
            conn,
            delivered=every_block(conn, source_id),
            citations=[request],
            rule=WHOLE_LINE,
        )


def test_an_overrun_is_named_from_any_word_of_its_line() -> None:
    """F496 under `EXCERPT`: a quote that starts inside a line, copies it to
    its end and runs on is named by that line, as one that starts at its
    first word is; a quote within its line, or whose first words are in no
    line, is not."""
    lines = [
        "Revenue was flat.",
        "The Borrower shall maintain the Collateral and take all actions"
        " required by such Security",
    ]
    mid = (
        "maintain the Collateral and take all actions required by such Security"
        " Documents to perfect the Liens"
    )
    assert overrun_line(mid, lines) == 1
    assert overrun_line(f"The Borrower shall {mid}", lines) == 1
    assert overrun_line("maintain the Collateral and take all actions", lines) is None
    assert overrun_line("keep the Collateral and take all actions required", lines) is (
        None
    )

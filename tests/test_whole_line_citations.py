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

from pathlib import Path
from uuid import UUID

import pytest
from conftest import every_block

from caos.blobs import BlobStore
from caos.boundary_text import BoundaryText
from caos.evidence.citations import (
    ANY_RUN,
    CITATION_RULES,
    WHOLE_LINE,
    Citation,
    CitationRule,
    _line_run,
    _Page,
    _shown,
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
    assert CITATION_RULES == {ANY_RUN, WHOLE_LINE}


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


def test_tracked_letters_join_within_their_line_and_never_across_two() -> None:
    """A heading tracked into single letters is quoted as the word a reader
    sees, on a tracking extractor only, and only inside its own line."""
    page = _Page([*_line(0, "H", "e", "a", "d"), *_line(1, "i", "n", "g")])
    lines = {0: ("B000000",), 1: ("B000001",)}

    ([joined], block_id) = _line_run(page, None, lines, "Head", tracking=True)
    assert joined.text == "Head"
    assert block_id == "B000000"
    with pytest.raises(Refusal, match=r"^CITATION_NOT_LOCATED$"):
        _line_run(page, None, lines, "Head", tracking=False)
    with pytest.raises(Refusal, match=r"^CITATION_NOT_LOCATED$"):
        _line_run(page, None, lines, "Heading", tracking=True)
    with pytest.raises(Refusal, match=r"^CITATION_NOT_LOCATED$"):
        _line_run(page, None, lines, "   ", tracking=True)


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

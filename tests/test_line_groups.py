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

import unicodedata
from pathlib import Path
from uuid import UUID

import pytest

from caos.blobs import BlobStore
from caos.boundary_text import BoundaryText
from caos.evidence import ingest
from caos.evidence.citations import (
    WHOLE_LINE,
    Citation,
    _line_blocks,
    verify_citations,
)
from caos.evidence.extract import Token
from caos.evidence.ingest import (
    GROUP_WIDTH,
    PACKING_BY_TOKEN,
    PACKING_BY_WIDTH,
    Document,
    admit_pack,
    block_ids_by_line,
    line_groups,
    token_groups,
)
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


def _packing(conn: StoreConnection, source_id: UUID) -> int:
    row = conn.execute(
        "SELECT format_version FROM source_extractions WHERE source_id = %s",
        (source_id,),
    ).fetchone()
    assert row is not None
    return int(row[0])


def _by_width(tokens: list[Token]) -> tuple[list[ingest._Block], int]:
    """Admission's packing before CF-013, as every source it admitted holds it:
    a wide line cut at `GROUP_WIDTH` wherever the width fell, recorded as
    packing 1. What a test admits through it is an old stored source."""
    lines: dict[int, list[Token]] = {}
    for token in tokens:
        lines.setdefault(token.line_id, []).append(token)
    groups = {
        line_id: line_groups(" ".join(token.text for token in line))
        for line_id, line in lines.items()
    }
    ids = block_ids_by_line({line_id: len(g) for line_id, g in groups.items()})
    blocks = [
        ingest._Block(block_id, lines[line_id][0].page, BoundaryText.of(text))
        for line_id in sorted(lines)
        for block_id, text in zip(ids[line_id], groups[line_id], strict=True)
    ]
    return blocks, PACKING_BY_WIDTH


@pytest.fixture
def by_width(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ingest, "_blocks", _by_width)


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
    assert " ".join(text for _id, text in blocks[1:3]) == WIDE_LINE


def test_a_wide_line_is_cut_between_its_tokens_never_inside_one() -> None:
    """CF-013: the width cut fell wherever the width fell, inside a word if
    that is where it fell. A line is now cut only where the token index can
    break a quote, and the space it is cut at is the one between two blocks."""
    groups = token_groups(WIDE_WORDS)

    assert len(groups) == 2
    assert all(len(group) <= GROUP_WIDTH for group in groups)
    assert [word for group in groups for word in group.split(" ")] == WIDE_WORDS
    # A line that fits is the one group the width rule made of it, byte for byte.
    assert token_groups(["Caf\u0065\u0301", "abcdefg"]) == line_groups(
        "Caf\u0065\u0301 abcdefg"
    )
    # A token as wide as a block is a block of its own.
    wide = "x" * GROUP_WIDTH
    assert token_groups(["a", wide, "b"]) == ["a", wide, "b"]


def test_each_block_of_a_split_line_can_be_quoted_whole(
    case: tuple[StoreConnection, UUID], tmp_path: Path
) -> None:
    """CF-013: a module is shown each block of a split line as a line of its
    own, and a quote of one of them whole was refused `CITATION_NOT_LOCATED`
    because the block began and ended inside words the token index does not
    break. Cut between tokens, each block is a run of whole words, quotable on
    the delivery of its line."""
    conn, case_id = case
    source_id = _admit(conn, case_id, tmp_path, DOCUMENT)
    blocks = _blocks(conn, source_id)
    line = frozenset(block_id for block_id, _ in blocks[1:3])

    for _block_id, text in blocks[1:3]:
        [anchored] = verify_citations(
            conn,
            delivered={source_id: line},
            citations=[Citation(source_id, 1, text)],
        )
        assert anchored.bboxes
    assert _packing(conn, source_id) == PACKING_BY_TOKEN
    assert _line_blocks(conn, source_id, PACKING_BY_TOKEN) == block_ids_by_line(
        {0: 1, 1: 2, 2: 1}
    )


def test_a_page_map_showing_only_the_first_block_of_a_split_line_still_anchors_it(
    case: tuple[StoreConnection, UUID], tmp_path: Path
) -> None:
    """R24-16: a gate page map may show a source line's first block while
    withholding its continuation (`caos.methodology.selection.gate_view`
    cuts a page's leading blocks to fit a budget, unaware of which blocks
    share a line). `WHOLE_LINE` already matches a quote against one block at
    a time, exactly as the map shows it, and calls that block whole citable
    evidence -- so its delivery check must be judged against that one block,
    not against the continuation the map never promised. The second block's
    own text still refuses: it was never delivered."""
    conn, case_id = case
    source_id = _admit(conn, case_id, tmp_path, DOCUMENT)
    (first_id, first_text), (second_id, second_text) = _blocks(conn, source_id)[1:3]
    delivered = {source_id: frozenset({first_id})}

    [anchored] = verify_citations(
        conn,
        delivered=delivered,
        citations=[Citation(source_id, 1, first_text)],
        rule=WHOLE_LINE,
    )
    assert anchored.bboxes

    with pytest.raises(Refusal, match=r"^CITATION_NOT_DELIVERED$"):
        verify_citations(
            conn,
            delivered=delivered,
            citations=[Citation(source_id, 1, second_text)],
            rule=WHOLE_LINE,
        )
    assert first_id != second_id


def _whole_line(
    conn: StoreConnection, source_id: UUID, quote: str
) -> RefusalCode | int:
    """What the whole-line rule an answer is held to makes of `quote` (N28):
    its refusal, or how many rectangles it anchored to."""
    delivered = {source_id: frozenset(block for block, _ in _blocks(conn, source_id))}
    try:
        [anchored] = verify_citations(
            conn,
            delivered=delivered,
            citations=[Citation(source_id, 1, quote)],
            rule=WHOLE_LINE,
        )
    except Refusal as refused:
        return refused.code
    return len(anchored.bboxes)


def test_each_block_of_a_split_line_anchors_whole_and_nothing_less(
    case: tuple[StoreConnection, UUID], tmp_path: Path
) -> None:
    """N28 on CF-013's blocks: each block of a token-cut line is a line of
    its own to the module shown it, so quoted whole it anchors under the
    whole-line rule, and part of one -- or the two read as one -- does not."""
    conn, case_id = case
    source_id = _admit(conn, case_id, tmp_path, DOCUMENT)
    blocks = _blocks(conn, source_id)

    assert [_whole_line(conn, source_id, text) for _id, text in blocks] == [1] * 4
    for quote in (
        " ".join(WIDE_WORDS[1:5]),
        " ".join(WIDE_WORDS[681:684]),
        WIDE_LINE,
    ):
        assert _whole_line(conn, source_id, quote) is RefusalCode.CITATION_NOT_LOCATED


EVEN_WORDS = [f"x{n:06d}" for n in range(600)]


def test_a_width_cut_source_anchors_the_blocks_it_cut_between_tokens(
    case: tuple[StoreConnection, UUID], tmp_path: Path, by_width: None
) -> None:
    """N28 on a source packed before CF-013 (packing 1): a block whose two
    edges the width cut between tokens is a line of its own and anchors
    whole; one the cut tore inside a word never could (F204), and still
    does not -- re-admission packs it between tokens."""
    conn, case_id = case
    data = "Heading\n" + " ".join(EVEN_WORDS) + "\n" + WIDE_LINE + "\n"
    source_id = _admit(conn, case_id, tmp_path, data.encode())
    assert _packing(conn, source_id) == PACKING_BY_WIDTH
    blocks = [text for _id, text in _blocks(conn, source_id)]

    assert len(blocks) == 5
    assert [_whole_line(conn, source_id, text) for text in blocks[:3]] == [1] * 3
    for torn in blocks[3:]:
        assert _whole_line(conn, source_id, torn) is RefusalCode.CITATION_NOT_LOCATED


def test_a_source_whose_lines_all_fit_keeps_packing_one(
    case: tuple[StoreConnection, UUID], tmp_path: Path
) -> None:
    """Both packings write a line that fits as one block, byte for byte, so a
    source with no wide line is recorded as packing 1 -- its extraction and
    output digests are the ones every earlier admission of it wrote."""
    conn, case_id = case
    source_id = _admit(conn, case_id, tmp_path, NARROW)

    assert _packing(conn, source_id) == PACKING_BY_WIDTH


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
    monkeypatch.setattr(ingest, "_blocks", _by_width)
    source_id = _admit(conn, case_id, tmp_path, DOCUMENT)
    monkeypatch.undo()
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


def _filler(first: str, length: int) -> str:
    """`first`, then ten-letter words, exactly `length` code points long."""
    words = [first]
    size = len(first)
    while length - size > 12:
        words.append("abcdefghij")
        size += 11
    words.append("z" * (length - size - 1))
    line = " ".join(words)
    assert len(line) == length
    return line


def _admission_numbering(
    conn: StoreConnection, source_id: UUID
) -> dict[int, tuple[str, ...]]:
    """What admission wrote, recomputed the way admission computes it: each
    line's tokens joined and cut by `line_groups`, which measures NFC."""
    lines: dict[int, list[str]] = {}
    for line_id, text in conn.execute(
        "SELECT line_id, text FROM source_tokens WHERE source_id = %s"
        " ORDER BY token_id",
        (source_id,),
    ).fetchall():
        lines.setdefault(int(line_id), []).append(str(text))
    return block_ids_by_line(
        {line_id: len(line_groups(" ".join(words))) for line_id, words in lines.items()}
    )


def test_a_decomposed_line_is_packed_and_anchored_by_the_same_measure(
    case: tuple[StoreConnection, UUID], tmp_path: Path, by_width: None
) -> None:
    """EV-1: admission cuts a line by its NFC length and anchoring read the
    stored, un-normalised length back. A decomposed line (what macOS writes)
    that fits one block in NFC and not raw made the totals disagree, and every
    citation of the source -- a pure-ASCII line's too -- refused
    `EVIDENCE_PACKING_MISMATCH`, for good: re-admission packs it the same way.
    Both sides now measure NFC. Held on a source packed by the width rule
    (`by_width`), as every source admitted before CF-013 was: stored rows
    keep verifying as recorded."""
    conn, case_id = case
    prefix = unicodedata.normalize("NFD", "\u00e9 " * 40)
    decomposed = prefix + _filler("Report", 4100 - len(prefix))
    assert len(decomposed) > GROUP_WIDTH
    assert len(unicodedata.normalize("NFC", decomposed)) <= GROUP_WIDTH
    wide = _filler("Leverage", 5000)
    source_id = _admit(
        conn, case_id, tmp_path, (decomposed + "\n" + wide + "\n").encode()
    )

    assert _line_blocks(conn, source_id) == _admission_numbering(conn, source_id)
    every = frozenset(block_id for block_id, _ in _blocks(conn, source_id))
    [anchored] = verify_citations(
        conn,
        delivered={source_id: every},
        citations=[Citation(source_id, 1, "Leverage abcdefghij")],
    )
    assert anchored.bboxes


def test_a_line_that_shrinks_and_one_that_grows_keep_their_own_blocks(
    case: tuple[StoreConnection, UUID], tmp_path: Path, by_width: None
) -> None:
    """EV-1's silent half: one line shrinks under NFC and the next grows (U+2ADC
    is a composition exclusion, one code point NFC writes as two), so the
    totals agreed, the guard passed, and each line was handed the other's
    blocks -- a quote on an undelivered half of a line was accepted and a
    quote on a delivered line refused. Held on a width-packed source, as the
    test above is."""
    conn, case_id = case
    shrinks = _filler("Cafe\u0301", 4097)  # NFC 4,096: one block
    grows = _filler("\u2adc", 4096)  # NFC 4,097: two blocks
    data = (shrinks + "\n" + grows + "\n").encode()
    source_id = _admit(conn, case_id, tmp_path, data)

    numbering = _line_blocks(conn, source_id)
    assert numbering == _admission_numbering(conn, source_id)
    assert sorted(numbering.values()) == [("b000000",), ("b000001", "b000002")]
    with pytest.raises(Refusal, match=r"^CITATION_NOT_DELIVERED$"):
        verify_citations(
            conn,
            delivered={source_id: frozenset({"b000002"})},
            citations=[Citation(source_id, 1, "\u2adc abcdefghij")],
        )
    [anchored] = verify_citations(
        conn,
        delivered={source_id: frozenset({"b000000"})},
        citations=[Citation(source_id, 1, "Caf\u00e9 abcdefghij")],
    )
    assert anchored.bboxes


def _token_numbering(
    conn: StoreConnection, source_id: UUID
) -> dict[int, tuple[str, ...]]:
    """What admission wrote under packing 2, recomputed from the stored tokens."""
    lines: dict[int, list[str]] = {}
    for line_id, text in conn.execute(
        "SELECT line_id, text FROM source_tokens WHERE source_id = %s"
        " ORDER BY token_id",
        (source_id,),
    ).fetchall():
        lines.setdefault(int(line_id), []).append(str(text))
    return block_ids_by_line(
        {line_id: len(token_groups(words)) for line_id, words in lines.items()}
    )


def test_a_token_packed_line_that_shrinks_and_one_that_grows_keep_their_own_blocks(
    case: tuple[StoreConnection, UUID], tmp_path: Path
) -> None:
    """EV-1's shapes under packing 2. Its numbering is read back from the
    stored blocks -- each block's space-separated pieces walked against each
    line's tokens -- so no length is measured on either side's Unicode table,
    and each line keeps the blocks admission wrote for it."""
    conn, case_id = case
    shrinks = _filler("Cafe\u0301", 4097)  # NFC 4,096: one block
    grows = _filler("\u2adc", 4096)  # NFC 4,097: two blocks
    source_id = _admit(
        conn, case_id, tmp_path, (shrinks + "\n" + grows + "\n").encode()
    )

    assert _packing(conn, source_id) == PACKING_BY_TOKEN
    numbering = _line_blocks(conn, source_id, PACKING_BY_TOKEN)
    assert numbering == _token_numbering(conn, source_id)
    assert sorted(numbering.values()) == [("b000000",), ("b000001", "b000002")]
    with pytest.raises(Refusal, match=r"^CITATION_NOT_DELIVERED$"):
        verify_citations(
            conn,
            delivered={source_id: frozenset({"b000002"})},
            citations=[Citation(source_id, 1, "\u2adc abcdefghij")],
        )
    [anchored] = verify_citations(
        conn,
        delivered={source_id: frozenset({"b000000"})},
        citations=[Citation(source_id, 1, "Caf\u00e9 abcdefghij")],
    )
    assert anchored.bboxes


def test_a_token_packed_source_whose_blocks_no_longer_tile_its_lines_refuses(
    case: tuple[StoreConnection, UUID], tmp_path: Path
) -> None:
    """Packing 2 is read back from what admission wrote, so a store whose
    blocks no longer tile its lines -- here one removed past migration 0027's
    seal -- is not numbered by guesswork: `EVIDENCE_PACKING_MISMATCH`, the
    host's own reading failing, for every citation of the source."""
    conn, case_id = case
    source_id = _admit(conn, case_id, tmp_path, DOCUMENT)
    blocks = _blocks(conn, source_id)
    with conn.transaction():
        conn.execute("ALTER TABLE source_blocks DISABLE TRIGGER evidence_immutable")
        conn.execute(
            "DELETE FROM source_blocks WHERE source_id = %s AND block_id = %s",
            (source_id, blocks[2][0]),
        )
        conn.execute("ALTER TABLE source_blocks ENABLE TRIGGER evidence_immutable")

    with pytest.raises(Refusal, match=r"^EVIDENCE_PACKING_MISMATCH$"):
        verify_citations(
            conn,
            delivered={source_id: frozenset({blocks[0][0]})},
            citations=[Citation(source_id, 1, "Annual report of the issuer")],
        )


def test_the_store_and_the_host_agree_on_every_nfc_length(
    case: tuple[StoreConnection, UUID],
) -> None:
    """Anchoring measures NFC in the database and admission in Python, so the
    two Unicode tables must agree on what changes a length: a composition, a
    composition exclusion, Hangul, a singleton, reordering, and the pairs
    that compose without a combining mark."""
    conn, _case_id = case
    samples = (
        "e\u0301",
        "\u2adc",
        "\u1100\u1161\u11a8",
        "\u212b",
        "a\u0323\u0302",
        "\u0f73",
        "\U0001d15e",
        "\u0b47\u0b3e",
    )
    for sample in samples:
        row = conn.execute("SELECT length(normalize(%s, NFC))", (sample,)).fetchone()
        assert row is not None
        assert row[0] == len(unicodedata.normalize("NFC", sample)), ascii(sample)

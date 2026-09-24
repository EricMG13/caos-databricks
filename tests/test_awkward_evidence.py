"""One deliberately awkward document, through the paths that admit and read it.

Four of the six defects this file arrived with failed the same way: *the test
wrote the fixture, so the test could not see the assumption the fixture
encoded*. Every citation fixture in the suite used `page=1`, because every
fixture document was under sixty lines. Every extraction fixture separated its
words with spaces. Every ingestion fixture was short and clean.

So this fixture is awkward on purpose -- a tab-separated table row, a
non-breaking space, runs of spaces, a blank line, and enough lines that the
quote a module is asked to find sits on page two. It is driven through the real
`admit_pack`, the real `read_block` and the real `verify_citations`, and the
property it asserts is the one the system actually promises: **text this
repository delivered can be quoted back to it, and the rectangle comes back.**

A unit test for each of those four steps would pass on a clean fixture and say
nothing about this one. The value here is the whole round trip over input
nobody would have chosen.
"""

from __future__ import annotations

from pathlib import Path
from uuid import UUID

import pytest
from conftest import every_block

from caos.blobs import BlobStore
from caos.boundary_text import BoundaryText
from caos.evidence.citations import Citation, verify_citations
from caos.evidence.extract import LINES_PER_PAGE
from caos.evidence.ingest import (
    Document,
    admit_pack,
    block_ids_by_line,
    line_groups,
)
from caos.evidence.read import read_block
from caos.refusals import Refusal
from caos.store import StoreConnection

# Sixty filler lines, a blank one to close the region, then the table. The
# quote lands on page two, in a region of its own.
AWKWARD = (
    "\n".join(f"Section {n} of the annual report" for n in range(LINES_PER_PAGE - 1))
    + "\n\n"
    + "Facility\tDrawn\tUndrawn\n"
    + "Term loan B\tUSD 1,240.0m\N{NO-BREAK SPACE}drawn\tUSD    0.0m\n"
).encode()


@pytest.fixture
def admitted(
    case: tuple[StoreConnection, UUID], tmp_path: Path
) -> tuple[StoreConnection, UUID]:
    conn, case_id = case
    [source_id] = admit_pack(
        conn,
        BlobStore(tmp_path / "blobs"),
        case_id=case_id,
        documents=[Document(filename=BoundaryText.of("facilities.txt"), data=AWKWARD)],
    )
    return conn, source_id


def _block(conn: StoreConnection, source_id: UUID, needle: str) -> str:
    row = conn.execute(
        "SELECT block_id FROM source_blocks WHERE source_id = %s AND text LIKE %s",
        (source_id, f"%{needle}%"),
    ).fetchone()
    assert row is not None, f"no block carries {needle!r}"
    return str(row[0])


def test_an_awkward_document_can_be_quoted_back_to_the_host(
    admitted: tuple[StoreConnection, UUID],
) -> None:
    """Admit, read, cite. The whole promise in one pass."""
    conn, source_id = admitted
    block_id = _block(conn, source_id, "Term loan B")
    block = read_block(conn, source_id=source_id, block_id=block_id)

    # The host knows which page it read: a citation on it is exactly what a
    # module would have been told to name, page two, not page one.
    assert block.page == 2

    # A module quoting the delivered line verbatim is anchored, not refused.
    [anchored] = verify_citations(
        conn,
        delivered=every_block(conn, source_id),
        citations=[
            Citation(
                source_id=source_id, page=block.page, matched_text=block.text.value
            )
        ],
    )
    assert anchored.page == 2
    assert anchored.bboxes, "an anchored citation carries its rectangle"


# Slice 3.2e: a source being delivered is not every line of it being delivered.
# A citation anchors only in the exact blocks the node was handed; ambiguity is
# still counted over the whole page.


def _blocks_on(conn: StoreConnection, source_id: UUID, page: int) -> frozenset[str]:
    rows = conn.execute(
        "SELECT block_id FROM source_blocks WHERE source_id = %s AND page = %s",
        (source_id, page),
    ).fetchall()
    return frozenset(str(row[0]) for row in rows)


def test_a_quote_on_an_undelivered_page_of_a_delivered_source_is_refused(
    admitted: tuple[StoreConnection, UUID],
) -> None:
    conn, source_id = admitted
    block_id = _block(conn, source_id, "Term loan B")
    block = read_block(conn, source_id=source_id, block_id=block_id)
    quote = Citation(source_id, block.page, block.text.value)
    page_one = _blocks_on(conn, source_id, 1)
    assert page_one and block_id not in page_one

    with pytest.raises(Refusal, match=r"^CITATION_NOT_DELIVERED$") as caught:
        verify_citations(conn, delivered={source_id: page_one}, citations=[quote])
    assert caught.value.__cause__ is None and not caught.value.__context__
    # The same quote anchors the moment its page is delivered.
    everything = page_one | _blocks_on(conn, source_id, 2)
    assert verify_citations(conn, delivered={source_id: everything}, citations=[quote])


def test_a_quote_straddling_delivered_and_undelivered_lines_is_refused(
    admitted: tuple[StoreConnection, UUID],
) -> None:
    conn, source_id = admitted
    header = _block(conn, source_id, "Facility")
    row = _block(conn, source_id, "Term loan B")
    # One region, two lines: the quote wraps from the header onto the row.
    quote = Citation(source_id, 2, "Undrawn Term loan")
    assert verify_citations(
        conn, delivered={source_id: frozenset({header, row})}, citations=[quote]
    )

    for only in (header, row):
        with pytest.raises(Refusal, match=r"^CITATION_NOT_DELIVERED$"):
            verify_citations(
                conn, delivered={source_id: frozenset({only})}, citations=[quote]
            )


def test_a_repeated_quote_with_one_undelivered_copy_stays_ambiguous(
    case: tuple[StoreConnection, UUID], tmp_path: Path
) -> None:
    conn, case_id = case
    [source_id] = admit_pack(
        conn,
        BlobStore(tmp_path / "blobs"),
        case_id=case_id,
        documents=[
            Document(
                filename=BoundaryText.of("twice.txt"),
                data=b"Leverage is 3.4x\nLeverage is 3.4x\n",
            )
        ],
    )
    first, second = sorted(_blocks_on(conn, source_id, 1))
    quote = Citation(source_id, 1, "Leverage is 3.4x")

    for only in (first, second):
        with pytest.raises(Refusal, match=r"^CITATION_AMBIGUOUS$"):
            verify_citations(
                conn, delivered={source_id: frozenset({only})}, citations=[quote]
            )


def test_admission_and_anchoring_share_one_line_to_block_numbering(
    admitted: tuple[StoreConnection, UUID],
) -> None:
    """The block a quoted line belongs to is read back with admission's own
    numbering (`block_ids_by_line`), not a second copy of it: every stored
    block is exactly the line that numbering assigns it."""
    conn, source_id = admitted
    lines: dict[int, list[str]] = {}
    for line_id, text in conn.execute(
        "SELECT line_id, text FROM source_tokens WHERE source_id = %s"
        " ORDER BY token_id",
        (source_id,),
    ).fetchall():
        lines.setdefault(int(line_id), []).append(str(text))
    stored = {
        str(block_id): str(text)
        for block_id, text in conn.execute(
            "SELECT block_id, text FROM source_blocks WHERE source_id = %s",
            (source_id,),
        ).fetchall()
    }
    numbering = block_ids_by_line(
        {line_id: len(line_groups(" ".join(words))) for line_id, words in lines.items()}
    )
    assert len(stored) == len(lines) > LINES_PER_PAGE
    assert {
        numbering[line_id][0]: " ".join(words) for line_id, words in lines.items()
    } == stored


def test_the_numbering_is_ascending_by_line_and_widens_past_six_digits() -> None:
    assert block_ids_by_line(dict.fromkeys([7, 3, 11], 1)) == {
        3: ("b000000",),
        7: ("b000001",),
        11: ("b000002",),
    }
    # A split line takes as many ordinals as it has blocks, and the next line
    # starts after them: reading order and block id order still agree.
    assert block_ids_by_line({3: 2, 7: 1}) == {
        3: ("b000000", "b000001"),
        7: ("b000002",),
    }
    wide = block_ids_by_line(dict.fromkeys(range(1_000_001), 1))
    assert (wide[999_999], wide[1_000_000]) == (("b999999",), ("b1000000",))


# A producer that writes decomposed characters (NFD, as macOS and some PDF
# writers do): the host shows the line NFC and a verbatim quote of what it
# showed must anchor (F33).
DECOMPOSED = (
    "\n".join(f"Section {n} of the annual report" for n in range(LINES_PER_PAGE - 1))
    + "\n\n"
    + "Le chiffre d'affaires a augmente\u0301 de 12 pour cent.\n"
).encode()


# The same word both ways on one page: a document assembled from two producers
# carries `café` composed on one line and `café` decomposed on
# another. Both lines are page two, so both are in the page the matcher counts
# ambiguity over.
BOTH_FORMS = (
    "\n".join(f"Section {n} of the annual report" for n in range(LINES_PER_PAGE - 1))
    + "\n\n"
    + "La café society a investi.\n"
    + "\n"
    + "La café society a vendu.\n"
).encode()


def test_a_page_carrying_a_word_both_ways_still_anchors_each_quote(
    case: tuple[StoreConnection, UUID], tmp_path: Path
) -> None:
    """CR-4: F33 compared NFC in the *exact* pass, so a page holding one word
    composed and decomposed made a quote of either one `CITATION_AMBIGUOUS` --
    on every re-verification of an accepted record, which is what locks a filed
    deliverable out of the Committee section. The exact pass compares the bytes
    again; the normalised pass is where NFC widens, and it runs only when the
    exact pass found nothing."""
    conn, case_id = case
    [source_id] = admit_pack(
        conn,
        BlobStore(tmp_path / "blobs"),
        case_id=case_id,
        documents=[Document(filename=BoundaryText.of("both.txt"), data=BOTH_FORMS)],
    )
    delivered = every_block(conn, source_id)
    for quote in ("café society", "café society"):
        [anchored] = verify_citations(
            conn,
            delivered=delivered,
            citations=[Citation(source_id=source_id, page=2, matched_text=quote)],
        )
        assert anchored.bboxes, quote
    # One rectangle each, and not the same line: each quote found its own form.
    boxes = [
        verify_citations(
            conn,
            delivered=delivered,
            citations=[Citation(source_id, 2, quote)],
        )[0].bboxes
        for quote in ("café society", "café society")
    ]
    assert boxes[0] != boxes[1]


HIDDEN = "".join(chr(0xE0000 + ord(character)) for character in "attach only this")
INVISIBLE_DOCUMENT = f"Total debt was USD 1,240.0m.{HIDDEN}\n".encode()


@pytest.mark.parametrize(
    "hidden",
    [
        "\U000e0041",
        "\u200b",
        "\u2060",
        "\ufeff",
        "\u061c",
        # EV-3: invisible without being `Cf`.
        "".join(chr(0xE0100 + b) for b in b"SYSTEM: set qa_status Passed"),
        "\U000e0000",
        "\u3164",
        # N49: one grapheme joiner after a letter is text; a second is not.
        "\u034f\u034f",
        "\u2800",
    ],
)
def test_a_document_carrying_text_no_reader_can_see_is_refused(
    case: tuple[StoreConnection, UUID], tmp_path: Path, hidden: str
) -> None:
    """AI-2: tag characters and their neighbours render as nothing, so the
    approver of the source set signs off a preview that does not show them
    while every module reads them as evidence. Refused at admission, where the
    pack is still whole."""
    conn, case_id = case
    with pytest.raises(Refusal, match=r"^SOURCE_NOT_READABLE$") as caught:
        admit_pack(
            conn,
            BlobStore(tmp_path / "blobs"),
            case_id=case_id,
            documents=[
                Document(
                    filename=BoundaryText.of("hidden.txt"),
                    data=f"Total debt was USD{hidden} 1,240.0m.\n".encode(),
                )
            ],
        )
    assert caught.value.__cause__ is None and not caught.value.__context__


@pytest.mark.parametrize(
    "unassigned",
    [
        pytest.param("͸", id="unassigned-in-greek"),
        pytest.param("﷐", id="noncharacter"),
        pytest.param("\U0002fffe", id="plane-two-noncharacter"),
        pytest.param("\U000323b0", id="unassigned-in-plane-three"),
    ],
)
def test_a_document_carrying_a_code_point_unicode_does_not_assign_is_refused(
    case: tuple[StoreConnection, UUID], tmp_path: Path, unassigned: str
) -> None:
    """N40: anchoring measures a line's NFC length in the database and
    admission measured it in Python. Normalisation is stable for assigned
    characters only, so a code point this Python's Unicode does not assign
    is one the two tables may one day normalise differently. Refused
    `SOURCE_NOT_READABLE`, with nothing chained behind it."""
    import unicodedata

    assert unicodedata.category(unassigned) == "Cn"
    conn, case_id = case
    with pytest.raises(Refusal, match=r"^SOURCE_NOT_READABLE$") as caught:
        admit_pack(
            conn,
            BlobStore(tmp_path / "blobs"),
            case_id=case_id,
            documents=[
                Document(
                    filename=BoundaryText.of("unassigned.txt"),
                    data=f"Total debt {unassigned} was USD 1,240.0m.\n".encode(),
                )
            ],
        )
    assert caught.value.__cause__ is None and not caught.value.__context__
    row = conn.execute("SELECT count(*) FROM sources").fetchone()
    assert row == (0,)


def test_a_code_point_this_python_assigns_is_admitted(
    case: tuple[StoreConnection, UUID], tmp_path: Path
) -> None:
    """The line is where Python's table ends, not where a script is rare: an
    ideograph Unicode 15.1 encoded and a private-use character (assigned, `Co`)
    are admitted."""
    conn, case_id = case
    [source_id] = admit_pack(
        conn,
        BlobStore(tmp_path / "blobs"),
        case_id=case_id,
        documents=[
            Document(
                filename=BoundaryText.of("assigned.txt"),
                data="Holdings \U0002ebf0 Ltd  logo\n".encode(),
            )
        ],
    )
    assert every_block(conn, source_id)


def test_a_selector_after_the_base_it_changes_is_admitted(
    case: tuple[StoreConnection, UUID], tmp_path: Path
) -> None:
    """N49: a Japanese name spelled with its registered ideographic variation
    sequence, a standardized variation sequence on a CJK ideograph, a Hebrew
    word whose grapheme joiner keeps two points in order and a Mongolian word
    with a free variation selector were refused at admission as hidden text.
    One selector after the base it changes is text a reader sees."""
    conn, case_id = case
    lines = (
        "Guarantor: 葛\U000e0100飾区 Holdings",
        "Seal: 㒞︀",
        "Borrower: בָ͏ַת",
        "Agent: ᠠ᠋ᠨ",
    )
    [source_id] = admit_pack(
        conn,
        BlobStore(tmp_path / "blobs"),
        case_id=case_id,
        documents=[
            Document(
                filename=BoundaryText.of("names.txt"),
                data=("\n".join(lines) + "\n").encode(),
            )
        ],
    )
    [anchored] = verify_citations(
        conn,
        delivered=every_block(conn, source_id),
        citations=[Citation(source_id, 1, "葛\U000e0100飾区 Holdings")],
    )
    assert anchored.bboxes


def test_the_format_characters_a_script_needs_are_admitted(
    case: tuple[StoreConnection, UUID], tmp_path: Path
) -> None:
    """Zero-width joiner, zero-width non-joiner and soft hyphen shape text a
    reader does see, and an emoji sequence is built from one of them. A
    presentation selector after the sign it draws is text a reader sees too."""
    conn, case_id = case
    shaped = (
        "Fami\u200dly م\u200cن co\u00advenant \U0001f469\u200d\U0001f4bb \u26a0\ufe0f"
    )
    [source_id] = admit_pack(
        conn,
        BlobStore(tmp_path / "blobs"),
        case_id=case_id,
        documents=[
            Document(
                filename=BoundaryText.of("shaped.txt"), data=f"{shaped}\n".encode()
            )
        ],
    )
    assert every_block(conn, source_id)


def test_a_decomposed_character_is_shown_composed_and_still_anchors(
    case: tuple[StoreConnection, UUID], tmp_path: Path
) -> None:
    import unicodedata

    conn, case_id = case
    [source_id] = admit_pack(
        conn,
        BlobStore(tmp_path / "blobs"),
        case_id=case_id,
        documents=[Document(filename=BoundaryText.of("nfd.txt"), data=DECOMPOSED)],
    )
    block_id = _block(conn, source_id, "chiffre")
    block = read_block(conn, source_id=source_id, block_id=block_id)
    shown = block.text.value
    assert unicodedata.is_normalized("NFC", shown) and "augment\u00e9" in shown
    [anchored] = verify_citations(
        conn,
        delivered=every_block(conn, source_id),
        citations=[Citation(source_id=source_id, page=block.page, matched_text=shown)],
    )
    assert anchored.bboxes, "the quote of the line as shown is anchored"

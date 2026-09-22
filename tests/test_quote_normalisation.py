"""Task 10.5: the two normalisations `docs/COMPLETION_PLAN.md` Phase 10 names.

Its exit check is "a letter-spaced heading and a quote ending in a full stop
anchor to the rectangle a reader sees". Both are refused today, and both are
refused for a reason the host created: the full stop because a quote is split
on whitespace and every word must equal a token, and the heading because
pdfminer inserts a virtual word break between glyphs tracked past
`word_margin` (`§44.5`), so the word comes back one token per letter.

Two rules, and the order between them is the whole of their safety. The exact
search runs first and unchanged; a normalised search runs **only** when the
exact one found nothing. So the widening is monotone -- every quote that
anchored before anchors to the same rectangles, and every stored record
re-verifies -- and a normalisation can never resolve an ambiguity, because an
ambiguous exact match never reaches it.
"""

from __future__ import annotations

from pathlib import Path
from uuid import UUID

import pytest
from test_pdf_extraction import (
    FIRST_LINE,
    _ingest_pdf,
    kerned_pdf,
    minimal_pdf,
    tracked_pdf,
)

from caos.blobs import BlobStore
from caos.boundary_text import BoundaryText
from caos.evidence.citations import (
    NORMALISATION_VERSION,
    TRACKING_EXTRACTORS,
    _extractor_name,
    anchor_citation,
)
from caos.evidence.ingest import Document, admit_pack
from caos.refusals import Refusal, RefusalCode
from caos.store import StoreConnection


def test_a_quote_ending_in_a_full_stop_anchors_to_the_words_it_names(
    case: tuple[StoreConnection, UUID], tmp_path: Path
) -> None:
    """The plan's second named case. `FIRST_LINE` ends `USD 1,240.0m` with no
    full stop, and a module writing the sentence ends it with one."""
    conn, case_id = case
    source_id = _ingest_pdf(conn, case_id, tmp_path, minimal_pdf([FIRST_LINE]))

    with_stop = anchor_citation(
        conn, source_id=source_id, page=1, matched_text="was USD 1,240.0m."
    )
    without = anchor_citation(
        conn, source_id=source_id, page=1, matched_text="was USD 1,240.0m"
    )

    assert with_stop == without


def test_a_letter_spaced_heading_anchors_as_the_word_a_reader_sees(
    case: tuple[StoreConnection, UUID], tmp_path: Path
) -> None:
    """The plan's first named case, and the rectangle is the union of the
    glyphs: a reader who opens the citation sees the highlight over the whole
    tracked word, which is what they read it as."""
    conn, case_id = case
    source_id = _ingest_pdf(conn, case_id, tmp_path, tracked_pdf("Hello", 3))

    [joined] = anchor_citation(conn, source_id=source_id, page=1, matched_text="Hello")
    letters = [
        anchor_citation(conn, source_id=source_id, page=1, matched_text=letter)
        for letter in ("H", "o")
    ]

    assert joined.x0 == pytest.approx(letters[0][0].x0)
    assert joined.x1 == pytest.approx(letters[1][0].x1)


def test_two_widely_spaced_words_still_refuse_their_concatenation(
    case: tuple[StoreConnection, UUID], tmp_path: Path
) -> None:
    """The guard the tracking rule must not reopen. `Alpha` and `Beta` kerned
    apart are two tokens, `AlphaBeta` is on no rendered page, and the rule
    above does not reach them because neither token is a single character --
    which is the axis that separates a tracked word from two words."""
    conn, case_id = case
    source_id = _ingest_pdf(conn, case_id, tmp_path, kerned_pdf("Alpha", "Beta", -1000))

    with pytest.raises(Refusal) as caught:
        anchor_citation(conn, source_id=source_id, page=1, matched_text="AlphaBeta")

    assert caught.value.code is RefusalCode.CITATION_NOT_LOCATED


def test_a_quote_the_document_does_not_carry_is_still_refused(
    case: tuple[StoreConnection, UUID], tmp_path: Path
) -> None:
    """Neither normalisation invents text: stripping the edges of a quote
    whose words are not there leaves words that are not there."""
    conn, case_id = case
    source_id = _ingest_pdf(conn, case_id, tmp_path, minimal_pdf([FIRST_LINE]))

    with pytest.raises(Refusal) as caught:
        anchor_citation(
            conn, source_id=source_id, page=1, matched_text="was USD 9,999.9m."
        )

    assert caught.value.code is RefusalCode.CITATION_NOT_LOCATED


def test_interior_punctuation_is_never_stripped(
    case: tuple[StoreConnection, UUID], tmp_path: Path
) -> None:
    """Only the quote's outer edges are typography the host forgives. A word
    inside the run must equal its token, or the quote names a sentence the
    document does not carry."""
    conn, case_id = case
    source_id = _ingest_pdf(conn, case_id, tmp_path, minimal_pdf([FIRST_LINE]))

    with pytest.raises(Refusal) as caught:
        anchor_citation(
            conn, source_id=source_id, page=1, matched_text="Total debt. at"
        )

    assert caught.value.code is RefusalCode.CITATION_NOT_LOCATED


def test_a_normalised_match_found_twice_is_ambiguous(
    case: tuple[StoreConnection, UUID], tmp_path: Path
) -> None:
    """Ambiguity is counted in the normalised pass exactly as in the exact
    one. The page carries the sentence twice and neither copy ends in a full
    stop, so the exact search finds nothing and the normalised search finds
    two places the quote could be -- which is a refusal, not a choice."""
    conn, case_id = case
    line = "Revenue rose in the fourth quarter"
    source_id = _ingest_pdf(conn, case_id, tmp_path, minimal_pdf([line, line]))

    with pytest.raises(Refusal) as caught:
        anchor_citation(conn, source_id=source_id, page=1, matched_text="Revenue rose.")

    assert caught.value.code is RefusalCode.CITATION_AMBIGUOUS


def test_the_exact_search_is_preferred_and_unchanged(
    case: tuple[StoreConnection, UUID], tmp_path: Path
) -> None:
    """A tracked word quoted letter by letter is an exact match, so the
    normalisation never runs and the rectangles are the letters' own."""
    conn, case_id = case
    source_id = _ingest_pdf(conn, case_id, tmp_path, tracked_pdf("Hello", 3))

    spelled = anchor_citation(
        conn, source_id=source_id, page=1, matched_text="H e l l o"
    )

    assert len(spelled) == 1


def test_the_declared_normalisations_carry_a_version() -> None:
    """A reader asking which rule anchored a quote has one thing to name."""
    assert NORMALISATION_VERSION == "1"


def test_a_plain_text_document_never_joins_its_single_character_words(
    case: tuple[StoreConnection, UUID], tmp_path: Path
) -> None:
    """The scoping claim, driven rather than asserted about. `caos.plain-text`
    has no `word_margin` and no tracking: a single-character token there is a
    single-character *word*, and joining `a b c` into `abc` would anchor a
    concatenation the file does not contain. Only `caos.pdfminer` is in
    `TRACKING_EXTRACTORS`, and this is what says so."""
    conn, case_id = case
    [source_id] = admit_pack(
        conn,
        BlobStore(tmp_path / "blobs"),
        case_id=case_id,
        documents=[
            Document(filename=BoundaryText.of("notes.txt"), data=b"option a b c here")
        ],
    )

    with pytest.raises(Refusal) as caught:
        anchor_citation(conn, source_id=source_id, page=1, matched_text="abc")

    assert caught.value.code is RefusalCode.CITATION_NOT_LOCATED


@pytest.mark.parametrize(
    "identity",
    [
        None,  # `source_extractions` carries no row: UNKNOWN, never today's adapter.
        "not json at all",
        '["caos.pdfminer"]',  # valid JSON, not an object
        '{"version": "2"}',  # an object with no name
        '{"name": 7}',  # a name that is not a string
    ],
)
def test_an_identity_this_build_cannot_read_gets_the_exact_search_alone(
    identity: str | None,
) -> None:
    """Fail closed, and never carry the stored text out. Every shape that is
    not a readable identity answers the same as no row at all, which is the
    exact search and no normalisation."""
    assert _extractor_name(identity) not in TRACKING_EXTRACTORS


def test_a_readable_pdf_identity_is_the_one_that_tracks() -> None:
    """The other side of the test above: without this, the parametrisation
    would pass against a function that always returned the empty string."""
    assert _extractor_name('{"name": "caos.pdfminer"}') in TRACKING_EXTRACTORS

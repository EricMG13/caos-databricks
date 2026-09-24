"""Task 10.5: the two normalisations tested here.

The requirement is that a letter-spaced heading and a quote ending in a full
stop still anchor to the rectangle a reader sees. Both are refused today, and both are
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
    _match_at,
    _Token,
    _unique_run,
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


def _line(*words: str, regions: tuple[int, ...] = ()) -> list[_Token]:
    """One line of tokens, a point apart, in one region unless told otherwise."""
    return [
        _Token(word, regions[at] if regions else 0, 0, float(at), 0.0, at + 1.0, 1.0)
        for at, word in enumerate(words)
    ]


def _located(tokens: list[_Token], quote: str, *, tracking: bool = False) -> str:
    try:
        run = _unique_run(tokens, quote, tracking=tracking)
    except Refusal as refused:
        return refused.code.value
    return " ".join(token.text for token in run)


@pytest.mark.parametrize(
    ("page", "quote"),
    [
        (("Net", "income", "(5)"), "Net income 5"),  # a loss shown as a profit
        (("Net", "income", "(5)."), "Net income 5"),
        (("Margin", "of", ".5"), "Margin of 5"),  # a point moved
        (("Covenant", "headroom", "12"), "Covenant headroom (12)"),
        (("(5)", "net", "loss"), "5 net loss"),
        (("(USD", "5)"), "USD 5"),  # the parenthesis on the figure's own word
    ],
)
def test_a_figure_keeps_the_marks_that_change_what_it_says(
    page: tuple[str, ...], quote: str
) -> None:
    """EV-4: accounting parentheses negate a figure and a leading point moves
    it, yet both were stripped from a quote's edge, so a quote stating a
    different number from the page anchored and was shown host-verified. A
    word with a digit in it keeps them; quotation marks, brackets and a
    sentence's closing punctuation are still forgiven."""
    assert _located(_line(*page), quote) == "CITATION_NOT_LOCATED"


@pytest.mark.parametrize(
    ("page", "quote", "anchored"),
    [
        (("Net", "loss", "(5)"), "Net loss (5).", "Net loss (5)"),
        (("Net", "loss", "(5)"), '"Net loss (5)"', "Net loss (5)"),
        (("Total", "2026"), "Total 2026.", "Total 2026"),
        (("was", "USD", "1,240.0m"), "was USD 1,240.0m.", "was USD 1,240.0m"),
        (("Margin", "of", ".5"), "Margin of .5,", "Margin of .5"),
        (("(see", "note", "the", "appendix)"), "see note the appendix", None),
        (("footnote", "[5]"), "footnote 5", "footnote [5]"),
    ],
)
def test_a_figure_still_forgives_what_a_sentence_puts_around_it(
    page: tuple[str, ...], quote: str, anchored: str | None
) -> None:
    expected = " ".join(page) if anchored is None else anchored
    assert _located(_line(*page), quote) == expected


def test_single_digits_are_never_joined_into_a_number() -> None:
    """EV-4's second half: the tracking join read two table cells `3` and `4`
    on one line as the figure `34`. A tracked word is letters; digits a column
    apart are two numbers."""
    cells = _line("Leverage", "3", "4")
    assert _located(cells, "Leverage 34", tracking=True) == "CITATION_NOT_LOCATED"
    assert _located(cells, "Leverage 3 4", tracking=True) == "Leverage 3 4"
    letters = _line("H", "e", "a", "d", "word")
    assert _located(letters, "Head word", tracking=True) == "Head word"


def test_the_declared_normalisations_moved_their_version() -> None:
    """EV-4 narrowed two of them, so a quote anchored under the first version
    may not anchor under this one; the version says which rule a reader met."""
    assert NORMALISATION_VERSION == "2"


def test_an_ambiguous_quote_stops_at_its_second_place() -> None:
    """MAX-06: every match was kept, each a quote-sized slice, before the
    count was read -- a repeated page and a long quote held millions of token
    references to refuse once. The search stops at the second place."""
    import tracemalloc

    page = _line(*(["a"] * 5_000))
    tracemalloc.start()
    try:
        with pytest.raises(Refusal, match=r"^CITATION_AMBIGUOUS$"):
            _unique_run(page, " ".join(["a"] * 1_000))
        _current, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert peak < 2_000_000, peak


@pytest.mark.parametrize("normalised", ["last", "edges", "region"])
def test_a_long_near_match_costs_no_more_than_the_page(normalised: str) -> None:
    """MAX-06's other half: a quote that matches the page almost everywhere and
    fails at its last word, or at a region, was compared word by word from
    every start. The search is linear in the page and the quote now."""
    import time

    size, width = 50_000, 5_000
    regions = tuple(at // (width - 1) for at in range(size))
    page = _line(*(["a"] * size), regions=regions if normalised == "region" else ())
    words = ["a"] * width
    if normalised == "last":
        words[-1] = "b"
    elif normalised == "edges":
        words[0], words[-1] = '"a', 'b."'
    started = time.perf_counter()
    with pytest.raises(Refusal, match=r"^CITATION_NOT_LOCATED$"):
        _unique_run(page, " ".join(words))
    assert time.perf_counter() - started < 1.0


def _every_start(
    tokens: list[_Token], words: list[str], *, normalised: bool
) -> list[_Token] | str | None:
    """The search as it was: `_match_at` asked at every start, every match
    kept. The rule the new search must find, whatever it costs here."""
    matches = [
        run
        for start in range(len(tokens))
        if (run := _match_at(tokens, start, words, normalised=normalised))
    ]
    if len(matches) > 1:
        return "CITATION_AMBIGUOUS"
    return matches[0] if matches else None


def test_the_linear_search_finds_what_every_start_found() -> None:
    """MAX-06: the new search against the old one on pages built to collide --
    a small vocabulary, repeats, regions a few tokens long, edge punctuation,
    figures and decomposed words -- in both passes, over thousands of quotes."""
    import random

    from caos.evidence.citations import _one_match

    rng = random.Random(20260923)
    vocabulary = ["a", "b", "a.", '"a', "(5)", "5", ".5", "e\u0301", "\u00e9", "ab"]
    for _page in range(300):
        size = rng.randint(1, 30)
        regions = sorted(rng.randint(0, 4) for _ in range(size))
        page = _line(*rng.choices(vocabulary, k=size), regions=tuple(regions))
        for _quote in range(12):
            width = rng.randint(1, 5)
            words = rng.choices(vocabulary, k=width)
            for normalised in (False, True):
                expected = _every_start(page, words, normalised=normalised)
                try:
                    found: object = _one_match(page, words, normalised=normalised)
                except Refusal as refused:
                    found = refused.code.value
                assert found == expected, (page, words, normalised)


def test_a_region_boundary_still_splits_a_run_found_by_the_new_search() -> None:
    """The one match that crosses a region is no match, and the one that does
    not is found, on a page that carries both."""
    page = _line("x", "y", "z", "x", "y", "z", regions=(0, 0, 1, 1, 1, 1))
    assert _located(page, "x y z") == "x y z"
    run = _unique_run(page, "x y z")
    assert run == page[3:6]


def test_one_index_derives_a_pages_search_keys_once(
    case: tuple[StoreConnection, UUID], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """N41: every citation of a page rebuilt the page's search keys -- its
    words' NFC and, for a tracking extractor, the page with tracked letters
    joined -- so 512 citations of a 240,000-token page spent 18 s rebuilding
    them. One `TokenIndex` now derives them once per page, and each citation
    anchors where a fresh index anchors it."""
    from conftest import every_block

    from caos.evidence import citations
    from caos.evidence.citations import Citation, TokenIndex, verify_citations

    conn, case_id = case
    document = minimal_pdf([FIRST_LINE, "Cash and equivalents stood at USD 310.5m"])
    source_id = _ingest_pdf(conn, case_id, tmp_path, document)
    delivered = every_block(conn, source_id)
    # Each ends in a full stop the page does not carry: the normalised pass.
    quotes = [
        Citation(source_id, 1, text)
        for text in (
            "Total debt at 31 December.",
            "at USD 310.5m.",
            "was USD 1,240.0m.",
        )
    ]
    joins: list[int] = []
    normalised: list[int] = []
    join, nfc = citations._joined_tracking, citations._nfc

    def counted_join(tokens: list[_Token]) -> list[_Token]:
        joins.append(len(tokens))
        return join(tokens)

    def counted_nfc(text: str) -> str:
        normalised.append(1)
        return nfc(text)

    monkeypatch.setattr(citations, "_joined_tracking", counted_join)
    monkeypatch.setattr(citations, "_nfc", counted_nfc)
    index = TokenIndex()
    shared = [
        verify_citations(conn, delivered=delivered, citations=[quote], index=index)
        for quote in quotes
    ]
    shared_calls = len(normalised)
    assert len(joins) == 1
    [tokens] = joins

    normalised.clear()
    fresh = [
        verify_citations(conn, delivered=delivered, citations=[quote])
        for quote in quotes
    ]
    assert fresh == shared
    assert len(joins) == 1 + len(quotes)
    # A fresh index derived the page's NFC keys once per citation.
    assert shared_calls + (len(quotes) - 1) * tokens <= len(normalised)

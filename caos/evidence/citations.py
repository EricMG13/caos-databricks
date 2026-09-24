"""Invariant 11: the host re-locates the quote, and refuses one it cannot.

A citation as a module offers it is `{source_id, page, matched_text}`. What
reaches an artifact is that plus the coordinates the host derived by finding the
quote in its own token index. The module never supplies a rectangle, because a
rectangle it supplied would be a claim nobody checked.

Two rules make the search honest:

*Exactly once.* A quote found twice is refused rather than resolved to the first
match. Highlighting one of two identical sentences asserts a precision the host
does not have.

*Never across a region.* Matching joins tokens within a line and continues only
onto the next line of the same region. Two columns are two regions, so a phrase
cannot be assembled across the gutter between them -- which is what a naive
scan of page text does, and what it silently produces is a quote that exists
nowhere on the page.

*One whole line, where an answer is accepted* (N28, `WHOLE_LINE`). The final
check tells a module that `matched_text` is the complete text of one evidence
line, and the host now holds it to that: a quote anchors only on a line as the
module was shown it, word for word (W6, N13). Any unique run anchored before,
so a fragment that dropped a "not" was shown as a host-verified source fact
(AI-4). A record names the rule it was accepted under and is re-anchored by
it (`ANY_RUN` when it names none, `WHOLE_LINE_AS_STORED` for N28's first
reading), so no stored record starts refusing.

The result is one rectangle per line the quote covers, the shape a PDF
highlight's QuadPoints uses and for the same reason: selected text wraps, and a
single enclosing rectangle would cover text the quote does not contain.
"""

from __future__ import annotations

import functools
import json
import unicodedata
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from itertools import groupby
from typing import Literal
from uuid import UUID

from caos.evidence.ingest import (
    GROUP_WIDTH,
    PACKING_BY_TOKEN,
    PACKING_BY_WIDTH,
    block_ids_by_line,
)
from caos.refusals import Refusal, RefusalCode
from caos.store import StoreConnection


@dataclass(frozen=True, slots=True)
class Rect:
    """One line's worth of a quote, in page coordinates."""

    page: int
    x0: float
    y0: float
    x1: float
    y1: float


@dataclass(frozen=True, slots=True)
class Citation:
    """What a module offers: where it says the quote is, and what it says it is."""

    source_id: UUID
    page: int
    matched_text: str


@dataclass(frozen=True, slots=True)
class AnchoredCitation:
    """What reaches the artifact: the module's claim, re-derived by the host."""

    document_sha256: str
    page: int
    matched_text: str
    bboxes: tuple[Rect, ...]


@dataclass(frozen=True, slots=True)
class _Token:
    text: str
    region_id: int
    line_id: int
    x0: float
    y0: float
    x1: float
    y1: float


# The declared quote normalisations.
#
# They are tried **only** after the exact search above has found nothing, which
# is what makes them safe: the widening is monotone, so every quote that
# anchored before this existed anchors to the same rectangles, every stored
# record re-verifies, and a normalisation can never resolve an ambiguity --
# an ambiguous exact match refuses before the normalised pass is reached.
#
# Version 2 narrowed them (EV-4): a word with a digit in it keeps its
# parentheses and a leading point, and single digits are never joined. A quote
# that anchored under version 1 only by losing one of those named a different
# figure from the page, and no longer anchors.
NORMALISATION_VERSION = "2"

# What a quote may carry at its outer edges that the token does not, or the
# other way round: a module writing a sentence ends it with a full stop and
# wraps a quotation in quotation marks. Only the first and last word of a run
# are stripped; an interior word must equal its token, or the quote names a
# sentence the page does not carry.
EDGE_PUNCTUATION = "\"'\u201c\u201d\u2018\u2019()[]{}.,;:!?"
# What an edge word with a digit in it may lose on each side: everything above
# but the marks that change the figure. Accounting parentheses negate it -- a
# loss of `(5)` quoted as `5` is a profit -- and a leading point moves it:
# `.5` quoted as `5` is ten times the page (EV-4). A trailing point is a
# sentence's full stop and still goes.
_FIGURE_LEFT = EDGE_PUNCTUATION.replace("(", "").replace(".", "")
_FIGURE_RIGHT = EDGE_PUNCTUATION.replace(")", "")

# How a citation is located (N28, D39). `WHOLE_LINE` is the rule an answer is
# accepted under: the quote is one whole evidence line as the evidence section
# showed it -- a block of the page, which is its line wherever the line fits
# and a token-cut piece of it where it did not (`_shown`), read word by word
# as the module read it, NFC -- and it must be the only such line on the page:
# two lines shown alike are ambiguous, however each is stored (N13). Only
# where no line is, the edge punctuation the normalised pass forgives, and
# then, on a tracking extractor, the line with its tracked letters joined
# (`_shown_line_run`, W6). `WHOLE_LINE_AS_STORED` is that rule as N28 first
# accepted answers under it -- the line's stored tokens byte for byte first,
# and past them only the tracked-letter line -- which refused a line copied
# exactly as shown when the PDF stored an accent decomposed or tracked a `$`,
# and anchored the stored form of one of two lines shown alike. `ANY_RUN` is
# the rule every record accepted before either was located by, any unique run
# of the page. A record names the rule it was accepted under
# (`CanonicalRecord.citation_rule`) and is re-anchored by it, so a rule
# changing never refuses or moves a record accepted before it.
# `anchor_citation`, the extractor suites' probe of where a quote is, stays
# `ANY_RUN`.
type CitationRule = Literal["any-run", "whole-line", "whole-line-as-shown"]
ANY_RUN: CitationRule = "any-run"
WHOLE_LINE_AS_STORED: CitationRule = "whole-line"
WHOLE_LINE: CitationRule = "whole-line-as-shown"
CITATION_RULES: frozenset[CitationRule] = frozenset(
    {ANY_RUN, WHOLE_LINE_AS_STORED, WHOLE_LINE}
)

# Glyphs tracked past pdfminer's `word_margin` come back one token per letter
# (section 44.5), so a heading tracked for display cannot be quoted as a word.
# Joining them is scoped to the extractor whose rule split them: in plain text
# a single-character token is a single-character word, and joining those would
# anchor a concatenation the file does not contain.
TRACKING_EXTRACTORS = frozenset({"caos.pdfminer"})


# The form the block was shown in: admission stores a token's own bytes but
# renders the line NFC, so a quote of what was shown must compare NFC (F33).
# Applied in the normalised pass alone, so a page carrying one word in both
# forms still anchors the quote that equals one of them exactly (CR-4). NFC and
# never NFKC, which would anchor `x2` on a page's `x²` (EV-8). A partial of the
# C function, so the search maps it over a page with no Python call per token.
_nfc = functools.partial(unicodedata.normalize, "NFC")


def _stripped(word: str) -> str:
    """An edge word less the punctuation a sentence puts around it, NFC.

    A word with a digit in it keeps what would change its figure: its
    parentheses and a leading point (`_FIGURE_LEFT`, `_FIGURE_RIGHT`).
    """
    normalised = _nfc(word)
    core = normalised.strip(EDGE_PUNCTUATION)
    if not any(character.isdigit() for character in core):
        return core
    return normalised.lstrip(_FIGURE_LEFT).rstrip(_FIGURE_RIGHT)


def _joined_tracking(tokens: list[_Token]) -> list[_Token]:
    """Each maximal run of single-letter tokens on one line of one region,
    joined into the word a reader sees, with the union of their rectangles.

    The grouping key *is* the rule, which is why it is written as one: tokens
    are consecutive, single-character, not a digit, and share a line and a
    region. Maximal follows from `groupby`, and so does the bound that matters
    -- any token that is not a single character has a different key, so it
    ends the run and is carried through untouched. `Alpha` and `Beta` kerned
    apart are tokens of five and four characters, so `AlphaBeta` -- text on no
    rendered page -- is out of this rule's reach, which is the axis that
    separates a tracked word from two words and what
    `test_two_widely_spaced_words_still_refuse_their_concatenation` holds.

    A digit is never joined (EV-4): two table cells `3` and `4` on one line are
    two figures, and joining them anchored a quote of `34`.

    A run of one is not a join, so it is carried through as itself rather than
    rebuilt: a single-character token is already the word it is.
    """
    joined: list[_Token] = []
    for (single, _line, _region), group in groupby(
        tokens,
        key=lambda token: (
            len(token.text) == 1 and not token.text.isdigit(),
            token.line_id,
            token.region_id,
        ),
    ):
        run = list(group)
        if not single or len(run) == 1:
            joined.extend(run)
            continue
        joined.append(
            _Token(
                text="".join(token.text for token in run),
                region_id=run[0].region_id,
                line_id=run[0].line_id,
                x0=min(token.x0 for token in run),
                y0=min(token.y0 for token in run),
                x1=max(token.x1 for token in run),
                y1=max(token.y1 for token in run),
            )
        )
    return joined


def anchor_citation(
    conn: StoreConnection, *, source_id: UUID, page: int, matched_text: str
) -> list[Rect]:
    """Find `matched_text` on `page` of a live source; return its rectangles.

    No server path calls this: it judges no delivery, so a run's citations go
    through `verify_citations`. It remains the extractor suites' probe of the
    search rule alone (`tests/test_pdf_extraction.py`), `ANY_RUN`: where a
    quote is, not whether an answer could cite it (`WHOLE_LINE`). Refuses
    `CITATION_NOT_LOCATED` when the quote is not there and `CITATION_AMBIGUOUS`
    when it is there more than once. Neither refusal carries the quote.
    """
    _digest, tracking, _packing = _source_facts(conn, source_id)
    tokens = _page_tokens(conn, source_id, page)
    return _rectangles(_unique_run(tokens, matched_text, tracking=tracking), page)


@dataclass(slots=True)
class _Page:
    """One page's tokens and the lists the search derives from them, each
    derived the first time a search asks for it and kept with the page.

    They depend on the page alone: its words as compared (their bytes, or
    their NFC) and, for a tracking extractor, the page with its tracked
    letters joined. Rebuilt per citation, 512 citations of one 240,000-token
    page spent 18 s on them (N41); a `TokenIndex` holds its pages as these.
    """

    tokens: list[_Token]
    exact: list[str] | None = None
    nfc: list[str] | None = None
    tracked: _Page | None = None
    # The page's evidence lines as a module was shown them, by word count:
    # as stored (`False`) and with tracked letters joined within each (`True`).
    # Each span carries the one block id it is (R24-16).
    shown_lines: dict[bool, dict[int, list[tuple[list[_Token], str]]]] = field(
        default_factory=dict
    )
    # The same lines as the evidence section shows them, word by word (W6),
    # keyed by how many words each shows.
    shown_as: dict[int, list[_ShownLine]] | None = None

    def keys(self, *, normalised: bool) -> list[str]:
        """The page's words as `_starts` compares them."""
        if self.exact is None:
            self.exact = [token.text for token in self.tokens]
        if not normalised:
            return self.exact
        if self.nfc is None:
            self.nfc = list(map(_nfc, self.exact))
        return self.nfc

    def joined(self) -> _Page:
        """This page with its tracked letters joined (`_joined_tracking`)."""
        if self.tracked is None:
            self.tracked = _Page(_joined_tracking(self.tokens))
        return self.tracked

    def shown(
        self,
        cuts: Mapping[int, tuple[int, ...]] | None,
        lines: Mapping[int, tuple[str, ...]],
        *,
        joined: bool,
    ) -> dict[int, list[tuple[list[_Token], str]]]:
        """The page's evidence lines as a module was shown them (`_shown`),
        keyed by how many words each holds, derived once per page. `cuts` is
        the source's packing-2 cut per line, `None` for packing 1; `lines` is
        the source's line-to-block-ids map, so each returned span carries the
        one block id it is. Joined, a line's tracked letters are joined
        within it and never across two."""
        if joined not in self.shown_lines:
            spans = _shown(self.tokens, cuts, lines)
            if joined:
                spans = [(_joined_tracking(span), block_id) for span, block_id in spans]
            by_width: dict[int, list[tuple[list[_Token], str]]] = {}
            for span, block_id in spans:
                by_width.setdefault(len(span), []).append((span, block_id))
            self.shown_lines[joined] = by_width
        return self.shown_lines[joined]

    def shown_words(
        self,
        cuts: Mapping[int, tuple[int, ...]] | None,
        lines: Mapping[int, tuple[str, ...]],
    ) -> dict[int, list[_ShownLine]]:
        """The page's evidence lines as the evidence section shows them (W6),
        keyed by how many words each shows, derived once per page: each
        line's tokens NFC, joined by one space as admission packed them, then
        split into words as a quote is -- so a token the extractor gave a
        space of its own is the words the module read, not one."""
        if self.shown_as is None:
            by_width: dict[int, list[_ShownLine]] = {}
            for spans in self.shown(cuts, lines, joined=False).values():
                for span, block_id in spans:
                    words = tuple(
                        word for token in span for word in _nfc(token.text).split()
                    )
                    by_width.setdefault(len(words), []).append(
                        _ShownLine(words, span, block_id)
                    )
            self.shown_as = by_width
        return self.shown_as


@dataclass(frozen=True, slots=True)
class _ShownLine:
    """One evidence line as the evidence section shows it: its words, the
    tokens it is, and the one block id it is."""

    words: tuple[str, ...]
    span: list[_Token]
    block_id: str


def _unique_run(
    tokens: list[_Token], matched_text: str, *, tracking: bool = False
) -> list[_Token]:
    """The one search rule both entry points use: exactly once, never across a
    region -- and, only where that finds nothing, once more under the declared
    normalisations.

    The order is the safety. An exact match that is ambiguous refuses here and
    never reaches the second pass, so no normalisation can pick between two
    places a quote might be; and an exact match that is unique returns before
    the second pass exists, so every quote that anchored before these rules
    were written anchors to the same rectangles.
    """
    return _page_run(_Page(tokens), matched_text, tracking=tracking)


def _page_run(page: _Page, matched_text: str, *, tracking: bool) -> list[_Token]:
    """`_unique_run` over a page whose derived keys may already be in hand."""
    words = matched_text.split()
    if not words:
        raise Refusal(RefusalCode.CITATION_NOT_LOCATED)
    exact = _one_match(page.tokens, words, normalised=False, page=page)
    if exact is not None:
        return exact
    candidates = page.joined() if tracking else page
    run = _one_match(candidates.tokens, words, normalised=True, page=candidates)
    if run is None:
        raise Refusal(RefusalCode.CITATION_NOT_LOCATED)
    return run


def _line_run(
    page: _Page,
    cuts: Mapping[int, tuple[int, ...]] | None,
    lines: Mapping[int, tuple[str, ...]],
    matched_text: str,
    *,
    tracking: bool,
) -> tuple[list[_Token], str]:
    """`WHOLE_LINE_AS_STORED`, the whole-line rule as N28 first accepted
    answers under it, by which their records are re-anchored: the one
    evidence line of the page `matched_text` is, whole -- its stored tokens
    exactly, and only where no line is, under the declared normalisations --
    in the order `_page_run` keeps and for its reason, and the one block id
    that line is (R24-16): what delivery is judged against.

    A candidate is a line as the module was shown it with as many words as
    the quote, so the search compares a handful of lines where the run search
    proposes every token of the page: 64 one- and two-word quotes of a
    240,000-token page through the normalised pass took 20.7 s by run and
    0.08 s by line, on one host under load (F206's author measured 13.9 s by
    run). Two such lines are
    `CITATION_AMBIGUOUS`; a quote that is part of a line, or that runs onto
    the next, is no line at all: `CITATION_NOT_LOCATED`, which the second
    attempt reads back as "not one evidence line of its cited page".
    """
    words = matched_text.split()
    if not words:
        raise Refusal(RefusalCode.CITATION_NOT_LOCATED)
    width = len(words)
    exact = _one_line(
        page.shown(cuts, lines, joined=False).get(width, ()), words, False
    )
    if exact is not None:
        return exact
    candidates = page.shown(cuts, lines, joined=tracking).get(width, ())
    run = _one_line(candidates, words, True)
    if run is None:
        raise Refusal(RefusalCode.CITATION_NOT_LOCATED)
    return run


def _shown_line_run(
    page: _Page,
    cuts: Mapping[int, tuple[int, ...]] | None,
    lines: Mapping[int, tuple[str, ...]],
    matched_text: str,
    *,
    tracking: bool,
) -> tuple[list[_Token], str]:
    """`WHOLE_LINE`: the one evidence line of the page `matched_text` is,
    compared with the line as the evidence section showed it -- its words,
    NFC -- and the one block id that line is.

    Three passes, each reached only where the one before found no line, and
    each counting every line of the page, so none can pick between two:

    - as shown: every word NFC-equal to the line's. Two lines shown alike are
      two, `CITATION_AMBIGUOUS`, whichever form each is stored in (N13): the
      module saw one text twice.
    - its edges forgiven: the first and last word less the punctuation a
      sentence puts around them (`_edge_equal`). It used to be tried only on
      a tracking extractor's joined line, so on a PDF a line with three
      one-character tokens (`$ -- $`) lost it, and a decomposed accent
      refused the NFC text the module was shown (W6).
    - on a tracking extractor, the line with its tracked letters joined
      (`_joined_tracking`), so a heading drawn letter by letter is quoted as
      the word a reader sees, as it was.

    A quote that is part of a line, or that runs onto the next, is no line:
    `CITATION_NOT_LOCATED`.
    """
    words = tuple(map(_nfc, matched_text.split()))
    if not words:
        raise Refusal(RefusalCode.CITATION_NOT_LOCATED)
    shown = page.shown_words(cuts, lines).get(len(words), ())
    found = _one_shown(shown, words, edges=False)
    if found is None:
        found = _one_shown(shown, words, edges=True)
    if found is None and tracking:
        joined = page.shown(cuts, lines, joined=True).get(len(words), ())
        found = _one_line(joined, words, True)
    if found is None:
        raise Refusal(RefusalCode.CITATION_NOT_LOCATED)
    return found


def _one_shown(
    lines: Iterable[_ShownLine], words: tuple[str, ...], *, edges: bool
) -> tuple[list[_Token], str] | None:
    """The single shown line whose words are `words` -- equal, or with the
    edge words forgiven -- with the block id it is; `None` for none, a
    refusal for two."""
    found: tuple[list[_Token], str] | None = None
    for line in lines:
        if not _same_words(line.words, words, edges=edges):
            continue
        if found is not None:
            raise Refusal(RefusalCode.CITATION_AMBIGUOUS)
        found = (line.span, line.block_id)
    return found


def _same_words(shown: tuple[str, ...], words: tuple[str, ...], *, edges: bool) -> bool:
    """Whether a shown line's words are the quote's, both NFC and as many:
    every one equal, or -- with `edges` -- the interior equal and the first
    and last standing for the quote's there (`_edge_equal`)."""
    if not edges:
        return shown == words
    last = len(words) - 1
    return (
        shown[1:last] == words[1:last]
        and _edge_equal(shown[0], words[0], normalised=True)
        and _edge_equal(shown[last], words[last], normalised=True)
    )


def _one_line(
    lines: Iterable[tuple[list[_Token], str]], words: Sequence[str], normalised: bool
) -> tuple[list[_Token], str] | None:
    """The single line `words` is whole (`_match_at` from its first token
    over a line exactly as long), with the one block id it is; `None` for
    none, a refusal for two."""
    found: tuple[list[_Token], str] | None = None
    for line, block_id in lines:
        if not _match_at(line, 0, words, normalised=normalised):
            continue
        if found is not None:
            raise Refusal(RefusalCode.CITATION_AMBIGUOUS)
        found = (line, block_id)
    return found


def _shown(
    tokens: list[_Token],
    cuts: Mapping[int, tuple[int, ...]] | None,
    lines: Mapping[int, tuple[str, ...]],
) -> list[tuple[list[_Token], str]]:
    """The page's evidence lines as the evidence section showed them: each
    token line, cut into the blocks admission wrote for it, each span paired
    with the one block id it is.

    A line that fits `GROUP_WIDTH` is one block, so it is itself. A wider
    line was shown as several, and each is a line of its own to the module:
    packing 2 cut it between tokens, and `cuts` holds how many space-separated
    pieces each of its blocks carries (`_token_spans`); packing 1 cut it at
    the width (`_width_spans`), which can hold fewer spans than the line has
    stored blocks -- a block a packing-1 cut tore inside a word is no line a
    quote can be, and is silently absent from `_width_spans`' own numbering,
    never a count to reconcile against the stored block count here.

    The block id travels with its span rather than staying only the line's
    (R24-16): `WHOLE_LINE` matches at this same per-block granularity -- the
    prompt calls one delivered block a citable evidence line -- and a
    delivery check that instead asked for every block of the *line* refused a
    quote whose one shown block was the whole match, withholding the rest of
    a wider line the map never promised. Each span carries the block index
    `_token_spans`/`_width_spans` numbered it at, which is `block_ids_by_line`'s
    own ordinal within the line (CF-013) -- so the span's block id is read
    off `lines[line_id]` at that index, not by position among the spans kept.
    An index past what the line's stored blocks carry is this host's own rows
    failing to read as they were written."""
    shown: list[tuple[list[_Token], str]] = []
    for line_id, group in groupby(tokens, key=lambda token: token.line_id):
        line = list(group)
        spans = (
            _width_spans(line)
            if cuts is None
            else _token_spans(line, cuts.get(line_id))
        )
        block_ids = lines.get(line_id, ())
        for index, (start, end) in spans:
            if index >= len(block_ids):
                raise Refusal(RefusalCode.EVIDENCE_PACKING_MISMATCH)
            shown.append((line[start:end], block_ids[index]))
    return shown


def _token_spans(
    line: list[_Token], pieces: tuple[int, ...] | None
) -> list[tuple[int, tuple[int, int]]]:
    """Packing 2: each block of `line` as the run of its tokens, found as
    `_walk` numbers them -- by the space-separated pieces each block holds --
    so a block quoted whole is one run however admission measured it
    (CF-013), with the block's own index within the line. A line the blocks
    do not tile is this host's own rows failing to read as they were
    written: `EVIDENCE_PACKING_MISMATCH`."""
    if pieces is None:
        raise Refusal(RefusalCode.EVIDENCE_PACKING_MISMATCH)
    spans: list[tuple[int, tuple[int, int]]] = []
    at = 0
    for index, wanted in enumerate(pieces):
        (start, held) = (at, 0)
        while held < wanted and at < len(line):
            held += line[at].text.count(" ") + 1
            at += 1
        if held != wanted:
            raise Refusal(RefusalCode.EVIDENCE_PACKING_MISMATCH)
        spans.append((index, (start, at)))
    if at != len(line):
        raise Refusal(RefusalCode.EVIDENCE_PACKING_MISMATCH)
    return spans


def _width_spans(line: list[_Token]) -> list[tuple[int, tuple[int, int]]]:
    """Packing 1: the whole line while it fits `GROUP_WIDTH`; past it, each
    block `line_groups` cut at the width whose two edges fall between
    tokens, as its run of whole tokens, with the block's own index within
    the line (its `GROUP_WIDTH` bucket number, which is `line_groups`' own
    ordinal for it).

    Measured as `line_groups` measured it, on the NFC line the tokens make
    joined by one space. A block whose edge fell inside a word began or ended
    with part of one, which no run of tokens is (F204), so it is no line a
    quote can be; every source admitted since CF-013 is cut between tokens
    instead, and re-admission is how an older one gains that."""
    bounds: list[tuple[int, int]] = []
    at = 0
    for token in line:
        size = len(_nfc(token.text))
        bounds.append((at, at + size))
        at += size + 1
    if at - 1 <= GROUP_WIDTH:
        return [(0, (0, len(line)))]
    held: dict[int, list[int]] = {}
    torn: set[int] = set()
    for index, (start, end) in enumerate(bounds):
        (first, last) = (start // GROUP_WIDTH, (end - 1) // GROUP_WIDTH)
        if first == last:
            held.setdefault(first, []).append(index)
        else:
            torn.update(range(first, last + 1))
    return [
        (block, (indexes[0], indexes[-1] + 1))
        for block, indexes in sorted(held.items())
        if block not in torn
    ]


def _one_match(
    tokens: list[_Token],
    words: Sequence[str],
    *,
    normalised: bool,
    page: _Page | None = None,
) -> list[_Token] | None:
    """The single run matching `words`, `None` for no run, a refusal for two.

    Ambiguity is counted over the whole page in both passes (section 44.5):
    highlighting one of two identical sentences asserts a precision the host
    does not have, whichever rule found them.

    The rule is `_match_at`'s at every start; this finds its starts without
    asking it at each (MAX-06). Every match used to be kept, each a slice the
    length of the quote, before the count was read, and every start compared
    the quote word by word: a repeated page and a long quote held millions of
    token references, and a quote failing only at its last word cost the page
    times the quote. `_starts` proposes the starts whose plainly compared
    words match, in one pass over the page; each is then held to its region
    and its edge words in constant time; and the search stops at the second.
    """
    width = len(words)
    found: int | None = None
    region_end = 0
    for start in _starts(tokens, words, normalised=normalised, page=page):
        if start >= region_end:
            # Starts ascend, so one scan per region serves every start in it.
            region_end = _region_end(tokens, start)
        end = start + width - 1
        if (
            region_end <= end
            or not _edge_equal(tokens[start].text, words[0], normalised=normalised)
            or not _edge_equal(tokens[end].text, words[-1], normalised=normalised)
        ):
            continue
        if found is not None:
            raise Refusal(RefusalCode.CITATION_AMBIGUOUS)
        found = start
    return None if found is None else tokens[found : found + width]


def _starts(
    tokens: list[_Token],
    words: Sequence[str],
    *,
    normalised: bool,
    page: _Page | None = None,
) -> Iterable[int]:
    """Every start, ascending, at which the words compared by equality alone
    match: the whole quote in the exact pass, its interior in the normalised
    one, whose edge words `_one_match` compares itself. With no interior every
    start is a candidate. `page`, when given, is `tokens` with the keys an
    earlier search of it already derived."""
    width = len(words)
    last = len(tokens) - width
    if last < 0:
        return ()
    inner = 1 if normalised else 0
    pattern = [
        _key(word, normalised=normalised) for word in words[inner : width - inner]
    ]
    if not pattern:
        return range(last + 1)
    # The page's keys in one comprehension each, not a call per token: on a
    # long page this is most of what the search costs, so a page derives them
    # once for every search of it (N41).
    keys = (page or _Page(tokens)).keys(normalised=normalised)
    return (
        at - inner for at in occurrences(keys, pattern) if inner <= at <= last + inner
    )


def _key(text: str, *, normalised: bool) -> str:
    """What an interior word is compared by: its bytes, or its NFC."""
    return _nfc(text) if normalised else text


def occurrences(sequence: list[str], pattern: list[str]) -> Iterator[int]:
    """Every index at which `pattern` begins in `sequence`, overlapping ones
    too, in one pass over each (Knuth-Morris-Pratt). Where nothing is matched
    yet, the next place the pattern could begin is found by `list.index`.
    Public for the handoff's body quote check, which needs the same bound
    (R24-09)."""
    border = _borders(pattern)
    matched = 0
    index = 0
    while index < len(sequence):
        if matched == 0:
            index = _next_index(sequence, pattern[0], index)
            if index == len(sequence):
                return
            matched = 1
        else:
            matched = _extended(matched, sequence[index], pattern, border)
        if matched == len(pattern):
            yield index - matched + 1
            matched = border[matched - 1]
        index += 1


def _borders(pattern: list[str]) -> list[int]:
    """For each prefix of `pattern`, the length of its longest proper prefix
    that is also its suffix: where a partial match resumes after a mismatch."""
    border = [0] * len(pattern)
    matched = 0
    for index in range(1, len(pattern)):
        matched = _extended(matched, pattern[index], pattern, border)
        border[index] = matched
    return border


def _extended(matched: int, item: str, pattern: list[str], border: list[int]) -> int:
    """How much of `pattern` is matched once `item` follows `matched` of it:
    fall back along the borders until `item` extends a prefix, or none does."""
    while matched and item != pattern[matched]:
        matched = border[matched - 1]
    return matched + 1 if item == pattern[matched] else matched


def _next_index(sequence: list[str], item: str, start: int) -> int:
    """The first index at or after `start` holding `item`, else the length."""
    try:
        return sequence.index(item, start)
    except ValueError:
        return len(sequence)


def _region_end(tokens: list[_Token], start: int) -> int:
    """One past the last token of the region run `start` is in."""
    region = tokens[start].region_id
    end = start + 1
    while end < len(tokens) and tokens[end].region_id == region:
        end += 1
    return end


@dataclass(slots=True)
class TokenIndex:
    """What `verify_citations` read from the token index, keyed per page and
    per source, so several calls inside one read unit read each once.

    Holds only what the store returned, and what the search derives from a
    page it returned (`_Page`); delivery is judged per call against that
    call's `delivered`, never cached.
    """

    pages: dict[tuple[UUID, int], _Page] = field(default_factory=dict)
    digests: dict[UUID, str] = field(default_factory=dict)
    tracking: dict[UUID, bool] = field(default_factory=dict)
    packing: dict[UUID, int] = field(default_factory=dict)
    line_blocks: dict[UUID, dict[int, tuple[str, ...]]] = field(default_factory=dict)
    # A packing-2 source's pieces per block, per line (`_walked_cuts`), read
    # in the one query that numbers its blocks.
    cuts: dict[UUID, dict[int, tuple[int, ...]]] = field(default_factory=dict)

    def page(self, conn: StoreConnection, source_id: UUID, page: int) -> _Page:
        """One page of a live source, read once."""
        key = (source_id, page)
        if key not in self.pages:
            self.pages[key] = _Page(_page_tokens(conn, source_id, page))
        return self.pages[key]

    def facts(self, conn: StoreConnection, source_id: UUID) -> tuple[str, bool]:
        """A live source's digest and whether it tracks (`_source_facts`),
        read once with the packing its blocks were written under."""
        if source_id not in self.digests:
            (digest, tracking, packing) = _source_facts(conn, source_id)
            self.digests[source_id], self.tracking[source_id] = digest, tracking
            self.packing[source_id] = packing
        return self.digests[source_id], self.tracking[source_id]

    def lines(
        self, conn: StoreConnection, source_id: UUID
    ) -> dict[int, tuple[str, ...]]:
        """Line id to the blocks admission wrote for it (`_line_blocks`),
        read once per source, under the packing `facts` read -- and, for a
        packing-2 source, each block's pieces from the same query."""
        if source_id not in self.line_blocks:
            self.facts(conn, source_id)
            if self.packing[source_id] == PACKING_BY_TOKEN:
                (self.line_blocks[source_id], self.cuts[source_id]) = _split_cuts(
                    _walked_cuts(conn, source_id)
                )
            else:
                self.line_blocks[source_id] = _line_blocks(
                    conn, source_id, self.packing[source_id]
                )
        return self.line_blocks[source_id]


def verify_citations(
    conn: StoreConnection,
    *,
    delivered: Mapping[UUID, frozenset[str]],
    citations: Sequence[Citation],
    index: TokenIndex | None = None,
    rule: CitationRule = ANY_RUN,
) -> list[AnchoredCitation]:
    """Re-derive every citation, or refuse the set.

    `rule` is how each is located (`CitationRule`): an answer being accepted
    is held to `WHOLE_LINE`, what its final check told it; a stored record
    is re-anchored by the rule it names.

    Called before an artifact is written, never after: an artifact naming a quote
    nobody can find is the thing invariant 11 exists to prevent, and one that has
    already been stored is a correction rather than a refusal.

    A citation may only name evidence actually delivered to that node --
    a real source in the same case is still something this node was not given.
    `delivered` maps each source to the exact blocks the node was handed. Under
    `ANY_RUN` the match must lie wholly within delivered lines: a quote on an
    undelivered page, or wrapping onto an undelivered line, refuses
    `CITATION_NOT_DELIVERED`. Under `WHOLE_LINE` a match is exactly one block,
    and delivery is judged against that one block (R24-16): the prompt calls a
    shown block whole citable evidence, and a page map may show a source line's
    first block while withholding its continuation, so requiring the *line's*
    every block would refuse a quote of exactly what was shown. Ambiguity is
    still counted over the whole page, so a quote repeated on a line the node
    never saw is ambiguous rather than resolved to the copy it did -- over every
    run of the page under `ANY_RUN`, over every line of it under `WHOLE_LINE`.

    An artifact carries many citations and they cluster: several quotes from one
    page of one source is the normal shape. Both lookups are therefore fetched
    once per distinct page and per distinct source rather than once per citation,
    avoiding the N+1 shape that runs ~8x slower on exactly this kind of list.
    A caller verifying several lists in one unit
    passes one `TokenIndex` to share those reads across them.
    """
    if index is None:
        index = TokenIndex()
    anchored = []
    for citation in citations:
        blocks = delivered.get(citation.source_id)
        if blocks is None:
            raise Refusal(RefusalCode.CITATION_NOT_DELIVERED)
        run, digest = _located(conn, index, citation, blocks, rule=rule)
        anchored.append(
            AnchoredCitation(
                document_sha256=digest,
                page=citation.page,
                matched_text=citation.matched_text,
                bboxes=tuple(_rectangles(run, citation.page)),
            )
        )
    return anchored


def _located(
    conn: StoreConnection,
    index: TokenIndex,
    citation: Citation,
    blocks: frozenset[str],
    *,
    rule: CitationRule,
) -> tuple[list[_Token], str]:
    """One citation's run under `rule`, already checked delivered, and its
    source's digest.

    Under either whole-line rule a match is exactly one block (R24-16):
    delivery is judged against the block its match is, not every block its
    source line was split into -- a page map showing that one block whole
    withholds nothing this match needs, even when the line continues past
    it. Under `ANY_RUN` a match is not confined to one block, so delivery is
    judged against every block of every line its tokens touch.
    """
    digest, tracking = index.facts(conn, citation.source_id)
    searched = index.page(conn, citation.source_id, citation.page)
    lines = index.lines(conn, citation.source_id)
    if rule in (WHOLE_LINE, WHOLE_LINE_AS_STORED):
        cuts = index.cuts.get(citation.source_id)
        locate = _shown_line_run if rule == WHOLE_LINE else _line_run
        run, block_id = locate(
            searched, cuts, lines, citation.matched_text, tracking=tracking
        )
        if block_id not in blocks:
            raise Refusal(RefusalCode.CITATION_NOT_DELIVERED)
        return run, digest
    run = _page_run(searched, citation.matched_text, tracking=tracking)
    if any(not _delivered(lines.get(token.line_id), blocks) for token in run):
        raise Refusal(RefusalCode.CITATION_NOT_DELIVERED)
    return run, digest


def _page_tokens(conn: StoreConnection, source_id: UUID, page: int) -> list[_Token]:
    """The page's tokens in reading order, from a live source only."""
    rows = conn.execute(
        "SELECT tokens.text, tokens.region_id, tokens.line_id,"
        " tokens.x0, tokens.y0, tokens.x1, tokens.y1"
        " FROM source_tokens AS tokens"
        " JOIN live_sources USING (source_id)"
        " WHERE tokens.source_id = %s AND tokens.page = %s"
        " ORDER BY tokens.token_id",
        (source_id, page),
    ).fetchall()
    return [_Token(*row) for row in rows]


def _line_blocks(
    conn: StoreConnection, source_id: UUID, packing: int = PACKING_BY_WIDTH
) -> dict[int, tuple[str, ...]]:
    """Line id to the blocks admission wrote for it, once per source: admission's
    own numbering (`block_ids_by_line`) over the token index's line ids.

    A source packed between tokens (`PACKING_BY_TOKEN`) is read back instead
    (`_walked_cuts`). What follows is `PACKING_BY_WIDTH`'s reading, which
    every source admitted before CF-013 was written under and still verifies
    by. A line past `GROUP_WIDTH` was split, so a line may own more than one block.
    Which lines were split is not guessed, and the direction of the count is
    what says whether to ask. Splitting only ever writes **more** blocks than
    lines, so a source with more stored blocks than lines carries a split and
    its packing is recomputed from the text. A source with as many blocks as
    lines had none -- every source admitted before there was any splitting, and
    every source whose lines fit. A source with *fewer* blocks than lines is
    neither: no packing this rule states produces one, and the only way to reach
    it is to remove a stored block, which migration 0027 seals against and which
    the suite does deliberately to narrow a delivery. There the one-block-a-line
    reading is right and the missing block is simply not among the delivered,
    which is `CITATION_NOT_DELIVERED` and not this function's to answer.
    """
    if packing == PACKING_BY_TOKEN:
        return _split_cuts(_walked_cuts(conn, source_id))[0]
    rows = conn.execute(
        "SELECT lines.line_id, blocks.stored FROM"
        " (SELECT DISTINCT line_id FROM source_tokens WHERE source_id = %s) AS lines,"
        " (SELECT count(*) AS stored FROM source_blocks WHERE source_id = %s)"
        " AS blocks",
        (source_id, source_id),
    ).fetchall()
    line_ids = [int(row[0]) for row in rows]
    stored = int(rows[0][1]) if rows else 0
    if stored <= len(line_ids):
        return block_ids_by_line(dict.fromkeys(line_ids, 1))
    counts = _group_counts(conn, source_id)
    if sum(counts.values()) != stored:
        # The recomputation is a derivation of what admission wrote, and here it
        # does not agree with it. The store cannot have drifted upward -- 0027
        # seals extracted evidence -- so the rule has: this source was packed
        # under a different `GROUP_WIDTH`. Every id past the disagreement names
        # a row no source carries, and asking whether such a block was delivered
        # answers about the citation when the fault is the host's own reading --
        # which is why the code is its own: the source is live, so "pin a live
        # source" cannot clear it, and re-admission under this build can.
        raise Refusal(RefusalCode.EVIDENCE_PACKING_MISMATCH)
    return block_ids_by_line(counts)


# Each line's and each block's space-separated pieces -- one more than the
# spaces its text holds -- in one statement. A line's pieces are its tokens'
# summed (the tokens are joined by one space), and NFC neither adds nor
# removes U+0020, so a block's pieces are the pieces of the tokens it holds.
_WALK_QUERY = (
    "SELECT 0, line_id::text,"
    " sum(length(text) - length(replace(text, ' ', '')) + 1)"
    " FROM source_tokens WHERE source_id = %s GROUP BY line_id"
    " UNION ALL SELECT 1, block_id,"
    " length(text) - length(replace(text, ' ', '')) + 1"
    " FROM source_blocks WHERE source_id = %s"
)


def _walked_cuts(
    conn: StoreConnection, source_id: UUID
) -> dict[int, tuple[tuple[str, int], ...]]:
    """`PACKING_BY_TOKEN`'s numbering, read back from the blocks admission
    wrote rather than re-derived from a rule (CF-013): each line's blocks, in
    order, each with the pieces it holds -- which is also where a block's
    run of the line's tokens ends (`_token_spans`).

    A packing-2 block is a run of a line's whole tokens joined by one space,
    so its space-separated pieces are exactly its tokens' pieces. Walking the
    blocks in id order against the lines in line order, each line takes blocks
    until their pieces sum to its own: what admission wrote, found without
    measuring a length on either side's Unicode tables (N40) and without
    `GROUP_WIDTH`. One round trip, the lines' and the blocks' counts together.
    Blocks that do not tile the lines exactly -- a block gone, a line that
    ends inside one -- are this host's own rows failing to read as they were
    written: `EVIDENCE_PACKING_MISMATCH`.
    """
    lines: list[tuple[int, int]] = []
    blocks: list[tuple[int, str, int]] = []
    for kind, key, pieces in conn.execute(
        _WALK_QUERY, (source_id, source_id)
    ).fetchall():
        if kind == 0:
            lines.append((int(key), int(pieces)))
        else:
            blocks.append((_ordinal(str(key)), str(key), int(pieces)))
    return _walk(sorted(lines), sorted(blocks))


def _split_cuts(
    walked: Mapping[int, tuple[tuple[str, int], ...]],
) -> tuple[dict[int, tuple[str, ...]], dict[int, tuple[int, ...]]]:
    """A walked numbering (`_walked_cuts`) as each line's block ids, which
    delivery is judged by, and each line's pieces per block, which its
    blocks' runs of tokens are cut by (`_token_spans`)."""
    ids = {line: tuple(block for block, _held in cut) for line, cut in walked.items()}
    pieces = {line: tuple(held for _block, held in cut) for line, cut in walked.items()}
    return ids, pieces


def _ordinal(block_id: str) -> int:
    digits = block_id[1:]
    if not (digits.isascii() and digits.isdigit()):
        raise Refusal(RefusalCode.EVIDENCE_PACKING_MISMATCH)
    return int(digits)


def _walk(
    lines: list[tuple[int, int]], blocks: list[tuple[int, str, int]]
) -> dict[int, tuple[tuple[str, int], ...]]:
    """Each line, in order, with the blocks whose pieces sum to its own, each
    block with its pieces."""
    numbering: dict[int, tuple[tuple[str, int], ...]] = {}
    at = 0
    for line_id, wanted in lines:
        taken: list[tuple[str, int]] = []
        pieces = 0
        while pieces < wanted and at < len(blocks):
            (_ordinal_at, block_id, held) = blocks[at]
            taken.append((block_id, held))
            pieces += held
            at += 1
        if pieces != wanted:
            raise Refusal(RefusalCode.EVIDENCE_PACKING_MISMATCH)
        numbering[line_id] = tuple(taken)
    if at != len(blocks):
        raise Refusal(RefusalCode.EVIDENCE_PACKING_MISMATCH)
    return numbering


def _group_counts(conn: StoreConnection, source_id: UUID) -> dict[int, int]:
    """How many blocks each line needs, by admission's own rule.

    The rule chunks a line by *length*, so the length is what is read --
    computed in the database rather than by shipping the document. It used to
    `fetchall` every token's text and rebuild each line in Python: with
    `AdmissionLimits.max_tokens` at 500,000 that is an unbounded read, and it
    runs inside `save_revision_in`'s and `freeze_in`'s governed transaction,
    under the case lock, on any source carrying one line past `GROUP_WIDTH` --
    an ordinary un-wrapped paragraph in a text export. `IO_BUDGET` could not
    see it: one round trip either way, while the work behind it was the whole
    token table. Found by the Completion Phase 12 adversarial audit.

    `line_groups` measures the line NFC, so this measures each token NFC too
    (EV-1). It counted the stored characters, which admission keeps in their
    own form: a decomposed line that fits one block in NFC and not raw made the
    totals disagree and refused every citation of the source, and one line
    that shrank beside one that grew kept the totals equal and handed each
    line the other's blocks. The tokens are joined by one space, and nothing
    composes across a space, so the NFC length of the joined line is the sum
    of the tokens' NFC lengths and the spaces between them. The guard in
    `_line_blocks` stays for what it was written for, a changed `GROUP_WIDTH`.
    """
    rows = conn.execute(
        "SELECT line_id, sum(length(normalize(text, NFC))) + count(*) - 1 AS width"
        " FROM source_tokens WHERE source_id = %s GROUP BY line_id",
        (source_id,),
    ).fetchall()
    return {
        int(line_id): max(1, -(-int(width) // GROUP_WIDTH)) for line_id, width in rows
    }


def _delivered(ids: tuple[str, ...] | None, blocks: frozenset[str]) -> bool:
    """A line is delivered when every block it was split into was.

    Fail closed, and deliberately line-granular: a quote crossing a group
    boundary needs both sides, and a delivery carrying half a split line
    carries none of it. `ANY_RUN`'s own rule -- its match is not confined to
    one block, so it is judged against every block of every line its tokens
    touch. `WHOLE_LINE` judges its match against the one block it is instead
    (R24-16, `verify_citations`), never calling this function: its match
    cannot cross a block boundary in the first place.
    """
    if not ids:
        return False
    return all(block in blocks for block in ids)


def _match_at(
    tokens: list[_Token],
    start: int,
    words: Sequence[str],
    *,
    normalised: bool = False,
) -> list[_Token]:
    """The tokens matching `words` from `start`, or an empty list.

    A run may cross a line boundary only inside one region. Crossing regions is
    what assembles a phrase across a column gutter, and the phrase it assembles
    is on no page.

    Under `normalised`, the first and last word may differ from their token by
    `EDGE_PUNCTUATION` alone. The edges only: a word inside the run still has
    to equal its token, because forgiving punctuation there would let one quote
    stand for two different sentences of the page.

    The exact pass compares the bytes and the normalised pass compares NFC.
    F33's widening -- a quote of the NFC line the block showed against a token
    stored in its own decomposed form -- belongs to the second pass, where the
    ambiguity rule already runs only after an exact match has failed. Comparing
    NFC in the *first* pass made a page that carries a word both composed and
    decomposed answer `CITATION_AMBIGUOUS` for a quote that had anchored
    uniquely before, at every later re-verification of an accepted record
    (CR-4).

    The search (`_one_match`) does not ask this at every start: it finds the
    starts it would accept in one pass. This is the rule it finds them by,
    stated at one start, and what `tests/test_quote_normalisation.py` holds
    the search to.
    """
    if start + len(words) > len(tokens):
        return []
    run = tokens[start : start + len(words)]
    last = len(words) - 1
    for position, (token, word) in enumerate(zip(run, words, strict=True)):
        if position in (0, last):
            if not _edge_equal(token.text, word, normalised=normalised):
                return []
        elif _key(token.text, normalised=normalised) != _key(
            word, normalised=normalised
        ):
            return []
    if any(token.region_id != run[0].region_id for token in run):
        return []
    return run


def _edge_equal(text: str, word: str, *, normalised: bool) -> bool:
    """Whether a run's first or last token stands for the quote's word there:
    the bytes, or -- in the normalised pass -- the NFC, or the two less the
    edge punctuation `_stripped` forgives."""
    if text == word:
        return True
    if not normalised:
        return False
    if _nfc(text) == _nfc(word):
        return True
    stripped = _stripped(word)
    return bool(stripped) and _stripped(text) == stripped


def _rectangles(run: list[_Token], page: int) -> list[Rect]:
    """One rectangle per line the run covers, in reading order."""
    by_line: dict[int, list[_Token]] = {}
    for token in run:
        by_line.setdefault(token.line_id, []).append(token)
    return [
        Rect(
            page=page,
            x0=min(token.x0 for token in line),
            y0=min(token.y0 for token in line),
            x1=max(token.x1 for token in line),
            y1=max(token.y1 for token in line),
        )
        for _line_id, line in sorted(by_line.items())
    ]


def _source_facts(conn: StoreConnection, source_id: UUID) -> tuple[str, bool, int]:
    """A live source's document digest, whether its extractor is one whose
    own rule can split a tracked word into letters, and the packing its blocks
    were written under (`format_version`, migration 0032).

    All in one round trip rather than two, because the digest read is already
    paid for once per source and every section's `IO_BUDGET` is asserted with
    `==`: a second query here would move four declared budgets for a fact the
    first row could carry.

    `source_extractions` is outer-joined, and a source with no row is not
    tracking-normalised -- "no row means UNKNOWN: never attribute legacy
    extraction to today's adapter" is that table's own rule, and the
    fail-closed reading of it here is the exact search alone. Such a source
    was packed before there was a second packing, so it reads as packing 1.
    """
    row = conn.execute(
        "SELECT live.document_sha256, extraction.extractor_identity,"
        " extraction.format_version"
        " FROM live_sources AS live"
        " LEFT JOIN source_extractions AS extraction USING (source_id)"
        " WHERE live.source_id = %s",
        (source_id,),
    ).fetchone()
    if row is None:
        raise Refusal(RefusalCode.EVIDENCE_NOT_AVAILABLE)
    tracking = _extractor_name(row[1]) in TRACKING_EXTRACTORS
    return str(row[0]), tracking, PACKING_BY_WIDTH if row[2] is None else int(row[2])


def _extractor_name(identity: str | None) -> str:
    """The `name` of a stored extractor identity, or `""` for anything this
    build cannot read as one.

    Never raises and never carries the stored text out: an identity that will
    not parse means the exact search alone, which is the same answer as no row.
    """
    if identity is None:
        return ""
    try:
        name = json.loads(identity).get("name")
    except (ValueError, AttributeError):
        return ""
    return name if isinstance(name, str) else ""

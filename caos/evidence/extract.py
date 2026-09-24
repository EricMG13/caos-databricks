"""Text into tokens that carry where they were.

Invariant 11 needs four things per token: the page, the layout region, the line,
and a rectangle. A citation is re-located by joining tokens within a line and
continuing only onto the next line of the same region, so a quote can never be
assembled across a column gutter -- the two columns are different regions and the
phrase never forms.

What extracts them is deliberately an argument. This module ships the plain-text
extractor, which is honest about what it is: a `.txt` document has no typography,
so its rectangles are the cells of a fixed-pitch rendering at `CELL`, stated here
rather than implied. `caos/evidence/pdf.py` is the real extractor, proven
against a real PDF fixture (`test_citations_anchor_in_an_extracted_pdf`); it
implements the same protocol and nothing above this module changes.
"""

from __future__ import annotations

import time
import unicodedata
from collections.abc import Iterator
from dataclasses import dataclass
from itertools import combinations, islice
from typing import Protocol

from caos.boundary_text import DEFAULT_LIMIT as BOUNDARY_LIMIT
from caos.boundary_text import BoundaryText
from caos.digest import canonical_json
from caos.refusals import Refusal, RefusalCode

# A fixed-pitch cell, in points. 7.2 x 12.0 is a 12pt monospace at its usual
# advance width; the numbers matter only in that they are declared and constant,
# because a rectangle derived from them describes a rendering we can reproduce.
CELL_WIDTH = 7.2
CELL_HEIGHT = 12.0
MARGIN = 72.0
# A blank line ends a region: consecutive non-blank lines are one paragraph, and
# a paragraph is the unit a quote may wrap within.
LINES_PER_PAGE = 60


@dataclass(frozen=True, slots=True)
class Token:
    """One extracted text run, and where on the page it sat."""

    text: str
    page: int
    region_id: int
    line_id: int
    x0: float
    y0: float
    x1: float
    y1: float


# Why a line's text may not be seen on the rendered page (N27): drawn in text
# render mode 3 -- every OCR'd scan's text layer -- painted near the colour
# behind it, in glyphs under 2 pt, inside optional content the document's
# default configuration switches off, or under an opaque fill the page paints
# over it later. Such text is kept as evidence and its line marked, never
# dropped. Sorted, so a mark is its reasons in this order.
NEAR_BACKGROUND = "near_background"
OPTIONAL_CONTENT_OFF = "optional_content_off"
PAINTED_OVER = "painted_over"
RENDER_MODE_3 = "render_mode_3"
UNDER_2PT = "under_2pt"
HIDDEN_REASONS = (
    NEAR_BACKGROUND,
    OPTIONAL_CONTENT_OFF,
    PAINTED_OVER,
    RENDER_MODE_3,
    UNDER_2PT,
)
# Every mark a line can carry: its reasons, sorted and joined by a comma.
HIDDEN_MARKS = frozenset(
    ",".join(reasons)
    for count in range(1, len(HIDDEN_REASONS) + 1)
    for reasons in combinations(HIDDEN_REASONS, count)
)


@dataclass(frozen=True, slots=True)
class MarkedToken(Token):
    """A token, and why a reader of the rendered page may not see the line it
    is on: one of `HIDDEN_MARKS`, or empty for a line with nothing to note.

    A subclass rather than a field of `Token`, so an extractor that marks
    nothing emits exactly the token it always has."""

    hidden: str = ""


@dataclass(frozen=True, slots=True)
class AdmissionLimits:
    """Host policy ceilings, checked before the expensive step each bounds (§44.1).

    `max_documents` and `max_pack_bytes` bound the whole pack; `max_document_bytes`
    bounds one document, before its extractor ever runs. `max_pages`, `max_tokens`
    and `max_seconds` bound one document's extraction, checked cooperatively by the
    extractor itself -- per page for a PDF, per line for plain text -- so a
    document that crosses one refuses before the rest of it is read, not after.
    """

    max_documents: int
    max_document_bytes: int
    max_pack_bytes: int
    max_pages: int
    max_tokens: int
    max_seconds: float
    # What one PDF's compressed streams may inflate to, in total (§47).
    max_decoded_bytes: int
    # One deadline for the whole pack, capping each document's: fifty documents
    # must not take fifty times `max_seconds` in one request (Phase 4 audit).
    max_pack_seconds: float = 300.0
    # What one pack may hold in tokens, across its documents. `max_tokens`
    # bounds one document, so fifty documents at their own ceiling are 25M
    # token objects -- each a `Token` and, while it is packed, a dict of its
    # fields -- in the one App process that also runs the worker. The pack
    # ceiling is the bound that actually fits the container, and it is checked
    # as each document is extracted rather than after the pack is read.
    max_pack_tokens: int = 2_000_000


DEFAULT_LIMITS = AdmissionLimits(
    max_documents=50,
    max_document_bytes=20 * 1024 * 1024,
    max_pack_bytes=100 * 1024 * 1024,
    max_pages=500,
    max_tokens=500_000,
    max_seconds=60.0,
    max_decoded_bytes=256 * 1024 * 1024,
    max_pack_seconds=300.0,
    max_pack_tokens=2_000_000,
)


@dataclass(frozen=True, slots=True)
class ExtractorIdentity:
    """Host-owned algorithm/version and bounded flat effective configuration."""

    name: str
    version: str
    config: dict[str, str | int | float | bool | None]

    def canonical(self) -> str:
        if not self.name or not self.version or type(self.config) is not dict:
            raise Refusal(RefusalCode.SOURCE_IDENTITY_INVALID)
        texts = [self.name, self.version, *self.config]
        scalar_types = (str, int, float, bool, type(None))
        for value in self.config.values():
            if type(value) not in scalar_types:
                raise Refusal(RefusalCode.SOURCE_IDENTITY_INVALID)
            if isinstance(value, str):
                texts.append(value)
        for text in texts:
            if type(text) is not str or BoundaryText.of(text).value != text:
                raise Refusal(RefusalCode.SOURCE_IDENTITY_INVALID)
        canonical = canonical_json(
            {"name": self.name, "version": self.version, "config": self.config}
        )
        BoundaryText.of(canonical)
        return canonical


class Extractor(Protocol):
    """Bytes to tokens. The one seam a real PDF extractor arrives through."""

    @property
    def identity(self) -> ExtractorIdentity: ...

    def extract(
        self,
        data: bytes,
        *,
        limits: AdmissionLimits = DEFAULT_LIMITS,
        deadline: float = float("inf"),
    ) -> list[Token]: ...


class ExtractorDispatch(Protocol):
    """Chooses the extractor for one document from its bytes (§44.6)."""

    def __call__(self, data: bytes) -> Extractor: ...


# Readers accept a PDF header anywhere in the first kilobyte, so a PDF with
# leading junk is still a PDF; past that it is not one any reader will open.
PDF_HEADER = b"%PDF-"
PDF_HEADER_WINDOW = 1024
# And they look for the end-of-file marker in the last kilobyte, the same
# implementation note's other half: what tells a PDF behind leading junk from
# a text that merely mentions a header near its top (CF-074).
PDF_EOF = b"%%EOF"
PDF_EOF_WINDOW = 1024


def dispatch_by_content(data: bytes) -> Extractor:
    """A PDF by its header, plain text otherwise -- never by its filename.

    A name is whatever the uploader typed; the bytes are what the extractor
    will actually meet. Bytes that begin with the header declare a PDF
    (§44.6). A header further into the first kilobyte is a PDF's only when
    the document also ends as one, so a memo naming `%PDF-1.7` in its first
    lines is read as the text it is rather than refused as a broken PDF.
    """
    at = data.find(PDF_HEADER, 0, PDF_HEADER_WINDOW)
    if at == 0 or (at > 0 and PDF_EOF in data[-PDF_EOF_WINDOW:]):
        # Imported here: `pdf` imports this module, and plain-text admission
        # should not pay for pdfminer.
        from caos.evidence.pdf import PdfExtractor

        return PdfExtractor()
    return PlainTextExtractor()


# The widest token this extractor emits. `BoundaryText`'s own limit, which is
# also what `GROUP_WIDTH` uses, so a token can never be the reason a block is
# refused. A cut falls wherever the width falls, inside a word if that is where
# it falls -- the same trade the line group takes, for the same reason.
MAX_TOKEN_CHARS = BOUNDARY_LIMIT
# How a run past `MAX_TOKEN_CHARS` is cut (`nfc_pieces`), declared by both
# extractors: on its NFC form, each piece taking its share of the run's
# rectangle -- or, in plain text, of its cells -- by character.
RUN_CUT = "nfc-proportional"
# How the plain-text extractor decodes a document, and how a frame re-reads it
# (`page._text_frame`): UTF-8, a leading byte order mark dropped (CF-017).
TEXT_ENCODING = "utf-8-sig"


@dataclass(frozen=True, slots=True)
class PlainTextExtractor:
    """UTF-8 text as tokens on a fixed-pitch page.

    Refuses `SOURCE_NOT_READABLE` for bytes that are not UTF-8, carrying the code
    and nothing else -- the offending bytes are exactly what must not travel.
    A leading byte order mark is read as the encoding's (`TEXT_ENCODING`): kept
    as text, it was the first word's first character, so the document's first
    line was never quoted as it reads.
    """

    @property
    def identity(self) -> ExtractorIdentity:
        return ExtractorIdentity(
            "caos.plain-text",
            # v3: a run past `max_token_chars` is cut. v4: a leading byte
            # order mark is the encoding's, not text (CF-017), and a run is
            # cut on its NFC form, each piece taking its share of the run's
            # cells (CF-073, as F203 cut PDF runs). Earlier rows keep their
            # stored identity and verify as recorded; readmission is how a
            # source gains the new tokenisation (section 44.4's rule).
            "4",
            {
                "encoding": TEXT_ENCODING,
                # Cells from the page's top-left corner, y down: the PDF
                # extractor's convention, with no crop or rotation to apply.
                "coordinates": "cell-top-left-pt",
                "cell_width": CELL_WIDTH,
                "cell_height": CELL_HEIGHT,
                "margin": MARGIN,
                "lines_per_page": LINES_PER_PAGE,
                "max_token_chars": MAX_TOKEN_CHARS,
                "token_cut": RUN_CUT,
            },
        )

    def extract(
        self,
        data: bytes,
        *,
        limits: AdmissionLimits = DEFAULT_LIMITS,
        deadline: float = float("inf"),
    ) -> list[Token]:
        try:
            text = data.decode(TEXT_ENCODING)
        except UnicodeDecodeError:
            raise Refusal(RefusalCode.SOURCE_NOT_READABLE) from None

        tokens: list[Token] = []
        region_id = 0
        for line_number, line in enumerate(text.splitlines()):
            # Checked per line (§44.2): cooperative, not preemptive -- one
            # pathological line can still overrun it (CLAUDE.md ledger).
            if time.monotonic() > deadline:
                raise Refusal(RefusalCode.SOURCE_EXTRACTION_TIMEOUT)
            page = line_number // LINES_PER_PAGE + 1
            if page > limits.max_pages:
                raise Refusal(RefusalCode.SOURCE_TOO_LARGE)
            if not line.strip():
                # A blank line closes the paragraph; the next non-blank one opens
                # a new region, so a quote cannot wrap across the gap.
                region_id += 1
                continue
            # One past the ceiling is enough to refuse: a line of a million
            # words never builds more (Phase 3 adversarial audit).
            words = _line_tokens(line, line_number, region_id)
            tokens.extend(islice(words, limits.max_tokens - len(tokens) + 1))
            if len(tokens) > limits.max_tokens:
                raise Refusal(RefusalCode.SOURCE_TOO_LARGE)
        return tokens


def _line_tokens(line: str, line_number: int, region_id: int) -> Iterator[Token]:
    page, row = divmod(line_number, LINES_PER_PAGE)
    top = MARGIN + row * CELL_HEIGHT
    for word, left, right in _words(line):
        yield Token(
            text=word,
            page=page + 1,
            region_id=region_id,
            line_id=line_number,
            x0=MARGIN + left * CELL_WIDTH,
            y0=top,
            x1=MARGIN + right * CELL_WIDTH,
            y1=top + CELL_HEIGHT,
        )


def _bounded(run: str, start: int) -> Iterator[tuple[str, float, float]]:
    """One whitespace-separated run, cut into tokens `BoundaryText` can hold,
    each with the columns it covers.

    A run longer than `BoundaryText`'s limit refuses the **whole pack** at
    `ingest._prepare`, before any line is grouped -- which is what stops
    Boeing's 71,243-character and Ford's 105,966-character single runs, and
    what no line group can help with, because the line group cuts between
    tokens and this is one token. Cut here instead: the extractor is where a
    token's boundaries are decided, and the cut is declared in its identity.

    The cut is `nfc_pieces`', chosen on the run's NFC form because that is the
    form `BoundaryText` measures (CF-073): cut on its raw length, a run that
    grows under NFC -- 3,000 U+2ADC are 6,000 code points -- fitted the bound
    and refused the pack anyway. A run whose NFC fits is one token, its own
    text, under its own cells; a cut piece takes its share of the run's cells
    by character, which for a run NFC leaves alone is exactly its own.

    Splitting rather than refusing, for the reason the line group splits. A
    refusal leaves the document unadmissible and every honest word in it
    uncitable; a split costs only the artefact. What a run of tens of thousands
    of characters with no whitespace in it actually is -- a base64 blob, a rule
    of dashes, a mangled extraction -- is not a thing a reader could quote as a
    word either.

    **What it costs, stated because `_words` states the rule it breaks.** The
    docstring below says the extractor and `citations.py` must agree on where a
    word ends. They still do for every run inside the bound. For one past it
    they cannot: `matched_text.split()` yields the whole run as one word and no
    stored token equals it, so the run is quotable only piece by piece. It was
    not quotable at all before, because the document did not admit.
    """
    for piece, at, end, of in nfc_pieces(run):
        yield piece, start + len(run) * at / of, start + len(run) * end / of


def nfc_pieces(run: str) -> list[tuple[str, int, int, int]]:
    """One whitespace run as the tokens `BoundaryText` can hold, each with the
    span of the run's NFC form it covers: `(text, start, end, of)`.

    The PDF extractor's cut (CF-072, CF-073). A run whose NFC fits
    `MAX_TOKEN_CHARS` is one token, its own text as drawn. Past it the cut
    points are chosen on the NFC form -- the form `BoundaryText` measures --
    so a piece is never past the limit it is measured against, as a raw cut
    can be: 3,000 U+2ADC fit a raw bound and are 6,000 code points in NFC.
    The plain-text extractor cuts by it too, from its v4 (`_bounded`).
    """
    normal = unicodedata.normalize("NFC", run)
    size = len(normal)
    if size <= MAX_TOKEN_CHARS:
        return [(run, 0, size, size)]
    return [
        (normal[at : at + MAX_TOKEN_CHARS], at, min(at + MAX_TOKEN_CHARS, size), size)
        for at in range(0, size, MAX_TOKEN_CHARS)
    ]


def _words(line: str) -> Iterator[tuple[str, float, float]]:
    """Each whitespace-separated run, cut by `_bounded`, with the columns it
    starts and ends at.

    Whitespace as `str.split()` draws it, not the space character alone.
    `caos/evidence/citations.py` splits `matched_text` that way, so a token
    holding an interior tab is one the index can never be asked for: the line is
    delivered by `read_evidence` and the verbatim quote of it is then refused
    `CITATION_NOT_LOCATED`. The two have to agree on where a word ends, or the
    evidence a module was handed is evidence it cannot cite.
    """
    start: int | None = None
    for column, character in enumerate(line):
        if not character.isspace():
            if start is None:
                start = column
        elif start is not None:
            yield from _bounded(line[start:column], start)
            start = None
    if start is not None:
        yield from _bounded(line[start:], start)

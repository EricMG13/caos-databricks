"""A real PDF into tokens that carry where they were.

`pdfminer.six` exposes a layout tree that maps exactly onto the three things
invariant 11 needs from a token:

    LTTextBox   -> the region a quote may not leave
    LTTextLine  -> the line it sits on
    LTChar      -> the rectangle, taken from the character rather than estimated

The last one is the point. `PlainTextExtractor` derives rectangles from a
declared fixed pitch, which is honest for a `.txt` file and is a fiction for a
PDF. Here the coordinates come out of the document, so a citation's rectangle is
a measurement rather than a reconstruction.

Rectangles are given in one convention whatever the page (§44.3): points from
the CropBox's top-left corner as the page is displayed, after `/Rotate`, with y
growing downward. Identity version 2 declares it beside the layout parameters
that decide where a word, a line and a region end; version 3 adds the width a
token is cut at.

Nothing above this module changes. It implements the same `Extractor` protocol,
so ingestion, block packing, citation anchoring and every refusal are the ones
already tested -- which is what a seam is for.

The walk runs in a child interpreter (§47). One page of a few kilobytes can
inflate to gigabytes or hold millions of operators, and neither is visible
between pages, so the parent kills the child at the deadline and the child's
decoders -- every filter pdfminer can apply, not `zlib` alone -- refuse past
`max_decoded_bytes`, under an address-space limit where the platform has one:
the bounds hold whatever pdfminer is doing. The child is `python -I` with an
empty environment -- no credential, no caller's `__main__` re-run -- and speaks
JSON, so nothing it prints is code.
"""

from __future__ import annotations

import json
import logging
import math
import subprocess  # nosec B404
import sys
import time
import zlib
from collections.abc import Callable, Iterator
from dataclasses import asdict, astuple, dataclass
from importlib.metadata import version
from io import BytesIO
from pathlib import Path
from typing import TYPE_CHECKING, TypedDict

from pdfminer.layout import LAParams, LTAnno, LTChar, LTPage, LTTextBox, LTTextLine
from pdfminer.pdfparser import PDFSyntaxError
from pdfminer.utils import apply_matrix_rect

from caos.evidence.extract import (
    DEFAULT_LIMITS,
    MAX_TOKEN_CHARS,
    RUN_CUT,
    AdmissionLimits,
    ExtractorIdentity,
    MarkedToken,
    Token,
    nfc_pieces,
)
from caos.refusals import Refusal, RefusalCode

if TYPE_CHECKING:
    from pdfminer.pdfpage import PDFPage


class _Layout(TypedDict):
    line_overlap: float
    char_margin: float
    line_margin: float
    word_margin: float
    boxes_flow: float
    detect_vertical: bool
    all_texts: bool


# The layout analysis pdfminer runs with, stated rather than inherited: these
# are pdfminer's own defaults, pinned here so the identity names the scalars
# that decide where a word, a line and a region end.
LAYOUT: _Layout = {
    "line_overlap": 0.5,
    "char_margin": 2.0,
    "line_margin": 0.5,
    "word_margin": 0.1,
    "boxes_flow": 0.5,
    "detect_vertical": False,
    "all_texts": False,
}
COORDINATES = "crop-top-left-rotated-pt"
# A token not wholly inside the crop is text no reader sees: dropped, not clipped.
CROP_POLICY = "drop-outside"
# pdfminer opens an unencrypted document with the empty password; the identity
# record names the parameter as pdfminer does and carries that value.
UNENCRYPTED = ""
# What marks a line a reader of the rendered page may not see (N27,
# `caos/evidence/visibility.py`), declared because it decides the tokens' marks.
# Text render mode 3 paints a glyph neither filled nor stroked (ISO 32000-1,
# 9.3.6): it lays out, and nothing is drawn.
INVISIBLE_RENDER_MODE = 3
# N27's remainder: render mode 7 -- add to the clip path, neither filled nor
# stroked -- is the same "nothing is drawn" as mode 3, so the same glyph is
# marked `render_mode_3` under it. Not declared in `PdfExtractor.identity`'s
# config: no admitted fixture's tokens change under it (checked directly,
# `tests/test_hidden_text.py`), and the config is part of the identity a
# stored source's own record must still verify against, so it is left to name
# only what a change in it would actually move.
CLIP_ONLY_RENDER_MODE = 7
# A glyph whose em is smaller than this on the page, in points, is not read.
SMALLEST_READABLE_PT = 2.0
# How far a glyph's paint may be from what is behind it, per channel of an RGB
# colour on 0..1, and still be the same colour to a reader.
NEAR_BACKGROUND_DISTANCE = 0.1
# What is behind a glyph: the last filled path under its centre, or white.
BACKDROP = "last-filled-path-over-white"

Frame = tuple[float, float, float, float]


@dataclass(frozen=True, slots=True)
class PdfExtractor:
    """Bytes of a PDF, as tokens with real coordinates."""

    @property
    def identity(self) -> ExtractorIdentity:
        # Everything that decides the tokens: engine, layout, convention, crop.
        return ExtractorIdentity(
            "caos.pdfminer",
            # v3: a run whose NFC is past `max_token_chars` is cut on its NFC
            # form, each piece taking its share of the run's rectangle by
            # character (CF-072, CF-073). v4: a line a reader of the rendered
            # page may not see is kept and marked with why (N27). Earlier rows
            # keep their stored identity and verify as recorded; readmission
            # is how a source gains the new tokens (section 44.4's rule).
            "4",
            {
                "pdfminer_version": version("pdfminer.six"),
                "line_overlap": LAYOUT["line_overlap"],
                "char_margin": LAYOUT["char_margin"],
                "line_margin": LAYOUT["line_margin"],
                "word_margin": LAYOUT["word_margin"],
                "boxes_flow": LAYOUT["boxes_flow"],
                "detect_vertical": LAYOUT["detect_vertical"],
                "all_texts": LAYOUT["all_texts"],
                "coordinates": COORDINATES,
                "crop_policy": CROP_POLICY,
                "password": UNENCRYPTED,
                "page_numbers": "all",
                "maxpages": 0,
                "caching": True,
                "max_token_chars": MAX_TOKEN_CHARS,
                "token_cut": RUN_CUT,
                "hidden_render_mode": INVISIBLE_RENDER_MODE,
                "hidden_under_pt": SMALLEST_READABLE_PT,
                "hidden_near_background": NEAR_BACKGROUND_DISTANCE,
                "hidden_backdrop": BACKDROP,
            },
        )

    def extract(
        self,
        data: bytes,
        *,
        limits: AdmissionLimits = DEFAULT_LIMITS,
        deadline: float | None = None,
    ) -> list[Token]:
        """`walk_pages` in a child interpreter, killed at `deadline` (§47).

        Refuses `SOURCE_EXTRACTION_TIMEOUT` when the child has not answered by
        the deadline, `SOURCE_TOO_LARGE` when its streams inflate past
        `max_decoded_bytes`, `SOURCE_ENCRYPTED` for an encrypted document, and
        `SOURCE_NOT_READABLE` for anything else, an unreadable answer included.
        Only a code or the tokens cross back, never a message.
        """
        header: dict[str, object] = {"limits": asdict(limits)}
        return _answer(*_in_child(header, data, _finite(deadline, limits)))


def page_frame(
    data: bytes,
    page: int,
    *,
    limits: AdmissionLimits = DEFAULT_LIMITS,
    deadline: float | None = None,
) -> Frame:
    """One page's visible crop in pdfminer's layout space, y up (`_crop_frame`).

    Read in the same killed, budgeted child as `extract` (§47): the page tree,
    its boxes and `/Rotate` only -- no content stream is interpreted and no
    layout runs -- but a cross-reference or object stream still inflates, so
    the deadline and `max_decoded_bytes` bound it as they bound extraction.
    Refuses `PAGE_NOT_AVAILABLE` for a page the document does not have or
    whose crop clips to nothing, and the child's codes otherwise.
    """
    header = {"limits": asdict(limits), "frame": page}
    return _frame_answer(*_in_child(header, data, _finite(deadline, limits)))


def _finite(deadline: float | None, limits: AdmissionLimits) -> float:
    """A caller that names no deadline gets the limits' own, and one that names
    a deadline no clock reaches gets it too.

    An entry point for untrusted bytes never waits forever on a child (F56),
    and `float('inf')` is exactly that wait: `communicate(timeout=inf)` raises
    `OverflowError` out of the selector, untyped, past every refusal this
    module states (AR-16/CR-10). NaN is the same wait by another spelling --
    every comparison against it is false -- so both are clamped to the limits'
    own seconds rather than refused: a caller asking for no deadline gets the
    host's, which is what `None` already means here.
    """
    own = time.monotonic() + limits.max_seconds
    if deadline is None or not math.isfinite(deadline):
        return own
    return deadline


def _in_child(
    header: dict[str, object], data: bytes, deadline: float
) -> tuple[bytes, int]:
    """The child's answer to `header` and `data` with its exit status, or
    `SOURCE_EXTRACTION_TIMEOUT` once `deadline` passes, with the child killed."""
    line = json.dumps({**header, "deadline": deadline}).encode()
    # Always a finite wait: `_finite` is what both entry points pass through,
    # and it clamps the deadlines a clock never reaches (F56, AR-16).
    wait = deadline - time.monotonic()
    if wait <= 0.0:
        # Before `Popen`: an interpreter started only to be killed unanswered is
        # a tenth of a second spent on a deadline that has already passed.
        raise Refusal(RefusalCode.SOURCE_EXTRACTION_TIMEOUT)
    # ponytail: one interpreter per PDF; a pool if admission volume makes the
    # start-up cost show.
    # Fixed argv, no shell, an empty environment.
    child = subprocess.Popen(  # nosec B603
        [sys.executable, "-I", "-c", _CHILD, str(_ROOT)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        env={},
    )
    try:
        out, _ = child.communicate(line + b"\n" + data, timeout=wait)
    except subprocess.TimeoutExpired:
        out = None
    if out is None:
        child.kill()
        child.communicate()
        raise Refusal(RefusalCode.SOURCE_EXTRACTION_TIMEOUT)
    return out, child.returncode


_ROOT = Path(__file__).resolve().parents[2]
_CHILD = (
    "import sys; sys.path.insert(0, sys.argv[1]); "
    "from caos.evidence.pdf import child_main; child_main()"
)
# What a child may answer; anything else it says is an unreadable document.
_CHILD_CODES = frozenset(
    {
        RefusalCode.SOURCE_NOT_READABLE,
        RefusalCode.SOURCE_ENCRYPTED,
        RefusalCode.SOURCE_TOO_LARGE,
        RefusalCode.SOURCE_EXTRACTION_TIMEOUT,
    }
)


def _note_death(returncode: int) -> None:
    """Say that the host's own child died rather than answering.

    The refusal is still the document's -- nothing better can be said about
    bytes no extraction was produced from -- but an unanswered child is a host
    fault, and an exit status is an integer, never document text.
    """
    if returncode != 0:
        print(f"extractor child exited {returncode}", file=sys.stderr)


def _answer(out: bytes, returncode: int) -> list[Token]:
    """The child's JSON answer as tokens, or the refusal it names."""
    _note_death(returncode)
    code = RefusalCode.SOURCE_NOT_READABLE
    tokens: list[Token] | None = None
    try:
        answer = json.loads(out)
        if "tokens" in answer:
            tokens = [MarkedToken(*row) for row in answer["tokens"]]
        elif RefusalCode(answer["refused"]) in _CHILD_CODES:
            code = RefusalCode(answer["refused"])
    except (ValueError, TypeError, KeyError):
        tokens = None
    if tokens is None:
        raise Refusal(code)
    return tokens


def _frame_answer(out: bytes, returncode: int) -> Frame:
    """The child's frame, `PAGE_NOT_AVAILABLE` for its `null`, or the code
    it names; anything else it says is an unreadable document."""
    _note_death(returncode)
    code = RefusalCode.SOURCE_NOT_READABLE
    frame: Frame | None = None
    try:
        answer = json.loads(out)
        if "frame" in answer and answer["frame"] is None:
            code = RefusalCode.PAGE_NOT_AVAILABLE
        elif "frame" in answer:
            (x0, y0, x1, y1) = (float(value) for value in answer["frame"])
            if all(math.isfinite(value) for value in (x0, y0, x1, y1)):
                frame = (x0, y0, x1, y1)
        elif RefusalCode(answer["refused"]) in _CHILD_CODES:
            code = RefusalCode(answer["refused"])
    except (ValueError, TypeError, KeyError):
        frame = None
    if frame is None:
        raise Refusal(code)
    return frame


def walk_pages(data: bytes, *, limits: AdmissionLimits, deadline: float) -> list[Token]:
    """The tokens of every page, in this process. Refuses `SOURCE_NOT_READABLE`
    for bytes that are not a readable PDF.

    A scanned page parses fine and yields no tokens; that is not an error
    here, and `admit_pack` refuses it as `SOURCE_HAS_NO_TEXT` -- the code
    that says what is actually wrong with it.

    Pages come from `_pages` one at a time, and the page and time ceilings
    are checked before a page's boxes are walked -- so a document that
    crosses `max_pages` stops pulling pages from pdfminer's own generator
    rather than paying to lay out every remaining page first (§44.1/§44.2).
    Only `PdfExtractor.extract`'s child should call it for untrusted bytes.
    """
    tokens: list[Token] = []
    region_id = 0
    line_id = 0
    for page_number, (frame, page, hidden) in enumerate(_pages(data), start=1):
        if page_number > limits.max_pages:
            raise Refusal(RefusalCode.SOURCE_TOO_LARGE)
        # Checked per page (§44.2): cooperative, not preemptive -- one
        # pathological page can still overrun it (CLAUDE.md ledger).
        if time.monotonic() > deadline:
            raise Refusal(RefusalCode.SOURCE_EXTRACTION_TIMEOUT)
        if frame is None:
            # Nothing on the page is visible, so nothing on it is citable.
            continue
        sheet = _Sheet(page_number, frame, hidden)
        for box in page:
            if not isinstance(box, LTTextBox):
                continue
            for line in box:
                if not isinstance(line, LTTextLine):
                    continue
                tokens.extend(_line_tokens(line, sheet, region_id, line_id))
                if len(tokens) > limits.max_tokens:
                    raise Refusal(RefusalCode.SOURCE_TOO_LARGE)
                line_id += 1
            region_id += 1
    return tokens


def _pages(data: bytes) -> Iterator[tuple[Frame | None, LTPage, dict[LTChar, str]]]:
    """Each page's layout beside its visible crop in the layout's own space,
    and why a reader of the rendered page may not see each glyph that has a
    reason (`visibility.MarkingAggregator`).

    `extract_pages`, written out so the `PDFPage` -- which carries the crop and
    the rotation, and which `extract_pages` does not hand back -- stays in hand.
    """
    # Imported here rather than at module scope: the interpreter pulls in most
    # of pdfminer, and nothing that merely imports this module should pay for it.
    from pdfminer.pdfinterp import PDFPageInterpreter, PDFResourceManager
    from pdfminer.pdfpage import PDFPage

    from caos.evidence.visibility import MarkingAggregator

    # Yielding inside this try keeps the whole walk lazy -- a caller that stops
    # asking for pages (the page ceiling above) never drives pdfminer's
    # generator past the one that crossed it -- while still catching a
    # malformed file however far into the walk it turns up malformed.
    try:
        resources = PDFResourceManager(caching=True)
        device = MarkingAggregator(resources, LAParams(**LAYOUT))
        interpreter = PDFPageInterpreter(resources, device)
        for page in PDFPage.get_pages(BytesIO(data), caching=True):
            frame = _crop_frame(page)
            interpreter.process_page(page)
            yield frame, device.get_result(), device.hidden
    except (PDFSyntaxError, ValueError, TypeError, AssertionError):
        # pdfminer reports a malformed file in several shapes. None of them may
        # travel: the message quotes the bytes it choked on.
        raise Refusal(RefusalCode.SOURCE_NOT_READABLE) from None


def _crop_frame(page: PDFPage) -> Frame | None:
    """The visible region, in the rotated y-up space pdfminer lays a page out in,
    or `None` when the CropBox clipped to the MediaBox is empty on either axis.

    `PDFPageInterpreter.process_page` maps user space through a matrix built
    from the MediaBox and `/Rotate`; this is that matrix, applied to the
    CropBox clipped to the MediaBox (the PDF specification's visible region),
    so the frame and every character sit in one space. A rotation that is not
    a quarter turn is refused: pdfminer would lay it out unrotated, and the
    convention could not say what a reader sees.
    """
    if page.rotate not in (0, 90, 180, 270):
        raise Refusal(RefusalCode.SOURCE_NOT_READABLE)
    (x0, y0, x1, y1) = page.mediabox
    ctm = {
        90: (0, -1, 1, 0, -y0, x1),
        180: (-1, 0, 0, -1, x1, y1),
        270: (0, 1, -1, 0, y1, -x0),
    }.get(page.rotate, (1, 0, 0, 1, -x0, -y0))
    (m0, n0, m1, n1) = _ordered(page.mediabox)
    (c0, d0, c1, d1) = _ordered(page.cropbox)
    visible = (max(m0, c0), max(n0, d0), min(m1, c1), min(n1, d1))
    if visible[0] >= visible[2] or visible[1] >= visible[3]:
        # Clipped to nothing. `apply_matrix_rect` would normalise the inverted
        # rectangle into one covering the gap between the boxes -- text no
        # reader sees -- so an empty visible area is no frame at all.
        return None
    return apply_matrix_rect(ctm, visible)


def _page_crop(data: bytes, page: int, *, deadline: float) -> Frame | None:
    """`_crop_frame` of page `page`, or `None` past the document's last page.

    `PDFPage.get_pages` builds each page from the page tree -- its inherited
    boxes and `/Rotate` -- without interpreting a content stream.
    """
    from pdfminer.pdfpage import PDFPage

    try:
        pages = PDFPage.get_pages(BytesIO(data), caching=True)
        for number, candidate in enumerate(pages, start=1):
            if time.monotonic() > deadline:
                raise Refusal(RefusalCode.SOURCE_EXTRACTION_TIMEOUT)
            if number == page:
                return _crop_frame(candidate)
    except (PDFSyntaxError, ValueError, TypeError, AssertionError):
        raise Refusal(RefusalCode.SOURCE_NOT_READABLE) from None
    return None


def _ordered(rect: Frame) -> Frame:
    (x0, y0, x1, y1) = rect
    return (min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1))


@dataclass(frozen=True, slots=True)
class _Sheet:
    """One page as its lines are read: its number, its visible crop and why a
    reader may not see each glyph that has a reason."""

    number: int
    frame: Frame
    hidden: dict[LTChar, str]


def _line_tokens(
    line: LTTextLine, sheet: _Sheet, region_id: int, line_id: int
) -> list[Token]:
    """Whitespace-separated runs of one line, each under the union of its
    characters' rectangles, measured from the crop's top-left corner.

    A run not wholly inside the crop is dropped: a clipped rectangle would
    anchor a quote whose other half no reader can see. A run past
    `MAX_TOKEN_CHARS` is cut as `nfc_pieces` cuts it (CF-072), each piece
    under its share of the run's rectangle. A page whose crop misses
    the MediaBox has no frame and never reaches here (`extract` skips it).
    Membership uses pdfminer's full glyph box, descent included, so a word
    whose baseline is inside the edge but whose box crosses it is dropped.

    Every token carries its line's mark (N27): why a reader of the rendered
    page may not see some of the text the line keeps, gathered over the
    glyphs of its kept runs -- one note a line, as the line is what a module
    and the approver are shown.
    """
    (left, _bottom, _right, top) = sheet.frame
    boxed = [(run, _box(run)) for run in _runs(line)]
    kept = [(run, box) for run, box in boxed if _within(box, sheet.frame)]
    mark = _mark([character for run, _box in kept for character in run], sheet)
    tokens: list[Token] = []
    for run, (x0, y0, x1, y1) in kept:
        text = "".join(character.get_text() for character in run)
        tokens.extend(
            MarkedToken(
                text=piece,
                page=sheet.number,
                region_id=region_id,
                line_id=line_id,
                x0=_along(x0, x1, start, of) - left,
                y0=top - y1,
                x1=_along(x0, x1, end, of) - left,
                y1=top - y0,
                hidden=mark,
            )
            for piece, start, end, of in nfc_pieces(text)
        )
    return tokens


def _mark(characters: list[LTChar], sheet: _Sheet) -> str:
    """The reasons any of `characters` may not be seen, sorted and joined."""
    reasons: set[str] = set()
    for character in characters:
        noted = sheet.hidden.get(character)
        if noted:
            reasons.update(noted.split(","))
    return ",".join(sorted(reasons))


def _within(box: Frame, frame: Frame) -> bool:
    """Whether `box` lies wholly inside the visible `frame`."""
    (left, bottom, right, top) = frame
    return left <= box[0] and box[2] <= right and bottom <= box[1] and box[3] <= top


def _box(run: list[LTChar]) -> Frame:
    """The union of a run's glyph rectangles, in pdfminer's layout space."""
    return (
        min(character.x0 for character in run),
        min(character.y0 for character in run),
        max(character.x1 for character in run),
        max(character.y1 for character in run),
    )


def _along(x0: float, x1: float, at: int, of: int) -> float:
    """The point `at` characters of `of` along a run from `x0` to `x1`: its
    share by character, and the run's own edges exactly at either end."""
    if at == 0:
        return x0
    if at == of:
        return x1
    return x0 + (x1 - x0) * at / of


def _runs(line: LTTextLine) -> list[list[LTChar]]:
    """The line's characters grouped into words.

    Split on whitespace as the document draws it, so a word's rectangle covers
    the word and not the space beside it -- a rectangle wider than its quote
    highlights text the citation does not contain.

    A word break is not only a drawn space glyph: pdfminer's own layout
    analysis (`LTTextLineHorizontal.add`) inserts a virtual `LTAnno(" ")`
    between two characters whose gap exceeds `laparams.word_margin` times the
    character's own width or height -- which is how two glyphs positioned by a
    `TJ` kerning array with no space character between them are recognised as
    two words rather than one run of letters (§44.5: glyph merging follows
    pdfminer's `word_margin`, no custom heuristic). `LTAnno` carries no
    rectangle, so it never becomes part of a run; it only ends one.
    """
    runs: list[list[LTChar]] = []
    current: list[LTChar] = []
    for item in line:
        if isinstance(item, LTAnno):
            if item.get_text().isspace() and current:
                runs.append(current)
                current = []
            continue
        if not isinstance(item, LTChar):
            continue
        if item.get_text().isspace():
            if current:
                runs.append(current)
                current = []
            continue
        current.append(item)
    if current:
        runs.append(current)
    return runs


class _Inflated(Exception):
    """The document's streams inflated past `max_decoded_bytes`."""


class _Inflater:
    """`zlib` as pdfminer's stream decoder sees it in the child: one budget.

    `decompress` keeps `zlib.decompress`'s contract (an incomplete or corrupt
    stream raises `zlib.error`, which sends pdfminer to its fallback), and the
    fallback's `decompressobj` draws on the same budget, so a corrupt checksum
    is no way around it. Output past the budget is never produced.
    """

    error = zlib.error

    def __init__(self, budget: int) -> None:
        self.left = budget
        self.exceeded = False

    def take(self, stream: zlib._Decompress, data: bytes) -> bytes:
        out = stream.decompress(data, self.left + 1)
        self.left -= len(out)
        if self.left < 0 or stream.unconsumed_tail:
            self.exceeded = True
            raise _Inflated
        return out

    def decompress(self, data: bytes) -> bytes:
        stream = zlib.decompressobj()
        out = self.take(stream, data)
        if not stream.eof:
            raise zlib.error
        return out

    def decompressobj(self) -> _Stream:
        return _Stream(self)


class _Stream:
    def __init__(self, inflater: _Inflater) -> None:
        self.inflater, self.stream = inflater, zlib.decompressobj()

    def decompress(self, data: bytes) -> bytes:
        return self.inflater.take(self.stream, data)


# The stream filters pdfminer decodes through its own unbudgeted functions.
# `zlib` is replaced wholesale above; these four are module-level names in
# `pdfminer.pdftypes` that `PDFStream.decode` looks up when it runs, so
# rebinding them there is the same seam (AS-1). `ccittfaxdecode` is not among
# them: it decodes an image, and its output is bounded by the /Columns and
# /Rows the stream declares.
BUDGETED_FILTERS = ("lzwdecode", "rldecode", "ascii85decode", "asciihexdecode")
# What the child's address space may reach, over `max_decoded_bytes`: the
# interpreter, pdfminer's tables and one document's decoded streams. A decoder
# that grows past it gets `MemoryError`, which the child already answers
# `SOURCE_TOO_LARGE` with, rather than growing until the container restarts.
ADDRESS_SPACE_HEADROOM = 512 * 1024 * 1024


def _budgeted(
    decode: Callable[[bytes], bytes], inflater: _Inflater
) -> Callable[[bytes], bytes]:
    """`decode` with its output drawn from the same budget `zlib` draws on.

    The output is measured after the decoder returns, so the budget is what
    bounds the *total* a document decodes; `RLIMIT_AS` is what bounds the one
    call, because only the operating system can stop a decoder that is still
    inside its own loop.
    """

    def bounded(data: bytes) -> bytes:
        out = decode(data)
        inflater.left -= len(out)
        if inflater.left < 0:
            inflater.exceeded = True
            raise _Inflated
        return out

    return bounded


def _limit_address_space(inflater: _Inflater) -> None:
    """Cap the child's address space where the platform has one to cap.

    Linux is where the App runs and where `RLIMIT_AS` binds. macOS reserves a
    very large address space for the shared cache before any of our code runs,
    so a limit there either refuses or fails every later mapping; the try is
    not decoration, and the child is still bounded by its deadline and by the
    decoded-bytes budget wherever the limit does not apply.
    """
    import resource

    ceiling = inflater.left + ADDRESS_SPACE_HEADROOM
    try:
        (_soft, hard) = resource.getrlimit(resource.RLIMIT_AS)
        if hard != resource.RLIM_INFINITY:
            ceiling = min(ceiling, hard)
        resource.setrlimit(resource.RLIMIT_AS, (ceiling, hard))
    except (OSError, ValueError, AttributeError):
        return


def child_main() -> None:
    """The extraction child: a header line and the document on stdin, one JSON
    answer on stdout -- the tokens, or with `frame` in the header that page's
    crop (`page_frame`). Its logs and its inflater are its own, and it never
    raises: a traceback would print the text pdfminer choked on (stderr is
    discarded by the parent as well).

    Every filter pdfminer can decode draws on the one budget, not `zlib`
    alone: `LZWDecode`, `RunLengthDecode` and the two ASCII filters build
    their output with no bound of their own, so a document that uses them
    would otherwise be held only by the wall clock (AS-1). The address-space
    limit is the backstop under all of them, for the decoder that is still
    inside its own loop when the budget would have stopped it.
    """
    import pdfminer.pdftypes
    from pdfminer.pdfdocument import PDFEncryptionError

    quiet = logging.getLogger("pdfminer")
    quiet.addHandler(logging.NullHandler())
    quiet.propagate = False
    answer: dict[str, object] = {"refused": RefusalCode.SOURCE_NOT_READABLE}
    inflater = _Inflater(0)
    try:
        header = json.loads(sys.stdin.buffer.readline())
        limits = AdmissionLimits(**header["limits"])
        inflater = _Inflater(limits.max_decoded_bytes)
        pdfminer.pdftypes.zlib = inflater  # type: ignore[assignment,attr-defined]
        for name in BUDGETED_FILTERS:
            decoder = _budgeted(getattr(pdfminer.pdftypes, name), inflater)
            setattr(pdfminer.pdftypes, name, decoder)
        _limit_address_space(inflater)
        (data, deadline) = (sys.stdin.buffer.read(), float(header["deadline"]))
        if "frame" in header:
            frame = _page_crop(data, int(header["frame"]), deadline=deadline)
            answer = {"frame": frame}
        else:
            tokens = walk_pages(data, limits=limits, deadline=deadline)
            answer = {"tokens": [astuple(token) for token in tokens]}
    except Refusal as refusal:
        answer = {"refused": refusal.code}
    except (_Inflated, MemoryError):
        answer = {"refused": RefusalCode.SOURCE_TOO_LARGE}
    except PDFEncryptionError:
        answer = {"refused": RefusalCode.SOURCE_ENCRYPTED}
    except BaseException:  # noqa: BLE001 -- untrusted bytes; any failure is a code
        answer = {"refused": RefusalCode.SOURCE_NOT_READABLE}
    if inflater.exceeded:  # however pdfminer handled the exception on its way up
        answer = {"refused": RefusalCode.SOURCE_TOO_LARGE}
    sys.stdout.buffer.write(json.dumps(answer).encode())

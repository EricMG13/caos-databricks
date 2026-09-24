"""One page of a run's pinned live source, as its text layer and frame.

Phase 4 Task 4.4 decisions 7 and 8. A page is served only from a source that is
live now and a member of the run's pinned source-set version with the document
and extraction identity the pin captured -- the `_RUN_BLOCKS_QUERY` join of
`caos/evidence/read.py` (invariant 1: withdrawal is checked at every use).
Its lines are the token index citations were anchored in, grouped by
`(region_id, line_id)`: the joined words and their union rectangle, in the
coordinates the tokens are stored in (invariant 11). No renderer draws the page.

The frame says what those coordinates are, read from the digest-verified
document under the stored extractor identity: a `caos.pdfminer` row's from v2
on (`PDF_CROP_VERSIONS`) are crop-relative with y down (§44.3), a v1 row's are
pdfminer's layout space with y up (§44.4), and a `caos.plain-text` row's are
the cells of its recorded fixed pitch. PDF frames come from the §47 child, and
a crop that child has already answered for a document is remembered in process
(`FRAME_CACHE_SIZE`): it is derived from a digest-addressed document and a page
number, so it cannot go stale, and the child costs an interpreter each time.

The store is read first and the read unit is ended before the document is
read or the child is run, so an extraction that takes seconds holds no
transaction or snapshot on the request's connection. That costs invariant 1
nothing. The membership row is a plain read with no lock, so a withdrawal
committed after it was never excluded by holding the transaction open: the
check is the read's, at the instant of the read, whether the extraction runs
inside that unit or after it. What is served after it is the stored lines that
read returned and a frame -- four numbers and an axis, no document text --
derived from bytes that are content-addressed and re-verified against the pin
by `BlobStore.get`, so nothing the extraction produces depends on the store.

Everything unavailable -- not pinned, withdrawn, re-extracted, a page the
document does not have, bytes that no longer hash to the pin, a child that
refused -- is one `PAGE_NOT_AVAILABLE`, raised outside any `except` so no
chain carries text (invariant 2). A stored identity no reader here knows is
the server's own row failing, `SOURCE_IDENTITY_INVALID`.
"""

from __future__ import annotations

import json
import math
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any, Literal, cast
from uuid import UUID

import psycopg

from caos.api.wire import (
    PAGE_LINES_MAX,
    PAGE_MAX,
    QUOTE_CHARS,
    FrameView,
    HiddenReason,
    PageBody,
    PageLine,
)
from caos.blobs import BlobStore
from caos.evidence.extract import DEFAULT_LIMITS, HIDDEN_REASONS, AdmissionLimits
from caos.refusals import Refusal, RefusalCode
from caos.store import StoreConnection

# The membership row and the page's lines in one statement; the blob read is
# not a store round trip.
IO_BUDGET = 1

_PAGE_QUERY = (
    "WITH member AS (SELECT sources.source_id, sources.document_sha256,"
    " extraction.extractor_identity FROM runs AS run"
    " JOIN run_inputs AS inputs ON (inputs.run_id,inputs.case_id)"
    " = (run.run_id,run.case_id)"
    " JOIN source_set_versions AS versions"
    " ON (versions.case_id,versions.version,versions.fingerprint)"
    " = (inputs.case_id,inputs.source_version,inputs.source_fingerprint)"
    " JOIN source_set_members AS members ON (members.case_id,members.version)"
    " = (versions.case_id,versions.version)"
    " JOIN live_sources AS sources ON (sources.case_id,sources.source_id)"
    " = (members.case_id,members.source_id)"
    " JOIN source_extractions AS extraction"
    " ON extraction.source_id = sources.source_id"
    " WHERE run.case_id = %s AND run.run_id = %s AND sources.source_id = %s"
    " AND members.document_sha256 = sources.document_sha256"
    " AND members.extractor_identity = extraction.extractor_identity"
    " AND members.output_sha256 = extraction.output_sha256"
    " AND members.extraction_sha256 = extraction.extraction_sha256)"
    " SELECT member.document_sha256, member.extractor_identity,"
    " left(line.text, %s), length(line.text) > %s,"
    " line.x0, line.y0, line.x1, line.y1, line.hidden"
    " FROM member LEFT JOIN LATERAL (SELECT"
    " string_agg(t.text, ' ' ORDER BY t.token_id) AS text,"
    " min(t.x0) AS x0, min(t.y0) AS y0, max(t.x1) AS x1, max(t.y1) AS y1,"
    " max(t.hidden) AS hidden,"
    " min(t.token_id) AS first FROM source_tokens AS t"
    " WHERE t.source_id = member.source_id AND t.page = %s"
    " GROUP BY t.region_id, t.line_id ORDER BY first LIMIT %s) AS line ON true"
    " ORDER BY line.first"
)
PDF_V2_COORDINATES = "crop-top-left-rotated-pt"
# The `caos.pdfminer` versions whose rectangles are crop-relative with y down:
# v2 introduced the convention, v3 cuts long runs within it (CF-072) and v4
# marks the lines a reader may not see (N27).
PDF_CROP_VERSIONS = frozenset({"2", "3", "4"})
TEXT_COORDINATES = "cell-top-left-pt"


@dataclass(frozen=True, slots=True)
class PageRead:
    """The page's body, and whether its text layer was cut to its bounds --
    more than `PAGE_LINES_MAX` lines, or a line longer than `QUOTE_CHARS`."""

    body: PageBody
    truncated: bool


def read_page(  # noqa: PLR0913 -- the store, the blobs, one page's four ids, the actor
    conn: StoreConnection,
    blobs: BlobStore,
    *,
    case_id: UUID,
    run_id: UUID,
    source_id: UUID,
    page: int,
    limits: AdmissionLimits = DEFAULT_LIMITS,
    actor_id: UUID | None = None,
) -> PageRead:
    """Page `page` of `source_id` as the run `run_id` of `case_id` pinned it,
    or `PAGE_NOT_AVAILABLE`. Authorisation is the caller's, and must be read
    before this is called: this ends the caller's read unit once the page's
    rows are fetched, before the document is read or its frame extracted.
    `actor_id`, when given, is who a shared `FRAME_CHILDREN` slot is charged
    to (N38); a caller that does not pass one shares nothing."""
    if (
        any(not isinstance(value, UUID) for value in (case_id, run_id, source_id))
        or type(page) is not int
        or not 1 <= page <= PAGE_MAX
    ):
        raise Refusal(RefusalCode.PAGE_NOT_AVAILABLE)
    rows = _rows(conn, (case_id, run_id, source_id, page))
    # A read unit: rolling it back sends what the connection's exit would
    # have sent as COMMIT, so this costs no round trip the budget does not
    # already pay, and the blob read and the child below run with none open.
    conn.rollback()
    if not rows:
        raise Refusal(RefusalCode.PAGE_NOT_AVAILABLE)
    (document, identity) = (str(rows[0][0]), str(rows[0][1]))
    name, version, config = _identity(identity)
    data = _document(blobs, document)
    deadline = time.monotonic() + limits.max_seconds
    crop = _Crop(document, data, limits, deadline, actor_id)
    frame = _frame(name, version, config, crop, page)
    lines = [row for row in rows if row[2] is not None]
    body = PageBody(
        case_id=case_id,
        run_id=run_id,
        source_id=source_id,
        document_sha256=document,
        page=page,
        frame=frame,
        lines=[
            PageLine(
                text=row[2],
                x0=row[4],
                y0=row[5],
                x1=row[6],
                y1=row[7],
                hidden=_reasons(row[8]),
            )
            for row in lines[:PAGE_LINES_MAX]
        ],
    )
    truncated = len(lines) > PAGE_LINES_MAX or any(row[3] for row in lines)
    return PageRead(body=body, truncated=truncated)


def _reasons(mark: object) -> list[HiddenReason]:
    """A line's stored mark (N27) as the reasons the page read names: none for
    a line with nothing to note, or a row written before there were marks. A
    mark this build does not name is the server's own row failing."""
    if mark is None:
        return []
    reasons = str(mark).split(",")
    if not all(reason in HIDDEN_REASONS for reason in reasons):
        raise Refusal(RefusalCode.SOURCE_IDENTITY_INVALID)
    return [cast(HiddenReason, reason) for reason in reasons]


def _rows(conn: StoreConnection, ids: tuple[UUID, UUID, UUID, int]) -> list[Any]:
    (case_id, run_id, source_id, page) = ids
    params = (case_id, run_id, source_id, QUOTE_CHARS, QUOTE_CHARS, page)
    try:
        rows = conn.execute(_PAGE_QUERY, (*params, PAGE_LINES_MAX + 1)).fetchall()
    except psycopg.Error:
        rows = None
    if rows is None:  # raised here, so psycopg's statement is not chained
        raise Refusal(RefusalCode.PAGE_NOT_AVAILABLE)
    return rows


def _identity(stored: str) -> tuple[str, str, dict[str, Any]]:
    """The stored identity's name, version and configuration."""
    parsed: Any = None
    try:
        parsed = json.loads(stored)
    except ValueError:
        parsed = None
    if (
        not isinstance(parsed, dict)
        or not isinstance(parsed.get("name"), str)
        or not isinstance(parsed.get("version"), str)
        or not isinstance(parsed.get("config"), dict)
    ):
        raise Refusal(RefusalCode.SOURCE_IDENTITY_INVALID)
    return parsed["name"], parsed["version"], parsed["config"]


def _document(blobs: BlobStore, digest: str) -> bytes:
    """The pinned document, proven to hash to its pin by `BlobStore.get`."""
    data: bytes | None
    try:
        data = blobs.get(digest)
    except Refusal:
        data = None
    if data is None:
        raise Refusal(RefusalCode.PAGE_NOT_AVAILABLE)
    return data


# How many page crops the process remembers. A crop is four floats derived
# from immutable inputs -- a digest-addressed document and a page number -- so
# it is the same answer however often it is asked for, and the ceiling is what
# stops a reader paging through many large documents from holding them all.
FRAME_CACHE_SIZE = 256
# `(document digest, page)` to that page's crop, most recently read last, or
# `None` for a page the child said the document does not have (EV-7). Only
# what the child answered: a refusal can be a deadline the load made, and a
# transient failure is not a fact about a document (AS-5).
_FRAMES: OrderedDict[tuple[str, int], tuple[float, float, float, float] | None] = (
    OrderedDict()
)
# How many frame children run at once in this process (EV-7). Each is an
# interpreter reading a document up to the admission ceiling -- measured at
# about 250 MiB resident and a second of CPU for an 18 MB PDF -- and a READER
# could ask for as many distinct pages at once as the server has threads,
# each starting its own. A read waits for a slot within its own deadline, the
# bound its child would have run under, and is refused if none frees.
FRAME_CHILDREN = 2
_CHILDREN = threading.BoundedSemaphore(FRAME_CHILDREN)
# One of the two global slots, never both (N38): nothing otherwise kept a
# single READER's own concurrent page requests from taking every slot this
# process has, so a different reader's read waited out its own deadline for
# a resource one actor was hoarding. A personal semaphore is acquired first
# and released last, so a second concurrent read from the same actor waits
# on its own share rather than ever contending for the slot a different
# actor needs -- the same idea as `ACTOR_STREAM_LIMIT` beside `STREAM_LIMIT`
# in `caos/api/stream.py`, adapted to a wait rather than an instant refusal.
ACTOR_FRAME_CHILDREN = 1
_ACTOR_CHILDREN_LOCK = threading.Lock()
_ACTOR_CHILDREN: dict[UUID, threading.BoundedSemaphore] = {}


def _actor_slot(actor_id: UUID) -> threading.BoundedSemaphore:
    with _ACTOR_CHILDREN_LOCK:
        slot = _ACTOR_CHILDREN.get(actor_id)
        if slot is None:
            slot = threading.BoundedSemaphore(ACTOR_FRAME_CHILDREN)
            _ACTOR_CHILDREN[actor_id] = slot
        return slot


# Sync routes run in the threadpool, so two readers share this dictionary. The
# lock covers the read-then-reorder and the write-then-evict, which are not one
# operation: without it a key evicted between a `get` and its `move_to_end`
# raises `KeyError` past every typed refusal this module states. The child runs
# outside the lock, so one slow extraction never blocks another page's read.
_FRAMES_LOCK = threading.Lock()


def _remembered(
    key: tuple[str, int],
) -> tuple[bool, tuple[float, float, float, float] | None]:
    """Whether the child already answered for `key`, and what."""
    with _FRAMES_LOCK:
        if key not in _FRAMES:
            return False, None
        _FRAMES.move_to_end(key)
        return True, _FRAMES[key]


def _remember(
    key: tuple[str, int], frame: tuple[float, float, float, float] | None
) -> None:
    with _FRAMES_LOCK:
        _FRAMES[key] = frame
        _FRAMES.move_to_end(key)
        while len(_FRAMES) > FRAME_CACHE_SIZE:
            _FRAMES.popitem(last=False)


@dataclass(frozen=True, slots=True)
class _Crop:
    """One document's bytes with the digest they are addressed by, the
    bounds a crop read of them runs under, and who is asking.

    `actor_id` is who a shared `FRAME_CHILDREN` slot is charged to (N38); a
    caller that does not track one leaves it `None` and shares nothing.
    """

    document_sha256: str
    data: bytes
    limits: AdmissionLimits
    deadline: float
    actor_id: UUID | None = None


def _page_crop(crop: _Crop, page: int) -> tuple[float, float, float, float] | None:
    """Page `page`'s crop in pdfminer's layout space, from the §47 child or
    from the cache of what that child already answered for these bytes.

    Every evidence-page read of a PDF source starts an interpreter that walks
    the page tree with a 60 s budget, at READER standing (AS-5). The crop is a
    pure function of the pinned document and the page, and `BlobStore.get` has
    already proven the bytes hash to `document_sha256`, so the digest and the
    page are the whole key -- and a page the document does not have is as
    much a fact of it as a crop (EV-7).

    The child runs in one of `FRAME_CHILDREN` slots, waited for within the
    read's deadline; the cache is asked again once a slot is held, because
    the reader holding it before may have been answering the same page. When
    `crop.actor_id` is set, its own `ACTOR_FRAME_CHILDREN` share is waited for
    first (N38), so at most that many of this actor's reads ever contend for
    a global slot at once; `None` (a caller that does not track one) waits on
    the global slots alone, exactly as before.
    """
    key = (crop.document_sha256, page)
    known, frame = _remembered(key)
    if known:
        return frame
    actor_slot = _actor_slot(crop.actor_id) if crop.actor_id is not None else None
    wait = min(max(0.0, crop.deadline - time.monotonic()), crop.limits.max_seconds)
    if actor_slot is not None and not actor_slot.acquire(timeout=wait):
        return None
    try:
        wait = min(max(0.0, crop.deadline - time.monotonic()), crop.limits.max_seconds)
        if not _CHILDREN.acquire(timeout=wait):
            return None
        try:
            known, frame = _remembered(key)
            return frame if known else _child_crop(crop, page)
        finally:
            _CHILDREN.release()
    finally:
        if actor_slot is not None:
            actor_slot.release()


def _child_crop(crop: _Crop, page: int) -> tuple[float, float, float, float] | None:
    """The §47 child's answer for one page, remembered when it is one."""
    # Imported here: plain-text pages should not pay for pdfminer.
    from caos.evidence.pdf import page_frame

    code: RefusalCode | None = None
    try:
        frame = page_frame(crop.data, page, limits=crop.limits, deadline=crop.deadline)
    except Refusal as refusal:
        code = refusal.code
    if code is None:
        _remember((crop.document_sha256, page), frame)
        return frame
    if code is RefusalCode.PAGE_NOT_AVAILABLE:
        # The child's `null`: no such page, or one that clips to nothing.
        _remember((crop.document_sha256, page), None)
    return None


def _frame(
    name: str,
    version: str,
    config: dict[str, Any],
    crop: _Crop,
    page: int,
) -> FrameView:
    """The frame the stored identity's rectangles are drawn in (decision 8)."""
    if name == "caos.plain-text":
        return _text_frame(config, crop.data, page)
    pdf_v1 = name == "caos.pdfminer" and version == "1"
    pdf_v2 = (
        name == "caos.pdfminer"
        and version in PDF_CROP_VERSIONS
        and config.get("coordinates") == PDF_V2_COORDINATES
    )
    if not (pdf_v1 or pdf_v2):
        raise Refusal(RefusalCode.SOURCE_IDENTITY_INVALID)
    box = _page_crop(crop, page)
    if box is None:
        raise Refusal(RefusalCode.PAGE_NOT_AVAILABLE)
    (left, bottom, right, top) = box
    if pdf_v2:
        return _view((0.0, 0.0, right - left, top - bottom), "down")
    return _view(box, "up")


def _text_frame(config: dict[str, Any], data: bytes, page: int) -> FrameView:
    """A fixed-pitch page from its recorded cells: the rows and margins its
    configuration declares, as wide as its widest line."""
    cell_width = _positive(config.get("cell_width"))
    cell_height = _positive(config.get("cell_height"))
    margin = _positive(config.get("margin"), zero=True)
    rows = config.get("lines_per_page")
    if (
        type(rows) is not int
        or rows < 1
        or config.get("coordinates", TEXT_COORDINATES) != TEXT_COORDINATES
    ):
        raise Refusal(RefusalCode.SOURCE_IDENTITY_INVALID)
    text: str | None
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        text = None
    lines = [] if text is None else text.splitlines()[(page - 1) * rows : page * rows]
    if not lines:
        raise Refusal(RefusalCode.PAGE_NOT_AVAILABLE)
    width = 2 * margin + cell_width * max(len(line) for line in lines)
    return _view((0.0, 0.0, width, 2 * margin + cell_height * rows), "down")


def _positive(value: object, *, zero: bool = False) -> float:
    if type(value) not in (int, float) or not math.isfinite(value):  # type: ignore[arg-type]
        raise Refusal(RefusalCode.SOURCE_IDENTITY_INVALID)
    number = float(value)  # type: ignore[arg-type]
    if number < 0 or (number == 0 and not zero):
        raise Refusal(RefusalCode.SOURCE_IDENTITY_INVALID)
    return number


def _view(
    frame: tuple[float, float, float, float], y_axis: Literal["down", "up"]
) -> FrameView:
    (x0, y0, x1, y1) = frame
    return FrameView(x0=x0, y0=y0, x1=x1, y1=y1, y_axis=y_axis)

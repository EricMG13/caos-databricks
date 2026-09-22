"""One page of a run's pinned live source, as its text layer and frame.

Phase 4 Task 4.4 decisions 7 and 8. A page is served only from a source that is
live now and a member of the run's pinned source-set version with the document
and extraction identity the pin captured -- the `_RUN_BLOCKS_QUERY` join of
`caos/evidence/read.py` (invariant 1: withdrawal is checked at every use).
Its lines are the token index citations were anchored in, grouped by
`(region_id, line_id)`: the joined words and their union rectangle, in the
coordinates the tokens are stored in (invariant 11). No renderer draws the page.

The frame says what those coordinates are, read from the digest-verified
document under the stored extractor identity: a `caos.pdfminer` v2 row's
rectangles are crop-relative with y down (§44.3), a v1 row's are pdfminer's
layout space with y up (§44.4), and a `caos.plain-text` row's are the cells of
its recorded fixed pitch. PDF frames come from the §47 child.

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
import time
from dataclasses import dataclass
from typing import Any, Literal
from uuid import UUID

import psycopg

from caos.api.wire import (
    PAGE_LINES_MAX,
    PAGE_MAX,
    QUOTE_CHARS,
    FrameView,
    PageBody,
    PageLine,
)
from caos.blobs import BlobStore
from caos.evidence.extract import DEFAULT_LIMITS, AdmissionLimits
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
    " line.x0, line.y0, line.x1, line.y1"
    " FROM member LEFT JOIN LATERAL (SELECT"
    " string_agg(t.text, ' ' ORDER BY t.token_id) AS text,"
    " min(t.x0) AS x0, min(t.y0) AS y0, max(t.x1) AS x1, max(t.y1) AS y1,"
    " min(t.token_id) AS first FROM source_tokens AS t"
    " WHERE t.source_id = member.source_id AND t.page = %s"
    " GROUP BY t.region_id, t.line_id ORDER BY first LIMIT %s) AS line ON true"
    " ORDER BY line.first"
)
PDF_V2_COORDINATES = "crop-top-left-rotated-pt"
TEXT_COORDINATES = "cell-top-left-pt"


@dataclass(frozen=True, slots=True)
class PageRead:
    """The page's body, and whether its text layer was cut to its bounds --
    more than `PAGE_LINES_MAX` lines, or a line longer than `QUOTE_CHARS`."""

    body: PageBody
    truncated: bool


def read_page(  # noqa: PLR0913 -- the store, the blobs and one page's four ids
    conn: StoreConnection,
    blobs: BlobStore,
    *,
    case_id: UUID,
    run_id: UUID,
    source_id: UUID,
    page: int,
    limits: AdmissionLimits = DEFAULT_LIMITS,
) -> PageRead:
    """Page `page` of `source_id` as the run `run_id` of `case_id` pinned it,
    or `PAGE_NOT_AVAILABLE`. Authorisation is the caller's, and must be read
    before this is called: this ends the caller's read unit once the page's
    rows are fetched, before the document is read or its frame extracted."""
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
    frame = _frame(name, version, config, data, page, limits, deadline)
    lines = [row for row in rows if row[2] is not None]
    body = PageBody(
        case_id=case_id,
        run_id=run_id,
        source_id=source_id,
        document_sha256=document,
        page=page,
        frame=frame,
        lines=[
            PageLine(text=row[2], x0=row[4], y0=row[5], x1=row[6], y1=row[7])
            for row in lines[:PAGE_LINES_MAX]
        ],
    )
    truncated = len(lines) > PAGE_LINES_MAX or any(row[3] for row in lines)
    return PageRead(body=body, truncated=truncated)


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


def _frame(  # noqa: PLR0913 -- one identity, one document, one page and its bounds
    name: str,
    version: str,
    config: dict[str, Any],
    data: bytes,
    page: int,
    limits: AdmissionLimits,
    deadline: float,
) -> FrameView:
    """The frame the stored identity's rectangles are drawn in (decision 8)."""
    if name == "caos.plain-text":
        return _text_frame(config, data, page)
    pdf_v1 = name == "caos.pdfminer" and version == "1"
    pdf_v2 = (
        name == "caos.pdfminer"
        and version == "2"
        and config.get("coordinates") == PDF_V2_COORDINATES
    )
    if not (pdf_v1 or pdf_v2):
        raise Refusal(RefusalCode.SOURCE_IDENTITY_INVALID)
    # Imported here: plain-text pages should not pay for pdfminer.
    from caos.evidence.pdf import page_frame

    crop: tuple[float, float, float, float] | None
    try:
        crop = page_frame(data, page, limits=limits, deadline=deadline)
    except Refusal:
        crop = None
    if crop is None:
        raise Refusal(RefusalCode.PAGE_NOT_AVAILABLE)
    (left, bottom, right, top) = crop
    if pdf_v2:
        return _view((0.0, 0.0, right - left, top - bottom), "down")
    return _view(crop, "up")


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

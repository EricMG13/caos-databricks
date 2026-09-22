"""The evidence page read (Phase 4 Task 4.4, slice 4.4c; decision 7).

`GET /api/v1/cases/{case_id}/runs/{run_id}/sources/{source_id}/pages/{page}`
serves one page's text layer and frame (`caos/evidence/page.py`). Identity is
checked first, then READER standing on the case -- an unknown, malformed,
unauthorised or revoked case is one private `CASE_NOT_FOUND` -- then that the
run is the case's (`RUN_NOT_FOUND` otherwise). Everything about the source and
the page, including a page outside 1..`PAGE_MAX` and a malformed source id, is
the same 404 `PAGE_NOT_AVAILABLE` with no text. Not a section document, so
no chrome; never cached. Standing and the page's rows are read in one read
unit, which `read_page` ends before the document is read and its frame
extracted, so no transaction is held across the extraction.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Response

from caos.api.deps import (
    IDENTITY_FIRST,
    Blobs,
    Caller,
    CasePath,
    RunPath,
    Store,
    parse_uuid,
    readable,
)
from caos.api.wire import PAGE_MAX, PageDocument, SectionNote
from caos.evidence import page as page_read
from caos.refusals import Refusal, RefusalCode
from caos.store.members import Standing

# Standing, `now()` and the run's ownership in one row; then the page itself.
IO_BUDGET = 1 + page_read.IO_BUDGET

router = APIRouter()


@router.get(
    "/api/v1/cases/{case_id}/runs/{run_id}/sources/{source_id}/pages/{page}",
    response_model=PageDocument,
    dependencies=[IDENTITY_FIRST],
)
def read_evidence_page(  # noqa: PLR0913 -- identity, three ids and a page, stores
    actor: Caller,
    case_id: CasePath,
    run_id: RunPath,
    source_id: str,
    page: str,
    conn: Store,
    blobs: Blobs,
    response: Response,
) -> PageDocument:
    """The order of the dependencies is load-bearing: identity, the path, then
    the store. The source and page are read only once the run is visible.

    The membership join is folded into the one row that also carries the
    clock and the run's ownership, so visibility costs no round trip of its
    own; the rule applied to it is `deps.readable`'s."""
    row = conn.execute(
        "SELECT m.standing, now(),"
        " EXISTS (SELECT 1 FROM runs r WHERE r.run_id = %s AND r.case_id = c.case_id)"
        " FROM cases c LEFT JOIN case_members m ON m.case_id = c.case_id"
        " AND m.user_id = %s AND m.revoked_at IS NULL WHERE c.case_id = %s",
        (run_id, actor.user_id, case_id),
    ).fetchone()
    if row is None:  # no such case: the same private answer as no standing
        raise Refusal(RefusalCode.CASE_NOT_FOUND)
    readable(None if row[0] is None else Standing(row[0]))
    if not row[2]:
        raise Refusal(RefusalCode.RUN_NOT_FOUND)
    read = page_read.read_page(
        conn,
        blobs,
        case_id=case_id,
        run_id=run_id,
        source_id=_source(source_id),
        page=_page(page),
    )
    response.headers["cache-control"] = "no-store"
    return PageDocument(
        body=read.body,
        observed_at=row[1],
        status="partial" if read.truncated else "complete",
        notes=[SectionNote.LIST_TRUNCATED] if read.truncated else [],
    )


def _source(value: str) -> UUID:
    return parse_uuid(value, RefusalCode.PAGE_NOT_AVAILABLE)


def _page(value: str) -> int:
    """A page number as a reader writes it: no sign, no padding, 1..PAGE_MAX."""
    digits = value.isascii() and value.isdigit() and not value.startswith("0")
    if not digits or len(value) > len(str(PAGE_MAX)) or int(value) > PAGE_MAX:
        raise Refusal(RefusalCode.PAGE_NOT_AVAILABLE)
    return int(value)

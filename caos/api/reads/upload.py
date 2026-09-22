"""The Upload section read (Task 4.1, slice 4.1c).

Every source of one case, admitted or withdrawn -- withdrawal read live, never
from a snapshot -- with the set versions each belongs to. The case is the
authorisation resource: unknown, unauthorised, revoked and malformed are one
private 404 `CASE_NOT_FOUND`, because any difference between them is the
disclosure (decision 1).
"""

from __future__ import annotations

from fastapi import APIRouter

from caos.api.commands.availability import upload_actions
from caos.api.deps import IDENTITY_FIRST, Caller, CasePath, Store, VisibleCase
from caos.api.wire import (
    SOURCES_MAX,
    Chrome,
    SectionNote,
    ServedRole,
    SetVersion,
    SourceRow,
    Subject,
    UploadBody,
    UploadDocument,
)
from caos.refusals import Refusal, RefusalCode
from caos.store.source_sets import case_sources

# Standing, the case title with the store's `now()`, then `case_sources`'s set
# versions and sources: four, whatever the number of sources or versions.
# Measured in `tests/test_directory_upload_sections.py`.
IO_BUDGET = 4

router = APIRouter()


@router.get(
    "/api/v1/cases/{case_id}/upload",
    response_model=UploadDocument,
    dependencies=[IDENTITY_FIRST],
)
def read_upload(
    actor: Caller, case_id: CasePath, standing: VisibleCase, conn: Store
) -> UploadDocument:
    """The order of the parameters is load-bearing: identity, then the path
    and the caller's visibility of it, then the store."""
    row = conn.execute(
        "SELECT title, now() FROM cases WHERE case_id = %s", (case_id,)
    ).fetchone()
    if row is None:  # standing on a case row that is gone: still not readable
        raise Refusal(RefusalCode.CASE_NOT_FOUND)
    title, observed_at = row
    listed = case_sources(conn, case_id=case_id, limit=SOURCES_MAX)
    return UploadDocument(
        chrome=Chrome(
            subject=Subject(case_id=case_id, title=title),
            served_role=ServedRole(global_role=actor.role, standing=standing),
            actions=upload_actions(
                actor.role,
                standing,
                sum(1 for source in listed.sources if source.withdrawn_at is None),
            ),
        ),
        body=UploadBody(
            case_id=case_id,
            sources=[
                SourceRow(
                    source_id=source.source_id,
                    filename=source.filename,
                    document_sha256=source.document_sha256,
                    admitted_at=source.admitted_at,
                    withdrawn_at=source.withdrawn_at,
                    extractor_identity=source.extractor_identity,
                    set_versions=list(source.set_versions),
                )
                for source in listed.sources
            ],
            set_versions=[
                SetVersion(
                    version=version.version,
                    fingerprint=version.fingerprint,
                    member_count=version.member_count,
                )
                for version in listed.set_versions
            ],
        ),
        observed_at=observed_at,
        observed_empty=not listed.sources,
        status="partial" if listed.truncated else "complete",
        notes=[SectionNote.LIST_TRUNCATED] if listed.truncated else [],
    )

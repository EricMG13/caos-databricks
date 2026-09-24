"""The deliverable's two downloads (N4; `docs/rebuild/next.md`).

`GET .../revisions/{revision_id}/render` answers the frozen or filed
revision's rendered page, and `GET .../revisions/{revision_id}/package`
answers a filed revision's audit package -- both produced only by the test
suite until this slice, while a filing receipt already pinned the renderer's
digest (`caos/deliverable/filing.py` `renderer_sha256`).

Neither derives from live state. The render reads the revision's own stored
bytes (`caos.deliverable.revisions.read_revision`) once its freeze is proven
by the row `caos/deliverable/filing.py` `freeze_in` wrote; the package reads
the filed record's own bytes through `caos.deliverable.receipts
.read_filed_receipt`, which proves the whole filing chain before this module
ever sees a byte. `caos.deliverable.render.render` stays the pure function it
always was -- nothing here re-derives its input from a source, a bundle or the
clock.

Standing is the floor Report and Committee already read at
(`caos.api.deps.VisibleCase`, `Standing.READER`): a case member reads either
download of a revision they could already read through those sections, and a
stranger or a revoked member gets the same private `CASE_NOT_FOUND` every
other section serves them.
"""

from __future__ import annotations

import json
from uuid import UUID

from fastapi import APIRouter, Response

from caos.api.deps import (
    IDENTITY_FIRST,
    Blobs,
    CasePath,
    RevisionPath,
    Store,
    VisibleCase,
)
from caos.blobs import BlobStore
from caos.deliverable.package import build_package
from caos.deliverable.receipts import read_filed_receipt
from caos.deliverable.render import RenderRefused, render
from caos.deliverable.revisions import read_revision
from caos.refusals import Refusal, RefusalCode
from caos.store import StoreConnection

# One case standing (`VisibleCase`), the revision's own digest, the frozen row
# that must bind it, and `read_revision`'s own read of the first row again --
# it re-reads rather than trusting the digest this module already holds,
# because its own cross-check (the stored payload names this exact case, run
# and revision) is not this module's to skip. Measured in
# `tests/test_deliverable_reads.py`.
RENDER_IO = 4
# The same standing check, the revision's run (so `read_filed_receipt` is
# asked what it is written to answer, not left to derive it), and that read's
# own six: the filed join, its signatures, the audit trail read twice -- once
# directly and once inside `verify_chain` -- the payload digests it rebuilds,
# and the chain's current head. Measured in `tests/test_deliverable_reads.py`.
PACKAGE_IO = 8
IO_BUDGET = {"render": RENDER_IO, "package": PACKAGE_IO}
# The render downloads one blob: the revision's own payload, inside
# `read_revision`. The package downloads two: the receipt `read_filed_receipt`
# proves, and the same payload digest again to build `payload.json` byte for
# byte -- the request's blob store remembers what it already verified
# (`caos.api.deps.request_blobs`, ED-7), so asking for that digest a second
# time costs no second download.
BLOB_BUDGET = {"render": 1, "package": 2}

router = APIRouter()


@router.get(
    "/api/v1/cases/{case_id}/revisions/{revision_id}/render",
    dependencies=[IDENTITY_FIRST],
)
def read_deliverable_render(
    case_id: CasePath,
    revision_id: RevisionPath,
    _standing: VisibleCase,
    conn: Store,
    blobs: Blobs,
) -> Response:
    """The frozen or filed revision's page, byte for byte what `render`
    produced from its own stored payload -- the "PENDING APPROVAL" marking
    included, exactly as that function writes it. Refuses
    `DELIVERABLE_NOT_FROZEN` before an unfrozen revision's draft ever reaches
    `render`, and a render refusal's own code otherwise.
    """
    html = render_revision(conn, blobs, case_id=case_id, revision_id=revision_id)
    return Response(content=html, media_type="text/html; charset=utf-8")


@router.get(
    "/api/v1/cases/{case_id}/revisions/{revision_id}/package",
    dependencies=[IDENTITY_FIRST],
)
def read_deliverable_package(
    case_id: CasePath,
    revision_id: RevisionPath,
    _standing: VisibleCase,
    conn: Store,
    blobs: Blobs,
) -> Response:
    """A filed revision's audit package, built fresh from its own filed bytes
    -- the same archive `caos.deliverable.package.verify_package` verifies.
    An unfiled revision, frozen or not, is `read_filed_receipt`'s own
    `DELIVERABLE_NOT_FOUND`: the closest existing code, since no receipt row
    for it exists to name any other.
    """
    archive = package_revision(conn, blobs, case_id=case_id, revision_id=revision_id)
    filename = f"deliverable-{revision_id}.zip"
    return Response(
        content=archive,
        media_type="application/zip",
        headers={"content-disposition": f'attachment; filename="{filename}"'},
    )


def render_revision(
    conn: StoreConnection, blobs: BlobStore, *, case_id: UUID, revision_id: UUID
) -> bytes:
    """The frozen or filed revision's rendered page, from its stored bytes."""
    digest = _digest(conn, case_id, revision_id)
    _frozen(conn, case_id, revision_id, digest)
    payload = read_revision(conn, blobs, case_id=case_id, revision_id=revision_id)
    return _rendered(payload)


def package_revision(
    conn: StoreConnection, blobs: BlobStore, *, case_id: UUID, revision_id: UUID
) -> bytes:
    """A filed revision's audit package, from the filed record's own bytes."""
    row = conn.execute(
        "SELECT run_id FROM deliverable_revisions WHERE case_id=%s AND revision_id=%s",
        (case_id, str(revision_id)),
    ).fetchone()
    if row is None:
        raise Refusal(RefusalCode.DELIVERABLE_NOT_FOUND)
    run_id = UUID(str(row[0]))
    receipt = read_filed_receipt(
        conn, blobs, case_id=case_id, run_id=run_id, revision_id=revision_id
    )
    digest = str(json.loads(receipt)["payload_sha256"])
    data = blobs.get(digest)
    export = _rendered(json.loads(data))
    return build_package(data, receipt, export)


def _digest(conn: StoreConnection, case_id: UUID, revision_id: UUID) -> str:
    row = conn.execute(
        "SELECT payload_sha256 FROM deliverable_revisions"
        " WHERE case_id=%s AND revision_id=%s",
        (case_id, str(revision_id)),
    ).fetchone()
    if row is None:
        raise Refusal(RefusalCode.DELIVERABLE_NOT_FOUND)
    return str(row[0])


def _frozen(
    conn: StoreConnection, case_id: UUID, revision_id: UUID, digest: str
) -> None:
    row = conn.execute(
        "SELECT payload_sha256 FROM deliverable_publications"
        " WHERE case_id=%s AND revision_id=%s",
        (case_id, str(revision_id)),
    ).fetchone()
    if row is None:
        raise Refusal(RefusalCode.DELIVERABLE_NOT_FROZEN)
    if str(row[0]) != digest:
        raise Refusal(RefusalCode.DELIVERABLE_PAYLOAD_INVALID)


def _rendered(payload: dict[str, object]) -> bytes:
    try:
        return render(payload)
    except RenderRefused as refused:
        raise Refusal(RefusalCode(refused.code)) from None

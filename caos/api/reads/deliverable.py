"""The deliverable's two downloads (N4; `docs/rebuild/next.md`).

`GET .../revisions/{revision_id}/render` answers the frozen or filed
revision's rendered page, and `GET .../revisions/{revision_id}/package`
answers a filed revision's audit package -- both produced only by the test
suite until this slice, while a filing receipt already pinned the renderer's
digest (`caos/deliverable/filing.py` `renderer_sha256`).

Each is proven exactly as Committee proves the same revision (W2), by the one
proof both share (`caos.api.reads.reports.proven_revision`): the publication,
its signatures and the audit provenance of every act; then, filed, the receipt
`caos.deliverable.receipts.read_filed_receipt` proves and the revision's own
stored bytes, or, frozen, the payload re-derived from the run as it stands, so
a source withdrawn after the freeze refuses the render as it refuses
Committee. The render only looked for the publication row, and served a
withdrawn source's quotes after Report and Committee refused them.
`caos.deliverable.render.render` stays the pure function it always was.

Standing is the floor Report and Committee already read at
(`caos.api.deps.readable`, `Standing.READER`), read inside the same read unit
as the proof: a case member reads either download of a revision they could
already read through those sections, and a stranger or a revoked member gets
the same private `CASE_NOT_FOUND` every other section serves them.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Response

from caos.api.deps import (
    IDENTITY_FIRST,
    Blobs,
    Caller,
    CasePath,
    Methodology,
    RevisionPath,
    Store,
    readable,
)
from caos.api.reads.reports import ProvenRevision, proven_filing, proven_revision
from caos.blobs import BlobStore
from caos.deliverable.package import build_package
from caos.deliverable.render import RenderRefused, render
from caos.methodology.bundle import Bundle
from caos.refusals import Refusal, RefusalCode
from caos.store import StoreConnection
from caos.store.members import standing_of
from caos.store.outcomes import execution_reads

# W2: each download runs the proof Committee runs for the same revision
# (`caos.api.reads.reports.proven_revision`), in one read unit, so each costs
# what that proof costs. A filed revision: the unit's isolation check, the
# caller's standing, the revision's run and digest, `_publication`'s seven
# (the publication, its signatures, the trail, the signer's and freezer's
# receipts, the chain and its head), `read_filed_receipt`'s own eight and
# `read_revision`'s one. Measured in `tests/test_deliverable_reads.py`.
RENDER_IO = 19
PACKAGE_IO = 19
# A frozen, unfiled revision is re-derived rather than read back
# (`prove_revision`), as Committee's "frozen" proof re-derives it.
RENDER_FROZEN_IO = 50
IO_BUDGET = {
    "render": RENDER_IO,
    "render_frozen": RENDER_FROZEN_IO,
    "package": PACKAGE_IO,
}
# A filed revision downloads two blobs, the receipt `read_filed_receipt`
# proves and the payload it names; asking for that payload again, to render
# or to pack it, costs nothing -- the request's blob store remembers what it
# already verified (`caos.api.deps.request_blobs`, ED-7). A frozen one pays
# `prove_revision`'s seven, as Committee's "frozen" does.
BLOB_BUDGET = {"render": 2, "render_frozen": 7, "package": 2}

router = APIRouter()


@dataclass(frozen=True, slots=True)
class Stores:
    """The request's connection, blobs and bundle a download is proven with."""

    conn: StoreConnection
    blobs: BlobStore
    bundle: Bundle


def _stores(conn: Store, blobs: Blobs, bundle: Methodology) -> Stores:
    """Declared after the caller and the path on each route, so the connection
    opens only for a request that names a well-formed revision."""
    return Stores(conn, blobs, bundle)


@router.get(
    "/api/v1/cases/{case_id}/revisions/{revision_id}/render",
    dependencies=[IDENTITY_FIRST],
)
def read_deliverable_render(
    actor: Caller,
    case_id: CasePath,
    revision_id: RevisionPath,
    stores: Annotated[Stores, Depends(_stores)],
) -> Response:
    """The frozen or filed revision's page, byte for byte what `render`
    produced from its own proven payload -- the "PENDING APPROVAL" marking
    included, exactly as that function writes it. Refuses whatever Committee
    refuses for the same revision (W2): `DELIVERABLE_NOT_FROZEN` before an
    unfrozen revision's draft ever reaches `render`, and a render refusal's
    own code otherwise.
    """
    html = render_revision(Selection(stores, actor.user_id, case_id, revision_id))
    return Response(content=html, media_type="text/html; charset=utf-8")


@router.get(
    "/api/v1/cases/{case_id}/revisions/{revision_id}/package",
    dependencies=[IDENTITY_FIRST],
)
def read_deliverable_package(
    actor: Caller,
    case_id: CasePath,
    revision_id: RevisionPath,
    stores: Annotated[Stores, Depends(_stores)],
) -> Response:
    """A filed revision's audit package, built from its own filed bytes once
    Committee's proof of the filing holds -- the same archive
    `caos.deliverable.package.verify_package` verifies. An unfiled revision,
    frozen or not, is `DELIVERABLE_NOT_FOUND`: the closest existing code, since
    no filing of it exists to name any other.
    """
    archive = package_revision(Selection(stores, actor.user_id, case_id, revision_id))
    filename = f"deliverable-{revision_id}.zip"
    return Response(
        content=archive,
        media_type="application/zip",
        headers={"content-disposition": f'attachment; filename="{filename}"'},
    )


@dataclass(frozen=True, slots=True)
class Selection:
    """What a download names -- a case's revision, asked for by a caller --
    and the request's stores it is proven with."""

    stores: Stores
    user_id: UUID
    case_id: UUID
    revision_id: UUID


def render_revision(selection: Selection) -> bytes:
    """The frozen or filed revision's rendered page, from its proven payload."""
    _publication, payload = _proven(selection, proven_revision)
    return _rendered(payload)


def package_revision(selection: Selection) -> bytes:
    """A filed revision's audit package, from the filed record's own bytes."""
    publication, payload = _proven(selection, proven_filing)
    receipt = json.dumps(
        publication["receipt"], sort_keys=True, separators=(",", ":")
    ).encode()
    data = selection.stores.blobs.get(publication["receipt"]["payload_sha256"])
    return build_package(data, receipt, _rendered(payload))


def _proven(
    selection: Selection,
    prove: Callable[[ProvenRevision], tuple[dict[str, Any], dict[str, Any]]],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """The revision proven by `prove` in one read unit, as Committee proves it:
    the caller's standing read inside the unit, then the revision's own run
    and digest, then the proof."""
    conn = selection.stores.conn
    with execution_reads(conn):
        user_id = selection.user_id
        readable(standing_of(conn, case_id=selection.case_id, user_id=user_id))
        row = conn.execute(
            "SELECT run_id,payload_sha256 FROM deliverable_revisions"
            " WHERE case_id=%s AND revision_id=%s",
            (selection.case_id, str(selection.revision_id)),
        ).fetchone()
        if row is None:
            raise Refusal(RefusalCode.DELIVERABLE_NOT_FOUND)
        return prove(
            ProvenRevision(
                conn,
                selection.stores.blobs,
                selection.stores.bundle,
                selection.case_id,
                UUID(str(row[0])),
                selection.revision_id,
                str(row[1]),
            )
        )


def _rendered(payload: dict[str, object]) -> bytes:
    try:
        return render(payload)
    except RenderRefused as refused:
        raise Refusal(RefusalCode(refused.code)) from None

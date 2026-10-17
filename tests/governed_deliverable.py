"""The deliverable's governed writes, as a test calls them.

Production drives each write through an API command (`caos/api/commands/
deliverable.py`), which runs the unit's `*_in` function inside `governed` and
its audit action. These compose the same `*_in` functions under the same
`governed_write` directly, so a test can sign, freeze, file or save without an
HTTP request; they are here, not in `caos/deliverable/`, because nothing in
production calls them (N114, SI-3).
"""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

from caos.blobs import BlobStore
from caos.deliverable.canonical import Revision
from caos.deliverable.filing import (
    Receipt,
    file_deliverable_in,
    filing_payload,
    freeze_in,
    persist_receipt,
    sign_opinion_in,
)
from caos.deliverable.revisions import save_revision_in
from caos.methodology.bundle import Bundle
from caos.store import StoreConnection
from caos.store.audit import GovernedAction, governed_write
from caos.store.members import Standing


def sign_opinion(
    conn: StoreConnection, *, case_id: UUID, actor_id: UUID, revision_id: UUID
) -> None:
    """Sign the stored digest; a frozen revision takes no further signature."""
    payload = {"revision_id": str(revision_id)}
    action = GovernedAction(
        case_id, actor_id, "OPINION_SIGNED", Standing.APPROVER, payload
    )

    def write(unit: StoreConnection) -> None:
        payload["payload_sha256"] = sign_opinion_in(
            unit, case_id=case_id, actor_id=actor_id, revision_id=revision_id
        )

    governed_write(conn, action, write)


def freeze(  # noqa: PLR0913 -- exact revision and authority for its re-proof
    conn: StoreConnection,
    blobs: BlobStore,
    bundle: Bundle,
    *,
    case_id: UUID,
    actor_id: UUID,
    revision_id: UUID,
) -> str:
    """Re-prove under the write lock, then freeze exactly the signed stored bytes."""
    payload = {"revision_id": str(revision_id)}
    action = GovernedAction(
        case_id, actor_id, "DELIVERABLE_FROZEN", Standing.APPROVER, payload
    )

    def write(unit: StoreConnection) -> None:
        payload["payload_sha256"] = freeze_in(
            unit,
            blobs,
            bundle,
            case_id=case_id,
            actor_id=actor_id,
            revision_id=revision_id,
        )

    governed_write(conn, action, write)
    return payload["payload_sha256"]


def file_deliverable(
    conn: StoreConnection,
    blobs: BlobStore,
    *,
    case_id: UUID,
    actor_id: UUID,
    revision_id: UUID,
) -> Receipt:
    """File once, independently of every signer and the freezer, naming this event."""
    payload = {"revision_id": str(revision_id)}
    action = GovernedAction(
        case_id, actor_id, "DELIVERABLE_FILED", Standing.APPROVER, payload
    )
    receipts: list[Receipt] = []

    def write(unit: StoreConnection) -> None:
        receipt = file_deliverable_in(
            unit, case_id=case_id, actor_id=actor_id, revision_id=revision_id
        )
        payload.update(filing_payload(receipt))
        receipts.append(receipt)

    def persist(unit: StoreConnection, event: str) -> None:
        receipts[0] = persist_receipt(unit, blobs, receipts[0], event)

    governed_write(conn, action, write, after_event=persist)
    return receipts[0]


def save_revision(  # noqa: PLR0913 -- authority, owner and narrative boundary
    conn: StoreConnection,
    blobs: BlobStore,
    bundle: Bundle,
    *,
    case_id: UUID,
    run_id: UUID,
    actor_id: UUID,
    narrative: object,
) -> UUID:
    """Save only proven route bytes under the case lock; callers supply no digest."""
    revision = uuid4()
    audit: dict[str, Any] = {"revision_id": str(revision), "run_id": str(run_id)}
    action = GovernedAction(case_id, actor_id, "REVISION_SAVED", Standing.WRITER, audit)

    def write(unit: StoreConnection) -> None:
        audit["payload_sha256"] = save_revision_in(
            unit,
            blobs,
            bundle,
            case_id=case_id,
            run_id=run_id,
            actor_id=actor_id,
            narrative=narrative,
            revision_id=revision,
        )

    governed_write(conn, action, write)
    return revision


def freeze_canonical(
    conn: StoreConnection,
    blobs: BlobStore,
    bundle: Bundle,
    revision: Revision,
    *,
    actor_id: UUID,
) -> str:
    """Freeze the payload the store proves now, never a caller's bytes."""
    return freeze(
        conn,
        blobs,
        bundle,
        case_id=revision.case_id,
        actor_id=actor_id,
        revision_id=UUID(revision.revision_id.value),
    )

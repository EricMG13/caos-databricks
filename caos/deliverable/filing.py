"""§57: sign, freeze and file immutable saved revisions under the case lock."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, replace
from hashlib import sha256
from pathlib import Path
from uuid import UUID

from caos.blobs import BlobStore
from caos.deliverable.revisions import prove_revision
from caos.methodology.bundle import Bundle
from caos.refusals import Refusal, RefusalCode
from caos.store import StoreConnection
from caos.store.audit import GovernedAction, governed_write
from caos.store.members import Standing


@dataclass(frozen=True, slots=True)
class Receipt:
    """Detached identity of the revision, three actors, renderer and filing event.

    `signed_by` names the latest signer, and `one_opinion_per_signer` allows
    several: a co-signer is therefore absent from the portable proof and from
    the `DELIVERABLE_FILED` payload the audit chain binds, and the offline
    verifier can prove the independence of one signer out of however many there
    were. That is FP-09, and carrying the whole sorted list here is a change to
    `FiledReceipt` in `caos/api/wire.py`, which this pass may not make.
    """

    case_id: UUID
    run_id: UUID
    revision_id: UUID
    payload_sha256: str
    signed_by: UUID
    frozen_by: UUID
    filed_by: UUID
    renderer_sha256: str
    filed_event_sha256: str


def _revision(
    conn: StoreConnection, case_id: UUID, revision_id: UUID
) -> tuple[UUID, str]:
    row = conn.execute(
        "SELECT run_id,payload_sha256 FROM deliverable_revisions"
        " WHERE case_id=%s AND revision_id=%s",
        (case_id, revision_id),
    ).fetchone()
    if row is None:
        raise Refusal(RefusalCode.DELIVERABLE_NOT_FOUND)
    return UUID(str(row[0])), str(row[1])


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


def sign_opinion_in(
    conn: StoreConnection, *, case_id: UUID, actor_id: UUID, revision_id: UUID
) -> str:
    """Sign in the caller's governed transaction; returns the bound digest.

    One signature per signer: a second is refused by the store's own
    constraint, named here so no other conflict can inherit the code, and
    `DO NOTHING` so the refusal leaves the governed transaction usable.
    """
    _, digest = _revision(conn, case_id, revision_id)
    if _frozen(conn, case_id, revision_id) is not None:
        raise Refusal(RefusalCode.DELIVERABLE_ALREADY_FROZEN)
    signed = conn.execute(
        "INSERT INTO deliverable_opinions"
        " (revision_id,case_id,payload_sha256,signed_by) VALUES (%s,%s,%s,%s)"
        " ON CONFLICT ON CONSTRAINT one_opinion_per_signer DO NOTHING",
        (str(revision_id), case_id, digest, actor_id),
    ).rowcount
    if not signed:
        raise Refusal(RefusalCode.DELIVERABLE_ALREADY_SIGNED)
    return digest


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


def freeze_in(  # noqa: PLR0913 -- exact revision and authority for its re-proof
    conn: StoreConnection,
    blobs: BlobStore,
    bundle: Bundle,
    *,
    case_id: UUID,
    actor_id: UUID,
    revision_id: UUID,
) -> str:
    """Freeze in the caller's governed transaction; returns the frozen digest.

    The independence check is here rather than in any caller's view: it is the
    case lock this runs under that makes a signer's second act refusable.
    """
    _, digest = _revision(conn, case_id, revision_id)
    if _frozen(conn, case_id, revision_id) is not None:
        raise Refusal(RefusalCode.DELIVERABLE_ALREADY_FROZEN)
    signatures = revision_signatures(conn, case_id, revision_id)
    if not signatures:
        raise Refusal(RefusalCode.DELIVERABLE_NOT_SIGNED)
    # Tamper evidence, not the review check. `sign_opinion_in` writes the digest
    # it has just read from the immutable revision row, so through this code a
    # signature always binds it; this fires only on a row altered outside it
    # (`test_freeze_refuses_a_signature_altered_outside_this_code`). What a
    # signer actually reviewed is the route's `_reviewed`, against the digest
    # the client sent -- that is the live check.
    if any(held != digest for _, held in signatures):
        raise Refusal(RefusalCode.DELIVERABLE_MOVED_SINCE_SIGNING)
    if actor_id in {who for who, _ in signatures}:
        raise Refusal(RefusalCode.APPROVER_NOT_INDEPENDENT)
    data = prove_revision(conn, blobs, bundle, case_id=case_id, revision_id=revision_id)
    if sha256(data).hexdigest() != digest:
        raise Refusal(RefusalCode.DELIVERABLE_MOVED_SINCE_SIGNING)
    conn.execute(
        "INSERT INTO deliverable_publications"
        " (revision_id,case_id,payload_sha256,frozen_by) VALUES (%s,%s,%s,%s)",
        (str(revision_id), case_id, digest, actor_id),
    )
    return digest


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


def renderer_sha256() -> str:
    """The exact renderer bytes a filing names (`docs/DECISIONS.md` §55)."""
    return sha256(Path(__file__).with_name("render.py").read_bytes()).hexdigest()


def file_deliverable_in(
    conn: StoreConnection, *, case_id: UUID, actor_id: UUID, revision_id: UUID
) -> Receipt:
    """File in the caller's governed transaction, returning the receipt whose
    `filed_event_sha256` `persist_receipt` fills once the link exists.

    Three actors, checked here: the filer is neither a signer nor the freezer,
    and the freezer is no signer either.

    **Re-proving the revision is the route's** (`caos/api/commands/deliverable.py`
    `file`), which derives it under this same governed unit before calling this.
    FP-04 asked for it here, as `freeze_in` does it; the two extra arguments
    `prove_revision` needs put this function over the argument ceiling and the
    suppression budget may only fall, so it lives at the one caller that files
    in production until `blobs` and `bundle` travel as one carrier.
    """
    run_id, digest = _revision(conn, case_id, revision_id)
    frozen = _frozen(conn, case_id, revision_id)
    if frozen is None:
        raise Refusal(RefusalCode.DELIVERABLE_NOT_FROZEN)
    frozen_by, frozen_digest = frozen
    # The two digest comparisons below are tamper evidence, for the reason
    # `freeze_in` states: the freeze and every signature were written from the
    # immutable revision row this reads, so through this code they equal it and
    # only a row altered outside it reaches either refusal
    # (`test_filing_rechecks_every_signer_and_freezer_independence`,
    # `test_filing_refuses_a_freeze_altered_outside_this_code`). The live check
    # is the route's `_reviewed`, against the digest the client sent.
    if frozen_digest != digest:
        raise Refusal(RefusalCode.DELIVERABLE_MOVED_SINCE_SIGNING)
    signatures = revision_signatures(conn, case_id, revision_id)
    if not signatures or any(
        signed_digest != digest for _, signed_digest in signatures
    ):
        raise Refusal(RefusalCode.DELIVERABLE_NOT_SIGNED)
    signers = {who for who, _ in signatures}
    if frozen_by in signers or actor_id in signers | {frozen_by}:
        raise Refusal(RefusalCode.APPROVER_NOT_INDEPENDENT)
    filed = conn.execute(
        "UPDATE deliverable_publications SET filed_by=%s,filed_at=now()"
        " WHERE case_id=%s AND revision_id=%s AND filed_by IS NULL",
        (actor_id, case_id, str(revision_id)),
    ).rowcount
    if not filed:
        raise Refusal(RefusalCode.DELIVERABLE_ALREADY_FILED)
    return Receipt(
        case_id,
        run_id,
        revision_id,
        digest,
        signatures[0][0],
        frozen_by,
        actor_id,
        renderer_sha256(),
        "",
    )


def persist_receipt(
    conn: StoreConnection, blobs: BlobStore, receipt: Receipt, event: str
) -> Receipt:
    """Store the detached receipt naming this exact filing link, in the unit
    that wrote it."""
    filed = replace(receipt, filed_event_sha256=event)
    digest = blobs.put(receipt_bytes(filed))
    conn.execute(
        "INSERT INTO deliverable_receipts"
        " (case_id,revision_id,receipt_sha256,renderer_sha256,filed_event_sha256)"
        " VALUES (%s,%s,%s,%s,%s)",
        (
            receipt.case_id,
            str(receipt.revision_id),
            digest,
            receipt.renderer_sha256,
            event,
        ),
    )
    return filed


def _wire(receipt: Receipt) -> dict[str, str]:
    """Every receipt field as the one string both the event and the bytes carry."""
    return {key: str(value) for key, value in asdict(receipt).items()}


def filing_payload(receipt: Receipt) -> dict[str, str]:
    """The event binds every receipt field except its own resulting link."""
    return {
        key: value
        for key, value in _wire(receipt).items()
        if key != "filed_event_sha256"
    }


def receipt_bytes(receipt: Receipt) -> bytes:
    """Canonical detached receipt bytes; UUIDs have one wire representation."""
    return json.dumps(
        _wire(receipt),
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def revision_signatures(
    conn: StoreConnection, case_id: UUID, revision_id: UUID
) -> list[tuple[UUID, str]]:
    rows = conn.execute(
        "SELECT signed_by,payload_sha256 FROM deliverable_opinions"
        " WHERE revision_id=%s AND case_id=%s ORDER BY signed_at DESC,signed_by",
        (str(revision_id), case_id),
    ).fetchall()
    return [(UUID(str(row[0])), str(row[1])) for row in rows]


def _frozen(
    conn: StoreConnection, case_id: UUID, revision_id: UUID
) -> tuple[UUID, str] | None:
    row = conn.execute(
        "SELECT frozen_by,payload_sha256 FROM deliverable_publications"
        " WHERE revision_id=%s AND case_id=%s",
        (str(revision_id), case_id),
    ).fetchone()
    return None if row is None else (UUID(str(row[0])), str(row[1]))

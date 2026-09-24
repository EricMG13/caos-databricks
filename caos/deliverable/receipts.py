"""Prove exact stored filing receipts; no reconstructed or latest-draft receipt."""

from __future__ import annotations

from hashlib import sha256
from uuid import UUID

from caos.blobs import BlobStore
from caos.deliverable.filing import (
    Receipt,
    filing_payload,
    receipt_bytes,
    revision_signatures,
)
from caos.refusals import Refusal, RefusalCode
from caos.store import StoreConnection
from caos.store.audit import audit_head, audit_trail, verify_chain
from caos.store.commands import payload_digests


def read_filed_receipt(
    conn: StoreConnection,
    blobs: BlobStore,
    *,
    case_id: UUID,
    run_id: UUID,
    revision_id: UUID,
) -> bytes:
    """Return the stored receipt in the caller's authorized read or write unit.

    The caller owns authorization, its own unit and transaction cleanup, as for
    `prove_revision`: a write caller holds the case lock, the filed Committee
    section read holds none, so the audit-head comparison below reads across
    snapshots and a governed write committing mid-read makes it refuse rather
    than serve bytes it cannot prove. Historical renderer pins remain valid.
    Legacy filings without bytes refuse.

    **A filed record is served from its own bytes, never from live state.** This
    re-ran `prove_revision` against the current sources, the current
    `vendor/deploy-v` and the current narrative rules, and refused with the codes
    tampering produces when any of the three moved -- so a WRITER withdrawing a
    source, a routine bundle upgrade or a tightened narrative rule each locked
    every filed record out of the Committee section permanently, with remediation
    advice offered for a record that is immutable (FP-05). What is proven here is
    what a filed record *is*: the frozen payload still hashes to the digest the
    receipt names, the receipt bytes are the ones the host wrote, the three roles
    are independent, and the `OPINION_SIGNED`, `DELIVERABLE_FROZEN` and
    `DELIVERABLE_FILED` links are all in one verified audit chain whose head has
    not moved (FP-34: `deliverable_opinions` and `deliverable_publications` are
    consistent with each other by construction here, but consistency is not
    provenance -- `sign_opinion_in` and `freeze_in` write only those rows, and a
    caller composing its own envelope around them, as this repository's own
    convenience wrappers do not, could commit either with no audit event at
    all). Filing itself re-proves the revision under the case lock
    (`caos/api/commands/deliverable.py`), which is where a live re-derivation
    belongs.
    """
    row = conn.execute(
        "SELECT r.payload_sha256,p.payload_sha256,p.frozen_by,p.filed_by,"
        " p.filed_at,c.receipt_sha256,c.renderer_sha256,c.filed_event_sha256"
        " FROM deliverable_receipts c JOIN deliverable_publications p"
        " USING (case_id,revision_id) JOIN deliverable_revisions r"
        " ON r.case_id=c.case_id AND r.revision_key=c.revision_id"
        " WHERE c.case_id=%s AND c.revision_id=%s AND r.run_id=%s",
        (case_id, str(revision_id), run_id),
    ).fetchone()
    if row is None:
        raise Refusal(RefusalCode.DELIVERABLE_NOT_FOUND)
    invalid = Refusal(RefusalCode.DELIVERABLE_PAYLOAD_INVALID)
    digest, frozen_digest, freezer, filer, filed_at, receipt_digest, renderer, event = (
        row
    )
    signatures = revision_signatures(conn, case_id, revision_id)
    signers = {who for who, _ in signatures}
    if (
        digest != frozen_digest
        or filer is None
        or filed_at is None
        or not signatures
        or any(signed_digest != digest for _, signed_digest in signatures)
        or freezer in signers
        or filer in signers | {freezer}
    ):
        raise invalid
    receipt = Receipt(
        case_id,
        run_id,
        revision_id,
        digest,
        signatures[0][0],
        freezer,
        filer,
        renderer,
        event,
    )
    data = blobs.get(receipt_digest)
    if data != receipt_bytes(receipt):
        raise invalid
    trail = audit_trail(conn, case_id)
    filed = next((entry for entry in trail if entry.entry_sha256 == event), None)
    if (
        filed is None
        or filed.action != "DELIVERABLE_FILED"
        or filed.actor_id != filer
        or filed.payload_sha256
        not in payload_digests(
            conn,
            scope=case_id,
            actor_id=filer,
            payload=filing_payload(receipt),
            commands=("FILE_DELIVERABLE",),
        )
        or not verify_chain(conn, case_id)
        or trail[-1].entry_sha256 != audit_head(conn, case_id)
    ):
        raise invalid
    # FP-34: the same OPINION_SIGNED/DELIVERABLE_FROZEN provenance check
    # `_publication` (`caos/api/reads/reports.py`) makes over a frozen
    # revision, made here too so this reader does not depend on that one
    # caller for it. The rows above are consistent with each other; this is
    # what proves each was actually signed or frozen through the audited
    # commands, not merely written to agree.
    bound = {"revision_id": str(revision_id), "payload_sha256": digest}
    required = {("OPINION_SIGNED", who) for who in signers}
    required.add(("DELIVERABLE_FROZEN", freezer))
    accepted = {
        actor: payload_digests(
            conn,
            scope=case_id,
            actor_id=actor,
            payload=bound,
            commands=("SIGN_OPINION", "FREEZE_DELIVERABLE"),
        )
        for _action, actor in required
    }
    events = {
        (entry.action, entry.actor_id)
        for entry in trail
        if entry.payload_sha256 in accepted.get(entry.actor_id, frozenset())
    }
    if not required <= events:
        raise invalid
    # The frozen payload's own bytes, from the store that addresses them by
    # digest: a filed record is immutable, so what is checked is that the bytes
    # the receipt names are still held and still hash to it.
    if sha256(blobs.get(digest)).hexdigest() != digest:
        raise invalid
    return data

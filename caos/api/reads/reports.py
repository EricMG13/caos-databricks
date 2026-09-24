"""Exact saved Report and frozen/filed Committee reads; no write authority.

Report names its revision or not. Named, it is served exactly as Committee
serves one. Unnamed, it serves the run's head -- the revision a save would be
composed against -- or, when the run has none, the run's accepted artifacts as
a save would carry them and the save that makes the first revision. That is
the filing chain's front door: nothing else in the workspace sets `?revision`.
"""

from __future__ import annotations

import json
from hashlib import sha256
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends

from caos.api.commands.availability import FilingFacts, report_actions
from caos.api.deps import (
    IDENTITY_FIRST,
    Blobs,
    Caller,
    CasePath,
    Methodology,
    RevisionQuery,
    RunQuery,
    Store,
    readable,
    revision_query,
)
from caos.api.wire import REVISIONS_MAX, CommitteeDocument, ReportDocument
from caos.boundary_text import BoundaryText
from caos.deliverable.canonical import Revision, canonical_payload
from caos.deliverable.filing import revision_signatures
from caos.deliverable.receipts import read_filed_receipt
from caos.deliverable.revisions import prove_revision, read_revision
from caos.refusals import Refusal, RefusalCode
from caos.store.audit import audit_head, audit_trail, verify_chain
from caos.store.commands import payload_digests
from caos.store.members import Standing, standing_of
from caos.store.outcomes import execution_reads
from caos.store.source_sets import cited_source_ids

# Three-node LITE: isolation/standing/selection (3), live proof (40). No lock:
# a read takes none, and the payload digest below is the consistency check.
# Committee adds publication/signatures (2) and three actor/audit proof reads.
# Filed Committee also adds receipt/audit (5) and saved payload (1).
# Task 12.1 adds two to each: the publication row and the signatures the
# section's four filing actions are judged from. Proving a filing act costs one
# more read per actor it looks for -- the receipts that actor committed on this
# case, which is how an event written by a command is rebuilt (`payload_digests`)
# -- so a frozen revision pays two, one signer and its freezer, and a filed one
# pays a third for its filer.
# The figures below are therefore stated **for one signer**, which is the only
# shape any fixture has and no longer the only shape the store allows: the
# opinions table is keyed per signer and `sign_opinion_in` refuses only a frozen
# revision, so a second approver may sign before the freeze and costs one more
# read. Measured at 53 for the frozen path with two signers. Recorded in
# CLAUDE.md rather than absorbed into the number, because a budget fitted to the
# widest shape stops measuring the common one.
# The head a save is judged against rides the revision's own statement, so it
# costs no round trip. "unsaved" is a run with no revision, measured on the
# same LITE route: isolation and standing (2), the head (1), the run and its
# title (1), and the payload derivation a first save would make (38) -- the
# derivation the saved path proves, less the stored revision's own reads.
# Every path that finds a revision lists the run's revisions too (1), so a
# committee member can reach a frozen one from Report; "unsaved" has none.
# FP-34: `read_filed_receipt` now re-checks OPINION_SIGNED and
# DELIVERABLE_FROZEN provenance itself rather than trusting `_publication`'s
# own pass alone, one more `payload_digests` read per signer and the freezer
# -- the same one signer, one freezer shape the rest of this budget is stated
# for -- so "committee" pays two more for a filed revision.
IO_BUDGET = {"report": 46, "committee": 22, "frozen": 53, "unsaved": 42}
# N35's remainder: "report" and "frozen" (a state the store has not filed)
# `prove_revision` -- the saved payload once, for its narrative
# (`read_revision`), then the whole payload re-derived (`canonical_payload`),
# the LITE route's three nodes at two blobs each (artifact and record,
# `PER_HANDOFF_BLOBS`'s own shape): 1 + 3*2. "unsaved" derives the same way
# with no saved payload to read first: 3*2. A filed "committee" instead reads
# its own two stored blobs -- the receipt `read_filed_receipt` proves and the
# frozen payload `read_revision` then serves -- never re-deriving.
BLOB_BUDGET = {"report": 7, "committee": 2, "frozen": 7, "unsaved": 6}
router = APIRouter()


def report_revision(revision: str | None = None) -> UUID | None:
    """Report's `revision` query: absent selects the run's head, or none.

    Present, it is parsed exactly as Committee's, so an empty or malformed one
    still names no deliverable rather than falling back to the head.
    """
    return None if revision is None else revision_query(revision)


ReportRevision = Annotated[UUID | None, Depends(report_revision)]


@router.get(
    "/api/v1/cases/{case_id}/report",
    response_model=ReportDocument,
    dependencies=[IDENTITY_FIRST],
)
def read_report(  # noqa: PLR0913 -- caller and parsed selection precede stores
    actor: Caller,
    case_id: CasePath,
    run: RunQuery,
    revision: ReportRevision,
    conn: Store,
    blobs: Blobs,
    bundle: Methodology,
) -> ReportDocument:
    return ReportDocument.model_validate(
        _read(actor, case_id, run, revision, conn, blobs, bundle, committee=False)
    )


@router.get(
    "/api/v1/cases/{case_id}/committee",
    response_model=CommitteeDocument,
    dependencies=[IDENTITY_FIRST],
)
def read_committee(  # noqa: PLR0913 -- same selection, with frozen/receipt proof
    actor: Caller,
    case_id: CasePath,
    run: RunQuery,
    revision: RevisionQuery,
    conn: Store,
    blobs: Blobs,
    bundle: Methodology,
) -> CommitteeDocument:
    return CommitteeDocument.model_validate(
        _read(actor, case_id, run, revision, conn, blobs, bundle, committee=True)
    )


def _read(  # noqa: PLR0913 -- both documents share one authorization/proof unit
    actor: Caller,
    case_id: UUID,
    run: UUID | None,
    revision: UUID | None,
    conn: Store,
    blobs: Blobs,
    bundle: Methodology,
    *,
    committee: bool,
) -> dict[str, Any]:
    if run is None:
        raise Refusal(RefusalCode.RUN_NOT_FOUND)
    with execution_reads(conn):
        # Read inside the unit rather than as `VisibleCase`: `execution_reads`
        # adopts no transaction already open, and a standing read before it
        # would be one.
        standing = readable(standing_of(conn, case_id=case_id, user_id=actor.user_id))
        # The head is ordered exactly as the save command's `_latest` orders
        # it, which is what makes "not the head" the save's own refusal.
        row = conn.execute(
            "SELECT r.revision_id,r.payload_sha256,now(),(SELECT h.revision_id"
            " FROM deliverable_revisions h WHERE h.case_id=r.case_id"
            " AND h.run_id=r.run_id ORDER BY h.saved_at DESC, h.revision_id DESC"
            " LIMIT 1) FROM deliverable_revisions r WHERE r.case_id=%s"
            " AND r.run_id=%s AND (%s::uuid IS NULL OR r.revision_id=%s)"
            " ORDER BY r.saved_at DESC, r.revision_id DESC LIMIT 1",
            (case_id, run, revision, revision),
        ).fetchone()
        if row is None and revision is None:
            return _unsaved(actor, standing, case_id, run, conn, blobs, bundle)
        if row is None:
            raise Refusal(RefusalCode.DELIVERABLE_NOT_FOUND)
        selected, digest, observed_at, head = row
        revision = UUID(str(selected))
        publication = _publication(conn, case_id, revision, digest) if committee else {}
        if publication.get("state") == "filed":
            publication["receipt"] = json.loads(
                read_filed_receipt(
                    conn,
                    blobs,
                    case_id=case_id,
                    run_id=run,
                    revision_id=revision,
                )
            )
            payload = read_revision(conn, blobs, case_id=case_id, revision_id=revision)
        else:
            data = prove_revision(
                conn, blobs, bundle, case_id=case_id, revision_id=revision
            )
            if sha256(data).hexdigest() != digest:
                raise Refusal(RefusalCode.DELIVERABLE_PAYLOAD_INVALID)
            payload = json.loads(data)
        return dict(
            chrome=dict(
                subject=dict(case_id=case_id, title=payload["case_title"]),
                served_role=dict(global_role=actor.role, standing=standing),
                actions=report_actions(
                    actor.role,
                    standing,
                    _filing_facts(conn, case_id, revision, actor, head=head),
                ),
            ),
            body={
                **_body(conn, payload, digest),
                **publication,
                "revisions": _revisions(conn, case_id, run),
            },
            observed_at=observed_at,
            observed_empty=False,
            status="complete",
            notes=[],
        )


def _unsaved(  # noqa: PLR0913 -- the read's caller, selection and stores
    actor: Caller,
    standing: Standing,
    case_id: UUID,
    run: UUID,
    conn: Store,
    blobs: Blobs,
    bundle: Methodology,
) -> dict[str, Any]:
    """A run with no revision: what a first save would carry, and that save.

    The save's commit derives the payload and refuses when it cannot, so the
    read derives it too and shows the save refused with that code rather than
    offering one its commit refuses. A refused derivation shows no artifact:
    nothing it could show was proven. No revision exists, so there is no digest
    to name and nothing to sign, freeze or file.
    """
    row = conn.execute(
        "SELECT c.title,now() FROM runs r JOIN cases c USING (case_id)"
        " WHERE r.run_id=%s AND r.case_id=%s",
        (run, case_id),
    ).fetchone()
    if row is None:
        raise Refusal(RefusalCode.RUN_NOT_FOUND)
    title, observed_at = str(row[0]), row[1]
    underivable = None
    artifacts: list[dict[str, Any]] = []
    try:
        # Nothing reads the store after this, so a refusal leaves nothing in
        # this unit to serve from a transaction it may have spoiled.
        artifacts = canonical_payload(
            conn,
            blobs,
            bundle,
            Revision(case_id, run, BoundaryText.of(title), BoundaryText.of("unsaved")),
            _in_unit=True,
        )["artifacts"]
    except Refusal as refusal:
        underivable = refusal.code
    payload = dict(
        case_id=str(case_id),
        run_id=str(run),
        revision_id=None,
        case_title=title,
        artifacts=artifacts,
        narrative=[],
    )
    return dict(
        chrome=dict(
            subject=dict(case_id=case_id, title=title),
            served_role=dict(global_role=actor.role, standing=standing),
            actions=report_actions(actor.role, standing, None, underivable),
        ),
        body={**_body(conn, payload, None), "revisions": []},
        observed_at=observed_at,
        observed_empty=not artifacts,
        status="complete",
        notes=[],
    )


def _revisions(conn: Store, case_id: UUID, run: UUID) -> list[dict[str, Any]]:
    """The run's revisions, newest first, each with how far it has gone.

    A publication row is the freeze and its `filed_at` the filing; the
    Committee read proves both before it serves either.
    """
    rows = conn.execute(
        "SELECT r.revision_id,r.payload_sha256,r.saved_at,"
        " CASE WHEN p.filed_at IS NOT NULL THEN 'filed'"
        " WHEN p.revision_id IS NOT NULL THEN 'frozen' ELSE 'saved' END"
        " FROM deliverable_revisions r LEFT JOIN deliverable_publications p"
        " ON p.case_id=r.case_id AND p.revision_id=r.revision_key"
        " WHERE r.case_id=%s AND r.run_id=%s"
        " ORDER BY r.saved_at DESC, r.revision_id DESC LIMIT %s",
        (case_id, run, REVISIONS_MAX),
    ).fetchall()
    keys = ("revision_id", "payload_sha256", "saved_at", "state")
    return [dict(zip(keys, row, strict=True)) for row in rows]


def _filing_facts(
    conn: Store, case_id: UUID, revision: UUID, actor: Caller, *, head: object
) -> FilingFacts:
    """What the section can say about this revision's filing, and no more.

    Deliberately not `_publication`: that one proves the chain and refuses a
    revision that is not frozen, which is the state the sign and freeze
    controls exist for. Availability grants nothing, so it reads the two rows
    and judges from them.
    """
    row = conn.execute(
        "SELECT frozen_by,filed_by FROM deliverable_publications"
        " WHERE case_id=%s AND revision_id=%s",
        (case_id, str(revision)),
    ).fetchone()
    signers = {who for who, _ in revision_signatures(conn, case_id, revision)}
    frozen_by = None if row is None else UUID(str(row[0]))
    return FilingFacts(
        signed=bool(signers),
        frozen=row is not None,
        filed=row is not None and row[1] is not None,
        actor_signed=actor.user_id in signers,
        actor_froze=actor.user_id == frozen_by,
        head=head is not None and UUID(str(head)) == revision,
    )


def _publication(
    conn: Store, case_id: UUID, revision: UUID, digest: str
) -> dict[str, Any]:
    row = conn.execute(
        "SELECT p.payload_sha256,frozen_by,filed_by,filed_at,"
        " c.receipt_sha256 IS NOT NULL OR EXISTS (SELECT 1 FROM audit_events e"
        " LEFT JOIN deliverable_receipts r ON r.case_id=e.case_id"
        " AND r.filed_event_sha256=e.entry_sha256 WHERE e.case_id=p.case_id"
        " AND e.action='DELIVERABLE_FILED' AND r.revision_id IS NULL"
        " AND NOT EXISTS (SELECT 1 FROM legacy_filing_events l"
        " WHERE l.case_id=e.case_id AND l.filed_event_sha256=e.entry_sha256))"
        " FROM deliverable_publications p LEFT JOIN deliverable_receipts c"
        " USING (case_id,revision_id)"
        " WHERE case_id=%s AND revision_id=%s",
        (case_id, str(revision)),
    ).fetchone()
    if row is None:
        raise Refusal(RefusalCode.DELIVERABLE_NOT_FROZEN)
    frozen_digest, freezer, filer, filed_at, filing_evidence = row
    signatures = revision_signatures(conn, case_id, revision)
    signers = [who for who, _ in signatures]
    if (
        frozen_digest != digest
        or not signers
        or freezer in signers
        or any(signed != digest for _, signed in signatures)
        or (filer is None) != (filed_at is None)
        or (filer is None and filing_evidence)
    ):
        raise Refusal(RefusalCode.DELIVERABLE_PAYLOAD_INVALID)
    bound = {"revision_id": str(revision), "payload_sha256": digest}
    trail = audit_trail(conn, case_id)
    required = {("OPINION_SIGNED", who) for who in signers}
    required.add(("DELIVERABLE_FROZEN", freezer))
    # One act, two possible writers: a store function called directly binds the
    # payload as given, a command's envelope adds its request digest. Both are
    # rebuilt exactly, so neither comparison is looser than the other. Read once
    # per actor this read is looking for rather than once per entry of a trail
    # that is the whole case's: only these actors' events can satisfy `required`.
    accepted = {
        actor: payload_digests(
            conn,
            scope=case_id,
            actor_id=actor,
            payload=bound,
            # The only commands that can have written OPINION_SIGNED or
            # DELIVERABLE_FROZEN; naming them keeps this read off the rest of
            # the actor's receipts, which nothing collects.
            commands=("SIGN_OPINION", "FREEZE_DELIVERABLE"),
        )
        for _action, actor in required
    }
    events = {
        (entry.action, entry.actor_id)
        for entry in trail
        if entry.payload_sha256 in accepted.get(entry.actor_id, frozenset())
    }
    if (
        not required <= events
        or not verify_chain(conn, case_id)
        or trail[-1].entry_sha256 != audit_head(conn, case_id)
    ):
        raise Refusal(RefusalCode.DELIVERABLE_PAYLOAD_INVALID)
    return dict(
        state="frozen" if filer is None else "filed",
        signed_by=signers,
        frozen_by=freezer,
        filed_by=filer,
        receipt=None,
        **_links(case_id, revision, filed=filer is not None),
    )


def _links(case_id: UUID, revision: UUID, *, filed: bool) -> dict[str, str | None]:
    """Where this revision's render and, once filed, its package are read
    (`caos/api/reads/deliverable.py`, N4). Proven nowhere here: opening either
    link runs that module's own proof."""
    base = f"/api/v1/cases/{case_id}/revisions/{revision}"
    return dict(
        render_url=f"{base}/render",
        package_url=f"{base}/package" if filed else None,
    )


def _body(conn: Store, payload: dict[str, Any], digest: str | None) -> dict[str, Any]:
    artifacts = []
    digests: dict[str, str] = {}
    for artifact in payload["artifacts"]:
        projections = json.loads(artifact["record"])["projections"]
        artifacts.append(dict(artifact))
        digests[artifact["route_node_id"]] = artifact["record_sha256"]
        for key in (
            "qa_status",
            "committee_status",
            "decision_scope",
            "limitation_flags",
            "validation_warnings",
        ):
            artifacts[-1][key] = projections[key]
    narrative = _narrative_view(
        conn, UUID(payload["run_id"]), payload["narrative"], digests
    )
    return dict(
        case_id=payload["case_id"],
        displayed_run_id=payload["run_id"],
        revision_id=payload["revision_id"],
        payload_sha256=digest,
        case_title=payload["case_title"],
        artifacts=artifacts,
        narrative=narrative,
    )


def _narrative_view(
    conn: Store,
    run_id: UUID,
    narrative: list[list[dict[str, Any]]],
    digests: dict[str, str],
) -> list[list[dict[str, Any]]]:
    """Each paragraph's spans, a bracketed figure filled out with the record
    digest its own node already carries (`digests`, from this same payload's
    artifacts) and the source its document resolves to, live preferred
    (N59) -- the two fields the evidence drawer needs to open a figure's
    source without cross-referencing `ReportBody.artifacts` itself."""
    documents = {
        span["figure"]["document_sha256"]
        for paragraph in narrative
        for span in paragraph
        if span.get("figure")
    }
    sources = cited_source_ids(conn, run_id, documents)
    return [
        [
            dict(
                text=span.get("text"),
                figure=_figure(span.get("figure"), digests, sources),
            )
            for span in paragraph
        ]
        for paragraph in narrative
    ]


def _figure(
    figure: dict[str, Any] | None, digests: dict[str, str], sources: dict[str, UUID]
) -> dict[str, Any] | None:
    if figure is None:
        return None
    return {
        **figure,
        "record_sha256": digests[figure["route_node_id"]],
        "source_id": sources[figure["document_sha256"]],
    }

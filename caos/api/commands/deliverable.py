"""Save, sign, freeze and file one revision (Task 12.1).

The filing chain existed in `caos/deliverable/` and no request path reached
it. Each act is now one command through the shared envelope, and three things
that were the store's remain the store's, checked inside the unit under the
case lock:

1. **Three independent actors.** The signer, the freezer and the filer are
   three different people (`APPROVER_NOT_INDEPENDENT`). The Report section
   composes its controls from what it can see, and a signer whose browser
   still offers "Freeze" is refused here -- persona is not authority.
2. **The digest a request binds** (invariant 5). Every one of the three carries
   the `payload_sha256` its actor reviewed, compared with the stored revision's
   before anything is written; `freeze` and `file` then compare the signature
   and the frozen digest as they always did.
3. **One head per run.** A draft names the revision it was composed against,
   so a save that raced another save is `COMMAND_EXPECTATION_STALE` rather
   than a second head nobody chose.

The revision id is minted in the route rather than in the unit, because the
receipt has to name it: a command that minted one inside its transaction could
not answer a replay with the body it first committed.
"""

from __future__ import annotations

from collections.abc import Callable
from hashlib import sha256
from typing import Annotated, Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel

from caos.api.commands._request import (
    CommandRequest,
    Key,
    governed,
    json_body,
    require_case_approver,
    require_case_writer,
)
from caos.api.deps import (
    IDENTITY_FIRST,
    Blobs,
    Caller,
    CasePath,
    Methodology,
    RevisionPath,
    RunPath,
    Store,
)
from caos.api.wire import (
    DeliverableFiled,
    DeliverableFrozen,
    FileDeliverable,
    FreezeDeliverable,
    NarrativeDraft,
    OpinionSigned,
    RevisionSaved,
    SaveRevision,
    SignOpinion,
)
from caos.blobs import BlobStore
from caos.deliverable.filing import (
    file_deliverable_in,
    filing_payload,
    freeze_in,
    persist_receipt,
    sign_opinion_in,
)
from caos.deliverable.revisions import prove_revision, save_revision_in
from caos.refusals import Refusal, RefusalCode
from caos.store import StoreConnection
from caos.store.audit import GovernedAction
from caos.store.members import Standing

# Statements per success path, each asserted with `==` by
# `tests/test_governed_write_routes.py`, measured over LITE's three nodes. Save
# and freeze are the two that scale: `canonical_payload` and `prove_revision`
# each re-derive the whole payload inside the unit -- the work
# `caos/api/reads/reports.py` budgets at 45 for the same run -- so both are
# stated for a route of that shape and a wider route is what first moves them.
# Signature reads only the revision's chain rows, so it does not. Filing
# re-proves what it files (FP-04), so it now scales with the route as freeze
# does; the difference between it and freeze is the filing chain's own rows.
SAVE_IO = 52
SIGN_IO = 14
FREEZE_IO = 55
FILE_IO = 56
IO_BUDGET = max(SAVE_IO, SIGN_IO, FREEZE_IO, FILE_IO)

_REVISION = "/api/v1/cases/{case_id}/revisions/{revision_id}"

router = APIRouter()
Writer = Annotated[Standing, Depends(require_case_writer)]
Approver = Annotated[Standing, Depends(require_case_approver)]


def _spans(narrative: list[list[NarrativeDraft]]) -> list[list[dict[str, Any]]]:
    """The draft in the shape `save_revision` validates.

    A span is prose or a figure and never both or neither; the wire cannot say
    that with a closed object, so it is said here, in the request's own code.
    """
    drafted = []
    for paragraph in narrative:
        spans: list[dict[str, Any]] = []
        for span in paragraph:
            if (span.text is None) == (span.figure is None):
                raise Refusal(RefusalCode.NARRATIVE_REFERENCE_INVALID)
            spans.append(
                {"text": span.text}
                if span.figure is None
                else {
                    "figure": {
                        "route_node_id": span.figure.route_node_id,
                        "citation_index": span.figure.citation_index,
                    }
                }
            )
        drafted.append(spans)
    return drafted


def _latest(conn: StoreConnection, case_id: UUID, run_id: UUID) -> UUID | None:
    """The run's newest revision, under the case lock the caller already holds."""
    row = conn.execute(
        "SELECT revision_id FROM deliverable_revisions WHERE case_id=%s AND run_id=%s"
        " ORDER BY saved_at DESC, revision_id DESC LIMIT 1",
        (case_id, run_id),
    ).fetchone()
    return None if row is None else UUID(str(row[0]))


def _owned_run(conn: StoreConnection, case_id: UUID, run_id: UUID) -> None:
    """A run of another case is as unknown as a run that does not exist."""
    row = conn.execute(
        "SELECT 1 FROM runs WHERE run_id = %s AND case_id = %s", (run_id, case_id)
    ).fetchone()
    if row is None:
        raise Refusal(RefusalCode.RUN_NOT_FOUND)


def _reviewed(
    conn: StoreConnection, case_id: UUID, revision_id: UUID, expected: str
) -> UUID:
    """The revision's run, having proved the caller reviewed its exact bytes.

    Invariant 5's half that a route owns: a revision is immutable, so this
    cannot refuse a revision that moved -- it refuses an actor acting on bytes
    other than the ones in front of them.
    """
    row = conn.execute(
        "SELECT run_id,payload_sha256 FROM deliverable_revisions"
        " WHERE case_id=%s AND revision_id=%s",
        (case_id, revision_id),
    ).fetchone()
    if row is None:
        raise Refusal(RefusalCode.DELIVERABLE_NOT_FOUND)
    if str(row[1]) != expected:
        raise Refusal(RefusalCode.DELIVERABLE_MOVED_SINCE_SIGNING)
    return UUID(str(row[0]))


@router.post(
    "/api/v1/cases/{case_id}/runs/{run_id}/revisions",
    status_code=201,
    dependencies=[IDENTITY_FIRST],
)
def save(  # noqa: PLR0913 -- decision 2's dependency order, keyword-only
    *,  # keyword-only: the order below is still the one FastAPI solves in
    actor: Caller,
    key: Key,
    _standing: Writer,
    run_id: RunPath,
    body: Annotated[SaveRevision, Depends(json_body(SaveRevision))],
    case_id: CasePath,
    conn: Store,
    blobs: Blobs,
    bundle: Methodology,
) -> Response:
    """A revision derived from the run's accepted artifacts and this draft.

    Nothing of the payload comes from the request but the narrative, and every
    figure in it is resolved against a record the host verified.
    """
    narrative = _spans(body.narrative)
    revision_id = uuid4()

    def write(unit: StoreConnection) -> tuple[int, RevisionSaved]:
        _owned_run(unit, case_id, run_id)
        if _latest(unit, case_id, run_id) != body.expected_revision_id:
            raise Refusal(RefusalCode.COMMAND_EXPECTATION_STALE)
        digest = save_revision_in(
            unit,
            blobs,
            bundle,
            case_id=case_id,
            run_id=run_id,
            actor_id=actor.user_id,
            narrative=narrative,
            revision_id=revision_id,
        )
        return 201, RevisionSaved(
            case_id=case_id,
            run_id=run_id,
            revision_id=revision_id,
            payload_sha256=digest,
        )

    return governed(
        conn,
        scope=case_id,
        key=key,
        request=CommandRequest(
            "SAVE_REVISION", case_id, run_id, None, body.model_dump(mode="json")
        ),
        action=GovernedAction(
            case_id=case_id,
            actor_id=actor.user_id,
            action="REVISION_SAVED",
            requires=Standing.WRITER,
            payload={"revision_id": str(revision_id), "run_id": str(run_id)},
        ),
        write=write,
        model=RevisionSaved,
    )


@router.post(f"{_REVISION}/signature", dependencies=[IDENTITY_FIRST])
def sign(  # noqa: PLR0913 -- decision 2's dependency order, keyword-only
    *,  # keyword-only: the order below is still the one FastAPI solves in
    actor: Caller,
    key: Key,
    _standing: Approver,
    revision_id: RevisionPath,
    body: Annotated[SignOpinion, Depends(json_body(SignOpinion))],
    case_id: CasePath,
    conn: Store,
) -> Response:
    """Sign the exact stored bytes. A frozen revision takes no further signature."""

    payload: dict[str, str] = {"revision_id": str(revision_id)}

    def write(unit: StoreConnection) -> tuple[int, OpinionSigned]:
        _reviewed(unit, case_id, revision_id, body.payload_sha256)
        digest = sign_opinion_in(
            unit, case_id=case_id, actor_id=actor.user_id, revision_id=revision_id
        )
        payload["payload_sha256"] = digest
        return 200, OpinionSigned(
            case_id=case_id,
            revision_id=revision_id,
            payload_sha256=digest,
            signed_by=actor.user_id,
        )

    return _command(
        conn,
        actor_id=actor.user_id,
        case_id=case_id,
        revision_id=revision_id,
        key=key,
        command="SIGN_OPINION",
        body=body,
        write=write,
        model=OpinionSigned,
        payload=payload,
    )


@router.post(f"{_REVISION}/freeze", dependencies=[IDENTITY_FIRST])
def freeze(  # noqa: PLR0913 -- decision 2's dependency order, keyword-only
    *,  # keyword-only: the order below is still the one FastAPI solves in
    actor: Caller,
    key: Key,
    _standing: Approver,
    revision_id: RevisionPath,
    body: Annotated[FreezeDeliverable, Depends(json_body(FreezeDeliverable))],
    case_id: CasePath,
    conn: Store,
    blobs: Blobs,
    bundle: Methodology,
) -> Response:
    """Re-prove under the case lock, then freeze exactly the signed bytes."""

    payload: dict[str, str] = {"revision_id": str(revision_id)}

    def write(unit: StoreConnection) -> tuple[int, DeliverableFrozen]:
        _reviewed(unit, case_id, revision_id, body.payload_sha256)
        digest = freeze_in(
            unit,
            blobs,
            bundle,
            case_id=case_id,
            actor_id=actor.user_id,
            revision_id=revision_id,
        )
        payload["payload_sha256"] = digest
        return 200, DeliverableFrozen(
            case_id=case_id,
            revision_id=revision_id,
            payload_sha256=digest,
            frozen_by=actor.user_id,
        )

    return _command(
        conn,
        actor_id=actor.user_id,
        case_id=case_id,
        revision_id=revision_id,
        key=key,
        command="FREEZE_DELIVERABLE",
        body=body,
        write=write,
        model=DeliverableFrozen,
        payload=payload,
    )


@router.post(f"{_REVISION}/filing", dependencies=[IDENTITY_FIRST])
def file(  # noqa: PLR0913 -- decision 2's dependency order, keyword-only
    *,  # keyword-only: the order below is still the one FastAPI solves in
    actor: Caller,
    key: Key,
    _standing: Approver,
    revision_id: RevisionPath,
    body: Annotated[FileDeliverable, Depends(json_body(FileDeliverable))],
    case_id: CasePath,
    conn: Store,
    blobs: Blobs,
    bundle: Methodology,
) -> Response:
    """File once, by someone who neither signed nor froze, over proven bytes.

    The detached receipt names the audit link this unit writes, so it is
    persisted in `after_event` -- after the command receipt, which therefore
    cannot carry it. The Committee section serves it.
    """
    filed: list[Any] = []
    payload: dict[str, str] = {"revision_id": str(revision_id)}

    def write(unit: StoreConnection) -> tuple[int, DeliverableFiled]:
        run_id = _reviewed(unit, case_id, revision_id, body.payload_sha256)
        # Re-derived here as the freeze re-derives it, under the same case lock.
        # Filing is the act that enters the permanent audit chain, and it was
        # the one act of the three that compared rows only: a WRITER
        # withdrawing a cited source reopens every gate bound to it, and
        # `DELIVERABLE_FILED` was still written for a deliverable the host could
        # no longer prove (FP-04).
        proven = prove_revision(
            unit, blobs, bundle, case_id=case_id, revision_id=revision_id
        )
        if sha256(proven).hexdigest() != body.payload_sha256:
            raise Refusal(RefusalCode.DELIVERABLE_MOVED_SINCE_SIGNING)
        receipt = file_deliverable_in(
            unit, case_id=case_id, actor_id=actor.user_id, revision_id=revision_id
        )
        payload.update(filing_payload(receipt))
        filed.append(receipt)
        return 200, DeliverableFiled(
            case_id=case_id,
            run_id=run_id,
            revision_id=revision_id,
            payload_sha256=receipt.payload_sha256,
            filed_by=actor.user_id,
        )

    return _command(
        conn,
        actor_id=actor.user_id,
        case_id=case_id,
        revision_id=revision_id,
        key=key,
        command="FILE_DELIVERABLE",
        body=body,
        write=write,
        model=DeliverableFiled,
        payload=payload,
        after_event=_persist(blobs, filed),
    )


def _persist(
    blobs: BlobStore, filed: list[Any]
) -> Callable[[StoreConnection, str], None]:
    def persist(unit: StoreConnection, event: str) -> None:
        persist_receipt(unit, blobs, filed[0], event)

    return persist


def _command(  # noqa: PLR0913 -- one command's identity and unit, keyword-only
    conn: StoreConnection,
    *,
    actor_id: UUID,
    case_id: UUID,
    revision_id: UUID,
    key: UUID,
    command: str,
    body: BaseModel,
    write: Callable[[StoreConnection], tuple[int, BaseModel]],
    model: type[BaseModel],
    payload: dict[str, str],
    after_event: Callable[[StoreConnection, str], None] | None = None,
) -> Response:
    """The three revision-scoped commands' shared envelope.

    The revision is bound into the request's one free string slot, so two
    signatures of two revisions under one key are two different requests.
    """
    # One literal per call site: `tests/test_event_names.py` reads the action set.
    action = {
        "SIGN_OPINION": GovernedAction(
            case_id, actor_id, "OPINION_SIGNED", Standing.APPROVER, payload
        ),
        "FREEZE_DELIVERABLE": GovernedAction(
            case_id, actor_id, "DELIVERABLE_FROZEN", Standing.APPROVER, payload
        ),
        "FILE_DELIVERABLE": GovernedAction(
            case_id, actor_id, "DELIVERABLE_FILED", Standing.APPROVER, payload
        ),
    }[command]
    return governed(
        conn,
        scope=case_id,
        key=key,
        request=CommandRequest(
            command, case_id, None, str(revision_id), body.model_dump(mode="json")
        ),
        action=action,
        write=write,
        model=model,
        after_event=after_event,
    )

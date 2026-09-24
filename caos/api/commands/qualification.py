"""A reviewer signs a qualification verdict (F17's producer half; §65).

The one write in this system that is not a case's. Qualification spans a set
of cases, so there is no case to lock, no `case_members` standing to hold and
no governed unit through `run_command`: the write is `record_verdict`, in one
transaction, and the store's own bindings are what refuse it -- provider, set
digest and build must equal the recorded evidence, and the snapshot must be
`complete`. Nothing here repeats those checks; it maps them to the wire.

Three things the route keeps apart.

*The document is the reviewer's.* The body is the seven bindings `read_verdict`
declares and nothing else, closed at the wire and read once, by that reader,
against the store's clock. The host originates none of it.

*The identity is the host's.* `reviewer_id` is `Actor.user_id`, derived at the
edge from the subject the proxy asserted. A body naming one is an undeclared
field and is refused before a connection opens.

*The floor is the top global rank.* A verdict turns every case's qualification
label to one person's word, which makes it the first authority here that is
account-wide rather than case-scoped -- the case `CLAUDE.md`'s ledger reserved
for the global role. Everywhere else an ANALYST's write needs case standing on
top of the role; with no case to stand on, the only separation available is
rank, and `_RANK` says which is highest. A caller below it is answered as a
stranger to a case is: not found, disclosing nothing about which evidence the
store holds.
"""

from __future__ import annotations

from re import fullmatch
from typing import Annotated, Any
from uuid import UUID

import psycopg
from fastapi import APIRouter, Depends, Response

from caos.api.commands._request import Key, command_response, json_body
from caos.api.deps import IDENTITY_FIRST, Caller, Store
from caos.api.identity import Actor, GlobalRole, at_least
from caos.api.wire import SignVerdict, VerdictRecorded
from caos.qualification.store import evidence_at, record_verdict
from caos.qualification.verdict import read_verdict
from caos.refusals import Refusal, RefusalCode
from caos.store import StoreConnection, rollback_or_close
from caos.store.commands import (
    NIL_SCOPE,
    CommandResult,
    StoredReceipt,
    find_receipt,
    record_receipt,
    request_digest,
)

# The receipt lookup, the store's clock, the exact evidence lookup, then
# `record_verdict` (the snapshot read, the runs' status and artifacts and the
# recorded models `assert_store_agrees` compares, `record_evidence`'s three
# statements and the insert) and the receipt.
# Measured in `tests/test_qualification_sign.py`.
SIGN_IO = 1 + 1 + 1 + 7 + 1
REPLAY_IO = 1  # the receipt lookup alone; a replay writes nothing
IO_BUDGET = SIGN_IO

# Who may sign. Compared by rank (`at_least`), not by identity.
SIGNS = GlobalRole.ADMIN

# The command this route records a receipt for. There is no case to scope a key
# to, so the scope is the nil UUID `0014_command_requests.sql` already uses for
# create case: a key is unique per reviewer, which is what a retry needs.
SIGN_VERDICT = "SIGN_VERDICT"

router = APIRouter()


def require_reviewer(actor: Caller) -> Actor:
    """The actor, if its global role reaches the signing floor.

    Declared ahead of the body and the store, so a caller below the floor is
    answered before either is read -- and answered as unknown evidence is.
    """
    if not at_least(actor.role, SIGNS):
        raise Refusal(RefusalCode.QUALIFICATION_EVIDENCE_NOT_FOUND)
    return actor


def evidence_path(evidence_sha256: str) -> str:
    """The path's evidence digest, or the same private answer a stranger gets.

    Typed `str` and checked here rather than validated by FastAPI, so a
    malformed digest is the declared refusal body and not a 422 that quotes
    the path -- and, as a dependency before the store, opens no connection.
    """
    if fullmatch(r"[0-9a-f]{64}", evidence_sha256) is None:
        raise Refusal(RefusalCode.QUALIFICATION_EVIDENCE_NOT_FOUND)
    return evidence_sha256


Reviewer = Annotated[Actor, Depends(require_reviewer)]
EvidencePath = Annotated[str, Depends(evidence_path)]


def _replayed(
    conn: StoreConnection, stored: StoredReceipt, request_sha256: str
) -> CommandResult:
    """`caos/store/commands.py`'s two replay predicates, over the one scope
    this command has: the same request replays its receipt, a different one
    under the same key is the conflict. Both end the read unit."""
    rollback_or_close(conn)
    if stored.request_sha256 != request_sha256:
        raise Refusal(RefusalCode.IDEMPOTENCY_KEY_REUSED)
    return CommandResult(stored.status, stored.receipt, replayed=True)


def _signed(  # noqa: PLR0913 -- one command's identity, key and document
    conn: StoreConnection,
    *,
    evidence_sha256: str,
    reviewer_id: UUID,
    key: UUID,
    request_sha256: str,
    document: dict[str, Any],
) -> CommandResult:
    """Every statement the request sends, so the route can type what fails.

    Its own function because each of these is the store answering: with them
    inline the route could not tell a driver fault from a refusal without
    catching `psycopg.Error` around raises of its own.

    The receipt is looked up first and written last, in the verdict's own
    transaction, which is `run_command`'s shape without the governed unit it
    has no case to run: no case lock to serialise twins and no audit event,
    because the immutable verdict row is the record. A twin that took the key
    while this request was in flight makes `record_receipt` insert nothing,
    and this request replays the commit that won rather than keeping a verdict
    nobody has a receipt for.
    """
    stored = find_receipt(conn, actor_id=reviewer_id, scope=NIL_SCOPE, key=key)
    if stored is not None:
        return _replayed(conn, stored, request_sha256)
    row = conn.execute("SELECT now()").fetchone()
    if row is None:
        raise Refusal(RefusalCode.STORE_UNAVAILABLE)
    [now] = row
    verdict = read_verdict(document, now=now)
    evidence = evidence_at(conn, evidence_sha256=evidence_sha256)
    if evidence is None:
        raise Refusal(RefusalCode.QUALIFICATION_EVIDENCE_NOT_FOUND)
    try:
        record_verdict(
            conn, evidence=evidence, reviewer_id=reviewer_id, verdict=verdict
        )
    except Refusal as refused:
        if refused.code is not RefusalCode.VERDICT_ALREADY_RECORDED:
            raise
        # A twin of this request took the verdict while it was in flight. Both
        # missed the receipt above, one committed, and the loser's insert
        # collided -- which was answered as a wrong binding although exactly one
        # verdict and one receipt persisted (AR-10). The committed receipt is
        # recovered after the duplicate's rollback, so an identical concurrent
        # signature replays what won. A *different* request under this key, or
        # the same reviewer signing this evidence again under a fresh key, finds
        # no receipt and keeps the refusal: that one really is already recorded.
        rollback_or_close(conn)
        twin = find_receipt(conn, actor_id=reviewer_id, scope=NIL_SCOPE, key=key)
        if twin is None:
            raise
        return _replayed(conn, twin, request_sha256)
    receipt = VerdictRecorded(
        evidence_sha256=evidence_sha256,
        reviewer_id=reviewer_id,
        decided_at=verdict.decided_at,
        expires_at=verdict.expires_at,
    ).model_dump(mode="json")
    if not record_receipt(
        conn,
        actor_id=reviewer_id,
        scope=NIL_SCOPE,
        key=key,
        command=SIGN_VERDICT,
        request_sha256=request_sha256,
        status=201,
        receipt=receipt,
    ):
        rollback_or_close(conn)
        twin = find_receipt(conn, actor_id=reviewer_id, scope=NIL_SCOPE, key=key)
        if twin is None:
            rollback_or_close(conn)
            raise Refusal(RefusalCode.STORE_UNAVAILABLE)
        return _replayed(conn, twin, request_sha256)
    conn.commit()
    return CommandResult(201, receipt, replayed=False)


@router.post(
    "/api/v1/qualification/{evidence_sha256}/verdict", dependencies=[IDENTITY_FIRST]
)
def sign_verdict(
    reviewer: Reviewer,
    evidence_sha256: EvidencePath,
    key: Key,
    body: Annotated[SignVerdict, Depends(json_body(SignVerdict))],
    conn: Store,
) -> Response:
    """Record the reviewer's verdict over one exact evidence identity.

    Order is `caos/api/commands/_request.py`'s, with the rank standing in
    for a case's standing: identity, the path's evidence digest, the
    `Idempotency-Key`, the body, and only then the store. A request missing
    its key opens no connection.

    Then: the reviewer's document is read against the store's clock, because a
    document that is not a verdict is refused whatever it names; then the
    evidence it names must be held; then the store binds the two or refuses. A
    refusal after the first write rolls the transaction back, so a verdict that
    did not bind leaves no evidence row behind it either.
    """
    try:
        result = _signed(
            conn,
            evidence_sha256=evidence_sha256,
            reviewer_id=reviewer.user_id,
            key=key,
            # The path's evidence digest travels in the one canonical slot
            # that takes a string: a key replayed against other evidence is
            # then the idempotency conflict, not this evidence's receipt.
            request_sha256=request_digest(
                SIGN_VERDICT,
                case_id=None,
                run_id=None,
                gate=evidence_sha256,
                body=body.model_dump(mode="json"),
            ),
            document=body.model_dump(mode="json"),
        )
    except Refusal:
        rollback_or_close(conn)
        raise
    except psycopg.Error:
        # The clock, the lookup and the writes are all the store's to fail.
        # Outside this handler a driver error left the typed boundary as an
        # untyped 500 carrying the driver's own message into whatever logs it.
        rollback_or_close(conn)
        raise Refusal(RefusalCode.STORE_UNAVAILABLE) from None
    return command_response(result, VerdictRecorded)

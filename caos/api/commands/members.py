"""Case standing, and the withdrawal of a source (Task 12.1).

Three governed writes the store has always had and nothing could reach. Each
is one `run_command` unit through the shared envelope, in decision 2's
dependency order, so a stranger is answered the private 404 before a member id
or a source id is parsed.

Standing is the case's own authority, so both membership commands take the
ADMIN floor: a WRITER who could grant themselves APPROVER would make the floor
on every other command a formality. Withdrawal takes WRITER, the floor
`withdraw_source` already declared.

A revocation that revoked nothing is refused rather than recorded, for the
reason the withdrawal beside it gives: the chain must not say something
happened when nothing did.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Response

from caos.api.commands._request import (
    CommandRequest,
    Key,
    governed,
    json_body,
    require_case_admin,
    require_case_writer,
)
from caos.api.deps import (
    IDENTITY_FIRST,
    Caller,
    CasePath,
    MemberPath,
    SourcePath,
    Store,
)
from caos.api.wire import (
    GrantStanding,
    RevokeStanding,
    SourceWithdrawn,
    StandingGranted,
    StandingRevoked,
    WithdrawSource,
)
from caos.refusals import Refusal, RefusalCode
from caos.store import StoreConnection
from caos.store.audit import GovernedAction
from caos.store.gates import withdraw_source_in
from caos.store.members import Standing, grant, revoke

# Statements per success path, each asserted with `==` by
# `tests/test_governed_write_routes.py` (N9): standing, the receipt lookup,
# then the unit -- chain head, standing, the domain statement (`grant` and
# `revoke` take their own case lock beside the envelope's; `withdraw_source_in`
# takes none), the receipt read-back, the receipt and two audit writes.
GRANT_IO = 13
REVOKE_IO = 13
WITHDRAW_IO = 11
IO_BUDGET = max(GRANT_IO, REVOKE_IO, WITHDRAW_IO)

router = APIRouter()
Writer = Annotated[Standing, Depends(require_case_writer)]
Admin = Annotated[Standing, Depends(require_case_admin)]


@router.post(
    "/api/v1/cases/{case_id}/members", status_code=201, dependencies=[IDENTITY_FIRST]
)
def grant_standing(
    actor: Caller,
    *,
    key: Key,
    _standing: Admin,
    body: Annotated[GrantStanding, Depends(json_body(GrantStanding))],
    case_id: CasePath,
    conn: Store,
) -> Response:
    """Give or replace one member's standing. Replacing is the same command:
    `grant` upserts, so a demotion is a grant of the lower standing."""
    receipt = StandingGranted(
        case_id=case_id, user_id=body.user_id, standing=body.standing
    )

    def write(unit: StoreConnection) -> tuple[int, StandingGranted]:
        grant(unit, case_id=case_id, user_id=body.user_id, standing=body.standing)
        return 201, receipt

    return governed(
        conn,
        scope=case_id,
        key=key,
        request=CommandRequest(
            "GRANT_STANDING", case_id, None, None, body.model_dump(mode="json")
        ),
        action=GovernedAction(
            case_id=case_id,
            actor_id=actor.user_id,
            action="STANDING_GRANTED",
            requires=Standing.ADMIN,
            payload={
                "case_id": str(case_id),
                "user_id": str(body.user_id),
                "standing": body.standing.value,
            },
        ),
        write=write,
        model=StandingGranted,
    )


@router.post(
    "/api/v1/cases/{case_id}/members/{user_id}/revocation",
    dependencies=[IDENTITY_FIRST],
)
def revoke_standing(
    actor: Caller,
    *,
    key: Key,
    _standing: Admin,
    user_id: MemberPath,
    _body: Annotated[RevokeStanding, Depends(json_body(RevokeStanding))],
    case_id: CasePath,
    conn: Store,
) -> Response:
    """End one membership. The row stays; only its liveness ends.

    An administrator may revoke their own standing: the governed write reads
    authority before this runs, so the act is authorised when it is made, and
    refusing it here would be the host deciding who a case may be left without.
    """

    def write(unit: StoreConnection) -> tuple[int, StandingRevoked]:
        if not revoke(unit, case_id=case_id, user_id=user_id):
            raise Refusal(RefusalCode.REQUEST_INVALID)
        return 200, StandingRevoked(case_id=case_id, user_id=user_id)

    return governed(
        conn,
        scope=case_id,
        key=key,
        request=CommandRequest("REVOKE_STANDING", case_id, None, str(user_id), {}),
        action=GovernedAction(
            case_id=case_id,
            actor_id=actor.user_id,
            action="STANDING_REVOKED",
            requires=Standing.ADMIN,
            payload={"case_id": str(case_id), "user_id": str(user_id)},
        ),
        write=write,
        model=StandingRevoked,
    )


@router.post(
    "/api/v1/cases/{case_id}/sources/{source_id}/withdrawal",
    dependencies=[IDENTITY_FIRST],
)
def withdraw(
    actor: Caller,
    *,
    key: Key,
    _standing: Writer,
    source_id: SourcePath,
    _body: Annotated[WithdrawSource, Depends(json_body(WithdrawSource))],
    case_id: CasePath,
    conn: Store,
) -> Response:
    """Invariant 1: withdrawal is checked live at every use, so this row
    leaving `live_sources` is the whole of the act."""

    def write(unit: StoreConnection) -> tuple[int, SourceWithdrawn]:
        withdraw_source_in(unit, case_id=case_id, source_id=source_id)
        return 200, SourceWithdrawn(case_id=case_id, source_id=source_id)

    return governed(
        conn,
        scope=case_id,
        key=key,
        request=CommandRequest("WITHDRAW_SOURCE", case_id, None, str(source_id), {}),
        action=GovernedAction(
            case_id=case_id,
            actor_id=actor.user_id,
            action="SOURCE_WITHDRAWN",
            requires=Standing.WRITER,
            payload={"source_id": str(source_id)},
        ),
        write=write,
        model=SourceWithdrawn,
    )

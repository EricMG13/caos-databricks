"""Route selection, subject pin, gate preview and approval (Task 4.2 slice 4.2e).

The path names the case and run, `Caller` the actor; the store holds every other
authority fact. Each write is one `run_command` unit under the case lock and
live standing, and first proves the run is the path case's own (a run's case
never changes), so no command locks or writes another case's run. Approval
re-derives the preview under the case and run locks (`release_gate_in`).
"""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response

from caos.api.commands._request import (
    CommandRequest,
    Key,
    governed,
    json_body,
    require_case_approver,
    require_case_reader,
    require_case_writer,
)
from caos.api.deps import (
    IDENTITY_FIRST,
    Caller,
    CasePath,
    Methodology,
    RunPath,
    Store,
)
from caos.api.wire import (
    ApproveGate,
    CreateRun,
    GateApproved,
    GatePreviewDocument,
    PinRunInput,
    RunCreated,
    RunInputPinned,
)
from caos.graph.route import RouteExtensions, resolve_route, route_digest
from caos.methodology.handoff import ADAPTER_ROUTES
from caos.methodology.vendor import catalog
from caos.refusals import Refusal, RefusalCode
from caos.store import StoreConnection
from caos.store.audit import GovernedAction
from caos.store.gates import (
    Gate,
    GateApproval,
    gate_preview,
    release_gate_in,
    require_adapter_route,
)
from caos.store.members import Standing
from caos.store.routes import pin_route_in
from caos.store.run_inputs import RunSubject, pin_run_input_in, valid_subject
from caos.store.runs import start_run
from caos.store.source_sets import snapshot_in

# Statements (and cursors) per success path, measured by
# `tests/test_run_commands.py`. A case lock is two statements, a run lock four.
REPLAY_IO = 2  # standing, receipt lookup
UNIT_IO = 8  # case lock, chain head, standing, receipt check; receipt, audit x2
# `start_run` 3; `pin_route_in` 12 (run lock, route, attempts, insert, event 5).
CREATE_RUN_IO = REPLAY_IO + UNIT_IO + 15
# A successor (§72) selects the run it answers `FOR SHARE` before the insert.
SUCCESSOR_RUN_IO = CREATE_RUN_IO + 1
# Ownership 1; `snapshot_in` over an earlier, different set 8;
# `pin_run_input_in` 16 (run lock, owner, set 2, route, pin, attempts, insert,
# event 5).
PIN_INPUT_IO = REPLAY_IO + UNIT_IO + 1 + 8 + 16
# The Run read's verified `load_run_input`, restated so this module does not
# import the runtime that read uses.
PINNED_INPUT_IO = 5
PREVIEW_IO = PINNED_INPUT_IO + 2  # standing; ownership, pin and clock
# Ownership 1; `release_gate_in`: run lock, preview, live sources, upsert.
APPROVE_IO = REPLAY_IO + UNIT_IO + 1 + 4 + PINNED_INPUT_IO + 2
IO_BUDGET = max(SUCCESSOR_RUN_IO, PIN_INPUT_IO, PREVIEW_IO, APPROVE_IO)

_GATES = {"source-set": Gate.SOURCE_SET, "research-plan": Gate.RESEARCH_PLAN}

router = APIRouter()
Writer = Annotated[Standing, Depends(require_case_writer)]
Approver = Annotated[Standing, Depends(require_case_approver)]
Reader = Annotated[Standing, Depends(require_case_reader)]


def path_gate(request: Request) -> Gate:
    """The path's gate slug; any other is routing's own 404, before a key or a
    connection is asked for."""
    gate = _GATES.get(str(request.path_params.get("gate")))
    if gate is None:
        raise HTTPException(status_code=404)
    return gate


PathGate = Annotated[Gate, Depends(path_gate)]

# `run_id: RunPath` is declared after `_standing` on every route that takes
# one: the run id is read after visibility, so a stranger learns nothing.


def _owned_run(conn: StoreConnection, case_id: UUID, run_id: UUID) -> tuple[bool, Any]:
    """Whether the case's run `run_id` has its input pinned, and the store's clock.

    `RUN_NOT_FOUND` for an unknown run or another case's: one answer for both.
    """
    row = conn.execute(
        "SELECT EXISTS (SELECT 1 FROM run_inputs i WHERE i.run_id = r.run_id), now()"
        " FROM runs r WHERE r.run_id = %s AND r.case_id = %s",
        (run_id, case_id),
    ).fetchone()
    if row is None:
        raise Refusal(RefusalCode.RUN_NOT_FOUND)
    return bool(row[0]), row[1]


@router.post("/api/v1/cases/{case_id}/runs", dependencies=[IDENTITY_FIRST])
def create_run(  # noqa: PLR0913 -- identity, key, floor, body, path, store, bundle
    actor: Caller,
    key: Key,
    _standing: Writer,
    body: Annotated[CreateRun, Depends(json_body(CreateRun))],
    case_id: CasePath,
    conn: Store,
    bundle: Methodology,
) -> Response:
    """A run with its route resolved from the verified catalog and pinned.

    A pair outside `ADAPTER_ROUTES` is refused before the catalog is read.
    `model_extension` appends CP-CF, and resolution refuses it
    `ROUTE_EXTENSION_OWNER_MISSING` on a pathway missing an owner it reads. The
    audit payload binds the selection (the flag included), the run this one
    answers (`supersedes`, §72, null for an ordinary run) and the route digest;
    the run id is in the receipt committed beside it under the same
    `request_sha256`. The link's own checks are `start_run`'s, inside the unit.
    """
    if (body.profile_id, body.selection_id) not in ADAPTER_ROUTES:
        raise Refusal(RefusalCode.ROUTE_NOT_ENABLED)
    route = resolve_route(
        catalog(bundle),
        body.profile_id,
        body.selection_id,
        extensions=RouteExtensions(model_extension=body.model_extension),
    )
    require_adapter_route(route)
    selection = body.model_dump(mode="json")

    def write(unit: StoreConnection) -> tuple[int, RunCreated]:
        run_id = start_run(unit, case_id, supersedes=body.supersedes)
        pinned = pin_route_in(unit, run_id, route)
        return 201, RunCreated(case_id=case_id, run_id=run_id, route_digest=pinned)

    return governed(
        conn,
        scope=case_id,
        key=key,
        request=CommandRequest("CREATE_RUN", case_id, None, None, selection),
        action=GovernedAction(
            case_id=case_id,
            actor_id=actor.user_id,
            action="RUN_CREATED",
            requires=Standing.WRITER,
            payload={**selection, "route_digest": route_digest(route)},
        ),
        write=write,
        model=RunCreated,
    )


@router.post(
    "/api/v1/cases/{case_id}/runs/{run_id}/input", dependencies=[IDENTITY_FIRST]
)
def pin_input(  # noqa: PLR0913 -- identity, key, floor, body, path, store, bundle
    actor: Caller,
    key: Key,
    _standing: Writer,
    run: RunPath,
    body: Annotated[PinRunInput, Depends(json_body(PinRunInput))],
    case_id: CasePath,
    conn: Store,
    bundle: Methodology,
) -> Response:
    """The subject, over a snapshot of the case's live sources taken in the
    same unit, so the SOURCE_SET preview shows exactly the members it binds.

    A run whose input is already pinned is a conflict before any snapshot: a
    new key is a new intent, and a replay is the same key's receipt.
    """
    subject = RunSubject(**body.subject.model_dump())
    if not valid_subject(subject):
        raise Refusal(RefusalCode.REQUEST_INVALID)

    def write(unit: StoreConnection) -> tuple[int, RunInputPinned]:
        if _owned_run(unit, case_id, run)[0]:
            raise Refusal(RefusalCode.RUN_INPUT_ALREADY_PINNED)
        source = snapshot_in(unit, case_id)
        pin = pin_run_input_in(unit, run, source.version, bundle, subject=subject)
        return 200, RunInputPinned(
            run_id=run,
            source_set_version=pin.source_version,
            input_fingerprint=pin.input_fingerprint,
        )

    return governed(
        conn,
        scope=case_id,
        key=key,
        request=CommandRequest(
            "PIN_RUN_INPUT", case_id, run, None, body.model_dump(mode="json")
        ),
        action=GovernedAction(
            case_id=case_id,
            actor_id=actor.user_id,
            action="RUN_INPUT_PINNED",
            requires=Standing.WRITER,
            payload={"run_id": str(run), "build_id": bundle.build_id},
        ),
        write=write,
        model=RunInputPinned,
    )


@router.get(
    "/api/v1/cases/{case_id}/runs/{run_id}/gates/{gate}/preview",
    response_model=GatePreviewDocument,
    dependencies=[IDENTITY_FIRST],
)
def read_gate_preview(
    _actor: Caller,
    gate: PathGate,
    _standing: Reader,
    run: RunPath,
    case_id: CasePath,
    conn: Store,
) -> GatePreviewDocument:
    """The exact content an approver is shown and the digests to submit.

    Reading it records nothing and releases nothing; approval re-derives it.
    """
    pinned, observed_at = _owned_run(conn, case_id, run)
    if not pinned:
        raise Refusal(RefusalCode.RUN_INPUT_NOT_PINNED)
    preview = gate_preview(conn, run, gate)
    return GatePreviewDocument(
        run_id=run,
        gate=gate,
        content=preview.content,
        preview_sha256=preview.preview_sha256,
        input_fingerprint=preview.input_fingerprint,
        observed_at=observed_at,
    )


@router.post(
    "/api/v1/cases/{case_id}/runs/{run_id}/gates/{gate}/approval",
    dependencies=[IDENTITY_FIRST],
)
def approve(  # noqa: PLR0913 -- identity, gate, key, floor, body, path, store
    actor: Caller,
    gate: PathGate,
    key: Key,
    _standing: Approver,
    run: RunPath,
    body: Annotated[ApproveGate, Depends(json_body(ApproveGate))],
    case_id: CasePath,
    conn: Store,
) -> Response:
    """Release one gate over the preview the approver submits, re-derived
    under the case and run locks at commit."""
    approval = GateApproval(
        run_id=run,
        gate=gate,
        actor_id=actor.user_id,
        preview_sha256=body.preview_sha256,
        input_fingerprint=body.input_fingerprint,
    )

    def write(unit: StoreConnection) -> tuple[int, GateApproved]:
        if not _owned_run(unit, case_id, run)[0]:
            raise Refusal(RefusalCode.RUN_INPUT_NOT_PINNED)
        release_gate_in(unit, approval)
        return 200, GateApproved(
            run_id=run,
            gate=gate,
            preview_sha256=body.preview_sha256,
            input_fingerprint=body.input_fingerprint,
        )

    return governed(
        conn,
        scope=case_id,
        key=key,
        request=CommandRequest(
            "APPROVE_GATE", case_id, run, gate.value, body.model_dump(mode="json")
        ),
        action=GovernedAction(
            case_id=case_id,
            actor_id=actor.user_id,
            action=f"GATE_RELEASED:{gate.value}",
            requires=Standing.APPROVER,
            payload={
                "run_id": str(run),
                "gate": gate.value,
                "preview_sha256": body.preview_sha256,
                "input_fingerprint": body.input_fingerprint,
            },
        ),
        write=write,
        model=GateApproved,
    )

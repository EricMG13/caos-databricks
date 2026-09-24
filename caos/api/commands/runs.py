"""Route selection, subject pin, gate preview and approval (Task 4.2 slice 4.2e).

The path names the case and run, `Caller` the actor; the store holds every other
authority fact. Each write is one `run_command` unit under the case lock and
live standing, and first proves the run is the path case's own (a run's case
never changes), so no command locks or writes another case's run. Approval
re-derives the preview under the case and run locks (`release_gate_in`).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response

from caos.api.commands._request import (
    MAX_BODY_BYTES,
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
    BRIEF_BYTES,
    ApproveGate,
    CreateRun,
    GateApproved,
    GatePreviewDocument,
    PinRunInput,
    RunCreated,
    RunInputPinned,
)
from caos.boundary_text import BoundaryText
from caos.graph.route import RouteExtensions, resolve_route, route_digest
from caos.methodology.bundle import Bundle
from caos.methodology.handoff import ADAPTER_ROUTES, RESEARCH_MODULE
from caos.methodology.vendor import (
    authority_bundle_sha256,
    cached_contract,
    catalog,
)
from caos.refusals import Refusal, RefusalCode
from caos.store import StoreConnection
from caos.store.audit import GovernedAction
from caos.store.budget import configured_ceiling
from caos.store.gates import (
    Gate,
    GateApproval,
    gate_preview,
    release_gate_in,
    require_adapter_route,
)
from caos.store.members import Standing
from caos.store.routes import pin_route_in, route_pin
from caos.store.run_inputs import (
    UNANCHORED_CP0,
    RunSubject,
    bound_research_brief,
    cos_run_id,
    linked_research_brief,
    pin_run_input_in,
    research_text,
    valid_subject,
)
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
# N1: every command body is held to `MAX_BODY_BYTES`, and a pin's carries a
# research brief the store admits up to `BRIEF_BYTES` of canonical JSON, so a
# twenty-question brief the wire and the store both accept was refused as a
# malformed body. The pin's body carries the brief twice over -- a client that
# escapes its non-ASCII text as `\uXXXX` doubles the three-byte characters
# most scripts need -- and the usual bound besides for the subject and the
# rest. Past the store's own bound the brief is `RESEARCH_BRIEF_INVALID`.
PIN_INPUT_BODY_BYTES = 2 * BRIEF_BYTES + MAX_BODY_BYTES

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
    ceiling = configured_ceiling()
    selection = body.model_dump(mode="json")

    def write(unit: StoreConnection) -> tuple[int, RunCreated]:
        run_id = start_run(
            unit, case_id, supersedes=body.supersedes, budget_ceiling=ceiling
        )
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
    body: Annotated[
        PinRunInput, Depends(json_body(PinRunInput, max_bytes=PIN_INPUT_BODY_BYTES))
    ],
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
    research = (
        None
        if body.research is None
        else linked_research_brief(
            _composed_brief(body.research.model_dump(mode="json")), subject=subject
        )
    )

    def write(unit: StoreConnection) -> tuple[int, RunInputPinned]:
        if _owned_run(unit, case_id, run)[0]:
            raise Refusal(RefusalCode.RUN_INPUT_ALREADY_PINNED)
        source = snapshot_in(unit, case_id)
        try:
            pin = pin_run_input_in(
                unit, run, source.version, bundle, research, subject=subject
            )
        except Refusal as refused:
            brief = Brief(bundle, run, research, subject)
            if refused.code is RefusalCode.RUN_INPUT_INVALID and brief_refused(
                unit, brief
            ):
                raise Refusal(RefusalCode.RESEARCH_BRIEF_INVALID) from None
            raise
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


type _Json = str | int | float | bool | None | list[_Json] | dict[str, _Json]


def _composed_brief(brief: dict[str, Any]) -> dict[str, Any]:
    """The caller's brief with every string in it composed (NFC) and held to
    the boundary's rules, as every other text a command takes is
    (`BoundaryText`, W4): text pasted from a PDF often arrives decomposed, and
    the store keeps a brief only as NFC. A control or bidi character is
    `BOUNDARY_TEXT_INVALID`."""
    return {key: _composed(value) for key, value in brief.items()}


def _composed(value: _Json) -> _Json:
    if isinstance(value, str):
        return BoundaryText.of(value).value
    if isinstance(value, dict):
        return {key: _composed(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_composed(item) for item in value]
    return value


@dataclass(frozen=True, slots=True)
class Brief:
    """A pin's research brief as the caller sent it, linked to its subject,
    with what judges it: the bundle and the run it is pinned to."""

    bundle: Bundle
    run: UUID
    research: dict[str, Any] | None
    subject: RunSubject


def brief_refused(conn: StoreConnection, brief: Brief) -> bool:
    """Whether the brief itself is what a pin refused `RUN_INPUT_INVALID` (W4).

    The store answers every refused input with that one code, which is right
    for the stored input it guards and wrong for the caller's own brief -- an
    empty field, an impossible date, a consumer the pathway does not select,
    a brief on a route no CP-DR node reads, or none on one that needs it -- so
    a refused pin asks the store's own two rules again, over the pinned route,
    for the brief alone (`research_text`, `bound_research_brief`) and for its
    absence (a CP-DR route requires one, as `pin_run_input_in` says). Asked
    only once the pin has refused, so a pin that succeeds pays nothing.
    """
    pinned = route_pin(conn, brief.run)
    created = conn.execute(
        "SELECT created_at FROM runs WHERE run_id=%s", (brief.run,)
    ).fetchone()
    if pinned is None or created is None:
        return False
    route = pinned[0]
    if brief.research is None:
        return (route.profile_id, route.selection_id) in ADAPTER_ROUTES and any(
            node.module_id == RESEARCH_MODULE for node in route.nodes
        )
    try:
        research_text(brief.research)
        bound_research_brief(
            cached_contract(brief.bundle),
            catalog(brief.bundle),
            brief=brief.research,
            route=route,
            subject=brief.subject,
            run_id=cos_run_id(brief.run, created[0]),
            cp0_sha256=UNANCHORED_CP0,
            authority_sha256=authority_bundle_sha256(brief.bundle),
        )
    except Refusal as refused:
        if refused.code is not RefusalCode.RUN_INPUT_INVALID:
            raise
        return True
    return False


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

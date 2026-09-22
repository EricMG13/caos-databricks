"""Start, retry and cancel (Task 4.2 decisions 1, 2 and 7).

These are the only commands that write `run_work`, and none of them calls a
provider: a command enqueues, and the worker's own `execution_input` rechecks
authority before every attempt (authority trace T8). Each is one governed unit
through `run_command` -- state, run event, work row, audit event and receipt
commit together or not at all (T15).

Start and retry classify inside the unit, under the case and run locks, in
decision 7's order, so a caller's mistake is a 409 and never the 503 that
`execution_input` would give a foreign pin (T13):

1. No pin: `RUN_INPUT_NOT_PINNED`.
2. The pin's build, manifest or adapter is not this process's:
   `ORCHESTRATION_BUILD_MOVED`.
3. `execution_input`: the run is not RUNNING, a pinned source is withdrawn, or
   a gate is not approved by a live APPROVER (T4, T6).
4. The verified pin's fingerprint is not the one the caller saw:
   `COMMAND_EXPECTATION_STALE`.
5. `enqueue_run` (`RUN_ALREADY_STARTED`) or `requeue_run` (`RUN_NOT_STOPPED`).

Cancel needs no authority beyond standing: a run with no work row is queued and
cancelled in the same unit, so it ends CANCELLED before any worker can see it.
A replayed key answers its stored receipt before any of this runs (T12).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel

from caos import methodology
from caos.api.commands._request import (
    CommandRequest,
    Key,
    governed,
    json_body,
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
from caos.api.wire import CancelRun, RetryRun, RunWork, StartRun, WorkView
from caos.methodology.bundle import Bundle
from caos.refusals import Refusal, RefusalCode
from caos.store import RunStatus, StoreConnection
from caos.store.audit import GovernedAction
from caos.store.events import lock_run
from caos.store.gates import execution_input
from caos.store.members import Standing
from caos.store.work import enqueue_run, request_cancel, requeue_run

# Measured on the costliest success, cancel of an unqueued run: standing, the
# receipt lookup, the governed unit's case lock, chain head and standing, the
# twin lookup, the run's owner, three `lock_run`s, the queue insert, the cancel
# and its run event, the receipt read-back, the receipt and the audit link.
# Start and retry spend 32 (`execution_input`'s verified pin reads).
IO_BUDGET = 35

router = APIRouter()

_RUN_PATH = "/api/v1/cases/{case_id}/runs/{run_id}"
Writer = Annotated[Standing, Depends(require_case_writer)]

# `run_id: RunPath` is declared after `_standing` on every route here: the
# run id is read after visibility, so a stranger learns nothing from it.


@router.post(f"{_RUN_PATH}/start", status_code=202, dependencies=[IDENTITY_FIRST])
def start_run(  # noqa: PLR0913 -- decision 2's dependency order
    actor: Caller,
    key: Key,
    _standing: Writer,
    run_id: RunPath,
    body: Annotated[StartRun, Depends(json_body(StartRun))],
    case_id: CasePath,
    conn: Store,
    bundle: Methodology,
) -> Response:
    return _queue(conn, actor.user_id, case_id, run_id, key, body, bundle)


@router.post(f"{_RUN_PATH}/retry", status_code=202, dependencies=[IDENTITY_FIRST])
def retry_run(  # noqa: PLR0913 -- decision 2's dependency order
    actor: Caller,
    key: Key,
    _standing: Writer,
    run_id: RunPath,
    body: Annotated[RetryRun, Depends(json_body(RetryRun))],
    case_id: CasePath,
    conn: Store,
    bundle: Methodology,
) -> Response:
    return _queue(conn, actor.user_id, case_id, run_id, key, body, bundle)


@router.post(f"{_RUN_PATH}/cancel", status_code=202, dependencies=[IDENTITY_FIRST])
def cancel_run(  # noqa: PLR0913 -- decision 2's dependency order
    actor: Caller,
    key: Key,
    _standing: Writer,
    run_id: RunPath,
    body: Annotated[CancelRun, Depends(json_body(CancelRun))],
    case_id: CasePath,
    conn: Store,
) -> Response:
    def write(unit: StoreConnection) -> tuple[int, BaseModel]:
        _require_owned(unit, case_id, run_id)
        if lock_run(unit, run_id) is not RunStatus.RUNNING:
            raise Refusal(RefusalCode.RUN_NOT_RUNNING)
        state = _work_state(unit, run_id)
        if state == "DONE":
            raise Refusal(RefusalCode.RUN_NOT_RUNNING)
        if state is None:
            enqueue_run(unit, run_id)
        if not request_cancel(unit, run_id):
            raise Refusal(RefusalCode.RUN_CANCEL_REQUESTED)
        return 202, _receipt(unit, run_id)

    return _command(
        conn, actor.user_id, case_id, run_id, key, "CANCEL_RUN", body, write, {}
    )


def _queue(  # noqa: PLR0913 -- one start or retry, positional
    conn: StoreConnection,
    actor_id: UUID,
    case_id: UUID,
    run_id: UUID,
    key: UUID,
    body: StartRun | RetryRun,
    bundle: Bundle,
) -> Response:
    requeue = isinstance(body, RetryRun)

    def write(unit: StoreConnection) -> tuple[int, BaseModel]:
        _require_owned(unit, case_id, run_id)
        _require_this_build(unit, run_id, bundle)
        pin, _route = execution_input(unit, run_id, bundle)
        if pin.input_fingerprint != body.input_fingerprint:
            raise Refusal(RefusalCode.COMMAND_EXPECTATION_STALE)
        if requeue and not requeue_run(unit, run_id):
            raise Refusal(RefusalCode.RUN_NOT_STOPPED)
        if not requeue and not enqueue_run(unit, run_id):
            raise Refusal(RefusalCode.RUN_ALREADY_STARTED)
        return 202, _receipt(unit, run_id)

    return _command(
        conn,
        actor_id,
        case_id,
        run_id,
        key,
        "RETRY_RUN" if requeue else "START_RUN",
        body,
        write,
        {"input_fingerprint": body.input_fingerprint},
    )


def _command(  # noqa: PLR0913 -- one command's identity and unit, positional
    conn: StoreConnection,
    actor_id: UUID,
    case_id: UUID,
    run_id: UUID,
    key: UUID,
    command: str,
    body: BaseModel,
    write: Callable[[StoreConnection], tuple[int, BaseModel]],
    payload: dict[str, str],
) -> Response:
    unit = {"run_id": str(run_id), **payload}
    # One literal per call site: `tests/test_event_names.py` reads the action set.
    action = {
        "START_RUN": GovernedAction(
            case_id, actor_id, "RUN_ENQUEUED", Standing.WRITER, unit
        ),
        "RETRY_RUN": GovernedAction(
            case_id, actor_id, "RUN_REQUEUED", Standing.WRITER, unit
        ),
        "CANCEL_RUN": GovernedAction(
            case_id, actor_id, "RUN_CANCEL_REQUESTED", Standing.WRITER, unit
        ),
    }[command]
    return governed(
        conn,
        scope=case_id,
        key=key,
        request=CommandRequest(
            command, case_id, run_id, None, body.model_dump(mode="json")
        ),
        action=action,
        write=write,
        model=RunWork,
    )


def _require_owned(conn: StoreConnection, case_id: UUID, run_id: UUID) -> None:
    """A run of another case is as unknown as a run that does not exist."""
    row = conn.execute(
        "SELECT case_id FROM runs WHERE run_id = %s", (run_id,)
    ).fetchone()
    if row is None or UUID(str(row[0])) != case_id:
        raise Refusal(RefusalCode.RUN_NOT_FOUND)


def _require_this_build(conn: StoreConnection, run_id: UUID, bundle: Bundle) -> None:
    """Classify a missing or foreign pin before `execution_input` verifies it.

    The raw row only classifies; the fingerprint compared later is the one
    `execution_input` returns from the verified pin.
    """
    row = conn.execute(
        "SELECT build_id, manifest_sha256, adapter_version FROM run_inputs"
        " WHERE run_id = %s",
        (run_id,),
    ).fetchone()
    if row is None:
        raise Refusal(RefusalCode.RUN_INPUT_NOT_PINNED)
    if tuple(row) != (
        bundle.build_id,
        bundle.manifest_sha256,
        methodology.CANONICAL_ADAPTER_VERSION,
    ):
        raise Refusal(RefusalCode.ORCHESTRATION_BUILD_MOVED)


def _work_state(conn: StoreConnection, run_id: UUID) -> str | None:
    """The work row's state under the caller's run lock, or None when unqueued.

    Only enqueue and terminal transitions (both under the run lock) create a row
    or mark it DONE, so neither answer can move before `request_cancel` reads it.
    """
    row = conn.execute(
        "SELECT state FROM run_work WHERE run_id = %s", (run_id,)
    ).fetchone()
    return None if row is None else str(row[0])


def _receipt(conn: StoreConnection, run_id: UUID) -> RunWork:
    """The run's status and work row as this unit leaves them."""
    row = conn.execute(
        "SELECT r.status, w.state, w.stop_code, w.cancel_requested_at IS NOT NULL"
        " FROM runs r JOIN run_work w USING (run_id) WHERE r.run_id = %s",
        (run_id,),
    ).fetchone()
    if row is None:
        raise Refusal(RefusalCode.STORE_UNAVAILABLE)
    return RunWork.model_validate(
        {
            "run_id": run_id,
            "run_status": row[0],
            "work": WorkView.model_validate(
                {"state": row[1], "stop_code": row[2], "cancel_requested": row[3]}
            ),
        }
    )

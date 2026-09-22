"""`Chrome.actions`: what each command would answer, judged from a read's facts.

Task 4.2 decision 10. Pure functions over facts the section reads already hold,
each action's checks in the order its command makes them (decision 7), so an
action refused here names the code its command would answer now. Advisory and
granting nothing: the command rechecks every one of these at commit, under the
case lock and live standing ("Persona is not authority"). A fact a read cannot
hold -- a body the client has not yet written, a digest it has not yet seen --
is the command's to refuse, never assumed here.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from caos.api.identity import GlobalRole
from caos.api.wire import CLEARS, ActionName, ActionView, RefusalBody
from caos.refusals import RefusalCode
from caos.store.members import Standing, satisfies

IO_BUDGET = 0

_C = RefusalCode
_A = ActionName


@dataclass(frozen=True, slots=True)
class RunFacts:
    """The displayed run, as the Run section read it."""

    running: bool
    route_pinned: bool
    input_pinned: bool
    this_build: bool  # the pin's build, manifest and adapter are this process's
    sources_live: bool
    gates_released: bool
    adapter_route: bool
    work_state: str | None
    cancel_requested: bool


def directory_actions(role: GlobalRole) -> list[ActionView]:
    """Create case needs only a global role that may write."""
    return [_view(_A.CREATE_CASE, [(role is GlobalRole.READER, _C.NOT_AUTHORISED)])]


def membership_actions(role: GlobalRole, standing: Standing) -> list[ActionView]:
    """Grant and revoke on one case: both commands take the ADMIN floor. Which
    member is named is the command's to refuse at commit."""
    admin = _floor(role, standing, Standing.ADMIN)
    return [_view(_A.GRANT_STANDING, admin), _view(_A.REVOKE_STANDING, admin)]


def upload_actions(
    role: GlobalRole, standing: Standing, live_sources: int
) -> list[ActionView]:
    """Admission, and the withdrawal that is invariant 1's second half.

    A case with nothing live has nothing to withdraw; which source is named is
    the command's to refuse, with the same code, from the path. `live_sources`
    is counted from what the section listed, which `SOURCES_MAX` bounds, so a
    truncated listing can under-claim -- the control is then shown refused on a
    case that does have live sources, which is the fail-closed direction and is
    the command's to correct at commit."""
    writer = _floor(role, standing, Standing.WRITER)
    return [
        _view(_A.ADMIT_SOURCES, writer),
        _view(
            _A.WITHDRAW_SOURCE,
            [*writer, (live_sources == 0, _C.EVIDENCE_NOT_AVAILABLE)],
        ),
    ]


@dataclass(frozen=True, slots=True)
class FilingFacts:
    """One saved revision's filing state, as the Report section read it.

    `actor_signed` and `actor_froze` are about the caller being shown the
    controls: the three-actor rule is checked at commit under the case lock,
    and saying so here only keeps a control from being offered to someone it
    would refuse.
    """

    signed: bool
    frozen: bool
    filed: bool
    actor_signed: bool
    actor_froze: bool
    # The revision is the run's newest. The save posts the served revision as
    # the head its draft was composed against, so on any other it is refused.
    head: bool


def report_actions(
    role: GlobalRole,
    standing: Standing,
    filing: FilingFacts | None,
    underivable: RefusalCode | None = None,
) -> list[ActionView]:
    """The Report section's four, in each command's own order (decision 7).

    They sit on Report rather than Committee because Committee refuses a
    revision that is not frozen, so it can never offer the sign or the freeze
    that would make it one.

    `filing` is `None` when the run has no saved revision. The save is then the
    one act that needs none -- it posts no expected head -- and `underivable`
    is the code the run's payload derivation refused with, which is the save's
    own answer past its floor. The other three name a revision their commands
    would not find.
    """
    writer = _floor(role, standing, Standing.WRITER)
    approver = _floor(role, standing, Standing.APPROVER)
    if filing is None:
        missing = [*approver, (True, _C.DELIVERABLE_NOT_FOUND)]
        derived = [] if underivable is None else [(True, underivable)]
        return [
            _view(_A.SAVE_REVISION, [*writer, *derived]),
            *(
                _view(action, missing)
                for action in (
                    _A.SIGN_OPINION,
                    _A.FREEZE_DELIVERABLE,
                    _A.FILE_DELIVERABLE,
                )
            ),
        ]
    return [
        _view(
            _A.SAVE_REVISION,
            [*writer, (not filing.head, _C.COMMAND_EXPECTATION_STALE)],
        ),
        _view(
            _A.SIGN_OPINION,
            [
                *approver,
                (filing.frozen, _C.DELIVERABLE_ALREADY_FROZEN),
                (filing.actor_signed, _C.DELIVERABLE_ALREADY_SIGNED),
            ],
        ),
        _view(
            _A.FREEZE_DELIVERABLE,
            [
                *approver,
                (filing.frozen, _C.DELIVERABLE_ALREADY_FROZEN),
                (not filing.signed, _C.DELIVERABLE_NOT_SIGNED),
                (filing.actor_signed, _C.APPROVER_NOT_INDEPENDENT),
            ],
        ),
        _view(
            _A.FILE_DELIVERABLE,
            [
                *approver,
                (not filing.frozen, _C.DELIVERABLE_NOT_FROZEN),
                (not filing.signed, _C.DELIVERABLE_NOT_SIGNED),
                (
                    filing.actor_signed or filing.actor_froze,
                    _C.APPROVER_NOT_INDEPENDENT,
                ),
                (filing.filed, _C.DELIVERABLE_ALREADY_FILED),
            ],
        ),
    ]


def run_actions(
    role: GlobalRole, standing: Standing, run: RunFacts | None, live_sources: int
) -> list[ActionView]:
    """The Run section's seven actions; run-scoped ones need a displayed run."""
    writer = _floor(role, standing, Standing.WRITER)
    approver = _floor(role, standing, Standing.APPROVER)
    missing = [(run is None, _C.RUN_NOT_FOUND)]
    if run is None:
        scoped = {action: missing for action in _RUN_SCOPED}
    else:
        scoped = _run_checks(run, live_sources)
    return [
        _view(_A.CREATE_RUN, writer),
        *(
            _view(action, [*(approver if action in _APPROVALS else writer), *checks])
            for action, checks in scoped.items()
        ),
    ]


_Checks = list[tuple[bool, RefusalCode]]
_APPROVALS = (_A.APPROVE_SOURCE_SET, _A.APPROVE_RESEARCH_PLAN)
_RUN_SCOPED = (
    _A.PIN_RUN_INPUT,
    *_APPROVALS,
    _A.START_RUN,
    _A.RETRY_RUN,
    _A.CANCEL_RUN,
)


def _run_checks(run: RunFacts, live_sources: int) -> dict[ActionName, _Checks]:
    pin: _Checks = [
        (run.input_pinned, _C.RUN_INPUT_ALREADY_PINNED),  # `pin_input`'s ownership
        (live_sources == 0, _C.SOURCE_PACK_EMPTY),  # `snapshot_in`
        (not run.route_pinned, _C.RUN_INPUT_INVALID),  # `pin_run_input_in`
        (not run.running, _C.RUN_NOT_RUNNING),
    ]
    approve: _Checks = [
        (not run.input_pinned, _C.RUN_INPUT_NOT_PINNED),
        (not run.running, _C.RUN_NOT_RUNNING),  # `release_gate_in`
        (not run.sources_live, _C.EVIDENCE_NOT_AVAILABLE),
    ]
    queue: _Checks = [
        (not run.input_pinned, _C.RUN_INPUT_NOT_PINNED),
        (not run.this_build, _C.ORCHESTRATION_BUILD_MOVED),
        (not run.running, _C.RUN_NOT_RUNNING),  # `execution_input`
        (not run.sources_live, _C.EVIDENCE_NOT_AVAILABLE),
        (not run.gates_released, _C.GATE_APPROVAL_MISMATCH),
        (not run.adapter_route, _C.HANDOFF_MODULE_UNSUPPORTED),
    ]
    return {
        _A.PIN_RUN_INPUT: pin,
        _A.APPROVE_SOURCE_SET: approve,
        _A.APPROVE_RESEARCH_PLAN: approve,
        _A.START_RUN: [*queue, (run.work_state is not None, _C.RUN_ALREADY_STARTED)],
        _A.RETRY_RUN: [
            *queue,
            # `requeue_run`: a stopped row with no cancel requested.
            (
                run.work_state != "STOPPED" or run.cancel_requested,
                _C.RUN_NOT_STOPPED,
            ),
        ],
        _A.CANCEL_RUN: [
            (not run.running or run.work_state == "DONE", _C.RUN_NOT_RUNNING),
            (
                run.work_state == "CLAIMED" and run.cancel_requested,
                _C.RUN_CANCEL_REQUESTED,
            ),
        ],
    }


def _floor(role: GlobalRole, standing: Standing, floor: Standing) -> _Checks:
    """Decision 2's order for a visible case: global role, then the floor."""
    return [
        (role is GlobalRole.READER, _C.NOT_AUTHORISED),
        (not satisfies(standing, floor), _C.NOT_AUTHORISED),
    ]


def _view(action: ActionName, checks: Iterable[tuple[bool, RefusalCode]]) -> ActionView:
    code = next((code for refused, code in checks if refused), None)
    refusal = None if code is None else RefusalBody(code=code, clears=CLEARS[code])
    return ActionView(action=action, refusal=refusal)

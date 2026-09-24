"""Task 4.2 slice 4.2g: `Chrome.actions` against the commands themselves.

Each action is judged by the section document read immediately before it is
sent: an action shown available must succeed, and an action shown refused must
refuse with exactly the code shown. The journey walks a run through every state
the Run section distinguishes, so no advertised answer goes unchecked.
Availability grants nothing: the command rechecks at commit.
"""

from __future__ import annotations

from collections.abc import Iterator
from uuid import UUID, uuid4

import pytest
from command_fixtures import command_client, command_headers, member
from fastapi.testclient import TestClient
from httpx2 import Response

from caos import methodology
from caos.api.commands.availability import (
    FilingFacts,
    RunFacts,
    directory_actions,
    membership_actions,
    report_actions,
    run_actions,
    upload_actions,
)
from caos.api.identity import TRUST_SWITCH, TRUSTED, GlobalRole
from caos.api.wire import (
    ActionName,
    ActionView,
    DirectoryDocument,
    RefusalBody,
    RunSectionDocument,
    UploadDocument,
)
from caos.boundary_text import BoundaryText
from caos.refusals import RefusalCode
from caos.store import StoreConnection
from caos.store.gates import sources_live
from caos.store.members import Standing, revoke
from caos.store.work import MAX_QUEUED_RUNS_PER_ACTOR, claim_run, stop

__all__ = ["command_client"]

A = ActionName
ROUTE = {
    "profile_id": "LITE_CREDIT_22",
    "selection_id": "LITE_EARNINGS_UPDATE",
    "supersedes": None,
    "model_extension": False,
}
SUBJECT = {
    "issuer_id": "EXAMPLE",
    "issuer_name": "Example Holdings plc",
    "reporting_period": "FY2025",
    "analysis_date": "2026-09-08",
}
ZERO = "0" * 64
GATE_SLUG = {
    A.APPROVE_SOURCE_SET: "source-set",
    A.APPROVE_RESEARCH_PLAN: "research-plan",
}
TAIL = {A.START_RUN: "start", A.RETRY_RUN: "retry", A.CANCEL_RUN: "cancel"}


@pytest.fixture(autouse=True)
def _the_role_header_decides(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """The development deployment: no edge token, so no groups are read, and a
    role above READER is the switched-on role header or nothing."""
    monkeypatch.setenv(TRUST_SWITCH, TRUSTED)
    yield


class _Journey:
    """One actor's view of one case, and the commands it sends."""

    def __init__(
        self, client: TestClient, case_id: UUID, user: UUID, role: str
    ) -> None:
        self.client, self.case_id, self.user, self.role = client, case_id, user, role
        self.run_id: UUID | None = None

    def _headers(self) -> dict[str, str]:
        return command_headers(self.user, role=self.role)

    def document(self) -> RunSectionDocument:
        query = "" if self.run_id is None else f"?run={self.run_id}"
        answer = self.client.get(
            f"/api/v1/cases/{self.case_id}/run{query}", headers=self._headers()
        )
        assert answer.status_code == 200, answer.text
        return RunSectionDocument.model_validate(answer.json())

    def _digests(self, slug: str = "source-set") -> dict[str, str]:
        """The digests a preview shows this actor, or stale ones when it shows none."""
        preview = self.client.get(
            f"/api/v1/cases/{self.case_id}/runs/{self.run_id}/gates/{slug}/preview",
            headers=self._headers(),
        )
        if preview.status_code != 200:
            return {"preview_sha256": ZERO, "input_fingerprint": ZERO}
        return {k: preview.json()[k] for k in ("preview_sha256", "input_fingerprint")}

    def send(self, action: ActionName) -> Response:
        runs = f"/api/v1/cases/{self.case_id}/runs"
        run = f"{runs}/{self.run_id or uuid4()}"
        body: dict[str, object]
        if action is A.CREATE_RUN:
            path, body = runs, dict(ROUTE)
        elif action is A.PIN_RUN_INPUT:
            path, body = f"{run}/input", {"subject": SUBJECT, "research": None}
        elif action in GATE_SLUG:
            slug = GATE_SLUG[action]
            path, body = f"{run}/gates/{slug}/approval", dict(self._digests(slug))
        elif action is A.CANCEL_RUN:
            path, body = f"{run}/cancel", {}
        else:
            fingerprint = self._digests()["input_fingerprint"]
            path, body = f"{run}/{TAIL[action]}", {"input_fingerprint": fingerprint}
        answer: Response = self.client.post(path, headers=self._headers(), json=body)
        return answer

    def check(self, *actions: ActionName) -> list[str]:
        """Send each action as the document read just before it judged it.

        Returns each answer as `status code`, for the reader of the journey."""
        answers = []
        for action in actions:
            [shown] = [v for v in self.document().chrome.actions if v.action is action]
            answer = self.send(action)
            if shown.refusal is None:
                assert answer.status_code in (200, 201, 202), (action, answer.text)
                if action is A.CREATE_RUN:
                    self.run_id = UUID(answer.json()["run_id"])
            else:
                assert answer.json()["code"] == shown.refusal.code, (action, shown)
            answers.append(f"{action} {shown.refusal and shown.refusal.code}")
        return answers


def _admit(client: TestClient, case_id: UUID, user: UUID) -> Response:
    answer: Response = client.post(
        f"/api/v1/cases/{case_id}/sources",
        headers=command_headers(user),
        files=[("document", ("report.txt", b"Total debt was USD 1,240.0m\n", "x"))],
    )
    return answer


def _upload(
    client: TestClient, case_id: UUID, user: UUID, role: str
) -> list[ActionView]:
    answer = client.get(
        f"/api/v1/cases/{case_id}/upload", headers=command_headers(user, role=role)
    )
    return list(UploadDocument.model_validate(answer.json()).chrome.actions)


def _withdraw(
    client: TestClient, case_id: UUID, user: UUID, source_id: object
) -> Response:
    answer: Response = client.post(
        f"/api/v1/cases/{case_id}/sources/{source_id}/withdrawal",
        headers=command_headers(user),
        json={},
    )
    return answer


def _stop_the_claimed_run(conn: StoreConnection) -> None:
    conn.rollback()  # the section read's transaction; a claim commits alone
    lease = claim_run(conn, worker=BoundaryText.of("w"), lease_seconds=60)
    assert lease is not None
    stop(conn, lease, RefusalCode.CITATION_NOT_LOCATED)
    conn.commit()


EVERY_RUN_ACTION = (
    A.PIN_RUN_INPUT,
    A.APPROVE_SOURCE_SET,
    A.APPROVE_RESEARCH_PLAN,
    A.START_RUN,
    A.RETRY_RUN,
    A.CANCEL_RUN,
)
TO_START = (A.PIN_RUN_INPUT, A.APPROVE_SOURCE_SET, A.APPROVE_RESEARCH_PLAN, A.START_RUN)


def test_every_available_action_succeeds_and_every_refused_action_refuses_with_its_code(
    command_client: TestClient,
    case: tuple[StoreConnection, UUID],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn, case_id = case
    lead = _Journey(
        command_client, case_id, member(conn, case_id, Standing.ADMIN), "ANALYST"
    )

    # No run and no source: run-scoped actions are RUN_NOT_FOUND; then a run.
    assert lead.check(*EVERY_RUN_ACTION)[0].endswith("RUN_NOT_FOUND")
    lead.check(A.CREATE_RUN)
    assert lead.check(*EVERY_RUN_ACTION)[0].endswith("SOURCE_PACK_EMPTY")
    lead.check(*EVERY_RUN_ACTION)  # the cancelled run refuses everything

    # Upload's two actions, for a writer and a reader. Withdrawal is shown
    # refused while nothing is live, available once a source is, and each
    # answer is the code the command gives.
    admit, withdraw = _upload(command_client, case_id, lead.user, "ANALYST")
    assert admit.refusal is None
    assert withdraw.refusal is not None and withdraw.refusal.code == (
        "EVIDENCE_NOT_AVAILABLE"
    )
    assert (
        _withdraw(command_client, case_id, lead.user, uuid4()).json()["code"]
        == withdraw.refusal.code
    )
    assert _admit(command_client, case_id, lead.user).status_code == 201
    reader = member(conn, case_id, Standing.READER)
    for refused in _upload(command_client, case_id, reader, "ANALYST"):
        assert refused.refusal is not None
        assert refused.refusal.code == "NOT_AUTHORISED", refused.action
    assert _admit(command_client, case_id, reader).json()["code"] == "NOT_AUTHORISED"

    # A run walked to its queue, stopped, retried and cancelled.
    lead.check(A.CREATE_RUN, *TO_START, A.RETRY_RUN, A.START_RUN)
    assert lead.document().body.run.work.state == "QUEUED"  # type: ignore[union-attr]
    _stop_the_claimed_run(conn)
    lead.check(A.START_RUN, A.PIN_RUN_INPUT, A.RETRY_RUN, A.CANCEL_RUN)
    lead.check(*EVERY_RUN_ACTION)
    assert lead.document().body.run.status == "CANCELLED"  # type: ignore[union-attr]

    # A claimed run: cancel requests once, then is refused.
    lead.check(A.CREATE_RUN, *TO_START)
    conn.rollback()
    assert claim_run(conn, worker=BoundaryText.of("w"), lease_seconds=60) is not None
    conn.commit()
    assert lead.check(A.CANCEL_RUN, A.CANCEL_RUN)[1].endswith("RUN_CANCEL_REQUESTED")

    # Another adapter, then a withdrawn source: conflicts, never faults.
    lead.check(A.CREATE_RUN, A.PIN_RUN_INPUT, A.APPROVE_SOURCE_SET)
    adapter = methodology.CANONICAL_ADAPTER_VERSION
    monkeypatch.setattr(methodology, "CANONICAL_ADAPTER_VERSION", "another-adapter")
    assert lead.check(A.START_RUN)[0].endswith("ORCHESTRATION_BUILD_MOVED")
    monkeypatch.setattr(methodology, "CANONICAL_ADAPTER_VERSION", adapter)
    assert lead.check(A.START_RUN)[0].endswith("GATE_APPROVAL_MISMATCH")
    [source] = conn.execute("SELECT source_id FROM sources").fetchall()[0]
    conn.rollback()
    _, live = _upload(command_client, case_id, lead.user, "ANALYST")
    assert live.refusal is None, "one live source: the control is offered"
    assert _withdraw(command_client, case_id, lead.user, source).status_code == 200
    assert lead.run_id is not None and not sources_live(conn, lead.run_id)
    conn.rollback()
    answers = lead.check(A.APPROVE_RESEARCH_PLAN, A.START_RUN, A.RETRY_RUN)
    assert all(answer.endswith("EVIDENCE_NOT_AVAILABLE") for answer in answers)

    # Below the floor, or a global READER holding WRITER standing: all refused.
    for user, role in ((reader, "ANALYST"), (member(conn, case_id), "READER")):
        viewer = _Journey(command_client, case_id, user, role)
        viewer.run_id = lead.run_id
        answers = viewer.check(A.CREATE_RUN, *EVERY_RUN_ACTION)
        assert all(answer.endswith("NOT_AUTHORISED") for answer in answers)


def test_served_role_and_actions_come_only_from_the_server(
    command_client: TestClient, case: tuple[StoreConnection, UUID]
) -> None:
    conn, case_id = case
    reader = member(conn, case_id, Standing.READER)
    # The groups header is the escalation a tokenless API must not believe: no
    # edge asserted it, so it names no role however well-formed it is. A role
    # header is not the claim to make here -- the switch above is what serves
    # this app, and under it that header is the deployment's word, not this
    # client's.
    claimed = {
        **command_headers(reader, role="READER"),
        "x-forwarded-groups": "caos-admins",
        "x-caos-standing": "ADMIN",
    }

    asked = command_client.get(
        f"/api/v1/cases/{case_id}/run?role=ADMIN&standing=ADMIN", headers=claimed
    )
    directory = command_client.get("/api/v1/directory", headers=claimed)

    document = RunSectionDocument.model_validate(asked.json())
    served = document.chrome.served_role
    assert (served.global_role, served.standing) == ("READER", "READER")
    assert {view.refusal.code for view in document.chrome.actions if view.refusal} == {
        "NOT_AUTHORISED"
    }
    assert all(view.refusal for view in document.chrome.actions)
    [create] = DirectoryDocument.model_validate(directory.json()).chrome.actions
    assert create.refusal is not None and create.refusal.code == "NOT_AUTHORISED"

    # Shown available, then standing is lost: the command decides at commit.
    writer = _Journey(command_client, case_id, member(conn, case_id), "ANALYST")
    assert writer.check(A.CREATE_RUN) == ["CREATE_RUN None"]
    [shown] = [v for v in writer.document().chrome.actions if v.action is A.CREATE_RUN]
    assert shown.refusal is None
    revoke(conn, case_id=case_id, user_id=writer.user)
    conn.commit()
    lost = writer.send(A.CREATE_RUN)
    assert (lost.status_code, lost.json()["code"]) == (404, "CASE_NOT_FOUND")


def test_the_pure_judgements_follow_each_command_order() -> None:
    """The functions the reads call, over facts no store could hold at once."""
    facts = RunFacts(
        running=False,
        route_pinned=True,
        input_pinned=True,
        this_build=False,
        sources_live=False,
        gates_released=False,
        adapter_route=True,
        work_state="CLAIMED",
        cancel_requested=True,
    )

    judged = {
        view.action: view.refusal and view.refusal.code
        for view in run_actions(GlobalRole.ANALYST, Standing.APPROVER, facts, 1, 0)
    }

    assert judged == {
        A.CREATE_RUN: None,
        A.PIN_RUN_INPUT: "RUN_INPUT_ALREADY_PINNED",
        A.APPROVE_SOURCE_SET: "RUN_NOT_RUNNING",
        A.APPROVE_RESEARCH_PLAN: "RUN_NOT_RUNNING",
        A.START_RUN: "ORCHESTRATION_BUILD_MOVED",
        A.RETRY_RUN: "ORCHESTRATION_BUILD_MOVED",
        A.CANCEL_RUN: "RUN_NOT_RUNNING",
    }
    ready = RunFacts(
        running=True,
        route_pinned=True,
        input_pinned=True,
        this_build=True,
        sources_live=True,
        gates_released=True,
        adapter_route=True,
        work_state="STOPPED",
        cancel_requested=True,
    )
    [retry] = [
        view
        for view in run_actions(GlobalRole.ANALYST, Standing.WRITER, ready, 1, 0)
        if view.action is A.RETRY_RUN
    ]
    # `requeue_run` requeues only a stopped run with no cancel requested.
    assert retry.refusal is not None and retry.refusal.code == "RUN_NOT_STOPPED"
    assert [v.refusal for v in directory_actions(GlobalRole.ADMIN)] == [None]
    admit, withdraw = upload_actions(GlobalRole.ADMIN, Standing.READER, 1)
    assert admit.refusal is not None and admit.refusal.code == "NOT_AUTHORISED"
    assert withdraw.refusal is not None and withdraw.refusal.code == "NOT_AUTHORISED"
    [_admit, empty] = upload_actions(GlobalRole.ADMIN, Standing.WRITER, 0)
    assert empty.refusal is not None and empty.refusal.code == "EVIDENCE_NOT_AVAILABLE"


def test_a_full_queue_refuses_start_and_retry_as_the_commands_would() -> None:
    """N5's remainder (D46): `enqueue_run`/`requeue_run` refuse
    `QUEUED_RUNS_LIMIT_REACHED` once the actor already holds
    `MAX_QUEUED_RUNS_PER_ACTOR` runs queued or claimed -- the section now
    names that refusal instead of offering a Start or Retry the command
    would then refuse."""
    startable = RunFacts(
        running=True,
        route_pinned=True,
        input_pinned=True,
        this_build=True,
        sources_live=True,
        gates_released=True,
        adapter_route=True,
        work_state=None,
        cancel_requested=False,
    )
    retryable = RunFacts(
        running=True,
        route_pinned=True,
        input_pinned=True,
        this_build=True,
        sources_live=True,
        gates_released=True,
        adapter_route=True,
        work_state="STOPPED",
        cancel_requested=False,
    )
    for facts, action in ((startable, A.START_RUN), (retryable, A.RETRY_RUN)):
        under_cap = {
            view.action: view.refusal
            for view in run_actions(
                GlobalRole.ANALYST,
                Standing.WRITER,
                facts,
                1,
                MAX_QUEUED_RUNS_PER_ACTOR - 1,
            )
        }
        assert under_cap[action] is None
        at_cap = {
            view.action: view.refusal and view.refusal.code
            for view in run_actions(
                GlobalRole.ANALYST, Standing.WRITER, facts, 1, MAX_QUEUED_RUNS_PER_ACTOR
            )
        }
        assert at_cap[action] == "QUEUED_RUNS_LIMIT_REACHED"


def test_membership_is_offered_to_a_case_administrator_that_may_write() -> None:
    """O21: grant and revoke take the ADMIN floor, after the global role, the
    order both commands check them in."""
    A = ActionName
    assert [
        (view.action, view.refusal)
        for view in membership_actions(GlobalRole.ANALYST, Standing.ADMIN)
    ] == [(A.GRANT_STANDING, None), (A.REVOKE_STANDING, None)]
    for role, standing in (
        (GlobalRole.READER, Standing.ADMIN),
        (GlobalRole.ADMIN, Standing.APPROVER),
    ):
        assert {
            view.refusal and view.refusal.code
            for view in membership_actions(role, standing)
        } == {RefusalCode.NOT_AUTHORISED}, (role, standing)


def test_a_membership_action_the_directory_offers_is_answered_as_offered(
    command_client: TestClient, case: tuple[StoreConnection, UUID]
) -> None:
    """The Directory's judgement against the commands themselves: an ADMIN's
    offered grant and revoke commit, and a WRITER's refused grant is refused
    with the code the Directory named."""
    conn, case_id = case
    admin = member(conn, case_id, Standing.ADMIN)
    writer = member(conn, case_id, Standing.WRITER)
    newcomer = uuid4()

    def offered(user: UUID) -> dict[ActionName, RefusalBody | None]:
        answered = command_client.get(
            "/api/v1/directory", headers=command_headers(user)
        )
        document = DirectoryDocument.model_validate(answered.json())
        [row] = [row for row in document.body.cases if row.case_id == case_id]
        return {view.action: view.refusal for view in row.actions}

    assert offered(admin) == {
        ActionName.GRANT_STANDING: None,
        ActionName.REVOKE_STANDING: None,
    }
    granted = command_client.post(
        f"/api/v1/cases/{case_id}/members",
        json={"user_id": str(newcomer), "standing": "READER"},
        headers=command_headers(admin),
    )
    assert granted.status_code == 201, granted.text
    revoked = command_client.post(
        f"/api/v1/cases/{case_id}/members/{newcomer}/revocation",
        json={},
        headers=command_headers(admin),
    )
    assert revoked.status_code == 200, revoked.text

    refusal = offered(writer)[ActionName.GRANT_STANDING]
    assert refusal is not None
    refused = command_client.post(
        f"/api/v1/cases/{case_id}/members",
        json={"user_id": str(newcomer), "standing": "READER"},
        headers=command_headers(writer),
    )
    assert (refused.status_code, refused.json()["code"]) == (403, refusal.code)


def test_the_filing_controls_follow_each_command_order() -> None:
    """Task 12.1: the four Report actions, judged as their commands judge."""
    unsigned = FilingFacts(
        signed=False,
        frozen=False,
        filed=False,
        actor_signed=False,
        actor_froze=False,
        head=True,
    )
    judged = {
        view.action: view.refusal and view.refusal.code
        for view in report_actions(GlobalRole.ANALYST, Standing.APPROVER, unsigned)
    }
    assert judged == {
        A.SAVE_REVISION: None,
        A.SIGN_OPINION: None,
        A.FREEZE_DELIVERABLE: "DELIVERABLE_NOT_SIGNED",
        A.FILE_DELIVERABLE: "DELIVERABLE_NOT_FROZEN",
    }

    # The signer is shown neither the freeze nor the filing their own commit
    # would refuse; a third approver is shown the filing.
    signer = FilingFacts(
        signed=True,
        frozen=True,
        filed=False,
        actor_signed=True,
        actor_froze=False,
        head=True,
    )
    third = FilingFacts(
        signed=True,
        frozen=True,
        filed=False,
        actor_signed=False,
        actor_froze=False,
        head=True,
    )
    filed = FilingFacts(
        signed=True,
        frozen=True,
        filed=True,
        actor_signed=False,
        actor_froze=False,
        head=True,
    )
    for facts, expected in (
        (signer, ["DELIVERABLE_ALREADY_FROZEN", "APPROVER_NOT_INDEPENDENT"]),
        (third, ["DELIVERABLE_ALREADY_FROZEN", None]),
        (filed, ["DELIVERABLE_ALREADY_FROZEN", "DELIVERABLE_ALREADY_FILED"]),
    ):
        views = {
            view.action: view.refusal and view.refusal.code
            for view in report_actions(GlobalRole.ANALYST, Standing.APPROVER, facts)
        }
        assert [views[A.FREEZE_DELIVERABLE], views[A.FILE_DELIVERABLE]] == expected

    # Below the floor every one of them is the floor's refusal.
    reader = {
        view.refusal and view.refusal.code
        for view in report_actions(GlobalRole.ANALYST, Standing.READER, third)
    }
    assert reader == {"NOT_AUTHORISED"}


def test_save_revision_is_judged_against_the_runs_head() -> None:
    """The save posts the served revision as the head it was composed against,
    so a revision that is no longer the head offers a save its commit refuses
    `COMMAND_EXPECTATION_STALE` -- shown refused with that code instead."""
    superseded = FilingFacts(
        signed=False,
        frozen=False,
        filed=False,
        actor_signed=False,
        actor_froze=False,
        head=False,
    )
    [save, *_] = report_actions(GlobalRole.ANALYST, Standing.WRITER, superseded)
    assert save.refusal is not None
    assert save.refusal.code == "COMMAND_EXPECTATION_STALE"


def test_sign_freeze_and_file_are_each_judged_against_the_runs_head() -> None:
    """CF-026: the route refuses sign, freeze and file of a superseded
    revision before any of the three acts on it, under exactly the code
    `save` already answers a stale draft with, so the Report shows the same
    thing whatever state the superseded revision was otherwise in."""
    for facts in (
        FilingFacts(
            signed=False,
            frozen=False,
            filed=False,
            actor_signed=False,
            actor_froze=False,
            head=False,
        ),
        # Even a fully filed revision is refused this way once superseded --
        # the stale check runs first, ahead of every filing-state check.
        FilingFacts(
            signed=True,
            frozen=True,
            filed=True,
            actor_signed=False,
            actor_froze=False,
            head=False,
        ),
    ):
        judged = {
            view.action: view.refusal and view.refusal.code
            for view in report_actions(GlobalRole.ANALYST, Standing.APPROVER, facts)
        }
        assert judged[A.SIGN_OPINION] == "COMMAND_EXPECTATION_STALE"
        assert judged[A.FREEZE_DELIVERABLE] == "COMMAND_EXPECTATION_STALE"
        assert judged[A.FILE_DELIVERABLE] == "COMMAND_EXPECTATION_STALE"


def test_a_run_with_no_revision_offers_its_first_save_and_nothing_else() -> None:
    """No revision saved: the save needs none, and the other three name one
    their command would not find. A save the run cannot derive is refused with
    the derivation's own code, which is the one its commit answers."""
    judged = {
        view.action: view.refusal and view.refusal.code
        for view in report_actions(GlobalRole.ANALYST, Standing.APPROVER, None)
    }
    assert judged == {
        A.SAVE_REVISION: None,
        A.SIGN_OPINION: "DELIVERABLE_NOT_FOUND",
        A.FREEZE_DELIVERABLE: "DELIVERABLE_NOT_FOUND",
        A.FILE_DELIVERABLE: "DELIVERABLE_NOT_FOUND",
    }
    [save, *_] = report_actions(
        GlobalRole.ANALYST,
        Standing.WRITER,
        None,
        underivable=RefusalCode.DELIVERABLE_PAYLOAD_INVALID,
    )
    assert save.refusal is not None
    assert save.refusal.code == "DELIVERABLE_PAYLOAD_INVALID"
    below = {
        view.refusal and view.refusal.code
        for view in report_actions(GlobalRole.READER, Standing.ADMIN, None)
    }
    assert below == {"NOT_AUTHORISED"}

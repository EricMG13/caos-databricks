"""The Run section document (Phase 4 Task 4.1, slice 4.1d).

`GET /api/v1/cases/{case_id}/run?run=` replaces the retired
`GET /api/runs/{run_id}`. The case is the authorisation resource: unknown,
unauthorised, revoked and malformed cases are one private 404, and a run the
case does not own is the same `RUN_NOT_FOUND` as a run that does not exist.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any
from uuid import UUID, uuid4

import pytest
from canonical_fixtures import CanonicalCompletions
from fastapi.testclient import TestClient
from httpx2 import Response
from test_api_routes import (
    LITE,
    _answer,
    _as,
    _CountingConnection,
    _refused,
    _section,
    catalog,
    client,
    lite,
    run,
)
from test_canonical_execution import harness, route
from test_canonical_runtime import _module_provider, _run_route
from test_execution_freshness import _Harness

from caos.api import app as app_module
from caos.api.identity import TRUST_SWITCH
from caos.api.reads import run as run_read
from caos.api.wire import BlockedByView, DirectoryDocument, RunSectionDocument
from caos.boundary_text import BoundaryText
from caos.graph.route import ResolvedRoute, resolve_route, route_digest
from caos.refusals import Refusal, RefusalCode
from caos.store import StoreConnection
from caos.store import routes as store_routes
from caos.store.members import Standing, grant, revoke
from caos.store.routes import pin_route
from caos.store.runs import create_case, start_run
from caos.store.work import claim_run, enqueue_run, request_cancel, stop

__all__ = ["catalog", "client", "harness", "lite", "route", "run"]


def _document(response: Response) -> RunSectionDocument:
    assert response.status_code == 200, response.json()
    return RunSectionDocument.model_validate(response.json())


def test_the_retired_run_document_route_is_absent(
    client: TestClient, run: tuple[UUID, UUID]
) -> None:
    """Decision 4: `/api/runs/{id}` pretended to be a section document. It is
    gone, not aliased, and its events path stays."""
    run_id, viewer = run

    response = client.get(f"/api/runs/{run_id}", headers=_as(viewer))

    assert (response.status_code, response.json()) == (
        404,
        _refused("ENDPOINT_NOT_FOUND"),
    )
    assert not hasattr(app_module, "read_run")
    assert not hasattr(app_module, "RunDocument")


def test_the_run_section_carries_node_states_with_their_reasons(
    client: TestClient,
    case: tuple[StoreConnection, UUID],
    run: tuple[UUID, UUID],
    catalog: dict[str, Any],
) -> None:
    conn, case_id = case
    run_id, viewer = run
    pinned = pin_route(conn, run_id, resolve_route(catalog, *LITE))

    document = _document(_section(client, case_id, run_id, viewer))

    assert document.chrome.subject is not None
    assert document.chrome.subject.case_id == case_id
    assert document.chrome.subject.title == "Acme 2026 refinancing"
    assert document.chrome.served_role.standing is Standing.READER
    assert (document.status, document.notes, document.observed_empty) == (
        "complete",
        [],
        False,
    )
    view = document.body.run
    assert view is not None
    assert (view.run_id, view.status, view.route_digest) == (run_id, "RUNNING", pinned)
    assert (view.build_id, view.source_set_version, view.subject) == (None, None, None)
    assert [(g.gate, g.state) for g in view.gates] == [
        ("SOURCE_SET", "OPEN"),
        ("RESEARCH_PLAN", "OPEN"),
    ]
    by_module = {node.module_id: node for node in view.nodes}
    assert (by_module["CP-0"].state, by_module["CP-0"].waiting_on) == ("RUNNABLE", [])
    assert by_module["CP-L10"].state == "BLOCKED"
    assert {(e.source, e.type) for e in by_module["CP-L10"].waiting_on} == {
        ("CP-0", "REQUIRED")
    }
    assert by_module["CP-L10"].gate_verdict is None
    assert by_module["CP-0"].stage < by_module["CP-L10"].stage
    assert view.attempts == []


def test_a_run_with_no_pinned_route_is_noted(
    client: TestClient, case: tuple[StoreConnection, UUID], run: tuple[UUID, UUID]
) -> None:
    _conn, case_id = case
    run_id, viewer = run

    document = _document(_section(client, case_id, run_id, viewer))

    assert document.body.run is not None
    assert (document.body.run.nodes, document.body.run.route_digest) == ([], None)
    assert document.notes == ["ROUTE_NOT_PINNED"]
    assert document.status == "partial"


def test_a_case_with_no_run_is_observed_empty(
    client: TestClient, case: tuple[StoreConnection, UUID]
) -> None:
    conn, case_id = case
    viewer = uuid4()
    grant(conn, case_id=case_id, user_id=viewer, standing=Standing.WRITER)
    conn.commit()

    document = _document(_section(client, case_id, None, viewer))

    assert document.observed_empty is True
    assert document.body.model_dump() == {
        "case_id": case_id,
        "latest_run_id": None,
        "displayed_run_id": None,
        "runs": [],
        "run": None,
        # Every enabled pathway, spelled out rather than derived from
        # `ADAPTER_ROUTES`: deriving it from the constant the reader already
        # uses would assert nothing, and enabling a pathway should cost a
        # deliberate edit here.
        # `accepts_model_extension` is the create command's own resolution
        # asked in advance: only RELATIVE_VALUE runs every owner CP-CF reads.
        "route_choices": [
            {
                "profile_id": "FULL_CREDIT_32",
                "selection_id": "COVENANT_REFINANCING",
                "accepts_model_extension": False,
            },
            {
                "profile_id": "FULL_CREDIT_32",
                "selection_id": "DECISION_LEDGER",
                "accepts_model_extension": False,
            },
            {
                "profile_id": "FULL_CREDIT_32",
                "selection_id": "DEEP_RESEARCH",
                "accepts_model_extension": False,
            },
            {
                "profile_id": "FULL_CREDIT_32",
                "selection_id": "DISTRESSED_RESTRUCTURING",
                "accepts_model_extension": True,
            },
            {
                "profile_id": "FULL_CREDIT_32",
                "selection_id": "EARNINGS_UPDATE",
                "accepts_model_extension": False,
            },
            {
                "profile_id": "FULL_CREDIT_32",
                "selection_id": "FULL_CREDIT_ASSESSMENT",
                "accepts_model_extension": True,
            },
            {
                "profile_id": "FULL_CREDIT_32",
                "selection_id": "LIQUIDITY_REVIEW",
                "accepts_model_extension": False,
            },
            {
                "profile_id": "FULL_CREDIT_32",
                "selection_id": "MARKET_DISLOCATION",
                "accepts_model_extension": False,
            },
            {
                "profile_id": "FULL_CREDIT_32",
                "selection_id": "PORTFOLIO_DECISION",
                "accepts_model_extension": False,
            },
            {
                "profile_id": "FULL_CREDIT_32",
                "selection_id": "RELATIVE_VALUE",
                "accepts_model_extension": True,
            },
            {
                "profile_id": "LITE_CREDIT_22",
                "selection_id": "LITE_COVENANT_REFINANCING",
                "accepts_model_extension": False,
            },
            {
                "profile_id": "LITE_CREDIT_22",
                "selection_id": "LITE_DECISION_LEDGER",
                "accepts_model_extension": False,
            },
            {
                "profile_id": "LITE_CREDIT_22",
                "selection_id": "LITE_DEEP_RESEARCH",
                "accepts_model_extension": False,
            },
            {
                "profile_id": "LITE_CREDIT_22",
                "selection_id": "LITE_DISTRESSED_RESTRUCTURING",
                "accepts_model_extension": False,
            },
            {
                "profile_id": "LITE_CREDIT_22",
                "selection_id": "LITE_EARNINGS_UPDATE",
                "accepts_model_extension": False,
            },
            {
                "profile_id": "LITE_CREDIT_22",
                "selection_id": "LITE_FULL_CREDIT_SCREEN",
                "accepts_model_extension": False,
            },
            {
                "profile_id": "LITE_CREDIT_22",
                "selection_id": "LITE_PORTFOLIO_DECISION",
                "accepts_model_extension": False,
            },
            {
                "profile_id": "LITE_CREDIT_22",
                "selection_id": "LITE_RELATIVE_VALUE",
                "accepts_model_extension": False,
            },
        ],
    }
    actions = {str(view.action): view.refusal for view in document.chrome.actions}
    assert actions["CREATE_RUN"] is not None  # the header named no writing group
    assert actions["START_RUN"] is not None
    assert actions["START_RUN"].code == "NOT_AUTHORISED"


def test_only_the_owner_refusal_withholds_the_model_extension_offer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A choice says "no extension" for the one refusal that means it. Any
    other refusal from resolution is a fault in the catalog, and reading it as
    "this route cannot carry CP-CF" would hide that fault behind an offer."""

    def refuse(*_: object, **__: object) -> ResolvedRoute:
        raise Refusal(RefusalCode.ROUTE_PROFILE_UNKNOWN)

    monkeypatch.setattr(run_read, "catalog", lambda _bundle: {})
    monkeypatch.setattr(run_read, "resolve_route", refuse)
    with pytest.raises(Refusal) as refused:
        run_read._route_choices(object())  # type: ignore[arg-type]
    assert refused.value.code is RefusalCode.ROUTE_PROFILE_UNKNOWN


def test_the_lite_run_carries_its_pinned_input_gates_and_attempts(
    client: TestClient, lite: tuple[_Harness, UUID]
) -> None:
    harness, viewer = lite
    _answer(harness, "CP-0", readiness={"CP-L10": "BLOCKED"})

    document = _document(_section(client, harness.case_id, harness.run_id, viewer))

    view = document.body.run
    assert view is not None
    assert view.build_id == harness.bundle.build_id
    assert view.source_set_version == 1
    assert view.subject is not None and view.subject.issuer_id
    assert {g.state for g in view.gates} == {"RELEASED"}
    by_module = {node.module_id: node for node in view.nodes}
    assert (by_module["CP-L10"].state, by_module["CP-L10"].gate_verdict) == (
        "BLOCKED",
        "BLOCKED",
    )
    cp0 = by_module["CP-0"].route_node_id
    assert [(a.route_node_id, a.ordinal, a.accepted) for a in view.attempts] == [
        (cp0, 1, True)
    ]


def test_a_run_of_another_case_is_the_same_run_not_found(
    client: TestClient, case: tuple[StoreConnection, UUID], run: tuple[UUID, UUID]
) -> None:
    conn, case_id = case
    _run_id, viewer = run
    other = create_case(conn, BoundaryText.of("Another case"))
    grant(conn, case_id=other, user_id=viewer, standing=Standing.ADMIN)
    foreign = start_run(conn, other)
    conn.commit()

    unknown = _section(client, case_id, uuid4(), viewer)
    answers = [
        _section(client, case_id, foreign, viewer),
        client.get(f"/api/v1/cases/{case_id}/run?run=not-a-run", headers=_as(viewer)),
        unknown,
    ]

    for response in answers:
        assert (response.status_code, response.json()) == (
            404,
            _refused("RUN_NOT_FOUND"),
        )
    assert _document(_section(client, other, foreign, viewer)).body.run is not None


def test_run_and_analysis_name_displayed_and_latest_runs_separately(
    client: TestClient, case: tuple[StoreConnection, UUID], run: tuple[UUID, UUID]
) -> None:
    """The run half: a displayed run is not the latest one just because it is
    shown, and the list names both, newest first."""
    conn, case_id = case
    older, viewer = run
    newer = start_run(conn, case_id)
    conn.commit()

    latest = _document(_section(client, case_id, None, viewer)).body
    shown = _document(_section(client, case_id, older, viewer)).body

    assert (latest.latest_run_id, latest.displayed_run_id) == (newer, newer)
    assert latest.run is not None and latest.run.run_id == newer
    assert (shown.latest_run_id, shown.displayed_run_id) == (newer, older)
    assert shown.run is not None and shown.run.run_id == older
    assert [summary.run_id for summary in shown.runs] == [newer, older]


def test_a_parked_run_s_stop_code_reaches_the_runs_list(
    client: TestClient,
    case: tuple[StoreConnection, UUID],
    run: tuple[UUID, UUID],
) -> None:
    """CF-044: a run a worker parked still reads `status: RUNNING` in its own
    summary -- `stop_code` is what tells the list it stopped being driven,
    the same field the detailed `RunView.work` already carried."""
    conn, case_id = case
    run_id, viewer = run
    enqueue_run(conn, run_id)
    conn.commit()
    lease = claim_run(conn, worker=BoundaryText.of("worker-a"), lease_seconds=60)
    assert lease is not None
    assert stop(conn, lease, RefusalCode.CONTEXT_OVER_CEILING) is True
    conn.commit()

    document = _document(_section(client, case_id, run_id, viewer))

    [summary] = document.body.runs
    assert summary.run_id == run_id
    assert summary.stop_code is RefusalCode.CONTEXT_OVER_CEILING


def test_a_run_beyond_the_bounded_list_is_still_displayed_and_the_list_noted(
    client: TestClient,
    case: tuple[StoreConnection, UUID],
    run: tuple[UUID, UUID],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn, case_id = case
    older, viewer = run
    newer = start_run(conn, case_id)
    conn.commit()
    monkeypatch.setattr(run_read, "RUNS_MAX", 1)
    monkeypatch.setattr(run_read, "ATTEMPTS_MAX", 0)
    counter = _CountingConnection(conn)
    app_module.app.dependency_overrides[app_module.store_connection] = lambda: counter

    document = _document(_section(client, case_id, older, viewer))

    assert [s.run_id for s in document.body.runs] == [newer]
    assert document.body.run is not None and document.body.run.run_id == older
    assert (document.status, document.notes) == (
        "partial",
        ["LIST_TRUNCATED", "ROUTE_NOT_PINNED"],
    )
    # No pinned route, so no accepted-artifact read; one read for the run the
    # bounded list did not hold.
    assert counter.executed == (
        run_read.UNPINNED_INPUT_IO - run_read.ACCEPTED_IO + run_read.BEYOND_LIST_IO
    )


def test_unknown_unauthorised_revoked_and_malformed_case_are_one_private_404(
    client: TestClient,
    case: tuple[StoreConnection, UUID],
    run: tuple[UUID, UUID],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn, case_id = case
    run_id, viewer = run
    revoked = uuid4()
    grant(conn, case_id=case_id, user_id=revoked, standing=Standing.APPROVER)
    revoke(conn, case_id=case_id, user_id=revoked)
    conn.commit()
    monkeypatch.setenv(TRUST_SWITCH, "1")
    admin = {**_as(uuid4()), "x-caos-role": "ADMIN"}

    answers = [
        client.get(f"/api/v1/cases/{uuid4()}/run", headers=_as(viewer)),
        client.get(f"/api/v1/cases/{case_id}/run", headers=_as(uuid4())),
        client.get(f"/api/v1/cases/{case_id}/run?run={run_id}", headers=_as(revoked)),
        client.get("/api/v1/cases/not-a-case/run", headers=_as(viewer)),
        client.get(f"/api/v1/cases/{case_id}/run", headers=admin),
    ]

    for response in answers:
        assert (response.status_code, response.json()) == (
            404,
            _refused("CASE_NOT_FOUND"),
        )


@pytest.mark.parametrize(
    ("actor", "status"),
    [
        ("anonymous", 401),
        ("nonmember", 404),
        ("reader", 200),
        ("writer", 200),
        ("approver", 200),
        ("revoked", 404),
        ("admin", 404),
        ("case_admin", 200),
    ],
)
def test_a_run_section_request_across_anonymous_nonmember_reader_writer_approver_revoked_and_admin(  # noqa: E501 -- the brief's name
    client: TestClient,
    case: tuple[StoreConnection, UUID],
    monkeypatch: pytest.MonkeyPatch,
    actor: str,
    status: int,
) -> None:
    conn, case_id = case
    user = uuid4()
    standing = {
        "reader": Standing.READER,
        "writer": Standing.WRITER,
        "approver": Standing.APPROVER,
        "revoked": Standing.READER,
        "case_admin": Standing.ADMIN,
    }.get(actor)
    if standing is not None:
        grant(conn, case_id=case_id, user_id=user, standing=standing)
    if actor == "revoked":
        revoke(conn, case_id=case_id, user_id=user)
    conn.commit()
    monkeypatch.setenv(TRUST_SWITCH, "1")
    headers = {} if actor == "anonymous" else _as(user)
    if actor == "admin":
        headers["x-caos-role"] = "ADMIN"

    response = client.get(f"/api/v1/cases/{case_id}/run", headers=headers)

    assert response.status_code == status
    if status == 200:
        document = RunSectionDocument.model_validate(response.json())
        assert document.chrome.served_role.standing is standing
    else:
        code = "NOT_AUTHENTICATED" if status == 401 else "CASE_NOT_FOUND"
        assert response.json() == _refused(code)


def test_an_anonymous_run_section_request_opens_no_store_connection(
    client: TestClient, case: tuple[StoreConnection, UUID]
) -> None:
    conn, case_id = case
    opened: list[str] = []

    def counted() -> Iterator[StoreConnection]:
        opened.append("store")
        yield conn

    app_module.app.dependency_overrides[app_module.store_connection] = counted

    response = client.get(f"/api/v1/cases/{case_id}/run")

    assert (response.status_code, response.json()) == (
        401,
        _refused("NOT_AUTHENTICATED"),
    )
    assert opened == []


def test_a_cancelled_run_reaches_the_wire(
    client: TestClient, case: tuple[StoreConnection, UUID], run: tuple[UUID, UUID]
) -> None:
    """Migration 0013 added `CANCELLED` to `runs.status`; `RunStatus` on the
    wire (`caos/api/wire.py`) carries it too, so a cancelled run validates in
    both the Directory and the Run section instead of failing response
    validation."""
    conn, case_id = case
    run_id, viewer = run
    enqueue_run(conn, run_id)
    conn.commit()
    assert request_cancel(conn, run_id) is True
    conn.commit()

    directory = DirectoryDocument.model_validate(
        client.get("/api/v1/directory", headers=_as(viewer)).json()
    )
    [row] = directory.body.cases
    assert row.latest_run is not None
    assert row.latest_run.status == "CANCELLED"

    document = _document(_section(client, case_id, run_id, viewer))
    assert document.body.run is not None
    assert document.body.run.status == "CANCELLED"
    assert document.body.run.work is not None
    assert document.body.run.work.model_dump() == {
        "state": "DONE",
        "stop_code": None,
        "cancel_requested": True,
    }


def test_the_run_section_carries_the_displayed_runs_work_row(
    client: TestClient, case: tuple[StoreConnection, UUID], run: tuple[UUID, UUID]
) -> None:
    """`RunView.work` is the run's `run_work` row, and null before any enqueue."""
    conn, case_id = case
    run_id, viewer = run

    before = _document(_section(client, case_id, run_id, viewer)).body.run
    enqueue_run(conn, run_id)
    conn.commit()
    after = _document(_section(client, case_id, run_id, viewer)).body.run

    assert before is not None and before.work is None
    assert after is not None and after.work is not None
    assert (after.work.state, after.work.cancel_requested) == ("QUEUED", False)


def test_the_run_document_names_the_node_whose_blocked_verdict_ended_it(
    client: TestClient, lite: tuple[_Harness, UUID]
) -> None:
    """Why the run ended, not only that it did (§68). CP-5's validated Blocked
    answer ends the run; its state is still the bundle's, recomputed from
    accepted artifacts -- RUNNABLE, with the gate's READY beside it -- so the
    document alone read as "CP-5 did not run", the opposite of what happened.
    `blocked_by` names the node, its module and the attempt, and that attempt
    is the one unaccepted row the same document carries for the node."""
    harness, viewer = lite
    answers = CanonicalCompletions(harness.source_id, qa_by_module={"CP-5": "Blocked"})
    assert _run_route(harness, _module_provider(harness, answers)) is None
    counter = _CountingConnection(harness.conn)
    app_module.app.dependency_overrides[app_module.store_connection] = lambda: counter

    view = _document(_section(client, harness.case_id, harness.run_id, viewer)).body.run

    assert view is not None and view.status == "BLOCKED"
    cp5 = next(node for node in view.nodes if node.module_id == "CP-5")
    assert (cp5.state, cp5.gate_verdict) == ("RUNNABLE", "READY")
    assert view.blocked_by == BlockedByView(
        route_node_id=cp5.route_node_id,
        module_id="CP-5",
        attempt_id=view.blocked_by.attempt_id if view.blocked_by else uuid4(),
    )
    mine = [a for a in view.attempts if a.route_node_id == cp5.route_node_id]
    assert [(a.attempt_id, a.accepted) for a in mine] == [
        (view.blocked_by.attempt_id, False)
    ]
    # One round trip more than the running LITE run the budget test counts
    # (its one readiness row is CP-0's), and only on a BLOCKED run: the row is
    # read, never re-derived.
    assert counter.executed == (
        run_read.SECTION_READ_IO
        + run_read.CANONICAL_READINESS_IO
        + run_read.BLOCKED_BY_IO
    )
    assert counter.executed <= run_read.IO_BUDGET


def test_a_run_the_frontier_emptied_names_no_blocking_node(
    client: TestClient, lite: tuple[_Harness, UUID]
) -> None:
    """The other way a run ends BLOCKED (§39): CP-0 says CP-L10 is BLOCKED, so
    nothing is ready and the route's own rule ends the run with no node asked.
    No verdict ended it, so the wire carries no blocking node -- it never
    claims one that does not exist."""
    harness, viewer = lite
    _answer(harness, "CP-0", readiness={"CP-L10": "BLOCKED"})
    answers = CanonicalCompletions(harness.source_id)
    assert _run_route(harness, _module_provider(harness, answers)) is None
    assert answers.prompts == [], "nothing was ready, so nobody was asked"

    view = _document(_section(client, harness.case_id, harness.run_id, viewer)).body.run

    assert view is not None and view.status == "BLOCKED"
    assert view.blocked_by is None
    assert all(a.accepted for a in view.attempts)


def test_the_run_section_request_path_declares_its_store_budget(
    client: TestClient, lite: tuple[_Harness, UUID]
) -> None:
    """Counted on a run with its input pinned and both gates released, which
    is the most a run document reads: the canonical gate row, both gates and
    the pinned input."""
    harness, viewer = lite
    _answer(harness, "CP-0")
    counter = _CountingConnection(harness.conn)
    app_module.app.dependency_overrides[app_module.store_connection] = lambda: counter

    assert _section(client, harness.case_id, None, viewer).status_code == 200

    read = run_read.SECTION_READ_IO + run_read.CANONICAL_READINESS_IO
    assert counter.executed == read
    assert counter.executed <= run_read.IO_BUDGET


def test_a_blocked_run_names_the_source_its_conditional_row_asked_for(
    client: TestClient, lite: tuple[_Harness, UUID]
) -> None:
    """Task 10.3: a run the gate blocked says which source would discharge it.

    CP-0 marks CP-5 CONDITIONAL, which under §61 names a source the effective
    set does not carry. `node_states` BLOCKS CP-5 on the verdict alone, the
    frontier empties with required work unfinished, and the run ends BLOCKED
    with no node's verdict to name (`blocked_by` is null, §39). Before this the
    document carried the verdict word and nothing else, so a reader was told
    CP-5 was conditional and never on what -- and the discharge is a new run
    against a supplied source, which nobody can supply without being told which.
    `gate_reason` is that cell, on the node it was written about and on no
    other.
    """
    asked = "The FY2025 audited consolidated statements are not in the pinned set."
    harness, viewer = lite
    answers = CanonicalCompletions(
        harness.source_id,
        readiness={"CP-5": "CONDITIONAL"},
        blockers={"CP-5": asked},
    )
    assert _run_route(harness, _module_provider(harness, answers)) is None

    view = _document(_section(client, harness.case_id, harness.run_id, viewer)).body.run

    assert view is not None and (view.status, view.blocked_by) == ("BLOCKED", None)
    reasons = {
        node.module_id: (node.gate_verdict, node.gate_reason) for node in view.nodes
    }
    assert reasons["CP-5"] == ("CONDITIONAL", asked)
    assert reasons["CP-L10"] == ("READY", None)
    # The gate rules on its consumers, never on itself, so it has neither.
    assert reasons["CP-0"] == (None, None)


def test_the_run_document_does_not_recompute_the_route_digest(
    client: TestClient,
    case: tuple[StoreConnection, UUID],
    run: tuple[UUID, UUID],
    catalog: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The digest the document carries is the one the read already derived.

    `resolved_route` hashes the route it read to check it against the stored
    column and refuses `ROUTE_IDENTITY_INVALID` when the two disagree, so a
    second hash in the view could never answer differently -- it only hashed a
    route the reader had already vouched for. The pin returns its digest now.
    """
    conn, case_id = case
    run_id, viewer = run
    pinned = pin_route(conn, run_id, resolve_route(catalog, *LITE))
    digested: list[str] = []
    hashed = route_digest

    def counted(route: ResolvedRoute) -> str:
        digested.append(route.selection_id)
        return hashed(route)

    # Both spellings: the store's reader, and the view that hashed the route a
    # second time. `raising=False` so the view losing its import is a pass.
    for module in (store_routes, run_read):
        monkeypatch.setattr(module, "route_digest", counted, raising=False)

    document = _document(_section(client, case_id, run_id, viewer))

    assert document.body.run is not None
    assert document.body.run.route_digest == pinned
    assert digested == [LITE[1]]

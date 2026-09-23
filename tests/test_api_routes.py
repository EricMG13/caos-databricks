"""The two request paths: the run document, the tail over a socket, and privacy.

`docs/REBUILD_PLAN.md` Phase 6: "The run endpoint serves node states with their
reasons, and the one QA_GATE reads as a gate". The one QA_GATE in the catalog is
`CP-5 -> CP-6`, and a node held by it is not in the same situation as a node held
by an ordinary REQUIRED edge: one is waiting for a person, the other for a
module. A surface that rendered both as "BLOCKED" would leave a reviewer with no
way to see that the run is waiting on them.

`test_unauthorised_case_is_private_404` is the second of the named pair from the
plan's standing rules. The first, identity derivation, is in
`tests/test_actor_matrix.py`.
"""

from __future__ import annotations

import ast
import asyncio
import json
import re
from collections.abc import Callable, Iterator
from dataclasses import replace
from importlib import import_module
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from canonical_fixtures import CanonicalCompletions
from conftest import route_fault
from fastapi import FastAPI, HTTPException
from fastapi.dependencies.utils import get_dependant
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from httpx2 import Response
from pydantic import BaseModel
from starlette.types import Message
from test_canonical_execution import _accept, _node, _run, harness, route
from test_execution_freshness import _Harness

from caos.api import app as app_module
from caos.api import deps
from caos.api import edge as edge_module
from caos.api.app import (
    _STATUS,
    PERMANENT,
    RETRY_AFTER_SECONDS,
    TRANSIENT,
    app,
    blob_store,
    methodology_bundle,
    read_case_events,
    store_connection,
)
from caos.api.commands import _request as request_module
from caos.api.commands import cases as cases_command
from caos.api.commands import execution as execution_command
from caos.api.commands import qualification as qualification_command
from caos.api.commands import runs as runs_command
from caos.api.commands._request import governed
from caos.api.deps import actor_from_request
from caos.api.edge import EDGE_STATUS, is_api_path, refusal_body, startup_failed
from caos.api.reads import analysis as analysis_read
from caos.api.reads import book as book_read
from caos.api.reads import directory as directory_read
from caos.api.reads import model as model_read
from caos.api.reads import reports as reports_read
from caos.api.reads import run as run_read
from caos.api.reads import upload as upload_read
from caos.api.reads.run import _node_view, node_readiness, read_run_section
from caos.api.wire import CLEARS, EdgeView, NodeView, RefusalBody, RunSectionDocument
from caos.blobs import BlobStore
from caos.graph.route import (
    EdgeType,
    NodeResult,
    blockers_from,
    node_states,
    readiness_from,
    resolve_route,
)
from caos.methodology.bundle import Bundle
from caos.methodology.handoff import _decoded_record, record_bytes
from caos.refusals import Refusal, RefusalCode
from caos.store import StoreConnection
from caos.store.commands import request_digest
from caos.store.members import Standing, grant, revoke
from caos.store.routes import pin_route, pinned_route
from caos.store.runs import block_run, start_run

__all__ = ["harness", "route"]

CATALOG_PATH = (
    Path(__file__).resolve().parents[1]
    / "vendor/deploy-v/skills/cp-os-credit-os/references"
    / "CREDIT_OS_V_MODULE_CATALOG_v2.json"
)
PROFILE = "FULL_CREDIT_32"
# Every run that accepts an artifact here is a canonical LITE run (§42): its
# gate verdicts are read from CP-0's host record, never from a claims body.
LITE = ("LITE_CREDIT_22", "LITE_EARNINGS_UPDATE")


@pytest.fixture(scope="module")
def catalog() -> dict[str, Any]:
    loaded: dict[str, Any] = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    return loaded


@pytest.fixture
def client(
    case: tuple[StoreConnection, UUID],
    empty_database: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[TestClient]:
    """The app served against the test's own database and blob root.

    `CAOS_DATABASE_URL` is set because startup reads it: entering the client runs
    the real lifespan, so every test here also proves the process can boot. The
    per-request connection is then overridden onto the fixture's own, which is
    the one holding the case these tests set up.
    """
    conn, _case_id = case
    blobs = BlobStore(tmp_path / "blobs")
    monkeypatch.setenv(app_module.DATABASE_URL, empty_database)
    _serve(conn, blobs)
    try:
        with TestClient(app) as opened:
            yield opened
    finally:
        app.dependency_overrides.clear()


@pytest.fixture
def run(case: tuple[StoreConnection, UUID]) -> tuple[UUID, UUID]:
    """A run, and a READER entitled to see it."""
    conn, case_id = case
    run_id = start_run(conn, case_id)
    viewer = uuid4()
    grant(conn, case_id=case_id, user_id=viewer, standing=Standing.READER)
    conn.commit()
    return run_id, viewer


@pytest.fixture
def lite(harness: _Harness, client: TestClient) -> tuple[_Harness, UUID]:
    """An approved canonical LITE run on the client's store, and a READER of it.

    The harness shares the `case` connection and the `tmp_path / "blobs"` root
    the client serves, and its bundle is the one records are verified under.
    """
    _serve(bundle=harness.bundle)
    viewer = uuid4()
    grant(
        harness.conn, case_id=harness.case_id, user_id=viewer, standing=Standing.READER
    )
    harness.conn.commit()
    return harness, viewer


def _answer(
    harness: _Harness, module_id: str, readiness: dict[str, str] | None = None
) -> None:
    """One node called through the canonical executor and accepted with its
    record; the run stays RUNNING."""
    answers = CanonicalCompletions(harness.source_id, readiness=readiness or {})
    attempt, result = _run(harness, module_id, answers)
    _accept(harness, attempt, result)


def _serve(
    conn: StoreConnection | None = None,
    blobs: BlobStore | None = None,
    bundle: Bundle | None = None,
) -> None:
    """Override the app's shared dependencies: every section read declares the
    same `caos.api.deps` functions, so overriding them here reaches every
    route that depends on one, section reads included."""
    pairs = (
        (conn, store_connection),
        (blobs, blob_store),
        (bundle, methodology_bundle),
    )
    for value, dependency in pairs:
        if value is not None:
            # A closure, not a default argument: FastAPI reads an override's
            # parameters as request inputs and copies their defaults.
            app.dependency_overrides[dependency] = _constant(value)


def _constant(value: object) -> Callable[[], object]:
    return lambda: value


def _section(
    client: TestClient, case_id: UUID, run_id: UUID | None, user: UUID | None
) -> Response:
    """The Run section for `run_id` (or the latest run) as `user` would ask."""
    query = "" if run_id is None else f"?run={run_id}"
    headers = {} if user is None else _as(user)
    response: Response = client.get(
        f"/api/v1/cases/{case_id}/run{query}", headers=headers
    )
    return response


def _view(response: Response) -> dict[str, Any]:
    """The displayed run of a Run section that validated as its model."""
    assert response.status_code == 200, response.json()
    document = RunSectionDocument.model_validate(response.json())
    assert document.body.run is not None
    view: dict[str, Any] = document.body.run.model_dump(mode="json")
    return view


def _refused(code: str) -> dict[str, str]:
    """The one refusal body: the code and its host-constant clearance."""
    return {"code": code, "clears": CLEARS[RefusalCode(code)]}


def _as(user_id: UUID) -> dict[str, str]:
    """Headers for an authenticated caller with no asserted groups."""
    return {"x-caos-user": str(user_id)}


def test_unauthorised_case_is_private_404(
    client: TestClient, case: tuple[StoreConnection, UUID], run: tuple[UUID, UUID]
) -> None:
    """A named test.

    A stranger asking about somebody else's run gets the answer they would get
    for a run that does not exist. 403 is the informative answer and that is the
    problem with it: it confirms the id names something real, which for a case
    id is the fact worth protecting.
    """
    _conn, case_id = case
    run_id, _viewer = run
    stranger = uuid4()

    response = _section(client, case_id, run_id, stranger)
    unknown = _section(client, uuid4(), run_id, stranger)

    assert response.status_code == unknown.status_code == 404
    assert response.json() == unknown.json() == _refused("CASE_NOT_FOUND")


def test_an_unknown_run_is_the_same_404(
    client: TestClient, case: tuple[StoreConnection, UUID], run: tuple[UUID, UUID]
) -> None:
    """The other half of the pair. The two answers have to be identical, or the
    difference between them is the disclosure."""
    _run_id, viewer = run
    response = _section(client, case[1], uuid4(), viewer)

    assert response.status_code == 404
    assert response.json() == _refused("RUN_NOT_FOUND")


def test_a_revoked_reader_stops_being_able_to_read_it(
    client: TestClient, case: tuple[StoreConnection, UUID], run: tuple[UUID, UUID]
) -> None:
    """Standing is read at the request, not cached in a session."""
    conn, case_id = case
    run_id, viewer = run
    assert _section(client, case_id, run_id, viewer).status_code == 200

    revoke(conn, case_id=case_id, user_id=viewer)
    conn.commit()

    assert _section(client, case_id, run_id, viewer).status_code == 404


def test_a_request_with_no_identity_is_401_not_404(
    client: TestClient, case: tuple[StoreConnection, UUID], run: tuple[UUID, UUID]
) -> None:
    """Unauthenticated and unauthorised are different questions. "I do not know
    who you are" discloses nothing about the run, so it can be said plainly --
    and a client that got a 404 would retry the wrong thing forever."""
    run_id, _viewer = run

    response = _section(client, case[1], run_id, None)

    assert response.status_code == 401
    assert response.json() == _refused("NOT_AUTHENTICATED")


@pytest.mark.parametrize(
    "database_url",
    [None, "postgresql://caos@127.0.0.1:1/caos?connect_timeout=2"],
    ids=["unconfigured", "unreachable"],
)
def test_an_anonymous_request_is_401_whatever_the_store_is_doing(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, database_url: str | None
) -> None:
    """The answer to a stranger does not depend on the database being up.

    Identity checked in the route body is identity checked after FastAPI has
    already resolved `Store`, so a process that had lost its database answered
    a caller whose actual problem was that it had not said who it was with a
    refusal about the store. Both shapes of that refusal are asked for, because
    they are separate codes and either would do as the wrong answer: the store
    unconfigured is STORE_NOT_CONFIGURED, the store not answering is
    STORE_UNAVAILABLE, and either would have told a caller whose problem was
    their own silence that the server was at fault. The two no longer share a
    status: D3 sends the unconfigured store to 500, because coming back later
    is not what configures it.
    """
    app.dependency_overrides.pop(store_connection)
    if database_url is None:
        monkeypatch.delenv(app_module.DATABASE_URL, raising=False)
    else:
        monkeypatch.setenv(app_module.DATABASE_URL, database_url)

    for path in (f"/api/v1/cases/{uuid4()}/run", f"/api/v1/cases/{uuid4()}/events"):
        response = client.get(path)

        assert (response.status_code, response.json()) == (
            401,
            _refused("NOT_AUTHENTICATED"),
        ), path


def test_an_anonymous_request_opens_no_store_connection(
    client: TestClient, case: tuple[StoreConnection, UUID], run: tuple[UUID, UUID]
) -> None:
    """`actor_from_request` is declared before `Store`, and FastAPI solves a
    route's dependencies in the order its parameters declare them.

    The connection is one per request and unpooled, so a stranger asking in a
    loop for a connection opened before identity is known is a cheap way to
    exhaust the database. The run here exists and is somebody's, so a 401 alone
    would not say where the refusal came from -- the count is what does. It is
    the dependency's own call that is counted rather than the queries it then
    serves, because opening the connection is the cost.
    """
    conn, case_id = case
    run_id, _viewer = run
    opened: list[str] = []

    def counted() -> StoreConnection:
        opened.append(store_connection.__name__)
        return conn

    def counted_bundle() -> Bundle:
        opened.append(methodology_bundle.__name__)
        raise AssertionError  # never reached before identity

    app.dependency_overrides[store_connection] = counted
    app.dependency_overrides[methodology_bundle] = counted_bundle

    for path in (
        f"/api/v1/cases/{case_id}/run",
        f"/api/v1/cases/{case_id}/events?run={run_id}",
    ):
        assert client.get(path).status_code == 401, path
    del app.dependency_overrides[methodology_bundle]
    assert opened == [], (
        "an anonymous request resolved the store dependency; identity is "
        "declared before it so that it does not"
    )


def test_store_connection_refuses_without_a_database_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The dependency the test client overrides in every other test. A
    deployment missing `CAOS_DATABASE_URL` should fail this way, not with a
    connection error from whatever `connect(None)` happens to do."""
    monkeypatch.delenv("CAOS_DATABASE_URL", raising=False)

    with pytest.raises(Refusal) as caught:
        next(store_connection())

    # Not STORE_NOT_TRANSACTIONAL, which it used to be: that code names an
    # autocommit connection, and a reader chasing it would look for the wrong
    # misconfiguration.
    assert caught.value.code is RefusalCode.STORE_NOT_CONFIGURED


def test_store_connection_opens_a_real_connection_from_the_environment(
    empty_database: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The success path the override in every other test bypasses entirely.
    Advanced twice, the way FastAPI itself drives a dependency generator: once
    for the connection, once past the `yield` to run the `with` block's exit."""
    monkeypatch.setenv("CAOS_DATABASE_URL", empty_database)

    generator = store_connection()
    conn = next(generator)

    assert conn.execute("SELECT 1").fetchone() == (1,)
    with pytest.raises(StopIteration):
        next(generator)


def test_blob_store_refuses_without_a_blob_root(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("CAOS_BLOB_ROOT", raising=False)

    with pytest.raises(Refusal) as caught:
        blob_store()

    assert caught.value.code is RefusalCode.STORE_NOT_CONFIGURED


def test_a_misconfigured_store_is_a_server_fault_not_a_bad_request(
    case: tuple[StoreConnection, UUID],
    empty_database: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With the blob root unset every run read failed 400 BLOB_NOT_FOUND --
    telling the client its request was bad, and answering an unknown run with
    something other than the 404 a stranger always gets. A store the process
    cannot reach is the server's fault, the same for every caller."""
    conn, _case_id = case
    monkeypatch.setenv(app_module.DATABASE_URL, empty_database)
    monkeypatch.delenv("CAOS_BLOB_ROOT", raising=False)
    _serve(conn)
    try:
        with TestClient(app) as opened:
            response = _section(opened, uuid4(), None, uuid4())
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 500  # D3: an operator configures it, not time.
    assert response.json() == _refused("STORE_NOT_CONFIGURED")
    assert "retry-after" not in response.headers


def test_a_store_that_does_not_answer_is_a_server_fault(
    empty_database: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A configured store that does not answer -- the commonest store fault --
    reached every caller as a bare 500, and the server's log as psycopg's
    message naming the host, port and role. It is refused like any other store
    fault: 503, and the code alone, with nothing chained behind it.

    Both callers are named. A caller with no identity never reaches the store
    at all, and gets 401 --
    `test_an_anonymous_request_is_401_whatever_the_store_is_doing` is where that
    is asserted. What this keeps from the arm that used to be anonymous is the
    tail route, which is the half of it that was about the route rather than
    about the caller.
    """
    monkeypatch.setenv(app_module.DATABASE_URL, empty_database)
    monkeypatch.setenv(app_module.BLOB_ROOT, str(tmp_path))
    with TestClient(app) as opened:
        monkeypatch.setenv(
            app_module.DATABASE_URL,
            "postgresql://caos@127.0.0.1:1/caos?connect_timeout=2",
        )
        document = _section(opened, uuid4(), None, uuid4())
        tail = opened.get(f"/api/v1/cases/{uuid4()}/events", headers=_as(uuid4()))

    for response in (document, tail):
        assert (response.status_code, response.json()) == (
            503,
            _refused("STORE_UNAVAILABLE"),
        )
    with pytest.raises(Refusal) as caught:
        next(store_connection())
    assert caught.value.code == "STORE_UNAVAILABLE"
    assert caught.value.__cause__ is None and caught.value.__context__ is None


def test_only_a_run_id_that_cannot_be_read_is_answered_as_a_missing_run() -> None:
    """Registered for the whole app, the handler answered every malformed path
    parameter as a missing run, so the first route to take a case id would have
    said RUN_NOT_FOUND about it. Any other path keeps FastAPI's default until
    its route says what it should get."""
    other = FastAPI()
    other.add_exception_handler(
        RequestValidationError, app.exception_handlers[RequestValidationError]
    )

    @other.get("/api/cases/{case_id}")
    def read_case(case_id: UUID) -> str:
        return str(case_id)

    assert TestClient(other).get("/api/cases/not-a-case").status_code == 422


def test_the_malformed_id_handler_derives_identity_of_its_own() -> None:
    """The handler answers a caller with no identity itself, and this app's
    routes no longer let it: `actor_from_request` refuses an anonymous caller
    before FastAPI validates the path, so the anonymous arm of
    `test_a_malformed_run_id_is_answered_like_any_unknown_run` now passes
    through the dependency rather than through here.

    The contract belongs to the handler and not to the route, so it is asserted
    against a route that does not carry the dependency -- which is what the
    first route to take a run id and forget it would be. Without this the two
    lines that answer it are reachable from no test at all.
    """
    other = FastAPI()
    other.add_exception_handler(
        RequestValidationError, app.exception_handlers[RequestValidationError]
    )

    @other.get("/api/runs/{run_id}")
    def read_run_without_identity(run_id: UUID) -> str:
        return str(run_id)

    response = TestClient(other).get("/api/runs/not-a-run")

    assert (response.status_code, response.json()) == (
        401,
        _refused("NOT_AUTHENTICATED"),
    )


def test_blob_store_is_rooted_at_the_environment_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CAOS_BLOB_ROOT", str(tmp_path))

    store = blob_store()

    assert store.root == tmp_path


def test_a_node_the_gate_blocked_says_so_on_the_run_surface(
    client: TestClient, lite: tuple[_Harness, UUID]
) -> None:
    """Phase 6 asked for "node states with their reasons", and after Phase 11 a
    node can be BLOCKED by the gate rather than by an edge. `waiting_on` cannot
    carry that cause -- there is no edge to name -- so the verdict travels
    beside it, read from CP-0's canonical T8 readiness, or the surface reports a
    state with no reason at all."""
    harness, viewer = lite
    _answer(harness, "CP-0", readiness={"CP-L10": "BLOCKED"})

    body = _view(_section(client, harness.case_id, harness.run_id, viewer))

    assert body["status"] == "RUNNING"
    by_module = {node["module_id"]: node for node in body["nodes"]}
    assert by_module["CP-0"]["state"] == "COMPLETE"
    assert by_module["CP-L10"]["state"] == "BLOCKED"
    assert by_module["CP-L10"]["waiting_on"] == []
    assert by_module["CP-L10"]["gate_verdict"] == "BLOCKED"
    assert by_module["CP-5"]["gate_verdict"] == "READY"


def test_a_stored_gate_record_the_markdown_does_not_bind_is_a_server_fault(
    client: TestClient, lite: tuple[_Harness, UUID]
) -> None:
    """The verdict is read out of a record this server wrote, so readiness the
    Markdown does not say is the server's own fault. A 400 would tell the caller
    their request was the problem, about bytes they do not hold."""
    harness, viewer = lite
    _answer(harness, "CP-0")
    attempt, record = _gate_record(harness)
    stored = _decoded_record(harness.blobs.get(record))
    lying = replace(
        stored,
        projections=replace(stored.projections, readiness=(("CP-5", "READY"),)),
    )
    harness.conn.execute(
        "UPDATE artifacts SET record_sha256 = %s WHERE attempt_id = %s",
        (harness.blobs.put(record_bytes(lying)), attempt),
    )
    harness.conn.commit()

    response = _section(client, harness.case_id, harness.run_id, viewer)

    assert (response.status_code, response.json()) == (
        500,
        _refused("ARTIFACT_RECORD_MISMATCH"),
    )
    harness.conn.execute(
        "UPDATE artifacts SET record_sha256 = %s WHERE attempt_id = %s",
        (harness.blobs.put(record_bytes(lying)), attempt),
    )
    harness.conn.commit()

    response = _section(client, harness.case_id, harness.run_id, viewer)

    # 500 under D3: the record is stored bytes, and a later read reads them.
    assert (response.status_code, response.json()) == (
        500,
        _refused("ARTIFACT_RECORD_MISMATCH"),
    )


def _gate_record(harness: _Harness) -> tuple[UUID, str]:
    row = harness.conn.execute(
        "SELECT attempt_id, record_sha256 FROM artifacts WHERE route_node_id = %s",
        (_node(harness, "CP-0").route_node_id,),
    ).fetchone()
    harness.conn.rollback()
    assert row is not None and row[1] is not None
    return UUID(str(row[0])), str(row[1])


def test_the_one_qa_gate_reads_as_a_gate(
    client: TestClient,
    case: tuple[StoreConnection, UUID],
    run: tuple[UUID, UUID],
    catalog: dict[str, Any],
) -> None:
    """The catalog holds exactly one QA_GATE edge, `CP-5 -> CP-6`. A node held by
    it waits for the QA verdict; every other BLOCKED node is waiting for a
    module, and a surface that rendered both the same way would hide it."""
    conn, case_id = case
    run_id, viewer = run
    pin_route(conn, run_id, resolve_route(catalog, PROFILE, "FULL_CREDIT_ASSESSMENT"))

    body = _view(_section(client, case_id, run_id, viewer))

    by_module = {node["module_id"]: node for node in body["nodes"]}
    assert by_module["CP-6"]["awaiting_gate"] is True
    assert by_module["CP-1"]["awaiting_gate"] is False
    assert sum(node["awaiting_gate"] for node in body["nodes"]) == 1


@pytest.mark.parametrize(
    ("qa_status", "held"), [("Blocked", True), ("Restricted", False), ("Passed", False)]
)
def test_a_qa_verdict_other_than_passed_blocks_without_awaiting(
    catalog: dict[str, Any], qa_status: str, held: bool
) -> None:
    """F03, as D34 left it: CP-5 answered a verdict the gate does not accept
    (`Blocked`), so CP-6 is blocked by that verdict and nothing is awaited --
    not a wait for a person. `Restricted` and `Passed` meet the gate.

    The view is asked directly over the typed result the reader reduces any
    accepted record to; the enabled portfolio-decision route covers the same
    projection over HTTP in `test_cp6_route`.
    """
    full = resolve_route(catalog, PROFILE, "FULL_CREDIT_ASSESSMENT")
    cp5 = next(n.route_node_id for n in full.nodes if n.module_id == "CP-5")
    accepted = {cp5: NodeResult(qa_status=qa_status)}
    states = node_states(full, accepted)
    readiness = readiness_from(full, accepted)
    reasons = blockers_from(full, accepted)

    by_module = {
        node.module_id: _node_view(
            full, accepted, node, states, readiness, reasons=reasons
        )
        for node in full.nodes
    }

    cp6 = by_module["CP-6"]
    assert (cp6.state, cp6.awaiting_gate, cp6.gate_verdict) == (
        "BLOCKED",
        False,
        qa_status,
    )
    gate = EdgeView(source="CP-5", type=EdgeType.QA_GATE)
    assert (gate in cp6.waiting_on) is held
    assert by_module["CP-5"].waiting_on == []


def test_node_readiness_is_the_shared_computation_node_view_builds_on(
    catalog: dict[str, Any],
) -> None:
    """`node_readiness` is the one computation of a node's unmet edges, its
    awaiting-gate flag and its readiness. It was extracted when two wires each
    had a `_node_view` and could drift apart; the legacy one in
    `caos/api/app.py` has since been retired with the run tail, so this is
    now what keeps the computation named and covered on its own rather than
    only through whichever caller happens to exercise it."""
    full = resolve_route(catalog, PROFILE, "FULL_CREDIT_ASSESSMENT")
    accepted: dict[str, NodeResult] = {}
    states = node_states(full, accepted)
    readiness = readiness_from(full, accepted)
    cp0 = next(n for n in full.nodes if n.module_id == "CP-0")

    unmet, awaiting_gate, gate_verdict = node_readiness(
        full, accepted, cp0, states, readiness
    )

    view = _node_view(full, accepted, cp0, states, readiness)
    assert [e.source for e in unmet] == [e.source for e in view.waiting_on]
    assert awaiting_gate == view.awaiting_gate
    assert gate_verdict == view.gate_verdict


def test_nothing_is_awaited_on_a_run_that_is_no_longer_running(
    client: TestClient,
    case: tuple[StoreConnection, UUID],
    run: tuple[UUID, UUID],
    catalog: dict[str, Any],
) -> None:
    conn, case_id = case
    run_id, viewer = run
    pin_route(conn, run_id, resolve_route(catalog, PROFILE, "FULL_CREDIT_ASSESSMENT"))
    block_run(conn, run_id)

    body = _view(_section(client, case_id, run_id, viewer))

    assert body["status"] == "BLOCKED"
    assert not any(node["awaiting_gate"] for node in body["nodes"])


@pytest.mark.parametrize("which", [0, 1], ids=["markdown", "record"])
def test_an_unreadable_gate_artifact_is_a_typed_server_fault(
    client: TestClient, lite: tuple[_Harness, UUID], which: int
) -> None:
    harness, viewer = lite
    _answer(harness, "CP-0")
    row = harness.conn.execute(
        "SELECT artifact_sha256, record_sha256 FROM artifacts WHERE run_id = %s",
        (harness.run_id,),
    ).fetchone()
    harness.conn.rollback()
    assert row is not None
    path = harness.blobs.path_of(str(row[which]))
    path.chmod(0o644)
    path.write_bytes(b"not a handoff")

    response = _section(client, harness.case_id, harness.run_id, viewer)

    # 500 under D3: damaged bytes stay damaged until an operator restores them.
    assert (response.status_code, response.json()) == (
        500,
        _refused("ARTIFACT_RECORD_MISMATCH"),
    )


def test_the_run_document_refuses_an_undeclared_field(
    client: TestClient, case: tuple[StoreConnection, UUID], run: tuple[UUID, UUID]
) -> None:
    """§9's closed shape, on the way out as well as in. A response model that
    let an extra key through would let a store column reach a browser because
    somebody widened a SELECT."""
    run_id, viewer = run
    body = _section(client, case[1], run_id, viewer).json()

    assert set(body) == set(RunSectionDocument.model_fields)
    with pytest.raises(ValueError, match="extra_forbidden"):
        RunSectionDocument.model_validate({**body, "budget_ceiling": "40.00"})
    widened = {**body["body"]["run"], "budget_ceiling": "40.00"}
    with pytest.raises(ValueError, match="extra_forbidden"):
        RunSectionDocument.model_validate(
            {**body, "body": {**body["body"], "run": widened}}
        )


@pytest.mark.parametrize("model", [RunSectionDocument, NodeView, EdgeView, RefusalBody])
def test_every_wire_model_forbids_an_undeclared_field(
    model: type[BaseModel],
) -> None:
    """The standing rule: every JSON success serves a named model,
    `extra="forbid"` both ways. One model left open is the hole, so the property
    is asserted of each rather than of the one that happens to be on top."""
    assert model.model_config.get("extra") == "forbid"


def test_the_wire_key_sets_are_pinned() -> None:
    """ "A new field means a model change plus an updated pinned key set". This
    is the pinned key set: a field added to a response without a decision about
    it fails here first."""
    assert set(NodeView.model_fields) == {
        "route_node_id",
        "module_id",
        "stage",
        "state",
        "waiting_on",
        "awaiting_gate",
        "gate_verdict",
        "gate_reason",
    }
    assert set(EdgeView.model_fields) == {"source", "type"}
    assert set(RefusalBody.model_fields) == {"code", "clears"}


def test_every_refusal_body_is_code_and_clears_and_nothing_else(
    client: TestClient,
) -> None:
    """The typed refusal, on the wire (brief 4.1, decision 3). A body that also
    carried a message would be the one place a document's contents could still
    get out, so `clears` is the host's constant for the code and never text
    from the request, whichever answer the route gave."""
    answers = {
        RefusalCode.RUN_NOT_FOUND: client.get(
            f"/api/v1/cases/{uuid4()}/events?run=not-a-run", headers=_as(uuid4())
        ),
        RefusalCode.CASE_NOT_FOUND: _section(client, uuid4(), None, uuid4()),
        RefusalCode.NOT_AUTHENTICATED: _section(client, uuid4(), None, None),
        RefusalCode.ENDPOINT_NOT_FOUND: client.get("/api/runs-not-declared"),
    }

    for code, response in answers.items():
        body = response.json()
        assert set(body) == {"code", "clears"} == set(RefusalBody.model_fields)
        assert RefusalBody.model_validate(body) == RefusalBody(
            code=code, clears=CLEARS[code]
        )
        assert body["clears"] == CLEARS[code]
    assert RefusalBody.model_config.get("frozen") is True
    with pytest.raises(ValueError, match="extra_forbidden"):
        RefusalBody.model_validate(
            {"code": "RUN_NOT_FOUND", "clears": "x", "refusal": "RUN_NOT_FOUND"}
        )


def test_every_refusal_code_has_a_constant_clearance() -> None:
    """`CLEARS` is total over `RefusalCode`, and each entry is a finished
    sentence: nothing in it could be filled in from a request or a document."""
    assert set(CLEARS) == set(RefusalCode)
    for code in RefusalCode:
        clears = CLEARS[code]
        assert isinstance(clears, str) and clears.strip(), code
        assert "{" not in clears and "}" not in clears and "%" not in clears, code


def test_every_refusal_code_has_an_explicit_http_status() -> None:
    """`_STATUS` is total over `RefusalCode`, the way `CLEARS` beside it is.

    A default would make a code added later answer 400 -- "your request was
    wrong" -- without anyone choosing that, which is how a store fault came to
    be served as a binding error. Being total, the table is the choice.
    """
    assert set(_STATUS) == set(RefusalCode), set(RefusalCode) - set(_STATUS)


# The owner's half of D3, decided on 18 September 2026 (§88). Each of these
# answered 400 -- "your request was wrong" -- while its clearance told the
# caller to retry: time wearing blame, the mirror of what §75 fixed. §75's one
# question decides each. The provider not answering is the only one waiting
# repairs; the other seven are an answer the provider already gave, which the
# identical request later meets again, and a new attempt is the discharge.
RETRY_SHAPED_400_DECIDED = {
    RefusalCode.PROVIDER_UNAVAILABLE: 503,
    RefusalCode.PROVIDER_OUTPUT_TRUNCATED: 500,
    RefusalCode.PROVIDER_REFUSED: 500,
    RefusalCode.PROVIDER_RESPONSE_INVALID: 500,
    RefusalCode.ENVELOPE_INVALID: 500,
    RefusalCode.ENVELOPE_UNDECLARED_FIELD: 500,
    RefusalCode.ENVELOPE_UNCITED_CLAIM: 500,
    RefusalCode.READINESS_INCOMPLETE: 500,
}


def test_every_refusal_is_classed_transient_or_permanent_and_none_is_both() -> None:
    """The owner's D3 split, stated as a partition of the whole enum rather than
    of the codes that already happened to answer 5xx.

    Every code is exactly one of: a client refusal (4xx), a permanent server
    fault (500, `PERMANENT`), or a transient one (503, `TRANSIENT`, the only
    class that says come back later). A code in neither server set could sit at
    5xx while nobody had asked whether waiting would help; a code in both would
    make the answer depend on which membership was consulted first. The first
    version of this test took its universe from the codes already at 500 or 503,
    so `INTERNAL_FAULT` at 400 was invisible to it.
    """
    assert TRANSIENT & PERMANENT == frozenset()
    client = {code for code, status in _STATUS.items() if 400 <= status < 500}
    permanent = {code for code, status in _STATUS.items() if status == 500}
    transient = {code for code, status in _STATUS.items() if status == 503}
    assert client | permanent | transient == set(RefusalCode)
    assert len(client) + len(permanent) + len(transient) == len(RefusalCode)
    assert permanent == PERMANENT
    assert transient == TRANSIENT


def test_no_400_tells_the_caller_to_retry() -> None:
    """A 400 whose clearance says retry is a claim about time wearing a status
    about blame, and none is left: the eight the owner decided (§88) carry the
    status decided for them, and a new retry-shaped 400 fails here until
    someone asks §75's question of it.

    400 exactly, not all of 4xx: `RUN_NOT_STOPPED`'s "Retry only a stopped run."
    is a precondition on a 409, the status that already means the state moved,
    and is no claim about waiting."""
    retry_shaped = {
        code
        for code, status in _STATUS.items()
        if status == 400 and CLEARS[code].startswith("Retry")
    }
    assert retry_shaped == set()
    assert {code: _STATUS[code] for code in RETRY_SHAPED_400_DECIDED} == (
        RETRY_SHAPED_400_DECIDED
    )
    assert RefusalCode.PROVIDER_UNAVAILABLE in TRANSIENT


def test_an_internal_fault_answers_500_wherever_it_is_raised(
    client: TestClient, case: tuple[StoreConnection, UUID]
) -> None:
    """The guard answered an unhandled exception 500 while a route raising
    `Refusal(INTERNAL_FAULT)` -- `caos/store/commands.py` does -- answered
    400, so one code had two statuses. It is a fault in this server that no
    waiting is promised to clear: 500, no `Retry-After`, and its clearance
    still true, since retrying is permitted and investigating is the discharge."""
    _conn, case_id = case
    app.dependency_overrides[store_connection] = _refusing(RefusalCode.INTERNAL_FAULT)

    response = _section(client, case_id, None, uuid4())

    assert (response.status_code, response.json()) == (
        500,
        _refused("INTERNAL_FAULT"),
    )
    assert "retry-after" not in response.headers
    assert RefusalCode.INTERNAL_FAULT in PERMANENT


def test_every_code_the_edge_answers_carries_the_apps_status() -> None:
    """The guard answers before routing, so it cannot use the app's handler and
    declares its own statuses. They must be the app's: a code whose status
    depended on which layer answered is how `INTERNAL_FAULT` came to be 500 at
    the edge and 400 behind it with nothing noticing.

    The second half reads every `RefusalCode` the guard's module names, so a
    code answered with a status that bypassed `EDGE_STATUS` fails here.
    `EDGE_CONFIG_INVALID` is the one exception: it is raised as a `Refusal` and
    sent as a lifespan failure, never answered by the guard over HTTP.
    """
    assert EDGE_STATUS.items() <= _STATUS.items()
    tree = ast.parse(Path(edge_module.__file__).read_text(encoding="utf-8"))
    named = {
        node.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == "RefusalCode"
    }
    answered = {code.name for code in EDGE_STATUS}
    assert named == answered | {RefusalCode.EDGE_CONFIG_INVALID.name}
    assert len(answered) == 5


def test_an_unhandled_fault_is_logged_as_its_class_and_frame_never_its_message(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """AS-6. The wire body was already a constant; the *log* was not. The
    guard re-raised into the server's logger, which writes the whole traceback
    including `str(exc)` -- and an exception that quotes its input (a pydantic
    `ValidationError` carries `input_value=`, a driver error quotes a bound
    parameter) would put source text into the App's log, which the refusal on
    the wire is careful to put nothing of.

    The class and the frame are host facts and say where to look, which is the
    same pair `caos/graph/worker.py` writes for the same reason.
    """
    faulty = FastAPI()
    faulty.add_middleware(edge_module.EdgeGuard)

    quoted = "BORROWER CONFIDENTIAL: the covenant text"

    @faulty.get("/api/v1/fault")
    def fault() -> None:
        raise RuntimeError(quoted)

    response = TestClient(faulty, raise_server_exceptions=False).get("/api/v1/fault")

    assert response.status_code == 500
    assert response.json()["code"] == "INTERNAL_FAULT"
    logged = capsys.readouterr().err
    assert "RuntimeError at " in logged
    assert "test_api_routes.py:" in logged, "the frame it was raised in"
    assert "BORROWER" not in logged and "covenant" not in logged


def test_a_permanent_fault_answers_500_and_carries_no_retry_after(
    client: TestClient, case: tuple[StoreConnection, UUID]
) -> None:
    """Read off the response, not off the map: an unconfigured store is a fault
    only an operator can repair, so nothing about coming back later is true of
    it and the answer must not say so."""
    _conn, case_id = case
    app.dependency_overrides[store_connection] = _refusing(
        RefusalCode.STORE_NOT_CONFIGURED
    )

    response = _section(client, case_id, None, uuid4())

    assert (response.status_code, response.json()) == (
        500,
        _refused("STORE_NOT_CONFIGURED"),
    )
    assert "retry-after" not in response.headers


def test_a_transient_fault_answers_503_and_names_when_to_retry(
    client: TestClient, case: tuple[StoreConnection, UUID]
) -> None:
    """A store that is not answering is the one fault here that heals with no
    one doing anything, so it keeps 503 and now says how soon to ask again --
    an integer count of seconds, which is the form a proxy can act on."""
    _conn, case_id = case
    app.dependency_overrides[store_connection] = _refusing(
        RefusalCode.STORE_UNAVAILABLE
    )

    response = _section(client, case_id, None, uuid4())

    assert (response.status_code, response.json()) == (
        503,
        _refused("STORE_UNAVAILABLE"),
    )
    assert int(response.headers["retry-after"]) == RETRY_AFTER_SECONDS


def _refusing(code: RefusalCode) -> Callable[[], StoreConnection]:
    """A store dependency that refuses `code`, so a status can be read off a
    real response without arranging the fault that produces it."""

    def dependency() -> StoreConnection:
        raise Refusal(code)

    return dependency


def test_an_undeclared_api_path_or_method_answers_endpoint_not_found_in_the_refusal_body(  # noqa: E501 -- the brief's name
    client: TestClient,
) -> None:
    """Starlette's own `{"detail": ...}` is a second refusal body, and two
    cannot coexist under `/api/`. An undeclared path is 404 and an undeclared
    method on a declared path is 405, both `ENDPOINT_NOT_FOUND`; nothing
    outside `/api/` is this contract's to answer."""
    missing = client.get("/api/not-declared", headers=_as(uuid4()))
    anonymous = client.get("/api/not-declared")
    wrong_method = client.post(f"/api/v1/cases/{uuid4()}/run", headers=_as(uuid4()))

    for response, status in ((missing, 404), (anonymous, 404), (wrong_method, 405)):
        assert (response.status_code, response.json()) == (
            status,
            _refused("ENDPOINT_NOT_FOUND"),
        )
    assert client.get("/not-api").json() == {"detail": "Not Found"}
    # One status per code (§87): the declared status is the one served for a
    # path nobody declared; 405 is routing's own answer to a known path.
    assert _STATUS[RefusalCode.ENDPOINT_NOT_FOUND] == missing.status_code


def test_the_surface_is_exactly_the_routes_it_declares(
    client: TestClient,
) -> None:
    """A route added without a test is a request path nobody agreed to. Listing
    them here means a new one has to be written down before it can ship."""
    # A section's router is included as a whole, so its routes sit one level
    # down in the app's list.
    routes = [
        inner
        for route in app.routes
        for inner in getattr(getattr(route, "original_router", None), "routes", [route])
    ]
    declared = {
        route.path: route.endpoint.__name__
        for route in routes
        if isinstance(route, APIRoute)
    }

    assert declared == {
        "/api/v1/directory": "read_directory",
        "/api/v1/book": "read_book",
        "/api/v1/cases/{case_id}/upload": "read_upload",
        "/api/v1/cases/{case_id}/run": read_run_section.__name__,
        "/api/v1/cases/{case_id}/analysis": "read_analysis",
        "/api/v1/cases/{case_id}/model": "read_model",
        "/api/v1/cases/{case_id}/report": "read_report",
        "/api/v1/cases/{case_id}/committee": "read_committee",
        "/api/v1/qualification/{evidence_sha256}": "read_qualification",
        "/api/v1/cases/{case_id}/runs/{run_id}/sources/{source_id}/pages/{page}": (
            "read_evidence_page"
        ),
        "/api/v1/cases/{case_id}/events": read_case_events.__name__,
        "/api/health": "read_health",
        "/api/v1/cases/{case_id}/runs/{run_id}/start": "start_run",
        "/api/v1/cases/{case_id}/runs/{run_id}/retry": "retry_run",
        "/api/v1/cases/{case_id}/runs/{run_id}/cancel": "cancel_run",
        "/api/v1/cases": "create_case_command",
        "/api/v1/cases/{case_id}/sources": "admit_sources",
        "/api/v1/cases/{case_id}/runs": "create_run",
        "/api/v1/cases/{case_id}/runs/{run_id}/input": "pin_input",
        "/api/v1/cases/{case_id}/runs/{run_id}/gates/{gate}/preview": (
            "read_gate_preview"
        ),
        "/api/v1/cases/{case_id}/runs/{run_id}/gates/{gate}/approval": "approve",
        "/api/v1/qualification/{evidence_sha256}/verdict": "sign_verdict",
        # Task 12.1: the seven governed writes that had no request path.
        "/api/v1/cases/{case_id}/members": "grant_standing",
        "/api/v1/cases/{case_id}/members/{user_id}/revocation": "revoke_standing",
        "/api/v1/cases/{case_id}/sources/{source_id}/withdrawal": "withdraw",
        "/api/v1/cases/{case_id}/runs/{run_id}/revisions": "save",
        "/api/v1/cases/{case_id}/revisions/{revision_id}/signature": "sign",
        "/api/v1/cases/{case_id}/revisions/{revision_id}/freeze": "freeze",
        "/api/v1/cases/{case_id}/revisions/{revision_id}/filing": "file",
    }


def test_every_section_read_depends_on_the_shared_dependencies() -> None:
    """Each section route calls the `caos.api.deps` functions directly, in
    the order identity, then any path/query parser and the case's visibility,
    then the store, blobs and bundle -- never a per-module wrapper that
    resolves them lazily.

    The parsers (`case_path`, `run_query`, `revision_query`) and `visible_case`
    are `caos.api.deps`'s too, so a route that took a copy would show here.
    `visible_case` opens the store, and stays behind identity by its own
    sub-dependencies whatever position a route gives it.
    """
    routes = {
        route.path: route
        for router in (
            directory_read,
            upload_read,
            run_read,
            analysis_read,
            model_read,
            book_read,
            reports_read,
        )
        for route in router.router.routes
        if isinstance(route, APIRoute)
    }
    # Each route first declares identity on its decorator (`IDENTITY_FIRST`),
    # which FastAPI puts at the front of the list; what follows is the
    # parameters' own order, compared below.
    leading = {
        path: route.dependant.dependencies[0].call for path, route in routes.items()
    }
    assert set(leading.values()) == {actor_from_request}
    calls = {
        path: [d.call for d in route.dependant.dependencies[1:]]
        for path, route in routes.items()
    }
    assert calls["/api/v1/directory"] == [actor_from_request, store_connection]
    # The Book is portfolio-scoped: no case in its path, so no `case_path` and
    # no `visible_case`. Standing is read per credit from the listing instead.
    assert calls["/api/v1/book"] == [
        actor_from_request,
        store_connection,
        deps.request_blobs,
        deps.methodology_bundle,
    ]
    # The request's blobs are the process's store remembering what it
    # verified (ED-7): a layer over `blob_store`, so overriding that reaches
    # every route, and each request gets a memo of its own.
    [layer] = get_dependant(path="/", call=deps.request_blobs).dependencies
    assert layer.call is blob_store
    assert calls["/api/v1/cases/{case_id}/upload"] == [
        actor_from_request,
        deps.case_path,
        deps.visible_case,
        store_connection,
    ]
    assert calls["/api/v1/cases/{case_id}/run"] == [
        actor_from_request,
        deps.case_path,
        deps.run_query,
        store_connection,
        deps.request_blobs,
        methodology_bundle,
    ]
    events = next(
        route
        for route in app.routes
        if isinstance(route, APIRoute)
        and route.path == "/api/v1/cases/{case_id}/events"
    )
    # Identity on the decorator first, then the parameters in their own order.
    assert [d.call for d in events.dependant.dependencies] == [
        actor_from_request,
        actor_from_request,
        deps.case_path,
        deps.run_query,
        deps.visible_case,
        store_connection,
    ]
    assert calls["/api/v1/cases/{case_id}/analysis"] == [
        actor_from_request,
        deps.case_path,
        deps.run_query,
        deps.visible_case,
        store_connection,
        deps.request_blobs,
        methodology_bundle,
    ]
    assert (
        calls["/api/v1/cases/{case_id}/model"]
        == calls["/api/v1/cases/{case_id}/analysis"]
    )
    committee_dependencies = [
        actor_from_request,
        deps.case_path,
        deps.run_query,
        deps.revision_query,
        store_connection,
        deps.request_blobs,
        methodology_bundle,
    ]
    assert calls["/api/v1/cases/{case_id}/committee"] == committee_dependencies
    # Report's revision is optional -- absent reads the run's head or offers its
    # first save -- and is parsed in the same place, before the store.
    assert calls["/api/v1/cases/{case_id}/report"] == [
        reports_read.report_revision if dep is deps.revision_query else dep
        for dep in committee_dependencies
    ]


def test_the_reported_digest_is_the_one_that_was_pinned(
    client: TestClient,
    case: tuple[StoreConnection, UUID],
    run: tuple[UUID, UUID],
    catalog: dict[str, Any],
) -> None:
    """The document recomputes the digest from the route it read back. That is
    only sound while it still equals the digest execution reads."""
    conn, case_id = case
    run_id, viewer = run
    pinned = pin_route(
        conn, run_id, resolve_route(catalog, PROFILE, "FULL_CREDIT_ASSESSMENT")
    )

    body = _view(_section(client, case_id, run_id, viewer))

    assert body["route_digest"] == pinned == pinned_route(conn, run_id)


def test_corrupt_route_is_a_sanitized_store_failure(
    client: TestClient,
    case: tuple[StoreConnection, UUID],
    run: tuple[UUID, UUID],
    catalog: dict[str, Any],
) -> None:
    conn, case_id = case
    run_id, viewer = run
    pin_route(conn, run_id, resolve_route(catalog, PROFILE, "LIQUIDITY_REVIEW"))
    with route_fault(conn):
        conn.execute("UPDATE run_routes SET route_digest = 'synthetic-corruption'")
    conn.commit()
    response = _section(client, case_id, run_id, viewer)
    # 500 under D3: the pin is immutable, so the next read resolves it the same.
    assert response.status_code == 500
    assert response.json() == _refused("ROUTE_IDENTITY_INVALID")


def test_each_request_path_declares_what_it_costs_the_store(
    client: TestClient,
    case: tuple[StoreConnection, UUID],
    run: tuple[UUID, UUID],
    catalog: dict[str, Any],
) -> None:
    """`scripts/io_budget.py`. A request path with no stated round-trip cost is
    how the predecessor's ~8x read amplification went unnoticed -- so the number
    is counted here, not asserted from memory.
    """
    conn, case_id = case
    run_id, viewer = run
    pin_route(conn, run_id, resolve_route(catalog, PROFILE, "FULL_CREDIT_ASSESSMENT"))
    counter = _CountingConnection(conn)
    app.dependency_overrides[store_connection] = lambda: counter

    assert _section(client, case_id, run_id, viewer).status_code == 200

    assert counter.executed == run_read.UNPINNED_INPUT_IO <= run_read.IO_BUDGET, (
        "the run document costs what it says it costs; a read that grew with "
        "the size of the route would show up here first"
    )


def test_a_process_with_no_database_refuses_to_start(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Fail at boot, not at the first request. A process that started without a
    database would answer every request with a 500 that reads like a bug in the
    route rather than a deployment pointed at nothing."""
    monkeypatch.delenv(app_module.DATABASE_URL, raising=False)

    with pytest.raises(Refusal) as caught, TestClient(app):
        pass  # pragma: no cover -- entering the client is what raises

    assert caught.value.code is RefusalCode.STORE_NOT_CONFIGURED


def test_startup_applies_the_declared_schema(
    empty_database: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ "Postgres schema in full at startup". The database here has had nothing
    applied to it, and after the app has started it holds the store's tables."""
    from caos.store import connect

    monkeypatch.setenv(app_module.DATABASE_URL, empty_database)

    with TestClient(app):
        pass

    with connect(empty_database) as conn:
        applied = conn.execute(
            "SELECT count(*) FROM information_schema.tables"
            " WHERE table_schema = 'public' AND table_name IN"
            " ('runs', 'run_events', 'case_members', 'audit_events')"
        ).fetchone()
    assert applied is not None
    assert applied[0] == 4


class _CountingConnection:
    """Counts store round trips, so the declared budget is measured."""

    def __init__(self, conn: StoreConnection) -> None:
        self._conn = conn
        self.executed = 0

    def execute(self, *args: object, **kwargs: object) -> object:
        self.executed += 1
        return self._conn.execute(*args, **kwargs)  # type: ignore[arg-type]


def test_no_route_module_parses_a_path_uuid_by_hand() -> None:
    """Every id a route reads off the path, the query or a header is parsed by
    one of `caos.api.deps`'s parsers, so the refusal a malformed id gets is
    decided in one place. `identity.py` is the boundary beneath `deps` (which
    imports it): its subject header refuses `NOT_AUTHENTICATED`, and it cannot
    import the module that depends on it.

    The scan names `caos/api` and asserts it read something (MAX-N01): it
    named the retired `server/api`, visited no file and passed vacuously."""
    api = Path(__file__).resolve().parents[1] / "caos" / "api"
    scanned = sorted(api.rglob("*.py"))
    assert {"app.py", "deps.py", "analysis.py", "cases.py"} <= {
        path.name for path in scanned
    }, "the scan did not reach the route modules"
    hand_rolled = sorted(
        str(path.relative_to(api))
        for path in scanned
        if path.name not in ("deps.py", "identity.py")
        and "ValueError" in path.read_text(encoding="utf-8")
        and "UUID(" in path.read_text(encoding="utf-8")
    )
    assert hand_rolled == [], hand_rolled


def test_the_shared_parsers_refuse_in_the_declared_body_and_chain_nothing() -> None:
    """One parser per id, each refusing the code its route answers, with the
    input -- the ValueError quotes it -- chained behind none of them."""
    cases: list[tuple[Callable[[], object], RefusalCode]] = [
        (lambda: deps.case_path("not-a-case"), RefusalCode.CASE_NOT_FOUND),
        (lambda: deps.run_path("not-a-run"), RefusalCode.RUN_NOT_FOUND),
        (lambda: deps.run_query("not-a-run"), RefusalCode.RUN_NOT_FOUND),
        (lambda: deps.revision_query(None), RefusalCode.DELIVERABLE_NOT_FOUND),
        (lambda: deps.revision_query("x"), RefusalCode.DELIVERABLE_NOT_FOUND),
        # The three path siblings, each answering a different code on purpose:
        # a source nobody may use and a revision that is not there are private
        # 404s, while a malformed member subject is a malformed *request* --
        # the caller already reads this case, so hiding it would say nothing.
        (
            lambda: deps.source_path("not-a-source"),
            RefusalCode.EVIDENCE_NOT_AVAILABLE,
        ),
        (
            lambda: deps.revision_path("not-a-revision"),
            RefusalCode.DELIVERABLE_NOT_FOUND,
        ),
        (lambda: deps.member_path("not-a-member"), RefusalCode.REQUEST_INVALID),
        (
            lambda: deps.parse_uuid("", RefusalCode.PAGE_NOT_AVAILABLE),
            RefusalCode.PAGE_NOT_AVAILABLE,
        ),
    ]
    for parse, code in cases:
        with pytest.raises(Refusal) as caught:
            parse()
        assert caught.value.code is code
        assert caught.value.__cause__ is None and caught.value.__context__ is None
    known = uuid4()
    assert deps.case_path(str(known)) == deps.run_path(str(known)) == known
    assert deps.run_query(None) is None
    assert deps.run_query(str(known)) == deps.revision_query(str(known)) == known
    assert deps.source_path(str(known)) == known
    assert deps.revision_path(str(known)) == deps.member_path(str(known)) == known


def test_case_visibility_is_one_rule_wherever_the_standing_was_read() -> None:
    """`readable` is the floor every case read applies -- `visible_case` to the
    standing it reads on its own, the Run and evidence reads to the standing
    their projection row carries -- so a stranger, a revoked member and an
    unknown case are the same private answer everywhere."""
    for standing in Standing:
        assert deps.readable(standing) is standing
    with pytest.raises(Refusal) as caught:
        deps.readable(None)
    assert caught.value.code is RefusalCode.CASE_NOT_FOUND
    assert deps.READ_REQUIRES is Standing.READER


def test_a_stranger_with_a_malformed_run_is_answered_about_the_case(
    client: TestClient, case: tuple[StoreConnection, UUID]
) -> None:
    """`run_path` is declared after the standing dependency on every command
    route that takes a run, so the run id is parsed only once the case is
    visible: a stranger learns nothing from a malformed run id, and a member
    gets `RUN_NOT_FOUND`. The gate preview is the route with no write floor."""
    conn, case_id = case
    member = uuid4()
    grant(conn, case_id=case_id, user_id=member, standing=Standing.READER)
    conn.commit()
    path = f"/api/v1/cases/{case_id}/runs/not-a-run/gates/source-set/preview"

    stranger = client.get(path, headers=_as(uuid4()))
    seen = client.get(path, headers=_as(member))

    assert (stranger.status_code, stranger.json()) == (404, _refused("CASE_NOT_FOUND"))
    assert (seen.status_code, seen.json()) == (404, _refused("RUN_NOT_FOUND"))


def test_every_case_command_ends_in_the_governed_envelope() -> None:
    """`governed` (digest, `run_command`, receipt) is the one envelope; the
    command modules no longer spell it out. A verdict is the exception: it has
    no case to scope, so its one transaction is its own (§65)."""
    for module in (cases_command, runs_command, execution_command):
        source = Path(str(module.__file__)).read_text(encoding="utf-8")
        assert "run_command(" not in source, module.__name__
        assert "governed(" in source, module.__name__
    verdict = Path(str(qualification_command.__file__)).read_text(encoding="utf-8")
    assert "governed(" not in verdict
    request = request_module.CommandRequest("CREATE_RUN", None, None, None, {"a": 1})
    assert request.digest() == request_digest(
        "CREATE_RUN", case_id=None, run_id=None, gate=None, body={"a": 1}
    )


def test_the_gateway_helpers_answer_the_same_for_the_guard_and_the_app() -> None:
    """`is_api_path`, `refusal_body` and `startup_failed` are the guard's, the
    dispatcher's and the app's one answer each."""
    assert [is_api_path(p) for p in ("/api", "/api/", "/api/v1/x", "/apix", "/")] == [
        True,
        True,
        True,
        False,
        False,
    ]
    body = refusal_body(RefusalCode.ENDPOINT_NOT_FOUND)
    assert RefusalBody.model_validate_json(body) == RefusalBody(
        code=RefusalCode.ENDPOINT_NOT_FOUND,
        clears=CLEARS[RefusalCode.ENDPOINT_NOT_FOUND],
    )
    assert app_module._body(RefusalCode.ENDPOINT_NOT_FOUND, 404).body == body
    sent: list[Message] = []

    async def receive() -> Message:
        return {"type": "lifespan.startup"}

    async def send(message: Message) -> None:
        sent.append(message)

    asyncio.run(startup_failed(receive, send))
    assert sent == [
        {
            "type": "lifespan.startup.failed",
            "message": RefusalCode.EDGE_CONFIG_INVALID.value,
        }
    ]


def test_an_unknown_gate_slug_is_routings_own_404_before_any_connection() -> None:
    """`path_gate` maps the path's slug to a `Gate` and raises a bare
    `HTTPException` for anything else -- deliberately not a `Refusal`, because
    a slug the router does not carry is a route that does not exist, answered
    before an idempotency key or a store connection is asked for. The two
    declared slugs are asserted beside it so a rename cannot pass by making
    every slug unknown."""
    from starlette.requests import Request

    from caos.api.commands.runs import path_gate
    from caos.store.gates import Gate

    def _request(slug: str) -> Request:
        return Request({"type": "http", "path_params": {"gate": slug}})

    assert path_gate(_request("source-set")) is Gate.SOURCE_SET
    assert path_gate(_request("research-plan")) is Gate.RESEARCH_PLAN

    with pytest.raises(HTTPException) as caught:
        path_gate(_request("no-such-gate"))

    assert caught.value.status_code == 404


def test_every_governed_write_goes_through_the_one_envelope() -> None:
    """`governed` is where the digest, the replay under the key, the case lock
    and the receipt's validation against its declared model are wired together.
    A command that reached `run_command` itself would get the unit and skip
    `command_response`, so its answer would never be checked against the model
    it declares -- and nothing else in the tree would notice.

    Written as the shape of the hand-rolled-parser test above, and for the same
    reason: what must not exist cannot be proved by testing what does.
    `qualification.py` is the stated exception and calls neither -- its write is
    `record_verdict` in its own transaction, which its docstring says out loud.
    """
    commands = Path(__file__).resolve().parents[1] / "caos" / "api" / "commands"
    callers = sorted(
        path.name
        for path in commands.rglob("*.py")
        if re.search(r"^\s*(?:\w+ = )?run_command\(", path.read_text("utf-8"), re.M)
    )
    assert callers == ["_request.py"], callers

    # A module that declares a *write* route, by the decorator rather than by
    # its name: `availability.py` sits here and declares none, and a module
    # added tomorrow must be judged on what it serves, not on what it is called.
    writes = re.compile(r"@router\.(?:post|put|patch|delete)\(")
    declaring = sorted(
        path.name
        for path in commands.rglob("*.py")
        if writes.search(path.read_text("utf-8"))
    )
    assert declaring, "no module declares a write route; the reader read nothing"
    for name in declaring:
        if name == "qualification.py":
            continue  # the stated exception; its own docstring says why
        module = import_module(f"caos.api.commands.{name[:-3]}")
        # The object, not the spelling: a module that defined its own helper
        # called `governed` would satisfy a text search and bypass the envelope.
        assert getattr(module, "governed", None) is governed, name

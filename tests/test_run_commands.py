"""Task 4.2 slice 4.2e: route selection, subject pin, gate preview and approval.

`create_run`, `pin_input`, `read_gate_preview`, `approve` and `path_gate`,
through the real app against PostgreSQL. A refusal commits nothing.
"""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from command_fixtures import command_client, command_headers, member
from fastapi.testclient import TestClient
from httpx2 import Response
from run_terminals import fail_run

from caos.api import app as app_module
from caos.api.commands import runs as runs_command
from caos.api.deps import methodology_bundle, store_connection
from caos.api.reads import run as run_read
from caos.api.wire import CLEARS
from caos.blobs import BlobStore
from caos.boundary_text import BoundaryText
from caos.evidence.ingest import Document, admit_pack
from caos.graph.route import (
    MODEL_MODULE,
    RouteExtensions,
    resolve_route,
    route_digest,
)
from caos.methodology.vendor import catalog
from caos.refusals import RefusalCode
from caos.store import StoreConnection
from caos.store.audit import audit_trail, digest_of
from caos.store.commands import request_digest
from caos.store.events import events_of
from caos.store.gates import (
    Gate,
    GateState,
    gate_preview,
    gate_state,
    withdraw_source,
)
from caos.store.members import Standing, grant, revoke
from caos.store.routes import pinned_route, resolved_route
from caos.store.run_inputs import load_run_input
from caos.store.runs import block_run, create_case, start_run
from caos.store.source_sets import snapshot_source_set

__all__ = ["command_client"]

ROUTE = {
    "profile_id": "LITE_CREDIT_22",
    "selection_id": "LITE_EARNINGS_UPDATE",
    "supersedes": None,
    "model_extension": False,
}
# The one enabled pathway that runs every owner CP-CF reads (`MODEL_OWNERS`).
MODEL_ROUTE = {
    **ROUTE,
    "profile_id": "FULL_CREDIT_32",
    "selection_id": "RELATIVE_VALUE",
    "model_extension": True,
}
SUBJECT = {
    "issuer_id": "EXAMPLE",
    "issuer_name": "Example Holdings plc",
    "reporting_period": "FY2025",
    "analysis_date": "2026-09-08",
}
PIN = {"subject": SUBJECT, "research": None}
# One of the two advertised research routes (R24-01): CP-0 -> CP-DR,
# anchored, so the vendor's own placement is consumer `NONE` after `CP-0`
# (`CP_DR_RESEARCH_BRIEF_V1.md`). The caller-authored fields only -- `schema`,
# `mode`, the CP-0 scope/subject identity and `source_mode` are the host's,
# filled in by `linked_research_brief` from the pinned `SUBJECT`.
RESEARCH_ROUTE = {**ROUTE, "selection_id": "LITE_DEEP_RESEARCH"}
RESEARCH_BRIEF = {
    "decision_context": "Test the liquidity assumption before the screen",
    "as_of_date": "2026-09-08",
    "time_horizon": "Next 12 months",
    "budget": "standard",
    "authorization_basis": "The task instruction to research this issuer",
    "exclusions": "No web or model-memory sources; no trade recommendation",
    "questions": [
        {
            "question_id": "RQ-headroom",
            "question": (
                "What undrawn committed facilities did the issuer report at year end?"
            ),
            "decision_relevance": "Sets the liquidity headroom assumption",
            "consumer_module_id": "NONE",
            "after_module_id": "CP-0",
            "evidence_needed": "The issuer's own year-end disclosure",
            "completion_test": "A supported answer with contrary evidence",
        }
    ],
}
SOURCE_SET, RESEARCH_PLAN = "gates/source-set/", "gates/research-plan/"
TABLES = "runs run_routes run_inputs source_set_versions run_gates audit_events"


@pytest.fixture
def client(command_client: TestClient) -> TestClient:
    return command_client


@pytest.fixture
def sourced(case: tuple[StoreConnection, UUID], tmp_path: Path) -> UUID:
    """One live source on the case, admitted into the blob root the app serves."""
    conn, case_id = case
    [source_id] = _admit(conn, case_id, tmp_path, "report.txt")
    return source_id


def _admit(conn: StoreConnection, case_id: UUID, root: Path, name: str) -> list[UUID]:
    data = f"Total debt in {name} was USD 1,240.0m\n".encode()
    document = Document(filename=BoundaryText.of(name), data=data)
    admitted = admit_pack(
        conn, BlobStore(root / "blobs"), case_id=case_id, documents=[document]
    )
    conn.commit()
    return admitted


def _effects(conn: StoreConnection) -> tuple[int, ...]:
    """Everything a command could commit, counted."""
    counts = []
    for table in [*TABLES.split(), "command_requests"]:
        row = conn.execute(f"SELECT count(*) FROM {table}").fetchone()
        assert row is not None
        counts.append(int(row[0]))
    conn.rollback()
    return tuple(counts)


def _path(case_id: UUID, run: object = None, tail: str = "") -> str:
    runs = f"/api/v1/cases/{case_id}/runs"
    return runs if run is None else f"{runs}/{run}/{tail}"


def _send(  # noqa: PLR0913 -- the request and its identity
    client: TestClient,
    path: str,
    user: UUID | None,
    body: object = None,
    *,
    role: str = "ANALYST",
    key: UUID | None = None,
) -> Response:
    """A GET without a body, a POST with one."""
    headers = {} if user is None else command_headers(user, role=role, key=key)
    if body is None:
        got: Response = client.get(path, headers=headers)
        return got
    posted: Response = client.post(path, headers=headers, json=body)
    return posted


def _outcome(answer: Response) -> str:
    return f"{answer.status_code} {answer.json().get('code')}"


def _run(client: TestClient, case_id: UUID, writer: UUID, *, pin: bool) -> UUID:
    created = _send(client, _path(case_id), writer, ROUTE)
    assert created.status_code == 201, created.text
    run_id = UUID(created.json()["run_id"])
    if pin:
        pinned = _send(client, _path(case_id, run_id, "input"), writer, PIN)
        assert pinned.status_code == 200, pinned.text
    return run_id


def _digests(
    client: TestClient, case_id: UUID, run_id: UUID, user: UUID, gate: str = SOURCE_SET
) -> dict[str, str]:
    preview = _send(client, _path(case_id, run_id, gate + "preview"), user)
    assert preview.status_code == 200, preview.text
    return {k: preview.json()[k] for k in ("preview_sha256", "input_fingerprint")}


def test_only_an_adapter_route_can_be_selected(
    client: TestClient,
    case: tuple[StoreConnection, UUID],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn, case_id = case
    writer = member(conn, case_id)
    resolved: list[tuple[str, str]] = []
    real = getattr(runs_command, "resolve_route", None)

    def watched(
        catalog: object, profile: str, selection: str, **kwargs: object
    ) -> object:
        resolved.append((profile, selection))
        assert real is not None
        return real(catalog, profile, selection, **kwargs)

    monkeypatch.setattr(runs_command, "resolve_route", watched, raising=False)
    before = _effects(conn)
    for profile, selection in [
        ("FULL_CREDIT_32", "NO_SUCH_PATHWAY"),
        ("LITE_CREDIT_22", "NO_SUCH_PATHWAY"),
        ("NO_SUCH_PROFILE", "LITE_EARNINGS_UPDATE"),
    ]:
        body = {**ROUTE, "profile_id": profile, "selection_id": selection}
        refused = _send(client, _path(case_id), writer, body)
        assert _outcome(refused) == "400 ROUTE_NOT_ENABLED"
    assert resolved == [], "a disabled pair is refused before resolution"
    extra = _send(client, _path(case_id), writer, {**ROUTE, "route": []})
    assert _outcome(extra) == "400 REQUEST_INVALID"
    assert _effects(conn) == before

    created = _send(client, _path(case_id), writer, ROUTE)

    assert created.status_code == 201
    run_id = UUID(created.json()["run_id"])
    assert resolved == [(ROUTE["profile_id"], ROUTE["selection_id"])]
    assert created.json() == {
        "case_id": str(case_id),
        "run_id": str(run_id),
        "route_digest": pinned_route(conn, run_id),
    }
    assert [e.name for e in events_of(conn, run_id)] == ["ROUTE_PINNED"]
    [entry] = audit_trail(conn, case_id)
    conn.rollback()
    assert (entry.action, entry.actor_id) == ("RUN_CREATED", writer)


def test_a_run_may_request_the_model_extension_and_its_pin_carries_cp_cf(
    client: TestClient, case: tuple[StoreConnection, UUID]
) -> None:
    """The flag is a route-selection input (invariant 10): it changes the
    resolved node list, so it is inside the digest the pin carries, and the
    pinned route read back is the route the same selection resolves again."""
    conn, case_id = case
    writer = member(conn, case_id)
    table = catalog(methodology_bundle())
    extended = resolve_route(
        table,
        "FULL_CREDIT_32",
        "RELATIVE_VALUE",
        extensions=RouteExtensions(model_extension=True),
    )
    plain = resolve_route(table, "FULL_CREDIT_32", "RELATIVE_VALUE")

    created = _send(client, _path(case_id), writer, MODEL_ROUTE)
    ordinary = _send(
        client, _path(case_id), writer, {**MODEL_ROUTE, "model_extension": False}
    )

    assert (created.status_code, ordinary.status_code) == (201, 201), created.text
    with_model = UUID(created.json()["run_id"])
    without = UUID(ordinary.json()["run_id"])
    pinned = resolved_route(conn, with_model)
    assert pinned == extended
    assert MODEL_MODULE in [node.module_id for node in pinned.nodes]
    assert created.json()["route_digest"] == route_digest(extended)
    assert resolved_route(conn, without) == plain
    assert (
        ordinary.json()["route_digest"] == route_digest(plain) != route_digest(extended)
    )
    # Resolution is pure: the same selection resolves the same digest again.
    again = resolve_route(
        table,
        "FULL_CREDIT_32",
        "RELATIVE_VALUE",
        extensions=RouteExtensions(model_extension=True),
    )
    assert route_digest(again) == pinned_route(conn, with_model)
    trail = audit_trail(conn, case_id)
    conn.rollback()
    assert [entry.action for entry in trail] == ["RUN_CREATED", "RUN_CREATED"]


def test_an_extended_run_pins_its_input_and_shows_cp_cf_on_the_run_document(
    client: TestClient, case: tuple[StoreConnection, UUID], sourced: UUID
) -> None:
    """The flag reaches the steps after creation: the subject pins, the gate
    previews, and the Run document draws CP-CF as a node of the pinned route."""
    conn, case_id = case
    writer = member(conn, case_id)
    approver = member(conn, case_id, Standing.APPROVER)
    created = _send(client, _path(case_id), writer, MODEL_ROUTE)
    assert created.status_code == 201, created.text
    run_id = UUID(created.json()["run_id"])

    pinned = _send(client, _path(case_id, run_id, "input"), writer, PIN)
    assert pinned.status_code == 200, pinned.text
    assert _digests(client, case_id, run_id, approver)
    nodes = _run_view(client, case_id, run_id, writer)["nodes"]
    assert isinstance(nodes, list)
    assert MODEL_MODULE in [node["module_id"] for node in nodes]


def test_the_model_extension_is_refused_on_a_pathway_without_its_owners(
    client: TestClient, case: tuple[StoreConnection, UUID]
) -> None:
    """LITE earnings runs none of CP-1, CP-2G, CP-4: CP-CF would read inputs
    that are not there, so the selection is refused before anything commits."""
    conn, case_id = case
    writer = member(conn, case_id)
    before = _effects(conn)

    refused = _send(client, _path(case_id), writer, {**ROUTE, "model_extension": True})

    assert _outcome(refused) == "400 ROUTE_EXTENSION_OWNER_MISSING"
    assert _effects(conn) == before


def test_the_model_extension_is_stated_on_every_request(
    client: TestClient, case: tuple[StoreConnection, UUID]
) -> None:
    """An absent key is a malformed body, not a default -- and the flag is part
    of the request a key binds, so one key cannot create both routes."""
    conn, case_id = case
    writer = member(conn, case_id)
    absent = {k: v for k, v in ROUTE.items() if k != "model_extension"}
    assert _outcome(_send(client, _path(case_id), writer, absent)) == (
        "400 REQUEST_INVALID"
    )
    for wrong in ("true", 1, None):
        body = {**MODEL_ROUTE, "model_extension": wrong}
        assert _outcome(_send(client, _path(case_id), writer, body)) == (
            "400 REQUEST_INVALID"
        )

    key = uuid4()
    first = _send(client, _path(case_id), writer, MODEL_ROUTE, key=key)
    assert first.status_code == 201, first.text
    flipped = {**MODEL_ROUTE, "model_extension": False}
    reused = _send(client, _path(case_id), writer, flipped, key=key)
    assert _outcome(reused) == "409 IDEMPOTENCY_KEY_REUSED"


def _refusal(code: str) -> dict[str, str]:
    """The one refusal body: the code and its host-constant clearance."""
    return {"code": code, "clears": CLEARS[RefusalCode(code)]}


def _ended_blocked(conn: StoreConnection, case_id: UUID) -> UUID:
    """A run of the case that ended BLOCKED, committed."""
    run_id = start_run(conn, case_id)
    conn.commit()
    assert block_run(conn, run_id)
    return run_id


def _run_view(
    client: TestClient, case_id: UUID, run_id: UUID, user: UUID
) -> dict[str, object]:
    """The displayed run of the Run section document, as `user` reads it."""
    got = _send(client, f"/api/v1/cases/{case_id}/run?run={run_id}", user)
    assert got.status_code == 200, got.text
    view = got.json()["body"]["run"]
    assert isinstance(view, dict)
    return view


def test_a_successor_run_links_a_blocked_run_of_its_case(
    client: TestClient, case: tuple[StoreConnection, UUID]
) -> None:
    """§72: a BLOCKED run is answered by a new run that names it, never by a
    resume. The command writes `runs.supersedes_run_id` in the unit that makes
    the run, the audit payload binds the predecessor beside the selection, and
    both run documents carry the link -- `supersedes` on the successor,
    `superseded_by` on the run it answers. A second successor for the same
    predecessor is refused `RUN_ALREADY_SUPERSEDED`, and nothing of it lands."""
    conn, case_id = case
    writer = member(conn, case_id)
    blocked = _ended_blocked(conn, case_id)
    body = {**ROUTE, "supersedes": str(blocked)}

    created = _send(client, _path(case_id), writer, body)

    assert created.status_code == 201, created.text
    successor = UUID(created.json()["run_id"])
    assert conn.execute(
        "SELECT supersedes_run_id FROM runs WHERE run_id = %s", (successor,)
    ).fetchone() == (blocked,)
    [entry] = audit_trail(conn, case_id)
    conn.rollback()
    assert entry.action == "RUN_CREATED"
    assert entry.payload_sha256 == digest_of(
        {
            **body,
            "route_digest": pinned_route(conn, successor),
            "request_sha256": request_digest(
                "CREATE_RUN", case_id=case_id, run_id=None, gate=None, body=body
            ),
        }
    ), "the audit payload binds the predecessor"
    conn.rollback()
    after = _run_view(client, case_id, successor, writer)
    before = _run_view(client, case_id, blocked, writer)
    assert (after["supersedes"], after["superseded_by"]) == (str(blocked), None)
    assert (before["supersedes"], before["superseded_by"]) == (None, str(successor))

    effects = _effects(conn)
    again = _send(client, _path(case_id), writer, body)
    assert _outcome(again) == "409 RUN_ALREADY_SUPERSEDED"
    assert again.json() == _refusal("RUN_ALREADY_SUPERSEDED")
    assert _effects(conn) == effects


def test_a_successor_for_a_running_run_or_another_case_is_refused(
    client: TestClient, case: tuple[StoreConnection, UUID]
) -> None:
    """Only a BLOCKED run of the path's case can be answered. A run in any
    other status is `RUN_NOT_BLOCKED`; a run of another case is the same
    private `RUN_NOT_FOUND` -- status, code and clearance -- as a run that does
    not exist, so neither answer says the other run is there. Every refusal is
    inside the unit: nothing is inserted, no receipt is recorded, and the key
    the refused request carried is not burned."""
    conn, case_id = case
    writer = member(conn, case_id)
    running = start_run(conn, case_id)
    conn.commit()
    elsewhere = create_case(conn, BoundaryText.of("Another issuer"))
    conn.commit()
    foreign = _ended_blocked(conn, elsewhere)
    before = _effects(conn)
    key = uuid4()

    not_blocked = _send(
        client, _path(case_id), writer, {**ROUTE, "supersedes": str(running)}, key=key
    )
    other_case = _send(
        client, _path(case_id), writer, {**ROUTE, "supersedes": str(foreign)}
    )
    unknown = _send(
        client, _path(case_id), writer, {**ROUTE, "supersedes": str(uuid4())}
    )

    assert _outcome(not_blocked) == "409 RUN_NOT_BLOCKED"
    assert not_blocked.json() == _refusal("RUN_NOT_BLOCKED")
    assert (other_case.status_code, other_case.json()) == (
        404,
        _refusal("RUN_NOT_FOUND"),
    )
    assert (unknown.status_code, unknown.json()) == (404, _refusal("RUN_NOT_FOUND"))
    assert _effects(conn) == before, "nothing inserted, no receipt"
    # The refused request left no receipt, so its key answers a fresh request.
    assert _send(client, _path(case_id), writer, ROUTE, key=key).status_code == 201


def test_the_subject_pin_snapshots_live_sources_once(
    client: TestClient,
    case: tuple[StoreConnection, UUID],
    sourced: UUID,
    tmp_path: Path,
) -> None:
    conn, case_id = case
    writer = member(conn, case_id)
    run_id = _run(client, case_id, writer, pin=False)
    ended = _run(client, case_id, writer, pin=False)
    assert fail_run(conn, ended)
    foreign = start_run(conn, create_case(conn, BoundaryText.of("Other 2026")))
    conn.commit()
    before = _effects(conn)
    invalid = {"subject": {**SUBJECT, "analysis_date": "2026-02-30"}, "research": None}
    for run, body, outcome in [
        (run_id, invalid, "400 REQUEST_INVALID"),
        (foreign, PIN, "404 RUN_NOT_FOUND"),
        ("not-a-run", PIN, "404 RUN_NOT_FOUND"),
        (ended, PIN, "409 RUN_NOT_RUNNING"),  # its snapshot rolls back too
    ]:
        answer = _send(client, _path(case_id, run, "input"), writer, body)
        assert _outcome(answer) == outcome
    assert _effects(conn) == before

    pinned = _send(client, _path(case_id, run_id, "input"), writer, PIN)

    assert pinned.status_code == 200, pinned.text
    stored = load_run_input(conn, run_id)
    assert stored is not None
    assert pinned.json() == {
        "run_id": str(run_id),
        "source_set_version": stored.source_version,
        "input_fingerprint": stored.input_fingerprint,
    }
    assert audit_trail(conn, case_id)[-1].action == "RUN_INPUT_PINNED"
    conn.rollback()
    assert _effects(conn)[3] == 1, "one source-set version"

    # A new source, then a second pin under a new key: a conflict, no snapshot.
    _admit(conn, case_id, tmp_path, "later.txt")
    before = _effects(conn)
    again = _send(client, _path(case_id, run_id, "input"), writer, PIN)
    assert _outcome(again) == "409 RUN_INPUT_ALREADY_PINNED"
    assert _effects(conn) == before


def test_a_research_route_requires_and_accepts_a_bound_brief(
    client: TestClient, case: tuple[StoreConnection, UUID], sourced: UUID
) -> None:
    """R24-01: the store requires a research brief for the two advertised
    research routes before it will pin their input, but Pin input accepted
    only a subject -- neither the command nor its wire model could carry one,
    so both research workflows stopped before execution. The wire model, the
    command, its request digest/idempotency (`body.model_dump` unchanged) and
    the store's `pin_run_input_in` now carry a caller's brief through, while
    the store's own route-specific validation is untouched: a subject alone
    on this route still refuses, exactly as before."""
    conn, case_id = case
    writer = member(conn, case_id)
    approver = member(conn, case_id, Standing.APPROVER)
    created = _send(client, _path(case_id), writer, RESEARCH_ROUTE)
    assert created.status_code == 201, created.text
    run_id = UUID(created.json()["run_id"])

    subject_only = _send(client, _path(case_id, run_id, "input"), writer, PIN)
    assert _outcome(subject_only) == "500 RUN_INPUT_INVALID"

    pinned = _send(
        client,
        _path(case_id, run_id, "input"),
        writer,
        {"subject": SUBJECT, "research": RESEARCH_BRIEF},
    )
    assert pinned.status_code == 200, pinned.text
    stored = load_run_input(conn, run_id)
    assert stored is not None and stored.research_json is not None
    conn.rollback()

    # Both gates -- SOURCE_SET and the research route's own RESEARCH_PLAN --
    # now preview and approve: the pinned run is no longer stuck before
    # execution.
    for slug in (SOURCE_SET, RESEARCH_PLAN):
        digests = _digests(client, case_id, run_id, approver, slug)
        approved = _send(
            client, _path(case_id, run_id, slug + "approval"), approver, digests
        )
        assert approved.status_code == 200, approved.text
    assert {gate_state(conn, run_id, gate) for gate in Gate} == {GateState.RELEASED}


def test_approval_of_a_stale_or_transplanted_preview_is_a_conflict(
    client: TestClient,
    case: tuple[StoreConnection, UUID],
    sourced: UUID,
    tmp_path: Path,
) -> None:
    conn, case_id = case
    writer = member(conn, case_id)
    approver = member(conn, case_id, Standing.APPROVER)
    first = _run(client, case_id, writer, pin=True)
    second = _run(client, case_id, writer, pin=True)
    unpinned = _run(client, case_id, writer, pin=False)
    other = create_case(conn, BoundaryText.of("Other 2026"))
    grant(conn, case_id=other, user_id=writer, standing=Standing.WRITER)
    grant(conn, case_id=other, user_id=approver, standing=Standing.APPROVER)
    conn.commit()
    _admit(conn, other, tmp_path, "other.txt")
    foreign = _run(client, other, writer, pin=True)
    of_first = _digests(client, case_id, first, approver)
    of_plan = _digests(client, case_id, first, approver, RESEARCH_PLAN)
    of_foreign = _digests(client, other, foreign, approver)
    approval = SOURCE_SET + "approval"
    before = _effects(conn)

    for run, digests, outcome in [
        (second, of_first, "409 GATE_APPROVAL_MISMATCH"),  # another run's preview
        (first, of_plan, "409 GATE_APPROVAL_MISMATCH"),  # another gate's preview
        (first, {**of_first, "preview_sha256": "0" * 64}, "409 GATE_APPROVAL_MISMATCH"),
        # Another case's run under this case's path, with its own exact preview.
        (foreign, of_foreign, "404 RUN_NOT_FOUND"),
        (unpinned, of_first, "409 RUN_INPUT_NOT_PINNED"),
    ]:
        answer = _send(client, _path(case_id, run, approval), approver, digests)
        assert _outcome(answer) == outcome
    assert _effects(conn) == before

    # A pinned member withdrawn after the preview was read.
    withdraw_source(conn, case_id=case_id, source_id=sourced, actor_id=writer)
    before = _effects(conn)
    withdrawn = _send(client, _path(case_id, first, approval), approver, of_first)
    assert _outcome(withdrawn) == "409 EVIDENCE_NOT_AVAILABLE"
    assert _effects(conn) == before
    assert gate_state(conn, first, Gate.SOURCE_SET) is GateState.OPEN

    # The exact preview of a live run of the path's case releases its gate.
    approved = _send(client, _path(other, foreign, approval), approver, of_foreign)
    assert approved.status_code == 200, approved.text
    assert (
        approved.json() == {"run_id": str(foreign), "gate": "SOURCE_SET"} | of_foreign
    )
    assert gate_state(conn, foreign, Gate.SOURCE_SET) is GateState.RELEASED
    entry = audit_trail(conn, other)[-1]
    conn.rollback()
    assert (entry.action, entry.actor_id) == ("GATE_RELEASED:SOURCE_SET", approver)


def test_approval_on_a_terminal_run_is_refused(
    client: TestClient, case: tuple[StoreConnection, UUID], sourced: UUID
) -> None:
    conn, case_id = case
    writer = member(conn, case_id)
    approver = member(conn, case_id, Standing.APPROVER)
    run_id = _run(client, case_id, writer, pin=True)
    digests = _digests(client, case_id, run_id, approver)
    assert fail_run(conn, run_id)
    before = _effects(conn)

    path = _path(case_id, run_id, SOURCE_SET + "approval")
    refused = _send(client, path, approver, digests)

    assert _outcome(refused) == "409 RUN_NOT_RUNNING"
    assert _effects(conn) == before
    assert _digests(client, case_id, run_id, approver) == digests, (
        "the historical preview stays readable; it releases nothing"
    )


def test_a_preview_is_exact_content_and_grants_nothing(
    client: TestClient, case: tuple[StoreConnection, UUID], sourced: UUID
) -> None:
    conn, case_id = case
    writer = member(conn, case_id)
    reader = member(conn, case_id, Standing.READER)
    run_id = _run(client, case_id, writer, pin=True)
    unpinned = _run(client, case_id, writer, pin=False)
    foreign = start_run(conn, create_case(conn, BoundaryText.of("Other 2026")))
    conn.commit()
    before = _effects(conn)

    for slug, gate in zip((SOURCE_SET, RESEARCH_PLAN), Gate, strict=True):
        answer = _send(client, _path(case_id, run_id, slug + "preview"), reader)
        assert answer.status_code == 200, answer.text
        body = answer.json()
        expected = gate_preview(conn, run_id, gate)
        conn.rollback()
        assert body.pop("observed_at").endswith(("Z", "+00:00"))
        assert body == {
            "run_id": str(run_id),
            "gate": gate.value,
            "content": expected.content,
            "preview_sha256": sha256(expected.content.encode()).hexdigest(),
            "input_fingerprint": expected.input_fingerprint,
        }

    assert _effects(conn) == before, "reading a preview writes nothing"
    assert {gate_state(conn, run_id, gate) for gate in Gate} == {GateState.OPEN}
    conn.rollback()
    for run, tail, outcome in [
        (run_id, "gates/SOURCE_SET/preview", "404 ENDPOINT_NOT_FOUND"),
        (unpinned, SOURCE_SET + "preview", "409 RUN_INPUT_NOT_PINNED"),
        (foreign, SOURCE_SET + "preview", "404 RUN_NOT_FOUND"),
        ("nope", SOURCE_SET + "preview", "404 RUN_NOT_FOUND"),
    ]:
        assert _outcome(_send(client, _path(case_id, run, tail), reader)) == outcome


def test_a_command_replays_its_receipt_and_refuses_a_reused_key(
    client: TestClient, case: tuple[StoreConnection, UUID], sourced: UUID
) -> None:
    conn, case_id = case
    writer = member(conn, case_id)
    approver = member(conn, case_id, Standing.APPROVER)
    key = uuid4()
    first = _send(client, _path(case_id), writer, ROUTE, key=key)
    again = _send(client, _path(case_id), writer, ROUTE, key=key)
    assert (first.status_code, again.json()) == (201, first.json())
    assert again.headers["idempotency-replayed"] == "true"
    assert _effects(conn)[0] == 1, "one run"

    run_id = UUID(first.json()["run_id"])
    assert _send(client, _path(case_id, run_id, "input"), writer, PIN).is_success
    digests = _digests(client, case_id, run_id, approver)
    path = _path(case_id, run_id, SOURCE_SET + "approval")
    approved = _send(client, path, approver, digests, key=key)
    before = _effects(conn)
    replayed = _send(client, path, approver, digests, key=key)
    assert (approved.status_code, replayed.json()) == (200, approved.json())
    assert replayed.headers["idempotency-replayed"] == "true"
    other_gate = _path(case_id, run_id, RESEARCH_PLAN + "approval")
    reused = _send(client, other_gate, approver, digests, key=key)
    assert _outcome(reused) == "409 IDEMPOTENCY_KEY_REUSED"
    assert _effects(conn) == before


# Writer and approver hold that standing with G = ANALYST; "G reader writer"
# holds WRITER standing with G = READER.
ACTORS = "anon nonmember reader writer approver revoked G_admin G_reader_writer"
MATRIX = {
    "runs": (401, 404, 403, 201, 201, 404, 404, 403),
    "input": (401, 404, 403, 200, 200, 404, 404, 403),
    "preview": (401, 404, 200, 200, 200, 404, 404, 200),
    "approval": (401, 404, 403, 403, 200, 404, 404, 403),
}


@pytest.mark.parametrize("endpoint", sorted(MATRIX))
def test_the_run_commands_across_the_actor_matrix(
    client: TestClient, case: tuple[StoreConnection, UUID], sourced: UUID, endpoint: str
) -> None:
    conn, case_id = case
    writer = member(conn, case_id)
    reader = member(conn, case_id, Standing.READER)
    approver = member(conn, case_id, Standing.APPROVER)
    revoked = member(conn, case_id, Standing.ADMIN)
    revoke(conn, case_id=case_id, user_id=revoked)
    conn.commit()
    users: list[tuple[UUID | None, str]] = [(None, "ANALYST"), (uuid4(), "ANALYST")]
    users += [(reader, "READER"), (writer, "ANALYST"), (approver, "ANALYST")]
    users += [(revoked, "ADMIN"), (uuid4(), "ADMIN"), (writer, "READER")]
    pinned = _run(client, case_id, writer, pin=True)
    digests = _digests(client, case_id, pinned, approver)

    def ask(user: UUID | None, role: str) -> int:
        body: object
        if endpoint == "runs":
            path, body = _path(case_id), ROUTE
        elif endpoint == "input":
            fresh = _run(client, case_id, writer, pin=False)
            path, body = _path(case_id, fresh, "input"), PIN
        elif endpoint == "preview":
            path, body = _path(case_id, pinned, SOURCE_SET + "preview"), None
        else:
            path, body = _path(case_id, pinned, SOURCE_SET + "approval"), digests
        return _send(client, path, user, body, role=role).status_code

    names = ACTORS.split()
    observed = {name: ask(*user) for name, user in zip(names, users, strict=True)}

    assert observed == dict(zip(names, MATRIX[endpoint], strict=True))


class _Counting:
    """The request's connection, counting statements sent to the store."""

    def __init__(self, conn: StoreConnection) -> None:
        self._conn = conn
        self.executed = 0

    def execute(self, *args: object, **kwargs: object) -> object:
        self.executed += 1
        return self._conn.execute(*args, **kwargs)  # type: ignore[arg-type]

    def cursor(self, *args: object, **kwargs: object) -> object:
        self.executed += 1
        return self._conn.cursor(*args, **kwargs)  # type: ignore[call-overload]

    def __getattr__(self, name: str) -> object:
        return getattr(self._conn, name)


def test_each_run_command_meets_its_declared_store_budget(
    client: TestClient,
    case: tuple[StoreConnection, UUID],
    sourced: UUID,
    tmp_path: Path,
) -> None:
    conn, case_id = case
    counted = _Counting(conn)
    writer = member(conn, case_id)
    approver = member(conn, case_id, Standing.APPROVER)
    # An earlier snapshot the pin's live set differs from: the costliest path.
    snapshot_source_set(conn, case_id)
    _admit(conn, case_id, tmp_path, "later.txt")
    overrides = app_module.app.dependency_overrides

    def measured(path: str, user: UUID, body: object, key: UUID) -> tuple[int, int]:
        overrides[store_connection] = lambda: counted
        counted.executed = 0
        try:
            status = _send(client, path, user, body, key=key).status_code
        finally:
            overrides[store_connection] = lambda: conn
        return status, counted.executed

    key = uuid4()
    created = measured(_path(case_id), writer, ROUTE, key)
    assert created == (201, runs_command.CREATE_RUN_IO)
    assert measured(_path(case_id), writer, ROUTE, key) == (201, runs_command.REPLAY_IO)
    assert runs_command.REPLAY_IO <= 3
    [run_id] = [UUID(str(r[0])) for r in conn.execute("SELECT run_id FROM runs")]
    conn.rollback()
    pin = measured(_path(case_id, run_id, "input"), writer, PIN, uuid4())
    assert pin == (200, runs_command.PIN_INPUT_IO)
    path = _path(case_id, run_id, SOURCE_SET + "preview")
    assert measured(path, approver, None, key) == (200, runs_command.PREVIEW_IO)
    assert runs_command.PINNED_INPUT_IO == run_read.PINNED_INPUT_IO
    digests = _digests(client, case_id, run_id, approver)
    path = _path(case_id, run_id, SOURCE_SET + "approval")
    assert measured(path, approver, digests, uuid4()) == (200, runs_command.APPROVE_IO)
    # A successor (§72) selects the run it answers `FOR SHARE`: one statement
    # more than an ordinary run, measured on a run this case ended BLOCKED.
    blocked = _ended_blocked(conn, case_id)
    successor = {**ROUTE, "supersedes": str(blocked)}
    assert measured(_path(case_id), writer, successor, uuid4()) == (
        201,
        runs_command.SUCCESSOR_RUN_IO,
    )
    assert runs_command.SUCCESSOR_RUN_IO == runs_command.CREATE_RUN_IO + 1
    budgets = [runs_command.CREATE_RUN_IO, runs_command.SUCCESSOR_RUN_IO]
    budgets += [runs_command.PIN_INPUT_IO, runs_command.PREVIEW_IO]
    budgets += [runs_command.APPROVE_IO]
    assert runs_command.IO_BUDGET == max(budgets)

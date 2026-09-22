"""Task 4.2 decision 6: a command's key replays its receipt, and only its own.

The runner under test is `caos.store.commands.run_command`, driven through
the request dependencies in `caos/api/commands/_request.py`. No real command
exists in this slice, so two test-only commands stand in for them on a probe
app carrying the real app's exception handlers: a nil-scope "create case"
(the case that has no lock to share) and a case-scoped "start run".
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from typing import Annotated
from uuid import UUID, uuid4

import psycopg
import pytest
from command_fixtures import command_client, command_headers, member
from fastapi import APIRouter, Depends, FastAPI, Request, Response
from fastapi.testclient import TestClient
from httpx2 import Response as HttpResponse
from pydantic import BaseModel, ConfigDict

from caos.api.app import app
from caos.api.commands._request import (
    Key,
    case_standing,
    command_response,
    idempotency_key,
    json_body,
    require_case_approver,
    require_case_reader,
    require_case_writer,
)
from caos.api.deps import Caller, Store, store_connection
from caos.api.identity import TRUST_SWITCH, TRUSTED, Actor, GlobalRole
from caos.api.wire import CaseCreated, CreateCase
from caos.boundary_text import BoundaryText
from caos.refusals import Refusal, RefusalCode
from caos.store import StoreConnection
from caos.store.audit import GovernedAction
from caos.store.commands import (
    NIL_SCOPE,
    CommandResult,
    StoredReceipt,
    find_receipt,
    request_digest,
    run_command,
)
from caos.store.members import Standing, grant, revoke
from caos.store.runs import create_case, start_run

__all__ = ["command_client"]


class ProbeRun(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    run_id: UUID


router = APIRouter()
_body_reads: list[int] = []
_opened: list[int] = []
_create_body = json_body(CreateCase)


async def _counted_body(request: Request) -> CreateCase:
    _body_reads.append(1)
    return await _create_body(request)


CreateBody = Annotated[CreateCase, Depends(_counted_body)]


def _insert_case(
    case_id: UUID, title: str, creator: UUID
) -> Callable[[StoreConnection], None]:
    def prepare(conn: StoreConnection) -> None:
        conn.execute(
            "INSERT INTO cases (case_id, title) VALUES (%s, %s)",
            (case_id, BoundaryText.of(title).value),
        )
        grant(conn, case_id=case_id, user_id=creator, standing=Standing.ADMIN)

    return prepare


def create_probe_case(
    conn: StoreConnection, actor_id: UUID, key: UUID, title: str
) -> CommandResult:
    """The nil-scope command: a new case, its creator ADMIN, one receipt."""
    case_id = uuid4()
    return run_command(
        conn,
        scope=NIL_SCOPE,
        key=key,
        command="PROBE_CREATE_CASE",
        request_sha256=request_digest(
            "PROBE_CREATE_CASE",
            case_id=None,
            run_id=None,
            gate=None,
            body={"title": title},
        ),
        action=GovernedAction(
            case_id=case_id,
            actor_id=actor_id,
            action="CASE_CREATED",
            requires=Standing.ADMIN,
            payload={"case_id": str(case_id)},
        ),
        prepare=_insert_case(case_id, title, actor_id),
        write=lambda _conn: (201, CaseCreated(case_id=case_id)),
    )


@router.post("/probe/cases")
def probe_create(actor: Caller, key: Key, body: CreateBody, conn: Store) -> Response:
    if actor.role is GlobalRole.READER:
        raise Refusal(RefusalCode.NOT_AUTHORISED)
    result = create_probe_case(conn, actor.user_id, key, body.title)
    return command_response(result, CaseCreated)


@router.post("/probe/cases/{case_id}/runs")
def probe_start(
    actor: Caller,
    key: Key,
    _standing: Annotated[Standing, Depends(require_case_writer)],
    body: CreateBody,
    case_id: UUID,
    conn: Store,
) -> Response:
    def write(unit: StoreConnection) -> tuple[int, BaseModel]:
        run_id = start_run(unit, case_id)
        if body.title == "refuse":
            raise Refusal(RefusalCode.RUN_NOT_RUNNING)
        return 201, ProbeRun(run_id=run_id)

    result = run_command(
        conn,
        scope=case_id,
        key=key,
        command="PROBE_START_RUN",
        request_sha256=request_digest(
            "PROBE_START_RUN",
            case_id=case_id,
            run_id=None,
            gate=None,
            body=body.model_dump(mode="json"),
        ),
        action=GovernedAction(
            case_id=case_id,
            actor_id=actor.user_id,
            action="RUN_CREATED",
            requires=Standing.WRITER,
            payload={},
        ),
        write=write,
    )
    return command_response(result, ProbeRun)


@router.get("/probe/cases/{case_id}/read")
def probe_read(
    _actor: Caller, standing: Annotated[Standing, Depends(require_case_reader)]
) -> dict[str, str]:
    return {"standing": standing.value}


@router.post("/probe/cases/{case_id}/approve")
def probe_approve(
    _actor: Caller,
    _key: Annotated[UUID, Depends(idempotency_key)],
    standing: Annotated[Standing, Depends(require_case_approver)],
) -> dict[str, str]:
    return {"standing": standing.value}


@router.post("/probe/native")
def probe_native(_actor: Caller, body: CreateCase) -> dict[str, str]:
    return {"title": body.title}


probe = FastAPI()
for _error, _handler in app.exception_handlers.items():
    probe.add_exception_handler(_error, _handler)
probe.include_router(router)


@pytest.fixture(autouse=True)
def _the_role_header_decides(monkeypatch: pytest.MonkeyPatch) -> None:
    """The development deployment: tokenless, so the groups header is not read
    and the role header is believed only because this switch says so."""
    monkeypatch.setenv(TRUST_SWITCH, TRUSTED)


@pytest.fixture
def client(case: tuple[StoreConnection, UUID]) -> Iterator[TestClient]:
    conn, _case_id = case

    def counted() -> StoreConnection:
        _opened.append(1)
        return conn

    probe.dependency_overrides[store_connection] = counted
    _body_reads.clear()
    _opened.clear()
    try:
        with TestClient(probe) as served:
            yield served
    finally:
        probe.dependency_overrides.clear()


def _count(conn: StoreConnection, table: str) -> int:
    row = conn.execute(f"SELECT count(*) FROM {table}").fetchone()
    conn.rollback()
    assert row is not None
    return int(row[0])


def _start(
    client: TestClient, case_id: UUID, user: UUID, key: UUID, title: str = "go"
) -> HttpResponse:
    answer: HttpResponse = client.post(
        f"/probe/cases/{case_id}/runs",
        headers=command_headers(user, key=key),
        json={"title": title},
    )
    return answer


def test_a_replayed_key_returns_the_original_receipt_and_writes_nothing(
    case: tuple[StoreConnection, UUID], client: TestClient
) -> None:
    conn, case_id = case
    writer = member(conn, case_id)
    key = uuid4()

    first = _start(client, case_id, writer, key)
    again = _start(client, case_id, writer, key)

    assert first.status_code == again.status_code == 201
    assert again.json() == first.json()
    assert "idempotency-replayed" not in first.headers
    assert again.headers["idempotency-replayed"] == "true"
    assert _count(conn, "runs") == 1
    assert _count(conn, "audit_events") == 1
    assert _count(conn, "command_requests") == 1


def test_the_same_key_with_a_different_body_is_a_conflict(
    case: tuple[StoreConnection, UUID], client: TestClient
) -> None:
    conn, case_id = case
    writer = member(conn, case_id)
    key = uuid4()
    _start(client, case_id, writer, key, "go")

    reused = _start(client, case_id, writer, key, "another")

    assert reused.status_code == 409
    assert reused.json()["code"] == "IDEMPOTENCY_KEY_REUSED"
    assert _count(conn, "runs") == 1
    assert _count(conn, "command_requests") == 1


def test_a_refused_command_records_no_receipt(
    case: tuple[StoreConnection, UUID], client: TestClient
) -> None:
    conn, case_id = case
    writer = member(conn, case_id)
    key = uuid4()

    refused = _start(client, case_id, writer, key, "refuse")

    assert refused.status_code == 409
    assert refused.json()["code"] == "RUN_NOT_RUNNING"
    assert (_count(conn, "runs"), _count(conn, "audit_events")) == (0, 0)
    assert _count(conn, "command_requests") == 0
    # Nothing was burned: the key still carries the first request that succeeds.
    assert _start(client, case_id, writer, key, "go").status_code == 201


def test_a_lost_commit_acknowledgement_replays(
    case: tuple[StoreConnection, UUID],
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The commit landed and its answer did not: the retry is a replay."""
    conn, case_id = case
    writer = member(conn, case_id)
    key = uuid4()
    commit = type(conn).commit

    def lost(self: StoreConnection) -> None:
        commit(self)
        monkeypatch.setattr(type(conn), "commit", commit)
        raise psycopg.OperationalError

    monkeypatch.setattr(type(conn), "commit", lost)
    unknown = _start(client, case_id, writer, key)
    assert unknown.status_code == 503
    assert unknown.json()["code"] == "STORE_UNAVAILABLE"

    retried = _start(client, case_id, writer, key)

    assert retried.status_code == 201
    assert retried.headers["idempotency-replayed"] == "true"
    assert _count(conn, "runs") == 1
    assert _count(conn, "audit_events") == 1


def test_a_revoked_member_cannot_replay(
    case: tuple[StoreConnection, UUID], client: TestClient
) -> None:
    conn, case_id = case
    writer = member(conn, case_id)
    key = uuid4()
    assert _start(client, case_id, writer, key).status_code == 201
    revoke(conn, case_id=case_id, user_id=writer)
    conn.commit()

    replay = _start(client, case_id, writer, key)

    assert replay.status_code == 404
    assert replay.json()["code"] == "CASE_NOT_FOUND"
    assert _count(conn, "command_requests") == 1, "the row is kept, not served"


def test_keys_are_scoped_per_actor_and_case(
    case: tuple[StoreConnection, UUID], client: TestClient
) -> None:
    conn, case_id = case
    other_case = create_case(conn, BoundaryText.of("Other 2026"))
    conn.commit()
    first, second = member(conn, case_id), member(conn, case_id)
    grant(conn, case_id=other_case, user_id=first, standing=Standing.WRITER)
    conn.commit()
    key = uuid4()

    answers = [
        _start(client, case_id, first, key),
        _start(client, case_id, second, key),
        _start(client, other_case, first, key),
    ]

    assert [a.status_code for a in answers] == [201, 201, 201]
    assert all("idempotency-replayed" not in a.headers for a in answers)
    assert len({a.json()["run_id"] for a in answers}) == 3
    assert _count(conn, "command_requests") == 3
    stored = find_receipt(conn, actor_id=first, scope=other_case, key=key)
    conn.rollback()
    assert isinstance(stored, StoredReceipt) and stored.command == "PROBE_START_RUN"


@pytest.mark.parametrize("key", [None, "", "not-a-uuid", "1234"])
def test_a_command_without_the_key_is_refused_before_its_body_is_read(
    client: TestClient, key: str | None
) -> None:
    headers = command_headers(uuid4())
    if key is None:
        del headers["idempotency-key"]
    else:
        headers["idempotency-key"] = key

    refused = client.post("/probe/cases", headers=headers, content=b"{" * 70_000)

    assert refused.status_code == 400
    assert refused.json() == {
        "code": "IDEMPOTENCY_KEY_REQUIRED",
        "clears": "Send a UUID Idempotency-Key header.",
    }
    assert _body_reads == [], "the body was never read"
    assert _opened == [], "and no store connection opened"
    anonymous = client.post("/probe/cases", content=b"{}")
    assert anonymous.status_code == 401, "identity still comes first"


@pytest.mark.parametrize(
    ("content", "content_type"),
    [
        (b"{", "application/json"),
        (b'{"title": "x", "actor_id": "someone"}', "application/json"),
        (b'{"title": "' + b"x" * 20_000 + b'"}', "application/json"),
        (b'{"title": "x"}', "text/plain"),
        (b"", "application/json"),
    ],
)
def test_a_malformed_or_oversized_body_is_request_invalid(
    client: TestClient, content: bytes, content_type: str
) -> None:
    refused = client.post(
        "/probe/cases",
        headers={**command_headers(uuid4()), "content-type": content_type},
        content=content,
    )

    assert refused.status_code == 400
    assert refused.json()["code"] == "REQUEST_INVALID"
    assert "someone" not in refused.text


def test_a_native_body_validation_error_answers_request_invalid_never_422(
    client: TestClient,
) -> None:
    refused = client.post(
        "/probe/native", headers=command_headers(uuid4()), json={"title": 7}
    )
    assert (refused.status_code, refused.json()["code"]) == (400, "REQUEST_INVALID")
    anonymous = client.post("/probe/native", json={"title": 7})
    assert anonymous.status_code == 401


def test_case_standing_is_visibility_then_global_role_then_floor(
    case: tuple[StoreConnection, UUID], client: TestClient
) -> None:
    conn, case_id = case
    reader = member(conn, case_id, Standing.READER)
    writer = member(conn, case_id, Standing.WRITER)
    approver = member(conn, case_id, Standing.APPROVER)
    revoked = member(conn, case_id, Standing.ADMIN)
    revoke(conn, case_id=case_id, user_id=revoked)
    conn.commit()

    def code(path: str, user: UUID, role: str = "ANALYST") -> tuple[int, str]:
        answer = client.post(
            f"/probe/cases/{case_id}/{path}",
            headers=command_headers(user, role=role),
            json={"title": "go"},
        )
        body = answer.json()
        return answer.status_code, str(body.get("code", body.get("standing")))

    assert code("runs", uuid4()) == (404, "CASE_NOT_FOUND")
    assert code("runs", uuid4(), "ADMIN") == (404, "CASE_NOT_FOUND")
    assert code("runs", revoked) == (404, "CASE_NOT_FOUND")
    assert code("runs", reader) == (403, "NOT_AUTHORISED")
    assert code("runs", writer, "READER") == (403, "NOT_AUTHORISED")
    assert code("approve", writer) == (403, "NOT_AUTHORISED")
    assert code("approve", approver) == (200, "APPROVER")
    assert code("approve", approver, "READER") == (403, "NOT_AUTHORISED")

    read = client.get(
        f"/probe/cases/{case_id}/read", headers=command_headers(reader, role="READER")
    )
    assert read.json() == {"standing": "READER"}
    bad_id = client.post("/probe/cases/x/runs", headers=command_headers(writer))
    assert (bad_id.status_code, bad_id.json()["code"]) == (404, "CASE_NOT_FOUND")
    assert _body_reads == [], "no body is read for a caller the case refuses"


def test_the_real_app_includes_the_command_routers_and_statuses() -> None:
    from caos.api import app as app_module

    status = app_module._STATUS
    assert status[RefusalCode.NOT_AUTHORISED] == 403
    assert status[RefusalCode.SOURCE_TOO_LARGE] == 413
    conflicts = """IDEMPOTENCY_KEY_REUSED RUN_NOT_RUNNING GATE_APPROVAL_MISMATCH
        EVIDENCE_NOT_AVAILABLE ROUTE_ALREADY_PINNED ROUTE_PIN_TOO_LATE
        RUN_INPUT_ALREADY_PINNED RUN_INPUT_TOO_LATE RUN_INPUT_NOT_PINNED
        RUN_ALREADY_STARTED RUN_NOT_STOPPED RUN_CANCEL_REQUESTED
        COMMAND_EXPECTATION_STALE ORCHESTRATION_BUILD_MOVED"""
    for code in conflicts.split():
        assert status[RefusalCode(code)] == 409, code
    # No default any more: 400 is a value in the table like every other.
    assert status[RefusalCode.REQUEST_INVALID] == 400


def test_case_standing_asks_the_global_role_only_of_a_write(
    case: tuple[StoreConnection, UUID],
) -> None:
    conn, case_id = case
    reader = member(conn, case_id, Standing.READER)
    as_reader = Actor(user_id=reader, role=GlobalRole.READER)

    held = case_standing(conn, as_reader, case_id, Standing.READER, write=False)
    assert held is Standing.READER
    with pytest.raises(Refusal) as caught:
        case_standing(conn, as_reader, case_id, Standing.READER, write=True)
    assert caught.value.code is RefusalCode.NOT_AUTHORISED
    conn.rollback()

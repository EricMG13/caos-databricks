"""The producer half of F17: an authenticated reviewer signs a verdict.

`POST /api/v1/qualification/{evidence_sha256}/verdict` is the one route by
which `record_verdict` is reached. The body is the reviewer's document and
nothing else -- `read_verdict` is still its only reader -- and `reviewer_id`
comes from the `Actor` the edge derived, never from the caller. The read side
is `tests/test_qualification_api.py`; this file is its write-side sibling.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient
from httpx2 import Response
from qualification_fixtures import (
    qualification_performed,
    record_performed_earlier,
    record_runs,
)

from caos.api import app as app_module
from caos.api.app import _STATUS, app, store_connection
from caos.api.commands import qualification as sign_command
from caos.api.commands._request import IDEMPOTENCY_HEADER, REPLAYED_HEADER
from caos.api.commands.qualification import (
    SIGNS,
    evidence_path,
    require_reviewer,
    sign_verdict,
)
from caos.api.deps import actor_from_request
from caos.api.identity import ROLE_HEADER, TRUST_SWITCH, TRUSTED, GlobalRole, at_least
from caos.api.wire import QualificationState, SignVerdict, VerdictRecorded
from caos.qualification.store import (
    Evidence,
    performed_evidence,
    record_evidence,
)
from caos.qualification.verdict import read_verdict
from caos.refusals import Refusal, RefusalCode
from caos.store import StoreConnection, apply_schema, connect
from caos.store.commands import NIL_SCOPE

__all__ = ["evidence_path", "require_reviewer", "sign_verdict"]

NOT_FOUND = {
    "code": "QUALIFICATION_EVIDENCE_NOT_FOUND",
    "clears": "Name qualification evidence you may sign.",
}


def _headers(user: UUID, role: str = "ADMIN") -> dict[str, str]:
    """What the development proxy forwards: the subject and the role header.

    Not the groups header: this app is served without an edge token, and a
    tokenless API reads no groups (`caos/api/identity.py`). The switch the
    `client` fixture sets is what makes that header the deployment's word
    rather than this client's.
    """
    return {"x-caos-user": str(user), ROLE_HEADER: role}


def _document(evidence: Evidence, **changes: str) -> dict[str, Any]:
    """A reviewer's verdict over `evidence`, decided a minute ago for a year."""
    decided_at = datetime.now(UTC) - timedelta(minutes=1)
    document: dict[str, Any] = {
        "provider": evidence.provider + ":" + evidence.model,
        "qualification_set_sha256": evidence.qualification_set_sha256,
        "build_id": evidence.build_id,
        "decided_at": decided_at.isoformat(),
        "expires_at": (decided_at + timedelta(days=365)).isoformat(),
        "reviewer": "A. Reviewer",
        # N44: the exact evidence identity the document is read against.
        "evidence_sha256": evidence.sha256,
    }
    document.update(changes)
    return document


class _Counting:
    """The request's connection, counting statements sent to the store."""

    def __init__(self, conn: StoreConnection) -> None:
        self._conn = conn
        self.executed = 0

    def execute(self, *args: object, **kwargs: object) -> object:
        self.executed += 1
        return self._conn.execute(*args, **kwargs)  # type: ignore[arg-type]

    def __getattr__(self, name: str) -> object:
        return getattr(self._conn, name)


@pytest.fixture
def client(
    empty_database: str, monkeypatch: pytest.MonkeyPatch
) -> Iterator[tuple[TestClient, StoreConnection]]:
    """The real app on one connection, over a complete snapshot and its
    evidence identity, recorded the way the harness records them."""
    # The development deployment: tokenless, so a role above READER is the
    # switched-on role header or nothing at all.
    monkeypatch.setenv(TRUST_SWITCH, TRUSTED)
    monkeypatch.setenv(app_module.DATABASE_URL, empty_database)
    with connect(empty_database) as conn:
        apply_schema(conn)
        performed = qualification_performed()
        # The runs behind the snapshot, each accepted artifact recording the
        # model the harness configured: what `record_verdict` compares the
        # reviewer's `provider` against. Recorded before the snapshot, as
        # production's run-then-persist order has it -- `record_performed`'s
        # own completeness check (FP-24) now reads these rows too.
        record_runs(conn, performed)
        record_performed_earlier(conn, performed)
        record_evidence(conn, performed.evidence)
        conn.commit()
        app.dependency_overrides[store_connection] = lambda: conn
        try:
            with TestClient(app) as opened:
                yield opened, conn
        finally:
            app.dependency_overrides.clear()


def _sign(  # noqa: PLR0913 -- one request's identity, body and key
    client: TestClient,
    evidence_sha256: str,
    body: object,
    user: UUID | None,
    role: str = "ADMIN",
    key: UUID | None = None,
    *,
    send_key: bool = True,
) -> Response:
    """One signing request. `send_key` off omits the `Idempotency-Key`; a key
    left unnamed is a fresh one, so each call is its own command."""
    headers = {} if user is None else _headers(user, role)
    if send_key:
        headers[IDEMPOTENCY_HEADER] = str(key or uuid4())
    answer: Response = client.post(
        f"/api/v1/qualification/{evidence_sha256}/verdict", headers=headers, json=body
    )
    return answer


def _rows(conn: StoreConnection) -> tuple[list[tuple[Any, ...]], int]:
    """Every verdict row, and the number of evidence rows beside them."""
    verdicts = conn.execute(
        "SELECT evidence_sha256, reviewer_id, reviewer FROM qualification_verdicts"
    ).fetchall()
    row = conn.execute("SELECT count(*) FROM qualification_evidence").fetchone()
    assert row is not None
    conn.rollback()
    return verdicts, int(row[0])


def test_an_admin_signs_a_complete_snapshot_and_the_row_carries_their_identity(
    client: tuple[TestClient, StoreConnection],
) -> None:
    """The host originates nothing in the verdict; it binds who signed it."""
    http, conn = client
    evidence = qualification_performed().evidence
    reviewer = uuid4()
    counted = _Counting(conn)
    app.dependency_overrides[store_connection] = lambda: counted
    document = _document(evidence)

    answer = _sign(http, evidence.sha256, document, reviewer)

    assert answer.status_code == 201, answer.text
    receipt = VerdictRecorded.model_validate(answer.json())
    assert receipt.evidence_sha256 == evidence.sha256
    assert receipt.reviewer_id == reviewer
    assert receipt.decided_at.isoformat() == document["decided_at"]
    assert receipt.expires_at.isoformat() == document["expires_at"]
    assert counted.executed == sign_command.SIGN_IO == sign_command.IO_BUDGET
    assert _rows(conn) == ([(evidence.sha256, reviewer, "A. Reviewer")], 1)

    shown = http.get(
        f"/api/v1/qualification/{evidence.sha256}", headers=_headers(uuid4(), "ANALYST")
    )
    assert shown.status_code == 200
    assert shown.json()["state"] == QualificationState.QUALIFIED
    assert shown.json()["reviewer"] == "A. Reviewer"


def test_a_second_signature_over_the_same_evidence_is_already_recorded_not_invalid(
    client: tuple[TestClient, StoreConnection],
) -> None:
    """One verdict per evidence identity (`0019_one_qualification_verdict.sql`).

    Told `VERDICT_BINDING_INVALID`, a retrying client could not tell "already
    signed" from "wrong bindings" and would correct a document that was right.
    The constraint has its own code and its own status, matched by constraint
    name so a future unique index cannot borrow it.
    """
    http, conn = client
    evidence = qualification_performed().evidence
    first = _sign(http, evidence.sha256, _document(evidence), uuid4())
    assert first.status_code == 201

    again = _sign(http, evidence.sha256, _document(evidence), uuid4())

    assert again.status_code == 409, again.text
    assert again.json()["code"] == "VERDICT_ALREADY_RECORDED"
    assert _STATUS[RefusalCode.VERDICT_ALREADY_RECORDED] == 409
    assert len(_rows(conn)[0]) == 1


@pytest.mark.parametrize("recorded", ["another-model", None])
def test_a_verdict_naming_a_model_no_run_recorded_is_refused(
    empty_database: str, monkeypatch: pytest.MonkeyPatch, recorded: str | None
) -> None:
    """Invariant 3: the host owns identity, so `provider` is checked against
    what the runs called, not against what the harness was configured with.

    Two ways a snapshot fails it: an accepted artifact whose call recorded
    another model, and a run that recorded no model at all. Both refuse.
    """
    monkeypatch.setenv(TRUST_SWITCH, TRUSTED)
    monkeypatch.setenv(app_module.DATABASE_URL, empty_database)
    with connect(empty_database) as conn:
        apply_schema(conn)
        performed = qualification_performed()
        record_performed_earlier(conn, performed)
        record_evidence(conn, performed.evidence)
        record_runs(conn, performed, model=recorded, outcome=recorded is not None)
        conn.commit()
        app.dependency_overrides[store_connection] = lambda: conn
        try:
            with TestClient(app) as http:
                evidence = performed.evidence
                answer = _sign(http, evidence.sha256, _document(evidence), uuid4())
        finally:
            app.dependency_overrides.clear()

        assert answer.status_code == 400, answer.text
        assert answer.json()["code"] == "VERDICT_BINDING_INVALID"
        assert _rows(conn)[0] == []


def test_a_verdict_naming_the_recorded_model_records(
    client: tuple[TestClient, StoreConnection],
) -> None:
    """The comparison's other side: the model every accepted artifact of every
    run recorded is the one the document names, and the verdict is stored."""
    http, conn = client
    evidence = qualification_performed().evidence
    recorded = conn.execute("SELECT DISTINCT model FROM call_outcomes").fetchall()
    conn.rollback()
    assert recorded == [(evidence.model,)]

    answer = _sign(http, evidence.sha256, _document(evidence), uuid4())

    assert answer.status_code == 201, answer.text
    assert len(_rows(conn)[0]) == 1


def test_a_replayed_signature_with_the_same_key_is_answered_by_its_receipt(
    client: tuple[TestClient, StoreConnection],
) -> None:
    """The receipt this route had none of (§65's second stated limit).

    Same actor, same key, same document: the stored receipt is the answer and
    nothing is written a second time. The same key over a different document
    is the idempotency conflict every other command answers.
    """
    http, conn = client
    evidence = qualification_performed().evidence
    reviewer = uuid4()
    key = uuid4()
    document = _document(evidence)

    first = _sign(http, evidence.sha256, document, reviewer, key=key)
    assert first.status_code == 201, first.text
    assert REPLAYED_HEADER not in first.headers

    counted = _Counting(conn)
    app.dependency_overrides[store_connection] = lambda: counted
    again = _sign(http, evidence.sha256, document, reviewer, key=key)
    app.dependency_overrides[store_connection] = lambda: conn

    assert again.status_code == 201, again.text
    assert again.headers[REPLAYED_HEADER] == "true"
    # The lookup alone: a replay reads the receipt and writes nothing.
    assert counted.executed == sign_command.REPLAY_IO
    assert again.json() == first.json()
    assert len(_rows(conn)[0]) == 1
    receipts = conn.execute(
        "SELECT actor_id,scope,command,status FROM command_requests"
    ).fetchall()
    conn.rollback()
    assert receipts == [(reviewer, NIL_SCOPE, sign_command.SIGN_VERDICT, 201)]

    other = _document(evidence, reviewer="B. Reviewer")
    reused = _sign(http, evidence.sha256, other, reviewer, key=key)
    assert reused.status_code == 409, reused.text
    assert reused.json()["code"] == "IDEMPOTENCY_KEY_REUSED"
    assert len(_rows(conn)[0]) == 1


def test_the_verdict_command_requires_an_idempotency_key(
    client: tuple[TestClient, StoreConnection],
) -> None:
    """The header every other command requires, refused before the store."""
    http, conn = client
    evidence = qualification_performed().evidence
    opened: list[str] = []

    def counted() -> StoreConnection:
        opened.append(store_connection.__name__)
        return conn

    app.dependency_overrides[store_connection] = counted
    answer = _sign(http, evidence.sha256, _document(evidence), uuid4(), send_key=False)

    assert answer.status_code == 400, answer.text
    assert answer.json()["code"] == "IDEMPOTENCY_KEY_REQUIRED"
    assert opened == []
    app.dependency_overrides[store_connection] = lambda: conn
    assert _rows(conn) == ([], 1)


# What each identity gets on the one route that is account-wide rather than
# case-scoped: there is no standing to hold, so rank is the whole matrix.
VERDICT_ACTORS: tuple[tuple[str, str | None, int], ...] = (
    ("anonymous", None, 401),
    ("reader", "READER", 404),
    ("analyst", "ANALYST", 404),
    ("admin", "ADMIN", 201),
)


@pytest.mark.parametrize(("name", "role", "status"), VERDICT_ACTORS)
def test_the_verdict_route_answers_each_identity_by_rank(
    client: tuple[TestClient, StoreConnection],
    name: str,
    role: str | None,
    status: int,
) -> None:
    """The actor row `tests/test_actor_matrix.py` has no case scope for."""
    http, conn = client
    evidence = qualification_performed().evidence

    answer = _sign(
        http,
        evidence.sha256,
        _document(evidence),
        None if role is None else uuid4(),
        role or "ADMIN",
    )

    assert answer.status_code == status, (name, answer.text)
    assert len(_rows(conn)[0]) == (1 if status == 201 else 0)


@pytest.mark.parametrize("role", ["READER", "ANALYST"])
def test_a_role_below_the_signing_floor_is_answered_not_found_before_a_connection_opens(
    client: tuple[TestClient, StoreConnection], role: str
) -> None:
    """A verdict is account-wide, so the floor is the top global rank, and a
    caller below it learns nothing about which evidence exists."""
    http, conn = client
    evidence = qualification_performed().evidence
    opened: list[str] = []

    def counted() -> StoreConnection:
        opened.append(store_connection.__name__)
        return conn

    app.dependency_overrides[store_connection] = counted
    answer = _sign(http, evidence.sha256, _document(evidence), uuid4(), role)

    assert (answer.status_code, answer.json()) == (404, NOT_FOUND)
    assert opened == []
    assert _rows(conn) == ([], 1)
    assert SIGNS is GlobalRole.ADMIN
    assert at_least(GlobalRole.ADMIN, SIGNS)
    assert not at_least(GlobalRole.ANALYST, SIGNS)
    assert not at_least(GlobalRole.READER, GlobalRole.ANALYST)


def test_an_anonymous_signing_request_opens_no_store_connection(
    client: tuple[TestClient, StoreConnection],
) -> None:
    """Identity is declared ahead of the store, as on every other route."""
    http, conn = client
    evidence = qualification_performed().evidence
    opened: list[str] = []

    def counted() -> StoreConnection:
        opened.append(store_connection.__name__)
        return conn

    app.dependency_overrides[store_connection] = counted
    answer = _sign(http, evidence.sha256, _document(evidence), None)

    assert answer.status_code == 401
    assert answer.json()["code"] == "NOT_AUTHENTICATED"
    assert opened == []
    route = next(
        inner
        for outer in app.routes
        for inner in getattr(getattr(outer, "original_router", None), "routes", [])
        if getattr(inner, "endpoint", None) is sign_verdict
    )
    declared = route.dependant.dependencies
    calls = [d.call for d in declared]
    assert calls.index(require_reviewer) < calls.index(store_connection)
    assert calls.index(evidence_path) < calls.index(store_connection)
    # Identity is declared on the decorator, ahead of every parameter, and the
    # reviewer floor resolves the same (cached) actor behind it.
    assert calls[0] is actor_from_request
    reviewer = declared[calls.index(require_reviewer)]
    assert [d.call for d in reviewer.dependencies] == [actor_from_request]


def test_a_body_carrying_reviewer_id_is_refused_as_undeclared(
    client: tuple[TestClient, StoreConnection],
) -> None:
    """The reviewer's identity is the host's to derive. A body that names one
    is refused at the wire, and the verdict reader refuses it independently."""
    http, conn = client
    evidence = qualification_performed().evidence
    document = _document(evidence, reviewer_id=str(uuid4()))

    answer = _sign(http, evidence.sha256, document, uuid4())

    assert answer.status_code == 400
    assert answer.json()["code"] == "REQUEST_INVALID"
    assert _rows(conn) == ([], 1)
    with pytest.raises(Refusal, match=r"^VERDICT_UNDECLARED_FIELD$"):
        read_verdict(document, now=datetime.now(UTC))
    with pytest.raises(ValueError, match="extra"):
        SignVerdict.model_validate(document)


@pytest.mark.parametrize(
    "changed",
    [
        {"build_id": "not-this-build"},
        {"qualification_set_sha256": "9" * 64},
        {"provider": "openrouter/other:some/model"},
        # N44: naming the six coarse bindings correctly is not enough --
        # the document must also name the exact evidence identity it was
        # read against.
        {"evidence_sha256": "9" * 64},
    ],
)
def test_a_verdict_bound_to_other_evidence_is_refused_and_nothing_is_written(
    client: tuple[TestClient, StoreConnection], changed: dict[str, str]
) -> None:
    """`record_verdict`'s own binding check, reaching the wire; nothing is
    committed by a request the store refused."""
    http, conn = client
    evidence = qualification_performed().evidence

    answer = _sign(http, evidence.sha256, _document(evidence, **changed), uuid4())

    assert answer.status_code == 400
    assert answer.json()["code"] == "VERDICT_BINDING_INVALID"
    assert _rows(conn) == ([], 1)


def test_a_snapshot_that_is_not_complete_cannot_be_signed(
    client: tuple[TestClient, StoreConnection],
) -> None:
    """`qualification_performed.complete` false: nothing a reviewer may sign."""
    http, conn = client
    original = qualification_performed()
    incomplete = performed_evidence(
        prepared=original.prepared,
        performed=replace(original.performed, matrix=None),
    )
    assert incomplete.complete is False
    record_performed_earlier(conn, incomplete)
    record_evidence(conn, incomplete.evidence)
    conn.commit()
    evidence = incomplete.evidence

    answer = _sign(http, evidence.sha256, _document(evidence), uuid4())

    assert answer.status_code == 400
    assert answer.json()["code"] == "VERDICT_BINDING_INVALID"
    assert _rows(conn)[0] == []


@pytest.mark.parametrize("digest", ["f" * 64, "not-a-digest"])
def test_evidence_the_store_does_not_hold_is_not_found(
    client: tuple[TestClient, StoreConnection], digest: str
) -> None:
    """An unknown identity and a malformed one get the same private answer as
    a caller below the floor."""
    http, conn = client
    evidence = qualification_performed().evidence

    answer = _sign(http, digest, _document(evidence), uuid4())

    assert (answer.status_code, answer.json()) == (404, NOT_FOUND)
    assert _rows(conn) == ([], 1)


@pytest.mark.parametrize(
    ("changed", "code"),
    [
        ({"decided_at": "2026-09-15T10:00:00"}, "VERDICT_BINDING_INVALID"),
        ({"decided_at": "2999-01-01T00:00:00+00:00"}, "VERDICT_BINDING_INVALID"),
        (
            {
                "decided_at": "2020-01-01T00:00:00+00:00",
                "expires_at": "2020-01-02T00:00:00+00:00",
            },
            "VERDICT_EXPIRED",
        ),
        ({"reviewer": "   "}, "VERDICT_INCOMPLETE"),
    ],
)
def test_the_verdict_reader_alone_decides_what_the_document_means(
    client: tuple[TestClient, StoreConnection], changed: dict[str, str], code: str
) -> None:
    """A naive or future `decided_at`, a passed expiry and a blank binding are
    `read_verdict`'s refusals, judged against the store's clock."""
    http, conn = client
    evidence = qualification_performed().evidence

    answer = _sign(http, evidence.sha256, _document(evidence, **changed), uuid4())

    assert answer.status_code == 400
    assert answer.json()["code"] == code
    assert _rows(conn) == ([], 1)


def test_a_request_that_is_not_a_verdict_document_is_request_invalid(
    client: tuple[TestClient, StoreConnection],
) -> None:
    http, conn = client
    evidence = qualification_performed().evidence
    incomplete = _document(evidence)
    del incomplete["expires_at"]

    oversized = _document(evidence, provider="x" * 300)
    bodies: tuple[object, ...] = (incomplete, [], "text", oversized)
    for body in bodies:
        answer = _sign(http, evidence.sha256, body, uuid4())
        assert answer.status_code == 400, body
        assert answer.json()["code"] == RefusalCode.REQUEST_INVALID, body
    assert _rows(conn) == ([], 1)


class _Faulting:
    """The request's connection, faulting on one statement the route sends."""

    def __init__(self, conn: StoreConnection, on: str) -> None:
        self._conn = conn
        self._on = on

    def execute(self, *args: object, **kwargs: object) -> object:
        if args and str(args[0]).startswith(self._on):
            raise psycopg.OperationalError("simulated")
        return self._conn.execute(*args, **kwargs)  # type: ignore[arg-type]

    def __getattr__(self, name: str) -> object:
        return getattr(self._conn, name)


@pytest.mark.parametrize(
    "statement",
    [
        "SELECT now()",
        "SELECT e.qualification_set_sha256",
        "SELECT qualification_set_sha256",
        "SELECT DISTINCT o.run_id",
        "INSERT INTO qualification_verdicts",
    ],
)
def test_a_store_fault_while_signing_is_503_and_not_a_binding_error(
    client: tuple[TestClient, StoreConnection], statement: str
) -> None:
    """The clock read, the evidence lookup and the writes underneath
    `record_verdict` are the store answering, not the reviewer's document.

    A driver fault on any of them said `VERDICT_BINDING_INVALID` -- a 400
    telling a reviewer whose bindings were correct to correct them -- or left
    the typed boundary entirely as an untyped 500. Both are 503 now.
    """
    http, conn = client
    evidence = qualification_performed().evidence
    app.dependency_overrides[store_connection] = lambda: _Faulting(conn, statement)

    answer = _sign(http, evidence.sha256, _document(evidence), uuid4())

    assert answer.status_code == 503, answer.text
    assert answer.json()["code"] == "STORE_UNAVAILABLE"
    app.dependency_overrides[store_connection] = lambda: conn
    assert _rows(conn) == ([], 1)


def test_the_same_reviewer_signing_again_under_a_new_key_is_already_recorded(
    client: tuple[TestClient, StoreConnection],
) -> None:
    """AR-10's other side: the twin recovery must not swallow a real repeat.

    The primary key `(evidence_sha256, reviewer_id)` collides before
    `one_verdict_per_evidence` does, and both mean the same thing -- this
    evidence already carries a verdict. A fresh key finds no receipt to replay,
    so the refusal stands and the reviewer is told what happened.
    """
    http, conn = client
    evidence = qualification_performed().evidence
    reviewer = uuid4()
    assert (
        _sign(http, evidence.sha256, _document(evidence), reviewer).status_code == 201
    )

    again = _sign(http, evidence.sha256, _document(evidence), reviewer)

    assert again.status_code == 409, again.text
    assert again.json()["code"] == "VERDICT_ALREADY_RECORDED"
    assert len(_rows(conn)[0]) == 1


def test_a_twin_of_an_in_flight_signature_replays_the_commit_that_won(
    client: tuple[TestClient, StoreConnection], monkeypatch: pytest.MonkeyPatch
) -> None:
    """AR-10: two concurrent identical signatures answered 201 and HTTP 400.

    Both requests miss the receipt, one commits, and the loser's insert collides
    on the primary key -- which was mapped to `VERDICT_BINDING_INVALID`, a false
    answer about a request whose bindings were right and whose verdict and
    receipt both persisted. The committed receipt is recovered after the
    duplicate's rollback, so the twin replays it. The miss is simulated here
    because it is exactly a race: the twin looked before the winner committed.
    """
    from caos.store.commands import StoredReceipt, find_receipt

    http, conn = client
    evidence = qualification_performed().evidence
    reviewer, key = uuid4(), uuid4()
    body = _document(evidence)
    first = _sign(http, evidence.sha256, body, reviewer, key=key)
    assert first.status_code == 201
    assert REPLAYED_HEADER not in first.headers

    original = find_receipt
    misses = [True]

    def missing_once(
        conn: StoreConnection, *, actor_id: UUID, scope: UUID, key: UUID
    ) -> StoredReceipt | None:
        if misses:
            misses.pop()
            return None
        return original(conn, actor_id=actor_id, scope=scope, key=key)

    monkeypatch.setattr(sign_command, "find_receipt", missing_once)
    twin = _sign(http, evidence.sha256, body, reviewer, key=key)

    assert twin.status_code == 201, twin.text
    assert twin.headers[REPLAYED_HEADER] == "true"
    assert twin.json() == first.json()
    assert len(_rows(conn)[0]) == 1

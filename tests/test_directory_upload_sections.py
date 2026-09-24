"""The Directory and Upload section reads (Phase 4 Task 4.1, slice 4.1c).

Directory lists only the cases the actor holds live standing on; a global
ADMIN without membership sees none. Upload names every source of one case,
withdrawal read live, with the set versions each belongs to. An unknown,
unauthorised, revoked or malformed case is one private 404.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from caos.api import app as app_module
from caos.api.app import app, blob_store, store_connection
from caos.api.identity import ROLE_HEADER, TRUST_SWITCH, TRUSTED
from caos.api.reads import directory as directory_read
from caos.api.reads import upload as upload_read
from caos.api.wire import (
    CASES_MAX,
    CLEARS,
    MEMBERS_MAX,
    ActionName,
    DirectoryDocument,
    MemberRow,
    UploadDocument,
)
from caos.blobs import BlobStore
from caos.boundary_text import BoundaryText
from caos.evidence.ingest import Document, admit_pack
from caos.graph.route import resolve_route
from caos.refusals import RefusalCode
from caos.store import StoreConnection
from caos.store.gates import withdraw_source
from caos.store.members import (
    Standing,
    grant,
    revoke,
)
from caos.store.routes import pin_route
from caos.store.runs import create_case, start_run
from caos.store.source_sets import (
    snapshot_source_set,
)
from caos.store.work import claim_run, enqueue_run, stop

CATALOG_PATH = (
    Path(__file__).resolve().parents[1]
    / "vendor/deploy-v/skills/cp-os-credit-os/references"
    / "CREDIT_OS_V_MODULE_CATALOG_v2.json"
)
DIRECTORY = "/api/v1/directory"


@pytest.fixture
def client(
    case: tuple[StoreConnection, UUID],
    empty_database: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[TestClient]:
    conn, _case_id = case
    blobs = BlobStore(tmp_path / "blobs")
    monkeypatch.setenv(app_module.DATABASE_URL, empty_database)
    # Tokenless, so no groups header is read: the development switch is how a
    # test here asserts a global role above the floor.
    monkeypatch.setenv(TRUST_SWITCH, TRUSTED)
    app.dependency_overrides[store_connection] = lambda: conn
    app.dependency_overrides[blob_store] = lambda: blobs
    try:
        with TestClient(app) as opened:
            yield opened
    finally:
        app.dependency_overrides.clear()


class _CountingConnection:
    """Counts store round trips, so the declared budget is measured."""

    def __init__(self, conn: StoreConnection) -> None:
        self._conn = conn
        self.executed = 0

    def execute(self, *args: object, **kwargs: object) -> object:
        self.executed += 1
        return self._conn.execute(*args, **kwargs)  # type: ignore[arg-type]


def _serving(counter: _CountingConnection) -> Callable[[], _CountingConnection]:
    return lambda: counter


def _as(user_id: UUID, role: str | None = None) -> dict[str, str]:
    headers = {"x-caos-user": str(user_id)}
    if role is not None:
        headers[ROLE_HEADER] = role
    return headers


def _refused(code: RefusalCode) -> dict[str, str]:
    return {"code": code.value, "clears": CLEARS[code]}


def _upload(case_id: object) -> str:
    return f"/api/v1/cases/{case_id}/upload"


def _admit(
    conn: StoreConnection, case_id: UUID, blobs: Path, *names: str
) -> list[UUID]:
    return admit_pack(
        conn,
        BlobStore(blobs),
        case_id=case_id,
        documents=[
            Document(BoundaryText.of(name), f"text of {name}".encode())
            for name in names
        ],
    )


def test_directory_lists_only_cases_with_live_standing(
    client: TestClient, case: tuple[StoreConnection, UUID], tmp_path: Path
) -> None:
    conn, case_id = case
    user = uuid4()
    grant(conn, case_id=case_id, user_id=user, standing=Standing.APPROVER)
    _admit(conn, case_id, tmp_path / "b", "one.txt", "two.txt")
    run_id = start_run(conn, case_id)
    catalog: dict[str, Any] = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    conn.commit()
    pin_route(
        conn,
        run_id,
        resolve_route(catalog, "FULL_CREDIT_32", "FULL_CREDIT_ASSESSMENT"),
    )
    revoked = create_case(conn, BoundaryText.of("Revoked case"))
    grant(conn, case_id=revoked, user_id=user, standing=Standing.READER)
    revoke(conn, case_id=revoked, user_id=user)
    create_case(conn, BoundaryText.of("A stranger's case"))
    conn.commit()

    response = client.get(DIRECTORY, headers=_as(user))

    assert response.status_code == 200
    document = DirectoryDocument.model_validate(response.json())
    assert document.chrome.subject is None
    assert document.chrome.served_role.standing is None
    assert (document.status, document.notes, document.observed_empty) == (
        "complete",
        [],
        False,
    )
    [row] = document.body.cases
    assert (row.case_id, row.title, row.standing) == (
        case_id,
        "Acme 2026 refinancing",
        Standing.APPROVER,
    )
    assert row.live_sources == 2
    assert row.latest_run is not None
    assert (row.latest_run.run_id, row.latest_run.status) == (run_id, "RUNNING")
    assert (row.latest_run.profile_id, row.latest_run.selection_id) == (
        "FULL_CREDIT_32",
        "FULL_CREDIT_ASSESSMENT",
    )
    assert row.latest_run.stop_code is None


def test_the_directory_names_a_parked_run_s_stop_code(
    client: TestClient, case: tuple[StoreConnection, UUID]
) -> None:
    """CF-044: a run a worker parked still reads `status: RUNNING` -- it is
    recoverable, not ended -- so `stop_code` is the one field that tells a
    list a run stopped being driven apart from one nobody is touching yet."""
    conn, case_id = case
    user = uuid4()
    grant(conn, case_id=case_id, user_id=user, standing=Standing.READER)
    run_id = start_run(conn, case_id)
    conn.commit()
    enqueue_run(conn, run_id)
    conn.commit()
    lease = claim_run(conn, worker=BoundaryText.of("worker-a"), lease_seconds=60)
    assert lease is not None
    assert stop(conn, lease, RefusalCode.CONTEXT_OVER_CEILING) is True
    conn.commit()

    response = client.get(DIRECTORY, headers=_as(user))

    document = DirectoryDocument.model_validate(response.json())
    [row] = document.body.cases
    assert row.latest_run is not None
    assert row.latest_run.status == "RUNNING"
    assert row.latest_run.stop_code is RefusalCode.CONTEXT_OVER_CEILING


def test_the_directory_serves_a_cases_members_only_to_its_administrator(
    client: TestClient, case: tuple[StoreConnection, UUID]
) -> None:
    """O21: membership surfaces in Directory. A case's live members are the
    administrator's to see, because they are the administrator's to change; a
    member below ADMIN is shown the two controls refused, never hidden."""
    conn, administered = case
    user, writer, gone = sorted((uuid4(), uuid4(), uuid4()))
    grant(conn, case_id=administered, user_id=user, standing=Standing.ADMIN)
    grant(conn, case_id=administered, user_id=writer, standing=Standing.WRITER)
    grant(conn, case_id=administered, user_id=gone, standing=Standing.READER)
    revoke(conn, case_id=administered, user_id=gone)
    written = create_case(conn, BoundaryText.of("Written, not administered"))
    grant(conn, case_id=written, user_id=user, standing=Standing.WRITER)
    conn.commit()

    rows = {
        row.case_id: row
        for row in DirectoryDocument.model_validate(
            client.get(DIRECTORY, headers=_as(user, "ANALYST")).json()
        ).body.cases
    }

    admin_row, writer_row = rows[administered], rows[written]
    assert admin_row.members == [
        MemberRow(user_id=user, standing=Standing.ADMIN),
        MemberRow(user_id=writer, standing=Standing.WRITER),
    ]
    assert [(a.action, a.refusal) for a in admin_row.actions] == [
        (ActionName.GRANT_STANDING, None),
        (ActionName.REVOKE_STANDING, None),
    ]
    assert writer_row.members is None
    assert [(a.action, a.refusal and a.refusal.code) for a in writer_row.actions] == [
        (ActionName.GRANT_STANDING, RefusalCode.NOT_AUTHORISED),
        (ActionName.REVOKE_STANDING, RefusalCode.NOT_AUTHORISED),
    ]

    as_reader = DirectoryDocument.model_validate(
        client.get(DIRECTORY, headers=_as(user, "READER")).json()
    ).body.cases
    reader_row = next(row for row in as_reader if row.case_id == administered)
    assert reader_row.members == admin_row.members
    assert {a.refusal and a.refusal.code for a in reader_row.actions} == {
        RefusalCode.NOT_AUTHORISED
    }


def test_a_member_list_past_its_bound_is_truncated_with_a_note(
    client: TestClient, case: tuple[StoreConnection, UUID]
) -> None:
    conn, case_id = case
    user = uuid4()
    grant(conn, case_id=case_id, user_id=user, standing=Standing.ADMIN)
    for _ in range(MEMBERS_MAX):
        grant(conn, case_id=case_id, user_id=uuid4(), standing=Standing.READER)
    conn.commit()

    document = DirectoryDocument.model_validate(
        client.get(DIRECTORY, headers=_as(user)).json()
    )

    [row] = document.body.cases
    assert row.members is not None and len(row.members) == MEMBERS_MAX
    assert document.status == "partial"
    assert [note.value for note in document.notes] == ["LIST_TRUNCATED"]


def test_an_empty_directory_is_observed_empty_with_its_time(
    client: TestClient, case: tuple[StoreConnection, UUID]
) -> None:
    conn, _case_id = case
    [[now]] = conn.execute("SELECT now()").fetchall()
    conn.commit()

    response = client.get(DIRECTORY, headers=_as(uuid4()))

    assert response.status_code == 200
    document = DirectoryDocument.model_validate(response.json())
    assert document.body.cases == []
    assert document.observed_empty is True
    assert document.status == "complete"
    assert document.observed_at >= now


def test_the_directory_is_truncated_past_its_bound_with_a_note(
    client: TestClient, case: tuple[StoreConnection, UUID]
) -> None:
    conn, _case_id = case
    user = uuid4()
    for index in range(CASES_MAX + 1):
        created = create_case(conn, BoundaryText.of(f"Case {index}"))
        grant(conn, case_id=created, user_id=user, standing=Standing.READER)
    conn.commit()

    response = client.get(DIRECTORY, headers=_as(user))

    document = DirectoryDocument.model_validate(response.json())
    assert len(document.body.cases) == CASES_MAX
    assert document.status == "partial"
    assert [note.value for note in document.notes] == ["LIST_TRUNCATED"]
    assert document.observed_empty is False


def test_upload_marks_withdrawal_live_and_names_set_versions(
    client: TestClient, case: tuple[StoreConnection, UUID], tmp_path: Path
) -> None:
    conn, case_id = case
    writer = uuid4()
    grant(conn, case_id=case_id, user_id=writer, standing=Standing.WRITER)
    kept, dropped = _admit(conn, case_id, tmp_path / "b", "kept.txt", "dropped.txt")
    conn.commit()
    first = snapshot_source_set(conn, case_id)
    withdraw_source(conn, case_id=case_id, source_id=dropped, actor_id=writer)
    [late] = _admit(conn, case_id, tmp_path / "b", "late.txt")
    conn.commit()
    second = snapshot_source_set(conn, case_id)

    response = client.get(_upload(case_id), headers=_as(writer))

    assert response.status_code == 200
    document = UploadDocument.model_validate(response.json())
    assert document.chrome.subject is not None
    assert (document.chrome.subject.case_id, document.chrome.subject.title) == (
        case_id,
        "Acme 2026 refinancing",
    )
    assert document.chrome.served_role.standing is Standing.WRITER
    assert (document.status, document.notes, document.observed_empty) == (
        "complete",
        [],
        False,
    )
    body = document.body
    assert body.case_id == case_id
    rows = {row.source_id: row for row in body.sources}
    assert set(rows) == {kept, dropped, late}
    assert rows[kept].withdrawn_at is None
    withdrawn_at = rows[dropped].withdrawn_at
    assert withdrawn_at is not None
    assert withdrawn_at >= rows[dropped].admitted_at
    assert rows[kept].set_versions == [1, 2]
    assert rows[dropped].set_versions == [1]
    assert rows[late].set_versions == [2]
    assert rows[dropped].filename == "dropped.txt"
    assert rows[kept].extractor_identity is not None
    assert len(rows[kept].document_sha256) == 64
    assert [(v.version, v.fingerprint, v.member_count) for v in body.set_versions] == [
        (1, first.fingerprint, 2),
        (2, second.fingerprint, 2),
    ]


def test_an_upload_with_no_sources_is_observed_empty(
    client: TestClient, case: tuple[StoreConnection, UUID]
) -> None:
    conn, case_id = case
    reader = uuid4()
    grant(conn, case_id=case_id, user_id=reader, standing=Standing.READER)
    conn.commit()

    document = UploadDocument.model_validate(
        client.get(_upload(case_id), headers=_as(reader)).json()
    )

    assert (document.body.sources, document.body.set_versions) == ([], [])
    assert document.observed_empty is True


def test_unknown_unauthorised_revoked_and_malformed_case_are_one_private_404(
    client: TestClient, case: tuple[StoreConnection, UUID]
) -> None:
    conn, case_id = case
    revoked = uuid4()
    grant(conn, case_id=case_id, user_id=revoked, standing=Standing.ADMIN)
    revoke(conn, case_id=case_id, user_id=revoked)
    conn.commit()
    stranger = uuid4()

    answers = [
        client.get(_upload(uuid4()), headers=_as(stranger)),
        client.get(_upload(case_id), headers=_as(stranger)),
        client.get(_upload(case_id), headers=_as(revoked)),
        client.get(_upload("not-a-case"), headers=_as(stranger)),
    ]

    for response in answers:
        assert (response.status_code, response.json()) == (
            404,
            _refused(RefusalCode.CASE_NOT_FOUND),
        )


def test_a_section_request_across_anonymous_nonmember_reader_writer_approver_revoked_and_admin(  # noqa: E501
    client: TestClient, case: tuple[StoreConnection, UUID]
) -> None:
    conn, case_id = case
    members = {standing: uuid4() for standing in Standing}
    for standing, user in members.items():
        grant(conn, case_id=case_id, user_id=user, standing=standing)
    revoked = uuid4()
    grant(conn, case_id=case_id, user_id=revoked, standing=Standing.WRITER)
    revoke(conn, case_id=case_id, user_id=revoked)
    conn.commit()

    for path in (DIRECTORY, _upload(case_id)):
        anonymous = client.get(path)
        assert (anonymous.status_code, anonymous.json()) == (
            401,
            _refused(RefusalCode.NOT_AUTHENTICATED),
        ), path

    for standing in (Standing.READER, Standing.WRITER, Standing.APPROVER):
        user = members[standing]
        directory = DirectoryDocument.model_validate(
            client.get(DIRECTORY, headers=_as(user)).json()
        )
        assert [(r.case_id, r.standing) for r in directory.body.cases] == [
            (case_id, standing)
        ]
        upload = client.get(_upload(case_id), headers=_as(user))
        assert upload.status_code == 200, standing
        served = UploadDocument.model_validate(upload.json()).chrome.served_role
        assert (served.global_role.value, served.standing) == ("READER", standing)

    for user, role in ((uuid4(), None), (revoked, None), (uuid4(), "ADMIN")):
        directory_response = client.get(DIRECTORY, headers=_as(user, role))
        assert directory_response.status_code == 200
        directory = DirectoryDocument.model_validate(directory_response.json())
        assert directory.body.cases == []
        assert directory.chrome.served_role.global_role.value == (role or "READER")
        upload = client.get(_upload(case_id), headers=_as(user, role))
        assert (upload.status_code, upload.json()) == (
            404,
            _refused(RefusalCode.CASE_NOT_FOUND),
        )


def test_an_anonymous_section_request_is_401_and_opens_no_store_connection(
    client: TestClient, case: tuple[StoreConnection, UUID]
) -> None:
    conn, case_id = case
    opened: list[str] = []

    def counted() -> StoreConnection:
        opened.append(store_connection.__name__)
        return conn

    app.dependency_overrides[store_connection] = counted

    for path in (DIRECTORY, _upload(case_id), _upload("not-a-case")):
        response = client.get(path)
        assert (response.status_code, response.json()) == (
            401,
            _refused(RefusalCode.NOT_AUTHENTICATED),
        ), path
    assert opened == []


def test_a_malformed_case_opens_no_store_connection(
    client: TestClient, case: tuple[StoreConnection, UUID]
) -> None:
    conn, _case_id = case
    opened: list[str] = []

    def counted() -> StoreConnection:
        opened.append(store_connection.__name__)
        return conn

    app.dependency_overrides[store_connection] = counted

    response = client.get(_upload("not-a-case"), headers=_as(uuid4()))

    assert (response.status_code, response.json()) == (
        404,
        _refused(RefusalCode.CASE_NOT_FOUND),
    )
    assert opened == []


def test_each_section_request_path_declares_its_store_budget(
    client: TestClient, case: tuple[StoreConnection, UUID], tmp_path: Path
) -> None:
    conn, case_id = case
    user = uuid4()
    for index in range(3):
        created = create_case(conn, BoundaryText.of(f"Case {index}"))
        grant(conn, case_id=created, user_id=user, standing=Standing.READER)
        start_run(conn, created)
    # ADMIN, so the budget is measured with the member list served.
    grant(conn, case_id=case_id, user_id=user, standing=Standing.ADMIN)
    _admit(conn, case_id, tmp_path / "b", "a.txt", "b.txt")
    conn.commit()
    snapshot_source_set(conn, case_id)
    _admit(conn, case_id, tmp_path / "b", "c.txt")
    conn.commit()
    snapshot_source_set(conn, case_id)

    for path, budget in (
        (DIRECTORY, directory_read.IO_BUDGET),
        (_upload(case_id), upload_read.IO_BUDGET),
    ):
        counter = _CountingConnection(conn)
        app.dependency_overrides[store_connection] = _serving(counter)
        assert client.get(path, headers=_as(user)).status_code == 200, path
        assert 0 < counter.executed == budget, path


def test_the_store_dependency_opens_the_apps_store_connection(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Every section read declares `caos.api.deps.store_connection` (as
    `app.py` re-exports it) directly, so a section read without a configured
    store is refused as every other path is."""
    del app.dependency_overrides[store_connection]
    monkeypatch.delenv(app_module.DATABASE_URL, raising=False)

    for path in (DIRECTORY, _upload(uuid4())):
        response = client.get(path, headers=_as(uuid4()))
        # 500 under D3: an unconfigured store is an operator's repair, and a
        # 503 would have every proxy retry until they made it.
        assert (response.status_code, response.json()) == (
            500,
            _refused(RefusalCode.STORE_NOT_CONFIGURED),
        ), path


def test_the_section_routes_are_the_read_functions() -> None:
    """`read_directory` and `read_upload` are what the paths serve.

    Dependency order and identity is `tests/test_api_routes.py`'s
    `test_every_section_read_depends_on_the_shared_dependencies`.
    """
    served = {
        route.path: route
        for route in (*directory_read.router.routes, *upload_read.router.routes)
        if isinstance(route, APIRoute)
    }
    assert served[DIRECTORY].endpoint is directory_read.read_directory
    assert served["/api/v1/cases/{case_id}/upload"].endpoint is upload_read.read_upload

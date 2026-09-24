"""Task 4.2 slice 4.2f: start, retry and cancel (decisions 1, 2 and 7).

Every run is the canonical LITE route, pinned and approved through the store
helpers the runtime suites use; the commands are driven through the real app.
No provider exists anywhere on these paths, and the import test says so.
"""

from __future__ import annotations

import ast
import json
import shutil
from collections.abc import Callable
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from canonical_fixtures import CATALOG, LITE_PROFILE, LITE_SELECTION, QUOTE, VENDORED
from command_fixtures import command_client, command_headers, constant, member
from conftest import approve_run
from fastapi.testclient import TestClient
from httpx2 import Response

from caos import methodology
from caos.api.app import app
from caos.api.commands import execution
from caos.api.deps import methodology_bundle
from caos.blobs import BlobStore
from caos.boundary_text import BoundaryText
from caos.evidence.ingest import Document, admit_pack
from caos.graph.route import resolve_route
from caos.methodology.bundle import MANIFEST_NAME, Bundle
from caos.refusals import RefusalCode
from caos.store import StoreConnection
from caos.store.gates import withdraw_source
from caos.store.members import Standing, revoke
from caos.store.runs import create_case, start_run
from caos.store.work import claim_run, enqueue_run, stop

__all__ = ["command_client"]

REPO = Path(__file__).resolve().parents[1]
ROUTE = resolve_route(CATALOG, LITE_PROFILE, LITE_SELECTION)
STALE = "0" * 64


class _Run:
    """One run of the `case` fixture, with its pin's fingerprint when pinned."""

    def __init__(
        self, conn: StoreConnection, case_id: UUID, tmp_path: Path, *, pinned: bool
    ) -> None:
        [self.source_id] = admit_pack(
            conn,
            BlobStore(tmp_path / "blobs"),
            case_id=case_id,
            documents=[
                Document(
                    filename=BoundaryText.of("report.txt"),
                    data=QUOTE.encode() + b"\n",
                )
            ],
        )
        self.run_id = start_run(conn, case_id)
        conn.commit()
        self.approver: UUID | None = None
        self.fingerprint = STALE
        if pinned:
            self.approver = approve_run(
                conn,
                case_id=case_id,
                run_id=self.run_id,
                route=ROUTE,
                bundle=Bundle(VENDORED),
            )
            row = conn.execute(
                "SELECT input_fingerprint FROM run_inputs WHERE run_id = %s",
                (self.run_id,),
            ).fetchone()
            conn.rollback()
            assert row is not None
            self.fingerprint = str(row[0])


def _scalar(conn: StoreConnection, sql: str, *params: object) -> int:
    row = conn.execute(sql, params).fetchone()
    conn.rollback()
    assert row is not None
    return int(row[0])


def _audited(conn: StoreConnection, case_id: UUID, action: str) -> int:
    return _scalar(
        conn,
        "SELECT count(*) FROM audit_events WHERE case_id = %s AND action = %s",
        case_id,
        action,
    )


def _work(conn: StoreConnection, run_id: UUID) -> tuple[object, ...] | None:
    row = conn.execute(
        "SELECT state, stop_code, cancel_requested_at IS NOT NULL FROM run_work"
        " WHERE run_id = %s",
        (run_id,),
    ).fetchone()
    conn.rollback()
    return None if row is None else tuple(row)


def _post(  # noqa: PLR0913 -- one request's parts, keyword-only
    client: TestClient,
    case_id: UUID,
    run_id: UUID | str,
    command: str,
    user: UUID,
    *,
    fingerprint: str | None = None,
    key: UUID | None = None,
    role: str = "ANALYST",
) -> Response:
    body: dict[str, str] = (
        {} if fingerprint is None else {"input_fingerprint": fingerprint}
    )
    answer: Response = client.post(
        f"/api/v1/cases/{case_id}/runs/{run_id}/{command}",
        headers=command_headers(user, role=role, key=key),
        json=body,
    )
    return answer


@pytest.fixture
def client(command_client: TestClient) -> TestClient:
    return command_client


def _code(answer: Response) -> tuple[int, str]:
    return answer.status_code, str(answer.json().get("code"))


def test_start_rechecks_live_authority_and_enqueues_in_the_audited_unit(
    case: tuple[StoreConnection, UUID], client: TestClient, tmp_path: Path
) -> None:
    conn, case_id = case
    writer = member(conn, case_id)
    run = _Run(conn, case_id, tmp_path, pinned=True)

    started = _post(
        client, case_id, run.run_id, "start", writer, fingerprint=run.fingerprint
    )

    assert started.status_code == 202
    assert started.json() == {
        "run_id": str(run.run_id),
        "run_status": "RUNNING",
        "work": {"state": "QUEUED", "stop_code": None, "cancel_requested": False},
    }
    assert _audited(conn, case_id, "RUN_ENQUEUED") == 1
    assert _scalar(conn, "SELECT count(*) FROM command_requests") == 1
    assert _scalar(conn, "SELECT count(*) FROM run_attempts") == 0, "no call"
    again = _post(
        client, case_id, run.run_id, "start", writer, fingerprint=run.fingerprint
    )
    assert _code(again) == (409, "RUN_ALREADY_STARTED")
    assert _audited(conn, case_id, "RUN_ENQUEUED") == 1

    # T4 and T6: authority that moved after approval refuses, with no work row.
    # The later run's snapshot alone holds the source withdrawn here.
    revoked = _Run(conn, case_id, tmp_path, pinned=True)
    withdrawn = _Run(conn, case_id, tmp_path, pinned=True)
    assert revoked.approver is not None
    revoke(conn, case_id=case_id, user_id=revoked.approver)
    conn.commit()
    withdraw_source(
        conn, case_id=case_id, source_id=withdrawn.source_id, actor_id=writer
    )
    for moved, code in (
        (withdrawn, "EVIDENCE_NOT_AVAILABLE"),
        (revoked, "GATE_APPROVAL_MISMATCH"),
    ):
        refused = _post(
            client,
            case_id,
            moved.run_id,
            "start",
            writer,
            fingerprint=moved.fingerprint,
        )
        assert _code(refused) == (409, code)
        assert _work(conn, moved.run_id) is None
    assert _audited(conn, case_id, "RUN_ENQUEUED") == 1


def test_start_without_a_pin_or_under_another_build_is_a_conflict_not_a_fault(
    case: tuple[StoreConnection, UUID],
    client: TestClient,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn, case_id = case
    writer = member(conn, case_id)
    unpinned = _Run(conn, case_id, tmp_path, pinned=False)
    pinned = _Run(conn, case_id, tmp_path, pinned=True)

    for command in ("start", "retry"):
        refused = _post(
            client, case_id, unpinned.run_id, command, writer, fingerprint=STALE
        )
        assert _code(refused) == (409, "RUN_INPUT_NOT_PINNED")

    root = tmp_path / "another-build"
    shutil.copytree(VENDORED, root)
    manifest = json.loads((root / MANIFEST_NAME).read_bytes())
    manifest["build_id"] = "b" * 64
    (root / MANIFEST_NAME).write_text(json.dumps(manifest), encoding="utf-8")
    app.dependency_overrides[methodology_bundle] = constant(Bundle(root))
    moved = _post(client, case_id, pinned.run_id, "start", writer, fingerprint=STALE)
    assert _code(moved) == (409, "ORCHESTRATION_BUILD_MOVED"), "before the fingerprint"
    del app.dependency_overrides[methodology_bundle]

    monkeypatch.setattr(methodology, "CANONICAL_ADAPTER_VERSION", "another-adapter")
    adapter = _post(client, case_id, pinned.run_id, "start", writer, fingerprint=STALE)
    assert _code(adapter) == (409, "ORCHESTRATION_BUILD_MOVED")
    assert _work(conn, unpinned.run_id) is None and _work(conn, pinned.run_id) is None
    assert _scalar(conn, "SELECT count(*) FROM command_requests") == 0


def test_a_stale_input_fingerprint_is_a_conflict_with_no_work_row(
    case: tuple[StoreConnection, UUID], client: TestClient, tmp_path: Path
) -> None:
    conn, case_id = case
    writer = member(conn, case_id)
    run = _Run(conn, case_id, tmp_path, pinned=True)
    key = uuid4()

    stale = _post(
        client, case_id, run.run_id, "start", writer, fingerprint=STALE, key=key
    )

    assert _code(stale) == (409, "COMMAND_EXPECTATION_STALE")
    assert _work(conn, run.run_id) is None
    assert _audited(conn, case_id, "RUN_ENQUEUED") == 0
    assert _scalar(conn, "SELECT count(*) FROM command_requests") == 0
    fresh = _post(
        client,
        case_id,
        run.run_id,
        "start",
        writer,
        fingerprint=run.fingerprint,
        key=key,
    )
    assert fresh.status_code == 202, "a refusal burns no key"


def test_retry_requeues_only_a_stopped_run(
    case: tuple[StoreConnection, UUID], client: TestClient, tmp_path: Path
) -> None:
    conn, case_id = case
    writer = member(conn, case_id)
    run = _Run(conn, case_id, tmp_path, pinned=True)

    def retry(fingerprint: str) -> Response:
        return _post(
            client, case_id, run.run_id, "retry", writer, fingerprint=fingerprint
        )

    assert _code(retry(run.fingerprint)) == (409, "RUN_NOT_STOPPED"), "never enqueued"
    enqueue_run(conn, run.run_id)
    conn.commit()
    assert _code(retry(run.fingerprint)) == (409, "RUN_NOT_STOPPED"), "queued"
    lease = claim_run(conn, worker=BoundaryText.of("w"), lease_seconds=60)
    assert lease is not None
    stop(conn, lease, RefusalCode.CITATION_NOT_LOCATED)
    conn.commit()
    assert _code(retry(STALE)) == (409, "COMMAND_EXPECTATION_STALE")
    assert _work(conn, run.run_id) == ("STOPPED", "CITATION_NOT_LOCATED", False)

    requeued = retry(run.fingerprint)

    assert requeued.status_code == 202
    assert requeued.json()["work"] == {
        "state": "QUEUED",
        "stop_code": None,
        "cancel_requested": False,
    }
    assert _audited(conn, case_id, "RUN_REQUEUED") == 1
    assert _code(retry(run.fingerprint)) == (409, "RUN_NOT_STOPPED")


def test_cancel_before_start_ends_the_run_cancelled_once(
    case: tuple[StoreConnection, UUID], client: TestClient, tmp_path: Path
) -> None:
    conn, case_id = case
    writer = member(conn, case_id)
    run = _Run(conn, case_id, tmp_path, pinned=True)
    start_key, cancel_key = uuid4(), uuid4()
    started = _post(
        client,
        case_id,
        run.run_id,
        "start",
        writer,
        fingerprint=run.fingerprint,
        key=start_key,
    )
    assert started.status_code == 202
    never = _Run(conn, case_id, tmp_path, pinned=False)

    for target in (run, never):
        cancelled = _post(
            client, case_id, target.run_id, "cancel", writer, key=cancel_key
        )
        assert cancelled.status_code == 202
        assert cancelled.json() == {
            "run_id": str(target.run_id),
            "run_status": "CANCELLED",
            "work": {"state": "DONE", "stop_code": None, "cancel_requested": True},
        }
        cancel_key = uuid4()
    events = "SELECT count(*) FROM run_events WHERE run_id = %s AND name = %s"
    assert _scalar(conn, events, never.run_id, "RUN_CANCELLED") == 1
    assert _audited(conn, case_id, "RUN_CANCEL_REQUESTED") == 2
    again = _post(client, case_id, never.run_id, "cancel", writer)
    assert _code(again) == (409, "RUN_NOT_RUNNING")
    assert _scalar(conn, events, never.run_id, "RUN_CANCELLED") == 1

    # T12: the stale start's replay returns its receipt and enqueues nothing.
    replay = _post(
        client,
        case_id,
        run.run_id,
        "start",
        writer,
        fingerprint=run.fingerprint,
        key=start_key,
    )
    assert replay.status_code == 202
    assert replay.headers["idempotency-replayed"] == "true"
    assert replay.json() == started.json()
    assert _work(conn, run.run_id) == ("DONE", None, True)
    assert _audited(conn, case_id, "RUN_ENQUEUED") == 1
    fresh = _post(
        client, case_id, run.run_id, "start", writer, fingerprint=run.fingerprint
    )
    assert _code(fresh) == (409, "RUN_NOT_RUNNING")


def test_cancel_during_a_claim_only_requests(
    case: tuple[StoreConnection, UUID], client: TestClient, tmp_path: Path
) -> None:
    conn, case_id = case
    writer = member(conn, case_id)
    run = _Run(conn, case_id, tmp_path, pinned=True)
    enqueue_run(conn, run.run_id)
    conn.commit()
    assert claim_run(conn, worker=BoundaryText.of("w"), lease_seconds=60) is not None

    requested = _post(client, case_id, run.run_id, "cancel", writer)

    assert requested.status_code == 202
    assert requested.json()["run_status"] == "RUNNING"
    assert requested.json()["work"] == {
        "state": "CLAIMED",
        "stop_code": None,
        "cancel_requested": True,
    }
    again = _post(client, case_id, run.run_id, "cancel", writer)
    assert _code(again) == (409, "RUN_CANCEL_REQUESTED")
    assert _audited(conn, case_id, "RUN_CANCEL_REQUESTED") == 1


FORBIDDEN = (
    "caos.graph.runtime",
    "caos.graph.worker",
    "caos.provider",
    "caos.methodology.runner",
    "caos.methodology.canonical",
)


def _imported(tree: ast.Module) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
            names.update(f"{node.module}.{alias.name}" for alias in node.names)
    return names


def test_command_modules_import_no_runtime_provider_or_transport() -> None:
    modules = sorted((REPO / "caos" / "api" / "commands").glob("*.py"))
    assert len(modules) >= 5, "a scan that scanned nothing is a failure"
    for module in modules:
        imported = _imported(ast.parse(module.read_text(encoding="utf-8")))
        banned = {
            name
            for name in imported
            for forbidden in FORBIDDEN
            if name == forbidden or name.startswith(forbidden + ".")
        }
        assert not banned, (module.name, banned)
    probe = _imported(ast.parse("from caos.graph import runtime\nimport caos.provider"))
    assert {"caos.graph.runtime", "caos.provider"} <= probe, "the scan sees both forms"


COMMANDS = ("start", "retry", "cancel")


def _ready(
    conn: StoreConnection, case_id: UUID, tmp_path: Path, command: str
) -> tuple[UUID, str | None]:
    """A run on which `command` succeeds, and the body's fingerprint."""
    run = _Run(conn, case_id, tmp_path, pinned=True)
    if command == "retry":
        enqueue_run(conn, run.run_id)
        conn.commit()
        lease = claim_run(conn, worker=BoundaryText.of("w"), lease_seconds=60)
        assert lease is not None
        stop(conn, lease, RefusalCode.CITATION_NOT_LOCATED)
        conn.commit()
    return run.run_id, None if command == "cancel" else run.fingerprint


@pytest.mark.parametrize("command", COMMANDS)
def test_start_retry_and_cancel_across_the_actor_matrix(
    case: tuple[StoreConnection, UUID],
    client: TestClient,
    tmp_path: Path,
    command: str,
) -> None:
    conn, case_id = case
    run_id, fingerprint = _ready(conn, case_id, tmp_path, command)
    # Prepared first: a later retry's claim would take the requeued run instead.
    second, second_fingerprint = _ready(conn, case_id, tmp_path, command)
    reader = member(conn, case_id, Standing.READER)
    writer = member(conn, case_id, Standing.WRITER)
    approver = member(conn, case_id, Standing.APPROVER)
    revoked = member(conn, case_id, Standing.ADMIN)
    revoke(conn, case_id=case_id, user_id=revoked)
    conn.commit()
    post: Callable[..., Response] = lambda user, **kw: _post(  # noqa: E731
        client, case_id, run_id, command, user, fingerprint=fingerprint, **kw
    )

    anonymous = client.post(f"/api/v1/cases/{case_id}/runs/{run_id}/{command}", json={})
    assert anonymous.status_code == 401
    assert _code(post(uuid4())) == (404, "CASE_NOT_FOUND")
    assert _code(post(uuid4(), role="ADMIN")) == (404, "CASE_NOT_FOUND")
    assert _code(post(revoked)) == (404, "CASE_NOT_FOUND")
    assert _code(post(reader)) == (403, "NOT_AUTHORISED")
    assert _code(post(writer, role="READER")) == (403, "NOT_AUTHORISED")

    other = create_case(conn, BoundaryText.of("Other 2026"))
    foreign = start_run(conn, other)
    conn.commit()
    for alien in (foreign, "not-a-run"):
        refused = _post(
            client, case_id, alien, command, writer, fingerprint=fingerprint
        )
        assert _code(refused) == (404, "RUN_NOT_FOUND")
    assert _scalar(conn, "SELECT count(*) FROM command_requests") == 0

    assert post(writer).status_code == 202
    by_approver = _post(
        client, case_id, second, command, approver, fingerprint=second_fingerprint
    )
    assert by_approver.status_code == 202


def test_each_execution_command_meets_its_store_budget(
    case: tuple[StoreConnection, UUID],
    client: TestClient,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn, case_id = case
    writer = member(conn, case_id)
    ready = {command: _ready(conn, case_id, tmp_path, command) for command in COMMANDS}
    executed: list[int] = []
    execute = type(conn).execute

    def counted(self: StoreConnection, *args: object, **kwargs: object) -> object:
        executed.append(1)
        return execute(self, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(type(conn), "execute", counted)
    spent: dict[str, int] = {}
    for command, (run_id, fingerprint) in ready.items():
        executed.clear()
        answer = _post(
            client, case_id, run_id, command, writer, fingerprint=fingerprint
        )
        assert answer.status_code == 202, command
        spent[command] = len(executed)
    assert max(spent.values()) == execution.IO_BUDGET, spent

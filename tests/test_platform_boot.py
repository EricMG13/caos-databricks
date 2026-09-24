"""The App booted the way the platform boots it, driven through its own HTTP
surface end to end (D28): health on minted credentials and the volume, a case,
its pack, a LITE run through `ChatDatabricks`, the event stream, the report.
Nothing below HTTP is injected; the workspace is the loopback stub."""

from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from uuid import UUID, uuid4, uuid5

import pytest
from canonical_fixtures import CATALOG, LITE_PROFILE, LITE_SELECTION
from platform_app import VOLUME, PlatformApp, platform_app, platform_environment
from test_loop_charges import REPORT, _Completions
from test_workspace_stub import stub
from workspace_stub import WorkspaceStub

from caos.api.identity import NAMESPACE
from caos.graph.route import resolve_route

__all__ = ["stub"]

ANALYST, APPROVER = "analyst-token", "approver-token"
ANALYST_ID, APPROVER_ID = "1001", "1002"
GATES = ("source-set", "research-plan")  # the path slugs of caos.api.commands.runs
SUBJECT = {
    "issuer_id": "EXAMPLE",
    "issuer_name": "Example Holdings plc",
    "reporting_period": "FY2025",
    "analysis_date": "2026-09-08",
}
RUN_SECONDS = 240
ROUTE = resolve_route(CATALOG, LITE_PROFILE, LITE_SELECTION)


@dataclass(frozen=True, slots=True)
class Answer:
    status: int
    body: dict[str, Any]


class Surface:
    """JSON calls against the booted app as one workspace user, presented the
    way the Apps proxy presents them: the user's token forwarded, and an
    idempotency key on every command."""

    def __init__(self, url: str, token: str) -> None:
        self.url, self.token = url, token

    def call(
        self,
        method: str,
        path: str,
        body: bytes | None = None,
        *,
        content_type: str = "application/json",
    ) -> Answer:
        headers = {"x-forwarded-access-token": self.token, "accept": "application/json"}
        if method == "POST":
            headers["idempotency-key"] = str(uuid4())
            headers["content-type"] = content_type
            headers["origin"] = self.url  # a command names its origin (edge rule)
        request = urllib.request.Request(
            self.url + path, data=body, method=method, headers=headers
        )
        try:
            with urllib.request.urlopen(request, timeout=60) as answer:
                return Answer(answer.status, _json(answer.read()))
        except urllib.error.HTTPError as failed:
            return Answer(failed.code, _json(failed.read()))

    def get(self, path: str) -> Answer:
        return self.call("GET", path)

    def post(self, path: str, body: dict[str, Any]) -> Answer:
        return self.call("POST", path, json.dumps(body).encode())

    def upload(self, path: str, filename: str, data: bytes) -> Answer:
        boundary = "caos-journey-" + uuid4().hex
        disposition = f'form-data; name="document"; filename="{filename}"'
        head = (
            f"--{boundary}\r\nContent-Disposition: {disposition}\r\n"
            "Content-Type: text/plain\r\n\r\n"
        ).encode()
        form = head + data + f"\r\n--{boundary}--\r\n".encode()
        kind = f"multipart/form-data; boundary={boundary}"
        return self.call("POST", path, form, content_type=kind)


def _json(raw: bytes) -> dict[str, Any]:
    try:
        parsed = json.loads(raw or b"{}")
    except ValueError:
        return {"raw": raw[:300].decode(errors="replace")}
    return parsed if isinstance(parsed, dict) else {"value": parsed}


@dataclass
class Stream:
    """One reader of a case's event stream: when its first named event came
    and whether the connection was still open then."""

    events: list[str] = field(default_factory=list)
    first_at: float | None = None
    ended_at: float | None = None
    error: str | None = None

    def watch(self, url: str, token: str, seconds: float) -> None:
        headers = {"x-forwarded-access-token": token, "accept": "text/event-stream"}
        request = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=seconds) as answer:
                for line in answer:
                    text = line.decode().rstrip("\n")
                    if text.startswith("event: "):
                        self.events.append(text[len("event: ") :])
                        self.first_at = self.first_at or time.monotonic()
        except (urllib.error.URLError, OSError, TimeoutError) as failed:
            self.error = type(failed).__name__
        self.ended_at = time.monotonic()


@pytest.fixture
def app(
    stub: WorkspaceStub, empty_database: str, tmp_path: Path
) -> Iterator[PlatformApp]:
    stub.identities = {
        ANALYST: (ANALYST_ID, frozenset({"caos-analysts"})),
        APPROVER: (APPROVER_ID, frozenset({"caos-admins"})),
    }
    with platform_app(stub, empty_database, tmp_path / "caos.serve.log") as served:
        yield served


def test_the_boot_environment_is_the_bundle_s_and_what_the_deploy_sent(
    stub: WorkspaceStub, tmp_path: Path
) -> None:
    """DF-12: the harness sets every variable the bundle sets, and when the
    stub holds a deployment, the values the CLI sent with it are the ones
    the process boots with; only the bind address and the export stay local."""
    from check_gate_config import APP_ENVIRONMENT

    database = "postgresql://u:p@127.0.0.1:5432/db"
    env = platform_environment(stub, database, 8000, tmp_path)
    assert {name for name in env if name.startswith("CAOS_")} >= APP_ENVIRONMENT
    sent = [
        {"name": "CAOS_RUN_CEILING", "value": "30.00"},
        {"name": "CAOS_BIND_HOST", "value": "0.0.0.0"},
        {"name": "CAOS_SITE_ROOT", "value": "frontend/dist"},
    ]
    stub.deployment_bodies.append({"env_vars": sent})
    env = platform_environment(stub, database, 8000, tmp_path)
    assert env["CAOS_RUN_CEILING"] == "30.00"
    assert (env["CAOS_BIND_HOST"], env["CAOS_SITE_ROOT"]) == (
        "127.0.0.1",
        str(tmp_path),
    )


def test_the_platform_process_boots_ready_on_minted_credentials_and_the_volume(
    app: PlatformApp, stub: WorkspaceStub
) -> None:
    health = app.health()
    assert health["status"] == "ready", health
    assert str(health["python_version"]).startswith("3.13")
    assert health["store"] == health["blobs"] == health["bundle"], health
    assert ("POST", "/api/2.0/database/credentials") in stub.requests
    assert ("HEAD", "/api/2.0/fs/directories" + VOLUME) in stub.requests
    # The platform is the edge: a request with no forwarded token is anonymous,
    # and a role header a client sends decides nothing.
    anonymous = urllib.request.Request(
        app.url + "/api/v1/book", headers={"x-caos-role": "ADMIN"}
    )
    with pytest.raises(urllib.error.HTTPError) as refused:
        urllib.request.urlopen(anonymous, timeout=10)
    assert refused.value.code == 401


def test_a_governed_run_completes_through_the_platform_surface(
    app: PlatformApp, stub: WorkspaceStub
) -> None:
    analyst, approver = Surface(app.url, ANALYST), Surface(app.url, APPROVER)
    created = analyst.post("/api/v1/cases", {"title": "Journey Holdings"})
    assert created.status == 201, created.body
    case = created.body["case_id"]
    approver_id = str(uuid5(NAMESPACE, f"1234:{APPROVER_ID}"))
    granted = analyst.post(
        f"/api/v1/cases/{case}/members",
        {"user_id": approver_id, "standing": "APPROVER"},
    )
    assert granted.status == 201, granted.body

    admitted = analyst.upload(f"/api/v1/cases/{case}/sources", "report.txt", REPORT)
    assert admitted.status == 201, admitted.body
    [source] = admitted.body["source_ids"]
    assert any(name.startswith(VOLUME + "/") for name in stub.files), (
        "bytes in the volume"
    )
    answers = _Completions(UUID(source))

    def reply(prompt: str, json_object: bool) -> str:
        return answers.complete(prompt, json_object=json_object).content or ""

    stub.reply = reply

    run = analyst.post(
        f"/api/v1/cases/{case}/runs",
        {
            "profile_id": LITE_PROFILE,
            "selection_id": LITE_SELECTION,
            "supersedes": None,
            "model_extension": False,
        },
    )
    assert run.status == 201, run.body
    run_id = run.body["run_id"]
    base = f"/api/v1/cases/{case}/runs/{run_id}"
    pinned = analyst.post(f"{base}/input", {"subject": SUBJECT})
    assert pinned.status in (200, 201), pinned.body
    fingerprint = pinned.body["input_fingerprint"]
    for gate in GATES:
        preview = approver.get(f"{base}/gates/{gate}/preview")
        assert preview.status == 200, preview.body
        approved = approver.post(
            f"{base}/gates/{gate}/approval",
            {
                "preview_sha256": preview.body["preview_sha256"],
                "input_fingerprint": preview.body["input_fingerprint"],
            },
        )
        assert approved.status in (200, 201), approved.body

    stream = Stream()
    events_url = f"{app.url}/api/v1/cases/{case}/events?run={run_id}"
    watcher = threading.Thread(
        target=stream.watch, args=(events_url, ANALYST, RUN_SECONDS), daemon=True
    )
    watcher.start()
    started = analyst.post(f"{base}/start", {"input_fingerprint": fingerprint})
    assert started.status == 202, started.body

    status, view = _wait_for_end(analyst, case, run_id)
    finished_at = time.monotonic()
    assert status == "COMPLETE", (
        view,
        app.health().get("workers"),
        stub.completions,
        app.log_tail(),
    )
    assert stream.first_at is not None, ("no event arrived", stream)
    assert stream.first_at < finished_at
    assert stream.ended_at is None or stream.ended_at > stream.first_at, stream
    assert stub.completions == stub.json_completions == len(ROUTE.nodes)

    report = analyst.get(f"/api/v1/cases/{case}/report?run={run_id}")
    assert report.status == 200, report.body
    # Everything the run accepted is in the volume, by digest.
    assert len(stub.files) > 1


def _wait_for_end(
    surface: Surface, case: str, run_id: str
) -> tuple[str, dict[str, Any]]:
    deadline = time.monotonic() + RUN_SECONDS
    view: dict[str, Any] = {}
    while time.monotonic() < deadline:
        answer = surface.get(f"/api/v1/cases/{case}/run?run={run_id}")
        view = answer.body
        run = (view.get("body") or {}).get("run") or {}
        status = str(run.get("status", ""))
        if answer.status == 200 and status and status != "RUNNING":
            return status, view
        time.sleep(1.0)
    return "TIMEOUT", view


@contextmanager
def _app_role(database_url: str, *, database_create: bool) -> Iterator[str]:
    """A login role holding only what the bundle grants the app's service
    principal (MAX-22, DL-1): CONNECT and, when `database_create`, CREATE on
    the database -- what `CAN_CONNECT_AND_CREATE` gives. Nothing on `public`,
    which PostgreSQL 15 and later give nobody. Its URL; the role goes when the
    block ends."""
    import psycopg

    parts = urlparse(database_url)
    database = parts.path.lstrip("/")
    role, password = f"caos_app_{uuid4().hex[:12]}", uuid4().hex
    granted = "CONNECT, CREATE" if database_create else "CONNECT"
    with psycopg.connect(database_url, autocommit=True) as admin:
        # Both names are this function's own hex, never caller input.
        admin.execute(f"CREATE ROLE \"{role}\" LOGIN PASSWORD '{password}'")
        admin.execute(f'GRANT {granted} ON DATABASE "{database}" TO "{role}"')
        admin.execute(f'REVOKE ALL ON SCHEMA public FROM PUBLIC, "{role}"')
    host = f"{parts.hostname}:{parts.port or 5432}"
    try:
        yield f"postgresql://{role}:{password}@{host}/{database}"
    finally:
        with psycopg.connect(database_url, autocommit=True) as admin:
            admin.execute(f'DROP OWNED BY "{role}" CASCADE')
            admin.execute(f'DROP ROLE "{role}"')


def test_the_app_starts_on_the_bundle_s_database_grant_alone(
    stub: WorkspaceStub, empty_database: str, tmp_path: Path
) -> None:
    """DL-1 (MAX-22): every other boot here connects as an administrator.
    Holding only CONNECT and CREATE on the database -- the bundle's
    `CAN_CONNECT_AND_CREATE`, and no hand-run grant on `public` -- the
    process creates and fills the store's own schema and the checkpoint
    schema, and answers ready; `public` is left with nothing of either."""
    import psycopg

    with _app_role(empty_database, database_create=True) as url:
        with platform_app(stub, url, tmp_path / "caos.serve.log") as served:
            health = served.health()
        with psycopg.connect(empty_database) as admin:  # before the role goes
            placed = {
                str(row[0])
                for row in admin.execute(
                    "SELECT DISTINCT table_schema FROM information_schema.tables"
                    " WHERE table_schema IN ('public', 'caos_store', 'caos_graph')"
                ).fetchall()
            }
    assert health["status"] == "ready" and health["store"] == "OK", health
    assert placed == {"caos_store", "caos_graph"}, placed


def test_a_role_that_may_not_create_the_schema_is_refused_by_sqlstate(
    empty_database: str, capsys: pytest.CaptureFixture[str]
) -> None:
    """DL-1: without CREATE on the database the store's schema cannot be
    created. The refusal keeps its typed code, and stderr carries the
    server's SQLSTATE alone -- 42501, a missing privilege, told apart from
    drift -- never the server's message."""
    from caos.refusals import Refusal, RefusalCode
    from caos.store import apply_schema, connect

    with _app_role(empty_database, database_create=False) as url:
        conn = connect(url)
        try:
            with pytest.raises(Refusal) as refused:
                apply_schema(conn)
        finally:
            conn.close()
    assert refused.value.code is RefusalCode.STORE_SCHEMA_DRIFT
    assert capsys.readouterr().err == "schema: sqlstate 42501\n"


def test_the_platform_s_stop_signal_drains_the_worker_inside_the_grace(
    app: PlatformApp,
) -> None:
    """DP-4: uvicorn re-raises SIGTERM after its shutdown, so the drain lives
    in the app's shutdown hook (`caos.api.app.on_shutdown`): the worker sees
    `stopping`, is joined, and the process ends inside the platform's grace."""
    import signal

    from caos import serve

    assert serve.GRACEFUL_SECONDS + serve.LIMIT_JOIN_SECONDS < 15
    app.process.send_signal(signal.SIGTERM)
    app.process.wait(timeout=serve.GRACEFUL_SECONDS + serve.LIMIT_JOIN_SECONDS + 10)
    assert "worker stopped" in app.log_tail(), app.log_tail()


def test_a_redeploy_whose_worker_refused_does_not_report_the_last_one_s(
    stub: WorkspaceStub,
    empty_database: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """DF-1. Every release after the first boots on a store whose previous
    process's last beat is still fresh for five minutes, and any fresh beat
    answered `workers=OK`: a release whose in-process worker refused to start
    served `ready` with `workers=OK`, E6 recorded exit 0 and the deploy
    printed its URL while runs queued and never ran. Booted twice on one
    store, the second time with a configuration the worker refuses."""
    import enterprise_deploy

    with platform_app(stub, empty_database, tmp_path / "first.log") as first:
        deadline = time.monotonic() + 30
        while first.health()["workers"] != "OK" and time.monotonic() < deadline:
            time.sleep(0.5)
        assert first.health()["workers"] == "OK", first.log_tail()
    # Stopped by the platform's signal; its last POLLING beat stays behind.
    monkeypatch.setenv("CAOS_REASONING_EFFORT", "high")  # the worker refuses it
    monkeypatch.setattr(enterprise_deploy, "_headers", dict)  # health needs none
    with platform_app(stub, empty_database, tmp_path / "second.log") as second:
        health = second.health()
        assert "PROVIDER_NOT_CONFIGURED" in second.log_tail(), second.log_tail()
        code, line = enterprise_deploy._health_once(second.url)
    assert health["status"] == "ready", health
    assert health["workers"] == "WORKERS_ABSENT", health
    assert code == 1, line

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
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4, uuid5

import pytest
from canonical_fixtures import CATALOG, LITE_PROFILE, LITE_SELECTION
from platform_app import VOLUME, PlatformApp, platform_app
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

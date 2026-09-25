"""One governed LITE run through a booted app's own HTTP surface, as two
workspace users the way the Apps proxy presents them: a case, its approver,
a pack, the input pin, both gates, the event stream, the run to its end and
the report (D28). `tests/test_platform_boot.py` asserts on what it returns;
`tests/shipped_boot.py` drives it against the app booted from the file set a
deployment ships."""

from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID, uuid4, uuid5

from canonical_fixtures import LITE_PROFILE, LITE_SELECTION
from platform_app import VOLUME, PlatformApp
from test_loop_charges import REPORT, _Completions
from workspace_stub import WorkspaceStub

from caos.api.identity import NAMESPACE

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


@dataclass(frozen=True, slots=True)
class Journey:
    """What one governed run left behind: its final status and Run view, the
    stream that watched it, when it ended, and the report read after it."""

    status: str
    view: dict[str, Any]
    stream: Stream
    finished_at: float
    report: Answer


def identities() -> dict[str, tuple[str, frozenset[str]]]:
    """The two workspace users the journey acts as, by bearer, for the stub's
    SCIM: an analyst and an admin who approves."""
    return {
        ANALYST: (ANALYST_ID, frozenset({"caos-analysts"})),
        APPROVER: (APPROVER_ID, frozenset({"caos-admins"})),
    }


def governed_run(app: PlatformApp, stub: WorkspaceStub) -> Journey:
    """Drive one LITE run from a new case to its end; each step before the
    start must answer as the command's contract says (`AssertionError` with
    the body otherwise), and the run's own end is returned, not asserted."""
    stub.identities = identities()
    analyst, approver = Surface(app.url, ANALYST), Surface(app.url, APPROVER)
    case, source = _admitted_case(analyst, stub)
    answers = _Completions(UUID(source))

    def reply(prompt: str, json_object: bool) -> str:
        return answers.complete(prompt, json_object=json_object).content or ""

    stub.reply = reply
    run_id, fingerprint = _approved_run(analyst, approver, case)
    stream = Stream()
    events_url = f"{app.url}/api/v1/cases/{case}/events?run={run_id}"
    watcher = threading.Thread(
        target=stream.watch, args=(events_url, ANALYST, RUN_SECONDS), daemon=True
    )
    watcher.start()
    base = f"/api/v1/cases/{case}/runs/{run_id}"
    started = analyst.post(f"{base}/start", {"input_fingerprint": fingerprint})
    assert started.status == 202, started.body
    status, view = wait_for_end(analyst, case, run_id)
    finished_at = time.monotonic()
    report = analyst.get(f"/api/v1/cases/{case}/report?run={run_id}")
    return Journey(status, view, stream, finished_at, report)


def _admitted_case(analyst: Surface, stub: WorkspaceStub) -> tuple[str, str]:
    """A new case with the approver as a member and one text source admitted
    to the volume; the case and source ids."""
    created = analyst.post("/api/v1/cases", {"title": "Journey Holdings"})
    assert created.status == 201, created.body
    case = str(created.body["case_id"])
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
    return case, str(source)


def _approved_run(analyst: Surface, approver: Surface, case: str) -> tuple[str, str]:
    """A LITE run with its input pinned and both gates approved by the
    approver; the run id and the input fingerprint Start must name."""
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
    run_id = str(run.body["run_id"])
    base = f"/api/v1/cases/{case}/runs/{run_id}"
    pinned = analyst.post(f"{base}/input", {"subject": SUBJECT, "research": None})
    assert pinned.status in (200, 201), pinned.body
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
    return run_id, str(pinned.body["input_fingerprint"])


def wait_for_end(
    surface: Surface, case: str, run_id: str
) -> tuple[str, dict[str, Any]]:
    """The run's status once it is no longer RUNNING, with its Run view, or
    `TIMEOUT` after `RUN_SECONDS`."""
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

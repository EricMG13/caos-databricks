"""`scripts/enterprise_deploy.sh` against the loopback workspace and the app
booted the platform way (D28, F31): the CLI on the path is a recorder, every
other step is the real one over HTTP, and the rows say what happened."""

from __future__ import annotations

import http.server
import json
import os
import re
import subprocess
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import check_gate_config
import enterprise_deploy
import pytest
from enterprise_deploy import Evidence, Row
from platform_app import REPO, PlatformApp
from test_platform_boot import app, stub
from workspace_stub import BEARER, ENDPOINT, PRICE, WorkspaceStub

__all__ = ["app", "stub"]

# What `bundle validate -o json` resolves for the dev target under the stub,
# cut to the fields the one command reads (DF-5: the stub's user id is 42).
DEV_APP = "caos-dev-42"


def _resolved(name: str, **env: str) -> dict[str, Any]:
    values = {
        "CAOS_MODEL_ENDPOINT": ENDPOINT,
        "CAOS_MODEL_PRICE": PRICE,
        "CAOS_RUN_CEILING": "100.00",  # the bundle default (D29)
        **env,
    }
    listed = [{"name": key, "value": value} for key, value in values.items()]
    return {"resources": {"apps": {"caos": {"name": name, "config": {"env": listed}}}}}


def test_the_one_command_runs_the_cli_and_verifies_the_deployment(
    app: PlatformApp, stub: WorkspaceStub, empty_database: str, tmp_path: Path
) -> None:
    parts = urlparse(empty_database)
    stub.instance_host = parts.hostname or "127.0.0.1"
    stub.user_name = parts.username or "postgres"  # Lakebase mints for the caller
    # What a real `bundle deploy` creates the app with; the recorder CLI does
    # not. E5 reads the name the CLI resolved, not one it recomputes (DF-5).
    stub.apps.add(DEV_APP)
    stub.app_bodies[DEV_APP] = {"forward_user_access_token": True}
    # R24-15: comma-holding group names (e.g. "Research, Credit") are
    # supported workspace display names; E1 must find them by their exact
    # name, unsplit. Added alongside the deployer's own admin group, which
    # E9's writer-standing check still needs.
    stub.groups |= {"Research, Credit", "Analysts, Readers"}
    calls = tmp_path / "cli-calls.txt"
    resolved = tmp_path / "resolved.json"
    resolved.write_text(json.dumps(_resolved(DEV_APP)))
    # What a real deploy records it synced: every file the app reads (DF-4).
    state = tmp_path / "state"
    state.mkdir()
    synced = [
        {"local_path": path} for path in sorted(check_gate_config.shipped_files())
    ]
    (state / "deployment.json").write_text(json.dumps({"files": synced}))
    shim = tmp_path / "bin"
    shim.mkdir()
    recorder = (
        "#!/usr/bin/env bash\n"
        'printf "%s price=%s admin=%s analyst=%s\\n" "$*" "$BUNDLE_VAR_model_price" '
        f'"$BUNDLE_VAR_group_admin" "$BUNDLE_VAR_group_analyst" >> "{calls}"\n'
        f'case " $* " in *" -o json "*) cat "{resolved}" ;; '
        '*) echo "Validation OK!" ;; esac\n'
    )
    (shim / "databricks").write_text(recorder)
    (shim / "databricks").chmod(0o755)
    evidence = tmp_path / "enterprise"
    env = {
        **os.environ,
        **stub.environment(),
        "PATH": f"{shim}{os.pathsep}{os.environ['PATH']}",
        "EVIDENCE": str(evidence),
        "BUNDLE_STATE": str(state),
        "TARGET": "dev",
        "LAKEBASE_DATABASE": parts.path.lstrip("/"),
        "PG_PORT": str(parts.port),
        "PG_SSLMODE": "disable",
        "MLFLOW_DISABLE_AGENT_HINT": "1",
        # R24-15: a comma-containing group name, the CLI's `--var` parser
        # splits a value on commas even when the shell argument is quoted.
        "GROUP_ADMIN": "Research, Credit",
        "GROUP_ANALYST": "Analysts, Readers",
        # The stub has no proxy to forward the caller's token (W4).
        enterprise_deploy.FORWARD_CALLER_ENV: "1",
    }
    env.pop("DATABRICKS_CONFIG_PROFILE", None)
    done = subprocess.run(
        [
            str(REPO / "scripts/enterprise_deploy.sh"),
            "",
            "main",
            "caos",
            "caos-lb",
            ENDPOINT,
            PRICE,
        ],
        cwd=REPO,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert done.returncode == 0, done.stdout + done.stderr
    rows = [
        line.split("\t")
        for line in (evidence / "evidence.tsv").read_text().splitlines()
    ]
    assert [row[0] for row in rows] == [f"E{n}" for n in range(1, 11)]
    assert all(row[2] == "0" for row in rows), rows
    assert (
        rows[1][3]
        == f"resolved app {DEV_APP}: endpoint, price and run ceiling as given"
    )
    assert rows[2][3] == "every path the app needs was synced"
    assert rows[4][1] == f"apps get {DEV_APP}"
    seen = calls.read_text().splitlines()
    assert [line.split(" -t ")[0] for line in seen] == [
        "bundle validate -o json",
        "bundle deploy",
        "bundle run caos",
    ]
    assert all("--var run_ceiling=100.00" in line and "-p" not in line for line in seen)
    # The price travels whole in the environment (C1), never as a `--var`.
    assert all(f"price={PRICE}" in line and "model_price" not in line for line in seen)
    # R24-15: the comma-holding group names travel the same way, never as a
    # `--var` the CLI's own parser would split on the comma.
    assert all(
        "admin=Research, Credit analyst=Analysts, Readers" in line
        and "group_admin" not in line
        and "group_analyst" not in line
        for line in seen
    )
    assert "answered 200 status=ready" in rows[5][3] and "workers=OK" in rows[5][3]
    assert "json_mode=accepted" in (evidence / "E7.log").read_text()
    assert "PostgreSQL" in (evidence / "E8.log").read_text()
    assert "with the stream open" in rows[8][3]
    assert "one model call recorded" in rows[-1][3]
    assert f"deployed: {app.url}" in done.stdout
    # No credential in any row, log or line: the bearer the SDK was handed,
    # and the minted password in the only shape it could leak in, a URL.
    everything = "".join(p.read_text() for p in evidence.iterdir()) + done.stdout
    assert BEARER not in everything
    assert parts.password and f":{parts.password}@" not in everything


def test_a_recorded_cli_step_is_one_row_with_the_log_tail(tmp_path: Path) -> None:
    log = tmp_path / "E2.out"
    log.write_text("Name: caos\n\nValidation OK!\n")
    code = enterprise_deploy.main(
        [
            "--stage",
            "record",
            "--evidence",
            str(tmp_path / "ev"),
            "--step",
            "E2",
            "--command",
            "databricks bundle validate",
            "--code",
            "0",
            "--log",
            str(log),
        ]
    )
    assert code == 0
    written = (tmp_path / "ev" / "evidence.tsv").read_text()
    assert written == "E2\tdatabricks bundle validate\t0\tValidation OK!\n"
    evidence = Evidence(tmp_path / "again")
    assert evidence.record("E3", "databricks bundle deploy", 7, "") == 7
    assert evidence.rows == [Row("E3", "databricks bundle deploy", 7, "")]


def test_a_validate_that_resolved_other_values_is_a_failed_row(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """DF-4 and DF-5: a misspelt `BUNDLE_VAR_model_price` validates on the
    default price, and a target with no name rule of its own resolves to the
    production app. Either is E2 failing, before anything deploys."""
    for name in ("CAOS_MODEL_ENDPOINT", "CAOS_MODEL_PRICE"):
        monkeypatch.delenv(name, raising=False)  # `main` sets them; undone after
    given = ["--target", "dev", "--endpoint", ENDPOINT, "--price", PRICE]
    resolved = tmp_path / "bundle.json"
    log = tmp_path / "E2.cli.log"
    log.write_text("")

    def record(document: object) -> tuple[int, str]:
        resolved.write_text(json.dumps(document))
        flags = ["--step", "E2", "--log", str(log), "--bundle", str(resolved)]
        evidence = tmp_path / "ev"
        code = enterprise_deploy.main(
            ["--stage", "record", "--evidence", str(evidence), *given, *flags]
        )
        return code, _last_summary(evidence)

    default = "databricks-claude-opus-5,0.000005,0.000025,2026-09-01"
    code, summary = record(_resolved(DEV_APP, CAOS_MODEL_PRICE=default))
    assert (code, summary) == (1, "resolved CAOS_MODEL_PRICE is not the value given")
    code, summary = record(_resolved("caos"))
    assert (code, summary) == (1, "target dev resolves to the production app")
    code, summary = record({"resources": {}})
    assert code == 1 and summary.startswith("no app resolved")
    code, summary = record(_resolved(DEV_APP))
    assert code == 0 and summary.startswith(f"resolved app {DEV_APP}")
    assert enterprise_deploy.resolved_app("not a document") == ("", {})
    assert (
        enterprise_deploy.resolution_problems(
            _resolved("caos"),
            target="prod",
            endpoint=ENDPOINT,
            price=PRICE,
            run_ceiling="100.00",
        )
        == []
    )
    # With nothing resolved, E5 has no name to look up and says so.
    assert (
        enterprise_deploy.main(["--stage", "after", "--evidence", str(tmp_path / "e5")])
        == 1
    )
    assert _last_summary(tmp_path / "e5") == "no app name resolved by E2"


def test_a_deploy_whose_record_lacks_a_file_the_app_reads_is_a_failed_row(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """DF-4: a sync that drops the export's scripts deploys a page that
    renders nothing while health, E6 and E9 stay green; E3 reads the CLI's
    own record of what it synced and fails."""
    for name in ("CAOS_MODEL_ENDPOINT", "CAOS_MODEL_PRICE"):
        monkeypatch.delenv(name, raising=False)  # `main` sets them; undone after
    needed = sorted(check_gate_config.shipped_files())
    dropped = next(p for p in needed if p.startswith("caos/"))
    record = tmp_path / "deployment.json"
    record.write_text(json.dumps({"files": [{"local_path": p} for p in needed]}))
    flags = ["--stage", "record", "--evidence", str(tmp_path / "ev"), "--step", "E3"]
    assert enterprise_deploy.main([*flags, "--shipped", str(record)]) == 0
    assert _last_summary(tmp_path / "ev") == "every path the app needs was synced"
    kept = [{"local_path": p} for p in needed if p != dropped]
    record.write_text(json.dumps({"files": kept}))
    assert enterprise_deploy.main([*flags, "--shipped", str(record)]) == 1
    assert _last_summary(tmp_path / "ev") == f"shipped: {dropped} was not synced"
    # A deploy that failed is its own code; the record is not read.
    assert enterprise_deploy.main([*flags, "--code", "3", "--shipped", "x"]) == 3

    def unlisted(root: Path, *pathspecs: str) -> list[str]:
        raise RuntimeError

    monkeypatch.setattr(check_gate_config, "tracked_files", unlisted)
    assert enterprise_deploy.main([*flags, "--shipped", str(record)]) == 1
    assert _last_summary(tmp_path / "ev").endswith("could not be listed (RuntimeError)")


def test_e5_fails_closed_on_an_app_that_is_not_running(
    stub: WorkspaceStub, tmp_path: Path
) -> None:
    """DF-12: the stand-in can now answer a crashed app, and E5 reads it as
    the failure it is."""
    stub.apps.add(DEV_APP)
    stub.app_bodies[DEV_APP] = {"forward_user_access_token": True}
    evidence = Evidence(tmp_path / "ev")
    assert (
        enterprise_deploy._app_url(evidence, DEV_APP) == f"{stub.host}/apps/{DEV_APP}"
    )
    stub.app_state = "CRASHED"
    assert enterprise_deploy._app_url(evidence, DEV_APP) == ""
    assert evidence.rows[-1].code == 1
    assert evidence.rows[-1].summary.startswith("state=CRASHED")


def _last_summary(evidence: Path) -> str:
    return (evidence / "evidence.tsv").read_text().splitlines()[-1].split("\t")[3]


def test_no_target_but_prod_names_the_production_app() -> None:
    """DP-6 and DF-5: the app's name is `caos-<target>` unless a target says
    otherwise, only `prod` says `caos`, and each developer's dev copy carries
    their numeric user id so two developers never share one app."""
    text = (REPO / "databricks.yml").read_text()
    top, _, targets = text.partition("\ntargets:\n")
    assert re.search(r"^      name: caos-\$\{bundle\.target\}$", top, re.M), top
    blocks = re.split(r"^  (\w+):\n", targets, flags=re.M)[1:]
    names = {
        target: re.findall(r"^          name: (\S+)$", body, re.M)
        for target, body in zip(blocks[::2], blocks[1::2], strict=True)
    }
    assert names.pop("prod") == ["caos"]
    assert names.pop("dev") == ["caos-${bundle.target}-${workspace.current_user.id}"]
    assert all("caos" not in overrides for overrides in names.values()), names


Write = tuple[float, bytes]  # (the wait before it, the bytes)
Scripted = tuple[
    int, dict[str, str], list[Write], bool
]  # status, headers, writes, close


@contextmanager
def _scripted(answers: list[Scripted]) -> Iterator[str]:
    """A loopback app that answers each request with the next scripted answer:
    its writes after their waits, then a close, or a silence that outlasts
    E9's wait for the next frame."""

    class _Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: object) -> None:
            del format, args

        def _answer(self) -> None:
            self.rfile.read(int(self.headers.get("Content-Length") or 0))
            status, headers, writes, close = answers.pop(0)
            self.send_response(status)
            for name, value in headers.items():
                self.send_header(name, value)
            self.end_headers()
            try:
                for wait, data in writes:
                    time.sleep(wait)
                    self.wfile.write(data)
                    self.wfile.flush()
                if not close:
                    time.sleep(enterprise_deploy.LIVE_SECONDS + 1)
            except OSError:
                return

        do_GET = do_POST = _answer

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()


JSON = {"Content-Type": "application/json"}
SSE = {"Content-Type": "text/event-stream"}
CASE: Scripted = (201, JSON, [(0, b'{"case_id": "c1"}')], True)
BEAT = 0.05


def _beats(seconds: float) -> list[Write]:
    return [(BEAT, b":\n\n")] * int(seconds / BEAT)


def test_the_stream_row_needs_frames_for_the_whole_interval(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AR-05, DF-2 and MAX-08: a stream is live only when frames keep coming
    for `LIVE_SECONDS`, none more than `FRAME_GAP_SECONDS` apart. A proxy
    that forwards the first frame and holds the rest, one that cuts the
    stream early, and two frames already buffered before a close all fail;
    so do an HTML page and a 403 with any code but NOT_AUTHORISED (W1)."""
    monkeypatch.setattr(
        enterprise_deploy, "_headers", lambda: {"Authorization": "Bearer x"}
    )
    monkeypatch.setattr(enterprise_deploy, "STREAM_SECONDS", 5.0)
    monkeypatch.setattr(enterprise_deploy, "LIVE_SECONDS", 1.0)
    monkeypatch.setattr(enterprise_deploy, "FRAME_GAP_SECONDS", 0.4)
    evidence = Evidence(tmp_path / "ev")
    first: Write = (0, b"id: 0.1\n\n")
    streams: dict[str, tuple[Scripted, str]] = {
        "heartbeats": (
            (200, SSE, [first, *_beats(1.6)], True),
            "first frame 'id: 0.1', then frames for 1.0s with the stream open",
        ),
        "first-then-hold": ((200, SSE, [first], False), "then no frame for 0.4s"),
        "cut": ((200, SSE, [first, *_beats(0.3)], True), "then the stream closed"),
        "buffered": (
            (200, SSE, [(0, b"id: 0.1\n\n:\n\n")], True),
            "then the stream closed",
        ),
        "silent": ((200, SSE, [], True), "no event frame before close"),
        "html": (
            (200, {"Content-Type": "text/html"}, [(0, b"<html></html>")], True),
            "not an event stream",
        ),
    }
    for label, (answer, said) in streams.items():
        with _scripted([CASE, answer]) as url:
            code, case_id = enterprise_deploy._stream(url, evidence)
        assert said in evidence.rows[-1].summary, (label, evidence.rows[-1])
        ok = label == "heartbeats"
        assert code == (0 if ok else 1), label
        assert case_id == ("c1" if ok else ""), label
    refused: Scripted = (403, JSON, [(0, b'{"code": "ORIGIN_REFUSED"}')], True)
    with _scripted([refused]) as url:
        assert enterprise_deploy._stream(url, evidence) == (1, "")
    assert "answered 403 ORIGIN_REFUSED" in evidence.rows[-1].summary
    unauthorised: Scripted = (403, JSON, [(0, b'{"code": "NOT_AUTHORISED"}')], True)
    with _scripted([unauthorised]) as url:
        assert enterprise_deploy._stream(url, evidence) == (0, "")
    assert evidence.rows[-1].summary.startswith("unverified")
    # A case answer cut short is a row with its class, not a traceback (MAX-17).
    short: Scripted = (201, {**JSON, "Content-Length": "100"}, [(0, b"{}")], True)
    with _scripted([short]) as url:
        assert enterprise_deploy._stream(url, evidence) == (1, "")
    assert evidence.rows[-1] == Row("E9", "POST /api/v1/cases", 1, "IncompleteRead")


def test_the_frame_gap_allows_a_late_heartbeat_and_no_more() -> None:
    """The app beats every `POLL_INTERVAL`: E9 lets a beat or two run late
    and still needs several inside `LIVE_SECONDS`."""
    from caos.api.app import POLL_INTERVAL

    assert 2 * POLL_INTERVAL <= enterprise_deploy.FRAME_GAP_SECONDS
    assert 2 * enterprise_deploy.FRAME_GAP_SECONDS <= enterprise_deploy.LIVE_SECONDS


def test_a_truncated_health_answer_is_a_row_not_a_traceback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """MAX-17: a body shorter than its declared length is `IncompleteRead`,
    polled like any failed answer and recorded as E6."""
    monkeypatch.setattr(
        enterprise_deploy, "_headers", lambda: {"Authorization": "Bearer x"}
    )
    monkeypatch.setattr(enterprise_deploy, "HEALTH_SECONDS", 0.0)
    short: Scripted = (
        200,
        {**JSON, "Content-Length": "100"},
        [(0, b'{"status"')],
        True,
    )
    evidence = Evidence(tmp_path / "ev")
    with _scripted([short]) as url:
        assert enterprise_deploy._health(url, evidence) == 1
    assert evidence.rows == [Row("E6", "GET /api/health", 1, "IncompleteRead")]


def test_open_forwards_the_query_string() -> None:
    """CF-054: `urlsplit` gives `path` and `query` separately, and `_open`
    once sent only the first -- so E10's own `?run=<id>` reached the app as
    the whole case's stream, never the one run's."""
    seen: list[str] = []

    class _Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: object) -> None:
            del format, args

        def do_GET(self) -> None:
            seen.append(self.path)
            self.send_response(200)
            self.send_header("Content-Length", "0")
            self.end_headers()

    server = http.server.HTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        url = f"http://127.0.0.1:{server.server_port}"
        status, response, _ = enterprise_deploy._open(
            url + "/api/v1/cases/x/events?run=abc", "GET", {}
        )
        response.read()
    finally:
        server.shutdown()
        server.server_close()
    assert status == 200
    assert seen == ["/api/v1/cases/x/events?run=abc"]

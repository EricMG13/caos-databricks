"""`scripts/enterprise_deploy.sh` against the loopback workspace and the app
booted the platform way (D28, F31): the CLI on the path is a recorder, every
other step is the real one over HTTP, and the rows say what happened."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from urllib.parse import urlparse

import enterprise_deploy
import pytest
from enterprise_deploy import Evidence, Row
from platform_app import REPO, PlatformApp
from test_platform_boot import app, stub
from workspace_stub import BEARER, ENDPOINT, PRICE, WorkspaceStub

__all__ = ["app", "stub"]


def test_the_one_command_runs_the_cli_and_verifies_the_deployment(
    app: PlatformApp, stub: WorkspaceStub, empty_database: str, tmp_path: Path
) -> None:
    parts = urlparse(empty_database)
    stub.instance_host = parts.hostname or "127.0.0.1"
    stub.user_name = parts.username or "postgres"  # Lakebase mints for the caller
    # What a real `bundle deploy` creates the app with; the recorder CLI does
    # not. The dev target's app is `caos-dev` (DP-6).
    stub.apps.add("caos-dev")
    stub.app_bodies["caos-dev"] = {"forward_user_access_token": True}
    calls = tmp_path / "cli-calls.txt"
    shim = tmp_path / "bin"
    shim.mkdir()
    recorder = (
        "#!/usr/bin/env bash\n"
        f'printf "%s price=%s\\n" "$*" "$BUNDLE_VAR_model_price" >> "{calls}"\n'
    )
    (shim / "databricks").write_text(recorder + 'echo "Validation OK!"\n')
    (shim / "databricks").chmod(0o755)
    evidence = tmp_path / "enterprise"
    env = {
        **os.environ,
        **stub.environment(),
        "PATH": f"{shim}{os.pathsep}{os.environ['PATH']}",
        "EVIDENCE": str(evidence),
        "TARGET": "dev",
        "LAKEBASE_DATABASE": parts.path.lstrip("/"),
        "PG_PORT": str(parts.port),
        "PG_SSLMODE": "disable",
        "MLFLOW_DISABLE_AGENT_HINT": "1",
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
    assert [row[0] for row in rows] == [f"E{n}" for n in range(1, 10)]
    assert all(row[2] == "0" for row in rows), rows
    seen = calls.read_text().splitlines()
    assert [line.split(" -t ")[0] for line in seen] == [
        "bundle validate",
        "bundle deploy",
        "bundle run caos",
    ]
    assert all("--var run_ceiling=25.00" in line and "-p" not in line for line in seen)
    # The price travels whole in the environment (C1), never as a `--var`.
    assert all(f"price={PRICE}" in line and "model_price" not in line for line in seen)
    assert "answered 200 status=ready" in rows[5][3] and "workers=OK" in rows[5][3]
    assert "json_mode=accepted" in (evidence / "E7.log").read_text()
    assert "PostgreSQL" in (evidence / "E8.log").read_text()
    assert "first frame" in rows[-1][3]
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


def test_the_dev_target_s_app_is_not_the_production_app() -> None:
    """DP-6: one name for both targets let a developer's deploy take over the
    production app."""
    assert enterprise_deploy.app_name("prod") == "caos"
    assert enterprise_deploy.app_name("dev") == "caos-dev"


def test_the_stream_row_refuses_html_a_closed_stream_and_a_foreign_403(
    tmp_path: Path,
) -> None:
    """AR-05 and W1: an HTML page, a stream that closes after its first frame,
    and a 403 with any code but NOT_AUTHORISED are rows that say so."""
    import http.server
    import threading

    answers: list[tuple[int, dict[str, str], bytes, bool]] = []

    class _Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: object) -> None:
            del format, args

        def _answer(self) -> None:
            status, headers, body, close = answers.pop(0)
            self.send_response(status)
            for name, value in headers.items():
                self.send_header(name, value)
            if headers.get("Content-Type") != "text/event-stream":
                self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            self.wfile.flush()
            if not close:
                # An open stream: nothing more arrives, and nothing closes.
                threading.Event().wait(enterprise_deploy.LIVE_SECONDS + 1)

        do_GET = do_POST = _answer

    server = http.server.HTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{server.server_port}"
    case = json.dumps({"case_id": "c1"}).encode()
    try:
        with pytest.MonkeyPatch.context() as patched:
            patched.setattr(
                enterprise_deploy, "_headers", lambda: {"Authorization": "Bearer x"}
            )
            patched.setattr(enterprise_deploy, "STREAM_SECONDS", 5.0)
            patched.setattr(enterprise_deploy, "LIVE_SECONDS", 0.5)
            evidence = Evidence(tmp_path / "ev")
            answers[:] = [
                (201, {"Content-Type": "application/json"}, case, True),
                (
                    200,
                    {"Content-Type": "text/html"},
                    b"<html>not a stream</html>",
                    True,
                ),
            ]
            assert enterprise_deploy._stream(url, evidence) == 1
            assert "not an event stream" in evidence.rows[-1].summary
            answers[:] = [
                (201, {"Content-Type": "application/json"}, case, True),
                (200, {"Content-Type": "text/event-stream"}, b"id: 0.1\n\n", True),
            ]
            assert enterprise_deploy._stream(url, evidence) == 1
            assert "then the stream closed" in evidence.rows[-1].summary
            answers[:] = [
                (201, {"Content-Type": "application/json"}, case, True),
                (200, {"Content-Type": "text/event-stream"}, b"id: 0.1\n\n", False),
            ]
            assert enterprise_deploy._stream(url, evidence) == 0
            assert (
                "first frame 'id: 0.1' with the stream open"
                in evidence.rows[-1].summary
            )
            refused = json.dumps({"code": "ORIGIN_REFUSED"}).encode()
            answers[:] = [(403, {"Content-Type": "application/json"}, refused, True)]
            assert enterprise_deploy._stream(url, evidence) == 1
            assert "answered 403 ORIGIN_REFUSED" in evidence.rows[-1].summary
            unauthorised = json.dumps({"code": "NOT_AUTHORISED"}).encode()
            answers[:] = [
                (403, {"Content-Type": "application/json"}, unauthorised, True)
            ]
            assert enterprise_deploy._stream(url, evidence) == 0
            assert evidence.rows[-1].summary.startswith("unverified")
    finally:
        server.shutdown()
        server.server_close()

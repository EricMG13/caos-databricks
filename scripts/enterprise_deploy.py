#!/usr/bin/env python3
"""The verification half of `scripts/enterprise_deploy.sh` (F31).

The shell wrapper runs the three `databricks bundle` commands; this script
does everything that is not the CLI, in three stages, each recording rows
(id, command, exit, last line) in `<evidence>/evidence.tsv` with the output
in `<evidence>/<id>.log`:

    --stage before   E1 preflight: the resources exist, the ceiling covers a call
    --stage record   one CLI step the wrapper ran: E2 validate, E3 deploy, E4 run
    --stage after    E5 the app is RUNNING with a URL
                     E6 /api/health answers ready on Python 3.13
                     E7 the gateway smoke, JSON mode included (A31)
                     E8 Lakebase `SELECT version()` as the deployer, for D17
                        (the app's own access is E6's `store` code)
                     E9 the event stream delivers through the Apps proxy (C42)

No secret is printed or written: the bearer the app calls carry comes from
the SDK's unified auth (the profile) and lives only in request headers; the
Lakebase credential is minted by `caos.store.lakebase` and never leaves it.
"""

from __future__ import annotations

import argparse
import contextlib
import http.client
import io
import json
import os
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from uuid import uuid4

from openai import OpenAIError

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

APP = "caos"
STREAM_SECONDS = 20.0


@dataclass(frozen=True, slots=True)
class Row:
    id: str
    command: str
    code: int
    summary: str


class Evidence:
    """The rows and logs of one deployment, written as each step ends."""

    def __init__(self, directory: Path) -> None:
        self.directory = directory
        self.rows: list[Row] = []
        directory.mkdir(parents=True, exist_ok=True)

    def record(self, step: str, command: str, code: int, output: str) -> int:
        (self.directory / f"{step}.log").write_text(output)
        lines = [line for line in output.splitlines() if line.strip()]
        row = Row(step, command, code, (lines[-1] if lines else "")[:180])
        self.rows.append(row)
        with (self.directory / "evidence.tsv").open("a") as sink:
            sink.write(f"{row.id}\t{row.command}\t{row.code}\t{row.summary}\n")
        state = "ok" if code == 0 else f"exit {code}"
        print(f"{step} {state}: {row.summary}")
        return code


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--stage", choices=("before", "record", "after"), required=True)
    parser.add_argument("--evidence", required=True, help="directory for the rows")
    parser.add_argument("--profile", default="", help="CLI profile; empty = ambient")
    parser.add_argument("--catalog", default="")
    parser.add_argument("--schema", default="")
    parser.add_argument("--lakebase-instance", default="")
    parser.add_argument("--lakebase-database", default="databricks_postgres")
    parser.add_argument("--endpoint", default="databricks-claude-opus-5")
    parser.add_argument(
        "--price", default="databricks-claude-opus-5,0.000005,0.000025,2026-09-22"
    )
    parser.add_argument("--run-ceiling", default="25.00")
    parser.add_argument("--group-admin", default="caos-admins")
    parser.add_argument("--group-analyst", default="caos-analysts")
    parser.add_argument("--pg-port", default="5432", help="Lakebase listens on 5432")
    parser.add_argument("--pg-sslmode", default="require")
    parser.add_argument("--step", default="", help="record: the row id (E2, E3, E4)")
    parser.add_argument("--command", default="", help="record: the command run")
    parser.add_argument("--code", type=int, default=0, help="record: its exit code")
    parser.add_argument("--log", default="", help="record: the file holding its output")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.profile:
        os.environ["DATABRICKS_CONFIG_PROFILE"] = args.profile
    os.environ["CAOS_MODEL_ENDPOINT"] = args.endpoint
    os.environ["CAOS_MODEL_PRICE"] = args.price
    evidence = Evidence(Path(args.evidence))
    if args.stage == "before":
        return _preflight(args, evidence)
    if args.stage == "record":
        output = Path(args.log).read_text() if args.log else ""
        return evidence.record(args.step, args.command, args.code, output)
    url = _app_url(evidence)
    if not url:
        return 1
    later: list[Callable[[], int]] = [
        lambda: _health(url, evidence),
        lambda: _smoke(evidence),
        lambda: _lakebase_version(args, evidence),
        lambda: _stream(url, evidence),
    ]
    for step in later:
        if (code := step()) != 0:
            return code
    print(f"deployed: {url}")
    return 0


def _preflight(args: argparse.Namespace, evidence: Evidence) -> int:
    import preflight

    flags = [
        "--endpoint", args.endpoint, "--catalog", args.catalog,
        "--schema", args.schema, "--lakebase-instance", args.lakebase_instance,
        "--group-admin", args.group_admin, "--group-analyst", args.group_analyst,
        "--price", args.price, "--run-ceiling", args.run_ceiling,
    ]  # fmt: skip
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = preflight.main(flags)
    command = "scripts/preflight.py " + " ".join(flags)
    return evidence.record("E1", command, code, out.getvalue())


def _app_url(evidence: Evidence) -> str:
    from databricks.sdk import WorkspaceClient

    try:
        app = WorkspaceClient().apps.get(APP)
    except OSError:
        evidence.record("E5", f"apps get {APP}", 1, "the app cannot be read")
        return ""
    status = app.app_status
    state = status.state.value if status and status.state else ""
    url = app.url or ""
    # The forwarded-token flag is a preview feature the workspace must have
    # enabled; an app deployed without it names nobody (F53).
    forwarding = bool(getattr(app, "forward_user_access_token", False))
    code = 0 if state == "RUNNING" and url and forwarding else 1
    line = (
        f"state={state} url={'set' if url else 'missing'} "
        f"forward_user_access_token={forwarding}"
    )
    evidence.record("E5", f"apps get {APP}", code, line)
    return url if code == 0 else ""


def _open(
    target: str,
    method: str,
    headers: dict[str, str],
    *,
    body: bytes | None = None,
    timeout: float = 30.0,
) -> tuple[int, http.client.HTTPResponse]:
    """One request to the app over http.client; the caller reads the body.
    A redirect is answered as its status: the sign-in flow's 302 is a row
    that says 302, never a body parsed as JSON."""
    parts = urlsplit(target)
    connection: http.client.HTTPConnection
    if parts.scheme == "https":
        connection = http.client.HTTPSConnection(
            parts.hostname or "", parts.port, timeout=timeout
        )
    else:
        connection = http.client.HTTPConnection(
            parts.hostname or "", parts.port, timeout=timeout
        )
    connection.request(method, parts.path, body=body, headers=headers)
    response = connection.getresponse()
    return response.status, response


def _headers() -> dict[str, str]:
    """The SDK's own bearer for the app's URL; read here, printed nowhere."""
    from databricks.sdk import WorkspaceClient

    return dict(WorkspaceClient().config.authenticate())


def _health(url: str, evidence: Evidence) -> int:
    try:
        status, response = _open(url + "/api/health", "GET", _headers())
        raw = response.read()
        body: dict[str, Any] = json.loads(raw) if status < 300 else {}
    except (OSError, ValueError) as failed:
        return evidence.record("E6", "GET /api/health", 1, type(failed).__name__)
    if status >= 300:
        return evidence.record("E6", "GET /api/health", 1, f"answered {status}")
    ready = status == 200 and body.get("status") == "ready"
    version = str(body.get("python_version", ""))
    # Every code, the worker's included (F54): an app whose worker never
    # started answers `ready` and runs nothing.
    codes = {
        k: body.get(k) for k in ("store", "bundle", "blobs", "identity", "workers")
    }
    code = (
        0
        if ready and version.startswith("3.13") and set(codes.values()) == {"OK"}
        else 1
    )
    line = f"status={body.get('status')} python_version={version} " + " ".join(
        f"{k}={v}" for k, v in codes.items()
    )
    return evidence.record("E6", "GET /api/health", code, line)


def _smoke(evidence: Evidence) -> int:
    import gateway_smoke

    from caos.refusals import Refusal

    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
        try:
            code = gateway_smoke.main()
        except (OSError, ValueError, RuntimeError, Refusal, OpenAIError) as failed:
            # The class is the evidence; the text may quote the host.
            code, _ = 1, out.write(type(failed).__name__)
    return evidence.record("E7", "scripts/gateway_smoke.py", code, out.getvalue())


def _lakebase_version(args: argparse.Namespace, evidence: Evidence) -> int:
    import psycopg
    from databricks.sdk import WorkspaceClient

    from caos.store.lakebase import store_url

    client = WorkspaceClient()
    try:
        instance = client.database.get_database_instance(args.lakebase_instance)
        user = client.current_user.me().user_name or ""
    except OSError as failed:
        return evidence.record("E8", "SELECT version()", 1, type(failed).__name__)
    os.environ.update(
        PGHOST=instance.read_write_dns or "",
        PGPORT=args.pg_port,
        PGDATABASE=args.lakebase_database,
        PGUSER=user,
        PGSSLMODE=args.pg_sslmode,
        CAOS_LAKEBASE_INSTANCE=args.lakebase_instance,
    )
    os.environ.pop("CAOS_DATABASE_URL", None)
    try:
        with psycopg.connect(store_url(), connect_timeout=20) as conn:
            row = conn.execute("SELECT version()").fetchone()
    except (psycopg.Error, OSError) as failed:
        return evidence.record("E8", "SELECT version()", 1, type(failed).__name__)
    return evidence.record("E8", "SELECT version()", 0, str(row[0]) if row else "")


def _stream(url: str, evidence: Evidence) -> int:
    """A case, then its stream: the first frame (a heartbeat counts) within
    `STREAM_SECONDS` while the connection stays open means the proxy passes
    frames as they come (C42). A case the deployer may not create is
    recorded as unverified, not as a failure of the app."""
    step, path = "E9", "GET /api/v1/cases/<id>/events"
    headers = _headers()
    token = headers.get("Authorization", "").removeprefix("Bearer ")
    forwarded = {**headers, "x-forwarded-access-token": token, "origin": url}
    command = {
        **forwarded,
        "content-type": "application/json",
        "idempotency-key": str(uuid4()),
    }
    title = json.dumps({"title": "deployment stream check"}).encode()
    try:
        status, response = _open(url + "/api/v1/cases", "POST", command, body=title)
        created = json.loads(response.read())
    except (OSError, ValueError) as failed:
        return evidence.record(step, "POST /api/v1/cases", 1, type(failed).__name__)
    if status == 403:
        note = "unverified: creating a case answered 403; needs writer standing"
        return evidence.record(step, path, 0, note)
    if status != 201:
        # Any other answer is the app failing, not a standing question (F55).
        return evidence.record(step, "POST /api/v1/cases", 1, f"answered {status}")
    events = f"/api/v1/cases/{created['case_id']}/events"
    try:
        status, response = _open(url + events, "GET", forwarded, timeout=STREAM_SECONDS)
        first = response.readline().decode(errors="replace").rstrip("\n")
    except OSError as failed:
        note = f"no frame within {STREAM_SECONDS}s ({type(failed).__name__}), C42"
        return evidence.record(step, path, 1, note)
    if status != 200 or not first:
        return evidence.record(step, path, 1, f"status {status}, no frame before close")
    return evidence.record(step, path, 0, f"first frame {first!r} with the stream open")


if __name__ == "__main__":
    sys.exit(main())

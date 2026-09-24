#!/usr/bin/env python3
"""The verification half of `scripts/enterprise_deploy.sh` (F31).

The shell wrapper runs the three `databricks bundle` commands; this script
does everything that is not the CLI, in three stages, each recording rows
(id, command, exit, last line) in `<evidence>/evidence.tsv` with the output
in `<evidence>/<id>.log`:

    --stage before   E1 preflight: the resources exist, the ceiling covers a call
    --stage record   one CLI step the wrapper ran: E2 validate (its JSON form,
                        whose resolved app name, endpoint, price and run
                        ceiling must be the ones given: DF-4, DF-5), E3
                        deploy (its deployment record must list every file
                        the app reads: F48, DF-4), E4 run
    --stage after    E5 the app E2 resolved is RUNNING with a URL
                     E6 /api/health answers ready on Python 3.13, polled until
                        the first probe round and the worker have reported (C4)
                     E7 the gateway smoke, JSON mode included (A31)
                     E8 Lakebase `SELECT version()` as the deployer, for D17
                        (the app's own access is E6's `store` code), reached
                        through the kind the target binds: an Autoscaling
                        endpoint through the Postgres API by default, a
                        `-provisioned` target's instance through the
                        database API (R24-14)
                     E9 the event stream delivers through the Apps proxy (C42):
                        an event-stream content type, a first frame, then
                        frames for `LIVE_SECONDS` with no silence longer than
                        `FRAME_GAP_SECONDS` and no close (AR-05, DF-2, MAX-08)
                     E10 one model call through the app's own HTTP surface,
                        not this script's process or credentials (CF-054): a
                        tiny text source admitted (a blob write) to the case
                        E9 left behind, a LITE run started, and the event
                        stream watched for the first node's call outcome

Every step ends in a row, never a traceback (N1): a failure is its class or
its typed code. No secret is printed or written: the bearer the app calls
carry comes from the SDK's unified auth (the profile) and lives only in
request headers; the Lakebase credential is minted by `caos.store.lakebase`
and never leaves it. Behind the platform the proxy forwards the caller's own
token; only a stand-in run, which has no proxy, forwards the deployer's
(`CAOS_DEPLOY_FORWARD_CALLER=1`, W4).
"""

from __future__ import annotations

import argparse
import contextlib
import http.client
import io
import json
import os
import queue
import sys
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import urlsplit
from uuid import uuid4

import bundle_defaults
from check_gate_config import (
    LAKEBASE_BINDINGS,
    LAKEBASE_ENDPOINT,
    LAKEBASE_INSTANCE,
    PROVISIONED_SUFFIX,
)
from openai import OpenAIError

if TYPE_CHECKING:
    from databricks.sdk import WorkspaceClient
    from preflight import LakebasePaths

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

# The bundle's own defaults (N23): `databricks.yml` states each once, and
# this script reads them back rather than repeating them.
_DEFAULTS = bundle_defaults.defaults()

STREAM_SECONDS = 20.0
# After the first frame, how long frames must keep coming to count as a live
# stream, and the longest silence allowed while they do. The app beats every
# `caos.api.app.POLL_INTERVAL` (0.5 s), so three beats may go missing and a
# proxy that holds the stream after its first write, or cuts it, may not.
LIVE_SECONDS = 3.0
FRAME_GAP_SECONDS = 1.5
# How long E6 waits for the first probe round and the worker's first beat.
HEALTH_SECONDS = 90.0
HEALTH_POLL_SECONDS = 3.0
FORWARD_CALLER_ENV = "CAOS_DEPLOY_FORWARD_CALLER"
# What an event-stream frame's first line may start with.
SSE_PREFIXES = ("id:", "event:", "data:", "retry:", ":")
HEALTH_CODES = ("store", "bundle", "blobs", "identity", "workers")
# The app's key under `resources.apps` in databricks.yml.
APP_KEY = "caos"
# The targets that deploy the production app `caos`: one per Lakebase kind.
PRODUCTION_TARGETS = frozenset({"prod", "prod" + PROVISIONED_SUFFIX})
# The app's resource that binds Lakebase, in either kind's form.
DATABASE_RESOURCE = "database"
# How a wait for the next frame ends.
FRAME, CLOSED, SILENT = "frame", "closed", "silent"
# What a read of an answer can raise: the socket's errors, and http.client's
# own for a body shorter than it declared or a status line that is not one
# (MAX-17). Both are a row, never a traceback.
READ_FAILURES = (OSError, http.client.HTTPException)

# E9 and E10 share one case (N22): an operator who opens it sees this title,
# not a machine-generated id, and knows it is a deploy's own check, safe to
# keep or to have an admin archive (docs/DEPLOYMENT.md's operator notes).
DEPLOYMENT_CASE_TITLE = "CAOS deployment check (safe to archive)"
# CF-054: the smallest enabled route, so E10 spends and waits as little as
# a real model call can. `caos.methodology.handoff.ADAPTER_ROUTES` enables
# this pair in production, not only in tests.
MODEL_CALL_PROFILE = "LITE_CREDIT_22"
MODEL_CALL_SELECTION = "LITE_EARNINGS_UPDATE"
MODEL_CALL_GATES = ("source-set", "research-plan")
MODEL_CALL_SOURCE = b"Revenue grew 4% year over year to $12.4 million.\n"
MODEL_CALL_SUBJECT = {
    "issuer_id": "CAOS-DEPLOY-CHECK",
    "issuer_name": "CAOS Deployment Check",
    "reporting_period": "FY2025",
    "analysis_date": "2026-09-22",
}
# `caos.provider.TIMEOUT_SECONDS` (240) is the model call's own deadline;
# E10 waits comfortably past it rather than racing it.
MODEL_CALL_SECONDS = 260.0
# Two `run_progress` frames after `start` are `ATTEMPT_STARTED` then
# `CALL_OUTCOME_RECORDED` (`caos/api/events.py`): the second is the model
# call's outcome written to the ledger, whatever the outcome was.
CALL_OUTCOME_AT = 2


def resolved_app(document: object) -> tuple[str, dict[str, str]]:
    """The app's name and environment as `bundle validate -o json` resolved
    them, or `("", {})` when the document holds no app. E5 looks up this
    name rather than recomputing it, so a target added without its own name
    rule is found here, not after it deployed (DF-5)."""
    resources = document.get("resources") if isinstance(document, dict) else None
    apps = resources.get("apps") if isinstance(resources, dict) else None
    app = apps.get(APP_KEY) if isinstance(apps, dict) else None
    if not isinstance(app, dict):
        return "", {}
    config = app.get("config")
    listed = config.get("env") if isinstance(config, dict) else None
    items = listed if isinstance(listed, list) else []
    env = {
        str(item.get("name")): str(item.get("value"))
        for item in items
        if isinstance(item, dict)
    }
    name = app.get("name")
    return (name if isinstance(name, str) else ""), env


def resolved_form(document: object) -> str:
    """Which form the app's `database` resource resolved to -- `postgres`
    (Lakebase Autoscaling) or `database` (Provisioned) -- or `""`."""
    apps = _mapping(_mapping(document).get("resources")).get("apps")
    listed = _mapping(_mapping(apps).get(APP_KEY)).get("resources")
    for resource in listed if isinstance(listed, list) else []:
        named = _mapping(resource)
        if named.get("name") == DATABASE_RESOURCE:
            forms = [key for key in LAKEBASE_BINDINGS.values() if key in named]
            return forms[0] if len(forms) == 1 else ""
    return ""


def _mapping(value: object) -> dict[str, object]:
    """`value` when it is a JSON object, else an empty one."""
    return value if isinstance(value, dict) else {}


def resolution_problems(
    document: object, *, target: str, endpoint: str, price: str, run_ceiling: str
) -> list[str]:
    """What the CLI resolved that is not what was given (DF-4, DF-5): a
    misspelt `BUNDLE_VAR_model_price` validates on the default price, and a
    target with no name rule of its own resolves to the production app."""
    name, env = resolved_app(document)
    problems = [] if name else ["no app resolved"]
    if name == "caos" and target not in PRODUCTION_TARGETS:
        problems.append(f"target {target} resolves to the production app")
    given = {
        "CAOS_MODEL_ENDPOINT": endpoint,
        "CAOS_MODEL_PRICE": price,
        "CAOS_RUN_CEILING": run_ceiling,
    }
    problems += [
        f"resolved {key} is not the value given"
        for key, value in given.items()
        if env.get(key) != value
    ]
    return problems


def binding_problems(document: object, lakebase: tuple[str, str]) -> list[str]:
    """A Lakebase binding the CLI resolved that is not the one given
    (R24-14): `lakebase` is the variable the target's kind sets and its
    value. The other kind's variable, a value that is not the one given (a
    misspelt `BUNDLE_VAR_lakebase_branch` validates on the default branch)
    or a `database` resource of the other form would connect the app as
    some other role."""
    bound, value = lakebase
    _, env = resolved_app(document)
    problems = (
        [] if env.get(bound) == value else [f"resolved {bound} is not the value given"]
    )
    problems += [
        f"resolved app also binds {other}"
        for other in LAKEBASE_BINDINGS
        if other != bound and other in env
    ]
    form = LAKEBASE_BINDINGS[bound]
    if resolved_form(document) != form:
        problems.append(f"resolved database resource is not the {form} form")
    return problems


def lakebase_binding(args: argparse.Namespace) -> tuple[str, str]:
    """The variable the target's Lakebase binding sets, and the value given
    for it: an Autoscaling endpoint's resource path, or a `-provisioned`
    target's instance name."""
    if args.target.endswith(PROVISIONED_SUFFIX):
        return LAKEBASE_INSTANCE, args.lakebase_instance
    return LAKEBASE_ENDPOINT, _paths(args).endpoint


def _paths(args: argparse.Namespace) -> LakebasePaths:
    """The Autoscaling resource paths the given ids compose (preflight's)."""
    from preflight import autoscaling_paths

    return autoscaling_paths(
        args.lakebase_project,
        args.lakebase_branch,
        args.lakebase_endpoint,
        args.lakebase_database_id,
    )


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
    parser.add_argument("--target", default="prod", help="the bundle target")
    parser.add_argument("--catalog", default="")
    parser.add_argument("--schema", default="")
    # The target names the Lakebase kind (R24-14): these for the default,
    # Lakebase Autoscaling...
    parser.add_argument("--lakebase-project", default="")
    parser.add_argument("--lakebase-branch", default=_DEFAULTS["lakebase_branch"])
    parser.add_argument("--lakebase-endpoint", default=_DEFAULTS["lakebase_endpoint"])
    parser.add_argument(
        "--lakebase-database-id", default=_DEFAULTS["lakebase_database_id"]
    )
    # ...these for a `-provisioned` target's existing instance.
    parser.add_argument("--lakebase-instance", default="")
    parser.add_argument("--lakebase-database", default=_DEFAULTS["lakebase_database"])
    parser.add_argument("--endpoint", default=_DEFAULTS["model_endpoint"])
    parser.add_argument("--price", default=_DEFAULTS["model_price"])
    parser.add_argument("--run-ceiling", default=_DEFAULTS["run_ceiling"])
    parser.add_argument("--group-admin", default=_DEFAULTS["group_admin"])
    parser.add_argument("--group-analyst", default=_DEFAULTS["group_analyst"])
    parser.add_argument("--pg-port", default="5432", help="Lakebase listens on 5432")
    parser.add_argument("--pg-sslmode", default="require")
    parser.add_argument("--step", default="", help="record: the row id (E2, E3, E4)")
    parser.add_argument("--command", default="", help="record: the command run")
    parser.add_argument("--code", type=int, default=0, help="record: its exit code")
    parser.add_argument("--log", default="", help="record: the file holding its output")
    parser.add_argument(
        "--bundle", default="", help="`bundle validate -o json` output: E2, E5"
    )
    parser.add_argument("--shipped", default="", help="the CLI's deployment.json: E3")
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
        return _record(args, evidence)
    name, _ = resolved_app(_resolved(args.bundle))
    if not name:
        return evidence.record("E5", "apps get", 1, "no app name resolved by E2")
    url = _app_url(evidence, name)
    if not url:
        return 1
    later: list[Callable[[], int]] = [
        lambda: _health(url, evidence),
        lambda: _smoke(evidence),
        lambda: _lakebase_version(args, evidence),
    ]
    for step in later:
        if (code := step()) != 0:
            return code
    code, case_id = _stream(url, evidence)
    if code != 0:
        return code
    if (code := _model_call(url, case_id, evidence)) != 0:
        return code
    print(f"deployed: {url}")
    return 0


def _resolved(path: str) -> object:
    """The CLI's resolved configuration, or None when there is none to read."""
    try:
        return json.loads(Path(path).read_text()) if path else None
    except (OSError, ValueError):
        return None


def _record(args: argparse.Namespace, evidence: Evidence) -> int:
    """One CLI step's row. With `--bundle`, a validate that passed is also
    held to resolving the values given (DF-4, DF-5); with `--shipped`, a
    deploy that passed is also held to its own record listing every file
    the app reads (DF-4)."""
    output = Path(args.log).read_text() if args.log else ""
    code = args.code
    for given, check in ((args.bundle, _resolution), (args.shipped, _shipped)):
        if given and code == 0:
            code, line = check(args)
            output += line + "\n"
    return evidence.record(args.step, args.command, code, output)


def _resolution(args: argparse.Namespace) -> tuple[int, str]:
    document = _resolved(args.bundle)
    problems = resolution_problems(
        document,
        target=args.target,
        endpoint=args.endpoint,
        price=args.price,
        run_ceiling=args.run_ceiling,
    ) + binding_problems(document, lakebase_binding(args))
    name, _ = resolved_app(document)
    if problems:
        return 1, "; ".join(problems)
    return 0, f"resolved app {name}: endpoint, price, run ceiling and Lakebase as given"


def _shipped(args: argparse.Namespace) -> tuple[int, str]:
    """What the deploy synced, against every tracked file under the sync
    roots and every file of the built export: an export reduced to its page
    serves a blank workspace while health, E6 and E9 stay green."""
    from check_gate_config import shipped_problems

    try:
        problems = shipped_problems(Path(args.shipped))
    except (RuntimeError, OSError) as failed:
        return (
            1,
            f"shipped: the tracked files could not be listed ({type(failed).__name__})",
        )
    if problems:
        return 1, "\n".join(problems)
    return 0, "every path the app needs was synced"


def _preflight(args: argparse.Namespace, evidence: Evidence) -> int:
    import preflight

    flags = [
        "--endpoint", args.endpoint, "--catalog", args.catalog,
        "--schema", args.schema, *_lakebase_flags(args),
        "--group-admin", args.group_admin, "--group-analyst", args.group_analyst,
        "--price", args.price, "--run-ceiling", args.run_ceiling,
    ]  # fmt: skip
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = preflight.main(flags)
    command = "scripts/preflight.py " + " ".join(flags)
    return evidence.record("E1", command, code, out.getvalue())


def _lakebase_flags(args: argparse.Namespace) -> list[str]:
    """Preflight's Lakebase flags for the kind the target binds."""
    if args.target.endswith(PROVISIONED_SUFFIX):
        return ["--lakebase-instance", args.lakebase_instance]
    return [
        "--lakebase-project", args.lakebase_project,
        "--lakebase-branch", args.lakebase_branch,
        "--lakebase-endpoint", args.lakebase_endpoint,
        "--lakebase-database-id", args.lakebase_database_id,
    ]  # fmt: skip


def _app_url(evidence: Evidence, name: str) -> str:
    from databricks.sdk import WorkspaceClient

    try:
        app = WorkspaceClient().apps.get(name)
    except (OSError, ValueError) as failed:
        # `ValueError` is the SDK's shape for auth that does not resolve.
        evidence.record("E5", f"apps get {name}", 1, type(failed).__name__)
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
    evidence.record("E5", f"apps get {name}", code, line)
    return url if code == 0 else ""


def _open(
    target: str,
    method: str,
    headers: dict[str, str],
    *,
    body: bytes | None = None,
    timeout: float = 30.0,
) -> tuple[int, http.client.HTTPResponse, http.client.HTTPConnection]:
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
    # `urlsplit` separates the query from the path; a caller's `?run=<id>`
    # (CF-054's own events read) reached the app as no query at all without
    # this, silently answering the case's stream, not the run's.
    request_target = parts.path + (f"?{parts.query}" if parts.query else "")
    connection.request(method, request_target, body=body, headers=headers)
    response = connection.getresponse()
    return response.status, response, connection


def _headers() -> dict[str, str]:
    """The SDK's own bearer for the app's URL; read here, printed nowhere."""
    from databricks.sdk import WorkspaceClient

    return dict(WorkspaceClient().config.authenticate())


def _document(raw: bytes) -> dict[str, Any]:
    """The body as a JSON object, or nothing: an HTML error page is not a document."""
    try:
        parsed = json.loads(raw)
    except ValueError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _health(url: str, evidence: Evidence) -> int:
    """Polled until ready or the deadline (C4): the lifespan yields before the
    first probe round, and `workers` needs the worker's first beat. Every
    answer's codes are recorded, a 503's included, so the row names the
    dependency that failed instead of only the status."""
    deadline = time.monotonic() + HEALTH_SECONDS
    while True:
        code, line = _health_once(url)
        if code == 0 or time.monotonic() >= deadline:
            return evidence.record("E6", "GET /api/health", code, line)
        time.sleep(HEALTH_POLL_SECONDS)


def _health_once(url: str) -> tuple[int, str]:
    try:
        status, response, _ = _open(url + "/api/health", "GET", _headers())
        body = _document(response.read())
    except (*READ_FAILURES, ValueError) as failed:
        return 1, type(failed).__name__
    ready = status == 200 and body.get("status") == "ready"
    version = str(body.get("python_version", ""))
    # Every code, the worker's included (F54): an app whose worker never
    # started answers `ready` and runs nothing.
    codes = {k: body.get(k) for k in HEALTH_CODES}
    code = (
        0
        if ready and version.startswith("3.13") and set(codes.values()) == {"OK"}
        else 1
    )
    line = (
        f"answered {status} status={body.get('status')} python_version={version} "
        + " ".join(f"{k}={v}" for k, v in codes.items())
    )
    return code, line


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

    from caos.refusals import Refusal
    from caos.store.lakebase import store_url

    step, command = "E8", "SELECT version()"
    try:
        environment = _lakebase_environment(args, WorkspaceClient())
    except (OSError, ValueError) as failed:
        return evidence.record(step, command, 1, type(failed).__name__)
    # Exactly the one Lakebase the target binds, the way the app is given it.
    for name in (*LAKEBASE_BINDINGS, "CAOS_DATABASE_URL"):
        os.environ.pop(name, None)
    os.environ.update(environment)
    try:
        with psycopg.connect(store_url(), connect_timeout=20) as conn:
            row = conn.execute(command).fetchone()
    except Refusal as refused:
        # A Lakebase with no read-write host, or a credential the deployer
        # cannot mint, is its typed code (N1).
        return evidence.record(step, command, 1, refused.code.value)
    except (psycopg.Error, OSError) as failed:
        return evidence.record(step, command, 1, type(failed).__name__)
    return evidence.record(step, command, 0, str(row[0]) if row else "")


def _lakebase_environment(
    args: argparse.Namespace, client: WorkspaceClient
) -> dict[str, str]:
    """The `PG*` values and the one Lakebase variable E8 connects with, read
    as the deployer through the API of the kind the target binds."""
    bound, value = lakebase_binding(args)
    user = client.current_user.me().user_name or ""
    if bound == LAKEBASE_INSTANCE:
        instance = client.database.get_database_instance(value)
        host, database = instance.read_write_dns, args.lakebase_database
    else:
        host, database = _autoscaling_host(args, client)
    return {
        "PGHOST": host or "",
        "PGPORT": args.pg_port,
        "PGDATABASE": database or "",
        "PGUSER": user,
        "PGSSLMODE": args.pg_sslmode,
        bound: value,
    }


def _autoscaling_host(
    args: argparse.Namespace, client: WorkspaceClient
) -> tuple[str, str]:
    """The endpoint's host and the database's Postgres name, from the
    Postgres API: the bundle binds the database by resource id, which is not
    always the name Postgres knows it by."""
    paths = _paths(args)
    status = client.postgres.get_endpoint(paths.endpoint).status
    hosts = getattr(status, "hosts", None)
    found = getattr(client.postgres.get_database(paths.database), "status", None)
    return (
        str(getattr(hosts, "host", None) or ""),
        str(getattr(found, "postgres_database", None) or ""),
    )


def _forwarded(url: str, headers: dict[str, str]) -> dict[str, str]:
    """The caller's own headers, plus a command's origin and, only where
    there is no proxy to do it, the caller's bearer forwarded as the
    platform would forward it (W4)."""
    forwarded = {**headers, "origin": url}
    if os.environ.get(FORWARD_CALLER_ENV) == "1":
        token = headers.get("Authorization", "").removeprefix("Bearer ")
        forwarded["x-forwarded-access-token"] = token
    return forwarded


def _stream(url: str, evidence: Evidence) -> tuple[int, str]:
    """A case, then its stream: an event-stream content type, a first frame
    within `STREAM_SECONDS`, then frames (heartbeats count) for
    `LIVE_SECONDS`, none more than `FRAME_GAP_SECONDS` apart, mean the proxy
    passes frames as they come (C42, AR-05, DF-2). A case the deployer may
    not create is recorded as unverified, and only for the one code that
    says so (W1). Its exit code, and the case's id for E10 to reuse (N22),
    empty when there is none to reuse."""
    step, path = "E9", "GET /api/v1/cases/<id>/events"
    try:
        headers = _headers()
    except ValueError as failed:
        return evidence.record(step, path, 1, type(failed).__name__), ""
    forwarded = _forwarded(url, headers)
    command = {
        **forwarded,
        "content-type": "application/json",
        "idempotency-key": str(uuid4()),
    }
    title = json.dumps({"title": DEPLOYMENT_CASE_TITLE}).encode()
    try:
        status, response, _ = _open(url + "/api/v1/cases", "POST", command, body=title)
        created = _document(response.read())
    except READ_FAILURES as failed:
        return evidence.record(step, "POST /api/v1/cases", 1, type(failed).__name__), ""
    if status == 403:
        code = str(created.get("code", "")) or "no code"
        if code == "NOT_AUTHORISED":
            note = "unverified: creating a case answered 403 NOT_AUTHORISED; "
            return evidence.record(step, path, 0, note + "needs writer standing"), ""
        summary = f"answered 403 {code}"
        return evidence.record(step, "POST /api/v1/cases", 1, summary), ""
    case_id = created.get("case_id")
    if status != 201 or not isinstance(case_id, str):
        # Any other answer is the app failing, not a standing question (F55).
        return evidence.record(step, "POST /api/v1/cases", 1, f"answered {status}"), ""
    events = f"/api/v1/cases/{case_id}/events"
    try:
        status, response, _ = _open(
            url + events, "GET", forwarded, timeout=STREAM_SECONDS
        )
    except READ_FAILURES as failed:
        note = f"no answer within {STREAM_SECONDS}s ({type(failed).__name__}), C42"
        return evidence.record(step, path, 1, note), ""
    kind = response.getheader("content-type") or ""
    exit_code = evidence.record(step, path, *_streamed(status, kind, response))
    return exit_code, (case_id if exit_code == 0 else "")


def _streamed(
    status: int, kind: str, response: http.client.HTTPResponse
) -> tuple[int, str]:
    """The E9 verdict on what came back: an event stream, a first frame, then
    frames that keep coming with the stream open."""
    if status != 200 or not kind.startswith("text/event-stream"):
        return 1, f"status {status}, content-type {kind!r}: not an event stream"
    lines = _lines(response)
    ended, frame = _next_frame(lines, time.monotonic() + STREAM_SECONDS)
    if ended == SILENT:
        return 1, f"status 200, no frame within {STREAM_SECONDS}s, C42"
    if ended == CLOSED or not frame.startswith(SSE_PREFIXES):
        return 1, "status 200, no event frame before close"
    broken = _held_open(lines)
    if broken:
        return 1, f"first frame {frame!r}, then {broken}: buffered or cut, C42"
    return 0, (
        f"first frame {frame!r}, then frames for {LIVE_SECONDS}s with the stream open"
    )


def _lines(response: http.client.HTTPResponse) -> queue.Queue[bytes]:
    """The stream's lines as they arrive, read on a thread of their own, then
    `b""` once it ends or a read fails. The waits below are the queue's: a
    socket timeout would not do, because `http.client` hands a `Connection:
    close` response its socket and forgets it, so there is none left to set;
    the connection's own timeout still bounds each read."""
    lines: queue.Queue[bytes] = queue.Queue()

    def read() -> None:
        with contextlib.suppress(*READ_FAILURES):
            while raw := response.readline():
                lines.put(raw)
        lines.put(b"")

    threading.Thread(target=read, name="caos-deploy-stream", daemon=True).start()
    return lines


def _next_frame(lines: queue.Queue[bytes], until: float) -> tuple[str, str]:
    """`(FRAME, its lines)` once a blank line ends a frame before `until` (a
    monotonic instant), else `(CLOSED, ...)` or `(SILENT, ...)`."""
    got: list[str] = []
    while True:
        try:
            raw = lines.get(timeout=max(until - time.monotonic(), 0.0))
        except queue.Empty:
            return SILENT, "\n".join(got)
        if raw == b"":
            return CLOSED, "\n".join(got)
        line = raw.decode(errors="replace").rstrip("\r\n")
        if not line:
            return FRAME, "\n".join(got)  # a blank line ends the frame
        got.append(line)


def _held_open(lines: queue.Queue[bytes]) -> str:
    """Empty when frames kept coming for `LIVE_SECONDS`, none more than
    `FRAME_GAP_SECONDS` apart; else what happened instead. A read that is
    merely still blocked proves nothing: frames already buffered before a
    close, or a first write forwarded and the rest held, are not a stream
    (DF-2, MAX-08)."""
    end = time.monotonic() + LIVE_SECONDS
    while (now := time.monotonic()) < end:
        ended, _ = _next_frame(lines, min(end, now + FRAME_GAP_SECONDS))
        if ended == CLOSED:
            return "the stream closed"
        if ended == SILENT and time.monotonic() < end:
            return f"no frame for {FRAME_GAP_SECONDS}s"
    return ""


def _json_call(
    url: str,
    method: str,
    path: str,
    headers: dict[str, str],
    body: dict[str, Any] | None = None,
) -> tuple[int, dict[str, Any]]:
    """One command or read against the app: a command carries its own
    idempotency key, every call its content type, the answer parsed as a
    document whatever it was."""
    sent = dict(headers)
    data = None
    if body is not None:
        sent["content-type"] = "application/json"
        sent["idempotency-key"] = str(uuid4())
        data = json.dumps(body).encode()
    status, response, _ = _open(url + path, method, sent, body=data)
    return status, _document(response.read())


def _admitted(
    url: str, case_id: str, headers: dict[str, str]
) -> tuple[int, dict[str, Any]]:
    """A tiny text source admitted the way a caller's own upload is: a blob
    write through the app's own multipart parsing (CF-054), not a shortcut
    around it."""
    boundary = "caos-deploy-" + uuid4().hex
    disposition = 'form-data; name="document"; filename="deployment-check.txt"'
    body = (
        f"--{boundary}\r\nContent-Disposition: {disposition}\r\n"
        "Content-Type: text/plain\r\n\r\n"
    ).encode()
    body += MODEL_CALL_SOURCE + f"\r\n--{boundary}--\r\n".encode()
    sent = {
        **headers,
        "content-type": f"multipart/form-data; boundary={boundary}",
        "idempotency-key": str(uuid4()),
    }
    status, response, _ = _open(
        url + f"/api/v1/cases/{case_id}/sources", "POST", sent, body=body
    )
    return status, _document(response.read())


@dataclass(frozen=True, slots=True)
class _Prepared:
    """Everything `start` needs, or the first answer that was not one
    (`ok` false): the step it happened at, the status, the run id once
    created and the pinned input's fingerprint once pinned."""

    ok: bool
    step: str
    status: int
    run_id: str = ""
    fingerprint: str = ""


def _prepared_run(url: str, case_id: str, headers: dict[str, str]) -> _Prepared:
    """A tiny source admitted, a run created against it, its input pinned
    and both gates approved -- everything short of starting it."""
    status, _ = _admitted(url, case_id, headers)
    if status != 201:
        return _Prepared(False, "POST .../sources", status)
    selection = {
        "profile_id": MODEL_CALL_PROFILE,
        "selection_id": MODEL_CALL_SELECTION,
        "supersedes": None,
        "model_extension": False,
    }
    status, run = _json_call(
        url, "POST", f"/api/v1/cases/{case_id}/runs", headers, selection
    )
    if status != 201:
        return _Prepared(False, "POST .../runs", status)
    run_id = str(run.get("run_id", ""))
    base = f"/api/v1/cases/{case_id}/runs/{run_id}"
    status, pinned = _json_call(
        url,
        "POST",
        f"{base}/input",
        headers,
        {"subject": MODEL_CALL_SUBJECT, "research": None},
    )
    if status not in (200, 201):
        return _Prepared(False, "POST .../input", status, run_id)
    for gate in MODEL_CALL_GATES:
        status = _gate_approved(url, base, gate, headers)
        if status not in (200, 201):
            return _Prepared(False, f"POST .../gates/{gate}/approval", status, run_id)
    fingerprint = str(pinned.get("input_fingerprint", ""))
    return _Prepared(True, "", status, run_id, fingerprint)


def _gate_approved(url: str, base: str, gate: str, headers: dict[str, str]) -> int:
    """One gate released: the preview re-read, then approved over its own
    digests, as an approver's browser would (no state carried between)."""
    status, preview = _json_call(url, "GET", f"{base}/gates/{gate}/preview", headers)
    if status != 200:
        return status
    approval = {
        "preview_sha256": preview.get("preview_sha256"),
        "input_fingerprint": preview.get("input_fingerprint"),
    }
    status, _ = _json_call(
        url, "POST", f"{base}/gates/{gate}/approval", headers, approval
    )
    return status


def _progress_events(lines: queue.Queue[bytes], seconds: float) -> int:
    """How many `run_progress` frames arrived before a terminal frame, a
    close or the deadline. Two mean the first node's attempt started and its
    call outcome was recorded (`caos.store.outcomes.record_outcome`) --
    proof of one model call, whatever the call answered (CF-054)."""
    seen = 0
    until = time.monotonic() + seconds
    while seen < CALL_OUTCOME_AT:
        ended, frame = _next_frame(lines, until)
        if ended != FRAME:
            return seen
        if "event: run_progress" in frame:
            seen += 1
        elif "event: run_terminal" in frame:
            return seen  # ended early, but not before a call was recorded
    return seen


def _started_and_watched(
    url: str,
    case_id: str,
    prepared: _Prepared,
    headers: dict[str, str],
    evidence: Evidence,
) -> int:
    """The stream opened before `start` so no early frame is missed, the run
    started, then watched for the first node's call outcome."""
    step = "E10"
    run_id = prepared.run_id
    events = f"/api/v1/cases/{case_id}/events?run={run_id}"
    try:
        status, response, _ = _open(
            url + events, "GET", headers, timeout=MODEL_CALL_SECONDS
        )
        kind = response.getheader("content-type") or ""
        if status != 200 or not kind.startswith("text/event-stream"):
            note = f"status {status}, content-type {kind!r}: not an event stream"
            return evidence.record(step, f"GET {events}", 1, note)
        lines = _lines(response)
        base = f"/api/v1/cases/{case_id}/runs/{run_id}"
        pin = {"input_fingerprint": prepared.fingerprint}
        status, _ = _json_call(url, "POST", f"{base}/start", headers, pin)
        if status != 202:
            return evidence.record(step, f"POST {base}/start", 1, f"answered {status}")
        seen = _progress_events(lines, MODEL_CALL_SECONDS)
    except READ_FAILURES as failed:
        return evidence.record(step, f"GET {events}", 1, type(failed).__name__)
    if seen < CALL_OUTCOME_AT:
        note = f"no model call recorded within {MODEL_CALL_SECONDS}s"
        return evidence.record(step, f"GET {events}", 1, note)
    note = "one model call recorded through the app's own HTTP surface"
    return evidence.record(step, f"GET {events}", 0, note)


def _model_call(url: str, case_id: str, evidence: Evidence) -> int:
    """One model call driven entirely through the deployed app's own HTTP
    surface, never this script's own process or credentials (CF-054): admit
    a tiny text source (a blob write), start the smallest enabled route, and
    watch the event stream for the first node's call outcome. Reuses the
    case E9 leaves behind (N22, `DEPLOYMENT_CASE_TITLE`); a case the
    deployer could not create was already reported there, and there is
    nothing here to admit a source to."""
    step, path = "E10", "POST .../sources"
    if not case_id:
        return evidence.record(step, path, 0, "unverified: needs writer standing")
    try:
        headers = _forwarded(url, _headers())
        prepared = _prepared_run(url, case_id, headers)
    except (ValueError, *READ_FAILURES) as failed:
        return evidence.record(step, path, 1, type(failed).__name__)
    if not prepared.ok:
        return evidence.record(step, prepared.step, 1, f"answered {prepared.status}")
    return _started_and_watched(url, case_id, prepared, headers, evidence)


if __name__ == "__main__":
    sys.exit(main())

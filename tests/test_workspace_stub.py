"""The production seams against the loopback workspace (D28): nothing below
HTTP is injected, so what passes here is the SDK, the wire shapes and this
repository's code. What a real workspace grants stays with the deployer."""

from __future__ import annotations

import base64
import json
import os
import sys
from collections.abc import Iterator
from pathlib import Path
from urllib.parse import urlparse
from uuid import UUID

import anyio
import gateway_smoke
import preflight
import pytest
from conftest import priced
from langgraph.checkpoint.postgres import PostgresSaver
from openai import NotFoundError
from test_loop_charges import ESTIMATE, _Completions, ready, route
from workspace_stub import BEARER, ENDPOINT, WorkspaceStub, fresh_state, main

from caos.api import edge, identity
from caos.api.identity import GlobalRole, actor_from_token
from caos.blobs import BlobStore
from caos.graph.build import thread_config
from caos.graph.checkpoint import (
    SCHEMA,
    MintedConnection,
    checkpointer,
    close_checkpointer,
)
from caos.graph.route import ResolvedRoute
from caos.graph.runtime import Execution, run_route
from caos.methodology.bundle import Bundle
from caos.methodology.runner import ModuleProvider
from caos.models import completions
from caos.refusals import Refusal
from caos.store import RunStatus, StoreConnection
from caos.store.runs import run_status
from caos.workspace import workspace_client

__all__ = ["ready", "route"]

CHAT = "/serving-endpoints/chat/completions"
VENDORED = Path(__file__).resolve().parents[1] / "vendor/deploy-v"


@pytest.fixture
def stub(monkeypatch: pytest.MonkeyPatch) -> Iterator[WorkspaceStub]:
    """A served stub, and the environment that points the SDK at it."""
    with WorkspaceStub().serving() as served:
        for name, value in served.environment().items():
            monkeypatch.setenv(name, value)
        monkeypatch.delenv("DATABRICKS_CONFIG_PROFILE", raising=False)
        yield served


def test_the_gateway_smoke_passes_over_http_with_chat_databricks(
    stub: WorkspaceStub, capsys: pytest.CaptureFixture[str]
) -> None:
    assert gateway_smoke.main() == 0
    out = capsys.readouterr().out
    assert f"endpoint={ENDPOINT} model=ChatDatabricks" in out
    assert "input_tokens=" in out and "charge=" in out
    assert out.rstrip().endswith("json_mode=accepted")
    assert stub.json_completions == 1
    assert [p for m, p in stub.requests if m == "POST"] == [CHAT, CHAT]
    assert BEARER not in json.dumps(stub.requests)


def test_the_smoke_refuses_an_endpoint_the_workspace_does_not_serve(
    stub: WorkspaceStub, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CAOS_MODEL_ENDPOINT", "not-served")
    monkeypatch.setenv("CAOS_MODEL_PRICE", "not-served,0.000005,0.000025,2026-09-22")
    # The smoke's first call is the raw chat model, so the workspace's own
    # answer surfaces; the priced seam behind it maps this to a refusal.
    with pytest.raises(NotFoundError):
        gateway_smoke.main()


def test_preflight_names_each_resource_and_the_fix_for_a_missing_one(
    stub: WorkspaceStub, capsys: pytest.CaptureFixture[str]
) -> None:
    flags = ["--endpoint", ENDPOINT, "--catalog", "main", "--schema", "caos"]
    assert preflight.main([*flags, "--lakebase-instance", "caos-lb"]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert len(lines) == 6 and all(line.startswith("ok") for line in lines)

    assert preflight.main([*flags, "--lakebase-instance", "absent"]) == 1
    out = capsys.readouterr().out
    assert "MISSING lakebase instance absent: create a Lakebase instance" in out
    assert out.count("ok ") == 5
    assert stub.host not in out


def test_the_documented_preflight_command_runs_as_its_own_process(
    stub: WorkspaceStub,
) -> None:
    """MAX-07: `uv run python scripts/preflight.py ... --price ...`, as the
    runbook gives it, with no PYTHONPATH: the price check imports `caos`, and
    a script run by path has only its own directory on the import path."""
    import subprocess

    repo = Path(__file__).resolve().parents[1]
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    flags = ["--endpoint", ENDPOINT, "--catalog", "main", "--schema", "caos"]
    flags += ["--lakebase-instance", "caos-lb", "--run-ceiling", "25.00"]
    price = f"{ENDPOINT},0.000005,0.000025,2026-09-22"
    done = subprocess.run(
        [
            sys.executable,
            str(repo / "scripts" / "preflight.py"),
            *flags,
            "--price",
            price,
        ],
        cwd=repo / "docs",  # not the root: nothing may rest on the working directory
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert done.returncode == 0, done.stdout + done.stderr
    assert done.stdout.startswith("ok      run ceiling 25.00 covers a worst-case call")


def test_preflight_names_a_profile_nobody_logged_in_as(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    for name in ("DATABRICKS_HOST", "DATABRICKS_TOKEN"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("DATABRICKS_CONFIG_PROFILE", "no-such-profile")
    flags = ["--endpoint", ENDPOINT, "--catalog", "c", "--schema", "s"]
    assert preflight.main([*flags, "--lakebase-instance", "i"]) == 1
    out = capsys.readouterr().out
    assert out.startswith("MISSING workspace credentials for profile no-such-profile")
    assert "databricks auth login" in out and "no-such-profile" in out


def test_the_forwarded_token_resolves_through_scim_over_http(
    stub: WorkspaceStub, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(edge.PLATFORM_ENV, "caos")
    monkeypatch.setenv(identity.WORKSPACE_ENV, "1234")
    monkeypatch.setattr(identity, "_CACHE", {})
    monkeypatch.setattr(identity, "_NEGATIVE", {})
    actor = anyio.run(actor_from_token, "a-forwarded-token")
    assert actor.role is GlobalRole.ADMIN
    assert isinstance(actor.user_id, UUID)
    assert ("GET", "/api/2.0/preview/scim/v2/Me") in stub.requests
    assert "a-forwarded-token" not in json.dumps(stub.requests)

    stub.groups = frozenset({"caos-analysts"})
    monkeypatch.setattr(identity, "_CACHE", {})
    monkeypatch.setattr(identity, "_NEGATIVE", {})
    assert anyio.run(actor_from_token, "another").role is GlobalRole.ANALYST
    # A token the workspace refuses is remembered briefly (F43): one round
    # trip, not one per request.
    stub.identities["refused"] = ("", frozenset())
    asked = len(stub.requests)
    for _ in range(3):
        with pytest.raises(Refusal, match=r"^NOT_AUTHENTICATED$"):
            anyio.run(actor_from_token, "refused")
    assert len(stub.requests) == asked + 1
    # The cache is bounded: past its capacity nothing more is remembered.
    monkeypatch.setattr(identity, "CACHE_CAPACITY", 1)
    monkeypatch.setattr(identity, "_CACHE", {})
    anyio.run(actor_from_token, "first")
    anyio.run(actor_from_token, "second")
    assert len(identity._CACHE) == 1


def test_the_volume_backend_round_trips_bytes_through_the_files_api(
    stub: WorkspaceStub,
) -> None:
    store = BlobStore.from_setting("volume:///Volumes/main/caos/caos_blobs")
    with pytest.raises(Refusal, match=r"^STORE_UNAVAILABLE$"):
        store.probe()  # nothing under the volume yet
    stub.directories.add("/Volumes/main/caos/caos_blobs")
    store.probe()

    digest = store.put(b"source bytes")
    assert store.get(digest) == b"source bytes"
    [(name, data)] = stub.files.items()
    assert name == f"/Volumes/main/caos/caos_blobs/{digest[:2]}/{digest}"
    assert data == b"source bytes"
    methods = {m for m, p in stub.requests if p.startswith("/api/2.0/fs/")}
    # CF-095: no presigned-URL negotiation (that mode's own POST) -- the
    # plain Files API path only ever GETs, PUTs and HEADs.
    assert methods == {"HEAD", "PUT", "GET"}
    with pytest.raises(Refusal, match=r"^BLOB_NOT_FOUND$"):
        store.get("0" * 64)


def test_a_lite_route_completes_through_chat_databricks_over_http(
    stub: WorkspaceStub,
    ready: tuple[StoreConnection, UUID, UUID, BlobStore],
    route: ResolvedRoute,
) -> None:
    conn, run_id, source, blobs = ready
    answers = _Completions(source)

    def reply(prompt: str, json_object: bool) -> str:
        return answers.complete(prompt, json_object=json_object).content or ""

    stub.reply = reply
    price = priced(ESTIMATE, ENDPOINT)
    provider = completions(price, endpoint=ENDPOINT)
    assert type(provider.chat).__name__ == "ChatDatabricks"
    bundle = Bundle(VENDORED)
    modules = ModuleProvider(conn, bundle, blobs, provider, route, run_id)
    run_route(
        conn,
        blobs,
        run_id=run_id,
        route=route,
        execution=Execution(modules, price, bundle),
    )
    assert run_status(conn, run_id) is RunStatus.COMPLETE
    conn.rollback()
    assert stub.completions == stub.json_completions == len(route.nodes)
    assert all(p == CHAT for m, p in stub.requests if m == "POST")


def test_main_runs_a_command_against_the_stub_and_lists_what_it_asked(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("DATABRICKS_CONFIG_PROFILE", "would-shadow-the-stub")
    child = (
        "import os, sys, urllib.request, urllib.error\n"
        "assert 'DATABRICKS_CONFIG_PROFILE' not in os.environ\n"
        "try:\n"
        "    urllib.request.urlopen(os.environ['DATABRICKS_HOST'] + '/.well-known/x')\n"
        "except urllib.error.HTTPError as failed:\n"
        "    sys.exit(0 if failed.code == 404 else 3)\n"
    )
    assert main(["--", sys.executable, "-c", child]) == 0
    assert "stub: GET /.well-known/x\n" in capsys.readouterr().out
    assert main([]) == 2
    assert "DATABRICKS_HOST" not in os.environ


def test_the_lakebase_checkpointer_mints_each_connection_over_the_platform_values(
    stub: WorkspaceStub, empty_database: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    parts = urlparse(empty_database)
    stub.database_credential = parts.password or ""
    monkeypatch.delenv("CAOS_DATABASE_URL", raising=False)
    monkeypatch.setenv("CAOS_LAKEBASE_INSTANCE", "caos-lb")
    monkeypatch.setenv("PGHOST", parts.hostname or "127.0.0.1")
    monkeypatch.setenv("PGPORT", str(parts.port))
    monkeypatch.setenv("PGDATABASE", parts.path.lstrip("/"))
    monkeypatch.setenv("PGUSER", parts.username or "postgres")
    monkeypatch.setenv("PGSSLMODE", "disable")
    saver = checkpointer()
    assert saver.get(thread_config("nobody")) is None
    assert ("POST", "/api/2.0/database/credentials") in stub.requests
    with MintedConnection.connect(autocommit=True) as conn:
        [(schema,)] = conn.execute(
            "SELECT schema_name FROM information_schema.schemata"
            " WHERE schema_name = %s",
            (SCHEMA,),
        ).fetchall()
    assert schema == SCHEMA
    close_checkpointer(saver)
    assert isinstance(saver, PostgresSaver) and saver.conn.closed, "pool released"


def test_the_bounded_workspace_client_reaches_the_stub_with_its_budgets(
    stub: WorkspaceStub,
) -> None:
    from caos.workspace import HTTP_TIMEOUT_SECONDS, RETRY_TIMEOUT_SECONDS

    stub.apps.add("caos")
    client = workspace_client()
    assert client.config.http_timeout_seconds == HTTP_TIMEOUT_SECONDS
    assert client.config.retry_timeout_seconds == RETRY_TIMEOUT_SECONDS
    # CF-095: the presigned-URL download mode is never taken; the plain
    # Files API path `caos.blobs` covers stays the one in force.
    assert client.config.disable_experimental_files_api_client is True
    assert client.apps.get("caos").name == "caos"


def test_a_client_the_sdk_refuses_to_build_is_store_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """N68: a construction the SDK itself refuses -- unresolved credentials, a
    host that will not parse -- is the typed `STORE_UNAVAILABLE` (CR-1),
    never the SDK's own `ValueError` reaching a caller."""
    from caos.workspace import forget_clients, workspace_client

    monkeypatch.delenv("DATABRICKS_HOST", raising=False)

    def broken(*args: object, **kwargs: object) -> object:
        raise ValueError("no")

    monkeypatch.setattr("databricks.sdk.WorkspaceClient", broken)
    forget_clients()
    try:
        with pytest.raises(Refusal, match=r"^STORE_UNAVAILABLE$"):
            workspace_client()
    finally:
        forget_clients()


def test_a_workspace_that_does_not_answer_is_unavailable_not_unauthenticated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """F43: SCIM over one bounded request; a closed port is the workspace's
    absence, a 401 is the caller's, and neither costs the SDK's discovery."""
    from caos.api import identity
    from caos.api.identity import actor_from_token

    monkeypatch.setenv(identity.WORKSPACE_ENV, "1234")
    monkeypatch.setenv("DATABRICKS_HOST", "http://127.0.0.1:9")
    monkeypatch.setattr(identity, "_CACHE", {})
    monkeypatch.setattr(identity, "_NEGATIVE", {})
    with pytest.raises(Refusal, match=r"^IDENTITY_UNAVAILABLE$"):
        anyio.run(actor_from_token, "a-token")
    monkeypatch.delenv("DATABRICKS_HOST")
    with pytest.raises(Refusal, match=r"^IDENTITY_UNAVAILABLE$"):
        anyio.run(actor_from_token, "a-token")


def test_the_stub_serves_exports_and_refuses_a_duplicate_app(
    stub: WorkspaceStub,
) -> None:
    """C3 and DP-6: a production deploy reads its lock and state back through
    `workspace/export`, and the platform answers a taken app name with 409."""
    import base64
    import json as json_module
    import urllib.error
    import urllib.request

    def call(method: str, path: str, body: bytes | None = None) -> tuple[int, bytes]:
        request = urllib.request.Request(
            stub.host + path,
            data=body,
            method=method,
            headers={"Authorization": f"Bearer {BEARER}"},
        )
        try:
            with urllib.request.urlopen(request, timeout=5) as answered:
                return answered.status, answered.read()
        except urllib.error.HTTPError as refused:
            return refused.code, refused.read()

    lock = "/Workspace/caos-bundle/prod/state/deploy.lock"
    status, body = call("GET", f"/api/2.0/workspace/export?path={lock}")
    assert status == 404 and b"RESOURCE_DOES_NOT_EXIST" in body
    stub.workspace_files[lock] = b'{"id": "one"}'
    status, body = call(
        "GET", f"/api/2.0/workspace/export?path={lock}&direct_download=true"
    )
    assert (status, body) == (200, b'{"id": "one"}')
    status, body = call("GET", f"/api/2.0/workspace/export?path={lock}")
    assert base64.b64decode(json_module.loads(body)["content"]) == b'{"id": "one"}'
    create = json_module.dumps({"name": "caos"}).encode()
    status, _ = call("POST", "/api/2.0/apps", create)
    assert status == 200 and "caos" in stub.apps
    status, _ = call("POST", "/api/2.0/apps", create)
    assert status == 409


def test_the_stub_refuses_what_the_platform_refuses(stub: WorkspaceStub) -> None:
    """DF-12: a write that keeps an existing file (the deploy lock another
    deployer holds) is 409, an app name outside the Apps rule is 400, and a
    deployment keeps the command and environment the CLI sent with it."""
    import json as json_module
    import urllib.error
    import urllib.request

    def call(method: str, path: str, body: bytes = b"") -> int:
        request = urllib.request.Request(
            stub.host + path,
            data=body,
            method=method,
            headers={"Authorization": f"Bearer {BEARER}"},
        )
        try:
            with urllib.request.urlopen(request, timeout=5) as answered:
                return int(answered.status)
        except urllib.error.HTTPError as refused:
            return refused.code

    lock = "/api/2.0/workspace-files/import-file/Workspace/b/state/deploy.lock"
    assert call("POST", lock + "?overwrite=false", b"mine") == 200
    assert call("POST", lock + "?overwrite=false", b"theirs") == 409
    assert stub.workspace_files["/Workspace/b/state/deploy.lock"] == b"mine"
    assert call("POST", lock + "?overwrite=true", b"again") == 200
    for name in ("caos-qa_eu", "Caos", ""):
        assert (
            call("POST", "/api/2.0/apps", json_module.dumps({"name": name}).encode())
            == 400
        )
    assert call("POST", "/api/2.0/apps", b'{"name": "caos-dev-42"}') == 200
    sent = {
        "source_code_path": "/Workspace/b/files",
        "command": ["uv", "run", "python", "-m", "caos.serve"],
        "env_vars": [{"name": "CAOS_RUN_CEILING", "value": "30.00"}],
    }
    body = json_module.dumps(sent).encode()
    assert call("POST", "/api/2.0/apps/caos-dev-42/deployments", body) == 200
    assert stub.deployed_environment() == {"CAOS_RUN_CEILING": "30.00"}
    assert stub.deployment("caos-dev-42")["command"] == sent["command"]
    stub.app_state, stub.deployment_state = "CRASHED", "FAILED"
    assert stub.app("caos-dev-42")["app_status"]["state"] == "CRASHED"
    assert stub.deployment("caos-dev-42")["status"]["state"] == "FAILED"


def test_the_token_endpoint_refuses_a_malformed_exchange(stub: WorkspaceStub) -> None:
    """N7: the client-credentials exchange the SDK's oauth-m2m strategy makes
    over Basic auth -- a missing or malformed pair, or a grant that is not
    `client_credentials`, is refused `invalid_client`; a well-formed one
    mints the same bearer every other route already accepts."""
    import urllib.error
    import urllib.request

    def token(headers: dict[str, str], body: bytes) -> tuple[int, dict[str, object]]:
        request = urllib.request.Request(
            stub.host + "/oidc/v1/token", data=body, method="POST", headers=headers
        )
        try:
            with urllib.request.urlopen(request, timeout=5) as answered:
                return int(answered.status), json.loads(answered.read())
        except urllib.error.HTTPError as refused:
            return refused.code, json.loads(refused.read())

    body = b"grant_type=client_credentials"
    assert token({}, body) == (400, {"error": "invalid_client"})
    basic = "Basic " + base64.b64encode(b"id:secret").decode()
    assert token({"Authorization": basic}, b"grant_type=authorization_code") == (
        400,
        {"error": "invalid_client"},
    )
    assert (
        token({"Authorization": "Basic " + base64.b64encode(b"noid").decode()}, body)[0]
        == 400
    )
    status, answer = token({"Authorization": basic}, body)
    assert status == 200
    assert answer == {
        "access_token": BEARER,
        "token_type": "Bearer",
        "expires_in": 3600,
    }


def test_a_stand_in_run_starts_from_no_bundle_state_of_its_own(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """DF-13: each stand-in run is a new, empty workspace; a deploy planned on
    the state an earlier one left made CLI 1.17.0 panic. That state is
    cleared; a real workspace's state is kept, and a bundle command refuses
    to run over it."""
    state = tmp_path / ".databricks" / "bundle"

    def target(name: str, snapshot: str | None) -> None:
        (state / name / "sync-snapshots").mkdir(parents=True)
        (state / name / "resources.json").write_text("{}")
        if snapshot is not None:
            (state / name / "sync-snapshots" / "s.json").write_text(snapshot)

    target("dev", json.dumps({"host": "http://127.0.0.1:50123"}))
    target("validated", None)
    target("prod", json.dumps({"host": "https://adb-1.azuredatabricks.net"}))
    target("torn", "{not json")
    assert fresh_state(tmp_path) == ["prod", "torn"]
    assert sorted(p.name for p in state.iterdir()) == ["prod", "torn"]
    monkeypatch.chdir(tmp_path)
    assert main(["--", "databricks", "bundle", "validate"]) == 2
    assert ".databricks/bundle/prod holds a real workspace's state" in (
        capsys.readouterr().err
    )
    assert fresh_state(tmp_path / "absent") == []


def test_preflight_reads_the_gateway_posture_and_the_price_s_endpoint(
    stub: WorkspaceStub, capsys: pytest.CaptureFixture[str]
) -> None:
    """DP-3 / MX-5 and AR-06: payload logging or a fallback on the endpoint is
    a MISSING row with the fix, and a price for another endpoint is refused
    before any deploy."""
    flags = ["--endpoint", ENDPOINT, "--catalog", "main", "--schema", "caos"]
    stub.gateway = {
        "inference_table_config": {"enabled": True, "catalog_name": "main"},
        "fallback_config": {"enabled": True},
    }
    assert preflight.main([*flags, "--lakebase-instance", "caos-lb"]) == 1
    out = capsys.readouterr().out
    assert "MISSING serving endpoint" in out
    assert "inference tables log every payload" in out and "fallback is enabled" in out
    assert issubclass(preflight.Unfit, OSError), "a MISSING row, with its own reason"
    assert preflight.gateway_problems(object()) == [], "no gateway settings: fit"
    stub.gateway = {"guardrails": {"input": {"pii": {"behavior": "BLOCK"}}}}
    assert preflight.main([*flags, "--lakebase-instance", "caos-lb"]) == 0
    out = capsys.readouterr().out
    assert "note    guardrails are set" in out and "ok      serving endpoint" in out
    price = "other-endpoint,0.000005,0.000025,2026-09-22"
    assert (
        preflight.main([*flags, "--lakebase-instance", "caos-lb", "--price", price])
        == 1
    )
    out = capsys.readouterr().out
    assert out.startswith("MISSING price names other-endpoint, not endpoint")
    assert stub.host not in out


ONE_ENTITY = {
    "served_entities": [{"name": "claude", "foundation_model": {"name": "claude"}}],
    "traffic_config": {
        "routes": [{"served_entity_name": "claude", "traffic_percentage": 100}]
    },
}


@pytest.mark.parametrize(
    ("fields", "said"),
    [
        (
            {
                "telemetry_config": {
                    "inference_table_config": {"sampling_fraction": 1.0}
                }
            },
            "inference tables log every payload",
        ),
        (
            {"telemetry_config": {"inference_table_config": {"name": "main.caos.p"}}},
            "inference tables log every payload",
        ),
        (
            {"telemetry_config": {"table_names": {"traces_table": "main.caos.t"}}},
            "telemetry exports logs or traces",
        ),
        (
            {
                "telemetry_config": {
                    "telemetry_profile_id": "profile-1",
                    "enabled_telemetry_features": ["TELEMETRY_FEATURE_LOGS"],
                }
            },
            "telemetry exports logs or traces",
        ),
        (
            {"pending_config": {"auto_capture_config": {"enabled": True}}},
            "a pending update: inference tables log every payload",
        ),
        (
            {"pending_config": {"served_entities": [{"name": "a"}, {"name": "b"}]}},
            "a pending update: more than one served entity",
        ),
    ],
)
def test_preflight_reads_the_endpoint_s_telemetry_and_its_pending_update(
    stub: WorkspaceStub,
    capsys: pytest.CaptureFixture[str],
    fields: dict[str, object],
    said: str,
) -> None:
    """DF-3: payload logging also lives in `telemetry_config`, and an update
    still pending is the configuration the endpoint is about to serve under.
    Each is refused, read through the SDK's own dataclasses."""
    flags = ["--endpoint", ENDPOINT, "--catalog", "main", "--schema", "caos"]
    stub.endpoint_fields = {"config": ONE_ENTITY, **fields}
    assert preflight.main([*flags, "--lakebase-instance", "caos-lb"]) == 1
    out = capsys.readouterr().out
    assert f"MISSING serving endpoint {ENDPOINT}: " in out and said in out, out


def test_preflight_passes_an_endpoint_that_exports_metrics_only(
    stub: WorkspaceStub, capsys: pytest.CaptureFixture[str]
) -> None:
    """Metrics carry no document text; a table named with sampling off and
    a pending update that changes nothing the host relies on are fit too."""
    flags = ["--endpoint", ENDPOINT, "--catalog", "main", "--schema", "caos"]
    stub.endpoint_fields = {
        "config": ONE_ENTITY,
        "telemetry_config": {
            "enabled_telemetry_features": ["TELEMETRY_FEATURE_METRICS"],
            "table_names": {"metrics_table": "main.caos.metrics"},
            "inference_table_config": {"sampling_fraction": 0.0},
        },
        "pending_config": {"config_version": 2, **ONE_ENTITY},
    }
    assert preflight.main([*flags, "--lakebase-instance", "caos-lb"]) == 0
    assert "ok      serving endpoint" in capsys.readouterr().out


def test_preflight_does_not_stop_on_a_profile_that_cannot_list_groups(
    stub: WorkspaceStub, capsys: pytest.CaptureFixture[str]
) -> None:
    """W5: unknown is not missing. The deployer is told, and the deploy goes on."""
    stub.groups_forbidden = True
    flags = ["--endpoint", ENDPOINT, "--catalog", "main", "--schema", "caos"]
    assert preflight.main([*flags, "--lakebase-instance", "caos-lb"]) == 0
    out = capsys.readouterr().out
    assert out.count("UNKNOWN group") == 2 and "MISSING" not in out
    assert out.count("ok ") == 4


def test_the_smoke_parses_the_json_answer_it_asked_for(
    stub: WorkspaceStub, capsys: pytest.CaptureFixture[str]
) -> None:
    """AR-17: JSON mode that the endpoint takes and ignores fails the smoke."""
    stub.reply = lambda prompt, json_object: "definitely not JSON"
    assert gateway_smoke.main() == 1
    assert capsys.readouterr().out.rstrip().endswith("json_mode=not JSON")


def test_an_answer_in_content_parts_prints_no_warning_quoting_it(
    stub: WorkspaceStub,
) -> None:
    """CF-077: an endpoint that answers with a list of content parts made the
    client's message dump raise Pydantic's serializer `UserWarning`, whose
    text quotes the answer -- the model's words, which quote the evidence --
    and Python prints a warning to stderr. Through the real `ChatDatabricks`
    over HTTP it is contained around the call, and nothing of it is left."""
    import warnings

    from caos.models import from_environment

    said = "SECRET-PART-TEXT from the model"
    stub.reply = lambda _prompt, _json_object: said
    stub.content_parts = True
    provider = from_environment()
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        completion = provider.complete("q" * 200)
    assert completion.charge is not None
    # The warning shortens the value it quotes, so its own words and the
    # answer's tail are what is looked for.
    messages = [str(w.message) for w in caught]
    assert not [m for m in messages if "serializer warnings" in m], messages
    assert not [m for m in messages if "from the model" in m], messages
    assert stub.completions == 1

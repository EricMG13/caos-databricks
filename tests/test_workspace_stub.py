"""The production seams against the loopback workspace (D28): nothing below
HTTP is injected, so what passes here is the SDK, the wire shapes and this
repository's code. What a real workspace grants stays with the deployer."""

from __future__ import annotations

import json
import os
import sys
from collections.abc import Iterator
from pathlib import Path
from urllib.parse import urlparse
from uuid import UUID

import gateway_smoke
import preflight
import pytest
from conftest import priced
from openai import NotFoundError
from test_loop_charges import ESTIMATE, _Completions, ready, route
from workspace_stub import BEARER, ENDPOINT, WorkspaceStub, main

from caos.api import edge, identity
from caos.api.identity import GlobalRole, actor_from_token
from caos.blobs import BlobStore
from caos.graph.build import thread_config
from caos.graph.checkpoint import SCHEMA, MintedConnection, checkpointer
from caos.graph.route import ResolvedRoute
from caos.graph.runtime import Execution, run_route
from caos.methodology.bundle import Bundle
from caos.methodology.runner import ModuleProvider
from caos.models import completions
from caos.refusals import Refusal
from caos.store import RunStatus, StoreConnection
from caos.store.runs import run_status

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
    actor = actor_from_token("a-forwarded-token")
    assert actor.role is GlobalRole.ADMIN
    assert isinstance(actor.user_id, UUID)
    assert ("GET", "/api/2.0/preview/scim/v2/Me") in stub.requests
    assert "a-forwarded-token" not in json.dumps(stub.requests)

    stub.groups = frozenset({"caos-analysts"})
    monkeypatch.setattr(identity, "_CACHE", {})
    assert actor_from_token("another").role is GlobalRole.ANALYST


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
    assert methods == {"HEAD", "PUT", "POST", "GET"}
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

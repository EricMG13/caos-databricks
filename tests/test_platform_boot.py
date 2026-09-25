"""The App booted the way the platform boots it, driven through its own HTTP
surface end to end (D28): health on minted credentials and the volume, a case,
its pack, a LITE run through `ChatDatabricks`, the event stream, the report.
Nothing below HTTP is injected; the workspace is the loopback stub, and the
Lakebase either kind the bundle binds (R24-14): an Autoscaling endpoint, the
default, or a Provisioned instance."""

from __future__ import annotations

import time
import urllib.error
import urllib.request
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlparse
from uuid import uuid4

import platform_app as platform_app_module
import pytest
from canonical_fixtures import CATALOG, LITE_PROFILE, LITE_SELECTION
from platform_app import (
    BINDINGS,
    VOLUME,
    BootFailed,
    PlatformApp,
    export_root,
    platform_app,
    platform_environment,
)
from platform_journey import governed_run, identities
from test_workspace_stub import CREDENTIALS, stub
from workspace_stub import LAKEBASE_ENDPOINT, LAKEBASE_INSTANCE, WorkspaceStub

from caos.api.site import _complete
from caos.graph.route import resolve_route
from caos.store import lakebase
from caos.store.lakebase import LakebaseKind

__all__ = ["stub"]

ROUTE = resolve_route(CATALOG, LITE_PROFILE, LITE_SELECTION)
BOTH_KINDS = pytest.mark.parametrize(
    "app", list(LakebaseKind), indirect=True, ids=[kind.value for kind in LakebaseKind]
)


@pytest.fixture
def app(
    request: pytest.FixtureRequest,
    stub: WorkspaceStub,
    empty_database: str,
    tmp_path: Path,
) -> Iterator[PlatformApp]:
    """The booted app, bound to Lakebase Autoscaling unless a test asks for
    another kind (`BOTH_KINDS`)."""
    kind = getattr(request, "param", LakebaseKind.AUTOSCALING)
    stub.identities = identities()
    log = tmp_path / "caos.serve.log"
    with platform_app(stub, empty_database, log, kind) as served:
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
    # Exactly one Lakebase, the default kind's unless another is asked for.
    assert env[lakebase.LAKEBASE_ENDPOINT] == LAKEBASE_ENDPOINT
    assert lakebase.LAKEBASE_INSTANCE not in env
    env = platform_environment(stub, database, 8000, tmp_path, LakebaseKind.PROVISIONED)
    assert env[lakebase.LAKEBASE_INSTANCE] == LAKEBASE_INSTANCE
    assert lakebase.LAKEBASE_ENDPOINT not in env
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
    # A deployment's own Lakebase binding is the one the process boots with.
    bound = {"name": lakebase.LAKEBASE_INSTANCE, "value": LAKEBASE_INSTANCE}
    stub.deployment_bodies.append({"env_vars": [*sent, bound]})
    env = platform_environment(stub, database, 8000, tmp_path)
    assert env[lakebase.LAKEBASE_INSTANCE] == LAKEBASE_INSTANCE
    assert lakebase.LAKEBASE_ENDPOINT not in env


def test_the_stand_in_export_is_complete_to_the_boot_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """N92: where no export is built, the harness boots a stand-in, and the
    boot check now reads the build manifest too; a stand-in without one would
    refuse boot on every job that builds no frontend."""
    monkeypatch.setattr(platform_app_module, "REPO", tmp_path / "unbuilt")
    root = export_root(tmp_path)
    assert root == tmp_path / "site"
    assert _complete(root)


@BOTH_KINDS
def test_the_platform_process_boots_ready_on_minted_credentials_and_the_volume(
    app: PlatformApp, stub: WorkspaceStub
) -> None:
    health = app.health()
    assert health["status"] == "ready", health
    assert str(health["python_version"]).startswith("3.13")
    assert health["store"] == health["blobs"] == health["bundle"], health
    # R24-14: the credential is minted through the bound kind's own API only.
    minted = {kind for kind, route in CREDENTIALS.items() if route in stub.requests}
    assert minted == {app.kind}, (minted, app.kind)
    assert ("HEAD", "/api/2.0/fs/directories" + VOLUME) in stub.requests
    # N7: the platform hands the process a service principal's client id and
    # secret, not a token; the app traded them for one itself, through the
    # SDK's own oauth-m2m discovery and exchange, to make every call above.
    assert ("GET", "/oidc/.well-known/oauth-authorization-server") in stub.requests
    assert ("POST", "/oidc/v1/token") in stub.requests
    # The platform is the edge: a request with no forwarded token is anonymous,
    # and a role header a client sends decides nothing.
    anonymous = urllib.request.Request(
        app.url + "/api/v1/book", headers={"x-caos-role": "ADMIN"}
    )
    with pytest.raises(urllib.error.HTTPError) as refused:
        urllib.request.urlopen(anonymous, timeout=10)
    assert refused.value.code == 401


@BOTH_KINDS
def test_a_governed_run_completes_through_the_platform_surface(
    app: PlatformApp, stub: WorkspaceStub
) -> None:
    journey = governed_run(app, stub)
    assert journey.status == "COMPLETE", (
        journey.view,
        app.health().get("workers"),
        stub.completions,
        app.log_tail(),
    )
    stream = journey.stream
    assert stream.first_at is not None, ("no event arrived", stream)
    assert stream.first_at < journey.finished_at
    assert stream.ended_at is None or stream.ended_at > stream.first_at, stream
    assert stub.completions == stub.json_completions == len(ROUTE.nodes)
    assert journey.report.status == 200, journey.report.body
    # Everything the run accepted is in the volume, by digest.
    assert len(stub.files) > 1


@pytest.mark.parametrize(
    "bound",
    [
        {**BINDINGS[LakebaseKind.AUTOSCALING], **BINDINGS[LakebaseKind.PROVISIONED]},
        {lakebase.LAKEBASE_ENDPOINT: ""},
    ],
    ids=["both-kinds", "neither-kind"],
)
def test_a_process_bound_to_no_one_lakebase_refuses_at_boot(
    stub: WorkspaceStub,
    empty_database: str,
    tmp_path: Path,
    bound: dict[str, str],
) -> None:
    """R24-14: a deployment that binds both kinds (the instance used to win)
    or neither does not start: the lifespan prints `STORE_NOT_CONFIGURED`
    and the process exits, and no credential is minted for either kind."""
    sent = [{"name": name, "value": value} for name, value in bound.items()]
    stub.deployment_bodies.append({"env_vars": sent})
    with (
        pytest.raises(BootFailed) as failed,
        platform_app(stub, empty_database, tmp_path / "caos.serve.log"),
    ):
        pytest.fail("the process answered ready")
    assert "STORE_NOT_CONFIGURED" in str(failed.value)
    assert not set(CREDENTIALS.values()) & set(stub.requests)


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

"""The process a Databricks App runs, started the way the platform starts it.

`python -m caos.serve` in a subprocess with the platform's environment: the
app name and port, `PG*` for the database resource, the workspace host and
a bearer, the volume blob root, the gateway endpoint and price, the run
ceiling, the in-process worker, the static export, and the one Lakebase the
target binds (an Autoscaling endpoint by default, or a Provisioned instance;
R24-14). The workspace is the loopback stub (D28) and the database is the
test Postgres, reached through the credential the stub mints for that
kind -- so `store_url()`, the migrations, the health probes, identity, the
worker and the volume backend all run as they would behind the Apps proxy,
with nothing injected below HTTP.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from socket import socket
from urllib.parse import urlparse

from workspace_stub import BEARER, LAKEBASE_ENDPOINT, LAKEBASE_INSTANCE, WorkspaceStub

from caos.api.site import MANIFEST
from caos.store import lakebase
from caos.store.lakebase import LakebaseKind

REPO = Path(__file__).resolve().parents[1]
VOLUME = "/Volumes/main/caos/caos_blobs"
BOOT_SECONDS = 90
# What no platform process inherits from a developer's shell or a test's.
LOCAL_ONLY = (
    "CAOS_DATABASE_URL",
    "CAOS_TEST_POSTGRES_URL",
    "CAOS_QUALIFY_POSTGRES_URL",
    "CAOS_DEV_USER",
    "CAOS_DEV_ROLE",
    "CAOS_TRUST_ROLE_HEADER",
    "CAOS_PUBLIC_ORIGIN",
    "DATABRICKS_CONFIG_PROFILE",
)
# What each kind's targets set for the process: the one Lakebase it mints for.
LAKEBASE_NAMES = (lakebase.LAKEBASE_ENDPOINT, lakebase.LAKEBASE_INSTANCE)
BINDINGS = {
    LakebaseKind.AUTOSCALING: {lakebase.LAKEBASE_ENDPOINT: LAKEBASE_ENDPOINT},
    LakebaseKind.PROVISIONED: {lakebase.LAKEBASE_INSTANCE: LAKEBASE_INSTANCE},
}


@dataclass(frozen=True, slots=True)
class PlatformApp:
    url: str
    process: subprocess.Popen[bytes]
    log: Path
    kind: LakebaseKind = LakebaseKind.AUTOSCALING

    def log_tail(self, chars: int = 4000) -> str:
        """The process's last output, for a failing assertion to quote."""
        return self.log.read_text(errors="replace")[-chars:]

    def health(self) -> dict[str, object]:
        with urllib.request.urlopen(self.url + "/api/health", timeout=10) as answer:
            import json

            body: dict[str, object] = json.loads(answer.read())
            return body


def platform_environment(
    stub: WorkspaceStub,
    database_url: str,
    port: int,
    site_root: Path,
    kind: LakebaseKind = LakebaseKind.AUTOSCALING,
) -> dict[str, str]:
    """The environment the bundle and the platform give the process. When the
    stub holds a deployment, its `env_vars` are the bundle's part, as the
    platform would apply them (DF-12), its Lakebase binding included; only
    the bind address and the export stay local, since a test binds loopback
    and serves the export it has."""
    parts = urlparse(database_url)
    ambient = LOCAL_ONLY + LAKEBASE_NAMES
    env = {k: v for k, v in os.environ.items() if k not in ambient}
    # N7: the platform hands the app a service principal's client id and
    # secret, never a token; an ambient DATABRICKS_TOKEN (a developer's own
    # shell) must not leak in and stand in for that exchange.
    env.pop("DATABRICKS_TOKEN", None)
    env.update(stub.service_principal_environment())
    env.update(
        DATABRICKS_APP_NAME="caos",
        DATABRICKS_APP_PORT=str(port),
        DATABRICKS_WORKSPACE_ID="1234",
        PGHOST=parts.hostname or "127.0.0.1",
        PGPORT=str(parts.port or 5432),
        PGDATABASE=parts.path.lstrip("/"),
        PGUSER=parts.username or "postgres",
        PGSSLMODE="disable",  # the test Postgres speaks no TLS; Lakebase requires it
        CAOS_BLOB_ROOT=f"volume://{VOLUME}",
        CAOS_RUN_CEILING="100.00",
        CAOS_WORKER_IN_PROCESS="1",
        CAOS_GROUP_ADMIN="caos-admins",
        CAOS_GROUP_ANALYST="caos-analysts",
        MLFLOW_DISABLE_AGENT_HINT="1",
    )
    deployed = stub.deployed_environment()
    if not deployed.keys() & set(LAKEBASE_NAMES):
        env.update(BINDINGS[kind])
    env.update(deployed)
    env.update(CAOS_SITE_ROOT=str(site_root), CAOS_BIND_HOST="127.0.0.1")
    return env


def export_root(scratch: Path) -> Path:
    """The built export when it is here, else a stand-in -- an index and the
    build manifest the boot check reads (N92) -- so the boot is the
    platform's (`CAOS_SITE_ROOT` set) and not the local 404 mode."""
    built = REPO / "frontend" / "dist"
    if (built / "index.html").is_file():
        return built
    stand_in = scratch / "site"
    (stand_in / MANIFEST).parent.mkdir(parents=True, exist_ok=True)
    (stand_in / "index.html").write_text("<!doctype html><title>stand-in</title>")
    (stand_in / MANIFEST).write_text('{"index.html": {"file": "index.html"}}')
    return stand_in


def free_port() -> int:
    with socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = int(probe.getsockname()[1])
    return port


@contextmanager
def platform_app(
    stub: WorkspaceStub,
    database_url: str,
    log: Path,
    kind: LakebaseKind = LakebaseKind.AUTOSCALING,
) -> Iterator[PlatformApp]:
    """`python -m caos.serve` under the platform's environment, ready or refused.

    Its output goes to `log`, never to a pipe nobody drains: a full pipe would
    block the process on its next log line and look exactly like a stalled run.
    """
    stub.database_credential = urlparse(database_url).password or BEARER
    stub.directories.add(VOLUME)
    port = free_port()
    url = f"http://127.0.0.1:{port}"
    stub.app_url = url
    site_root = export_root(log.parent)
    with log.open("wb") as sink:
        process = subprocess.Popen(
            [sys.executable, "-m", "caos.serve"],
            cwd=REPO,
            env=platform_environment(stub, database_url, port, site_root, kind),
            stdout=sink,
            stderr=subprocess.STDOUT,
        )
    try:
        _wait_ready(url, process, log)
        yield PlatformApp(url, process, log, kind)
    finally:
        process.terminate()
        try:
            process.wait(timeout=30)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=10)


class BootFailed(RuntimeError):
    """The process exited before it was ready; its output tail is the message."""


class NotReady(BootFailed):
    """The process is still up but never answered `ready` within `BOOT_SECONDS`."""


def _wait_ready(url: str, process: subprocess.Popen[bytes], log: Path) -> None:
    deadline = time.monotonic() + BOOT_SECONDS
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise BootFailed(log.read_text(errors="replace")[-4000:])
        try:
            with urllib.request.urlopen(url + "/api/health", timeout=5) as answer:
                if b'"status":"ready"' in answer.read().replace(b" ", b""):
                    return
        except (urllib.error.URLError, OSError):
            pass
        time.sleep(0.5)
    process.terminate()
    raise NotReady

"""The file set a stand-in deployment ships, booted the way the platform boots it.

`databricks bundle deploy` and `bundle run caos` go to the loopback workspace
(D28) the way `workspace_stub.py` runs them; then the bytes the CLI synced to
the app's source path -- read back from the stub, not from this checkout --
are written to a scratch directory, `python -m caos.serve` starts *there*
under the platform's environment and the deployment's own variables, every
health code must be `OK`, and one governed LITE run must complete through
`ChatDatabricks` over the stub (CF-001, N47). The boot from the repository
(`tests/test_platform_boot.py`) cannot tell a file the sync left out from one
the process never needed; this can.

`uv run python tests/shipped_boot.py` after `npm --prefix frontend run build`,
with `CAOS_TEST_POSTGRES_URL` naming a Postgres server this may create a
database on. CI's `bundle` job runs it, the job that has the CLI.
"""

from __future__ import annotations

import os
import sys
import tempfile
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

if TYPE_CHECKING:
    from platform_app import PlatformApp
    from workspace_stub import WorkspaceStub

REPO = Path(__file__).resolve().parents[1]
TARGET = "dev"
# As long as E6 waits for every code (`enterprise_deploy.HEALTH_SECONDS`).
HEALTH_SECONDS = 90
VARIABLES = (
    "--var", "uc_catalog=main", "--var", "uc_schema=caos",
    "--var", "lakebase_project=caos",
)  # fmt: skip


def shipped_tree(stub: WorkspaceStub, into: Path) -> int:
    """Write every file the last deployment's source path holds under `into`,
    as the app's working directory holds it; the number written.

    `ValueError` when no deployment was made, when it holds no file, or when a
    stored path would land outside `into`."""
    if not stub.deployments or not stub.deployments[-1]:
        raise ValueError  # no deployment
    source = stub.deployments[-1].rstrip("/") + "/"
    root = into.resolve()
    written = 0
    for path, data in sorted(stub.workspace_files.items()):
        if not path.startswith(source):
            continue
        target = (root / path[len(source) :]).resolve()
        if not target.is_relative_to(root):
            raise ValueError  # a stored path that leaves the tree
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        written += 1
    if not written:
        raise ValueError  # a deployment that holds nothing
    return written


@contextmanager
def fresh_database(server_url: str) -> Iterator[str]:
    """A database of its own on `server_url`'s server, dropped afterwards."""
    import psycopg

    name = f"caos_shipped_{uuid4().hex}"
    with psycopg.connect(server_url, autocommit=True) as admin:
        # The name is this function's own hex, never caller input.
        admin.execute(f'CREATE DATABASE "{name}"')
    try:
        # A URL, as `platform_app` reads the `PG*` variables from one.
        yield urlunsplit(urlsplit(server_url)._replace(path=f"/{name}"))
    finally:
        with psycopg.connect(server_url, autocommit=True) as admin:
            admin.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')


def every_code_ok(app: PlatformApp, names: tuple[str, ...]) -> dict[str, object]:
    """Health's codes once every one reads `OK`, or as they last read after
    `HEALTH_SECONDS`: `ready` needs only the first four, and the in-process
    worker's first beat lands just after it, as E6 waits for it."""
    deadline = time.monotonic() + HEALTH_SECONDS
    while True:
        health = app.health()
        codes = {name: health.get(name) for name in names}
        if set(codes.values()) == {"OK"} or time.monotonic() > deadline:
            return codes
        time.sleep(1.0)


def main() -> int:
    for entry in (str(REPO), str(REPO / "scripts"), str(REPO / "tests")):
        if entry not in sys.path:
            sys.path.insert(0, entry)
    # Loaded once the path holds the repository, `scripts/` and `tests/`, the
    # way `tests/conftest.py` lets the suite load them.
    from enterprise_deploy import HEALTH_CODES
    from platform_app import platform_app
    from platform_journey import governed_run
    from workspace_stub import WorkspaceStub, run_against

    server = os.environ.get("CAOS_TEST_POSTGRES_URL")
    if not server:
        print("shipped: CAOS_TEST_POSTGRES_URL is unset", file=sys.stderr)
        return 2
    stub = WorkspaceStub()
    with stub.serving(), tempfile.TemporaryDirectory() as scratch:
        # Deploy and run under the one stub, as CI does: the run starts the
        # app the deploy created, and a second `bundle` command would first
        # clear the stand-in state the deploy left (`fresh_state`).
        variables = " ".join(VARIABLES)
        both = (
            f"databricks bundle deploy -t {TARGET} {variables}"
            f" && databricks bundle run caos -t {TARGET} {variables}"
        )
        code = run_against(stub, ["sh", "-c", both])
        if code:
            print(f"shipped: bundle deploy and run exited {code}", file=sys.stderr)
            return code
        tree = Path(scratch) / "shipped"
        count = shipped_tree(stub, tree)
        print(f"shipped: {count} files synced to {stub.deployments[-1]}")
        log = Path(scratch) / "caos.serve.log"
        with (
            fresh_database(server) as database,
            platform_app(stub, database, log, root=tree) as app,
        ):
            codes = every_code_ok(app, HEALTH_CODES)
            print("shipped: health " + " ".join(f"{k}={v}" for k, v in codes.items()))
            if set(codes.values()) != {"OK"}:
                return 1
            journey = governed_run(app, stub)
            print(
                f"shipped: governed LITE run {journey.status}, "
                f"{stub.completions} completions through ChatDatabricks, "
                f"report {journey.report.status}"
            )
            done = journey.status == "COMPLETE" and journey.report.status == 200
            return 0 if done else 1


if __name__ == "__main__":
    sys.exit(main())

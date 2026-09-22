#!/usr/bin/env python3
"""Check that a workspace holds what `databricks.yml` binds to (D23).

Run before the first deploy with a CLI profile in the environment
(`DATABRICKS_CONFIG_PROFILE`) and the bundle variables as flags. Each named
resource is looked up through the SDK; a missing one is printed with the
command an administrator runs to create it. Nothing is created here.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from databricks.sdk import WorkspaceClient


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--endpoint", required=True, help="serving endpoint name")
    parser.add_argument("--catalog", required=True)
    parser.add_argument("--schema", required=True)
    parser.add_argument("--lakebase-instance", required=True)
    parser.add_argument("--group-admin", default="caos-admins")
    parser.add_argument("--group-analyst", default="caos-analysts")
    parser.add_argument("--price", help="the bundle's model_price value")
    parser.add_argument("--run-ceiling", help="the bundle's run_ceiling value")
    args = parser.parse_args(argv)

    if args.price is not None and not affordable(args.price, args.run_ceiling):
        return 1

    from databricks.sdk import WorkspaceClient

    client = WorkspaceClient()
    checks: list[tuple[str, Callable[[], object], str]] = [
        (
            f"serving endpoint {args.endpoint}",
            lambda: client.serving_endpoints.get(args.endpoint),
            "create or enable the endpoint under Serving > AI Gateway",
        ),
        (
            f"schema {args.catalog}.{args.schema}",
            lambda: client.schemas.get(f"{args.catalog}.{args.schema}"),
            f"CREATE SCHEMA {args.catalog}.{args.schema}",
        ),
        (
            f"volume {args.catalog}.{args.schema}.caos_blobs",
            lambda: client.volumes.read(f"{args.catalog}.{args.schema}.caos_blobs"),
            f"CREATE VOLUME {args.catalog}.{args.schema}.caos_blobs",
        ),
        (
            f"lakebase instance {args.lakebase_instance}",
            lambda: client.database.get_database_instance(args.lakebase_instance),
            "create a Lakebase instance in Compute > Lakebase",
        ),
        (
            f"group {args.group_admin}",
            lambda: _group(client, args.group_admin),
            f"create workspace group {args.group_admin}",
        ),
        (
            f"group {args.group_analyst}",
            lambda: _group(client, args.group_analyst),
            f"create workspace group {args.group_analyst}",
        ),
    ]
    missing = 0
    for name, look, fix in checks:
        try:
            look()
        except OSError:
            # The SDK's errors are `IOError`s; their text may carry the host.
            missing += 1
            print(f"MISSING {name}: {fix}")
            continue
        print(f"ok      {name}")
    return 1 if missing else 0


def affordable(price: str, run_ceiling: str | None) -> bool:
    """Whether `run_ceiling` covers one worst-case call at `price` (F28).

    Pure and printed like the lookups: a run whose ceiling cannot pay for one
    call is refused at start, so it is found here, before a deploy.
    """
    from caos.pricing import price_from_environment, worst_case
    from caos.refusals import Refusal
    from caos.store.budget import CEILING, configured_ceiling

    endpoint = price.split(",", 1)[0]
    try:
        worst = worst_case(price_from_environment(endpoint, price))
        ceiling = configured_ceiling(run_ceiling)
    except Refusal as refused:
        print(f"MISSING price or run ceiling ({refused.code.value}): fix model_price")
        return False
    ceiling = CEILING if ceiling is None else ceiling
    if ceiling < worst:
        print(
            f"MISSING run ceiling {ceiling} covers no worst-case call ({worst}): "
            f"set run_ceiling to at least {worst}"
        )
        return False
    print(f"ok      run ceiling {ceiling} covers a worst-case call ({worst})")
    return True


def _group(client: WorkspaceClient, display: str) -> object:
    found = list(client.groups.list(filter=f'displayName eq "{display}"'))
    if not found:
        raise OSError(display)
    return found[0]


if __name__ == "__main__":
    sys.exit(main())

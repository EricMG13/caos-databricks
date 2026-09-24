#!/usr/bin/env python3
"""Check that a workspace holds what `databricks.yml` binds to (D23).

Run before the first deploy with a CLI profile in the environment
(`DATABRICKS_CONFIG_PROFILE`) and the bundle variables as flags. Each named
resource is looked up through the SDK; a missing one is printed with the
command an administrator runs to create it. Nothing is created here.

The serving endpoint is also checked for the AI Gateway posture the host
relies on (DP-3, MX-5): no inference-table payload logging, because every
prompt carries document text; no fallback and one served entity, because the
host prices one model per endpoint. Guardrails are reported, not refused.

Lakebase is looked up as the target binds it (R24-14): by default a Lakebase
Autoscaling project, its read-write endpoint and its database through the
Postgres API (`--lakebase-project`), or an existing Provisioned instance
through the database API (`--lakebase-instance`); exactly one is given.
"""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import bundle_defaults

if TYPE_CHECKING:
    from databricks.sdk import WorkspaceClient

# Run by path (`uv run python scripts/preflight.py`, as the runbook gives
# it), Python puts only `scripts/` on the import path; the price check
# imports `caos` from the root (MAX-07).
REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

# What `_group` answers when the profile cannot list groups: not missing.
UNKNOWN = object()
# The bundle's own defaults for the Lakebase names and the groups (N23, N5).
_DEFAULTS = bundle_defaults.defaults()
READ_ONLY = "ENDPOINT_TYPE_READ_ONLY"
ENDPOINT_READ_ONLY = "a read-only endpoint: the app writes; name the read-write one"
ENDPOINT_DISABLED = "the endpoint is disabled: enable it or name another"

Check = tuple[str, Callable[[], object], str]


@dataclass(frozen=True, slots=True)
class LakebasePaths:
    """A Lakebase Autoscaling binding as the Postgres API names it: the
    bundle's `postgres` resource binds `branch` and `database`, and the app
    mints its credential for `endpoint`."""

    project: str
    branch: str
    endpoint: str
    database: str


def autoscaling_paths(
    project: str, branch: str, endpoint: str, database_id: str
) -> LakebasePaths:
    """The resource paths `databricks.yml` composes from the same four ids."""
    project_path = f"projects/{project}"
    branch_path = f"{project_path}/branches/{branch}"
    return LakebasePaths(
        project_path,
        branch_path,
        f"{branch_path}/endpoints/{endpoint}",
        f"{branch_path}/databases/{database_id}",
    )


class Unfit(OSError):
    """A resource that exists but is configured against the app's rules."""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--endpoint", required=True, help="serving endpoint name")
    parser.add_argument("--catalog", required=True)
    parser.add_argument("--schema", required=True)
    kind = parser.add_mutually_exclusive_group(required=True)
    kind.add_argument(
        "--lakebase-project", help="Lakebase Autoscaling project id (the default)"
    )
    kind.add_argument(
        "--lakebase-instance", help="an existing Lakebase Provisioned instance"
    )
    parser.add_argument("--lakebase-branch", default=_DEFAULTS["lakebase_branch"])
    parser.add_argument("--lakebase-endpoint", default=_DEFAULTS["lakebase_endpoint"])
    parser.add_argument(
        "--lakebase-database-id", default=_DEFAULTS["lakebase_database_id"]
    )
    parser.add_argument("--group-admin", default=_DEFAULTS["group_admin"])
    parser.add_argument("--group-analyst", default=_DEFAULTS["group_analyst"])
    parser.add_argument("--price", help="the bundle's model_price value")
    parser.add_argument("--run-ceiling", help="the bundle's run_ceiling value")
    args = parser.parse_args(argv)

    if args.price is not None and not affordable(
        args.price, args.run_ceiling, endpoint=args.endpoint
    ):
        return 1

    from databricks.sdk import WorkspaceClient

    try:
        client = WorkspaceClient()
    except ValueError:
        # No credentials resolve. The SDK's message names the profile and the
        # variables it read; the profile name is all this prints.
        profile = os.environ.get("DATABRICKS_CONFIG_PROFILE") or "DEFAULT"
        print(
            f"MISSING workspace credentials for profile {profile}: run "
            f"'databricks auth login --host <workspace-url> --profile {profile}'"
        )
        return 1
    checks: list[Check] = [
        (
            f"serving endpoint {args.endpoint}",
            lambda: _fit_endpoint(client, args.endpoint),
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
        *_lakebase_checks(client, args),
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
            found = look()
        except Unfit as unfit:
            missing += 1
            print(f"MISSING {name}: {unfit.args[0]}")
            continue
        except OSError:
            # The SDK's errors are `IOError`s; their text may carry the host.
            missing += 1
            print(f"MISSING {name}: {fix}")
            continue
        if found is UNKNOWN:
            continue  # said already, and not a reason to stop (W5)
        print(f"ok      {name}")
    return 1 if missing else 0


def affordable(
    price: str, run_ceiling: str | None, *, endpoint: str | None = None
) -> bool:
    """Whether `run_ceiling` covers one worst-case call at `price` (F28), and
    the price names `endpoint` when one is given (AR-06).

    Pure and printed like the lookups: a run whose ceiling cannot pay for one
    call, or a price for some other endpoint, is refused at the app's start,
    so it is found here, before a deploy.
    """
    from caos.pricing import price_from_environment, worst_case
    from caos.refusals import Refusal
    from caos.store.budget import CEILING, configured_ceiling

    priced = price.split(",", 1)[0]
    if endpoint is not None and priced != endpoint:
        print(f"MISSING price names {priced}, not endpoint {endpoint}: fix model_price")
        return False
    try:
        worst = worst_case(price_from_environment(priced, price))
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


def _fit_endpoint(client: WorkspaceClient, name: str) -> object:
    """The endpoint, or `Unfit` naming the gateway setting the host cannot run under."""
    endpoint = client.serving_endpoints.get(name)
    problems = gateway_problems(endpoint)
    if problems:
        raise Unfit("; ".join(problems))
    return endpoint


PAYLOADS_LOGGED = (
    "inference tables log every payload: turn payload logging off, "
    "the prompts carry document text"
)
# Telemetry signals that carry no request or response text.
TEXT_FREE_TELEMETRY = frozenset({"TELEMETRY_FEATURE_METRICS"})


def gateway_problems(endpoint: object) -> list[str]:
    """What the endpoint's AI Gateway and telemetry settings would do to the
    host (DP-3), and what an update still pending would do once it lands
    (DF-3): payload logging lives in `ai_gateway`, in the legacy
    `auto_capture_config` and in `telemetry_config`."""
    gateway = getattr(endpoint, "ai_gateway", None)
    problems = _serving_problems(getattr(endpoint, "config", None))
    tables = getattr(gateway, "inference_table_config", None)
    if getattr(tables, "enabled", False):
        problems.append(PAYLOADS_LOGGED)
    problems += _telemetry_problems(getattr(endpoint, "telemetry_config", None))
    pending = _serving_problems(getattr(endpoint, "pending_config", None))
    problems += [f"a pending update: {problem}" for problem in pending]
    if getattr(getattr(gateway, "fallback_config", None), "enabled", False):
        problems.append("fallback is enabled: the host prices one model per endpoint")
    if getattr(gateway, "guardrails", None) is not None:
        print(
            "note    guardrails are set on the endpoint: an output guardrail "
            "alters or refuses answers, which the host refuses as PROVIDER_REFUSED"
        )
    return list(dict.fromkeys(problems))


def _serving_problems(config: object) -> list[str]:
    """A served or pending configuration: its legacy payload capture, and more
    than one entity, model or route to price."""
    problems: list[str] = []
    if getattr(getattr(config, "auto_capture_config", None), "enabled", False):
        problems.append(PAYLOADS_LOGGED)
    entities = getattr(config, "served_entities", None) or []
    models = getattr(config, "served_models", None) or []
    routes = getattr(getattr(config, "traffic_config", None), "routes", None) or []
    if max(len(entities), len(models), len(routes)) > 1:
        problems.append(
            "more than one served entity or route: the recorded model identity "
            "and price would not describe every answer"
        )
    return problems


def _telemetry_problems(telemetry: object) -> list[str]:
    """`telemetry_config`: an inference table named or sampling any request
    copies payloads; an export destination for logs or traces (every signal
    when none is listed) copies them too."""
    if telemetry is None:
        return []
    problems: list[str] = []
    table = getattr(telemetry, "inference_table_config", None)
    sampled = getattr(table, "sampling_fraction", None) or 0
    if getattr(table, "name", None) or sampled > 0:
        problems.append(PAYLOADS_LOGGED)
    names = getattr(telemetry, "table_names", None)
    exported = bool(getattr(telemetry, "telemetry_profile_id", None)) or any(
        getattr(names, field, None)
        for field in ("logs_table", "traces_table", "annotations_table")
    )
    features = getattr(telemetry, "enabled_telemetry_features", None) or []
    signals = {getattr(feature, "value", feature) for feature in features}
    if exported and not (signals and signals <= TEXT_FREE_TELEMETRY):
        problems.append(
            "telemetry exports logs or traces to tables: export metrics only, "
            "the prompts carry document text"
        )
    return problems


def _lakebase_checks(client: WorkspaceClient, args: argparse.Namespace) -> list[Check]:
    """The rows for the Lakebase the target binds: an Autoscaling project,
    endpoint and database, or one Provisioned instance."""
    if args.lakebase_instance is not None:
        instance = args.lakebase_instance
        return [
            (
                f"lakebase instance {instance}",
                lambda: client.database.get_database_instance(instance),
                "name an existing Provisioned instance (none can be created "
                "now), or deploy the default kind, Lakebase Autoscaling",
            )
        ]
    paths = autoscaling_paths(
        args.lakebase_project,
        args.lakebase_branch,
        args.lakebase_endpoint,
        args.lakebase_database_id,
    )
    return [
        (
            f"lakebase project {paths.project}",
            lambda: client.postgres.get_project(paths.project),
            f"databricks postgres create-project {args.lakebase_project}",
        ),
        (
            f"lakebase endpoint {paths.endpoint}",
            lambda: _fit_lakebase_endpoint(client, paths.endpoint),
            f"'databricks postgres list-endpoints {paths.branch}' names its endpoints",
        ),
        (
            f"lakebase database {paths.database}",
            lambda: client.postgres.get_database(paths.database),
            f"'databricks postgres list-databases {paths.branch}' names its databases",
        ),
    ]


def _fit_lakebase_endpoint(client: WorkspaceClient, path: str) -> object:
    """The endpoint, or `Unfit` when the app could not write through it."""
    endpoint = client.postgres.get_endpoint(path)
    status = getattr(endpoint, "status", None)
    kind = getattr(getattr(status, "endpoint_type", None), "value", "")
    if kind == READ_ONLY:
        raise Unfit(ENDPOINT_READ_ONLY)
    if getattr(status, "disabled", False):
        raise Unfit(ENDPOINT_DISABLED)
    return endpoint


def _group(client: WorkspaceClient, display: str) -> object:
    from databricks.sdk.errors import PermissionDenied

    try:
        found = list(client.groups.list(filter=f'displayName eq "{display}"'))
    except PermissionDenied:
        # The profile may not list workspace groups: unknown, not missing,
        # and not a reason to stop the deploy (W5).
        print(f"UNKNOWN group {display}: this profile may not list workspace groups")
        return UNKNOWN
    if not found:
        raise OSError(display)
    return found[0]


if __name__ == "__main__":
    sys.exit(main())

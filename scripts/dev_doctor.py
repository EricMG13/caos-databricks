#!/usr/bin/env python3
"""Check local development prerequisites without exposing configuration values."""

from __future__ import annotations

import os
import re
import subprocess  # nosec B404
import sys

# Commands below are fixed version probes; they never accept input or use a shell.
PYTHON_VERSION = sys.version_info[:2]
REQUIRED_CONFIGURATION = frozenset(
    {
        "CAOS_DATABASE_URL",
        "CAOS_TEST_POSTGRES_URL",
        "CAOS_BLOB_ROOT",
        "CAOS_TRUST_ROLE_HEADER",
        "CAOS_REQUIRE_POSTGRES",
    }
)
LIVE_CONFIGURATION = frozenset(
    {
        "CAOS_QUALIFY_POSTGRES_URL",
        # The gateway endpoint and its dated price: the worker and
        # `scripts/qualify.py` refuse PROVIDER_NOT_CONFIGURED without them.
        "CAOS_MODEL_ENDPOINT",
        "CAOS_MODEL_PRICE",
        "CAOS_REASONING_EFFORT",
        "CAOS_REQUIRE_PROVIDER",
        # Test-only: the OpenRouter adapter under tests/ reads the key.
        "OPENROUTER_API_KEY",
        # The ceiling is read by the live suite alone.
        "CAOS_RUN_CEILING",
    }
)
# Set by the bundle and the platform on Databricks Apps (docs/DEPLOYMENT.md);
# absent in local dev work.
DEPLOYMENT_CONFIGURATION = frozenset(
    {
        "CAOS_SITE_ROOT",
        "CAOS_BIND_HOST",
        "CAOS_WORKER_IN_PROCESS",
        "CAOS_PUBLIC_ORIGIN",
        "CAOS_LAKEBASE_INSTANCE",
        "CAOS_GROUP_ADMIN",
        "CAOS_GROUP_ANALYST",
        "DATABRICKS_APP_NAME",
    }
)
OPTIONAL_CONFIGURATION = LIVE_CONFIGURATION | DEPLOYMENT_CONFIGURATION
DEV_ROLES = frozenset({"READER", "ANALYST", "ADMIN"})
# The same canonical form the dev proxy in frontend/vite.config.ts accepts.
DEV_USER = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.IGNORECASE
)


def _dev_actor() -> bool:
    """Check the dev UI proxy's local actor; never print either value."""
    user = os.environ.get("CAOS_DEV_USER")
    role = os.environ.get("CAOS_DEV_ROLE") or "ANALYST"
    print(f"CAOS_DEV_USER: {'present' if user else 'absent (dev UI answers 401)'}")
    healthy = True
    if user and DEV_USER.fullmatch(user) is None:
        print("CAOS_DEV_USER must be a UUID", file=sys.stderr)
        healthy = False
    if role not in DEV_ROLES:
        print("CAOS_DEV_ROLE must be READER, ANALYST or ADMIN", file=sys.stderr)
        healthy = False
    return healthy


def _version(command: list[str]) -> str:
    try:
        # The caller supplies only the fixed command lists in `_tool_versions`.
        result = subprocess.run(  # nosec B603
            command,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
        )
    except (FileNotFoundError, subprocess.CalledProcessError):
        return "missing"
    return next(iter(result.stdout.strip().splitlines()), "missing")


def _tool_versions() -> list[tuple[str, str]]:
    return [
        ("node", _version(["node", "--version"]).removeprefix("v")),
        ("npm", _version(["npm", "--version"])),
        ("uv", _version(["uv", "--version"]).removeprefix("uv ").split()[0]),
        (
            "docker",
            _version(["docker", "--version"])
            .removeprefix("Docker version ")
            .split(",")[0],
        ),
        (
            "docker compose",
            _version(["docker", "compose", "version"])
            .removeprefix("Docker Compose version ")
            .removeprefix("v"),
        ),
        (
            "pre-commit",
            _version([".venv/bin/pre-commit", "--version"]).removeprefix("pre-commit "),
        ),
        (
            "databricks",
            _version(["databricks", "--version"]).removeprefix("Databricks CLI "),
        ),
    ]


def main() -> int:
    healthy = True
    found_python = ".".join(map(str, PYTHON_VERSION))
    print(f"Python: {found_python}")
    if PYTHON_VERSION != (3, 13):
        print(f"Python 3.13 required; found {found_python}", file=sys.stderr)
        healthy = False

    tools = _tool_versions()
    for name, version in tools:
        print(f"{name}: {version}")
        if version == "missing":
            healthy = False
    versions = dict(tools)
    node_version = versions.get("node", "missing")
    if not node_version.startswith("24."):
        print(f"Node 24 required; found {node_version}", file=sys.stderr)
        healthy = False

    for name in sorted(REQUIRED_CONFIGURATION):
        present = bool(os.environ.get(name))
        print(f"{name}: {'present' if present else 'missing'}")
        healthy &= present
    healthy &= _dev_actor()
    for name in sorted(OPTIONAL_CONFIGURATION):
        state = "present" if os.environ.get(name) else "absent"
        where = "optional live mode" if name in LIVE_CONFIGURATION else "deployment"
        print(f"{name}: {state} ({where})")
    return 0 if healthy else 1


if __name__ == "__main__":
    raise SystemExit(main())

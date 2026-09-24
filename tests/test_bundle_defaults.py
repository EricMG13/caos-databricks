"""`databricks.yml` is the one source of the bundle's defaults (N23, N5).

Review 4 found three gaps in F245's single source: preflight still spelled
both group defaults itself; the one command's `:=` eval let an inherited
MODEL_ENDPOINT, MODEL_PRICE or RUN_CEILING silently replace the bundle's
default for arguments 5 to 7; and an inline `# comment` after a default was
read into its value.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import bundle_defaults
import preflight
import pytest
from test_workspace_stub import stub
from workspace_stub import ENDPOINT, GROUP_ANALYST, LAKEBASE_PROJECT, WorkspaceStub

__all__ = ["stub"]

VARIABLES = """\
bundle:
  name: caos

variables:
  model_endpoint:
    description: The endpoint.
    default: databricks-claude-opus-5  # the gateway endpoint
  run_ceiling:
    default: "100.00"  # D29
  group_admin:
    default: 'caos-admins'   # quoted the other way
  group_analyst:
    default: analysts#one  # a hash inside a plain value is part of it

resources:
  apps: {}
"""


def test_an_inline_comment_is_not_part_of_a_default(tmp_path: Path) -> None:
    (tmp_path / "databricks.yml").write_text(VARIABLES, encoding="utf-8")
    assert bundle_defaults.defaults(tmp_path) == {
        "model_endpoint": "databricks-claude-opus-5",
        "run_ceiling": "100.00",
        "group_admin": "caos-admins",
        "group_analyst": "analysts#one",
    }


def test_the_environment_sets_only_what_the_one_command_lists(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Arguments 5 to 7 -- the endpoint, price and run ceiling -- are never
    read from the environment: an inherited MODEL_PRICE once replaced the
    bundle's default price unannounced. The names the header lists as
    environment values still are."""
    assert bundle_defaults.main(["--shell"]) == 0
    script = capsys.readouterr().out
    bash = shutil.which("bash")
    assert bash is not None
    shown = '"$MODEL_ENDPOINT" "$MODEL_PRICE" "$RUN_CEILING" "$GROUP_ADMIN" '
    shown += '"$GROUP_ANALYST" "$LAKEBASE_BRANCH"'
    inherited = {
        "PATH": os.environ["PATH"],
        "MODEL_ENDPOINT": "inherited-endpoint",
        "MODEL_PRICE": "inherited-endpoint,1,1,2026-01-01",
        "RUN_CEILING": "1.00",
        "GROUP_ADMIN": "Research, Credit",
        "LAKEBASE_BRANCH": "staging",
    }
    done = subprocess.run(
        [bash, "-c", f"set -euo pipefail\n{script}printf '%s|' {shown}"],
        env=inherited,
        capture_output=True,
        text=True,
        check=True,
    )
    values = bundle_defaults.defaults()
    assert done.stdout.split("|")[:-1] == [
        values["model_endpoint"],
        values["model_price"],
        values["run_ceiling"],
        "Research, Credit",
        values["group_analyst"],
        "staging",
    ]


def test_preflight_takes_its_group_defaults_from_the_bundle(
    stub: WorkspaceStub,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setitem(preflight._DEFAULTS, "group_admin", "bundle-admins")
    stub.groups = frozenset({"bundle-admins", GROUP_ANALYST})
    flags = ["--endpoint", ENDPOINT, "--catalog", "main", "--schema", "caos"]
    assert preflight.main([*flags, "--lakebase-project", LAKEBASE_PROJECT]) == 0
    assert "ok      group bundle-admins" in capsys.readouterr().out.splitlines()

"""Does a `databricks` CLI release panic on the DF-13 state? One command to know.

CLI 1.17.0 panics (`OverrideChangeDesc`) on `bundle deploy` over state that
names an app the workspace lacks, when that app's configuration has changed.
The stand-in is such a workspace on every run: new and empty, beside
`.databricks/bundle` state an earlier run left. `workspace_stub.fresh_state`
clears that state so the pinned CLI never meets it (DF-13); this probe skips
the clearing on purpose, so the next CLI release can be tried against the
state itself (N47's CLI half, N234):

    uv run python tests/cli_panic_probe.py [--cli-dir DIR] [--target dev]

It deploys the bundle twice, each time to a new, empty loopback stub and over
the state the first left, the model price rotated between the two (a changed
app configuration), and exits 0 when both deploys succeed, 1 when one panics or fails,
2 with nothing run when it may not (a real workspace's state under
`.databricks`, a profile or a bundle naming a workspace of its own, no CLI).
`--cli-dir` puts a directory with the candidate `databricks` first on PATH.
Raise `databricks_cli_version`, the `setup-cli` pin and `check_gate_config.py`'s
pin together once a release passes it.

Only the loopback stub is ever the workspace: inherited auth variables are
dropped and the CLI's config file is a private, empty one, the way
`workspace_stub.run_against` runs it. No model call is made.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
# Two dated prices of the bundle's `model_price` form; the second is the
# rotation the first deploy's state meets.
PRICES = (
    "databricks-claude-opus-5,0.000007,0.000030,2026-09-23",
    "databricks-claude-opus-5,0.000008,0.000031,2026-09-24",
)
# What the CLI's crash prints: Go's own word, and the function that fails.
PANIC_MARKS = ("panic", "OverrideChangeDesc")
VARIABLES = (
    "--var", "uc_catalog=main", "--var", "uc_schema=caos",
    "--var", "lakebase_project=caos",
)  # fmt: skip
HEAD_LINES = 12


@dataclass(frozen=True)
class Deploy:
    """One deploy: the CLI's exit code, whether it panicked, its first lines."""

    code: int
    panicked: bool
    head: str


def panicked(text: str) -> bool:
    """Whether CLI output carries a panic (`PANIC_MARKS`, any case for the
    word, the function name exactly)."""
    return any(
        mark in text if mark[0].isupper() else mark in text.lower()
        for mark in PANIC_MARKS
    )


def _deploy(root: Path, target: str, price: str, cli_dir: Path | None) -> Deploy | str:
    """Deploy to a new, empty stub with `price`, over whatever state is
    under `root`; or why it may not run."""
    from workspace_stub import WorkspaceStub, _refused, stand_in_environment

    path = os.environ.get("PATH", "")
    if cli_dir is not None:
        path = f"{cli_dir}{os.pathsep}{path}"
    cli = shutil.which("databricks", path=path)
    if cli is None:
        return "probe: no databricks CLI on PATH"
    command = [cli, "bundle", "deploy", "-t", target, *VARIABLES]
    refused = _refused(command)
    if refused:
        return refused
    stub = WorkspaceStub()
    with stub.serving(), tempfile.TemporaryDirectory() as private:
        config_file = Path(private) / "empty.databrickscfg"
        config_file.write_text("", encoding="utf-8")
        env = stand_in_environment(dict(os.environ), stub)
        env["PATH"] = path
        env["DATABRICKS_CONFIG_FILE"] = str(config_file)
        env["BUNDLE_VAR_model_price"] = price
        if not env["DATABRICKS_HOST"].startswith("http://127.0.0.1:"):
            return "probe: the stub is not on loopback"
        done = subprocess.run(
            command, cwd=root, env=env, capture_output=True, text=True, check=False
        )
    text = done.stdout + done.stderr
    head = "\n".join(text.splitlines()[:HEAD_LINES])
    return Deploy(done.returncode, panicked(text), head)


def probe(root: Path, target: str, cli_dir: Path | None = None) -> list[Deploy] | str:
    """The two deploys, or why nothing ran. Starts and ends with no stand-in
    state under `root`; a real workspace's state is never touched."""
    from workspace_stub import fresh_state

    kept = fresh_state(root)
    if kept:
        return (
            f"probe: .databricks/bundle/{kept[0]} holds a real workspace's "
            "state; move .databricks aside before a probe"
        )
    deploys: list[Deploy] = []
    try:
        for price in PRICES:
            deployed = _deploy(root, target, price, cli_dir)
            if isinstance(deployed, str):
                return deployed
            deploys.append(deployed)
    finally:
        fresh_state(root)
    return deploys


def main(argv: list[str] | None = None) -> int:
    for entry in (str(REPO / "scripts"), str(REPO / "tests")):
        if entry not in sys.path:
            sys.path.insert(0, entry)
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--target", default="dev")
    parser.add_argument("--cli-dir", type=Path, default=None)
    args = parser.parse_args(argv)
    os.chdir(REPO)
    result = probe(REPO, args.target, args.cli_dir)
    if isinstance(result, str):
        print(result, file=sys.stderr)
        return 2
    for number, deploy in enumerate(result, 1):
        verdict = "panic" if deploy.panicked else "no panic"
        print(f"deploy {number}: exit {deploy.code}, {verdict}")
        if deploy.panicked or deploy.code:
            print(deploy.head)
    # A deploy that fails without a panic proves nothing about the panic.
    return 1 if any(deploy.panicked or deploy.code for deploy in result) else 0


if __name__ == "__main__":
    sys.exit(main())

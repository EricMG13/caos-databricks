"""`scripts/enterprise_deploy.sh` against the loopback workspace and the app
booted the platform way (D28, F31): the CLI on the path is a recorder, every
other step is the real one over HTTP, and the rows say what happened."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from urllib.parse import urlparse

import enterprise_deploy
from enterprise_deploy import Evidence, Row
from platform_app import REPO, PlatformApp
from test_platform_boot import app, stub
from workspace_stub import BEARER, ENDPOINT, PRICE, WorkspaceStub

__all__ = ["app", "stub"]


def test_the_one_command_runs_the_cli_and_verifies_the_deployment(
    app: PlatformApp, stub: WorkspaceStub, empty_database: str, tmp_path: Path
) -> None:
    parts = urlparse(empty_database)
    stub.instance_host = parts.hostname or "127.0.0.1"
    stub.user_name = parts.username or "postgres"  # Lakebase mints for the caller
    calls = tmp_path / "cli-calls.txt"
    shim = tmp_path / "bin"
    shim.mkdir()
    recorder = f'#!/usr/bin/env bash\nprintf "%s\\n" "$*" >> "{calls}"\n'
    (shim / "databricks").write_text(recorder + 'echo "Validation OK!"\n')
    (shim / "databricks").chmod(0o755)
    evidence = tmp_path / "enterprise"
    env = {
        **os.environ,
        **stub.environment(),
        "PATH": f"{shim}{os.pathsep}{os.environ['PATH']}",
        "EVIDENCE": str(evidence),
        "TARGET": "dev",
        "LAKEBASE_DATABASE": parts.path.lstrip("/"),
        "PG_PORT": str(parts.port),
        "PG_SSLMODE": "disable",
        "MLFLOW_DISABLE_AGENT_HINT": "1",
    }
    env.pop("DATABRICKS_CONFIG_PROFILE", None)
    done = subprocess.run(
        [
            str(REPO / "scripts/enterprise_deploy.sh"),
            "",
            "main",
            "caos",
            "caos-lb",
            ENDPOINT,
            PRICE,
        ],
        cwd=REPO,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert done.returncode == 0, done.stdout + done.stderr
    rows = [
        line.split("\t")
        for line in (evidence / "evidence.tsv").read_text().splitlines()
    ]
    assert [row[0] for row in rows] == [f"E{n}" for n in range(1, 10)]
    assert all(row[2] == "0" for row in rows), rows
    seen = calls.read_text().splitlines()
    assert [line.split(" -t ")[0] for line in seen] == [
        "bundle validate",
        "bundle deploy",
        "bundle run caos",
    ]
    assert all("--var run_ceiling=25.00" in line and "-p" not in line for line in seen)
    assert "json_mode=accepted" in (evidence / "E7.log").read_text()
    assert "PostgreSQL" in (evidence / "E8.log").read_text()
    assert "first frame" in rows[-1][3]
    assert f"deployed: {app.url}" in done.stdout
    everything = "".join(p.read_text() for p in evidence.iterdir()) + done.stdout
    assert parts.password and parts.password not in everything
    assert BEARER not in everything


def test_a_recorded_cli_step_is_one_row_with_the_log_tail(tmp_path: Path) -> None:
    log = tmp_path / "E2.out"
    log.write_text("Name: caos\n\nValidation OK!\n")
    code = enterprise_deploy.main(
        [
            "--stage",
            "record",
            "--evidence",
            str(tmp_path / "ev"),
            "--step",
            "E2",
            "--command",
            "databricks bundle validate",
            "--code",
            "0",
            "--log",
            str(log),
        ]
    )
    assert code == 0
    written = (tmp_path / "ev" / "evidence.tsv").read_text()
    assert written == "E2\tdatabricks bundle validate\t0\tValidation OK!\n"
    evidence = Evidence(tmp_path / "again")
    assert evidence.record("E3", "databricks bundle deploy", 7, "") == 7
    assert evidence.rows == [Row("E3", "databricks bundle deploy", 7, "")]

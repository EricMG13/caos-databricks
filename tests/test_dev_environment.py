"""Development setup stays reproducible, isolated, and secret-safe."""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

REPO = Path(__file__).resolve().parents[1]
TOOLS = [
    ("node", "24.1.0"),
    ("npm", "11.0.0"),
    ("uv", "0.12.0"),
    ("docker", "29.0.0"),
    ("docker compose", "5.2.0"),
    ("gitnexus", "1.6.9"),
    ("security Python", "3.12.12"),
    ("pre-commit", "4.6.2"),
]


def _load_doctor() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "dev_doctor", REPO / "scripts" / "dev_doctor.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_doctor_reports_presence_without_secret_values(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    doctor = _load_doctor()
    sentinel = "synthetic-do-not-print-93fc"
    for name in doctor.REQUIRED_CONFIGURATION | doctor.OPTIONAL_CONFIGURATION:
        monkeypatch.setenv(name, sentinel)
    monkeypatch.setattr(doctor, "_tool_versions", lambda: TOOLS)

    assert doctor.main() == 0
    captured = capsys.readouterr()
    assert sentinel not in captured.out + captured.err
    assert "CAOS_DATABASE_URL: present" in captured.out
    assert "OPENROUTER_API_KEY: present (optional live mode)" in captured.out
    assert "CAOS_MODEL_PRICE: present (optional live mode)" in captured.out
    assert "CAOS_SITE_ROOT: present (deployment)" in captured.out


def test_deployment_and_live_configuration_do_not_overlap() -> None:
    doctor = _load_doctor()
    assert doctor.LIVE_CONFIGURATION.isdisjoint(doctor.DEPLOYMENT_CONFIGURATION)
    assert doctor.OPTIONAL_CONFIGURATION == (
        doctor.LIVE_CONFIGURATION | doctor.DEPLOYMENT_CONFIGURATION
    )


def test_doctor_rejects_the_wrong_runtime(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    doctor = _load_doctor()
    monkeypatch.setattr(doctor, "PYTHON_VERSION", (3, 13))
    monkeypatch.setattr(doctor, "_tool_versions", lambda: TOOLS)
    for name in doctor.REQUIRED_CONFIGURATION:
        monkeypatch.setenv(name, "configured")

    assert doctor.main() == 1
    assert "Python 3.14 required; found 3.13" in capsys.readouterr().err


def test_empty_tool_output_is_reported_as_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    doctor = _load_doctor()
    monkeypatch.setattr(
        doctor.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(stdout=""),
    )

    assert doctor._version(["node", "--version"]) == "missing"


def test_malformed_runtime_versions_fail_without_a_traceback(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    doctor = _load_doctor()
    malformed = [
        (name, "not-a-version" if name in {"node", "security Python"} else value)
        for name, value in TOOLS
    ]
    monkeypatch.setattr(doctor, "_tool_versions", lambda: malformed)
    for name in doctor.REQUIRED_CONFIGURATION:
        monkeypatch.setenv(name, "configured")

    assert doctor.main() == 1
    captured = capsys.readouterr()
    assert "Node 24 required; found not-a-version" in captured.err
    assert "security Python 3.12 required; found not-a-version" in captured.err
    assert "Traceback" not in captured.out + captured.err


def test_index_fails_closed_when_gitnexus_is_not_installed() -> None:
    result = subprocess.run(
        ["make", "--no-print-directory", "index"],
        cwd=REPO,
        env={"PATH": "/usr/bin:/bin"},
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "gitnexus is required; install it before indexing" in result.stderr
    assert "npx" not in result.stdout + result.stderr
    assert "pnpm" not in result.stdout + result.stderr


def test_make_doctor_uses_the_bootstrapped_python(
    tmp_path: Path,
) -> None:
    (tmp_path / "Makefile").write_text(
        (REPO / "Makefile").read_text(encoding="utf-8"), encoding="utf-8"
    )
    project_bin = tmp_path / ".venv" / "bin"
    project_bin.mkdir(parents=True)
    (project_bin / "python").symlink_to(sys.executable)
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    (scripts / "dev_doctor.py").write_text(
        'print("project interpreter selected")\n', encoding="utf-8"
    )
    ambient_python = tmp_path / "python3"
    ambient_python.write_text("#!/bin/sh\nexit 93\n", encoding="utf-8")
    ambient_python.chmod(0o755)
    environment = os.environ.copy()
    environment["PATH"] = f"{tmp_path}:{environment['PATH']}"

    result = subprocess.run(
        ["make", "--no-print-directory", "doctor"],
        cwd=tmp_path,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert result.stdout.strip() == "project interpreter selected"


def test_compose_keeps_dev_and_test_storage_isolated() -> None:
    compose = (REPO / "compose.yaml").read_text(encoding="utf-8")

    digest = "18cfe3ef5e6815560c98237d6216d1e5119702fb0f3894c8785dd58b8bbe5d73"
    assert f"postgres@sha256:{digest}" in compose
    assert '"127.0.0.1:55436:5432"' in compose
    assert '"127.0.0.1:55437:5432"' in compose
    assert "caos-workbench-dev-postgres" in compose
    assert "tmpfs:" in compose
    assert "caos_app" in (REPO / "scripts" / "dev-init.sql").read_text(encoding="utf-8")


def test_make_dev_worker_runs_the_worker_entry_point(tmp_path: Path) -> None:
    (tmp_path / "Makefile").write_text(
        (REPO / "Makefile").read_text(encoding="utf-8"), encoding="utf-8"
    )
    project_bin = tmp_path / ".venv" / "bin"
    project_bin.mkdir(parents=True)
    (project_bin / "python").symlink_to(sys.executable)
    engine = tmp_path / "server" / "engine"
    engine.mkdir(parents=True)
    (tmp_path / "server" / "__init__.py").write_text("", encoding="utf-8")
    (engine / "__init__.py").write_text("", encoding="utf-8")
    (engine / "worker.py").write_text(
        'print("worker entry point selected")\n', encoding="utf-8"
    )
    environment = {"PATH": os.environ["PATH"], "PYTHONDONTWRITEBYTECODE": "1"}

    result = subprocess.run(
        ["make", "--no-print-directory", "dev-worker"],
        cwd=tmp_path,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip().splitlines()[-1] == "worker entry point selected"


def test_make_dev_api_serves_the_guarded_site_on_loopback_without_proxy_headers(
    tmp_path: Path,
) -> None:
    """`make dev-api` names the guarded site, not the bare app, with the flag
    that makes the edge guard's loopback check read the real socket peer.

    The stub replaces `.venv/bin/python` itself rather than a module: the
    Makefile invokes `uvicorn` as `python -m uvicorn ...`, and what this test
    checks is the exact command line that reaches it, not uvicorn's own
    behaviour.
    """
    (tmp_path / "Makefile").write_text(
        (REPO / "Makefile").read_text(encoding="utf-8"), encoding="utf-8"
    )
    project_bin = tmp_path / ".venv" / "bin"
    project_bin.mkdir(parents=True)
    stub = project_bin / "python"
    stub.write_text('#!/bin/sh\necho "$@"\n', encoding="utf-8")
    stub.chmod(0o755)
    environment = {"PATH": os.environ["PATH"]}

    result = subprocess.run(
        ["make", "--no-print-directory", "dev-api"],
        cwd=tmp_path,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    printed = result.stdout.strip()
    assert "-m uvicorn caos.api.site:application" in printed
    assert "caos.api.app:app" not in printed
    assert "--host 127.0.0.1 --port 8000" in printed
    assert "--no-proxy-headers" in printed


def test_the_smoke_stack_is_disposable_and_isolated_from_dev_storage() -> None:
    """`compose.smoke.yaml` never touches the persistent dev database or its
    published ports, and its own database is disposable `tmpfs`."""
    smoke = (REPO / "compose.smoke.yaml").read_text(encoding="utf-8")
    dev = (REPO / "compose.yaml").read_text(encoding="utf-8")

    assert "caos-workbench-smoke" in smoke
    assert "tmpfs:" in smoke
    assert "caos-workbench-dev-postgres" not in smoke
    assert ".dev-data" not in smoke
    assert "55436" not in smoke
    assert "55437" not in smoke
    # The smoke stack's own volume name never collides with the dev volume.
    assert "smoke-blobs" in smoke
    # The dev volume this proves isolation from.
    assert "caos-workbench-dev-postgres" in dev


def test_doctor_names_every_variable_the_worker_and_edge_read() -> None:
    """An operator learns a variable exists from the doctor and the example,
    not from the failure it causes."""
    doctor = _load_doctor()
    example = (REPO / ".env.example").read_text(encoding="utf-8")

    for name in (
        "CAOS_MODEL_PRICE",
        "CAOS_LIVE_BUDGET_CEILING",
        "CAOS_SITE_ROOT",
        "CAOS_EDGE_TOKEN",
        "CAOS_PUBLIC_ORIGIN",
    ):
        assert name in doctor.REQUIRED_CONFIGURATION | doctor.OPTIONAL_CONFIGURATION, (
            name
        )
        assert name in example, name

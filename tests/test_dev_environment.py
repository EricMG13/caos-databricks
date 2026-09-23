"""Development setup stays reproducible, isolated, and secret-safe."""

from __future__ import annotations

import importlib.util
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
    ("pre-commit", "4.6.2"),
    ("databricks", "v1.17.0"),
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
    assert "CAOS_MODEL_ENDPOINT: present (optional live mode)" in captured.out
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
    monkeypatch.setattr(doctor, "PYTHON_VERSION", (3, 14))
    monkeypatch.setattr(doctor, "_tool_versions", lambda: TOOLS)
    for name in doctor.REQUIRED_CONFIGURATION:
        monkeypatch.setenv(name, "configured")

    assert doctor.main() == 1
    assert "Python 3.13 required; found 3.14" in capsys.readouterr().err


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
        (name, "not-a-version" if name == "node" else value) for name, value in TOOLS
    ]
    monkeypatch.setattr(doctor, "_tool_versions", lambda: malformed)
    for name in doctor.REQUIRED_CONFIGURATION:
        monkeypatch.setenv(name, "configured")

    assert doctor.main() == 1
    captured = capsys.readouterr()
    assert "Node 24 required; found not-a-version" in captured.err
    assert "Traceback" not in captured.out + captured.err


def test_compose_keeps_dev_and_test_storage_isolated() -> None:
    compose = (REPO / "compose.yaml").read_text(encoding="utf-8")

    digest = "18cfe3ef5e6815560c98237d6216d1e5119702fb0f3894c8785dd58b8bbe5d73"
    assert f"postgres@sha256:{digest}" in compose
    assert '"127.0.0.1:55436:5432"' in compose
    assert '"127.0.0.1:55437:5432"' in compose
    assert "caos-workbench-dev-postgres" in compose
    assert "tmpfs:" in compose
    assert "caos_app" in (REPO / "scripts" / "dev-init.sql").read_text(encoding="utf-8")


def test_doctor_names_every_variable_the_worker_and_edge_read() -> None:
    """An operator learns a variable exists from the doctor and the example,
    not from the failure it causes."""
    doctor = _load_doctor()
    example = (REPO / ".env.example").read_text(encoding="utf-8")

    for name in (
        "CAOS_MODEL_ENDPOINT",
        "CAOS_MODEL_PRICE",
        "CAOS_RUN_CEILING",
        "CAOS_SITE_ROOT",
        "CAOS_LAKEBASE_INSTANCE",
        "CAOS_PUBLIC_ORIGIN",
    ):
        assert name in doctor.REQUIRED_CONFIGURATION | doctor.OPTIONAL_CONFIGURATION, (
            name
        )
        assert name in example, name

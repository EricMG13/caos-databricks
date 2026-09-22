"""The gate configuration cannot be loosened, and suppressions only fall (G16)."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import check_gate_config

REPO = Path(__file__).resolve().parents[1]


def _tree(tmp_path: Path) -> Path:
    """A copy of the configuration files and parity manifests, to tamper with."""
    root = tmp_path / "repo"
    for name in ("pyproject.toml", ".python-version", ".pre-commit-config.yaml"):
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(REPO / name, root / name)
    for group in check_gate_config.PARITY_GROUPS:
        manifest = REPO / "tests" / "parity" / "golden" / group / "manifest.json"
        target = root / "tests" / "parity" / "golden" / group / "manifest.json"
        target.parent.mkdir(parents=True)
        if manifest.is_file():
            shutil.copy(manifest, target)
        else:
            target.write_text('{"placeholder": "x"}')
    return root


def test_the_committed_configuration_holds() -> None:
    assert check_gate_config.configuration_problems() == []
    assert check_gate_config.suppression_problems() == []
    assert check_gate_config.main([]) == 0


def test_every_loosening_is_named(tmp_path: Path) -> None:
    root = _tree(tmp_path)
    text = (root / "pyproject.toml").read_text(encoding="utf-8")
    text = text.replace("max-complexity = 10", "max-complexity = 11")
    text = text.replace("--cov-fail-under=80", "--cov-fail-under=70")
    text = text.replace("strict = true", "strict = false")
    text = text.replace(
        'requires-python = ">=3.13,<3.14"', 'requires-python = ">=3.12"'
    )
    text = text.replace('"BLE", ', "")
    (root / "pyproject.toml").write_text(text, encoding="utf-8")
    (root / "requirements.txt").write_text("fastapi\n")
    (root / ".python-version").write_text("3.12\n")
    shutil.rmtree(root / "tests" / "parity" / "golden" / "routes")
    problems = check_gate_config.configuration_problems(root)
    for expected in (
        "ruff: a rule family was dropped",
        "ruff: mccabe max-complexity is not 10",
        "mypy: strict is off",
        "pytest: --cov-fail-under=80 missing from addopts",
        "requires-python moved",
        ".python-version moved",
        "requirements.txt present at the root (switches Apps to pip)",
        "parity: routes has no manifest",
    ):
        assert expected in problems, problems


def test_a_rising_suppression_count_fails(tmp_path: Path) -> None:
    counts = check_gate_config.suppression_counts()
    assert counts["noqa"] > 0, "the tree carries suppressions to budget"
    zero = tmp_path / "baseline.json"
    zero.write_text(json.dumps(dict.fromkeys(counts, 0)))
    risen = check_gate_config.suppression_problems(baseline=zero)
    assert any(problem.startswith("suppressions: noqa rose") for problem in risen)
    missing = tmp_path / "absent.json"
    assert check_gate_config.suppression_problems(baseline=missing) == [
        "baseline: tests/gate_baseline.json unreadable"
    ]

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
    for name in (
        "pyproject.toml",
        ".python-version",
        ".pre-commit-config.yaml",
        "databricks.yml",
        "app.yaml",
        ".github/workflows/ci.yml",
    ):
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


def test_the_suppression_grammar_is_each_tool_s_own() -> None:
    """F58: the spellings the tools honour are the spellings the gate counts.
    The sample is assembled so this file carries none of them itself."""
    hash_ = "#"
    sample = "\n".join(
        [
            f"import os  {hash_} " + "NOQA",
            f"x = 1  {hash_} " + "noqa: E501",
            f"def f():  {hash_} " + "pragma: nocover",
            f"    pass  {hash_}" + "pragma no cover",
            "@pytest." + "mark.skipif(True, reason='x')",
            "@mark." + "skip",
            "pytest." + "skip('y')",
            "pytest." + "importorskip('z')",
            "@mark." + "xfail",
        ]
    )
    found = {
        name: len(pattern.findall(sample))
        for name, pattern in check_gate_config.SUPPRESSIONS.items()
    }
    assert found == {
        "noqa": 2,
        "type_ignore": 0,
        "nosec": 0,
        "no_cover": 2,
        "skip": 4,
        "xfail": 1,
    }


def test_a_sync_exclude_that_hides_the_methodology_is_named(tmp_path: Path) -> None:
    """F48: `*.md` took every SKILL.md and prompt block out of the app."""
    root = _tree(tmp_path)
    bundle = root / "databricks.yml"
    assert check_gate_config._bundle_problems(root) == []
    bundle.write_text(
        bundle.read_text().replace("  exclude:\n", '  exclude:\n    - "*.md"\n')
    )
    problems = check_gate_config._bundle_problems(root)
    assert any("'*.md' hides vendor/deploy-v/CANON_SHARED.md" in p for p in problems)
    assert any("hides icm/shared/prompt/instruction.md" in p for p in problems)
    (root / "app.yaml").write_text("command: [x]\nenv:\n  - name: A\n    value: b\n")
    assert any(
        p.startswith("app.yaml: sets env")
        for p in check_gate_config._bundle_problems(root)
    )
    m = check_gate_config._matches
    assert m("*.md", "vendor/deploy-v/skills/x/SKILL.md")
    assert not m("frontend/*.html", "frontend/dist/index.html")
    assert m("tests/**", "tests/a/b.py") and not m("scripts/**", "caos/serve.py")
    assert m("CLAUDE.md", "CLAUDE.md") and not m("CLAUDE.md", "icm/CONTEXT.md")


def test_the_goldens_must_come_from_the_legacy_snapshot_and_not_shrink(
    tmp_path: Path,
) -> None:
    """F57: a golden regenerated from the rebuilt package matches a regression."""
    root = _tree(tmp_path)
    assert check_gate_config._parity_problems(root) == []
    manifest = root / "tests" / "parity" / "golden" / "render" / "manifest.json"
    document = json.loads(manifest.read_text())
    document["package"] = "caos"
    manifest.write_text(json.dumps(document))
    assert (
        "parity: render was not written from server"
        in check_gate_config._parity_problems(root)
    )
    document["package"] = "server"
    document["cases"] = dict(list(document["cases"].items())[:1])
    manifest.write_text(json.dumps(document))
    assert any(
        "render fell below" in p for p in check_gate_config._parity_problems(root)
    )


def test_a_budget_may_not_rise_against_the_base_branch_and_shipping_is_checked(
    tmp_path: Path,
) -> None:
    """F58 and F48: the PR that breaches a budget cannot rewrite it, and the
    CLI's own deployment record must list what the app needs."""
    now = json.loads(check_gate_config.BASELINE.read_text())
    base = tmp_path / "base.json"
    base.write_text(json.dumps({**now, "noqa": now["noqa"] - 1}))
    assert check_gate_config.baseline_problems(base) == [
        f"baseline: noqa rose to {now['noqa']} (base branch {now['noqa'] - 1})"
    ]
    base.write_text(json.dumps(now))
    assert check_gate_config.baseline_problems(base) == []
    assert check_gate_config.main(["--against", str(base)]) == 0
    record = tmp_path / "deployment.json"
    files = [{"local_path": path} for path in check_gate_config.SHIPPED]
    record.write_text(json.dumps({"files": files}))
    assert check_gate_config.shipped_problems(record) == []
    assert check_gate_config.main(["--shipped", str(record)]) == 0
    record.write_text(json.dumps({"files": files[1:]}))
    assert check_gate_config.shipped_problems(record) == [
        f"shipped: {check_gate_config.SHIPPED[0]} was not synced"
    ]
    assert check_gate_config._gitleaks_problems(check_gate_config.REPO) == []

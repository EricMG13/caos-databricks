"""The gate configuration cannot be loosened, and suppressions only fall (G16)."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import check_gate_config
from tracked import tracked_files

REPO = Path(__file__).resolve().parents[1]


def _git(root: Path, *args: str) -> None:
    git = shutil.which("git")
    assert git is not None
    subprocess.run([git, *args], cwd=root, check=True, capture_output=True)


def _tree(tmp_path: Path) -> Path:
    """A copy of the configuration files and parity manifests, to tamper
    with, as a repository: the gate reads what git tracks."""
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
    _git(root, "init", "-q")
    _git(root, "add", "-A")
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


def test_the_suppression_count_is_a_ratchet(tmp_path: Path) -> None:
    """F58 and DF-11: a count above the baseline is a new suppression, and a
    count below it is room a later change could spend unseen; either fails
    until the baseline is the count."""
    counts = check_gate_config.suppression_counts()
    assert counts["noqa"] > 0, "the tree carries suppressions to budget"
    assert check_gate_config.suppression_problems() == []
    baseline = tmp_path / "baseline.json"
    baseline.write_text(json.dumps(dict.fromkeys(counts, 0)))
    risen = check_gate_config.suppression_problems(baseline=baseline)
    assert f"suppressions: noqa rose to {counts['noqa']} (baseline 0)" in risen
    baseline.write_text(json.dumps({**counts, "noqa": counts["noqa"] + 3}))
    assert check_gate_config.suppression_problems(baseline=baseline) == [
        f"suppressions: noqa fell to {counts['noqa']} (baseline "
        f"{counts['noqa'] + 3}): lower tests/gate_baseline.json to match"
    ]
    missing = tmp_path / "absent.json"
    assert check_gate_config.suppression_problems(baseline=missing) == [
        "baseline: tests/gate_baseline.json unreadable"
    ]


def test_a_raised_complexity_record_is_a_budget_that_rose(tmp_path: Path) -> None:
    """MAX-13: raising one function's recorded complexity in the snapshot
    (31 to 60) let it grow while the baselined count stayed the same; the
    total the snapshot allows is budgeted too."""
    snapshot = json.loads((REPO / check_gate_config.SNAPSHOT).read_text())
    counts = check_gate_config.suppression_counts()
    assert counts["complexity_baselined"] == sum(
        len(entry["functions"]) for entry in snapshot
    )
    snapshot[0]["functions"][0]["complexity"] += 29
    root = tmp_path / "tree"
    root.mkdir()
    _git(root, "init", "-q")
    (root / check_gate_config.SNAPSHOT).write_text(json.dumps(snapshot))
    raised = check_gate_config.suppression_counts(root)
    assert raised["complexity_baselined"] == counts["complexity_baselined"]
    assert raised["complexity_total"] == counts["complexity_total"] + 29


def test_the_suppression_grammar_is_each_tool_s_own() -> None:
    """F58 and MAX-13: the spellings the tools honour are the spellings the
    gate counts, the whole-file forms included. The sample is assembled so
    this file carries none of them itself."""
    hash_ = "#"
    sample = "\n".join(
        [
            f"import os  {hash_} " + "NOQA",
            f"x = 1  {hash_} " + "noqa: E501",
            f"{hash_} ruff: " + "noqa",
            f"{hash_} flake8: " + "noqa: E501",
            f"{hash_} my" + "py: ignore-errors",
            "@typing.no_type" + "_check",
            f"def f():  {hash_} " + "pragma: nocover",
            f"    pass  {hash_}" + "pragma no cover",
            f"if x:  {hash_} pragma: no " + "branch",
            "@pytest." + "mark.skipif(True, reason='x')",
            "@mark." + "skip",
            "pytest." + "skip('y')",
            "pytest." + "importorskip('z')",
            "@unittest." + "skip('u')",
            "self.skip" + "Test('v')",
            "raise unittest.Skip" + "Test",
            "@mark." + "xfail",
            "@unittest.expected" + "Failure",
        ]
    )
    found = {
        name: len(pattern.findall(sample))
        for name, pattern in check_gate_config.SUPPRESSIONS.items()
    }
    assert found == {
        "noqa": 2,
        "file_noqa": 2,
        "type_ignore": 0,
        "mypy_directive": 2,
        "nosec": 0,
        "no_cover": 3,
        "skip": 7,
        "xfail": 2,
    }


def test_a_gate_weakened_in_effect_is_named(tmp_path: Path) -> None:
    """MAX-13: a rule ignored, a second coverage floor after the first, a
    narrowed coverage source, a mypy override, a configuration file that
    shadows pyproject.toml, and CI drift (a gate step gone, a gate that
    cannot fail, a raised duplication threshold) each keep every threshold
    the old check read and weaken the gate anyway."""
    root = _tree(tmp_path)
    assert check_gate_config.configuration_problems(root) == []
    project = root / "pyproject.toml"
    text = project.read_text(encoding="utf-8")
    text = text.replace(
        "[tool.ruff.lint.mccabe]",
        'ignore = ["F821"]\nper-file-ignores = {"caos/*" = ["ANN"]}\n\n'
        "[tool.ruff.lint.mccabe]",
    )
    text = text.replace(
        "--cov-fail-under=80", "--cov-fail-under=80 --cov-fail-under=0 --ignore=tests"
    )
    text = text.replace('source = ["."]', 'source = ["caos.boundary_text"]')
    text += (
        '\n[[tool.mypy.overrides]]\nmodule = "caos.*"\nignore_errors = true\n'
        '\n[tool.coverage.report]\nexclude_also = ["def "]\n'
    )
    project.write_text(text, encoding="utf-8")
    (root / "caos").mkdir()
    (root / "caos" / "ruff.toml").write_text("[lint]\nignore = ['F']\n")
    _git(root, "add", "caos/ruff.toml")
    ci = root / ".github" / "workflows" / "ci.yml"
    ci_text = ci.read_text(encoding="utf-8")
    ci_text = ci_text.replace(
        "      - run: uv run python scripts/scan_floors.py coverage.xml --cobertura\n",
        "",
    )
    ci_text = ci_text.replace(
        "run: uv run mypy caos scripts tests",
        "run: uv run mypy caos scripts tests || true",
    )
    ci_text = ci_text.replace("jscpd --threshold 3", "jscpd --threshold 30")
    ci_text = ci_text.replace(
        "    timeout-minutes: 20\n",
        "    timeout-minutes: 20\n    continue-on-error: true\n",
        1,
    )
    ci.write_text(ci_text, encoding="utf-8")
    problems = check_gate_config.configuration_problems(root)
    for expected in (
        "ruff: lint.ignore is set; it can silence a rule",
        "ruff: lint.per-file-ignores is set; it can silence a rule",
        "pytest: addopts carries '--cov-fail-under=0'",
        "pytest: addopts carries '--ignore=tests'",
        "coverage: run.source is not as committed",
        "coverage: report is set; it can exclude what is measured",
        "mypy: overrides is not as committed",
        "caos/ruff.toml: overrides the committed tool configuration",
        "ci: no step runs 'uv run python scripts/scan_floors.py coverage.xml "
        "--cobertura'",
        "ci: no step runs 'uv run mypy caos scripts tests'",
        "ci: 'uv run mypy caos scripts tests || true' cannot fail",
        "ci: continue-on-error is set; a gate would pass whatever it finds",
    ):
        assert expected in problems, problems
    assert any("jscpd --threshold 3 " in p for p in problems), problems


def test_the_ci_file_s_commands_are_read_as_the_runner_runs_them() -> None:
    """A folded block is one command, a literal block one per line with its
    continuations joined, and the keys after a block are not part of it."""
    ci_text = "\n".join(
        [
            "    steps:",
            "      - run: >-",
            "          a b",
            "          c",
            "      - run: |",
            "          one \\",
            "            two",
            "          three",
            "        env:",
            "          X: y",
            "      - name: n",
            "        run: four",
        ]
    )
    assert check_gate_config.ci_commands(ci_text) == [
        "a b c",
        "one two",
        "three",
        "four",
    ]


def test_a_sync_exclude_is_refused_in_any_spelling(tmp_path: Path) -> None:
    """F48 and DQ-9: `*.md` took every SKILL.md and prompt block out of the
    app; a flow-style list, a character class and a runtime file outside a
    sample then passed the check. With an allowlist there is nothing to
    exclude, so any exclude, and any target's own sync, is refused."""
    root = _tree(tmp_path)
    bundle = root / "databricks.yml"
    assert check_gate_config._bundle_problems(root) == []
    written = bundle.read_text()
    refused = "bundle: an exclude is set; the sync is an allowlist"
    for spelling in (
        '  exclude:\n    - "*.md"\n',
        '  exclude: ["caos/qualification/**"]\n',
        "  exclude:\n    - caos/[q]ualification/**\n",
        "  exclude:\n    - caos/deliverable/render.py\n",
    ):
        bundle.write_text(written.replace("  include:\n", spelling + "  include:\n"))
        assert refused in check_gate_config._bundle_problems(root), spelling
    bundle.write_text(
        written.replace("  dev:\n", "  dev:\n    sync:\n      paths: [caos]\n")
    )
    assert "bundle: a target sets its own sync; there is one allowlist" in (
        check_gate_config._bundle_problems(root)
    )
    # The sync is an allowlist (C2, TM-3): a root the app reads that no
    # listed path carries, or no allowlist at all, is named.
    bundle.write_text(written.replace("    - caos\n", "    - caos/api\n"))
    problems = check_gate_config._bundle_problems(root)
    assert "bundle: sync.paths does not carry caos" in problems
    bundle.write_text(written.replace("  paths:\n", "  roots:\n"))
    problems = check_gate_config._bundle_problems(root)
    assert any(p.startswith("bundle: sync.paths is not set") for p in problems)
    bundle.write_text(written.replace("    - frontend/dist/**\n", ""))
    problems = check_gate_config._bundle_problems(root)
    assert "bundle: sync.include lacks frontend/dist/** (git-ignored)" in problems
    (root / "app.yaml").write_text("command: [x]\nenv:\n  - name: A\n    value: b\n")
    assert any(
        p.startswith("app.yaml: sets env")
        for p in check_gate_config._bundle_problems(root)
    )


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
    needed = sorted(check_gate_config.shipped_files())
    files = [{"local_path": path} for path in needed]
    record.write_text(json.dumps({"files": files}))
    assert check_gate_config.shipped_problems(record) == []
    assert check_gate_config.main(["--shipped", str(record)]) == 0
    record.write_text(json.dumps({"files": files[1:]}))
    assert check_gate_config.shipped_problems(record) == [
        f"shipped: {needed[0]} was not synced"
    ]
    record.write_text(json.dumps({"files": []}))
    missing = check_gate_config.shipped_problems(record)
    assert missing[-1] == f"shipped: and {len(needed) - 20} more", missing
    assert check_gate_config._gitleaks_problems(check_gate_config.REPO) == []


def test_the_deployment_must_carry_every_file_the_app_reads(tmp_path: Path) -> None:
    """DF-4 and DQ-9: the record is held to every tracked file under the sync
    roots and every file of the built export, so an export reduced to its
    page, or a runtime file no sample names, is a file missing."""
    root = tmp_path / "tree"
    (root / "caos" / "deliverable").mkdir(parents=True)
    (root / "caos" / "serve.py").write_text("")
    (root / "caos" / "deliverable" / "render.py").write_text("")
    (root / "scripts").mkdir()
    (root / "scripts" / "not_shipped.py").write_text("")
    assets = root / "frontend" / "dist" / "assets"
    assets.mkdir(parents=True)
    (root / "frontend" / "dist" / "index.html").write_text("<script src=x>")
    (assets / "index-abc.js").write_text("")
    _git(root, "init", "-q")
    _git(root, "add", "caos", "scripts")
    assert tracked_files(root, "caos") == [
        "caos/deliverable/render.py",
        "caos/serve.py",
    ]
    needed = check_gate_config.shipped_files(root)
    assert needed == {
        "caos/serve.py",
        "caos/deliverable/render.py",
        "frontend/dist/index.html",
        "frontend/dist/assets/index-abc.js",
        *check_gate_config.SHIPPED,
    }
    record = tmp_path / "deployment.json"
    for dropped in ("frontend/dist/assets/index-abc.js", "caos/deliverable/render.py"):
        kept = [{"local_path": path} for path in sorted(needed - {dropped})]
        record.write_text(json.dumps({"files": kept}))
        assert check_gate_config.shipped_problems(record, root) == [
            f"shipped: {dropped} was not synced"
        ]

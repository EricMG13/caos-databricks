"""The gate configuration cannot be loosened, and suppressions only fall (G16)."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import check_gate_config
from tracked import tracked_files

REPO = Path(__file__).resolve().parents[1]
# Built at runtime, not spelled contiguously in this file's own source: this
# file is itself one of the tracked .py files a real scan measures, and a
# suppression comment written whole into a sample below would inflate it.
_HASH = "#"


def _noqa(code: str) -> str:
    return f"{_HASH} noqa: {code}"


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
        "tests/conftest.py",
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


def test_a_complexipy_or_bandit_config_file_is_refused(tmp_path: Path) -> None:
    """FP-10: complexipy reads either spelling of its own TOML file, and
    bandit reads its legacy `.bandit` file, ahead of anything committed
    here; neither was in `OVERRIDING`, so either appearing anywhere in the
    tree silently overrode the gates' CLI flags."""
    root = _tree(tmp_path)
    assert check_gate_config._overriding_problems(root) == []
    (root / "complexipy.toml").write_text("max-complexity-allowed = 999\n")
    (root / ".bandit").write_text("[bandit]\nskips: B101\n")
    _git(root, "add", "complexipy.toml", ".bandit")
    problems = check_gate_config._overriding_problems(root)
    assert "complexipy.toml: overrides the committed tool configuration" in problems
    assert ".bandit: overrides the committed tool configuration" in problems


def test_a_complexipy_table_in_pyproject_is_refused(tmp_path: Path) -> None:
    """FP-10: `[tool.complexipy]` is read directly by the complexipy binary
    and none of `_tool_problems`'s checks ever looked at it, so a
    `max-complexity-allowed` set there would raise the ceiling with nothing
    in this file the wiser."""
    root = _tree(tmp_path)
    assert check_gate_config.configuration_problems(root) == []
    project = root / "pyproject.toml"
    project.write_text(
        project.read_text(encoding="utf-8")
        + "\n[tool.complexipy]\nmax-complexity-allowed = 999\n"
    )
    assert (
        "complexipy: [tool.complexipy] is set; it is read directly and unchecked"
        in check_gate_config.configuration_problems(root)
    )


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


def test_a_noqa_code_swap_is_named_even_though_the_aggregate_holds(
    tmp_path: Path,
) -> None:
    """FP-11, optional: budgeting only the aggregate `noqa` count let one
    rule code's occurrences rise as long as another's fell to match, so the
    total held still and the swap passed unseen. Each code is its own
    `noqa:<CODE>` budget now."""
    root = tmp_path / "tree"
    root.mkdir()
    _git(root, "init", "-q")
    (root / "m.py").write_text(
        f"a = 1  {_noqa('E501')}\nb = 2  {_noqa('E501')}\nc = 3  {_noqa('BLE001')}\n",
        encoding="utf-8",
    )
    _git(root, "add", "m.py")
    baseline = tmp_path / "baseline.json"
    baseline.write_text(json.dumps({"noqa": 3, "noqa:E501": 2, "noqa:BLE001": 1}))
    assert check_gate_config.suppression_problems(root, baseline) == []

    # Swap: one E501 becomes a BLE001. The aggregate noqa count (3) holds.
    (root / "m.py").write_text(
        f"a = 1  {_noqa('E501')}\nb = 2  {_noqa('BLE001')}\nc = 3  {_noqa('BLE001')}\n",
        encoding="utf-8",
    )

    problems = check_gate_config.suppression_problems(root, baseline)

    assert "suppressions: noqa:BLE001 rose to 2 (baseline 1)" in problems
    assert (
        "suppressions: noqa:E501 fell to 1 (baseline 2): lower "
        "tests/gate_baseline.json to match" in problems
    )
    assert not any(p.startswith("suppressions: noqa rose") for p in problems)


def test_a_raised_complexity_record_is_a_budget_that_rose(tmp_path: Path) -> None:
    """MAX-13: raising one function's recorded complexity in the snapshot
    (31 to 60) let it grow while the baselined count stayed the same; each
    function the snapshot allows is budgeted by its own name now."""
    snapshot = json.loads((REPO / check_gate_config.SNAPSHOT).read_text())
    counts = check_gate_config.suppression_counts()
    assert counts["complexity_baselined"] == sum(
        len(entry["functions"]) for entry in snapshot
    )
    key = f"complexity:{snapshot[0]['path']}::{snapshot[0]['functions'][0]['name']}"
    assert counts[key] == snapshot[0]["functions"][0]["complexity"]
    snapshot[0]["functions"][0]["complexity"] += 29
    root = tmp_path / "tree"
    root.mkdir()
    _git(root, "init", "-q")
    (root / check_gate_config.SNAPSHOT).write_text(json.dumps(snapshot))
    raised = check_gate_config.suppression_counts(root)
    assert raised["complexity_baselined"] == counts["complexity_baselined"]
    assert raised[key] == counts[key] + 29


def test_two_baselined_functions_cannot_swap_complexity_unnoticed(
    tmp_path: Path,
) -> None:
    """AR-07 and N46: ratcheting only the snapshot's total let one function's
    complexity rise as long as another fell to match, so the pair's sum held
    still and the rise passed unseen. Each function is its own budget now,
    so the one that rose is named even though the total did not move."""
    snapshot = json.loads((REPO / check_gate_config.SNAPSHOT).read_text())
    first_entry, second_entry = snapshot[0], snapshot[1]
    first, second = first_entry["functions"][0], second_entry["functions"][0]
    delta = 5
    first["complexity"] += delta
    second["complexity"] -= delta
    root = tmp_path / "tree"
    root.mkdir()
    _git(root, "init", "-q")
    (root / check_gate_config.SNAPSHOT).write_text(json.dumps(snapshot))
    baseline = tmp_path / "baseline.json"
    baseline.write_text(json.dumps(check_gate_config.suppression_counts()))

    problems = check_gate_config.suppression_problems(root, baseline)

    first_key = f"complexity:{first_entry['path']}::{first['name']}"
    second_key = f"complexity:{second_entry['path']}::{second['name']}"
    assert any(p.startswith(f"suppressions: {first_key} rose") for p in problems)
    assert any(p.startswith(f"suppressions: {second_key} fell") for p in problems)


def test_a_function_fixed_off_the_snapshot_must_lower_the_baseline_too(
    tmp_path: Path,
) -> None:
    """A baselined function brought to 15 or below leaves the complexipy
    snapshot, and with it this run's counts; the committed baseline still
    naming it is a fall to 0, not a key the ratchet stops watching."""
    snapshot = json.loads((REPO / check_gate_config.SNAPSHOT).read_text())
    fixed_key = (
        f"complexity:{snapshot[0]['path']}::{snapshot[0]['functions'][0]['name']}"
    )
    baseline = tmp_path / "baseline.json"
    baseline.write_text(json.dumps(check_gate_config.suppression_counts()))
    del snapshot[0]["functions"][0]
    if not snapshot[0]["functions"]:
        del snapshot[0]
    root = tmp_path / "tree"
    root.mkdir()
    _git(root, "init", "-q")
    (root / check_gate_config.SNAPSHOT).write_text(json.dumps(snapshot))

    problems = check_gate_config.suppression_problems(root, baseline)

    assert any(p.startswith(f"suppressions: {fixed_key} fell to 0") for p in problems)


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
            f"    pass  {hash_} complex" + "ipy: ignore",
            "@pytest.mark." + "live_provider",
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
        "complexipy_ignore": 1,
        "live_provider": 1,
    }
    assert check_gate_config.NOQA_CODE.findall(sample) == ["E501"]


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
        "ci: job lint sets 'continue-on-error'; a job may set only "
        f"{sorted(check_gate_config.JOB_KEYS)}",
    ):
        assert expected in problems, problems
    assert any("jscpd --threshold 3 " in p for p in problems), problems


def test_a_template_expression_spliced_into_a_run_script_is_refused(
    tmp_path: Path,
) -> None:
    """FP-40: a run: script is shell, and github.base_ref (or any other
    attacker-influenced context) spliced straight into one is a template
    expanded before the shell ever sees it -- script injection. Every such
    value must cross an env: variable instead."""
    root = _tree(tmp_path)
    assert check_gate_config._ci_problems(root) == []
    ci = root / ".github" / "workflows" / "ci.yml"
    ci_text = ci.read_text(encoding="utf-8")
    ci_text = ci_text.replace(
        '      - run: python3 scripts/check_pr_size.py "origin/$BASE_REF"\n'
        "        env:\n"
        "          BASE_REF: ${{ github.base_ref }}\n",
        "      - run: python3 scripts/check_pr_size.py "
        '"origin/${{ github.base_ref }}"\n',
    )
    assert ci_text != ci.read_text(encoding="utf-8"), "the size job's shape changed"
    ci.write_text(ci_text, encoding="utf-8")

    problems = check_gate_config._ci_problems(root)

    assert any(
        p.startswith("ci: ") and "splices a template expression" in p for p in problems
    ), problems


def test_a_required_step_disabled_with_if_is_refused(tmp_path: Path) -> None:
    """R24-11: the old check read only a required command's `run:` text, so
    a step left intact but given `if: false` still counted as present --
    the command never runs, but nothing here said so."""
    root = _tree(tmp_path)
    assert check_gate_config._ci_problems(root) == []
    ci = root / ".github" / "workflows" / "ci.yml"
    ci_text = ci.read_text(encoding="utf-8")
    disabled = ci_text.replace(
        "      - run: uv run mypy caos scripts tests\n",
        "      - if: false\n        run: uv run mypy caos scripts tests\n",
        1,
    )
    assert disabled != ci_text, "the types job's shape changed"
    ci.write_text(disabled, encoding="utf-8")

    problems = check_gate_config._ci_problems(root)

    assert (
        "ci: 'uv run mypy caos scripts tests' runs only when its step's "
        "if: allows it" in problems
    ), problems
    # The command's own text is still there, so the old, narrower check
    # alone would have called this configuration intact.
    assert "ci: no step runs 'uv run mypy caos scripts tests'" not in problems


def test_a_required_job_disabled_with_if_is_refused(tmp_path: Path) -> None:
    """R24-11: a job-level `if:` disables every step under it, its required
    commands included, the same way a step-level one does."""
    root = _tree(tmp_path)
    ci = root / ".github" / "workflows" / "ci.yml"
    ci_text = ci.read_text(encoding="utf-8")
    disabled = ci_text.replace(
        "  types:\n    runs-on: ubuntu-latest\n    timeout-minutes: 20\n    steps:\n",
        "  types:\n    runs-on: ubuntu-latest\n    timeout-minutes: 20\n"
        "    if: github.actor != 'nobody'\n    steps:\n",
        1,
    )
    assert disabled != ci_text, "the types job's shape changed"
    ci.write_text(disabled, encoding="utf-8")

    problems = check_gate_config._ci_problems(root)

    assert (
        "ci: 'uv run mypy caos scripts tests' runs only when its job's "
        "if: allows it" in problems
    ), problems


def test_a_job_if_for_an_optional_job_is_not_refused(tmp_path: Path) -> None:
    """The `size` job's own `if: github.event_name == 'pull_request'` is the
    one condition pinned for the one script it runs, so it is not refused:
    the rule is about a gate that can be switched off, not `if:` in
    general. Any other condition there is refused all the same."""
    root = _tree(tmp_path)
    ci = root / ".github" / "workflows" / "ci.yml"
    ci_text = ci.read_text(encoding="utf-8")
    assert "if: github.event_name == 'pull_request'" in ci_text
    assert check_gate_config._ci_problems(root) == []
    ci.write_text(
        ci_text.replace("if: github.event_name == 'pull_request'", "if: false")
    )
    assert check_gate_config._ci_problems(root) == [
        f"ci: {check_gate_config.PR_SIZE!r} runs only when its job's if: allows it"
    ]


def test_a_hook_s_own_body_weakened_in_effect_is_named(tmp_path: Path) -> None:
    """AR-07 and N46: the old check matched only `- id:`, so a hook kept
    naming itself present while its `entry` was swapped for a no-op, its
    `exclude` widened, or a fresh `stages`/`files` moved it off the default
    run or narrowed what it saw."""
    root = _tree(tmp_path)
    assert check_gate_config._hook_problems(root) == []
    config = root / ".pre-commit-config.yaml"
    text = config.read_text(encoding="utf-8")
    text = text.replace(
        "        entry: uv run python scripts/check_vocabulary.py\n",
        "        entry: 'true'\n",
    )
    text = text.replace(
        "      - id: ruff\n        args: [--fix]\n        exclude: ^vendor/\n",
        "      - id: ruff\n        args: [--fix]\n        exclude: ^(vendor/|caos/)\n",
    )
    text = text.replace(
        "      - id: gitleaks\n",
        "      - id: gitleaks\n        stages: [manual]\n",
        1,
    )
    config.write_text(text, encoding="utf-8")
    problems = check_gate_config._hook_problems(root)
    assert (
        "pre-commit: vocabulary[0].entry is 'true', not 'uv run python "
        "scripts/check_vocabulary.py'" in problems
    )
    assert (
        "pre-commit: ruff[0].exclude is '^(vendor/|caos/)', not '^vendor/'" in problems
    )
    assert (
        "pre-commit: gitleaks[0].stages is set; it can change what the hook runs on"
        in problems
    )


def test_a_hook_removed_is_still_named_missing(tmp_path: Path) -> None:
    root = _tree(tmp_path)
    config = root / ".pre-commit-config.yaml"
    text = config.read_text(encoding="utf-8").replace(
        "      - id: io-budget\n"
        "        name: every request path declares an I/O budget\n"
        "        entry: uv run python scripts/io_budget.py --assert\n"
        "        language: system\n"
        "        pass_filenames: false\n",
        "",
    )
    config.write_text(text, encoding="utf-8")
    assert (
        "pre-commit: hooks missing ['io-budget']"
        in check_gate_config._hook_problems(root)
    )


def test_the_gitleaks_dir_scan_of_the_uncommitted_tree_is_required(
    tmp_path: Path,
) -> None:
    """CF-064: the staged-scan gitleaks hook never sees an unstaged or
    untracked file, so a second `gitleaks dir` invocation of the same
    pinned hook covers the working tree as it sits on disk. Dropping it,
    or weakening what it runs, is refused the same as any other hook."""
    root = _tree(tmp_path)
    assert check_gate_config._hook_problems(root) == []
    config = root / ".pre-commit-config.yaml"
    original = config.read_text(encoding="utf-8")

    dropped = original.replace(
        "      - id: gitleaks\n"
        "        name: gitleaks (uncommitted tree)\n"
        "        entry: gitleaks dir --no-banner --redact -v .\n",
        "",
    )
    assert dropped != original
    config.write_text(dropped, encoding="utf-8")
    assert (
        "pre-commit: gitleaks appears 1 time(s), expected 2"
        in check_gate_config._hook_problems(root)
    )

    weakened = original.replace(
        "entry: gitleaks dir --no-banner --redact -v .",
        "entry: gitleaks dir --no-banner --redact -v . --no-git",
    )
    assert weakened != original
    config.write_text(weakened, encoding="utf-8")
    assert (
        "pre-commit: gitleaks[1].entry is 'gitleaks dir --no-banner --redact "
        "-v . --no-git', not 'gitleaks dir --no-banner --redact -v .'"
        in check_gate_config._hook_problems(root)
    )


def test_a_conftest_collection_hook_is_refused_unless_pinned(tmp_path: Path) -> None:
    """N46: `tests/conftest.py`'s `pytest_collection_modifyitems` is what
    makes `-m "not live_provider"` a floor rather than an opt-out, so it is
    pinned rather than banned outright; a change to it, a `collect_ignore`
    anywhere, or a second collection hook elsewhere under `tests/` all drop
    a test from a run with nothing in the tally to notice, and are refused."""
    root = _tree(tmp_path)
    assert check_gate_config._collection_hook_problems(root) == []

    conftest = root / "tests" / "conftest.py"
    original = conftest.read_text(encoding="utf-8")
    tampered = original.replace(
        "    live = [item for item in items if item.get_closest_marker"
        '("live_provider")]\n',
        "    live = []\n",
    )
    assert tampered != original
    conftest.write_text(tampered, encoding="utf-8")
    assert (
        "conftest: tests/conftest.py's pytest_collection_modifyitems no longer "
        "matches what is committed" in check_gate_config._collection_hook_problems(root)
    )

    conftest.write_text(original + "\ncollect_ignore = ['test_security.py']\n")
    assert (
        "conftest: tests/conftest.py sets collect_ignore; it can drop a file "
        "from collection with nothing reported"
        in check_gate_config._collection_hook_problems(root)
    )

    conftest.write_text(original, encoding="utf-8")
    nested = root / "tests" / "sub" / "conftest.py"
    nested.parent.mkdir(parents=True)
    nested.write_text(
        "def pytest_ignore_collect(collection_path, config):\n    return True\n",
        encoding="utf-8",
    )
    _git(root, "add", "tests/sub/conftest.py")
    assert (
        "conftest: tests/sub/conftest.py defines pytest_ignore_collect; it can "
        "change what pytest collects or runs"
        in check_gate_config._collection_hook_problems(root)
    )


def test_the_ci_file_s_commands_are_read_as_the_runner_runs_them() -> None:
    """A folded block is one command, a literal block one per line with its
    continuations joined, and the keys after a block are not part of it."""
    ci_text = "\n".join(
        [
            "jobs:",
            "  one:",
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


def test_each_target_binds_exactly_its_own_lakebase_kind(tmp_path: Path) -> None:
    """R24-14: a variable cannot choose the `database` resource's form, so the
    targets do, each once: dev and prod bind Lakebase Autoscaling (the
    endpoint variable with a `postgres` resource), the `-provisioned` pair an
    existing instance (the instance variable with a `database` resource).
    Nothing binds outside the targets, and no target binds both or neither."""
    root = _tree(tmp_path)
    bundle = root / "databricks.yml"
    written = bundle.read_text()
    assert check_gate_config._bundle_problems(root) == []
    blocks = check_gate_config.target_blocks(written)
    assert list(blocks) == ["dev", "prod", "dev-provisioned", "prod-provisioned"]

    def problems(text: str) -> list[str]:
        bundle.write_text(text)
        return [p for p in check_gate_config._bundle_problems(root) if "LAKEBASE" in p]

    swapped = written.replace("CAOS_LAKEBASE_INSTANCE", "CAOS_LAKEBASE_ENDPOINT")
    assert problems(swapped) == [
        f"bundle: target {target} must bind CAOS_LAKEBASE_INSTANCE and a database "
        "resource, and nothing of the other kind"
        for target in ("dev-provisioned", "prod-provisioned")
    ]
    endpoint_env = (
        "              - name: CAOS_LAKEBASE_ENDPOINT\n"
        "                value: projects/${var.lakebase_project}/branches/"
        "${var.lakebase_branch}/endpoints/${var.lakebase_endpoint}\n"
    )
    assert written.count(endpoint_env) == 2
    unbound = written.replace(endpoint_env, "", 1)  # dev's resource, no variable
    assert problems(unbound) == [
        "bundle: target dev must bind CAOS_LAKEBASE_ENDPOINT and a postgres "
        "resource, and nothing of the other kind"
    ]
    both = written.replace(
        endpoint_env,
        endpoint_env + "              - name: CAOS_LAKEBASE_INSTANCE\n"
        "                value: x\n",
        1,
    )
    assert len(problems(both)) == 1
    shared = written.replace(
        "        env:\n", "        env:\n          - name: CAOS_LAKEBASE_INSTANCE\n", 1
    )
    assert "bundle: CAOS_LAKEBASE_INSTANCE is bound outside the targets" in (
        problems(shared)
    )
    added = written + "  staging:\n    mode: production\n"
    assert problems(added) == [
        "bundle: target staging must bind CAOS_LAKEBASE_ENDPOINT and a postgres "
        "resource, and nothing of the other kind"
    ]


def test_ci_runs_every_target_under_the_stand_in() -> None:
    """R24-14 (A37, DF-4): each target is validated, deployed and run under
    one stub, then held to what its deploy synced -- the Provisioned pair
    with the instance, the default targets with the Autoscaling project."""
    run, shipped = check_gate_config.stand_in_target("dev-provisioned", "--var x=y")
    assert run == (
        f"{check_gate_config.STAND_IN} sh -c "
        '"databricks bundle validate -t dev-provisioned --var x=y '
        "&& databricks bundle deploy -t dev-provisioned --var x=y "
        '&& databricks bundle run caos -t dev-provisioned --var x=y"'
    )
    assert shipped.endswith(
        "--shipped .databricks/bundle/dev-provisioned/deployment.json"
    )
    gates = check_gate_config.CI_GATES
    for target in check_gate_config.target_blocks(
        (REPO / "databricks.yml").read_text()
    ):
        assert any(f"--shipped .databricks/bundle/{target}/" in g for g in gates), (
            target
        )
    assert "lakebase_project=caos" in check_gate_config.STAND_IN_VARS
    assert "lakebase_instance=caos-lb" in check_gate_config.STAND_IN_PROVISIONED_VARS


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
    assert check_gate_config.baseline_problems("HEAD") == []
    assert check_gate_config.main(["--against", "HEAD"]) == 0
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


def _base_rev(root: Path) -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def test_baseline_problems_measures_the_base_tree_fresh_not_its_own_json(
    tmp_path: Path,
) -> None:
    """FP-11: comparing two commits' own committed tests/gate_baseline.json
    numbers let a PR that only weakened a `SUPPRESSIONS` pattern make its
    own, freshly weaker count look like a fall against a base measured
    under the old, stronger one. Both sides are now measured fresh under
    this module's current patterns; the base commit's own committed JSON
    -- deliberately wrong here -- is not read at all."""
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "test@example.invalid")
    _git(root, "config", "user.name", "Gate test")
    (root / "m.py").write_text(f"x = 1  {_noqa('E501')}\n", encoding="utf-8")
    (root / "tests").mkdir()
    # A wildly wrong committed number: trusted at face value, a rise would
    # read as a fall instead.
    (root / "tests" / "gate_baseline.json").write_text(
        json.dumps({"noqa": 999, "noqa:E501": 999})
    )
    _git(root, "add", "m.py", "tests/gate_baseline.json")
    _git(root, "commit", "-qm", "base")
    base_rev = _base_rev(root)

    (root / "m.py").write_text(
        f"x = 1  {_noqa('E501')}\ny = 2  {_noqa('E501')}\n", encoding="utf-8"
    )
    _git(root, "add", "m.py")
    _git(root, "commit", "-qm", "add a second noqa")

    problems = check_gate_config.baseline_problems(base_rev, root)

    assert "baseline: noqa rose to 2 (base branch 1)" in problems
    assert "baseline: noqa:E501 rose to 2 (base branch 1)" in problems


def test_baseline_problems_refuses_an_unresolvable_revision(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q")
    problems = check_gate_config.baseline_problems("not-a-real-revision", root)
    assert len(problems) == 1
    assert problems[0].startswith("baseline: git could not list")


def test_suppression_counts_at_matches_a_fresh_checkout_of_the_same_commit(
    tmp_path: Path,
) -> None:
    """`suppression_counts_at(rev)` reads `rev`'s own tracked files through
    git, not the working tree; measured at the tip of a small repo it must
    equal `suppression_counts` measured on a working tree checked out to
    that same commit."""
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "test@example.invalid")
    _git(root, "config", "user.name", "Gate test")
    (root / "m.py").write_text(f"x = 1  {_noqa('E501')}\n", encoding="utf-8")
    _git(root, "add", "m.py")
    _git(root, "commit", "-qm", "one file, one suppression")
    tip = _base_rev(root)

    assert check_gate_config.suppression_counts_at(tip, root) == (
        check_gate_config.suppression_counts(root)
    )


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

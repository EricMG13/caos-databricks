"""The gate configuration cannot be loosened, and suppressions only fall (G16)."""

from __future__ import annotations

import ast
import json
import os
import shutil
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

import check_gate_config
import pytest
import tracked
import yaml
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
        ".github/workflows/gitleaks.yml",
        ".github/workflows/secrets-weekly.yml",
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


def test_the_namespace_and_import_routes_to_a_hook_are_refused(tmp_path: Path) -> None:
    """N109 review: `vars()`, `exec`, `__import__`, frame access, a star
    import and a PEP 562 module `__getattr__` each install a hook with no
    `pytest_` binding. The runtime guard is the sturdy answer; these are
    the routes the static gate still names."""
    root = _tree(tmp_path)
    for index, text in enumerate(
        (
            "vars()['pytest_' + 'pyfunc_call'] = lambda pyfuncitem: True\n",
            "locals()['x'] = 1\n",
            "exec('def pytest_pyfunc_call(pyfuncitem): return True')\n",
            "eval('1')\n",
            "compile('1', 'x', 'eval')\n",
            "__import__('builtins')\n",
            "import sys\nsys._getframe().f_globals['x'] = 1\n",
            "from helper import *\n",
            "def __getattr__(name):\n    return None\n",
            "def __dir__():\n    return ['pytest_pyfunc_call']\n",
        )
    ):
        name = f"tests/route{index}/conftest.py"
        problems = _conftest_problems(root, name, text)
        assert any(problem.startswith(f"conftest: {name} ") for problem in problems), (
            text,
            problems,
        )


def test_every_binding_of_pytest_plugins_in_another_conftest_is_refused(
    tmp_path: Path,
) -> None:
    """N109 review: `+=`, an annotated assignment, a tuple target and a loop
    target each bind `pytest_plugins`."""
    root = _tree(tmp_path)
    for index, text in enumerate(
        (
            "pytest_plugins += ('evil',)\n",
            "pytest_plugins: tuple[str, ...] = ('evil',)\n",
            "pytest_plugins, _z = ('evil',), 1\n",
            "for pytest_plugins in [('evil',)]:\n    pass\n",
        )
    ):
        name = f"tests/binds{index}/conftest.py"
        problems = _conftest_problems(root, name, text)
        assert any(
            problem.startswith(f"conftest: {name} sets pytest_plugins")
            for problem in problems
        ), (text, problems)


_GUARD_PROJECT_TEST = "def test_a():\n    assert False\n"


_EXEC_HOOK = (
    "import builtins\n"
    "builtins.exec('def pytest_' + 'pyfunc_call(pyfuncitem): return True')\n"
)


def _guard_project(
    tmp_path: Path, *, hook_in: str | None, workers: int = 0
) -> subprocess.CompletedProcess[str]:
    """A throwaway repository whose `tests/conftest.py` carries the
    repository's own runtime guard, run from the repository root as CI runs
    it (outside the guarded directory), with a hook replacing how a test runs
    placed in a plugin (`-p`), a nested conftest, code built by `exec` in a
    nested conftest, or nowhere, over one test that fails."""
    source = (REPO / "tests" / "conftest.py").read_text(encoding="utf-8")
    [guard] = [
        ast.get_source_segment(source, node)
        for node in ast.parse(source).body
        if isinstance(node, ast.FunctionDef)
        and node.name == "_refuse_run_hooks_from_tests"
    ]
    repo = tmp_path / "repo"
    tests = repo / "tests"
    (tests / "sub").mkdir(parents=True)
    (tests / "conftest.py").write_text(
        "from pathlib import Path\n\nimport pytest\n\n\n"
        "_EXIT = pytest.exit\n_IS_RELATIVE_TO = Path.is_relative_to\n\n\n"
        f"{guard}\n\n\n"
        "def pytest_sessionstart(session):\n"
        "    _refuse_run_hooks_from_tests(session.config)\n\n\n"
        "def pytest_collection_modifyitems(config, items):\n"
        "    _refuse_run_hooks_from_tests(config)\n",
        encoding="utf-8",
    )
    (tests / "sub" / "test_a.py").write_text(_GUARD_PROJECT_TEST)
    bad = "def pytest_pyfunc_call(pyfuncitem):\n    return True\n"
    arguments = ["-p", "no:cacheprovider"]
    if hook_in == "plugin":
        (tests / "hooks_plugin.py").write_text(bad)
        arguments += ["-p", "hooks_plugin"]
    elif hook_in == "nested":
        (tests / "sub" / "conftest.py").write_text(bad)
    elif hook_in == "exec":
        (tests / "sub" / "conftest.py").write_text(_EXEC_HOOK)
    if workers:
        arguments += ["-n", str(workers)]
    environment = {
        key: value for key, value in os.environ.items() if not key.startswith("PYTEST_")
    }
    environment["PYTHONPATH"] = str(tests)
    return subprocess.run(
        [sys.executable, "-m", "pytest", *arguments, "-q", "tests"],
        cwd=repo,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )


def test_the_runtime_guard_ends_a_session_that_replaces_how_a_test_runs(
    tmp_path: Path,
) -> None:
    """N109 review: a conftest or a plugin module that implements
    `pytest_pyfunc_call` can return True and pass `assert False`, including
    one built by `exec` (its code object's file is "<string>", so the guard
    judges the registering module's file); the guard in the pinned conftest
    ends the session before it can. A clean session is untouched, with and
    without xdist workers."""
    for workers in (0, 2):
        clean = _guard_project(
            tmp_path / f"clean{workers}", hook_in=None, workers=workers
        )
        assert "1 failed" in clean.stdout, clean.stdout + clean.stderr
        for where in ("plugin", "nested", "exec"):
            case = tmp_path / f"{where}{workers}"
            ended = _guard_project(case, hook_in=where, workers=workers)
            output = ended.stdout + ended.stderr
            if not workers:
                assert "pytest_pyfunc_call is implemented by" in output, output
            assert "passed" not in output, (where, workers, output)
            assert ended.returncode != 0, (where, workers, output)


def test_builtins_reached_by_attribute_are_refused(tmp_path: Path) -> None:
    """N109 re-review: `builtins.exec(...)` and a computed `getattr` build a
    hook as `exec` by name does."""
    root = _tree(tmp_path)
    for index, text in enumerate(
        (
            "import builtins\nbuiltins.exec('1')\n",
            "import builtins\nbuiltins.eval('1')\n",
            "import builtins\nbuiltins.compile('1', 'x', 'eval')\n",
            "import builtins\ngetattr(builtins, 'ex' + 'ec')('1')\n",
            "import builtins\ngetattr(builtins, 'exec')('1')\n",
        )
    ):
        name = f"tests/attr{index}/conftest.py"
        problems = _conftest_problems(root, name, text)
        assert any(problem.startswith(f"conftest: {name} ") for problem in problems), (
            text,
            problems,
        )


def test_the_pinned_conftest_is_pinned_whole(tmp_path: Path) -> None:
    """N109 re-review: pinning each function by name left the module's other
    statements free to disarm the guard (`del` of a hook, a store on
    `pytest.exit`, a swapped `__code__`, an edit of `__builtins__`). The
    whole file is pinned instead: any edit to it fails the gate until
    `CONFTEST_PIN` is updated in the same change."""
    root = _tree(tmp_path)
    original = (root / "tests" / "conftest.py").read_text(encoding="utf-8")
    assert _conftest_problems(root, "tests/conftest.py", original) == []
    for extra in (
        "\ndel pytest_sessionstart, pytest_collection_modifyitems\n",
        "\npytest.exit = lambda *a, **k: None\n",
        "\n_refuse_run_hooks_from_tests.__code__ = (lambda config: None).__code__\n",
        "\n__builtins__['getattr'] = None\n",
        "\n_refuse_run_hooks_from_tests.__defaults__ = None\n",
        "\nPath.is_relative_to = lambda *arguments: False\n",
    ):
        problems = _conftest_problems(root, "tests/conftest.py", original + extra)
        assert any(
            problem.startswith("conftest: tests/conftest.py changed")
            for problem in problems
        ), (extra, problems)


def test_the_pytest_plugins_module_is_read_with_stores_refused(
    tmp_path: Path,
) -> None:
    """N109 re-review: the module the pinned `pytest_plugins` names is loaded
    as a plugin before the guard runs, so a store into `sys.modules` or into
    its own module object there disarms the guard and installs a hook with no
    `pytest_` binding; it is read like every other conftest-loaded module the
    pin does not cover, with stores refused. The committed module passes."""
    root = _tree(tmp_path)
    [module] = check_gate_config.PYTEST_PLUGINS_PIN
    plugin = f"tests/{module}.py"
    committed = (REPO / plugin).read_text(encoding="utf-8")
    assert _conftest_problems(root, plugin, committed) == []
    tampered = committed + (
        "\nimport sys as _sys\n\n"
        '_sys.modules["conftest"]._EXIT = lambda *a, **k: None\n'
        "_sys.modules[__name__].pytest_pyfunc_call = lambda pyfuncitem: True\n"
    )
    problems = _conftest_problems(root, plugin, tampered)
    assert any(
        problem.startswith(f"conftest: {plugin} stores into an attribute or item")
        for problem in problems
    ), problems


def test_the_pinned_conftest_is_byte_pinned_in_gitattributes() -> None:
    """N109 re-review: `tests/conftest.py` is pinned by digest, so a checkout
    that converts its line endings fails the gate; `.gitattributes` must hold
    its bytes as it does the other byte-pinned files (`-text`)."""
    git = shutil.which("git")
    assert git is not None
    attribute = subprocess.run(
        [git, "check-attr", "text", "tests/conftest.py"],
        cwd=REPO,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert attribute == "tests/conftest.py: text: unset"


def test_a_store_or_a_del_in_another_conftest_is_refused(tmp_path: Path) -> None:
    """N109 re-review: an attribute or subscript store, an augmented one or
    a `del` can disarm a guard or a hook from a conftest the pin does not
    cover."""
    root = _tree(tmp_path)
    for index, text in enumerate(
        (
            "import os\nos.environ = {}\n",
            "import os\nos.environ['x'] = '1'\n",
            "import os\nos.counter += 1\n",
            "import os\nos.counter: int = 1\n",
            "x = 1\ndel x\n",
            "import os\ndel os.environ['x']\n",
            "def f(o):\n    o.x = 1\n",
        )
    ):
        name = f"tests/store{index}/conftest.py"
        problems = _conftest_problems(root, name, text)
        assert any(problem.startswith(f"conftest: {name} ") for problem in problems), (
            text,
            problems,
        )


def _edit_ci(root: Path, edit: Callable[[dict[str, Any]], None]) -> None:
    """Rewrite the copied workflow after `edit` has changed its parsed jobs."""
    ci = root / ".github" / "workflows" / "ci.yml"
    document = cast(dict[Any, Any], yaml.safe_load(ci.read_text(encoding="utf-8")))
    edit(document["jobs"])
    # YAML 1.1 reads the bare key `on` as true; JSON, which is YAML, spells it.
    document = {("on" if key is True else key): v for key, v in document.items()}
    ci.write_text(json.dumps(document), encoding="utf-8")


def _move_before(steps: list[dict[str, Any]], mover: str, anchor: str) -> None:
    """Move the step whose `run` holds `mover` to just ahead of the one
    holding `anchor`."""
    [moving] = [step for step in steps if mover in str(step.get("run"))]
    steps.remove(moving)
    [target] = [step for step in steps if anchor in str(step.get("run"))]
    steps.insert(steps.index(target), moving)


def test_a_floor_check_ahead_of_the_step_that_writes_its_report_is_refused(
    tmp_path: Path,
) -> None:
    """N110: the floor check judges whatever file is on disk, so one moved
    ahead of its producer (or into another job) judges a stale report a
    commit force-added. Each must follow its producer in the same job."""
    root = _tree(tmp_path)
    assert check_gate_config._ci_problems(root) == []

    _edit_ci(
        root,
        lambda jobs: _move_before(
            jobs["security"]["steps"], "scan_floors.py bandit.json", "-o bandit.json"
        ),
    )
    problems = check_gate_config._ci_problems(root)
    assert (
        "ci: job security reads bandit.json before the step that writes it" in problems
    ), problems


def test_the_coverage_floor_ahead_of_its_report_or_in_another_job_is_refused(
    tmp_path: Path,
) -> None:
    root = _tree(tmp_path)
    _edit_ci(
        root,
        lambda jobs: _move_before(
            jobs["test"]["steps"], "scan_floors.py coverage.xml", "coverage xml"
        ),
    )
    assert (
        "ci: job test reads coverage.xml before the step that writes it"
        in check_gate_config._ci_problems(root)
    )

    root = _tree(tmp_path / "other")

    def to_lint(jobs: dict[str, Any]) -> None:
        [step] = [
            step
            for step in jobs["test"]["steps"]
            if "scan_floors.py coverage.xml" in str(step.get("run"))
        ]
        jobs["test"]["steps"].remove(step)
        jobs["lint"]["steps"].append(step)

    _edit_ci(root, to_lint)
    assert (
        "ci: job lint reads coverage.xml before the step that writes it"
        in check_gate_config._ci_problems(root)
    )


def test_a_shipped_check_ahead_of_its_deploy_is_refused(tmp_path: Path) -> None:
    """N110: `--shipped .databricks/bundle/<target>/deployment.json` reads a
    file the target's deploy writes; ahead of it, a stale file would do."""
    root = _tree(tmp_path)
    _edit_ci(
        root,
        lambda jobs: _move_before(
            jobs["bundle"]["steps"],
            "--shipped .databricks/bundle/prod/deployment.json",
            "bundle deploy -t prod ",
        ),
    )
    assert (
        "ci: job bundle reads .databricks/bundle/prod/deployment.json before "
        "the step that writes it" in check_gate_config._ci_problems(root)
    )


def test_a_job_s_services_are_pinned(tmp_path: Path) -> None:
    """N110: `services` was free, so a job's store could be swapped for an
    unpinned image, or one added to a job that has none."""
    root = _tree(tmp_path)

    def swap(jobs: dict[str, Any]) -> None:
        jobs["bundle"]["services"]["postgres"]["image"] = "postgres:latest"
        jobs["lint"]["services"] = {"redis": {"image": "redis"}}

    _edit_ci(root, swap)
    problems = check_gate_config._ci_problems(root)
    assert "ci: job bundle's services are not as pinned" in problems, problems
    assert "ci: job lint's services are not as pinned" in problems, problems


def test_a_tracked_report_or_deployment_record_is_refused(tmp_path: Path) -> None:
    """N110: a tracked `bandit.json`, `coverage.xml` or `.databricks/**` is
    a stale report the floor checks could judge in place of a fresh one."""
    root = _tree(tmp_path)
    assert check_gate_config._report_problems(root) == []
    (root / "coverage.xml").write_text("<coverage/>")
    (root / "bandit.json").write_text("{}")
    deployment = root / ".databricks" / "bundle" / "dev" / "deployment.json"
    deployment.parent.mkdir(parents=True)
    deployment.write_text("{}")
    _git(root, "add", "-f", "coverage.xml", "bandit.json", ".databricks")
    assert check_gate_config._report_problems(root) == [
        "report: .databricks/bundle/dev/deployment.json is tracked; a floor "
        "check would judge it stale",
        "report: bandit.json is tracked; a floor check would judge it stale",
        "report: coverage.xml is tracked; a floor check would judge it stale",
    ]
    assert set(check_gate_config._report_problems(root)) <= set(
        check_gate_config.configuration_problems(root)
    )


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
    pinned hook covers the working tree as git would commit it (F466).
    Dropping it, or weakening what it runs, is refused the same as any
    other hook."""
    root = _tree(tmp_path)
    assert check_gate_config._hook_problems(root) == []
    config = root / ".pre-commit-config.yaml"
    original = config.read_text(encoding="utf-8")

    dropped = original.replace(
        "      - id: gitleaks\n"
        "        name: gitleaks (uncommitted tree)\n"
        "        entry: bash scripts/gitleaks_tree.sh\n",
        "",
    )
    assert dropped != original
    config.write_text(dropped, encoding="utf-8")
    assert (
        "pre-commit: gitleaks appears 1 time(s), expected 2"
        in check_gate_config._hook_problems(root)
    )

    weakened = original.replace(
        "entry: bash scripts/gitleaks_tree.sh",
        "entry: gitleaks dir --no-banner --redact -v .",
    )
    assert weakened != original
    config.write_text(weakened, encoding="utf-8")
    assert (
        "pre-commit: gitleaks[1].entry is 'gitleaks dir --no-banner --redact "
        "-v .', not 'bash scripts/gitleaks_tree.sh'"
        in check_gate_config._hook_problems(root)
    )


def test_a_conftest_collection_hook_is_refused_unless_pinned(tmp_path: Path) -> None:
    """N46: `tests/conftest.py`'s `pytest_collection_modifyitems` is what
    makes `-m "not live_provider"` a floor rather than an opt-out, so the
    file is pinned whole rather than banned outright (a change to it fails
    until the pin moves); a `collect_ignore` or a collection hook in any
    other conftest under `tests/` drops a test from a run with nothing in the
    tally to notice, and is refused."""
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
    [problem] = check_gate_config._collection_hook_problems(root)
    assert problem.startswith("conftest: tests/conftest.py changed (sha256 ")
    assert problem.endswith(
        "update CONFTEST_PIN in scripts/check_gate_config.py in the same change"
    )

    conftest.write_text(original, encoding="utf-8")
    other = root / "tests" / "other" / "conftest.py"
    other.parent.mkdir(parents=True)
    other.write_text("collect_ignore = ['test_security.py']\n", encoding="utf-8")
    _git(root, "add", "tests/other/conftest.py")
    assert (
        "conftest: tests/other/conftest.py sets collect_ignore; it can drop a file "
        "from collection with nothing reported"
        in check_gate_config._collection_hook_problems(root)
    )
    other.write_text("", encoding="utf-8")

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


def _conftest_problems(root: Path, name: str, text: str) -> list[str]:
    """What the gate says once the tracked `name` holds `text`."""
    target = root / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    _git(root, "add", name)
    return check_gate_config._collection_hook_problems(root)


def test_a_conftest_hook_that_can_pass_a_test_is_refused(tmp_path: Path) -> None:
    """N109: a conftest.py can define `pytest_pyfunc_call` or
    `pytest_runtest_protocol`, return True and pass a test without running
    it. Every `pytest_*` binding and every `pytest_plugins` in a conftest
    but the pinned ones is refused in the statement forms the AST reads (a
    def, an async def, an assignment, an import alias, nested or not). The
    runtime guard covers what a name list cannot; a fixture that rebinds
    `request.node.runtest` is a named limit, open to any test module."""
    root = _tree(tmp_path)
    assert check_gate_config._collection_hook_problems(root) == []
    refused = "it can change what pytest collects or runs"
    for index, text in enumerate(
        (
            "def pytest_pyfunc_call(pyfuncitem):\n    return True\n",
            "def pytest_runtest_protocol(item, nextitem):\n    return True\n",
            "async def pytest_runtest_call(item):\n    return True\n",
            "pytest_runtest_protocol = lambda item, nextitem: True\n",
            "import os\nif os:\n    def pytest_pyfunc_call(pyfuncitem):\n"
            "        return True\n",
            "from helper import pytest_pyfunc_call\n",
            "from helper import hook as pytest_runtest_protocol\n",
        )
    ):
        name = f"tests/hooks{index}/conftest.py"
        problems = _conftest_problems(root, name, text)
        assert any(
            problem.startswith(f"conftest: {name} ") and refused in problem
            for problem in problems
        ), (text, problems)


def test_pytest_plugins_is_refused_in_another_conftest(tmp_path: Path) -> None:
    """N109: `pytest_plugins` loads any module's hooks; the one value
    `tests/conftest.py` carries is pinned with that file, and nowhere else."""
    root = _tree(tmp_path)
    for index, text in enumerate(
        ('pytest_plugins = ["evil"]\n', 'pytest_plugins += ["evil"]\n')
    ):
        name = f"tests/plugins{index}/conftest.py"
        problems = _conftest_problems(root, name, text)
        assert any(
            problem.startswith(f"conftest: {name} ") and "pytest_plugins" in problem
            for problem in problems
        ), (text, problems)


def test_a_root_conftest_is_read_too(tmp_path: Path) -> None:
    """N109: a conftest.py at the repository root is read by pytest as well."""
    root = _tree(tmp_path)
    problems = _conftest_problems(
        root, "conftest.py", "def pytest_pyfunc_call(pyfuncitem):\n    return True\n"
    )
    assert any(problem.startswith("conftest: conftest.py ") for problem in problems)


def test_a_conftest_that_registers_a_hook_by_name_is_refused(tmp_path: Path) -> None:
    """N109: a hook can also be installed without a `pytest_` binding, through
    the namespace, the plugin manager or frames (the static list; the runtime
    guard reads what pytest registered)."""
    root = _tree(tmp_path)
    for index, text in enumerate(
        (
            "globals()['pytest_' + 'pyfunc_call'] = lambda pyfuncitem: True\n",
            "import sys\nsetattr(sys.modules[__name__], 'x', 1)\n",
            "def pytest_configure(config):\n    config.pluginmanager.register(1)\n",
        )
    ):
        name = f"tests/dyn{index}/conftest.py"
        problems = _conftest_problems(root, name, text)
        assert any(problem.startswith(f"conftest: {name} ") for problem in problems), (
            text,
            problems,
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


def _not_python(_directory: str, names: list[str]) -> list[str]:
    return [name for name in names if not name.endswith(".py")]


def _narrowed_repo(root: Path, *, checker: bool = False) -> str:
    """A repo whose second commit adds a suppression under `skipped/`; returns
    the base revision. With `checker`, the base commit carries this repo's own
    `scripts/`, so it has a checker and a `tracked` module of its own."""
    root.mkdir()
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "test@example.invalid")
    _git(root, "config", "user.name", "Gate test")
    (root / "m.py").write_text("x = 1\n", encoding="utf-8")
    _git(root, "add", "m.py")
    if checker:
        shutil.copytree(REPO / "scripts", root / "scripts", ignore=_not_python)
        _git(root, "add", "scripts")
    _git(root, "commit", "-qm", "base")
    base_rev = _base_rev(root)
    (root / "skipped").mkdir()
    (root / "skipped" / "s.py").write_text(
        f"x = 1  {_noqa('E501')}\n", encoding="utf-8"
    )
    _git(root, "add", "skipped/s.py")
    _git(root, "commit", "-qm", "suppress where the lister does not look")
    return base_rev


def test_baseline_problems_refuses_a_tracked_path_the_current_tree_did_not_measure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """N108: a change that narrows `tracked_python` to skip a directory and
    adds a suppression there passed unseen, because both file lists came from
    the narrowed function. The checker lists the tree itself and refuses a
    tracked `.py` path the measure left out."""
    root = tmp_path / "repo"
    base_rev = _narrowed_repo(root)
    real = tracked.tracked_python
    monkeypatch.setattr(
        "check_gate_config.tracked_python",
        lambda repo: [p for p in real(repo) if "skipped" not in p.parts],
    )
    problems = check_gate_config.baseline_problems(base_rev, root)
    assert "baseline: skipped/s.py is tracked but was not measured" in problems


@pytest.mark.parametrize("how", ["vendor", "tracked_files"])
def test_baseline_problems_refuses_when_tracked_py_itself_is_narrowed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, how: str
) -> None:
    """N108, the PR that edits `scripts/tracked.py`: this commit's `VENDOR` or
    `tracked_files` skips a directory for the measure and for every lister
    this commit owns alike. The base revision's own `tracked` module still
    names the file, so the checker refuses it."""
    root = tmp_path / "repo"
    base_rev = _narrowed_repo(root, checker=True)
    if how == "vendor":
        # An edited `tracked.py` is what `check_gate_config` imports from, so
        # both modules' bindings change together.
        monkeypatch.setattr("tracked.VENDOR", "skipped")
        monkeypatch.setattr("check_gate_config.VENDOR", "skipped")
    else:
        real = tracked.tracked_files

        def narrowed(repo: Path, *specs: str) -> list[str]:
            return [n for n in real(repo, *specs) if not n.startswith("skipped/")]

        monkeypatch.setattr("tracked.tracked_files", narrowed)
        monkeypatch.setattr("check_gate_config.tracked_files", narrowed)
    problems = check_gate_config.baseline_problems(base_rev, root)
    assert "baseline: skipped/s.py is tracked but was not measured" in problems


def test_baseline_problems_refuses_a_tracked_path_the_base_tree_did_not_measure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """N108, base side: the narrowed `tracked_python_at` hides a base file."""
    root = tmp_path / "repo"
    base_rev = _narrowed_repo(root)
    real = tracked.tracked_python_at
    monkeypatch.setattr(
        "check_gate_config.tracked_python_at",
        lambda repo, rev: {k: v for k, v in real(repo, rev).items() if k != "m.py"},
    )
    problems = check_gate_config.baseline_problems(base_rev, root)
    assert f"baseline: m.py is tracked at {base_rev} but was not measured" in problems


def test_python_names_at_lists_every_python_path_but_vendor(tmp_path: Path) -> None:
    """N108: the independent list is every `.py` the revision names."""
    root = tmp_path / "repo"
    base_rev = _narrowed_repo(root)
    (root / "vendor").mkdir()
    (root / "vendor" / "v.py").write_text("y = 1\n", encoding="utf-8")
    (root / "notes.txt").write_text("n\n", encoding="utf-8")
    _git(root, "add", "vendor/v.py", "notes.txt")
    _git(root, "commit", "-qm", "vendored")
    assert tracked.python_names_at(root, "HEAD") == {"m.py", "skipped/s.py"}
    assert tracked.python_names_at(root, base_rev) == {"m.py"}
    with pytest.raises(RuntimeError):
        tracked.python_names_at(root, "not-a-real-revision")


def test_baseline_problems_accepts_a_fully_measured_pair(tmp_path: Path) -> None:
    """N108: the listing check is silent when every path was measured."""
    root = tmp_path / "repo"
    base_rev = _narrowed_repo(root)
    problems = check_gate_config.baseline_problems(base_rev, root)
    assert not [p for p in problems if "not measured" in p]


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


def test_an_unchanged_secret_scan_holds_and_comments_stay_free(
    tmp_path: Path,
) -> None:
    """C1: each secret-scan workflow is pinned by the sha256 of its parsed
    YAML (`actions_file_pin`), so the committed files hold and a comment or a
    blank line changes nothing."""
    root = _tree(tmp_path)
    assert check_gate_config._gitleaks_ci_problems(root) == []
    for name, pinned in (
        (check_gate_config.GITLEAKS_CI_FILE, check_gate_config.GITLEAKS_CI_SHA256),
        (
            check_gate_config.SECRETS_WEEKLY_FILE,
            check_gate_config.SECRETS_WEEKLY_SHA256,
        ),
    ):
        path = root / name
        text = path.read_text(encoding="utf-8")
        assert check_gate_config.actions_file_pin(text) == pinned
        path.write_text("# a note\n\n" + text + "\n# another\n", encoding="utf-8")
    assert check_gate_config._gitleaks_ci_problems(root) == []
    assert check_gate_config.actions_file_pin(None) is None
    assert check_gate_config.actions_file_pin("- a list\n") is None
    assert check_gate_config.actions_file_pin("on: {1: a, b: c}\n") is None


def test_a_deliberate_scan_change_passes_once_its_pin_moves(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A pin upgrade edits the workflow and the one constant together; the
    refusal names the constant and the digest to set it to."""
    root = _tree(tmp_path)
    scan = root / check_gate_config.GITLEAKS_CI_FILE
    changed = scan.read_text(encoding="utf-8").replace(
        "timeout-minutes: 15", "timeout-minutes: 20", 1
    )
    scan.write_text(changed, encoding="utf-8")
    digest = check_gate_config.actions_file_pin(changed)
    assert digest is not None
    [problem] = check_gate_config._gitleaks_ci_problems(root)
    assert digest in problem
    assert "GITLEAKS_CI_SHA256" in problem
    monkeypatch.setattr(check_gate_config, "GITLEAKS_CI_SHA256", digest)
    assert check_gate_config._gitleaks_ci_problems(root) == []


def test_the_hook_types_to_install_may_only_be_the_default(tmp_path: Path) -> None:
    """W3: the key absent, or set to pre-commit's own default, holds."""
    root = _tree(tmp_path)
    config = root / ".pre-commit-config.yaml"
    text = config.read_text(encoding="utf-8")
    assert "default_install_hook_types" not in text
    config.write_text("default_install_hook_types: [pre-commit]\n" + text)
    assert check_gate_config._hook_problems(root) == []


@pytest.mark.parametrize(
    "job,key,value",
    [
        ("test-shards", "strategy", {"matrix": {"shard": [0, 1, 2]}}),
        ("test-shards", "continue-on-error", True),
        ("test", "needs", []),
        ("test", "if", "success()"),
        ("frontend", "needs", ["frontend-checks"]),
        ("frontend-a11y", "if", False),
        ("frontend-workbench", "continue-on-error", True),
    ],
)
def test_parallel_ci_controls_cannot_drop_or_ignore_a_gate(
    tmp_path: Path, job: str, key: str, value: object
) -> None:
    root = _tree(tmp_path)
    ci = root / ".github/workflows/ci.yml"
    ci_file = check_gate_config._ci_file(ci.read_text())
    assert ci_file is not None
    jobs = check_gate_config._map(ci_file["jobs"])
    check_gate_config._map(jobs[job])[key] = value
    ci.write_text(json.dumps(ci_file))
    assert any(
        f"parallel job {job} is not as pinned" in problem
        for problem in check_gate_config.configuration_problems(root)
    )


@pytest.mark.parametrize(
    "before,after",
    [
        ("coverage report --fail-under=80", "coverage report --fail-under=0"),
        ("include-hidden-files: true", "include-hidden-files: false"),
        ("if-no-files-found: error", "if-no-files-found: warn"),
        ('test "$SHARDS_RESULT" = success', 'test "$SHARDS_RESULT" != failure'),
        ('test "$A11Y_RESULT" = success', 'test "$A11Y_RESULT" != failure'),
        ('--cov-report= "${files[@]}"', "--cov-report= tests/test_gates.py"),
    ],
)
def test_parallel_ci_data_and_verdict_cannot_be_weakened(
    tmp_path: Path, before: str, after: str
) -> None:
    root = _tree(tmp_path)
    ci = root / ".github/workflows/ci.yml"
    text = ci.read_text()
    assert before in text
    ci.write_text(text.replace(before, after, 1))
    assert any(
        "parallel job" in problem
        for problem in check_gate_config.configuration_problems(root)
    )


def test_parallel_jobs_are_required_even_if_their_commands_move(tmp_path: Path) -> None:
    root = _tree(tmp_path)
    ci = root / ".github/workflows/ci.yml"
    ci_file = check_gate_config._ci_file(ci.read_text())
    assert ci_file is not None
    jobs = check_gate_config._map(ci_file["jobs"])
    jobs["unused-browser"] = jobs.pop("frontend-a11y")
    ci.write_text(json.dumps(ci_file))
    assert any(
        "parallel job frontend-a11y is not as pinned" in problem
        for problem in check_gate_config.configuration_problems(root)
    )


def test_parallel_job_unserialisable_yaml_fails_closed() -> None:
    ci_file = check_gate_config._ci_file("jobs:\n  test:\n    date: 2026-10-12\n")
    assert ci_file is not None
    assert "ci: parallel job test is not a JSON mapping" in (
        check_gate_config._parallel_job_problems(ci_file)
    )

"""Every way a test can be kept from failing is a counted suppression (W4).

pytest's skip, importorskip and xfail were counted only behind a `pytest.`
or `mark.` prefix, so `from pytest import skip` and a call to `skip(...)`
went uncounted; and a test marked `live_provider` is deselected by CI's
marker expression and was budgeted nowhere. Both held the gate at "hold"
with a failing test in the tree (review 4's probe_hidden_tests.py).

The samples are assembled at runtime: this file is itself a tracked .py
file the real scan measures, so no suppression may be spelled whole here.
"""

from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import check_gate_config

PYTEST = "py" + "test"
MARK = "mark"


def _git(root: Path, *args: str) -> None:
    git = shutil.which("git")
    assert git is not None
    subprocess.run([git, *args], cwd=root, check=True, capture_output=True)


def _counts(sample: str) -> dict[str, int]:
    return check_gate_config._measure_suppressions([sample])


def test_a_skip_or_xfail_imported_bare_or_aliased_is_counted() -> None:
    sample = "\n".join(
        [
            f"import {PYTEST} as pt",
            f"from {PYTEST} import skip, xfail as expect_failure",
            f"from {PYTEST} import importorskip as need",
            f"from {PYTEST} import {MARK} as m",
            "from _pytest.outcomes import skip as quietly",
            "need('numpy')",
            "@m.skipif(True, reason='x')",
            "@m.xfail",
            "def test_one() -> None:",
            "    skip('imported bare')",
            "    pt.skip('aliased module')",
            "    quietly('from the implementation module')",
            "    expect_failure('aliased xfail')",
        ]
    )
    counts = _counts(sample)
    assert counts["skip"] == 5
    assert counts["xfail"] == 2


def test_a_prefixed_skip_is_counted_once_not_twice() -> None:
    """The text patterns already count `<pytest>.skip` and `<mark>.skip`;
    the resolved names add only what they do not read."""
    sample = "\n".join(
        [
            f"import {PYTEST}",
            f"@{PYTEST}.{MARK}.skip",
            "def test_one() -> None:",
            f"    {PYTEST}.skip('x')",
        ]
    )
    assert _counts(sample)["skip"] == 2


def test_a_live_provider_marker_is_its_own_budget() -> None:
    """CI's `-m "not live_provider"` deselects these; each is budgeted."""
    sample = "\n".join(
        [
            f"import {PYTEST}",
            f"from {PYTEST} import {MARK} as m",
            f"pytestmark = {PYTEST}.{MARK}.live_provider",
            "@m.live_provider",
            "def test_one() -> None: ...",
        ]
    )
    assert _counts(sample)["live_provider"] == 2
    committed = check_gate_config.suppression_counts()
    assert committed["live_provider"] > 0, "the tree carries live tests to budget"


def test_the_reviewed_hidden_tests_are_named_by_the_ratchet(tmp_path: Path) -> None:
    """Review 4's probe: one deselected and one bare-skipped failing test
    once left the gate at "hold"."""
    root = tmp_path / "tree"
    root.mkdir()
    _git(root, "init", "-q")
    (root / "test_hidden.py").write_text(
        "\n".join(
            [
                f"import {PYTEST}",
                f"from {PYTEST} import skip",
                "",
                f"@{PYTEST}.{MARK}.live_provider",
                "def test_marked_live_so_ci_deselects_it() -> None:",
                "    raise AssertionError('never runs under the CI marker expression')",
                "",
                "def test_skipped_through_a_bare_import() -> None:",
                "    skip('imported bare')",
                "    raise AssertionError('never reached')",
            ]
        ),
        encoding="utf-8",
    )
    _git(root, "add", "test_hidden.py")
    baseline = tmp_path / "baseline.json"
    baseline.write_text(json.dumps({}))
    problems = check_gate_config.suppression_problems(root, baseline)
    assert "suppressions: skip rose to 1 (baseline 0)" in problems
    assert "suppressions: live_provider rose to 1 (baseline 0)" in problems


def _load(path: Path, name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        del sys.modules[name]
    return module


def _commit(root: Path, message: str) -> str:
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", message)
    git = shutil.which("git")
    assert git is not None
    done = subprocess.run(
        [git, "rev-parse", "HEAD"], cwd=root, check=True, capture_output=True
    )
    return done.stdout.decode().strip()


def test_a_pattern_weakened_with_the_suppression_it_hides_is_named(
    tmp_path: Path,
) -> None:
    """W5, review 4's commit: a pull request that drops `re.IGNORECASE` from
    the noqa pattern and adds an upper-case NOQA measures both trees under
    its own, weaker rule, sees no rise, and passed. The base branch's own
    rules are applied to both trees as well now, and under them it rose."""
    root = tmp_path / "repo"
    (root / "scripts").mkdir(parents=True)
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "test@example.invalid")
    _git(root, "config", "user.name", "Ratchet test")
    checker = Path(check_gate_config.__file__).read_text(encoding="utf-8")
    (root / "scripts" / "check_gate_config.py").write_text(checker, encoding="utf-8")
    (root / "m.py").write_text("import os\n", encoding="utf-8")
    base = _commit(root, "base")

    strong = 're.compile(r"#\\s*noqa\\b", re.IGNORECASE)'
    assert strong in checker
    weakened = checker.replace(strong, 're.compile(r"#\\s*noqa\\b")')
    (root / "scripts" / "check_gate_config.py").write_text(weakened, encoding="utf-8")
    (root / "m.py").write_text("import os  " + "#" + " NOQA: F401\n", encoding="utf-8")
    _commit(root, "weaken the pattern and spend it")

    pull_request = _load(root / "scripts" / "check_gate_config.py", "_pr_checker")
    # Under the pull request's own rules alone the NOQA is invisible.
    assert pull_request.suppression_counts_at(base, root)["noqa"] == 0
    assert pull_request.suppression_counts(root)["noqa"] == 0
    problems = pull_request.baseline_problems(base, root)
    assert problems == [
        f"baseline: noqa rose to 1 under {base}'s own rules (base branch 0)"
    ]


def test_the_base_rules_are_the_base_checker_s_own(tmp_path: Path) -> None:
    """The measure comes from the base revision's checker, or from its
    `SUPPRESSIONS` alone where it predates the shared measure (84eb06d);
    no checker there is no rule to hold to, and one that will not load is
    refused rather than skipped."""
    measure = check_gate_config.base_measure("84eb06d")
    assert measure is not None
    assert measure(["x = 1  " + "#" + " noqa"])["noqa"] == 1
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "test@example.invalid")
    _git(root, "config", "user.name", "Ratchet test")
    (root / "m.py").write_text("x = 1\n", encoding="utf-8")
    bare = _commit(root, "no checker")
    assert check_gate_config.base_measure(bare, root) is None
    (root / "scripts").mkdir()
    (root / "scripts" / "check_gate_config.py").write_text("import nowhere_at_all\n")
    broken = _commit(root, "a checker that will not load")
    assert check_gate_config.baseline_problems(broken, root) == [
        f"baseline: {broken}'s own checker could not be loaded"
    ]

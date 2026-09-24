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

import json
import shutil
import subprocess
from pathlib import Path

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

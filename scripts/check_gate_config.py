#!/usr/bin/env python3
"""Refuse a gate configuration that has been loosened (spec G16, D15).

Every threshold the gate table states is read back from the files that hold
it, and the number of suppressions in tracked Python is compared with the
committed baseline: it may fall, never rise. `--baseline` rewrites the
baseline from the current tree; it is run once, before new code, and the
result is committed (`tests/gate_baseline.json`).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import tomllib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from tracked import tracked_python

REPO = Path(__file__).resolve().parents[1]
BASELINE = REPO / "tests" / "gate_baseline.json"

RUFF_SELECT = frozenset(
    {
        "E", "F", "W", "I", "UP", "B", "ANN", "BLE", "TRY",
        "C901", "PLR0912", "PLR0913", "PLR0915", "RUF",
    }
)  # fmt: skip
REQUIRES_PYTHON = ">=3.13,<3.14"
PYTHON_VERSION = "3.13"
COVERAGE_OMIT = ["tests/*", "vendor/*", ".venv*/*"]
ADDOPTS = ("--strict-markers", "--cov", "--cov-branch", "--cov-fail-under=80")
PRE_COMMIT_HOOKS = frozenset(
    {
        "ruff", "ruff-format", "gitleaks", "check-added-large-files",
        "check-merge-conflict", "end-of-file-fixer", "trailing-whitespace",
        "vocabulary", "tested", "io-budget",
    }
)  # fmt: skip
PARITY_GROUPS = (
    "cash_flow", "pricing", "budget", "forecast", "routes", "digest",
    "boundary_text", "extraction", "citations", "render", "prompt",
)  # fmt: skip
SUPPRESSIONS = {
    "noqa": re.compile(r"#\s*noqa\b"),
    "type_ignore": re.compile(r"#\s*type:\s*ignore\b"),
    "nosec": re.compile(r"#\s*nosec\b"),
    "no_cover": re.compile(r"#\s*pragma:\s*no cover\b"),
    "skip": re.compile(r"pytest\.mark\.skip\b"),
    "xfail": re.compile(r"pytest\.mark\.xfail\b"),
}


def _tool_problems(tool: dict[str, object]) -> list[str]:
    problems: list[str] = []
    ruff = _table(tool, "ruff")
    lint = _table(ruff, "lint")
    if not RUFF_SELECT <= set(_list(lint, "select")):
        problems.append("ruff: a rule family was dropped")
    if _table(lint, "mccabe").get("max-complexity") != 10:
        problems.append("ruff: mccabe max-complexity is not 10")
    if ruff.get("line-length") != 88:
        problems.append("ruff: line-length is not 88")
    if _table(tool, "mypy").get("strict") is not True:
        problems.append("mypy: strict is off")
    addopts = str(_table(_table(tool, "pytest"), "ini_options").get("addopts", ""))
    problems += [
        f"pytest: {f} missing from addopts" for f in ADDOPTS if f not in addopts
    ]
    if _table(_table(tool, "coverage"), "run").get("omit") != COVERAGE_OMIT:
        problems.append("coverage: omit list moved")
    return problems


def _python_problems(root: Path, project: dict[str, object]) -> list[str]:
    problems: list[str] = []
    if _table(project, "project").get("requires-python") != REQUIRES_PYTHON:
        problems.append("requires-python moved")
    pinned = (root / ".python-version").read_text(encoding="utf-8").strip()
    if pinned != PYTHON_VERSION:
        problems.append(".python-version moved")
    if (root / "requirements.txt").exists():
        problems.append("requirements.txt present at the root (switches Apps to pip)")
    return problems


def _hook_problems(root: Path) -> list[str]:
    config = (root / ".pre-commit-config.yaml").read_text(encoding="utf-8")
    hooks = set(re.findall(r"^\s*-\s*id:\s*(\S+)", config, re.M))
    missing = sorted(PRE_COMMIT_HOOKS - hooks)
    return [f"pre-commit: hooks missing {missing}"] if missing else []


def _parity_problems(root: Path) -> list[str]:
    problems: list[str] = []
    for group in PARITY_GROUPS:
        manifest = root / "tests" / "parity" / "golden" / group / "manifest.json"
        try:
            cases = json.loads(manifest.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            problems.append(f"parity: {group} has no manifest")
            continue
        if not cases:
            problems.append(f"parity: {group} has no cases")
    return problems


def _table(mapping: dict[str, object], key: str) -> dict[str, object]:
    value = mapping.get(key)
    return value if isinstance(value, dict) else {}


def _list(mapping: dict[str, object], key: str) -> list[object]:
    value = mapping.get(key)
    return value if isinstance(value, list) else []


def configuration_problems(root: Path = REPO) -> list[str]:
    """Every threshold that moved, by name; an empty list when none did."""
    try:
        project = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return ["pyproject.toml: unreadable"]
    return (
        _tool_problems(_table(project, "tool"))
        + _python_problems(root, project)
        + _hook_problems(root)
        + _parity_problems(root)
    )


SNAPSHOT = "complexipy-snapshot.json"


def suppression_counts(root: Path = REPO) -> dict[str, int]:
    """How many of each suppression the tracked Python files carry, and how
    many functions the cognitive-complexity baseline (G14) still carries."""
    counts = dict.fromkeys(SUPPRESSIONS, 0)
    for path in tracked_python(root):
        text = path.read_text(encoding="utf-8")
        for name, pattern in SUPPRESSIONS.items():
            counts[name] += len(pattern.findall(text))
    counts["complexity_baselined"] = _baselined_functions(root / SNAPSHOT)
    return counts


def _baselined_functions(snapshot: Path) -> int:
    try:
        recorded = json.loads(snapshot.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return 0
    return sum(len(entry.get("functions", [])) for entry in recorded)


def suppression_problems(root: Path = REPO, baseline: Path = BASELINE) -> list[str]:
    """Each suppression kind whose count rose above the baseline."""
    try:
        allowed = json.loads(baseline.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ["baseline: tests/gate_baseline.json unreadable"]
    counts = suppression_counts(root)
    return [
        f"suppressions: {name} rose to {count} (baseline {allowed.get(name)})"
        for name, count in counts.items()
        if count > int(allowed.get(name, 0))
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", action="store_true", help="rewrite the baseline")
    args = parser.parse_args(argv)
    if args.baseline:
        BASELINE.write_text(
            json.dumps(suppression_counts(), indent=2, sort_keys=True) + "\n"
        )
        print(f"wrote {BASELINE.relative_to(REPO)}")
        return 0
    problems = configuration_problems() + suppression_problems()
    for problem in problems:
        print(problem)
    if problems:
        return 1
    print("gate configuration and suppression budget hold")
    return 0


if __name__ == "__main__":
    sys.exit(main())

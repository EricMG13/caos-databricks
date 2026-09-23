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
PARITY_PACKAGE = "server"  # the legacy snapshot the goldens describe
PARITY_CASE_FLOOR = {
    "cash_flow": 71,
    "pricing": 46,
    "budget": 22,
    "forecast": 16,
    "routes": 72,
    "digest": 15,
    "boundary_text": 50,
    "extraction": 15,
    "citations": 14,
    "render": 30,
    "prompt": 27,
}
PARITY_GROUPS = (
    "cash_flow", "pricing", "budget", "forecast", "routes", "digest",
    "boundary_text", "extraction", "citations", "render", "prompt",
)  # fmt: skip
# Each pattern is the tool's own grammar, not the house spelling (F58): ruff
# reads its directive in upper case too, coverage reads its pragma in any
# case and spacing, pytest reads the skipif marker, the skip call, the
# importorskip call and a `mark` imported bare. A form the gate did not
# count was a budget with no ceiling.
SUPPRESSIONS = {
    "noqa": re.compile(r"#\s*noqa\b", re.IGNORECASE),
    "type_ignore": re.compile(r"#\s*type:\s*ignore\b"),
    "nosec": re.compile(r"#\s*nosec\b"),
    "no_cover": re.compile(
        r"#\s*(?:pragma|PRAGMA)[:\s]?\s*(?:no|NO)\s*(?:cover|COVER)"
    ),
    "skip": re.compile(r"(?:\bpytest\.|\bmark\.)(?:skip(?:if)?|importorskip)\b"),
    "xfail": re.compile(r"(?:\bpytest\.|\bmark\.)xfail\b"),
}
# What the App must ship (F48): a sync pattern that hides any of these hides
# the methodology while health stays green.
SHIPPED = (
    "vendor/deploy-v/DEPLOY_V_INTEGRITY_v1.json",
    "vendor/deploy-v/CANON_SHARED.md",
    "vendor/deploy-v/skills/cp-0-source-readiness/SKILL.md",
    "icm/CONTEXT.md",
    "icm/HOST_INTEGRITY_v1.json",
    "icm/shared/prompt/instruction.md",
    "icm/stages/cp-cf/references/SKILL.md",
    "caos/serve.py",
    "app.yaml",
    "pyproject.toml",
    "uv.lock",
    ".python-version",
    "frontend/dist/index.html",
)
# What the bundle must set: the process refuses or runs on a legacy default
# without each of these (F52).
APP_ENVIRONMENT = frozenset(
    {
        "CAOS_BIND_HOST", "CAOS_WORKER_IN_PROCESS", "CAOS_SITE_ROOT",
        "CAOS_MODEL_ENDPOINT", "CAOS_MODEL_PRICE", "CAOS_RUN_CEILING",
        "CAOS_UC_SCHEMA", "CAOS_BLOB_ROOT", "CAOS_LAKEBASE_INSTANCE",
        "CAOS_GROUP_ADMIN", "CAOS_GROUP_ANALYST",
    }
)  # fmt: skip


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
    """Every golden group is present, written from the legacy snapshot and
    no smaller than when it was committed (F57): a golden regenerated from
    the rebuilt package would match a regression rather than catch it."""
    problems: list[str] = []
    for group in PARITY_GROUPS:
        manifest = root / "tests" / "parity" / "golden" / group / "manifest.json"
        try:
            document = json.loads(manifest.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            problems.append(f"parity: {group} has no manifest")
            continue
        cases = document.get("cases") if isinstance(document, dict) else None
        if not cases:
            problems.append(f"parity: {group} has no cases")
            continue
        if document.get("package") != PARITY_PACKAGE:
            problems.append(f"parity: {group} was not written from {PARITY_PACKAGE}")
        if len(cases) < PARITY_CASE_FLOOR.get(group, 1):
            problems.append(
                f"parity: {group} fell below {PARITY_CASE_FLOOR[group]} cases"
            )
    return problems


def _matches(pattern: str, path: str) -> bool:
    """gitignore's rule as the CLI applies it: `*` and `?` stop at a slash,
    `**` does not, a pattern with no slash matches the name at every depth
    and one with a slash matches from the root."""
    anchored = "/" in pattern.rstrip("/")
    expression = re.escape(pattern.rstrip("/")).replace(r"\*\*", ".*")
    expression = expression.replace(r"\*", "[^/]*").replace(r"\?", "[^/]")
    if anchored:
        return re.fullmatch(expression + "(?:/.*)?", path) is not None
    return any(re.fullmatch(expression, part) for part in path.split("/"))


def _read(root: Path, name: str) -> str | None:
    try:
        return (root / name).read_text(encoding="utf-8")
    except OSError:
        return None


def _bundle_problems(root: Path) -> list[str]:
    problems: list[str] = []
    bundle, app = _read(root, "databricks.yml"), _read(root, "app.yaml")
    if bundle is None or app is None:
        return ["bundle: databricks.yml or app.yaml missing"]
    sync = bundle.partition("\nsync:")[2].partition("\ntargets:")[0]
    excludes = re.findall(
        r"^\s+-\s*\"?([^\"\n#]+?)\"?\s*$", sync.partition("exclude:")[2], re.M
    )
    for pattern in excludes:
        for path in SHIPPED:
            if _matches(pattern, path):
                problems.append(f"bundle: sync.exclude {pattern!r} hides {path}")
    named = set(re.findall(r"^\s+-\s*name:\s*(CAOS_\w+)", bundle, re.M))
    for missing in sorted(APP_ENVIRONMENT - named):
        problems.append(f"bundle: env does not set {missing}")
    if re.search(r"^env:", app, re.M):
        problems.append("app.yaml: sets env; the bundle is the one source (F52)")
    return problems


def _gitleaks_problems(root: Path) -> list[str]:
    hooks = _read(root, ".pre-commit-config.yaml") or ""
    pinned = re.search(r"gitleaks/gitleaks\n\s*rev:\s*(v[\d.]+)", hooks)
    ci = _read(root, ".github/workflows/ci.yml") or ""
    image = re.search(r"ghcr\.io/gitleaks/gitleaks:(v[\d.]+)@sha256:[0-9a-f]{64}", ci)
    if pinned is None or image is None:
        return ["gitleaks: not pinned in both the hook and the CI image"]
    if pinned.group(1) != image.group(1):
        return [
            f"gitleaks: hook {pinned.group(1)} and CI image {image.group(1)} differ"
        ]
    return []


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
        + _bundle_problems(root)
        + _gitleaks_problems(root)
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


def baseline_problems(against: Path, baseline: Path = BASELINE) -> list[str]:
    """Each budget the committed baseline raised above `against`, the base
    branch's copy (F58): the change that breaches a budget cannot also be the
    change that rewrites it."""
    try:
        base = json.loads(against.read_text(encoding="utf-8"))
        now = json.loads(baseline.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ["baseline: a baseline to compare is unreadable"]
    return [
        f"baseline: {name} rose to {count} (base branch {base.get(name)})"
        for name, count in now.items()
        if name in base and int(count) > int(base[name])
    ]


def shipped_problems(record: Path) -> list[str]:
    """Each path the app needs that the CLI's deployment record does not list."""
    try:
        listed = json.loads(record.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return [f"shipped: {record} unreadable"]
    files = {entry.get("local_path") for entry in listed.get("files", [])}
    return [f"shipped: {path} was not synced" for path in SHIPPED if path not in files]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", action="store_true", help="rewrite the baseline")
    parser.add_argument("--against", type=Path, help="the base branch's baseline file")
    parser.add_argument("--shipped", type=Path, help="the CLI's deployment.json")
    args = parser.parse_args(argv)
    if args.shipped is not None:
        problems = shipped_problems(args.shipped)
        for problem in problems:
            print(problem)
        if problems:
            return 1
        print("every path the app needs was synced")
        return 0
    if args.against is not None:
        problems = baseline_problems(args.against)
        for problem in problems:
            print(problem)
        if problems:
            return 1
        print("no budget rose against the base branch")
        return 0
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

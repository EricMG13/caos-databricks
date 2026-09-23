#!/usr/bin/env python3
"""Refuse a gate configuration that has been loosened (spec G16, D15).

Every threshold the gate table states is read back from the files that hold
it, as the tool will apply it: a key that could narrow what a tool reads or
silence what it reports is refused, not only a threshold that moved (MAX-13).
The number of suppressions in tracked Python must equal the committed
baseline: a new one fails, and so does one removed while the baseline keeps
its room (DF-11). `--baseline` rewrites the baseline from the current tree,
and `--against` refuses a baseline that rose above an earlier commit's.
"""

from __future__ import annotations

import argparse
import json
import re
import shlex
import sys
import tomllib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from tracked import tracked_files, tracked_python

REPO = Path(__file__).resolve().parents[1]
BASELINE = REPO / "tests" / "gate_baseline.json"

RUFF_SELECT = frozenset(
    {
        "E", "F", "W", "I", "UP", "B", "ANN", "BLE", "TRY",
        "C901", "PLR0912", "PLR0913", "PLR0915", "RUF",
    }
)  # fmt: skip
# The only keys the ruff configuration may carry. Anything else -- `ignore`,
# `per-file-ignores`, `exclude`, a `pylint` table that raises a ceiling, an
# `extend` that pulls in another file -- narrows what ruff reads or reports.
RUFF_KEYS = frozenset({"target-version", "line-length", "extend-exclude", "lint"})
RUFF_LINT_KEYS = frozenset({"select", "extend-select", "mccabe"})
RUFF_EXCLUDE = [".venv", "vendor", ".claude/worktrees"]
# mypy exactly as committed: an override, `ignore_errors` or a disabled
# error code is a key this table does not hold.
MYPY = {
    "python_version": "3.13",
    "strict": True,
    "mypy_path": "stubs",
    "exclude": ["^\\.venv/", "^vendor/"],
}
REQUIRES_PYTHON = ">=3.13,<3.14"
PYTHON_VERSION = "3.13"
COVERAGE_OMIT = ["tests/*", "vendor/*", ".venv*/*"]
COVERAGE_RUN = {"branch": True, "source": ["."], "omit": COVERAGE_OMIT}
PYTEST_KEYS = frozenset({"testpaths", "addopts", "markers"})
ADDOPTS = ("--strict-markers", "--cov", "--cov-branch", "--cov-fail-under=80")
# Every option `addopts` may carry: a second `--cov-fail-under`, a narrowed
# `--cov=<package>`, `--ignore`, `--deselect` or `-p no:...` is refused.
ADDOPTS_ALLOWED = frozenset(
    {*ADDOPTS, "-q", "--cov-report=xml", "--cov-report=term:skip-covered"}
)
# Files each tool reads before pyproject.toml, or instead of it below their
# directory: one of these anywhere outside the vendored tree overrides the
# committed configuration without touching it.
OVERRIDING = (
    "ruff.toml", ".ruff.toml", "mypy.ini", ".mypy.ini", "pytest.ini",
    ".pytest.ini", "tox.ini", "setup.cfg", ".coveragerc", "pyproject.toml",
)  # fmt: skip
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
    "citations": 18,
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
# count was a budget with no ceiling. The whole-file forms count too
# (MAX-13): ruff's and flake8's file directive, mypy's inline configuration
# and its decorator that turns checking off, unittest's skips and expected
# failures, and coverage's branch pragma. The patterns are written so this
# file matches none of them.
SUPPRESSIONS = {
    "noqa": re.compile(r"#\s*noqa\b", re.IGNORECASE),
    "file_noqa": re.compile(r"#\s*(?:ruff|flake8)\s*:\s*noqa\b", re.IGNORECASE),
    "type_ignore": re.compile(r"#\s*type:\s*ignore\b"),
    "mypy_directive": re.compile(r"#\s*mypy\s*:|\bno_type_check\b"),
    "nosec": re.compile(r"#\s*nosec\b"),
    "no_cover": re.compile(
        r"#\s*(?:pragma|PRAGMA)[:\s]?\s*(?:no|NO)\s*(?:cover|COVER|branch|BRANCH)"
    ),
    "skip": re.compile(
        r"(?:\bpytest\.|\bmark\.)(?:skip(?:if)?|importorskip)\b"
        r"|\bunittest\.skip\w*|\bskip(?:If|Unless|Test)\b|\bSkipTest\b"
    ),
    "xfail": re.compile(r"(?:\bpytest\.|\bmark\.)xfail\b|\bexpectedFailure\b"),
}
# What the App must ship (F48): the sample every deployment record must
# list, whatever else the tree holds. `--shipped` also asks for every
# tracked file under `SYNC_ROOTS` and every file of the built export.
SHIPPED = (
    "vendor/deploy-v/DEPLOY_V_INTEGRITY_v1.json",
    "vendor/deploy-v/CANON_SHARED.md",
    "vendor/deploy-v/skills/cp-0-source-readiness/SKILL.md",
    # Nested `scripts/` and `tests/` directories, and a package directory
    # that a denylist's `dir/**` once matched at every depth (C2).
    "vendor/deploy-v/skills/cp-1-canonical-data-foundation/scripts/completeness_check.py",
    "vendor/deploy-v/tests/test_regressions.py",
    "caos/qualification/store.py",
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
# What the process reads, as the roots the sync allowlist must carry: the
# package, the agent definitions, the bundle authority, the export and the
# lock. `sync.paths` must list each of these or a directory above it.
SYNC_ROOTS = (
    "caos", "icm", "vendor", "frontend/dist",
    "app.yaml", "pyproject.toml", "uv.lock", ".python-version",
)  # fmt: skip
EXPORT = "frontend/dist"
# What the bundle must set: the process refuses or runs on a legacy default
# without each of these (F52).
APP_ENVIRONMENT = frozenset(
    {
        "CAOS_BIND_HOST", "CAOS_WORKER_IN_PROCESS", "CAOS_SITE_ROOT",
        "CAOS_MODEL_ENDPOINT", "CAOS_MODEL_PRICE", "CAOS_RUN_CEILING",
        "CAOS_BLOB_ROOT", "CAOS_LAKEBASE_INSTANCE",
        "CAOS_GROUP_ADMIN", "CAOS_GROUP_ANALYST",
    }
)  # fmt: skip


def _tool_problems(tool: dict[str, object]) -> list[str]:
    return (
        _ruff_problems(_table(tool, "ruff"))
        + _mypy_problems(_table(tool, "mypy"))
        + _pytest_problems(_table(_table(tool, "pytest"), "ini_options"))
        + _coverage_problems(_table(tool, "coverage"))
    )


def _ruff_problems(ruff: dict[str, object]) -> list[str]:
    lint = _table(ruff, "lint")
    problems = [
        f"ruff: {key} is set; it can narrow what ruff reads"
        for key in sorted(set(ruff) - RUFF_KEYS)
    ] + [
        f"ruff: lint.{key} is set; it can silence a rule"
        for key in sorted(set(lint) - RUFF_LINT_KEYS)
    ]
    if not RUFF_SELECT <= set(_list(lint, "select")):
        problems.append("ruff: a rule family was dropped")
    if _table(lint, "mccabe") != {"max-complexity": 10}:
        problems.append("ruff: mccabe max-complexity is not 10")
    if ruff.get("line-length") != 88:
        problems.append("ruff: line-length is not 88")
    if ruff.get("extend-exclude") != RUFF_EXCLUDE:
        problems.append("ruff: extend-exclude moved")
    return problems


def _mypy_problems(mypy: dict[str, object]) -> list[str]:
    if mypy.get("strict") is not True:
        return ["mypy: strict is off"]
    return [
        f"mypy: {key} is not as committed"
        for key in sorted(set(mypy) | set(MYPY))
        if mypy.get(key) != MYPY.get(key)
    ]


def _pytest_problems(ini: dict[str, object]) -> list[str]:
    problems = [
        f"pytest: {key} is set; it can narrow what pytest runs"
        for key in sorted(set(ini) - PYTEST_KEYS)
    ]
    if ini.get("testpaths") != ["tests"]:
        problems.append("pytest: testpaths moved")
    try:
        options = shlex.split(str(ini.get("addopts", "")))
    except ValueError:
        options = []
    problems += [
        f"pytest: {f} missing from addopts" for f in ADDOPTS if f not in options
    ]
    problems += [
        f"pytest: addopts carries {option!r}"
        for option in options
        if option not in ADDOPTS_ALLOWED
    ]
    if len(options) != len(set(options)):
        problems.append("pytest: addopts repeats an option; the last one wins")
    return problems


def _coverage_problems(coverage: dict[str, object]) -> list[str]:
    run = _table(coverage, "run")
    problems = [
        f"coverage: {key} is set; it can exclude what is measured"
        for key in sorted(set(coverage) - {"run"})
    ]
    if run.get("omit") != COVERAGE_OMIT:
        problems.append("coverage: omit list moved")
    problems += [
        f"coverage: run.{key} is not as committed"
        for key in sorted(set(run) | set(COVERAGE_RUN))
        if key != "omit" and run.get(key) != COVERAGE_RUN.get(key)
    ]
    return problems


def _overriding_problems(root: Path) -> list[str]:
    """A configuration file a tool reads before the root pyproject.toml, or
    in its place below its own directory (MAX-13)."""
    found = tracked_files(root, *(f":(glob)**/{name}" for name in OVERRIDING))
    return [
        f"{name}: overrides the committed tool configuration"
        for name in found
        if name != "pyproject.toml" and not name.startswith("vendor/")
    ]


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


def _sync_lists(sync: str) -> dict[str, list[str]]:
    """The bundle's `sync` block as its lists: `paths`, `include`, `exclude`."""
    lists: dict[str, list[str]] = {}
    current: list[str] | None = None
    for line in sync.splitlines():
        if (key := re.fullmatch(r"  (\w+):\s*", line)) is not None:
            current = lists.setdefault(key.group(1), [])
        elif current is not None and (
            item := re.fullmatch(r"\s+-\s*\"?([^\"\n#]+?)\"?\s*", line)
        ):
            current.append(item.group(1))
    return lists


def _under(path: str, listed: str) -> bool:
    root = listed.rstrip("/")
    return path == root or path.startswith(root + "/")


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
    sync = _sync_lists(bundle.partition("\nsync:")[2].partition("\ntargets:")[0])
    paths = sync.get("paths", [])
    if not paths:
        # A denylist shipped whatever a working tree held and dropped nested
        # package directories (C2, TM-3); the allowlist is the rule.
        problems.append("bundle: sync.paths is not set; the sync must be an allowlist")
    problems += [
        f"bundle: sync.paths does not carry {needed}"
        for needed in SYNC_ROOTS
        if paths and not any(_under(needed, listed) for listed in paths)
    ]
    # With an allowlist there is nothing to exclude, and no spelling of an
    # exclude is read here: a flow-style list, a character class, a file
    # outside a sample (DQ-9). Any `exclude` key, and any `sync` a target
    # sets for itself, is refused as text.
    code = "\n".join(line.partition("#")[0] for line in bundle.splitlines())
    if re.search(r"\bexclude\s*:", code):
        problems.append("bundle: an exclude is set; the sync is an allowlist")
    if re.search(r"^[ \t]+sync\s*:", code, re.M):
        problems.append("bundle: a target sets its own sync; there is one allowlist")
    if "frontend/dist/**" not in sync.get("include", []):
        problems.append("bundle: sync.include lacks frontend/dist/** (git-ignored)")
    named = set(re.findall(r"^\s+-\s*name:\s*(CAOS_\w+)", bundle, re.M))
    for missing in sorted(APP_ENVIRONMENT - named):
        problems.append(f"bundle: env does not set {missing}")
    if re.search(r"^env:", app, re.M):
        problems.append("app.yaml: sets env; the bundle is the one source (F52)")
    return problems


def ci_commands(ci_text: str) -> list[str]:
    """Every command a CI file's `run:` steps execute, whitespace collapsed:
    a folded block is one command, a literal block one per line (with its
    backslash continuations joined)."""
    lines = ci_text.splitlines()
    commands: list[str] = []
    for index, line in enumerate(lines):
        step = re.match(r"^(\s*)(-\s+)?run:\s*(.*?)\s*$", line)
        if step is None:
            continue
        value = step.group(3)
        if value not in ("|", "|-", ">", ">-"):
            commands.append(value)
            continue
        indent = len(step.group(1)) + len(step.group(2) or "")
        block: list[str] = []
        for follow in lines[index + 1 :]:
            if follow.strip() and len(follow) - len(follow.lstrip()) <= indent:
                break
            block.append(follow.strip())
        joined = "\n".join(block).replace("\\\n", " ")
        commands += (
            [joined.replace("\n", " ")] if value[0] == ">" else joined.split("\n")
        )
    return [" ".join(command.split()) for command in commands if command.strip()]


STAND_IN = "uv run python tests/workspace_stub.py --"
STAND_IN_VARS = (
    "--var uc_catalog=main --var uc_schema=caos --var lakebase_instance=caos-lb"
)
STAND_IN_PRICE = (
    "BUNDLE_VAR_model_price=databricks-claude-opus-5,0.000007,0.000030,2026-09-23"
)
# Each gate CLAUDE.md lists, as CI runs it (MAX-13): a step removed, a
# threshold raised or a command made to pass whatever it finds is a gate
# that no longer runs. `|| true` stands on one command only, bandit's JSON
# report, whose verdict is the floor check after it.
CI_GATES = (
    "uv run ruff check .",
    "uv run ruff format --check .",
    "uv run python scripts/check_vocabulary.py",
    "uv run python scripts/check_tested.py",
    "uv run python scripts/io_budget.py --assert",
    "uv run python scripts/check_gate_config.py",
    "uv run python scripts/check_icm.py",
    "uv run complexipy caos scripts icm --max-complexity-allowed 15",
    "uv run pre-commit run --all-files --show-diff-on-failure",
    "uv run mypy caos scripts tests",
    'uv run pytest -n auto -m "not live_provider" --max-worker-restart=0 '
    "-o faulthandler_timeout=600 -ra --durations=25",
    "uv run python scripts/scan_floors.py coverage.xml --cobertura",
    "uv run pytest --no-cov tests/test_postgres_races.py",
    "uv run python scripts/scan_floors.py bandit.json --no-parse-errors "
    "--cover caos scripts icm --unscanned tests",
    "uv run bandit -r caos scripts icm",
    "uv run pip-audit --strict",
    'uv run python scripts/check_gate_config.py --against "$RUNNER_TEMP/base.json"',
    f"{STAND_IN_PRICE} {STAND_IN} databricks bundle validate -t dev {STAND_IN_VARS}",
    f'{STAND_IN} sh -c "databricks bundle deploy -t dev {STAND_IN_VARS} '
    f'&& databricks bundle run caos -t dev {STAND_IN_VARS}"',
    "uv run python scripts/check_gate_config.py --shipped "
    ".databricks/bundle/dev/deployment.json",
    f'{STAND_IN} sh -c "databricks bundle validate -t prod {STAND_IN_VARS} '
    f"&& databricks bundle deploy -t prod {STAND_IN_VARS} "
    f'&& databricks bundle run caos -t prod {STAND_IN_VARS}"',
    "uv run python scripts/check_gate_config.py --shipped "
    ".databricks/bundle/prod/deployment.json",
    "npm run lint",
    "npm run typecheck",
    "npm test",
    "npm run build",
    "npm run build:demo",
    "npx --no-install jscpd --threshold 3 --min-lines 10 --ignore "
    '"**/node_modules/**,**/dist/**,**/dist-demo/**" ../caos ../scripts ../icm src',
    "npm run a11y",
    "npm run test:workbench",
)
EXCUSED = "uv run bandit -r caos scripts icm -f json -o bandit.json || true"
# A failure turned into a success: `|| true`, `|| :`, `|| exit 0`, `set +e`.
SWALLOWED = re.compile(r"\|\|\s*(?:true\b|:(?:\s|;|$)|exit\s+0\b)|\bset\s+\+e\b")


def _ci_problems(root: Path) -> list[str]:
    ci_text = _read(root, ".github/workflows/ci.yml")
    if ci_text is None:
        return ["ci: .github/workflows/ci.yml missing"]
    commands = ci_commands(ci_text)
    problems = [
        f"ci: no step runs {gate!r}" for gate in CI_GATES if gate not in commands
    ]
    problems += [
        f"ci: {command!r} cannot fail"
        for command in commands
        if SWALLOWED.search(command) and command != EXCUSED
    ]
    for key in ("continue-on-error", "PYTEST_ADDOPTS"):
        if key in ci_text:
            problems.append(f"ci: {key} is set; a gate would pass whatever it finds")
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
        + _overriding_problems(root)
        + _python_problems(root, project)
        + _hook_problems(root)
        + _parity_problems(root)
        + _bundle_problems(root)
        + _ci_problems(root)
        + _gitleaks_problems(root)
    )


SNAPSHOT = "complexipy-snapshot.json"


def suppression_counts(root: Path = REPO) -> dict[str, int]:
    """How many of each suppression the tracked Python files carry, how many
    functions the cognitive-complexity baseline (G14) still carries, and the
    complexity it allows them in all: a recorded value raised (31 to 60)
    lets its function grow while the count stays put (MAX-13)."""
    counts = dict.fromkeys(SUPPRESSIONS, 0)
    for path in tracked_python(root):
        text = path.read_text(encoding="utf-8")
        for name, pattern in SUPPRESSIONS.items():
            counts[name] += len(pattern.findall(text))
    functions = _baselined_functions(root / SNAPSHOT)
    counts["complexity_baselined"] = len(functions)
    counts["complexity_total"] = sum(functions)
    return counts


def _baselined_functions(snapshot: Path) -> list[int]:
    """The complexity recorded for each function the snapshot baselines."""
    try:
        recorded = json.loads(snapshot.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return [
        int(function.get("complexity", 0))
        for entry in recorded
        for function in entry.get("functions", [])
    ]


def suppression_problems(root: Path = REPO, baseline: Path = BASELINE) -> list[str]:
    """Each suppression kind whose count is not the baseline's. A ratchet
    (DF-11): a count above it is a new suppression, and a count below it is
    room a later change could spend unseen, so the change that removes a
    suppression lowers the baseline with it."""
    try:
        allowed = json.loads(baseline.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ["baseline: tests/gate_baseline.json unreadable"]
    counts = suppression_counts(root)
    problems: list[str] = []
    for name, count in counts.items():
        budget = int(allowed.get(name, 0))
        if count > budget:
            problems.append(f"suppressions: {name} rose to {count} (baseline {budget})")
        elif count < budget:
            problems.append(
                f"suppressions: {name} fell to {count} (baseline {budget}): "
                "lower tests/gate_baseline.json to match"
            )
    return problems


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


def shipped_files(root: Path = REPO) -> set[str]:
    """What a deployment must carry (DF-4, DQ-9): every tracked file under the
    sync roots, every file of the built export (git-ignored, so read from
    disk) and the `SHIPPED` sample, so an export reduced to its page, or a
    runtime file no sample names, is a file missing rather than a pass."""
    tracked = tracked_files(root, *(r for r in SYNC_ROOTS if r != EXPORT))
    present = {name for name in tracked if (root / name).is_file()}
    export = root / EXPORT
    built = {
        path.relative_to(root).as_posix()
        for path in export.rglob("*")
        if path.is_file()
    }
    return present | built | set(SHIPPED)


def shipped_problems(record: Path, root: Path = REPO) -> list[str]:
    """Each path the app needs that the CLI's deployment record does not list."""
    try:
        listed = json.loads(record.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return [f"shipped: {record} unreadable"]
    files = {entry.get("local_path") for entry in listed.get("files", [])}
    missing = sorted(shipped_files(root) - files)
    shown = [f"shipped: {path} was not synced" for path in missing[:20]]
    if len(missing) > len(shown):
        shown.append(f"shipped: and {len(missing) - len(shown)} more")
    return shown


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

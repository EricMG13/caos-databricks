#!/usr/bin/env python3
"""Refuse a gate configuration that has been loosened (spec G16, D15).

Every threshold the gate table states is read back from the files that hold
it, as the tool will apply it: a key that could narrow what a tool reads or
silence what it reports is refused, not only a threshold that moved (MAX-13).
The number of suppressions in tracked Python must equal the committed
baseline: a new one fails, and so does one removed while the baseline keeps
its room (DF-11). `--baseline` rewrites the baseline from the current tree,
and `--against <revision>` refuses a count that rose above that revision's
own tree, both measured fresh under this commit's rules (FP-11).
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import shlex
import sys
import tomllib
from collections.abc import Iterable
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from tracked import blob_at, tracked_files, tracked_python, tracked_python_at

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
    # complexipy reads either spelling of its own TOML file, and bandit
    # reads its legacy ini-style file, ahead of anything the gate table
    # states (FP-10); neither is committed today, so either appearing at
    # all overrides the CLI flags the gates invoke.
    "complexipy.toml", ".complexipy.toml", ".bandit",
)  # fmt: skip
PRE_COMMIT_HOOKS = frozenset(
    {
        "ruff", "ruff-format", "gitleaks", "check-added-large-files",
        "check-merge-conflict", "end-of-file-fixer", "trailing-whitespace",
        "vocabulary", "tested", "io-budget",
    }
)  # fmt: skip
# The five keys on a hook's own body that change whether or on what it runs
# (AR-07, N46): `entry` swapped for a no-op, `stages` moved off the default
# run, and `files`/`exclude`/`args` narrowed all disable a hook while its
# `id` keeps naming it present in `PRE_COMMIT_HOOKS` above. Each hook not
# listed here must carry none of the five; a hook that is listed is held to
# exactly the value given.
HOOK_KEYS = ("entry", "stages", "files", "exclude", "args")
_LARGE_FILES_EXCLUDE = (
    r"^(vendor/|qualification/ba-fy2025/documents/BA_FY2025_10K\.txt$|"
    r"qualification/f-fy2025/documents/F_FY2025_10K\.txt$|"
    r"qualification/ccl-fy2025-covenant-refinancing/documents/"
    r"CCL_2025_Revolving_Credit_Agreement\.txt$|"
    r"qualification/ccl-fy2025-full-relative-value/documents/"
    r"CCL_2025_Revolving_Credit_Agreement\.txt$|"
    r"qualification/ccl-fy2025-lite-covenant-refinancing/documents/"
    r"CCL_2025_Revolving_Credit_Agreement\.txt$|"
    r"qualification/ccl-fy2025-lite-full-credit-screen/documents/"
    r"CCL_2025_Revolving_Credit_Agreement\.txt$|"
    r"qualification/save-2024-distressed-restructuring/documents/"
    r"SAVE_2024_RSA_with_Chapter_11_Plan\.txt$|"
    r"qualification/save-2024-lite-distressed-restructuring/documents/"
    r"SAVE_2024_RSA_with_Chapter_11_Plan\.txt$)"
)
_VENDOR_QUAL_EXCLUDE = (
    r"^(vendor/|qualification/.*/documents/|\.claude/skills/|"
    r"complexipy-snapshot\.json$)"
)
PRE_COMMIT_HOOK_BODY: dict[str, dict[str, str]] = {
    "ruff": {"args": "[--fix]", "exclude": "^vendor/"},
    "ruff-format": {"exclude": "^vendor/"},
    "check-added-large-files": {"exclude": _LARGE_FILES_EXCLUDE},
    "check-merge-conflict": {"exclude": "^vendor/"},
    "end-of-file-fixer": {"exclude": _VENDOR_QUAL_EXCLUDE},
    "trailing-whitespace": {"exclude": _VENDOR_QUAL_EXCLUDE},
    "vocabulary": {"entry": "uv run python scripts/check_vocabulary.py"},
    "tested": {"entry": "uv run python scripts/check_tested.py"},
    "io-budget": {"entry": "uv run python scripts/io_budget.py --assert"},
}
# A conftest.py can drop a test from the run with nothing in the output to
# notice (N46): `collect_ignore`/`collect_ignore_glob` drop a file from
# collection outright, and a collection hook can deselect items the same
# way pytest_collection_modifyitems already does for `live_provider`. That
# one use is legitimate and pinned below; anything else is refused.
COLLECTION_ASSIGNMENTS = frozenset({"collect_ignore", "collect_ignore_glob"})
COLLECTION_HOOKS = frozenset(
    {
        "pytest_collection_modifyitems", "pytest_ignore_collect",
        "pytest_collect_file", "pytest_pycollect_makemodule",
        "pytest_collectstart",
    }
)  # fmt: skip
PYTEST_COLLECTION_MODIFYITEMS = (
    "def pytest_collection_modifyitems(config: pytest.Config, "
    "items: list[pytest.Item]) -> None:\n"
    "    live = [item for item in items if item.get_closest_marker"
    "('live_provider')]\n"
    "    if not config.getoption('--live-provider'):\n"
    "        items[:] = [item for item in items if item not in live]\n"
    "        config.hook.pytest_deselected(items=live)\n"
    "        return\n"
    "    missing = [name for name in _LIVE_CONFIGURATION if not "
    "os.environ.get(name)]\n"
    "    if live and missing:\n"
    "        raise pytest.UsageError('live provider tests require: ' + "
    "', '.join(missing))"
)
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
    # complexipy's own ignore comment (FP-11): its binary's grammar, from
    # its compiled matcher, is `#\s*complexipy\s*:\s*ignore`; the sibling
    # spelling, a noqa comment scoped to the word "complexipy" as though it
    # were a rule code, is already a `noqa` match above (the pattern this
    # file matches none of, per the note above SUPPRESSIONS).
    "complexipy_ignore": re.compile(r"#\s*complexipy\s*:\s*ignore\b", re.IGNORECASE),
}
# A noqa comment scoped to one or more rule codes has each code budgeted
# individually (FP-11, optional): the aggregate `noqa` count stays put
# while one code is swapped for another underneath it, so each is also its
# own `noqa:<CODE>` key in `suppression_counts` below.
NOQA_CODE = re.compile(r"#\s*noqa\s*:\s*([A-Za-z0-9, ]+)")
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
        + _complexipy_table_problems(tool)
    )


def _complexipy_table_problems(tool: dict[str, object]) -> list[str]:
    """`[tool.complexipy]` in pyproject.toml, read by the complexipy binary
    itself and never validated here (FP-10): none is committed today, and a
    `max-complexity-allowed` or `exclude` set there would override the
    gate's own CLI flag with nothing in this file the wiser."""
    if "complexipy" in tool:
        return [
            "complexipy: [tool.complexipy] is set; it is read directly and unchecked"
        ]
    return []


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


def _pre_commit_hooks(config: str) -> dict[str, dict[str, str]]:
    """Every hook's own body, by id: whichever of `HOOK_KEYS` it sets.

    A line-oriented reading, not a YAML parser (stdlib first): a hook starts
    at `- id: <name>`, and its own keys are every following line indented
    past that dash, up to the next `- id:` or a line indented no further.
    """
    hooks: dict[str, dict[str, str]] = {}
    current: dict[str, str] | None = None
    indent = -1
    for line in config.splitlines():
        started = re.match(r"^(\s*)-\s*id:\s*(\S+)\s*$", line)
        if started is not None:
            indent = len(started.group(1))
            current = hooks.setdefault(started.group(2), {})
            continue
        if not line.strip():
            continue
        this_indent = len(line) - len(line.lstrip(" "))
        if current is None or this_indent <= indent:
            current = None
            continue
        body = re.match(r"^\s*(\w[\w-]*):\s*(.*?)\s*$", line)
        if body is not None and body.group(1) in HOOK_KEYS:
            current[body.group(1)] = body.group(2).strip("'\"")
    return hooks


def _hook_problems(root: Path) -> list[str]:
    config = (root / ".pre-commit-config.yaml").read_text(encoding="utf-8")
    hooks = _pre_commit_hooks(config)
    missing = sorted(PRE_COMMIT_HOOKS - set(hooks))
    problems = [f"pre-commit: hooks missing {missing}"] if missing else []
    for name in sorted(PRE_COMMIT_HOOKS & set(hooks)):
        expected = PRE_COMMIT_HOOK_BODY.get(name, {})
        actual = hooks[name]
        problems += [
            f"pre-commit: {name}.{key} is {actual.get(key)!r}, not {value!r}"
            for key, value in expected.items()
            if actual.get(key) != value
        ]
        problems += [
            f"pre-commit: {name}.{key} is set; it can change what the hook runs on"
            for key in HOOK_KEYS
            if key not in expected and key in actual
        ]
    return problems


def _collection_hook_problems(root: Path) -> list[str]:
    """Refuse a `conftest.py` that can drop a test with nothing to notice.

    `tests/conftest.py`'s own `pytest_collection_modifyitems` is legitimate
    -- it is what makes `-m "not live_provider"` a floor rather than an
    opt-out -- and is pinned to the body it is committed with; any other
    `collect_ignore`, `collect_ignore_glob` or collection hook, there or in
    a conftest.py anywhere else under `tests/`, is new and is refused.
    """
    problems: list[str] = []
    for name in tracked_files(root, "tests/conftest.py", ":(glob)tests/**/conftest.py"):
        path = root / name
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=name)
        except (OSError, SyntaxError):
            problems.append(f"conftest: {name} could not be parsed")
            continue
        for node in tree.body:
            problems += _collection_node_problems(name, node)
    return problems


def _collection_node_problems(name: str, node: ast.stmt) -> list[str]:
    if isinstance(node, ast.Assign | ast.AnnAssign):
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        return [
            f"conftest: {name} sets {target.id}; it can drop a file from "
            "collection with nothing reported"
            for target in targets
            if isinstance(target, ast.Name) and target.id in COLLECTION_ASSIGNMENTS
        ]
    if isinstance(node, ast.FunctionDef) and node.name in COLLECTION_HOOKS:
        if name == "tests/conftest.py" and node.name == "pytest_collection_modifyitems":
            if ast.unparse(node) != PYTEST_COLLECTION_MODIFYITEMS:
                return [
                    "conftest: tests/conftest.py's pytest_collection_modifyitems "
                    "no longer matches what is committed"
                ]
            return []
        return [
            f"conftest: {name} defines {node.name}; it can change what pytest "
            "collects or runs"
        ]
    return []


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
    'uv run python scripts/check_gate_config.py --against "$base"',
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
        + _collection_hook_problems(root)
        + _parity_problems(root)
        + _bundle_problems(root)
        + _ci_problems(root)
        + _gitleaks_problems(root)
    )


SNAPSHOT = "complexipy-snapshot.json"


def _noqa_code_counts(text: str) -> dict[str, int]:
    """Each `noqa:<CODE>` key a noqa comment scoped to one or more rule
    codes names (FP-11, optional): the aggregate `noqa` count stays put
    while one code is swapped for another underneath it, so each code is
    budgeted too."""
    counts: dict[str, int] = {}
    for match in NOQA_CODE.finditer(text):
        for code in match.group(1).split(","):
            code = code.strip().upper()
            if code:
                counts[f"noqa:{code}"] = counts.get(f"noqa:{code}", 0) + 1
    return counts


def _measure_suppressions(texts: Iterable[str]) -> dict[str, int]:
    """`SUPPRESSIONS` and per-code `noqa` counts over a set of file texts,
    however they were read -- from disk for the working tree, or from git
    for an earlier commit (FP-11)."""
    counts = dict.fromkeys(SUPPRESSIONS, 0)
    for text in texts:
        for name, pattern in SUPPRESSIONS.items():
            counts[name] += len(pattern.findall(text))
        for code, found in _noqa_code_counts(text).items():
            counts[code] = counts.get(code, 0) + found
    return counts


def suppression_counts(root: Path = REPO) -> dict[str, int]:
    """How many of each suppression the tracked Python files carry, how many
    functions the cognitive-complexity baseline (G14) still carries, and the
    complexity recorded for each of them by name (AR-07, N46): ratcheting
    only their sum let one function's complexity rise as long as another's
    fell to match, so the pair's total held still and the rise passed
    unseen. Each baselined function is its own budget below."""
    counts = _measure_suppressions(
        path.read_text(encoding="utf-8") for path in tracked_python(root)
    )
    functions = _baselined_functions(root / SNAPSHOT)
    counts["complexity_baselined"] = len(functions)
    counts.update(functions)
    return counts


def suppression_counts_at(rev: str, root: Path = REPO) -> dict[str, int]:
    """`suppression_counts`, but measuring `rev`'s own tracked files rather
    than the working tree (FP-11): this module's *current* `SUPPRESSIONS`
    patterns and per-function complexity keys, applied to an earlier
    commit's code. Comparing two commits' own committed JSON numbers let a
    PR that only weakened a pattern -- so it now matches less -- make its
    own, freshly weaker count look like a fall against a base measured
    under the old, stronger one; both sides are measured the same way now.
    """
    counts = _measure_suppressions(tracked_python_at(root, rev).values())
    functions = _parse_baselined_functions(blob_at(root, rev, SNAPSHOT))
    counts["complexity_baselined"] = len(functions)
    counts.update(functions)
    return counts


def _parse_baselined_functions(snapshot_text: str | None) -> dict[str, int]:
    """The complexity recorded for each function a complexipy-snapshot.json
    text baselines, by a `complexity:<path>::<name>` key unique to that
    function; `{}` if there is no text or it does not parse."""
    if snapshot_text is None:
        return {}
    try:
        recorded = json.loads(snapshot_text)
    except ValueError:
        return {}
    return {
        f"complexity:{entry.get('path')}::{function.get('name')}": int(
            function.get("complexity", 0)
        )
        for entry in recorded
        for function in entry.get("functions", [])
    }


def _baselined_functions(snapshot: Path) -> dict[str, int]:
    """The complexity recorded for each function the snapshot baselines, by
    a `complexity:<path>::<name>` key unique to that function."""
    try:
        text = snapshot.read_text(encoding="utf-8")
    except OSError:
        return {}
    return _parse_baselined_functions(text)


def suppression_problems(root: Path = REPO, baseline: Path = BASELINE) -> list[str]:
    """Each suppression kind whose count is not the baseline's. A ratchet
    (DF-11): a count above it is a new suppression, and a count below it is
    room a later change could spend unseen, so the change that removes a
    suppression lowers the baseline with it. The two sides can also name
    different kinds outright -- a baselined function fixed below 15 leaves
    the complexipy snapshot, and with it this run's counts, while the
    committed baseline still carries its key -- and that too is a fall to 0,
    not silence."""
    try:
        allowed = json.loads(baseline.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ["baseline: tests/gate_baseline.json unreadable"]
    counts = suppression_counts(root)
    problems: list[str] = []
    for name in sorted(set(counts) | set(allowed)):
        count = counts.get(name, 0)
        budget = int(allowed.get(name, 0))
        if count > budget:
            problems.append(f"suppressions: {name} rose to {count} (baseline {budget})")
        elif count < budget:
            problems.append(
                f"suppressions: {name} fell to {count} (baseline {budget}): "
                "lower tests/gate_baseline.json to match"
            )
    return problems


def baseline_problems(against: str, root: Path = REPO) -> list[str]:
    """Each budget that rose against `against`, a base branch's git revision
    (F58, FP-11): both sides are measured fresh, this commit's own
    `SUPPRESSIONS` patterns and complexity keys applied to each tree in
    turn, rather than trusting two commits' own committed JSON numbers --
    which let a PR that only weakened a pattern compare its own count
    against a base measured under the old, stronger one."""
    try:
        base = suppression_counts_at(against, root)
    except RuntimeError as refusal:
        return [f"baseline: {refusal}"]
    now = suppression_counts(root)
    return [
        f"baseline: {name} rose to {count} (base branch {base.get(name, 0)})"
        for name, count in now.items()
        if count > int(base.get(name, 0))
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
    parser.add_argument("--against", help="the base branch's git revision")
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

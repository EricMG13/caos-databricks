#!/usr/bin/env python3
"""Refuse a gate configuration that has been loosened (spec G16, D15).

Every threshold the gate table states is read back from the files that hold
it, as the tool will apply it: a key that could narrow what a tool reads or
silence what it reports is refused, not only a threshold that moved (MAX-13).
The number of suppressions in tracked Python must equal the committed
baseline: a new one fails, and so does one removed while the baseline keeps
its room (DF-11). `--baseline` rewrites the baseline from the current tree,
and `--against <revision>` refuses a count that rose above that revision's
own tree, both measured fresh under this commit's rules (FP-11) and under
that revision's own checker (W5).
"""

from __future__ import annotations

import argparse
import ast
import importlib.util
import json
import re
import shlex
import sys
import tempfile
import tomllib
from collections.abc import Callable, Iterable, Iterator
from hashlib import sha256
from pathlib import Path
from typing import cast

import yaml

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
# The one gitleaks both scans run (W3): the hook's rev and the CI image's
# tag are this one version, and the image is also pinned by digest.
GITLEAKS_VERSION = "v8.24.3"
GITLEAKS_IMAGE = (
    f"ghcr.io/gitleaks/gitleaks:{GITLEAKS_VERSION}"
    "@sha256:e1b35e12a8c6fa8901f060459cfb6b2fc4c484d3afbe3b029733a3bbfab07055"
)
# The config's own top level (review 4, W2): a top-level `exclude`, `files`
# or `default_stages` switches every hook off at once while each hook's own
# body stays exactly as pinned below, so `repos` is the one key it may set.
PRE_COMMIT_KEYS = frozenset({"repos"})
REPO_KEYS = frozenset({"repo", "rev", "hooks"})
# Each repo by its URL, at its pinned rev, running exactly these hook ids in
# file order: a repo pointed at a fork, a rev moved, or a hook id moved into
# another repo (a `local` hook named `ruff`) runs something else under the
# same name. `local` has no rev.
PRE_COMMIT_REPOS: dict[str, tuple[str | None, tuple[str, ...]]] = {
    "https://github.com/astral-sh/ruff-pre-commit": (
        "v0.14.0",
        ("ruff", "ruff-format"),
    ),
    "https://github.com/gitleaks/gitleaks": (
        GITLEAKS_VERSION,
        ("gitleaks", "gitleaks"),
    ),
    "https://github.com/pre-commit/pre-commit-hooks": (
        "v5.0.0",
        (
            "check-added-large-files",
            "check-merge-conflict",
            "end-of-file-fixer",
            "trailing-whitespace",
        ),
    ),
    "local": (None, ("vocabulary", "tested", "io-budget")),
}
PRE_COMMIT_HOOKS = frozenset(
    hook for _, hooks in PRE_COMMIT_REPOS.values() for hook in hooks
)
# The keys a hook body may carry without changing what it runs: its `id`,
# and the `name` it is displayed under.
HOOK_LABELS = frozenset({"id", "name"})
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


def _local(entry: str) -> dict[str, object]:
    """A local hook's whole body: the command, run once by the system."""
    return {"entry": entry, "language": "system", "pass_filenames": False}


# Each hook id's whole body but its labels (or bodies, in file order, for an
# id repeated with a different override -- gitleaks below, CF-064), exactly
# (AR-07, N46, review 4 W2): `entry` swapped for a no-op, `stages` moved off
# the default run, `files`/`exclude`/`args` narrowed, and `types`,
# `types_or`, `exclude_types` or `language` set all disable a hook while its
# `id` keeps naming it present. A key not given here is refused.
PRE_COMMIT_HOOK_BODY: dict[str, list[dict[str, object]]] = {
    "ruff": [{"args": ["--fix"], "exclude": "^vendor/"}],
    "ruff-format": [{"exclude": "^vendor/"}],
    "check-added-large-files": [{"exclude": _LARGE_FILES_EXCLUDE}],
    "check-merge-conflict": [{"exclude": "^vendor/"}],
    "end-of-file-fixer": [{"exclude": _VENDOR_QUAL_EXCLUDE}],
    "trailing-whitespace": [{"exclude": _VENDOR_QUAL_EXCLUDE}],
    "vocabulary": [_local("uv run python scripts/check_vocabulary.py")],
    "tested": [_local("uv run python scripts/check_tested.py")],
    "io-budget": [_local("uv run python scripts/io_budget.py --assert")],
    "gitleaks": [
        {},
        {"entry": "gitleaks dir --no-banner --redact -v ."},
    ],
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
    # A test CI's marker expression (`-m "not live_provider"`) deselects:
    # it never runs there, so each one is budgeted like a skip (W4).
    "live_provider": re.compile(r"\bmark\.live_provider\b"),
}
# The pytest names each kind above covers, as the module path they resolve
# to (W4): `from pytest import skip` and a bare call, `import pytest as pt`,
# or `mark` imported under another name spell one without the prefix the
# patterns read, so each file's imports are resolved too. Written as tuples
# so this file matches none of the patterns.
PYTEST_MODULES = {("pytest",): ("pytest",), ("_pytest", "outcomes"): ("pytest",)}
PYTEST_NAMES: dict[tuple[str, ...], str] = {
    ("pytest", "skip"): "skip",
    ("pytest", "importorskip"): "skip",
    ("pytest", "mark", "skip"): "skip",
    ("pytest", "mark", "skipif"): "skip",
    ("pytest", "xfail"): "xfail",
    ("pytest", "mark", "xfail"): "xfail",
    ("pytest", "mark", "live_provider"): "live_provider",
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
        "CAOS_BLOB_ROOT", "CAOS_GROUP_ADMIN", "CAOS_GROUP_ANALYST",
    }
)  # fmt: skip
# Which Lakebase the app binds is each target's to say, once (R24-14): the
# variable the process mints its credential for, with the `database`
# resource in the matching form. A `-provisioned` target binds an existing
# Provisioned instance; every other target Lakebase Autoscaling, the default.
LAKEBASE_ENDPOINT = "CAOS_LAKEBASE_ENDPOINT"
LAKEBASE_INSTANCE = "CAOS_LAKEBASE_INSTANCE"
LAKEBASE_BINDINGS = {LAKEBASE_ENDPOINT: "postgres", LAKEBASE_INSTANCE: "database"}
PROVISIONED_SUFFIX = "-provisioned"


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


def _yaml_mapping(text: str | None) -> dict[object, object] | None:
    """`text` read as YAML, the way pre-commit and Actions read it, when it
    is a mapping; None when it is missing, does not parse, or is not one."""
    if text is None:
        return None
    try:
        loaded = yaml.safe_load(text)
    except yaml.YAMLError:
        return None
    return loaded if isinstance(loaded, dict) else None


def _map(value: object) -> dict[object, object]:
    """`value` when it is a YAML mapping, else an empty one."""
    return value if isinstance(value, dict) else {}


def _seq(value: object) -> list[object]:
    """`value` when it is a YAML sequence, else an empty one."""
    return value if isinstance(value, list) else []


def _repo_problems(url: str, entry: dict[object, object]) -> list[str]:
    """One `repos` entry against `PRE_COMMIT_REPOS`: its URL, its rev and the
    hook ids it runs, in order."""
    pinned = PRE_COMMIT_REPOS.get(url)
    if pinned is None:
        return [f"pre-commit: repo {url} is not one this gate pins"]
    rev, hooks = pinned
    problems = [
        f"pre-commit: repo {url} sets {key!r}; a repo may set only {sorted(REPO_KEYS)}"
        for key in entry
        if key not in REPO_KEYS
    ]
    if entry.get("rev") != rev:
        problems.append(
            f"pre-commit: repo {url} is at {entry.get('rev')!r}, not {rev!r}"
        )
    ids = tuple(str(_map(hook).get("id")) for hook in _seq(entry.get("hooks")))
    if ids != hooks:
        problems.append(f"pre-commit: repo {url} runs {list(ids)}, not {list(hooks)}")
    return problems


def _pre_commit_hooks(
    config: dict[object, object],
) -> list[tuple[str, dict[object, object]]]:
    """Every hook, in file order, as (id, body): its whole body but its
    labels. A repo-hosted id can appear more than once with a different
    override each time (gitleaks's staged scan and its dir scan, CF-064),
    so this is a list, not a dict keyed by id."""
    return [
        (
            str(_map(hook).get("id")),
            {k: v for k, v in _map(hook).items() if k not in HOOK_LABELS},
        )
        for repo in _seq(config.get("repos"))
        for hook in _seq(_map(repo).get("hooks"))
    ]


def _hook_occurrence_problems(
    name: str, index: int, expected: dict[str, object], actual: dict[object, object]
) -> list[str]:
    """One occurrence of one hook id against the body expected of it."""
    return [
        f"pre-commit: {name}[{index}].{key} is {actual.get(key)!r}, not {value!r}"
        for key, value in expected.items()
        if actual.get(key) != value
    ] + [
        f"pre-commit: {name}[{index}].{key} is set; it can change what the hook runs on"
        for key in actual
        if key not in expected
    ]


def _named_hook_problems(
    name: str, actual_list: list[dict[object, object]]
) -> list[str]:
    """One hook id's every occurrence against `PRE_COMMIT_HOOK_BODY`."""
    expected_list = PRE_COMMIT_HOOK_BODY.get(name, [{}])
    if len(actual_list) != len(expected_list):
        return [
            f"pre-commit: {name} appears {len(actual_list)} time(s), "
            f"expected {len(expected_list)}"
        ]
    return [
        problem
        for index, (expected, actual) in enumerate(
            zip(expected_list, actual_list, strict=True)
        )
        for problem in _hook_occurrence_problems(name, index, expected, actual)
    ]


def _hook_problems(root: Path) -> list[str]:
    """The pre-commit configuration, read as pre-commit reads it (W2): only
    `repos` at the top, each pinned repo once at its rev with its own hook
    ids, and each hook's whole body as pinned."""
    config = _yaml_mapping(_read(root, ".pre-commit-config.yaml"))
    if config is None:
        return ["pre-commit: .pre-commit-config.yaml is missing or not a mapping"]
    problems = [
        f"pre-commit: the config sets {key!r}; it may set only "
        f"{sorted(PRE_COMMIT_KEYS)}"
        for key in config
        if key not in PRE_COMMIT_KEYS
    ]
    urls = [str(_map(repo).get("repo")) for repo in _seq(config.get("repos"))]
    for repo in _seq(config.get("repos")):
        problems += _repo_problems(str(_map(repo).get("repo")), _map(repo))
    problems += [
        f"pre-commit: repo {url} appears {urls.count(url)} times, not once"
        for url in PRE_COMMIT_REPOS
        if urls.count(url) != 1
    ]
    occurrences = _pre_commit_hooks(config)
    present = {hook_id for hook_id, _ in occurrences}
    missing = sorted(PRE_COMMIT_HOOKS - present)
    if missing:
        problems.append(f"pre-commit: hooks missing {missing}")
    by_id: dict[str, list[dict[object, object]]] = {}
    for hook_id, body in occurrences:
        by_id.setdefault(hook_id, []).append(body)
    for name in sorted(present):
        problems += _named_hook_problems(name, by_id[name])
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


def target_blocks(bundle: str) -> dict[str, str]:
    """Each target's own text under `targets:`, by name."""
    targets = bundle.partition("\ntargets:\n")[2]
    parts = re.split(r"^  ([\w-]+):[ \t]*\n", targets, flags=re.M)
    return dict(zip(parts[1::2], parts[2::2], strict=True))


def _lakebase_bound(text: str) -> list[tuple[str, bool]]:
    """Each Lakebase variable `text` sets, with whether its resource form is
    there too; a form with no variable counts as the variable unset."""
    found = []
    for name, form in LAKEBASE_BINDINGS.items():
        named = re.search(rf"^\s+-\s*name:\s*{name}\s*$", text, re.M) is not None
        formed = re.search(rf"^\s+{form}:\s*$", text, re.M) is not None
        if named or formed:
            found.append((name, named and formed))
    return found


def _binding_problems(bundle: str) -> list[str]:
    """R24-14: no Lakebase outside the targets, and each target binds exactly
    its own kind, variable and resource form together."""
    code = "\n".join(line.partition("#")[0] for line in bundle.splitlines())
    shared = code.partition("\ntargets:\n")[0]
    problems = [
        f"bundle: {name} is bound outside the targets"
        for name, _ in _lakebase_bound(shared)
    ]
    for target, body in target_blocks(code).items():
        provisioned = target.endswith(PROVISIONED_SUFFIX)
        wanted = LAKEBASE_INSTANCE if provisioned else LAKEBASE_ENDPOINT
        if _lakebase_bound(body) != [(wanted, True)]:
            form = LAKEBASE_BINDINGS[wanted]
            problems.append(
                f"bundle: target {target} must bind {wanted} and a {form} "
                "resource, and nothing of the other kind"
            )
    return problems


# What a bundle's `workspace` mapping may set, at the top or in a target
# (W7): paths inside whichever workspace it is deployed to. `host`,
# `profile`, `auth_type`, a client id, an account or any cloud's credential
# names a workspace, or a way into one, of the bundle's own, which CLI
# 1.17.0 prefers to the profile's and to a stand-in's DATABRICKS_HOST: the
# one command supplies the workspace through the profile, and a stand-in
# run through the loopback stub, so the bundle never does. An `include`
# brings in files these checks do not read, so it is refused as well.
BUNDLE_WORKSPACE_KEYS = frozenset(
    {"root_path", "file_path", "artifact_path", "state_path", "resource_path"}
)


def bundle_auth_problems(bundle: str | None) -> list[str]:
    """Each way a bundle's text names a workspace or credential of its own,
    read as the CLI reads it (W7); the loopback stand-in refuses to run a
    bundle this names anything for, and the committed one must name none."""
    document = _yaml_mapping(bundle)
    if document is None:
        return ["bundle: databricks.yml is missing or not a mapping"]
    problems = (
        ["bundle: the bundle includes other files; one file states it"]
        if "include" in document
        else []
    )
    targets = _map(document.get("targets"))
    scopes = [("the bundle", document)] + [
        (f"target {name}", _map(body)) for name, body in targets.items()
    ]
    return problems + [
        f"bundle: {scope} sets workspace.{key}; the workspace is the profile's"
        for scope, body in scopes
        for key in _map(body.get("workspace"))
        if key not in BUNDLE_WORKSPACE_KEYS
    ]


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
    return problems + _binding_problems(bundle) + bundle_auth_problems(bundle)


STAND_IN = "uv run python tests/workspace_stub.py --"
# The stand-in's own Lakebase of each kind (`tests/workspace_stub.py`).
STAND_IN_VARS = "--var uc_catalog=main --var uc_schema=caos --var lakebase_project=caos"
STAND_IN_PROVISIONED_VARS = (
    "--var uc_catalog=main --var uc_schema=caos --var lakebase_instance=caos-lb"
)
STAND_IN_PRICE = (
    "BUNDLE_VAR_model_price=databricks-claude-opus-5,0.000007,0.000030,2026-09-23"
)
# Each target with the stand-in Lakebase of its own kind (R24-14).
STAND_IN_TARGETS = (
    ("dev", STAND_IN_VARS),
    ("prod", STAND_IN_VARS),
    ("dev-provisioned", STAND_IN_PROVISIONED_VARS),
    ("prod-provisioned", STAND_IN_PROVISIONED_VARS),
)


def stand_in_target(target: str, variables: str) -> tuple[str, str]:
    """One target validated, deployed and run under one stub (A37), then
    held to what its deploy synced (DF-4): the two commands CI runs."""
    run = " && ".join(
        f"databricks bundle {verb} -t {target} {variables}"
        for verb in ("validate", "deploy", "run caos")
    )
    shipped = f".databricks/bundle/{target}/deployment.json"
    return (
        f'{STAND_IN} sh -c "{run}"',
        f"uv run python scripts/check_gate_config.py --shipped {shipped}",
    )


def _resolved_check(target: str, variables: str) -> tuple[str, str]:
    """E2 in CI for one target (DF-4, DF-5, R24-14): the stand-in's
    `validate -o json`, and the one command's own E2 over what it wrote."""
    kind = variables.rpartition(" --var ")[2].partition("=")
    flag = (
        "--lakebase-instance"
        if kind[0] == "lakebase_instance"
        else "--lakebase-project"
    )
    return (
        f"databricks bundle validate -t {target} -o json {variables} "
        f"> $RUNNER_TEMP/{target}.json",
        "uv run python scripts/enterprise_deploy.py --stage record --evidence "
        f'"$RUNNER_TEMP/resolved" --step E2 --target {target} --price '
        f"{STAND_IN_PRICE.partition('=')[2]} {flag} {kind[2]} "
        f'--bundle "$RUNNER_TEMP/{target}.json"',
    )


# Each gate CLAUDE.md lists, as CI runs it (MAX-13): a step removed, a
# threshold raised or a command made to pass whatever it finds is a gate
# that no longer runs. `|| true` stands on one command only, bandit's JSON
# report, whose verdict is the floor check after it -- the one bandit
# invocation now, since a bare second run once existed only to let its own
# exit code stand for the same scan the floor already verdicts (N29).
PYTEST_GATE = (
    'uv run pytest -n auto -m "not live_provider" --max-worker-restart=0 '
    "-o faulthandler_timeout=600 -ra --durations=25"
)
RACES_GATE = "uv run pytest --no-cov tests/test_postgres_races.py"
GITLEAKS_GATE = (
    'docker run --rm -u "$(id -u):$(id -g)" -e GIT_CONFIG_COUNT=1 '
    "-e GIT_CONFIG_KEY_0=safe.directory -e GIT_CONFIG_VALUE_0=/repo "
    f'-v "$PWD:/repo" -w /repo {GITLEAKS_IMAGE} git --no-banner .'
)
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
    PYTEST_GATE,
    "uv run python scripts/scan_floors.py coverage.xml --cobertura",
    RACES_GATE,
    "uv run python scripts/scan_floors.py bandit.json --no-parse-errors "
    "--cover caos scripts icm --unscanned tests",
    "uv run pip-audit --strict",
    # The whole history, digest-pinned (W3): its text alone in a comment
    # once satisfied a check that read the file's raw text.
    GITLEAKS_GATE,
    f"{STAND_IN_PRICE} {STAND_IN} databricks bundle validate -t dev {STAND_IN_VARS}",
    f'{STAND_IN} sh -c "databricks bundle deploy -t dev {STAND_IN_VARS} '
    f'&& databricks bundle run caos -t dev {STAND_IN_VARS}"',
    "uv run python scripts/check_gate_config.py --shipped "
    ".databricks/bundle/dev/deployment.json",
    *stand_in_target("prod", STAND_IN_VARS),
    # The Provisioned pair (R24-14), each the way prod is.
    *stand_in_target("dev-provisioned", STAND_IN_PROVISIONED_VARS),
    *stand_in_target("prod-provisioned", STAND_IN_PROVISIONED_VARS),
    # E2 for every target: what the CLI resolved is what was given.
    f'{STAND_IN_PRICE} {STAND_IN} sh -c "'
    + " && ".join(_resolved_check(*target)[0] for target in STAND_IN_TARGETS)
    + '"',
    *(_resolved_check(*target)[1] for target in STAND_IN_TARGETS),
    "uv run python scripts/document_register.py",
    "uv run python -B vendor/deploy-v/verify_package.py",
    "npm --prefix frontend run lint",
    "npm --prefix frontend run typecheck",
    "npm --prefix frontend run test",
    "npm --prefix frontend run build",
    "npm --prefix frontend run build:demo",
    "npx --prefix frontend --no-install jscpd --threshold 3 --min-lines 10 --ignore "
    '"**/node_modules/**,**/dist/**,**/dist-demo/**" caos scripts icm frontend/src',
    "npm --prefix frontend run a11y",
    "npm --prefix frontend run test:workbench",
)
EXCUSED = "uv run bandit -r caos scripts icm -f json -o bandit.json || true"
# A failure turned into a success: `|| true`, `|| :`, `|| exit 0`, `set +e`.
SWALLOWED = re.compile(r"\|\|\s*(?:true\b|:(?:\s|;|$)|exit\s+0\b)|\bset\s+\+e\b")
# The steps that are more than one line, each exactly (W2): an `exit 0` or a
# `trap 'exit 0' EXIT` ahead of a gate, or the gate inside a heredoc, is a
# script no pin names. Comment lines are not part of a script.
BASELINE_SCRIPT = (
    "base=HEAD^",
    'if [ -n "$BASE_REF" ]; then base="origin/$BASE_REF"; elif git cat-file -e '
    '"$BEFORE^{commit}" 2>/dev/null; then base="$BEFORE"; fi',
    'uv run python scripts/check_gate_config.py --against "$base"',
)
FRONTEND_SECURITY = (
    "uv sync --locked --all-groups",
    "uv run pytest -rs --no-cov "
    '"tests/test_frontend_modes.py::test_the_dev_proxy_strips_client_identity_and_'
    'injects_the_local_actor" '
    '"tests/test_frontend_modes.py::test_production_build_contains_no_fixture_or_'
    'demo_route"',
)
SECTION_ROUTES = (
    "for s in directory upload analysis book run model report committee admin; do",
    'test -f "frontend/dist/$s/index.html" || { echo "missing '
    'frontend/dist/$s/index.html"; exit 1; }',
    "done",
)
PR_SIZE = 'python3 scripts/check_pr_size.py "origin/$BASE_REF"'
_POSTGRES = {
    "CAOS_TEST_POSTGRES_URL": "postgresql://postgres:caos@localhost:5432/caos",
    # A store suite that skipped is not a store suite that passed.
    "CAOS_REQUIRE_POSTGRES": "1",
}
# Every script a CI step may run, as its lines, with the environment its
# step carries exactly (W2): a script not listed here can rewrite PATH, the
# environment or the virtualenv before a gate runs, so it is refused, and
# every one listed must run -- the gates above among them. An env key is a
# way in too: `SKIP` skips pre-commit hooks, `PYTEST_ADDOPTS` narrows the
# suite, and the races suite without `CAOS_REQUIRE_POSTGRES` skips whole.
CI_STEPS: dict[tuple[str, ...], dict[str, str]] = {
    **{(gate,): {} for gate in CI_GATES},
    (PYTEST_GATE,): _POSTGRES,
    (RACES_GATE,): _POSTGRES,
    BASELINE_SCRIPT: {
        "BASE_REF": "${{ github.base_ref }}",
        "BEFORE": "${{ github.event.before }}",
    },
    FRONTEND_SECURITY: {"CAOS_REQUIRE_NODE": "1"},
    SECTION_ROUTES: {},
    # FP-40: the base ref crosses an env: variable, never the script.
    (PR_SIZE,): {"BASE_REF": "${{ github.base_ref }}"},
    ("uv sync --locked --all-groups",): {},
    ("npm --prefix frontend ci --ignore-scripts",): {},
    ("frontend/node_modules/.bin/playwright install --with-deps",): {},
    (EXCUSED,): {},
}
# The one condition a job may run under, by the script it runs: the PR size
# check on pull requests. A job holding any other script may set none.
CI_CONDITIONS: dict[tuple[str, ...], str] = {
    (PR_SIZE,): "github.event_name == 'pull_request'"
}
# Each action step exactly, by its SHA and its inputs: a tag, a fork's
# commit or an input such as `ref:` or a `version:` runs something else.
_CHECKOUT = "actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1"
_SETUP_UV = "astral-sh/setup-uv@bec219d24cd3e171d82865faccec33120bb574f4"
_SETUP_NODE = "actions/setup-node@820762786026740c76f36085b0efc47a31fe5020"
CI_ACTIONS: tuple[dict[object, object], ...] = (
    {"uses": _CHECKOUT},
    {"uses": _CHECKOUT, "with": {"fetch-depth": 0}},
    {"uses": _SETUP_UV, "with": {"version": "0.12.5", "enable-cache": True}},
    {
        "uses": "databricks/setup-cli@d76f84cea9893ce68311a1f33fb0c95af6c963b7",
        "with": {"version": "1.17.0"},
    },
    {
        "uses": _SETUP_NODE,
        "with": {
            "node-version": "24",
            "cache": "npm",
            "cache-dependency-path": "frontend/package-lock.json",
        },
    },
    {
        "uses": "actions/cache@55cc8345863c7cc4c66a329aec7e433d2d1c52a9",
        "with": {
            "path": "~/.cache/ms-playwright",
            "key": "playwright-${{ hashFiles('frontend/package-lock.json') }}",
        },
    },
)
# The workflow's own top level (W2): what triggers it, what its token may
# do and the one environment every step inherits are pinned; `defaults`
# (`defaults.run.shell: "true {0}"` reaches every gate at once) and any
# other key are refused. YAML 1.1 reads the bare key `on` as true.
CI_TOP_PINNED: dict[str, object] = {
    "on": {
        "push": {"branches": ["main", "rebuild/databricks"]},
        "pull_request": {
            "types": ["opened", "synchronize", "reopened", "ready_for_review", "edited"]
        },
    },
    "permissions": {"contents": "read"},
    "env": {"UV_VERSION": "0.12.5"},
}
CI_TOP_FREE = frozenset({"name", "concurrency", "jobs"})
# A job's own keys: `defaults`, `env`, `continue-on-error`, `container`,
# `strategy` and `needs` each change how, where or whether its gates run.
JOB_KEYS = frozenset({"runs-on", "timeout-minutes", "services", "steps", "if"})
RUNS_ON = "ubuntu-latest"
# A step's own keys: `if`, `continue-on-error`, `working-directory` and
# `shell` each change whether, where or how its script runs.
STEP_KEYS = frozenset({"name", "uses", "with", "run", "env"})


def script_lines(run: str) -> tuple[str, ...]:
    """A `run:` value as the shell runs it, one command a line: backslash
    continuations joined, whitespace collapsed, blank and comment lines
    dropped. PyYAML has already folded a `>` block into one line."""
    joined = run.replace("\\\n", " ")
    lines = (" ".join(line.split()) for line in joined.split("\n"))
    return tuple(line for line in lines if line and not line.startswith("#"))


def _ci_file(ci_text: str | None) -> dict[object, object] | None:
    """The workflow as Actions reads it, with `on` under its own name."""
    ci_file = _yaml_mapping(ci_text)
    if ci_file is None:
        return None
    return {("on" if key is True else key): value for key, value in ci_file.items()}


def _jobs(ci_file: dict[object, object]) -> Iterator[tuple[str, dict[object, object]]]:
    for name, job in _map(ci_file.get("jobs")).items():
        yield str(name), _map(job)


def ci_commands(ci_text: str) -> list[str]:
    """Every command a CI file's `run:` steps execute, one a line, as
    `script_lines` reads each step's script."""
    ci_file = _ci_file(ci_text) or {}
    return [
        line
        for _, job in _jobs(ci_file)
        for step in _seq(job.get("steps"))
        if isinstance(_map(step).get("run"), str)
        for line in script_lines(str(_map(step).get("run")))
    ]


def _shown(script: tuple[str, ...]) -> str:
    return "\n".join(script)


def _ci_top_problems(ci_file: dict[object, object]) -> list[str]:
    problems = [
        f"ci: the workflow sets {key!r}; only {sorted(CI_TOP_PINNED)} and "
        f"{sorted(CI_TOP_FREE)} are held"
        for key in ci_file
        if key not in CI_TOP_PINNED and key not in CI_TOP_FREE
    ]
    return problems + [
        f"ci: the workflow's {key} is not as pinned"
        for key, value in CI_TOP_PINNED.items()
        if ci_file.get(key) != value
    ]


def _job_problems(name: str, job: dict[object, object]) -> list[str]:
    """A job's own keys, and its `if:` against the scripts it runs (R24-11):
    a gate whose job can be switched off is a gate that need not run."""
    problems = [
        f"ci: job {name} sets {key!r}; a job may set only {sorted(JOB_KEYS)}"
        for key in job
        if key not in JOB_KEYS
    ]
    if job.get("runs-on") != RUNS_ON:
        problems.append(f"ci: job {name} runs on {job.get('runs-on')!r}, not {RUNS_ON}")
    condition = job.get("if")
    if condition is None:
        return problems
    runs = [_map(step).get("run") for step in _seq(job.get("steps"))]
    scripts = [script_lines(run) for run in runs if isinstance(run, str)]
    return problems + [
        f"ci: {_shown(script)!r} runs only when its job's if: allows it"
        for script in scripts or [()]
        if CI_CONDITIONS.get(script) != condition
    ]


def _step_problems(job: str, step: dict[object, object]) -> list[str]:
    """One step against the pins: an action exactly as `CI_ACTIONS` gives
    it, or a script `CI_STEPS` names carrying exactly its env."""
    run = step.get("run")
    script = script_lines(run) if isinstance(run, str) else ()
    problems = [
        f"ci: {_shown(script)!r} runs only when its step's if: allows it"
        if key == "if"
        else f"ci: a step in job {job} sets {key!r}; a step may set only "
        f"{sorted(STEP_KEYS)}"
        for key in step
        if key not in STEP_KEYS
    ]
    if "uses" in step or not isinstance(run, str):
        action = {key: value for key, value in step.items() if key != "name"}
        if action not in CI_ACTIONS:
            problems.append(f"ci: job {job} uses {step.get('uses')!r} as no pin gives")
        return problems
    return problems + _script_problems(job, run, _map(step.get("env")))


def _script_problems(job: str, run: str, given: dict[object, object]) -> list[str]:
    """A step's script: pinned, carrying exactly its pinned env, able to
    fail, and free of a spliced template expression."""
    script = script_lines(run)
    # FP-40, N3: a template spliced into a script is expanded before the
    # shell sees it -- script injection -- in whatever YAML spelling.
    spliced = "${{" in run
    problems = (
        [f"ci: {run!r} splices a template expression into a run: script"]
        if spliced
        else []
    )
    problems += [
        f"ci: {line!r} cannot fail"
        for line in script
        if SWALLOWED.search(line) and line != EXCUSED
    ]
    env = {str(key): str(value) for key, value in given.items()}
    if script not in CI_STEPS:
        problems.append(f"ci: job {job} runs a script no pin names: {_shown(script)!r}")
    elif env != CI_STEPS[script]:
        problems.append(
            f"ci: {_shown(script)!r} does not carry exactly its pinned env "
            f"{sorted(CI_STEPS[script])}"
        )
    return problems


def _ci_problems(root: Path) -> list[str]:
    """`ci.yml` read as Actions reads it (W2, W3, N3): the workflow's own
    keys, each job's, and each step against the pins, then every pinned
    script present."""
    ci_text = _read(root, ".github/workflows/ci.yml")
    ci_file = _ci_file(ci_text)
    if ci_file is None:
        return ["ci: .github/workflows/ci.yml is missing or not a mapping"]
    problems = _ci_top_problems(ci_file)
    present: set[tuple[str, ...]] = set()
    for name, job in _jobs(ci_file):
        problems += _job_problems(name, job)
        for step in _seq(job.get("steps")):
            problems += _step_problems(name, _map(step))
            run = _map(step).get("run")
            if isinstance(run, str):
                present.add(script_lines(run))
    return problems + [
        f"ci: no step runs {_shown(script)!r}"
        for script in CI_STEPS
        if script not in present
    ]


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


def _pytest_bindings(tree: ast.Module) -> dict[str, tuple[str, ...]]:
    """Each name a module binds to pytest or one of its names, by the path
    it resolves to: `import pytest as pt` binds `pt` to `("pytest",)`, and
    `from pytest import skip as s` binds `s` to `("pytest", "skip")`."""
    bound: dict[str, tuple[str, ...]] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            bound.update(_imported(node))
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            module = tuple(node.module.split("."))
            if module in PYTEST_MODULES:
                bound.update(
                    {
                        alias.asname or alias.name: (*module, alias.name)
                        for alias in node.names
                    }
                )
    return bound


def _imported(node: ast.Import) -> dict[str, tuple[str, ...]]:
    """What one `import` statement binds to pytest: `import pytest [as x]`,
    `import _pytest.outcomes as x`, or `_pytest` itself for the dotted form."""
    bound: dict[str, tuple[str, ...]] = {}
    for alias in node.names:
        path = tuple(alias.name.split("."))
        if alias.asname and path in PYTEST_MODULES:
            bound[alias.asname] = PYTEST_MODULES[path]
        elif path[0] in ("pytest", "_pytest"):
            bound[path[0]] = path[:1]
    return bound


def _resolved(node: ast.expr, bound: dict[str, tuple[str, ...]]) -> tuple[str, ...]:
    """The pytest path a name or attribute chain resolves to, or `()`;
    `_pytest.outcomes.<name>` is `pytest.<name>`."""
    if isinstance(node, ast.Name):
        path = bound.get(node.id, ())
    elif isinstance(node, ast.Attribute):
        base = _resolved(node.value, bound)
        path = (*base, node.attr) if base else ()
    else:
        return ()
    for prefix, module in PYTEST_MODULES.items():
        if path[: len(prefix)] == prefix:
            return module + path[len(prefix) :]
    return path


def _pytest_counts(text: str) -> dict[str, int]:
    """Each use of a pytest name in `PYTEST_NAMES` that the text patterns
    do not already count: a bare or aliased skip, xfail or marker (W4)."""
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError):
        return {}
    bound = _pytest_bindings(tree)
    counts: dict[str, int] = {}
    for node in ast.walk(tree) if bound else []:
        if not isinstance(node, ast.Name | ast.Attribute):
            continue
        kind = PYTEST_NAMES.get(_resolved(node, bound))
        if kind is not None and not SUPPRESSIONS[kind].search(ast.unparse(node)):
            counts[kind] = counts.get(kind, 0) + 1
    return counts


def _measure_suppressions(texts: Iterable[str]) -> dict[str, int]:
    """`SUPPRESSIONS`, per-code `noqa` counts and the pytest names the
    patterns cannot read over a set of file texts, however they were read
    -- from disk for the working tree, or from git for an earlier commit
    (FP-11)."""
    counts = dict.fromkeys(SUPPRESSIONS, 0)
    for text in texts:
        for name, pattern in SUPPRESSIONS.items():
            counts[name] += len(pattern.findall(text))
        for code, found in _noqa_code_counts(text).items():
            counts[code] = counts.get(code, 0) + found
        for kind, found in _pytest_counts(text).items():
            counts[kind] += found
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


Measure = Callable[[Iterable[str]], dict[str, int]]
CHECKER = "scripts/check_gate_config.py"


def base_measure(rev: str, root: Path = REPO) -> Measure | None:
    """`rev`'s own measure of suppressions (W5): its checker, read through
    git and loaded under a private name, supplies `_measure_suppressions`,
    or, for a checker from before that existed (84eb06d), its `SUPPRESSIONS`
    counted over each text. None when `rev` has no checker at all; an
    `ImportError` or `SyntaxError` when it has one that will not load."""
    source = blob_at(root, rev, CHECKER)
    if source is None:
        return None
    name = (
        "_base_check_gate_config_" + sha256(f"{root}:{rev}".encode()).hexdigest()[:16]
    )
    saved = list(sys.path)
    with tempfile.TemporaryDirectory() as scratch:
        path = Path(scratch) / "check_gate_config.py"
        path.write_text(source, encoding="utf-8")
        spec = importlib.util.spec_from_file_location(name, path)
        if spec is None or spec.loader is None:
            raise ImportError(name)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        try:
            spec.loader.exec_module(module)
        finally:
            sys.path[:] = saved
            del sys.modules[name]
    measure = getattr(module, "_measure_suppressions", None)
    if callable(measure):
        return cast(Measure, measure)
    patterns = getattr(module, "SUPPRESSIONS", None)
    if isinstance(patterns, dict):
        return lambda texts: _pattern_counts(patterns, texts)
    # A checker with neither is not one this gate can hold a tree to.
    raise ImportError(name)


def _pattern_counts(
    patterns: dict[str, re.Pattern[str]], texts: Iterable[str]
) -> dict[str, int]:
    """Each pattern's matches over every text: an old checker's whole rule."""
    counts = dict.fromkeys(patterns, 0)
    for text in texts:
        for kind, pattern in patterns.items():
            counts[kind] += len(pattern.findall(text))
    return counts


def baseline_problems(against: str, root: Path = REPO) -> list[str]:
    """Each budget that rose against `against`, a base branch's git revision
    (F58, FP-11, W5): both trees are measured fresh, rather than trusting two
    commits' own committed JSON numbers, and twice -- under this commit's
    own `SUPPRESSIONS` patterns and complexity keys, which let no pattern the
    base lacked go unapplied to it, and under `against`'s own checker, which
    lets no pattern this commit weakened hide the suppression it spends."""
    try:
        base = suppression_counts_at(against, root)
    except RuntimeError as refusal:
        return [f"baseline: {refusal}"]
    now = suppression_counts(root)
    problems = [
        f"baseline: {name} rose to {count} (base branch {base.get(name, 0)})"
        for name, count in now.items()
        if count > int(base.get(name, 0))
    ]
    try:
        measure = base_measure(against, root)
    except (ImportError, SyntaxError):
        return [*problems, f"baseline: {against}'s own checker could not be loaded"]
    if measure is None:
        return problems
    was = measure(tracked_python_at(root, against).values())
    held = measure(path.read_text(encoding="utf-8") for path in tracked_python(root))
    return problems + [
        f"baseline: {name} rose to {count} under {against}'s own rules "
        f"(base branch {was.get(name, 0)})"
        for name, count in held.items()
        if count > int(was.get(name, 0))
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

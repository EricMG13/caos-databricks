"""CI and pre-commit are read as Actions and pre-commit read them (review 4,
W2, W3, N3). Each layout change below once left a gate switched off -- a
condition placed after the steps, a quoted key, a workflow default, a line
ahead of the gate, a deleted scan kept alive in a comment, an env dropped --
while the line-oriented checker still passed; each is refused now, and so
is the committed configuration's own shape changed any other way."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import check_gate_config
import pytest
from test_check_gate_config import _tree
from tracked import tracked_files

CI = ".github/workflows/ci.yml"
HOOKS = ".pre-commit-config.yaml"
RUFF = "      - run: uv run ruff check .\n"
RACES = (
    "      - run: uv run pytest --no-cov tests/test_postgres_races.py\n"
    "        env:\n"
    "          CAOS_TEST_POSTGRES_URL: postgresql://postgres:caos@localhost:5432/caos\n"
    '          CAOS_REQUIRE_POSTGRES: "1"\n'
)
LINT_STEP_KEYS = sorted(check_gate_config.STEP_KEYS)
MISSING_RUFF = "ci: no step runs 'uv run ruff check .'"


def _unpinned(job: str, *lines: str) -> str:
    return f"ci: job {job} runs a script no pin names: {'\n'.join(lines)!r}"


# id -> (the edit, the problems it must raise)
CI_MUTATIONS: dict[str, tuple[Callable[[str], str], list[str]]] = {
    "job if placed after the job's steps": (
        lambda t: t.replace("\n  types:\n", "    if: false\n\n  types:\n", 1),
        ["ci: 'uv run ruff check .' runs only when its job's if: allows it"],
    ),
    "step if placed after its run": (
        lambda t: t.replace(RUFF, RUFF + "        if: false\n", 1),
        ["ci: 'uv run ruff check .' runs only when its step's if: allows it"],
    ),
    "step if as a quoted key": (
        lambda t: t.replace(
            RUFF, '      - "if": false\n        run: uv run ruff check .\n', 1
        ),
        ["ci: 'uv run ruff check .' runs only when its step's if: allows it"],
    ),
    "workflow defaults.run.shell": (
        lambda t: t.replace(
            "\nenv:\n", '\ndefaults:\n  run:\n    shell: "true {0}"\n\nenv:\n', 1
        ),
        [
            "ci: the workflow sets 'defaults'; only "
            f"{sorted(check_gate_config.CI_TOP_PINNED)} and "
            f"{sorted(check_gate_config.CI_TOP_FREE)} are held"
        ],
    ),
    "exit 0 ahead of the gate in a literal block": (
        lambda t: t.replace(
            RUFF, "      - run: |\n          exit 0\n          uv run ruff check .\n", 1
        ),
        [_unpinned("lint", "exit 0", "uv run ruff check ."), MISSING_RUFF],
    ),
    "the gate inside a heredoc": (
        lambda t: t.replace(
            RUFF,
            "      - run: |\n          cat <<'EOF'\n          uv run ruff check .\n"
            "          EOF\n",
            1,
        ),
        [_unpinned("lint", "cat <<'EOF'", "uv run ruff check .", "EOF"), MISSING_RUFF],
    ),
    "trap exit 0 on EXIT": (
        lambda t: t.replace(
            RUFF,
            "      - run: |\n          trap 'exit 0' EXIT\n"
            "          uv run ruff check .\n",
            1,
        ),
        [_unpinned("lint", "trap 'exit 0' EXIT", "uv run ruff check ."), MISSING_RUFF],
    ),
    "the races step loses its database and CAOS_REQUIRE_POSTGRES": (
        lambda t: t.replace(
            RACES,
            "      - run: uv run pytest --no-cov tests/test_postgres_races.py\n",
            1,
        ),
        [
            f"ci: {check_gate_config.RACES_GATE!r} does not carry exactly its "
            "pinned env ['CAOS_REQUIRE_POSTGRES', 'CAOS_TEST_POSTGRES_URL']"
        ],
    ),
    "working-directory on the ruff step": (
        lambda t: t.replace(RUFF, RUFF + "        working-directory: frontend\n", 1),
        [
            "ci: a step in job lint sets 'working-directory'; a step may set only "
            f"{LINT_STEP_KEYS}"
        ],
    ),
    # N3: F171's `${{` check read raw text.
    "a template spliced through a quoted run key": (
        lambda t: t.replace(
            RUFF, '      - "run": echo ${{ github.head_ref }}\n' + RUFF
        ),
        [
            "ci: 'echo ${{ github.head_ref }}' splices a template expression into "
            "a run: script"
        ],
    ),
    "a template spliced through a double-quoted escape": (
        lambda t: t.replace(
            RUFF, '      - run: "echo $\\x7B{ github.head_ref }}"\n' + RUFF
        ),
        [
            "ci: 'echo ${{ github.head_ref }}' splices a template expression into "
            "a run: script"
        ],
    ),
    # An unpinned step runs before the gates and can put a stand-in `uv`
    # first on PATH, or skip every pre-commit hook through the environment.
    "a step that rewrites PATH before the gates": (
        lambda t: t.replace(
            RUFF, '      - run: echo "$PWD/bin" >> "$GITHUB_PATH"\n' + RUFF, 1
        ),
        [_unpinned("lint", 'echo "$PWD/bin" >> "$GITHUB_PATH"')],
    ),
    "SKIP in the workflow's environment": (
        lambda t: t.replace(
            '  UV_VERSION: "0.12.5"\n', '  UV_VERSION: "0.12.5"\n  SKIP: gitleaks\n'
        ),
        ["ci: the workflow's env is not as pinned"],
    ),
    "pull requests no longer trigger the workflow": (
        lambda t: t.replace("  pull_request:\n", "  workflow_dispatch:\n", 1),
        ["ci: the workflow's on is not as pinned"],
    ),
    "checkout of another ref": (
        lambda t: t.replace(
            "        with: {fetch-depth: 0}\n",
            "        with: {fetch-depth: 0, ref: main}\n",
            1,
        ),
        [
            "ci: job lint uses "
            "'actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1' "
            "as no pin gives"
        ],
    ),
}


@pytest.mark.parametrize("mutation", list(CI_MUTATIONS))
def test_a_ci_layout_that_switches_a_gate_off_is_refused(
    tmp_path: Path, mutation: str
) -> None:
    root = _tree(tmp_path)
    ci = root / CI
    text = ci.read_text(encoding="utf-8")
    assert check_gate_config._ci_problems(root) == []
    edit, expected = CI_MUTATIONS[mutation]
    mutated = edit(text)
    assert mutated != text, "the committed ci.yml no longer has this shape"
    ci.write_text(mutated, encoding="utf-8")
    problems = check_gate_config._ci_problems(root)
    for problem in expected:
        assert problem in problems, problems


HOOK_MUTATIONS: dict[str, tuple[Callable[[str], str], list[str]]] = {
    "a top-level exclude skips every hook": (
        lambda t: "exclude: '.*'\n" + t,
        [
            "pre-commit: the config sets 'exclude'; it may set only "
            f"{sorted(check_gate_config.PRE_COMMIT_KEYS)}"
        ],
    ),
    "a top-level default_stages moves every hook off the commit": (
        lambda t: "default_stages: [manual]\n" + t,
        [
            "pre-commit: the config sets 'default_stages'; it may set only "
            f"{sorted(check_gate_config.PRE_COMMIT_KEYS)}"
        ],
    ),
    # W3: pre-push and pre-merge-commit would run every hook without
    # `stages`, the auto-fixers and the repo-wide checks included.
    "the hook types to install widened to pushes and merges": (
        lambda t: "default_install_hook_types: [pre-commit, pre-push]\n" + t,
        [
            "pre-commit: default_install_hook_types is set beyond "
            f"{check_gate_config.HOOK_TYPES}"
        ],
    ),
    "a hook narrowed to files of another type": (
        lambda t: t.replace(
            "        entry: uv run python scripts/check_vocabulary.py\n",
            "        entry: uv run python scripts/check_vocabulary.py\n"
            "        types: [ruby]\n",
            1,
        ),
        ["pre-commit: vocabulary[0].types is set; it can change what the hook runs on"],
    ),
    "the ruff repo pointed at a fork": (
        lambda t: t.replace(
            "https://github.com/astral-sh/ruff-pre-commit",
            "https://github.com/someone-else/ruff-pre-commit",
            1,
        ),
        [
            "pre-commit: repo https://github.com/someone-else/ruff-pre-commit is not "
            "one this gate pins",
            "pre-commit: repo https://github.com/astral-sh/ruff-pre-commit appears 0 "
            "times, not once",
        ],
    ),
    "a local hook takes the ruff id": (
        lambda t: t.replace(
            "      - id: io-budget\n",
            "      - id: ruff\n        name: ruff\n        entry: 'true'\n"
            "        language: system\n      - id: io-budget\n",
            1,
        ),
        [
            "pre-commit: repo local runs ['vocabulary', 'tested', 'ruff', "
            "'io-budget'], not ['vocabulary', 'tested', 'io-budget']",
            "pre-commit: ruff appears 2 time(s), expected 1",
        ],
    ),
}


@pytest.mark.parametrize("mutation", list(HOOK_MUTATIONS))
def test_a_pre_commit_layout_that_switches_a_hook_off_is_refused(
    tmp_path: Path, mutation: str
) -> None:
    root = _tree(tmp_path)
    hooks = root / HOOKS
    text = hooks.read_text(encoding="utf-8")
    assert check_gate_config._hook_problems(root) == []
    edit, expected = HOOK_MUTATIONS[mutation]
    mutated = edit(text)
    assert mutated != text, "the committed pre-commit config no longer has this shape"
    hooks.write_text(mutated, encoding="utf-8")
    problems = check_gate_config._hook_problems(root)
    for problem in expected:
        assert problem in problems, problems


def test_a_script_is_read_as_the_shell_runs_it() -> None:
    """Continuations joined, whitespace collapsed, blank and comment lines
    dropped; any other line is part of what must match its pin."""
    assert check_gate_config.script_lines(
        "uv run a \\\n    --flag  b\n\n# a note\n  next   line\n"
    ) == ("uv run a --flag b", "next line")
    assert check_gate_config.script_lines("exit 0\nuv run ruff check .") == (
        "exit 0",
        "uv run ruff check .",
    )


def test_both_gitleaks_scans_run_the_one_pinned_version(tmp_path: Path) -> None:
    """W3: the hook's rev is the version the gitleaks workflow installs."""
    version = check_gate_config.GITLEAKS_VERSION
    hook_rev, _ = check_gate_config.PRE_COMMIT_REPOS[
        "https://github.com/gitleaks/gitleaks"
    ]
    assert hook_rev == version
    root = _tree(tmp_path)
    assert check_gate_config._gitleaks_ci_problems(root) == []
    scan_file = root / check_gate_config.GITLEAKS_CI_FILE
    text = scan_file.read_text(encoding="utf-8")
    scan_file.write_text(
        text.replace(f"GITLEAKS_VERSION: {version[1:]}", "GITLEAKS_VERSION: 8.24.3"),
        encoding="utf-8",
    )
    problems = check_gate_config._gitleaks_ci_problems(root)
    assert f"gitleaks: the workflow does not install {version}" in problems


def test_a_weakened_or_missing_gitleaks_ci_file_is_refused(tmp_path: Path) -> None:
    root = _tree(tmp_path)
    scan_file = root / check_gate_config.GITLEAKS_CI_FILE
    text = scan_file.read_text(encoding="utf-8")
    scan_file.write_text(
        text.replace("--ignore-gitleaks-allow", "--redact", 1).replace(
            "--redact --ignore-gitleaks-allow", "--redact --first-parent", 1
        ),
        encoding="utf-8",
    )
    problems = check_gate_config._gitleaks_ci_problems(root)
    assert (
        "gitleaks: a scan lacks one of "
        "['--ignore-gitleaks-allow', '--config .gitleaks.toml']"
    ) in problems
    assert "gitleaks: the workflow narrows the scan to first parents" in problems
    scan_file.unlink()
    assert check_gate_config._gitleaks_ci_problems(root) == [
        f"gitleaks: {check_gate_config.GITLEAKS_CI_FILE} is missing or not a mapping"
    ]


SCAN = check_gate_config.GITLEAKS_CI_FILE
WEEKLY = check_gate_config.SECRETS_WEEKLY_FILE
SCAN_UNPINNED = f"gitleaks: {SCAN} is not as pinned"
VERSION = check_gate_config.GITLEAKS_VERSION
SCAN_FLAGS = (
    "gitleaks: a scan lacks one of "
    "['--ignore-gitleaks-allow', '--config .gitleaks.toml']"
)
CHECKOUT = "actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1"
ASSET = 'asset="gitleaks_${GITLEAKS_VERSION}_${GITLEAKS_PLATFORM}.tar.gz"'
TARBALL_SHA = "551f6fc83ea457d62a0d98237cbad105af8d557003051f41f3e7ca7b3f2470eb"


def _between(text: str, start: str, end: str) -> str:
    return text[text.index(start) : text.index(end)]


def _exact(old: str, new: str) -> Callable[[str], str]:
    return lambda t: t.replace(old, new, 1)


# C1 (adv-gates-wave1.md): each edit weakens the secret scan, and each once
# passed this gate and its tests. id -> (the edit, the problems it must raise
# besides the whole-file pin).
SCAN_MUTATIONS: dict[str, tuple[Callable[[str], str], list[str]]] = {
    "#1 the sha256 check deleted and the hash zeroed": (
        lambda t: t.replace(
            '          echo "${GITLEAKS_SHA256}  ${asset}" | sha256sum -c -\n', "", 1
        ).replace(TARBALL_SHA, "0" * 64, 1),
        [],
    ),
    "#2 job-level continue-on-error": (
        _exact(
            "    if: ${{ !cancelled() }}\n",
            "    if: ${{ !cancelled() }}\n    continue-on-error: true\n",
        ),
        [],
    ),
    "#3 the job switched off": (
        _exact("if: ${{ !cancelled() }}", "if: false"),
        [],
    ),
    "#4 push and pull_request triggers removed": (
        lambda t: t.replace(
            _between(t, "  push:\n", "  workflow_call:"), "  workflow_dispatch:\n", 1
        ),
        [],
    ),
    "#5 the scan's exit code swallowed": (
        _exact('tee "$log" || rc=$?', 'tee "$log" || true'),
        [],
    ),
    "#6 --enable-rule narrows the rules": (
        _exact(
            "--config .gitleaks.toml ",
            "--config .gitleaks.toml --enable-rule bare-token-in-dot-directory ",
        ),
        [],
    ),
    "#7 another config that satisfies the substring": (
        _exact("--config .gitleaks.toml ", "--config .gitleaks.toml.off "),
        [],
    ),
    "#8 --gitleaks-ignore-path elsewhere": (
        _exact(
            "--config .gitleaks.toml ",
            "--config .gitleaks.toml --gitleaks-ignore-path docs/ ",
        ),
        [],
    ),
    "#9 exit 0 ahead of the case": (
        _exact(
            '          case "$GITHUB_EVENT_NAME" in\n',
            '          exit 0\n          case "$GITHUB_EVENT_NAME" in\n',
        ),
        [],
    ),
    "#10 checkout by tag, shallow, keeping the token": (
        lambda t: t.replace(CHECKOUT, "actions/checkout@v4", 1)
        .replace("fetch-depth: 0 ", "fetch-depth: 1 ", 1)
        .replace("persist-credentials: false", "persist-credentials: true", 1),
        [],
    ),
    "#11 permissions write-all": (
        _exact("permissions:\n  contents: read\n", "permissions: write-all\n"),
        [],
    ),
    "#12 the PR range narrowed to the head commit": (
        _exact(
            'scan "${PR_BASE_SHA}..${PR_HEAD_SHA}"',
            'scan "${PR_HEAD_SHA}^..${PR_HEAD_SHA}"',
        ),
        [],
    ),
    "#13 the scan replaced by an echo": (
        _exact(
            "            gitleaks git --no-banner",
            "            echo gitleaks git --no-banner",
        ),
        [],
    ),
    "#14 the asset hard-coded to another version": (
        _exact(ASSET, ASSET.replace("${GITLEAKS_VERSION}", "8.18.0")),
        [],
    ),
    "control: the installed version moved": (
        _exact("GITLEAKS_VERSION: 8.30.1", "GITLEAKS_VERSION: 8.24.3"),
        [f"gitleaks: the workflow does not install {VERSION}"],
    ),
    "control: --first-parent added": (
        _exact(
            "--redact --ignore-gitleaks-allow",
            "--redact --ignore-gitleaks-allow --log-opts=--first-parent",
        ),
        ["gitleaks: the workflow narrows the scan to first parents"],
    ),
    "control: --ignore-gitleaks-allow dropped": (
        _exact(" --ignore-gitleaks-allow \\\n", " \\\n"),
        [SCAN_FLAGS],
    ),
}


@pytest.mark.parametrize("mutation", list(SCAN_MUTATIONS))
def test_a_weakened_secret_scan_file_is_refused(tmp_path: Path, mutation: str) -> None:
    root = _tree(tmp_path)
    scan = root / SCAN
    text = scan.read_text(encoding="utf-8")
    assert check_gate_config._gitleaks_ci_problems(root) == []
    edit, expected = SCAN_MUTATIONS[mutation]
    mutated = edit(text)
    assert mutated != text, "the committed gitleaks.yml no longer has this shape"
    scan.write_text(mutated, encoding="utf-8")
    problems = check_gate_config._gitleaks_ci_problems(root)
    assert any(problem.startswith(SCAN_UNPINNED) for problem in problems), problems
    for problem in expected:
        assert problem in problems, problems
    assert check_gate_config.configuration_problems(root) != []


@pytest.mark.parametrize(
    "edit",
    [
        lambda t: t.replace(
            "  schedule:\n    - cron: '17 3 * * 1'", "  schedule: []", 1
        ),
        lambda t: t.replace("./.github/workflows/gitleaks.yml", "./other.yml", 1),
        lambda t: t.replace("permissions:\n  contents: read\n", "", 1),
    ],
    ids=["cron removed", "another workflow called", "top permissions dropped"],
)
def test_a_weakened_weekly_scan_is_refused(
    tmp_path: Path, edit: Callable[[str], str]
) -> None:
    root = _tree(tmp_path)
    weekly = root / WEEKLY
    text = weekly.read_text(encoding="utf-8")
    assert edit(text) != text
    weekly.write_text(edit(text), encoding="utf-8")
    problems = check_gate_config._gitleaks_ci_problems(root)
    assert any(
        problem.startswith(f"gitleaks: {WEEKLY} is not as pinned")
        for problem in problems
    ), problems


def test_an_unreadable_ci_file_or_hook_config_is_refused(tmp_path: Path) -> None:
    root = _tree(tmp_path)
    (root / CI).write_text("jobs: [unclosed\n", encoding="utf-8")
    (root / HOOKS).write_text("- a list, not a mapping\n", encoding="utf-8")
    assert check_gate_config._ci_problems(root) == [
        "ci: .github/workflows/ci.yml is missing or not a mapping"
    ]
    assert check_gate_config._hook_problems(root) == [
        "pre-commit: .pre-commit-config.yaml is missing or not a mapping"
    ]


def test_a_committed_host_or_auth_key_in_the_bundle_is_refused(tmp_path: Path) -> None:
    """W7: the one command supplies the workspace through the profile, and
    a stand-in run through the stub; a host, profile or credential the
    bundle names for itself would win over either, and an `include` brings
    in files the checks never read."""
    root = _tree(tmp_path)
    bundle = root / "databricks.yml"
    written = bundle.read_text(encoding="utf-8")
    assert check_gate_config.bundle_auth_problems(written) == []
    target_host = written.replace(
        "    workspace:\n      root_path: /Workspace/caos-bundle/${bundle.target}\n",
        "    workspace:\n      root_path: /Workspace/caos-bundle/${bundle.target}\n"
        "      host: https://elsewhere.example.invalid\n",
        1,
    )
    assert target_host != written
    bundle.write_text(target_host, encoding="utf-8")
    assert (
        "bundle: target prod sets workspace.host; the workspace is the profile's"
        in check_gate_config._bundle_problems(root)
    )
    for extra, named in (
        ("workspace:\n  profile: deployer\n", "the bundle sets workspace.profile"),
        ("workspace:\n  client_id: an-sp\n", "the bundle sets workspace.client_id"),
        ("include:\n  - more/*.yml\n", "the bundle includes other files"),
    ):
        bundle.write_text(written + extra, encoding="utf-8")
        assert any(named in p for p in check_gate_config._bundle_problems(root)), extra


# Acceptance row A28's scope: the package the App runs, the agent definitions
# and vendored skills its prompts are built from, and the App's own config.
OPENROUTER_FREE = ("caos", "icm", ".claude/skills", "databricks.yml", "app.yaml")


def test_openrouter_is_named_only_under_tests() -> None:
    """A28, which no CI step runs: the test provider exists only under
    `tests/` (CLAUDE.md), so none of A28's paths -- the App's code, its
    prompts' sources and its config -- names it, a comment included, which is
    how one reached `caos/`. `pyproject.toml` ships too and names the adapter
    and its marker, which is the dependency list's to do."""
    root = check_gate_config.REPO
    named = [
        name
        for name in tracked_files(root, *OPENROUTER_FREE)
        if b"openrouter" in (root / name).read_bytes().lower()
    ]
    assert named == []

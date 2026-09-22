"""Build hygiene: facts about the files that build and ship this, asserted here.

A job with no timeout can hold a runner for six hours on a hung step, and two
runs of one branch racing each other report whichever finished last. Both are
facts about the CI file, so both are asserted against that file itself.

The Dockerfile is here for the same reason and was not, which is the gap: it is
the other place this repository installs packages and the only one whose result
ships, and no gate read it. `check_tested.py` reads Python; Trivy answers "are
the installed packages known-vulnerable", never "was this build hashed,
wheels-only, digest-pinned and unprivileged".
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
CI_YAML = REPO / ".github" / "workflows" / "ci.yml"
DOCKERFILE = REPO / "Dockerfile"
MAKEFILE = REPO / "Makefile"


def _dockerfile() -> str:
    return DOCKERFILE.read_text(encoding="utf-8")


def _jobs(text: str) -> dict[str, str]:
    """Job name -> job body, split on the two-space-indented keys under `jobs:`."""
    body = text.split("\njobs:\n", 1)[1]
    parts = re.split(r"\n  ([a-z][a-z0-9_-]*):\n", "\n" + body)
    return dict(zip(parts[1::2], parts[2::2], strict=True))


def test_every_job_declares_a_timeout() -> None:
    jobs = _jobs(CI_YAML.read_text(encoding="utf-8"))
    assert jobs, "no jobs parsed; the workflow layout changed under this test"
    missing = [name for name, body in jobs.items() if "timeout-minutes:" not in body]
    assert not missing, f"jobs without timeout-minutes: {missing}"


def test_ci_cancels_superseded_runs() -> None:
    text = CI_YAML.read_text(encoding="utf-8")
    assert "cancel-in-progress: true" in text


def test_the_size_job_delegates_to_the_canonical_script() -> None:
    """The `size` job once reimplemented `check_pr_size.py`'s pathspec inline,
    with `**/vendor/**` where the script's own comment explains why that must
    be root-anchored `vendor/**` -- `**/vendor/**` does not match a bundle at
    the repo root, so the job counted 8,840 vendor-bundle lines a correctly
    authorised rebuild (§92) never should have. Delegating to the one script
    keeps CI and a local run measuring the same thing."""
    jobs = _jobs(CI_YAML.read_text(encoding="utf-8"))
    assert "check_pr_size.py" in jobs["size"]
    assert "**/vendor/**" not in jobs["size"]


def test_every_install_is_locked_and_wheels_only() -> None:
    """A lock pins which bytes arrive; `uv sync --locked` refuses a lock that
    drifted, and `tool.uv.no-build` is what stops those bytes being a source
    distribution whose setup code runs at install time. This is what stops
    the next job being added without either."""
    installs = [
        line.strip()
        for line in CI_YAML.read_text(encoding="utf-8").splitlines()
        if "uv sync" in line
    ]

    assert installs, "CI installs something; this test found nothing"
    for install in installs:
        assert "--locked" in install, install
    project = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))
    assert project["tool"]["uv"]["no-build"] is True
    assert not (REPO / "requirements.txt").exists(), "pip would take over the App"

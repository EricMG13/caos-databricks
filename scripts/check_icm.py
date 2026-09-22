#!/usr/bin/env python3
"""Refuse an ICM workspace that does not match what the runtime loads (spec G17).

Every module has a stage folder; every contract names exactly the files the
bundle delivers and the prompt blocks the host renders; no reference file is
orphaned; the stage folders are current; every vendored build-time skill the
skills ledger keeps exists with its provenance line.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from caos.methodology.bundle import Bundle

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))
VENDORED_SKILLS = (
    "databricks-core",
    "databricks-apps-python",
    "databricks-lakebase",
    "databricks-model-serving",
    "databricks-dabs",
    "databricks-python-sdk",
)
PROVENANCE = "<!-- provenance: vendored"


def skill_problems(root: Path = REPO) -> list[str]:
    """Each kept skill missing, or vendored without its provenance line."""
    problems = []
    for name in VENDORED_SKILLS:
        skill = root / ".claude" / "skills" / name / "SKILL.md"
        if not skill.is_file():
            problems.append(f".claude/skills/{name}/SKILL.md: missing")
        elif PROVENANCE not in skill.read_text(encoding="utf-8"):
            problems.append(f".claude/skills/{name}/SKILL.md: no provenance line")
    return problems


def stale_stages(bundle: Bundle) -> list[str]:
    """Stage files whose content differs from what the bundle implies."""
    from icm_stages import stage_files

    return [
        path.relative_to(REPO).as_posix()
        for path, text in stage_files(bundle).items()
        if not path.is_file() or path.read_text(encoding="utf-8") != text
    ]


def main() -> int:
    from caos.icm import BUNDLE, verify
    from caos.methodology.bundle import Bundle

    bundle = Bundle(BUNDLE)
    problems = verify(bundle) + [f"stale: {p}" for p in stale_stages(bundle)]
    problems += skill_problems()
    for problem in problems:
        print(problem)
    if problems:
        return 1
    print("icm: contracts, blocks, references and vendored skills verified")
    return 0


if __name__ == "__main__":
    sys.exit(main())

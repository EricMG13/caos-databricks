#!/usr/bin/env python3
"""Regenerate the ICM stage folders from the bundle; never hand-maintain them.

One `CONTEXT.md` and one `prompt.md` per module (`icm/CONTEXT.md`). The
Inputs table is derived from `delivered_authority`, the Process and Outputs
from what the graph node does, and the prompt blocks from
`caos.icm.expected_blocks`. `--check` reports whether the tree is current.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from caos.methodology.bundle import Bundle

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

_TITLE = re.compile(r"^#\s+(.+)$", re.M)
_DESCRIPTION = re.compile(r"^description:\s*(.+)$", re.M)

# Every stage runs the same six-step host process and writes the same three
# outputs (neither is delivered to the model: `caos.icm.load_contract` only
# checks the header is present, never the body). Stated once, in
# `icm/CONTEXT.md` (Layer 1), rather than repeated verbatim in all 27 stage
# folders (SI-12, N29) -- each stage's CONTEXT.md points at it instead.
PROCESS = """\
## Process

Common to every stage: the host's six-step process, from reading the store's
pins to accepting the artifact -- stated once in `icm/CONTEXT.md` (Layer 1).
"""

OUTPUTS = """\
## Outputs

Common to every stage: the handoff, its host record and the call outcome --
stated once in `icm/CONTEXT.md` (Layer 1).
"""


def _purpose(bundle: Bundle, module_id: str) -> str:
    """The module's own one-line purpose, from its verified `SKILL.md`."""
    from caos.icm import MODEL_MODULE, PARSE_MODULE, STAGES
    from caos.methodology.bundle import verified_bytes

    if module_id == MODEL_MODULE:
        skill = (STAGES / "cp-cf" / "references" / "SKILL.md").read_text(
            encoding="utf-8"
        )
    else:
        owner = "CP-0" if module_id == PARSE_MODULE else module_id
        skill = verified_bytes(bundle, owner, "SKILL.md").decode("utf-8")
    described = _DESCRIPTION.search(skill)
    if described:
        return described.group(1).strip().strip('"')
    titled = _TITLE.search(skill)
    return titled.group(1).strip() if titled else module_id


def render_context(bundle: Bundle, module_id: str, slugs: dict[str, str]) -> str:
    """The `CONTEXT.md` for one module."""
    from caos.icm import (
        CONDITIONS,
        MODEL_MODULE,
        PARSE_MODULE,
        expected_blocks,
        expected_inputs,
    )

    slug = slugs[module_id]
    rows = [
        f"| {'host' if module_id == MODEL_MODULE else 'bundle'} | {path} | whole | "
        + (
            "the module's authority, delivered first"
            if path.endswith("SKILL.md")
            else "delivered authority file"
        )
        + " |"
        for path in expected_inputs(bundle, module_id, slugs)
    ]
    always, conditional = expected_blocks(module_id)
    rows += [
        f"| prompt | icm/shared/prompt/{block}.md | whole | prompt block |"
        for block in always
    ]
    rows += [
        f"| prompt | icm/shared/prompt/{block}.md | whole | prompt block, "
        f"{CONDITIONS[block]} |"
        for block in conditional
    ]
    rows += [
        "| store | accepted upstream handoffs | whole | context labelled by "
        "`allowed_use`; never citable |",
        "| store | delivered evidence blocks | CP-0's T8 selection for this module "
        "| the only citable text |",
    ]
    note = {
        PARSE_MODULE: "CP-PARSE is CP-0's authority under its own route node "
        "(host carve-out, legacy decision §5).",
        MODEL_MODULE: "CP-CF is host-owned: the calculator is repo code, "
        "byte-pinned by `icm/HOST_INTEGRITY_v1.json`.",
    }.get(
        module_id,
        f"Bundle folder `vendor/deploy-v/skills/{slug}/`, read through the "
        "verified `Bundle` seam and never edited.",
    )
    return (
        f"# Stage {module_id}\n\n"
        f"{_purpose(bundle, module_id)}\n\n"
        f"{note} The pinned route, not this folder, decides when the node runs "
        "(`icm/CONTEXT.md`).\n\n"
        "## Inputs\n\n| Source | File | Section | Why |\n|---|---|---|---|\n"
        + "\n".join(rows)
        + "\n\n"
        + PROCESS
        + "\n"
        + OUTPUTS
    )


def render_prompt(module_id: str) -> str:
    """The `prompt.md` for one module: the blocks its node renders, in order."""
    from caos.icm import expected_blocks

    always, conditional = expected_blocks(module_id)
    return (
        "---\n"
        f"module: {module_id}\n"
        f"blocks: [{', '.join(always)}]\n"
        f"conditional: [{', '.join(conditional)}]\n"
        "---\n\n"
        f"# Prompt for {module_id}\n\n"
        "The host renders the blocks above from `icm/shared/prompt/` in this "
        "order, with the authority, upstream, citation-register, research-brief, "
        "source-preparation and evidence sections between them as "
        "`caos/methodology/invocation.py` assembles them. A conditional block is "
        "rendered only under the condition the stage contract's Inputs table "
        "names for it. A first attempt's rendered bytes are parity-tested against "
        "the legacy host.\n"
    )


def stage_files(bundle: Bundle) -> dict[Path, str]:
    """Every stage file the bundle implies, keyed by path."""
    from caos.icm import STAGES, stage_slugs

    slugs = stage_slugs(bundle)
    files: dict[Path, str] = {}
    for module_id, slug in sorted(slugs.items()):
        folder = STAGES / slug
        files[folder / "CONTEXT.md"] = render_context(bundle, module_id, slugs)
        files[folder / "prompt.md"] = render_prompt(module_id)
    return files


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true", help="write the folders")
    parser.add_argument("--check", action="store_true", help="exit 1 if stale")
    args = parser.parse_args(argv)
    from caos.icm import BUNDLE
    from caos.methodology.bundle import Bundle

    files = stage_files(Bundle(BUNDLE))
    stale = [
        path
        for path, text in files.items()
        if not path.is_file() or path.read_text(encoding="utf-8") != text
    ]
    if args.write:
        for path, text in files.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
        print(f"wrote {len(files)} files")
        return 0
    if args.check and stale:
        for path in stale:
            shown = path.relative_to(REPO) if path.is_relative_to(REPO) else path
            print(f"stale: {shown}")
        return 1
    print(f"{len(files)} stage files, {len(stale)} stale")
    return 0


if __name__ == "__main__":
    sys.exit(main())

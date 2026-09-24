"""The ICM workspace loader: stage contracts, prompt blocks, and their check.

Spec section 3.5 (D4, D5; ICM paper arXiv 2603.16021). `icm/` is the agent
definition layer: `icm/CONTEXT.md` is Layer 1, each `icm/stages/<slug>/` is one
module's Layer 2 contract (`CONTEXT.md`: Inputs, Process, Outputs) beside the
host prompt blocks it declares (`prompt.md`), and `icm/shared/prompt/` holds
the host's prompt text as Layer 3 reference files. Bundle files are named by
path and read through the verified `Bundle` seam, never copied (invariant 4).

`build_handoff_prompt` reads its blocks through `prompt_block`, so the rendered
prompt is exactly the text these files hold. `verify` is what
`scripts/check_icm.py` and the suite run: every module has a contract, every
contract names exactly the files the bundle delivers, every block a contract
declares is one the host will actually render, and no reference file is
orphaned.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import cache
from hashlib import sha256
from pathlib import Path, PurePosixPath

from caos.methodology.bundle import Bundle, delivered_authority
from caos.refusals import Refusal, RefusalCode

ROOT = Path(__file__).resolve().parents[1]
ICM = ROOT / "icm"
STAGES = ICM / "stages"
PROMPTS = ICM / "shared" / "prompt"
BUNDLE = ROOT / "vendor" / "deploy-v"

GATE_MODULE = "CP-0"
PARSE_MODULE = "CP-PARSE"
MODEL_MODULE = "CP-CF"
# Host-owned stage folders that are not bundle skills.
HOST_SLUGS = {PARSE_MODULE: "cp-parse", MODEL_MODULE: "cp-cf"}
# The modules `build_handoff_prompt` hands the forecast extension when the
# route carries CP-CF (`caos/methodology/invocation.py`).
FORECAST_OWNERS = frozenset({"CP-1", "CP-2G", "CP-4"})
BASE_BLOCKS = ("instruction", "tagged", "host_steps", "final_check")
# The block a node's one second attempt adds (D30), and when each conditional
# block is rendered, as the stage contracts state it.
RETRY_BLOCK = "validator_feedback"
CONDITIONS = {
    "forecast_extension": "when the route carries CP-CF",
    RETRY_BLOCK: "on a node's one second attempt after a refused answer (D30)",
}

_NAME = re.compile(r"^[a-z0-9_]+$")
_ROW = re.compile(
    r"^\|\s*(?P<source>[^|]+?)\s*\|\s*(?P<file>[^|]+?)\s*\|\s*(?P<section>[^|]+?)\s*\|\s*(?P<why>[^|]+?)\s*\|$"
)


@cache
def prompt_block(name: str) -> str:
    """One host prompt block, exactly as its file holds it (Layer 3), and
    exactly as the host manifest records it (F67): bytes the manifest does not
    name, or names differently, are refused, never delivered."""
    if _NAME.match(name) is None:
        raise Refusal(RefusalCode.AUTHORITY_BYTES_MISMATCH)
    from caos.methodology.host import host_skill

    entry = host_skill().get("host_prompt_hashes", {}).get(f"{name}.md")
    try:
        raw = (PROMPTS / f"{name}.md").read_bytes()
    except OSError:
        raise Refusal(RefusalCode.AUTHORITY_BYTES_MISMATCH) from None
    if not isinstance(entry, dict) or entry.get("sha256") != sha256(raw).hexdigest():
        raise Refusal(RefusalCode.AUTHORITY_BYTES_MISMATCH)
    return raw.decode("utf-8")


@dataclass(frozen=True, slots=True)
class InputRow:
    """One row of a stage contract's Inputs table."""

    source: str
    file: str
    section: str
    why: str


@dataclass(frozen=True, slots=True)
class Contract:
    """A stage folder as read: its contract and the prompt blocks it declares."""

    module_id: str
    slug: str
    inputs: tuple[InputRow, ...]
    has_process: bool
    has_outputs: bool
    blocks: tuple[str, ...]
    conditional: tuple[str, ...]


def stage_slugs(bundle: Bundle) -> dict[str, str]:
    """Every module that has a stage folder, to that folder's name."""
    return {**bundle.physical_modules(), **HOST_SLUGS}


def expected_blocks(module_id: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """The blocks the host renders for `module_id`: always, and under the
    condition `CONDITIONS` names for each of the rest. Mirrors
    `build_handoff_prompt`; the contract restates it."""
    always: list[str] = [BASE_BLOCKS[0]]
    if module_id == GATE_MODULE:
        always.append("gate_instruction")
    always += BASE_BLOCKS[1:]
    if module_id == GATE_MODULE:
        always.append("cp0_final_check")
    forecast = ("forecast_extension",) if module_id in FORECAST_OWNERS else ()
    # Every node's one second attempt after a refused answer (D30).
    return tuple(always), (*forecast, RETRY_BLOCK)


def expected_inputs(
    bundle: Bundle, module_id: str, slugs: dict[str, str]
) -> tuple[str, ...]:
    """The repo paths of every file the bundle delivers to `module_id`, in
    delivery order (`SKILL.md` first), as the contract must name them."""
    if module_id == MODEL_MODULE:
        return (
            "icm/stages/cp-cf/references/SKILL.md",
            "caos/calculators/cash_flow.py",
        )
    owner = GATE_MODULE if module_id == PARSE_MODULE else module_id
    folder = PurePosixPath("vendor/deploy-v/skills") / slugs[owner]
    paths = []
    for name, _data in delivered_authority(bundle, module_id).files:
        parts: list[str] = list(folder.parts)
        for part in PurePosixPath(name).parts:
            if part == "..":
                parts.pop()
            else:
                parts.append(part)
        paths.append("/".join(parts))
    return tuple(paths)


def load_contract(module_id: str, slug: str) -> Contract:
    """Read one stage folder; a missing file refuses `AUTHORITY_BYTES_MISMATCH`."""
    folder = STAGES / slug
    try:
        context = (folder / "CONTEXT.md").read_text(encoding="utf-8")
        prompt = (folder / "prompt.md").read_text(encoding="utf-8")
    except OSError:
        raise Refusal(RefusalCode.AUTHORITY_BYTES_MISMATCH) from None
    rows = []
    in_inputs = False
    for line in context.splitlines():
        if line.startswith("## "):
            in_inputs = line.strip() == "## Inputs"
            continue
        match = _ROW.match(line.strip()) if in_inputs else None
        if (
            match
            and match["source"] != "Source"
            and not match["source"].startswith("-")
        ):
            rows.append(
                InputRow(*(match[key] for key in ("source", "file", "section", "why")))
            )
    return Contract(
        module_id=module_id,
        slug=slug,
        inputs=tuple(rows),
        has_process="\n## Process" in context,
        has_outputs="\n## Outputs" in context,
        blocks=_front_matter_list(prompt, "blocks"),
        conditional=_front_matter_list(prompt, "conditional"),
    )


def _front_matter_list(prompt: str, key: str) -> tuple[str, ...]:
    """`key: [a, b]` from the prompt file's front matter, or nothing."""
    match = re.search(rf"^{key}: \[(.*?)\]$", prompt, re.M)
    if match is None:
        return ()
    return tuple(item.strip() for item in match.group(1).split(",") if item.strip())


def _block_byte_problems(slug: str, blocks: tuple[str, ...]) -> list[str]:
    """Every declared block, read through `prompt_block` (CF-079): a file
    missing was the only thing `is_file()` could ever have told this gate,
    so a block edited without its host manifest entry updated to match --
    the bytes `build_handoff_prompt` would actually refuse at request time
    -- passed a workspace check that only asked whether the name existed.
    """
    problems = []
    for block in blocks:
        try:
            prompt_block(block)
        except Refusal:
            problems.append(
                f"{slug}: block {block} is missing, or its bytes do not match "
                "the host manifest"
            )
    return problems


def _contract_problems(
    bundle: Bundle, module_id: str, slug: str, slugs: dict[str, str]
) -> tuple[list[str], set[str]]:
    """One stage folder's problems, and every file its contract names."""
    try:
        contract = load_contract(module_id, slug)
    except Refusal:
        return [f"{slug}: CONTEXT.md or prompt.md missing"], set()
    problems: list[str] = []
    named = {row.file for row in contract.inputs}
    bundle_rows = tuple(
        row.file for row in contract.inputs if row.source in ("bundle", "host")
    )
    if bundle_rows != expected_inputs(bundle, module_id, slugs):
        problems.append(f"{slug}: Inputs table does not match the delivered authority")
    always, conditional = expected_blocks(module_id)
    if (contract.blocks, contract.conditional) != (always, conditional):
        problems.append(f"{slug}: prompt.md blocks {contract.blocks} != {always}")
    blocks = tuple(f"icm/shared/prompt/{b}.md" for b in (*always, *conditional))
    prompt_rows = tuple(row.file for row in contract.inputs if row.source == "prompt")
    if prompt_rows != blocks:
        problems.append(f"{slug}: Inputs prompt rows do not match the blocks")
    problems += _block_byte_problems(slug, (*always, *conditional))
    if not (contract.has_process and contract.has_outputs):
        problems.append(f"{slug}: Process or Outputs section missing")
    return problems, named | set(blocks)


def verify(bundle: Bundle | None = None) -> list[str]:
    """Every problem with the workspace, or an empty list.

    Checks: a stage folder per module; each contract's bundle rows equal to
    the delivered authority in order; each contract's prompt rows equal to the
    blocks the host renders; Process and Outputs present; every file under
    `icm/shared/prompt/` and `icm/stages/*/references/` named by a contract.
    """
    bundle = bundle if bundle is not None else Bundle(BUNDLE)
    slugs = stage_slugs(bundle)
    problems: list[str] = []
    named: set[str] = set()
    for module_id, slug in sorted(slugs.items()):
        found, names = _contract_problems(bundle, module_id, slug, slugs)
        problems += found
        named |= names
    for path in sorted(ICM.rglob("*")):
        relative = path.relative_to(ROOT).as_posix()
        reference = "/references/" in relative or "/shared/prompt/" in relative
        if path.is_file() and reference and relative not in named:
            problems.append(f"{relative}: named by no contract")
    return problems

"""The ICM workspace is verified against what the runtime actually loads."""

from __future__ import annotations

from pathlib import Path

import check_icm
import icm_stages
import pytest

from caos import icm
from caos.icm import (
    BUNDLE,
    CONDITIONS,
    RETRY_BLOCK,
    Contract,
    InputRow,
    expected_blocks,
    expected_inputs,
    load_contract,
    prompt_block,
    stage_slugs,
    verify,
)
from caos.methodology.bundle import Bundle
from caos.refusals import Refusal

REPO = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def bundle() -> Bundle:
    return Bundle(BUNDLE)


def test_the_workspace_verifies_clean(bundle: Bundle) -> None:
    assert verify(bundle) == []
    assert check_icm.stale_stages(bundle) == []
    assert check_icm.skill_problems() == []


def test_every_module_has_a_stage_folder_including_the_host_ones(
    bundle: Bundle,
) -> None:
    slugs = stage_slugs(bundle)
    assert len(slugs) == 27
    assert slugs["CP-PARSE"] == "cp-parse" and slugs["CP-CF"] == "cp-cf"
    for slug in slugs.values():
        assert (icm.STAGES / slug / "CONTEXT.md").is_file()
        assert (icm.STAGES / slug / "prompt.md").is_file()


def test_a_contract_names_the_delivered_authority_skill_first(bundle: Bundle) -> None:
    slugs = stage_slugs(bundle)
    contract = load_contract("CP-DR", slugs["CP-DR"])
    assert isinstance(contract, Contract)
    assert isinstance(contract.inputs[0], InputRow)
    assert contract.inputs[0].file.endswith("cp-dr-deep-research/SKILL.md")
    expected = expected_inputs(bundle, "CP-DR", slugs)
    assert expected[0].endswith("/SKILL.md")
    assert "vendor/deploy-v/CANON_SHARED.md" in expected
    assert expected_inputs(bundle, "CP-CF", slugs) == (
        "icm/stages/cp-cf/references/SKILL.md",
        "caos/calculators/cash_flow.py",
    )


def test_the_gate_and_forecast_owners_declare_their_extra_blocks() -> None:
    always, conditional = expected_blocks("CP-0")
    assert always[:2] == ("instruction", "gate_instruction")
    # Every node may take its one second attempt (D30); only that is conditional.
    assert always[-1] == "cp0_final_check" and conditional == (RETRY_BLOCK,)
    assert expected_blocks("CP-1") == (
        ("instruction", "tagged", "host_steps", "final_check"),
        ("forecast_extension", RETRY_BLOCK),
    )
    assert expected_blocks("CP-5")[1] == (RETRY_BLOCK,)
    assert set(CONDITIONS) == {"forecast_extension", RETRY_BLOCK}


def test_prompt_blocks_are_read_byte_for_byte_and_names_are_closed() -> None:
    text = prompt_block("instruction")
    assert text == (icm.PROMPTS / "instruction.md").read_text(encoding="utf-8")
    assert text.startswith("You are executing methodology module {module_id}")
    for bad in ("../CLAUDE", "Instruction", "no-such-block"):
        with pytest.raises(Refusal, match=r"^AUTHORITY_BYTES_MISMATCH$"):
            prompt_block(bad)


def test_a_missing_stage_or_a_drifted_contract_is_a_problem(
    bundle: Bundle, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with pytest.raises(Refusal, match=r"^AUTHORITY_BYTES_MISMATCH$"):
        load_contract("CP-0", "no-such-stage")
    stages = tmp_path / "stages"
    stages.mkdir()
    slug = stage_slugs(bundle)["CP-5"]
    (stages / slug).mkdir()
    (stages / slug / "CONTEXT.md").write_text(
        "# Stage CP-5\n\n## Inputs\n\n## Process\n"
    )
    (stages / slug / "prompt.md").write_text("---\nblocks: [instruction]\n---\n")
    monkeypatch.setattr(icm, "STAGES", stages)
    problems = verify(bundle)
    assert any("Inputs table" in p for p in problems)
    assert any("prompt.md blocks" in p for p in problems)
    assert any("Outputs section missing" in p for p in problems)


def test_the_generator_renders_what_is_committed(bundle: Bundle) -> None:
    files = icm_stages.stage_files(bundle)
    assert len(files) == 54
    slugs = stage_slugs(bundle)
    assert icm_stages.render_context(bundle, "CP-0", slugs) == files[
        icm.STAGES / slugs["CP-0"] / "CONTEXT.md"
    ].replace("", "")
    assert icm_stages.render_prompt("CP-0").startswith("---\nmodule: CP-0\n")
    assert icm_stages.main(["--check"]) == 0
    assert check_icm.main() == 0


def test_the_vendored_bundle_is_pinned_and_a_swapped_manifest_refuses(
    bundle: Bundle, tmp_path: Path
) -> None:
    """F66: the manifest verifies every file; the pin verifies the manifest."""
    from caos.methodology.bundle_pin import BUNDLE_MANIFEST_SHA256

    assert bundle.manifest_sha256 == BUNDLE_MANIFEST_SHA256
    bundle.verify_pinned()
    swapped = tmp_path / "bundle"
    swapped.mkdir()
    manifest = bundle.root / "DEPLOY_V_INTEGRITY_v1.json"
    (swapped / manifest.name).write_bytes(manifest.read_bytes().replace(b"}", b" }", 1))
    with pytest.raises(Refusal, match=r"^AUTHORITY_BYTES_MISMATCH$"):
        Bundle(swapped).verify_pinned()


def test_verify_catches_a_declared_block_whose_bytes_do_not_match_the_manifest(
    bundle: Bundle, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """CF-079: `is_file()` could only ever say a block's name existed; a
    block edited without regenerating the host manifest to match -- the
    exact bytes `build_handoff_prompt` would refuse at request time -- once
    passed the static workspace check, which asked only that."""
    blocks = tmp_path / "prompt"
    blocks.mkdir()
    for block in icm.PROMPTS.glob("*.md"):
        (blocks / block.name).write_bytes(block.read_bytes())
    (blocks / "instruction.md").write_bytes(
        (blocks / "instruction.md").read_bytes() + b"\nOne more line.\n"
    )
    monkeypatch.setattr(icm, "PROMPTS", blocks)
    prompt_block.cache_clear()
    try:
        problems = verify(bundle)
    finally:
        prompt_block.cache_clear()
    assert any(
        "block instruction is missing, or its bytes do not match the host manifest" in p
        for p in problems
    )


def test_manifest_problems_matches_the_committed_manifest(bundle: Bundle) -> None:
    assert check_icm.manifest_problems() == []


def test_manifest_problems_reports_a_missing_manifest(tmp_path: Path) -> None:
    assert check_icm.manifest_problems(tmp_path) == [
        "icm/HOST_INTEGRITY_v1.json: missing"
    ]


def test_manifest_problems_catches_a_source_file_edited_without_regenerating_it(
    tmp_path: Path,
) -> None:
    """CF-079: nothing checked that icm/HOST_INTEGRITY_v1.json still matches
    a fresh run of host_manifest.py's own logic, so cash_flow.py, SKILL.md
    or a prompt block could drift from what the manifest records with
    nothing catching it until a route actually tried to use CP-CF."""
    root = tmp_path / "repo"
    for name in (
        "icm/HOST_INTEGRITY_v1.json",
        "icm/stages/cp-cf/references/SKILL.md",
        "caos/calculators/cash_flow.py",
    ):
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_bytes((REPO / name).read_bytes())
    prompts = root / "icm" / "shared" / "prompt"
    prompts.mkdir(parents=True)
    for block in icm.PROMPTS.glob("*.md"):
        (prompts / block.name).write_bytes(block.read_bytes())
    assert check_icm.manifest_problems(root) == []

    cash_flow = root / "caos" / "calculators" / "cash_flow.py"
    cash_flow.write_bytes(cash_flow.read_bytes() + b"\n# tampered, not regenerated\n")

    assert check_icm.manifest_problems(root) == [
        "icm/HOST_INTEGRITY_v1.json: does not match a freshly generated "
        "manifest; run scripts/host_manifest.py"
    ]


def test_a_prompt_block_that_is_not_what_the_host_manifest_records_refuses(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """F67: the instruction layer of every prompt is verified like the
    methodology it is delivered with."""
    blocks = tmp_path / "prompt"
    blocks.mkdir()
    for block in icm.PROMPTS.glob("*.md"):
        (blocks / block.name).write_bytes(block.read_bytes())
    (blocks / "instruction.md").write_bytes(
        (blocks / "instruction.md").read_bytes() + b"\nOne more line.\n"
    )
    (blocks / "unlisted.md").write_text("A block the manifest never named.\n")
    monkeypatch.setattr(icm, "PROMPTS", blocks)
    prompt_block.cache_clear()
    try:
        assert prompt_block("tagged") == (blocks / "tagged.md").read_text()
        for tampered in ("instruction", "unlisted"):
            with pytest.raises(Refusal, match=r"^AUTHORITY_BYTES_MISMATCH$"):
                prompt_block(tampered)
    finally:
        prompt_block.cache_clear()

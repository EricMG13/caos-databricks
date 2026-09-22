"""The ICM workspace is verified against what the runtime actually loads."""

from __future__ import annotations

from pathlib import Path

import check_icm
import icm_stages
import pytest

from caos import icm
from caos.icm import (
    BUNDLE,
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
    assert always[-1] == "cp0_final_check" and conditional == ()
    assert expected_blocks("CP-1") == (
        ("instruction", "tagged", "host_steps", "final_check"),
        ("forecast_extension",),
    )
    assert expected_blocks("CP-5")[1] == ()


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

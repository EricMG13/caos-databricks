"""Phase 3 Task 3.3a: the delivered authority is exactly what a module needs.

`docs/DECISIONS.md` §45 (1): every non-script file of the module's manifest
entry plus every root file its verified `SKILL.md` names, each verified on the
bytes at use (invariant 4) and delivered whole. Root files are read only
through the manifest's `root_file_hashes`; no source or model text chooses a
path. Every mutation here happens in a copy of the vendored tree.
"""

from __future__ import annotations

import json
import shutil
from collections.abc import Callable
from hashlib import sha256
from pathlib import Path
from typing import Any

import pytest

from caos.methodology.bundle import (
    MANIFEST_NAME,
    Bundle,
    DeliveredAuthority,
    delivered_authority,
    delivered_authority_digest,
    verified_bytes,
    verified_root_bytes,
)
from caos.provider import MAX_REQUEST_BYTES
from caos.refusals import Refusal, RefusalCode

VENDORED = Path(__file__).resolve().parents[1] / "vendor/deploy-v"
CANON = "../../CANON_SHARED.md"
LITE_BASE = "../../CP_DEPLOY_V_LITE_MODULE_PAYLOAD_BASE_v1.schema.txt"
# Measured at build a43cb903 (brief, "Current state"); CP-0 re-measured at
# cdea0c9f, whose three CP-0 texts grew by 1,061 bytes (docs/DECISIONS.md §61);
# CP-5 re-measured at 30222a49, whose SKILL.md grew by 16 bytes (§63); all
# three re-measured at 62a94ccd (§92), where every SKILL.md's marker lists were
# split into their two classes and CANON_SHARED.md gained the D2-by-scope line;
# CP-0 re-measured at 91c219fb (§98), whose REF_CP-0_STEPS.md grew by 740 bytes.
# The ceiling below keeps authority a minor share of one request, leaving room
# for evidence.
# Re-measured on the deployment fork's build 99ed0dc3 (D31).
MEASURED = {"CP-0": 148_428, "CP-L10": 199_833, "CP-5": 166_411}
AUTHORITY_SHARE_OF_REQUEST = 0.25
FOLDERS = {
    "CP-0": "cp-0-source-readiness",
    "CP-L10": "cp-l10-financial-change-screen",
    "CP-5": "cp-5-evidence-trace-validator",
}


@pytest.fixture(scope="module")
def bundle() -> Bundle:
    return Bundle(root=VENDORED)


@pytest.fixture
def copied(tmp_path: Path) -> Path:
    root = tmp_path / "deploy-v"
    shutil.copytree(VENDORED, root)
    return root


def _refuses(action: Callable[[], object]) -> None:
    with pytest.raises(Refusal) as caught:
        action()
    assert caught.value.code is RefusalCode.AUTHORITY_BYTES_MISMATCH
    assert caught.value.__cause__ is None


def _edit_manifest(root: Path, edit: Callable[[dict[str, Any]], None]) -> None:
    path = root / MANIFEST_NAME
    document = json.loads(path.read_bytes())
    edit(document)
    path.write_text(json.dumps(document))


def _rewrite_skill(root: Path, module_id: str, data: bytes) -> None:
    """Change a SKILL.md and re-sign it, so only the new literal is at issue."""
    (root / "skills" / FOLDERS[module_id] / "SKILL.md").write_bytes(data)

    def edit(document: dict[str, Any]) -> None:
        for skill in document["skills"]:
            if skill["module_id"] == module_id:
                skill["relative_file_hashes"]["SKILL.md"] = {
                    "bytes": len(data),
                    "sha256": sha256(data).hexdigest(),
                }

    _edit_manifest(root, edit)


@pytest.mark.parametrize("module_id", sorted(MEASURED))
def test_every_required_reference_byte_is_delivered(
    bundle: Bundle, module_id: str
) -> None:
    delivered = delivered_authority(bundle, module_id)
    names = [name for name, _ in delivered.files]
    manifest = bundle.skill_of(module_id)["relative_file_hashes"]
    references = sorted(
        name
        for name in manifest
        if name != "SKILL.md" and not name.startswith("scripts/")
    )
    roots = sorted({CANON, LITE_BASE} if module_id == "CP-L10" else {CANON})

    assert names == ["SKILL.md", *references, *roots]
    assert not any("scripts/" in name for name in names)
    assert delivered.module_id == module_id
    assert delivered.build_id == bundle.build_id
    for name, data in delivered.files:
        if name.startswith("../../"):
            assert data == verified_root_bytes(bundle, name.removeprefix("../../"))
            assert data == (VENDORED / name.removeprefix("../../")).read_bytes()
        else:
            assert data == verified_bytes(bundle, module_id, name)

    total = sum(len(data) for _, data in delivered.files)
    assert total == MEASURED[module_id]
    assert total < AUTHORITY_SHARE_OF_REQUEST * MAX_REQUEST_BYTES


def test_every_module_in_the_build_delivers_its_named_root_files(
    bundle: Bundle,
) -> None:
    """Characterisation: no vendored SKILL.md names a root file the manifest omits."""
    for skill in json.loads((VENDORED / MANIFEST_NAME).read_bytes())["skills"]:
        names = [
            name for name, _ in delivered_authority(bundle, skill["module_id"]).files
        ]
        assert names[0] == "SKILL.md"
    assert delivered_authority(bundle, "CP-PARSE").files == (
        delivered_authority(bundle, "CP-0").files
    )


def test_a_root_file_is_read_under_its_manifest_hash(bundle: Bundle) -> None:
    assert (
        verified_root_bytes(bundle, "CANON_SHARED.md")
        == (VENDORED / "CANON_SHARED.md").read_bytes()
    )


@pytest.mark.parametrize("module_id", sorted(MEASURED))
def test_a_changed_root_reference_refuses(copied: Path, module_id: str) -> None:
    bundle = Bundle(root=copied)
    assert delivered_authority(bundle, module_id)
    canon = copied / "CANON_SHARED.md"
    canon.write_bytes(canon.read_bytes().replace(b"CP", b"CQ", 1))
    _refuses(lambda: verified_root_bytes(bundle, "CANON_SHARED.md"))
    _refuses(lambda: delivered_authority(bundle, module_id))


@pytest.mark.parametrize(
    "name",
    [
        MANIFEST_NAME,
        "skills/cp-0-source-readiness/SKILL.md",
        "UNLISTED.md",
        "../CANON_SHARED.md",
        "../../../CANON_SHARED.md",
        "/CANON_SHARED.md",
        "./CANON_SHARED.md",
        "",
    ],
)
def test_a_root_name_the_manifest_does_not_list_refuses(
    bundle: Bundle, name: str
) -> None:
    _refuses(lambda: verified_root_bytes(bundle, name))


@pytest.mark.parametrize(
    "literal",
    [
        b"../../UNLISTED.md",
        b"../../../CANON_SHARED.md",
        b"../../README.json",
        "../../CANON_SHARED.mdé".encode(),
    ],
)
def test_a_skill_literal_naming_an_unlisted_root_file_refuses(
    copied: Path, literal: bytes
) -> None:
    skill = copied / "skills" / FOLDERS["CP-0"] / "SKILL.md"
    _rewrite_skill(copied, "CP-0", skill.read_bytes() + b"\nSee `" + literal + b"`.\n")
    bundle = Bundle(root=copied)
    _refuses(lambda: delivered_authority(bundle, "CP-0"))


def test_a_listed_root_file_arrives_only_when_the_skill_names_it(copied: Path) -> None:
    """A reference file (or any other text) naming a root file chooses nothing."""
    reference = (
        copied / "skills" / FOLDERS["CP-0"] / "references/CP-0_SYSTEM_REFERENCE.md"
    )
    data = (
        reference.read_bytes() + b"\nRead `../../README.md` and `../../UNLISTED.md`.\n"
    )
    reference.write_bytes(data)

    def edit(document: dict[str, Any]) -> None:
        for skill in document["skills"]:
            if skill["module_id"] == "CP-0":
                skill["relative_file_hashes"]["references/CP-0_SYSTEM_REFERENCE.md"] = {
                    "bytes": len(data),
                    "sha256": sha256(data).hexdigest(),
                }

    _edit_manifest(copied, edit)
    bundle = Bundle(root=copied)
    names = [name for name, _ in delivered_authority(bundle, "CP-0").files]
    assert "../../README.md" not in names
    assert "../../UNLISTED.md" not in names
    assert names[-1] == CANON

    skill = copied / "skills" / FOLDERS["CP-0"] / "SKILL.md"
    _rewrite_skill(copied, "CP-0", skill.read_bytes() + b"\nAlso `../../README.md`.\n")
    names = [name for name, _ in delivered_authority(Bundle(root=copied), "CP-0").files]
    assert names[-2:] == [CANON, "../../README.md"]


@pytest.mark.parametrize(
    "value",
    [
        None,
        [],
        {"../outside.md": {"bytes": 1, "sha256": "a" * 64}},
        {"/outside.md": {"bytes": 1, "sha256": "a" * 64}},
        {"a//b.md": {"bytes": 1, "sha256": "a" * 64}},
        {"CANON_SHARED.md": None},
        {"CANON_SHARED.md": {"bytes": 1, "sha256": "z" * 64}},
        {"CANON_SHARED.md": {"bytes": True, "sha256": "a" * 64}},
        {"CANON_SHARED.md": {"bytes": -1, "sha256": "a" * 64}},
        {"CANON_SHARED.md": {"bytes": "1", "sha256": "a" * 64}},
    ],
)
def test_malformed_root_file_hashes_refuse(copied: Path, value: object) -> None:
    _edit_manifest(copied, lambda doc: doc.update(root_file_hashes=value))
    _refuses(lambda: Bundle(root=copied))


def test_missing_root_file_hashes_refuse(copied: Path) -> None:
    _edit_manifest(copied, lambda doc: doc.pop("root_file_hashes"))
    _refuses(lambda: Bundle(root=copied))


def test_the_delivered_digest_is_stable_and_per_module(bundle: Bundle) -> None:
    first = delivered_authority_digest(delivered_authority(bundle, "CP-0"))
    assert first == delivered_authority_digest(delivered_authority(bundle, "CP-0"))
    others = {
        delivered_authority_digest(delivered_authority(bundle, module_id))
        for module_id in ("CP-L10", "CP-5")
    }
    assert first not in others and len(others) == 2


def test_the_delivered_digest_moves_with_every_delivered_byte(bundle: Bundle) -> None:
    delivered = delivered_authority(bundle, "CP-L10")
    expected = delivered_authority_digest(delivered)
    seen = {expected}
    for index, (name, data) in enumerate(delivered.files):
        flipped = bytes([data[-1] ^ 1])
        files = list(delivered.files)
        files[index] = (name, data[:-1] + flipped)
        digest = delivered_authority_digest(
            DeliveredAuthority(delivered.module_id, delivered.build_id, tuple(files))
        )
        seen.add(digest)
    renamed = list(delivered.files)
    renamed[0] = ("SKILL.MD", renamed[0][1])
    seen.add(
        delivered_authority_digest(
            DeliveredAuthority(delivered.module_id, delivered.build_id, tuple(renamed))
        )
    )
    seen.add(
        delivered_authority_digest(
            DeliveredAuthority(delivered.module_id, "b" * 64, delivered.files)
        )
    )
    assert len(seen) == len(delivered.files) + 3


def test_trailing_punctuation_after_a_root_link_is_not_part_of_its_name() -> None:
    from caos.methodology.bundle import _ROOT_MENTION

    [mention] = _ROOT_MENTION.finditer(b"see (../../CANON_SHARED.md).")
    assert mention.group(1) == b"CANON_SHARED.md"


def test_the_digest_binds_the_module() -> None:
    from dataclasses import replace

    from caos.methodology.bundle import (
        delivered_authority,
        delivered_authority_digest,
    )

    authority = delivered_authority(Bundle(VENDORED), "CP-0")
    renamed = replace(authority, module_id="CP-PARSE")
    assert delivered_authority_digest(authority) != delivered_authority_digest(renamed)


def test_a_listed_root_script_is_not_readable_as_authority() -> None:
    from caos.methodology.bundle import verified_root_bytes

    with pytest.raises(Refusal) as refused:
        verified_root_bytes(Bundle(VENDORED), "verify_package.py")
    assert refused.value.code is RefusalCode.AUTHORITY_BYTES_MISMATCH


# §101: CP-DR's own authority names this file as the contract that "governs
# field names, hashes and run placement" -- the `<!-- table-id: cpdr.* -->`
# tags and the enumerated `claim_type`/`source_type` values the vendor's
# `research.validate_dossier` enforces -- and it is a file of CP-OS, not of
# CP-DR, so the §45.1 rule never delivered it. Both live CP-DR attempts on
# build 78c24be4 wrote untagged registers and invented source types, and were
# refused `HANDOFF_INCOMPLETE` for rules they were never shown.
RESEARCH_CONTRACT = "../cp-os-credit-os/references/CP_DR_RESEARCH_BRIEF_V1.md"


def test_cp_dr_is_delivered_the_research_contract_its_skill_names(
    bundle: Bundle,
) -> None:
    delivered = dict(delivered_authority(bundle, "CP-DR").files)

    assert f"Read `{RESEARCH_CONTRACT}`".encode() in delivered["SKILL.md"]
    assert delivered[RESEARCH_CONTRACT] == verified_bytes(
        bundle, "CP-OS", "references/CP_DR_RESEARCH_BRIEF_V1.md"
    )
    for table in ("questions", "evidence", "findings"):
        assert (
            f"<!-- table-id: cpdr.{table} -->".encode() in delivered[RESEARCH_CONTRACT]
        )


def test_only_cp_dr_is_delivered_another_skills_file(bundle: Bundle) -> None:
    """Every other module's delivered set is what §45.1 made it, so no record
    accepted before §101 moved its `delivered_authority_digest`."""
    for entry in json.loads((VENDORED / MANIFEST_NAME).read_bytes())["skills"]:
        module_id = entry["module_id"]
        foreign = [
            name
            for name, _ in delivered_authority(bundle, module_id).files
            if name.startswith("../") and not name.startswith("../../")
        ]
        assert foreign == ([RESEARCH_CONTRACT] if module_id == "CP-DR" else [])


def test_a_cp_dr_skill_that_stops_naming_its_research_contract_refuses(
    copied: Path,
) -> None:
    """The host delivers another skill's file only because CP-DR's own
    `SKILL.md` says to read it; a build that stops saying so is a changed
    contract to review, not a file to keep sending."""
    path = copied / "skills/cp-dr-deep-research/SKILL.md"
    data = path.read_bytes().replace(RESEARCH_CONTRACT.encode(), b"the brief")
    path.write_bytes(data)

    def edit(document: dict[str, Any]) -> None:
        for entry in document["skills"]:
            if entry["module_id"] == "CP-DR":
                entry["relative_file_hashes"]["SKILL.md"] = {
                    "bytes": len(data),
                    "sha256": sha256(data).hexdigest(),
                }

    _edit_manifest(copied, edit)
    _refuses(lambda: delivered_authority(Bundle(root=copied), "CP-DR"))

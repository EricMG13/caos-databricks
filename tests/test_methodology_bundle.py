"""Phase 5: the bundle is authority, and it is checked on the bytes at use.

Invariant 4 (CLAUDE.md): integrity checked on the bytes at use, not at startup
only. A digest verified when the process booted says nothing about the file the
process is reading an hour later -- and the file is the methodology a credit
opinion rests on.

`docs/DECISIONS.md` §5 adds the one thing that must *not* happen here:
`assemble_authority` must not slice `SKILL.md` on section markers. The merged
upstream skill has dropped `## CP-PARSE runnable profile`, so slicing would
break CP-0 as well as CP-PARSE. CP-PARSE receives the whole CP-0 skill plus its
own reference files.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from caos.methodology.bundle import (
    Authority,
    Bundle,
    assemble_authority,
    authority_digest,
    module_display_names,
    verified_bytes,
)
from caos.refusals import Refusal, RefusalCode

VENDORED = Path(__file__).resolve().parents[1] / "vendor/deploy-v"


@pytest.fixture(scope="module")
def bundle() -> Bundle:
    return Bundle(root=VENDORED)


@pytest.fixture
def tampered(tmp_path: Path) -> Bundle:
    """A copy of the bundle with one byte of CP-1's skill changed.

    A copy rather than the vendored tree: the tree is authority we never edit
    (`docs/DECISIONS.md` §6), and a test that edited it would be the thing the
    rule forbids.
    """
    root = tmp_path / "deploy-v"
    shutil.copytree(VENDORED, root)
    skill = root / "skills/cp-1-canonical-data-foundation/SKILL.md"
    skill.write_bytes(skill.read_bytes().replace(b"CP-1", b"CP-l", 1))
    return Bundle(root=root)


def test_the_build_id_is_the_one_the_repository_pinned(bundle: Bundle) -> None:
    """`docs/DECISIONS.md` §61 pins the build, having moved the §13 pin. A run
    pinned to one build never executes under another (invariant 4)."""
    assert bundle.build_id.startswith("820dfc7c")


def test_authority_is_the_whole_skill_and_its_references(bundle: Bundle) -> None:
    authority = assemble_authority(bundle, "CP-1")

    assert authority.module_id == "CP-1"
    # The skill opens with its own frontmatter, so this also says the right
    # module's authority came back rather than merely some file.
    assert authority.files["SKILL.md"].startswith(b"---\nname: cp-1-")
    assert len(authority.files) == 10
    assert any(name.startswith("references/") for name in authority.files)


def test_authority_records_the_build_it_was_read_under(bundle: Bundle) -> None:
    """An `Authority` is not just bytes: it is bytes plus which build they came
    from. A run pinned to one build never executes under another (invariant 4),
    and that check needs the build to travel with the files."""
    authority = assemble_authority(bundle, "CP-1")

    assert isinstance(authority, Authority)
    assert authority.build_id == bundle.build_id


def test_assemble_authority_does_not_slice_the_skill(bundle: Bundle) -> None:
    """§5's consequence, stated as a test. The whole file or nothing.

    Slicing on section markers is what broke CP-0 and CP-PARSE together when the
    merged upstream skill dropped a heading, so the assembled bytes must equal
    the file's bytes exactly.
    """
    authority = assemble_authority(bundle, "CP-1")
    on_disk = (VENDORED / "skills/cp-1-canonical-data-foundation/SKILL.md").read_bytes()

    assert authority.files["SKILL.md"] == on_disk


def test_authority_bytes_mismatch_refuses(tampered: Bundle) -> None:
    """The Phase 5 exit test. One byte changed under the manifest, and the
    module refuses to assemble rather than running on authority nobody signed."""
    with pytest.raises(Refusal) as caught:
        assemble_authority(tampered, "CP-1")

    assert caught.value.code is RefusalCode.AUTHORITY_BYTES_MISMATCH


def test_the_mismatch_refusal_carries_no_path_or_content(tampered: Bundle) -> None:
    with pytest.raises(Refusal) as caught:
        assemble_authority(tampered, "CP-1")

    leaked = str(caught.value) + repr(caught.value) + repr(caught.value.__cause__)
    assert "cp-1-canonical-data-foundation" not in leaked
    assert "SKILL" not in leaked


def test_bytes_are_checked_at_use_not_at_startup(tmp_path: Path) -> None:
    """Invariant 4's actual claim. A bundle that verified when it was opened is
    not a bundle that is still what it was when a module reads it."""
    root = tmp_path / "deploy-v"
    shutil.copytree(VENDORED, root)
    bundle = Bundle(root=root)
    assert assemble_authority(bundle, "CP-1").files["SKILL.md"]

    skill = root / "skills/cp-1-canonical-data-foundation/SKILL.md"
    skill.write_bytes(skill.read_bytes() + b"\n<!-- changed after the first read -->")

    with pytest.raises(Refusal) as caught:
        assemble_authority(bundle, "CP-1")
    assert caught.value.code is RefusalCode.AUTHORITY_BYTES_MISMATCH


def test_a_module_the_bundle_does_not_carry_is_refused(bundle: Bundle) -> None:
    with pytest.raises(Refusal) as caught:
        assemble_authority(bundle, "CP-NOT-A-MODULE")

    assert caught.value.code is RefusalCode.AUTHORITY_MODULE_UNKNOWN


def test_a_missing_file_is_a_mismatch_not_a_silent_gap(tmp_path: Path) -> None:
    """A file the manifest names and the tree does not have is authority that
    is not there -- which must refuse, not assemble a shorter set."""
    root = tmp_path / "deploy-v"
    shutil.copytree(VENDORED, root)
    (root / "skills/cp-1-canonical-data-foundation/references/CP-1_RUNBOOK.md").unlink()

    with pytest.raises(Refusal) as caught:
        assemble_authority(Bundle(root=root), "CP-1")

    assert caught.value.code is RefusalCode.AUTHORITY_BYTES_MISMATCH


def test_the_authority_digest_is_stable_and_per_module(bundle: Bundle) -> None:
    """A run records what authority it executed under. Two modules of one build
    are different authority, and the same module twice is the same."""
    first = authority_digest(assemble_authority(bundle, "CP-1"))
    again = authority_digest(assemble_authority(bundle, "CP-1"))
    other = authority_digest(assemble_authority(bundle, "CP-0"))

    assert first == again
    assert first != other
    assert len(first) == 64


def test_verified_bytes_reads_one_file_under_its_hash(bundle: Bundle) -> None:
    data = verified_bytes(bundle, "CP-1", "SKILL.md")

    assert data.startswith(b"---\nname: cp-1-")


def test_a_path_outside_the_module_is_refused(bundle: Bundle) -> None:
    """The manifest names every file a module may read. Anything else is not
    authority, and a traversal is not a file the manifest could ever name."""
    for name in ("../../../etc/passwd", "references/../../CANON_SHARED.md"):
        with pytest.raises(Refusal) as caught:
            verified_bytes(bundle, "CP-1", name)
        assert caught.value.code is RefusalCode.AUTHORITY_BYTES_MISMATCH


def test_cp_parse_receives_the_whole_cp0_skill(bundle: Bundle) -> None:
    """`docs/DECISIONS.md` §5: the host keeps CP-PARSE as a separate stage-0
    node even though upstream merged it into CP-0. It owns the
    `document_parse_manifest` over the host's own already-extracted blocks,
    which is host territory.

    The carve-out is the host's one declaration, and what CP-PARSE gets is the
    whole CP-0 skill -- not a slice of it, for the reason above.
    """
    cp_parse = assemble_authority(bundle, "CP-PARSE")
    cp0 = assemble_authority(bundle, "CP-0")

    assert cp_parse.files["SKILL.md"] == cp0.files["SKILL.md"]
    assert authority_digest(cp_parse) == authority_digest(cp0)


def test_the_manifest_itself_is_pinned(bundle: Bundle) -> None:
    """The one vendored file the manifest cannot cover is its own bytes, so
    `docs/DECISIONS.md` §61 records that digest separately."""
    recorded = json.loads(
        (VENDORED / "DEPLOY_V_INTEGRITY_v1.json").read_text(encoding="utf-8")
    )

    assert recorded["build_id"] == bundle.build_id
    assert bundle.manifest_sha256.startswith("a80849a8")


def test_module_display_names_reads_the_bundle_catalog(bundle: Bundle) -> None:
    """N61: a display name for every module the manifest carries, read from
    its own folder slug -- prose, not a slug -- plus the two modules the
    manifest itself does not carry a slug for: CP-PARSE, which shares CP-0's
    name under the host's own carve-out (§5), and CP-CF, the host's model
    extension, which keeps its host-declared name."""
    names = module_display_names(bundle)

    assert names["CP-1"] == "Canonical data foundation"
    assert names["CP-2G"] == "Forward credit model"
    assert names["CP-PARSE"] == names["CP-0"] == "Source readiness"
    assert names["CP-CF"] == "Cash-flow forecast"
    # Every manifest module plus the two carve-outs, never a blank name.
    assert set(names) == set(bundle.physical_modules()) | {"CP-PARSE", "CP-CF"}
    assert all(names.values())

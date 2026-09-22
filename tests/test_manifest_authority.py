"""One immutable manifest snapshot governs identity and every authority read."""

from __future__ import annotations

import json
from collections.abc import Callable
from hashlib import sha256
from io import BytesIO
from os import mkfifo
from pathlib import Path
from typing import Any, BinaryIO, Literal

import pytest

from caos.methodology.bundle import (
    MANIFEST_NAME,
    Bundle,
    assemble_authority,
    authority_digest,
    verified_bytes,
)
from caos.refusals import Refusal, RefusalCode

LIMIT = 128 * 1024
BUILD = "a" * 64


@pytest.fixture
def manifest(tmp_path: Path) -> Path:
    folder = tmp_path / "skills/cp-1"
    folder.mkdir(parents=True)
    files = {"SKILL.md": b"whole skill\n", "references/required.md": b"reference\n"}
    hashes = {}
    for name, data in files.items():
        path = folder / name
        path.parent.mkdir(exist_ok=True)
        path.write_bytes(data)
        hashes[name] = {"bytes": len(data), "sha256": sha256(data).hexdigest()}
    document = {
        "authority": "DEPLOY_V_INTEGRITY_v1",
        "schema_version": "1.0",
        "build_id": BUILD,
        "root_file_hashes": {},
        "skills": [
            {"module_id": "CP-1", "folder_slug": "cp-1", "relative_file_hashes": hashes}
        ],
    }
    path = tmp_path / MANIFEST_NAME
    path.write_text(json.dumps(document))
    return path


def _change(manifest: Path, edit: Callable[[dict[str, Any]], None]) -> None:
    document = json.loads(manifest.read_bytes())
    edit(document)
    manifest.write_text(json.dumps(document))


def _refuses(action: Callable[[], object]) -> None:
    with pytest.raises(Refusal) as caught:
        action()
    assert caught.value.code is RefusalCode.AUTHORITY_BYTES_MISMATCH
    assert str(caught.value) == "AUTHORITY_BYTES_MISMATCH"
    assert caught.value.__cause__ is None


def test_bundle_binds_before_first_property_access(manifest: Path) -> None:
    bundle = Bundle(manifest.parent)
    manifest.write_bytes(manifest.read_bytes() + b" ")
    _refuses(lambda: bundle.build_id)


@pytest.mark.parametrize(
    "first,second", [("build_id", "manifest_sha256"), ("manifest_sha256", "build_id")]
)
def test_identity_reads_never_mix_manifest_versions(
    manifest: Path, first: str, second: str
) -> None:
    bundle = Bundle(manifest.parent)
    assert getattr(bundle, first)
    _change(manifest, lambda doc: doc.update(build_id="b" * 64))
    _refuses(lambda: getattr(bundle, second))


@pytest.mark.parametrize(
    "use",
    ["build_id", "manifest_sha256", "skill_of", "verified_bytes", "assemble_authority"],
)
@pytest.mark.parametrize("damage", ["changed", "malformed", "missing", "oversized"])
def test_same_bundle_rechecks_every_authority_use(
    manifest: Path, use: str, damage: str
) -> None:
    bundle = Bundle(manifest.parent)
    assert assemble_authority(bundle, "CP-1").build_id == BUILD
    assert bundle.manifest_sha256 == sha256(manifest.read_bytes()).hexdigest()
    if damage == "missing":
        manifest.unlink()
    else:
        data = {
            "changed": manifest.read_bytes() + b" ",
            "malformed": b"{",
            "oversized": b" " * (LIMIT + 1),
        }[damage]
        manifest.write_bytes(data)
    actions: dict[str, Callable[[], object]] = {
        "build_id": lambda: bundle.build_id,
        "manifest_sha256": lambda: bundle.manifest_sha256,
        "skill_of": lambda: bundle.skill_of("CP-1"),
        "verified_bytes": lambda: verified_bytes(bundle, "CP-1", "SKILL.md"),
        "assemble_authority": lambda: assemble_authority(bundle, "CP-1"),
    }
    _refuses(actions[use])


@pytest.mark.parametrize(
    "data",
    [
        b"",
        b"{",
        b"[]",
        b"null",
        b"\xff",
        pytest.param(b"[" * 2000 + b"]" * 2000, id="invalid top-level array"),
    ],
)
def test_unparseable_manifest_has_a_sanitized_refusal(
    manifest: Path, data: bytes
) -> None:
    manifest.write_bytes(data)
    _refuses(lambda: assemble_authority(Bundle(manifest.parent), "CP-1"))


@pytest.mark.parametrize(
    "field,value",
    [
        ("authority", None),
        ("authority", "other"),
        ("schema_version", 1),
        ("build_id", None),
        ("build_id", 1),
        ("build_id", ""),
        ("build_id", "z" * 64),
        ("build_id", "a" * 63),
        ("skills", None),
        ("skills", []),
        ("skills", {}),
        ("skills", [None]),
    ],
)
def test_malformed_manifest_identity_refuses(
    manifest: Path, field: str, value: object
) -> None:
    _change(manifest, lambda doc: doc.update({field: value}))
    _refuses(lambda: assemble_authority(Bundle(manifest.parent), "CP-1"))


@pytest.mark.parametrize("field", ["authority", "schema_version", "build_id", "skills"])
def test_missing_manifest_identity_refuses(manifest: Path, field: str) -> None:
    _change(manifest, lambda doc: doc.pop(field))
    _refuses(lambda: assemble_authority(Bundle(manifest.parent), "CP-1"))


@pytest.mark.parametrize(
    "field,value",
    [
        ("module_id", None),
        ("module_id", ""),
        ("module_id", " CP-1"),
        ("folder_slug", None),
        ("folder_slug", ""),
        ("relative_file_hashes", None),
        ("relative_file_hashes", []),
        ("relative_file_hashes", {}),
        ("relative_file_hashes", {"other": {}}),
        ("relative_file_hashes", {"SKILL.md": None}),
        ("relative_file_hashes", {"SKILL.md": {"sha256": 1, "bytes": 1}}),
        ("relative_file_hashes", {"SKILL.md": {"sha256": "z" * 64, "bytes": 1}}),
        ("relative_file_hashes", {"SKILL.md": {"sha256": "a" * 64, "bytes": True}}),
        ("relative_file_hashes", {"SKILL.md": {"sha256": "a" * 64, "bytes": -1}}),
    ],
)
def test_malformed_module_metadata_refuses(
    manifest: Path, field: str, value: object
) -> None:
    _change(manifest, lambda doc: doc["skills"][0].update({field: value}))
    _refuses(lambda: assemble_authority(Bundle(manifest.parent), "CP-1"))


def test_duplicate_module_ids_refuse(manifest: Path) -> None:
    _change(manifest, lambda doc: doc["skills"].append(doc["skills"][0]))
    _refuses(lambda: assemble_authority(Bundle(manifest.parent), "CP-1"))


@pytest.mark.parametrize("field", ["module_id", "folder_slug", "relative_file_hashes"])
def test_missing_module_metadata_refuses(manifest: Path, field: str) -> None:
    _change(manifest, lambda doc: doc["skills"][0].pop(field))
    _refuses(lambda: Bundle(manifest.parent))


def test_empty_skill_is_not_authority(manifest: Path) -> None:
    (manifest.parent / "skills/cp-1/SKILL.md").write_bytes(b"")
    _change(
        manifest,
        lambda doc: doc["skills"][0]["relative_file_hashes"].update(
            {"SKILL.md": {"bytes": 0, "sha256": sha256(b"").hexdigest()}}
        ),
    )
    _refuses(lambda: assemble_authority(Bundle(manifest.parent), "CP-1"))


def test_oversized_manifest_is_not_read_unbounded_or_parsed(
    manifest: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    reads: list[int | None] = []

    class BoundedRead(BytesIO):
        def read(self, size: int | None = -1) -> bytes:
            reads.append(size)
            assert size == LIMIT + 1
            return super().read(size)

    def stream(self: Path, mode: str) -> BoundedRead:
        return BoundedRead(b" " * (LIMIT + 2))

    def parse(raw: bytes, **kwargs: object) -> None:
        pytest.fail("oversized manifest reached parsing")

    monkeypatch.setattr(Path, "open", stream)
    monkeypatch.setattr(json, "loads", parse)
    _refuses(lambda: Bundle(manifest.parent))
    assert reads == [LIMIT + 1]


@pytest.mark.parametrize("extra", ['"build_id": "b",', '"unused": NaN,'])
def test_ambiguous_or_non_json_metadata_refuses(manifest: Path, extra: str) -> None:
    manifest.write_bytes(b"{" + extra.encode() + manifest.read_bytes()[1:])
    _refuses(lambda: assemble_authority(Bundle(manifest.parent), "CP-1"))


@pytest.mark.parametrize("length", [LIMIT - 1, LIMIT, LIMIT + 1])
def test_manifest_byte_limit_is_exact(manifest: Path, length: int) -> None:
    data = manifest.read_bytes()
    manifest.write_bytes(data + b" " * (length - len(data)))
    if length > LIMIT:
        _refuses(lambda: assemble_authority(Bundle(manifest.parent), "CP-1"))
    else:
        bundle = Bundle(manifest.parent)
        assert bundle.manifest_sha256 == sha256(manifest.read_bytes()).hexdigest()
        assert assemble_authority(bundle, "CP-1").build_id == BUILD


def test_manifest_entry_mutation_does_not_change_authority(manifest: Path) -> None:
    bundle = Bundle(manifest.parent)
    expected = authority_digest(assemble_authority(bundle, "CP-1"))
    skill = bundle.skill_of("CP-1")
    skill["relative_file_hashes"].clear()
    skill["folder_slug"] = "other"
    assert authority_digest(assemble_authority(bundle, "CP-1")) == expected


@pytest.mark.parametrize("field", ["folder_slug", "relative_file_hashes"])
@pytest.mark.parametrize(
    "name",
    ["../outside", "/outside", "a/../../outside", "a//b", "./a", "a\\b", "a\x00b"],
)
def test_manifest_paths_must_be_contained_names(
    manifest: Path, field: str, name: str
) -> None:
    def edit(doc: dict[str, Any]) -> None:
        skill = doc["skills"][0]
        if field == "folder_slug":
            skill[field] = name
        else:
            skill[field][name] = skill[field]["SKILL.md"]

    _change(manifest, edit)
    _refuses(lambda: assemble_authority(Bundle(manifest.parent), "CP-1"))


@pytest.mark.parametrize("target", ["manifest", "skills", "folder", "file"])
def test_symlink_escape_is_refused_before_outside_bytes_are_read(
    manifest: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, target: str
) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    root = tmp_path / "bundle"
    # Move only this fixture's files into a narrower root; outside is a sibling.
    root.mkdir()
    manifest.rename(root / MANIFEST_NAME)
    (tmp_path / "skills").rename(root / "skills")
    path = {
        "manifest": root / MANIFEST_NAME,
        "skills": root / "skills",
        "folder": root / "skills/cp-1",
        "file": root / "skills/cp-1/SKILL.md",
    }[target]
    saved = outside / path.name
    path.rename(saved)
    path.symlink_to(saved, target_is_directory=target in {"skills", "folder"})
    original = Path.open

    def checked_open(self: Path, mode: Literal["rb"] = "rb") -> BinaryIO:
        assert not self.resolve().is_relative_to(outside), "outside read attempted"
        return original(self, mode)

    monkeypatch.setattr(Path, "open", checked_open)
    _refuses(lambda: assemble_authority(Bundle(root), "CP-1"))


def _replace_with_guarded_fifo(path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path.unlink()
    mkfifo(path)
    original = Path.open

    def checked_open(
        self: Path, mode: Literal["rb"] = "rb", buffering: int = -1
    ) -> BinaryIO:
        if self == path:
            pytest.fail("authority FIFO was opened")
        return original(self, mode, buffering=buffering)

    monkeypatch.setattr(Path, "open", checked_open)


def test_manifest_fifo_refuses_before_open(
    manifest: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _replace_with_guarded_fifo(manifest, monkeypatch)
    _refuses(lambda: Bundle(manifest.parent))


def test_module_fifo_refuses_before_open(
    manifest: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bundle = Bundle(manifest.parent)
    _replace_with_guarded_fifo(manifest.parent / "skills/cp-1/SKILL.md", monkeypatch)
    _refuses(lambda: assemble_authority(bundle, "CP-1"))


def test_mutation_during_the_last_file_read_refuses_assembly(
    manifest: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bundle = Bundle(manifest.parent)
    original = Path.open
    raw = Path.read_bytes

    def mutate(self: Path, *args: object, **kwargs: object) -> object:
        stream = original(self, *args, **kwargs)  # type: ignore[call-overload]
        if self.name == "required.md":
            manifest.write_bytes(raw(manifest) + b" ")
        return stream

    monkeypatch.setattr(Path, "open", mutate)
    _refuses(lambda: assemble_authority(bundle, "CP-1"))

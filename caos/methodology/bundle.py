"""The methodology bundle: authority, verified on the bytes at use.

Invariant 4. The bundle is the methodology authority, it is read-only at runtime,
and its integrity is checked *at use* rather than at startup only -- because a
digest verified when the process booted says nothing about the file the process
reads an hour later, and that file is the methodology a credit opinion rests on.

Two rules from `docs/DECISIONS.md` shape what is here.

*§5, the carve-out.* Upstream merged CP-PARSE into CP-0. The host keeps them as
separate stage-0 nodes because CP-PARSE owns the `document_parse_manifest` over
the host's own already-extracted blocks, which is host territory. `_CARVE_OUTS`
is the host's one declaration, and CP-PARSE receives the whole CP-0 skill.

*§5's consequence, which is easy to miss.* `assemble_authority` must not slice
`SKILL.md` on section markers. The merged skill has dropped
`## CP-PARSE runnable profile`, so a slicer looking for it would break CP-0 as
well as CP-PARSE. The whole file, or a refusal.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import Path, PurePosixPath
from typing import Any, NoReturn, cast

from caos.boundary_text import BoundaryText
from caos.graph.route import MODEL_MODULE
from caos.methodology.host import host_skill, verified_host_bytes
from caos.refusals import Refusal, RefusalCode

MANIFEST_NAME = "DEPLOY_V_INTEGRITY_v1.json"
SKILLS_DIR = "skills"
# §35: pinned manifest is 68,657 bytes; read at most this ceiling plus one.
MANIFEST_BYTE_LIMIT = 128 * 1024

# The host's one declaration (`docs/DECISIONS.md` §5). CP-PARSE is not a folder
# in this build; it is CP-0's authority under its own route node.
_CARVE_OUTS = {"CP-PARSE": "CP-0"}


@dataclass(frozen=True, slots=True)
class Authority:
    """Everything one module may read, and the bytes it actually read."""

    module_id: str
    build_id: str
    files: dict[str, bytes]


@dataclass(frozen=True, slots=True)
class Bundle:
    """One immutable manifest snapshot, selected before the Bundle is shared.

    Only raw bytes are retained. Parsed entries are fresh copies, so a caller
    cannot mutate cached metadata into authority. No lazy initialization race.
    """

    root: Path
    _raw_manifest: bytes = field(init=False, repr=False)

    def __post_init__(self) -> None:
        raw = _read_manifest(self.root)
        _parse_manifest(raw)
        object.__setattr__(self, "_raw_manifest", raw)

    def verify_manifest(self) -> None:
        """Refuse a removed or changed manifest; never adopt a replacement."""
        if _read_manifest(self.root) != self._raw_manifest:
            raise Refusal(RefusalCode.AUTHORITY_BYTES_MISMATCH)

    def verify_pinned(self) -> None:
        """Refuse a manifest other than the one compiled into this build (F66):
        the manifest verifies every file, and this pin verifies the manifest,
        so a bundle swapped under a deployed process names nothing."""
        from caos.methodology.bundle_pin import BUNDLE_MANIFEST_SHA256

        if self.manifest_sha256 != BUNDLE_MANIFEST_SHA256:
            raise Refusal(RefusalCode.AUTHORITY_BYTES_MISMATCH)

    @property
    def _manifest(self) -> dict[str, Any]:
        self.verify_manifest()
        loaded: dict[str, Any] = json.loads(self._raw_manifest)
        return loaded

    @property
    def manifest_sha256(self) -> str:
        """The one vendored file the manifest cannot cover: its own bytes.

        `docs/DECISIONS.md` §13 records this digest separately, because the host
        does not mint an identity for something that ships with one.
        """
        self.verify_manifest()
        return sha256(self._raw_manifest).hexdigest()

    @property
    def build_id(self) -> str:
        """The build a run is pinned to. One build never executes as another."""
        return cast(str, self._manifest["build_id"])

    def physical_modules(self) -> dict[str, str]:
        """Every module the manifest carries, to its skill folder name."""
        return {
            str(skill["module_id"]): str(skill["folder_slug"])
            for skill in self._manifest["skills"]
        }

    def skill_of(self, module_id: str) -> dict[str, Any]:
        """The manifest entry for a module, following the host's carve-outs."""
        if module_id == MODEL_MODULE:
            self.verify_manifest()
            return host_skill()
        wanted = _CARVE_OUTS.get(module_id, module_id)
        for skill in self._manifest["skills"]:
            if skill["module_id"] == wanted:
                entry: dict[str, Any] = skill
                return entry
        raise Refusal(RefusalCode.AUTHORITY_MODULE_UNKNOWN)


def _authority_name(value: object) -> str:
    """A canonical relative POSIX name, never a filesystem instruction."""
    if not isinstance(value, str) or not value or value != value.strip():
        raise Refusal(RefusalCode.AUTHORITY_BYTES_MISMATCH)
    try:
        boundary = BoundaryText.of(value).value
    except Refusal:
        raise Refusal(RefusalCode.AUTHORITY_BYTES_MISMATCH) from None
    path = PurePosixPath(value)
    if (
        boundary != value
        or path.is_absolute()
        or ".." in path.parts
        or path.as_posix() != value
        or not path.parts
        or "\\" in value
    ):
        raise Refusal(RefusalCode.AUTHORITY_BYTES_MISMATCH)
    return value


def _contained_path(root: Path, name: str) -> Path:
    _authority_name(name)
    try:
        base = root.resolve(strict=True)
        path = (base / name).resolve(strict=True)
    except (OSError, ValueError):
        raise Refusal(RefusalCode.AUTHORITY_BYTES_MISMATCH) from None
    if not path.is_relative_to(base) or path == base:
        raise Refusal(RefusalCode.AUTHORITY_BYTES_MISMATCH)
    return path


def _read_manifest(root: Path) -> bytes:
    path = _contained_path(root, MANIFEST_NAME)
    if not path.is_file():
        raise Refusal(RefusalCode.AUTHORITY_BYTES_MISMATCH)
    try:
        with path.open("rb") as stream:
            raw = stream.read(MANIFEST_BYTE_LIMIT + 1)
    except OSError:
        raise Refusal(RefusalCode.AUTHORITY_BYTES_MISMATCH) from None
    if len(raw) > MANIFEST_BYTE_LIMIT:
        raise Refusal(RefusalCode.AUTHORITY_BYTES_MISMATCH)
    return raw


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result = dict(pairs)
    if len(result) != len(pairs):
        raise Refusal(RefusalCode.AUTHORITY_BYTES_MISMATCH)
    return result


def _invalid_constant(value: str) -> NoReturn:
    raise Refusal(RefusalCode.AUTHORITY_BYTES_MISMATCH)


def _is_digest(value: object) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[a-f0-9]{64}", value) is not None


def _validate_hashes(hashes: object, *, nonempty: str | None) -> None:
    """Contained names, digests and sizes; `nonempty` names a file that must exist."""
    if not isinstance(hashes, dict) or (
        nonempty is not None and nonempty not in hashes
    ):
        raise Refusal(RefusalCode.AUTHORITY_BYTES_MISMATCH)
    for name, entry in hashes.items():
        _authority_name(name)
        if not isinstance(entry, dict) or not _is_digest(entry.get("sha256")):
            raise Refusal(RefusalCode.AUTHORITY_BYTES_MISMATCH)
        size = entry.get("bytes")
        if type(size) is not int or size < 0 or (name == nonempty and size == 0):
            raise Refusal(RefusalCode.AUTHORITY_BYTES_MISMATCH)


def _validate_skill(skill: object) -> str:
    if not isinstance(skill, dict):
        raise Refusal(RefusalCode.AUTHORITY_BYTES_MISMATCH)
    module_id = _authority_name(skill.get("module_id"))
    folder = _authority_name(skill.get("folder_slug"))
    if "/" in module_id or "/" in folder:
        raise Refusal(RefusalCode.AUTHORITY_BYTES_MISMATCH)
    _validate_hashes(skill.get("relative_file_hashes"), nonempty="SKILL.md")
    return module_id


def _parse_manifest(raw: bytes) -> dict[str, Any]:
    try:
        loaded = json.loads(
            raw, object_pairs_hook=_unique_object, parse_constant=_invalid_constant
        )
    except (ValueError, RecursionError):
        raise Refusal(RefusalCode.AUTHORITY_BYTES_MISMATCH) from None
    if (
        not isinstance(loaded, dict)
        or loaded.get("authority") != "DEPLOY_V_INTEGRITY_v1"
        or loaded.get("schema_version") != "1.0"
        or not _is_digest(loaded.get("build_id"))
    ):
        raise Refusal(RefusalCode.AUTHORITY_BYTES_MISMATCH)
    _validate_hashes(loaded.get("root_file_hashes"), nonempty=None)
    skills = loaded.get("skills")
    if not isinstance(skills, list) or not skills:
        raise Refusal(RefusalCode.AUTHORITY_BYTES_MISMATCH)
    module_ids = [_validate_skill(skill) for skill in skills]
    if len(set(module_ids)) != len(module_ids):
        raise Refusal(RefusalCode.AUTHORITY_BYTES_MISMATCH)
    return loaded


def verified_bytes(bundle: Bundle, module_id: str, relative_path: str) -> bytes:
    """One file of one module's authority, proven against the manifest.

    Refuses `AUTHORITY_BYTES_MISMATCH` for a file whose bytes have moved, one the
    tree no longer has, and one the manifest never named. Both declared names
    and their resolved targets must remain contained. The code alone travels:
    a path or a body would put the vendor's filesystem into whatever logs it.
    """
    if module_id == MODEL_MODULE:
        bundle.verify_manifest()
        return verified_host_bytes(relative_path)
    skill = bundle.skill_of(module_id)
    expected = skill["relative_file_hashes"].get(relative_path)
    if not isinstance(expected, dict):
        raise Refusal(RefusalCode.AUTHORITY_BYTES_MISMATCH)

    skills = _contained_path(bundle.root, SKILLS_DIR)
    folder = _contained_path(skills, skill["folder_slug"])
    return _read_verified(bundle, _contained_path(folder, relative_path), expected)


def _read_verified(bundle: Bundle, path: Path, expected: dict[str, Any]) -> bytes:
    if not path.is_file():
        raise Refusal(RefusalCode.AUTHORITY_BYTES_MISMATCH)
    try:
        with path.open("rb") as stream:
            # Never more than the manifest allows plus one byte to prove excess.
            data = stream.read(expected["bytes"] + 1)
    except OSError:
        raise Refusal(RefusalCode.AUTHORITY_BYTES_MISMATCH) from None

    if len(data) != expected["bytes"] or sha256(data).hexdigest() != expected["sha256"]:
        raise Refusal(RefusalCode.AUTHORITY_BYTES_MISMATCH)
    bundle.verify_manifest()
    return data


def verified_root_bytes(bundle: Bundle, name: str) -> bytes:
    """One bundle-root file, proven against the manifest's `root_file_hashes`.

    The same contract as `verified_bytes`: a name the manifest does not list,
    one that escapes the root, and bytes that moved all refuse
    `AUTHORITY_BYTES_MISMATCH`, carrying no path or content.
    """
    expected = bundle._manifest["root_file_hashes"].get(_authority_name(name))
    # Methodology text only: the root also lists scripts and tests.
    if not isinstance(expected, dict) or _ROOT_LITERAL.fullmatch(name.encode()) is None:
        raise Refusal(RefusalCode.AUTHORITY_BYTES_MISMATCH)
    return _read_verified(bundle, _contained_path(bundle.root, name), expected)


# A root file a skill names, as it names it (`../../CANON_SHARED.md`). Every
# `../../` in a verified SKILL.md must be one of these, naming a listed root file.
# The name is matched directly, so trailing prose punctuation is not part of it.
# One-level-up links (`../cp-os-credit-os/scripts/prepare_invocation.py`) name
# scripts whose steps the host performs itself; they are not delivered (§45.1).
ROOT_PREFIX = "../../"
_ROOT_MENTION = re.compile(
    rb"\.\./\.\./([A-Za-z0-9_][A-Za-z0-9_.-]*\.(?:md|txt)(?![A-Za-z0-9_\x80-\xff-]))?"
)
_ROOT_LITERAL = re.compile(rb"[A-Za-z0-9_][A-Za-z0-9_.-]*\.(?:md|txt)")

# The one exception to "one-level-up links are not delivered" (§101): CP-DR's
# own authority says to read CP-OS's research contract, which "governs field
# names, hashes and run placement" -- the `table-id` tags and closed value sets
# the vendor's `research.validate_dossier` refuses a dossier for. It is a
# reference, not a script, so it is delivered to CP-DR under the literal
# CP-DR's `SKILL.md` names it by, verified under CP-OS's manifest entry, and
# only while that `SKILL.md` still names it. Declared per module rather than
# derived from every `../<skill>/` mention because every other SKILL.md names
# the same file for the consumer side of research, and delivering it there
# would move each module's prompt and delivered digest for a route none of
# them is on.
CROSS_SKILL_AUTHORITY: dict[str, tuple[tuple[str, str], ...]] = {
    "CP-DR": (("CP-OS", "references/CP_DR_RESEARCH_BRIEF_V1.md"),),
}


@dataclass(frozen=True, slots=True)
class DeliveredAuthority:
    """Exactly the verified files a module is handed, in delivery order.

    `SKILL.md` first, then the module's non-script manifest files by name, then
    any declared file of another skill its `SKILL.md` names (§101), then the
    root files `SKILL.md` names, each under its `../../` literal
    (`docs/DECISIONS.md` §45.1).
    """

    module_id: str
    build_id: str
    files: tuple[tuple[str, bytes], ...]


def _named_root_files(bundle: Bundle, skill: bytes) -> list[str]:
    listed = bundle._manifest["root_file_hashes"]
    names: set[str] = set()
    for mention in _ROOT_MENTION.finditer(skill):
        literal = mention.group(1)
        if literal is None or _ROOT_LITERAL.fullmatch(literal) is None:
            raise Refusal(RefusalCode.AUTHORITY_BYTES_MISMATCH)
        name = literal.decode("ascii")
        if name not in listed:
            raise Refusal(RefusalCode.AUTHORITY_BYTES_MISMATCH)
        names.add(name)
    return sorted(names)


def _cross_skill_files(
    bundle: Bundle, module_id: str, skill: bytes
) -> list[tuple[str, bytes]]:
    """The declared files of other skills this module's `SKILL.md` names, each
    under `../<folder>/<path>` and verified under its owner's manifest entry.
    `AUTHORITY_BYTES_MISMATCH` when the `SKILL.md` no longer names one."""
    files: list[tuple[str, bytes]] = []
    for owner, path in CROSS_SKILL_AUTHORITY.get(module_id, ()):
        name = f"../{bundle.skill_of(owner)['folder_slug']}/{path}"
        if f"`{name}`".encode() not in skill:
            raise Refusal(RefusalCode.AUTHORITY_BYTES_MISMATCH)
        files.append((name, verified_bytes(bundle, owner, path)))
    return files


def delivered_authority(bundle: Bundle, module_id: str) -> DeliveredAuthority:
    """The module's delivered set: names come only from the manifest and the
    verified `SKILL.md`, never from a caller, a source or a model."""
    build_id = bundle.build_id
    skill = verified_bytes(bundle, module_id, "SKILL.md")
    references = sorted(
        name
        for name in bundle.skill_of(module_id)["relative_file_hashes"]
        if name != "SKILL.md"
        and (module_id == MODEL_MODULE or not name.startswith("scripts/"))
    )
    files = [("SKILL.md", skill)]
    files += [(name, verified_bytes(bundle, module_id, name)) for name in references]
    files += _cross_skill_files(bundle, module_id, skill)
    files += [
        (ROOT_PREFIX + name, verified_root_bytes(bundle, name))
        for name in _named_root_files(bundle, skill)
    ]
    # Every read above re-verified the manifest bound when `build_id` was read.
    return DeliveredAuthority(
        module_id=module_id, build_id=build_id, files=tuple(files)
    )


def delivered_authority_digest(authority: DeliveredAuthority) -> str:
    """One value over the build and each delivered (name, sha256) in order.

    Length-prefixed, so no two different sets encode the same byte stream.
    """
    digest = sha256(b"caos-delivered-authority-v1\x00")
    parts = [authority.build_id.encode("utf-8"), authority.module_id.encode("utf-8")]
    for name, data in authority.files:
        parts += [name.encode("utf-8"), sha256(data).digest()]
    for part in parts:
        digest.update(len(part).to_bytes(8, "big"))
        digest.update(part)
    return digest.hexdigest()


def assemble_authority(bundle: Bundle, module_id: str) -> Authority:
    """Every file the manifest gives this module, each verified as it is read.

    Never a slice of `SKILL.md`. See this module's docstring: the section marker
    a slicer would look for is gone from the merged upstream skill, so slicing
    breaks CP-0 and CP-PARSE together.
    """
    skill = bundle.skill_of(module_id)
    names = sorted(skill["relative_file_hashes"])
    authority = Authority(
        module_id=module_id,
        build_id=bundle.build_id,
        files={name: verified_bytes(bundle, module_id, name) for name in names},
    )
    bundle.verify_manifest()
    return authority


def authority_digest(authority: Authority) -> str:
    """What authority a module executed under, in one value.

    Over the build and the verified bytes, so two modules of one build differ and
    one module across two builds differs. A run records this; a replay that
    produced a different one did not run the same methodology.
    """
    digest = sha256()
    digest.update(authority.build_id.encode("utf-8"))
    for name in sorted(authority.files):
        digest.update(name.encode("utf-8"))
        digest.update(sha256(authority.files[name]).digest())
    return digest.hexdigest()

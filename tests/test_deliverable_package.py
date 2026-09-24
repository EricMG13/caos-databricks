"""§55: bounded, portable consistency checking and exclusive package creation."""

from __future__ import annotations

import ast
import errno
import hashlib
import json
import os
import struct
import subprocess
import sys
import zipfile
import zlib
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from pathlib import Path
from threading import Barrier
from typing import Any
from uuid import uuid4

import pytest
from test_deliverable_render import PAYLOAD_DATA

from caos.deliverable.package import (
    Verification,
    build_package,
    verify_package,
    write_package,
)
from caos.deliverable.render import render
from caos.deliverable.verify_package import UNREADABLE

ROOT = Path(__file__).resolve().parents[1]
NAMES = {
    "payload.json",
    "receipt.json",
    "deliverable.html",
    "render.py",
    "verify_package.py",
}


# Every receipt this host writes names its case, run and revision (F60).
IDENTITY = {
    "case_id": "11111111-1111-4111-8111-111111111111",
    "run_id": "22222222-2222-4222-8222-222222222222",
    "revision_id": "33333333-3333-4333-8333-333333333333",
}
# The narrative as the save boundary writes it: paragraphs of spans. The render
# suite's payload keeps the historical string, which `render` still draws and
# the verifier refuses (DQ-15): no filed revision carries one.
PAYLOAD_DATA = {
    **PAYLOAD_DATA,
    **IDENTITY,
    "narrative": [[{"text": "Leverage is inside the covenant with limited headroom."}]],
}


def _package(**changes: bytes) -> bytes:
    payload = changes.get("payload", json.dumps(PAYLOAD_DATA).encode())
    receipt = json.dumps(
        {
            "payload_sha256": hashlib.sha256(payload).hexdigest(),
            "signed_by": "analyst",
            "frozen_by": "freezer",
            "filed_by": "filer",
            **IDENTITY,
        }
    ).encode()
    return build_package(
        payload,
        changes.get("receipt", receipt),
        changes.get("export", render(PAYLOAD_DATA)),
    )


def _members(data: bytes) -> dict[str, bytes]:
    with zipfile.ZipFile(BytesIO(data)) as archive:
        return {name: archive.read(name) for name in archive.namelist()}


def _archive(
    members: list[tuple[str, bytes]], compression: int = zipfile.ZIP_STORED
) -> bytes:
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=compression) as archive:
        for name, body in members:
            archive.writestr(name, body)
    return buffer.getvalue()


def _central(data: bytes, offset: int, value: int, fmt: str = "<I") -> bytes:
    changed = bytearray(data)
    start = changed.index(b"PK\x01\x02")
    struct.pack_into(fmt, changed, start + offset, value)
    return bytes(changed)


def _local(data: bytes, name: str, offset: int, value: int, fmt: str = "<I") -> bytes:
    """Like `_central`, but the named member's own local header (R24-17):
    signature(4) version(2) flags(2) method(2) time(2) date(2) crc(4)
    compressed_size(4) uncompressed_size(4) at offsets 14, 18, 22."""
    changed = bytearray(data)
    with zipfile.ZipFile(BytesIO(data)) as archive:
        start = archive.getinfo(name).header_offset
    struct.pack_into(fmt, changed, start + offset, value)
    return bytes(changed)


def test_a_package_verifies_with_a_fresh_interpreter_outside_the_repository(
    tmp_path: Path,
) -> None:
    data = _package()
    package = tmp_path / "package.zip"
    package.write_bytes(data)
    script = _members(data)["verify_package.py"]
    # Only the archive is copied; isolated stdin execution installs/imports nothing.
    result = subprocess.run(
        [sys.executable, "-I", "-S", "-", str(package)],
        input=script,
        cwd=tmp_path,
        env={},
        capture_output=True,
        timeout=10,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {"verified": True, "reason": None}
    assert list(tmp_path.iterdir()) == [package]


def test_render_and_verifier_import_only_the_standard_library() -> None:
    for filename in ("render.py", "verify_package.py"):
        tree = ast.parse((ROOT / "caos/deliverable" / filename).read_text())
        imports: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                assert node.level == 0 and node.module
                imports.add(node.module.split(".")[0])
        assert imports and imports <= sys.stdlib_module_names


def test_oversized_archive_or_member_is_refused_without_reading_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from caos.deliverable import verify_package as standalone

    good = _package()
    oversized_member = _central(good, 24, 65 * 1024 * 1024)
    reads: list[str] = []
    original = zipfile.ZipFile.open

    def observed(
        self: zipfile.ZipFile, name: object, *args: object, **kwargs: object
    ) -> object:
        reads.append(str(name))
        return original(self, name, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(zipfile.ZipFile, "open", observed)
    assert not standalone.verify(oversized_member)[0]
    assert reads == []
    monkeypatch.setattr(standalone, "MAX_ARCHIVE_BYTES", len(good) - 1)
    assert not standalone.verify(good)[0]
    assert reads == []


@pytest.mark.parametrize(
    "change",
    [
        "duplicate",
        "extra",
        "missing",
        "../payload.json",
        "/payload.json",
        "a\\payload.json",
        "folder/",
    ],
)
def test_duplicate_extra_missing_or_traversal_members_are_refused(change: str) -> None:
    members = list(_members(_package()).items())
    if change == "missing":
        members.pop()
    else:
        members.append(members[0] if change == "duplicate" else (change, b"unexpected"))
    if change == "duplicate":
        with pytest.warns(UserWarning, match="Duplicate name"):
            data = _archive(members)
    else:
        data = _archive(members)
    assert not verify_package(data).verified


@pytest.mark.parametrize(
    ("offset", "value"), [(8, 1), (10, 99), (10, zipfile.ZIP_BZIP2)]
)
def test_encrypted_or_unsupported_compression_is_refused(
    offset: int, value: int
) -> None:
    assert not verify_package(_central(_package(), offset, value, "<H")).verified


def test_a_highly_compressible_valid_package_round_trips(tmp_path: Path) -> None:
    payload_data = json.loads(json.dumps(PAYLOAD_DATA))
    payload_data["narrative"] = [[{"text": "Risk disclosure. " * 20_000}]]
    payload = json.dumps(payload_data).encode()
    receipt = json.dumps(
        {
            "payload_sha256": hashlib.sha256(payload).hexdigest(),
            "signed_by": "analyst",
            "frozen_by": "freezer",
            "filed_by": "filer",
            **IDENTITY,
        }
    ).encode()

    package = build_package(payload, receipt, render(payload_data))

    assert verify_package(package).verified
    with zipfile.ZipFile(BytesIO(package)) as archive:
        assert archive.getinfo("payload.json").compress_type == zipfile.ZIP_STORED
        assert archive.getinfo("deliverable.html").compress_type == zipfile.ZIP_STORED
        script = archive.read("verify_package.py")
    path = tmp_path / "repetitive-package.zip"
    path.write_bytes(package)
    result = subprocess.run(
        [sys.executable, "-I", "-S", "-", str(path)],
        input=script,
        cwd=tmp_path,
        env={},
        capture_output=True,
        timeout=10,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_a_current_receipt_identity_must_match_its_payload() -> None:
    payload_data = json.loads(json.dumps(PAYLOAD_DATA))
    payload_data.update(
        case_id=str(uuid4()), run_id=str(uuid4()), revision_id=str(uuid4())
    )
    payload = json.dumps(payload_data).encode()
    receipt = {
        "payload_sha256": hashlib.sha256(payload).hexdigest(),
        "signed_by": "analyst",
        "frozen_by": "freezer",
        "filed_by": "filer",
        **{key: payload_data[key] for key in ("case_id", "run_id", "revision_id")},
    }
    export = render(payload_data)

    package = build_package(payload, json.dumps(receipt).encode(), export)
    assert verify_package(package).verified
    receipt["case_id"] = str(uuid4())
    package = build_package(payload, json.dumps(receipt).encode(), export)
    result = verify_package(package)
    assert not result.verified
    assert result.reason == "the receipt does not identify this payload"


@pytest.mark.parametrize(
    "change",
    [
        "not zip",
        "truncated",
        "list receipt",
        "null receipt",
        "bad payload",
        "list payload",
        "changed export",
    ],
)
def test_malformed_input_never_raises(change: str) -> None:
    data = _package()
    if change == "not zip":
        data = b"not zip"
    elif change == "truncated":
        data = data[:-10]
    elif change in {"list receipt", "null receipt"}:
        data = _package(receipt=b"[]" if change == "list receipt" else b"null")
    elif change in {"bad payload", "list payload"}:
        data = _package(payload=b"{" if change == "bad payload" else b"[]")
    else:
        data = _package(export=render(PAYLOAD_DATA) + b" ")
    result = verify_package(data)
    assert not result.verified and result.reason


def test_write_package_never_overwrites_under_concurrent_writers(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "package.zip"
    barrier = Barrier(2)
    checked = Barrier(2)
    exists = Path.exists

    def synchronized_exists(self: Path) -> bool:
        result = exists(self)
        if self == path:
            checked.wait(timeout=5)
        return result

    # Deterministically exposes the old exists-then-write race. Exclusive open
    # does not consult exists, so the new implementation never uses this seam.
    monkeypatch.setattr(Path, "exists", synchronized_exists)
    packages = [_package(), _package(export=b"different complete bytes")]

    def write(data: bytes) -> bool:
        barrier.wait(timeout=5)
        try:
            write_package(path, data)
        except FileExistsError:
            return False
        return True

    with ThreadPoolExecutor(max_workers=2) as pool:
        winners = list(pool.map(write, packages))
    assert winners.count(True) == 1
    assert path.read_bytes() == packages[winners.index(True)]
    with pytest.raises(FileExistsError):
        write_package(path, b"replacement")
    assert path.read_bytes() == packages[winners.index(True)]


def test_the_same_inputs_build_the_same_package_bytes() -> None:
    data = _package()
    assert data == _package()
    with zipfile.ZipFile(BytesIO(data)) as archive:
        assert archive.namelist() == sorted(NAMES)
        assert all(
            info.date_time == (1980, 1, 1, 0, 0, 0) for info in archive.infolist()
        )
        for filename in ("render.py", "verify_package.py"):
            assert (
                archive.read(filename)
                == (ROOT / "caos/deliverable" / filename).read_bytes()
            )


def test_archived_renderer_is_used_and_receipt_renderer_hash_is_checked(
    tmp_path: Path,
) -> None:
    members = _members(_package())
    receipt = json.loads(members["receipt.json"])
    receipt["renderer_sha256"] = hashlib.sha256(members["render.py"]).hexdigest()
    members["receipt.json"] = json.dumps(receipt).encode()
    assert verify_package(_archive(list(members.items()))).verified
    receipt["renderer_sha256"] = "0" * 64
    members["receipt.json"] = json.dumps(receipt).encode()
    assert not verify_package(_archive(list(members.items()))).verified
    marker = tmp_path / "must-not-exist"
    members["render.py"] = f"open({str(marker)!r}, 'w').close()".encode()
    assert not verify_package(_archive(list(members.items()))).verified
    assert not marker.exists()


@pytest.mark.parametrize("compression", [zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED])
def test_declared_and_actual_member_sizes_must_match(compression: int) -> None:
    members = list(_members(_package()).items())
    data = _archive(members, compression)
    assert verify_package(data).verified
    assert not verify_package(_central(data, 24, len(members[0][1]) + 1)).verified
    assert not verify_package(_central(data, 24, len(members[0][1]) - 1)).verified


def test_a_local_header_crc_or_size_disagreeing_with_the_directory_is_refused() -> None:
    """R24-17: `_member` compared the local header's flags and method
    against the central directory but trusted only the central CRC and
    sizes when reading and checking a member -- so a local header naming a
    different CRC, compressed size or uncompressed size left content, both
    directories and every other member intact, and still verified, while a
    reader that walks local headers instead of the directory (a streaming
    unzip, `tar` reading a pipe) extracted the local header's own bytes."""
    data = _package()
    assert verify_package(data).verified
    for local_offset in (14, 18, 22):  # crc, compressed size, uncompressed size
        assert not verify_package(
            _local(data, "deliverable.html", local_offset, 0)
        ).verified


def test_an_underdeclared_deflate_body_with_a_matching_prefix_crc_is_refused() -> None:
    members = _members(_package())
    original = members["deliverable.html"]
    members["deliverable.html"] += b"hidden trailing output"
    data = _archive(list(members.items()), zipfile.ZIP_DEFLATED)
    import zlib

    data = _central(data, 24, len(original))
    data = _central(data, 16, zlib.crc32(original))
    # zipfile silently truncates this valid deflate stream to the declared size.
    with zipfile.ZipFile(BytesIO(data)) as opened:
        assert opened.read("deliverable.html") == original
    assert not verify_package(data).verified


def test_decompression_uses_a_hard_output_cap_even_when_metadata_lies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import zlib
    from unittest.mock import Mock

    from caos.deliverable import verify_package as standalone

    members = _members(_package())
    members["deliverable.html"] = b"x" * 100000
    built = _archive(list(members.items()), zipfile.ZIP_DEFLATED)
    # R24-17: local and central sizes must now agree, so the lie is told in
    # both, the same way a genuine package's local and central headers
    # would (a decompression bomb is not local/central disagreement).
    built = _local(built, "deliverable.html", 22, 1)
    data = _central(built, 24, 1)
    inflater = Mock(wraps=zlib.decompressobj(-15))
    monkeypatch.setitem(standalone.LIMITS, "deliverable.html", 32)
    monkeypatch.setattr(zlib, "decompressobj", lambda _: inflater)
    assert not standalone.verify(data)[0]
    assert inflater.decompress.call_args.args[1] == 33


def test_a_forged_central_entry_count_refuses_before_zipfile_parses_members(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data = bytearray(_archive([*_members(_package()).items(), ("extra", b"")]))
    end = data.rfind(b"PK\x05\x06")
    struct.pack_into("<2H", data, end + 8, 5, 5)
    opened: list[bool] = []
    original = zipfile.ZipFile

    def observed(source: BytesIO) -> zipfile.ZipFile:
        opened.append(True)
        return original(source)

    monkeypatch.setattr(zipfile, "ZipFile", observed)
    assert not verify_package(bytes(data)).verified
    assert not opened


def test_a_member_name_containing_a_null_is_not_the_exact_package_name() -> None:
    members = _members(_package())
    members["payload.jsonXignored"] = members.pop("payload.json")
    data = _archive(list(members.items())).replace(
        b"payload.jsonXignored", b"payload.json\x00ignored"
    )
    assert not verify_package(data).verified


def test_verify_package_without_an_argument_prints_usage_and_exits_2() -> None:
    """The verifier states its one argument instead of exiting on an IndexError."""
    verifier = ROOT / "caos/deliverable/verify_package.py"
    done = subprocess.run(
        [sys.executable, "-I", "-S", str(verifier)],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )

    assert done.returncode == 2, done.stderr
    assert "usage:" in done.stderr


def test_a_refused_archive_says_why_and_a_verified_one_has_nothing_to_say() -> None:
    """`Verification` carries two fields and the suite asserted one of them.

    Every test above reads `.verified` alone, so a verifier that always
    returned `reason=None` would pass all of them while telling a reader
    holding a bad archive nothing about what is wrong with it -- and the
    archived verifier this type wraps exists precisely so that a reader
    without this repository can find out. The `reason` is the half a person
    actually acts on, and it is asserted here as one.
    """
    good = verify_package(_package())
    assert isinstance(good, Verification)
    assert (good.verified, good.reason) == (True, None)

    truncated = verify_package(_package()[:-1])
    assert truncated.verified is False
    assert truncated.reason
    assert isinstance(truncated.reason, str)


def test_a_package_is_published_whole_or_not_at_all(tmp_path: Path) -> None:
    """The ledger entry this closes: `write_package` used `xb`, so two writers
    could not overwrite one another, but a crash or an I/O failure part-way
    could leave a short file at the destination that every later write then
    refuses -- a path that is permanently poisoned by a package nobody can
    verify.

    Staged and renamed instead: the bytes are written and fsynced to a
    temporary name in the *same directory* (a rename is only atomic within a
    filesystem), then linked into place. A reader therefore sees the whole
    archive or no file, never a prefix of one.
    """
    package, data = tmp_path / "filing.zip", _package()
    write_package(package, data)

    assert package.read_bytes() == data
    assert verify_package(package.read_bytes()).verified
    # Nothing is left behind: a staging file that survived would be the same
    # litter the entry complains about, one name along.
    assert [p.name for p in tmp_path.iterdir()] == ["filing.zip"]


def test_a_failed_write_leaves_no_file_at_the_destination(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The half that matters. A publication that dies after the bytes are
    written and before they are in place must leave *nothing* at the published
    path -- `xb` would otherwise refuse every correct write that followed a
    truncated one, poisoning the path permanently.

    The failure is injected at the fsync, which is exactly the window the old
    code had no answer for: the bytes exist somewhere, and the question is
    whether they exist under the name a reader will open.
    """
    package = tmp_path / "filing.zip"

    def dying(_fd: int) -> None:
        raise OSError(errno.EIO, os.strerror(errno.EIO))

    monkeypatch.setattr(os, "fsync", dying)
    with pytest.raises(OSError) as caught:
        write_package(package, _package())
    assert caught.value.errno == errno.EIO
    monkeypatch.undo()

    assert not package.exists()
    assert list(tmp_path.iterdir()) == [], "a staging file was left behind"

    # And the path is still usable, which is the whole point of the change.
    write_package(package, _package())
    assert verify_package(package.read_bytes()).verified


def test_two_writers_still_cannot_overwrite_one_another(tmp_path: Path) -> None:
    """The property the old `xb` had and the staged write must keep: a second
    publication to a live path is refused, never silently replaced."""
    package = tmp_path / "filing.zip"
    write_package(package, _package())

    with pytest.raises(FileExistsError):
        write_package(package, _package())


def test_the_archived_verifier_must_be_this_verifier() -> None:
    """F59: a package whose verifier member is not the host's is refused by
    the host, so the lie it would carry is never published."""
    members = _members(_package())
    assert verify_package(_archive(list(members.items()))).verified
    members["verify_package.py"] = b"# replaced\n"
    result = verify_package(_archive(list(members.items())))
    assert not result.verified
    assert result.reason == "the archived verifier is not this verifier"


def test_a_receipt_that_names_no_identity_verifies_nothing() -> None:
    """F60: nothing this host filed omits the three identifiers."""
    payload = json.dumps(PAYLOAD_DATA).encode()
    receipt = {
        "payload_sha256": hashlib.sha256(payload).hexdigest(),
        "signed_by": "analyst",
        "frozen_by": "freezer",
        "filed_by": "filer",
    }
    package = build_package(payload, json.dumps(receipt).encode(), render(PAYLOAD_DATA))
    result = verify_package(package)
    assert not result.verified
    assert result.reason == "the receipt does not identify this payload"


def _cross_referenced() -> dict[str, Any]:
    """A payload whose narrative names a citation of the record it binds."""
    from copy import deepcopy

    payload = deepcopy(PAYLOAD_DATA)
    [artifact] = payload["artifacts"]
    artifact["route_node_id"] = "1-CP-1"
    [citation] = json.loads(artifact["record"])["citations"]
    payload["narrative"] = [
        [{"figure": {"route_node_id": "1-CP-1", "citation_index": 0, **citation}}]
    ]
    return payload


def _package_of(payload: dict[str, Any]) -> bytes:
    data = json.dumps(payload).encode()
    receipt = json.dumps(
        {
            "payload_sha256": hashlib.sha256(data).hexdigest(),
            "signed_by": "analyst",
            "frozen_by": "freezer",
            "filed_by": "filer",
            **IDENTITY,
        }
    ).encode()
    return build_package(data, receipt, render(payload))


def test_a_narrative_figure_must_match_the_record_the_payload_binds() -> None:
    """FP-17: the payload's one internal cross-reference went unchecked.

    A figure carries its own copy of `document_sha256`, `page` and
    `matched_text`, and the verifier never compared that copy with
    `citations[citation_index]` of the record it binds -- so a package showing a
    forged quote on a page nobody cited was reported internally consistent.
    """
    from copy import deepcopy

    payload = _cross_referenced()
    assert verify_package(_package_of(payload)) == Verification(True, None)

    for field, forged in (
        ("matched_text", "A quote nobody anchored"),
        ("page", 99),
        ("document_sha256", "f" * 64),
    ):
        moved = deepcopy(payload)
        moved["narrative"][0][0]["figure"][field] = forged
        assert verify_package(_package_of(moved)) == Verification(
            False, "a narrative figure does not match the citation it names"
        )

    unresolvable = deepcopy(payload)
    unresolvable["narrative"][0][0]["figure"]["citation_index"] = 7
    assert verify_package(_package_of(unresolvable)) == Verification(
        False, "a narrative figure names no citation of this payload"
    )

    elsewhere = deepcopy(payload)
    elsewhere["narrative"][0][0]["figure"]["route_node_id"] = "2-CP-5"
    assert verify_package(_package_of(elsewhere)) == Verification(
        False, "a narrative figure names no citation of this payload"
    )


FORGED_PAGE = b"<!doctype html><h1>APPROVED -- no limitations</h1>\n"


def _local_entry(name: bytes, body: bytes) -> bytes:
    """One stored local entry, as a sequential reader meets it."""
    header = struct.pack(
        "<4s5H3I2H",
        b"PK\x03\x04",
        20,
        0,
        0,
        0,
        0x21,
        zlib.crc32(body),
        len(body),
        len(body),
        len(name),
        0,
    )
    return header + name + body


def _before_the_directory(package: bytes, extra: bytes) -> bytes:
    """`extra` inserted between the last member and the central directory, with
    the end record moved to keep naming the directory."""
    end = package.rfind(b"PK\x05\x06")
    offset = struct.unpack_from("<I", package, end + 16)[0]
    record = bytearray(package[end:])
    struct.pack_into("<I", record, 16, offset + len(extra))
    return package[:offset] + extra + package[offset:end] + bytes(record)


def test_bytes_no_member_covers_do_not_verify() -> None:
    """DQ-8: `_member` reads each member through its central entry, so a sixth
    local entry -- a forged `deliverable.html` -- placed before the directory
    was never read and the package verified, while a reader walking local
    headers in file order (a streaming unzip, `tar` reading a pipe) extracted
    the forged page. The five entries must cover the archive with no gap."""
    genuine = _package()
    assert verify_package(genuine) == Verification(True, None)
    smuggled = _before_the_directory(
        genuine, _local_entry(b"deliverable.html", FORGED_PAGE)
    )
    with zipfile.ZipFile(BytesIO(smuggled)) as archive:
        assert len(archive.infolist()) == 5, "the directory still names five"
    assert verify_package(smuggled) == Verification(False, UNREADABLE)
    gap = _before_the_directory(genuine, b"\0" * 16)
    assert verify_package(gap) == Verification(False, UNREADABLE)


@pytest.mark.parametrize(
    "narrative",
    [
        [[{"text": "Net leverage is 4.2x, headroom 45%."}]],
        [[{"text": "Headroom is " + chr(0xFF14) + chr(0xFF15) + " per cent."}]],
        [[{"text": "Leverage is below " + chr(0xBD) + " turn."}]],
        "Leverage is inside the covenant with limited headroom.",
    ],
    ids=["ascii", "fullwidth", "fraction", "string"],
)
def test_the_portable_check_re_applies_the_figure_rule(narrative: object) -> None:
    """DQ-15: a text span stating a quantity -- the uncited figure the save
    boundary refuses (invariant 11) -- verified, and so did a narrative that
    was one string. No filed revision carries a string (`prove_revision`
    refuses one), so the reason F108 kept that shape does not hold."""
    payload = _cross_referenced()
    payload["narrative"] = narrative
    reason = verify_package(_package_of(payload)).reason
    assert reason in {
        "a narrative states a figure no citation stands behind",
        "the narrative is not a list of paragraphs",
    }
    assert (reason == "the narrative is not a list of paragraphs") == (
        type(narrative) is str
    )


@pytest.mark.parametrize("page", [1.0, True])
def test_a_figure_field_must_be_the_citations_own_type(page: object) -> None:
    """DQ-15: `_figure_error` compared with `!=`, so page `1.0` and `True`
    matched page 1 and only the archived renderer refused them -- reported as
    "not a readable package", which is not what was wrong."""
    from copy import deepcopy

    payload = _cross_referenced()
    forged = deepcopy(payload)
    [[span]] = forged["narrative"]
    assert span["figure"]["page"] == 1
    span["figure"]["page"] = page
    # The export is the genuine page: the host's renderer refuses the forged
    # figure, and the verifier must say why before it ever re-renders.
    data = json.dumps(forged).encode()
    receipt = json.dumps(
        {
            "payload_sha256": hashlib.sha256(data).hexdigest(),
            "signed_by": "analyst",
            "frozen_by": "freezer",
            "filed_by": "filer",
            **IDENTITY,
        }
    ).encode()
    package = build_package(data, receipt, render(payload))
    assert verify_package(package) == Verification(
        False, "a narrative figure does not match the citation it names"
    )


def test_a_filing_names_the_renderer_the_verifier_pins() -> None:
    """`filing.renderer_sha256` is the digest a receipt carries, and the
    archived verifier refuses a renderer that does not hash to its own pin, so
    the two must name the same bytes: `render.py` as it is on disk."""
    from caos.deliverable.filing import renderer_sha256
    from caos.deliverable.verify_package import RENDERER_SHA256

    render_py = ROOT / "caos" / "deliverable" / "render.py"
    assert renderer_sha256() == hashlib.sha256(render_py.read_bytes()).hexdigest()
    assert renderer_sha256() == RENDERER_SHA256

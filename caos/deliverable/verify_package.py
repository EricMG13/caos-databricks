"""§55 portable consistency verifier. Run: python -I -S verify_package.py FILE.

The renderer pin protects execution by this trusted verifier. A replaced verifier
can lie: this package has no external authenticity or signature trust anchor.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import struct
import zipfile
import zlib
from io import BytesIO
from pathlib import Path
from typing import Any

VERIFIER_VERSION = "1"
# Updated with render.py; the archived verifier retains its historical pin.
RENDERER_SHA256 = "cae64483764b94d325ad96f2a329ce3271c3772d36e4f02e4c827aa5630a49ad"
MAX_ARCHIVE_BYTES = 64 * 1024 * 1024
LIMITS = {
    "payload.json": 32 * 1024 * 1024,
    "receipt.json": 64 * 1024,
    "deliverable.html": 64 * 1024 * 1024,
    "render.py": 1024 * 1024,
    "verify_package.py": 1024 * 1024,
}
UNREADABLE = "the archive is not a readable package"


def _directory(data: bytes) -> bool:
    """Bound directory parsing before ZipFile allocates one object per entry.

    These small packages require single-disk ZIP32, without trailing bytes.
    Inspect only five central headers; refuse ZIP64 and misleading entry counts.
    """
    end = data.rfind(b"PK\x05\x06", max(0, len(data) - 65557))
    if end < 0:
        return False
    _, disk, start_disk, count, total, size, offset, comment = struct.unpack_from(
        "<4s4H2IH", data, end
    )
    if (disk, start_disk, count, total) != (0, 0, 5, 5):
        return False
    if end + 22 + comment != len(data) or offset + size != end:
        return False
    cursor = offset
    for _ in range(5):
        if data[cursor : cursor + 4] != b"PK\x01\x02" or cursor + 46 > end:
            return False
        cursor += 46 + sum(struct.unpack_from("<3H", data, cursor + 28))
    return bool(cursor == end)


def _metadata(infos: list[zipfile.ZipInfo]) -> str | None:
    if len(infos) != 5 or {info.filename for info in infos} != set(LIMITS):
        return "the archive does not contain exactly the five package members"
    for info in infos:
        if info.orig_filename != info.filename:
            return "the archive does not contain exact package member names"
        if info.flag_bits & 1 or info.compress_type not in (0, 8):
            return "the archive uses encryption or unsupported compression"
        if info.file_size > LIMITS[info.filename]:
            return "the archive exceeds its member size limit"
        if info.file_size > 100 * info.compress_size:
            return "the archive exceeds its compression ratio limit"
    return None


def _member(archive: zipfile.ZipFile, info: zipfile.ZipInfo, data: bytes) -> bytes:
    # ZipFile.open checks local names, flags and overlapping member extents.
    # Read compressed bytes ourselves: ZipExtFile truncates an inflater's output
    # to the declared size, hiding a maliciously under-declared body.
    with archive.open(info):
        fields = struct.unpack_from("<4s5H3I2H", data, info.header_offset)
        if fields[2:4] != (info.flag_bits, info.compress_type):
            raise ValueError
        offset = info.header_offset + 30 + fields[-2] + fields[-1]
        compressed = memoryview(data)[offset : offset + info.compress_size]
        limit = LIMITS[info.filename]
        if info.compress_type == zipfile.ZIP_DEFLATED:
            inflater = zlib.decompressobj(-15)
            body = inflater.decompress(compressed, limit + 1)
            if not inflater.eof or inflater.unused_data or inflater.unconsumed_tail:
                raise ValueError
        else:
            body = bytes(compressed[: limit + 1])
        if len(body) > limit or len(body) != info.file_size:
            raise ValueError
        if zlib.crc32(body) != info.CRC:
            raise ValueError
        return body


def _receipt_identity_matches(receipt: dict[str, Any], payload: object) -> bool:
    """Current receipts bind their three identifiers; historical ones omit all."""
    identity = ("case_id", "run_id", "revision_id")
    if not any(key in receipt for key in identity):
        return True
    return isinstance(payload, dict) and all(
        isinstance(receipt.get(key), str)
        and receipt[key].strip()
        and receipt[key] == payload.get(key)
        for key in identity
    )


def _receipt_role_error(receipt: dict[str, Any]) -> str | None:
    named = [receipt.get(role) for role in ("signed_by", "frozen_by", "filed_by")]
    if any(not isinstance(actor, str) or not actor.strip() for actor in named):
        return "the receipt does not name all three roles"
    if len({str(actor).strip() for actor in named}) != 3:
        return "the receipt names fewer than three people"
    return None


def _contents(members: dict[str, bytes]) -> tuple[bool, str | None]:
    payload = members["payload.json"]
    receipt = json.loads(members["receipt.json"])
    if not isinstance(receipt, dict):
        return False, "the receipt is not a JSON object"
    if hashlib.sha256(payload).hexdigest() != receipt.get("payload_sha256"):
        return False, "the payload does not hash to what the receipt says"
    if role_error := _receipt_role_error(receipt):
        return False, role_error
    renderer = members["render.py"]
    digest = hashlib.sha256(renderer).hexdigest()
    if digest != RENDERER_SHA256:
        return False, "the renderer does not match this verifier's build"
    if "renderer_sha256" in receipt and receipt["renderer_sha256"] != digest:
        return False, "the renderer does not hash to what the receipt says"
    namespace: dict[str, Any] = {"__name__": "archived_render"}
    # §55: only exact, pinned build bytes execute, never arbitrary archive code.
    exec(compile(renderer, "<archived render.py>", "exec"), namespace)  # nosec B102
    decoded = json.loads(payload)
    if not _receipt_identity_matches(receipt, decoded):
        return False, "the receipt does not identify this payload"
    held = decoded.get("artifacts") if isinstance(decoded, dict) else None
    if not isinstance(held, list) or not held:
        return False, "the payload has no canonical handoffs"
    if any(not namespace["canonical_bound"](artifact) for artifact in held):
        return False, "a handoff does not hash to the pair the payload binds"
    if namespace["render"](decoded) != members["deliverable.html"]:
        return False, "the export does not re-render from the payload"
    return True, None


def verify(archive: bytes) -> tuple[bool, str | None]:
    """Return a fixed safe failure for malformed/unreadable input, never its text."""
    try:
        if not isinstance(archive, bytes) or len(archive) > MAX_ARCHIVE_BYTES:
            return False, "the archive exceeds its size limit or is not bytes"
        if not _directory(archive):
            return False, UNREADABLE
        with zipfile.ZipFile(BytesIO(archive)) as opened:
            infos = opened.infolist()
            reason = _metadata(infos)
            if reason:
                return False, reason
            members = {info.filename: _member(opened, info, archive) for info in infos}
        return _contents(members)
    except Exception:  # noqa: BLE001 -- §55 total boundary, no exception text escapes.
        return False, UNREADABLE


def main() -> int:
    """Read at most one byte beyond the archive ceiling and print a JSON verdict.

    argparse states the one argument and exits 2 with a usage line when it is
    absent, so a reader who runs the archived verifier bare is told what it
    wants instead of meeting an IndexError answered as an unreadable package.

    The argument is the package the operator wants checked, on their own
    machine, read with their own authority -- there is no root to confine it to
    and no privilege to escape. This verifier is shipped beside a package
    precisely so it runs wherever that package is (§55), so a path bound would
    defeat what it is for rather than protect anything. Anything unreadable,
    a directory or a dangling link included, becomes the same safe verdict
    below (sonar pythonsecurity:S8707).
    """
    parser = argparse.ArgumentParser(
        prog="verify_package.py",
        description="Check a deliverable package for internal consistency.",
    )
    parser.add_argument("archive", help="path to the package to verify")
    try:
        archive = parser.parse_args().archive
        with Path(archive).open("rb") as source:  # NOSONAR -- operator's own file
            result = verify(source.read(MAX_ARCHIVE_BYTES + 1))
    except Exception:  # noqa: BLE001 -- CLI failures use the same safe verdict.
        result = (False, UNREADABLE)
    print(json.dumps({"verified": result[0], "reason": result[1]}))
    return 0 if result[0] else 1


if __name__ == "__main__":
    raise SystemExit(main())

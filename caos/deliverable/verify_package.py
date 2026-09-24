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
from uuid import UUID

VERIFIER_VERSION = "1"
# Updated with render.py; the archived verifier retains its historical pin.
RENDERER_SHA256 = "5a8586276b5d22a52fb5fe0f6daaba63c5e21a13335c3cda0ea125cb8a9cd6af"
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
    extents = []
    for _ in range(5):
        if data[cursor : cursor + 4] != b"PK\x01\x02" or cursor + 46 > end:
            return False
        # Flags, compressed size and the local header's offset.
        extents.append(
            (
                struct.unpack_from("<I", data, cursor + 42)[0],
                struct.unpack_from("<I", data, cursor + 20)[0],
                struct.unpack_from("<H", data, cursor + 8)[0],
            )
        )
        cursor += 46 + sum(struct.unpack_from("<3H", data, cursor + 28))
    return cursor == end and _tiled(data, extents, offset)


def _tiled(data: bytes, extents: list[tuple[int, int, int]], directory: int) -> bool:
    """Whether the five local entries cover every byte before the directory.

    `_member` reads each member through the offset its central entry names, so
    bytes no central entry names were never read -- and a sixth local entry put
    there, a second `deliverable.html`, verified while a reader that walks local
    headers in file order (a streaming unzip, `tar` reading a pipe) extracted it
    (DQ-8). The entries must run from offset 0 to the directory with no gap and
    no trailing data descriptor, so there is nowhere for a sixth entry to be.
    """
    cursor = 0
    for local, size, flags in sorted(extents):
        if local != cursor or flags & 8 or local + 30 > directory:
            return False
        if data[local : local + 4] != b"PK\x03\x04":
            return False
        name, extra = struct.unpack_from("<2H", data, local + 26)
        cursor = local + 30 + name + extra + size
    return cursor == directory


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
    """A receipt binds its three identifiers to the payload's (F60); nothing
    this host ever filed omits them, so none is excused."""
    identity = ("case_id", "run_id", "revision_id")
    return isinstance(payload, dict) and all(
        isinstance(receipt.get(key), str)
        and receipt[key].strip()
        and receipt[key] == payload.get(key)
        for key in identity
    )


def _receipt_role_error(receipt: dict[str, Any]) -> str | None:
    """The signer, the freezer and the filer, and no two of them the same.

    One signer, because that is all the receipt names: FP-09 asks for the whole
    list, which is a change to `FiledReceipt` in `caos/api/wire.py`.

    CF-084: a role is a UUID, case-insensitive by RFC 4122 -- comparing the
    three as bare, case-sensitive strings let one person sign under one
    spelling and file under another and counted as three distinct people.
    Parsed as `UUID` before counting, which also refuses a role that is
    present and non-blank but not a UUID at all, the same way a role that is
    absent already is.
    """
    named = [receipt.get(role) for role in ("signed_by", "frozen_by", "filed_by")]
    texts = [actor for actor in named if isinstance(actor, str)]
    if len(texts) != len(named) or any(not actor.strip() for actor in texts):
        return "the receipt does not name all three roles"
    try:
        identities = {UUID(actor.strip()) for actor in texts}
    except ValueError:
        return "the receipt does not name all three roles"
    if len(identities) != 3:
        return "the receipt names fewer than three people"
    return None


def _own_bytes() -> bytes | None:
    try:
        return Path(__file__).read_bytes()
    except (NameError, OSError):
        return None


def _receipt_error(receipt: dict[str, Any], payload: bytes) -> str | None:
    if hashlib.sha256(payload).hexdigest() != receipt.get("payload_sha256"):
        return "the payload does not hash to what the receipt says"
    return _receipt_role_error(receipt)


_FIGURE_FIELDS = ("document_sha256", "page", "matched_text")


def _same(left: object, right: object) -> bool:
    """Equal and of one type: `1.0 == 1` and `True == 1` are Python's equality,
    not the same page (DQ-15)."""
    return type(left) is type(right) and left == right


def _cited_by_node(artifacts: list[Any]) -> dict[str, list[Any]]:
    """Each bound handoff's citation list, by the route node the payload names."""
    found: dict[str, list[Any]] = {}
    for artifact in artifacts:
        if not isinstance(artifact, dict):
            return {}
        citations = json.loads(str(artifact.get("record"))).get("citations")
        found[str(artifact.get("route_node_id"))] = (
            citations if isinstance(citations, list) else []
        )
    return found


def _figure_error(figure: object, cited: dict[str, list[Any]]) -> str | None:
    """One narrative figure against the citation of the record it names."""
    if not isinstance(figure, dict):
        return "a narrative figure is not an object"
    index = figure.get("citation_index")
    citations = cited.get(str(figure.get("route_node_id")), [])
    if (
        not isinstance(index, int)
        or isinstance(index, bool)
        or not 0 <= index < len(citations)
    ):
        return "a narrative figure names no citation of this payload"
    citation = citations[index]
    if not isinstance(citation, dict) or not all(
        _same(figure.get(field), citation.get(field)) for field in _FIGURE_FIELDS
    ):
        return "a narrative figure does not match the citation it names"
    return None


def _narrative_error(
    decoded: dict[str, Any], cited: dict[str, list[Any]]
) -> str | None:
    """Every narrative figure against the record the payload binds it to.

    A figure carries its own copy of `document_sha256`, `page` and
    `matched_text`, and nothing compared that copy with
    `citations[citation_index]` of the bound record -- so a package showing a
    forged quote on a page nobody cited was reported internally consistent, and
    this is the payload's one internal cross-reference (FP-17).

    And the save boundary's own rule, re-applied: prose states no quantity a
    figure does not cite (invariant 11), and the narrative is spans. A text span
    reading "Net leverage is 4.2x", or a narrative that was one string, verified
    with the uncited figure the save boundary refuses (DQ-15). No filed revision
    carries a string: `prove_revision` refuses one, and filing re-proves.
    """
    narrative = decoded.get("narrative")
    if narrative is None:
        # A payload carrying no narrative states nothing to cite; `render`
        # draws none. The save boundary always writes a list, empty or not.
        return None
    if not isinstance(narrative, list):
        return "the narrative is not a list of paragraphs"
    for paragraph in narrative:
        if not isinstance(paragraph, list):
            return "a narrative paragraph is not a list of spans"
        for span in paragraph:
            if error := _span_error(span, cited):
                return error
    return None


def _span_error(span: object, cited: dict[str, list[Any]]) -> str | None:
    """One span: a figure resolved against its record, text carrying none."""
    if isinstance(span, dict) and "figure" in span:
        return _figure_error(span["figure"], cited)
    text = span.get("text") if isinstance(span, dict) else None
    if isinstance(text, str) and any(character.isnumeric() for character in text):
        # `revisions._is_figure`, the whole numeric class and not only ASCII.
        return "a narrative states a figure no citation stands behind"
    return None


def _code_error(members: dict[str, bytes], receipt: dict[str, Any]) -> str | None:
    """The two files the package carries that run, against their pins."""
    # The verifier that travels with the package is this one (F59): the host
    # never blesses a package whose verifier it did not write. A copy run from
    # a pipe has no file to compare against and checks everything else.
    running = _own_bytes()
    if running is not None and members["verify_package.py"] != running:
        return "the archived verifier is not this verifier"
    digest = hashlib.sha256(members["render.py"]).hexdigest()
    if digest != RENDERER_SHA256:
        return "the renderer does not match this verifier's build"
    if "renderer_sha256" in receipt and receipt["renderer_sha256"] != digest:
        return "the renderer does not hash to what the receipt says"
    return None


def _contents(members: dict[str, bytes]) -> tuple[bool, str | None]:
    payload = members["payload.json"]
    receipt = json.loads(members["receipt.json"])
    if not isinstance(receipt, dict):
        return False, "the receipt is not a JSON object"
    if receipt_error := _receipt_error(receipt, payload):
        return False, receipt_error
    if code_error := _code_error(members, receipt):
        return False, code_error
    namespace: dict[str, Any] = {"__name__": "archived_render"}
    # §55: only exact, pinned build bytes execute, never arbitrary archive code.
    exec(  # nosec B102
        compile(members["render.py"], "<archived render.py>", "exec"), namespace
    )
    decoded = json.loads(payload)
    if not _receipt_identity_matches(receipt, decoded):
        return False, "the receipt does not identify this payload"
    held = decoded.get("artifacts") if isinstance(decoded, dict) else None
    if not isinstance(held, list) or not held:
        return False, "the payload has no canonical handoffs"
    if any(not namespace["canonical_bound"](artifact) for artifact in held):
        return False, "a handoff does not hash to the pair the payload binds"
    if narrative_error := _narrative_error(decoded, _cited_by_node(held)):
        return False, narrative_error
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

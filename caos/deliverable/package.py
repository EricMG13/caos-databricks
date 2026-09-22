"""Deterministic audit packages, portable consistency checks, exclusive creation.

§55: a package proves internal consistency, not externally authenticated signers.
Its archived verifier retains the renderer pin for that build.
"""

from __future__ import annotations

import os
import secrets
import zipfile
import zlib
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

from caos.deliverable.verify_package import verify

PAYLOAD = "payload.json"
RECEIPT = "receipt.json"
EXPORT = "deliverable.html"


def _compression(data: bytes) -> int:
    """Keep generated packages inside the verifier's bounded ratio policy."""
    compressor = zlib.compressobj(9, zlib.DEFLATED, -15)
    compressed_size = len(compressor.compress(data) + compressor.flush())
    return (
        zipfile.ZIP_STORED
        if len(data) > 100 * max(1, compressed_size)
        else zipfile.ZIP_DEFLATED
    )


@dataclass(frozen=True, slots=True)
class Verification:
    """What a reader learns from the archive, and why it failed if it did."""

    verified: bool
    reason: str | None = None


def build_package(payload: bytes, receipt: bytes, export: bytes) -> bytes:
    """Five sorted members, fixed timestamps and compression for this build."""
    directory = Path(__file__).parent
    members = {PAYLOAD: payload, RECEIPT: receipt, EXPORT: export}
    for name in ("render.py", "verify_package.py"):
        members[name] = (directory / name).read_bytes()
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, data in sorted(members.items()):
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.external_attr = 0o600 << 16
            archive.writestr(
                info, data, compress_type=_compression(data), compresslevel=9
            )
    return buffer.getvalue()


def verify_package(archive_bytes: bytes) -> Verification:
    """The portable verifier's verdict in the host's existing return type."""
    return Verification(*verify(archive_bytes))


def write_package(path: Path, archive_bytes: bytes) -> None:
    """Publish a package whole, once, or not at all.

    Two properties, and the second is the one this gained. *Once*: a second
    publication to a live path is refused rather than silently replacing it,
    which `os.link` gives for the same reason `open("xb")` did -- the
    filesystem refuses the name, not this code. *Whole*: the bytes are written
    and fsynced under a temporary name in the **same directory**, then linked
    into place, so a crash or an I/O failure part-way leaves nothing at the
    published path. The old `xb` wrote straight there, and a short file at that
    name was then refused by every correct write that followed it -- a path
    permanently poisoned by a package nobody could verify.

    The staging name shares the directory because a rename is only atomic
    within one filesystem, and the directory is fsynced after the link so the
    *name* is durable and not just its contents: a reader after a power loss
    must not find an entry pointing at nothing.
    """
    staging = path.with_name(f"{path.name}.{os.getpid()}.{secrets.token_hex(8)}")
    try:
        with staging.open("xb") as destination:
            destination.write(archive_bytes)
            destination.flush()
            os.fsync(destination.fileno())
        os.link(staging, path)
    finally:
        staging.unlink(missing_ok=True)
    directory = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)

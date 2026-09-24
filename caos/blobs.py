"""The content-addressed blob store. Bytes in, `sha256` out, verified on the way back.

`SYSTEM_SPEC.md` section 2 keeps bytes out of the database: rows hold a digest.
The digest is only worth holding if reading it back proves it, so `get` re-hashes
what it read and refuses what does not match. Nothing else in the system can tell
a source document apart from a plausible replacement of it.

A blob is written under a temporary name and renamed into place, so the address
either holds the whole blob or holds nothing. A partial file at the final address
would fail every later read for the life of the store.
"""

from __future__ import annotations

import io
import os
import re
from dataclasses import dataclass, field, replace
from hashlib import sha256
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import BinaryIO, Protocol

from caos.refusals import Refusal, RefusalCode

# `CAOS_BLOB_ROOT` may name a Unity Catalog volume instead of a directory (D9):
# `volume:///Volumes/<catalog>/<schema>/<volume>/<prefix>`.
VOLUME_SCHEME = "volume://"

# 64 lower-case hex characters, anchored. This is what stops an address from
# naming a path: no separator, no parent, no case-folding surprise on a
# case-insensitive filesystem.
_DIGEST = re.compile(r"\A[0-9a-f]{64}\Z")

# Blobs are sharded one level on the first two characters. A single directory
# holding every artifact a case ever produced is a directory listing nobody
# needs and some filesystems handle badly.
_SHARD = 2


class FilesService(Protocol):
    """The three Files API calls the volume backend makes (SDK `w.files`)."""

    def upload(
        self, file_path: str, contents: BinaryIO, *, overwrite: bool = False
    ) -> object: ...
    def download(self, file_path: str) -> object: ...
    def get_directory_metadata(self, directory_path: str) -> object: ...


# What an SDK call raises when it cannot be answered: `OSError` for the
# transport and the API's own errors, and -- because the service principal's
# token is re-minted inside the call it expires under -- `ValueError` for a
# token endpoint that answered non-2xx and `NotImplementedError` for one that
# answered without a token (ED-6). F85 mapped the second pair only where the
# client is built; each was an untyped 500 on every volume read once an
# hourly re-mint met a failing endpoint.
_SDK_FAULTS = (OSError, ValueError, NotImplementedError)


@dataclass(frozen=True, slots=True)
class VolumeBackend:
    """Bytes under a volume path through the SDK Files API (D9).

    `files` is the SDK's `files` service, built lazily from unified auth on
    first use so tests can hand in a double; the App's local disk is
    ephemeral, so on Databricks this is where every source and artifact lives.
    Every fault of a call is the typed `STORE_UNAVAILABLE` (a missing file
    `BLOB_NOT_FOUND`), raised from nothing, so no SDK message travels.
    """

    files: FilesService | None = field(default=None, repr=False)

    def _service(self) -> FilesService:
        if self.files is not None:
            return self.files
        from caos.workspace import workspace_client

        service: FilesService = workspace_client().files
        object.__setattr__(self, "files", service)
        return service

    def upload(self, path: Path, data: bytes) -> None:
        try:
            self._service().upload(str(path), io.BytesIO(data), overwrite=True)
        except _SDK_FAULTS:
            raise Refusal(RefusalCode.STORE_UNAVAILABLE) from None

    def download(self, path: Path) -> bytes:
        try:
            response = self._service().download(str(path))
            contents = getattr(response, "contents", None)
            data: bytes = contents.read() if contents is not None else b""
        except _SDK_FAULTS as failed:
            if isinstance(failed, OSError) and _not_found(failed):
                raise Refusal(RefusalCode.BLOB_NOT_FOUND) from None
            raise Refusal(RefusalCode.STORE_UNAVAILABLE) from None
        return data

    def probe(self, root: Path) -> None:
        try:
            self._service().get_directory_metadata(str(root))
        except _SDK_FAULTS:
            raise Refusal(RefusalCode.STORE_UNAVAILABLE) from None


def _not_found(failed: OSError) -> bool:
    """Whether the SDK said the file is not there (F41): its `NotFound` is a
    family (`ResourceDoesNotExist` answers a missing file, `issubclass`d from
    it), checked by `isinstance` against the SDK's own class rather than by
    matching a class name across `__mro__`. The error code is still read as a
    fallback, for a double that raises the shape without the class. Imported
    lazily, like `_service`'s workspace client: this module carries no SDK
    import until Databricks is actually in use."""
    from databricks.sdk.errors import NotFound

    code = getattr(failed, "error_code", "")
    return isinstance(failed, NotFound) or code in {
        "NOT_FOUND",
        "RESOURCE_DOES_NOT_EXIST",
    }


@dataclass(frozen=True, slots=True)
class BlobStore:
    """Bytes under their own digest, beneath one root directory or volume path."""

    root: Path
    volume: VolumeBackend | None = None
    # What `get` has already verified, by digest, on a `remembering` copy.
    verified: dict[str, bytes] | None = field(default=None, repr=False, compare=False)

    def remembering(self) -> BlobStore:
        """This store, keeping every blob `get` verifies for as long as the
        copy lives -- one request's (ED-7).

        Bytes proven against their own digest never change, so a second read
        of one is the same bytes. Without it one Analysis read of a ten-node
        route downloaded 91 blobs of which 20 were distinct -- a record up to
        sixteen times -- each a Files API download and a SHA-256 on
        Databricks, and the Book paid that per credit. Nothing but verified
        bytes is kept: a refusal is raised again on the next read.
        """
        return replace(self, verified={})

    @classmethod
    def from_setting(
        cls, setting: str, *, files: FilesService | None = None
    ) -> BlobStore:
        """The store `CAOS_BLOB_ROOT` names: a directory, or a `volume://` path."""
        if setting.startswith(VOLUME_SCHEME):
            path = setting[len(VOLUME_SCHEME) :]
            if not path.startswith("/Volumes/"):
                raise Refusal(RefusalCode.STORE_NOT_CONFIGURED)
            return cls(Path(path), VolumeBackend(files))
        return cls(Path(setting))

    def probe(self) -> None:
        """Refuse a root that is not reachable; nothing is written."""
        if self.volume is not None:
            self.volume.probe(self.root)
        elif not os.access(self.root, os.R_OK | os.W_OK | os.X_OK):
            raise Refusal(RefusalCode.STORE_UNAVAILABLE)

    def path_of(self, digest: str) -> Path:
        """Where `digest` lives. Refuses anything that is not a digest."""
        if not _DIGEST.match(digest):
            raise Refusal(RefusalCode.BLOB_ADDRESS_INVALID)
        return self.root / digest[:_SHARD] / digest

    def put(self, data: bytes) -> str:
        """Store `data`; return its digest. Storing the same bytes twice is one
        blob.

        The write is not skipped when the address is already occupied. Skipping
        would need a `stat` and a branch to save a write that is rare in a
        content-addressed store, and it would leave a blob whose bytes had been
        damaged even while the caller was holding the good ones. Writing
        unconditionally is shorter and repairs that case.
        """
        digest = sha256(data).hexdigest()
        destination = self.path_of(digest)
        if self.volume is not None:
            self.volume.upload(destination, data)
            return digest
        destination.parent.mkdir(parents=True, exist_ok=True)
        staged = self._stage(data, destination.parent)
        # Atomic within the directory: a reader sees the old state or the whole
        # blob, never a prefix of it.
        os.replace(staged, destination)
        self._sync_directory(destination.parent)
        return digest

    def put_both(self, first: bytes, second: bytes) -> tuple[str, str]:
        """`put` two blobs as one unit: both digests, or `STORE_UNAVAILABLE`.

        A module's handoff and its host record -- or a replayed outcome's
        same pair -- are accepted together or not at all, so a write failing
        partway must not leave an attempt accepted on half a pair. The second
        `put` after the first has already faulted would carry no useful
        context, so the raw fault is swallowed here and every caller sees one
        typed refusal instead of writing this same three-line guard itself.
        """
        stored: tuple[str, str] | None = None
        try:
            stored = self.put(first), self.put(second)
        except (OSError, Refusal):
            pass  # raised below, outside the handler: no context carried
        if stored is None:
            raise Refusal(RefusalCode.STORE_UNAVAILABLE)
        return stored

    @staticmethod
    def _stage(data: bytes, directory: Path) -> Path:
        """`data` in a durable file beside where it is going."""
        with NamedTemporaryFile(dir=directory, delete=False) as handle:
            staged = Path(handle.name)
            try:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            except OSError:
                # A full disk otherwise leaves its staging file behind on every
                # attempt, and the next attempt is the same full disk.
                staged.unlink(missing_ok=True)
                raise
        return staged

    @staticmethod
    def _sync_directory(directory: Path) -> None:
        """Make the rename itself durable, not just the bytes it renamed.

        Without this a crash can leave the row that names a digest committed and
        the blob at that digest absent -- which reads back as BLOB_NOT_FOUND, a
        typed refusal for something that was in fact stored.
        """
        handle = os.open(directory, os.O_RDONLY)
        try:
            os.fsync(handle)
        finally:
            os.close(handle)

    def get(self, digest: str) -> bytes:
        """The bytes stored under `digest`, proven to still hash to it.

        Refuses `BLOB_NOT_FOUND` for an address the store does not hold and
        `BLOB_DIGEST_MISMATCH` for one whose bytes have changed under it. Neither
        refusal carries any of the bytes: the code travels, the content does not.
        """
        path = self.path_of(digest)
        held = None if self.verified is None else self.verified.get(digest)
        if held is not None:
            return held
        if self.volume is not None:
            data = self.volume.download(path)
        else:
            try:
                data = path.read_bytes()
            except FileNotFoundError:
                raise Refusal(RefusalCode.BLOB_NOT_FOUND) from None
        if sha256(data).hexdigest() != digest:
            raise Refusal(RefusalCode.BLOB_DIGEST_MISMATCH)
        if self.verified is not None:
            self.verified[digest] = data
        return data

"""Phase 1: bytes are content-addressed, and the address is checked on the way out.

`SYSTEM_SPEC.md` section 2: bytes live in a content-addressed blob store keyed by
`sha256`; the database holds the digest, never the bytes. That is a guarantee
only if the store re-derives the digest from what it is about to return. A store
that trusts its own filenames is a naming convention, and the citation chain of
invariant 11 rests on it being more than that.
"""

from __future__ import annotations

import json
import os
import threading
from hashlib import sha256
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import BinaryIO

import pytest

from caos.api.identity import PLATFORM_ENV
from caos.blobs import VOLUME_SCHEME, BlobStore, FilesService
from caos.refusals import Refusal, RefusalCode

CONTENT = b"Total debt at 31 December 2026 was USD 1,240.0m.\n"
# 64 hex characters that address nothing in the store.
ABSENT = "0" * 64


@pytest.fixture
def blobs(tmp_path: Path) -> BlobStore:
    return BlobStore(tmp_path / "blobs")


def test_the_same_bytes_are_one_blob(blobs: BlobStore) -> None:
    first = blobs.put(CONTENT)
    second = blobs.put(CONTENT)

    assert first == second
    assert blobs.get(first) == CONTENT


def test_different_bytes_are_different_blobs(blobs: BlobStore) -> None:
    assert blobs.put(CONTENT) != blobs.put(CONTENT + b"amended\n")


def test_bytes_that_no_longer_hash_to_their_address_are_refused(
    blobs: BlobStore,
) -> None:
    """The one failure a content-addressed store exists to catch."""
    digest = blobs.put(CONTENT)
    blobs.path_of(digest).write_bytes(b"Total debt at 31 December 2026 was USD 0.0m.\n")

    with pytest.raises(Refusal) as caught:
        blobs.get(digest)

    assert caught.value.code is RefusalCode.BLOB_DIGEST_MISMATCH


def test_the_mismatch_refusal_carries_none_of_the_bytes(blobs: BlobStore) -> None:
    digest = blobs.put(CONTENT)
    blobs.path_of(digest).write_bytes(b"USD 0.0m")

    with pytest.raises(Refusal) as caught:
        blobs.get(digest)

    assert str(caught.value) == RefusalCode.BLOB_DIGEST_MISMATCH.value
    assert "USD" not in repr(caught.value)


def test_storing_the_bytes_again_repairs_a_damaged_blob(blobs: BlobStore) -> None:
    """`put` does not skip an address it already holds. The caller has the bytes
    in its hand; leaving the damaged ones there would refuse every later read of
    something the store could have made good."""
    digest = blobs.put(CONTENT)
    blobs.path_of(digest).write_bytes(b"Total debt at 31 December 2026 was USD 0.0m.\n")

    assert blobs.put(CONTENT) == digest
    assert blobs.get(digest) == CONTENT


def test_a_blob_that_was_never_stored_is_refused(blobs: BlobStore) -> None:
    with pytest.raises(Refusal) as caught:
        blobs.get(ABSENT)

    assert caught.value.code is RefusalCode.BLOB_NOT_FOUND


@pytest.mark.parametrize(
    "address",
    [
        "../../../../etc/passwd",
        "a" * 63,
        "A" * 64,
        "g" * 64,
        "",
        "a" * 64 + "/../../etc/passwd",
    ],
)
def test_an_address_that_is_not_a_digest_never_reaches_the_filesystem(
    blobs: BlobStore, address: str
) -> None:
    """`get` takes its argument from whatever the store held. A digest is 64
    lower-case hex characters and nothing else is looked up, so no argument can
    name a path outside the store's root."""
    with pytest.raises(Refusal) as caught:
        blobs.get(address)

    assert caught.value.code is RefusalCode.BLOB_ADDRESS_INVALID


def test_put_removes_its_staging_file_when_the_write_fails(
    blobs: BlobStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A full disk otherwise leaves its staging file behind on every attempt, and
    the next attempt meets the same full disk."""
    message = "no space left on device"

    def _failing_fsync(_fd: int) -> None:
        raise OSError(message)

    monkeypatch.setattr(os, "fsync", _failing_fsync)

    with pytest.raises(OSError, match=message):
        blobs.put(CONTENT)

    assert [p for p in blobs.root.rglob("*") if p.is_file()] == []


def test_put_leaves_no_staging_file_behind(blobs: BlobStore) -> None:
    """`put` writes under a temporary name and renames onto the address, so a
    reader sees the whole blob or no blob -- that part is `os.replace`, which
    this cannot observe. What it can observe is the other half: the staging name
    does not survive a successful write, so the store holds one file per blob."""
    digest = blobs.put(CONTENT)

    leftovers = [p for p in blobs.root.rglob("*") if p.is_file() and p.name != digest]

    assert leftovers == []


def test_a_remembering_store_reads_each_verified_blob_once(
    blobs: BlobStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ED-7. A request's store keeps what it verified: bytes proven against
    their own digest never change, so a second read is the same bytes without
    a second download and hash. Only verified bytes are kept -- a blob that
    fails is refused again on the next read -- and the store it was made from
    keeps nothing."""
    digest = blobs.put(CONTENT)
    damaged = blobs.put(b"to be damaged")
    blobs.path_of(damaged).write_bytes(b"damaged")
    reads: list[Path] = []
    real_read = Path.read_bytes

    def counted(path: Path) -> bytes:
        reads.append(path)
        return real_read(path)

    monkeypatch.setattr(Path, "read_bytes", counted)
    remembered = blobs.remembering()

    assert [remembered.get(digest) for _ in range(3)] == [CONTENT] * 3
    for _ in range(2):
        with pytest.raises(Refusal, match=r"^BLOB_DIGEST_MISMATCH$"):
            remembered.get(damaged)
    with pytest.raises(Refusal, match=r"^BLOB_ADDRESS_INVALID$"):
        remembered.get("not-a-digest")

    assert reads == [blobs.path_of(digest)] + [blobs.path_of(damaged)] * 2
    assert blobs.verified is None and remembered.verified == {digest: CONTENT}
    assert remembered == blobs, "the memo is not part of the store's identity"


class _Refusing:
    """A Files service whose every call fails the way the SDK's token refresh
    fails: `ValueError` for a token endpoint that answered non-2xx,
    `NotImplementedError` for one that answered without a token."""

    def __init__(self, fault: Exception) -> None:
        self.fault = fault

    def upload(
        self, file_path: str, contents: BinaryIO, *, overwrite: bool = False
    ) -> object:
        raise self.fault

    def download(self, file_path: str) -> object:
        raise self.fault

    def get_directory_metadata(self, directory_path: str) -> object:
        raise self.fault


@pytest.mark.parametrize(
    "fault",
    [ValueError("the token endpoint said 503"), NotImplementedError("no token")],
)
def test_an_sdk_fault_on_a_volume_call_is_a_typed_store_fault(fault: Exception) -> None:
    """ED-6. F85 mapped the SDK's `ValueError` where the client is built, not
    where it is used: the service principal re-mints its token inside each
    Files API call, so an expired token meeting a failing token endpoint
    escaped `put`, `get` and `probe` untyped and answered a plain 500."""
    files: FilesService = _Refusing(fault)
    store = BlobStore.from_setting(VOLUME_SCHEME + "/Volumes/c/s/v", files=files)
    for call in (
        lambda: store.put(CONTENT),
        lambda: store.get("a" * 64),
        store.probe,
    ):
        with pytest.raises(Refusal) as caught:
            call()
        assert caught.value.code is RefusalCode.STORE_UNAVAILABLE
        assert str(caught.value) == RefusalCode.STORE_UNAVAILABLE.value
        assert caught.value.__suppress_context__, "no SDK message chained"


class _Workspace(BaseHTTPRequestHandler):
    """OIDC discovery, a token endpoint that can be switched, and the Files
    API, on a loopback socket: the SDK's own oauth-m2m path end to end."""

    protocol_version = "HTTP/1.1"
    token = "ok"

    def log_message(self, *_: object) -> None:
        return

    def _json(self, status: int, payload: object) -> None:
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        here = f"http://{self.headers['Host']}"
        if self.path.startswith("/.well-known/databricks-config"):
            self._json(200, {"oidc_endpoint": f"{here}/oidc", "workspace_id": "1"})
        elif self.path.startswith("/oidc/.well-known/oauth-authorization-server"):
            self._json(
                200,
                {
                    "authorization_endpoint": f"{here}/oidc/v1/authorize",
                    "token_endpoint": f"{here}/oidc/v1/token",
                },
            )
        elif self.path.startswith("/api/2.0/fs/files/"):
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Length", str(len(CONTENT)))
            self.end_headers()
            self.wfile.write(CONTENT)
        else:
            self._json(404, {"error_code": "NOT_FOUND", "message": "no"})

    def do_POST(self) -> None:
        self.rfile.read(int(self.headers.get("Content-Length") or 0))
        if not self.path.startswith("/oidc/v1/token"):
            self._json(404, {"error_code": "NOT_FOUND", "message": "no"})
        elif _Workspace.token == "ok":
            # Expired as soon as it is minted, so every call re-mints.
            self._json(
                200, {"access_token": "t", "token_type": "Bearer", "expires_in": 1}
            )
        elif _Workspace.token == "garbled":
            self._json(200, {"token_type": "Bearer"})
        else:
            self._json(503, {"error": "temporarily_unavailable"})


def test_a_failing_token_endpoint_after_the_first_mint_is_a_typed_store_fault(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ED-6 through the real SDK client (N7's gap): the first read mints and
    succeeds; then the token endpoint answers 503, then a body with no token,
    and each read is the typed `STORE_UNAVAILABLE` rather than the SDK's
    `ValueError` or `NotImplementedError`."""
    from caos.workspace import forget_clients

    server = ThreadingHTTPServer(("127.0.0.1", 0), _Workspace)
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True).start()
    for name in ("DATABRICKS_TOKEN", "DATABRICKS_CONFIG_PROFILE", PLATFORM_ENV):
        monkeypatch.delenv(name, raising=False)
    host = f"http://127.0.0.1:{server.server_address[1]}"
    monkeypatch.setenv("DATABRICKS_HOST", host)
    monkeypatch.setenv("DATABRICKS_CLIENT_ID", "a-made-up-client")
    monkeypatch.setenv("DATABRICKS_CLIENT_SECRET", "made-up-not-a-secret")
    monkeypatch.setenv("DATABRICKS_CONFIG_FILE", os.devnull)
    monkeypatch.setattr(_Workspace, "token", "ok")
    forget_clients()
    store = BlobStore.from_setting(VOLUME_SCHEME + "/Volumes/c/s/v")
    digest = sha256(CONTENT).hexdigest()
    try:
        assert store.get(digest) == CONTENT
        for answer in ("down", "garbled"):
            monkeypatch.setattr(_Workspace, "token", answer)
            with pytest.raises(Refusal) as caught:
                store.get(digest)
            assert caught.value.code is RefusalCode.STORE_UNAVAILABLE, answer
    finally:
        forget_clients()
        server.shutdown()
        server.server_close()

"""Phase 1: bytes are content-addressed, and the address is checked on the way out.

`SYSTEM_SPEC.md` section 2: bytes live in a content-addressed blob store keyed by
`sha256`; the database holds the digest, never the bytes. That is a guarantee
only if the store re-derives the digest from what it is about to return. A store
that trusts its own filenames is a naming convention, and the citation chain of
invariant 11 rests on it being more than that.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from caos.blobs import BlobStore
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

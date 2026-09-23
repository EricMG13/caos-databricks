"""The store URL resolver and the volume blob backend, without a workspace (D9, R11)."""

from __future__ import annotations

import io
from pathlib import Path
from typing import BinaryIO

import pytest

from caos import blobs as blobs_module
from caos.blobs import VOLUME_SCHEME, BlobStore, FilesService, VolumeBackend
from caos.refusals import Refusal
from caos.store import lakebase
from caos.store.lakebase import store_url


def test_store_url_prefers_the_explicit_url_then_the_injected_pg_names(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CAOS_DATABASE_URL", "postgresql://explicit/db")
    assert store_url() == "postgresql://explicit/db"
    monkeypatch.delenv("CAOS_DATABASE_URL")
    for name in lakebase.PG_ENV:
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(Refusal, match=r"^STORE_NOT_CONFIGURED$"):
        store_url()
    monkeypatch.setenv("PGHOST", "instance.database.cloud")
    monkeypatch.setenv("PGPORT", "5432")
    monkeypatch.setenv("PGDATABASE", "databricks_postgres")
    monkeypatch.setenv("PGUSER", "0000-client-id")
    monkeypatch.setenv("PGSSLMODE", "require")
    minted: list[int] = []

    def mint() -> str:
        minted.append(1)
        return "tok/en+with=chars"

    monkeypatch.setattr(lakebase, "_mint", mint)
    monkeypatch.setattr(lakebase, "_CACHED", None)
    url = store_url()
    assert url == (
        "postgresql://0000-client-id:tok%2Fen%2Bwith%3Dchars@instance.database.cloud"
        ":5432/databricks_postgres?sslmode=require"
    )
    assert store_url() == url and minted == [1], "a fresh token is cached"


class _Files:
    """A `FilesService` double: an in-memory volume."""

    def __init__(self) -> None:
        self.held: dict[str, bytes] = {}
        self.directories: set[str] = set()

    def upload(
        self, file_path: str, contents: BinaryIO, *, overwrite: bool = False
    ) -> None:
        self.held[file_path] = contents.read()

    def download(self, file_path: str) -> object:
        if file_path not in self.held:
            raise _NotFound()
        return type("Download", (), {"contents": io.BytesIO(self.held[file_path])})()

    def get_directory_metadata(self, directory_path: str) -> None:
        if directory_path not in self.directories:
            raise OSError("private")


class NotFound(OSError):
    """The SDK's class family: `ResourceDoesNotExist` is a `NotFound` (F41)."""


class ResourceDoesNotExist(NotFound):
    error_code = "RESOURCE_DOES_NOT_EXIST"


_NotFound = ResourceDoesNotExist


def test_the_volume_backend_keeps_the_cas_contract() -> None:
    files = _Files()
    service: FilesService = files
    store = BlobStore.from_setting(
        VOLUME_SCHEME + "/Volumes/main/caos/caos_blobs", files=service
    )
    assert isinstance(store.volume, VolumeBackend)
    digest = store.put(b"bytes")
    assert (
        store.path_of(digest)
        == Path("/Volumes/main/caos/caos_blobs") / digest[:2] / digest
    )
    assert files.held[str(store.path_of(digest))] == b"bytes"
    assert store.get(digest) == b"bytes"
    files.held[str(store.path_of(digest))] = b"other"
    with pytest.raises(Refusal, match=r"^BLOB_DIGEST_MISMATCH$"):
        store.get(digest)
    with pytest.raises(Refusal, match=r"^BLOB_NOT_FOUND$"):
        store.get("0" * 64)
    with pytest.raises(Refusal, match=r"^STORE_UNAVAILABLE$"):
        store.probe()
    files.directories.add("/Volumes/main/caos/caos_blobs")
    store.probe()


def test_a_volume_setting_must_name_a_volume_and_a_directory_probe_is_real(
    tmp_path: Path,
) -> None:
    with pytest.raises(Refusal, match=r"^STORE_NOT_CONFIGURED$"):
        BlobStore.from_setting(VOLUME_SCHEME + "/tmp/not-a-volume")
    local = BlobStore.from_setting(str(tmp_path))
    assert local.volume is None and local.root == tmp_path
    local.probe()
    missing = BlobStore(tmp_path / "absent")
    with pytest.raises(Refusal, match=r"^STORE_UNAVAILABLE$"):
        missing.probe()
    assert blobs_module.VOLUME_SCHEME == "volume://"


def test_the_credential_life_and_an_authentication_failure_dropping_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from psycopg import errors

    from caos.store.lakebase import (
        TOKEN_SECONDS,
        invalidate_credential,
        note_connect_failure,
    )

    assert TOKEN_SECONDS == 14 * 60, "the vendor's 15-minute plan, minus room"
    monkeypatch.setattr(lakebase, "_CACHED", ("token", float("inf")))
    note_connect_failure(errors.ConnectionTimeout())
    assert lakebase._CACHED is not None, "a network fault keeps the credential"
    note_connect_failure(errors.InvalidPassword())
    assert lakebase._CACHED is None, "a refused password mints anew (F37)"
    monkeypatch.setattr(lakebase, "_CACHED", ("token", float("inf")))
    note_connect_failure(errors.InvalidAuthorizationSpecification())
    assert lakebase._CACHED is None
    invalidate_credential()
    assert lakebase._CACHED is None


def test_the_injected_names_are_quoted_and_the_port_must_be_a_number(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("CAOS_DATABASE_URL", raising=False)
    for name, value in {
        "PGHOST": "instance.database.cloud",
        "PGPORT": "5432",
        "PGDATABASE": "odd?name&here",
        "PGUSER": "0000-client-id",
        "PGSSLMODE": "require",
    }.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(lakebase, "_mint", lambda: "tok")
    monkeypatch.setattr(lakebase, "_CACHED", None)
    assert "/odd%3Fname%26here?sslmode=require" in store_url()
    monkeypatch.setenv("PGPORT", "54 32")
    with pytest.raises(Refusal, match=r"^STORE_NOT_CONFIGURED$"):
        store_url()

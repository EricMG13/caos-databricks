"""The store URL resolver and the volume blob backend, without a workspace (D9, R11)."""

from __future__ import annotations

import io
import os
from pathlib import Path
from typing import BinaryIO

import pytest

from caos import blobs as blobs_module
from caos.blobs import VOLUME_SCHEME, BlobStore, FilesService, VolumeBackend
from caos.refusals import Refusal, RefusalCode
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

    def mint() -> tuple[str, float]:
        minted.append(1)
        return "tok/en+with=chars", float("inf")

    monkeypatch.setattr(lakebase, "_mint", mint)
    lakebase.invalidate_credential()
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


def test_the_credential_life_and_a_connection_failure_dropping_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AR-02: the driver reports a refused password as a bare OperationalError
    with no SQLSTATE, the same as an unreachable host, so any connection
    failure drops the cached credential and the next connect mints."""
    import psycopg

    from caos.store.lakebase import (
        TOKEN_SECONDS,
        invalidate_credential,
        note_connect_failure,
    )

    assert TOKEN_SECONDS == 14 * 60, "the vendor's 15-minute plan, minus room"
    held = lakebase._Credential("token", float("inf"), float("inf"))
    monkeypatch.setattr(lakebase, "_CACHED", held)
    note_connect_failure(psycopg.OperationalError())
    assert lakebase._CACHED is None, "a refused password mints anew (F37, AR-02)"
    monkeypatch.setattr(lakebase, "_CACHED", held)
    invalidate_credential()
    assert lakebase._CACHED is None


def test_minting_is_single_flight_bounded_and_falls_back_to_a_live_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """MX-3 and DL-4: one mint at a time, abandoned past `MINT_SECONDS`; a mint
    that fails while the held token is still accepted by the server hands
    that token out; a failed mint is not retried for `FAILURE_SECONDS`."""
    import threading
    import time

    from caos.store.lakebase import MINT_SECONDS, TOKEN_SECONDS

    assert MINT_SECONDS == 30.0
    for name, value in {
        "PGHOST": "h",
        "PGPORT": "5432",
        "PGDATABASE": "d",
        "PGUSER": "u",
    }.items():
        monkeypatch.setenv(name, value)
    monkeypatch.delenv("CAOS_DATABASE_URL", raising=False)
    lakebase.invalidate_credential()
    calls: list[str] = []
    gate = threading.Event()

    def slow_mint() -> tuple[str, float]:
        calls.append("mint")
        gate.wait(5)
        return "fresh", float("inf")

    monkeypatch.setattr(lakebase, "_mint", slow_mint)
    answers: list[str] = []
    threads = [
        threading.Thread(target=lambda: answers.append(store_url())) for _ in range(4)
    ]
    for thread in threads:
        thread.start()
    time.sleep(0.2)
    gate.set()
    for thread in threads:
        thread.join(5)
    assert calls == ["mint"], "four cold callers made one round trip"
    assert len(set(answers)) == 1 and "fresh" in answers[0]

    # The refresh point passed but the server still accepts the token: a mint
    # that fails hands the held token out; one that is gone refuses.
    now = time.monotonic()
    monkeypatch.setattr(
        lakebase, "_CACHED", lakebase._Credential("held", now - 1, now + 60)
    )
    monkeypatch.setattr(lakebase, "_REFUSED_UNTIL", 0.0)

    def failing_mint() -> tuple[str, float]:
        calls.append("fail")
        raise Refusal(RefusalCode.STORE_UNAVAILABLE)

    monkeypatch.setattr(lakebase, "_mint", failing_mint)
    assert "held" in store_url()
    assert "held" in store_url(), "and the failure is not retried at once"
    assert calls == ["mint", "fail"]
    monkeypatch.setattr(
        lakebase, "_CACHED", lakebase._Credential("held", now - 1, now - 1)
    )
    monkeypatch.setattr(lakebase, "_REFUSED_UNTIL", 0.0)
    with pytest.raises(Refusal, match=r"^STORE_UNAVAILABLE$"):
        store_url()

    # A mint that never answers is abandoned within the bound.
    lakebase.invalidate_credential()
    monkeypatch.setattr(lakebase, "MINT_SECONDS", 0.2)
    monkeypatch.setattr(lakebase, "_mint", lambda: (threading.Event().wait(5), 0.0))
    started = time.monotonic()
    with pytest.raises(Refusal, match=r"^STORE_UNAVAILABLE$"):
        store_url()
    assert time.monotonic() - started < 2.0
    assert (
        lakebase._expires_at("2099-01-01T00:00:00Z") > time.monotonic() + TOKEN_SECONDS
    )
    assert lakebase._expires_at("not a date") <= time.monotonic() + TOKEN_SECONDS


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
    monkeypatch.setattr(lakebase, "_mint", lambda: ("tok", float("inf")))
    lakebase.invalidate_credential()
    assert "/odd%3Fname%26here?sslmode=require" in store_url()
    monkeypatch.setenv("PGPORT", "54 32")
    with pytest.raises(Refusal, match=r"^STORE_NOT_CONFIGURED$"):
        store_url()


def test_the_workspace_client_is_one_per_identity_and_refuses_typed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """W2 and CR-1: one bounded client per process and identity, and a
    construction the SDK refuses (a `ValueError` naming the host) is the
    typed `STORE_UNAVAILABLE`, which the mint and the worker ride out."""
    import databricks.sdk
    from databricks.sdk import config as sdk_config

    from caos import workspace
    from caos.workspace import IDENTITY_ENV, forget_clients, workspace_client

    assert "DATABRICKS_HOST" in IDENTITY_ENV
    forget_clients()
    built: list[str] = []
    message = "the host, which must not be printed"

    class _Config:
        def __init__(self, **kwargs: object) -> None:
            self.given = kwargs

    class _WorkspaceClient:
        def __init__(self, *, config: _Config) -> None:
            host = os.environ.get("DATABRICKS_HOST", "")
            built.append(host)
            if host.endswith("refused"):
                raise ValueError(message)
            self.config = config

    monkeypatch.setattr(sdk_config, "Config", _Config)
    monkeypatch.setattr(databricks.sdk, "WorkspaceClient", _WorkspaceClient)
    monkeypatch.setenv("DATABRICKS_HOST", "http://one")
    first = workspace_client()
    assert workspace_client() is first and built == ["http://one"]
    monkeypatch.setenv("DATABRICKS_HOST", "http://two")
    assert workspace_client() is not first and built == ["http://one", "http://two"]
    monkeypatch.setenv("DATABRICKS_HOST", "http://refused")
    with pytest.raises(Refusal, match=r"^STORE_UNAVAILABLE$"):
        workspace_client()
    assert workspace._client.cache_info().currsize == 2, "a failure is not cached"
    # And through the mint, with the instance named: typed, never ValueError.
    monkeypatch.setenv(lakebase.LAKEBASE_INSTANCE, "caos-lb")
    with pytest.raises(Refusal, match=r"^STORE_UNAVAILABLE$"):
        lakebase._mint()
    forget_clients()

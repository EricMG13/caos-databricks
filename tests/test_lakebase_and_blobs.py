"""The store URL resolver and the volume blob backend, without a workspace (D9, R11)."""

from __future__ import annotations

import io
import os
from pathlib import Path
from typing import BinaryIO

import pytest
from psycopg.conninfo import conninfo_to_dict

from caos import blobs as blobs_module
from caos.blobs import VOLUME_SCHEME, BlobStore, FilesService, VolumeBackend
from caos.refusals import Refusal, RefusalCode
from caos.store import lakebase
from caos.store.lakebase import store_url

# An Autoscaling endpoint's resource path, the default kind's binding.
ENDPOINT_PATH = "projects/caos/branches/production/endpoints/primary"


def _name_the_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    """The one Lakebase a platform process mints for: the default kind."""
    monkeypatch.setenv(lakebase.LAKEBASE_ENDPOINT, ENDPOINT_PATH)
    monkeypatch.delenv(lakebase.LAKEBASE_INSTANCE, raising=False)


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
    _name_the_endpoint(monkeypatch)
    minted: list[int] = []

    def mint() -> tuple[str, float]:
        minted.append(1)
        return "tok/en+with=chars", float("inf")

    monkeypatch.setattr(lakebase, "_mint", mint)
    lakebase.invalidate_credential()
    url = store_url()
    assert url == (
        "user=0000-client-id password=tok/en+with=chars"
        " host=instance.database.cloud port=5432 dbname=databricks_postgres"
        " sslmode=require"
    )
    assert store_url() == url and minted == [1], "a fresh token is cached"


def test_exactly_one_lakebase_is_named_or_the_store_is_not_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """R24-14: the instance was preferred over the endpoint, so a process
    handed both minted for whichever came first. Now exactly one names the
    Lakebase: neither, both, or an endpoint that is not an endpoint's
    resource path is `STORE_NOT_CONFIGURED` from the store URL, the
    checkpointer and the health probe alike, before anything is minted."""
    from caos.api.health import probe_store
    from caos.graph.checkpoint import checkpointer
    from caos.store.lakebase import LakebaseDatabase, LakebaseKind, lakebase_database

    monkeypatch.delenv("CAOS_DATABASE_URL", raising=False)
    for name, value in {
        "PGHOST": "h",
        "PGPORT": "5432",
        "PGDATABASE": "d",
        "PGUSER": "u",
    }.items():
        monkeypatch.setenv(name, value)
    minted: list[int] = []

    def mint() -> tuple[str, float]:
        minted.append(1)
        return "tok", float("inf")

    monkeypatch.setattr(lakebase, "_mint", mint)
    lakebase.invalidate_credential()
    monkeypatch.delenv(lakebase.LAKEBASE_ENDPOINT, raising=False)
    monkeypatch.delenv(lakebase.LAKEBASE_INSTANCE, raising=False)
    assert lakebase_database() is None
    refused: list[tuple[str, str]] = [
        ("", ""),  # neither: nothing says which database the role lives in
        (ENDPOINT_PATH, "caos-lb"),  # both: never guessed
        ("primary", ""),  # an endpoint id, not its resource path
        (ENDPOINT_PATH + "/", ""),
    ]
    for endpoint, instance in refused:
        monkeypatch.setenv(lakebase.LAKEBASE_ENDPOINT, endpoint)
        monkeypatch.setenv(lakebase.LAKEBASE_INSTANCE, instance)
        with pytest.raises(Refusal, match=r"^STORE_NOT_CONFIGURED$"):
            store_url()
        assert probe_store() == "STORE_NOT_CONFIGURED"
        with pytest.raises(Refusal, match=r"^STORE_NOT_CONFIGURED$"):
            checkpointer()
    assert minted == [], "nothing is minted for a refused configuration"
    monkeypatch.setenv(lakebase.LAKEBASE_ENDPOINT, ENDPOINT_PATH)
    monkeypatch.setenv(lakebase.LAKEBASE_INSTANCE, "")
    assert lakebase_database() == LakebaseDatabase(
        LakebaseKind.AUTOSCALING, ENDPOINT_PATH
    )
    monkeypatch.setenv(lakebase.LAKEBASE_ENDPOINT, "")
    monkeypatch.setenv(lakebase.LAKEBASE_INSTANCE, "caos-lb")
    assert lakebase_database() == LakebaseDatabase(LakebaseKind.PROVISIONED, "caos-lb")
    assert "tok" in store_url() and minted == [1]


def test_each_kind_mints_through_its_own_api(monkeypatch: pytest.MonkeyPatch) -> None:
    """R24-14: an Autoscaling endpoint through the Postgres API, a Provisioned
    instance through the database API, and neither through the other's."""
    from types import SimpleNamespace

    import caos.workspace

    asked: list[tuple[str, object]] = []

    def postgres(endpoint: str) -> object:
        asked.append(("postgres", endpoint))
        return SimpleNamespace(token="autoscaling", expire_time=None)

    def database(request_id: str, instance_names: list[str]) -> object:
        asked.append(("database", instance_names))
        return SimpleNamespace(token="provisioned", expiration_time=None)

    fake = SimpleNamespace(
        postgres=SimpleNamespace(generate_database_credential=postgres),
        database=SimpleNamespace(generate_database_credential=database),
    )
    monkeypatch.setattr(caos.workspace, "workspace_client", lambda: fake)
    _name_the_endpoint(monkeypatch)
    assert lakebase._mint()[0] == "autoscaling"
    monkeypatch.delenv(lakebase.LAKEBASE_ENDPOINT)
    monkeypatch.setenv(lakebase.LAKEBASE_INSTANCE, "caos-lb")
    assert lakebase._mint()[0] == "provisioned"
    assert asked == [("postgres", ENDPOINT_PATH), ("database", ["caos-lb"])]
    monkeypatch.delenv(lakebase.LAKEBASE_INSTANCE)
    with pytest.raises(Refusal, match=r"^STORE_NOT_CONFIGURED$"):
        lakebase._mint()


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
    _name_the_endpoint(monkeypatch)
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
        "PGDATABASE": "odd name's here",
        "PGUSER": "0000-client-id",
        "PGSSLMODE": "require",
    }.items():
        monkeypatch.setenv(name, value)
    _name_the_endpoint(monkeypatch)
    monkeypatch.setattr(lakebase, "_mint", lambda: ("tok", float("inf")))
    lakebase.invalidate_credential()
    # Round-tripped through psycopg's own parser rather than matched as a
    # substring, so what is asserted is that the odd name survives quoting
    # intact -- not one particular quoting spelling of it.
    assert conninfo_to_dict(store_url())["dbname"] == "odd name's here"
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
    monkeypatch.delenv(lakebase.LAKEBASE_ENDPOINT, raising=False)
    monkeypatch.setenv(lakebase.LAKEBASE_INSTANCE, "caos-lb")
    with pytest.raises(Refusal, match=r"^STORE_UNAVAILABLE$"):
        lakebase._mint()
    forget_clients()


def test_a_live_token_is_handed_out_while_another_caller_mints(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ST-1: while one mint hangs, a caller holding a token the server still
    accepts gets it at once; only a caller with no live token waits."""
    import threading
    import time

    hang = threading.Event()
    started = threading.Event()

    def hung_mint() -> tuple[str, float]:
        started.set()
        hang.wait(10)
        return "fresh", float("inf")

    _name_the_endpoint(monkeypatch)
    monkeypatch.setattr(lakebase, "_mint", hung_mint)
    monkeypatch.setattr(lakebase, "MINT_SECONDS", 3.0)
    now = time.monotonic()
    monkeypatch.setattr(
        lakebase, "_CACHED", lakebase._Credential("live", now - 1, now + 3600)
    )
    monkeypatch.setattr(lakebase, "_REFUSED_UNTIL", 0.0)
    minter = threading.Thread(target=lakebase._credential)
    minter.start()
    assert started.wait(5), "one caller is minting"
    waits: list[float] = []
    answers: list[str] = []
    lock = threading.Lock()

    def one() -> None:
        began = time.monotonic()
        token = lakebase._credential()
        with lock:
            waits.append(time.monotonic() - began)
            answers.append(token)

    callers = [threading.Thread(target=one) for _ in range(5)]
    for caller in callers:
        caller.start()
    for caller in callers:
        caller.join(5)
    assert answers == ["live"] * 5
    assert max(waits) < 0.5, "nobody waited out the mint in flight"
    hang.set()
    minter.join(5)


def test_the_autoscaling_credential_s_stated_expiry_is_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ST-3, MAX-15: the autoscaling form states its expiry as a protobuf
    `Timestamp` named `expire_time`; only the provisioned `expiration_time`
    was read, so the live-token fallback never applied on that path."""
    import time
    from datetime import UTC, datetime, timedelta
    from types import SimpleNamespace

    from databricks.sdk.service import postgres

    import caos.workspace

    # The SDK's own reading of the endpoint's answer: a protobuf `Timestamp`.
    stated = (datetime.now(UTC) + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    issued = postgres.DatabaseCredential.from_dict(
        {"token": "autoscaling", "expire_time": stated}
    )
    assert not isinstance(issued.expire_time, str)
    fake = SimpleNamespace(
        postgres=SimpleNamespace(generate_database_credential=lambda endpoint: issued)
    )
    monkeypatch.setattr(caos.workspace, "workspace_client", lambda: fake)
    _name_the_endpoint(monkeypatch)
    token, expires_at = lakebase._mint()
    left = expires_at - time.monotonic()
    assert token == "autoscaling"
    assert 3600 - lakebase.EXPIRY_MARGIN_SECONDS - 5 < left <= 3600
    assert lakebase._stated_instant(object()) is None
    assert lakebase._stated_instant("not a date") is None


def test_a_short_lived_credential_is_refreshed_by_its_stated_expiry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ST-3: a token the server says dies before `TOKEN_SECONDS` was handed
    out past that; and a mint that failed after another path dropped the
    token handed the dropped token back."""
    import threading
    import time

    lakebase.invalidate_credential()
    _name_the_endpoint(monkeypatch)
    minted: list[int] = []

    def short_lived() -> tuple[str, float]:
        minted.append(1)
        return f"short-{len(minted)}", time.monotonic() + 0.2

    monkeypatch.setattr(lakebase, "_mint", short_lived)
    assert lakebase._credential() == "short-1"
    held = lakebase._CACHED
    assert held is not None and held.refresh_at <= held.expires_at
    time.sleep(0.3)
    assert lakebase._credential() == "short-2", "never handed out past its expiry"

    # A mint that fails after the token was reported refused re-reads the
    # cache and refuses; it does not hand the dropped token back.
    started = threading.Event()

    def slow_failure() -> tuple[str, float]:
        started.set()
        time.sleep(0.3)
        raise Refusal(RefusalCode.STORE_UNAVAILABLE)

    now = time.monotonic()
    monkeypatch.setattr(
        lakebase, "_CACHED", lakebase._Credential("refused", now - 1, now + 3600)
    )
    monkeypatch.setattr(lakebase, "_REFUSED_UNTIL", 0.0)
    monkeypatch.setattr(lakebase, "_mint", slow_failure)
    outcome: list[str] = []

    def mint_once() -> None:
        try:
            outcome.append(lakebase._credential())
        except Refusal as refused:
            outcome.append(refused.code.value)

    minter = threading.Thread(target=mint_once)
    minter.start()
    assert started.wait(5)
    lakebase.invalidate_credential()  # another path's connect was refused
    minter.join(5)
    assert outcome == ["STORE_UNAVAILABLE"]


def test_every_store_connection_drops_a_refused_credential_but_boundedly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ST-2, MAX-03: `caos.store.connect` -- the API's, the health probes' and
    the lifespan's connection -- drops the cached credential when the connect
    fails, so the next one mints; a credential minted under
    `FAILURE_SECONDS` ago is kept, so an outage costs one mint per window."""
    import time

    import psycopg

    from caos.store import connect

    unreachable = "postgresql://u:p@127.0.0.1:1/db"
    now = time.monotonic()
    old = lakebase._Credential("old", now + 600, now + 3600, now - 60)
    monkeypatch.setattr(lakebase, "_CACHED", old)
    with pytest.raises(psycopg.OperationalError):
        connect(unreachable, connect_timeout=1)
    assert lakebase._CACHED is None, "a refused connect mints anew (ST-2)"
    fresh = lakebase._Credential("fresh", now + 600, now + 3600, time.monotonic())
    monkeypatch.setattr(lakebase, "_CACHED", fresh)
    with pytest.raises(psycopg.OperationalError):
        connect(unreachable, connect_timeout=1)
    assert lakebase._CACHED is fresh, "one mint per FAILURE_SECONDS (MAX-03)"

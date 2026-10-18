"""Behind a Databricks App the platform is the edge and the token the caller (D10)."""

from __future__ import annotations

import http.client
import json
import queue
import socket
import threading
import time
from collections import Counter
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid5

import anyio
import httpx2 as httpx
import pytest
import uvicorn
from fastapi.testclient import TestClient
from starlette.types import Receive, Scope, Send

from caos.api import edge, identity
from caos.api.edge import EdgeMode, resolve_mode
from caos.api.identity import (
    Actor,
    GlobalRole,
    WorkspaceAddress,
    WorkspaceUser,
    actor_from_headers,
    actor_from_token,
    role_from_groups,
    scim_me,
    workspace_address,
)
from caos.refusals import Refusal, RefusalCode


@pytest.fixture
def platform(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(edge.PLATFORM_ENV, "caos")
    monkeypatch.setenv(identity.WORKSPACE_ENV, "1234")
    monkeypatch.delenv(edge.PUBLIC_ORIGIN_ENV, raising=False)
    monkeypatch.delenv(identity.HOST_ENV, raising=False)
    monkeypatch.delenv(identity.GROUP_ADMIN_ENV, raising=False)
    monkeypatch.delenv(identity.GROUP_ANALYST_ENV, raising=False)
    monkeypatch.setattr(identity, "_CACHE", {})
    monkeypatch.setattr(identity, "_NEGATIVE", {})
    monkeypatch.setattr(identity, "_INFLIGHT", {})


def test_platform_mode_is_declared_by_the_app_name_and_excludes_the_others(
    platform: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert resolve_mode() == EdgeMode(public_origin=None, platform=True)
    monkeypatch.setenv(edge.PUBLIC_ORIGIN_ENV, "https://caos.example")
    assert resolve_mode().public_origin == "https://caos.example"
    monkeypatch.setenv(edge.PUBLIC_ORIGIN_ENV, "https://caos.example/path")
    with pytest.raises(Refusal, match=r"^EDGE_CONFIG_INVALID$"):
        resolve_mode()
    monkeypatch.delenv(edge.PUBLIC_ORIGIN_ENV)
    monkeypatch.setenv(identity.TRUST_SWITCH, "1")
    with pytest.raises(Refusal, match=r"^EDGE_CONFIG_INVALID$"):
        resolve_mode()


def test_the_token_names_the_caller_and_the_groups_name_the_role(
    platform: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    looked_up: list[str] = []

    def current_user(token: str) -> WorkspaceUser:
        looked_up.append(token)
        groups = {"tok-admin": {"caos-admins"}, "tok-analyst": {"caos-analysts"}}
        return WorkspaceUser(scim_id="42", groups=frozenset(groups.get(token, ())))

    monkeypatch.setattr(identity, "_current_user", current_user)

    async def main() -> None:
        admin = await actor_from_token("tok-admin")
        assert admin.role is GlobalRole.ADMIN
        assert isinstance(admin.user_id, UUID)
        assert admin.user_id == uuid5(identity.NAMESPACE, "1234:42")
        assert (await actor_from_token("tok-analyst")).role is GlobalRole.ANALYST
        assert (await actor_from_token("tok-other")).role is GlobalRole.READER
        assert (await actor_from_token("tok-admin")).user_id == (
            await actor_from_token("tok-other")
        ).user_id
        assert looked_up == ["tok-admin", "tok-analyst", "tok-other"], (
            "one lookup per token"
        )
        for bad in (None, "", "   ", 7):
            with pytest.raises(Refusal, match=r"^NOT_AUTHENTICATED$"):
                await actor_from_token(bad)
        monkeypatch.setenv(identity.GROUP_ADMIN_ENV, "lf-credit-admins")
        monkeypatch.setattr(identity, "_CACHE", {})
        monkeypatch.setattr(identity, "_NEGATIVE", {})
        assert (await actor_from_token("tok-admin")).role is GlobalRole.READER
        served = await actor_from_headers({"x-forwarded-access-token": "tok-analyst"})
        assert served.role is GlobalRole.ANALYST

    anyio.run(main)


def test_the_positive_and_negative_caches_expire_on_their_own_schedules(
    platform: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """CF-070. `CACHE_SECONDS` bounds a good token's cached actor and
    `NEGATIVE_SECONDS` a refused one's; neither had a test that moved past
    either bound, and both call `time.monotonic()` directly, so the clock
    is replaced rather than actually waited on.
    """
    clock = [0.0]
    monkeypatch.setattr(time, "monotonic", lambda: clock[0])
    calls: list[str] = []

    def current_user(token: str) -> WorkspaceUser:
        calls.append(token)
        if token == "revoked":
            raise Refusal(RefusalCode.NOT_AUTHENTICATED)
        return WorkspaceUser(scim_id="42", groups=frozenset())

    monkeypatch.setattr(identity, "_current_user", current_user)

    async def main() -> None:
        # A good lookup is remembered for CACHE_SECONDS, to the second: still
        # cached at one second short of it, asked again once past it.
        await actor_from_token("good")
        clock[0] += identity.CACHE_SECONDS - 1
        await actor_from_token("good")
        assert calls == ["good"], "still within CACHE_SECONDS"
        clock[0] += 2
        await actor_from_token("good")
        assert calls == ["good", "good"], "past CACHE_SECONDS, asked again"

        # A refused lookup is remembered for NEGATIVE_SECONDS the same way.
        with pytest.raises(Refusal, match=r"^NOT_AUTHENTICATED$"):
            await actor_from_token("revoked")
        clock[0] += identity.NEGATIVE_SECONDS - 1
        with pytest.raises(Refusal, match=r"^NOT_AUTHENTICATED$"):
            await actor_from_token("revoked")
        assert calls == ["good", "good", "revoked"], "still within NEGATIVE_SECONDS"
        clock[0] += 2
        with pytest.raises(Refusal, match=r"^NOT_AUTHENTICATED$"):
            await actor_from_token("revoked")
        assert calls == ["good", "good", "revoked", "revoked"], "past it, asked again"

    anyio.run(main)


def test_a_workspace_that_cannot_answer_is_not_authenticated(
    platform: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    def failing(token: str) -> WorkspaceUser:
        raise Refusal(RefusalCode.NOT_AUTHENTICATED)

    monkeypatch.setattr(identity, "_current_user", failing)
    with pytest.raises(Refusal, match=r"^NOT_AUTHENTICATED$"):
        anyio.run(actor_from_headers, {"x-forwarded-access-token": "tok"})


def test_a_platform_request_from_any_peer_reaches_the_api_without_forged_headers(
    platform: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    from caos.api.app import app

    monkeypatch.setattr(
        identity,
        "_current_user",
        lambda token: WorkspaceUser(scim_id="7", groups=frozenset({"caos-analysts"})),
    )
    monkeypatch.delenv("CAOS_DATABASE_URL", raising=False)
    client = TestClient(
        app, base_url="https://caos.apps.example", client=("10.1.2.3", 5000)
    )
    forged = {
        "x-forwarded-access-token": "tok",
        "x-caos-user": "00000000-0000-4000-8000-000000000001",
        "x-caos-role": "ADMIN",
        "sec-fetch-site": "same-origin",
    }
    # A non-loopback peer is admitted (no dev-peer rule), the forged identity
    # headers are dropped, and the request fails on the store, not the edge.
    response = client.get("/api/v1/directory", headers=forged)
    assert response.json()["code"] == "STORE_NOT_CONFIGURED"
    unsigned = client.get(
        "/api/v1/directory", headers={"sec-fetch-site": "same-origin"}
    )
    assert unsigned.json()["code"] == "NOT_AUTHENTICATED"
    kept = edge._rewritten([(b"x-caos-user", b"u"), (b"host", b"h")], edged=True)
    assert kept == [(b"host", b"h")]
    assert edge._rewritten([(b"x-caos-user", b"u")], edged=False) == [
        (b"x-caos-user", b"u")
    ]


def test_the_health_path_is_scrubbed_and_a_doubled_token_names_nobody(
    platform: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """F44: the identity headers a client sends are gone on the health path
    too, and two forwarded tokens are refused at the edge."""
    from caos.api.site import application

    seen: list[list[tuple[bytes, bytes]]] = []

    async def recorder(scope: Scope, receive: Receive, send: Send) -> None:
        seen.append(list(scope.get("headers", [])))
        await application(scope, receive, send)

    guarded = edge.EdgeGuard(recorder)
    client = TestClient(guarded, base_url="https://caos.apps.example")
    client.get(
        "/api/health",
        headers={"x-caos-user": "u", "x-forwarded-groups": "caos-admins"},
    )
    names = {key for key, _ in seen[-1]}
    assert b"x-caos-user" not in names and b"x-forwarded-groups" not in names
    monkeypatch.setattr(
        identity, "_current_user", lambda token: WorkspaceUser("1", frozenset())
    )
    monkeypatch.delenv("CAOS_DATABASE_URL", raising=False)
    doubled = client.get(
        "/api/v1/directory",
        headers=[
            ("x-forwarded-access-token", "a"),
            ("x-forwarded-access-token", "b"),
            ("sec-fetch-site", "same-origin"),
        ],
    )
    assert doubled.status_code == 401
    assert doubled.json()["code"] == "NOT_AUTHENTICATED"


def test_behind_the_platform_a_command_s_origin_must_name_the_host(
    platform: None,
) -> None:
    """F45: with no public origin declared, an unsafe request without
    `sec-fetch-site` is admitted only when its origin is this host."""
    headers = [(b"host", b"caos.apps.example")]
    mode = resolve_mode()
    allowed = edge._origin_allowed
    assert allowed(mode, "POST", [*headers, (b"origin", b"https://caos.apps.example")])
    assert not allowed(mode, "POST", [*headers, (b"origin", b"https://evil.example")])
    assert not allowed(mode, "POST", headers)
    assert allowed(mode, "POST", [*headers, (b"sec-fetch-site", b"same-origin")])
    assert allowed(mode, "GET", [*headers, (b"origin", b"https://evil.example")])


def test_the_platform_refuses_to_boot_without_the_workspace_id(
    platform: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """F46: every subject is minted under it; an empty one names everybody
    under the same nothing."""
    monkeypatch.delenv(identity.WORKSPACE_ENV)
    with pytest.raises(Refusal, match=r"^EDGE_CONFIG_INVALID$"):
        resolve_mode()


def test_the_configured_group_names_are_read_in_every_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """EI-W2. A literal `caos-admins` used to be the only spelling any mode
    read, so the configured `CAOS_GROUP_ADMIN` granted nothing while whatever
    IdP group happened to carry that spelling granted everything. One reader
    of the two variables (`role_from_groups`, the mapping platform mode feeds
    SCIM's group list through -- the only mode a group list decides a role in
    at all now that the HMAC edge assertion is gone, D10) now answers every
    mode there is.
    """
    monkeypatch.setenv(identity.GROUP_ADMIN_ENV, "lf-credit-admins")
    monkeypatch.setenv(identity.GROUP_ANALYST_ENV, "lf-credit-analysts")

    assert role_from_groups({"lf-credit-admins"}) is GlobalRole.ADMIN
    assert role_from_groups({"caos-admins"}) is GlobalRole.READER, (
        "the displaced literal grants nothing"
    )
    assert role_from_groups({"other", "lf-credit-analysts"}) is GlobalRole.ANALYST
    monkeypatch.delenv(identity.GROUP_ADMIN_ENV)
    monkeypatch.delenv(identity.GROUP_ANALYST_ENV)
    assert role_from_groups({identity.GROUP_ADMIN_DEFAULT}) is GlobalRole.ADMIN
    assert role_from_groups({identity.GROUP_ANALYST_DEFAULT}) is GlobalRole.ANALYST
    assert role_from_groups(frozenset()) is GlobalRole.READER


def test_requests_arriving_together_for_one_cold_token_make_one_round_trip(
    platform: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """EI-W3. Each SCIM call holds one of the process's 32 concurrency slots
    for up to the socket timeout, so a burst on a cold token -- a tab reload,
    a fleet restart -- used to spend one slot and one round trip per request.
    The first request asks; the rest wait on its answer.
    """
    arrived, release = threading.Event(), threading.Event()
    calls: list[str] = []

    def slow(token: str) -> WorkspaceUser:
        calls.append(token)
        arrived.set()
        release.wait(5)
        return WorkspaceUser(scim_id="42", groups=frozenset({"caos-analysts"}))

    monkeypatch.setattr(identity, "_current_user", slow)
    found: list[Actor] = []

    async def asked() -> None:
        found.append(await actor_from_token("tok"))

    async def main() -> None:
        async with anyio.create_task_group() as group:
            for _ in range(8):
                group.start_soon(asked)
            assert await anyio.to_thread.run_sync(arrived.wait, 5), (
                "the first request never reached the workspace"
            )
            release.set()

    anyio.run(main)

    assert calls == ["tok"], "one round trip for the whole burst"
    assert len(found) == 8
    assert {actor.user_id for actor in found} == {found[0].user_id}
    assert {actor.role for actor in found} == {GlobalRole.ANALYST}


def test_a_refusal_shared_by_a_burst_is_the_workspace_s_own_refusal(
    platform: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The requests that waited get the answer the one round trip got, code
    and all -- never a second call to a workspace in no state to answer the
    first, and never a success nobody was told about."""
    calls: list[str] = []

    def refusing(token: str) -> WorkspaceUser:
        calls.append(token)
        raise Refusal(RefusalCode.NOT_AUTHENTICATED)

    monkeypatch.setattr(identity, "_current_user", refusing)

    async def main() -> None:
        with pytest.raises(Refusal, match=r"^NOT_AUTHENTICATED$"):
            await actor_from_token("revoked")
        with pytest.raises(Refusal, match=r"^NOT_AUTHENTICATED$"):
            await actor_from_token("revoked")

        assert calls == ["revoked"], "the refusal is remembered, not re-asked"
        # The flight is closed however it ended: nothing waits on it afterwards.
        assert identity._INFLIGHT == {}
        shared = identity._Flight()
        shared.code = RefusalCode.IDENTITY_UNAVAILABLE
        shared.settled.set()
        with pytest.raises(Refusal, match=r"^IDENTITY_UNAVAILABLE$"):
            await identity._shared(shared)

    anyio.run(main)


def test_a_refused_token_is_stamped_after_the_workspace_answers(
    platform: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """CR-7. The negative entry used to carry the clock read *before* the
    call, so a workspace that took longer to refuse than `NEGATIVE_SECONDS`
    wrote an entry that had already expired -- and the cache that exists to
    spare a slow round trip failed exactly when the round trip was slow.
    """
    refusal_seconds, calls = 0.3, []
    # The fake clock the file's other cache tests use (N197): the workspace
    # "takes" `refusal_seconds` by moving it, so no thread handoff or real
    # wait decides whether the entry had already expired.
    clock = [0.0]
    monkeypatch.setattr(time, "monotonic", lambda: clock[0])

    def slow_refusal(token: str) -> WorkspaceUser:
        calls.append(token)
        clock[0] += refusal_seconds
        raise Refusal(RefusalCode.NOT_AUTHENTICATED)

    monkeypatch.setattr(identity, "_current_user", slow_refusal)
    monkeypatch.setattr(identity, "NEGATIVE_SECONDS", refusal_seconds - 0.1)

    async def main() -> None:
        for _ in range(3):
            with pytest.raises(Refusal, match=r"^NOT_AUTHENTICATED$"):
                await actor_from_token("revoked")

    anyio.run(main)

    assert calls == ["revoked"], "one round trip for three back-to-back requests"


def test_refused_tokens_are_pruned_and_bounded_as_they_arrive(
    platform: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AR-04. The negative cache was swept only after a *successful* uncached
    lookup, which a process being handed one distinct rejected token after
    another never reaches: entries grew without bound, expired ones included,
    and a later lookup had to walk the pile.
    """
    monkeypatch.setattr(
        identity,
        "_current_user",
        lambda token: (_ for _ in ()).throw(Refusal(RefusalCode.NOT_AUTHENTICATED)),
    )
    monkeypatch.setattr(identity, "CACHE_CAPACITY", 2)
    monkeypatch.setattr(identity, "NEGATIVE_SECONDS", 60.0)

    async def revoked() -> None:
        for ordinal in range(6):
            with pytest.raises(Refusal, match=r"^NOT_AUTHENTICATED$"):
                await actor_from_token(f"revoked-{ordinal}")

    anyio.run(revoked)
    assert len(identity._NEGATIVE) == 2, "bounded on the way in"

    monkeypatch.setattr(identity, "_NEGATIVE", {})
    monkeypatch.setattr(identity, "NEGATIVE_SECONDS", 0.0)

    async def stale() -> None:
        for ordinal in range(6):
            with pytest.raises(Refusal, match=r"^NOT_AUTHENTICATED$"):
                await actor_from_token(f"stale-{ordinal}")

    anyio.run(stale)
    assert len(identity._NEGATIVE) <= 1, "expired entries go on every write"


def test_a_malformed_scim_answer_is_a_typed_refusal_not_a_type_error(
    platform: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AR-12. `{"groups": true}` raised `TypeError` out of the comprehension
    that walked the groups, so an upstream answering nonsense read on the wire
    as this host's own `INTERNAL_FAULT`. Every shape is checked first now.
    """
    for body in (
        b'{"id": "42", "groups": true}',
        b'{"id": "42", "groups": 7}',
        b'{"id": "42", "groups": [1, 2]}',
        b'{"id": "42", "groups": {"display": "caos-admins"}}',
        b"not json at all",
        b'["not", "an", "object"]',
    ):
        with pytest.raises(Refusal, match=r"^IDENTITY_UNAVAILABLE$"):
            identity._scim_user(body)

    # ED-9: a `200` naming nobody is a malformed answer too, not "sign in" --
    # and it is not remembered as a refused token, so the workspace is asked
    # again as soon as it answers properly.
    for nameless in (b"{}", b'{"id": ""}', b'{"id": 42}'):
        with pytest.raises(Refusal, match=r"^IDENTITY_UNAVAILABLE$"):
            identity._scim_user(nameless)
    monkeypatch.setenv(identity.HOST_ENV, "caos.cloud.databricks.com")
    scim = _Scim(body=b"{}")
    scim.install(monkeypatch)

    async def asking() -> None:
        for _ in range(2):
            with pytest.raises(Refusal, match=r"^IDENTITY_UNAVAILABLE$"):
                await actor_from_token("nameless")

    anyio.run(asking)
    assert (len(scim.sent), identity._NEGATIVE) == (2, {})

    read = identity._scim_user(
        b'{"id": "42", "groups": [{"display": "caos-admins"}, {"value": "x"}]}'
    )
    assert read == WorkspaceUser(scim_id="42", groups=frozenset({"caos-admins"}))


class _Answer:
    """One SCIM response, read the way `scim_me` reads it."""

    def __init__(self, status: int, body: bytes) -> None:
        self.status, self._body = status, body

    def read1(self, amount: int) -> bytes:
        taken, self._body = self._body[:amount], self._body[amount:]
        return taken


class _Scim:
    """A stand-in workspace over `http.client`, recording what reached it."""

    def __init__(self, status: int = 200, body: bytes = b'{"id": "42"}') -> None:
        self.status, self.body = status, body
        self.fault: Exception | None = None
        self.opened: list[str] = []
        self.sent: list[Mapping[str, str]] = []
        self.closed = 0

    def _opener(self, scheme: str) -> Callable[..., Any]:
        scim = self

        class _Connection:
            def __init__(
                self, host: str, port: int | None = None, timeout: float | None = None
            ) -> None:
                scim.opened.append(f"{scheme}://{host}:{port}")

            def request(
                self, method: str, path: str, headers: Mapping[str, str]
            ) -> None:
                if scim.fault is not None:
                    raise scim.fault
                scim.sent.append({**headers, "method": method, "path": path})

            def getresponse(self) -> _Answer:
                return _Answer(scim.status, scim.body)

            def close(self) -> None:
                scim.closed += 1

        return _Connection

    def install(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(http.client, "HTTPConnection", self._opener("http"))
        monkeypatch.setattr(http.client, "HTTPSConnection", self._opener("https"))


def test_the_status_the_workspace_answers_decides_the_refusal(
    platform: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """EI-W5. The mapping F43 introduced had never run: a refused token, an
    unavailable workspace and an oversized body all reached the wire through
    lines nothing exercised.
    """
    monkeypatch.setenv(identity.HOST_ENV, "caos.cloud.databricks.com")

    for status in (401, 403):
        scim = _Scim(status=status)
        scim.install(monkeypatch)
        with pytest.raises(Refusal, match=r"^NOT_AUTHENTICATED$"):
            scim_me("Bearer tok")
        assert scim.closed == 1, "the socket is given back on every way out"

    for status in (404, 429, 500, 503):
        scim = _Scim(status=status)
        scim.install(monkeypatch)
        with pytest.raises(Refusal, match=r"^IDENTITY_UNAVAILABLE$"):
            scim_me("Bearer tok")

    oversized = _Scim(body=b" " * (identity.SCIM_BODY_BYTES + 1))
    oversized.install(monkeypatch)
    with pytest.raises(Refusal, match=r"^IDENTITY_UNAVAILABLE$"):
        scim_me("Bearer tok")

    for fault in (OSError("down"), http.client.HTTPException("truncated")):
        broken = _Scim()
        broken.fault = fault
        broken.install(monkeypatch)
        with pytest.raises(Refusal, match=r"^IDENTITY_UNAVAILABLE$"):
            scim_me("Bearer tok")
        assert broken.closed == 1


def test_a_workspace_is_asked_over_tls_and_the_header_is_passed_through(
    platform: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The HTTPS branch, and the whole `Authorization` header rather than a
    token: it is what lets the health probe send the credentials the SDK
    minted for this process down the very path a request takes (EI-W1)."""
    monkeypatch.setenv(identity.HOST_ENV, "https://caos.cloud.databricks.com")
    scim = _Scim(body=b'{"id": "42", "groups": [{"display": "caos-analysts"}]}')
    scim.install(monkeypatch)

    read = scim_me("Bearer minted-for-the-app")

    assert read.groups == frozenset({"caos-analysts"})
    assert scim.opened == ["https://caos.cloud.databricks.com:443"]
    assert scim.sent[0]["Authorization"] == "Bearer minted-for-the-app"
    assert scim.sent[0]["path"] == identity.SCIM_ME_PATH
    # And the token the platform forwards reaches it the same way.
    monkeypatch.setattr(identity, "_CACHE", {})
    assert anyio.run(actor_from_token, "forwarded").role is GlobalRole.ANALYST
    assert scim.sent[1]["Authorization"] == "Bearer forwarded"


def test_a_bearer_is_never_sent_in_clear_to_anything_but_this_machine() -> None:
    """N6 / EI-N3. The `http://` branch exists for the loopback stand-in. A
    `DATABRICKS_HOST` naming any other host over `http` would have put the
    caller's own access token on the wire unencrypted -- and EI-N2's
    non-numeric port raised an untyped `ValueError` that answered 500.
    """
    assert workspace_address("http://127.0.0.1:9") == WorkspaceAddress(
        secure=False, host="127.0.0.1", port=9
    )
    assert workspace_address("http://LOCALHOST:8000") == WorkspaceAddress(
        secure=False, host="localhost", port=8000
    )
    assert workspace_address("caos.cloud.databricks.com") == WorkspaceAddress(
        secure=True, host="caos.cloud.databricks.com", port=443
    )
    # ED-3: the port is always explicit, because `http.client` given none
    # reads it off the host and splits an IPv6 literal at its last colon --
    # `[::1]` asked `:` on port 1, `[2001:db8::a]` raised `InvalidURL`.
    assert workspace_address("http://[::1]") == WorkspaceAddress(
        secure=False, host="::1", port=80
    )
    assert workspace_address("https://[2001:db8::1]") == WorkspaceAddress(
        secure=True, host="2001:db8::1", port=443
    )
    assert workspace_address("https://[2001:db8::a]") == WorkspaceAddress(
        secure=True, host="2001:db8::a", port=443
    )
    assert workspace_address("https://adb-1.azuredatabricks.net.") == WorkspaceAddress(
        secure=True, host="adb-1.azuredatabricks.net.", port=443
    )
    for refused in (
        None,
        "",
        "http://workspace.example.com",  # a bearer in clear over the network
        "http://[::2]:9",
        "https://workspace.example.com:abc",  # the untyped ValueError
        "https://[::1",
        "ftp://workspace.example.com",
        "https://user:secret@workspace.example.com",
        "https://",
        "https://adb-123.net ",  # ED-3: booted, then `InvalidURL` per lookup
        "https://adb 123.net",
        "https://adb-123.net\t",
        "https://adb_123.net",
        "https://adb-123.net:0",
    ):
        assert workspace_address(refused) is None, refused


def test_an_unreachable_workspace_is_refused_at_boot_and_at_the_request(
    platform: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """EI-N2. Both callers of the parser answer it with their own typed
    refusal: boot with `EDGE_CONFIG_INVALID`, a request with
    `IDENTITY_UNAVAILABLE`. Neither used to be reachable at all."""
    monkeypatch.setenv(identity.HOST_ENV, "https://caos.cloud.databricks.com")
    assert resolve_mode().platform is True

    for broken in (
        "https://caos.cloud.databricks.com:abc",
        "http://evil.example",
        "https://localhost ",  # ED-3: booted, then answered 500 per request
    ):
        monkeypatch.setenv(identity.HOST_ENV, broken)
        with pytest.raises(Refusal, match=r"^EDGE_CONFIG_INVALID$"):
            resolve_mode()
        with pytest.raises(Refusal, match=r"^IDENTITY_UNAVAILABLE$"):
            scim_me("Bearer tok")

    monkeypatch.delenv(identity.HOST_ENV)
    assert resolve_mode().platform is True, "an absent host is the request's answer"
    with pytest.raises(Refusal, match=r"^IDENTITY_UNAVAILABLE$"):
        scim_me("Bearer tok")


def test_a_host_http_client_will_not_use_is_a_typed_refusal(
    platform: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ED-3. The connection was built outside the `try`, so the `InvalidURL`
    `http.client` raises for a host it cannot use escaped untyped and the
    request answered 500 instead of 503 `IDENTITY_UNAVAILABLE`."""
    monkeypatch.setenv(identity.HOST_ENV, "https://caos.cloud.databricks.com")

    def refusing(*_args: object, **_kwargs: object) -> None:
        raise http.client.InvalidURL

    monkeypatch.setattr(http.client, "HTTPSConnection", refusing)
    with pytest.raises(Refusal, match=r"^IDENTITY_UNAVAILABLE$"):
        scim_me("Bearer tok")


# How long a test waits on a thread, a socket or the workspace before it fails
# rather than hangs. Never what a test asserts: every wait it bounds ends on
# an event long before it in a passing run.
_HANG_GUARD_SECONDS = 30.0


@pytest.mark.parametrize("fails_at", ("construction", "start"))
def test_scim_worker_start_failure_restores_the_slot(
    platform: None, monkeypatch: pytest.MonkeyPatch, fails_at: str
) -> None:
    monkeypatch.setenv(identity.HOST_ENV, "https://caos.cloud.databricks.com")
    slots = threading.BoundedSemaphore(1)
    monkeypatch.setattr(identity, "_EXCHANGES", slots)

    def fail() -> None:
        detail = "private worker startup details"
        raise RuntimeError(detail)

    def worker(**_kwargs: object) -> SimpleNamespace:
        if fails_at == "construction":
            fail()
        return SimpleNamespace(start=fail)

    monkeypatch.setattr(threading, "Thread", worker)
    with pytest.raises(Refusal, match=r"^IDENTITY_UNAVAILABLE$") as refused:
        scim_me("Bearer tok")
    assert refused.value.__suppress_context__
    assert slots.acquire(blocking=False), "startup failure must return its slot"
    assert not slots.acquire(blocking=False), "return the slot exactly once"


class _Trickle:
    """The `drip` token's pace, and the clock its lookup reads.

    The workspace sends one byte of the body for each receive the lookup
    makes and none ahead of it, so each receive takes exactly one byte; each
    receive moves the clock on by `step`, a byte arriving well inside the
    socket's timeout every time, however loaded the machine is."""

    def __init__(self, step: float) -> None:
        self.step = step
        self.now = 0.0
        self.receives = 0
        self.sent = 0
        # True asks the workspace for one more byte; False ends the answer.
        self.wanted: queue.Queue[bool] = queue.Queue()
        # Set when the workspace waited out its guard for a byte to be asked
        # for: the lookup was reading by a path the trickle never fed.
        self.starved = False
        self.ended = threading.Event()

    def monotonic(self) -> float:
        return self.now

    def received(self) -> None:
        self.receives += 1
        self.now += self.step
        self.wanted.put(True)


class _Hold:
    """The `held` token's lookup, kept at the workspace until the test lets
    it go. `changed` is notified whenever anything the test waits on moves."""

    def __init__(self) -> None:
        self.changed = threading.Condition()
        self.arrived = 0
        self.release = threading.Event()
        self.answered = threading.Event()


class _SlowWorkspace(BaseHTTPRequestHandler):
    """SCIM `Me` on a real socket: `drip` trickles its body at `trickle`'s
    pace, `held` answers once `hold` is released, `slow` answers after a
    pause, anything else answers at once."""

    protocol_version = "HTTP/1.1"
    pause = 1.5
    # Set by the one test that asks for each token.
    trickle: _Trickle
    hold: _Hold

    def log_message(self, *_: object) -> None:
        return

    def do_GET(self) -> None:
        token = self.headers.get("Authorization", "").removeprefix("Bearer ")
        body = json.dumps({"id": token, "groups": []}).encode()
        if token == "slow":
            time.sleep(self.pause)
        if token == "held":
            hold = self.hold
            with hold.changed:
                hold.arrived += 1
                hold.changed.notify_all()
            # Shorter than every timeout of the lookup's own (twice it, where
            # it is held), so a caller stuck behind this answer is answered
            # once it passes, and fails.
            hold.release.wait(_HANG_GUARD_SECONDS)
            hold.answered.set()
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if token != "drip":
            self.wfile.write(body)
            return
        trickle = self.trickle
        try:
            self._trickled(trickle, body)
        finally:
            trickle.ended.set()

    def _trickled(self, trickle: _Trickle, body: bytes) -> None:
        """`body` a byte for each one the lookup asks for, and none ahead."""
        for byte in body:
            try:
                more = trickle.wanted.get(timeout=_HANG_GUARD_SECONDS)
            except queue.Empty:
                trickle.starved = True
                return
            if not more:
                return
            trickle.sent += 1
            self.wfile.write(bytes([byte]))
            self.wfile.flush()


@pytest.fixture
def workspace(platform: None, monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _SlowWorkspace)
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True).start()
    host = f"http://127.0.0.1:{server.server_address[1]}"
    monkeypatch.setenv(identity.HOST_ENV, host)
    try:
        yield host
    finally:
        server.shutdown()
        server.server_close()


def test_a_trickling_workspace_is_given_up_at_the_deadline(
    workspace: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ED-8. The socket's timeout bounds each receive, so a body arriving a
    byte inside every timeout held the lookup -- and every request sharing it
    -- open for as long as it trickled. The lookup now ends at
    `SCIM_DEADLINE_SECONDS`, its sharers with it, and the helper thread stops
    reading too, so nothing is left talking to the workspace. The clock the
    lookup reads is the trickle's (`_Trickle`): each receive takes one byte
    and a quarter of the deadline, so the lookup gives up after its fourth
    receive, whatever the machine's load, and the workspace is never asked
    for another byte. The deadline and the socket's timeout are hang guards,
    never reached in real time by a passing run."""
    monkeypatch.setattr(identity, "SCIM_DEADLINE_SECONDS", _HANG_GUARD_SECONDS)
    monkeypatch.setattr(identity, "SCIM_TIMEOUT_SECONDS", _HANG_GUARD_SECONDS * 2)
    trickle = _Trickle(step=_HANG_GUARD_SECONDS / 4)
    monkeypatch.setattr(_SlowWorkspace, "trickle", trickle, raising=False)
    # Only this module's clock: the event loop keeps the real one.
    monkeypatch.setattr(identity, "time", SimpleNamespace(monotonic=trickle.monotonic))
    body_by = identity._body_by

    def paced(response: http.client.HTTPResponse, deadline: float) -> bytes:
        receive = response.read1

        def read1(n: int = -1) -> bytes:
            trickle.received()
            return receive(n)

        monkeypatch.setattr(response, "read1", read1)
        return body_by(response, deadline)

    monkeypatch.setattr(identity, "_body_by", paced)
    helpers: list[threading.Thread] = []
    run = identity._Exchange.run

    def recorded(exchange: identity._Exchange) -> None:
        helpers.append(threading.current_thread())
        run(exchange)

    monkeypatch.setattr(identity._Exchange, "run", recorded)
    outcomes: list[str] = []

    async def ask() -> None:
        try:
            await actor_from_token("drip")
            outcomes.append("actor")
        except Refusal as refused:
            outcomes.append(refused.code.value)

    async def main() -> None:
        async with anyio.create_task_group() as group:
            for _ in range(3):
                group.start_soon(ask)

    try:
        anyio.run(main)
        for helper in helpers:
            helper.join(_HANG_GUARD_SECONDS)
        unasked = trickle.wanted.qsize()
    finally:
        # Ends the answer, if the workspace is still waiting to be asked.
        trickle.wanted.put(False)
    ended = trickle.ended.wait(_HANG_GUARD_SECONDS)

    assert outcomes == ["IDENTITY_UNAVAILABLE"] * 3
    # One lookup, made by one helper thread, and all three shared it.
    started = len(helpers)
    assert started == 1
    alive = [helper.name for helper in helpers if helper.is_alive()]
    assert alive == [], "a helper is still reading the trickle"
    assert ended, "the workspace is still answering"
    # A read the trickle never fed -- past the deadline or instead of `read1`
    # -- leaves the workspace waiting out its guard for a byte to be asked
    # for; the socket's timeout is twice that guard, so the read ends there.
    starved = trickle.starved
    assert not starved, "the lookup read the workspace by a path the trickle never fed"
    # Four: the clock reads 0, 7.5, 15 and 22.5 before the four receives
    # and 30, the deadline, before the fifth, which is never made. Four
    # bytes of a 28-byte body were sent and none is still asked for.
    receives = trickle.receives
    assert receives == 4
    sent = trickle.sent
    assert sent == 4
    assert unasked == 0


@pytest.mark.parametrize("recorded", [True, False])
def test_scim_me_waits_for_its_helper_for_the_deadline_and_no_longer(
    platform: None, monkeypatch: pytest.MonkeyPatch, recorded: bool
) -> None:
    """ED-8, the bound `scim_me` holds itself (N197). Both trickle tests end
    their helper through `_body_by`, which sets `done` first; neither reaches
    `exchange.done.wait(SCIM_DEADLINE_SECONDS)` giving up. Here the helper
    never sets `done` and never answers, and the wait on it is recorded
    rather than slept: `scim_me` asks for exactly the deadline, takes the
    unanswered exchange as `IDENTITY_UNAVAILABLE`, and the slot is returned
    when the helper does end. The unrecorded case (N232) lets a real `Event`
    give up after a short deadline: the argument is also what the wait obeys."""
    monkeypatch.setenv(identity.HOST_ENV, "https://caos.cloud.databricks.com")
    deadline = 7.0 if recorded else 0.2
    monkeypatch.setattr(identity, "SCIM_DEADLINE_SECONDS", deadline)
    waits: list[float | None] = []
    ended = threading.Event()
    slots = threading.BoundedSemaphore(1)
    monkeypatch.setattr(identity, "_EXCHANGES", slots)

    class _Unanswered(threading.Event):
        def wait(self, timeout: float | None = None) -> bool:
            waits.append(timeout)
            return False

    class _Stalled(identity._Exchange):
        def __init__(
            self,
            address: identity.WorkspaceAddress,
            authorization: str,
            deadline: float,
        ) -> None:
            super().__init__(address, authorization, deadline)
            if recorded:
                self.done = _Unanswered()

        def run(self) -> None:
            # The helper outlives the wait, and sets neither `answer` nor
            # `done`; it only gives its slot back, as the real one does.
            try:
                ended.wait(_HANG_GUARD_SECONDS)
            finally:
                slots.release()

    monkeypatch.setattr(identity, "_Exchange", _Stalled)
    try:
        started = time.monotonic()
        with pytest.raises(Refusal, match=r"^IDENTITY_UNAVAILABLE$"):
            scim_me("Bearer tok")
        took = time.monotonic() - started
        if recorded:
            assert waits == [deadline]
        else:
            assert deadline <= took < 5, "a real Event gave up after the deadline"
        assert not slots.acquire(blocking=False), "the helper still holds its slot"
    finally:
        ended.set()
    assert slots.acquire(timeout=_HANG_GUARD_SECONDS), "the slot comes back"


def test_requests_past_the_waiting_limit_are_refused_at_once(
    workspace: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ED-8. The one request actually making a cold lookup holds a worker
    thread for its socket call (N36); every other request sharing it now
    awaits the flight's own async signal, holding nothing. Past
    `SCIM_WAITING_LIMIT` a request is refused at once and holds nothing
    either, and the limit still leaves every waiter's wait bounded.

    Ordered on the workspace's hold, not on elapsed time (N197): the cold
    lookup is held at the workspace until the test releases it, so a request
    "refused at once" is one answered while the lookup is still held, and a
    cached caller "holding nothing behind it" is answered before it is let go.
    """
    total = anyio.run(_thread_limit)
    assert identity.SCIM_WAITING_LIMIT <= total // 2
    anyio.run(actor_from_token, "cached")
    monkeypatch.setattr(identity, "SCIM_DEADLINE_SECONDS", _HANG_GUARD_SECONDS * 2)
    monkeypatch.setattr(identity, "SCIM_TIMEOUT_SECONDS", _HANG_GUARD_SECONDS * 2)
    monkeypatch.setattr(identity, "SHARED_WAIT_SECONDS", _HANG_GUARD_SECONDS * 3)
    hold = _Hold()
    monkeypatch.setattr(_SlowWorkspace, "hold", hold, raising=False)
    burst = identity.SCIM_WAITING_LIMIT + 8
    # (code, whether the workspace had answered the held lookup by then)
    outcomes: list[tuple[str, bool]] = []
    over = burst - identity.SCIM_WAITING_LIMIT

    async def ask() -> None:
        try:
            await actor_from_token("held")
            code = "actor"
        except Refusal as refused:
            code = refused.code.value
        outcomes.append((code, hold.answered.is_set()))

    async def main() -> None:
        try:
            async with anyio.create_task_group() as group:
                for _ in range(burst):
                    group.start_soon(ask)
                with anyio.fail_after(_HANG_GUARD_SECONDS):
                    while len(outcomes) < over:
                        await anyio.sleep(0)
                refused_while_held = list(outcomes)
                assert (await actor_from_token("cached")).role is GlobalRole.READER
                cached_while_held = not hold.answered.is_set()
                hold.release.set()
        finally:
            hold.release.set()
        assert refused_while_held == [("IDENTITY_UNAVAILABLE", False)] * over
        assert cached_while_held, "the cached caller waited for the held lookup"

    anyio.run(main)

    served = [code for code, _ in outcomes if code == "actor"]
    refused = [code for code, _ in outcomes if code == "IDENTITY_UNAVAILABLE"]
    assert len(served) == identity.SCIM_WAITING_LIMIT
    assert len(refused) == over


async def _thread_limit() -> int:
    return int(anyio.to_thread.current_default_thread_limiter().total_tokens)


def test_a_cached_caller_is_served_while_a_cold_burst_waits(
    workspace: str, empty_database: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ED-8, over the socket the way the process serves it: forty-five
    requests for one cold token while its lookup was slow used to hold every
    AnyIO thread, and a caller whose identity was already cached waited
    behind them (0.06 s became 5.5 s in the review's probe). The workspace
    now holds the burst's lookup (`_Hold`) until the cached caller has been
    answered, so a cached caller queued behind the burst is answered only
    once the hold's guard has let the lookup go and the workspace answered."""
    from caos.api import app as app_module

    monkeypatch.setenv(app_module.DATABASE_URL, empty_database)
    # The lookup's own bounds, past the hold's guard: the burst waits on the
    # workspace for as long as the test holds it, and a cached caller queued
    # behind the burst is answered once the guard passes rather than refused.
    monkeypatch.setattr(identity, "SCIM_DEADLINE_SECONDS", _HANG_GUARD_SECONDS * 2)
    monkeypatch.setattr(identity, "SCIM_TIMEOUT_SECONDS", _HANG_GUARD_SECONDS * 2)
    monkeypatch.setattr(identity, "SHARED_WAIT_SECONDS", _HANG_GUARD_SECONDS * 3)
    hold = _Hold()
    monkeypatch.setattr(_SlowWorkspace, "hold", hold, raising=False)
    seen = _Resolutions.recorded(monkeypatch, hold)
    outcomes: list[tuple[int, str | None]] = []

    def in_burst(http: httpx.Client) -> None:
        answer = _directory(http, "held")
        with hold.changed:
            outcomes.append(answer)
            hold.changed.notify_all()

    # Every client is built before the burst starts: building one reads the
    # CA bundle into a TLS context, 0.07 s alone but 1.5 s while forty-five
    # are built at once on one host. Each request opens a connection of its
    # own. The clients' timeout is past every guard, so it is never the answer.
    with _served() as base:
        warm, cached, *cold = (
            httpx.Client(base_url=base, timeout=_HANG_GUARD_SECONDS * 4)
            for _ in range(47)
        )
        try:
            before = _directory(warm, "cached")
            burst = [threading.Thread(target=in_burst, args=(one,)) for one in cold]
            for one in burst:
                one.start()
            # The burst is waiting once the workspace holds its one lookup and
            # every request of it has entered `actor_from_token`: the event loop
            # runs each up to its first await -- joining the lookup or refused --
            # before it reads the cached caller's request.
            with hold.changed:
                waiting = hold.changed.wait_for(
                    lambda: hold.arrived == 1 and seen.entered["held"] == len(cold),
                    _HANG_GUARD_SECONDS,
                )
            during = _directory(cached, "cached")
            answered_first = hold.answered.is_set()
            resolved_during = dict(seen.resolved)
            asked_during = list(seen.asked)
            hold.release.set()
            for one in burst:
                one.join(_HANG_GUARD_SECONDS)
        finally:
            hold.release.set()
            for client in (warm, cached, *cold):
                client.close()

    assert waiting, (hold.arrived, seen.entered["held"])
    # Past identity before the burst and during it -- whatever the store
    # then answered -- while the workspace still held the burst's lookup and
    # with no SCIM call of its own: its identity was resolved twice and no
    # request of the burst's once; "cached" was asked of the workspace once,
    # before the burst, and "held" once.
    assert before[1] not in ("IDENTITY_UNAVAILABLE", "NOT_AUTHENTICATED"), before
    assert during[1] not in ("IDENTITY_UNAVAILABLE", "NOT_AUTHENTICATED"), during
    assert not answered_first, "the cached caller was answered after the burst"
    assert resolved_during == {"cached": 2}
    assert asked_during == ["cached", "held"]
    # The burst's one lookup resolved the `SCIM_WAITING_LIMIT` requests that
    # waited on it, and the rest were refused at once. Counted at identity,
    # not at the store, which those served go on to ask at once.
    assert hold.arrived == 1
    assert seen.resolved["held"] == identity.SCIM_WAITING_LIMIT
    answered = len(outcomes)
    assert answered == len(cold)
    refused = sum(code == "IDENTITY_UNAVAILABLE" for _, code in outcomes)
    assert refused == len(cold) - identity.SCIM_WAITING_LIMIT


@contextmanager
def _served() -> Iterator[str]:
    """The app on a uvicorn socket of its own, the way the process serves it,
    at the base URL yielded; stopped on the way out."""
    from caos import serve
    from caos.api.app import app

    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    server = uvicorn.Server(
        uvicorn.Config(
            app,
            lifespan="off",
            log_level="warning",
            limit_concurrency=serve.LIMIT_CONCURRENCY,
        )
    )
    thread = threading.Thread(
        target=server.run, kwargs={"sockets": [listener]}, daemon=True
    )
    thread.start()
    try:
        ends = time.monotonic() + _HANG_GUARD_SECONDS
        while not server.started:
            assert thread.is_alive(), "uvicorn stopped before it started"
            assert time.monotonic() < ends, "uvicorn did not start"
            time.sleep(0.01)
        yield f"http://127.0.0.1:{listener.getsockname()[1]}"
    finally:
        server.should_exit = True
        thread.join(10)
        listener.close()


@dataclass
class _Resolutions:
    """What `actor_from_token` was asked and answered, per token, and each
    token a SCIM lookup was made for, in order. Counted under
    `hold.changed`, so a test can wait on `entered`; the recorders delegate
    to the real functions."""

    entered: Counter[str] = field(default_factory=Counter)
    resolved: Counter[str] = field(default_factory=Counter)
    asked: list[str] = field(default_factory=list)

    @classmethod
    def recorded(cls, monkeypatch: pytest.MonkeyPatch, hold: _Hold) -> _Resolutions:
        seen = cls()
        resolve = identity.actor_from_token
        current_user = identity._current_user

        async def counted(token: object) -> Actor:
            with hold.changed:
                seen.entered[str(token)] += 1
                hold.changed.notify_all()
            actor = await resolve(token)
            seen.resolved[str(token)] += 1
            return actor

        def asked(token: str) -> WorkspaceUser:
            seen.asked.append(token)
            return current_user(token)

        monkeypatch.setattr(identity, "actor_from_token", counted)
        monkeypatch.setattr(identity, "_current_user", asked)
        return seen


def _directory(http: httpx.Client, token: str) -> tuple[int, str | None]:
    """The Directory read as `token`'s holder: its status and refusal code."""
    response = http.get(
        "/api/v1/directory",
        headers={"x-forwarded-access-token": token, "sec-fetch-site": "same-origin"},
    )
    code = response.json().get("code")
    return response.status_code, code if isinstance(code, str) else None


def test_the_origin_rules_refuse_a_doubled_or_unparsable_header(
    platform: None,
) -> None:
    """F45's branches, which nothing drove (EI-W5): two of either header names
    no single origin to check, and an origin that will not parse names no
    host. Each is a refusal rather than a value picked out of the pair."""
    mode = resolve_mode()
    host = [(b"host", b"caos.apps.example")]
    allowed = edge._origin_allowed

    assert not allowed(
        mode, "POST", [*host, (b"origin", b"https://a"), (b"origin", b"https://b")]
    )
    assert not allowed(
        mode,
        "POST",
        [*host, (b"sec-fetch-site", b"same-origin"), (b"sec-fetch-site", b"none")],
    )
    assert not allowed(mode, "POST", [*host, (b"origin", b"https://[::1")])
    assert not allowed(mode, "POST", [(b"origin", b"https://caos.apps.example")])
    assert not allowed(
        mode, "POST", [*host, *host, (b"origin", b"https://caos.apps.example")]
    )
    assert not allowed(mode, "POST", [*host, (b"origin", b"not-a-url")])
    assert not allowed(mode, "POST", [*host, (b"sec-fetch-site", b"cross-site")])

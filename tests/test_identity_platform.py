"""Behind a Databricks App the platform is the edge and the token the caller (D10)."""

from __future__ import annotations

import http.client
import json
import socket
import threading
import time
from collections.abc import Callable, Iterator, Mapping
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
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
    admin = actor_from_token("tok-admin")
    assert admin.role is GlobalRole.ADMIN
    assert isinstance(admin.user_id, UUID)
    assert admin.user_id == uuid5(identity.NAMESPACE, "1234:42")
    assert actor_from_token("tok-analyst").role is GlobalRole.ANALYST
    assert actor_from_token("tok-other").role is GlobalRole.READER
    assert (
        actor_from_token("tok-admin").user_id == actor_from_token("tok-other").user_id
    )
    assert looked_up == ["tok-admin", "tok-analyst", "tok-other"], (
        "one lookup per token"
    )
    for bad in (None, "", "   ", 7):
        with pytest.raises(Refusal, match=r"^NOT_AUTHENTICATED$"):
            actor_from_token(bad)
    monkeypatch.setenv(identity.GROUP_ADMIN_ENV, "lf-credit-admins")
    monkeypatch.setattr(identity, "_CACHE", {})
    monkeypatch.setattr(identity, "_NEGATIVE", {})
    assert actor_from_token("tok-admin").role is GlobalRole.READER
    assert actor_from_headers({"x-forwarded-access-token": "tok-analyst"}).role is (
        GlobalRole.ANALYST
    )


def test_a_workspace_that_cannot_answer_is_not_authenticated(
    platform: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    def failing(token: str) -> WorkspaceUser:
        raise Refusal(RefusalCode.NOT_AUTHENTICATED)

    monkeypatch.setattr(identity, "_current_user", failing)
    with pytest.raises(Refusal, match=r"^NOT_AUTHENTICATED$"):
        actor_from_headers({"x-forwarded-access-token": "tok"})


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
    threads = [
        threading.Thread(target=lambda: found.append(actor_from_token("tok")))
        for _ in range(8)
    ]
    for thread in threads:
        thread.start()
    assert arrived.wait(5), "the first request never reached the workspace"
    release.set()
    for thread in threads:
        thread.join(5)

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
    with pytest.raises(Refusal, match=r"^NOT_AUTHENTICATED$"):
        actor_from_token("revoked")
    with pytest.raises(Refusal, match=r"^NOT_AUTHENTICATED$"):
        actor_from_token("revoked")

    assert calls == ["revoked"], "the refusal is remembered, not re-asked"
    # The flight is closed however it ended: nothing waits on it afterwards.
    assert identity._INFLIGHT == {}
    shared = identity._Flight()
    shared.code = RefusalCode.IDENTITY_UNAVAILABLE
    shared.settled.set()
    with pytest.raises(Refusal, match=r"^IDENTITY_UNAVAILABLE$"):
        identity._shared(shared)


def test_a_refused_token_is_stamped_after_the_workspace_answers(
    platform: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """CR-7. The negative entry used to carry the clock read *before* the
    call, so a workspace that took longer to refuse than `NEGATIVE_SECONDS`
    wrote an entry that had already expired -- and the cache that exists to
    spare a slow round trip failed exactly when the round trip was slow.
    """
    refusal_seconds, calls = 0.3, []

    def slow_refusal(token: str) -> WorkspaceUser:
        calls.append(token)
        threading.Event().wait(refusal_seconds)
        raise Refusal(RefusalCode.NOT_AUTHENTICATED)

    monkeypatch.setattr(identity, "_current_user", slow_refusal)
    monkeypatch.setattr(identity, "NEGATIVE_SECONDS", refusal_seconds - 0.1)
    for _ in range(3):
        with pytest.raises(Refusal, match=r"^NOT_AUTHENTICATED$"):
            actor_from_token("revoked")

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

    for ordinal in range(6):
        with pytest.raises(Refusal, match=r"^NOT_AUTHENTICATED$"):
            actor_from_token(f"revoked-{ordinal}")
    assert len(identity._NEGATIVE) == 2, "bounded on the way in"

    monkeypatch.setattr(identity, "_NEGATIVE", {})
    monkeypatch.setattr(identity, "NEGATIVE_SECONDS", 0.0)
    for ordinal in range(6):
        with pytest.raises(Refusal, match=r"^NOT_AUTHENTICATED$"):
            actor_from_token(f"stale-{ordinal}")
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
    for _ in range(2):
        with pytest.raises(Refusal, match=r"^IDENTITY_UNAVAILABLE$"):
            actor_from_token("nameless")
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
    assert actor_from_token("forwarded").role is GlobalRole.ANALYST
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


class _SlowWorkspace(BaseHTTPRequestHandler):
    """SCIM `Me` on a real socket: `drip` trickles its body a byte at a time,
    `slow` answers after a pause, anything else answers at once."""

    protocol_version = "HTTP/1.1"
    pause = 1.5

    def log_message(self, *_: object) -> None:
        return

    def do_GET(self) -> None:
        token = self.headers.get("Authorization", "").removeprefix("Bearer ")
        body = json.dumps({"id": token, "groups": []}).encode()
        if token == "slow":
            time.sleep(self.pause)
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if token != "drip":
            self.wfile.write(body)
            return
        for byte in body:
            self.wfile.write(bytes([byte]))
            self.wfile.flush()
            time.sleep(0.2)


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
    reading too, so nothing is left talking to the workspace."""
    monkeypatch.setattr(identity, "SCIM_DEADLINE_SECONDS", 1.0)
    monkeypatch.setattr(identity, "SCIM_TIMEOUT_SECONDS", 1.0)
    outcomes: list[tuple[str, float]] = []

    def ask() -> None:
        started = time.monotonic()
        try:
            actor_from_token("drip")
            outcomes.append(("actor", time.monotonic() - started))
        except Refusal as refused:
            outcomes.append((refused.code.value, time.monotonic() - started))

    askers = [threading.Thread(target=ask) for _ in range(3)]
    for asker in askers:
        asker.start()
    for asker in askers:
        asker.join(10)

    assert [code for code, _ in outcomes] == ["IDENTITY_UNAVAILABLE"] * 3
    assert max(took for _, took in outcomes) < 2.0
    ended = time.monotonic()
    while _helpers_alive() and time.monotonic() - ended < 2.0:
        time.sleep(0.05)
    assert not _helpers_alive(), "a helper is still reading the trickle"


def _helpers_alive() -> bool:
    return any(t.name == "caos-scim" and t.is_alive() for t in threading.enumerate())


def test_requests_past_the_waiting_limit_are_refused_at_once(
    workspace: str,
) -> None:
    """ED-8. Every request waiting on the workspace holds one of AnyIO's forty
    threads, and a burst of cold requests during a slow lookup took all of
    them: a caller already cached waited behind it. Past
    `SCIM_WAITING_LIMIT` a request is refused at once and holds nothing, and
    the limit leaves most of the pool to everyone else."""
    total = anyio.run(_thread_limit)
    assert identity.SCIM_WAITING_LIMIT <= total // 2
    actor_from_token("cached")
    burst = identity.SCIM_WAITING_LIMIT + 8
    outcomes: list[tuple[str, float]] = []
    lock = threading.Lock()

    def ask() -> None:
        started = time.monotonic()
        try:
            actor_from_token("slow")
            code = "actor"
        except Refusal as refused:
            code = refused.code.value
        with lock:
            outcomes.append((code, time.monotonic() - started))

    askers = [threading.Thread(target=ask) for _ in range(burst)]
    for asker in askers:
        asker.start()
    time.sleep(0.3)
    started = time.monotonic()
    assert actor_from_token("cached").role is GlobalRole.READER
    assert time.monotonic() - started < 0.1
    for asker in askers:
        asker.join(10)

    served = [took for code, took in outcomes if code == "actor"]
    refused = [took for code, took in outcomes if code == "IDENTITY_UNAVAILABLE"]
    assert len(served) == identity.SCIM_WAITING_LIMIT
    assert len(refused) == burst - identity.SCIM_WAITING_LIMIT
    assert max(refused) < _SlowWorkspace.pause / 2, "a refused request waited"


async def _thread_limit() -> int:
    return int(anyio.to_thread.current_default_thread_limiter().total_tokens)


def test_a_cached_caller_is_served_while_a_cold_burst_waits(
    workspace: str, empty_database: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ED-8, over the socket the way the process serves it: forty-five
    requests for one cold token while its lookup takes 1.5 s used to hold
    every AnyIO thread, and a caller whose identity was already cached waited
    behind them (0.06 s became 5.5 s in the review's probe)."""
    from caos import serve
    from caos.api import app as app_module

    monkeypatch.setenv(app_module.DATABASE_URL, empty_database)
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    base = f"http://127.0.0.1:{listener.getsockname()[1]}"
    server = uvicorn.Server(
        uvicorn.Config(
            app_module.app,
            lifespan="off",
            log_level="warning",
            limit_concurrency=serve.LIMIT_CONCURRENCY,
        )
    )
    thread = threading.Thread(
        target=server.run, kwargs={"sockets": [listener]}, daemon=True
    )
    thread.start()
    while not server.started:
        time.sleep(0.01)

    def read(token: str) -> float:
        started = time.monotonic()
        with httpx.Client(base_url=base, timeout=30) as http:
            http.get(
                "/api/v1/directory",
                headers={
                    "x-forwarded-access-token": token,
                    "sec-fetch-site": "same-origin",
                },
            )
        return time.monotonic() - started

    try:
        read("cached")
        burst = [threading.Thread(target=read, args=("slow",)) for _ in range(45)]
        for one in burst:
            one.start()
        time.sleep(0.5)
        during = read("cached")
        for one in burst:
            one.join(30)
    finally:
        server.should_exit = True
        thread.join(10)
        listener.close()

    assert during < _SlowWorkspace.pause / 2, during


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

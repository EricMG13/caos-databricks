"""Behind a Databricks App the platform is the edge and the token the caller (D10)."""

from __future__ import annotations

import http.client
import threading
from collections.abc import Callable, Mapping
from typing import Any
from uuid import UUID, uuid4, uuid5

import pytest
from fastapi.testclient import TestClient
from starlette.types import Receive, Scope, Send

from caos.api import edge, identity
from caos.api.edge import Asserted, EdgeMode, resolve_mode
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
    assert resolve_mode() == EdgeMode(key=None, public_origin=None, platform=True)
    monkeypatch.setenv(edge.PUBLIC_ORIGIN_ENV, "https://caos.example")
    assert resolve_mode().public_origin == "https://caos.example"
    monkeypatch.setenv(edge.PUBLIC_ORIGIN_ENV, "https://caos.example/path")
    with pytest.raises(Refusal, match=r"^EDGE_CONFIG_INVALID$"):
        resolve_mode()
    monkeypatch.delenv(edge.PUBLIC_ORIGIN_ENV)
    monkeypatch.setenv(identity.TRUST_SWITCH, "1")
    with pytest.raises(Refusal, match=r"^EDGE_CONFIG_INVALID$"):
        resolve_mode()
    monkeypatch.delenv(identity.TRUST_SWITCH)
    monkeypatch.setenv(identity.EDGE_TOKEN_ENV, "k" * 40)
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
    asserted = Asserted(subject="s", groups=("g",))
    kept = edge._rewritten([(b"x-caos-user", b"u"), (b"host", b"h")], None, edged=True)
    assert kept == [(b"host", b"h")]
    assert edge._rewritten([(b"x-caos-user", b"u")], asserted)[0][0] == b"x-caos-user"


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
    """EI-W2. Edge mode used to map the literal `caos-admins` to ADMIN and
    never look at `CAOS_GROUP_ADMIN`, so the configured group granted nothing
    while whatever IdP group happened to carry that spelling granted
    everything. One reader of the two variables now answers both modes.
    """
    monkeypatch.delenv(identity.TRUST_SWITCH, raising=False)
    monkeypatch.setenv(identity.EDGE_TOKEN_ENV, "x" * 32)
    monkeypatch.setenv(identity.GROUP_ADMIN_ENV, "lf-credit-admins")
    monkeypatch.setenv(identity.GROUP_ANALYST_ENV, "lf-credit-analysts")
    subject = {identity.SUBJECT_HEADER: str(uuid4())}

    named = actor_from_headers({**subject, identity.GROUPS_HEADER: "lf-credit-admins"})
    displaced = actor_from_headers({**subject, identity.GROUPS_HEADER: "caos-admins"})
    analyst = actor_from_headers(
        {**subject, identity.GROUPS_HEADER: "other,lf-credit-analysts"}
    )

    assert named.role is GlobalRole.ADMIN
    assert displaced.role is GlobalRole.READER, "the displaced literal grants nothing"
    assert analyst.role is GlobalRole.ANALYST
    # The same reader, and the same defaults, whichever mode asks it.
    assert role_from_groups({"lf-credit-admins"}) is GlobalRole.ADMIN
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
    platform: None,
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

    for nameless in (b"{}", b'{"id": ""}', b'{"id": 42}'):
        with pytest.raises(Refusal, match=r"^NOT_AUTHENTICATED$"):
            identity._scim_user(nameless)

    read = identity._scim_user(
        b'{"id": "42", "groups": [{"display": "caos-admins"}, {"value": "x"}]}'
    )
    assert read == WorkspaceUser(scim_id="42", groups=frozenset({"caos-admins"}))


class _Answer:
    """One SCIM response, read the way `scim_me` reads it."""

    def __init__(self, status: int, body: bytes) -> None:
        self.status, self._body = status, body

    def read(self, amount: int) -> bytes:
        return self._body[:amount]


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
    assert scim.opened == ["https://caos.cloud.databricks.com:None"]
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
        secure=True, host="caos.cloud.databricks.com", port=None
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

    for broken in ("https://caos.cloud.databricks.com:abc", "http://evil.example"):
        monkeypatch.setenv(identity.HOST_ENV, broken)
        with pytest.raises(Refusal, match=r"^EDGE_CONFIG_INVALID$"):
            resolve_mode()
        with pytest.raises(Refusal, match=r"^IDENTITY_UNAVAILABLE$"):
            scim_me("Bearer tok")

    monkeypatch.delenv(identity.HOST_ENV)
    assert resolve_mode().platform is True, "an absent host is the request's answer"
    with pytest.raises(Refusal, match=r"^IDENTITY_UNAVAILABLE$"):
        scim_me("Bearer tok")


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

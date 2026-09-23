"""Behind a Databricks App the platform is the edge and the token the caller (D10)."""

from __future__ import annotations

from uuid import UUID, uuid5

import pytest
from fastapi.testclient import TestClient
from starlette.types import Receive, Scope, Send

from caos.api import edge, identity
from caos.api.edge import Asserted, EdgeMode, resolve_mode
from caos.api.identity import (
    GlobalRole,
    WorkspaceUser,
    actor_from_headers,
    actor_from_token,
)
from caos.refusals import Refusal, RefusalCode


@pytest.fixture
def platform(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(edge.PLATFORM_ENV, "caos")
    monkeypatch.setenv(identity.WORKSPACE_ENV, "1234")
    monkeypatch.delenv(edge.PUBLIC_ORIGIN_ENV, raising=False)
    monkeypatch.setattr(identity, "_CACHE", {})
    monkeypatch.setattr(identity, "_NEGATIVE", {})


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
    kept = edge._rewritten(
        [(b"x-caos-user", b"u"), (b"host", b"h")], None, platform=True
    )
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

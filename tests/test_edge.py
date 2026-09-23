"""Repair Phase 4, slice 4.5a1: the edge guard in front of every request.

Task 4.5 brief, decisions 2 to 6 and authority trace A1-A6, A8 and A10. The
guard is pure ASGI, so most of these drive it over a recording app that shows
exactly what reached the application; the rest ask the real app, on paths that
answer before any store connection.
"""

from __future__ import annotations

import logging
import secrets
import time
from collections.abc import Iterator
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.types import Receive, Scope, Send

from caos.api.app import app
from caos.api.edge import (
    EDGE_ASSERTION_HEADER,
    PUBLIC_ORIGIN_ENV,
    SECURITY_HEADERS,
    EdgeGuard,
    EdgeMode,
    is_api_path,
    refusal_body,
    resolve_mode,
    sign_assertion,
    startup_failed,
)
from caos.api.identity import (
    EDGE_TOKEN_ENV,
    TRUST_SWITCH,
    GlobalRole,
    actor_from_headers,
)
from caos.api.wire import CLEARS
from caos.refusals import Refusal, RefusalCode

PUBLIC = "https://caos.example.test"


class Recorder:
    """An app that answers 200 and keeps the headers it was handed."""

    def __init__(self) -> None:
        self.seen: list[list[tuple[bytes, bytes]]] = []

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        self.seen.append(list(scope["headers"]))
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"reached"})


@pytest.fixture
def token(monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    minted = secrets.token_urlsafe(32)
    monkeypatch.setenv(EDGE_TOKEN_ENV, minted)
    monkeypatch.setenv(PUBLIC_ORIGIN_ENV, PUBLIC)
    monkeypatch.delenv(TRUST_SWITCH, raising=False)
    yield minted


def _guarded() -> tuple[Recorder, TestClient]:
    recorder = Recorder()
    return recorder, TestClient(EdgeGuard(recorder))


def _names(seen: list[tuple[bytes, bytes]]) -> set[bytes]:
    return {name for name, _ in seen}


def _signed(key: str, method: str = "GET", target: str = "/api/v1/cases") -> str:
    """One assertion under `key` for one request, as the edge would set it
    (§93); every case here that reaches the app needs its own."""
    return sign_assertion(
        key.encode(),
        subject=str(uuid4()),
        groups=("caos-analysts",),
        method=method,
        target=target,
        issued_at=int(time.time()),
        nonce=secrets.token_hex(16),
    )


def test_edge_mode_refuses_a_request_without_an_assertion_before_routing(
    token: str,
) -> None:
    recorder, client = _guarded()
    wrong_key = _signed(token[:-1] + "x", "POST")
    for headers in ({}, {EDGE_ASSERTION_HEADER: wrong_key}):
        response = client.post("/api/v1/cases", headers=headers, json={})
        assert response.status_code == 403
        assert response.json()["code"] == RefusalCode.EDGE_NOT_TRUSTED
    signed = _signed(token)
    doubled = client.get(
        "/api/v1/cases",
        headers=[(EDGE_ASSERTION_HEADER, signed), (EDGE_ASSERTION_HEADER, signed)],
    )
    assert doubled.status_code == 403
    assert recorder.seen == []
    # A forged identity on the real app, directly, never reaches identity.
    real = TestClient(app).get(
        "/api/v1/cases", headers={"x-caos-user": str(uuid4()), "x-caos-role": "ADMIN"}
    )
    assert (real.status_code, real.json()["code"]) == (403, "EDGE_NOT_TRUSTED")

    admitted = client.get(
        "/api/v1/cases",
        headers={EDGE_ASSERTION_HEADER: _signed(token), "sec-fetch-site": "none"},
    )
    assert admitted.status_code == 200
    assert len(recorder.seen) == 1


def test_the_edge_key_never_reaches_the_app_a_log_or_a_refusal(
    token: str, caplog: pytest.LogCaptureFixture
) -> None:
    recorder, client = _guarded()
    caplog.set_level(logging.DEBUG)
    signed = _signed(token, target="/anything")
    client.get("/anything", headers={EDGE_ASSERTION_HEADER: signed})
    assert EDGE_ASSERTION_HEADER.encode() not in _names(recorder.seen[0])
    wrong = client.get("/anything", headers={EDGE_ASSERTION_HEADER: signed + "!"})
    for secret in (token, signed):
        assert secret not in wrong.text and secret not in str(wrong.headers)
        assert secret not in caplog.text


def test_health_needs_no_edge_token_and_no_identity(token: str) -> None:
    recorder, client = _guarded()
    assert client.get("/api/health").status_code == 200
    assert client.head("/api/health").status_code == 200
    assert client.post("/api/health").status_code == 403
    assert len(recorder.seen) == 2


def test_boot_refuses_the_trust_switch_alongside_an_edge_token(
    token: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    for value in ("1", "0", ""):
        monkeypatch.setenv(TRUST_SWITCH, value)
        with pytest.raises(Refusal) as caught:
            resolve_mode()
        assert caught.value.code is RefusalCode.EDGE_CONFIG_INVALID
    with pytest.raises(Refusal) as booted, TestClient(EdgeGuard(Recorder())):
        pass
    assert booted.value.code is RefusalCode.EDGE_CONFIG_INVALID
    # A request under a configuration that would not boot is not trusted.
    response = TestClient(EdgeGuard(Recorder())).get(
        "/api/v1/cases", headers={EDGE_ASSERTION_HEADER: _signed(token)}
    )
    assert response.status_code == 403


def test_boot_refuses_a_short_token_or_a_missing_public_origin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(TRUST_SWITCH, raising=False)
    long = secrets.token_urlsafe(32)
    for edge_token, origin in (
        ("", PUBLIC),
        ("x" * 31, PUBLIC),
        (long, None),
        (long, ""),
        (long, "caos.example.test"),
        (long, PUBLIC + "/"),
        (long, "https://user@caos.example.test"),
        (long, "ftp://caos.example.test"),
    ):
        monkeypatch.setenv(EDGE_TOKEN_ENV, edge_token)
        if origin is None:
            monkeypatch.delenv(PUBLIC_ORIGIN_ENV, raising=False)
        else:
            monkeypatch.setenv(PUBLIC_ORIGIN_ENV, origin)
        with pytest.raises(Refusal) as caught:
            resolve_mode()
        assert caught.value.code is RefusalCode.EDGE_CONFIG_INVALID
    monkeypatch.setenv(PUBLIC_ORIGIN_ENV, PUBLIC)
    assert resolve_mode() == EdgeMode(key=long.encode(), public_origin=PUBLIC)
    monkeypatch.delenv(EDGE_TOKEN_ENV)
    assert resolve_mode() == EdgeMode(key=None, public_origin=None)


def test_edge_mode_never_believes_the_role_header(
    token: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    subject = str(uuid4())
    monkeypatch.setenv(TRUST_SWITCH, "1")
    claimed = {"x-caos-user": subject, "x-caos-role": "ADMIN"}
    assert actor_from_headers(claimed).role is GlobalRole.READER
    monkeypatch.delenv(EDGE_TOKEN_ENV)
    assert actor_from_headers(claimed).role is GlobalRole.ADMIN


def test_dev_mode_serves_only_loopback_peers_with_a_loopback_host(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(EDGE_TOKEN_ENV, raising=False)
    recorder = Recorder()
    guard = EdgeGuard(recorder)
    for host in ("localhost:8000", "127.0.0.1", "[::1]:5173"):
        served = TestClient(guard).get("/x", headers={"host": host})
        assert served.status_code == 200, host
    refused = [
        TestClient(guard, client=("203.0.113.9", 4000)).get("/x"),
        TestClient(guard, base_url="http://10.0.0.2:8000").get(
            "/x", headers={"host": "localhost"}
        ),
        TestClient(guard).get("/x", headers={"host": "rebind.example.test"}),
        TestClient(guard).get("/x", headers={"host": "localhost.example.test"}),
        TestClient(guard, client=("testclient", 50000)).get("/x"),
    ]
    assert [r.status_code for r in refused] == [403] * len(refused)
    assert {r.json()["code"] for r in refused} == {"EDGE_NOT_TRUSTED"}
    assert len(recorder.seen) == 3
    # An image started without a token still answers health to anyone.
    far = TestClient(guard, client=("203.0.113.9", 4000))
    assert far.get("/api/health", headers={"host": "caos.example.test"}).is_success


def test_a_repeated_identity_header_is_not_authenticated() -> None:
    recorder, client = _guarded()
    for name in ("x-caos-user", "x-forwarded-groups", "x-caos-role"):
        response = client.get(
            "/api/v1/cases", headers=[(name, str(uuid4())), (name, str(uuid4()))]
        )
        assert response.status_code == 401
        assert response.json()["code"] == RefusalCode.NOT_AUTHENTICATED
    assert recorder.seen == []


def test_an_underscore_lookalike_identity_header_is_not_authenticated() -> None:
    recorder, client = _guarded()
    for name in ("x_caos_user", "x-forwarded_groups", "X_CAOS_ROLE"):
        response = client.get("/api/v1/cases", headers=[(name, "value")])
        assert response.status_code == 401, name
    assert recorder.seen == []


def test_a_cross_site_or_same_site_api_request_is_origin_refused() -> None:
    recorder, client = _guarded()
    for site in ("cross-site", "same-site"):
        for method in ("GET", "POST"):
            response = client.request(
                method, "/api/v1/cases", headers={"sec-fetch-site": site}
            )
            assert response.status_code == 403
            assert response.json()["code"] == RefusalCode.ORIGIN_REFUSED
    assert (
        client.get("/api", headers={"sec-fetch-site": "cross-site"}).status_code == 403
    )
    # Outside `/api`, a navigation from another site loads the page.
    assert client.get("/run/", headers={"sec-fetch-site": "cross-site"}).is_success
    assert client.get(
        "/api/health", headers={"sec-fetch-site": "cross-site"}
    ).is_success
    assert len(recorder.seen) == 2


def test_an_unsafe_api_request_needs_the_public_origin_or_a_same_origin_fetch(
    token: str,
) -> None:
    recorder, client = _guarded()
    del client.headers["sec-fetch-site"]

    def edge(method: str = "POST") -> dict[str, str]:
        return {EDGE_ASSERTION_HEADER: _signed(token, method)}

    refused = [
        client.post("/api/v1/cases", headers=edge()),
        client.post("/api/v1/cases", headers={**edge(), "sec-fetch-site": "none"}),
        client.post("/api/v1/cases", headers={**edge(), "origin": "https://evil.test"}),
        client.post("/api/v1/cases", headers={**edge(), "origin": "null"}),
        client.post(
            "/api/v1/cases",
            headers={
                **edge(),
                "sec-fetch-site": "same-origin",
                "origin": "http://127.0.0.1:8000",
            },
        ),
        client.get(
            "/api/v1/cases", headers={**edge("GET"), "origin": "https://evil.test"}
        ),
    ]
    assert [r.status_code for r in refused] == [403] * len(refused)
    assert {r.json()["code"] for r in refused} == {"ORIGIN_REFUSED"}
    assert recorder.seen == []

    admitted = [
        client.post("/api/v1/cases", headers={**edge(), "origin": PUBLIC}),
        client.post(
            "/api/v1/cases", headers={**edge(), "sec-fetch-site": "same-origin"}
        ),
        client.get("/api/v1/cases", headers={**edge("GET"), "sec-fetch-site": "none"}),
        client.get("/api/v1/cases", headers=edge("GET")),
    ]
    assert all(r.status_code == 200 for r in admitted)


def test_no_response_sets_a_cookie_or_a_cors_header() -> None:
    async def leaky(scope: Scope, receive: Receive, send: Send) -> None:
        headers = [
            (b"set-cookie", b"session=1"),
            (b"access-control-allow-origin", b"*"),
            (b"access-control-allow-credentials", b"true"),
        ]
        await send({"type": "http.response.start", "status": 200, "headers": headers})
        await send({"type": "http.response.body", "body": b""})

    responses = [
        TestClient(EdgeGuard(leaky)).get("/api/v1/cases"),
        TestClient(app).get("/api/v1/cases", headers={"origin": "https://evil.test"}),
        TestClient(app).options("/api/v1/cases"),
    ]
    for response in responses:
        names = {name.lower() for name in response.headers}
        assert "set-cookie" not in names
        assert not any(name.startswith("access-control-") for name in names)


def test_every_response_carries_the_security_headers_and_the_policy(
    token: str,
) -> None:
    csp = SECURITY_HEADERS["content-security-policy"]
    assert "default-src 'none'" in csp and "trusted-types 'none'" in csp
    client = TestClient(app)
    events = f"/api/v1/cases/{uuid4()}/events"
    # An assertion whose subject is no identifier: verified by the guard,
    # refused by identity, so the app answers 401 without a store.
    nobody = sign_assertion(
        token.encode(),
        subject="nobody",
        groups=(),
        method="GET",
        target=events,
        issued_at=int(time.time()),
        nonce=secrets.token_hex(16),
    )
    responses = {
        "refused": client.get("/api/v1/cases"),
        "health": client.get("/api/health"),
        "unauthenticated": client.get(events, headers={EDGE_ASSERTION_HEADER: nobody}),
        "not-found": client.get(
            "/api/v2/nothing",
            headers={EDGE_ASSERTION_HEADER: _signed(token, target="/api/v2/nothing")},
        ),
        "site": client.get(
            "/index.html",
            headers={EDGE_ASSERTION_HEADER: _signed(token, target="/index.html")},
        ),
    }
    for label, response in responses.items():
        for name, value in SECURITY_HEADERS.items():
            assert response.headers.get(name) == value, (label, name)
    for label in ("refused", "health", "unauthenticated", "not-found"):
        assert responses[label].headers["cache-control"] == "no-store", label
    assert responses["site"].headers["cache-control"] == "no-cache"
    _, recorder_client = _guarded()
    asset = recorder_client.get(
        "/assets/app.js",
        headers={EDGE_ASSERTION_HEADER: _signed(token, target="/assets/app.js")},
    )
    assert asset.headers["cache-control"] == "public, max-age=31536000, immutable"


def test_openapi_and_docs_are_not_served() -> None:
    client = TestClient(app)
    for path in ("/docs", "/redoc", "/openapi.json", "/docs/oauth2-redirect"):
        assert client.get(path).status_code == 404, path
    assert (app.docs_url, app.redoc_url, app.openapi_url) == (None, None, None)


def test_an_unhandled_fault_answers_a_secured_constant_500() -> None:
    faulty = FastAPI()
    faulty.add_middleware(EdgeGuard)

    @faulty.get("/api/v1/fault")
    def fault() -> None:
        text = "secret document text"
        raise RuntimeError(text)

    response = TestClient(faulty, raise_server_exceptions=False).get("/api/v1/fault")
    assert response.status_code == 500
    assert response.json() == {
        "code": "INTERNAL_FAULT",
        "clears": CLEARS[RefusalCode.INTERNAL_FAULT],
    }
    assert "secret" not in response.text
    for name, value in SECURITY_HEADERS.items():
        assert response.headers.get(name) == value, name
    assert response.headers["cache-control"] == "no-store"
    with pytest.raises(RuntimeError):
        TestClient(faulty).get("/api/v1/fault")


def test_the_process_entry_answers_an_unhandled_fault_in_the_typed_body(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """ED-2. `caos.serve` serves `caos.api.site:application`, where the app's
    own guard sits behind the outer one and passed straight through: the fault
    reached Starlette's `ServerErrorMiddleware`, which answered `text/plain`
    "Internal Server Error" before the outer guard could, and the typed body
    never arrived. The inner guard answers first now, and the fault is logged
    once, as its class and frame."""
    from caos.api import app as app_module
    from caos.api.site import SITE_ROOT_ENV, application

    def raising() -> Iterator[None]:
        text = "secret document text"
        raise RuntimeError(text)
        yield

    monkeypatch.setenv(TRUST_SWITCH, "1")
    monkeypatch.delenv(SITE_ROOT_ENV, raising=False)
    app.dependency_overrides[app_module.store_connection] = raising
    try:
        client = TestClient(
            application,
            base_url="http://127.0.0.1:8000",
            client=("127.0.0.1", 50000),
            raise_server_exceptions=False,
        )
        response = client.get(
            "/api/v1/directory",
            headers={"x-caos-user": str(uuid4()), "sec-fetch-site": "same-origin"},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 500
    assert response.headers["content-type"] == "application/json"
    assert response.json() == {
        "code": "INTERNAL_FAULT",
        "clears": CLEARS[RefusalCode.INTERNAL_FAULT],
    }
    assert "secret" not in response.text
    for name, value in SECURITY_HEADERS.items():
        assert response.headers.get(name) == value, name
    logged = capsys.readouterr().err
    [fault] = [line for line in logged.splitlines() if "RuntimeError" in line]
    assert fault.startswith("RuntimeError at ")
    assert "secret" not in logged


def test_is_api_path_matches_the_root_and_everything_under_it() -> None:
    assert is_api_path("/api") is True
    assert is_api_path("/api/v1/cases") is True
    assert is_api_path("/apidoc") is False
    assert is_api_path("/") is False


def test_refusal_body_carries_the_code_and_its_constant_clearance() -> None:
    import json

    body = refusal_body(RefusalCode.ORIGIN_REFUSED)

    assert json.loads(body) == {
        "code": "ORIGIN_REFUSED",
        "clears": CLEARS[RefusalCode.ORIGIN_REFUSED],
    }


def test_startup_failed_answers_only_a_lifespan_startup_message() -> None:
    import asyncio
    from collections.abc import MutableMapping
    from typing import Any

    sent: list[MutableMapping[str, Any]] = []

    async def receive() -> MutableMapping[str, Any]:
        return {"type": "lifespan.startup"}

    async def send(message: MutableMapping[str, Any]) -> None:
        sent.append(message)

    asyncio.run(startup_failed(receive, send))

    assert sent == [
        {
            "type": "lifespan.startup.failed",
            "message": RefusalCode.EDGE_CONFIG_INVALID.value,
        }
    ]


def test_startup_failed_ignores_a_non_startup_message() -> None:
    import asyncio
    from collections.abc import MutableMapping
    from typing import Any

    sent: list[MutableMapping[str, Any]] = []

    async def receive() -> MutableMapping[str, Any]:
        return {"type": "lifespan.shutdown"}

    async def send(message: MutableMapping[str, Any]) -> None:
        sent.append(message)

    asyncio.run(startup_failed(receive, send))

    assert sent == []

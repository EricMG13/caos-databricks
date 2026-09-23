"""Repair Phase 4, slice 4.5a1: the edge guard in front of every request.

Task 4.5 brief, decisions 2 to 6 and authority trace A1-A6, A8 and A10. The
guard is pure ASGI, so most of these drive it over a recording app that shows
exactly what reached the application; the rest ask the real app, on paths that
answer before any store connection.
"""

from __future__ import annotations

from collections.abc import Iterator
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.types import Receive, Scope, Send

from caos.api import edge, identity
from caos.api.app import app
from caos.api.edge import (
    PUBLIC_ORIGIN_ENV,
    SECURITY_HEADERS,
    EdgeGuard,
    EdgeMode,
    is_api_path,
    refusal_body,
    resolve_mode,
    startup_failed,
)
from caos.api.identity import TRUST_SWITCH
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
def public_origin(monkeypatch: pytest.MonkeyPatch) -> None:
    """Platform mode with a declared public origin (D10): the only surviving
    way to exercise `_origin_allowed`'s fixed-origin branch now that edge
    mode, the other way a deployment used to declare one, is gone."""
    monkeypatch.setenv(edge.PLATFORM_ENV, "caos")
    monkeypatch.setenv(identity.WORKSPACE_ENV, "1234")
    monkeypatch.setenv(PUBLIC_ORIGIN_ENV, PUBLIC)


def _guarded() -> tuple[Recorder, TestClient]:
    recorder = Recorder()
    return recorder, TestClient(EdgeGuard(recorder))


def test_dev_mode_serves_only_loopback_peers_with_a_loopback_host() -> None:
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


def test_dev_mode_honours_a_declared_public_origin_off_the_conventional_ports(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CF-056. `DEV_ORIGINS` names only the conventional vite-plus-loopback-API
    pair (5173 and 8000); a developer whose ports differ could not make an
    unsafe command of their own origin succeed. `CAOS_PUBLIC_ORIGIN`, already
    read this way in platform mode, is honoured in dev mode too."""
    monkeypatch.delenv(PUBLIC_ORIGIN_ENV, raising=False)
    assert resolve_mode() == EdgeMode(public_origin=None)

    other = "http://localhost:9000"
    monkeypatch.setenv(PUBLIC_ORIGIN_ENV, other)
    assert resolve_mode() == EdgeMode(public_origin=other)

    recorder, client = _guarded()
    del client.headers["sec-fetch-site"]
    refused = client.post("/api/v1/cases", headers={"origin": PUBLIC})
    assert refused.status_code == 403
    assert refused.json()["code"] == "ORIGIN_REFUSED"
    assert recorder.seen == []
    admitted = client.post("/api/v1/cases", headers={"origin": other})
    assert admitted.status_code == 200

    monkeypatch.setenv(PUBLIC_ORIGIN_ENV, "not-an-origin")
    with pytest.raises(Refusal) as caught:
        resolve_mode()
    assert caught.value.code is RefusalCode.EDGE_CONFIG_INVALID


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
    public_origin: None,
) -> None:
    recorder, client = _guarded()
    del client.headers["sec-fetch-site"]

    refused = [
        client.post("/api/v1/cases"),
        client.post("/api/v1/cases", headers={"sec-fetch-site": "none"}),
        client.post("/api/v1/cases", headers={"origin": "https://evil.test"}),
        client.post("/api/v1/cases", headers={"origin": "null"}),
        client.post(
            "/api/v1/cases",
            headers={
                "sec-fetch-site": "same-origin",
                "origin": "http://127.0.0.1:8000",
            },
        ),
        client.get("/api/v1/cases", headers={"origin": "https://evil.test"}),
    ]
    assert [r.status_code for r in refused] == [403] * len(refused)
    assert {r.json()["code"] for r in refused} == {"ORIGIN_REFUSED"}
    assert recorder.seen == []

    admitted = [
        client.post("/api/v1/cases", headers={"origin": PUBLIC}),
        client.post("/api/v1/cases", headers={"sec-fetch-site": "same-origin"}),
        client.get("/api/v1/cases", headers={"sec-fetch-site": "none"}),
        client.get("/api/v1/cases"),
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


def test_every_response_carries_the_security_headers_and_the_policy() -> None:
    csp = SECURITY_HEADERS["content-security-policy"]
    assert "default-src 'none'" in csp and "trusted-types 'none'" in csp
    client = TestClient(app)
    events = f"/api/v1/cases/{uuid4()}/events"
    responses = {
        "refused": client.get("/api/v1/cases"),
        "health": client.get("/api/health"),
        # No identifier at all: dev mode's own loopback rule admits the
        # request, and identity refuses the subject, so the app answers 401
        # without a store.
        "unauthenticated": client.get(events, headers={"x-caos-user": "nobody"}),
        "not-found": client.get("/api/v2/nothing"),
        "site": client.get("/index.html"),
    }
    for label, response in responses.items():
        for name, value in SECURITY_HEADERS.items():
            assert response.headers.get(name) == value, (label, name)
    for label in ("refused", "health", "unauthenticated", "not-found"):
        assert responses[label].headers["cache-control"] == "no-store", label
    assert responses["site"].headers["cache-control"] == "no-cache"
    _, recorder_client = _guarded()
    asset = recorder_client.get("/assets/app.js")
    assert asset.headers["cache-control"] == "public, max-age=31536000, immutable"


def test_the_immutable_asset_cache_is_never_set_on_a_refusal() -> None:
    """CF-087. `_secured` used to pick the cache policy from the path alone,
    before the response existed: a 404 or a refusal under `/assets/` carried
    the same year-long `immutable` policy as a real file, so a browser that
    ever saw one cached it forever. Only 200 and 304 earn it."""
    client = TestClient(app)
    missing = client.get("/assets/does-not-exist.js")
    assert missing.status_code == 404
    assert missing.headers["cache-control"] != "public, max-age=31536000, immutable"
    assert missing.headers["cache-control"] == "no-store"


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

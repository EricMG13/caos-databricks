"""Repair Phase 4, slice 4.5a2: the site entry in front of the API and export.

Task 4.5 brief, decision 7. `caos.api.site:application` is the one ASGI
entry the image serves: the edge guard outermost, `/api` to the FastAPI app with
its lifespan, and every other path a GET/HEAD-only read of the static export
that lists no directory, leaves no root and follows no symlink out of it.
"""

from __future__ import annotations

import asyncio
import json
import re
import socket
import threading
import time
from collections.abc import Iterator
from pathlib import Path

import httpx2 as httpx
import pytest
import uvicorn
from fastapi.testclient import TestClient
from starlette.types import Message

from caos.api import health
from caos.api.app import app
from caos.api.deps import DATABASE_URL
from caos.api.edge import PLATFORM_ENV, SECURITY_HEADERS
from caos.api.identity import WORKSPACE_ENV
from caos.api.site import (
    MANIFEST,
    MANIFEST_CAP,
    SECTIONS,
    SITE_ROOT_ENV,
    _complete,
    application,
    dispatch,
)
from caos.refusals import Refusal, RefusalCode

INDEX = b"<!doctype html><title>CAOS</title><div id=root></div>"
CASE = "8c0d2b7e-3f7a-4e53-9a53-2f4f4c1b7a10"
RUN = "1f6a3c55-8e0b-4b8e-a4ad-6f2d1c9e0b42"


def _write_manifest(root: Path, entries: object) -> None:
    """Vite's `build.manifest` shape: entry key to its file, styles, assets."""
    (root / MANIFEST).parent.mkdir(parents=True, exist_ok=True)
    (root / MANIFEST).write_text(json.dumps(entries), encoding="utf-8")


@pytest.fixture
def site(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    root = tmp_path / "site"
    (root / "assets").mkdir(parents=True)
    (root / "index.html").write_bytes(INDEX)
    (root / "assets" / "app.js").write_bytes(b"export {};")
    _write_manifest(root, {"index.html": {"file": "assets/app.js", "isEntry": True}})
    (root / "api").mkdir()
    (root / "api" / "index.html").write_bytes(b"shadow")
    (tmp_path / "secret.txt").write_bytes(b"outside the export")
    monkeypatch.setenv(SITE_ROOT_ENV, str(root))
    yield root


def _secured(response: httpx.Response) -> None:
    for name, value in SECURITY_HEADERS.items():
        assert response.headers[name] == value
    assert "set-cookie" not in response.headers


async def _ask(path: str, method: str = "GET") -> tuple[int, bytes]:
    """Ask the entry with a path no client library normalises first."""
    sent: list[Message] = []

    async def receive() -> Message:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: Message) -> None:
        sent.append(message)

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": method,
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "root_path": "",
        "query_string": b"",
        "headers": [(b"host", b"127.0.0.1:8000")],
        "client": ("127.0.0.1", 50000),
        "server": ("127.0.0.1", 8000),
    }
    await application(scope, receive, send)
    start = next(m for m in sent if m["type"] == "http.response.start")
    body = b"".join(
        m.get("body", b"") for m in sent if m["type"] == "http.response.body"
    )
    return start["status"], body


def _raw(path: str, method: str = "GET") -> tuple[int, bytes]:
    return asyncio.run(_ask(path, method))


async def _dispatched(path: str, host: bytes) -> tuple[int, list[tuple[bytes, bytes]]]:
    """`dispatch` directly, past the edge guard: platform mode admits any
    `Host` (`_dev_peer`'s loopback check is dev mode's alone), so the guard
    is not what stands between a directory request and a redirect."""
    sent: list[Message] = []

    async def receive() -> Message:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: Message) -> None:
        sent.append(message)

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "root_path": "",
        "query_string": b"",
        "headers": [(b"host", host)],
        "client": ("127.0.0.1", 50000),
        "server": ("127.0.0.1", 8000),
    }
    await dispatch(scope, receive, send)
    start = next(m for m in sent if m["type"] == "http.response.start")
    return start["status"], list(start.get("headers", []))


def test_a_directory_request_is_never_redirected(site: Path) -> None:
    """CF-086, then C1. Starlette's own directory redirect built its
    `Location` from the request's `Host` (CF-086); the relative rewrite that
    replaced it kept the request's path, and a path uvicorn decoded from
    `/%2Fevil.example%2F..` was the scheme-relative `//evil.example/../`
    (C1). The export never redirects: a directory without its slash is 404,
    whatever `Host` or path asked for it, and with its slash it serves its
    own index."""
    (site / "docs").mkdir()
    (site / "docs" / "index.html").write_bytes(b"nested")

    for path in ("/docs", "//evil.example/..", "/assets/.."):
        status, headers = asyncio.run(_dispatched(path, host=b"evil.example.com"))
        assert status == 404, path
        assert b"location" not in dict(headers), path
    assert _raw("/docs/") == (200, b"nested")


def _served_on_a_socket() -> tuple[uvicorn.Server, threading.Thread, int]:
    """`caos.api.site:application` under a real uvicorn, as `caos.serve` runs
    it (`proxy_headers=False`): the request target reaches it percent-decoded
    by uvicorn itself, which no test client reproduces."""
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    port = int(listener.getsockname()[1])
    server = uvicorn.Server(
        uvicorn.Config(
            application, lifespan="off", log_level="warning", proxy_headers=False
        )
    )
    thread = threading.Thread(
        target=server.run, kwargs={"sockets": [listener]}, daemon=True
    )
    thread.start()
    while not server.started:
        time.sleep(0.01)
    return server, thread, port


def _raw_get(port: int, target: str, host: str) -> tuple[str, str | None]:
    with socket.create_connection(("127.0.0.1", port), timeout=10) as sock:
        request = f"GET {target} HTTP/1.1\r\nHost: {host}\r\nConnection: close\r\n"
        sock.sendall(f"{request}\r\n".encode())
        answer = b""
        while received := sock.recv(65536):
            answer += received
    head = answer.split(b"\r\n\r\n", 1)[0].decode("latin-1").splitlines()
    location = next(
        (
            line.split(":", 1)[1].strip()
            for line in head
            if line.lower().startswith("location:")
        ),
        None,
    )
    return head[0], location


@pytest.mark.parametrize("platform", [False, True], ids=["dev", "platform"])
def test_no_request_target_redirects_off_the_app_origin(
    site: Path, monkeypatch: pytest.MonkeyPatch, platform: bool
) -> None:
    """C1, over a real socket in both modes: `%2F` in the target is decoded by
    uvicorn to a path starting `//`, which the export normalised to its root
    and answered with a scheme-relative `Location` that a browser follows to
    another host, the query (an OAuth `code`, say) carried along."""
    port_host = "caos-1.aws.databricksapps.com"
    if platform:
        monkeypatch.setenv(PLATFORM_ENV, "caos")
        monkeypatch.setenv(WORKSPACE_ENV, "1")
    server, thread, port = _served_on_a_socket()
    host = port_host if platform else f"127.0.0.1:{port}"
    try:
        for target in (
            "/%2Fevil.example%2F..",
            "/%2F%2Fevil.example%2F..",
            "/%2Fevil.example%2F..?code=abc&state=xyz",
            "/%5Cevil.example%2F..",
            "/%2F%5Cevil.example%2F..",
        ):
            status, location = _raw_get(port, target, host)
            assert location is None, (target, status, location)
            assert status.split()[1] in {"200", "404"}, (target, status)
    finally:
        server.should_exit = True
        thread.join(10)


@pytest.mark.parametrize("platform", [False, True], ids=["dev", "platform"])
def test_no_api_path_redirects_either(
    site: Path, monkeypatch: pytest.MonkeyPatch, platform: bool
) -> None:
    """C1's sibling on the API: routing answered a declared path asked for with
    a trailing slash with a 307 to the same path without it, built from the
    request's own `Host` over `http` -- behind the platform, whatever `Host`
    the request named, and a downgrade from the TLS the proxy terminated. The
    API redirects nothing: an undeclared spelling is `ENDPOINT_NOT_FOUND`."""
    if platform:
        monkeypatch.setenv(PLATFORM_ENV, "caos")
        monkeypatch.setenv(WORKSPACE_ENV, "1")
    server, thread, port = _served_on_a_socket()
    host = "evil.example" if platform else f"127.0.0.1:{port}"
    try:
        for target in ("/api/health/", "/api/v1/directory/", "/api/v1/cases/"):
            status, location = _raw_get(port, target, host)
            assert location is None, (target, status, location)
            assert status.split()[1] == "404", (target, status)
    finally:
        server.should_exit = True
        thread.join(10)


def test_section_deep_links_serve_the_export_with_their_query(site: Path) -> None:
    client = TestClient(application)
    for link in (
        "/",
        "/directory/",
        f"/upload/?case={CASE}",
        f"/run/?case={CASE}&run={RUN}",
        f"/analysis/?case={CASE}&run={RUN}",
    ):
        response = client.get(link, follow_redirects=False)
        assert response.status_code == 200, link
        assert response.content == INDEX, link
        assert response.headers["content-type"].startswith("text/html")
        assert response.headers["cache-control"] == "no-cache"
        _secured(response)
    head = client.head(f"/run/?case={CASE}&run={RUN}")
    assert head.status_code == 200
    assert head.content == b""
    asset = client.get("/assets/app.js")
    assert asset.status_code == 200
    assert asset.content == b"export {};"
    assert asset.headers["cache-control"] == "public, max-age=31536000, immutable"
    _secured(asset)
    # An unknown section is not quietly the workspace.
    assert client.get("/not-a-section/").status_code == 404


def test_a_wrong_method_on_an_api_path_still_answers_endpoint_not_found(
    site: Path,
) -> None:
    client = TestClient(application)
    for method, path, status in (
        ("DELETE", "/api/health", 405),
        ("GET", "/api/not-declared", 404),
        ("GET", "/api/", 404),
        ("GET", "/api", 404),
    ):
        response = client.request(method, path)
        assert response.status_code == status, path
        assert response.json()["code"] == RefusalCode.ENDPOINT_NOT_FOUND, path
        assert response.headers["cache-control"] == "no-store"
        _secured(response)


def test_site_paths_refuse_traversal_symlinks_and_unsafe_methods(
    site: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (site / "leak.txt").symlink_to(site.parent / "secret.txt")
    (site / "listed").mkdir()
    (site / "listed" / "file.txt").write_bytes(b"x")
    for path in ("/../secret.txt", "/assets/../../secret.txt", "/leak.txt"):
        status, body = _raw(path)
        assert status == 404, path
        assert b"outside the export" not in body
    for directory in ("/assets/", "/listed/"):
        status, body = _raw(directory)
        assert status == 404, directory
        assert b"file.txt" not in body and b"app.js" not in body
    for method in ("POST", "PUT", "DELETE", "PATCH", "OPTIONS"):
        status, body = _raw("/directory/", method)
        assert (status, body) == (405, b""), method
    monkeypatch.delenv(SITE_ROOT_ENV)
    assert _raw("/directory/") == (404, b"")


def test_the_api_lifespan_runs_through_the_site_application(
    site: Path, empty_database: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    started: list[health.ProbeState] = []

    async def counted(state: health.ProbeState) -> None:
        started.append(state)

    monkeypatch.setattr(health, "probe_loop", counted)
    monkeypatch.delenv(DATABASE_URL, raising=False)
    with pytest.raises(Refusal) as unconfigured, TestClient(application):
        pass
    assert unconfigured.value.code is RefusalCode.STORE_NOT_CONFIGURED
    monkeypatch.setenv(DATABASE_URL, empty_database)
    with TestClient(application) as client:
        _secured(client.get("/directory/"))
    assert len(started) == 1
    assert app.state.health is started[0]
    # An export without its index refuses boot before the app starts.
    (site / "index.html").unlink()
    with pytest.raises(Refusal) as missing, TestClient(application):
        pass
    assert missing.value.code is RefusalCode.EDGE_CONFIG_INVALID
    assert len(started) == 1


def test_an_export_missing_a_file_its_index_names_refuses_boot(
    site: Path, empty_database: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """DF-4: a sync that dropped the export's scripts or styles shipped an index
    that served 200 and drew nothing while health answered `ready`. Boot now
    holds the index to every file it names."""

    async def idle(state: health.ProbeState) -> None:
        del state

    monkeypatch.setattr(health, "probe_loop", idle)
    monkeypatch.setenv(DATABASE_URL, empty_database)
    (site / "index.html").write_bytes(
        b'<!doctype html><script type="module" src="/assets/app.js"></script>'
        b'<link rel="stylesheet" href="/assets/app.css">'
        b'<link rel="preconnect" href="//fonts.example">'
    )
    with pytest.raises(Refusal) as missing, TestClient(application):
        pass
    assert missing.value.code is RefusalCode.EDGE_CONFIG_INVALID
    (site / "assets" / "app.css").write_bytes(b"")
    with TestClient(application) as client:
        _secured(client.get("/directory/"))


def test_an_export_missing_a_lazy_section_view_refuses_boot(
    site: Path, empty_database: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """N92: since F317 each section view is its own file, loaded when its
    section opens, and the index names none of them; an export missing one
    booted `ready` and drew that section as a failed load. Boot now holds
    the export to every file the build's manifest names as well."""

    async def idle(state: health.ProbeState) -> None:
        del state

    monkeypatch.setattr(health, "probe_loop", idle)
    monkeypatch.setenv(DATABASE_URL, empty_database)
    lazy = "src/sections/analysis/AnalysisSection.tsx"
    _write_manifest(
        site,
        {
            "index.html": {
                "file": "assets/app.js",
                "isEntry": True,
                "dynamicImports": [lazy],
                "css": ["assets/app.css"],
                "assets": ["assets/font.woff2"],
            },
            lazy: {"file": "assets/AnalysisSection.js", "isDynamicEntry": True},
        },
    )
    (site / "assets" / "app.css").write_bytes(b"")
    (site / "assets" / "font.woff2").write_bytes(b"")
    with pytest.raises(Refusal) as missing, TestClient(application):
        pass
    assert missing.value.code is RefusalCode.EDGE_CONFIG_INVALID
    (site / "assets" / "AnalysisSection.js").write_bytes(b"export {};")
    with TestClient(application) as client:
        _secured(client.get("/analysis/"))
        # The manifest is the server's record of the export, never served: it
        # names the build's source paths.
        assert client.get("/.vite/manifest.json").status_code == 404
        assert client.get("/assets/AnalysisSection.js").status_code == 200


@pytest.mark.parametrize(
    "manifest",
    [
        None,
        b"",
        b"{not json",
        b"\xff\xfe",
        b"[" * 100_000 + b"]" * 100_000,
        b"[]",
        b"{}",
        b'{"src/main.tsx": {"file": "assets/app.js"}}',
        b'{"index.html": "assets/app.js"}',
        b'{"index.html": {"isEntry": true}}',
        b'{"index.html": {"file": ""}}',
        b'{"index.html": {"file": "assets/app.js", "css": "assets/app.js"}}',
        b'{"index.html": {"file": "assets/app.js", "assets": [7]}}',
        b'{"index.html": {"file": "../secret.txt"}}',
        b'{"index.html": {"file": "/etc/hosts"}}',
        b'{"index.html": {"file": ".vite/manifest.json"}}',
    ],
    ids=[
        "missing",
        "empty",
        "not-json",
        "not-utf8",
        "too-deep",
        "not-an-object",
        "no-entries",
        "no-index-entry",
        "entry-not-an-object",
        "entry-without-file",
        "empty-file",
        "css-not-a-list",
        "asset-not-a-name",
        "outside-the-root",
        "absolute",
        "a-dot-file",
    ],
)
def test_a_missing_or_malformed_manifest_is_not_a_complete_export(
    site: Path, manifest: bytes | None
) -> None:
    """N92: the manifest fails closed. Missing, unreadable, not JSON, not
    Vite's shape, without the index's own entry, or naming a path the export
    would not serve: each is an export boot refuses."""
    assert _complete(site)
    if manifest is None:
        (site / MANIFEST).unlink()
    else:
        (site / MANIFEST).write_bytes(manifest)
    assert not _complete(site)


def test_a_manifest_past_its_cap_is_not_read(site: Path) -> None:
    """N92: the boot read is bounded; a manifest past `MANIFEST_CAP` is not
    the build's, and is refused without being parsed."""
    entry = b'{"index.html": {"file": "assets/app.js"}}'
    padding = b" " * (MANIFEST_CAP - len(entry))
    (site / MANIFEST).write_bytes(entry + padding)
    assert _complete(site)
    (site / MANIFEST).write_bytes(entry + padding + b" ")
    assert not _complete(site)


def test_the_deep_link_sections_are_the_workspace_sections() -> None:
    """`site.SECTIONS` is copied from the workspace's list; a section added there
    and not here would deep-link to a 404 in the production image."""
    shared = Path(__file__).resolve().parents[1] / "frontend/src/wire/shared.ts"
    text = shared.read_text(encoding="utf-8")
    block = text[text.index("export const SECTIONS = [") : text.index("] as const;")]
    assert tuple(re.findall(r'"([a-z]+)"', block)) == SECTIONS

"""Repair Phase 4, slice 4.5a2: the site entry in front of the API and export.

Task 4.5 brief, decision 7. `caos.api.site:application` is the one ASGI
entry the image serves: the edge guard outermost, `/api` to the FastAPI app with
its lifespan, and every other path a GET/HEAD-only read of the static export
that lists no directory, leaves no root and follows no symlink out of it.
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import Iterator
from pathlib import Path

import httpx2 as httpx
import pytest
from fastapi.testclient import TestClient
from starlette.types import Message

from caos.api import health
from caos.api.app import app
from caos.api.deps import DATABASE_URL
from caos.api.edge import SECURITY_HEADERS
from caos.api.site import SECTIONS, SITE_ROOT_ENV, application
from caos.refusals import Refusal, RefusalCode

INDEX = b"<!doctype html><title>CAOS</title><div id=root></div>"
CASE = "8c0d2b7e-3f7a-4e53-9a53-2f4f4c1b7a10"
RUN = "1f6a3c55-8e0b-4b8e-a4ad-6f2d1c9e0b42"


@pytest.fixture
def site(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    root = tmp_path / "site"
    (root / "assets").mkdir(parents=True)
    (root / "index.html").write_bytes(INDEX)
    (root / "assets" / "app.js").write_bytes(b"export {};")
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


def test_the_deep_link_sections_are_the_workspace_sections() -> None:
    """`site.SECTIONS` is copied from the workspace's list; a section added there
    and not here would deep-link to a 404 in the production image."""
    shared = Path(__file__).resolve().parents[1] / "frontend/src/wire/shared.ts"
    text = shared.read_text(encoding="utf-8")
    block = text[text.index("export const SECTIONS = [") : text.index("] as const;")]
    assert tuple(re.findall(r'"([a-z]+)"', block)) == SECTIONS

"""The one ASGI entry the image serves: the edge, the API and the static export.

`application` is `EdgeGuard` outermost, so every response -- a static file, a
refusal, an API document -- carries the security headers and policy, and no
request reaches a file or a route before the edge has admitted it. Behind it:

- `/api` and `/api/*` go to `caos.api.app:app`, lifespan included, so routing's
  own 404 and 405 there stay `ENDPOINT_NOT_FOUND` and a file under the export
  never shadows an API path. The app installs `EdgeGuard` too; the scope marker
  the outer guard sets makes the inner one pass through, except that it still
  answers an unhandled fault in the typed body before Starlette's error
  middleware can answer it in plain text (ED-2).
- Every other path is a GET/HEAD-only read of `CAOS_SITE_ROOT`. `/` and each
  section's `/<section>/` (with or without its slash, with any query) serve the
  exported `index.html`, which routes on the client; anything else is a file
  under the root or 404. A directory is never listed, a path that normalises
  outside the root and a symlink resolving outside it are 404, nothing is
  ever redirected (C1), and any other method is 405. Both carry no body.

The root is read from the environment on every use, like the edge's mode. With
it unset every non-API path is 404; set without an `index.html`, boot refuses
`EDGE_CONFIG_INVALID` before the app's own lifespan runs.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from starlette.exceptions import HTTPException
from starlette.responses import Response
from starlette.staticfiles import StaticFiles
from starlette.types import ASGIApp, Receive, Scope, Send

from caos.api.app import app
from caos.api.edge import EdgeGuard, is_api_path, startup_failed
from caos.refusals import Refusal, RefusalCode

# The dispatcher reads the environment and the export's files, never the store.
IO_BUDGET = 0

SITE_ROOT_ENV = "CAOS_SITE_ROOT"
# The nine sections of `frontend/src/app/sections.ts` (IA_SPEC.md 1). A disabled
# section still loads the workspace, which renders it unavailable.
SECTIONS = (
    "directory",
    "upload",
    "analysis",
    "book",
    "run",
    "model",
    "report",
    "committee",
    "admin",
)
_WORKSPACE = re.compile(r"^/(?:(?:" + "|".join(SECTIONS) + r")/?)?$")
_SAFE = frozenset({"GET", "HEAD"})


def _site_root() -> Path | None:
    root = os.environ.get(SITE_ROOT_ENV)
    return Path(root) if root else None


def _exported(root: Path) -> bool:
    return (root / "index.html").is_file()


# A root-relative `src` or `href` in the index: the export's own script,
# stylesheet and icons, never an external or protocol-relative address.
_NAMED = re.compile(rb'(?:src|href)="/(?!/)([^"?#]+)"')


def _complete(root: Path) -> bool:
    """The index and every file it names (DF-4). Asked once, at boot: an index
    whose script or stylesheet did not ship would serve 200 and draw nothing,
    while health answered `ready`."""
    if not _exported(root):
        return False
    named = _NAMED.findall((root / "index.html").read_bytes())
    return all((root / name.decode("utf-8", "replace")).is_file() for name in named)


async def _bare(send: Send, status: int) -> None:
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [(b"content-length", b"0")],
        }
    )
    await send({"type": "http.response.body", "body": b""})


class _Export(StaticFiles):
    """The export's files, with no redirect of any kind (C1).

    Starlette answers a directory request missing its trailing slash with a
    307 built from the request itself: first its `Host` (CF-086), and, once
    that was rewritten to a relative reference, its path -- which uvicorn
    percent-decodes, so `/%2Fevil.example%2F..` arrived as
    `//evil.example/..`, normalised to the root and came back as the
    scheme-relative `Location: //evil.example/../` a browser follows off the
    app's origin. Nothing the export serves needs a redirect: the workspace
    paths are rewritten to `/` before this runs, and any other directory is
    404 without its slash and its own index with it. A response that would
    carry a `Location` is refused before a byte of it is sent.
    """

    async def get_response(self, path: str, scope: Scope) -> Response:
        response = await super().get_response(path, scope)
        if "location" in response.headers:
            raise HTTPException(status_code=404)
        return response


async def _static(scope: Scope, receive: Receive, send: Send) -> None:
    if scope.get("method") not in _SAFE:
        await _bare(send, 405)
        return
    root = _site_root()
    if root is None or not _exported(root):
        await _bare(send, 404)
        return
    path = scope.get("path", "")
    if _WORKSPACE.match(path):
        scope = {**scope, "path": "/", "raw_path": b"/", "root_path": ""}
    files = _Export(directory=root, html=True, follow_symlink=False)
    try:
        await files(scope, receive, send)
    except HTTPException as refused:
        await _bare(send, refused.status_code)


async def dispatch(scope: Scope, receive: Receive, send: Send) -> None:
    """`/api` to the app, lifespan to the app, everything else to the export."""
    if scope["type"] == "lifespan":
        root = _site_root()
        if root is not None and not _complete(root):
            await startup_failed(receive, send)
            raise Refusal(RefusalCode.EDGE_CONFIG_INVALID)
        await app(scope, receive, send)
        return
    path = scope.get("path", "")
    if is_api_path(path):
        await app(scope, receive, send)
        return
    if scope["type"] == "http":
        await _static(scope, receive, send)


application: ASGIApp = EdgeGuard(dispatch)

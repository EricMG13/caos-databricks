"""The workspace that is not there yet, as an HTTP surface on a loopback socket.

Every call this repository makes to a Databricks workspace goes through the
SDK or the CLI over HTTPS, so the same code runs unchanged against this
server when `DATABRICKS_HOST` names it: the model factory's chat completion
(`/serving-endpoints/chat/completions`), SCIM `Me` and `Groups`, the Files
API the volume backend uses, the Unity Catalog, serving-endpoint, Lakebase
and Apps lookups `scripts/preflight.py` and the runbook make, and the two
workspace-tree calls `databricks bundle validate` needs (D28).

What it proves: that the bundle, the scripts and the production seams speak
the workspace's wire shapes end to end, with nothing injected below HTTP.
What it cannot prove: that a real workspace grants what the bundle asks for,
how the Apps proxy treats a stream (C42), or what a real model answers. Those
stay with the enterprise deployer (docs/rebuild/ENTERPRISE_HANDOFF.md).

The stub checks that a bearer header is present and never reads, records or
prints its value; `requests` holds methods and paths only.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from functools import partial
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from socket import socket
from socketserver import BaseServer
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

# What the SDK is handed as a token. It is a placeholder the stub never
# compares against; any non-empty bearer passes.
BEARER = "local-stub"
ENDPOINT = "databricks-claude-opus-5"
PRICE = f"{ENDPOINT},0.000005,0.000025,2026-09-22"
USER = {"id": "42", "userName": "stub@example.com", "displayName": "Stub User"}
FILES = "/api/2.0/fs/files"
DIRECTORIES = "/api/2.0/fs/directories"

Reply = Callable[[str, bool], str]


def _ok(prompt: str, json_object: bool) -> str:
    return '{"ok": true}' if json_object else "OK"


@dataclass
class WorkspaceStub:
    """One in-memory workspace: what it holds, what it answers, what it saw."""

    reply: Reply = _ok
    groups: frozenset[str] = frozenset({"caos-admins", "caos-analysts"})
    endpoints: frozenset[str] = frozenset({ENDPOINT})
    schemas: frozenset[str] = frozenset({"main.caos"})
    volumes: frozenset[str] = frozenset({"main.caos.caos_blobs"})
    instances: frozenset[str] = frozenset({"caos-lb"})
    apps: frozenset[str] = frozenset({"caos"})
    files: dict[str, bytes] = field(default_factory=dict)
    directories: set[str] = field(default_factory=set)
    requests: list[tuple[str, str]] = field(default_factory=list)
    completions: int = 0
    json_completions: int = 0
    host: str = ""

    @contextmanager
    def serving(self) -> Iterator[WorkspaceStub]:
        """Serve on a free loopback port for the duration of the block."""
        server = _Server(("127.0.0.1", 0), partial(_Handler, self))
        self.host = f"http://127.0.0.1:{server.server_address[1]}"
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        try:
            yield self
        finally:
            server.shutdown()
            server.server_close()

    def environment(self) -> dict[str, str]:
        """What a process needs to talk to this stub instead of a workspace."""
        return {
            "DATABRICKS_HOST": self.host,
            "DATABRICKS_TOKEN": BEARER,
            "CAOS_MODEL_ENDPOINT": ENDPOINT,
            "CAOS_MODEL_PRICE": PRICE,
        }

    def completion(self, body: dict[str, Any]) -> dict[str, Any] | None:
        """An OpenAI-shaped chat completion for `body`, or None for an unknown model."""
        if body.get("model") not in self.endpoints:
            return None
        prompt = _text(body.get("messages") or [])
        wanted = body.get("response_format") or {}
        json_object = isinstance(wanted, dict) and wanted.get("type") == "json_object"
        answer = self.reply(prompt, json_object)
        self.completions += 1
        self.json_completions += json_object
        prompt_tokens, completion_tokens = _tokens(prompt), _tokens(answer)
        return {
            "id": f"chatcmpl-stub-{self.completions}",
            "object": "chat.completion",
            "created": 0,
            "model": body["model"],
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": answer},
                    "finish_reason": "stop",
                }
            ],
            "usage": {
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": prompt_tokens + completion_tokens,
            },
        }


def _text(messages: list[dict[str, Any]]) -> str:
    content = messages[-1].get("content", "") if messages else ""
    if isinstance(content, str):
        return content
    return "".join(part.get("text", "") for part in content if isinstance(part, dict))


def _tokens(text: str) -> int:
    return max(1, len(text) // 4)


class _Server(ThreadingHTTPServer):
    """Handler threads never outlive the test that served them."""

    daemon_threads = True
    block_on_close = False


class _Handler(BaseHTTPRequestHandler):
    """Routes by method and path; every answer is JSON, bytes for a file read."""

    def __init__(
        self,
        stub: WorkspaceStub,
        request: socket | tuple[bytes, socket],
        client_address: tuple[str, int],
        server: BaseServer,
    ) -> None:
        self.stub = stub
        super().__init__(request, client_address, server)

    def log_message(self, format: str, *args: object) -> None:
        return

    def _send(self, code: int, body: dict[str, Any] | None, raw: bytes = b"") -> None:
        data = raw if body is None else json.dumps(body).encode()
        self.send_response(code)
        kind = "application/octet-stream" if body is None else "application/json"
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(data)

    def _missing(self, code: str = "NOT_FOUND") -> None:
        self._send(404, {"error_code": code, "message": "not in the stub"})

    def _body(self) -> bytes:
        return self.rfile.read(int(self.headers.get("Content-Length") or 0))

    def _authorized(self, path: str) -> bool:
        if not (path.startswith("/api/") or path.startswith("/serving-endpoints/")):
            return True
        return self.headers.get("Authorization", "").startswith("Bearer ")

    def _handle(self) -> None:
        url = urlparse(self.path)
        path = unquote(url.path)
        self.stub.requests.append((self.command, path))
        if not self._authorized(path):
            self._body()
            self._send(401, {"error_code": "PERMISSION_DENIED", "message": "no bearer"})
            return
        query = parse_qs(url.query)
        route = _ROUTES.get(self.command)
        handled = route(self, path, query) if route is not None else False
        if not handled:
            self._body()
            self._missing()

    do_GET = do_POST = do_PUT = do_HEAD = _handle

    def _get(self, path: str, query: dict[str, list[str]]) -> bool:
        stub = self.stub
        if path == "/api/2.0/preview/scim/v2/Me":
            groups = [{"display": g, "value": g} for g in sorted(stub.groups)]
            self._send(200, {**USER, "groups": groups})
        elif path == "/api/2.0/preview/scim/v2/Groups":
            # The SDK pages by `startIndex` until a page comes back empty.
            wanted = query.get("filter", [""])[0].partition('eq "')[2].rstrip('"')
            first = query.get("startIndex", ["1"])[0] == "1"
            found = [{"displayName": g, "id": g} for g in stub.groups if g == wanted]
            page = found if first else []
            self._send(200, {"Resources": page, "totalResults": len(found)})
        elif path == "/api/2.0/workspace/get-status":
            wanted = query.get("path", [""])[0]
            if wanted in stub.directories:
                self._send(200, {"path": wanted, "object_type": "DIRECTORY"})
            else:
                self._missing("RESOURCE_DOES_NOT_EXIST")
        elif path.startswith(FILES + "/"):
            data = stub.files.get(path[len(FILES) :])
            if data is None:
                self._missing()
            else:
                self._send(200, None, data)
        else:
            return self._lookup(path)
        return True

    def _lookup(self, path: str) -> bool:
        stub = self.stub
        prefixes: list[tuple[str, frozenset[str], Callable[[str], dict[str, Any]]]] = [
            ("/api/2.0/serving-endpoints/", stub.endpoints, _endpoint),
            ("/api/2.1/unity-catalog/schemas/", stub.schemas, _named),
            ("/api/2.1/unity-catalog/volumes/", stub.volumes, _named),
            ("/api/2.0/database/instances/", stub.instances, _instance),
            ("/api/2.0/apps/", stub.apps, partial(_app, stub.host)),
        ]
        for prefix, known, shape in prefixes:
            if path.startswith(prefix):
                name = path[len(prefix) :]
                if name in known:
                    self._send(200, shape(name))
                else:
                    self._missing()
                return True
        return False

    def _post(self, path: str, query: dict[str, list[str]]) -> bool:
        raw = self._body()
        if path == "/serving-endpoints/chat/completions":
            body = json.loads(raw or b"{}")
            completion = self.stub.completion(body)
            if completion is None:
                self._missing()
            else:
                self._send(200, completion)
        elif path == "/api/2.0/workspace/mkdirs":
            self.stub.directories.add(json.loads(raw or b"{}").get("path", ""))
            self._send(200, {})
        elif path == "/api/2.0/fs/create-download-url":
            self._missing()  # the SDK then reads the file directly
        else:
            return False
        return True

    def _put(self, path: str, query: dict[str, list[str]]) -> bool:
        raw = self._body()
        if path.startswith(FILES + "/"):
            self.stub.files[path[len(FILES) :]] = raw
        elif path.startswith(DIRECTORIES + "/"):
            self.stub.directories.add(path[len(DIRECTORIES) :])
        else:
            return False
        self._send(204, {})
        return True

    def _head(self, path: str, query: dict[str, list[str]]) -> bool:
        if not path.startswith(DIRECTORIES + "/"):
            return False
        directory = path[len(DIRECTORIES) :].rstrip("/")
        known = directory in self.stub.directories or any(
            name.startswith(directory + "/") for name in self.stub.files
        )
        if known:
            self._send(200, {})
        else:
            self._missing()
        return True


_ROUTES: dict[str, Callable[[_Handler, str, dict[str, list[str]]], bool]] = {
    "GET": _Handler._get,
    "POST": _Handler._post,
    "PUT": _Handler._put,
    "HEAD": _Handler._head,
}


def _endpoint(name: str) -> dict[str, Any]:
    return {
        "name": name,
        "state": {"ready": "READY", "config_update": "NOT_UPDATING"},
        "ai_gateway": {},
    }


def _named(full_name: str) -> dict[str, Any]:
    return {"full_name": full_name, "name": full_name.rsplit(".", 1)[-1]}


def _instance(name: str) -> dict[str, Any]:
    return {"name": name, "state": "AVAILABLE", "pg_version": "PG_VERSION_16"}


def _app(host: str, name: str) -> dict[str, Any]:
    return {
        "name": name,
        "url": f"{host}/apps/{name}",
        "app_status": {"state": "RUNNING"},
        "compute_status": {"state": "ACTIVE"},
    }


def main(argv: list[str] | None = None) -> int:
    """`workspace_stub.py -- <command...>`: run the command against the stub.

    The child inherits the environment with the stub as its workspace and no
    CLI profile; the exit code is the child's. Afterwards the paths the child
    asked for are printed, one per line, so a run shows what it exercised.
    """
    args = sys.argv[1:] if argv is None else argv
    if args[:1] == ["--"]:
        args = args[1:]
    if not args:
        print("usage: workspace_stub.py -- <command> [args...]", file=sys.stderr)
        return 2
    stub = WorkspaceStub()
    with stub.serving():
        env = {**os.environ, **stub.environment()}
        env.pop("DATABRICKS_CONFIG_PROFILE", None)
        code = subprocess.run(args, env=env, check=False).returncode
    for method, path in stub.requests:
        print(f"stub: {method} {path}")
    return code


if __name__ == "__main__":
    sys.exit(main())

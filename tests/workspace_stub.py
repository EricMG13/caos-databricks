"""The workspace that is not there yet, as an HTTP surface on a loopback socket.

Every call this repository makes to a Databricks workspace goes through the
SDK or the CLI over HTTPS, so the same code runs unchanged against this
server when `DATABRICKS_HOST` names it: the model factory's chat completion
(`/serving-endpoints/chat/completions`), SCIM `Me` and `Groups`, the Files
API the volume backend uses, the Lakebase credential the store mints, the
Unity Catalog, serving-endpoint, Lakebase-instance and Apps lookups
`scripts/preflight.py` and the runbook make, and the workspace-tree, file
import and Apps calls `databricks bundle validate|deploy|run` make (D28).

What it proves: that the bundle, the scripts, the process entry and the
production seams speak the workspace's wire shapes end to end, with nothing
injected below HTTP. What it cannot prove: that a real workspace grants what
the bundle asks for, how the Apps proxy treats a stream (C42), or what a
real model answers. Those stay with the enterprise deployer
(docs/rebuild/ENTERPRISE_HANDOFF.md).

A bearer header must be present on every API call. Its value is read only
to pick an identity from `identities` (as SCIM would) and is never stored,
compared for authorisation or printed; `requests` holds methods and paths.
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
IMPORT = "/api/2.0/workspace-files/import-file"
APPS = "/api/2.0/apps"

Reply = Callable[[str, bool], str]
Query = dict[str, list[str]]


def _ok(prompt: str, json_object: bool) -> str:
    return '{"ok": true}' if json_object else "OK"


@dataclass
class WorkspaceStub:
    """One in-memory workspace: what it holds, what it answers, what it saw."""

    reply: Reply = _ok
    groups: frozenset[str] = frozenset({"caos-admins", "caos-analysts"})
    # bearer -> (SCIM id, groups); a bearer not listed is `USER` in `groups`.
    identities: dict[str, tuple[str, frozenset[str]]] = field(default_factory=dict)
    user_name: str = str(USER["userName"])
    endpoints: frozenset[str] = frozenset({ENDPOINT})
    schemas: frozenset[str] = frozenset({"main.caos"})
    volumes: frozenset[str] = frozenset({"main.caos.caos_blobs"})
    instances: frozenset[str] = frozenset({"caos-lb"})
    instance_host: str = "127.0.0.1"
    # What `POST /api/2.0/database/credentials` mints: the local password in
    # a platform-mode boot, so `store_url()` reaches the Docker Postgres.
    database_credential: str = BEARER
    apps: set[str] = field(default_factory=lambda: {"caos"})
    app_url: str = ""
    files: dict[str, bytes] = field(default_factory=dict)
    directories: set[str] = field(default_factory=set)
    workspace_files: dict[str, bytes] = field(default_factory=dict)
    deployments: list[str] = field(default_factory=list)
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

    def identity(self, bearer: str) -> tuple[str, frozenset[str]]:
        scim_id, groups = self.identities.get(bearer, (str(USER["id"]), self.groups))
        return scim_id, groups

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

    def app(self, name: str) -> dict[str, Any]:
        url = self.app_url or f"{self.host}/apps/{name}"
        return {
            "name": name,
            "id": f"app-{name}",
            "url": url,
            "app_status": {"state": "RUNNING", "message": "App is running"},
            "compute_status": {"state": "ACTIVE", "message": ""},
            "service_principal_client_id": "sp-stub",
            "active_deployment": self.deployment(name) if self.deployments else None,
        }

    def deployment(self, name: str) -> dict[str, Any]:
        number = len(self.deployments)
        return {
            "deployment_id": f"deployment-{number}",
            "source_code_path": self.deployments[-1] if self.deployments else "",
            "mode": "SNAPSHOT",
            "status": {"state": "SUCCEEDED", "message": "deployed"},
        }

    def known(self, path: str) -> str | None:
        """`DIRECTORY`, `FILE` or None for a workspace-tree path."""
        if path in self.workspace_files:
            return "FILE"
        tree = [*self.directories, *self.workspace_files]
        if path in self.directories or any(p.startswith(path + "/") for p in tree):
            return "DIRECTORY"
        return None


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

    def _bearer(self) -> str | None:
        header = self.headers.get("Authorization", "")
        return header[len("Bearer ") :] if header.startswith("Bearer ") else None

    def _handle(self) -> None:
        url = urlparse(self.path)
        path = unquote(url.path)
        self.stub.requests.append((self.command, path))
        raw = self._body()
        guarded = path.startswith("/api/") or path.startswith("/serving-endpoints/")
        if guarded and self._bearer() is None:
            self._send(401, {"error_code": "PERMISSION_DENIED", "message": "no bearer"})
            return
        query = parse_qs(url.query)
        for method, prefix, exact, route in _ROUTES:
            matched = path == prefix if exact else path.startswith(prefix)
            if method == self.command and matched:
                route(self, path[len(prefix) :], query, raw)
                return
        self._missing()

    do_GET = do_POST = do_PUT = do_HEAD = do_DELETE = do_PATCH = _handle

    # -- identity -----------------------------------------------------------

    def _me(self, rest: str, query: Query, raw: bytes) -> None:
        scim_id, groups = self.stub.identity(self._bearer() or "")
        listed = [{"display": g, "value": g} for g in sorted(groups)]
        me = {**USER, "id": scim_id, "userName": self.stub.user_name, "groups": listed}
        self._send(200, me)

    def _groups(self, rest: str, query: Query, raw: bytes) -> None:
        # The SDK pages by `startIndex` until a page comes back empty.
        wanted = query.get("filter", [""])[0].partition('eq "')[2].rstrip('"')
        first = query.get("startIndex", ["1"])[0] == "1"
        found = [{"displayName": g, "id": g} for g in self.stub.groups if g == wanted]
        self._send(
            200, {"Resources": found if first else [], "totalResults": len(found)}
        )

    # -- the model, the store's credential ---------------------------------

    def _chat(self, rest: str, query: Query, raw: bytes) -> None:
        completion = self.stub.completion(json.loads(raw or b"{}"))
        if completion is None:
            self._missing()
        else:
            self._send(200, completion)

    def _credential(self, rest: str, query: Query, raw: bytes) -> None:
        body = json.loads(raw or b"{}")
        if not set(body.get("instance_names") or []) <= self.stub.instances:
            self._missing()
            return
        token = self.stub.database_credential
        self._send(200, {"token": token, "expiration_time": "2099-01-01T00:00:00Z"})

    # -- lookups preflight and the runbook make ---------------------------

    def _known(
        self, name: str, known: frozenset[str], shape: Callable[[str], dict[str, Any]]
    ) -> None:
        if name in known:
            self._send(200, shape(name))
        else:
            self._missing()

    def _endpoint_get(self, rest: str, query: Query, raw: bytes) -> None:
        self._known(rest, self.stub.endpoints, _endpoint)

    def _schema_get(self, rest: str, query: Query, raw: bytes) -> None:
        self._known(rest, self.stub.schemas, _named)

    def _volume_get(self, rest: str, query: Query, raw: bytes) -> None:
        self._known(rest, self.stub.volumes, _named)

    def _instance_get(self, rest: str, query: Query, raw: bytes) -> None:
        shape = partial(_instance, self.stub.instance_host)
        self._known(rest, self.stub.instances, shape)

    # -- the volume's Files API -------------------------------------------

    def _file_get(self, rest: str, query: Query, raw: bytes) -> None:
        data = self.stub.files.get("/" + rest)
        if data is None:
            self._missing()
        else:
            self._send(200, None, data)

    def _file_put(self, rest: str, query: Query, raw: bytes) -> None:
        self.stub.files["/" + rest] = raw
        self._send(204, {})

    def _directory_put(self, rest: str, query: Query, raw: bytes) -> None:
        self.stub.directories.add("/" + rest)
        self._send(204, {})

    def _directory_head(self, rest: str, query: Query, raw: bytes) -> None:
        directory = "/" + rest.rstrip("/")
        known = directory in self.stub.directories or any(
            name.startswith(directory + "/") for name in self.stub.files
        )
        if known:
            self._send(200, {})
        else:
            self._missing()

    # -- the workspace tree the bundle syncs into --------------------------

    def _status(self, rest: str, query: Query, raw: bytes) -> None:
        wanted = query.get("path", [""])[0]
        kind = self.stub.known(wanted)
        if kind is None:
            self._missing("RESOURCE_DOES_NOT_EXIST")
        else:
            self._send(200, {"path": wanted, "object_type": kind, "object_id": 1})

    def _mkdirs(self, rest: str, query: Query, raw: bytes) -> None:
        path = json.loads(raw or b"{}").get("path", "")
        parts = path.strip("/").split("/")
        for depth in range(1, len(parts) + 1):
            self.stub.directories.add("/" + "/".join(parts[:depth]))
        self._send(200, {})

    def _delete(self, rest: str, query: Query, raw: bytes) -> None:
        path = json.loads(raw or b"{}").get("path", "")
        stub = self.stub
        stub.directories = {d for d in stub.directories if not _under(d, path)}
        stub.workspace_files = {
            f: b for f, b in stub.workspace_files.items() if not _under(f, path)
        }
        self._send(200, {})

    def _import(self, rest: str, query: Query, raw: bytes) -> None:
        self.stub.workspace_files["/" + rest.lstrip("/")] = raw
        self._send(200, {})

    # -- the Apps API ------------------------------------------------------

    def _apps(self, rest: str, query: Query, raw: bytes) -> None:
        stub = self.stub
        name, _, action = rest.strip("/").partition("/")
        if self.command == "POST" and not rest.strip("/"):
            created = json.loads(raw or b"{}").get("name", "")
            stub.apps.add(created)
            self._send(200, stub.app(created))
        elif name not in stub.apps:
            self._missing()
        elif action == "" and self.command in ("GET", "PATCH"):
            self._send(200, stub.app(name))
        elif action == "deployments" and self.command == "POST":
            stub.deployments.append(
                json.loads(raw or b"{}").get("source_code_path", "")
            )
            self._send(200, stub.deployment(name))
        elif action == "deployments" and self.command == "GET":
            listed = [stub.deployment(name)] if stub.deployments else []
            self._send(200, {"app_deployments": listed})
        elif action.startswith("deployments/") and self.command == "GET":
            self._send(200, stub.deployment(name))
        elif action == "update":
            # The direct engine POSTs the update, then GETs it until its status
            # settles; the SDK reads `status.state`.
            settled = {"state": "SUCCEEDED", "message": "updated"}
            self._send(200, {**stub.app(name), "status": settled})
        elif action in ("start", "stop"):
            self._send(200, stub.app(name))
        else:
            self._missing()

    def _telemetry(self, rest: str, query: Query, raw: bytes) -> None:
        self._send(200, {})


def _under(path: str, root: str) -> bool:
    return path == root or path.startswith(root.rstrip("/") + "/")


Route = Callable[[_Handler, str, Query, bytes], None]
# (method, prefix, exact, route); the first match answers.
_ROUTES: list[tuple[str, str, bool, Route]] = [
    ("GET", "/api/2.0/preview/scim/v2/Me", True, _Handler._me),
    ("GET", "/api/2.0/preview/scim/v2/Groups", True, _Handler._groups),
    ("POST", "/serving-endpoints/chat/completions", True, _Handler._chat),
    ("POST", "/api/2.0/database/credentials", True, _Handler._credential),
    ("GET", "/api/2.0/serving-endpoints/", False, _Handler._endpoint_get),
    ("GET", "/api/2.1/unity-catalog/schemas/", False, _Handler._schema_get),
    ("GET", "/api/2.1/unity-catalog/volumes/", False, _Handler._volume_get),
    ("GET", "/api/2.0/database/instances/", False, _Handler._instance_get),
    ("GET", FILES + "/", False, _Handler._file_get),
    ("PUT", FILES + "/", False, _Handler._file_put),
    ("PUT", DIRECTORIES + "/", False, _Handler._directory_put),
    ("HEAD", DIRECTORIES + "/", False, _Handler._directory_head),
    ("GET", "/api/2.0/workspace/get-status", True, _Handler._status),
    ("POST", "/api/2.0/workspace/mkdirs", True, _Handler._mkdirs),
    ("POST", "/api/2.0/workspace/delete", True, _Handler._delete),
    ("POST", IMPORT + "/", False, _Handler._import),
    ("GET", APPS, False, _Handler._apps),
    ("POST", APPS, False, _Handler._apps),
    ("PATCH", APPS, False, _Handler._apps),
    ("POST", "/telemetry-ext", True, _Handler._telemetry),
]


def _endpoint(name: str) -> dict[str, Any]:
    return {
        "name": name,
        "state": {"ready": "READY", "config_update": "NOT_UPDATING"},
        "ai_gateway": {},
    }


def _named(full_name: str) -> dict[str, Any]:
    return {"full_name": full_name, "name": full_name.rsplit(".", 1)[-1]}


def _instance(host: str, name: str) -> dict[str, Any]:
    return {
        "name": name,
        "state": "AVAILABLE",
        "pg_version": "PG_VERSION_16",
        "read_write_dns": host,
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
        env = {**os.environ, **stub.environment(), "DATABRICKS_BUNDLE_ENGINE": "direct"}
        env.pop("DATABRICKS_CONFIG_PROFILE", None)
        code = subprocess.run(args, env=env, check=False).returncode
    for method, path in stub.requests:
        print(f"stub: {method} {path}")
    return code


if __name__ == "__main__":
    sys.exit(main())

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

import base64
import binascii
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from functools import partial
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from socket import socket
from socketserver import BaseServer
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

try:
    from bundle_defaults import defaults as _bundle_defaults
except ImportError:
    # Standalone (`python tests/workspace_stub.py -- ...`) has no conftest to
    # put the gate scripts on the path first, the way pytest's always has.
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
    from bundle_defaults import defaults as _bundle_defaults

# What the SDK is handed as a token. It is a placeholder the stub never
# compares against; any non-empty bearer passes. The rest are the bundle's
# own defaults (N23): `databricks.yml` states each once.
BEARER = "local-stub"
_DEFAULTS = _bundle_defaults()
ENDPOINT = _DEFAULTS["model_endpoint"]
PRICE = _DEFAULTS["model_price"]
GROUP_ADMIN = _DEFAULTS["group_admin"]
GROUP_ANALYST = _DEFAULTS["group_analyst"]
# N7: the platform hands the app a service principal's client id and secret,
# not a token; the process trades them for one itself, through the SDK's
# oauth-m2m credential strategy over these two placeholders. Never a real
# secret -- the stub never compares against it, the same as `BEARER`.
CLIENT_ID = "stub-client-id"
CLIENT_SECRET = "stub-client-secret"
USER = {"id": "42", "userName": "stub@example.com", "displayName": "Stub User"}
FILES = "/api/2.0/fs/files"
DIRECTORIES = "/api/2.0/fs/directories"
IMPORT = "/api/2.0/workspace-files/import-file"
APPS = "/api/2.0/apps"
# The Apps API's name rule: lowercase letters, digits and hyphens (DF-12).
APP_NAME = re.compile(r"[a-z0-9-]+")
# Where every stand-in workspace lives; bundle state naming any other host
# came from a real workspace.
LOOPBACK = "http://127.0.0.1:"

Reply = Callable[[str, bool], str]
Query = dict[str, list[str]]


def _ok(prompt: str, json_object: bool) -> str:
    return '{"ok": true}' if json_object else "OK"


@dataclass
class WorkspaceStub:
    """One in-memory workspace: what it holds, what it answers, what it saw."""

    reply: Reply = _ok
    # Answer with the content as a list of text parts, the shape some serving
    # endpoints send where the client's model declares a string (CF-077).
    content_parts: bool = False
    groups: frozenset[str] = frozenset({GROUP_ADMIN, GROUP_ANALYST})
    # A profile that may not list groups is answered 403 (preflight's W5).
    groups_forbidden: bool = False
    # What the serving endpoint's `ai_gateway` reads back (preflight's DP-3),
    # and any other field its answer carries: `config`, `pending_config`,
    # `telemetry_config` (DF-3).
    gateway: dict[str, Any] = field(default_factory=dict)
    endpoint_fields: dict[str, Any] = field(default_factory=dict)
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
    # No app until a deploy creates one: a name already taken answers 409
    # (DP-6), so a stand-in run creates the app the way the platform does.
    apps: set[str] = field(default_factory=set)
    # What each app was created or updated with; `app()` echoes the fields a
    # deploy reads back (`forward_user_access_token`).
    app_bodies: dict[str, dict[str, Any]] = field(default_factory=dict)
    permissions: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    app_url: str = ""
    # How every app and deployment settles; a crashed app or a failed
    # deployment is one assignment away, so E5 meets those answers too (DF-12).
    app_state: str = "RUNNING"
    deployment_state: str = "SUCCEEDED"
    files: dict[str, bytes] = field(default_factory=dict)
    directories: set[str] = field(default_factory=set)
    workspace_files: dict[str, bytes] = field(default_factory=dict)
    # Each deployment's source path, and each as the CLI sent it: the
    # `command` and `env_vars` the platform starts the app with (DF-12).
    deployments: list[str] = field(default_factory=list)
    deployment_bodies: list[dict[str, Any]] = field(default_factory=list)
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

    def service_principal_environment(self) -> dict[str, str]:
        """What the platform actually hands the app process (N7): a service
        principal's client id and secret, never a token. The SDK's
        oauth-m2m strategy trades them for one itself, over the discovery
        and token routes this stub also answers (`/.well-known/databricks-
        config`, `/oidc/.well-known/oauth-authorization-server`,
        `/oidc/v1/token`)."""
        return {
            "DATABRICKS_HOST": self.host,
            "DATABRICKS_CLIENT_ID": CLIENT_ID,
            "DATABRICKS_CLIENT_SECRET": CLIENT_SECRET,
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
                    "message": {
                        "role": "assistant",
                        "content": (
                            [{"type": "text", "text": answer}]
                            if self.content_parts
                            else answer
                        ),
                    },
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
        body = self.app_bodies.get(name, {})
        return {
            "name": name,
            "id": f"app-{name}",
            "url": url,
            "forward_user_access_token": body.get("forward_user_access_token"),
            "app_status": {
                "state": self.app_state,
                "message": f"App is {self.app_state}",
            },
            "compute_status": {"state": "ACTIVE", "message": ""},
            "service_principal_client_id": "sp-stub",
            "active_deployment": self.deployment(name) if self.deployments else None,
        }

    def deployment(self, name: str) -> dict[str, Any]:
        number = len(self.deployments)
        sent = self.deployment_bodies[-1] if self.deployment_bodies else {}
        return {
            "deployment_id": f"deployment-{number}",
            "source_code_path": self.deployments[-1] if self.deployments else "",
            "mode": "SNAPSHOT",
            "command": sent.get("command", []),
            "env_vars": sent.get("env_vars", []),
            "status": {
                "state": self.deployment_state,
                "message": f"Deployment {self.deployment_state}",
            },
        }

    def deployed_environment(self) -> dict[str, str]:
        """The environment the last deployment asked the platform for."""
        sent = self.deployment_bodies[-1] if self.deployment_bodies else {}
        return {
            str(item.get("name")): str(item.get("value", ""))
            for item in sent.get("env_vars") or []
            if isinstance(item, dict)
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

    # -- OAuth machine-to-machine (N7): the service principal's own login ---

    def _host_metadata(self, rest: str, query: Query, raw: bytes) -> None:
        """`GET /.well-known/databricks-config`: names where OIDC discovery
        is, so the SDK's own host-metadata probe resolves `discovery_url`
        without either side hard-coding the other's path."""
        self._send(200, {"oidc_endpoint": f"{self.stub.host}/oidc"})

    def _oidc_endpoints(self, rest: str, query: Query, raw: bytes) -> None:
        """`GET /oidc/.well-known/oauth-authorization-server`: the two
        endpoints `oauth_service_principal`'s `ClientCredentials` needs."""
        self._send(
            200,
            {
                "authorization_endpoint": f"{self.stub.host}/oidc/v1/authorize",
                "token_endpoint": f"{self.stub.host}/oidc/v1/token",
            },
        )

    def _token(self, rest: str, query: Query, raw: bytes) -> None:
        """`POST /oidc/v1/token`: the client-credentials exchange the SDK's
        oauth-m2m strategy makes with the client id and secret over Basic
        auth (`use_header=True`), never the bearer this stub otherwise reads.
        Any non-empty pair passes, the same looseness `BEARER` gets; the
        placeholders are compared to nothing here either."""
        header = self.headers.get("Authorization", "")
        pair = b""
        if header.startswith("Basic "):
            try:
                pair = base64.b64decode(header[len("Basic ") :], validate=True)
            except (ValueError, binascii.Error):
                pair = b""
        client_id, _, client_secret = pair.decode(errors="replace").partition(":")
        given = parse_qs(raw.decode())
        grant = given.get("grant_type", [""])[0]
        if not client_id or not client_secret or grant != "client_credentials":
            self._send(400, {"error": "invalid_client"})
            return
        self._send(
            200, {"access_token": BEARER, "token_type": "Bearer", "expires_in": 3600}
        )

    # -- identity -----------------------------------------------------------

    def _me(self, rest: str, query: Query, raw: bytes) -> None:
        scim_id, groups = self.stub.identity(self._bearer() or "")
        if not scim_id:
            # A token the workspace refuses is a 401, as the real one answers;
            # a 200 naming nobody is a malformed answer, not a refusal (ED-9).
            self._send(401, {"error_code": "UNAUTHENTICATED", "message": "no"})
            return
        listed = [{"display": g, "value": g} for g in sorted(groups)]
        me = {**USER, "id": scim_id, "userName": self.stub.user_name, "groups": listed}
        self._send(200, me)

    def _groups(self, rest: str, query: Query, raw: bytes) -> None:
        if self.stub.groups_forbidden:
            self._send(403, {"error_code": "PERMISSION_DENIED", "message": "no"})
            return
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
        shape = partial(_endpoint, self.stub.gateway, self.stub.endpoint_fields)
        self._known(rest, self.stub.endpoints, shape)

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
            self._missing("RESOURCE_DOES_NOT_EXIST")  # the Files API's own code
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
        """A write that names `overwrite=false` over a file already there is
        refused, as the platform refuses it: that is how a deploy lock held
        by another deployer stops the next deploy (DF-12)."""
        path = "/" + rest.lstrip("/")
        kept = query.get("overwrite", [""])[0] == "false"
        if kept and path in self.stub.workspace_files:
            self._send(
                409, {"error_code": "RESOURCE_ALREADY_EXISTS", "message": "exists"}
            )
            return
        self.stub.workspace_files[path] = raw
        self._send(200, {})

    def _export(self, rest: str, query: Query, raw: bytes) -> None:
        """`GET /api/2.0/workspace/export`: a production deploy reads its lock
        and its state through this (C3); a path not there is the code the
        CLI takes for "no lock yet"."""
        wanted = query.get("path", [""])[0]
        held = self.stub.workspace_files.get(wanted)
        if held is None:
            self._missing("RESOURCE_DOES_NOT_EXIST")
        elif query.get("direct_download", ["false"])[0] == "true":
            self._send(200, None, raw=held)
        else:
            self._send(200, {"content": base64.b64encode(held).decode()})

    # -- the Apps API ------------------------------------------------------

    def _apps(self, rest: str, query: Query, raw: bytes) -> None:
        stub = self.stub
        name, _, action = rest.strip("/").partition("/")
        if self.command == "POST" and not rest.strip("/"):
            self._create_app(raw)
        elif name not in stub.apps:
            self._missing()
        elif action == "" and self.command in ("GET", "PATCH"):
            self._send(200, stub.app(name))
        elif action == "deployments" and self.command == "POST":
            sent = json.loads(raw or b"{}")
            stub.deployments.append(sent.get("source_code_path", ""))
            stub.deployment_bodies.append(sent)
            self._send(200, stub.deployment(name))
        elif action == "deployments" and self.command == "GET":
            listed = [stub.deployment(name)] if stub.deployments else []
            self._send(200, {"app_deployments": listed})
        elif action.startswith("deployments/") and self.command == "GET":
            self._send(200, stub.deployment(name))
        elif action == "update":
            # The direct engine POSTs the update, then GETs it until its status
            # settles; the SDK reads `status.state`.
            if self.command == "POST":
                stub.app_bodies[name] = {
                    **stub.app_bodies.get(name, {}),
                    **json.loads(raw or b"{}"),
                }
            settled = {"state": "SUCCEEDED", "message": "updated"}
            self._send(200, {**stub.app(name), "status": settled})
        elif action in ("start", "stop"):
            self._send(200, stub.app(name))
        else:
            self._missing()

    def _create_app(self, raw: bytes) -> None:
        stub = self.stub
        body = json.loads(raw or b"{}")
        created = body.get("name", "")
        if not APP_NAME.fullmatch(created):
            # As the Apps API answers a name outside its rule (DF-12).
            self._send(
                400, {"error_code": "INVALID_PARAMETER_VALUE", "message": "name"}
            )
            return
        if created in stub.apps:
            # As the platform answers a name already taken (DP-6).
            self._send(409, {"error_code": "ALREADY_EXISTS", "message": "taken"})
            return
        stub.apps.add(created)
        stub.app_bodies[created] = body
        self._send(200, stub.app(created))

    def _permissions(self, rest: str, query: Query, raw: bytes) -> None:
        """`PUT|GET /api/2.0/permissions/apps/<name>`: the grants as given."""
        name = rest.strip("/").split("/", 1)[0]
        if name not in self.stub.apps:
            self._missing()
            return
        if self.command == "PUT":
            given = json.loads(raw or b"{}").get("access_control_list", [])
            self.stub.permissions[name] = given
        granted = self.stub.permissions.get(name, [])
        self._send(200, {"object_id": f"/apps/{name}", "access_control_list": granted})

    def _telemetry(self, rest: str, query: Query, raw: bytes) -> None:
        self._send(200, {})


def _under(path: str, root: str) -> bool:
    return path == root or path.startswith(root.rstrip("/") + "/")


Route = Callable[[_Handler, str, Query, bytes], None]
# (method, prefix, exact, route); the first match answers.
_ROUTES: list[tuple[str, str, bool, Route]] = [
    ("GET", "/.well-known/databricks-config", True, _Handler._host_metadata),
    (
        "GET",
        "/oidc/.well-known/oauth-authorization-server",
        True,
        _Handler._oidc_endpoints,
    ),
    ("POST", "/oidc/v1/token", True, _Handler._token),
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
    ("GET", "/api/2.0/workspace/export", True, _Handler._export),
    ("POST", "/api/2.0/workspace/mkdirs", True, _Handler._mkdirs),
    ("POST", "/api/2.0/workspace/delete", True, _Handler._delete),
    ("POST", IMPORT + "/", False, _Handler._import),
    ("GET", APPS, False, _Handler._apps),
    ("POST", APPS, False, _Handler._apps),
    ("PATCH", APPS, False, _Handler._apps),
    ("PUT", "/api/2.0/permissions/apps/", False, _Handler._permissions),
    ("GET", "/api/2.0/permissions/apps/", False, _Handler._permissions),
    ("POST", "/telemetry-ext", True, _Handler._telemetry),
]


def _endpoint(
    gateway: dict[str, Any], fields: dict[str, Any], name: str
) -> dict[str, Any]:
    return {
        "name": name,
        "state": {"ready": "READY", "config_update": "NOT_UPDATING"},
        "ai_gateway": gateway,
        **fields,
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


def fresh_state(root: Path) -> list[str]:
    """Clear the bundle state earlier stand-in runs left under `root`, and
    name each target whose state a real workspace wrote, which stays.

    Each stand-in run is a new, empty workspace, while `.databricks/bundle`
    outlives it: a deploy planned against the last run's state looks for an
    app this workspace never had, and CLI 1.17.0 panics when that config has
    changed (DF-13). State is the stand-in's only when it holds a sync
    snapshot and every one names a loopback host (R24-N02): no snapshot at
    all -- `bundle summary` can leave exactly that, a `resources.json` with
    nothing under `sync-snapshots` -- is not positive evidence either way,
    `all()` of nothing is `True`, and this is deleted state, not a refusal;
    it is kept, the same as state this cannot read.
    """
    kept: list[str] = []
    state = root / ".databricks" / "bundle"
    targets = sorted(p for p in state.iterdir() if p.is_dir()) if state.is_dir() else []
    for target in targets:
        try:
            hosts = {
                str(json.loads(snapshot.read_text()).get("host", ""))
                for snapshot in (target / "sync-snapshots").glob("*.json")
            }
        except (OSError, ValueError, AttributeError):
            hosts = {"unreadable"}
        if hosts and all(host.startswith(LOOPBACK) for host in hosts):
            shutil.rmtree(target)
        else:
            kept.append(target.name)
    return kept


# R24-02: real CLI 1.17.0 resolves an explicit `-p`/`--profile` flag's own
# host and credentials ahead of `DATABRICKS_HOST`/`DATABRICKS_TOKEN`, so a
# copied manual command that still carries one (docs/DEPLOYMENT.md) would
# reach the workspace that profile names instead of this loopback stub, even
# with `DATABRICKS_CONFIG_PROFILE` stripped. Matched inside a whole `sh -c
# "..."` argument too, the same way the `bundle` guard below is. The CLI
# name is bounded by whitespace or a path separator, not `\b`: this repo's
# own checkout path can read "...-caos-databricks/...", and `\b` alone
# would treat that hyphenated segment as the CLI too.
_DATABRICKS_CLI = re.compile(r"(?:^|[\s/])databricks(?:[\s/]|$)")
_PROFILE_FLAG = re.compile(r"(?:^|[\s\"'])(-p(?:[=\s\"']|$)|--profile\b)")


def _forwards_profile(args: list[str]) -> bool:
    """Whether a `databricks` command in `args` carries `-p`/`--profile`."""
    joined = " ".join(args)
    return bool(_DATABRICKS_CLI.search(joined) and _PROFILE_FLAG.search(joined))


def main(argv: list[str] | None = None) -> int:
    """`workspace_stub.py -- <command...>`: run the command against the stub.

    The child inherits the environment with the stub as its workspace, no
    ambient CLI profile and no `.databrickscfg` of its own -- an explicit
    `-p`/`--profile` is refused outright (R24-02), and the config file the
    CLI would otherwise read is a private, empty one, so nothing named by a
    profile or left over in an inherited config can be reached; only this
    loopback stub can. The exit code is the child's. Afterwards the paths
    the child asked for are printed, one per line, so a run shows what it
    exercised. A `bundle` command starts from no bundle state but a real
    workspace's, and refuses to run over that (`fresh_state`, DF-13).
    """
    args = sys.argv[1:] if argv is None else argv
    if args[:1] == ["--"]:
        args = args[1:]
    if not args:
        print("usage: workspace_stub.py -- <command> [args...]", file=sys.stderr)
        return 2
    if _forwards_profile(args):
        print(
            "stub: -p/--profile would let the CLI resolve a workspace of its "
            "own; omit it -- this stand-in already points the CLI at the "
            "loopback stub",
            file=sys.stderr,
        )
        return 2
    if any(re.search(r"\bbundle\b", arg) for arg in args):
        kept = fresh_state(Path.cwd())
        if kept:
            print(
                f"stub: .databricks/bundle/{kept[0]} holds a real workspace's "
                "state; move .databricks aside before a stand-in run",
                file=sys.stderr,
            )
            return 2
    stub = WorkspaceStub()
    with stub.serving(), tempfile.TemporaryDirectory() as private:
        config_file = Path(private) / "empty.databrickscfg"
        config_file.write_text("", encoding="utf-8")
        env = {**os.environ, **stub.environment(), "DATABRICKS_BUNDLE_ENGINE": "direct"}
        env.pop("DATABRICKS_CONFIG_PROFILE", None)
        env["DATABRICKS_CONFIG_FILE"] = str(config_file)
        code = subprocess.run(args, env=env, check=False).returncode
    for method, path in stub.requests:
        print(f"stub: {method} {path}")
    return code


if __name__ == "__main__":
    sys.exit(main())

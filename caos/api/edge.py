"""The edge guard: what a request must prove before anything else reads it.

The spec's §4 (`docs/rebuild/2026-09-22-caos-databricks-spec.md`) and D10 in
`docs/rebuild/decisions.md`. D10: the platform is the edge. The legacy host's
static shared secret, and the signed per-request HMAC assertion that replaced
it, are both gone (spec §54); a deployment is either behind a Databricks App
or it is a loopback development image, and there is no third thing.

**The platform's contract.** Databricks Apps authenticates the caller with
OIDC ahead of this process and forwards the caller's own access token in
`x-forwarded-access-token`; `caos/api/identity.py` resolves who that token
names with SCIM. It passes `origin`, `sec-fetch-*`, `idempotency-key`,
`last-event-id`, `content-type` and `content-length` through.

**Two modes, decided by the environment on every use.**

- *Platform mode* (`PLATFORM_ENV` set): the workspace id must be configured
  and any declared `CAOS_PUBLIC_ORIGIN` or `DATABRICKS_HOST` well-formed, or
  boot refuses `EDGE_CONFIG_INVALID`. Every identity header a request arrived
  with is dropped before routing, identity or body -- a header a misconfigured
  proxy forwarded decides nothing -- and the caller is whoever the workspace's
  `Me` names for the forwarded token.
- *Dev mode* (`PLATFORM_ENV` unset): served only when both socket ends are
  loopback addresses and `Host` is `localhost`, `127.0.0.1` or `[::1]`. A
  published port on this image therefore answers health and nothing else, and
  a DNS rebinding page is refused by its `Host`. `caos/api/identity.py` reads
  `x-caos-user` and, only while `CAOS_TRUST_ROLE_HEADER` is on, `x-caos-role`;
  a peer that passes the loopback check is otherwise READER. An unsafe `/api`
  request's origin must be the conventional vite-plus-loopback-API pair
  (`DEV_ORIGINS`: ports 5173 and 8000) unless `CAOS_PUBLIC_ORIGIN` declares a
  different one (CF-056), which must be well-formed or boot refuses
  `EDGE_CONFIG_INVALID`.

In both modes a repeated or lookalike identity header is 401
`NOT_AUTHENTICATED`; `/api` is checked for Origin and `Sec-Fetch-Site` (the
second half of Task 4.2's CSRF split); and every response carries the
security headers and policy, with no cookie and no CORS header.

No header value is ever logged, formatted into a body or compared in a way
that would need constant time: the refusal bodies are constants, and an
unhandled fault is logged as its class and the frame it was raised in, never
its message (AS-6).
"""

from __future__ import annotations

import ipaddress
import os
import re
import sys
import time
import traceback
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from urllib.parse import urlsplit

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from caos.api.identity import (
    GROUPS_HEADER,
    HOST_ENV,
    PLATFORM_HEADER,
    ROLE_HEADER,
    SUBJECT_HEADER,
    TRUST_SWITCH,
    WORKSPACE_ENV,
    workspace_address,
)
from caos.api.identity import PLATFORM_ENV as PLATFORM_ENV  # re-exported, see below
from caos.api.wire import CLEARS, RefusalBody
from caos.refusals import Refusal, RefusalCode

# Pure: the guard reads the environment, the clock and the scope, never the store.
IO_BUDGET = 0

PUBLIC_ORIGIN_ENV = "CAOS_PUBLIC_ORIGIN"
# Platform mode (D10): Databricks Apps set `PLATFORM_ENV` for every app
# process. The platform's proxy authenticates the caller and forwards a user
# token; there is no assertion to verify and no loopback rule, and no header is
# believed. The name is `caos/api/identity.py`'s, re-exported rather than
# spelled a second time, so the mode the guard decides and the mode identity
# decides can never be two different variables (EI-N5).

HEALTH_PATH = "/api/health"
_SAFE = frozenset({"GET", "HEAD"})
_IDENTITY = frozenset({SUBJECT_HEADER, GROUPS_HEADER, ROLE_HEADER})
_LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "[::1]"})
_HOST = re.compile(r"^(?P<name>localhost|127\.0\.0\.1|\[::1\])(?::[0-9]{1,5})?$")
# Loopback only, and only when no public origin is configured (`_origin_allowed`):
# these never leave the machine, so there is no transport to secure. A production
# deployment sets `CAOS_PUBLIC_ORIGIN` and this set is not consulted at all.
DEV_ORIGINS = frozenset(
    f"http://{host}:{port}"  # NOSONAR -- loopback, never a network hop
    for host in _LOOPBACK_HOSTS
    for port in (5173, 8000)
)

SECURITY_HEADERS: Mapping[str, str] = {
    "content-security-policy": (
        "default-src 'none'; script-src 'self'; style-src 'self'; "
        "img-src 'self'; font-src 'self'; connect-src 'self'; base-uri 'none'; "
        "form-action 'self'; frame-ancestors 'none'; object-src 'none'; "
        "require-trusted-types-for 'script'; trusted-types 'none'"
    ),
    "x-content-type-options": "nosniff",
    "referrer-policy": "no-referrer",
    "cross-origin-opener-policy": "same-origin",
    "cross-origin-resource-policy": "same-origin",
}
_STRIPPED = (b"set-cookie", b"cache-control")
_ASSET_CACHE = "public, max-age=31536000, immutable"


def is_api_path(path: str) -> bool:
    """Whether `path` is the API's: `/api` itself or anything under it. The one
    predicate the guard, the dispatcher and the app's handlers all decide by."""
    return path == "/api" or path.startswith("/api/")


def refusal_body(code: RefusalCode) -> bytes:
    """The one refusal body on the wire: the code, its constant clearance,
    and no part of what caused it -- the same bytes whether the guard or the
    app answers."""
    return RefusalBody(code=code, clears=CLEARS[code]).model_dump_json().encode()


async def startup_failed(receive: Receive, send: Send) -> None:
    """Answer the lifespan startup as failed, `EDGE_CONFIG_INVALID`.

    Sent before the caller raises, because a server whose lifespan mode is
    "auto" treats a bare exception as a missing lifespan protocol and serves
    anyway.
    """
    message = await receive()
    if message["type"] == "lifespan.startup":
        await send(
            {
                "type": "lifespan.startup.failed",
                "message": RefusalCode.EDGE_CONFIG_INVALID.value,
            }
        )


@dataclass(frozen=True, slots=True)
class EdgeMode:
    """Platform mode behind a Databricks App; dev mode otherwise (D10)."""

    public_origin: str | None
    platform: bool = False


def resolve_mode(environ: Mapping[str, str] | None = None) -> EdgeMode:
    """The mode this environment declares, or `EDGE_CONFIG_INVALID`."""
    env = os.environ if environ is None else environ
    if env.get(PLATFORM_ENV):
        return _platform_mode(env)
    return _dev_mode(env)


def _dev_mode(env: Mapping[str, str]) -> EdgeMode:
    """Dev mode, or `EDGE_CONFIG_INVALID` for a malformed declared origin
    (CF-056).

    `DEV_ORIGINS` names only the conventional pair of ports -- the vite dev
    server proxying to the loopback API, or the API serving the built
    export itself -- and is a convenience for that shape, not a ceiling on
    it: a developer whose ports differ could otherwise never make an unsafe
    command of their own origin succeed. `CAOS_PUBLIC_ORIGIN`, already read
    this way in platform mode, is honoured here too, and replaces the
    default pair rather than adding to it, exactly as it does there.
    """
    origin = env.get(PUBLIC_ORIGIN_ENV)
    if origin is not None and not _bare_origin(origin):
        raise Refusal(RefusalCode.EDGE_CONFIG_INVALID)
    return EdgeMode(public_origin=origin)


def _platform_mode(env: Mapping[str, str]) -> EdgeMode:
    """Platform mode, or `EDGE_CONFIG_INVALID` for the three ways it is not one.

    The trust switch beside the platform is a configuration that cannot mean
    anything: the platform is the edge, never a development convenience.
    Every subject is minted under the workspace id (F46), so a process
    without one would name everybody under an empty workspace. And the
    workspace this process asks about a caller's token has to be one it can
    reach: a `DATABRICKS_HOST` with a non-numeric port, or an `http://` host
    that is not this machine, used to be found on the first request -- the
    first as an untyped `ValueError` answered 500, the second as a bearer
    sent in clear (EI-N2, EI-N3). Boot is where a configuration is answered.
    """
    origin = env.get(PUBLIC_ORIGIN_ENV)
    host = env.get(HOST_ENV)
    if TRUST_SWITCH in env:
        raise Refusal(RefusalCode.EDGE_CONFIG_INVALID)
    if not env.get(WORKSPACE_ENV):
        raise Refusal(RefusalCode.EDGE_CONFIG_INVALID)
    if origin is not None and not _bare_origin(origin):
        raise Refusal(RefusalCode.EDGE_CONFIG_INVALID)
    if host and workspace_address(host) is None:
        raise Refusal(RefusalCode.EDGE_CONFIG_INVALID)
    return EdgeMode(public_origin=origin, platform=True)


def _bare_origin(value: str) -> bool:
    """`scheme://host[:port]` exactly as a browser serialises an Origin."""
    try:
        parts = urlsplit(value)
        port = parts.port
    except ValueError:
        return False
    if parts.scheme not in ("http", "https") or not parts.hostname:
        return False
    if parts.username is not None or parts.password is not None:
        return False
    host = f"[{parts.hostname}]" if ":" in parts.hostname else parts.hostname
    rebuilt = f"{parts.scheme}://{host}" + (f":{port}" if port is not None else "")
    return rebuilt == value


def _logged(fault: BaseException) -> None:
    """An unhandled fault, as its class and the frame it was raised in.

    Never `str(fault)` (AS-6): an exception that quotes its input -- a
    pydantic `ValidationError` carries `input_value=`, a driver error quotes a
    parameter -- would put source text into the App's log, where the wire
    refusal is careful to put nothing. The class and the frame are host facts,
    which is exactly the pair `caos/graph/worker.py` writes for the same
    reason. The wire body is `INTERNAL_FAULT` either way.
    """
    frames = traceback.extract_tb(fault.__traceback__)
    where = f"{frames[-1].filename}:{frames[-1].lineno}" if frames else "?"
    print(f"{type(fault).__name__} at {where}", file=sys.stderr)


async def _answering_faults(
    app: ASGIApp, scope: Scope, receive: Receive, send: Send, *, log: bool
) -> None:
    """Run `app`, answering an unhandled fault `INTERNAL_FAULT` if nothing has
    been sent yet, then re-raising it.

    Starlette's error middleware sits outside the app's own guard, so its
    plain-text 500 would skip both the policy and the typed body: whichever
    guard is innermost answers first, and every layer above sees the response
    started and sends nothing. Only the outermost guard logs (`log`), so one
    fault is one line.
    """
    started = False

    async def tracked(message: Message) -> None:
        nonlocal started
        if message["type"] == "http.response.start":
            started = True
        await send(message)

    try:
        await app(scope, receive, tracked)
    except Exception as fault:
        if not started:
            await _refuse(send, RefusalCode.INTERNAL_FAULT)
        if log:
            _logged(fault)
        raise


def _loopback(address: object) -> bool:
    if not isinstance(address, (list, tuple)) or not address:
        return False
    try:
        return ipaddress.ip_address(str(address[0])).is_loopback
    except ValueError:
        return False


def _all(headers: list[tuple[bytes, bytes]], name: str) -> list[bytes]:
    wanted = name.encode()
    return [value for key, value in headers if key.lower() == wanted]


class EdgeGuard:
    """Pure ASGI middleware in front of the API and the static site."""

    def __init__(self, app: ASGIApp, *, clock: Callable[[], float] = time.time) -> None:
        self.app = app
        self.clock = clock

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "lifespan":
            await self._lifespan(scope, receive, send)
            return
        if scope["type"] != "http":
            return  # nothing here serves a websocket
        if scope.get("caos.edge_guarded"):
            # The guard never wraps twice, but the inner one still answers a
            # fault (ED-2). `caos.api.site:application` puts this app's guard
            # behind the outer one and inside Starlette's error middleware,
            # which answered `text/plain` first when this branch passed the
            # fault straight through. The outer guard logs it.
            await _answering_faults(self.app, scope, receive, send, log=False)
            return
        path = scope.get("path", "")
        refusal, mode = self._refusal(scope, path)
        # Wherever an edge exists (the platform, or a mode that would not
        # resolve) every identity header the request carried is gone before
        # any other code -- a refusal included -- runs, on the health path
        # too (F44): what the application reads is never a header the client
        # itself could set.
        edged = mode is None or mode.platform
        scope["headers"] = _rewritten(scope.get("headers", []), edged=edged)
        scope["caos.edge_guarded"] = True
        guarded = _secured(send, path)
        if refusal is not None:
            await _refuse(guarded, refusal)
            return
        await _answering_faults(self.app, scope, receive, guarded, log=True)

    async def _lifespan(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Refuse to start under an invalid edge configuration."""
        if scope.get("caos.edge_guarded"):
            await self.app(scope, receive, send)
            return
        try:
            resolve_mode()
        except Refusal:
            await startup_failed(receive, send)
            raise
        scope["caos.edge_guarded"] = True
        await self.app(scope, receive, send)

    def _refusal(
        self, scope: Scope, path: str
    ) -> tuple[RefusalCode | None, EdgeMode | None]:
        method = scope.get("method", "")
        headers: list[tuple[bytes, bytes]] = list(scope.get("headers", []))
        health = path == HEALTH_PATH and method in _SAFE
        try:
            mode = resolve_mode()
        except Refusal:
            return (None if health else RefusalCode.EDGE_NOT_TRUSTED), None
        if health:
            return None, mode
        if not mode.platform and not _dev_peer(scope, headers):
            return RefusalCode.EDGE_NOT_TRUSTED, mode
        if not _hygienic(headers):
            return RefusalCode.NOT_AUTHENTICATED, mode
        # The one header that decides identity behind the platform gets the
        # hygiene the others get (F44): two of them name nobody.
        if mode.platform and len(_all(headers, PLATFORM_HEADER)) > 1:
            return RefusalCode.NOT_AUTHENTICATED, mode
        if is_api_path(path) and not _origin_allowed(mode, method, headers):
            return RefusalCode.ORIGIN_REFUSED, mode
        return None, mode


def _rewritten(
    headers: list[tuple[bytes, bytes]], *, edged: bool = False
) -> list[tuple[bytes, bytes]]:
    """The scope's headers, stripped of every identity header the request
    carried when an edge exists (behind the platform, or under a
    configuration that would not resolve): downstream identity is never a
    header the client itself could set (D10, EI-N5)."""
    if not edged:
        return list(headers)
    dropped = {name.encode() for name in _IDENTITY}
    return [(key, value) for key, value in headers if key.lower() not in dropped]


def _dev_peer(scope: Scope, headers: list[tuple[bytes, bytes]]) -> bool:
    """Dev mode's whole proof: loopback at both ends and a loopback Host."""
    if not (_loopback(scope.get("client")) and _loopback(scope.get("server"))):
        return False
    hosts = _all(headers, "host")
    return len(hosts) == 1 and _HOST.match(hosts[0].decode("latin-1")) is not None


def _hygienic(headers: list[tuple[bytes, bytes]]) -> bool:
    """At most one of each identity header, and no lookalike of any."""
    seen: dict[str, int] = {}
    for raw, _ in headers:
        name = raw.decode("latin-1")
        canonical = name.lower().replace("_", "-")
        if canonical not in _IDENTITY:
            continue
        if name != canonical:
            return False
        seen[canonical] = seen.get(canonical, 0) + 1
        if seen[canonical] > 1:
            return False
    return True


def _origin_allowed(
    mode: EdgeMode, method: str, headers: list[tuple[bytes, bytes]]
) -> bool:
    # Behind the platform without a declared public origin, the browser's
    # own `sec-fetch-site` is the whole cross-site rule: the app's URL is the
    # platform's to choose, and it is not known here.
    allowed: frozenset[str] | None = (
        None
        if mode.platform and mode.public_origin is None
        else DEV_ORIGINS
        if mode.public_origin is None
        else frozenset({mode.public_origin})
    )
    sites = _all(headers, "sec-fetch-site")
    origins = _all(headers, "origin")
    if len(sites) > 1 or len(origins) > 1:
        return False
    site = sites[0].decode("latin-1") if sites else None
    origin = origins[0].decode("latin-1") if origins else None
    if allowed is not None and origin is not None and origin not in allowed:
        return False
    # `cross-site`, `same-site` and any unknown value fall through both rules.
    if method in _SAFE:
        return site in (None, "none", "same-origin")
    if site == "same-origin":
        return True
    if site is not None or origin is None:
        return False
    # A client with no `sec-fetch-site`: its origin was checked above when a
    # public origin is declared; behind the platform without one, the request's
    # own `Host` is what the origin must name (F45), never any origin at all.
    return allowed is not None or _names_host(origin, headers)


def _names_host(origin: str, headers: list[tuple[bytes, bytes]]) -> bool:
    hosts = _all(headers, "host")
    if len(hosts) != 1:
        return False
    try:
        named = urlsplit(origin).netloc
    except ValueError:
        return False
    return bool(named) and named.lower() == hosts[0].decode("latin-1").lower()


_CACHEABLE = frozenset({200, 304})


def _cache_policy(path: str, status: int) -> str:
    """The one cache-control this status earns at this path (CF-087): the
    year-long immutable asset policy only on a response that actually served
    the asset, never on a refusal or a miss that happened to share its path
    -- a browser that cached either of those forever would never ask again."""
    if is_api_path(path):
        return "no-store"
    if path.startswith("/assets/"):
        return _ASSET_CACHE if status in _CACHEABLE else "no-store"
    return "no-cache"


def _secured(send: Send, path: str) -> Send:
    """Every response start gains the policy and loses any cookie or CORS."""

    async def wrapped(message: Message) -> None:
        if message["type"] == "http.response.start":
            kept = [
                (key, value)
                for key, value in message.get("headers", [])
                if key.lower() not in _STRIPPED
                and key.lower() not in SECURITY_HEADERS_BYTES
                and not key.lower().startswith(b"access-control-")
            ]
            kept.extend(SECURITY_HEADER_PAIRS)
            cache = _cache_policy(path, message["status"])
            kept.append((b"cache-control", cache.encode()))
            message = {**message, "headers": kept}
        await send(message)

    return wrapped


SECURITY_HEADER_PAIRS = tuple(
    (name.encode(), value.encode()) for name, value in SECURITY_HEADERS.items()
)
SECURITY_HEADERS_BYTES = frozenset(name for name, _ in SECURITY_HEADER_PAIRS)


# Every code the guard answers, with its status. The guard runs before routing
# and so cannot reach the app's refusal handler, but a code's status must not
# depend on which layer answered it: each entry here equals `app._STATUS`'s,
# which `tests/test_api_routes.py` asserts (this module cannot import the app,
# which imports it). `INTERNAL_FAULT` is the unhandled exception's answer, and
# it was 500 here while the app served the same code 400 (§75's upgrade).
EDGE_STATUS: Mapping[RefusalCode, int] = MappingProxyType(
    {
        RefusalCode.EDGE_NOT_TRUSTED: 403,
        RefusalCode.NOT_AUTHENTICATED: 401,
        RefusalCode.ORIGIN_REFUSED: 403,
        RefusalCode.INTERNAL_FAULT: 500,
    }
)


async def _refuse(send: Send, code: RefusalCode) -> None:
    body = refusal_body(code)
    status = EDGE_STATUS[code]
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode()),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})

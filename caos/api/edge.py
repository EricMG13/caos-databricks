"""The edge guard: what a request must prove before anything else reads it.

The spec's §4 (`docs/rebuild/2026-09-22-caos-databricks-spec.md`) and D10 in
`docs/rebuild/decisions.md`. The legacy host replaced its static shared secret
with the signed per-request assertion described below; D10 then made the
platform the edge, and SI-2 records that the assertion mode is still shipped
here although the spec says it was removed.

**The edge contract.** The operator's edge authenticates with OIDC and forwards
only to a private API listener. It strips every inbound `x-caos-user`,
`x-forwarded-groups`, `x-caos-role` and `x-caos-edge-assertion`, every header
whose name contains `_`, and its own session cookie; it then sets exactly one
`x-caos-edge-assertion`, computed per request with `sign_assertion` below: an
HMAC-SHA256 under the deployment's key over the subject, the sorted groups,
the method, the raw target (path and query), the issued-at second and a
random nonce. It passes `origin`, `sec-fetch-*`, `idempotency-key`,
`last-event-id`, `content-type` and `content-length` through. Its session
cookie is `__Host-`-prefixed, `Secure; HttpOnly; SameSite=Lax`, and SSE is
unbuffered with an idle timeout above 300 s.

**Two modes, decided by the environment on every use.**

- *Edge mode* (`CAOS_EDGE_TOKEN` set -- the key): the key must be at least 32
  bytes, `CAOS_PUBLIC_ORIGIN` a bare `scheme://host[:port]`, and the
  development trust switch absent, or boot refuses `EDGE_CONFIG_INVALID` (and
  a request meeting such a configuration later is not trusted). Every request
  but `GET|HEAD /api/health` carries exactly one assertion that verifies under
  `hmac.compare_digest`, names this request's method and target, was issued
  within `ASSERTION_MAX_AGE_SECONDS` of now, and carries a nonce this process
  has not seen inside that window -- or it is answered 403 `EDGE_NOT_TRUSTED`
  before routing, identity or body. The subject and groups the application
  then reads are **the verified assertion's**: the guard removes every
  identity header the request arrived with and writes those two from the
  assertion, so a header a misconfigured proxy forwarded unsigned decides
  nothing.
- *Dev mode* (no key): served only when both socket ends are loopback
  addresses and `Host` is `localhost`, `127.0.0.1` or `[::1]`. A published port
  on a keyless image therefore answers health and nothing else, and a DNS
  rebinding page is refused by its `Host`. No edge asserted anything here, so
  `caos/api/identity.py` reads no groups header at all in this mode: a peer
  that passes the loopback check is READER unless the development switch is on.

In both modes the assertion header is removed from the scope, so no
application, log or refusal downstream can hold it; a repeated or lookalike
identity header is 401 `NOT_AUTHENTICATED`; `/api` is checked for Origin and
`Sec-Fetch-Site` (the second half of Task 4.2's CSRF split); and every response
carries the security headers and policy, with no cookie and no CORS header.

No header value is ever logged, formatted into a body or compared outside
`hmac.compare_digest`: the refusal bodies are constants, and an unhandled
fault is logged as its class and the frame it was raised in, never its message
(AS-6). The nonce register is one process's memory: the image runs one uvicorn
worker, and a second process would hold a register of its own
(`docs/rebuild/decisions.md`).
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import ipaddress
import json
import os
import re
import sys
import time
import traceback
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from urllib.parse import urlsplit

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from caos.api.identity import (
    EDGE_TOKEN_ENV,
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
EDGE_ASSERTION_HEADER = "x-caos-edge-assertion"
MIN_KEY_BYTES = 32

# The assertion. `v1.<payload>.<mac>`, both base64url without padding; the
# payload is the canonical JSON below and the MAC is HMAC-SHA256 under the key
# over a domain tag and those exact bytes. An assertion is good for
# `ASSERTION_MAX_AGE_SECONDS` either side of its issued-at second (the edge and
# the API keep their own clocks), and its nonce is remembered for as long as it
# could still verify. The register is bounded and refuses when full rather than
# forgetting a nonce early: a full register means far more than the image's own
# concurrency limit of requests inside one window, and a replay admitted under
# load is the one thing this exists to refuse.
ASSERTION_VERSION = "v1"
ASSERTION_DOMAIN = b"caos-edge-assertion-v1\n"
ASSERTION_MAX_AGE_SECONDS = 30
ASSERTION_MAX_BYTES = 4096
NONCE_HEX_CHARS = 32
NONCE_CAPACITY = 65_536
_PAYLOAD_KEYS = frozenset(
    {"subject", "groups", "method", "target", "issued_at", "nonce"}
)
_PRINTABLE = re.compile(r"^[\x21-\x7e]{1,256}$")  # ASCII, no space, no control
_METHOD = re.compile(r"^[A-Z]{1,16}$")
_NONCE = re.compile(rf"^[0-9a-f]{{{NONCE_HEX_CHARS}}}$")

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
    """Edge mode when `key` is set; platform mode behind a Databricks App;
    dev mode when neither."""

    key: bytes | None
    public_origin: str | None
    platform: bool = False


def resolve_mode(environ: Mapping[str, str] | None = None) -> EdgeMode:
    """The mode this environment declares, or `EDGE_CONFIG_INVALID`."""
    env = os.environ if environ is None else environ
    key = env.get(EDGE_TOKEN_ENV)
    if env.get(PLATFORM_ENV):
        return _platform_mode(env, key)
    if key is None:
        return EdgeMode(key=None, public_origin=None)
    encoded = key.encode()
    origin = env.get(PUBLIC_ORIGIN_ENV)
    if (
        len(encoded) < MIN_KEY_BYTES
        or TRUST_SWITCH in env
        or origin is None
        or not _bare_origin(origin)
    ):
        raise Refusal(RefusalCode.EDGE_CONFIG_INVALID)
    return EdgeMode(key=encoded, public_origin=origin)


def _platform_mode(env: Mapping[str, str], key: str | None) -> EdgeMode:
    """Platform mode, or `EDGE_CONFIG_INVALID` for the four ways it is not one.

    A key or the trust switch beside the platform is a configuration that
    cannot mean anything: the platform is the edge. Every subject is minted
    under the workspace id (F46), so a process without one would name
    everybody under an empty workspace. And the workspace this process asks
    about a caller's token has to be one it can reach: a `DATABRICKS_HOST`
    with a non-numeric port, or an `http://` host that is not this machine,
    used to be found on the first request -- the first as an untyped
    `ValueError` answered 500, the second as a bearer sent in clear (EI-N2,
    EI-N3). Boot is where a configuration is answered.
    """
    origin = env.get(PUBLIC_ORIGIN_ENV)
    host = env.get(HOST_ENV)
    if key is not None or TRUST_SWITCH in env:
        raise Refusal(RefusalCode.EDGE_CONFIG_INVALID)
    if not env.get(WORKSPACE_ENV):
        raise Refusal(RefusalCode.EDGE_CONFIG_INVALID)
    if origin is not None and not _bare_origin(origin):
        raise Refusal(RefusalCode.EDGE_CONFIG_INVALID)
    if host and workspace_address(host) is None:
        raise Refusal(RefusalCode.EDGE_CONFIG_INVALID)
    return EdgeMode(key=None, public_origin=origin, platform=True)


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


# --- the assertion -----------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Asserted:
    """What a verified assertion says about the caller: the subject as the
    edge asserted it (identity parses it as a UUID) and the sorted groups."""

    subject: str
    groups: tuple[str, ...]


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _unb64(text: str) -> bytes | None:
    if not re.fullmatch(r"[A-Za-z0-9_-]*", text):
        return None
    try:
        return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))
    except (binascii.Error, ValueError):
        return None


def _payload(  # noqa: PLR0913 -- the six fields one assertion binds
    *,
    subject: str,
    groups: Iterable[str],
    method: str,
    target: str,
    issued_at: int,
    nonce: str,
) -> bytes:
    """The canonical bytes both ends sign: sorted keys, no whitespace, groups
    sorted and unique."""
    document = {
        "subject": subject,
        "groups": sorted(set(groups)),
        "method": method,
        "target": target,
        "issued_at": issued_at,
        "nonce": nonce,
    }
    return json.dumps(document, sort_keys=True, separators=(",", ":")).encode()


def _mac(key: bytes, payload: bytes) -> bytes:
    return hmac.new(key, ASSERTION_DOMAIN + payload, hashlib.sha256).digest()


def sign_assertion(  # noqa: PLR0913 -- the six fields one assertion binds
    key: bytes,
    *,
    subject: str,
    groups: Iterable[str],
    method: str,
    target: str,
    issued_at: int,
    nonce: str,
) -> str:
    """The header value an edge sets for one request. Defined beside the
    verifier so the two cannot drift; the operator's edge implements exactly
    this, and the journey's test edge imports it."""
    payload = _payload(
        subject=subject,
        groups=groups,
        method=method,
        target=target,
        issued_at=issued_at,
        nonce=nonce,
    )
    return f"{ASSERTION_VERSION}.{_b64(payload)}.{_b64(_mac(key, payload))}"


class NonceRegister:
    """The nonces this process has admitted and until when each could still
    verify. Bounded; a full register refuses rather than forgetting."""

    def __init__(self, capacity: int = NONCE_CAPACITY) -> None:
        self._capacity = capacity
        self._seen: dict[str, float] = {}

    def admit(self, nonce: str, *, expires_at: float, now: float) -> bool:
        # The assertion age check admits the exact expiry instant, so retain its
        # nonce until strictly after that instant.
        expired = [seen for seen, until in self._seen.items() if until < now]
        for seen in expired:
            del self._seen[seen]
        if nonce in self._seen or len(self._seen) >= self._capacity:
            return False
        self._seen[nonce] = expires_at
        return True


def _shape(decoded: object) -> tuple[str, tuple[str, ...], str, str, int, str] | None:
    """The payload's closed shape, or None. Every field typed and bounded, the
    groups in canonical order, so that the bytes the MAC bound are the only
    bytes that could have produced them."""
    if not isinstance(decoded, dict) or set(decoded) != _PAYLOAD_KEYS:
        return None
    subject, groups = decoded["subject"], decoded["groups"]
    method, target = decoded["method"], decoded["target"]
    issued_at, nonce = decoded["issued_at"], decoded["nonce"]
    if not (isinstance(subject, str) and _PRINTABLE.match(subject)):
        return None
    if not isinstance(groups, list) or not all(
        isinstance(group, str) and _PRINTABLE.match(group) and "," not in group
        for group in groups
    ):
        return None
    if groups != sorted(set(groups)):
        return None
    if not (isinstance(method, str) and _METHOD.match(method)):
        return None
    if not (isinstance(target, str) and target.startswith("/") and "\n" not in target):
        return None
    if isinstance(issued_at, bool) or not isinstance(issued_at, int):
        return None
    if not (isinstance(nonce, str) and _NONCE.match(nonce)):
        return None
    return subject, tuple(groups), method, target, issued_at, nonce


def verify_assertion(  # noqa: PLR0913 -- the key, the header, the request and the clock
    key: bytes,
    presented: bytes,
    *,
    method: str,
    target: str,
    now: float,
    nonces: NonceRegister,
) -> Asserted | None:
    """The caller a presented assertion proves for this request, or None.

    The MAC is checked before the payload is read, so nothing unauthenticated
    is parsed; then the shape, the binding to this method and target, the age
    either side of now, and the nonce. None says nothing about which check
    failed: the refusal on the wire is one constant body either way.
    """
    if len(presented) > ASSERTION_MAX_BYTES:
        return None
    try:
        version, encoded_payload, encoded_mac = presented.decode("ascii").split(".")
    except (UnicodeDecodeError, ValueError):
        return None
    if version != ASSERTION_VERSION:
        return None
    payload, mac = _unb64(encoded_payload), _unb64(encoded_mac)
    if (
        payload is None
        or mac is None
        or not hmac.compare_digest(mac, _mac(key, payload))
    ):
        return None
    try:
        decoded = json.loads(payload)
    except ValueError:
        return None
    shape = _shape(decoded)
    if shape is None:
        return None
    subject, groups, for_method, for_target, issued_at, nonce = shape
    if for_method != method or for_target != target:
        return None
    if abs(now - issued_at) > ASSERTION_MAX_AGE_SECONDS:
        return None
    if not nonces.admit(
        nonce, expires_at=issued_at + ASSERTION_MAX_AGE_SECONDS, now=now
    ):
        return None
    return Asserted(subject=subject, groups=groups)


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


def _target(scope: Scope) -> str:
    """The raw target as the client sent it: the undecoded path and the query,
    which is what the edge signed."""
    raw: bytes = scope.get("raw_path") or scope.get("path", "").encode()
    target: str = raw.decode("latin-1")
    query: bytes = scope.get("query_string", b"")
    return target + "?" + query.decode("latin-1") if query else target


class EdgeGuard:
    """Pure ASGI middleware in front of the API and the static site."""

    def __init__(self, app: ASGIApp, *, clock: Callable[[], float] = time.time) -> None:
        self.app = app
        self.clock = clock
        self.nonces = NonceRegister()

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
        refusal, asserted, mode = self._refusal(scope, path)
        # The assertion is gone before any other code -- a refusal included --
        # runs, and wherever an edge exists (a key, the platform, or a mode
        # that would not resolve) so is every identity header the request
        # carried, on the health path too (F44): what the application reads
        # is the verified assertion's, or nothing.
        edged = mode is None or mode.platform or mode.key is not None
        scope["headers"] = _rewritten(scope.get("headers", []), asserted, edged=edged)
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
    ) -> tuple[RefusalCode | None, Asserted | None, EdgeMode | None]:
        method = scope.get("method", "")
        headers: list[tuple[bytes, bytes]] = list(scope.get("headers", []))
        health = path == HEALTH_PATH and method in _SAFE
        try:
            mode = resolve_mode()
        except Refusal:
            return (None if health else RefusalCode.EDGE_NOT_TRUSTED), None, None
        if health:
            return None, None, mode
        asserted: Asserted | None = None
        if mode.key is not None:
            asserted = self._asserted(mode.key, scope, method, headers)
            if asserted is None:
                return RefusalCode.EDGE_NOT_TRUSTED, None, mode
        elif not mode.platform and not _dev_peer(scope, headers):
            return RefusalCode.EDGE_NOT_TRUSTED, None, mode
        if not _hygienic(headers):
            return RefusalCode.NOT_AUTHENTICATED, None, mode
        # The one header that decides identity behind the platform gets the
        # hygiene the others get (F44): two of them name nobody.
        if mode.platform and len(_all(headers, PLATFORM_HEADER)) > 1:
            return RefusalCode.NOT_AUTHENTICATED, None, mode
        if is_api_path(path) and not _origin_allowed(mode, method, headers):
            return RefusalCode.ORIGIN_REFUSED, None, mode
        return None, asserted, mode

    def _asserted(
        self, key: bytes, scope: Scope, method: str, headers: list[tuple[bytes, bytes]]
    ) -> Asserted | None:
        presented = _all(headers, EDGE_ASSERTION_HEADER)
        if len(presented) != 1:
            return None
        return verify_assertion(
            key,
            presented[0],
            method=method,
            target=_target(scope),
            now=self.clock(),
            nonces=self.nonces,
        )


def _rewritten(
    headers: list[tuple[bytes, bytes]],
    asserted: Asserted | None,
    *,
    edged: bool = False,
) -> list[tuple[bytes, bytes]]:
    """The scope's headers without the assertion, and -- when one verified, or
    an edge exists at all -- without any identity header the request carried,
    the assertion's subject and groups written in their place.

    `edged` rather than `platform` (EI-N5): the caller passes True behind the
    platform, in edge mode, *and* under a configuration that would not resolve,
    so a name meaning only the first of the three misread the other two.
    """
    dropped = {EDGE_ASSERTION_HEADER.encode()}
    if asserted is not None or edged:
        dropped |= {name.encode() for name in _IDENTITY}
    kept = [(key, value) for key, value in headers if key.lower() not in dropped]
    if asserted is not None:
        kept.append((SUBJECT_HEADER.encode(), asserted.subject.encode("ascii")))
        kept.append((GROUPS_HEADER.encode(), ",".join(asserted.groups).encode("ascii")))
    return kept


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


def _secured(send: Send, path: str) -> Send:
    """Every response start gains the policy and loses any cookie or CORS."""
    if is_api_path(path):
        cache = "no-store"
    elif path.startswith("/assets/"):
        cache = _ASSET_CACHE
    else:
        cache = "no-cache"

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

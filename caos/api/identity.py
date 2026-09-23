"""Who is asking. Derived from what the edge asserted, never from what the client
claimed about itself.

The spec's §8 (`docs/rebuild/2026-09-22-caos-databricks-spec.md`) and D10 in
`docs/rebuild/decisions.md`. The host sits behind a proxy that authenticates
the caller, and what that proxy hands over is the whole input.

*Behind a Databricks App* (platform mode, the production deployment) the proxy
forwards the caller's own access token, and this module asks the workspace who
holds it: one bounded SCIM `Me` round trip per token digest, remembered for
`CACHE_SECONDS`. So a group list is **not** the only thing read in production,
and this module is not free: `IO_BUDGET` below counts store round trips and
says so.

*In edge mode* the proxy asserts the subject and its groups instead, and those
two reach this module as the two headers `caos/api/edge.py`'s guard **wrote**
from the request's verified per-request assertion, after removing every
identity header the request arrived with -- so a proxy that forwarded a
client-supplied `x-forwarded-groups` unsigned is not a misconfiguration this
code cannot detect any more: the forwarded header is dropped and the
assertion's groups are what is read. The role header is off by default.

Which of the two carries the role is the deployment's mode, and the role is
never a third thing. In edge mode (`CAOS_EDGE_TOKEN` set -- the assertion key)
the groups decide it, because a proxy stood between the client and this
process and signed what it asserted. Without a key the groups header proves
nothing -- no edge asserted it -- so it is not read at all, and the role comes
from the role header only while the development switch below asks for it. A
process configured as neither serves READER, whatever arrives.

Two things this deliberately does not do.

*It does not carry per-case standing.* A `GlobalRole` says what kind of account
this is, not what it may do to a particular case; that is `case_members`, checked
at commit time inside the store call. An actor arriving at a route already
holding case authority would be authority checked at the request, which §8 says
is not the place.

*It does not carry persona.* Which section a user is reading composes a view and
grants nothing, so it is not on the actor and cannot be mistaken for authority.
"""

from __future__ import annotations

import http.client
import json
import os
import threading
import time
from collections.abc import Container
from dataclasses import dataclass, field
from enum import StrEnum
from hashlib import sha256
from urllib.parse import urlsplit
from uuid import NAMESPACE_URL, UUID, uuid5

from caos.refusals import Refusal, RefusalCode

# No *store* round trips: nothing here opens a connection or reads a row.
# Platform mode does make one bounded SCIM call to the workspace per token
# digest (`scim_me`), which is not what this number counts; it is stated here
# so the two are never read as one. Declared rather than exempted, because
# `caos/api/` is where every module is on a request path and "it does no store
# I/O" is a fact worth stating rather than a rule a gate has to infer every
# time (`scripts/io_budget.py`). The day this reads a user row, this moves.
IO_BUDGET = 0

# The development convenience, and it is opt-in. An environment variable that had
# to be set to *disable* trust is one a deployment forgets, and that failure is
# silent and total: every request would arrive as whatever it said it was. The
# same reasoning is why the groups header is an edge-mode header: reading it
# without a token would be the forgettable default in the other direction, one
# any peer that reached a tokenless listener could use to name itself ADMIN.
TRUST_SWITCH = "CAOS_TRUST_ROLE_HEADER"
TRUSTED = "1"

SUBJECT_HEADER = "x-caos-user"
GROUPS_HEADER = "x-forwarded-groups"  # edge mode only: written from the assertion
ROLE_HEADER = "x-caos-role"
# Edge mode (`caos/api/edge.py`): the per-request assertion's HMAC key. While
# this is set, the switch above is never believed, whatever it says -- boot
# refuses the pair, and this is the rule a request meeting the pair anyway
# still obeys. The name predates §93, when the value was a static shared
# secret; it is kept so no deployment's environment moves.
EDGE_TOKEN_ENV = "CAOS_EDGE_TOKEN"  # nosec B105 -- a variable name, not a secret
# Platform mode (D10): Databricks Apps forward the caller's own access token in
# this header; the caller is then whoever the workspace says holds it (SCIM
# `Me`), and the role is read from the workspace groups named below.
PLATFORM_ENV = "DATABRICKS_APP_NAME"
PLATFORM_HEADER = "x-forwarded-access-token"
GROUP_ADMIN_ENV = "CAOS_GROUP_ADMIN"
GROUP_ANALYST_ENV = "CAOS_GROUP_ANALYST"
WORKSPACE_ENV = "DATABRICKS_WORKSPACE_ID"
HOST_ENV = "DATABRICKS_HOST"
# Subjects are minted from the workspace and the SCIM id, never from a name.
NAMESPACE = uuid5(NAMESPACE_URL, "caos.databricks.identity")
# F13. A role held on a token outlives the group membership that granted it by
# up to this long, and there is no way to invalidate one entry: the cost the
# TTL buys is one SCIM call per token per five minutes instead of one per
# request. Recorded rather than changed (EI-N1).
CACHE_SECONDS = 300.0


class GlobalRole(StrEnum):
    """What kind of account this is. Not what it may do to a given case."""

    READER = "READER"
    ANALYST = "ANALYST"
    ADMIN = "ADMIN"


# Written out rather than derived from declaration order, so that adding a role
# in the middle of the enum cannot silently reorder authority.
_RANK = {GlobalRole.READER: 0, GlobalRole.ANALYST: 1, GlobalRole.ADMIN: 2}


def at_least(role: GlobalRole, floor: GlobalRole) -> bool:
    """Whether `role` ranks at or above `floor`.

    The one comparison a global floor needs, read from `_RANK` rather than
    from identity, so a role added above the floor later is admitted and one
    added below it is not -- which `is` against a single member would get
    wrong in both directions.
    """
    return _RANK[role] >= _RANK[floor]


# The identity provider's groups, mapped to this system's words. Both names are
# the deployment's to choose, and they are read in **every** mode. A literal
# only platform mode honoured meant `CAOS_GROUP_ADMIN` granted nothing in edge
# mode while any IdP group that happened to be spelled `caos-admins` granted
# ADMIN there (EI-W2); one reader of the two variables is the whole fix.
# A group neither variable names grants nothing -- an unknown group is not an
# unknown *role*, it is a group about some other system. READER needs no name:
# it is what an authenticated caller holds before any group says otherwise.
GROUP_ADMIN_DEFAULT = "caos-admins"
GROUP_ANALYST_DEFAULT = "caos-analysts"


def role_from_groups(groups: Container[str]) -> GlobalRole:
    """The greatest role the configured group names carry, READER if neither.

    Read at the request rather than at import, for the reason
    `actor_from_headers` states: a process started against a wrong environment
    starts behaving correctly the moment it is corrected.
    """
    if (os.environ.get(GROUP_ADMIN_ENV) or GROUP_ADMIN_DEFAULT) in groups:
        return GlobalRole.ADMIN
    if (os.environ.get(GROUP_ANALYST_ENV) or GROUP_ANALYST_DEFAULT) in groups:
        return GlobalRole.ANALYST
    return GlobalRole.READER


@dataclass(frozen=True, slots=True)
class Actor:
    """The authenticated subject and its global role. Nothing else."""

    user_id: UUID
    role: GlobalRole


def actor_from_headers(headers: object) -> Actor:
    """The actor this request is from, or `NOT_AUTHENTICATED`.

    The switch is read here rather than at import, so a process started against a
    wrong environment starts behaving correctly the moment it is corrected --
    rather than for as long as it happens to stay up.
    """
    get = getattr(headers, "get", None)
    if get is None:
        raise Refusal(RefusalCode.NOT_AUTHENTICATED)
    if os.environ.get(PLATFORM_ENV):
        return actor_from_token(get(PLATFORM_HEADER))

    subject = get(SUBJECT_HEADER)
    if not isinstance(subject, str):
        raise Refusal(RefusalCode.NOT_AUTHENTICATED)
    try:
        user_id = UUID(subject)
    except ValueError:
        # `from None`: the ValueError's message is the header the client sent.
        raise Refusal(RefusalCode.NOT_AUTHENTICATED) from None

    if EDGE_TOKEN_ENV in os.environ:
        return Actor(user_id=user_id, role=_from_groups(get(GROUPS_HEADER)))
    if os.environ.get(TRUST_SWITCH) == TRUSTED:
        return Actor(user_id=user_id, role=_claimed(get(ROLE_HEADER)))
    # ponytail: no token and no switch is nobody's deployment; the lowest role,
    # never a header's word. The one line that closes C3.
    return Actor(user_id=user_id, role=GlobalRole.READER)


def _from_groups(groups: object) -> GlobalRole:
    """The greatest role the asserted group header carries, READER if none."""
    if not isinstance(groups, str):
        return GlobalRole.READER
    return role_from_groups({part.strip() for part in groups.split(",")})


def _claimed(role: object) -> GlobalRole:
    """The role the client asked for, when the switch says to believe it.

    Still a closed set: falling through to whatever string arrived would be
    trusting the header twice, once for the value and once for the vocabulary.
    """
    if not isinstance(role, str):
        return GlobalRole.READER
    try:
        return GlobalRole(role.strip().upper())
    except ValueError:
        return GlobalRole.READER


@dataclass(frozen=True, slots=True)
class WorkspaceUser:
    """What SCIM `Me` says about the token's holder: an id and group names."""

    scim_id: str
    groups: frozenset[str]


_CACHE: dict[str, tuple[Actor, float]] = {}
_NEGATIVE: dict[str, float] = {}
CACHE_CAPACITY = 4096
NEGATIVE_SECONDS = 5.0
SCIM_ME_PATH = "/api/2.0/preview/scim/v2/Me"
SCIM_TIMEOUT_SECONDS = 10.0
SCIM_BODY_BYTES = 1_048_576
# How long a request waits on the lookup another thread is already making for
# the very same token before answering `IDENTITY_UNAVAILABLE`. Longer than one
# round trip can take, so the wait ends because the lookup ended; bounded all
# the same, because a thread waiting forever on another thread's socket is the
# `LIMIT_CONCURRENCY` exhaustion the single flight exists to prevent.
SHARED_WAIT_SECONDS = SCIM_TIMEOUT_SECONDS * 2
_CACHE_LOCK = threading.Lock()


@dataclass
class _Flight:
    """One SCIM lookup in progress, and what it found. Shared by every request
    that arrives for the same token digest while it is open."""

    settled: threading.Event = field(default_factory=threading.Event)
    actor: Actor | None = None
    code: RefusalCode | None = None


_INFLIGHT: dict[str, _Flight] = {}


def actor_from_token(token: object) -> Actor:
    """The actor behind a platform-forwarded token, or `NOT_AUTHENTICATED`.

    One SCIM round trip per token, remembered for `CACHE_SECONDS` under the
    token's digest (never the token); a token the workspace refused is
    remembered for `NEGATIVE_SECONDS` so it costs one round trip, not one per
    request (F43). One round trip *concurrently*, too: requests that arrive
    for the same cold token while a lookup is open wait on that lookup instead
    of opening their own (EI-W3), because each of those holds a thread out of
    the process's `LIMIT_CONCURRENCY`. Both caches are bounded: expired entries
    go on every write and nothing is added past `CACHE_CAPACITY`. The subject
    is `uuid5` over the workspace and the SCIM id, so the same person is the
    same subject on every request and no name reaches the store. Roles come
    from the two configured group names; any other group grants nothing.
    """
    if not isinstance(token, str) or not token.strip():
        raise Refusal(RefusalCode.NOT_AUTHENTICATED)
    key = sha256(token.encode("utf-8")).hexdigest()
    remembered = _remembered(key)
    if remembered is not None:
        return remembered
    flight, leading = _flight(key)
    if not leading:
        return _shared(flight)
    try:
        actor = _looked_up(key, token)
    except Refusal as refused:
        flight.code = refused.code
        raise
    else:
        flight.actor = actor
        return actor
    finally:
        _settle(key, flight)


def _remembered(key: str) -> Actor | None:
    """What this process already knows about a token digest: the actor it
    names, `NOT_AUTHENTICATED` when the workspace refused it inside
    `NEGATIVE_SECONDS`, or None when the workspace has to be asked."""
    now = time.monotonic()
    with _CACHE_LOCK:
        cached = _CACHE.get(key)
        if cached is not None and cached[1] > now:
            return cached[0]
        if _NEGATIVE.get(key, 0.0) > now:
            raise Refusal(RefusalCode.NOT_AUTHENTICATED)
    return None


def _flight(key: str) -> tuple[_Flight, bool]:
    """The lookup this token digest is on, and whether this thread is the one
    that has to make it."""
    with _CACHE_LOCK:
        ongoing = _INFLIGHT.get(key)
        if ongoing is not None:
            return ongoing, False
        opened = _Flight()
        _INFLIGHT[key] = opened
        return opened, True


def _settle(key: str, flight: _Flight) -> None:
    """Close a lookup: no later request joins it, and every request already
    waiting on it is released. The identity is compared rather than the key,
    so a lookup that has already been replaced cannot remove its successor."""
    with _CACHE_LOCK:
        if _INFLIGHT.get(key) is flight:
            del _INFLIGHT[key]
    flight.settled.set()


def _shared(flight: _Flight) -> Actor:
    """What the thread already asking about this token found.

    A lookup that never settles, or settled with neither an actor nor a code,
    is `IDENTITY_UNAVAILABLE` rather than a second call to a workspace that is
    in no state to answer the first.
    """
    if not flight.settled.wait(SHARED_WAIT_SECONDS) or flight.actor is None:
        raise Refusal(flight.code or RefusalCode.IDENTITY_UNAVAILABLE)
    return flight.actor


def _looked_up(key: str, token: str) -> Actor:
    """One SCIM round trip, and what this process remembers of it.

    The clock is read *after* the call returns or raises (CR-7). Read before,
    a workspace that took longer than `NEGATIVE_SECONDS` to refuse a revoked
    token wrote an entry that had already expired, and every retry paid the
    same slow round trip again -- the cache failing exactly under the load it
    exists for.
    """
    try:
        user = _current_user(token)
    except Refusal as refused:
        if refused.code is RefusalCode.NOT_AUTHENTICATED:
            _deny(key, time.monotonic())
        raise
    workspace = os.environ.get(WORKSPACE_ENV, "")
    actor = Actor(
        user_id=uuid5(NAMESPACE, f"{workspace}:{user.scim_id}"),
        role=role_from_groups(user.groups),
    )
    _remember(key, actor, time.monotonic())
    return actor


def _deny(key: str, now: float) -> None:
    """Remember a refused token digest, pruned and bounded on the way in.

    Bounded here rather than only on the next successful lookup (AR-04): a
    process being handed one distinct rejected token after another never
    reaches that path, so the entries accumulated with nothing to sweep them
    and a later lookup had to walk the accumulation.
    """
    with _CACHE_LOCK:
        for stale in [k for k, until in _NEGATIVE.items() if until <= now]:
            del _NEGATIVE[stale]
        if len(_NEGATIVE) < CACHE_CAPACITY:
            _NEGATIVE[key] = now + NEGATIVE_SECONDS


def _remember(key: str, actor: Actor, now: float) -> None:
    """Remember what the workspace said, pruned and bounded on the way in."""
    with _CACHE_LOCK:
        for stale in [k for k, (_, until) in _CACHE.items() if until <= now]:
            del _CACHE[stale]
        for stale in [k for k, until in _NEGATIVE.items() if until <= now]:
            del _NEGATIVE[stale]
        if len(_CACHE) < CACHE_CAPACITY:
            _CACHE[key] = (actor, now + CACHE_SECONDS)


# `http://` is the loopback stand-in's (`tests/workspace_stub.py`) and nothing
# else. A platform-forwarded bearer is the caller's own credential, and sending
# one in clear to a host that is not this machine is not a deployment this
# process serves (EI-N3).
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})


@dataclass(frozen=True, slots=True)
class WorkspaceAddress:
    """Where SCIM is, as `DATABRICKS_HOST` names it."""

    secure: bool
    host: str
    port: int | None


def workspace_address(value: str | None) -> WorkspaceAddress | None:
    """The workspace `DATABRICKS_HOST` names, or None when it names nothing
    this process may send a bearer token to.

    None rather than an exception, because the two callers answer it with
    their own typed refusal: a request with `IDENTITY_UNAVAILABLE`, boot with
    `EDGE_CONFIG_INVALID`. Neither used to be reachable -- `DATABRICKS_HOST`
    with a non-numeric port raised an untyped `ValueError` out of
    `urlsplit(...).port` on the first request, which the edge answered 500
    (EI-N2).
    """
    if not value:
        return None
    try:
        parts = urlsplit(value if "://" in value else f"https://{value}")
        port = parts.port
    except ValueError:
        return None
    if parts.scheme not in ("http", "https") or not parts.hostname:
        return None
    if parts.username is not None or parts.password is not None:
        return None
    if parts.scheme == "http" and parts.hostname not in LOOPBACK_HOSTS:
        return None
    return WorkspaceAddress(
        secure=parts.scheme == "https", host=parts.hostname, port=port
    )


def _current_user(token: str) -> WorkspaceUser:
    """SCIM `Me` for the token's holder. The one seam the suite substitutes."""
    return scim_me(f"Bearer {token}")


def scim_me(authorization: str) -> WorkspaceUser:
    """SCIM `Me` for whoever `authorization` names, over one bounded request.

    Not through the SDK (F43): building its client performs an uncached
    discovery probe with a five-minute retry budget, and beside the app's own
    service-principal variables a forwarded token is refused as a second
    authentication method. Nothing of the credential or of a failure's text
    travels past this boundary: the workspace's refusal is
    `NOT_AUTHENTICATED`, anything else `IDENTITY_UNAVAILABLE`.

    The whole `Authorization` header rather than a token, so that the health
    probe can send the credentials the SDK minted for the process itself down
    this exact path, whatever scheme they carry (EI-W1): a host, a path or a
    scope requests would fail on then fails the probe too.
    """
    address = workspace_address(os.environ.get(HOST_ENV))
    if address is None:
        raise Refusal(RefusalCode.IDENTITY_UNAVAILABLE)
    opener: type[http.client.HTTPConnection] = (
        http.client.HTTPSConnection if address.secure else http.client.HTTPConnection
    )
    connection = opener(address.host, address.port, timeout=SCIM_TIMEOUT_SECONDS)
    try:
        connection.request(
            "GET",
            SCIM_ME_PATH,
            headers={"Authorization": authorization, "Accept": "application/json"},
        )
        response = connection.getresponse()
        status, body = response.status, response.read(SCIM_BODY_BYTES + 1)
    except (OSError, http.client.HTTPException):
        raise Refusal(RefusalCode.IDENTITY_UNAVAILABLE) from None
    finally:
        connection.close()
    if status in (401, 403):
        raise Refusal(RefusalCode.NOT_AUTHENTICATED)
    if status != 200 or len(body) > SCIM_BODY_BYTES:
        raise Refusal(RefusalCode.IDENTITY_UNAVAILABLE)
    return _scim_user(body)


def _scim_user(body: bytes) -> WorkspaceUser:
    """The id and the group names a SCIM `Me` body carries, or a refusal.

    Every shape is checked before it is walked (AR-12). `{"groups": true}`
    used to raise `TypeError` out of the comprehension below, and an upstream
    that answered nonsense then read on the wire as `INTERNAL_FAULT` -- this
    host's own fault -- rather than as the `IDENTITY_UNAVAILABLE` it is.
    """
    try:
        current = json.loads(body)
    except ValueError:
        raise Refusal(RefusalCode.IDENTITY_UNAVAILABLE) from None
    if not isinstance(current, dict):
        raise Refusal(RefusalCode.IDENTITY_UNAVAILABLE)
    scim_id = current.get("id")
    if not isinstance(scim_id, str) or not scim_id:
        raise Refusal(RefusalCode.NOT_AUTHENTICATED)
    listed = current.get("groups") or []
    if not isinstance(listed, list) or not all(
        isinstance(group, dict) for group in listed
    ):
        raise Refusal(RefusalCode.IDENTITY_UNAVAILABLE)
    groups = frozenset(
        group["display"] for group in listed if isinstance(group.get("display"), str)
    )
    return WorkspaceUser(scim_id=scim_id, groups=groups)

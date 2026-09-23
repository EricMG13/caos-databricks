"""Who is asking. Derived from what the edge asserted, never from what the client
claimed about itself.

`SYSTEM_SPEC.md` §8, and `docs/DECISIONS.md` §22 and §93. The host sits behind
a proxy that authenticates the caller and asserts the subject and its groups.
Those two are the whole input. In edge mode they reach this module as the two
headers `caos/api/edge.py`'s guard **wrote** from the request's verified
per-request assertion, after removing every identity header the request
arrived with -- so a proxy that forwarded a client-supplied
`x-forwarded-groups` unsigned is not a misconfiguration this code cannot
detect any more: the forwarded header is dropped and the assertion's groups
are what is read. The group list is the *only* thing this reads in production
and the role header is off by default.

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
from dataclasses import dataclass
from enum import StrEnum
from hashlib import sha256
from urllib.parse import urlsplit
from uuid import NAMESPACE_URL, UUID, uuid5

from caos.refusals import Refusal, RefusalCode

# No round trips: the actor comes out of two headers and a closed group table,
# and nothing here touches the store. Declared rather than exempted, because
# `caos/api/` is where every module is on a request path and "it does no I/O"
# is a fact worth stating rather than a rule a gate has to infer every time
# (`scripts/io_budget.py`). The day this reads a user row, this number moves.
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
# Subjects are minted from the workspace and the SCIM id, never from a name.
NAMESPACE = uuid5(NAMESPACE_URL, "caos.databricks.identity")
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


# The identity provider's groups, mapped to this system's words. A group absent
# from here grants nothing -- an unknown group is not an unknown *role*, it is a
# group about some other system.
_GROUPS = {
    "caos-readers": GlobalRole.READER,
    "caos-analysts": GlobalRole.ANALYST,
    "caos-admins": GlobalRole.ADMIN,
}


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
    """The greatest role any asserted group carries, READER if none does."""
    if not isinstance(groups, str):
        return GlobalRole.READER
    held = [
        _GROUPS[name]
        for name in (part.strip() for part in groups.split(","))
        if name in _GROUPS
    ]
    return max(held, key=_RANK.__getitem__, default=GlobalRole.READER)


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
_CACHE_LOCK = threading.Lock()


def actor_from_token(token: object) -> Actor:
    """The actor behind a platform-forwarded token, or `NOT_AUTHENTICATED`.

    One SCIM round trip per token, remembered for `CACHE_SECONDS` under the
    token's digest (never the token); a token the workspace refused is
    remembered for `NEGATIVE_SECONDS` so it costs one round trip, not one per
    request (F43). The cache is bounded: expired entries go on every write
    and nothing is added past `CACHE_CAPACITY`. The subject is `uuid5` over
    the workspace and the SCIM id, so the same person is the same subject on
    every request and no name reaches the store. Roles come from the two
    configured group names; any other group grants nothing.
    """
    if not isinstance(token, str) or not token.strip():
        raise Refusal(RefusalCode.NOT_AUTHENTICATED)
    key = sha256(token.encode("utf-8")).hexdigest()
    now = time.monotonic()
    with _CACHE_LOCK:
        cached = _CACHE.get(key)
        if cached is not None and cached[1] > now:
            return cached[0]
        if _NEGATIVE.get(key, 0.0) > now:
            raise Refusal(RefusalCode.NOT_AUTHENTICATED)
    try:
        user = _current_user(token)
    except Refusal as refused:
        if refused.code is RefusalCode.NOT_AUTHENTICATED:
            with _CACHE_LOCK:
                _NEGATIVE[key] = now + NEGATIVE_SECONDS
        raise
    workspace = os.environ.get(WORKSPACE_ENV, "")
    actor = Actor(
        user_id=uuid5(NAMESPACE, f"{workspace}:{user.scim_id}"),
        role=_platform_role(user.groups),
    )
    with _CACHE_LOCK:
        for stale in [k for k, (_, until) in _CACHE.items() if until <= now]:
            del _CACHE[stale]
        for stale in [k for k, until in _NEGATIVE.items() if until <= now]:
            del _NEGATIVE[stale]
        if len(_CACHE) < CACHE_CAPACITY:
            _CACHE[key] = (actor, now + CACHE_SECONDS)
    return actor


def _platform_role(groups: frozenset[str]) -> GlobalRole:
    admin = os.environ.get(GROUP_ADMIN_ENV) or "caos-admins"
    analyst = os.environ.get(GROUP_ANALYST_ENV) or "caos-analysts"
    if admin in groups:
        return GlobalRole.ADMIN
    if analyst in groups:
        return GlobalRole.ANALYST
    return GlobalRole.READER


def _current_user(token: str) -> WorkspaceUser:
    """SCIM `Me` for the token's holder, over one bounded HTTP request.

    Not through the SDK (F43): building its client performs an uncached
    discovery probe with a five-minute retry budget, and beside the app's own
    service-principal variables a forwarded token is refused as a second
    authentication method. Nothing of the token or of a failure's text
    travels past this boundary: the workspace's refusal is
    `NOT_AUTHENTICATED`, anything else `IDENTITY_UNAVAILABLE`.
    """
    host = os.environ.get("DATABRICKS_HOST") or ""
    parts = urlsplit(host if "://" in host else f"https://{host}")
    if not parts.hostname:
        raise Refusal(RefusalCode.IDENTITY_UNAVAILABLE)
    connection: http.client.HTTPConnection
    if parts.scheme == "http":
        connection = http.client.HTTPConnection(
            parts.hostname, parts.port, timeout=SCIM_TIMEOUT_SECONDS
        )
    else:
        connection = http.client.HTTPSConnection(
            parts.hostname, parts.port, timeout=SCIM_TIMEOUT_SECONDS
        )
    try:
        connection.request(
            "GET",
            SCIM_ME_PATH,
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
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
    try:
        current = json.loads(body)
    except ValueError:
        raise Refusal(RefusalCode.IDENTITY_UNAVAILABLE) from None
    scim_id = current.get("id") if isinstance(current, dict) else None
    if not isinstance(scim_id, str) or not scim_id:
        raise Refusal(RefusalCode.NOT_AUTHENTICATED)
    listed = current.get("groups") or []
    groups = frozenset(
        str(group["display"])
        for group in listed
        if isinstance(group, dict) and isinstance(group.get("display"), str)
    )
    return WorkspaceUser(scim_id=scim_id, groups=groups)

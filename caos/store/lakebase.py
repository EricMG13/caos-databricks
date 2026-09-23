"""Where the store's connection string comes from: an explicit URL, or Lakebase.

Spec section 4 (R11). Locally and in tests `CAOS_DATABASE_URL` is the whole
answer. On Databricks Apps the platform injects `PGHOST`, `PGPORT`,
`PGDATABASE`, `PGUSER` and `PGSSLMODE` for the app's database resource, and
the password is a short-lived credential the SDK mints for the app's service
principal. Tokens live about an hour, so one is refreshed well before that and
every new connection gets a fresh one after it ages out.

Minting is single-flight and bounded (MX-3, DL-4): one caller mints; a caller
that arrives while that mint is in flight is handed the held token when the
server still accepts it (ST-1) and waits for the mint only when there is none;
a mint that has not answered within `MINT_SECONDS` is abandoned as
`STORE_UNAVAILABLE`, a failed mint is not retried for `FAILURE_SECONDS`, and a
token the server still accepts is used until its real expiry when a fresh one
cannot be had. A token is refreshed at `TOKEN_SECONDS` or at the server's
stated expiry, whichever is sooner (ST-3). No lock is held across the network.

No credential is ever printed, logged or written; the URL this returns is
handed straight to the driver.
"""

from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import quote
from uuid import uuid4

import psycopg

from caos.refusals import Refusal, RefusalCode

DATABASE_URL = "CAOS_DATABASE_URL"
LAKEBASE_INSTANCE = "CAOS_LAKEBASE_INSTANCE"
AUTOSCALING_ENDPOINT = "LAKEBASE_AUTOSCALING_ENDPOINT"
# Databricks Apps inject these for the first database resource (R11).
PG_ENV = ("PGHOST", "PGPORT", "PGDATABASE", "PGUSER")
# Below the credential life the vendor library plans for (a 15-minute cache
# and a 14-minute pool recycle in `databricks_ai_bridge.lakebase`, the same
# figure the build contract names), with room for a slow connect. F37.
TOKEN_SECONDS = 14 * 60
# The most any caller waits on a mint: the SDK's own retry budget.
MINT_SECONDS = 30.0
# A failed mint is not retried for this long, so a stalled token endpoint
# costs one bounded wait, not one per request.
FAILURE_SECONDS = 5.0
# How long before the server's stated expiry a token stops being reused.
EXPIRY_MARGIN_SECONDS = 60.0


@dataclass(frozen=True, slots=True)
class _Credential:
    token: str
    refresh_at: float  # monotonic: mint a fresh one after this
    expires_at: float  # monotonic: the server stops accepting it here
    minted_at: float = 0.0  # monotonic: when it was minted


_LOCK = threading.Lock()  # guards `_CACHED` and `_REFUSED_UNTIL`; never held on I/O
_MINTING = threading.Lock()  # single-flight: one mint at a time
_CACHED: _Credential | None = None
_REFUSED_UNTIL = 0.0


def store_url() -> str:
    """The connection string for this environment, or `STORE_NOT_CONFIGURED`."""
    url = os.environ.get(DATABASE_URL)
    if url:
        return url
    values = {name: os.environ.get(name) for name in PG_ENV}
    if not all(values.values()):
        raise Refusal(RefusalCode.STORE_NOT_CONFIGURED)
    port = str(values["PGPORT"])
    if not (port.isascii() and port.isdigit()):
        raise Refusal(RefusalCode.STORE_NOT_CONFIGURED)
    user = quote(str(values["PGUSER"]), safe="")
    password = quote(_credential(), safe="")
    host = quote(str(values["PGHOST"]), safe="")
    database = quote(str(values["PGDATABASE"]), safe="")
    # `verify-full` with `PGSSLROOTCERT` authenticates the server (MX-7);
    # libpq reads that variable itself, so only the mode travels here.
    sslmode = quote(os.environ.get("PGSSLMODE", "require"), safe="")
    return f"postgresql://{user}:{password}@{host}:{port}/{database}?sslmode={sslmode}"


def invalidate_credential() -> None:
    """Forget the cached credential; the next connection mints a fresh one."""
    global _CACHED, _REFUSED_UNTIL
    with _LOCK:
        _CACHED = None
        _REFUSED_UNTIL = 0.0


def note_connect_failure(failed: psycopg.OperationalError) -> None:
    """A failed connection drops the cached credential (F37, AR-02).

    The driver reports a refused password as a bare `OperationalError` with no
    SQLSTATE, the same shape as an unreachable host, so no class narrows it: a
    re-mint after any connection failure costs one bounded SDK call, and a
    token revoked or rotated early would otherwise be handed to the driver
    until the clock said otherwise. Bounded (MAX-03): a credential minted
    under `FAILURE_SECONDS` ago is kept, so a store that is down costs one
    mint per `FAILURE_SECONDS` however many connections fail, not one each.
    """
    del failed
    held = _held()
    if held is not None and time.monotonic() - held.minted_at < FAILURE_SECONDS:
        return
    invalidate_credential()


def _credential() -> str:
    """A Lakebase credential for the app's service principal, cached briefly."""
    held = _held()
    now = time.monotonic()
    if held is not None and held.refresh_at > now:
        return held.token
    # Only a caller with no live token waits on a mint in flight (ST-1): the
    # rest are handed the token the server still accepts at once.
    live = held is not None and held.expires_at > now
    if not _MINTING.acquire(blocking=not live):
        return _live_or_refused()
    try:
        held = _held()  # the minter before us may have answered
        now = time.monotonic()
        if held is not None and held.refresh_at > now:
            return held.token
        try:
            return _refreshed(now)
        except Refusal:
            # Read afresh (ST-3): a credential another path reported refused
            # while this mint was failing is gone, not handed back.
            return _live_or_refused()
    finally:
        _MINTING.release()


def _live_or_refused() -> str:
    """The held token while the server still accepts it (DL-4), else the
    typed refusal."""
    held = _held()
    if held is not None and held.expires_at > time.monotonic():
        return held.token
    raise Refusal(RefusalCode.STORE_UNAVAILABLE)


def _held() -> _Credential | None:
    with _LOCK:
        return _CACHED


def _refreshed(now: float) -> str:
    """Mint under the failure cache and record the result."""
    global _CACHED, _REFUSED_UNTIL
    with _LOCK:
        refused_until = _REFUSED_UNTIL
    if refused_until > now:
        raise Refusal(RefusalCode.STORE_UNAVAILABLE)
    try:
        token, expires_at = _mint_bounded()
    except Refusal:
        with _LOCK:
            _REFUSED_UNTIL = time.monotonic() + FAILURE_SECONDS
        raise
    minted = time.monotonic()
    # Refreshed before the server's stated expiry when that comes first (ST-3):
    # a short-lived credential is never handed out past it.
    refresh_at = min(minted + TOKEN_SECONDS, expires_at)
    with _LOCK:
        _CACHED = _Credential(token, refresh_at, expires_at, minted)
    return token


def _mint_bounded() -> tuple[str, float]:
    """`_mint` on a helper thread, abandoned past `MINT_SECONDS` (MX-3): the
    SDK posts to the token endpoint with no timeout of its own."""
    outcome: list[tuple[str, float] | Refusal] = []

    def run() -> None:
        try:
            outcome.append(_mint())
        except Refusal as refused:
            outcome.append(refused)

    minter = threading.Thread(target=run, name="caos-lakebase-mint", daemon=True)
    minter.start()
    minter.join(MINT_SECONDS)
    if not outcome:
        raise Refusal(RefusalCode.STORE_UNAVAILABLE)
    answer = outcome[0]
    if isinstance(answer, Refusal):
        raise answer
    return answer


def _mint() -> tuple[str, float]:
    """One credential from the SDK's unified auth: instance or endpoint form,
    with the monotonic instant the server stops accepting it."""
    from caos.workspace import workspace_client

    instance = os.environ.get(LAKEBASE_INSTANCE)
    endpoint = os.environ.get(AUTOSCALING_ENDPOINT)
    issued: object
    try:
        client = workspace_client()
        if instance:
            issued = client.database.generate_database_credential(
                request_id=str(uuid4()), instance_names=[instance]
            )
        elif endpoint:
            issued = client.postgres.generate_database_credential(endpoint=endpoint)
        else:
            raise Refusal(RefusalCode.STORE_NOT_CONFIGURED)
    except (OSError, ValueError):
        # `DatabricksError` is an `IOError` and the SDK's auth failures are
        # `ValueError`s; either message may name the host (CR-1).
        raise Refusal(RefusalCode.STORE_UNAVAILABLE) from None
    token = getattr(issued, "token", None)
    if not isinstance(token, str) or not token:
        raise Refusal(RefusalCode.STORE_UNAVAILABLE)
    # The provisioned form states `expiration_time` as text; the autoscaling
    # form states `expire_time` as a protobuf `Timestamp` (ST-3, MAX-15).
    stated = getattr(issued, "expiration_time", None)
    if stated is None:
        stated = getattr(issued, "expire_time", None)
    return token, _expires_at(stated)


def _expires_at(stated: object) -> float:
    """The server's expiry as a monotonic instant, less a margin; a missing or
    unreadable one gives the token no life beyond its refresh."""
    when = _stated_instant(stated)
    if when is None:
        return time.monotonic() + TOKEN_SECONDS
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    left = (when - datetime.now(UTC)).total_seconds() - EXPIRY_MARGIN_SECONDS
    return time.monotonic() + max(left, 0.0)


def _stated_instant(stated: object) -> datetime | None:
    """An ISO-8601 string or a `Timestamp`-shaped value as a datetime, or None."""
    if isinstance(stated, str):
        try:
            return datetime.fromisoformat(stated.replace("Z", "+00:00"))
        except ValueError:
            return None
    to_datetime = getattr(stated, "ToDatetime", None)
    if not callable(to_datetime):
        return None
    try:
        when = to_datetime(tzinfo=UTC)
    except (TypeError, ValueError, OverflowError):
        return None
    return when if isinstance(when, datetime) else None

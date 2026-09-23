"""`GET /api/health`: readiness over store, bundle and blobs, read from a cache.

The spec's §11 (`docs/rebuild/2026-09-22-caos-databricks-spec.md`). One
background task, started in the app's lifespan, runs the probes every
`PROBE_INTERVAL` seconds; each probe runs in a worker thread under
`PROBE_DEADLINE`, and a round already in flight is never started twice. The
route reads only what the last round left, so a request -- anonymous, unguarded,
as often as anyone likes -- costs no store connection, no bundle read and no
filesystem call. A round older than `STALE_AFTER` is not trusted, and before
the first round nothing is.

The body is codes and a timestamp only: no path, no URL, no exception text.
A probe that raises is its failure code, and nothing of what it raised.
"""

from __future__ import annotations

import asyncio
import os
import platform
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from os import environ
from pathlib import Path
from time import monotonic
from typing import Literal

import psycopg
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import AwareDatetime, BaseModel, ConfigDict

from caos.api.deps import BLOB_ROOT, VENDORED_BUNDLE, _vendored_bundle
from caos.api.edge import PLATFORM_ENV
from caos.api.identity import scim_me
from caos.blobs import VOLUME_SCHEME, BlobStore
from caos.methodology.bundle import Bundle
from caos.refusals import Refusal
from caos.store import connect, verify_schema
from caos.store.lakebase import store_url
from caos.store.work import worker_states

# The route reads a cached result; the probes' round trips are the loop's.
IO_BUDGET = 0

PROBE_INTERVAL = 10.0
# A credential mint and a TLS connect across the workspace network fit in
# this; `PROBE_INTERVAL` stays above it so rounds never queue (F47).
PROBE_DEADLINE = 5.0
STALE_AFTER = 30.0
# How long a probe still in flight may hold the next round back. A probe thread
# the executor never started -- `wait_for` cancelled the job while it was still
# queued -- never runs its own accounting, so `inflight` stayed raised and
# every later round returned without probing anything until the process was
# restarted (AR-11). The count gate is therefore a *time* gate as well: past
# this, a round runs whatever `inflight` says. Twice the deadline is longer
# than any probe that is really running and well inside `STALE_AFTER`, so a
# leak costs one skipped round rather than readiness.
INFLIGHT_CEILING = PROBE_DEADLINE * 2

HealthCode = Literal[
    "OK",
    "STORE_NOT_CONFIGURED",
    "STORE_UNAVAILABLE",
    "IDENTITY_UNAVAILABLE",
    "STORE_SCHEMA_DRIFT",
    "BUNDLE_MOVED",
    "BUNDLE_INVALID",
    "BLOB_ROOT_UNAVAILABLE",
    "PROBE_TIMEOUT",
    "PROBE_STALE",
    "PROBE_NOT_RUN",
    # The worker's own codes. They never make the API `not_ready`: the API is
    # not the worker, and reporting the surface unready because a queue is
    # stalled would take the surface down with it. An operator alerts on this
    # field; a load balancer reads `status`.
    "WORKERS_ABSENT",
    "WORKERS_STALE",
    "WORKERS_BACKING_OFF",
]
type Probe = Callable[[], HealthCode]


class HealthDocument(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    status: Literal["ready", "not_ready"]
    store: HealthCode
    bundle: HealthCode
    blobs: HealthCode
    # Behind the platform, the workspace that names every caller (F43).
    identity: HealthCode
    # Reported, never folded into `status` -- see `HealthCode`.
    workers: HealthCode
    checked_at: AwareDatetime | None
    # What is running (spec section 3.1): the interpreter and the bundle build.
    python_version: str
    build_id: str | None


def probe_store() -> HealthCode:
    """Connect with a deadline, bound every statement, verify the schema.

    Nothing is committed: the connection is closed with its transaction open,
    which discards it.
    """
    try:
        url = store_url()
    except Refusal:
        return "STORE_NOT_CONFIGURED"
    try:
        conn = connect(url, connect_timeout=int(PROBE_DEADLINE))
    except psycopg.Error:
        return "STORE_UNAVAILABLE"
    try:
        conn.execute("SET LOCAL statement_timeout = '2s'")
        verify_schema(conn)
    except Refusal:
        return "STORE_SCHEMA_DRIFT"
    except psycopg.Error:
        return "STORE_UNAVAILABLE"
    finally:
        conn.close()
    return "OK"


def probe_bundle(
    root: Path = VENDORED_BUNDLE, held: Callable[[], Bundle] = _vendored_bundle
) -> HealthCode:
    """A fresh manifest snapshot must equal the one the process verifies under."""
    try:
        fresh = Bundle(root)
        process = held()
    except Refusal:
        return "BUNDLE_INVALID"
    try:
        fresh.verify_pinned()
        same = process.manifest_sha256 == fresh.manifest_sha256
    except Refusal:
        same = False
    return "OK" if same else "BUNDLE_MOVED"


def probe_blobs() -> HealthCode:
    """The blob root is configured, a directory, and usable. Nothing is written."""
    root = environ.get(BLOB_ROOT)
    if not root:
        return "BLOB_ROOT_UNAVAILABLE"
    if root.startswith(VOLUME_SCHEME):
        try:
            BlobStore.from_setting(root).probe()
        except Refusal:
            return "BLOB_ROOT_UNAVAILABLE"
        return "OK"
    if not os.path.isdir(root) or not os.access(root, os.R_OK | os.W_OK | os.X_OK):
        return "BLOB_ROOT_UNAVAILABLE"
    return "OK"


def probe_workers() -> HealthCode:
    """What the fleet last said about itself, from the store's own clock.

    Three answers a person acts on differently. `WORKERS_ABSENT`: nothing has
    ever beaten, so a queued run will simply wait. `WORKERS_STALE`: a worker
    beat and stopped -- the row names which one, and the worker is the thing to
    go and look at. `WORKERS_BACKING_OFF`: every fresh worker is failing to
    reach the store, which is the case the ledger entry names and the one that
    used to be visible in nothing but a log.

    A fresh worker in `WORKING` or `POLLING` is `OK`, including one that has
    been driving the same long run for minutes: its run's liveness is the lease
    in `run_work`, which every fenced write renews, and duplicating that
    judgement here would put two clocks on one question.
    """
    try:
        url = store_url()
    except Refusal:
        return "STORE_NOT_CONFIGURED"
    try:
        conn = connect(url, connect_timeout=int(PROBE_DEADLINE))
    except psycopg.Error:
        return "STORE_UNAVAILABLE"
    try:
        conn.execute("SET LOCAL statement_timeout = '2s'")
        states = worker_states(conn)
    except psycopg.Error:
        return "STORE_UNAVAILABLE"
    finally:
        conn.close()
    if not states:
        return "WORKERS_ABSENT"
    fresh = [state for state in states if state.fresh]
    if not fresh:
        return "WORKERS_STALE"
    if all(state.state == "BACKOFF" for state in fresh):
        return "WORKERS_BACKING_OFF"
    return "OK"


def probe_identity() -> HealthCode:
    """Behind the platform, one SCIM `Me` as the app's own principal; anywhere
    else there is nothing to ask. A process that cannot reach the workspace
    cannot name a caller, so this is folded into `status` (F43).

    Down `identity.scim_me`, the very path a request takes, with the
    credentials the SDK mints for this process. Through the SDK's own client
    it was a *different* path (EI-W1): a `DATABRICKS_HOST` the hand-rolled
    parser rejected, a SCIM path that had moved, or a token scope the
    workspace refused made every request 401 or 503 while health still
    reported `ready`, because the SDK resolved its own host and asked its own
    way. The SDK is still what holds the credential -- nothing here reads one.
    """
    if not os.environ.get(PLATFORM_ENV):
        return "OK"
    from caos.workspace import workspace_client

    try:
        minted = workspace_client().config.authenticate()
    except (OSError, ValueError):
        return "IDENTITY_UNAVAILABLE"
    authorization = minted.get("Authorization")
    if not authorization:
        return "IDENTITY_UNAVAILABLE"
    try:
        scim_me(authorization)
    except Refusal:
        return "IDENTITY_UNAVAILABLE"
    return "OK"


PROBES: Mapping[str, Probe] = {
    "store": probe_store,
    "bundle": probe_bundle,
    "blobs": probe_blobs,
    "identity": probe_identity,
    "workers": probe_workers,
}
_FAILED: Mapping[str, HealthCode] = {
    "store": "STORE_UNAVAILABLE",
    "identity": "IDENTITY_UNAVAILABLE",
    "bundle": "BUNDLE_INVALID",
    "blobs": "BLOB_ROOT_UNAVAILABLE",
    "workers": "STORE_UNAVAILABLE",
}


def _default_probes() -> dict[str, Probe]:
    return dict(PROBES)


def _now() -> datetime:
    return datetime.now(UTC)


@dataclass
class ProbeState:
    """The last round's codes, and what a test may substitute to drive it."""

    probes: Mapping[str, Probe] = field(default_factory=_default_probes)
    interval: float = PROBE_INTERVAL
    deadline: float = PROBE_DEADLINE
    clock: Callable[[], float] = monotonic
    wall: Callable[[], datetime] = _now
    store: HealthCode = "PROBE_NOT_RUN"
    bundle: HealthCode = "PROBE_NOT_RUN"
    blobs: HealthCode = "PROBE_NOT_RUN"
    identity: HealthCode = "PROBE_NOT_RUN"
    workers: HealthCode = "PROBE_NOT_RUN"
    checked_at: datetime | None = None
    checked: float | None = None
    running: bool = False
    # Probe threads still alive, an abandoned one included: no new round
    # starts over them, so a slow store cannot pile up connections (F47).
    inflight: int = 0
    # When the oldest of them was started, on `clock`, and how long that may
    # hold the next round back (AR-11). None when nothing is in flight.
    inflight_since: float | None = None
    inflight_ceiling: float = INFLIGHT_CEILING


async def _one(state: ProbeState, name: str) -> HealthCode:
    probe = state.probes[name]

    def counted() -> HealthCode:
        try:
            return probe()
        finally:
            state.inflight -= 1
            if state.inflight <= 0:
                # Clamped: a thread abandoned by an earlier round can return
                # after a later round has already counted itself out.
                state.inflight, state.inflight_since = 0, None

    state.inflight += 1
    if state.inflight_since is None:
        state.inflight_since = state.clock()
    try:
        return await asyncio.wait_for(asyncio.to_thread(counted), state.deadline)
    except TimeoutError:
        # The thread is abandoned, not awaited: it cannot be interrupted, and
        # the next round must not queue behind it; `inflight` says it lives.
        return "PROBE_TIMEOUT"
    except Exception:  # noqa: BLE001 -- a probe's fault is its code, never text
        return _FAILED[name]


def _blocked(state: ProbeState) -> bool:
    """Whether a probe still in flight holds the next round back.

    It does, until it has been in flight longer than `inflight_ceiling`. A job
    the executor never started because `wait_for` cancelled it while it was
    still queued never runs `counted`, so its count is never given back: the
    gate has to expire on its own, or one such cancellation stalls every
    future round and only a restart returns readiness (AR-11).
    """
    if not state.inflight:
        return False
    since = state.inflight_since
    return since is None or state.clock() - since < state.inflight_ceiling


async def probe_once(state: ProbeState) -> None:
    """One round of every probe, unless a round is already in flight."""
    if state.running or _blocked(state):
        return
    if state.inflight:
        # Past the ceiling with a count still raised: whatever it counts was
        # abandoned or was never started. Forgotten here, so the gate holds
        # again for this round's own probes rather than staying open for the
        # life of the process.
        state.inflight, state.inflight_since = 0, None
    state.running = True
    try:
        store, bundle, blobs, identity, workers = await asyncio.gather(
            _one(state, "store"),
            _one(state, "bundle"),
            _one(state, "blobs"),
            _one(state, "identity"),
            _one(state, "workers"),
        )
        state.store, state.bundle, state.blobs = store, bundle, blobs
        state.identity, state.workers = identity, workers
        state.checked_at, state.checked = state.wall(), state.clock()
    finally:
        state.running = False


async def probe_loop(state: ProbeState) -> None:
    """The one background task: a round, then the interval, until cancelled."""
    while True:
        await probe_once(state)
        await asyncio.sleep(state.interval)


def _document(state: ProbeState | None) -> HealthDocument:
    """What the cached round says now: stale past `STALE_AFTER`."""
    if state is None or state.checked is None:
        codes: tuple[HealthCode, ...] = ("PROBE_NOT_RUN",) * 5
        checked_at = None
    else:
        checked_at = state.checked_at
        if state.clock() - state.checked > STALE_AFTER:
            codes = ("PROBE_STALE",) * 5
        else:
            codes = (
                state.store,
                state.bundle,
                state.blobs,
                state.identity,
                state.workers,
            )
    return HealthDocument(
        # The first four only: a stalled queue does not make this API unready.
        status="ready" if codes[:4] == ("OK",) * 4 else "not_ready",
        store=codes[0],
        bundle=codes[1],
        blobs=codes[2],
        identity=codes[3],
        workers=codes[4],
        checked_at=checked_at,
        python_version=platform.python_version(),
        build_id=_held_build_id(),
    )


def _held_build_id() -> str | None:
    """The build the process verifies under, from the cached manifest snapshot.

    No I/O: the bundle is built once per process (`_vendored_bundle`), and a
    manifest that will not parse is the `bundle` probe's answer, not this one's.
    """
    try:
        return _vendored_bundle().build_id
    except Refusal:
        return None


router = APIRouter()


@router.get("/api/health", response_model=HealthDocument)
async def read_health(request: Request) -> JSONResponse:
    """200 when every probe holds and is fresh, else 503. No identity, no I/O."""
    body = _document(getattr(request.app.state, "health", None))
    return JSONResponse(
        status_code=200 if body.status == "ready" else 503,
        content=body.model_dump(mode="json"),
        headers={"cache-control": "no-store"},
    )

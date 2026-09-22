"""`GET /api/health`: readiness over store, bundle and blobs, read from a cache.

`SYSTEM_SPEC.md` §11 and the Phase 4 task 4.5 brief, slice 4.5b. One background
task, started in the app's lifespan, runs the three probes every
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
from caos.blobs import VOLUME_SCHEME, BlobStore
from caos.methodology.bundle import Bundle
from caos.refusals import Refusal
from caos.store import connect, verify_schema
from caos.store.lakebase import store_url
from caos.store.work import worker_states

# The route reads a cached result; the probes' round trips are the loop's.
IO_BUDGET = 0

PROBE_INTERVAL = 10.0
PROBE_DEADLINE = 2.0
STALE_AFTER = 30.0

HealthCode = Literal[
    "OK",
    "STORE_NOT_CONFIGURED",
    "STORE_UNAVAILABLE",
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
    # Reported, never folded into `status` -- see `HealthCode`.
    workers: HealthCode
    checked_at: AwareDatetime | None


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


PROBES: Mapping[str, Probe] = {
    "store": probe_store,
    "bundle": probe_bundle,
    "blobs": probe_blobs,
    "workers": probe_workers,
}
_FAILED: Mapping[str, HealthCode] = {
    "store": "STORE_UNAVAILABLE",
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
    workers: HealthCode = "PROBE_NOT_RUN"
    checked_at: datetime | None = None
    checked: float | None = None
    running: bool = False


async def _one(state: ProbeState, name: str) -> HealthCode:
    try:
        return await asyncio.wait_for(
            asyncio.to_thread(state.probes[name]), state.deadline
        )
    except TimeoutError:
        # The thread is abandoned, not awaited: it cannot be interrupted, and
        # the next round must not queue behind it.
        return "PROBE_TIMEOUT"
    except Exception:  # noqa: BLE001 -- a probe's fault is its code, never text
        return _FAILED[name]


async def probe_once(state: ProbeState) -> None:
    """One round of all three probes, unless a round is already in flight."""
    if state.running:
        return
    state.running = True
    try:
        store, bundle, blobs, workers = await asyncio.gather(
            _one(state, "store"),
            _one(state, "bundle"),
            _one(state, "blobs"),
            _one(state, "workers"),
        )
        state.store, state.bundle, state.blobs = store, bundle, blobs
        state.workers = workers
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
        codes: tuple[HealthCode, ...] = ("PROBE_NOT_RUN",) * 4
        checked_at = None
    else:
        checked_at = state.checked_at
        if state.clock() - state.checked > STALE_AFTER:
            codes = ("PROBE_STALE",) * 4
        else:
            codes = (state.store, state.bundle, state.blobs, state.workers)
    return HealthDocument(
        # The first three only: a stalled queue does not make this API unready.
        status="ready" if codes[:3] == ("OK",) * 3 else "not_ready",
        store=codes[0],
        bundle=codes[1],
        blobs=codes[2],
        workers=codes[3],
        checked_at=checked_at,
    )


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

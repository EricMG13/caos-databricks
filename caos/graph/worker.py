"""One PostgreSQL-backed worker: poll, claim a run, drive it, map the outcome.

Brief 4.3 D9. No broker, no LISTEN/NOTIFY, no listener: lease expiry has to be
polled anyway, and the work row is the whole queue. A claim is per run (D1), so
this process is the run's only writer until its lease is lost, and every write
it makes is fenced by the lease token (D3).

`stopping` is checked between nodes -- before a node's context check, so before
its attempt, reservation or call -- and between polls, never during a call: a
SIGTERM lets the call in flight be billed and accepted, then gives the run back
to the queue.
"""

from __future__ import annotations

import os
import secrets
import signal
import sys
import threading
import traceback
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path
from threading import Event
from uuid import UUID

import psycopg
from langgraph.checkpoint.base import BaseCheckpointSaver

from caos.blobs import BlobStore
from caos.boundary_text import BoundaryText
from caos.graph.checkpoint import checkpointer, close_checkpointer
from caos.graph.runtime import Execution, Provider, ProviderResult, run_route
from caos.methodology.bundle import Bundle
from caos.methodology.runner import ModuleProvider
from caos.models import ChatCompletions, from_environment
from caos.pricing import ModelPrice
from caos.pricing import price_from_environment as price_from_environment
from caos.provider import CompletionProvider
from caos.refusals import Refusal, RefusalCode
from caos.store import StoreConnection, apply_schema, connect, rollback_or_close
from caos.store.gates import execution_input
from caos.store.lakebase import note_connect_failure, store_url
from caos.store.outcomes import execution_reads
from caos.store.runs import cancel_run
from caos.store.work import (
    LEASE_SECONDS,
    Lease,
    WorkerState,
    beat,
    claim_run,
    release,
    stop,
)

DATABASE_URL = "CAOS_DATABASE_URL"
BLOB_ROOT = "CAOS_BLOB_ROOT"
# `model,input_per_token,output_per_token,YYYY-MM-DD`: the worker's price (§49).
MODEL_PRICE = "CAOS_MODEL_PRICE"
# `1`: the API process runs this worker as a daemon thread (D11).
IN_PROCESS = "CAOS_WORKER_IN_PROCESS"
VENDORED_BUNDLE = Path(__file__).resolve().parents[2] / "vendor" / "deploy-v"
# Only the faults that are the *store's*, not one run's. A blob fault names a
# run: releasing it would put that run back at the head of the queue (`release`
# leaves `requested_at` alone) to fail the same way every poll, with no stop
# code and no line on stderr. It is parked STOPPED with its code instead, which
# is what tells an operator to restore the blob. Replay does not need the
# release: `outcomes._NOT_AN_EXPLANATION` is what keeps a billed answer out of
# `attempt_refusals`, and `_drive` asks `replay_billed` before any new attempt,
# so a requeued run replays the body it already paid for.
STORE_FAULTS = frozenset(
    {RefusalCode.STORE_UNAVAILABLE, RefusalCode.STORE_NOT_TRANSACTIONAL}
)

ExecutionFor = Callable[[StoreConnection, UUID, Lease], Execution]


@dataclass(frozen=True, slots=True)
class WorkerConfig:
    """Who this worker is (diagnostic only) and how it paces itself."""

    worker: BoundaryText
    lease_seconds: int = LEASE_SECONDS
    poll_seconds: float = 1.0
    backoff_cap_seconds: float = 30.0


class _Stopping(Exception):
    """Raised between nodes once `stopping` is set; never during a call."""


@dataclass(frozen=True, slots=True)
class _Stoppable:
    """The run's provider, refusing to begin another node once stopping."""

    inner: Provider
    stopping: Event

    @property
    def model(self) -> str:
        return self.inner.model

    def check_context(self, route_node_id: str, module_id: str) -> int:
        if self.stopping.is_set():
            raise _Stopping
        return self.inner.check_context(route_node_id, module_id)

    def execute(
        self, route_node_id: str, module_id: str, *, attempt_id: UUID
    ) -> ProviderResult:
        return self.inner.execute(route_node_id, module_id, attempt_id=attempt_id)


def module_execution(
    completions: CompletionProvider,
    price: ModelPrice,
    bundle: Bundle,
    blobs: BlobStore,
    saver: BaseCheckpointSaver[str] | None = None,
) -> ExecutionFor:
    """Each claimed run executes its pinned route through the real module
    provider, on the worker's connection and under its lease, one node at a
    time (next.md N1), checkpointed by `saver` when the worker has one.
    """

    def execution_for(conn: StoreConnection, run_id: UUID, lease: Lease) -> Execution:
        with execution_reads(conn):
            _pin, route = execution_input(conn, run_id, bundle)
        provider = ModuleProvider(
            conn, bundle, blobs, completions, route, run_id, lease
        )
        return Execution(provider, price, bundle, lease=lease, checkpointer=saver)

    return execution_for


def work_once(
    conn: StoreConnection,
    blobs: BlobStore,
    *,
    execution_for: ExecutionFor,
    config: WorkerConfig,
    stopping: Event,
) -> UUID | None:
    """Claim at most one run and drive it until it ends or cannot go on.

    Returns the claimed run, or None when stopping or nothing is claimable. A
    store fault releases the claim (or leaves it to expire) and is raised, so
    the loop backs off.
    """
    if stopping.is_set():
        return None
    lease = claim_run(conn, worker=config.worker, lease_seconds=config.lease_seconds)
    if lease is None:
        return None
    # Said before the run is driven rather than after it: driving is the part
    # that takes minutes, and a worker that went quiet *while working* is a
    # different thing for an operator than one that went quiet while idle.
    # `claim_run` commits alone, so this beat is its own unit too.
    _beat(conn, config, "WORKING", 0)
    try:
        execution = execution_for(conn, lease.run_id, lease)
        with execution_reads(conn):
            _pin, route = execution_input(conn, lease.run_id, execution.bundle)
        run_route(
            conn,
            blobs,
            run_id=lease.run_id,
            route=route,
            # `replace`, not a fresh `Execution` listing the fields this line
            # happens to know about. It used to be the latter, and when
            # `per_node` was added the worker silently dropped it -- so the
            # concurrent pass was built, tested, documented and then never
            # reached production, because one constructor call four screens
            # away did not mention it. A field added tomorrow survives this.
            execution=replace(
                execution,
                provider=_Stoppable(execution.provider, stopping),
                lease=lease,
                # One beat per node, so a worker driving a long run reads as
                # fresh rather than stale for its whole length (F38).
                heartbeat=lambda: _beat(conn, config, "WORKING", 0),
            ),
        )
    except _Stopping:
        _settle(conn, lambda: release(conn, lease))
    except psycopg.Error:
        _settle(conn, lambda: release(conn, lease))
        raise Refusal(RefusalCode.STORE_UNAVAILABLE) from None
    except Refusal as refused:
        _refused(conn, lease, refused)
    except Exception as fault:  # noqa: BLE001 -- neither a refusal nor a store error
        # Parked, not raised: a worker that died holding the claim would find the
        # same run first after every lease expiry and never reach the rest of the
        # queue. The class and the frame it was raised in are host facts; the
        # message may quote a document and is never written.
        frames = traceback.extract_tb(fault.__traceback__)
        where = f"{frames[-1].filename}:{frames[-1].lineno}" if frames else "?"
        print(f"{type(fault).__name__} at {where}", file=sys.stderr)
        _settle(conn, lambda: stop(conn, lease, RefusalCode.INTERNAL_FAULT))
    return lease.run_id


def _refused(conn: StoreConnection, lease: Lease, refused: Refusal) -> None:
    code = refused.code
    if code in (RefusalCode.LEASE_NOT_HELD, RefusalCode.RUN_NOT_RUNNING):
        _settle(conn, lambda: False)  # another holder or a terminal run owns it
    elif code is RefusalCode.RUN_CANCEL_REQUESTED:
        _settle(conn, lambda: False)
        try:
            cancel_run(conn, lease.run_id, lease=lease)  # commits its own unit
        except Refusal as lost:
            # `cancel_run` refuses three classes and no others: a store
            # fault (`STORE_UNAVAILABLE` or `STORE_NOT_TRANSACTIONAL`),
            # `LEASE_NOT_HELD` from its `require_lease` fence, and
            # `RUN_NOT_FOUND` from `lock_run` for a run row that is not there
            # (a run already terminal is answered False, not refused). The
            # store fault heals itself -- released, or failing that left to
            # expire -- so the run is reclaimed and the cancel retried, the
            # same back-off the branch below gives that class, and parking it
            # would turn a transient fault into a stop an operator must
            # requeue by hand. A missing run has no such recovery, and raising
            # it would leave `work_once` holding the claim, with the run at
            # the head of every later poll.
            unmet = lost.code
            if unmet in STORE_FAULTS:
                _settle(conn, lambda: release(conn, lease))
                raise Refusal(unmet) from None
            if unmet is not RefusalCode.LEASE_NOT_HELD:
                print(unmet.value, file=sys.stderr)
                _settle(conn, lambda: stop(conn, lease, unmet))
    elif code in STORE_FAULTS:
        _settle(conn, lambda: release(conn, lease))
        raise Refusal(code)
    else:
        _settle(conn, lambda: stop(conn, lease, code))


def _settle(conn: StoreConnection, write: Callable[[], bool]) -> None:
    """Discard any open unit, then commit one queue write; a store that cannot
    take it leaves the lease to expire."""
    try:
        conn.rollback()
        write()
        conn.commit()
    except psycopg.Error:
        rollback_or_close(conn)


def pause_seconds(config: WorkerConfig, failures: int) -> float:
    """The next wait: the poll interval, doubled per consecutive store fault up
    to the cap, with +-20% jitter so workers do not poll in step."""
    base = config.poll_seconds * float(2 ** max(failures - 1, 0))
    # Integer thousandths first: `0.8 + 400 / 1000` is 1.2000000000000002.
    jitter = (800 + secrets.randbelow(401)) / 1000
    return min(base, config.backoff_cap_seconds) * jitter


def _beat(
    conn: StoreConnection, config: WorkerConfig, state: WorkerState, faults: int
) -> None:
    """Record this worker's state, and never let saying so stop it working.

    A heartbeat is an observation for a person, not a fence: nothing reads it
    to decide whether work may proceed. So a store that will not take the beat
    must not take the worker down with it -- the loop's own fault handling is
    what answers a store that is failing, and it does that by trying to claim a
    run, which is the thing that actually matters.
    """
    try:
        beat(conn, worker_id=config.worker.value, state=state, faults=faults)
        conn.commit()
    except (psycopg.Error, Refusal):
        conn.rollback()


def _store_fault(fault: Refusal | psycopg.OperationalError) -> None:
    """A fault the loop rides out, or re-raised when it is not the store's.
    A refused credential drops the cached one, so the next connect mints."""
    if isinstance(fault, Refusal):
        if fault.code not in STORE_FAULTS:
            raise fault
        return
    note_connect_failure(fault)


def run_worker(
    config: WorkerConfig,
    *,
    execution_for: ExecutionFor,
    stopping: Event,
    conn_factory: Callable[[], StoreConnection],
    blobs: BlobStore,
) -> int:
    """Poll until `stopping`; returns the process exit code."""
    conn: StoreConnection | None = None
    failures = 0
    try:
        while not stopping.is_set():
            claimed: UUID | None = None
            try:
                if conn is None or conn.closed:
                    conn = conn_factory()
                _beat(conn, config, "POLLING", failures)
                claimed = work_once(
                    conn,
                    blobs,
                    execution_for=execution_for,
                    config=config,
                    stopping=stopping,
                )
                failures = 0
            except (Refusal, psycopg.OperationalError) as fault:
                _store_fault(fault)
                failures += 1
                # Said here rather than at the next poll, and before the
                # connection is dropped. A worker looping claim-fault-claim
                # would otherwise read `WORKING` -- its last word before the
                # fault -- for as long as it kept faulting, which is the exact
                # signal this beat exists to carry. A beat that cannot be
                # written on a connection that has just failed is no loss: a
                # store that is down cannot record that it is down, and the
                # staleness of the last beat says it instead.
                if conn is not None:
                    _beat(conn, config, "BACKOFF", failures)
                _closed(conn)
                conn = None
            if claimed is None:
                stopping.wait(pause_seconds(config, failures))
    finally:
        _closed(conn)
    return 0


def _closed(conn: StoreConnection | None) -> None:
    if conn is not None:
        conn.close()


def _store_configuration() -> tuple[str, str]:
    root = os.environ.get(BLOB_ROOT)
    if not root:
        raise Refusal(RefusalCode.STORE_NOT_CONFIGURED)
    return store_url(), root


def install_stop_handler(stopping: Event) -> None:
    """SIGTERM only sets `stopping`; the loop decides when that is safe."""
    signal.signal(signal.SIGTERM, lambda _signum, _frame: stopping.set())


@dataclass(frozen=True, slots=True)
class Configured:
    """Everything a worker needs, read from the environment and verified."""

    completions: ChatCompletions
    url: str
    root: str
    bundle: Bundle
    saver: BaseCheckpointSaver[str]


def _configured() -> Configured:
    """Configure from the environment, or refuse having made no call."""
    completions = from_environment()
    url, root = _store_configuration()
    bundle = Bundle(VENDORED_BUNDLE)
    bundle.verify_manifest()
    bundle.verify_pinned()
    with connect(url) as conn:
        apply_schema(conn)
    return Configured(completions, url, root, bundle, checkpointer())


def _report(refused: Refusal, unset: str) -> None:
    """The typed code and, where a variable nobody set is the reason, its name
    beside it. A name is a host fact; a value is never printed."""
    named = f" {unset} unset" if unset else ""
    print(f"{refused.code.value}{named}", file=sys.stderr)


def _unset_price() -> str:
    """A variable nobody set is an unset variable, not a misconfigured one."""
    return "" if os.environ.get(MODEL_PRICE, "") else MODEL_PRICE


def _worker(configured: Configured, stopping: Event) -> int:
    blobs = BlobStore.from_setting(configured.root)
    try:
        return _drive(configured, blobs, stopping)
    finally:
        close_checkpointer(configured.saver)


def _drive(configured: Configured, blobs: BlobStore, stopping: Event) -> int:
    return run_worker(
        WorkerConfig(BoundaryText.of(f"worker-{os.getpid()}")),
        execution_for=module_execution(
            configured.completions,
            configured.completions.price,
            configured.bundle,
            blobs,
            configured.saver,
        ),
        stopping=stopping,
        # Minted at connect time, as the API and the checkpoint pool do (F30,
        # F37): a URL frozen at boot dies with its credential, and the loop's
        # reconnect would then fail forever without ever re-minting.
        conn_factory=lambda: connect(store_url()),
        blobs=blobs,
    )


def main() -> int:
    """Configure from the environment, or exit 2 having made no call, printing
    the typed code -- and, where a variable nobody set is the reason, that
    variable's name beside it. A name is a host fact; a value is never printed."""
    stopping = Event()
    unset = _unset_price()
    try:
        configured = _configured()
    except Refusal as refused:
        _report(refused, unset)
        return 2
    except psycopg.Error:
        print(RefusalCode.STORE_UNAVAILABLE.value, file=sys.stderr)
        return 2
    install_stop_handler(stopping)
    return _worker(configured, stopping)


def start_in_process(stopping: Event) -> threading.Thread | None:
    """The worker as a daemon thread beside the API (D11), when
    `CAOS_WORKER_IN_PROCESS=1`; `None` -- and the reason on stderr -- when the
    environment does not configure one. The API serves either way: a queued run
    waits, and `/api/health` reports `WORKERS_ABSENT`."""
    if os.environ.get(IN_PROCESS) != "1":
        return None
    unset = _unset_price()
    try:
        configured = _configured()
    except Refusal as refused:
        _report(refused, unset)
        return None
    except psycopg.Error:
        print(RefusalCode.STORE_UNAVAILABLE.value, file=sys.stderr)
        return None
    thread = threading.Thread(
        target=_worker, args=(configured, stopping), name="caos-worker", daemon=True
    )
    thread.start()
    return thread


if __name__ == "__main__":
    sys.exit(main())

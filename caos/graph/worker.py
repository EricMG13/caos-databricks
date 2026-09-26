"""One PostgreSQL-backed worker: poll, claim a run, drive it, map the outcome.

Brief 4.3 D9. No broker, no LISTEN/NOTIFY, no listener: lease expiry has to be
polled anyway, and the work row is the whole queue. A claim is per run (D1), so
this process is the run's only writer until its lease is lost, and every write
it makes is fenced by the lease token (D3).

`stopping` is checked between nodes -- before a node's context check, so before
its attempt, reservation or call -- between polls, and before a rate-limited
call is sent again (ST-7), never during a call. A call in flight when SIGTERM
arrives is billed and accepted only if it answers within the drain's join
(`caos.serve.LIMIT_JOIN_SECONDS`); past that it is abandoned with its
reservation held, and the run is reclaimed once its lease expires (ST-15).
"""

from __future__ import annotations

import os
import secrets
import signal
import sys
import threading
import time
import traceback
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass, replace
from pathlib import Path
from threading import Event
from uuid import UUID

import psycopg
from langgraph.checkpoint.base import BaseCheckpointSaver

from caos.blobs import BlobStore
from caos.boundary_text import BoundaryText
from caos.graph.checkpoint import checkpointer, close_checkpointer
from caos.graph.route import ResolvedRoute, route_digest
from caos.graph.runtime import Execution, Provider, ProviderResult, run_route
from caos.methodology.bundle import Bundle
from caos.methodology.runner import ModuleProvider
from caos.models import ChatCompletions, from_environment
from caos.pricing import ModelPrice
from caos.pricing import price_from_environment as price_from_environment
from caos.provider import CompletionProvider, resend_checked
from caos.refusals import Refusal, RefusalCode
from caos.store import (
    RunStatus,
    StoreConnection,
    apply_schema,
    connect,
    rollback_or_close,
)
from caos.store.budget import configured_ceiling
from caos.store.gates import execution_input
from caos.store.lakebase import note_connect_failure, store_url
from caos.store.outcomes import execution_reads
from caos.store.runs import cancel_run
from caos.store.work import (
    LEASE_SECONDS,
    Lease,
    WorkerState,
    beat,
    checkpoint_thread,
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
# What a refused pass gives its claim back for and backs off on, rather than
# parking the run: the store's own faults, and a node whose last attempt is
# not settled yet (`ATTEMPT_UNSETTLED`) -- another worker may still bill its
# call, or its bill landed as this pass started and the next pass replays it.
# Waiting is what clears each; a park would ask an operator to requeue a run
# nothing is wrong with.
RELEASED = STORE_FAULTS | {RefusalCode.ATTEMPT_UNSETTLED}

ExecutionFor = Callable[[StoreConnection, UUID, Lease], Execution]


# The idle heartbeat cadence (DL-10) and the most the backoff ever doubles.
BEAT_SECONDS = 10.0
MAX_DOUBLINGS = 30
# CF-041: well under LEASE_SECONDS, so a single wedged statement -- lock
# contention, a stuck autovacuum -- cannot hold the worker's own connection
# past the point its lease has already been reclaimed and a second worker is
# free to claim the same run; every query this loop makes is a handful of
# short reads and writes, never a model call, which is not sent over this
# connection at all.
STATEMENT_TIMEOUT_MS = 30_000


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

    @property
    def price(self) -> ModelPrice | None:
        """The price the inner provider states it bills at (`pricing.bills_at`),
        passed on: a wrapper that states none has the run refused (N15)."""
        stated = getattr(self.inner, "price", None)
        return stated if isinstance(stated, ModelPrice) else None

    def check_context(self, route_node_id: str, module_id: str) -> int:
        if self.stopping.is_set():
            raise _Stopping
        return self.inner.check_context(route_node_id, module_id)

    def execute(
        self, route_node_id: str, module_id: str, *, attempt_id: UUID
    ) -> ProviderResult:
        # A rate-limited call is not sent again once stopping (ST-7).
        with resend_checked(self._going_on):
            return self.inner.execute(route_node_id, module_id, attempt_id=attempt_id)

    def _going_on(self) -> None:
        if self.stopping.is_set():
            raise _Stopping


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
    execution: Execution | None = None
    route: ResolvedRoute | None = None
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
        _released(conn, execution, lease, route)
    except psycopg.Error:
        _released(conn, execution, lease, route)
        raise Refusal(RefusalCode.STORE_UNAVAILABLE) from None
    except Refusal as refused:
        _forget(
            conn, execution, lease.run_id, route, mine=_refused(conn, lease, refused)
        )
    except Exception as fault:  # noqa: BLE001 -- neither a refusal nor a store error
        # Parked, not raised: a worker that died holding the claim would find the
        # same run first after every lease expiry and never reach the rest of the
        # queue. The class and the frame it was raised in are host facts; the
        # message may quote a document and is never written.
        frames = traceback.extract_tb(fault.__traceback__)
        where = f"{frames[-1].filename}:{frames[-1].lineno}" if frames else "?"
        print(f"{type(fault).__name__} at {where}", file=sys.stderr)
        mine = _settle(conn, lambda: stop(conn, lease, RefusalCode.INTERNAL_FAULT))
        _forget(conn, execution, lease.run_id, route, mine=mine)
    return lease.run_id


def _released(
    conn: StoreConnection,
    execution: Execution | None,
    lease: Lease,
    route: ResolvedRoute | None,
) -> None:
    """Give the claim back after a stop or a store fault, and forget a thread
    nobody will resume (N1).

    Released, the run is RUNNING and its thread is the next holder's to resume
    (D6), so `_forget` keeps it on its fresh read. Not released, the run may
    have ended out from under a stale lease -- F218's residual race -- after
    this worker wrote one more checkpoint, and that straggler is forgotten
    here as the refused branch forgets it."""
    _settle(conn, lambda: release(conn, lease))
    _forget(conn, execution, lease.run_id, route, mine=False)


def _forget(
    conn: StoreConnection,
    execution: Execution | None,
    run_id: UUID,
    route: ResolvedRoute | None,
    *,
    mine: bool,
) -> None:
    """Drop the checkpoint thread of a run this worker just parked or ended
    (DL-8): the thread holds position only (D6), a requeued run re-derives
    its frontier from the ledger, and a thread nobody will resume is rows
    nothing reads. Best effort: the run's status is already committed.

    `mine` is whether this worker's own write moved the run (ST-5): true, the
    thread is unconditionally this worker's to forget. False, this worker's
    own write lost -- another holder's claim, still driving the same thread
    key, or the run ended out from under it while its lease was already
    stale (F218's residual race: a cancel that finds an abandoned claim ends
    the run and forgets the thread in its own unit, but the stale holder can
    still write one more checkpoint after that commits). The two read alike
    here, so a fresh read of the run's own status tells them apart: RUNNING
    is a live holder's, still using the thread; anything else is nobody's,
    including the run this stale write just found already ended.

    `route` names the same pinned route `run_route` bound the thread to
    (CF-037): a pass that never resolved one -- the claim's own read refused
    before `run_route` was ever called -- opened no thread, so there is
    nothing here to forget.
    """
    if execution is None or execution.checkpointer is None or route is None:
        return
    if not mine and not _run_is_terminal(conn, run_id):
        return
    thread = checkpoint_thread(run_id, route_digest(route))
    with suppress(psycopg.Error, OSError, Refusal):
        execution.checkpointer.delete_thread(thread)


def _run_is_terminal(conn: StoreConnection, run_id: UUID) -> bool:
    """Whether the run's own status now says anything but RUNNING -- read
    fresh, never assumed from a refusal's code alone (F218's residual race)."""
    with suppress(psycopg.Error):
        found = conn.execute(
            "SELECT status FROM runs WHERE run_id = %s", (run_id,)
        ).fetchall()
        return bool(found) and found[0][0] != RunStatus.RUNNING.value
    return False


def _refused(conn: StoreConnection, lease: Lease, refused: Refusal) -> bool:
    """Settle the queue for a refused run; True when this worker's own write
    parked or ended it (ST-5), never on the word of the refusal alone."""
    code = refused.code
    if code in (RefusalCode.LEASE_NOT_HELD, RefusalCode.RUN_NOT_RUNNING):
        _settle(conn, lambda: False)  # another holder or a terminal run owns it
        return False
    if code is RefusalCode.RUN_CANCEL_REQUESTED:
        _settle(conn, lambda: False)
        try:
            return cancel_run(conn, lease.run_id, lease=lease)  # its own unit
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
            if unmet is RefusalCode.LEASE_NOT_HELD:
                return False
            print(unmet.value, file=sys.stderr)
            return _settle(conn, lambda: stop(conn, lease, unmet))
    if code in RELEASED:
        # An unsettled attempt is this run's own wait, so it goes behind the
        # queue: at its old place it was the head of every claim, each worker
        # took it and was refused, and no other actor's run was claimed.
        behind = code is RefusalCode.ATTEMPT_UNSETTLED
        _settle(conn, lambda: release(conn, lease, behind=behind))
        raise Refusal(code)
    # CF-044: the code alone, the same shape the sibling branch above already
    # prints for the same reason -- a run parked with nothing on stderr is a
    # worker that went quiet for a reason nobody watching the process learns.
    print(code.value, file=sys.stderr)
    return _settle(conn, lambda: stop(conn, lease, code))


def _settle(conn: StoreConnection, write: Callable[[], bool]) -> bool:
    """Discard any open unit, then commit one queue write; whether it moved
    the row (ST-5). A store that cannot take it leaves the lease to expire."""
    try:
        conn.rollback()
        moved = write()
        conn.commit()
    except psycopg.Error:
        rollback_or_close(conn)
        return False
    except Refusal:
        # The write's own refusal (a run row gone from under `lock_run`): the
        # unit is ended and nothing moved; the worker must not die of it.
        rollback_or_close(conn)
        return False
    return moved


def pause_seconds(config: WorkerConfig, failures: int) -> float:
    """The next wait: the poll interval, doubled per consecutive store fault up
    to the cap, with +-20% jitter so workers do not poll in step."""
    # The exponent is bounded before it is raised (AR-03): an outage long
    # enough to count a thousand faults would otherwise overflow the float
    # and take the worker down at exactly the moment it should keep waiting.
    base = config.poll_seconds * float(2 ** min(max(failures - 1, 0), MAX_DOUBLINGS))
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
        # A session the server ended (a Lakebase failover, AR-01) fails the
        # rollback too; that failure closes the connection and stops here.
        rollback_or_close(conn)


def _store_fault(fault: Refusal | psycopg.OperationalError) -> None:
    """A fault the loop rides out (`RELEASED`), or re-raised when it is not one.
    A refused credential drops the cached one, so the next connect mints."""
    if isinstance(fault, Refusal):
        if fault.code not in RELEASED:
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
    beaten = 0.0  # when POLLING was last said; an idle worker beats every
    # `BEAT_SECONDS`, not every poll, so Lakebase can go idle (DL-10)
    try:
        while not stopping.is_set():
            claimed: UUID | None = None
            try:
                if conn is None or conn.closed:
                    conn = _connected(conn_factory)
                    beaten = 0.0
                now = time.monotonic()
                if now - beaten >= BEAT_SECONDS:
                    _beat(conn, config, "POLLING", failures)
                    beaten = now
                claimed = work_once(
                    conn,
                    blobs,
                    execution_for=execution_for,
                    config=config,
                    stopping=stopping,
                )
                failures = 0
                if claimed is not None:
                    beaten = 0.0  # WORKING was said; say POLLING again at once
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
        _beat_stopped(conn, config, failures)
        _closed(conn)
    return 0


def _beat_stopped(
    conn: StoreConnection | None, config: WorkerConfig, failures: int
) -> None:
    """N37: a beat of STOPPED, distinct from BACKOFF or a merely stale
    POLLING/WORKING, so a fleet read tells a worker that ended here on
    purpose from one whose last word just went quiet. Best effort, on
    whatever connection the loop still holds when it stops; `_beat` never
    raises. Its own function so `run_worker`'s `finally` costs no added
    branch (C901)."""
    if conn is not None and not conn.closed:
        _beat(conn, config, "STOPPED", failures)


def _closed(conn: StoreConnection | None) -> None:
    if conn is not None:
        conn.close()


def _connected(conn_factory: Callable[[], StoreConnection]) -> StoreConnection:
    """One connection, or a store fault: the SDK behind `store_url` reports an
    unreachable workspace or a refused token as `ValueError` (CR-1), and a
    worker that let that escape died for good while health stayed ready."""
    try:
        return conn_factory()
    except (OSError, ValueError) as fault:
        print(type(fault).__name__, file=sys.stderr)
        raise Refusal(RefusalCode.STORE_UNAVAILABLE) from None


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
    # CF-048: checked first, before the provider or the store, the same way a
    # malformed CAOS_MODEL_PRICE refuses below -- so a CAOS_RUN_CEILING nobody
    # could price refuses the worker at boot instead of sitting invisible
    # until the first run a caller starts under it.
    configured_ceiling()
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
        conn_factory=lambda: connect(
            store_url(), statement_timeout_ms=STATEMENT_TIMEOUT_MS
        ),
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
    `CAOS_WORKER_IN_PROCESS=1`; `None` when the environment does not ask for
    one. The API serves either way: a queued run waits, and `/api/health`
    reports `WORKERS_ABSENT` until the worker beats.

    The thread configures itself (ST-4, MAX-20): nothing here touches the
    store, so the port binds without waiting on the checkpoint set-up, and a
    store that cannot answer yet is asked again under the loop's back-off
    rather than leaving the process with no worker for its whole life. A
    configuration the environment refuses is printed with its code and the
    thread ends: asking again would not change the answer.
    """
    if os.environ.get(IN_PROCESS) != "1":
        return None
    thread = threading.Thread(
        target=_boot, args=(stopping,), name="caos-worker", daemon=True
    )
    thread.start()
    return thread


def _boot(stopping: Event) -> int:
    """Configure, retrying a store fault with back-off, then work until stopped."""
    config = WorkerConfig(BoundaryText.of(f"worker-{os.getpid()}"))
    failures = 0
    while not stopping.is_set():
        configured = _configured_or_code(_unset_price())
        if isinstance(configured, Configured):
            return _worker(configured, stopping)
        if configured is RefusalCode.STORE_UNAVAILABLE:
            failures += 1
            stopping.wait(pause_seconds(config, failures))
            continue
        return 2
    return 0


def _configured_or_code(unset: str) -> Configured | RefusalCode:
    """The configured worker, or the code that refused it, printed once."""
    try:
        return _configured()
    except Refusal as refused:
        _report(refused, unset)
        return (
            RefusalCode.STORE_UNAVAILABLE
            if refused.code in STORE_FAULTS
            else refused.code
        )
    except psycopg.Error:
        print(RefusalCode.STORE_UNAVAILABLE.value, file=sys.stderr)
        return RefusalCode.STORE_UNAVAILABLE


if __name__ == "__main__":
    sys.exit(main())

"""The PostgreSQL worker loop (brief 4.3 D9): claim, drive, map, stop cleanly.

Every run here is the canonical LITE route through the real `ModuleProvider`,
answered by a deterministic completions double; no provider is ever live.
"""

from __future__ import annotations

import ast
import signal
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from threading import Event
from typing import cast
from uuid import UUID

import psycopg
import pytest
from canonical_fixtures import UNANCHORED, CanonicalCompletions
from conftest import priced
from lite_route_fixtures import RealisticLiteCompletions
from test_runtime import ESTIMATE, _approved_run, _Run, blobs, bundle, route

from caos import models
from caos import provider as provider_module
from caos.blobs import BlobStore
from caos.boundary_text import BoundaryText
from caos.graph import worker
from caos.graph.route import ResolvedRoute
from caos.graph.runtime import Execution
from caos.graph.worker import (
    WorkerConfig,
    install_stop_handler,
    module_execution,
    run_worker,
    work_once,
)
from caos.methodology.bundle import Bundle
from caos.provider import CompletionProvider
from caos.refusals import Refusal, RefusalCode
from caos.store import RunStatus, StoreConnection
from caos.store.runs import run_status
from caos.store.work import LEASE_SECONDS, Lease, enqueue_run, worker_states

__all__ = ["blobs", "bundle", "route"]

REPO = Path(__file__).resolve().parents[1]
CONFIG = WorkerConfig(BoundaryText.of("worker-test"), poll_seconds=0.5)


def queued_run(
    case: tuple[StoreConnection, UUID],
    route: ResolvedRoute,
    bundle: Bundle,
    blobs: BlobStore,
) -> _Run:
    """An approved LITE run, enqueued and committed."""
    conn, case_id = case
    run = _approved_run(conn, case_id, route, bundle, blobs)
    enqueue_run(conn, run.run_id)
    conn.commit()
    return run


def work_row(conn: StoreConnection, run_id: UUID) -> tuple[object, ...]:
    row = conn.execute(
        "SELECT state, stop_code, worker, lease_expires_at IS NULL"
        " FROM run_work WHERE run_id = %s",
        (run_id,),
    ).fetchone()
    conn.rollback()
    assert row is not None
    return tuple(row)


def count(conn: StoreConnection, table: str, run_id: UUID) -> int:
    row = conn.execute(
        "SELECT count(*) FROM " + table + " WHERE run_id = %s", (run_id,)
    ).fetchone()
    conn.rollback()
    assert row is not None
    return int(row[0])


def drive(
    run: _Run, completions: CompletionProvider, *, stopping: Event | None = None
) -> UUID | None:
    return work_once(
        run.conn,
        run.blobs,
        execution_for=module_execution(
            completions, priced(ESTIMATE), run.bundle, run.blobs
        ),
        config=CONFIG,
        stopping=stopping or Event(),
    )


def test_worker_drives_an_enqueued_lite_run_to_complete_with_a_deterministic_provider(
    case: tuple[StoreConnection, UUID],
    route: ResolvedRoute,
    bundle: Bundle,
    blobs: BlobStore,
) -> None:
    run = queued_run(case, route, bundle, blobs)
    completions = RealisticLiteCompletions(run.source_id)

    assert drive(run, completions) == run.run_id

    assert run_status(run.conn, run.run_id) is RunStatus.COMPLETE
    assert work_row(run.conn, run.run_id) == ("DONE", None, None, True)
    assert count(run.conn, "artifacts", run.run_id) == len(route.nodes)
    assert len(completions.prompts) == len(route.nodes)
    assert drive(run, completions) is None, "nothing left to claim"


def test_worker_stops_a_refused_run_with_its_code_and_releases_the_lease(
    case: tuple[StoreConnection, UUID],
    route: ResolvedRoute,
    bundle: Bundle,
    blobs: BlobStore,
) -> None:
    run = queued_run(case, route, bundle, blobs)
    completions = CanonicalCompletions(run.source_id, quotes=(UNANCHORED,))

    assert drive(run, completions) == run.run_id

    [(code,)] = run.conn.execute(
        "SELECT r.code FROM attempt_refusals r JOIN run_attempts a USING (attempt_id)"
        " WHERE a.run_id = %s",
        (run.run_id,),
    ).fetchall()
    assert work_row(run.conn, run.run_id) == ("STOPPED", code, None, True)
    assert run_status(run.conn, run.run_id) is RunStatus.RUNNING
    run.conn.rollback()
    assert drive(run, completions) is None, "a stopped run waits for a retry"
    assert len(completions.prompts) == 1


def test_sigterm_finishes_the_unit_and_requeues(
    case: tuple[StoreConnection, UUID],
    route: ResolvedRoute,
    bundle: Bundle,
    blobs: BlobStore,
) -> None:
    """The signal only sets `stopping`; the call in flight is billed and
    accepted, and the next node is never started."""
    run = queued_run(case, route, bundle, blobs)
    stopping = Event()
    previous = signal.getsignal(signal.SIGTERM)
    install_stop_handler(stopping)
    try:
        completions = CanonicalCompletions(
            run.source_id, during=lambda: signal.raise_signal(signal.SIGTERM)
        )
        assert drive(run, completions, stopping=stopping) == run.run_id
    finally:
        signal.signal(signal.SIGTERM, previous)

    assert stopping.is_set()
    assert len(completions.prompts) == 1
    assert count(run.conn, "artifacts", run.run_id) == 1
    assert count(run.conn, "run_attempts", run.run_id) == 1
    assert work_row(run.conn, run.run_id) == ("QUEUED", None, None, True)
    assert run_status(run.conn, run.run_id) is RunStatus.RUNNING
    run.conn.rollback()
    assert drive(run, completions, stopping=stopping) is None, "stopping claims nothing"


@dataclass
class _Clock(Event):
    """A `stopping` event that records each pause and stops after `limit`."""

    limit: int = 4
    pauses: list[float] = field(default_factory=list)

    def __post_init__(self) -> None:
        super().__init__()

    def wait(self, timeout: float | None = None) -> bool:
        assert timeout is not None
        self.pauses.append(timeout)
        if len(self.pauses) >= self.limit:
            self.set()
        return self.is_set()


@pytest.mark.parametrize(
    "code",
    [
        RefusalCode.BLOB_ADDRESS_INVALID,
        RefusalCode.BLOB_DIGEST_MISMATCH,
        RefusalCode.BLOB_NOT_FOUND,
    ],
)
def test_a_blob_fault_parks_the_run_with_its_code(
    case: tuple[StoreConnection, UUID],
    route: ResolvedRoute,
    bundle: Bundle,
    blobs: BlobStore,
    code: RefusalCode,
) -> None:
    """A blob fault names one run, so it parks rather than going back in the queue.

    `release` leaves `requested_at` alone and `claim_run` orders by it, so a
    released run is re-claimed first every poll. A lost or tampered original
    does not heal on its own, so releasing it would spin the worker on that run
    forever with no stop code, no event and nothing on stderr. STOPPED with the
    code is the signal to restore the blob; the operator requeues, and
    `replay_billed` uses the body already paid for.
    """
    run = queued_run(case, route, bundle, blobs)

    def faulty(conn: StoreConnection, run_id: UUID, lease: object) -> object:
        raise Refusal(code)

    assert (
        work_once(
            run.conn,
            run.blobs,
            execution_for=faulty,  # type: ignore[arg-type]
            config=CONFIG,
            stopping=Event(),
        )
        == run.run_id
    )

    assert work_row(run.conn, run.run_id) == ("STOPPED", code.value, None, True)


@pytest.mark.parametrize(
    "code",
    [RefusalCode.STORE_UNAVAILABLE, RefusalCode.STORE_NOT_TRANSACTIONAL],
)
def test_store_fault_backs_off_without_holding_a_claim(  # noqa: PLR0913 -- parametrized store faults
    case: tuple[StoreConnection, UUID],
    route: ResolvedRoute,
    bundle: Bundle,
    blobs: BlobStore,
    empty_database: str,
    code: RefusalCode,
) -> None:
    run = queued_run(case, route, bundle, blobs)
    config = WorkerConfig(
        BoundaryText.of("worker-test"), poll_seconds=1.0, backoff_cap_seconds=3.0
    )
    built: list[UUID] = []

    def faulty(conn: StoreConnection, run_id: UUID, lease: object) -> object:
        built.append(run_id)
        raise Refusal(code)

    connects = iter([False, True, True, True, True])

    def conn_factory() -> StoreConnection:
        if not next(connects):
            raise psycopg.OperationalError("down")
        return psycopg.connect(empty_database, autocommit=False)

    clock = _Clock(limit=4)
    assert (
        run_worker(
            config,
            execution_for=faulty,  # type: ignore[arg-type]
            stopping=clock,
            conn_factory=conn_factory,
            blobs=blobs,
        )
        == 0
    )

    assert built == [run.run_id] * 3, "each claim was released and taken again"
    assert work_row(run.conn, run.run_id) == ("QUEUED", None, None, True)
    assert worker.pause_seconds(config, 9) <= 3.0 * 1.2, "capped"
    base = [1.0, 2.0, 3.0, 3.0]
    assert len(clock.pauses) == len(base)
    for pause, expected in zip(clock.pauses, base, strict=True):
        assert expected * 0.8 <= pause <= expected * 1.2


def test_main_refuses_without_provider_and_price(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def never(*_args: object, **_kwargs: object) -> object:
        pytest.fail("no store, bundle or call before configuration")

    monkeypatch.setattr(worker, "connect", never)
    monkeypatch.setattr(worker, "run_worker", never)
    monkeypatch.setattr(models, "chat_model", never)
    for name in ("CAOS_MODEL_ENDPOINT", "CAOS_MODEL_PRICE"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("CAOS_DATABASE_URL", "postgresql://unused.invalid/none")
    monkeypatch.setenv("CAOS_BLOB_ROOT", "/nonexistent")

    # The endpoint has a default, so the one thing nobody set is the price, and
    # its name is printed beside the code (a host fact; the value never is).
    assert worker.main() == 2
    assert capsys.readouterr().err == "PROVIDER_NOT_CONFIGURED CAOS_MODEL_PRICE unset\n"

    monkeypatch.setenv("CAOS_MODEL_ENDPOINT", "a-model/for-the-test")
    for price in ("a-model/for-the-test,0,1", "other/model,0,0.1,2026-09-13"):
        monkeypatch.setenv("CAOS_MODEL_PRICE", price)
        assert worker.main() == 2
        captured = capsys.readouterr()
        assert captured.err == "PROVIDER_NOT_CONFIGURED\n"
        assert price.split(",")[1] not in captured.out


def test_an_unset_price_says_unset_not_misconfigured(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A price that was never set names its variable; a malformed one does not,
    because the name is a host fact and the value is not printable."""

    def never(*_args: object, **_kwargs: object) -> object:
        pytest.fail("no store, bundle or call before configuration")

    monkeypatch.setattr(worker, "connect", never)
    monkeypatch.setattr(worker, "run_worker", never)
    monkeypatch.setenv("CAOS_MODEL_ENDPOINT", "a-model/for-the-test")
    monkeypatch.delenv("CAOS_MODEL_PRICE", raising=False)

    assert worker.main() == 2
    printed = capsys.readouterr().err.strip()
    assert printed == "PROVIDER_NOT_CONFIGURED CAOS_MODEL_PRICE unset"

    # Set-but-empty reads as unset, here and in the doctor and the store
    # configuration. The case the earlier test carried before this one replaced
    # it: without this, only the deleted-variable path is covered.
    monkeypatch.setenv("CAOS_MODEL_PRICE", "")

    assert worker.main() == 2
    assert capsys.readouterr().err.strip() == (
        "PROVIDER_NOT_CONFIGURED CAOS_MODEL_PRICE unset"
    )

    # A malformed price is misconfiguration, not absence: the code alone, with
    # no name and nothing of the value.
    monkeypatch.setenv("CAOS_MODEL_PRICE", "a-model/for-the-test,not-a-number")

    assert worker.main() == 2
    assert capsys.readouterr().err.strip() == "PROVIDER_NOT_CONFIGURED"


def test_price_from_environment_reads_one_dated_price() -> None:
    price = worker.price_from_environment("m/x", "m/x,0.000001,0.000004,2026-09-13")
    assert (str(price.input_per_token), str(price.as_of)) == ("0.000001", "2026-09-13")
    with pytest.raises(Refusal, match=r"^MONEY_INVALID$"):
        worker.price_from_environment("m/x", "m/x,NaN,0.1,2026-09-13")


def test_the_lease_outlives_the_provider_timeout() -> None:
    """D5: a lease renewed before a call outlives two socket timeouts."""
    assert LEASE_SECONDS > 2 * provider_module.TIMEOUT_SECONDS
    assert WorkerConfig(BoundaryText.of("w")).lease_seconds == LEASE_SECONDS


FORBIDDEN_MODULES = frozenset(
    {"caos.provider", "caos.models", "caos.methodology.runner", "caos.graph.worker"}
)
FORBIDDEN_NAMES = frozenset(
    {
        "run_route",
        "Execution",
        "ModuleProvider",
        "ChatCompletions",
        "chat_model",
        "from_environment",
        "execute_handoff",
        "work_once",
        "run_worker",
    }
)


def _reaches(tree: ast.AST) -> set[str]:
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found |= {a.name for a in node.names if a.name in FORBIDDEN_MODULES}
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if module in FORBIDDEN_MODULES:
                found.add(module)
            found |= {
                f"{module}.{a.name}"
                for a in node.names
                if a.name in FORBIDDEN_NAMES
                or f"{module}.{a.name}" in FORBIDDEN_MODULES
            }
        elif isinstance(node, ast.Attribute) and node.attr in FORBIDDEN_NAMES:
            found.add(node.attr)
    return found


def test_no_api_module_reaches_the_runtime_or_a_provider_transport() -> None:
    """D4: a browser disconnect cannot cancel a paid call because the API holds
    nothing that makes one. The API shares `caos.graph.runtime` for
    `accepted_artifacts`, so the check is on what each module names, not on the
    transitive import closure."""
    modules = sorted((REPO / "caos" / "api").rglob("*.py"))
    assert len(modules) > 5, "a scan that read nothing is a failure"
    reached = {
        str(path.relative_to(REPO)): hits
        for path in modules
        if (hits := _reaches(ast.parse(path.read_text(encoding="utf-8"))))
    }
    assert reached == {}
    assert _reaches(ast.parse("from caos.graph.runtime import run_route")) == {
        "caos.graph.runtime.run_route"
    }


def test_an_unexpected_fault_parks_the_run_and_the_worker_goes_on(
    case: tuple[StoreConnection, UUID],
    route: ResolvedRoute,
    bundle: Bundle,
    blobs: BlobStore,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A fault that is neither a refusal nor a store error must not kill the
    worker with the claim still held: the run would be reclaimed first after
    every lease expiry and block the queue. It is parked `INTERNAL_FAULT`
    (retry requeues it), the fault's class alone is written, and `work_once`
    returns so the loop polls on."""
    run = queued_run(case, route, bundle, blobs)

    def fault() -> None:
        raise RuntimeError("an unexpected fault with text that must not be shown")  # noqa: TRY003 -- the text is the point

    completions = CanonicalCompletions(run.source_id, during=fault)

    assert drive(run, completions) == run.run_id

    assert work_row(run.conn, run.run_id) == ("STOPPED", "INTERNAL_FAULT", None, True)
    assert run_status(run.conn, run.run_id) is RunStatus.RUNNING
    run.conn.rollback()
    written = capsys.readouterr().err
    assert "RuntimeError" in written and "must not be shown" not in written


def test_the_widest_jitter_stays_within_twenty_percent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The bounds are exact at both ends: the float sum once overshot +20%."""
    config = WorkerConfig(BoundaryText.of("worker-test"), poll_seconds=1.0)
    monkeypatch.setattr("caos.graph.worker.secrets.randbelow", lambda _n: 400)
    assert worker.pause_seconds(config, 2) <= 2.0 * 1.2
    monkeypatch.setattr("caos.graph.worker.secrets.randbelow", lambda _n: 0)
    assert worker.pause_seconds(config, 2) >= 2.0 * 0.8


@pytest.mark.parametrize(
    "refused",
    [RefusalCode.STORE_UNAVAILABLE, RefusalCode.RUN_NOT_FOUND],
)
def test_a_cancel_that_refuses_backs_off_or_parks_but_never_escapes(  # noqa: PLR0913 -- the loop's own fixtures, plus the patch, the capture and the code
    case: tuple[StoreConnection, UUID],
    route: ResolvedRoute,
    bundle: Bundle,
    blobs: BlobStore,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    refused: RefusalCode,
) -> None:
    """W4: the two codes `cancel_run` can refuse beside a lost lease, each
    treated as its own recovery allows.

    `STORE_UNAVAILABLE` heals itself -- released, the lease expires, the run is
    reclaimed with its cancel still pending and the cancel is retried -- so it
    takes the loop's back-off; parking it would turn a transient fault into a
    stop an operator has to requeue by hand. `RUN_NOT_FOUND` has no such
    recovery, so it parks with its code, because raising it would leave
    `work_once` holding the claim and the run at the head of every later poll.
    """
    run = queued_run(case, route, bundle, blobs)
    # What `request_cancel` records for a run a worker holds; recorded here
    # before the claim because this test's `execution_for` stands in for the
    # fence that would otherwise read it.
    run.conn.execute(
        "UPDATE run_work SET cancel_requested_at = now() WHERE run_id = %s",
        (run.run_id,),
    )
    run.conn.commit()

    def cancelling(conn: StoreConnection, run_id: UUID, lease: object) -> object:
        raise Refusal(RefusalCode.RUN_CANCEL_REQUESTED)

    def refusing(*args: object, **kwargs: object) -> None:
        raise Refusal(refused)

    monkeypatch.setattr(worker, "cancel_run", refusing)

    def claim() -> UUID | None:
        return work_once(
            run.conn,
            run.blobs,
            execution_for=cancelling,  # type: ignore[arg-type]
            config=CONFIG,
            stopping=Event(),
        )

    if refused is RefusalCode.STORE_UNAVAILABLE:
        with pytest.raises(Refusal) as caught:
            claim()
        assert caught.value.code is refused
        # Released, not stopped, and the request that the run be cancelled
        # survives the release -- which is what makes the retry a retry.
        assert work_row(run.conn, run.run_id) == ("QUEUED", None, None, True)
        assert _cancel_requested(run.conn, run.run_id)
        assert capsys.readouterr().err == ""
    else:
        assert claim() == run.run_id, "returned, not raised"
        assert work_row(run.conn, run.run_id) == (
            "STOPPED",
            refused.value,
            None,
            True,
        )
        assert capsys.readouterr().err.strip().splitlines()[-1] == refused.value


def _cancel_requested(conn: StoreConnection, run_id: UUID) -> bool:
    row = conn.execute(
        "SELECT cancel_requested_at IS NOT NULL FROM run_work WHERE run_id = %s",
        (run_id,),
    ).fetchone()
    conn.rollback()
    assert row is not None
    return bool(row[0])


def test_the_worker_says_what_it_is_doing_and_a_backing_off_worker_says_so(
    case: tuple[StoreConnection, UUID],
    route: ResolvedRoute,
    bundle: Bundle,
    blobs: BlobStore,
    empty_database: str,
) -> None:
    """The half of the heartbeat that lives in the loop rather than the store.

    A worker failing to reach the store is the case the ledger entry names --
    until now visible in nothing but a log -- so the states it writes have to
    tell that apart from an idle poll. `WORKING` is said *before* the run is
    driven, because driving is the part that takes minutes and "went quiet
    while working" is a different thing to an operator than "went quiet while
    idle".
    """
    run = queued_run(case, route, bundle, blobs)

    def faulty(conn: StoreConnection, run_id: UUID, lease: object) -> object:
        raise Refusal(RefusalCode.STORE_UNAVAILABLE)

    run_worker(
        CONFIG,
        execution_for=faulty,  # type: ignore[arg-type]
        stopping=_Clock(limit=3),
        conn_factory=lambda: psycopg.connect(empty_database, autocommit=False),
        blobs=blobs,
    )

    [state] = worker_states(run.conn)
    assert (state.worker_id, state.fresh) == ("worker-test", True)
    # The last word is BACKOFF with a count: the loop faulted and said so.
    assert state.state == "BACKOFF"
    assert state.consecutive_faults > 0


def test_a_store_that_will_not_take_the_beat_does_not_stop_the_worker(
    case: tuple[StoreConnection, UUID],
    route: ResolvedRoute,
    bundle: Bundle,
    blobs: BlobStore,
    empty_database: str,
) -> None:
    """A heartbeat is an observation for a person, not a fence. Nothing reads
    it to decide whether work may proceed, so a beat that will not write must
    not take the worker down with it -- what answers a failing store is the
    loop's own fault handling, by trying to claim a run."""
    queued_run(case, route, bundle, blobs)
    driven: list[UUID] = []

    def refusing(*args: object, **kwargs: object) -> None:
        raise psycopg.OperationalError

    def watching(conn: StoreConnection, run_id: UUID, lease: object) -> object:
        driven.append(run_id)
        raise Refusal(RefusalCode.STORE_UNAVAILABLE)

    # A context rather than the fixture: one parameter fewer, and the patch is
    # visibly scoped to the loop it is meant to affect.
    with pytest.MonkeyPatch.context() as patched:
        patched.setattr("caos.graph.worker.beat", refusing)
        assert (
            run_worker(
                CONFIG,
                execution_for=watching,  # type: ignore[arg-type]
                stopping=_Clock(limit=2),
                conn_factory=lambda: psycopg.connect(empty_database, autocommit=False),
                blobs=blobs,
            )
            == 0
        )

    assert driven, "the worker kept claiming runs while its beat was refused"


def test_a_worker_drives_runs_one_node_at_a_time_without_a_checkpointer(
    case: tuple[StoreConnection, UUID],
    route: ResolvedRoute,
    bundle: Bundle,
    blobs: BlobStore,
) -> None:
    """The default every test in this file relies on, asserted once so it is a
    decision rather than an accident: one node at a time (next.md N1) and no
    checkpointer unless the worker was given one (D6)."""
    run = queued_run(case, route, bundle, blobs)
    handed: list[Execution] = []

    def capture(*_args: object, **kwargs: object) -> None:
        handed.append(cast(Execution, kwargs["execution"]))

    with pytest.MonkeyPatch.context() as patched:
        patched.setattr("caos.graph.worker.run_route", capture)
        work_once(
            run.conn,
            blobs,
            execution_for=module_execution(
                CanonicalCompletions(run.source_id), priced(ESTIMATE), bundle, blobs
            ),
            config=CONFIG,
            stopping=Event(),
        )

    [execution] = handed
    assert execution.checkpointer is None
    assert execution.lease is not None


def test_the_backoff_stays_at_its_cap_after_any_number_of_faults() -> None:
    """AR-03: the exponent is bounded before it is raised, so a worker that has
    faulted for hours keeps waiting at the cap instead of overflowing."""
    config = WorkerConfig(BoundaryText.of("worker-test"), poll_seconds=1.0)
    assert worker.MAX_DOUBLINGS == 30
    for failures in (1025, 100_000):
        assert (
            worker.pause_seconds(config, failures) <= config.backoff_cap_seconds * 1.2
        )


def test_a_session_the_server_ends_does_not_stop_the_worker(
    blobs: BlobStore, empty_database: str
) -> None:
    """AR-01, SA-C4: Lakebase ends sessions on every failover, restart and
    scale-to-zero. The worker's heartbeat on the dead session, its rollback
    included, must not escape the reconnect; the loop opens a new session."""
    import threading

    opened: list[int] = []
    name = "caos-worker-under-test"

    def factory() -> StoreConnection:
        conn = psycopg.connect(empty_database, autocommit=False, application_name=name)
        opened.append(1)
        return conn

    def never(conn: StoreConnection, run_id: UUID, lease: Lease) -> Execution:
        raise AssertionError(name)

    stopping = Event()
    config = WorkerConfig(BoundaryText.of("worker-test"), poll_seconds=0.1)
    thread = threading.Thread(
        target=run_worker,
        kwargs={
            "config": config,
            "execution_for": never,
            "stopping": stopping,
            "conn_factory": factory,
            "blobs": blobs,
        },
        daemon=True,
    )
    thread.start()
    try:
        deadline = time.monotonic() + 10
        while not opened and time.monotonic() < deadline:
            time.sleep(0.05)
        ended: tuple[object, ...] | None = (0,)
        with psycopg.connect(empty_database, autocommit=True) as admin:
            # The backend shows in `pg_stat_activity` a moment after the
            # client's connect returns; ask until it is there.
            while ended == (0,) and time.monotonic() < deadline:
                ended = admin.execute(
                    "SELECT count(pg_terminate_backend(pid)) FROM pg_stat_activity"
                    " WHERE application_name = %s",
                    (name,),
                ).fetchone()
                time.sleep(0.05)
        assert ended == (1,)
        while len(opened) < 2 and time.monotonic() < deadline:
            time.sleep(0.05)
        assert len(opened) >= 2, "the loop reconnected"
        assert thread.is_alive(), "and the worker went on"
    finally:
        stopping.set()
        thread.join(5)
    assert not thread.is_alive()


def test_a_connection_factory_failing_in_the_sdk_s_shapes_is_a_store_fault(
    blobs: BlobStore,
) -> None:
    """CR-1, SA-C3: the SDK behind `store_url` reports an unreachable workspace
    or a refused token as `ValueError`; the loop rides it out as a store fault
    and never exits with the API still serving."""

    message = "the host, which must not be printed"

    def unreachable() -> StoreConnection:
        raise ValueError(message)

    def never(conn: StoreConnection, run_id: UUID, lease: Lease) -> Execution:
        raise AssertionError(message)

    with pytest.raises(Refusal, match=r"^STORE_UNAVAILABLE$"):
        worker._connected(unreachable)
    clock = _Clock(limit=2)
    assert (
        run_worker(
            CONFIG,
            execution_for=never,
            stopping=clock,
            conn_factory=unreachable,
            blobs=blobs,
        )
        == 0
    )
    assert len(clock.pauses) == 2, "backed off twice, then stopped as told"


def test_a_cancel_during_the_last_call_ends_the_run_cancelled(
    case: tuple[StoreConnection, UUID],
    route: ResolvedRoute,
    bundle: Bundle,
    blobs: BlobStore,
    empty_database: str,
) -> None:
    """AR-13: a cancel that lands during the last node's call is honoured at
    the terminal move. The last call's artifact and bill stay committed; the
    run ends CANCELLED through the holder's cancel path, not COMPLETE."""
    from caos.store.work import request_cancel

    run = queued_run(case, route, bundle, blobs)
    calls: list[int] = []

    def late_cancel() -> None:
        calls.append(1)
        if len(calls) == len(route.nodes):
            with psycopg.connect(empty_database, autocommit=False) as other:
                assert request_cancel(other, run.run_id) is True
                other.commit()

    completions = CanonicalCompletions(run.source_id, during=late_cancel)
    assert drive(run, completions) == run.run_id
    assert len(calls) == len(route.nodes), "every node was called once"
    assert run_status(run.conn, run.run_id) is RunStatus.CANCELLED
    run.conn.rollback()
    assert count(run.conn, "artifacts", run.run_id) == len(route.nodes)
    assert work_row(run.conn, run.run_id)[0] == "DONE"


def test_a_parked_run_s_checkpoint_thread_is_forgotten(
    case: tuple[StoreConnection, UUID],
    route: ResolvedRoute,
    bundle: Bundle,
    blobs: BlobStore,
    empty_database: str,
) -> None:
    """DL-8: the thread holds position only (D6); a run this worker parked
    leaves no rows behind, and the requeued run re-derives its frontier."""
    from caos.graph.build import thread_config
    from caos.graph.checkpoint import checkpointer, close_checkpointer

    run = queued_run(case, route, bundle, blobs)
    saver = checkpointer(empty_database)
    try:

        def refuse() -> None:
            raise Refusal(RefusalCode.PROVIDER_CALL_INVALID)

        completions = CanonicalCompletions(run.source_id, during=refuse)
        driven = work_once(
            run.conn,
            run.blobs,
            execution_for=module_execution(
                completions, priced(ESTIMATE), run.bundle, run.blobs, saver
            ),
            config=CONFIG,
            stopping=Event(),
        )
        assert driven == run.run_id
        assert work_row(run.conn, run.run_id)[:2] == (
            "STOPPED",
            "PROVIDER_CALL_INVALID",
        )
        assert saver.get(thread_config(str(run.run_id))) is None
    finally:
        close_checkpointer(saver)


def test_a_lost_or_corrupt_stored_body_parks_the_run_with_its_own_code() -> None:
    """DL-5: a blob that is gone or corrupt is not a store fault. As one it
    released the run to the head of the queue, and every other run waited
    behind it forever."""
    from caos.methodology import canonical

    class _Blobs:
        def __init__(self, code: RefusalCode) -> None:
            self.code = code

        def get(self, digest: str) -> bytes:
            raise Refusal(self.code)

    def stored(code: RefusalCode) -> str | None:
        return canonical._stored_body(cast("BlobStore", _Blobs(code)), "ab" * 32)

    for lost in (RefusalCode.BLOB_NOT_FOUND, RefusalCode.BLOB_DIGEST_MISMATCH):
        with pytest.raises(Refusal, match=f"^{lost.value}$"):
            stored(lost)
    with pytest.raises(Refusal, match=r"^STORE_UNAVAILABLE$"):
        stored(RefusalCode.STORE_UNAVAILABLE)


def test_the_app_s_shutdown_hooks_run_after_the_probes_stop(
    empty_database: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """DP-4: what the process entry registers runs inside the lifespan's
    shutdown, the only code that runs before uvicorn re-raises the platform's
    signal; `caos.serve` registers the worker drain there."""
    from fastapi.testclient import TestClient

    from caos import serve
    from caos.api import app as app_module
    from caos.api import health

    assert serve.GRACEFUL_SECONDS + serve.LIMIT_JOIN_SECONDS < 15
    assert serve.LIMIT_CONCURRENCY > 24, "every stream slot and forty more (DP-7)"
    monkeypatch.setenv("CAOS_DATABASE_URL", empty_database)
    monkeypatch.setattr(health, "PROBES", dict.fromkeys(health.PROBES, lambda: "OK"))
    ran: list[str] = []
    app_module.on_shutdown(lambda: ran.append("drained"))
    try:
        with TestClient(app_module.app):
            assert ran == []
        assert ran == ["drained"]
    finally:
        app_module.SHUTDOWN_HOOKS.clear()


def test_the_server_log_never_carries_an_exception_s_text() -> None:
    """AS-6: uvicorn logs an unhandled fault with its traceback, and a
    traceback carries `str(exc)`; the process entry's filter drops it."""
    import logging

    from caos import serve

    serve.install_log_filter()
    serve.install_log_filter()
    logger = logging.getLogger(serve.SERVER_LOGGER)
    assert sum(isinstance(f, serve._NoExceptionText) for f in logger.filters) == 1
    message = "document text that must not be logged"

    def fault() -> None:
        raise RuntimeError(message)

    try:
        fault()
    except RuntimeError:
        record = logging.LogRecord(
            serve.SERVER_LOGGER,
            logging.ERROR,
            __file__,
            1,
            "Exception in ASGI application",
            None,
            sys.exc_info(),
        )
    assert logger.filter(record), "the record still logs, without its text"
    assert record.exc_info is None and record.exc_text is None
    assert message not in logging.Formatter().format(record)

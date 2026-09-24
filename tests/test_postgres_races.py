"""Every governed race proven on two independent connections.

`docs/AI_CODE_QUALITY.md` section 1 lists concurrency at ~2x in agent-written
code, and the control it names is this file: a race argued from the code is not
a race proven. One connection cannot prove a lock -- it never contends with
itself -- so each test here holds two.
"""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from threading import Barrier, Event
from uuid import UUID, uuid4

import pytest
from canonical_fixtures import (
    CATALOG,
    LITE_PROFILE,
    LITE_SELECTION,
    VENDORED,
    CanonicalCompletions,
)
from conftest import priced
from conftest import reserve_at as reserve
from run_terminals import fail_run
from test_run_events import RECORD, accept_nodes, approved_nodes

from caos.blobs import BlobStore
from caos.boundary_text import BoundaryText
from caos.graph import runtime
from caos.graph.route import NodeState, ResolvedRoute, resolve_route
from caos.graph.runtime import Execution, Provider, ProviderResult, run_route
from caos.methodology.bundle import Bundle
from caos.refusals import Refusal, RefusalCode
from caos.store import RunStatus, StoreConnection, apply_schema, connect, runs
from caos.store.events import RunEvent, events_of
from caos.store.outcomes import check_call, execution_reads
from caos.store.runs import (
    Accepted,
    accept_attempt,
    block_run,
    complete_attempt,
    complete_run,
    create_case,
    run_status,
    start_attempt,
    start_run,
)
from caos.store.work import (
    MAX_QUEUED_RUNS_PER_ACTOR,
    Lease,
    claim_run,
    enqueue_run,
    holds_lease,
    request_cancel,
    stop,
)

# The producer the store records beside every accepted artifact: what the
# host configured, and the provider's own handle for the call.
MODEL = "a-model/for-the-test"
GENERATION = "gen-for-the-test"

ARTIFACT = "c" * 64
CHARGE = Decimal("0.0142")
APPENDERS = 8


def test_concurrent_sign_freeze_and_file_across_two_cases_keep_one_chain_each(
    empty_database: str, tmp_path: Path
) -> None:
    import inspect
    from dataclasses import replace
    from typing import cast

    from test_deliverable_canonical import LITE, _accept
    from test_execution_freshness import _Harness, harness
    from test_filing_chain import _actor, _freeze, _sign
    from test_revisions import _save

    from caos.deliverable.filing import file_deliverable
    from caos.deliverable.receipts import read_filed_receipt
    from caos.store.audit import audit_trail, verify_chain

    make_harness = cast(
        Callable[[tuple[StoreConnection, UUID], Path, ResolvedRoute], _Harness],
        inspect.unwrap(harness),
    )
    with connect(empty_database) as conn:
        apply_schema(conn)
        cases = []
        for index in range(2):
            case_id = create_case(conn, BoundaryText.of(f"Issuer {index}"))
            conn.commit()
            held = make_harness((conn, case_id), tmp_path / str(index), LITE)
            for module in ("CP-0", "CP-L10", "CP-5"):
                _accept(held, module)
            # FP-33: `_save` drafts as `held.approver`, so the two racing sign
            # attempts need their own, independent signer minted up front --
            # `_sign`'s own default is memoized lazily, which two threads
            # racing its very first call could double-grant.
            cases.append((held, _save(held), _actor(held), _actor(held), _actor(held)))

        for stage in ("sign", "freeze", "file"):
            barrier = Barrier(4)

            def race(index: int, stage: str = stage, barrier: Barrier = barrier) -> str:
                held, revision, signer, freezer, filer = cases[index // 2]
                with connect(empty_database) as other:
                    current = replace(held, conn=other)
                    barrier.wait(10)
                    try:
                        if stage == "sign":
                            _sign(current, revision, signer)
                        elif stage == "freeze":
                            _freeze(current, revision, freezer)
                        else:
                            receipt = file_deliverable(
                                other,
                                held.blobs,
                                case_id=held.case_id,
                                actor_id=filer,
                                revision_id=revision,
                            )
                            assert (receipt.case_id, receipt.run_id) == (
                                held.case_id,
                                held.run_id,
                            )
                    except Refusal as refused:
                        return refused.code.value
                    return "OK"

            with ThreadPoolExecutor(max_workers=4) as pool:
                outcomes = list(pool.map(race, range(4)))
            expected = {
                # One approver signing twice at once: `0029` keeps one.
                "sign": ["OK", "DELIVERABLE_ALREADY_SIGNED"],
                "freeze": ["OK", "DELIVERABLE_ALREADY_FROZEN"],
                "file": ["OK", "DELIVERABLE_ALREADY_FILED"],
            }[stage]
            for pair in (outcomes[:2], outcomes[2:]):
                assert sorted(pair) == sorted(expected)
        for held, revision, _, _, _ in cases:
            actions = [entry.action for entry in audit_trail(conn, held.case_id)]
            assert (
                actions.count("OPINION_SIGNED")
                == actions.count("DELIVERABLE_FROZEN")
                == actions.count("DELIVERABLE_FILED")
                == 1
            )
            assert verify_chain(conn, held.case_id)
            rows = conn.execute(
                "SELECT receipt_sha256 FROM deliverable_receipts WHERE case_id=%s",
                (held.case_id,),
            ).fetchall()
            assert len(rows) == 1
            assert read_filed_receipt(
                conn,
                held.blobs,
                case_id=held.case_id,
                run_id=held.run_id,
                revision_id=revision,
            ) == held.blobs.get(rows[0][0])


@pytest.fixture
def prepared_run(empty_database: str) -> tuple[UUID, UUID]:
    with connect(empty_database) as conn:
        apply_schema(conn)
        case_id = create_case(conn, BoundaryText.of("Acme 2026 refinancing"))
        run_id = start_run(conn, case_id)
        conn.commit()
    return case_id, run_id


def test_concurrent_appenders_never_share_a_seq(
    empty_database: str, prepared_run: tuple[UUID, UUID]
) -> None:
    """`run_events.seq` is allocated under the run row lock (SYSTEM_SPEC.md 2).

    Without the lock, two connections read the same `max(seq)` and insert the
    same next one: on a primary key that is a failed insert, and on anything
    weaker it is two events that claim one position in the stream.
    """
    _case_id, run_id = prepared_run

    def append(node: int) -> None:
        with connect(empty_database) as conn:
            start_attempt(conn, run_id, f"CP-{node}")
            conn.commit()

    with ThreadPoolExecutor(max_workers=APPENDERS) as pool:
        list(pool.map(append, range(APPENDERS)))

    with connect(empty_database) as conn:
        assert [event.seq for event in events_of(conn, run_id)] == list(
            range(1, APPENDERS + 1)
        )


def test_two_connections_claiming_one_queued_run_claim_it_once(
    empty_database: str, prepared_run: tuple[UUID, UUID]
) -> None:
    """`FOR UPDATE SKIP LOCKED` and the token increment make one claim (D3, I1)."""
    _case_id, run_id = prepared_run
    with connect(empty_database) as conn:
        enqueue_run(conn, run_id)
        conn.commit()
    start = Barrier(APPENDERS)

    def claim(worker: int) -> Lease | None:
        with connect(empty_database) as conn:
            start.wait(5)
            return claim_run(
                conn, worker=BoundaryText.of(f"worker-{worker}"), lease_seconds=60
            )

    with ThreadPoolExecutor(max_workers=APPENDERS) as pool:
        claims = list(pool.map(claim, range(APPENDERS)))

    assert [lease for lease in claims if lease is not None] == [Lease(run_id, 1, 60)]
    with connect(empty_database) as conn:
        assert conn.execute(
            "SELECT state, lease_token FROM run_work WHERE run_id = %s", (run_id,)
        ).fetchone() == ("CLAIMED", 1)


def test_two_connections_completing_one_run_produce_one_terminal_event(
    empty_database: str, prepared_run: tuple[UUID, UUID], tmp_path: Path
) -> None:
    """Exactly-once under real contention rather than under replay.

    Two recovering processes can both believe they own the same attempt. The
    conditional update is what makes only one of them right.
    """
    _case_id, run_id = prepared_run
    with connect(empty_database) as conn:
        *others, last = approved_nodes(conn, run_id, tmp_path).values()
        # Completion needs every other pinned node accepted (brief 4.3 D8).
        accept_nodes(conn, run_id, *others)
        attempt_id = start_attempt(conn, run_id, last)
        conn.commit()

    def complete() -> bool:
        with connect(empty_database) as conn:
            return complete_attempt(
                conn,
                attempt_id=attempt_id,
                accepted=Accepted(
                    artifact_sha256=ARTIFACT,
                    charge=CHARGE,
                    model=MODEL,
                    generation_id=GENERATION,
                    record_sha256=RECORD,
                ),
            )

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(complete) for _ in range(2)]
        outcomes = sorted(future.result() for future in futures)

    assert outcomes == [False, True], "exactly one caller completed the run"
    with connect(empty_database) as conn:
        row = conn.execute(
            "SELECT count(*) FROM budget_ledger WHERE run_id = %s", (run_id,)
        ).fetchone()
        assert row is not None and row[0] == len(others) + 1, "one charge per node"
        assert run_status(conn, run_id) is RunStatus.COMPLETE
        assert [e.name for e in events_of(conn, run_id)].count("RUN_COMPLETE") == 1


def test_two_successors_for_one_blocked_run_commit_one(empty_database: str) -> None:
    """At most one successor per predecessor (§72), under real contention.

    Two connections each call `start_run` against the same BLOCKED predecessor.
    They do not meet at the index: `start_run` takes the case lock first
    (`lock_case`, `FOR UPDATE` on the case row), so the second serialises there
    and reaches its insert only after the first has committed. The partial unique
    index `runs_one_successor` is the backstop that then refuses it, inside its
    own unit, as the typed `RUN_ALREADY_SUPERSEDED` mapped from the index's
    declared name and never from a driver message. One link is committed; the
    loser committed nothing.

    The index is not redundant with the lock: drop `runs_one_successor` and both
    inserts commit, which is what makes this a rule rather than a consequence of
    the lock ordering. The original docstring described the two connections
    meeting at the index with both holding `FOR SHARE`, and the Task 10.3
    acceptance review probed it: with the case lock held elsewhere, the second
    caller hits `lock_timeout` before any share lock is taken. No host path
    reaches the insert without the case lock."""
    with connect(empty_database) as conn:
        apply_schema(conn)
        case_id = create_case(conn, BoundaryText.of("Issuer"))
        blocked = start_run(conn, case_id)
        conn.commit()
        assert block_run(conn, blocked)
    start = Barrier(2)

    def succeed(_: int) -> UUID | RefusalCode:
        with connect(empty_database) as conn:
            start.wait(5)
            try:
                run_id = start_run(conn, case_id, supersedes=blocked)
                conn.commit()
            except Refusal as refusal:
                return refusal.code
            return run_id

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(succeed, range(2)))

    winners = [o for o in outcomes if isinstance(o, UUID)]
    assert [o for o in outcomes if not isinstance(o, UUID)] == [
        RefusalCode.RUN_ALREADY_SUPERSEDED
    ]
    with connect(empty_database) as conn:
        rows = conn.execute(
            "SELECT run_id FROM runs WHERE supersedes_run_id = %s", (blocked,)
        ).fetchall()
        assert rows == [(winners[0],)]
        counted = conn.execute("SELECT count(*) FROM runs").fetchone()
        assert counted == (2,), "the loser inserted nothing"


def test_one_actor_racing_past_the_queue_cap_queues_exactly_the_cap(
    empty_database: str,
) -> None:
    """N15 (D39): the per-actor cap is counted under a per-actor lock held to
    commit. Each run here is in a case of its own, so no case or run lock
    orders the racers: without the actor's lock each would count the same
    committed rows and all would pass. Exactly the cap commits; every other
    racer is refused `QUEUED_RUNS_LIMIT_REACHED` and wrote nothing."""
    racers = MAX_QUEUED_RUNS_PER_ACTOR + 3
    actor = uuid4()
    with connect(empty_database) as conn:
        apply_schema(conn)
        run_ids = [
            start_run(conn, create_case(conn, BoundaryText.of(f"Issuer {n}")))
            for n in range(racers)
        ]
        conn.commit()
    start = Barrier(racers)

    def queue(run_id: UUID) -> bool | RefusalCode:
        with connect(empty_database) as conn:
            start.wait(5)
            try:
                queued = enqueue_run(conn, run_id, actor_id=actor)
            except Refusal as refusal:
                conn.rollback()
                return refusal.code
            conn.commit()
            return queued

    with ThreadPoolExecutor(max_workers=racers) as pool:
        outcomes = list(pool.map(queue, run_ids))

    assert outcomes.count(True) == MAX_QUEUED_RUNS_PER_ACTOR, outcomes
    assert outcomes.count(RefusalCode.QUEUED_RUNS_LIMIT_REACHED) == 3, outcomes
    with connect(empty_database) as conn:
        assert conn.execute(
            "SELECT count(*), count(*) FILTER (WHERE requested_by = %s) FROM run_work",
            (actor,),
        ).fetchone() == (MAX_QUEUED_RUNS_PER_ACTOR, MAX_QUEUED_RUNS_PER_ACTOR)
        # Nobody's queue is anybody else's: a run queued with no actor, as a
        # direct caller or Cancel queues one, counts against no one.
        spare = start_run(conn, create_case(conn, BoundaryText.of("Spare")))
        assert enqueue_run(conn, spare) is True
        conn.commit()


# -- The lease fence (brief 4.3 D3; interleavings I2-I4, I7, I8, I12) --------

RESERVED = Decimal("0.10")
WORKER = BoundaryText.of("worker-a")


def _claimed(url: str, run_id: UUID, *, enqueue: bool = True) -> Lease:
    with connect(url) as conn:
        if enqueue:
            enqueue_run(conn, run_id)
            conn.commit()
        lease = claim_run(conn, worker=WORKER, lease_seconds=60)
    assert lease is not None and lease.run_id == run_id
    return lease


def _reclaimed(url: str, run_id: UUID) -> Lease:
    """Expire the holder's lease and claim the run on another connection."""
    with connect(url) as conn:
        conn.execute(
            "UPDATE run_work SET lease_expires_at = now() - interval '1 second'"
            " WHERE run_id = %s",
            (run_id,),
        )
        conn.commit()
        lease = claim_run(conn, worker=BoundaryText.of("worker-b"), lease_seconds=60)
    assert lease is not None and lease.run_id == run_id
    return lease


def _refused(code: RefusalCode, call: Callable[[], object]) -> None:
    with pytest.raises(Refusal) as refused:
        call()
    assert refused.value.code is code


def _count(conn: StoreConnection, table: str, run_id: UUID) -> int:
    row = conn.execute(
        "SELECT count(*) FROM " + table + " WHERE run_id = %s", (run_id,)
    ).fetchone()
    conn.rollback()
    assert row is not None
    return int(row[0])


def _accepted() -> Accepted:
    return Accepted(
        artifact_sha256=ARTIFACT,
        charge=CHARGE,
        model=MODEL,
        generation_id=GENERATION,
        record_sha256=RECORD,
    )


def _checked(
    conn: StoreConnection, attempt: UUID, run_id: UUID, node: str, lease: Lease | None
) -> None:
    with execution_reads(conn):
        check_call(
            conn, attempt_id=attempt, run_id=run_id, route_node_id=node, lease=lease
        )


def test_a_reclaimed_lease_refuses_the_stale_start_attempt(
    empty_database: str, prepared_run: tuple[UUID, UUID]
) -> None:
    """I2: a holder whose lease was reclaimed starts nothing."""
    _case_id, run_id = prepared_run
    stale = _claimed(empty_database, run_id)
    fresh = _reclaimed(empty_database, run_id)
    with connect(empty_database) as a, connect(empty_database) as b:
        _refused(
            RefusalCode.LEASE_NOT_HELD,
            lambda: start_attempt(a, run_id, "CP-0", lease=stale),
        )
        assert _count(a, "run_attempts", run_id) == 0
        attempt = start_attempt(b, run_id, "CP-0", lease=fresh)
        assert b.execute(
            "SELECT lease_token FROM run_attempts WHERE attempt_id = %s", (attempt,)
        ).fetchone() == (fresh.token,)


def test_a_reclaimed_lease_refuses_the_stale_reservation_and_no_call_is_made(
    empty_database: str, prepared_run: tuple[UUID, UUID]
) -> None:
    """I3: the reservation refuses, and the pre-transport check refuses too."""
    _case_id, run_id = prepared_run
    stale = _claimed(empty_database, run_id)
    with connect(empty_database) as a:
        attempt = start_attempt(a, run_id, "CP-0", lease=stale)
        _reclaimed(empty_database, run_id)
        _refused(
            RefusalCode.LEASE_NOT_HELD,
            lambda: reserve(a, attempt, RESERVED, lease=stale),
        )
        assert _count(a, "budget_reservations", run_id) == 0
        _refused(
            RefusalCode.LEASE_NOT_HELD,
            lambda: _checked(a, attempt, run_id, "CP-0", stale),
        )


def test_a_stale_worker_returning_after_reclaim_keeps_its_bill_and_accepts_nothing(
    empty_database: str, prepared_run: tuple[UUID, UUID], tmp_path: Path
) -> None:
    """I4: money always commits; acceptance is the holder's alone."""
    _case_id, run_id = prepared_run
    with connect(empty_database) as conn:
        node = approved_nodes(conn, run_id, tmp_path)["CP-0"]
    stale = _claimed(empty_database, run_id)
    with connect(empty_database) as a, connect(empty_database) as b:
        first = start_attempt(a, run_id, node, lease=stale)
        reserve(a, first, RESERVED, lease=stale)
        # A is calling; its lease expires and B reclaims, starts and pays.
        fresh = _reclaimed(empty_database, run_id)
        second = start_attempt(b, run_id, node, lease=fresh)
        reserve(b, second, RESERVED, lease=fresh)
        # A returns before B accepts: nothing but the fence stops it.
        _refused(
            RefusalCode.LEASE_NOT_HELD,
            lambda: accept_attempt(
                a, attempt_id=first, accepted=_accepted(), lease=stale
            ),
        )
        assert _count(a, "budget_ledger", run_id) == 1, "A's bill committed"
        assert _count(a, "artifacts", run_id) == 0
        assert accept_attempt(b, attempt_id=second, accepted=_accepted(), lease=fresh)
        assert _count(b, "budget_ledger", run_id) == 2
        assert b.execute(
            "SELECT attempt_id FROM artifacts WHERE run_id = %s", (run_id,)
        ).fetchall() == [(second,)]


def test_a_claim_during_an_in_flight_acceptance_takes_nothing(
    empty_database: str, prepared_run: tuple[UUID, UUID], tmp_path: Path
) -> None:
    """I7: the accept holds the work row and renews it; the claim skips it."""
    _case_id, run_id = prepared_run
    with connect(empty_database) as conn:
        node = approved_nodes(conn, run_id, tmp_path)["CP-0"]
    lease = _claimed(empty_database, run_id)
    with connect(empty_database) as a, connect(empty_database) as b:
        attempt = start_attempt(a, run_id, node, lease=lease)
        reserve(a, attempt, RESERVED, lease=lease)
        b.execute(
            "UPDATE run_work SET lease_expires_at = now() - interval '1 second'"
            " WHERE run_id = %s",
            (run_id,),
        )
        b.commit()
        # The acceptance unit, stopped before its commit.
        assert runs._accept(a, attempt, _accepted(), lease)
        assert claim_run(b, worker=WORKER, lease_seconds=60) is None, "row held"
        a.commit()
        assert claim_run(b, worker=WORKER, lease_seconds=60) is None, "renewed"
        assert _count(b, "artifacts", run_id) == 1
        assert b.execute(
            "SELECT state, lease_token FROM run_work WHERE run_id = %s", (run_id,)
        ).fetchone() == ("CLAIMED", lease.token)


def test_a_stale_worker_cannot_end_the_run(
    empty_database: str, prepared_run: tuple[UUID, UUID]
) -> None:
    """I8: every terminal transition is fenced."""
    _case_id, run_id = prepared_run
    stale = _claimed(empty_database, run_id)
    fresh = _reclaimed(empty_database, run_id)
    with connect(empty_database) as conn:
        for end in (complete_run, block_run, fail_run):
            _refused(
                RefusalCode.LEASE_NOT_HELD,
                lambda end=end: end(conn, run_id, lease=stale),  # type: ignore[misc]
            )
            assert run_status(conn, run_id) is RunStatus.RUNNING
        assert not [e for e in events_of(conn, run_id) if e.name.startswith("RUN_")]
        conn.rollback()
        assert fail_run(conn, run_id, lease=fresh)
        assert run_status(conn, run_id) is RunStatus.FAILED


def test_an_unleased_writer_cannot_touch_an_enqueued_run(
    empty_database: str, prepared_run: tuple[UUID, UUID], tmp_path: Path
) -> None:
    """I12: once enqueued, a run has no direct writers."""
    _case_id, run_id = prepared_run
    with connect(empty_database) as conn:
        node = approved_nodes(conn, run_id, tmp_path)["CP-0"]
        enqueue_run(conn, run_id)
        conn.commit()
        _refused(RefusalCode.LEASE_NOT_HELD, lambda: start_attempt(conn, run_id, node))
    lease = _claimed(empty_database, run_id, enqueue=False)
    with connect(empty_database) as conn:
        attempt = start_attempt(conn, run_id, node, lease=lease)
        _refused(RefusalCode.LEASE_NOT_HELD, lambda: reserve(conn, attempt, RESERVED))
        reserve(conn, attempt, RESERVED, lease=lease)
        _refused(
            RefusalCode.LEASE_NOT_HELD,
            lambda: _checked(conn, attempt, run_id, node, None),
        )
        _refused(
            RefusalCode.LEASE_NOT_HELD,
            lambda: accept_attempt(conn, attempt_id=attempt, accepted=_accepted()),
        )
        for end in (complete_run, block_run, fail_run):
            _refused(RefusalCode.LEASE_NOT_HELD, lambda end=end: end(conn, run_id))  # type: ignore[misc]
        assert _count(conn, "artifacts", run_id) == 0
        assert run_status(conn, run_id) is RunStatus.RUNNING


def test_a_requested_cancel_refuses_the_next_start_and_reservation(
    empty_database: str, prepared_run: tuple[UUID, UUID], tmp_path: Path
) -> None:
    """D4: a cancel stops new spend; an answer already paid for still lands."""
    _case_id, run_id = prepared_run
    with connect(empty_database) as conn:
        node = approved_nodes(conn, run_id, tmp_path)["CP-0"]
    lease = _claimed(empty_database, run_id)
    with connect(empty_database) as a, connect(empty_database) as b:
        paid = start_attempt(a, run_id, node, lease=lease)
        reserve(a, paid, RESERVED, lease=lease)
        unpaid = start_attempt(a, run_id, "CP-L10", lease=lease)
        assert request_cancel(b, run_id)
        b.commit()
        _refused(
            RefusalCode.RUN_CANCEL_REQUESTED,
            lambda: reserve(a, unpaid, RESERVED, lease=lease),
        )
        _refused(
            RefusalCode.RUN_CANCEL_REQUESTED,
            lambda: start_attempt(a, run_id, node, lease=lease),
        )
        assert _count(a, "budget_reservations", run_id) == 1
        assert _count(a, "run_attempts", run_id) == 2
        assert accept_attempt(a, attempt_id=paid, accepted=_accepted(), lease=lease)


def test_a_terminal_transition_marks_work_done_in_the_same_transaction(
    empty_database: str, prepared_run: tuple[UUID, UUID]
) -> None:
    """A work row that cannot close rolls the terminal status and event back."""
    _case_id, run_id = prepared_run
    lease = _claimed(empty_database, run_id)
    with connect(empty_database) as conn:
        conn.execute(
            "CREATE FUNCTION refuse_done() RETURNS trigger LANGUAGE plpgsql AS"
            " $$ BEGIN RAISE EXCEPTION 'no'; END; $$"
        )
        conn.execute(
            "CREATE TRIGGER refuse_done BEFORE UPDATE ON run_work FOR EACH ROW"
            " WHEN (NEW.state = 'DONE') EXECUTE FUNCTION refuse_done()"
        )
        conn.commit()
        _refused(
            RefusalCode.STORE_UNAVAILABLE, lambda: block_run(conn, run_id, lease=lease)
        )
        assert run_status(conn, run_id) is RunStatus.RUNNING
        names = [e.name for e in events_of(conn, run_id)]
        assert RunEvent.RUN_BLOCKED.value not in names
        conn.execute("DROP TRIGGER refuse_done ON run_work")
        conn.commit()
        assert block_run(conn, run_id, lease=lease)
        assert conn.execute(
            "SELECT state FROM run_work WHERE run_id = %s", (run_id,)
        ).fetchone() == ("DONE",)
        assert [e.name for e in events_of(conn, run_id)].count(
            RunEvent.RUN_BLOCKED.value
        ) == 1


@dataclass
class _Reclaiming:
    """A provider during whose call another worker reclaims the run.

    It deliberately does not record its own call outcome, unlike every other
    provider here and unlike `ModuleProvider`, which is what makes the bill
    this test counts `_accept`'s own record rather than the provider's: since
    the loop stopped recording, only acceptance can write that row. Read it as
    a probe of the acceptance unit, never as a template for a new provider --
    `Provider.execute` requires an implementation to bill its own call.
    """

    url: str
    run_id: UUID
    calls: list[str] = field(default_factory=list)

    @property
    def model(self) -> str:
        return MODEL

    def check_context(self, route_node_id: str, module_id: str) -> int:
        # No prompt is built here, so there are no request bytes to price.
        return 0

    def execute(
        self, route_node_id: str, module_id: str, *, attempt_id: UUID
    ) -> ProviderResult:
        self.calls.append(module_id)
        _reclaimed(self.url, self.run_id)
        return ProviderResult(ARTIFACT, CHARGE, MODEL, GENERATION, record_sha256=RECORD)


def test_the_runtime_writes_under_its_executions_lease(
    empty_database: str, prepared_run: tuple[UUID, UUID], tmp_path: Path
) -> None:
    """`Execution.lease` reaches every fenced write: a lease lost mid-call keeps
    the bill and accepts nothing, and the stale lease then starts nothing."""
    _case_id, run_id = prepared_run
    bundle = Bundle(VENDORED)
    route = resolve_route(CATALOG, LITE_PROFILE, LITE_SELECTION)
    with connect(empty_database) as conn:
        approved_nodes(conn, run_id, tmp_path, bundle, route)
        conn.commit()
    lease = _claimed(empty_database, run_id)
    blobs = BlobStore(tmp_path / "blobs")
    provider = _Reclaiming(empty_database, run_id)
    with connect(empty_database) as conn:

        def run() -> None:
            run_route(
                conn,
                blobs,
                run_id=run_id,
                route=route,
                execution=Execution(provider, priced(RESERVED), bundle, lease=lease),
            )

        _refused(RefusalCode.LEASE_NOT_HELD, run)
        assert provider.calls == ["CP-0"]
        assert _count(conn, "budget_ledger", run_id) == 1
        assert _count(conn, "artifacts", run_id) == 0
        _refused(RefusalCode.LEASE_NOT_HELD, run)
        assert provider.calls == ["CP-0"], "a stale lease starts no attempt"
        # The node is billed with no stored body, which is its own refusal --
        # but the lease answer comes first, so `holds_lease` is what decides
        # which of the two this caller is told.
        assert not holds_lease(conn, run_id, lease)
        assert _count(conn, "run_attempts", run_id) == 1


@pytest.mark.parametrize("moves", [1, 2])
def test_a_stale_terminal_decision_runs_one_more_pass_then_raises(
    empty_database: str,
    prepared_run: tuple[UUID, UUID],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    moves: int,
) -> None:
    """D8: `run_route` decides from a read unit; a node accepted on another
    connection before the lock refuses `RUN_TERMINAL_STALE`, and the loop
    decides once more from the store -- at most once per call."""
    _case_id, run_id = prepared_run
    bundle = Bundle(VENDORED)
    route = resolve_route(CATALOG, LITE_PROFILE, LITE_SELECTION)
    with connect(empty_database) as conn:
        nodes = approved_nodes(conn, run_id, tmp_path, bundle, route)
        conn.commit()
    # Neither gate nor QA source: accepted as presence, no record to verify.
    movers = [nodes["CP-L10"], nodes["CP-5"]][:moves]
    decided: list[frozenset[str] | None] = []

    def moving(
        conn: StoreConnection,
        run: UUID,
        *,
        lease: Lease | None = None,
        accepted: frozenset[str] | None = None,
    ) -> bool:
        decided.append(accepted)
        if movers:
            with connect(empty_database) as other:
                accept_nodes(other, run, movers.pop(0))
        return block_run(conn, run, lease=lease, accepted=accepted)

    monkeypatch.setattr(runtime, "frontier", lambda *_args: ())
    monkeypatch.setattr(
        runtime,
        "node_states",
        lambda *_args: {n.route_node_id: NodeState.BLOCKED for n in route.nodes},
    )
    monkeypatch.setattr(runtime, "block_run", moving)
    execution = Execution(_Reclaiming(empty_database, run_id), priced(RESERVED), bundle)
    blobs = BlobStore(tmp_path / "blobs")
    with connect(empty_database) as conn:

        def run() -> None:
            run_route(conn, blobs, run_id=run_id, route=route, execution=execution)

        if moves == 1:
            run()
            assert run_status(conn, run_id) is RunStatus.BLOCKED
        else:
            _refused(RefusalCode.RUN_TERMINAL_STALE, run)
            assert run_status(conn, run_id) is RunStatus.RUNNING
        assert decided == [frozenset(), frozenset({nodes["CP-L10"]})], "no third"
        names = [e.name for e in events_of(conn, run_id)]
        assert names.count(RunEvent.RUN_BLOCKED.value) == (2 - moves)


# -- The worker loop (brief 4.3 D9; interleavings I1, I5, I9-I11) -------------


def _work(url: str, run: object, completions: object, blobs: BlobStore) -> UUID | None:
    from test_worker import CONFIG

    from caos.graph.worker import module_execution, work_once

    with connect(url) as conn:
        return work_once(
            conn,
            blobs,
            execution_for=module_execution(
                completions,  # type: ignore[arg-type]
                priced(Decimal("0.10")),
                Bundle(VENDORED),
                blobs,
            ),
            config=CONFIG,
            stopping=Event(),
        )


def _events(conn: StoreConnection, run_id: UUID, name: RunEvent) -> int:
    found = [e.name for e in events_of(conn, run_id)].count(name.value)
    conn.rollback()
    return found


def test_two_workers_polling_one_queued_run_claim_it_once(
    case: tuple[StoreConnection, UUID], empty_database: str, tmp_path: Path
) -> None:
    """I1 through `work_once`: the loser builds no execution and calls nothing."""
    from test_worker import queued_run

    run = queued_run(case, _lite(), Bundle(VENDORED), BlobStore(tmp_path / "blobs"))
    completions = CanonicalCompletions(run.source_id)
    start = Barrier(2)

    def poll(_worker: int) -> UUID | None:
        start.wait(5)
        return _work(empty_database, run, completions, run.blobs)

    with ThreadPoolExecutor(max_workers=2) as pool:
        claimed = sorted(pool.map(poll, range(2)), key=lambda found: found is None)

    assert claimed == [run.run_id, None]
    assert run_status(run.conn, run.run_id) is RunStatus.COMPLETE
    assert len(completions.prompts) == len(_lite().nodes)
    assert _events(run.conn, run.run_id, RunEvent.RUN_COMPLETE) == 1


def test_cancel_during_a_call_keeps_the_bill_accepts_once_and_starts_nothing(
    case: tuple[StoreConnection, UUID], empty_database: str, tmp_path: Path
) -> None:
    """I9: the cancel never interrupts the call in flight; the next start
    refuses and the worker ends the run CANCELLED."""
    from test_worker import queued_run

    run = queued_run(case, _lite(), Bundle(VENDORED), BlobStore(tmp_path / "blobs"))

    def cancel() -> None:
        with connect(empty_database) as other:
            assert request_cancel(other, run.run_id)
            other.commit()

    completions = CanonicalCompletions(run.source_id, during=cancel)

    assert _work(empty_database, run, completions, run.blobs) == run.run_id

    assert len(completions.prompts) == 1
    for table in ("run_attempts", "budget_reservations", "budget_ledger", "artifacts"):
        assert _count(run.conn, table, run.run_id) == 1, table
    assert run_status(run.conn, run.run_id) is RunStatus.CANCELLED
    assert _events(run.conn, run.run_id, RunEvent.RUN_CANCELLED) == 1
    assert run.conn.execute(
        "SELECT state FROM run_work WHERE run_id = %s", (run.run_id,)
    ).fetchone() == ("DONE",)


def test_cancel_with_reclaim_ends_the_run_cancelled_exactly_once(
    case: tuple[StoreConnection, UUID], empty_database: str, tmp_path: Path
) -> None:
    """I10: A reserved, a cancel landed, A's lease expired; B's claim ends the
    run CANCELLED once and A's late acceptance and cancel change nothing."""
    from test_worker import queued_run

    run = queued_run(case, _lite(), Bundle(VENDORED), BlobStore(tmp_path / "blobs"))
    stale = _claimed(empty_database, run.run_id, enqueue=False)
    node = _lite().nodes[0].route_node_id
    with connect(empty_database) as a:
        attempt = start_attempt(a, run.run_id, node, lease=stale)
        reserve(a, attempt, RESERVED, lease=stale)
        assert request_cancel(a, run.run_id)
        a.commit()
        a.execute(
            "UPDATE run_work SET lease_expires_at = now() - interval '1 second'"
            " WHERE run_id = %s",
            (run.run_id,),
        )
        a.commit()
        completions = CanonicalCompletions(run.source_id)

        assert _work(empty_database, run, completions, run.blobs) == run.run_id

        assert completions.prompts == []
        assert run_status(a, run.run_id) is RunStatus.CANCELLED
        # A terminal run answers False before the fence; nothing is accepted.
        assert not accept_attempt(
            a, attempt_id=attempt, accepted=_accepted(), lease=stale
        )
        assert not runs.cancel_run(a, run.run_id, lease=stale)
        assert _count(a, "artifacts", run.run_id) == 0
        assert _events(a, run.run_id, RunEvent.RUN_CANCELLED) == 1


@pytest.mark.parametrize("state", ["QUEUED", "STOPPED"])
def test_a_cancel_racing_a_claim_either_claims_or_cancels(
    empty_database: str, prepared_run: tuple[UUID, UUID], state: str
) -> None:
    """I11: both need the work row; the run is claimed or cancelled, never
    cancelled with a live claim."""
    _case_id, run_id = prepared_run
    with connect(empty_database) as conn:
        enqueue_run(conn, run_id)
        conn.commit()
    if state == "STOPPED":
        stopped = _claimed(empty_database, run_id, enqueue=False)
        with connect(empty_database) as conn:
            assert stop(conn, stopped, RefusalCode.CITATION_NOT_LOCATED)
            conn.commit()
    start = Barrier(2)

    def cancel() -> bool:
        with connect(empty_database) as conn:
            start.wait(5)
            ended = request_cancel(conn, run_id)
            conn.commit()
            return ended

    def claim() -> Lease | None:
        with connect(empty_database) as conn:
            start.wait(5)
            return claim_run(conn, worker=WORKER, lease_seconds=60)

    with ThreadPoolExecutor(max_workers=2) as pool:
        cancelled, claimed = pool.submit(cancel), pool.submit(claim)
        lease = claimed.result()
        assert cancelled.result()
    with connect(empty_database) as conn:
        status = run_status(conn, run_id)
        [(work,)] = conn.execute(
            "SELECT state FROM run_work WHERE run_id = %s", (run_id,)
        ).fetchall()
        if lease is None:
            assert (status, work) == (RunStatus.CANCELLED, "DONE")
            assert _events(conn, run_id, RunEvent.RUN_CANCELLED) == 1
        else:
            assert state == "QUEUED"
            assert (status, work) == (RunStatus.RUNNING, "CLAIMED")
            assert _refused_start(conn, run_id, lease)


def _refused_start(conn: StoreConnection, run_id: UUID, lease: Lease) -> bool:
    _refused(
        RefusalCode.RUN_CANCEL_REQUESTED,
        lambda: start_attempt(conn, run_id, "CP-0", lease=lease),
    )
    return True


def _lite() -> ResolvedRoute:
    return resolve_route(CATALOG, LITE_PROFILE, LITE_SELECTION)


WORKER_SCRIPT = """
import os, signal, sys
from pathlib import Path
from threading import Event
from uuid import UUID
sys.dont_write_bytecode = True
sys.path[:0] = [os.environ["REPO"], os.environ["REPO"] + "/tests"]
from canonical_fixtures import VENDORED, CanonicalCompletions
from conftest import priced
from decimal import Decimal
from caos.blobs import BlobStore
from caos.boundary_text import BoundaryText
from caos.graph import runtime
from caos.graph.worker import WorkerConfig, module_execution, run_worker
from caos.methodology.bundle import Bundle
from caos.store import connect

calls = Path(os.environ["CALLS"])

class Recording(CanonicalCompletions):
    def complete(self, prompt, *, json_object=False):
        with calls.open("a") as out:
            out.write("call\\n")
        return super().complete(prompt, json_object=json_object)

class Once(Event):
    def wait(self, timeout=None):
        self.set()
        return True

if os.environ.get("KILL") == "1":
    def killed(*args, **kwargs):
        os.kill(os.getpid(), signal.SIGKILL)
    runtime.accept_attempt = killed

blobs = BlobStore(Path(os.environ["BLOBS"]))
bundle = Bundle(VENDORED)
completions = Recording(UUID(os.environ["SOURCE"]))
sys.exit(run_worker(
    WorkerConfig(BoundaryText.of("worker-subprocess")),
    execution_for=module_execution(completions, priced(Decimal("0.10")), bundle, blobs),
    stopping=Once(),
    conn_factory=lambda: connect(os.environ["URL"]),
    blobs=blobs,
))
"""


def test_worker_sigkilled_after_provider_return_restarts_without_a_second_call(
    case: tuple[StoreConnection, UUID], empty_database: str, tmp_path: Path
) -> None:
    """I5 across processes: the first worker dies after its provider returned
    and billed, before its acceptance; the restarted worker accepts the stored
    answer and never calls for that node again."""
    import os
    import signal
    import subprocess
    import sys

    from test_worker import queued_run

    run = queued_run(case, _lite(), Bundle(VENDORED), BlobStore(tmp_path / "blobs"))
    script = tmp_path / "worker_script.py"
    script.write_text(WORKER_SCRIPT, encoding="utf-8")
    calls = tmp_path / "calls.txt"
    repo = Path(__file__).resolve().parents[1]
    environment = {
        "PATH": os.environ["PATH"],
        "PYTHONDONTWRITEBYTECODE": "1",
        "REPO": str(repo),
        "URL": empty_database,
        "BLOBS": str(tmp_path / "blobs"),
        "SOURCE": str(run.source_id),
        "CALLS": str(calls),
    }

    def worker_process(kill: str) -> int:
        return subprocess.run(
            [sys.executable, "-B", str(script)],
            cwd=repo,
            env={**environment, "KILL": kill},
            check=False,
            timeout=120,
        ).returncode

    assert worker_process("1") == -signal.SIGKILL
    assert calls.read_text().splitlines() == ["call"]
    assert _count(run.conn, "budget_ledger", run.run_id) == 1
    assert _count(run.conn, "artifacts", run.run_id) == 0
    run.conn.execute(
        "UPDATE run_work SET lease_expires_at = now() - interval '1 second'"
        " WHERE run_id = %s",
        (run.run_id,),
    )
    run.conn.commit()

    assert worker_process("0") == 0

    assert calls.read_text().splitlines() == ["call"] * len(_lite().nodes)
    assert run_status(run.conn, run.run_id) is RunStatus.COMPLETE
    assert _count(run.conn, "run_attempts", run.run_id) == len(_lite().nodes)
    assert _count(run.conn, "budget_ledger", run.run_id) == len(_lite().nodes)
    assert _events(run.conn, run.run_id, RunEvent.RUN_COMPLETE) == 1


def test_a_report_read_never_blocks_a_governed_write_on_its_case(
    empty_database: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """C1: GET /report holds no row lock, so a writer's NOWAIT lock succeeds
    while the read is in progress."""
    import inspect
    from typing import cast

    import psycopg
    from fastapi.testclient import TestClient
    from test_deliverable_canonical import LITE, _accept
    from test_execution_freshness import _Harness, harness
    from test_revision_sections import _get
    from test_revisions import _save

    from caos.api import app as app_module
    from caos.api.app import app, blob_store, methodology_bundle, store_connection
    from caos.api.identity import TRUST_SWITCH
    from caos.api.reads import reports as reports_read
    from caos.deliverable.revisions import prove_revision

    make_harness = cast(
        Callable[[tuple[StoreConnection, UUID], Path, ResolvedRoute], _Harness],
        inspect.unwrap(harness),
    )
    with connect(empty_database) as conn:
        apply_schema(conn)
        case_id = create_case(conn, BoundaryText.of("Issuer"))
        conn.commit()
        held = make_harness((conn, case_id), tmp_path, LITE)
        for module in ("CP-0", "CP-L10", "CP-5"):
            _accept(held, module)
        revision = _save(held)
        conn.commit()

        probed: list[bool] = []
        original = cast(Callable[..., object], prove_revision)

        def probing(*args: object, **kwargs: object) -> object:
            # While the read is inside its unit, a second connection must be able
            # to take the case lock without waiting.
            with connect(empty_database) as other:
                try:
                    other.execute(
                        "SELECT case_id FROM cases WHERE case_id = %s"
                        " FOR UPDATE NOWAIT",
                        (case_id,),
                    )
                    probed.append(True)
                except psycopg.errors.LockNotAvailable:
                    probed.append(False)
                other.rollback()
            return original(*args, **kwargs)

        monkeypatch.setenv(app_module.DATABASE_URL, empty_database)
        monkeypatch.delenv(TRUST_SWITCH, raising=False)
        monkeypatch.setattr(reports_read, "prove_revision", probing)
        app.dependency_overrides[store_connection] = lambda: held.conn
        app.dependency_overrides[blob_store] = lambda: held.blobs
        app.dependency_overrides[methodology_bundle] = lambda: held.bundle
        try:
            with TestClient(app) as client:
                body = _get(client, held, revision, "report")
        finally:
            app.dependency_overrides.clear()
    assert body["revision_id"] == str(revision)
    assert probed == [True]


def test_two_saves_against_one_head_commit_one_revision(
    empty_database: str, tmp_path: Path
) -> None:
    """Task 12.1, invariant 5. Both drafts name the head they were composed
    against; the case lock orders them, and the second sees the first's commit.

    The route functions are called directly, on two connections of their own:
    what is under test is the unit the command builds, not FastAPI's resolution
    of its dependencies, which `tests/test_actor_matrix.py` drives.
    """
    import inspect
    from typing import cast
    from uuid import uuid4

    from test_deliverable_canonical import LITE, _accept
    from test_execution_freshness import _Harness, harness

    from caos.api.commands.deliverable import save as save_command
    from caos.api.commands.members import withdraw as withdraw_command
    from caos.api.identity import Actor, GlobalRole
    from caos.api.wire import SaveRevision, WithdrawSource
    from caos.store.members import Standing, grant

    make_harness = cast(
        Callable[[tuple[StoreConnection, UUID], Path, ResolvedRoute], _Harness],
        inspect.unwrap(harness),
    )
    with connect(empty_database) as conn:
        apply_schema(conn)
        case_id = create_case(conn, BoundaryText.of("Issuer"))
        conn.commit()
        held = make_harness((conn, case_id), tmp_path, LITE)
        for module in ("CP-0", "CP-L10", "CP-5"):
            _accept(held, module)
        writer = uuid4()
        grant(conn, case_id=case_id, user_id=writer, standing=Standing.WRITER)
        conn.commit()
        actor = Actor(user_id=writer, role=GlobalRole.ANALYST)
        draft = SaveRevision(expected_revision_id=None, narrative=[])

        for stage in ("save", "withdraw"):
            barrier = Barrier(2)

            def race(_index: int, stage: str = stage, bar: Barrier = barrier) -> str:
                with connect(empty_database) as other:
                    bar.wait(10)
                    try:
                        if stage == "save":
                            save_command(
                                actor=actor,
                                key=uuid4(),
                                _standing=Standing.WRITER,
                                run_id=held.run_id,
                                body=draft,
                                case_id=case_id,
                                conn=other,
                                blobs=held.blobs,
                                bundle=held.bundle,
                            )
                        else:
                            withdraw_command(
                                actor=actor,
                                key=uuid4(),
                                _standing=Standing.WRITER,
                                source_id=held.source_id,
                                _body=WithdrawSource(),
                                case_id=case_id,
                                conn=other,
                            )
                    except Refusal as refused:
                        return refused.code.value
                    return "OK"

            with ThreadPoolExecutor(max_workers=2) as pool:
                outcomes = sorted(pool.map(race, range(2)))
            assert outcomes == sorted(
                {
                    "save": ["OK", "COMMAND_EXPECTATION_STALE"],
                    "withdraw": ["OK", "EVIDENCE_NOT_AVAILABLE"],
                }[stage]
            ), stage

        saved = conn.execute(
            "SELECT count(*) FROM deliverable_revisions WHERE run_id=%s",
            (held.run_id,),
        ).fetchone()
        withdrawn = conn.execute(
            "SELECT count(*) FROM audit_events WHERE action='SOURCE_WITHDRAWN'"
        ).fetchone()
        conn.rollback()
        assert (saved, withdrawn) == ((1,), (1,))


@pytest.fixture
def relative_harness(case: tuple[StoreConnection, UUID], tmp_path: Path) -> object:
    """The RELATIVE_VALUE run, which is the only enabled route whose frontier
    is ever wider than one node -- 1, then 2, then 4, then 2 -- and therefore
    the only place the concurrent pass can be raced at all."""
    from test_relative_value_route import harness as build

    from caos.graph.route import resolve_route

    route = resolve_route(CATALOG, "FULL_CREDIT_32", "RELATIVE_VALUE")
    return build.__wrapped__(case, tmp_path, route)  # type: ignore[attr-defined]


def _relative_provider(harness: object, answers: object) -> Provider:
    from caos.methodology.runner import ModuleProvider

    return ModuleProvider(
        harness.conn,  # type: ignore[attr-defined]
        harness.bundle,  # type: ignore[attr-defined]
        harness.blobs,  # type: ignore[attr-defined]
        answers,  # type: ignore[arg-type]
        harness.route,  # type: ignore[attr-defined]
        harness.run_id,  # type: ignore[attr-defined]
    )


def test_two_workers_on_a_queue_of_two_runs_take_one_each(
    case: tuple[StoreConnection, UUID], empty_database: str, tmp_path: Path
) -> None:
    """Completion Phase 13.2: with work for both, neither worker idles.

    The neighbour above proves two workers cannot claim the *same* run. This
    proves the other half, and it is the half an operator wants: a queue that
    handed both pollers the same row and made the loser wait would satisfy
    every other test in this file while halving the fleet.

    Claims only. What happens *after* a claim -- one accepted artifact per
    node, one terminal event -- is the neighbour's, which drives a whole run
    through `work_once`; proving it twice here would need each worker to hold
    answers for whichever run its claim happened to give it, which measures the
    fixture rather than the queue.
    """
    from test_worker import CONFIG, queued_run

    from caos.store.work import claim_run

    blobs = BlobStore(tmp_path / "blobs")
    queued = {
        queued_run(case, _lite(), Bundle(VENDORED), blobs).run_id for _ in range(2)
    }
    start = Barrier(2)

    def poll(worker: int) -> UUID | None:
        with connect(empty_database) as conn:
            start.wait(5)
            lease = claim_run(
                conn,
                worker=BoundaryText.of(f"{CONFIG.worker.value}-{worker}"),
                lease_seconds=CONFIG.lease_seconds,
            )
            return None if lease is None else lease.run_id

    with ThreadPoolExecutor(max_workers=2) as pool:
        claimed = list(pool.map(poll, range(2)))

    assert None not in claimed, "a worker idled while there was work for it"
    assert set(claimed) == queued, "the two workers did not take one run each"

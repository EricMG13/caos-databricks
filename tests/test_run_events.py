"""Phase 1 exit test: a crash in the commit gap yields one of everything.

Invariant 6 (CLAUDE.md): execution is durable and exactly-once. `SYSTEM_SPEC.md`
section 2 says how -- a run-state transition commits its state and its event in
one transaction, every event insert rides a conditional update whose zero rows
mean no event, and `run_events.seq` is allocated under the run row lock.

The commit gap is the window between the work being done and the transaction
that records it landing. A process can die on either side of the commit and must
not be able to tell the difference afterwards: replaying the same completion
must leave one artifact, one charge and one terminal event, never two.
"""

from __future__ import annotations

from collections.abc import Iterator
from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid4

import psycopg
import pytest
from canonical_fixtures import CATALOG, LITE_PROFILE, LITE_SELECTION
from conftest import _checked_values, approve_run
from psycopg.pq import TransactionStatus
from run_terminals import fail_run
from test_loop_charges import VENDORED

from caos.blobs import BlobStore
from caos.boundary_text import BoundaryText
from caos.evidence.ingest import Document, admit_pack
from caos.graph.route import ResolvedRoute, resolve_route
from caos.methodology.bundle import Bundle
from caos.refusals import Refusal, RefusalCode
from caos.store import RunStatus, StoreConnection, apply_schema, connect
from caos.store.events import Event, RunEvent, events_of, lock_run
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

# The producer the store records beside every accepted artifact: what the
# host configured, and the provider's own handle for the call.
MODEL = "a-model/for-the-test"
GENERATION = "gen-for-the-test"

ARTIFACT = "b" * 64
# Every accepted artifact carries its host record (§42.1).
RECORD = "c" * 64
CHARGE = Decimal("0.0142")


@pytest.fixture
def run(empty_database: str) -> Iterator[tuple[StoreConnection, UUID, UUID]]:
    """A case and a RUNNING run on a committed connection."""
    with connect(empty_database) as conn:
        apply_schema(conn)
        case_id = create_case(conn, BoundaryText.of("Acme 2026 refinancing"))
        run_id = start_run(conn, case_id)
        conn.commit()
        yield conn, case_id, run_id


def approved_nodes(
    conn: StoreConnection,
    run_id: UUID,
    blobs: Path,
    bundle: Bundle | None = None,
    route: ResolvedRoute | None = None,
) -> dict[str, str]:
    """Admit evidence, then pin and govern this run on the canonical LITE route
    (acceptance refuses any other, §42.2); acceptance checks that authority at
    the store boundary."""
    row = conn.execute(
        "SELECT case_id FROM runs WHERE run_id = %s", (run_id,)
    ).fetchone()
    assert row is not None
    case_id = row[0]
    admit_pack(
        conn,
        BlobStore(blobs),
        case_id=case_id,
        documents=[Document(filename=BoundaryText.of("pack.txt"), data=b"Pack.\n")],
    )
    route = route or resolve_route(CATALOG, LITE_PROFILE, LITE_SELECTION)
    approve_run(
        conn,
        case_id=case_id,
        run_id=run_id,
        route=route,
        bundle=bundle or Bundle(VENDORED),
    )
    return {node.module_id: node.route_node_id for node in route.nodes}


def _accepted() -> Accepted:
    return Accepted(
        artifact_sha256=ARTIFACT,
        charge=CHARGE,
        model=MODEL,
        generation_id=GENERATION,
        record_sha256=RECORD,
    )


def accept_nodes(conn: StoreConnection, run_id: UUID, *node_ids: str) -> None:
    """Start and accept one attempt per named node: what completion now needs
    of every other pinned node (brief 4.3 D8)."""
    for node_id in node_ids:
        attempt_id = start_attempt(conn, run_id, node_id)
        assert accept_attempt(conn, attempt_id=attempt_id, accepted=_accepted())


def _names(conn: StoreConnection, run_id: UUID) -> list[str]:
    return [event.name for event in events_of(conn, run_id)]


def _count(conn: StoreConnection, table: str, run_id: UUID) -> int:
    row = conn.execute(
        # `table` is a literal from this module, never caller input.
        f"SELECT count(*) FROM {table} WHERE run_id = %s",
        (run_id,),
    ).fetchone()
    assert row is not None
    return int(row[0])


def test_terminal_event_is_exactly_once(
    run: tuple[StoreConnection, UUID, UUID], empty_database: str, tmp_path: Path
) -> None:
    """The Phase 1 exit test.

    The completion commits. The process then dies before it learns that it did,
    which is indistinguishable from the commit never happening -- so recovery
    replays it. One artifact, one charge, one terminal event.
    """
    conn, _case_id, run_id = run
    nodes = approved_nodes(conn, run_id, tmp_path)
    # Completion needs every other pinned node accepted (brief 4.3 D8).
    accept_nodes(conn, run_id, nodes["CP-0"], nodes["CP-5"])
    attempt_id = start_attempt(conn, run_id, nodes["CP-L10"])
    conn.commit()

    completed = complete_attempt(
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
    assert completed is True

    # The crash: the caller never saw the commit, so recovery does it again.
    replayed = complete_attempt(
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

    assert replayed is False, "the replay must not claim to have completed the run"
    # One of each per node is the whole test. Stated as a count rather than only
    # as a list, so a later phase adding an event cannot weaken it by editing
    # the list -- which is exactly what Phase 4 did when ATTEMPT_ACCEPTED arrived.
    assert _count(conn, "artifacts", run_id) == len(nodes)
    assert _count(conn, "budget_ledger", run_id) == len(nodes)
    names = _names(conn, run_id)
    assert names.count(RunEvent.RUN_COMPLETE.value) == 1
    assert names.count(RunEvent.CALL_OUTCOME_RECORDED.value) == len(nodes)
    assert names.count(RunEvent.ATTEMPT_ACCEPTED.value) == len(nodes)
    assert names == [
        RunEvent.ROUTE_PINNED.value,
        RunEvent.INPUT_PINNED.value,
        *[
            RunEvent.ATTEMPT_STARTED.value,
            RunEvent.CALL_OUTCOME_RECORDED.value,
            RunEvent.ATTEMPT_ACCEPTED.value,
        ]
        * len(nodes),
        RunEvent.RUN_COMPLETE.value,
    ]
    assert run_status(conn, run_id) is RunStatus.COMPLETE


def test_a_crash_before_the_commit_leaves_no_event_and_no_charge(
    run: tuple[StoreConnection, UUID, UUID], empty_database: str, tmp_path: Path
) -> None:
    """The other side of the gap. The work happened; the transaction did not.

    The uncommitted analytical write leaves nothing. A committed independent
    outcome would retain its bill even if the process died before acceptance.
    """
    conn, case_id, run_id = run
    nodes = approved_nodes(conn, run_id, tmp_path)
    attempt_id = start_attempt(conn, run_id, nodes["CP-L10"])
    conn.commit()

    with connect(empty_database) as dying:
        dying.execute(
            "INSERT INTO artifacts (attempt_id, artifact_sha256, run_id, case_id,"
            " model, generation_id)"
            " VALUES (%s, %s, %s, %s, %s, %s)",
            (attempt_id, ARTIFACT, run_id, case_id, MODEL, GENERATION),
        )
        dying.close()  # the process dies here, mid-transaction

    assert _count(conn, "artifacts", run_id) == 0
    assert _count(conn, "budget_ledger", run_id) == 0
    assert _names(conn, run_id) == [
        RunEvent.ROUTE_PINNED.value,
        RunEvent.INPUT_PINNED.value,
        RunEvent.ATTEMPT_STARTED.value,
    ]

    # Accepting, not completing: the other pinned nodes are unaccepted (D8).
    assert accept_attempt(conn, attempt_id=attempt_id, accepted=_accepted()) is True
    assert _count(conn, "artifacts", run_id) == 1
    assert _count(conn, "budget_ledger", run_id) == 1


def test_locking_a_run_that_does_not_exist_is_refused(
    run: tuple[StoreConnection, UUID, UUID],
) -> None:
    """`lock_run` is where every ordering guarantee starts, so it is also where
    an unknown run stops -- before a caller can append to a stream that has no
    run behind it."""
    conn, _case_id, _run_id = run

    with pytest.raises(Refusal) as caught:
        lock_run(conn, uuid4())

    assert caught.value.code is RefusalCode.RUN_NOT_FOUND


def test_run_status_of_an_unknown_run_is_refused(
    run: tuple[StoreConnection, UUID, UUID],
) -> None:
    """The same refusal an unauthorised run gets, so that neither answer tells a
    caller the other one exists."""
    conn, _case_id, _run_id = run

    with pytest.raises(Refusal) as caught:
        run_status(conn, uuid4())

    assert caught.value.code is RefusalCode.RUN_NOT_FOUND


def test_an_event_carries_its_position_name_and_an_aware_time(
    run: tuple[StoreConnection, UUID, UUID],
) -> None:
    conn, _case_id, run_id = run
    start_attempt(conn, run_id, "CP-1")

    [event] = events_of(conn, run_id)

    assert isinstance(event, Event)
    assert (event.seq, event.name) == (1, RunEvent.ATTEMPT_STARTED.value)
    # timestamptz, never a naive local time: an event stream that cannot be
    # ordered across a deployment's timezone is not an audit trail.
    assert event.at.tzinfo is not None


def test_events_of_a_run_are_numbered_from_one_without_gaps(
    run: tuple[StoreConnection, UUID, UUID], tmp_path: Path
) -> None:
    conn, _case_id, run_id = run
    nodes = approved_nodes(conn, run_id, tmp_path)
    start_attempt(conn, run_id, nodes["CP-0"])
    attempt_id = start_attempt(conn, run_id, nodes["CP-L10"])
    accept_attempt(conn, attempt_id=attempt_id, accepted=_accepted())
    fail_run(conn, run_id)

    # Route and input pinned, CP-0 started, CP-L10 started, outcome recorded,
    # CP-L10 accepted, run failed.
    assert [event.seq for event in events_of(conn, run_id)] == [1, 2, 3, 4, 5, 6, 7]


def test_accept_attempt_records_the_artifact_without_ending_the_run(
    run: tuple[StoreConnection, UUID, UUID], tmp_path: Path
) -> None:
    """A route has many nodes and only the last one ends the run. Accepting is
    therefore its own operation, and a replay of it appends no second event."""
    conn, _case_id, run_id = run
    attempt_id = start_attempt(
        conn, run_id, approved_nodes(conn, run_id, tmp_path)["CP-L10"]
    )

    assert (
        accept_attempt(
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
        is True
    )
    assert run_status(conn, run_id) is RunStatus.RUNNING

    assert (
        accept_attempt(
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
        is False
    ), "the replay accepted nothing new"
    assert _count(conn, "artifacts", run_id) == 1
    assert _count(conn, "budget_ledger", run_id) == 1
    assert _names(conn, run_id).count(RunEvent.ATTEMPT_ACCEPTED.value) == 1


def test_complete_run_ends_a_run_once(
    run: tuple[StoreConnection, UUID, UUID], tmp_path: Path
) -> None:
    conn, _case_id, run_id = run
    accept_nodes(conn, run_id, *approved_nodes(conn, run_id, tmp_path).values())
    before = _names(conn, run_id)

    assert complete_run(conn, run_id) is True
    assert complete_run(conn, run_id) is False

    assert _names(conn, run_id) == [*before, RunEvent.RUN_COMPLETE.value]
    assert run_status(conn, run_id) is RunStatus.COMPLETE


def test_store_refuses_complete_with_an_unaccepted_pinned_node(
    run: tuple[StoreConnection, UUID, UUID], tmp_path: Path
) -> None:
    """D8: COMPLETE is decided under the run lock, from the pinned route, not
    trusted from a caller's snapshot. No status, no event, until every pinned
    node owns an accepted artifact."""
    conn, _case_id, run_id = run
    nodes = approved_nodes(conn, run_id, tmp_path)
    accept_nodes(conn, run_id, nodes["CP-0"])
    before = _names(conn, run_id)

    with pytest.raises(Refusal) as caught:
        complete_run(conn, run_id)
    assert caught.value.code is RefusalCode.RUN_NODES_UNACCEPTED

    attempt_id = start_attempt(conn, run_id, nodes["CP-L10"])
    with pytest.raises(Refusal) as caught:
        complete_attempt(conn, attempt_id=attempt_id, accepted=_accepted())
    assert caught.value.code is RefusalCode.RUN_NODES_UNACCEPTED
    assert _count(conn, "artifacts", run_id) == 2, "the acceptance still stands"
    assert run_status(conn, run_id) is RunStatus.RUNNING
    assert RunEvent.RUN_COMPLETE.value not in _names(conn, run_id)
    assert len(_names(conn, run_id)) == len(before) + 3

    accept_nodes(conn, run_id, nodes["CP-5"])
    assert complete_run(conn, run_id) is True
    assert run_status(conn, run_id) is RunStatus.COMPLETE


def test_a_terminal_snapshot_moved_under_the_lock_refuses_stale(
    run: tuple[StoreConnection, UUID, UUID], tmp_path: Path
) -> None:
    """D8: a decision taken from a snapshot is refused when the accepted set
    re-read under `lock_run` differs from it, for BLOCKED and COMPLETE alike."""
    conn, _case_id, run_id = run
    nodes = approved_nodes(conn, run_id, tmp_path)
    accept_nodes(conn, run_id, nodes["CP-0"])
    decided = frozenset({nodes["CP-0"]})
    accept_nodes(conn, run_id, nodes["CP-L10"])  # moves after the decision
    before = _names(conn, run_id)

    for end in (block_run, complete_run):
        with pytest.raises(Refusal) as caught:
            end(conn, run_id, accepted=decided)
        assert caught.value.code is RefusalCode.RUN_TERMINAL_STALE
        assert run_status(conn, run_id) is RunStatus.RUNNING
        assert _names(conn, run_id) == before

    accept_nodes(conn, run_id, nodes["CP-5"])
    everything = frozenset(nodes.values())
    with pytest.raises(Refusal) as caught:
        block_run(conn, run_id, accepted=decided | {nodes["CP-L10"]})
    assert caught.value.code is RefusalCode.RUN_TERMINAL_STALE
    assert complete_run(conn, run_id, accepted=everything) is True
    assert _names(conn, run_id) == [
        *before,
        RunEvent.ATTEMPT_STARTED.value,
        RunEvent.CALL_OUTCOME_RECORDED.value,
        RunEvent.ATTEMPT_ACCEPTED.value,
        RunEvent.RUN_COMPLETE.value,
    ]


def test_a_transition_that_changed_nothing_appends_no_event(
    run: tuple[StoreConnection, UUID, UUID],
) -> None:
    """The conditional-update rule, on a run that is already terminal.

    A completion arriving for a failed run is not a completion. Zero rows
    updated, no event -- otherwise a run carries two terminal events and the
    stream that closes on one of them closes twice.
    """
    conn, _case_id, run_id = run
    attempt_id = start_attempt(conn, run_id, "CP-1")
    assert fail_run(conn, run_id) is True

    completed = complete_attempt(
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

    assert completed is False
    assert _count(conn, "budget_ledger", run_id) == 1
    assert _names(conn, run_id) == [
        RunEvent.ATTEMPT_STARTED.value,
        RunEvent.RUN_FAILED.value,
        RunEvent.CALL_OUTCOME_RECORDED.value,
    ], "a terminal run accepts nothing, so there is no ATTEMPT_ACCEPTED"
    assert run_status(conn, run_id) is RunStatus.FAILED
    # And it accepted nothing on the way past. A failed run holding an accepted
    # artifact is a node Phase 3 would recompute as COMPLETE.
    assert _count(conn, "artifacts", run_id) == 0


def test_failing_a_run_twice_appends_one_event(
    run: tuple[StoreConnection, UUID, UUID],
) -> None:
    conn, _case_id, run_id = run

    assert fail_run(conn, run_id) is True
    assert fail_run(conn, run_id) is False

    assert _names(conn, run_id) == [RunEvent.RUN_FAILED.value]


def test_an_attempt_cannot_start_on_a_run_that_has_ended(
    run: tuple[StoreConnection, UUID, UUID],
) -> None:
    """A terminal run is terminal. An attempt started after it would be work
    nothing can accept and a charge nothing can reconcile."""
    conn, _case_id, run_id = run
    fail_run(conn, run_id)

    with pytest.raises(Refusal) as caught:
        start_attempt(conn, run_id, "CP-1")

    assert caught.value.code is RefusalCode.RUN_NOT_RUNNING
    assert _names(conn, run_id) == [RunEvent.RUN_FAILED.value]


def test_start_run_refuses_a_float_ceiling(
    run: tuple[StoreConnection, UUID, UUID],
) -> None:
    """Invariant 7 on the ceiling itself: a run carrying a float ceiling would
    give invariant 8's checks a number they cannot trust."""
    conn, case_id, _run_id = run

    with pytest.raises(Refusal) as caught:
        start_run(conn, case_id, budget_ceiling=0.5)  # type: ignore[arg-type]

    assert caught.value.code is RefusalCode.MONEY_NOT_DECIMAL


def test_a_float_charge_is_refused_before_it_reaches_the_ledger(
    run: tuple[StoreConnection, UUID, UUID],
) -> None:
    """Invariant 7: Decimal, never float, on any money path. Binary floating
    point cannot represent a cent, and a charge is what a run is billed."""
    conn, _case_id, run_id = run
    attempt_id = start_attempt(conn, run_id, "CP-1")

    with pytest.raises(Refusal) as caught:
        complete_attempt(
            conn,
            attempt_id=attempt_id,
            accepted=Accepted(
                artifact_sha256=ARTIFACT,
                charge=0.0142,  # type: ignore[arg-type]
                model=MODEL,
                generation_id=GENERATION,
                record_sha256=RECORD,
            ),
        )

    assert caught.value.code is RefusalCode.MONEY_NOT_DECIMAL
    assert _count(conn, "budget_ledger", run_id) == 0


def test_the_charge_survives_as_the_decimal_it_was_given(
    run: tuple[StoreConnection, UUID, UUID], tmp_path: Path
) -> None:
    conn, _case_id, run_id = run
    attempt_id = start_attempt(
        conn, run_id, approved_nodes(conn, run_id, tmp_path)["CP-L10"]
    )
    accept_attempt(conn, attempt_id=attempt_id, accepted=_accepted())

    row = conn.execute(
        "SELECT amount FROM budget_ledger WHERE run_id = %s", (run_id,)
    ).fetchone()

    assert row is not None
    assert row[0] == CHARGE
    assert isinstance(row[0], Decimal)


def test_every_run_event_is_one_the_database_accepts(
    run: tuple[StoreConnection, UUID, UUID],
) -> None:
    """`RunEvent` and the `run_events_name_is_known` CHECK are one closed set,
    checked in both directions (CF-106): the INSERT loop below only catches a
    Python event the database refuses, not a name the CHECK still accepts
    after `RunEvent` dropped it."""
    conn, _case_id, run_id = run
    assert _checked_values(conn, "run_events", "run_events_name_is_known") == {
        event.value for event in RunEvent
    }

    for index, event in enumerate(RunEvent, start=1):
        conn.execute(
            "INSERT INTO run_events (run_id, seq, name) VALUES (%s, %s, %s)",
            (run_id, index, event.value),
        )
    conn.commit()


def test_an_unknown_attempt_cannot_complete_a_run(
    run: tuple[StoreConnection, UUID, UUID],
) -> None:
    """A completion names the attempt it is completing. One that never started
    has no reservation behind it, so it may not charge or transition."""
    conn, _case_id, run_id = run

    with pytest.raises(Refusal) as caught:
        complete_attempt(
            conn,
            attempt_id=uuid4(),
            accepted=Accepted(
                artifact_sha256=ARTIFACT,
                charge=CHARGE,
                model=MODEL,
                generation_id=GENERATION,
                record_sha256=RECORD,
            ),
        )

    assert caught.value.code is RefusalCode.ATTEMPT_NOT_FOUND
    assert run_status(conn, run_id) is RunStatus.RUNNING
    assert _names(conn, run_id) == []


def test_start_attempt_turns_a_store_fault_into_a_typed_refusal(
    run: tuple[StoreConnection, UUID, UUID], monkeypatch: pytest.MonkeyPatch
) -> None:
    """W4: a driver error on the attempt insert must not cross the boundary as
    itself. `accept_attempt` already types its faults; the row that identifies
    the work has to type its own, or a worker sees a psycopg class where every
    other path hands it a code."""
    conn, _case_id, run_id = run
    real = conn.execute

    def failing(query: object, *args: object, **kwargs: object) -> object:
        if isinstance(query, str) and "INSERT INTO run_attempts" in query:
            raise psycopg.OperationalError("simulated")
        return real(query, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(conn, "execute", failing)

    with pytest.raises(Refusal) as caught:
        start_attempt(conn, run_id, "CP-0")

    assert caught.value.code is RefusalCode.STORE_UNAVAILABLE
    assert caught.value.__cause__ is None


def test_lock_run_leaves_no_lock_behind_on_a_missing_run(
    case: tuple[StoreConnection, UUID], empty_database: str
) -> None:
    """`RUN_NOT_FOUND` raised with the unit open holds `runs` open with it.

    The first statement opens the caller's transaction and takes an
    `ACCESS SHARE` on `runs`, and the refusal is raised before anything ends
    it -- so a caller that answered the 404 and went on serving kept that lock
    for the rest of its request, and a migration or any other exclusive writer
    on `runs` waited behind a run that does not exist. The probe is what such a
    writer would meet: `NOWAIT` turns the wait into an error this test can see.
    """
    conn, _case_id = case

    with pytest.raises(Refusal) as caught:
        lock_run(conn, uuid4())

    assert caught.value.code is RefusalCode.RUN_NOT_FOUND
    assert conn.info.transaction_status is TransactionStatus.IDLE
    with connect(empty_database) as probe:
        probe.execute("LOCK TABLE runs IN ACCESS EXCLUSIVE MODE NOWAIT")
        probe.rollback()


def test_lock_run_also_ends_its_transaction_when_the_row_is_gone_under_for_update(
    run: tuple[StoreConnection, UUID, UUID], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The owner lookup and the `FOR UPDATE` row lock are two statements. This
    run exists at the first and is gone -- deleted here right after it, standing
    in for a concurrent writer -- by the second, which is the other branch that
    used to leave `runs` locked behind a `RUN_NOT_FOUND` it raised."""
    conn, _case_id, run_id = run
    real_execute = conn.execute

    def vanish(query: object, *args: object, **kwargs: object) -> object:
        result = real_execute(query, *args, **kwargs)  # type: ignore[arg-type]
        if isinstance(query, str) and "case_id FROM runs" in query:
            real_execute("DELETE FROM runs WHERE run_id = %s", (run_id,))
        return result

    monkeypatch.setattr(conn, "execute", vanish)

    with pytest.raises(Refusal) as caught:
        lock_run(conn, run_id)

    assert caught.value.code is RefusalCode.RUN_NOT_FOUND
    assert conn.info.transaction_status is TransactionStatus.IDLE

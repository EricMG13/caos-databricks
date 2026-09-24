"""Completion Phase 13.3: a stalled queue is visible, not only in a log.

The ledger entry this closes: "The worker has no readiness. The API's
`/api/health` probes the store, bundle and blob root it uses;
`caos/graph/worker.py` serves no listener, and `compose.smoke.yaml` gives
the worker no healthcheck. A worker that exited 2 (`PROVIDER_NOT_CONFIGURED`)
or is backing off on store faults is visible only in its exit code and logs,
and a queued run simply waits."

Two things are deliberately *not* done. The worker still serves no listener --
a process that already talks to PostgreSQL every poll does not need a second
protocol to say it is alive. And a missing worker does **not** make the API
`not_ready`: the API is not the worker, and an API that reported itself unready
because a queue was stalled would take the surface down with it. The worker's
state is its own field, which is what an operator alerts on.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import psycopg
import pytest

from caos.api.deps import DATABASE_URL
from caos.api.health import probe_workers
from caos.store import StoreConnection, apply_schema, connect
from caos.store.work import (
    WORKER_STALE_AFTER,
    WorkerBeat,
    beat,
    worker_states,
)


@pytest.fixture
def migrated(empty_database: str) -> Iterator[StoreConnection]:
    """A migrated store. `empty_database` is deliberately unmigrated -- it
    answers what a process finds before any schema is applied -- and a
    heartbeat needs its table."""
    with connect(empty_database) as conn:
        apply_schema(conn)
        conn.commit()
        yield conn


def test_a_beat_is_one_row_per_worker_however_often_it_beats(
    migrated: StoreConnection,
) -> None:
    """A heartbeat is the one deliberately mutable row in this store: it
    records *now*, not a history. Upserting keeps the table the size of the
    fleet rather than the size of the uptime -- `command_requests` already
    grows without bound by design, to replay idempotent retries, and nothing
    wants a second such table."""
    for _ in range(3):
        beat(migrated, worker_id="worker-a", state="POLLING", faults=0)
    beat(migrated, worker_id="worker-b", state="WORKING", faults=0)
    migrated.commit()

    assert sorted(s.worker_id for s in worker_states(migrated)) == [
        "worker-a",
        "worker-b",
    ]


def test_a_beat_records_the_state_an_operator_has_to_act_on(
    migrated: StoreConnection,
) -> None:
    """`BACKOFF` with a fault count is the case the entry names: a worker that
    is running, polling, and getting nowhere. It has to be distinguishable from
    one that is merely idle, because an idle queue and a stalled one look
    identical from outside."""
    beat(migrated, worker_id="worker-a", state="BACKOFF", faults=7)
    migrated.commit()

    [state] = worker_states(migrated)

    assert isinstance(state, WorkerBeat)
    assert (state.state, state.consecutive_faults, state.fresh) == ("BACKOFF", 7, True)
    # The beat's own time, not the reader's: a worker with a skewed clock would
    # otherwise read as permanently fresh or permanently stale, so `beat_at` is
    # the store's `now()` and is carried out for an operator to read.
    assert state.beat_at.tzinfo is not None


def test_a_worker_that_stopped_beating_reads_as_stale_rather_than_absent(
    migrated: StoreConnection,
) -> None:
    """A worker that exited leaves its last beat behind, and that row is more
    use than no row: "worker-a last spoke nine minutes ago, in BACKOFF" names
    the process to go and look at, where an empty table only says nobody is
    working."""
    beat(migrated, worker_id="worker-a", state="BACKOFF", faults=3)
    migrated.execute(
        "UPDATE worker_heartbeats SET beat_at = %s WHERE worker_id = %s",
        (datetime.now(UTC) - timedelta(seconds=WORKER_STALE_AFTER + 1), "worker-a"),
    )
    migrated.commit()

    [state] = worker_states(migrated)

    assert state.fresh is False
    assert (state.worker_id, state.state) == ("worker-a", "BACKOFF")


def test_the_staleness_threshold_covers_one_whole_provider_call() -> None:
    """AR-24. A worker beats once per node and never during the node's model
    call, so a threshold shorter than one call calls a healthy worker stale for
    doing the one thing it exists to do -- while the run's lease, the real
    liveness, stays held. The floor is the longest call the host supports plus
    a minute of margin, and it is asserted rather than remembered so that
    raising the provider deadline cannot silently uncover it again.
    """
    from caos.provider import TIMEOUT_SECONDS

    assert WORKER_STALE_AFTER >= TIMEOUT_SECONDS + 60.0


def test_a_beat_refuses_a_state_the_worker_does_not_have(
    migrated: StoreConnection,
) -> None:
    """The three states are a closed set in the store, not a free-text column:
    an operator alerting on `BACKOFF` must be able to trust that nothing writes
    a different word meaning the same thing."""
    with pytest.raises(psycopg.errors.CheckViolation):
        beat(migrated, worker_id="worker-a", state="MOSTLY_FINE", faults=0)  # type: ignore[arg-type]
    migrated.rollback()


def test_a_beat_is_visible_to_another_connection_once_committed(
    migrated: StoreConnection, empty_database: str
) -> None:
    """The beat is an ordinary committed write, so `/api/health` -- a different
    process on a different connection -- reads it. Without this the tests above
    would all pass against a beat only its own writer can see."""
    beat(migrated, worker_id="worker-a", state="POLLING", faults=0)
    migrated.commit()

    with connect(empty_database) as observer:
        assert [s.worker_id for s in worker_states(observer)] == ["worker-a"]


def test_the_health_probe_reads_the_three_states_a_person_acts_on(
    migrated: StoreConnection, empty_database: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The probe over a real store rather than a substituted callable, because
    what the entry promises an operator is that `/api/health` reflects what the
    fleet actually wrote.

    Each answer means a different action: nothing has ever beaten, so a queued
    run will wait; a worker beat and stopped, so go and look at that process;
    or every fresh worker is failing to reach the store, which is the case the
    entry names and the one that used to be visible in nothing but a log.
    """
    monkeypatch.setenv(DATABASE_URL, empty_database)
    assert probe_workers() == "WORKERS_ABSENT"

    beat(migrated, worker_id="worker-a", state="BACKOFF", faults=4)
    migrated.commit()
    assert probe_workers() == "WORKERS_BACKING_OFF"

    # One healthy worker beside it is a fleet that is working.
    beat(migrated, worker_id="worker-b", state="WORKING", faults=0)
    migrated.commit()
    assert probe_workers() == "OK"

    migrated.execute(
        "UPDATE worker_heartbeats SET beat_at = %s",
        (datetime.now(UTC) - timedelta(seconds=WORKER_STALE_AFTER + 1),),
    )
    migrated.commit()
    assert probe_workers() == "WORKERS_STALE"

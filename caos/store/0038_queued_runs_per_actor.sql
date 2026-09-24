-- N15 (D39, owner-approved 2026-09-23): who holds a run's place in the queue.
-- `caos.store.work` counts one actor's QUEUED and CLAIMED rows against
-- `MAX_QUEUED_RUNS_PER_ACTOR` before it queues another for them (Start) or
-- puts a stopped one back (Retry). NULL is a place nobody holds: a row queued
-- before this migration, by a direct caller, or by Cancel only to end its run
-- in the same unit. Nothing is backfilled.
ALTER TABLE run_work ADD COLUMN requested_by uuid;
CREATE INDEX run_work_queued_by ON run_work (requested_by)
    WHERE state IN ('QUEUED', 'CLAIMED');

-- The one deliberately mutable row in this store, and the reason is stated
-- rather than assumed: a heartbeat records *now*, not a history. Every other
-- table here is immutable by trigger because it carries a governed fact that
-- somebody may later be held to; a beat is an observation with a shelf life of
-- seconds, and keeping every one of them would grow a table by one row per
-- worker per poll forever -- the shape `command_requests` already carries a
-- known-gaps entry for. So this table is the size of the fleet, not of the
-- uptime, and no trigger defends it.
--
-- It grants nothing. Nothing reads it to decide whether work may proceed: the
-- lease in `run_work` is what fences a run, and a worker that lies here still
-- cannot write a run it does not hold. It exists so that a stalled queue is
-- visible to an operator, which is the whole of the ledger entry it closes.
CREATE TABLE worker_heartbeats (
    worker_id          text        PRIMARY KEY
                                   CHECK (length(worker_id) BETWEEN 1 AND 64),
    beat_at            timestamptz NOT NULL,
    -- A closed set, so that alerting on BACKOFF can trust that nothing else
    -- ever writes a different word meaning the same thing.
    state              text        NOT NULL
                                   CHECK (state IN ('POLLING', 'WORKING', 'BACKOFF')),
    consecutive_faults integer     NOT NULL CHECK (consecutive_faults >= 0)
);

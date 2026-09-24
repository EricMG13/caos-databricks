-- N37: a standalone worker's graceful shutdown records STOPPED, a word
-- distinct from POLLING, WORKING or BACKOFF, so a fleet read can tell a
-- worker that stopped on purpose from one whose last beat merely went stale
-- (`worker_heartbeats` keeps only the latest word per worker on purpose --
-- see 0028's own comment -- so this is the same mutable row, one more word
-- in its closed set).
ALTER TABLE worker_heartbeats DROP CONSTRAINT worker_heartbeats_state_check;
ALTER TABLE worker_heartbeats ADD CONSTRAINT worker_heartbeats_state_check
    CHECK (state IN ('POLLING', 'WORKING', 'BACKOFF', 'STOPPED'));

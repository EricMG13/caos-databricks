-- Phase 4 Task 4.3 (brief D2): one work row per enqueued run. The token, not
-- the clock, is the fence: every claim advances it, and a write guarded by an
-- older token refuses. A run with no row is still driven by a direct caller.
CREATE TABLE run_work (
    run_id uuid PRIMARY KEY REFERENCES runs (run_id),
    state text NOT NULL CHECK (state IN ('QUEUED', 'CLAIMED', 'STOPPED', 'DONE')),
    lease_token bigint NOT NULL DEFAULT 0 CHECK (lease_token >= 0),
    worker text CHECK (octet_length(worker) <= 128),
    lease_expires_at timestamptz,
    requested_at timestamptz NOT NULL DEFAULT now(),
    cancel_requested_at timestamptz,
    stop_code text CHECK (stop_code ~ '^[A-Z][A-Z0-9_]{0,63}$'),
    CHECK ((state = 'CLAIMED') = (lease_expires_at IS NOT NULL AND worker IS NOT NULL)),
    CHECK ((state = 'STOPPED') = (stop_code IS NOT NULL))
);
CREATE INDEX run_work_claimable ON run_work (requested_at, run_id)
    WHERE state IN ('QUEUED', 'CLAIMED');

-- The token an attempt was started under. Attempts before 0013 keep NULL.
ALTER TABLE run_attempts ADD COLUMN lease_token bigint;

-- A billed answer the host explained rather than accepted, written once. Codes
-- are checked by shape, so a new code needs no migration; a store fault is
-- never an explanation of an answer.
CREATE TABLE attempt_refusals (
    attempt_id uuid PRIMARY KEY REFERENCES run_attempts (attempt_id),
    code text NOT NULL CHECK (code ~ '^[A-Z][A-Z0-9_]{0,63}$' AND code !~ '^STORE_'),
    recorded_at timestamptz NOT NULL DEFAULT now()
);
CREATE FUNCTION refuse_refusal_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'attempt refusals are immutable';
END;
$$;
CREATE TRIGGER refusal_immutable BEFORE UPDATE OR DELETE ON attempt_refusals
    FOR EACH ROW EXECUTE FUNCTION refuse_refusal_mutation();
CREATE TRIGGER refusal_no_truncate BEFORE TRUNCATE ON attempt_refusals
    FOR EACH STATEMENT EXECUTE FUNCTION refuse_refusal_mutation();

ALTER TABLE runs DROP CONSTRAINT runs_status_is_known;
ALTER TABLE runs ADD CONSTRAINT runs_status_is_known
    CHECK (status IN ('RUNNING', 'COMPLETE', 'FAILED', 'BLOCKED', 'CANCELLED'));
ALTER TABLE run_events DROP CONSTRAINT run_events_name_is_known;
ALTER TABLE run_events ADD CONSTRAINT run_events_name_is_known CHECK (
    name IN ('ROUTE_PINNED', 'INPUT_PINNED', 'ATTEMPT_STARTED', 'CALL_OUTCOME_RECORDED',
             'ATTEMPT_ACCEPTED', 'RUN_COMPLETE', 'RUN_FAILED', 'RUN_BLOCKED',
             'RUN_CANCELLED')
);

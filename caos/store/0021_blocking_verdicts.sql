-- The answer whose validated Blocked verdict ended a run, recorded by the
-- transition that acted on it, in the transaction that ended the run (§68).
--
-- Written and not re-derived, because it cannot be re-derived later: the
-- verdict sits in an unaccepted attempt's stored body, and `replay_billed`
-- judges that body through `check_attempt`, which refuses once the run is no
-- longer RUNNING. What ended the run is a fact about the moment it ended, the
-- same kind of fact as `runs.status`, and it is recorded beside it.
--
-- At most one per run, and only an attempt of that run: the primary key holds
-- the first, `block_run` refuses `ATTEMPT_NOT_FOUND` for an attempt the run
-- did not make. A run the frontier emptied (§39) has no row -- no node's
-- verdict ended it, and the wire must not claim one did.
CREATE TABLE run_blocking_verdicts (
    run_id      uuid PRIMARY KEY REFERENCES runs (run_id),
    attempt_id  uuid NOT NULL UNIQUE REFERENCES run_attempts (attempt_id),
    recorded_at timestamptz NOT NULL DEFAULT now()
);
CREATE FUNCTION refuse_blocking_verdict_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'blocking verdicts are immutable';
END;
$$;
CREATE TRIGGER blocking_verdict_immutable BEFORE UPDATE OR DELETE ON run_blocking_verdicts
    FOR EACH ROW EXECUTE FUNCTION refuse_blocking_verdict_mutation();
CREATE TRIGGER blocking_verdict_no_truncate BEFORE TRUNCATE ON run_blocking_verdicts
    FOR EACH STATEMENT EXECUTE FUNCTION refuse_blocking_verdict_mutation();

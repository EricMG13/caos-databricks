-- CF-091, the trigger half of N16 (MX-6): `budget_reservations` and
-- `run_events` -- read with `caos/store/budget.py` and `events.py`'s own
-- queries first, the way every earlier immutability migration here did --
-- are inserted into and never updated, deleted or truncated anywhere in the
-- app, with no trigger of their own refusing what the app never sends.
-- Until now a privileged session (or a bug) could rewrite a budget
-- reservation or a run event with nothing in the schema to stop it;
-- `0007_call_outcomes.sql`'s `refuse_call_mutation` is the same shape,
-- reused here as one function across both tables via `TG_TABLE_NAME`, which
-- names whichever of them the change was refused on.
--
-- `run_attempts` and `artifacts` are written the same way (insert-only) but
-- are deliberately left out of this migration: the test suite reaches into
-- both directly, by design, to simulate a stored row corrupted after the
-- fact -- proving the *application's* verification catches what the
-- database no longer prevents (`tests/test_canonical_proof.py`,
-- `test_deliverable_canonical.py`, `test_qualification_matrix.py` and
-- others). Guarding them the same way this migration guards the other two
-- would need each of those call sites rewritten to disable the trigger
-- first, the way `tests/test_execution_input.py`'s `fault == "input"` case
-- already does for `run_inputs`; that is a broader, judgment-laden sweep
-- than this fix, and is left for the owner to decide (N16).
CREATE FUNCTION refuse_governed_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION '% rows are immutable', TG_TABLE_NAME;
END;
$$;

CREATE TRIGGER reservation_immutable BEFORE UPDATE OR DELETE ON budget_reservations
    FOR EACH ROW EXECUTE FUNCTION refuse_governed_mutation();
CREATE TRIGGER reservation_no_truncate BEFORE TRUNCATE ON budget_reservations
    FOR EACH STATEMENT EXECUTE FUNCTION refuse_governed_mutation();

CREATE TRIGGER run_event_immutable BEFORE UPDATE OR DELETE ON run_events
    FOR EACH ROW EXECUTE FUNCTION refuse_governed_mutation();
CREATE TRIGGER run_event_no_truncate BEFORE TRUNCATE ON run_events
    FOR EACH STATEMENT EXECUTE FUNCTION refuse_governed_mutation();

-- The other half of CF-091: `runs.status` moves exactly once, RUNNING to one
-- of the four terminal statuses (`caos.store.runs._transition`, `work.py`'s
-- `_end_cancelled` -- both conditioned on `WHERE status = 'RUNNING'` already,
-- so this is the schema saying what the app's own writes already assume:
-- BLOCKED, COMPLETE, FAILED and CANCELLED never move again, not even back to
-- RUNNING (`0025_supersedes.sql`'s own comment: a BLOCKED run's discharge is
-- a new run, never itself resumed).
CREATE FUNCTION refuse_terminal_run_status_move() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF OLD.status <> 'RUNNING' THEN
        RAISE EXCEPTION 'a run''s terminal status never changes';
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER runs_status_terminal_once BEFORE UPDATE OF status ON runs
    FOR EACH ROW
    WHEN (NEW.status IS DISTINCT FROM OLD.status)
    EXECUTE FUNCTION refuse_terminal_run_status_move();

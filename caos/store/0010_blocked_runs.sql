-- §39: an empty frontier with unfinished required work ends the run BLOCKED,
-- never COMPLETE. Recoverable: nothing failed, and no further spend is allowed.
ALTER TABLE runs DROP CONSTRAINT runs_status_is_known;
ALTER TABLE runs ADD CONSTRAINT runs_status_is_known
    CHECK (status IN ('RUNNING', 'COMPLETE', 'FAILED', 'BLOCKED'));
ALTER TABLE run_events DROP CONSTRAINT run_events_name_is_known;
ALTER TABLE run_events ADD CONSTRAINT run_events_name_is_known CHECK (
    name IN ('ROUTE_PINNED', 'INPUT_PINNED', 'ATTEMPT_STARTED', 'CALL_OUTCOME_RECORDED',
             'ATTEMPT_ACCEPTED', 'RUN_COMPLETE', 'RUN_FAILED', 'RUN_BLOCKED')
);

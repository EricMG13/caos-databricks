-- CF-044: a parked run (`run_work.state = 'STOPPED'`) had no event of its
-- own, so neither the audit trail nor the SSE tail ever said a worker gave up
-- on it -- it just stayed RUNNING with nothing to notice by. Widens the
-- closed set `run_events_name_is_known` accepts the same way 0013 did, for
-- exactly one new name; `caos.store.events.RunEvent` names it as `RUN_PARKED`.
ALTER TABLE run_events DROP CONSTRAINT run_events_name_is_known;
ALTER TABLE run_events ADD CONSTRAINT run_events_name_is_known CHECK (
    name IN ('ROUTE_PINNED', 'INPUT_PINNED', 'ATTEMPT_STARTED', 'CALL_OUTCOME_RECORDED',
             'ATTEMPT_ACCEPTED', 'RUN_COMPLETE', 'RUN_FAILED', 'RUN_BLOCKED',
             'RUN_CANCELLED', 'RUN_PARKED')
);

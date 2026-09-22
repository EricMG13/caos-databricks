-- No backfill: an absent outcome does not verify historical provider metadata.
ALTER TABLE budget_ledger ADD UNIQUE (run_id, attempt_id);
CREATE TABLE call_outcomes (
    attempt_id uuid PRIMARY KEY,
    run_id uuid NOT NULL,
    charged_attempt_id uuid CHECK (charged_attempt_id = attempt_id),
    model text CHECK (model ~ '^[A-Za-z0-9][A-Za-z0-9._:/@+-]{0,255}$'),
    generation_id text CHECK (octet_length(generation_id) <= 512
        AND generation_id ~ '^[A-Za-z0-9][A-Za-z0-9._:/@+-]*$'),
    diagnostic_sha256 text CHECK (diagnostic_sha256 ~ '^[0-9a-f]{64}$'),
    recorded_at timestamptz NOT NULL DEFAULT now(),
    FOREIGN KEY (run_id, attempt_id) REFERENCES run_attempts (run_id, attempt_id),
    FOREIGN KEY (run_id, charged_attempt_id) REFERENCES budget_ledger (run_id, attempt_id)
);

CREATE FUNCTION refuse_call_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'call records are immutable';
END;
$$;
CREATE TRIGGER outcome_immutable BEFORE UPDATE OR DELETE ON call_outcomes
    FOR EACH ROW EXECUTE FUNCTION refuse_call_mutation();
CREATE TRIGGER outcome_no_truncate BEFORE TRUNCATE ON call_outcomes
    FOR EACH STATEMENT EXECUTE FUNCTION refuse_call_mutation();
CREATE TRIGGER ledger_immutable BEFORE UPDATE OR DELETE ON budget_ledger
    FOR EACH ROW EXECUTE FUNCTION refuse_call_mutation();
CREATE TRIGGER ledger_no_truncate BEFORE TRUNCATE ON budget_ledger
    FOR EACH STATEMENT EXECUTE FUNCTION refuse_call_mutation();

ALTER TABLE run_events DROP CONSTRAINT run_events_name_is_known;
ALTER TABLE run_events ADD CONSTRAINT run_events_name_is_known CHECK (
    name IN ('ROUTE_PINNED', 'INPUT_PINNED', 'ATTEMPT_STARTED', 'CALL_OUTCOME_RECORDED',
             'ATTEMPT_ACCEPTED', 'RUN_COMPLETE', 'RUN_FAILED')
);

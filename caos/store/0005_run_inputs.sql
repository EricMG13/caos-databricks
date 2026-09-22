ALTER TABLE runs ADD UNIQUE (case_id, run_id);
ALTER TABLE run_routes ADD UNIQUE (run_id, route_digest);
ALTER TABLE source_set_versions ADD UNIQUE (case_id, version, fingerprint);

CREATE TABLE run_inputs (
    run_id uuid PRIMARY KEY,
    case_id uuid NOT NULL,
    source_version bigint NOT NULL,
    source_fingerprint text NOT NULL,
    route_digest text NOT NULL,
    build_id text NOT NULL CHECK (build_id ~ '^[0-9a-f]{64}$'),
    manifest_sha256 text NOT NULL CHECK (manifest_sha256 ~ '^[0-9a-f]{64}$'),
    adapter_version text NOT NULL CHECK (adapter_version ~ '^[a-z0-9][a-z0-9.-]{0,63}$'),
    research_json text CHECK (octet_length(research_json) <= 65536),
    input_fingerprint text NOT NULL CHECK (input_fingerprint ~ '^[0-9a-f]{64}$'),
    format_version integer NOT NULL DEFAULT 1 CHECK (format_version = 1),
    FOREIGN KEY (case_id, run_id) REFERENCES runs (case_id, run_id),
    FOREIGN KEY (run_id, route_digest) REFERENCES run_routes (run_id, route_digest),
    FOREIGN KEY (case_id, source_version, source_fingerprint)
        REFERENCES source_set_versions (case_id, version, fingerprint)
);
CREATE FUNCTION refuse_input_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'run inputs are immutable';
END;
$$;
CREATE TRIGGER input_immutable BEFORE UPDATE OR DELETE ON run_inputs
    FOR EACH ROW EXECUTE FUNCTION refuse_input_mutation();
CREATE TRIGGER input_no_truncate BEFORE TRUNCATE ON run_inputs
    FOR EACH STATEMENT EXECUTE FUNCTION refuse_input_mutation();

ALTER TABLE run_events DROP CONSTRAINT run_events_name_is_known;
ALTER TABLE run_events ADD CONSTRAINT run_events_name_is_known CHECK (
    name IN ('ROUTE_PINNED', 'INPUT_PINNED', 'ATTEMPT_STARTED', 'ATTEMPT_ACCEPTED',
             'RUN_COMPLETE', 'RUN_FAILED')
);

-- A reviewer signs an immutable performed snapshot, not a detached digest.
CREATE TABLE qualification_performed (
    performed_sha256 text PRIMARY KEY CHECK (performed_sha256 ~ '^[0-9a-f]{64}$'),
    qualification_set_sha256 text NOT NULL
        CHECK (qualification_set_sha256 ~ '^[0-9a-f]{64}$'),
    build_id text NOT NULL,
    adapter_version text NOT NULL,
    provider text NOT NULL,
    model text NOT NULL,
    complete boolean NOT NULL,
    performed_json jsonb NOT NULL,
    recorded_at timestamptz NOT NULL DEFAULT now()
);
CREATE TRIGGER qualification_performed_immutable
    BEFORE UPDATE OR DELETE ON qualification_performed
    FOR EACH ROW EXECUTE FUNCTION refuse_revision_mutation();
CREATE TRIGGER qualification_performed_no_truncate
    BEFORE TRUNCATE ON qualification_performed
    FOR EACH STATEMENT EXECUTE FUNCTION refuse_revision_mutation();

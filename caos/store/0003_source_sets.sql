ALTER TABLE sources ADD UNIQUE (case_id, source_id);

CREATE TABLE source_set_versions (
    case_id uuid NOT NULL REFERENCES cases (case_id),
    version bigint NOT NULL CHECK (version > 0),
    format_version integer NOT NULL CHECK (format_version = 1),
    fingerprint text NOT NULL CHECK (fingerprint ~ '^[0-9a-f]{64}$'),
    member_count integer NOT NULL CHECK (member_count > 0),
    PRIMARY KEY (case_id, version)
);
CREATE TABLE source_set_members (
    case_id uuid NOT NULL,
    version bigint NOT NULL,
    source_id uuid NOT NULL REFERENCES source_extractions (source_id),
    document_sha256 text NOT NULL CHECK (document_sha256 ~ '^[0-9a-f]{64}$'),
    filename text NOT NULL,
    admitted_at text NOT NULL,
    extractor_identity text NOT NULL,
    output_sha256 text NOT NULL CHECK (output_sha256 ~ '^[0-9a-f]{64}$'),
    extraction_sha256 text NOT NULL CHECK (extraction_sha256 ~ '^[0-9a-f]{64}$'),
    PRIMARY KEY (case_id, version, source_id),
    FOREIGN KEY (case_id, version) REFERENCES source_set_versions (case_id, version),
    FOREIGN KEY (case_id, source_id) REFERENCES sources (case_id, source_id)
);

CREATE FUNCTION check_source_set_complete() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE expected integer; actual bigint;
BEGIN
    EXECUTE format('SELECT member_count FROM %I.source_set_versions'
        ' WHERE case_id = $1 AND version = $2', TG_TABLE_SCHEMA)
        INTO expected USING NEW.case_id, NEW.version;
    EXECUTE format('SELECT count(*) FROM %I.source_set_members'
        ' WHERE case_id = $1 AND version = $2', TG_TABLE_SCHEMA)
        INTO actual USING NEW.case_id, NEW.version;
    IF expected IS NULL OR expected <> actual THEN
        RAISE EXCEPTION 'source set membership must be complete';
    END IF;
    RETURN NULL;
END;
$$;
-- A committed header already has exactly its immutable count. Each later
-- INSERT therefore exceeds it, even if concurrent extra inserts are invisible.
-- ponytail: O(N^2) counts over sources; batch validation if measured throughput needs it.
CREATE CONSTRAINT TRIGGER source_set_complete AFTER INSERT ON source_set_versions
    DEFERRABLE INITIALLY DEFERRED FOR EACH ROW
    EXECUTE FUNCTION check_source_set_complete();
CREATE CONSTRAINT TRIGGER source_set_complete AFTER INSERT ON source_set_members
    DEFERRABLE INITIALLY DEFERRED FOR EACH ROW
    EXECUTE FUNCTION check_source_set_complete();

CREATE FUNCTION refuse_source_set_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'source sets are immutable';
END;
$$;
CREATE TRIGGER source_set_immutable BEFORE UPDATE OR DELETE ON source_set_versions
    FOR EACH ROW EXECUTE FUNCTION refuse_source_set_mutation();
CREATE TRIGGER source_set_no_truncate BEFORE TRUNCATE ON source_set_versions
    FOR EACH STATEMENT EXECUTE FUNCTION refuse_source_set_mutation();
CREATE TRIGGER source_set_immutable BEFORE UPDATE OR DELETE ON source_set_members
    FOR EACH ROW EXECUTE FUNCTION refuse_source_set_mutation();
CREATE TRIGGER source_set_no_truncate BEFORE TRUNCATE ON source_set_members
    FOR EACH STATEMENT EXECUTE FUNCTION refuse_source_set_mutation();

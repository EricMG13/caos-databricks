-- Host-minted immutable revisions; legacy text labels stay readable.
CREATE TABLE deliverable_revisions (
    revision_id uuid PRIMARY KEY,
    revision_key text GENERATED ALWAYS AS (revision_id::text) STORED,
    case_id uuid NOT NULL REFERENCES cases(case_id),
    run_id uuid NOT NULL REFERENCES runs(run_id),
    payload_sha256 text NOT NULL CHECK (payload_sha256 ~ '^[0-9a-f]{64}$'),
    saved_by uuid NOT NULL,
    saved_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE(case_id, payload_sha256),
    UNIQUE(case_id, revision_key)
);
CREATE FUNCTION refuse_revision_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'revisions are immutable';
END;
$$;
CREATE TRIGGER revision_immutable BEFORE UPDATE OR DELETE ON deliverable_revisions
    FOR EACH ROW EXECUTE FUNCTION refuse_revision_mutation();
CREATE TRIGGER revision_no_truncate BEFORE TRUNCATE ON deliverable_revisions
    FOR EACH STATEMENT EXECUTE FUNCTION refuse_revision_mutation();
ALTER TABLE deliverable_opinions ADD CONSTRAINT opinion_saved_revision
    FOREIGN KEY(case_id, revision_id)
    REFERENCES deliverable_revisions(case_id, revision_key) NOT VALID;
ALTER TABLE deliverable_publications ADD CONSTRAINT publication_saved_revision
    FOREIGN KEY(case_id, revision_id)
    REFERENCES deliverable_revisions(case_id, revision_key) NOT VALID;

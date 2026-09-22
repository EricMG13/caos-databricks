-- Historical digest-only filings remain historical; never synthesize receipts.
CREATE TABLE deliverable_receipts (
    case_id uuid NOT NULL,
    revision_id text NOT NULL,
    receipt_sha256 text NOT NULL CHECK (receipt_sha256 ~ '^[0-9a-f]{64}$'),
    renderer_sha256 text NOT NULL CHECK (renderer_sha256 ~ '^[0-9a-f]{64}$'),
    filed_event_sha256 text NOT NULL CHECK (filed_event_sha256 ~ '^[0-9a-f]{64}$'),
    PRIMARY KEY (case_id, revision_id),
    UNIQUE (case_id, filed_event_sha256),
    FOREIGN KEY (case_id, revision_id)
        REFERENCES deliverable_publications(case_id, revision_id)
);
CREATE TRIGGER receipt_immutable BEFORE UPDATE OR DELETE ON deliverable_receipts
    FOR EACH ROW EXECUTE FUNCTION refuse_revision_mutation();
CREATE TRIGGER receipt_no_truncate BEFORE TRUNCATE ON deliverable_receipts
    FOR EACH STATEMENT EXECUTE FUNCTION refuse_revision_mutation();

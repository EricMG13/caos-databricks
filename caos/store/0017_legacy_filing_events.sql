-- Snapshot receiptless filings at the receipt cutover. Future filings must carry
-- a receipt, so this immutable set is the durable legacy boundary.
ALTER TABLE audit_events ADD CONSTRAINT audit_event_hash_per_case
    UNIQUE (case_id, entry_sha256);
CREATE TABLE legacy_filing_events (
    case_id uuid NOT NULL,
    filed_event_sha256 text NOT NULL CHECK (filed_event_sha256 ~ '^[0-9a-f]{64}$'),
    PRIMARY KEY (case_id, filed_event_sha256),
    FOREIGN KEY (case_id, filed_event_sha256)
        REFERENCES audit_events (case_id, entry_sha256)
);
INSERT INTO legacy_filing_events (case_id, filed_event_sha256)
    SELECT e.case_id, e.entry_sha256
    FROM audit_events e
    LEFT JOIN deliverable_receipts r
        ON r.case_id = e.case_id AND r.filed_event_sha256 = e.entry_sha256
    WHERE e.action = 'DELIVERABLE_FILED' AND r.filed_event_sha256 IS NULL;
CREATE FUNCTION refuse_audit_event_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'audit events are immutable';
END;
$$;
CREATE TRIGGER audit_event_immutable BEFORE UPDATE OR DELETE ON audit_events
    FOR EACH ROW EXECUTE FUNCTION refuse_audit_event_mutation();
CREATE TRIGGER audit_event_no_truncate BEFORE TRUNCATE ON audit_events
    FOR EACH STATEMENT EXECUTE FUNCTION refuse_audit_event_mutation();
CREATE FUNCTION refuse_legacy_filing_event_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'legacy filing events are immutable';
END;
$$;
CREATE TRIGGER legacy_filing_event_immutable
    BEFORE INSERT OR UPDATE OR DELETE ON legacy_filing_events
    FOR EACH ROW EXECUTE FUNCTION refuse_legacy_filing_event_mutation();
CREATE TRIGGER legacy_filing_event_no_truncate BEFORE TRUNCATE ON legacy_filing_events
    FOR EACH STATEMENT EXECUTE FUNCTION refuse_legacy_filing_event_mutation();

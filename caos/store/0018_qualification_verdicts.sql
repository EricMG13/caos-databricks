-- Qualification covers a complete set, potentially spanning several cases.
-- It is therefore global evidence, not a case-scoped governed write.
CREATE TABLE qualification_evidence (
    evidence_sha256 text PRIMARY KEY CHECK (evidence_sha256 ~ '^[0-9a-f]{64}$'),
    qualification_set_sha256 text NOT NULL
        CHECK (qualification_set_sha256 ~ '^[0-9a-f]{64}$'),
    performed_sha256 text NOT NULL CHECK (performed_sha256 ~ '^[0-9a-f]{64}$'),
    build_id text NOT NULL,
    adapter_version text NOT NULL,
    provider text NOT NULL,
    model text NOT NULL,
    recorded_at timestamptz NOT NULL DEFAULT now()
);
CREATE TRIGGER qualification_evidence_immutable
    BEFORE UPDATE OR DELETE ON qualification_evidence
    FOR EACH ROW EXECUTE FUNCTION refuse_revision_mutation();
CREATE TRIGGER qualification_evidence_no_truncate
    BEFORE TRUNCATE ON qualification_evidence
    FOR EACH STATEMENT EXECUTE FUNCTION refuse_revision_mutation();

CREATE TABLE qualification_verdicts (
    evidence_sha256 text NOT NULL REFERENCES qualification_evidence(evidence_sha256),
    reviewer_id uuid NOT NULL,
    reviewer text NOT NULL,
    decided_at timestamptz NOT NULL,
    expires_at timestamptz NOT NULL CHECK (expires_at > decided_at),
    PRIMARY KEY (evidence_sha256, reviewer_id)
);
CREATE TRIGGER qualification_verdicts_immutable
    BEFORE UPDATE OR DELETE ON qualification_verdicts
    FOR EACH ROW EXECUTE FUNCTION refuse_revision_mutation();
CREATE TRIGGER qualification_verdicts_no_truncate
    BEFORE TRUNCATE ON qualification_verdicts
    FOR EACH STATEMENT EXECUTE FUNCTION refuse_revision_mutation();

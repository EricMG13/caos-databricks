-- A UI cannot truthfully select a "current" verdict from competing reviewers.
-- Qualification requires one authenticated decision for one evidence identity.
ALTER TABLE qualification_verdicts
    ADD CONSTRAINT one_verdict_per_evidence UNIQUE (evidence_sha256);

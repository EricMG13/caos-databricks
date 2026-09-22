-- One signature per signer per revision. `deliverable_opinions` was keyed
-- `(case_id, revision_id, signed_by, signed_at)`, so the same approver pressing
-- Sign twice under two idempotency keys wrote two rows for one act of
-- judgement, and the revision's `signed_by` carried that actor twice.
--
-- A constraint rather than a bare index, so that `sign_opinion_in` can name it
-- in `ON CONFLICT ON CONSTRAINT` and answer DELIVERABLE_ALREADY_SIGNED by the
-- constraint's name rather than by a message text -- the reason
-- `0019_one_qualification_verdict` gives for naming its own.
--
-- A store already holding a doubled signature is refused before this runs
-- (`apply_schema`, STORE_SCHEMA_DRIFT), not repaired: each row is governed
-- evidence an `OPINION_SIGNED` event names, and choosing which to delete is an
-- operator's decision, not a migration's.
ALTER TABLE deliverable_opinions
    ADD CONSTRAINT one_opinion_per_signer UNIQUE (case_id, revision_id, signed_by);

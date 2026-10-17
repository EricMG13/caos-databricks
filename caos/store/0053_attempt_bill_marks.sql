-- N223: a hold the store owns while a call's bill is owed. `call_hold` is a
-- session advisory lock and dies with its backend; a bill that lost its
-- try-lock to a half-open old backend, and waits on a case row a freeze holds
-- (unbounded by design, W1), left the node unheld the moment that backend
-- ended, and a reclaim queued ahead of the bill paid the node again. The bill
-- now writes a mark, in a unit of its own that waits on no other session,
-- before its
-- write; `start_attempt` reads it beside the advisory lock and refuses
-- ATTEMPT_UNSETTLED while `owed_until` is in the future.
--
-- The bound is the store's own clock written at the mark (`owed_until = now()
-- + BILL_OWED_SECONDS`, caos.store.outcomes), never a duration a caller says:
-- a mark expires by itself, so a bill abandoned with no session left holds the
-- node for that span and no longer. The bill's landing needs no delete: an
-- attempt with a call outcome is settled and its mark is not read (`_UNSETTLED`
-- reads outcomes first).
--
-- The table is append-only, like the ledger beside it: every try of a bill
-- inserts a row of its own under a fresh `mark_id`, and nothing is updated,
-- deleted or truncated (`refuse_governed_mutation`, 0033). An upsert on
-- `attempt_id` was the first design and was wrong: a bill's old backend cut
-- between the INSERT and its COMMIT sits idle in transaction holding the row,
-- and the fresh bill's upsert waited on it -- under a `lock_timeout` the mark
-- failed and no outcome was written (F704). Inserts of distinct keys wait on
-- nothing, so the mark never queues behind another session. A mark grants
-- nothing and spends nothing; the worst a stray one does is hold one node for
-- its span, then lapse.
CREATE TABLE attempt_bill_marks (
    mark_id    uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    attempt_id uuid        NOT NULL REFERENCES run_attempts (attempt_id),
    owed_until timestamptz NOT NULL
);

CREATE INDEX attempt_bill_marks_by_attempt ON attempt_bill_marks (attempt_id, owed_until);

CREATE TRIGGER bill_mark_immutable BEFORE UPDATE OR DELETE ON attempt_bill_marks
    FOR EACH ROW EXECUTE FUNCTION refuse_governed_mutation();
CREATE TRIGGER bill_mark_no_truncate BEFORE TRUNCATE ON attempt_bill_marks
    FOR EACH STATEMENT EXECUTE FUNCTION refuse_governed_mutation();

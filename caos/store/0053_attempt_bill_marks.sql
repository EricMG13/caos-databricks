-- N223: a hold the store owns while a call's bill is owed. `call_hold` is a
-- session advisory lock and dies with its backend; a bill that lost its
-- try-lock to a half-open old backend, and waits on a case row a freeze holds
-- (unbounded by design, W1), left the node unheld the moment that backend
-- ended, and a reclaim queued ahead of the bill paid the node again. The bill
-- now writes a mark, in a unit of its own that waits on nothing, before its
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
-- The one mutable row kind beside `worker_heartbeats`, for the same reason: it
-- is an observation with a shelf life, not a governed fact. It grants nothing
-- and spends nothing -- the accepted-attempt ledger (`run_attempts`,
-- `artifacts`, `budget_ledger`, `call_outcomes`) is untouched; the worst a
-- stray mark does is hold one node for the span, then lapse.
CREATE TABLE attempt_bill_marks (
    attempt_id uuid        PRIMARY KEY REFERENCES run_attempts (attempt_id),
    owed_until timestamptz NOT NULL
);

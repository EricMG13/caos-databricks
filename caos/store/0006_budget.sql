-- Numeric NaN sorts above Infinity in PostgreSQL: the upper comparison excludes
-- both, while the lower comparison excludes negative values and -Infinity.
ALTER TABLE runs ADD CONSTRAINT ceiling_finite_nonnegative
    CHECK (budget_ceiling >= 0 AND budget_ceiling < 'Infinity'::numeric);
ALTER TABLE budget_reservations ADD CONSTRAINT reservation_finite_nonnegative
    CHECK (amount >= 0 AND amount < 'Infinity'::numeric);
ALTER TABLE budget_ledger ADD CONSTRAINT charge_finite_nonnegative
    CHECK (amount >= 0 AND amount < 'Infinity'::numeric);

-- Exposure belongs to the attempt's actual run, including legacy ledger rows.
ALTER TABLE run_attempts ADD UNIQUE (run_id, attempt_id);
ALTER TABLE budget_reservations ADD FOREIGN KEY (run_id, attempt_id)
    REFERENCES run_attempts (run_id, attempt_id);
ALTER TABLE budget_ledger ADD FOREIGN KEY (run_id, attempt_id)
    REFERENCES run_attempts (run_id, attempt_id);

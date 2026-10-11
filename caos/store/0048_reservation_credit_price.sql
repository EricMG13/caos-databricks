-- D77, addendum 2 (the plan's re-spec R2.2): the dated price of one AI credit
-- a Copilot reservation was taken under, beside the per-token price 0024
-- stores. A Copilot call is settled in AI units at this price, never at the
-- process's current one, so a redeploy cannot change a live run's charge
-- (F468's rule for the per-token price, 0043, applied to the credit). A
-- reservation for any other model names none, and one that names none
-- settles no Copilot call. Both columns or neither, and a price above zero:
-- a free credit would settle every call at nothing. Numeric NaN sorts above
-- Infinity, so the upper comparison excludes both.
ALTER TABLE budget_reservations
    ADD COLUMN credit_price numeric,
    ADD COLUMN credit_as_of date,
    ADD CONSTRAINT reservation_credit_price_readable CHECK (
        (credit_price IS NULL) = (credit_as_of IS NULL)
        AND (
            credit_price IS NULL
            OR (credit_price > 0 AND credit_price < 'Infinity'::numeric)
        )
    );

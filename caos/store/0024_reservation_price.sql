-- The dated price a reservation was taken under, beside the amount it produced
-- (§40, completion O09). The amount alone cannot be read back to a price: many
-- prices and request sizes reach the same number, so an auditor asking what a
-- run was priced at had nothing to read.
--
-- The defaults migrate the rows that exist and are then dropped: a reservation
-- written after this migration must name its own price, and 'legacy' is how a
-- row says plainly that it predates the columns. Amounts are not touched.
ALTER TABLE budget_reservations
    ADD COLUMN price_model  text    NOT NULL DEFAULT 'legacy',
    ADD COLUMN price_input  numeric NOT NULL DEFAULT 0,
    ADD COLUMN price_output numeric NOT NULL DEFAULT 0,
    ADD COLUMN price_as_of  date    NOT NULL DEFAULT '1970-01-01';

ALTER TABLE budget_reservations
    ALTER COLUMN price_model  DROP DEFAULT,
    ALTER COLUMN price_input  DROP DEFAULT,
    ALTER COLUMN price_output DROP DEFAULT,
    ALTER COLUMN price_as_of  DROP DEFAULT;

-- Numeric NaN sorts above Infinity in PostgreSQL: the upper comparison excludes
-- both, while the lower comparison excludes negative values and -Infinity. A
-- price naming no model is not the fact these columns exist to hold.
ALTER TABLE budget_reservations ADD CONSTRAINT reservation_price_readable
    CHECK (
        price_model <> ''
        AND price_input >= 0 AND price_input < 'Infinity'::numeric
        AND price_output >= 0 AND price_output < 'Infinity'::numeric
    );

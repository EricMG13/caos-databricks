-- The model a run was started on and its dated price, pinned with the row
-- (the model choice, F468). Before this a run read the process's one
-- configured model at every node, so a redeploy that changed the model
-- moved a running run onto it part way through. A run started from here on
-- names its model once, and the worker executes it on that model at that
-- price or not at all.
--
-- A run that predates the columns keeps them null, and runs on the
-- deployment's configured model as it always did. Written once with the row:
-- nothing updates them.
ALTER TABLE runs
    ADD COLUMN price_model  text,
    ADD COLUMN price_input  numeric,
    ADD COLUMN price_output numeric,
    ADD COLUMN price_as_of  date;

-- All four or none, and readable as a price by the rule a reservation's
-- price is (0024): a model with a name, and finite rates no lower than zero
-- (NaN sorts above Infinity, so the upper comparison excludes both).
ALTER TABLE runs ADD CONSTRAINT run_price_readable
    CHECK (
        (price_model IS NULL AND price_input IS NULL
            AND price_output IS NULL AND price_as_of IS NULL)
        OR (
            price_model <> ''
            AND price_input >= 0 AND price_input < 'Infinity'::numeric
            AND price_output >= 0 AND price_output < 'Infinity'::numeric
            AND price_as_of IS NOT NULL
        )
    );

-- Written once, by the insert that starts the run, and never moved, as
-- `supersedes_run_id` is (0025): a price written later would move a run onto
-- a model it was not admitted under, the very thing these columns stop.
CREATE FUNCTION refuse_run_price_move() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'a run''s model and price are written once';
END;
$$;
CREATE TRIGGER runs_price_write_once
    BEFORE UPDATE OF price_model, price_input, price_output, price_as_of ON runs
    FOR EACH ROW
    WHEN ((NEW.price_model, NEW.price_input, NEW.price_output, NEW.price_as_of)
        IS DISTINCT FROM (OLD.price_model, OLD.price_input, OLD.price_output, OLD.price_as_of))
    EXECUTE FUNCTION refuse_run_price_move();

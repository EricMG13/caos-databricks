-- The run a run answers (§72). A BLOCKED run is never moved back to RUNNING:
-- its source set and route are pinned (invariants 1 and 10), and the source a
-- CONDITIONAL verdict asked for (§61) makes a new source-set version, so the
-- discharge is a new run. This column is how the new run says which run it
-- answers. Nullable: an ordinary run answers nothing.
ALTER TABLE runs ADD COLUMN supersedes_run_id uuid NULL REFERENCES runs (run_id);

-- Never itself. `start_run` mints the successor's id, so no host path can
-- write this; the CHECK is what a hand-written row meets.
ALTER TABLE runs ADD CONSTRAINT runs_never_supersede_self
    CHECK (supersedes_run_id IS DISTINCT FROM run_id);

-- At most one successor per predecessor. `start_run` maps a violation of this
-- index, by its name, to `RUN_ALREADY_SUPERSEDED`; a second unique index on
-- this table must not inherit that code, which is why the name is the key.
CREATE UNIQUE INDEX runs_one_successor ON runs (supersedes_run_id)
    WHERE supersedes_run_id IS NOT NULL;

-- Written once, by the insert that makes the successor, and never moved: not
-- to another run, not to null, and not from null onto a run after the fact.
-- A link written later would bypass the checks `start_run` makes in the unit
-- that writes it (the predecessor is this case's and is BLOCKED), so the
-- trigger refuses every change of the column rather than only a rewrite.
CREATE FUNCTION refuse_supersedes_move() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'a run''s predecessor is written once';
END;
$$;
CREATE TRIGGER runs_supersedes_write_once BEFORE UPDATE OF supersedes_run_id ON runs
    FOR EACH ROW
    WHEN (NEW.supersedes_run_id IS DISTINCT FROM OLD.supersedes_run_id)
    EXECUTE FUNCTION refuse_supersedes_move();

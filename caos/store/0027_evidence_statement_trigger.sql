-- 0008's seal check, once per statement instead of once per row.
--
-- The contract is 0008's, unchanged: evidence writes require read committed,
-- an evidence row needs a parent this transaction can lock, and a source whose
-- extraction is sealed takes no further evidence. The three refusal messages
-- and their SQLSTATEs are the same bytes 0008 raised; only how often the check
-- runs, and when within the statement, has moved.
--
-- `FOR NO KEY UPDATE`, where 0008 took `FOR UPDATE`: an AFTER trigger runs
-- after the statement's own foreign-key checks, which take `FOR KEY SHARE` on
-- the same `sources` rows. Two writers of one unsealed source would each hold
-- a key share and each wait for the other's before either could take
-- `FOR UPDATE` -- a deadlock the BEFORE trigger could not have, because it
-- locked first and inserted after. `FOR NO KEY UPDATE` conflicts with every
-- lock `FOR UPDATE` conflicted with except that key share, so the seal insert
-- (still `FOR UPDATE`, still a BEFORE row trigger on `source_extractions`) and
-- every other evidence writer are excluded exactly as before.
CREATE FUNCTION lock_extraction_sources() RETURNS trigger
LANGUAGE plpgsql VOLATILE AS $$
DECLARE
    subject uuid;
    parent uuid;
    sealed boolean;
BEGIN
    IF current_setting('transaction_isolation') <> 'read committed' THEN
        RAISE EXCEPTION 'evidence writes require read committed' USING ERRCODE = '25000';
    END IF;
    -- `inserted` is the statement's transition table, resolved ahead of the
    -- search path, so a shadowing schema cannot substitute rows for it.
    -- Ordered, so two statements touching the same sources queue rather than
    -- take their locks in opposite orders.
    FOR subject IN SELECT DISTINCT source_id FROM inserted ORDER BY source_id LOOP
        EXECUTE format('SELECT source_id FROM %I.sources WHERE source_id = $1'
                       ' FOR NO KEY UPDATE', TG_TABLE_SCHEMA) INTO parent USING subject;
        IF parent IS NULL THEN
            -- The foreign key reaches this first now; kept, and kept identical,
            -- because a trigger that assumes its parent is a trigger that stops
            -- saying so.
            RAISE EXCEPTION 'evidence parent is unavailable' USING ERRCODE = '23503';
        END IF;
        -- A separate VOLATILE query sees seals committed while the lock waited.
        EXECUTE format('SELECT EXISTS (SELECT 1 FROM %I.source_extractions WHERE source_id = $1)',
                       TG_TABLE_SCHEMA) INTO sealed USING subject;
        IF sealed THEN
            RAISE EXCEPTION 'extracted evidence is sealed' USING ERRCODE = '23514';
        END IF;
    END LOOP;
    RETURN NULL;
END;
$$;

DROP TRIGGER evidence_insert ON source_tokens;
DROP TRIGGER evidence_insert ON source_blocks;
CREATE TRIGGER evidence_insert_stmt AFTER INSERT ON source_tokens
    REFERENCING NEW TABLE AS inserted
    FOR EACH STATEMENT EXECUTE FUNCTION lock_extraction_sources();
CREATE TRIGGER evidence_insert_stmt AFTER INSERT ON source_blocks
    REFERENCING NEW TABLE AS inserted
    FOR EACH STATEMENT EXECUTE FUNCTION lock_extraction_sources();

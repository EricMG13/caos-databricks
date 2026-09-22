-- The existing extraction INSERT seals a private admission transaction.
CREATE FUNCTION lock_extraction_source() RETURNS trigger
LANGUAGE plpgsql VOLATILE AS $$
DECLARE
    parent uuid;
    sealed boolean;
BEGIN
    IF current_setting('transaction_isolation') <> 'read committed' THEN
        RAISE EXCEPTION 'evidence writes require read committed' USING ERRCODE = '25000';
    END IF;
    EXECUTE format('SELECT source_id FROM %I.sources WHERE source_id = $1 FOR UPDATE',
                   TG_TABLE_SCHEMA) INTO parent USING NEW.source_id;
    IF parent IS NULL THEN
        RAISE EXCEPTION 'evidence parent is unavailable' USING ERRCODE = '23503';
    END IF;
    IF TG_TABLE_NAME <> 'source_extractions' THEN
        -- A separate VOLATILE query sees seals committed while the lock waited.
        EXECUTE format('SELECT EXISTS (SELECT 1 FROM %I.source_extractions WHERE source_id = $1)',
                       TG_TABLE_SCHEMA) INTO sealed USING NEW.source_id;
        IF sealed THEN
            RAISE EXCEPTION 'extracted evidence is sealed' USING ERRCODE = '23514';
        END IF;
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER evidence_insert BEFORE INSERT ON source_tokens
    FOR EACH ROW EXECUTE FUNCTION lock_extraction_source();
CREATE TRIGGER evidence_insert BEFORE INSERT ON source_blocks
    FOR EACH ROW EXECUTE FUNCTION lock_extraction_source();
CREATE TRIGGER extraction_seal BEFORE INSERT ON source_extractions
    FOR EACH ROW EXECUTE FUNCTION lock_extraction_source();
CREATE TRIGGER evidence_immutable BEFORE UPDATE OR DELETE ON source_tokens
    FOR EACH ROW EXECUTE FUNCTION refuse_extraction_mutation();
CREATE TRIGGER evidence_immutable BEFORE UPDATE OR DELETE ON source_blocks
    FOR EACH ROW EXECUTE FUNCTION refuse_extraction_mutation();
CREATE TRIGGER evidence_no_truncate BEFORE TRUNCATE ON source_tokens
    FOR EACH STATEMENT EXECUTE FUNCTION refuse_extraction_mutation();
CREATE TRIGGER evidence_no_truncate BEFORE TRUNCATE ON source_blocks
    FOR EACH STATEMENT EXECUTE FUNCTION refuse_extraction_mutation();

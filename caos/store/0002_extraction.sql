-- No row means UNKNOWN: never attribute legacy extraction to today's adapter.
CREATE TABLE source_extractions (
    source_id uuid PRIMARY KEY REFERENCES sources (source_id),
    format_version integer NOT NULL CHECK (format_version = 1),
    extractor_identity text NOT NULL CHECK (length(extractor_identity) BETWEEN 1 AND 4096),
    output_sha256 text NOT NULL CHECK (output_sha256 ~ '^[0-9a-f]{64}$'),
    extraction_sha256 text NOT NULL CHECK (extraction_sha256 ~ '^[0-9a-f]{64}$')
);

CREATE FUNCTION refuse_extraction_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'extraction provenance is immutable';
END;
$$;
CREATE TRIGGER extraction_is_immutable BEFORE UPDATE OR DELETE ON source_extractions
    FOR EACH ROW EXECUTE FUNCTION refuse_extraction_mutation();
CREATE TRIGGER extraction_cannot_truncate BEFORE TRUNCATE ON source_extractions
    FOR EACH STATEMENT EXECUTE FUNCTION refuse_extraction_mutation();

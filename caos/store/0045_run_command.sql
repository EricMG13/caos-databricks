-- D109: format version 3 pins the run's command -- each module's qualifiers
-- and CP-0's stated objective, and CP-2G's forecast scope derived by the
-- owner's rule where the caller stated none -- as the canonical JSON the
-- host wrote, or NULL when it carries none. Version 1 and 2 rows keep every
-- byte: the column is added empty and nothing is backfilled.
ALTER TABLE run_inputs
    ADD COLUMN command_json text CHECK (octet_length(command_json) <= 65536);
ALTER TABLE run_inputs DROP CONSTRAINT run_inputs_subject_by_format;
ALTER TABLE run_inputs ADD CONSTRAINT run_inputs_subject_by_format CHECK (
    (format_version = 1
        AND issuer_id IS NULL AND issuer_name IS NULL AND reporting_period IS NULL
        AND analysis_date IS NULL AND cos_run_id IS NULL)
    -- NOT NULL is spelled out: a CHECK over NULL is not false, so it passes.
    -- `analysis_date` is shape only here; the host refuses an impossible date.
    OR (format_version IN (2, 3)
        AND issuer_id IS NOT NULL AND issuer_name IS NOT NULL
        AND reporting_period IS NOT NULL AND analysis_date IS NOT NULL
        AND cos_run_id IS NOT NULL
        AND issuer_id COLLATE "C" ~ '^[A-Za-z0-9]([A-Za-z0-9.-]*[A-Za-z0-9])?$'
        AND octet_length(issuer_id) <= 128
        AND octet_length(issuer_name) BETWEEN 1 AND 1024
        AND octet_length(reporting_period) BETWEEN 1 AND 1024
        AND analysis_date ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}$'
        AND cos_run_id ~ '^COS-[0-9]{8}T[0-9]{6}Z-[0-9a-f]{32}$')
);
ALTER TABLE run_inputs ADD CONSTRAINT run_inputs_command_by_format CHECK (
    format_version = 3 OR command_json IS NULL
);

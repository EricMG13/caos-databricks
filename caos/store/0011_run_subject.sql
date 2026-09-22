-- Format version 2 pins the subject a run is about and the vendor run id the
-- host derives once, in UTC, from `runs.created_at`. Version 1 rows keep every
-- byte: the columns are added empty and nothing is backfilled.
ALTER TABLE run_inputs
    ADD COLUMN issuer_id text,
    ADD COLUMN issuer_name text,
    ADD COLUMN reporting_period text,
    ADD COLUMN analysis_date text,
    ADD COLUMN cos_run_id text;
ALTER TABLE run_inputs DROP CONSTRAINT run_inputs_format_version_check;
ALTER TABLE run_inputs ADD CONSTRAINT run_inputs_subject_by_format CHECK (
    (format_version = 1
        AND issuer_id IS NULL AND issuer_name IS NULL AND reporting_period IS NULL
        AND analysis_date IS NULL AND cos_run_id IS NULL)
    -- NOT NULL is spelled out: a CHECK over NULL is not false, so it passes.
    -- `analysis_date` is shape only here; the host refuses an impossible date.
    OR (format_version = 2
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

-- The vendor derives an attempt id from (run, node, ordinal) and caps a run
-- folder at 256 entries. Existing attempts predate the ordinal and keep NULL.
ALTER TABLE run_attempts
    ADD COLUMN ordinal integer CHECK (ordinal BETWEEN 1 AND 256),
    ADD CONSTRAINT run_attempts_one_ordinal UNIQUE (run_id, route_node_id, ordinal);

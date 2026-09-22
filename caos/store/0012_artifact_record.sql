-- The host record a canonical handoff is accepted with (§41.2). Artifacts
-- accepted before it, and every claims-adapter artifact, keep NULL: nothing is
-- backfilled, and acceptance, not this column, requires it for a canonical pin.
ALTER TABLE artifacts
    ADD COLUMN record_sha256 text CHECK (record_sha256 ~ '^[0-9a-f]{64}$');

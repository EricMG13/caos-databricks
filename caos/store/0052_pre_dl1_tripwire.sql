-- N81: a build from before DL-1 (F219) must refuse this store, not boot empty.
--
-- That code names no schema: its connections search Postgres's default path,
-- "$user", public. It finds no bookkeeping in `public`, builds an empty store
-- there and serves it beside the real one in `caos_store`. The schema named for
-- the app's own role comes first on that path and needs nothing `public` does
-- (the role already holds CREATE on the database, DL-1), so the bookkeeping row
-- sits there, holding a digest no migration history yields. The old build's
-- boot reads it, finds a store it cannot account for and answers
-- STORE_SCHEMA_DRIFT. This build never reads that schema: its connections
-- search `caos_store` alone. Nothing here names a schema but the role's own.
DO $tripwire$
BEGIN
    EXECUTE format('CREATE SCHEMA IF NOT EXISTS %I', current_user);
    EXECUTE format(
        'CREATE TABLE IF NOT EXISTS %I.store_schema ('
        ' only_row boolean PRIMARY KEY DEFAULT true CHECK (only_row),'
        ' applied_digest text NOT NULL)',
        current_user);
    EXECUTE format(
        'INSERT INTO %I.store_schema (applied_digest) VALUES (%L)'
        ' ON CONFLICT (only_row) DO UPDATE SET applied_digest = EXCLUDED.applied_digest',
        current_user,
        'caos-n81-tripwire: the store moved to caos_store (DL-1); roll forward');
END
$tripwire$;

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
--
-- The role's name is public (W2), so a co-tenant may have made the schema
-- first, with a trigger on `store_schema` that would run as this role at the
-- INSERT below. Nothing is written into a schema this role does not own, or
-- one holding an object another role owns, or a `store_schema` carrying a
-- trigger, rule or policy: the migration refuses, and `apply_schema` answers
-- STORE_SCHEMA_DRIFT, as `owned_schema` does for `caos_store`.
DO $tripwire$
DECLARE
    squatted boolean;
BEGIN
    SELECT n.nspowner <> (SELECT oid FROM pg_roles WHERE rolname = current_user)
        OR EXISTS (SELECT 1 FROM pg_class c WHERE c.relnamespace = n.oid
            AND c.relowner <> n.nspowner)
        OR EXISTS (SELECT 1 FROM pg_proc p WHERE p.pronamespace = n.oid
            AND p.proowner <> n.nspowner)
        OR EXISTS (SELECT 1 FROM pg_type t WHERE t.typnamespace = n.oid
            AND t.typowner <> n.nspowner)
        OR EXISTS (SELECT 1 FROM pg_class c
            WHERE c.relnamespace = n.oid AND c.relname = 'store_schema'
            AND (EXISTS (SELECT 1 FROM pg_trigger g
                    WHERE g.tgrelid = c.oid AND NOT g.tgisinternal)
                OR EXISTS (SELECT 1 FROM pg_rewrite r WHERE r.ev_class = c.oid)
                OR EXISTS (SELECT 1 FROM pg_policy o WHERE o.polrelid = c.oid)))
    INTO squatted
    FROM pg_namespace n WHERE n.nspname = current_user;
    IF squatted THEN
        RAISE EXCEPTION 'tripwire schema is not this role''s own'
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;
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

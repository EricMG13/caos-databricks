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
-- INSERT below. The schema and table are therefore created first, and the check
-- runs on what exists after that, in this one transaction: a schema made by
-- another role in any earlier gap is seen, and once the check passes the schema
-- is this role's own with no privilege held by anyone else, so no other role
-- can add an object to it before the INSERT. (Plain CREATE SCHEMA would refuse
-- a clean schema the role already owns, a dev role's, so IF NOT EXISTS stays and
-- the check does the refusing.) The check refuses, as `owned_schema` does for
-- `caos_store`, a schema this role does not own; any privilege on it, or a
-- default privilege for it, held by another role or PUBLIC; any relation,
-- function or type in it owned by another role; and a `store_schema` carrying a
-- trigger, rule, policy or a table or column grant. `apply_schema` answers
-- STORE_SCHEMA_DRIFT. A co-tenant's empty schema of this name therefore blocks
-- the upgrade, fail closed (docs/DEPLOYMENT.md section 6).
DO $tripwire$
DECLARE
    squatted boolean;
BEGIN
    EXECUTE format('CREATE SCHEMA IF NOT EXISTS %I', current_user);
    EXECUTE format(
        'CREATE TABLE IF NOT EXISTS %I.store_schema ('
        ' only_row boolean PRIMARY KEY DEFAULT true CHECK (only_row),'
        ' applied_digest text NOT NULL)',
        current_user);
    SELECT n.nspowner <> (SELECT oid FROM pg_roles WHERE rolname = current_user)
        OR EXISTS (SELECT 1 FROM aclexplode(n.nspacl) a WHERE a.grantee <> n.nspowner)
        OR EXISTS (SELECT 1 FROM pg_default_acl d WHERE d.defaclnamespace = n.oid)
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
                OR EXISTS (SELECT 1 FROM pg_policy o WHERE o.polrelid = c.oid)
                OR EXISTS (SELECT 1 FROM aclexplode(c.relacl) a
                    WHERE a.grantee <> c.relowner)
                OR EXISTS (SELECT 1 FROM pg_attribute t
                    WHERE t.attrelid = c.oid AND t.attacl IS NOT NULL)))
    INTO squatted
    FROM pg_namespace n WHERE n.nspname = current_user;
    IF squatted THEN
        RAISE EXCEPTION 'tripwire schema is not this role''s own'
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    EXECUTE format(
        'INSERT INTO %I.store_schema (applied_digest) VALUES (%L)'
        ' ON CONFLICT (only_row) DO UPDATE SET applied_digest = EXCLUDED.applied_digest',
        current_user,
        'caos-n81-tripwire: the store moved to caos_store (DL-1); roll forward');
END
$tripwire$;

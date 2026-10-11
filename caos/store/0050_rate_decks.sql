-- Plan 2 Task 1: the rate deck, the desk's dated statement of reference
-- rates per fiscal year for the Base and Downside cases (CONTEXT.md). A
-- global ADMIN saves one; every run pins the latest deck in the transaction
-- that creates it (`caos.store.runs.start_run`). A deck, its rates and a
-- run's pin are written once, in their own transaction, and never updated,
-- deleted or truncated: a newer deck is a new row, so a run's projection
-- reads the rates it was started under for ever.
--
-- "Latest" is `deck_seq`, handed out at insert while the save lock
-- (`caos.store.rate_decks.SAVE_LOCK`, class 0x0CA00050 = 211812432, second
-- key 0) is held exclusively, so its order is commit order; a deck inserted
-- without that lock is refused. `saved_at` is for display, and finite.
-- `rates_sha256` is the digest of the deck's rates as written
-- (`rates_digest`), checked on every read.
--
-- Every guard below runs with `search_path = pg_catalog, pg_temp`, so no
-- session can shadow a catalog view or one of these tables in its temporary
-- schema (searched first for an unqualified name); and it names the store's
-- tables through `TG_TABLE_SCHEMA`, the schema of the table it guards, which
-- is the schema these tables were created in -- the migration never names a
-- schema (`caos.store.STORE_SCHEMA` is the session's choice, DL-1).
--
-- Rates are decimals (0.0380 is 3.80%), strictly inside (-1, 1); numeric NaN
-- sorts above every number, so the upper bound refuses it too. A rate's text
-- is at most 64 characters, what the wire's decimal text carries back.
CREATE TABLE rate_decks (
    deck_id uuid PRIMARY KEY,
    deck_seq bigint GENERATED ALWAYS AS IDENTITY UNIQUE,
    as_of date NOT NULL,
    saved_by uuid NOT NULL,
    saved_at timestamptz NOT NULL DEFAULT now() CHECK (isfinite(saved_at)),
    rates_sha256 text NOT NULL CHECK (rates_sha256 ~ '^[0-9a-f]{64}$'),
    -- The saving transaction, top-level (savepoint-safe) and 64-bit (no
    -- wraparound); written once, since a deck row is never updated.
    saved_xact xid8 NOT NULL DEFAULT pg_current_xact_id()
);
CREATE TABLE rate_deck_rates (
    deck_id uuid NOT NULL REFERENCES rate_decks (deck_id),
    reference_rate text NOT NULL
        CHECK (reference_rate IN ('SOFR', 'TERM_SOFR', 'EURIBOR', 'SONIA')),
    year_offset integer NOT NULL CHECK (year_offset BETWEEN 1 AND 5),
    base_rate numeric NOT NULL CHECK (
        base_rate > -1 AND base_rate < 1 AND length(base_rate::text) <= 64
    ),
    downside_rate numeric NOT NULL CHECK (
        downside_rate > -1 AND downside_rate < 1
        AND length(downside_rate::text) <= 64
    ),
    PRIMARY KEY (deck_id, reference_rate, year_offset)
);
-- The transaction that created each run, written by its insert and never
-- again: what a pin is checked against. An existing run is given the id of
-- the transaction applying this migration, which no later transaction is,
-- so no run created before decks existed can ever be pinned. And a run's id
-- never changes, nor is a run deleted or truncated: a run moved aside under a
-- new id, or deleted, would free its id for a run inserted again, created by
-- a transaction that could then pin it. (Writing the same id is no change.)
ALTER TABLE runs ADD COLUMN created_xact xid8 NOT NULL DEFAULT pg_current_xact_id();
CREATE FUNCTION refuse_run_creator_change() RETURNS trigger LANGUAGE plpgsql
SET search_path = pg_catalog, pg_temp AS $$
BEGIN
    IF TG_OP = 'INSERT' AND NEW.created_xact <> pg_current_xact_id() THEN
        RAISE EXCEPTION 'a run is created by the transaction inserting it';
    END IF;
    IF TG_OP = 'UPDATE' AND NEW.created_xact <> OLD.created_xact THEN
        RAISE EXCEPTION 'a run''s creating transaction is written once';
    END IF;
    IF TG_OP = 'UPDATE' AND NEW.run_id IS DISTINCT FROM OLD.run_id THEN
        RAISE EXCEPTION 'a run''s identity is written once';
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER run_created_xact_once BEFORE INSERT OR UPDATE ON runs
    FOR EACH ROW EXECUTE FUNCTION refuse_run_creator_change();
CREATE FUNCTION refuse_run_delete() RETURNS trigger LANGUAGE plpgsql
SET search_path = pg_catalog, pg_temp AS $$
BEGIN
    RAISE EXCEPTION 'a run is never deleted';
END;
$$;
CREATE TRIGGER run_not_deleted BEFORE DELETE ON runs
    FOR EACH ROW EXECUTE FUNCTION refuse_run_delete();
-- TRUNCATE fires no row trigger; refused here, not left to a child's guard.
CREATE TRIGGER run_no_truncate BEFORE TRUNCATE ON runs
    FOR EACH STATEMENT EXECUTE FUNCTION refuse_run_delete();
CREATE TABLE run_rate_decks (
    run_id uuid PRIMARY KEY REFERENCES runs (run_id),
    deck_id uuid NOT NULL REFERENCES rate_decks (deck_id)
);
CREATE FUNCTION refuse_rate_deck_mutation() RETURNS trigger LANGUAGE plpgsql
SET search_path = pg_catalog, pg_temp AS $$
BEGIN
    RAISE EXCEPTION 'rate decks are immutable';
END;
$$;
CREATE TRIGGER rate_deck_immutable BEFORE UPDATE OR DELETE ON rate_decks
    FOR EACH ROW EXECUTE FUNCTION refuse_rate_deck_mutation();
CREATE TRIGGER rate_deck_no_truncate BEFORE TRUNCATE ON rate_decks
    FOR EACH STATEMENT EXECUTE FUNCTION refuse_rate_deck_mutation();
CREATE TRIGGER rate_deck_rate_immutable BEFORE UPDATE OR DELETE ON rate_deck_rates
    FOR EACH ROW EXECUTE FUNCTION refuse_rate_deck_mutation();
CREATE TRIGGER rate_deck_rate_no_truncate BEFORE TRUNCATE ON rate_deck_rates
    FOR EACH STATEMENT EXECUTE FUNCTION refuse_rate_deck_mutation();
CREATE TRIGGER run_rate_deck_immutable BEFORE UPDATE OR DELETE ON run_rate_decks
    FOR EACH ROW EXECUTE FUNCTION refuse_rate_deck_mutation();
CREATE TRIGGER run_rate_deck_no_truncate BEFORE TRUNCATE ON run_rate_decks
    FOR EACH STATEMENT EXECUTE FUNCTION refuse_rate_deck_mutation();

-- A deck is inserted only by a session holding the save lock exclusively;
-- with the identity the sequence just handed this session (an OVERRIDING
-- SYSTEM VALUE `deck_seq` would otherwise be latest for ever), above every
-- deck already saved (the lock serialises saves, so a sequence moved back
-- cannot file a new deck below the latest); and as saved by this
-- transaction.
CREATE FUNCTION refuse_rate_deck_unlocked() RETURNS trigger LANGUAGE plpgsql
SET search_path = pg_catalog, pg_temp AS $$
DECLARE
    issued bigint;
    highest bigint;
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_catalog.pg_locks
        WHERE locktype = 'advisory' AND pid = pg_backend_pid() AND granted
          AND classid = 211812432 AND objid = 0 AND objsubid = 2
          AND mode = 'ExclusiveLock'
    ) THEN
        RAISE EXCEPTION 'a rate deck is saved under the save lock';
    END IF;
    BEGIN
        issued := currval(pg_get_serial_sequence(
            format('%I.%I', TG_TABLE_SCHEMA, TG_TABLE_NAME), 'deck_seq'));
    EXCEPTION WHEN object_not_in_prerequisite_state THEN
        issued := NULL;  -- this session drew no identity at all
    END;
    IF NEW.deck_seq IS DISTINCT FROM issued THEN
        RAISE EXCEPTION 'a rate deck takes the identity its save drew';
    END IF;
    EXECUTE format('SELECT coalesce(max(deck_seq), 0) FROM %I.rate_decks',
                   TG_TABLE_SCHEMA)
        INTO highest;
    IF NEW.deck_seq <= highest THEN
        RAISE EXCEPTION 'a rate deck is saved after the latest';
    END IF;
    IF NEW.saved_xact <> pg_current_xact_id() THEN
        RAISE EXCEPTION 'a rate deck is saved by the transaction inserting it';
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER rate_deck_saved_locked BEFORE INSERT ON rate_decks
    FOR EACH ROW EXECUTE FUNCTION refuse_rate_deck_unlocked();

-- A deck's rates are written in the transaction that saved the deck (top
-- level, so a savepoint does not matter).
CREATE FUNCTION refuse_rate_after_save() RETURNS trigger LANGUAGE plpgsql
SET search_path = pg_catalog, pg_temp AS $$
DECLARE
    saved boolean;
BEGIN
    EXECUTE format(
        'SELECT EXISTS (SELECT 1 FROM %I.rate_decks'
        ' WHERE deck_id = $1 AND saved_xact = pg_current_xact_id())',
        TG_TABLE_SCHEMA)
        INTO saved USING NEW.deck_id;
    IF NOT saved THEN
        RAISE EXCEPTION 'a rate deck gains no rate after its save';
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER rate_deck_rate_with_its_deck BEFORE INSERT ON rate_deck_rates
    FOR EACH ROW EXECUTE FUNCTION refuse_rate_after_save();

-- A run is pinned in the transaction that created it: its write-once
-- `created_xact`, never a timestamp a later transaction could rewrite.
CREATE FUNCTION refuse_pin_after_creation() RETURNS trigger LANGUAGE plpgsql
SET search_path = pg_catalog, pg_temp AS $$
DECLARE
    created boolean;
BEGIN
    EXECUTE format(
        'SELECT EXISTS (SELECT 1 FROM %I.runs'
        ' WHERE run_id = $1 AND created_xact = pg_current_xact_id())',
        TG_TABLE_SCHEMA)
        INTO created USING NEW.run_id;
    IF NOT created THEN
        RAISE EXCEPTION 'a run is pinned to a rate deck only at its creation';
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER run_rate_deck_at_creation BEFORE INSERT ON run_rate_decks
    FOR EACH ROW EXECUTE FUNCTION refuse_pin_after_creation();

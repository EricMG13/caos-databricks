-- Plan 3 Task 2: the book entry, a completed run a case writer added to the
-- Book (CONTEXT.md): the desk-wide record of its subject, the analyst-stated
-- classification, and its metrics on each basis, computed by the Model's own
-- calculator when it was added (spec B10), with the limitations the Model
-- served beside them. Written by the Add to Book command
-- (`caos.api.commands.book`) beside its BOOK_ENTRY_ADDED event on the case's
-- audit chain, in one transaction.
--
-- One entry per run, ever (`run_id` unique): a withdrawn entry is not added
-- again, a newer run is. An entry is never deleted or truncated, and the one
-- change it takes is its withdrawal (spec B7): the four withdrawal columns
-- set once, from null, and nothing else touched -- whatever columns the table
-- gains later. `snapshot_sha256` is the digest the adder reviewed (invariant
-- 5, `caos.store.book.snapshot_sha256`): the run's accepted artifacts, its
-- pinned deck and these metrics; the withdrawal is bound to it as well.
--
-- The store keeps its own times: `added_at` and `withdrawn_at` are the
-- clock when the row was written, whatever the writer said, so a later add
-- is never older than an earlier one and a withdrawal never precedes its
-- add; `entry_seq` is the identity the insert drew, the tiebreak for B4's
-- "newest". `issuer_key` is `upper(trim(issuer_id))`, so a Book row's
-- issuer is one spelling (spec B1). Every figure in `metrics` is decimal
-- text or null, by basis and line, never a JSON number (invariant 7).
--
-- Every guard runs with `search_path = pg_catalog, pg_temp` and names its
-- own table through `TG_TABLE_SCHEMA`, as 0050's do; the migration names no
-- schema (DL-1).
CREATE FUNCTION book_metrics_valid(metrics jsonb) RETURNS boolean
LANGUAGE sql IMMUTABLE SET search_path = pg_catalog, pg_temp AS $$
    SELECT jsonb_typeof(metrics) = 'object' AND NOT EXISTS (
        SELECT 1 FROM jsonb_each(metrics) AS basis (key, lines)
        WHERE jsonb_typeof(basis.lines) <> 'object' OR EXISTS (
            SELECT 1 FROM jsonb_each(basis.lines) AS line (key, figure)
            WHERE NOT (
                jsonb_typeof(line.figure) = 'null'
                OR (jsonb_typeof(line.figure) = 'string'
                    AND line.figure #>> '{}' ~ '^-?[0-9]+(\.[0-9]+)?$')
            )
        )
    )
$$;
CREATE TABLE book_entries (
    entry_id uuid PRIMARY KEY,
    entry_seq bigint GENERATED ALWAYS AS IDENTITY UNIQUE,
    case_id uuid NOT NULL REFERENCES cases (case_id),
    run_id uuid NOT NULL UNIQUE,
    issuer_key text NOT NULL,
    issuer_id text NOT NULL,
    issuer_name text NOT NULL,
    reporting_period text NOT NULL,
    analysis_date date NOT NULL,
    route text NOT NULL,
    sector text NOT NULL,
    industry_group text,
    domicile text NOT NULL CHECK (domicile ~ '^[A-Z]{2}$'),
    moodys text,
    moodys_outlook text,
    sp text,
    sp_outlook text,
    fitch text,
    fitch_outlook text,
    composite_notch integer CHECK (composite_notch BETWEEN 1 AND 22),
    snapshot_sha256 text NOT NULL CHECK (snapshot_sha256 ~ '^[0-9a-f]{64}$'),
    rate_deck_id uuid REFERENCES rate_decks (deck_id),
    currency text,
    unit text,
    metrics jsonb NOT NULL CHECK (book_metrics_valid(metrics)),
    limitations text[] NOT NULL DEFAULT '{}'
        CHECK (array_position(limitations, NULL) IS NULL),
    added_by uuid NOT NULL,
    added_at timestamptz NOT NULL DEFAULT clock_timestamp()
        CHECK (isfinite(added_at)),
    withdrawn_at timestamptz CHECK (isfinite(withdrawn_at)),
    withdrawn_by uuid,
    withdrawal_reason text CHECK (
        withdrawal_reason IN
            ('ADDED_IN_ERROR', 'DATA_ERROR', 'SUPERSEDED_SOURCES', 'OTHER')
    ),
    withdrawal_note text,
    FOREIGN KEY (case_id, run_id) REFERENCES runs (case_id, run_id),
    CHECK (issuer_key = upper(trim(issuer_id)) AND issuer_key <> ''),
    -- An outlook is stated on a rating, never alone (spec B5).
    CHECK (moodys_outlook IS NULL OR moodys IS NOT NULL),
    CHECK (sp_outlook IS NULL OR sp IS NOT NULL),
    CHECK (fitch_outlook IS NULL OR fitch IS NOT NULL),
    -- Live, or withdrawn by someone, when and why; never half of it, and
    -- never before it was added.
    CHECK (
        (withdrawn_at IS NULL AND withdrawn_by IS NULL
            AND withdrawal_reason IS NULL AND withdrawal_note IS NULL)
        OR (withdrawn_at IS NOT NULL AND withdrawn_by IS NOT NULL
            AND withdrawal_reason IS NOT NULL)
    ),
    CHECK (withdrawn_at >= added_at),
    -- OTHER says what, in a note with something in it but white space.
    CHECK (
        withdrawal_reason IS DISTINCT FROM 'OTHER'
        OR withdrawal_note ~ '[^[:space:]]'
    )
);
CREATE INDEX book_entries_live_by_issuer
    ON book_entries (issuer_key, analysis_date DESC, added_at DESC, entry_seq DESC)
    WHERE withdrawn_at IS NULL;

-- Inserted live, stamped with the store's clock and the identity its insert
-- drew; deleted never; updated only to stamp the withdrawal once, every
-- other column -- the row's whole JSON, so a column added later is covered
-- -- unchanged, at the store's clock.
CREATE FUNCTION refuse_book_entry_change() RETURNS trigger LANGUAGE plpgsql
SET search_path = pg_catalog, pg_temp AS $$
DECLARE
    stamp CONSTANT text[] :=
        ARRAY['withdrawn_at', 'withdrawn_by', 'withdrawal_reason', 'withdrawal_note'];
    issued bigint;
BEGIN
    IF TG_OP = 'INSERT' THEN
        IF NEW.withdrawn_at IS NOT NULL THEN
            RAISE EXCEPTION 'a book entry is added live';
        END IF;
        BEGIN
            issued := currval(pg_get_serial_sequence(
                format('%I.%I', TG_TABLE_SCHEMA, TG_TABLE_NAME), 'entry_seq'));
        EXCEPTION WHEN object_not_in_prerequisite_state THEN
            issued := NULL;  -- this session drew no identity at all
        END;
        IF NEW.entry_seq IS DISTINCT FROM issued THEN
            RAISE EXCEPTION 'a book entry takes the identity its insert drew';
        END IF;
        NEW.added_at := clock_timestamp();
        RETURN NEW;
    END IF;
    IF TG_OP = 'UPDATE'
        AND OLD.withdrawn_at IS NULL
        AND NEW.withdrawn_at IS NOT NULL
        AND to_jsonb(NEW) - stamp = to_jsonb(OLD) - stamp
    THEN
        NEW.withdrawn_at := clock_timestamp();
        RETURN NEW;
    END IF;
    RAISE EXCEPTION 'a book entry is never changed but withdrawn, once';
END;
$$;
CREATE TRIGGER book_entry_immutable BEFORE INSERT OR UPDATE OR DELETE
    ON book_entries FOR EACH ROW EXECUTE FUNCTION refuse_book_entry_change();
CREATE FUNCTION refuse_book_entry_truncate() RETURNS trigger LANGUAGE plpgsql
SET search_path = pg_catalog, pg_temp AS $$
BEGIN
    RAISE EXCEPTION 'book entries are never truncated';
END;
$$;
CREATE TRIGGER book_entry_no_truncate BEFORE TRUNCATE ON book_entries
    FOR EACH STATEMENT EXECUTE FUNCTION refuse_book_entry_truncate();

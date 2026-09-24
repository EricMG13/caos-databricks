-- CF-091's remainder (N16; invariant 6, the accepted-attempt ledger is the
-- truth). `run_attempts` and `artifacts`, read with every query the app sends
-- them first, are inserted into and never updated, deleted or truncated: an
-- attempt at `caos.store.runs._start`, its artifact at acceptance (a replay
-- is a read, `_legacy_replay`), and nothing else. So every column of both is
-- write-once, and neither loses a row. `0033`'s `refuse_governed_mutation`
-- is reused; it names whichever table refused.
--
-- The suite still corrupts rows on purpose, to prove the application's own
-- verification catches what the database would otherwise prevent; it does so
-- through one helper, as a superuser in a disposable database, one statement
-- at a time (`tests/conftest.py` `tamper`).
CREATE TRIGGER attempt_immutable BEFORE UPDATE OR DELETE ON run_attempts
    FOR EACH ROW EXECUTE FUNCTION refuse_governed_mutation();
CREATE TRIGGER attempt_no_truncate BEFORE TRUNCATE ON run_attempts
    FOR EACH STATEMENT EXECUTE FUNCTION refuse_governed_mutation();

CREATE TRIGGER artifact_immutable BEFORE UPDATE OR DELETE ON artifacts
    FOR EACH ROW EXECUTE FUNCTION refuse_governed_mutation();
CREATE TRIGGER artifact_no_truncate BEFORE TRUNCATE ON artifacts
    FOR EACH STATEMENT EXECUTE FUNCTION refuse_governed_mutation();

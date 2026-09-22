-- Phase 4 Task 4.2 (decision 6): one receipt per committed command, keyed by
-- who asked, where (the case, or the nil UUID for create case) and the client's
-- key. Only committed successes are recorded, inside the command's own unit;
-- the primary key is what makes a concurrent twin wait and then replay.
CREATE TABLE command_requests (
    actor_id uuid NOT NULL,
    scope uuid NOT NULL,
    idempotency_key uuid NOT NULL,
    command text NOT NULL CHECK (command ~ '^[A-Z][A-Z_]{0,63}$'),
    request_sha256 text NOT NULL CHECK (request_sha256 ~ '^[0-9a-f]{64}$'),
    status smallint NOT NULL CHECK (status IN (200, 201, 202)),
    receipt jsonb NOT NULL CHECK (octet_length(receipt::text) <= 65536),
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (actor_id, scope, idempotency_key)
);
CREATE FUNCTION refuse_command_request_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'command requests are immutable';
END;
$$;
CREATE TRIGGER command_request_immutable BEFORE UPDATE OR DELETE ON command_requests
    FOR EACH ROW EXECUTE FUNCTION refuse_command_request_mutation();
CREATE TRIGGER command_request_no_truncate BEFORE TRUNCATE ON command_requests
    FOR EACH STATEMENT EXECUTE FUNCTION refuse_command_request_mutation();

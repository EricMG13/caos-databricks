-- One accepted result per run node. In Phase 2 a node's generation is its
-- (run_id, route_node_id): a retry is another attempt of it, never a second owner.
-- A populated database already holding two artifacts for one node fails the
-- unique constraint, and the whole upgrade rolls back.
ALTER TABLE run_attempts ADD UNIQUE (run_id, attempt_id, route_node_id);
ALTER TABLE artifacts ADD COLUMN route_node_id text;
UPDATE artifacts a SET route_node_id = t.route_node_id
    FROM run_attempts t WHERE t.attempt_id = a.attempt_id;
ALTER TABLE artifacts ALTER COLUMN route_node_id SET NOT NULL;
-- A writer that names no node gets its attempt's; the foreign key refuses a wrong one.
CREATE FUNCTION artifact_node() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.route_node_id IS NULL THEN
        SELECT route_node_id INTO NEW.route_node_id
            FROM run_attempts WHERE attempt_id = NEW.attempt_id;
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER artifact_node BEFORE INSERT ON artifacts
    FOR EACH ROW EXECUTE FUNCTION artifact_node();
ALTER TABLE artifacts ADD FOREIGN KEY (run_id, attempt_id, route_node_id)
    REFERENCES run_attempts (run_id, attempt_id, route_node_id);
ALTER TABLE artifacts ADD UNIQUE (run_id, route_node_id);

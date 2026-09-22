CREATE FUNCTION refuse_route_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'route pins are immutable';
END;
$$;
CREATE TRIGGER route_immutable BEFORE UPDATE OR DELETE ON run_routes
    FOR EACH ROW EXECUTE FUNCTION refuse_route_mutation();
CREATE TRIGGER route_no_truncate BEFORE TRUNCATE ON run_routes
    FOR EACH STATEMENT EXECUTE FUNCTION refuse_route_mutation();

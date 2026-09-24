CREATE ROLE caos_app LOGIN PASSWORD 'local-app-only' NOSUPERUSER NOCREATEDB NOCREATEROLE;
-- What the platform's CAN_CONNECT_AND_CREATE gives the app's principal (DL-1):
-- the app creates and owns its own schemas, caos_store and caos_graph.
GRANT CONNECT, CREATE ON DATABASE caos_dev TO caos_app;

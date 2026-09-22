# Next — out-of-scope items logged during the build

A new feature or requirement beyond the ledgers is written here, not built. One line each: what, why it came up, where it would go.

- N1 (spec author, 2026-09-22) — Parallel execution of independent route nodes (`independent_batch` in legacy `server/engine/runtime.py`) under LangGraph; v1 runs nodes sequentially to keep budget reservation order simple.
- N2 (spec author, 2026-09-22) — Reasoning-effort passthrough to Databricks Claude endpoints (`extra_params`), once the endpoint's accepted parameters are confirmed; v1 records `none` in the qualification identity when the parameter is not sent.
- N3 (spec author, 2026-09-22) — Lakebase-hosted test databases for CI (instead of the local Docker Postgres) once a Databricks profile exists in CI.

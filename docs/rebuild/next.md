# Next — out-of-scope items logged during the build

A new feature or requirement beyond the ledgers is written here, not built. One line each: what, why it came up, where it would go.

- N1 (spec author, 2026-09-22) — Parallel execution of independent route nodes (`independent_batch` in legacy `server/engine/runtime.py`) under LangGraph; v1 runs nodes sequentially to keep budget reservation order simple.
- N2 (spec author, 2026-09-22) — Reasoning-effort passthrough to Databricks Claude endpoints (`extra_params`), once the endpoint's accepted parameters are confirmed; v1 records `none` in the qualification identity when the parameter is not sent.
- N3 (spec author, 2026-09-22) — Lakebase-hosted test databases for CI (instead of the local Docker Postgres) once a Databricks profile exists in CI.
- N4 (review, 2026-09-23) — A read that renders the deliverable (`render.py`) and a download that builds the audit package (`package.py`): both are produced only by the suite today, while filing receipts pin the renderer's digest. Route shape and standing to be decided by the owner.
- N5 (review, 2026-09-23) — `admit_sources` materialises a pack twice (spooled and in memory) for up to fifty documents; a streaming admission or a process-wide semaphore. Writer-only cost.
- N6 (review, 2026-09-23) — `FORECAST_CHAIN_BROKEN` cannot fire from `cash_flow_forecast`: give `_check_chain` a caller-declared opening to compare against, or retire the code (wire tables included).
- N7 (review, 2026-09-23) — The stand-in still hands the process a token where the platform hands it a client id and secret; a stub OAuth token endpoint would let the harness run the service principal's own authentication.
- N8 (review, 2026-09-23) — `matrix._digested` tags three of nine optional fields; tag the rest so two different sets cannot share a digest.
- N9 (review, 2026-09-23) — `IO_BUDGET` numbers are declared, not all measured (`reads/model.py`, `reads/qualification.py`, `commands/members.py`).
- N10 (review, 2026-09-23) — A `host_prompt_digest` on `CanonicalRecord`, so a record says which host instructions the call carried (a record-shape change: parity goldens and the wire).

# Findings patched in the store, worker, graph, model seam and deployment path

One paragraph per finding: `ID — STATUS — what changed (files) — test / reason`.

C1 — FIXED — The CLI splits a `--var` value on commas, so the dated price never reached the bundle. `scripts/enterprise_deploy.sh` exports `BUNDLE_VAR_model_price` and drops the `--var`; `docs/DEPLOYMENT.md` §3a and `CLAUDE.md`'s gate row say the same; CI's validate passes a non-default price that way and the acceptance row A34 does too. Test: `tests/test_enterprise_deploy.py` asserts the recorder saw the price in the environment and no `model_price` flag.

C2 / R2-E1 / TM-3 — FIXED — The sync is an allowlist: `databricks.yml` `sync.paths` names the package, `icm`, `vendor`, `frontend/dist`, `app.yaml`, `pyproject.toml`, `uv.lock` and `.python-version`, with `frontend/dist/**` under `include` because the export is git-ignored. Against the stub the deploy now uploads 600 files, every tracked runtime file and the export, and nothing untracked. `scripts/check_gate_config.py` parses the sync block and refuses a missing allowlist, a needed path no root carries, and a missing export include; `SHIPPED` gained three nested paths a `dir/**` exclude once dropped. Tests: `tests/test_check_gate_config.py::test_a_sync_exclude_that_hides_the_methodology_is_named` (extended).

C3 — FIXED — `tests/workspace_stub.py` serves `GET /api/2.0/workspace/export` (raw with `direct_download`, base64 otherwise, `RESOURCE_DOES_NOT_EXIST` when absent) so the production target's deployment lock and state round-trip; the prod target's validate, deploy and run pass under one stub (`sh -c`), added to CI and as acceptance row A37. Test: `tests/test_workspace_stub.py::test_the_stub_serves_exports_and_refuses_a_duplicate_app`.

C4 — FIXED — E6 polls `/api/health` for up to `HEALTH_SECONDS` (90 s) every 3 s until ready, and records every answer's codes, a 503's included, so the row names the dependency that failed. `scripts/enterprise_deploy.py::_health`.

W1 — FIXED — E9 records "unverified" only when the 403 carries `NOT_AUTHORISED`; any other 403 code is a failing row with that code. Test: `tests/test_enterprise_deploy.py::test_the_stream_row_refuses_html_a_closed_stream_and_a_foreign_403`.

W2 — FIXED — `caos/workspace.py` caches one client per process and identity (host, profile, client id, app name), never keyed on a secret; a failed construction is not cached. Test: `tests/test_lakebase_and_blobs.py::test_the_workspace_client_is_one_per_identity_and_refuses_typed`.

W3 / DP-10 — FIXED — Both business groups get `CAN_USE`; the deployer alone holds `CAN_MANAGE` (`databricks.yml`, `docs/DEPLOYMENT.md` §1). A dedicated deployer service principal with top-level `permissions` is deferred to `next.md`.

W4 — FIXED — E9 sends only `Authorization` behind the platform; the deployer's token is forwarded as `x-forwarded-access-token` only when `CAOS_DEPLOY_FORWARD_CALLER=1`, which the stand-in test sets because the stub has no proxy.

W5 — FIXED — `scripts/preflight.py::_group` answers `UNKNOWN` on `PermissionDenied` instead of re-raising, so a profile that cannot list groups is told and not stopped. Test: `tests/test_workspace_stub.py::test_preflight_does_not_stop_on_a_profile_that_cannot_list_groups`.

N1 — FIXED — Every `after` step ends in a row: `_app_url` catches the SDK's `ValueError`, `_lakebase_version` records a `Refusal` as its code, `_stream` takes `_headers()` inside its try and a 201 without a case id is a row.

N2 — FIXED — `EVIDENCE` defaults to `docs/rebuild/runs/<date>/enterprise/<HHMMSS>`, one directory per run; the CLI step's output is written once as `E<n>.log`.

N3 — NOTED — E9 leaves one governed case per deploy; cases have no delete command by design. Recorded in `next.md`.

N4 — FIXED — `docs/DEPLOYMENT.md` names `DATABRICKS_WORKSPACE_ID` and `CAOS_RUN_CEILING`, drops `CAOS_UC_SCHEMA`, sets the engine in §3a; `pyproject.toml` names `caos.serve`; `app.yaml`'s F52 comment says what actually happens (the app boots refusing and answers `not_ready`).

N5 — PARTLY FIXED — `bundle.databricks_cli_version: ">= 1.17.0"` pins the CLI floor. The duplicated defaults across the wrapper, the Python stages, the bundle and the stub stay; recorded in `next.md`.

DP-6 — FIXED — The app is `caos` in `prod` and `caos-<target>` elsewhere (a dev-target override in `databricks.yml`); `enterprise_deploy.app_name` follows the rule and the stub answers a taken name with 409 and seeds no app. Tests: `tests/test_enterprise_deploy.py::test_the_dev_target_s_app_is_not_the_production_app`, the stub test above.

DP-12 — FIXED — `CAOS_UC_SCHEMA` removed from the bundle env, the gate checker's `APP_ENVIRONMENT`, `scripts/dev_doctor.py` and the platform harness.

CR-9 — FIXED — gitleaks is v8.24.3 in both the pre-commit hook and the CI image (digest `e1b35e12…`); the hook ran clean at that version.

MX-5 / DP-3 / TM-6 — FIXED — `scripts/preflight.py::gateway_problems` refuses an endpoint whose AI Gateway logs payloads to inference tables (or legacy auto-capture), has a fallback, or serves more than one entity or route; guardrails are reported as a note. Test: `tests/test_workspace_stub.py::test_preflight_reads_the_gateway_posture_and_the_price_s_endpoint`.

AR-05 — FIXED — E9 requires a `text/event-stream` content type, one complete frame whose first line is an SSE field or comment, and a stream still open `LIVE_SECONDS` after it, read on a thread because `http.client` forgets the socket of a `Connection: close` response. Test: the stream-row test above (HTML page, closed stream, foreign 403, open stream).

AR-06 — FIXED — `preflight.affordable(..., endpoint=)` refuses a price that names another endpoint before any deploy. Test: `tests/test_run_ceiling.py`.

AR-17 — FIXED — `scripts/gateway_smoke.py` parses the JSON-mode answer and passes only on a JSON object. Test: `tests/test_workspace_stub.py::test_the_smoke_parses_the_json_answer_it_asked_for`.

AR-21 — DEFERRED — The deployment path binds a provisioned instance only; carrying an autoscaling endpoint through preflight, the bundle resource and E8 is new scope in `next.md`.

AI-8 — NOTED — The gateway smoke's two paid calls run outside the ledger; documented in `docs/DEPLOYMENT.md` §6 as the one exception.

SA-C2 / TM-1 — FIXED — `caos/graph/checkpoint.py::serializer` builds `JsonPlusSerializer` with an allowlist of exactly `caos.graph.build.RunState`; a crafted row naming `os.system` loads as inert data. Test: `tests/test_checkpoint.py::test_the_serializer_never_imports_what_a_checkpoint_row_names`.

SA-C3 / CR-1 / DL-2 / DP-1 — FIXED — `caos/workspace.py` turns the SDK's `ValueError`/`OSError` at construction into `STORE_UNAVAILABLE`; `caos/store/lakebase.py::_mint` builds the client inside its try and maps both shapes; `caos/graph/worker.py::_connected` treats any `OSError`/`ValueError` from the connection factory as a store fault. Tests: `tests/test_worker.py::test_a_connection_factory_failing_in_the_sdk_s_shapes_is_a_store_fault`, the client test above.

SA-C4 / AR-01 / DL-3 — FIXED — `_beat` rolls back with `rollback_or_close`, so a session the server ended cannot escape the reconnect. Test: `tests/test_worker.py::test_a_session_the_server_ends_does_not_stop_the_worker` (a real `pg_terminate_backend`).

AR-02 — FIXED — `note_connect_failure` drops the cached credential on any `OperationalError` (the driver reports a refused password with no SQLSTATE), and `MintedConnection.connect` calls it for the checkpoint pool. Tests: `tests/test_lakebase_and_blobs.py::test_the_credential_life_and_a_connection_failure_dropping_it`, `tests/test_checkpoint.py::test_the_platform_pool_checks_connections_and_a_refused_connect_drops_the_token`.

AR-03 — FIXED — `pause_seconds` bounds the exponent at `MAX_DOUBLINGS` (30) before raising it. Test: `tests/test_worker.py::test_the_backoff_stays_at_its_cap_after_any_number_of_faults`.

MX-3 / DP-2 / DL-4 — FIXED — Minting is single-flight (`_MINTING`), bounded (`_mint_bounded` joins a helper thread for `MINT_SECONDS`), no lock is held across the network, a failed mint is not retried for `FAILURE_SECONDS`, and a held token is reused until the server's stated expiry less a margin when a fresh one cannot be had. `chat_model` passes the process's bounded client to `ChatDatabricks` (CR-6). Tests: `tests/test_lakebase_and_blobs.py::test_minting_is_single_flight_bounded_and_falls_back_to_a_live_token`, `tests/test_models.py::test_the_production_model_is_chat_databricks_on_the_endpoint`.

MX-4 / CR-3 / DP-8 — FIXED — `caos.provider.TIMEOUT_SECONDS` is 240 s, the generation budget of a non-streamed call, and `LEASE_SECONDS` is 600 s so the D5 rule (a lease outlives two call deadlines) holds. `MAX_COMPLETION_TOKENS` remains the reservation ceiling, not a delivery promise; streaming with an idle deadline and lease renewal is in `next.md`.

CR-2 — FIXED — A pool or connection whose set-up fails is closed before the refusal leaves; the pool waits `POOL_TIMEOUT_SECONDS` for a connection. Test: `tests/test_checkpoint.py::test_a_pool_whose_set_up_fails_is_closed_before_the_refusal_leaves`.

AR-20 — FIXED — Set-up runs under a polled advisory lock (`pg_try_advisory_lock`, `SETUP_LOCK_KEY`): polled, because LangGraph's set-up builds an index `CONCURRENTLY`, which waits for every open transaction, and a session blocked in `pg_advisory_lock` is one. Test: `tests/test_checkpoint.py::test_concurrent_set_up_on_a_fresh_database_all_succeed`.

DL-9 — FIXED — The platform pool checks each connection before handing it out (`check=ConnectionPool.check_connection`). Test: the pooled-path test above.

DL-5 — FIXED — `canonical._stored_body` lets `BLOB_NOT_FOUND` and `BLOB_DIGEST_MISMATCH` through, so the worker parks the run with that code instead of releasing it to the head of the queue. Test: `tests/test_worker.py::test_a_lost_or_corrupt_stored_body_parks_the_run_with_its_own_code`.

DL-8 — FIXED — The worker deletes a run's checkpoint thread when it parks or ends the run (`_forget`); the thread holds position only (D6). Test: `tests/test_worker.py::test_a_parked_run_s_checkpoint_thread_is_forgotten`. A run cancelled while QUEUED, which no worker holds, still leaves its thread; a sweep is in `next.md`.

DL-10 — FIXED — An idle worker beats `POLLING` every `BEAT_SECONDS` (10 s) rather than every poll, and says it again at once after any work; state changes still beat immediately.

AR-13 / CR-8 — FIXED — `caos/store/runs.py::_transition` refuses `RUN_CANCEL_REQUESTED` when the lease's cancel flag is set at a COMPLETE move, so the holder's cancel path ends the run CANCELLED with the last node's artifact and bill kept. Test: `tests/test_worker.py::test_a_cancel_during_the_last_call_ends_the_run_cancelled`.

CR-11 — FIXED — `require_lease(lease_seconds: int | None = None)`: the lease's own length unless the caller names one.

DP-4 — FIXED — `caos/api/app.py::on_shutdown` runs registered hooks inside the lifespan's shutdown; `caos/serve.py` registers the worker drain there (`stopping.set()`, join for `LIMIT_JOIN_SECONDS` = 12 s) and passes `timeout_graceful_shutdown` = 2 s, both inside the platform's grace. Tests: `tests/test_platform_boot.py::test_the_platform_s_stop_signal_drains_the_worker_inside_the_grace` (a real SIGTERM), `tests/test_worker.py::test_the_app_s_shutdown_hooks_run_after_the_probes_stop`.

DP-5 — FIXED — A 429 reached no model, so `ChatCompletions.complete` asks again under the same reservation, up to `RATE_LIMIT_TRIES` (3), waiting `Retry-After` capped at 20 s; every other status is answered once by its class. Test: `tests/test_models.py::test_a_rate_limit_is_asked_again_under_the_same_reservation`.

DP-7 — FIXED — `LIMIT_CONCURRENCY` is `STREAM_LIMIT + 40`, so every stream slot plus forty connections fit before uvicorn's plain-text 503; the proxy's idle timeout is still unverified (`next.md`).

AR-14 — FIXED — `_charge` requires whole, non-negative counts (`_count`); anything else is an unknown charge and `PROVIDER_RESPONSE_INVALID`. Test: `tests/test_models.py::test_a_usage_block_with_a_negative_or_fractional_count_is_not_billed`.

AR-15 — FIXED — `from_environment` refuses `PROVIDER_NOT_CONFIGURED` when `CAOS_REASONING_EFFORT` is set, since the effort is never sent; no identity names an effort the model did not receive. Test: `tests/test_models.py::test_from_environment_reads_three_names_and_never_a_value`.

CR-5 — NOTED — Every production generation id is host-minted because `ChatDatabricks` never surfaces the completion id; F36's claim is corrected in `decisions.md` and capturing the id is in `next.md`.

MX-7 / TM-5 / DP-11 — DOCUMENTED — `PGSSLMODE=verify-full` with `PGSSLROOTCERT` in the bundle env authenticates the server; libpq reads both (`docs/DEPLOYMENT.md` §6).

AS-6 — FIXED (with the edge patch) — `caos/serve.py::install_log_filter` strips exception text from `uvicorn.error` records, so an unhandled fault's traceback, which carries `str(exc)`, never reaches the server log; the edge writes the class and frame. Test: `tests/test_worker.py::test_the_server_log_never_carries_an_exception_s_text`.

SI-1 (databricks-langchain), SI-2 (HMAC edge mode), AI-3, AI-4, AI-6, AI-7, AS-4, TM-2, DL-6, DP-9, SI-6..SI-12 — DEFERRED to `next.md` with their reasons: dependency or design decisions needing a `Dn`, parity goldens that bind the current behaviour, or new scope.

# Enterprise handoff: apply the workspace implementation

Instructions for the agent (Claude Code or equivalent) that runs inside the enterprise environment with a Databricks CLI profile. Everything below was built and verified without a workspace: the code, the bundle and the scripts were exercised against a loopback stand-in (`tests/workspace_stub.py`, D28) and Docker Postgres. Your job is to repeat the workspace-dependent steps for real, record what you find, and change nothing that is not listed here.

Read first: `CLAUDE.md`, `docs/DEPLOYMENT.md`, `docs/rebuild/blockers.md` (B2, B9), `docs/rebuild/decisions.md` (D17, D23, D28, F27).

## Hard limits

- Never print, log, echo or write a token, secret, connection string or minted credential. Pipe `databricks auth token` output straight into the consumer; never into a file or a variable you then print.
- Never weaken a gate: no lowered threshold, no new `noqa`, `type: ignore`, `nosec`, `pragma` or skip, no excluded path.
- Never edit `vendor/deploy-v/`. Never push to a remote unless the owner says so; commit on `rebuild/databricks`.
- Never delete or recreate a workspace resource you did not create in this session. `databricks bundle destroy` and `databricks apps delete` are off limits.
- A failing test or gate is not a blocker; fix it. A missing external resource is a blocker: record it in `docs/rebuild/blockers.md` with the exact command and error, then continue with every step that does not depend on it.
- A finding you fix goes in `docs/rebuild/decisions.md` as the next `Fn`. New scope goes in `docs/rebuild/next.md`, not into the code.

## Inputs you must have (ask the owner for any that is missing)

| Value | Used as |
|---|---|
| CLI profile name, already logged in (`databricks auth profiles` lists it) | `-p <profile>` and `DATABRICKS_CONFIG_PROFILE` |
| Unity Catalog catalog and schema | `--var uc_catalog=` `--var uc_schema=` |
| Lakebase provisioned instance name (and database, default `databricks_postgres`) | `--var lakebase_instance=` `--var lakebase_database=` |
| AI Gateway serving endpoint that serves a Claude model | `--var model_endpoint=` (default `databricks-claude-opus-5`) |
| That endpoint's dated per-token price from the enterprise contract | `--var model_price=<endpoint>,<input_per_token>,<output_per_token>,<YYYY-MM-DD>` |
| Two workspace groups for ADMIN and ANALYST (defaults `caos-admins`, `caos-analysts`) | `--var group_admin=` `--var group_analyst=` |

Below, `<profile>`, `<catalog>` and the rest are placeholders: substitute the real values and drop the angle brackets before running anything.

## Steps, in order

Each step names what to record. Keep a log of every command and its exit code; the report at the end is built from it.

**0. Preconditions.**

```bash
uv --version && node --version && databricks --version
databricks auth profiles
databricks current-user me -p <profile>
uv sync --locked --all-groups
npm --prefix frontend ci --ignore-scripts && npm --prefix frontend run build
docker compose up -d --wait
```

Python must resolve to 3.13 (`uv run python --version`). If `databricks current-user me` fails, stop: authentication is the owner's to fix.

**1. Local gates are green before anything touches the workspace.** Run the full matrix in `docs/rebuild/runs/2026-09-22/acceptance/run.sh` (copy it to a new dated directory, `docs/rebuild/runs/<today>/acceptance/`). Every row except A30 must exit 0 before you continue; A34 (the stand-in validate) must exit 0 too.

**2. Preflight the resources.** Nothing is created by this script; it prints the command an administrator runs for each missing resource.

```bash
DATABRICKS_CONFIG_PROFILE=<profile> uv run python scripts/preflight.py \
  --endpoint <endpoint> --catalog <catalog> --schema <schema> \
  --lakebase-instance <instance> --group-admin <admin-group> --group-analyst <analyst-group>
```

Record the six lines. A `MISSING` line is a blocker unless you are authorised to create that resource; the volume is the one you may create yourself when the schema exists: `CREATE VOLUME <catalog>.<schema>.caos_blobs` through `databricks api post /api/2.1/unity-catalog/volumes` or SQL.

**3. Validate the bundle against the real workspace (A30).**

```bash
databricks bundle validate -t prod -p <profile> \
  --var model_endpoint=<endpoint> --var model_price=<endpoint>,<in>,<out>,<date> \
  --var uc_catalog=<catalog> --var uc_schema=<schema> \
  --var lakebase_instance=<instance> --var lakebase_database=<database> \
  --var group_admin=<admin-group> --var group_analyst=<analyst-group>
```

Record the exit code and the last line. This closes blocker B9's validate half; update B9 with the command and its output (no host, no token).

**4. Deploy and start.** Same `--var` flags as step 3 on every bundle command.

```bash
databricks bundle deploy -t prod -p <profile> --var ...
databricks bundle run caos -t prod -p <profile>
databricks apps get caos -p <profile>
```

`app_status.state` must be `RUNNING`. If deploy fails on a resource grant (`CAN_QUERY`, `CAN_CONNECT_AND_CREATE`, `WRITE_VOLUME`), the app's service principal lacks a permission the bundle asked for; record the exact error as a blocker and ask an administrator. Do not edit `databricks.yml` to drop a resource.

**5. Health.** The app URL is behind workspace sign-in, so present a token without ever printing it:

```bash
APP_URL="$(databricks apps get caos -p <profile> | jq -r .url)"
curl -fsS "$APP_URL/api/health" -H "Authorization: Bearer $(databricks auth token -p <profile> | jq -r .access_token)"
```

Expect HTTP 200, `python_version` starting `3.13`, `status: ready`, a `build_id`. Record the body minus nothing sensitive (it contains none). If `python_version` is not 3.13, the platform did not install from `uv.lock`; check that no `requirements.txt` was added at the root and that `pyproject.toml` still pins `requires-python = ">=3.13,<3.14"`.

**6. Gateway smoke (A31).** Spends a few tokens; both calls go through the production factory, the second in JSON mode (F27).

```bash
DATABRICKS_CONFIG_PROFILE=<profile> CAOS_MODEL_ENDPOINT=<endpoint> \
  CAOS_MODEL_PRICE=<endpoint>,<in>,<out>,<date> uv run python scripts/gateway_smoke.py
```

Expect exit 0 and one line ending `json_mode=accepted`. Any other `json_mode=` value means the endpoint rejects `response_format`; record it as a finding, do not remove the parameter, and ask the owner which endpoint to use instead.

**7. Lakebase version (D17).** Connect as yourself with a minted credential and record `SELECT version()` in `docs/rebuild/decisions.md` under D17.

```bash
PGHOST="$(databricks database get-database-instance <instance> -p <profile> | jq -r .read_write_dns)"
DATABRICKS_CONFIG_PROFILE=<profile> CAOS_LAKEBASE_INSTANCE=<instance> \
  PGHOST="$PGHOST" PGPORT=5432 PGDATABASE=<database> PGUSER="$(databricks current-user me -p <profile> | jq -r .userName)" \
  uv run python -c "import psycopg; from caos.store.lakebase import store_url; print(psycopg.connect(store_url()).execute('SELECT version()').fetchone()[0])"
```

If the major version is below 17, run the migrations' compatibility check: `CAOS_DATABASE_URL` is never set here; instead confirm the app's own start applied the schema by reading `databricks apps logs caos -p <profile>` for `migrations applied` and no `STORE_` refusal.

**8. The event stream through the Apps proxy (C42).** Create a case in the workspace UI (or through the API with the same bearer), then watch its stream and confirm events arrive incrementally rather than in one buffered burst:

```bash
curl -N -sS "$APP_URL/api/v1/cases/<case-id>/events" \
  -H "Authorization: Bearer $(databricks auth token -p <profile> | jq -r .access_token)" | head -c 2000
```

Trigger a governed write on the case from a second shell while this runs. If lines appear as the write happens, C42 holds; record it. If nothing arrives until the connection closes, the proxy buffers: record `Fn` in `decisions.md`, log the polling fallback in `docs/rebuild/next.md`, and tell the owner; do not build the fallback unasked.

**9. One governed run end to end.** In the UI: upload a small public document, approve the run's gate, watch the Run section reach COMPLETE or BLOCKED, open the deliverable. Then confirm the bytes landed in the volume:

```bash
databricks fs ls dbfs:/Volumes/<catalog>/<schema>/caos_blobs -p <profile> | head
```

**10. Optional live provider tests.** Only if the owner exports `OPENROUTER_API_KEY` into your shell (never into a file):

```bash
CAOS_REQUIRE_PROVIDER=1 CAOS_REQUIRE_POSTGRES=1 uv run pytest --no-cov -m live_provider tests/graph
```

**11. Record and commit.** Update `docs/rebuild/blockers.md` (B2 and B9 resolved with the commands and their last lines; the profile name is fine, the host and any token are not), `docs/rebuild/decisions.md` (D17; any `Fn`), the dated evidence table (A30, A31 and A34 with real exit codes), then:

```bash
uv run pre-commit run --all-files
git add -A && git commit -m "Enterprise deploy: A30/A31 against <profile>, D17 recorded"
```

Do not push unless told.

## Report back

One message, standing alone: the evidence table for the rows you ran (id, command, exit, last line), each blocker you added or resolved verbatim, each `Fn` you added, the Lakebase version, whether C42 held, and the app URL's health line. Nothing in the report may be a secret or a host name the owner has not already written down.

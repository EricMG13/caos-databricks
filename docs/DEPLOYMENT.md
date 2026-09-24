# Deploying CAOS to an enterprise Databricks workspace

This repository deploys as one Databricks App from an asset bundle. Nothing in the tree names a workspace: every value that differs per deployment is a bundle variable, and authentication comes from the Databricks CLI profile of whoever deploys. The steps below are what a workspace administrator runs once, then what a deployer runs per release. The gateway path is marked unverified in `docs/rebuild/blockers.md` until step 5 has been run in a real workspace.

## 1. Prerequisites in the workspace

| Resource | Bundle variable | Notes |
|---|---|---|
| A serving endpoint under AI Gateway that serves a Claude model | `model_endpoint` (default `databricks-claude-opus-5`) | Pay-per-token Foundation Model API endpoints work as they are; an external-model endpoint must be created under Serving with AI Gateway enabled. The app's service principal needs `CAN_QUERY`; the bundle grants it. |
| A dated price for exactly that endpoint | `model_price` | `endpoint,input_per_token,output_per_token,YYYY-MM-DD`. Budgets fail closed on it; the default names the public list price on the day this repository was written and must be checked against the workspace's contract. |
| A Unity Catalog schema and a volume `caos_blobs` in it | `uc_catalog`, `uc_schema` | `CREATE VOLUME <catalog>.<schema>.caos_blobs`. Sources and artifacts live there by digest; the app's service principal needs `WRITE_VOLUME` (granted by the bundle). |
| A Lakebase (provisioned) instance | `lakebase_instance`, `lakebase_database` (default `databricks_postgres`) | The store's schema is applied on first start, in schema `public`; LangGraph checkpoints go to schema `caos_graph` on the same database. The app's service principal needs `CAN_CONNECT_AND_CREATE` (granted by the bundle), which the Apps documentation describes as `CONNECT` and `CREATE` on the database. It also needs `USAGE` and `CREATE` on schema `public`, which that grant does not name and PostgreSQL 15 and later give nobody by default (MAX-22; what Lakebase grants there by default has not been observed). Once the app exists (after its first `bundle deploy`, so on a first run of the one command E6 reports `store` not `OK`), the instance's owner runs `GRANT USAGE, CREATE ON SCHEMA public TO "<service_principal_client_id>";` in that database, the id being what `databricks apps get <app>` reports, and runs the command again. `tests/test_platform_boot.py` starts the app holding exactly these grants, and shows the database grants alone refused. |
| Two workspace groups | `group_admin` (default `caos-admins`), `group_analyst` (default `caos-analysts`) | Members of the admin group act as ADMIN, of the analyst group as ANALYST; any other authenticated user is READER. |
| What one run may spend | `run_ceiling` (default `100.00`, D29) | Must cover one worst-case call at `model_price` (about 22.61 at the default price); preflight refuses less (F28). |
| The forwarded-token preview | none | `forward_user_access_token` is a preview feature Databricks must enable for the workspace (F53); row E5 reads it back. Changing it on an existing app needs `databricks apps stop` then `start`. |
| Who may open the app | `group_admin` → `CAN_USE`, `group_analyst` → `CAN_USE` | Granted by the bundle (F50); a user outside both groups is stopped at the proxy. Neither business group manages the app (W3): `CAN_MANAGE` deploys code as the app's principal, which writes the ledger, so only the deployer holds it. Members must be in the groups directly: SCIM `Me` does not expand nested groups. |
| The app's Lakebase role | none | `CAN_CONNECT_AND_CREATE` is expected to provision the app's service principal as a Postgres role; row E6's `store` code says whether it did. |

Check them with the deployer's profile before the first deploy:

```bash
DATABRICKS_CONFIG_PROFILE=<profile> uv run python scripts/preflight.py \
  --endpoint databricks-claude-opus-5 --catalog <catalog> --schema <schema> \
  --lakebase-instance <instance> \
  --price databricks-claude-opus-5,0.000005,0.000025,2026-09-22 --run-ceiling 100.00
```

## 2. Build the tree that ships

```bash
uv sync --locked --all-groups
npm --prefix frontend ci --ignore-scripts && npm --prefix frontend run build
```

`frontend/dist` is git-ignored but included by the bundle's `sync.include`, so the static export the app serves is the one built here.

## 3. One command

```bash
scripts/enterprise_deploy.sh <profile> <catalog> <schema> <lakebase-instance> \
  [<endpoint>] [<endpoint>,<in>,<out>,<YYYY-MM-DD>] [<run-ceiling>]
```

It runs sections 1, 3 and 5 of this page in order and writes one evidence row per step to `docs/rebuild/runs/<today>/enterprise/<time>/evidence.tsv` (E1 preflight; E2–E4 the three bundle commands, E2 being `validate -o json`, whose resolved app name, endpoint, price and run ceiling must be the ones given, DF-4, DF-5; E5 the state and URL of the app E2 resolved; E6 health; E7 the gateway smoke in JSON mode; E8 the Lakebase version for D17; E9 the event stream through the proxy for C42, which must keep delivering frames for 3 s, none more than 1.5 s apart, DF-2; E10 one model call through the app's own HTTP surface, not this script's process or credentials, CF-054: a tiny text source admitted to the case E9 left behind, a LITE run started, and the event stream watched for the first node's call outcome), stopping at the first failure. `TARGET`, `LAKEBASE_DATABASE`, `GROUP_ADMIN`, `GROUP_ANALYST` and `EVIDENCE` are read from the environment when set. The manual commands below are what it runs.

## 3a. Validate and deploy by hand

```bash
export DATABRICKS_BUNDLE_ENGINE=direct                    # the engine every stand-in run used
export BUNDLE_VAR_model_price=<endpoint,in,out,date>      # commas: the CLI splits a --var on them (C1)
VARS=(--var model_endpoint=<endpoint> --var uc_catalog=<catalog> --var uc_schema=<schema>
  --var lakebase_instance=<instance>)                     # and run_ceiling, lakebase_database, the groups when not the defaults
databricks bundle validate -t prod -p <profile> "${VARS[@]}"
databricks bundle validate -t prod -p <profile> -o json "${VARS[@]}" \
  | jq '.resources.apps.caos | {name, env: .config.env}'  # the name and values the app will get
databricks bundle deploy -t prod -p <profile> "${VARS[@]}"
databricks bundle run caos -t prod -p <profile> "${VARS[@]}"   # starts, or restarts on new code
databricks apps get caos -p <profile>                     # app_status.state RUNNING
```

Every one of these commands resolves the whole bundle again, so each takes the same `--var` values and the exported `BUNDLE_VAR_model_price`: a value given to `deploy` is not remembered for `run`, and `uc_catalog`, `uc_schema` and `lakebase_instance` have no default (MAX-N02).

The App installs from `uv.lock` on Python 3.13 (`requires-python`) with `uv run --locked --no-dev` (F49); there is deliberately no `requirements.txt`, which would switch the platform to pip and Python 3.11. `app.yaml` sets no environment: the bundle's `config` is the one source (F52).

## 4. What the app expects at runtime

Set by the platform: `DATABRICKS_HOST`, `DATABRICKS_WORKSPACE_ID` (boot refuses without it, F46), `DATABRICKS_APP_PORT`, `DATABRICKS_APP_NAME`, `DATABRICKS_CLIENT_ID`/`_SECRET`, `PGHOST`/`PGPORT`/`PGDATABASE`/`PGUSER`/`PGSSLMODE` (from the database resource) and `x-forwarded-access-token` on each request (`forward_user_access_token: true`, scope `iam.current-user:read`).

Set by the bundle: `CAOS_BIND_HOST=0.0.0.0`, `CAOS_WORKER_IN_PROCESS=1`, `CAOS_SITE_ROOT=frontend/dist`, `CAOS_MODEL_ENDPOINT`, `CAOS_MODEL_PRICE`, `CAOS_RUN_CEILING`, `CAOS_BLOB_ROOT=volume:///Volumes/<catalog>/<schema>/caos_blobs`, `CAOS_LAKEBASE_INSTANCE`, `CAOS_GROUP_ADMIN`, `CAOS_GROUP_ANALYST`.

Identity: the platform proxy is the edge. The app reads the forwarded token, resolves the caller through SCIM `Me`, mints a stable subject from the workspace id and the SCIM id, and maps the two group names to roles. Every identity header a client could send is dropped before the API sees it.

## 5. Smoke test after the first deploy

```bash
TOKEN=$(DATABRICKS_CONFIG_PROFILE=<profile> uv run python -c \
  "from databricks.sdk import WorkspaceClient as W; print(W().config.authenticate()['Authorization'])")
curl -fsS -H "Authorization: $TOKEN" \
  "$(databricks apps get caos -p <profile> | jq -r .url)/api/health"
DATABRICKS_CONFIG_PROFILE=<profile> CAOS_MODEL_ENDPOINT=<endpoint> \
  CAOS_MODEL_PRICE=<endpoint,in,out,date> uv run python scripts/gateway_smoke.py
```

`/api/health` sits behind the Apps proxy like every other route: an unauthenticated request never reaches the app, so the curl above carries the same bearer `scripts/enterprise_deploy.py`'s `_headers()` reads from the SDK's unified auth (`WorkspaceClient().config.authenticate()`). `$TOKEN` holds the word `Bearer` and the token together; nothing here prints it, and it belongs in a variable, never in a logged command line.

Health must answer 200 with `python_version` starting `3.13` and `status: ready`; the smoke script must print the endpoint, `model=ChatDatabricks`, a response id and token usage. Record the Lakebase `SELECT version()` on first connection in `docs/rebuild/decisions.md` (D17).

## 6. Rolling back a release

A rollback is a redeploy: check out the previous commit and run the same one command (section 3) against it, or run section 3a by hand at that commit. There is no separate rollback path or script, because there is nothing else to run -- `bundle deploy` overwrites the app's code and restarts it on whatever commit is checked out, the same as any other release.

What a rollback does not undo is the store's schema: migrations (`caos/store/0002_*.sql` onward) are ordered, forward-only and applied additively on boot (`apply_schema`), with no corresponding "down" migration for any of them. Rolling code back to a commit from before a migration was added leaves that migration's tables and columns in place; the older code simply never reads them, which is safe only because every migration to date is additive (a new table or a new nullable column, never a rename or a drop). If a future migration ever needs to remove or rename something, redeploying the older code is not a safe way to undo it, and that migration's own entry should say so. The accepted-attempt ledger and the audit chain are append-only regardless (invariant 6), so a rollback never rewrites or loses either.

## 7. Operating notes

- The app is `caos` in the `prod` target only. In `dev` it is `caos-dev-<user id>`, each developer's own app (an app name is unique in the workspace, and the numeric SCIM id keeps to the Apps name rule of lowercase letters, digits and hyphens), and in any other target `caos-<target>` (DP-6, DF-5). A target added later therefore never deploys over the production app; the one command's E5 row looks up the name E2 resolved, and E2 fails if a target other than `prod` resolves to `caos`.
- Preflight refuses an endpoint that logs payloads (an AI Gateway inference table, the legacy auto-capture, or a `telemetry_config` inference table that is named or samples any request), that exports logs or traces through `telemetry_config` (metrics alone are fine), that falls back to another model, or that serves more than one entity; the same rules are applied to an update still pending on the endpoint (DP-3, DF-3). Every prompt carries document text, and the host prices one model per endpoint. Guardrails are reported, not refused.
- A deploy of the `prod` target that was interrupted leaves its lock at `/Workspace/caos-bundle/prod/state/deploy.lock`, and the next `bundle deploy` (E3) stops and names the lock's holder. Ask that person whether a deploy is still running; only when none is, rerun with `databricks bundle deploy --force-lock` (DF-12).
- CLI 1.17.0 panics during `bundle deploy` (a Go stack trace naming `OverrideChangeDesc`) when the app its state records was deleted outside the bundle and the release changes the app's configuration, a price rotation for instance (DF-13). Run `databricks bundle deployment unbind caos -t <target> -p <profile>` with the same variables, then deploy again: the deploy creates the app anew. Raise `databricks_cli_version` once a CLI release no longer panics.
- `PGSSLMODE=require` encrypts but does not authenticate the Lakebase server (MX-7). Where the workspace publishes a CA bundle, set `PGSSLMODE=verify-full` and `PGSSLROOTCERT` in the bundle's `config.env`; libpq reads both.
- The gateway smoke (E7) makes two paid calls outside the budget ledger (AI-8): a documented exception, once per deploy.
- E9 and E10 leave one governed case behind per deploy, titled `CAOS deployment check (safe to archive)` so an operator who opens it recognises it at a glance: it exists only to prove the event stream delivers through the Apps proxy (E9) and that one model call reaches the gateway through the app's own HTTP surface (E10, CF-054), never through this script's process or credentials. It costs one tiny admitted source and one model call at the configured price, same as any other run. It is safe to leave in place (every later deploy makes its own) or for an admin to archive; nothing reads it back.

- The worker runs inside the app process (one run at a time). A queued run waits while the app restarts; leases expire and the run is reclaimed.
- Secrets: the app reads none. Model calls use the service principal's OAuth; Lakebase credentials are minted per connection and never logged.
- Logs never carry document text: refusals are typed codes (`caos/refusals.py`).
- To rotate the model: change `model_endpoint` and `model_price` together and redeploy; runs pinned under the old price finish under it.

## 8. Before the workspace exists: the loopback stand-in

`tests/workspace_stub.py` (D28) answers, on `127.0.0.1`, every workspace path this repository's code and the CLI use, so the whole chain can be exercised with no profile:

```bash
uv run python tests/workspace_stub.py -- databricks bundle validate -t dev \
  --var uc_catalog=main --var uc_schema=caos --var lakebase_instance=caos-lb
CAOS_REQUIRE_POSTGRES=1 uv run pytest --no-cov tests/test_workspace_stub.py
```

The first ends with `Validation OK!` and lists the paths the CLI asked for (`bundle deploy` and `bundle run caos` pass the same way; the `prod` target, deployment lock and all, runs its validate, deploy and run under one stub with `sh -c` (A37); the stub answers a taken app name with 409, a name outside the Apps rule with 400 and a write that would replace a held lock with 409, keeps each deployment's command and environment, and serves `workspace/export` as the platform does; and `scripts/check_gate_config.py --shipped .databricks/bundle/dev/deployment.json` then checks that what the deploy synced holds every tracked file under the sync roots and every file of the built export, so build the export first). Each stand-in run is a new, empty workspace, so a `bundle` command under the stub first clears the bundle state an earlier stand-in run left in `.databricks/bundle`, and refuses to run over state a real workspace wrote (DF-13). The second runs the gateway smoke, `scripts/preflight.py`, SCIM identity, the volume backend, the Lakebase checkpointer and a LITE route through `ChatDatabricks` over HTTP. `tests/test_platform_boot.py` goes further: it boots `python -m caos.serve` under the platform's own environment against the stub and the Docker Postgres and drives a governed run through the HTTP surface to COMPLETE; `tests/test_enterprise_deploy.py` runs the one command of section 3 against that. What the stand-in cannot tell you: whether the workspace grants what the bundle asks for, how its Apps proxy treats the event stream (C42), the Lakebase major version (D17), or what a real model answers. The one command reports each of those the first time it runs there; the instruction for that run is `docs/rebuild/ENTERPRISE_HANDOFF.md`.

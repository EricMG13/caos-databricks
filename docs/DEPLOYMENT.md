# Deploying CAOS to an enterprise Databricks workspace

This repository deploys as one Databricks App from an asset bundle. Nothing in the tree names a workspace: every value that differs per deployment is a bundle variable, and authentication comes from the Databricks CLI profile of whoever deploys. The steps below are what a workspace administrator runs once, then what a deployer runs per release. The gateway path is marked unverified in `docs/rebuild/blockers.md` until step 5 has been run in a real workspace.

## 1. Prerequisites in the workspace

| Resource | Bundle variable | Notes |
|---|---|---|
| A serving endpoint under AI Gateway that serves a Claude model | `model_endpoint` (default `databricks-claude-opus-5`) | Pay-per-token Foundation Model API endpoints work as they are; an external-model endpoint must be created under Serving with AI Gateway enabled. The app's service principal needs `CAN_QUERY`; the bundle grants it. |
| A dated price for exactly that endpoint | `model_price` | `endpoint,input_per_token,output_per_token,YYYY-MM-DD`. Budgets fail closed on it; the default names the public list price on the day this repository was written and must be checked against the workspace's contract. |
| A Unity Catalog schema and a volume `caos_blobs` in it | `uc_catalog`, `uc_schema` | `CREATE VOLUME <catalog>.<schema>.caos_blobs`. Sources and artifacts live there by digest; the app's service principal needs `WRITE_VOLUME` (granted by the bundle). |
| A Lakebase (provisioned) instance | `lakebase_instance`, `lakebase_database` (default `databricks_postgres`) | The store's schema is applied on first start; LangGraph checkpoints go to schema `caos_graph` on the same database. The app's service principal needs `CAN_CONNECT_AND_CREATE` (granted by the bundle). |
| Two workspace groups | `group_admin` (default `caos-admins`), `group_analyst` (default `caos-analysts`) | Members of the admin group act as ADMIN, of the analyst group as ANALYST; any other authenticated user is READER. |
| What one run may spend | `run_ceiling` (default `25.00`) | Must cover one worst-case call at `model_price` (about 6.88 at the default price); preflight refuses less (F28). |
| The forwarded-token preview | none | `forward_user_access_token` is a preview feature Databricks must enable for the workspace (F53); row E5 reads it back. Changing it on an existing app needs `databricks apps stop` then `start`. |
| Who may open the app | `group_admin` → `CAN_MANAGE`, `group_analyst` → `CAN_USE` | Granted by the bundle (F50); a user outside both groups is stopped at the proxy. Members must be in the groups directly: SCIM `Me` does not expand nested groups. |
| The app's Lakebase role | none | `CAN_CONNECT_AND_CREATE` is expected to provision the app's service principal as a Postgres role; row E6's `store` code says whether it did. |

Check them with the deployer's profile before the first deploy:

```bash
DATABRICKS_CONFIG_PROFILE=<profile> uv run python scripts/preflight.py \
  --endpoint databricks-claude-opus-5 --catalog <catalog> --schema <schema> \
  --lakebase-instance <instance> \
  --price databricks-claude-opus-5,0.000005,0.000025,2026-09-22 --run-ceiling 25.00
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

It runs sections 1, 3 and 5 of this page in order and writes one evidence row per step to `docs/rebuild/runs/<today>/enterprise/evidence.tsv` (E1 preflight, E2–E4 the three bundle commands, E5 the app state and URL, E6 health, E7 the gateway smoke in JSON mode, E8 the Lakebase version for D17, E9 the event stream through the proxy for C42), stopping at the first failure. `TARGET`, `LAKEBASE_DATABASE`, `GROUP_ADMIN`, `GROUP_ANALYST` and `EVIDENCE` are read from the environment when set. The manual commands below are what it runs.

## 3a. Validate and deploy by hand

```bash
databricks bundle validate -t prod -p <profile> \
  --var model_endpoint=<endpoint> --var uc_catalog=<catalog> --var uc_schema=<schema> \
  --var lakebase_instance=<instance> --var model_price=<endpoint,in,out,date>
databricks bundle deploy -t prod -p <profile> --var ...   # same variables
databricks bundle run caos -t prod -p <profile>           # starts, or restarts on new code
databricks apps get caos -p <profile>                     # app_status.state RUNNING
```

The App installs from `uv.lock` on Python 3.13 (`requires-python`) with `uv run --locked --no-dev` (F49); there is deliberately no `requirements.txt`, which would switch the platform to pip and Python 3.11. `app.yaml` sets no environment: the bundle's `config` is the one source (F52).

## 4. What the app expects at runtime

Set by the platform: `DATABRICKS_HOST`, `DATABRICKS_APP_PORT`, `DATABRICKS_APP_NAME`, `DATABRICKS_CLIENT_ID`/`_SECRET`, `PGHOST`/`PGPORT`/`PGDATABASE`/`PGUSER`/`PGSSLMODE` (from the database resource) and `x-forwarded-access-token` on each request (`forward_user_access_token: true`, scope `iam.current-user:read`).

Set by the bundle: `CAOS_BIND_HOST=0.0.0.0`, `CAOS_WORKER_IN_PROCESS=1`, `CAOS_SITE_ROOT=frontend/dist`, `CAOS_MODEL_ENDPOINT`, `CAOS_MODEL_PRICE`, `CAOS_UC_SCHEMA`, `CAOS_BLOB_ROOT=volume:///Volumes/<catalog>/<schema>/caos_blobs`, `CAOS_LAKEBASE_INSTANCE`, `CAOS_GROUP_ADMIN`, `CAOS_GROUP_ANALYST`.

Identity: the platform proxy is the edge. The app reads the forwarded token, resolves the caller through SCIM `Me`, mints a stable subject from the workspace id and the SCIM id, and maps the two group names to roles. Every identity header a client could send is dropped before the API sees it.

## 5. Smoke test after the first deploy

```bash
curl -fsS "$(databricks apps get caos -p <profile> | jq -r .url)/api/health"
DATABRICKS_CONFIG_PROFILE=<profile> CAOS_MODEL_ENDPOINT=<endpoint> \
  CAOS_MODEL_PRICE=<endpoint,in,out,date> uv run python scripts/gateway_smoke.py
```

Health must answer 200 with `python_version` starting `3.13` and `status: ready`; the smoke script must print the endpoint, `model=ChatDatabricks`, a response id and token usage. Record the Lakebase `SELECT version()` on first connection in `docs/rebuild/decisions.md` (D17).

## 6. Operating notes

- The worker runs inside the app process (one run at a time). A queued run waits while the app restarts; leases expire and the run is reclaimed.
- Secrets: the app reads none. Model calls use the service principal's OAuth; Lakebase credentials are minted per connection and never logged.
- Logs never carry document text: refusals are typed codes (`caos/refusals.py`).
- To rotate the model: change `model_endpoint` and `model_price` together and redeploy; runs pinned under the old price finish under it.

## 7. Before the workspace exists: the loopback stand-in

`tests/workspace_stub.py` (D28) answers, on `127.0.0.1`, every workspace path this repository's code and the CLI use, so the whole chain can be exercised with no profile:

```bash
uv run python tests/workspace_stub.py -- databricks bundle validate -t dev \
  --var uc_catalog=main --var uc_schema=caos --var lakebase_instance=caos-lb
CAOS_REQUIRE_POSTGRES=1 uv run pytest --no-cov tests/test_workspace_stub.py
```

The first ends with `Validation OK!` and lists the paths the CLI asked for (`bundle deploy` and `bundle run caos` pass the same way, and `scripts/check_gate_config.py --shipped .databricks/bundle/dev/deployment.json` then checks that what the deploy synced holds everything the app needs); the second runs the gateway smoke, `scripts/preflight.py`, SCIM identity, the volume backend, the Lakebase checkpointer and a LITE route through `ChatDatabricks` over HTTP. `tests/test_platform_boot.py` goes further: it boots `python -m caos.serve` under the platform's own environment against the stub and the Docker Postgres and drives a governed run through the HTTP surface to COMPLETE; `tests/test_enterprise_deploy.py` runs the one command of section 3 against that. What the stand-in cannot tell you: whether the workspace grants what the bundle asks for, how its Apps proxy treats the event stream (C42), the Lakebase major version (D17), or what a real model answers. The one command reports each of those the first time it runs there; the instruction for that run is `docs/rebuild/ENTERPRISE_HANDOFF.md`.

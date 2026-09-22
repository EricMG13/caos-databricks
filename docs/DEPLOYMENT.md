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

Check them with the deployer's profile before the first deploy:

```bash
DATABRICKS_CONFIG_PROFILE=<profile> uv run python scripts/preflight.py \
  --endpoint databricks-claude-opus-5 --catalog <catalog> --schema <schema> \
  --lakebase-instance <instance>
```

## 2. Build the tree that ships

```bash
uv sync --locked --all-groups
npm --prefix frontend ci --ignore-scripts && npm --prefix frontend run build
```

`frontend/dist` is git-ignored but included by the bundle's `sync.include`, so the static export the app serves is the one built here.

## 3. Validate and deploy

```bash
databricks bundle validate -t prod -p <profile> \
  --var model_endpoint=<endpoint> --var uc_catalog=<catalog> --var uc_schema=<schema> \
  --var lakebase_instance=<instance> --var model_price=<endpoint,in,out,date>
databricks bundle deploy -t prod -p <profile> --var ...   # same variables
databricks bundle run caos -t prod -p <profile>           # starts, or restarts on new code
databricks apps get caos -p <profile>                     # app_status.state RUNNING
```

The App installs from `uv.lock` on Python 3.13 (`requires-python`); there is deliberately no `requirements.txt`, which would switch the platform to pip and Python 3.11.

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

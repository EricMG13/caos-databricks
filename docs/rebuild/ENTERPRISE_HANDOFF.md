# Enterprise handoff: what only the workspace can do

For the implementer inside the enterprise: an agent (Claude Opus 5 in Claude Code, or equivalent) or a person, holding a Databricks CLI profile for the enterprise workspace. Everything that needs no workspace is built and verified: the process boots the way Databricks Apps boots it, a governed run completes through the gateway seam, the bundle validates, deploys and runs, and the one deployment command has been exercised end to end, all against a loopback stand-in for the workspace (D28) and a Docker Postgres for Lakebase. What is left needs the workspace's own knowledge and access, and it is all in this page: the values only the enterprise knows, the one command, the steps after it, and what you must not do.

> **Status, 2026-10-07.** AI Gateway is disabled in the enterprise workspace (`docs/rebuild/blockers.md` B12). Model calls go to GitHub Copilot from a worker on the analyst's PC: follow `docs/COPILOT_WORKER.md` in place of the steps here that need a serving endpoint (D77-D79). It has not yet run on a real seat (N185). Lakebase, the volume and the groups below still apply. Whether Databricks Apps may host the API and UI is still the administrator's answer.

Read `docs/DEPLOYMENT.md` beside this page (the runbook the command follows). Background, only when a row points there: `docs/rebuild/blockers.md` (B2, B9), `docs/rebuild/decisions.md` (D17, D28, D29, D30, D75, F468–F472), `qualification/PROVIDER_RUNBOOK.md` (what has and has not been qualified live).

## 1. Do not

Each of these is a hard stop. If a step seems to need one, stop and ask the owner.

- **No secrets in the open.** Never print, log, echo, commit or paste into chat a token, secret, connection string, minted credential or workspace host name. The CLI profile is the whole of your authentication; nothing here asks you for a credential.
- **No change to the product to get past a failure.** Never edit `vendor/deploy-v/` (invariant 4), the prompts or stage contracts under `icm/`, the validators, the refusal rules, a gate, a test, `tests/gate_baseline.json`, or `databricks.yml` (to drop a resource, add a `host`, `profile` or credential, or change a default). A failing step is reported with its row and log, never worked around.
- **No destruction.** Never run `databricks bundle destroy`, `databricks apps delete`, `databricks bundle deploy --force-lock`, or `databricks bundle deployment unbind`/`bind` without the owner's word for that run. Never delete or recreate a workspace resource you did not create in this session. Never switch an app from one Lakebase kind to the other (`docs/DEPLOYMENT.md` section 7).
- **No permission beyond the list.** Grant `CAN_QUERY` only on the endpoints the owner approved, only to the app's service principal, and only with `update-permissions` (it adds). `set-permissions` replaces an endpoint's whole access list and would lock everyone else out: never use it. Never widen the app's `CAN_USE` beyond the two groups, and never give a business group `CAN_MANAGE` (W3).
- **No model the owner did not approve, and no gateway setting changed to fit the app.** Every prompt carries the case's document text. Do not add an endpoint to `model_endpoint` or `model_choices` that the owner has not approved for that data, and do not turn off an endpoint's payload logging, fallback or telemetry yourself because preflight refused it: the owner decides (step 2). Do not use an endpoint that adds retrieval, tools or web search on the provider side: sources are the case's pinned documents only (invariant 1).
- **No other provider.** Production calls go through `caos.models`: to AI Gateway or to GitHub Copilot for a `copilot:` or `copilot-cli:` model. OpenRouter and every other adapter under `tests/` are for this repository's own tests only.
- **No reasoning-effort setting.** `CAOS_REASONING_EFFORT` is refused at start (N2): the host does not send it yet. A Copilot model's effort is part of its name (D77).
- **No spend without an amount.** A qualification run and the first governed runs cost real money. Start one only against a ceiling the owner authorised for it, and retry a refused node at most once (D30 already gives it one second attempt).
- **No push, no merge.** Commit on a branch; the owner pushes and merges.

## 2. Get these decisions from the owner first

Nothing below can be defaulted from this repository.

| Decision | Why it is theirs |
|---|---|
| Which serving endpoints are approved to receive the case's document text, which one is the configured default, and which, if any, are offered as other choices | Every prompt carries document text. An external-model endpoint sends it to that model's provider; a Databricks-hosted one keeps it in the workspace. `databricks serving-endpoints get <name> -p <profile> -o json` shows which (`served_entities[].external_model` versus `foundation_model`). |
| Each approved endpoint's dated per-token price, input and output, in dollars | Budgets fail closed on it (invariant 8). A pay-per-token Foundation Model API endpoint bills DBUs: its DBUs per token times the contract's price per DBU. An external-model endpoint bills the provider's contract rates. A provisioned-throughput endpoint bills by the hour: no per-token price is exact, so the owner names the figure the budgets reserve on. |
| What a run may spend (`run_ceiling`, default 120.00) and what the qualification run may spend | Each run's ceiling must cover one worst-case call at its model's price (about 22.61 at 5/25 dollars per million tokens, D29); preflight checks every approved model against it. |
| What happens if an approved endpoint logs payloads, exports traces, has a fallback or serves more than one model | Preflight refuses each (DP-3). If the workspace's policy requires payload logging, the app cannot run on that endpoint as built: that is a policy conflict for the owner, not a setting for you to change. |
| The Lakebase kind: an Autoscaling project (the default) or an existing Provisioned instance | An app keeps the kind it was first deployed with. |
| The two groups, if not `caos-admins` and `caos-analysts` | Members must be direct members: SCIM `Me` does not expand nested groups (B9). |

## 3. What you need in hand

| Value | Where it goes | How to find it |
|---|---|---|
| A CLI profile, already logged in | argument 1 | `databricks auth profiles` |
| Unity Catalog catalog and schema | arguments 2 and 3 | The volume is `<catalog>.<schema>.caos_blobs`; you may create the volume yourself once the schema exists (`CREATE VOLUME`). |
| Lakebase Autoscaling project id, or an existing Provisioned instance's name with `--provisioned` | argument 4 | `databricks postgres list-projects -p <profile>`. Branch, read-write endpoint and database id default to `production`, `primary`, `databricks-postgres`; override with `LAKEBASE_BRANCH`, `LAKEBASE_ENDPOINT`, `LAKEBASE_DATABASE_ID` (`databricks postgres list-databases projects/<project>/branches/<branch>`), or `LAKEBASE_DATABASE` for a Provisioned instance. |
| The configured endpoint's exact name | argument 5, required | `databricks serving-endpoints list -p <profile>`. Custom and external endpoints rarely carry the `databricks-` prefix, and the bundle's default `databricks-claude-opus-5` may not exist in this workspace. |
| That endpoint's dated contract price | argument 6, required | `<endpoint>,<input_per_token>,<output_per_token>,<YYYY-MM-DD>`, dated no later than today; the first field must be argument 5 exactly. |
| The run ceiling | argument 7 (default 120.00) | From the owner. |
| The other approved models, if any | argument 8 (default none) | Each one's price in argument 6's form, joined by `;`, quoted: `'<endpoint>,<in>,<out>,<date>;<endpoint>,<in>,<out>,<date>'`. At most 15 beside the configured one. |
| The groups and the target | environment | `GROUP_ADMIN`, `GROUP_ANALYST`, `TARGET` (`prod` or `dev` only; `--provisioned` deploys its pair). The app is `caos` in both production targets and `caos-dev-<your user id>` in `dev`. |

No grant is run by hand before the first deploy: the bundle's `CAN_CONNECT_AND_CREATE` lets the app create its own schemas, `caos_store` and `caos_graph`.

## 4. Steps

### 4.1 Build and deploy

```bash
uv sync --locked --all-groups
npm --prefix frontend ci --ignore-scripts && npm --prefix frontend run build
scripts/enterprise_deploy.sh <profile> <catalog> <schema> <lakebase-project> \
  <endpoint> <endpoint>,<in>,<out>,<date> 120.00 '<choice>,<in>,<out>,<date>;...'
# or, for an existing Provisioned instance only:
scripts/enterprise_deploy.sh --provisioned <profile> <catalog> <schema> <lakebase-instance> \
  <endpoint> <endpoint>,<in>,<out>,<date> 120.00 '<choice>,<in>,<out>,<date>;...'
```

Leave argument 8 off when the owner approved one model only. The command stops at the first failing row and writes `docs/rebuild/runs/<today>/enterprise/<time>/evidence.tsv`, one row per step, with each step's output in `E<n>.log` beside it (section 5).

### 4.2 Grant each other approved model to the app

Only when argument 8 named models. The bundle grants `CAN_QUERY` on the configured endpoint alone, so for each other approved endpoint, after E5 shows the app exists:

```bash
databricks apps get caos -p <profile> -o json | jq -r .service_principal_client_id   # the app's application id
databricks serving-endpoints get <endpoint> -p <profile> -o json | jq -r .id        # the endpoint's id
databricks serving-endpoints update-permissions <endpoint id> -p <profile> --json \
  '{"access_control_list":[{"service_principal_name":"<application id>","permission_level":"CAN_QUERY"}]}'
```

If your profile cannot change the endpoint's permissions, ask a workspace administrator to run the third command; record the endpoint as a blocker until it is done. Then check that the endpoint answers the production path, JSON mode included, from your own profile (two small paid calls outside the budget ledger, as E7):

```bash
DATABRICKS_CONFIG_PROFILE=<profile> CAOS_MODEL_ENDPOINT=<endpoint> \
  CAOS_MODEL_PRICE=<endpoint>,<in>,<out>,<date> CAOS_MODEL_CHOICES= \
  uv run python scripts/gateway_smoke.py
```

It must print `model=ChatDatabricks`, a response id, token usage and `json_mode=accepted`. A refusal of the request's `max_tokens` (65,536) or of `response_format` means that endpoint cannot run the app as built: tell the owner, and drop it from `model_choices` by redeploying without it.

### 4.3 Qualify the configured model through the gateway

A green E1 to E10 proves the path to the model, not that the model can complete a governed run. E10's one-line source usually ends in a validated `Blocked` verdict, which counts as an answer. The live record is thin: one qualification set has been qualified end to end, on `openai/gpt-6-luna-pro` in its reasoning mode through OpenRouter. Every other model measured failed CP-0's own severity or confidence-cap rule on nearly every attempt. That includes Claude Opus 5 and 5.5, whose three recorded CP-0 answers were first attempts, each refused by the vendor's severity rule. No module past CP-0, CP-1, CP-1A, CP-3D or CP-5 has been reached by any real model, CP-DR included (`qualification/PROVIDER_RUNBOOK.md`).

So, with a ceiling the owner authorised, qualify the configured endpoint on a tracked set through the same gateway path the app uses:

```bash
docker compose up -d --wait dev-postgres     # the persistent local server (compose.yaml, 127.0.0.1:55436)
mkdir -p .dev-data/qualification-blobs
DATABRICKS_CONFIG_PROFILE=<profile> \
CAOS_MODEL_ENDPOINT=<endpoint> CAOS_MODEL_PRICE=<endpoint>,<in>,<out>,<date> CAOS_MODEL_CHOICES= \
CAOS_QUALIFY_POSTGRES_URL=<the dev-postgres URL, from compose.yaml> \
CAOS_QUALIFY_BLOB_ROOT="$PWD/.dev-data/qualification-blobs" \
uv run python scripts/qualify.py qualification/ccl-fy2025-market-dislocation \
  --expect-identity databricks/<endpoint>/none/65536 --ceiling <authorised amount> \
  --capture .dev-data/qualification-blobs/capture.json
```

`--expect-identity` must be `databricks/<endpoint>/none/65536`: the run refuses before spending anything otherwise. The set is two public documents and two modules (CP-0, CP-3D); the ceiling must cover one worst-case call per case at the endpoint's price. Record the outcome in the set's `RESULT.md` and in `qualification/PROVIDER_RUNBOOK.md`: set, endpoint, identity, database name, spend, and for each node accepted or its stop code. Never record a credential or a host. Repeat for each other approved model only if the owner asks: until a model qualifies, analysts who choose it should expect runs that stop at CP-0 after paying for them.

### 4.4 The first governed run

Open the app URL (row E5), upload a small public document, choose the model, pin the subject, approve the run's gates, start it and watch the Run section. Report how far it got: COMPLETE, a validated `Blocked`, or the stop code with the run id. A refused node already had its one second attempt (D30). Do not retry it more than once, and do not change anything to make it pass.

D38: CP-3 and CP-6 read portfolio, mandate, constraint and sector relative-value inputs only from the case's own sources. Supply the enterprise's maintained workbook as a case source (a CSV export or a PDF), never as a live constraint or a placeholder.

### 4.5 Record and commit

1. `docs/rebuild/blockers.md`: B2 and B9 resolved, quoting the rows' last lines (the profile name is fine; the host and any token are not); a new entry, with the exact command and error, for anything missing.
2. `docs/rebuild/decisions.md`: the Lakebase `SELECT version()` line under D17; each finding as the next `Fn`.
3. Then:

```bash
uv run pre-commit run --all-files
git switch -c enterprise/deploy-<date>
git add docs qualification && git commit -m "Enterprise deploy: E1-E10 against <profile>, D17 recorded"
```

Do not push unless told.

## 5. The rows and what to do when one fails

| Row | What it proves | If it fails |
|---|---|---|
| E1 | Preflight: every approved endpoint exists and is fit (one served entity, no fallback, no payload logging or trace export, pending update included), the schema, volume, Lakebase and both groups exist, and the run ceiling covers one worst-case call at every approved model's price | The log names what is missing and the command an administrator runs to create it. An endpoint refused for its gateway settings is the owner's decision (section 2), not a setting to change. |
| E2 | `databricks bundle validate -o json` resolved the app's name, the endpoint, price, model choices and run ceiling you gave, both group names exactly (in the app's environment and its CAN_USE grants), and the Lakebase kind with its values (`bundle.json` beside the rows) | The bundle or a variable value; the log is the CLI's own message, or names the resolved value that is not the one given. |
| E3 | `databricks bundle deploy` | Usually a grant the deployer or the app's service principal lacks (`CAN_QUERY`, `CAN_CONNECT_AND_CREATE`, `WRITE_VOLUME`) or a Lakebase path the workspace does not hold: record a blocker. A deploy lock held by another deployer, or a CLI panic after the app was deleted out of band, has its recovery in `docs/DEPLOYMENT.md` section 7: run it only after asking the owner. |
| E4 | `databricks bundle run caos` | The app failed to start: `databricks apps logs caos -p <profile>` has the process output, as typed codes only. |
| E5 | The app is RUNNING, has a URL, and reports `forward_user_access_token=True` | `False` means the workspace has not enabled the preview feature (F53): ask Databricks to enable it, then `databricks apps stop caos` and `start`. |
| E6 | `/api/health` answers ready with `python_version` 3.13 and every code `OK`: store, bundle, blobs, identity, workers | A `python_version` other than 3.13 means the platform did not install from `uv.lock` (check that no `requirements.txt` was added). `store` not `OK` on a first deploy is most often the database grant. `workers` absent with `PROVIDER_NOT_CONFIGURED` in the logs is a model price or choice the app could not read. |
| E7 | The gateway smoke on the configured endpoint, JSON mode included (A31) | `json_mode=` other than `accepted` means the endpoint rejects `response_format`: ask the owner which endpoint to use; do not remove the parameter. |
| E8 | Lakebase `SELECT version()` as the deployer, through the chosen kind's API | Copy the version line into `docs/rebuild/decisions.md` under D17 when it succeeds. |
| E9 | The event stream through the Apps proxy: first frame, then frames for 3 s, none more than 1.5 s apart (C42, DF-2). Leaves one case, `CAOS deployment check (safe to archive)` | A frame timeout or a closed stream means the proxy buffers or cuts it: record it as a finding and log the polling fallback in `docs/rebuild/next.md`; do not build it unasked. `unverified` (a 403) means your profile is in neither group: ask to be added, then rerun. |
| E10 | One model call through the app's own HTTP surface on the configured model (CF-054): a one-line source, a LITE run, its first node accepted or ended by a validated `Blocked` verdict (W1) | `the run parked PROVIDER_*: no model call answered` is the gateway refusing or failing the app's service principal (its `CAN_QUERY` grant, a rate limit, the endpoint's state). `the run parked <other code>: the model answered and the host refused the answer` means the gateway works and the model's answer broke the module's contract: record it, and treat step 4.3 as the real test. `no model call answered within <n>s`: check `databricks apps logs caos -p <profile>` and the endpoint's status. |

## 6. What is proven here and what only the workspace can prove

Proven without a workspace, against the loopback stand-in and a Docker Postgres (D28, `docs/DEPLOYMENT.md` section 8):

- The bundle validates, deploys and runs for all four targets.
- The file set a deploy ships boots `python -m caos.serve` from its own tree with every health code OK and completes a governed LITE run through `ChatDatabricks` (`tests/shipped_boot.py`).
- This command runs E1 to E10 against that app (`tests/test_enterprise_deploy.py`).
- A run is pinned to its model and price, and parks rather than moving when the deployment drops that model (`tests/test_model_choice.py`).

Only the workspace can prove what the gap table at the end of `docs/DEPLOYMENT.md` section 8 lists, each with the row that shows it:

- The grants and the app's Lakebase role.
- The forwarded-token preview (E5).
- How the proxy treats the event stream (E9).
- The app's own model call answered by the gateway (E10).
- The Lakebase version (E8) and the platform's install of Python (E6).

Two more need the workspace too:

- Whether each approved model can complete a governed run (step 4.3).
- Whether the other approved models are reachable by the app's service principal (step 4.2).

## 7. Owner decisions still open

None of these blocks the command; each is the owner's:

- OD-10 (N73): whether the second attempt stops relaying values from the model's own answer in the T8 parser's lines.
- OD-11 (N95, N98): the form a register of ten or more columns takes, and which columns of a wide table give way first.
- OD-5's remainder (N16): a migration role the runtime cannot assume, for the enterprise DBA.
- OD-6: account credit, if the modules no real model has reached are to be proven live before the gateway is.
- N117: whether the model select offers a model to analysts before it has qualified.

## 8. Report back

One message, standing alone:

- The ten rows as written (id, exit, last line).
- Each blocker you added or resolved, verbatim, and each `Fn` you added.
- The Lakebase kind you deployed and its version.
- Whether E9 held, and whether E10's call was answered (or the code it parked with).
- The health line.
- For each approved model: granted or not, the smoke's `json_mode`, and the qualification outcome if one was run.

Nothing in it may be a secret or a host name the owner has not already written down.

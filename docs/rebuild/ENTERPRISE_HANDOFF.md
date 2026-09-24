# Enterprise handoff: the workspace values, one command

For the agent (Claude Code or equivalent) or the person who has a Databricks CLI profile for the enterprise workspace. Everything else has been built and verified without a workspace: the process boots the way Databricks Apps boots it, a governed run completes through the gateway seam, the bundle validates, deploys and runs, and the deployment command itself has been exercised, all against a loopback stand-in for the workspace (D28) and a Docker Postgres for Lakebase. Your job is to run that one command against the real workspace and report what it wrote.

Read first if anything is unclear: `docs/DEPLOYMENT.md` (the runbook the command follows), `docs/rebuild/blockers.md` (B2, B9), `docs/rebuild/decisions.md` (D17, D23, D28, F27–F31, D29–D45), `qualification/PROVIDER_RUNBOOK.md` (what has and has not been qualified live).

## Hard limits

- Never print, log, echo or write a token, secret, connection string or minted credential. The command needs none from you: the CLI profile is the whole of its authentication.
- Never weaken a gate, never edit `vendor/deploy-v/`, never push to a remote unless the owner says so; commit on `rebuild/databricks`.
- Never delete or recreate a workspace resource you did not create in this session. `databricks bundle destroy` and `databricks apps delete` are off limits.
- A failing step is reported with its row and log, not worked around. A missing external resource is a blocker: record it in `docs/rebuild/blockers.md` with the exact command and error.

## The values

| Value | Where it goes |
|---|---|
| CLI profile name, already logged in (`databricks auth profiles` lists it) | argument 1 |
| Unity Catalog catalog | argument 2 |
| Schema under it (the volume is `<catalog>.<schema>.caos_blobs`) | argument 3 |
| The Lakebase Autoscaling project id (the default kind; `databricks postgres list-projects` lists them) | argument 4 |
| Or, only for an existing Lakebase Provisioned instance (none can be created since 12 March 2026): its name | argument 4, with `--provisioned` before argument 1 |
| AI Gateway serving endpoint that serves a Claude model | argument 5 (default `databricks-claude-opus-5`) |
| That endpoint's dated per-token price from the enterprise contract | argument 6, as `<endpoint>,<input_per_token>,<output_per_token>,<YYYY-MM-DD>` |
| What one run may spend | argument 7 (default `100.00`: the widest profile at its section bounds plus one worst-case call, D29; it must cover at least one worst-case call, about 22.61 at the default price; raise it for large packs, since evidence is on top) |
| The project's branch, read-write endpoint and database (Autoscaling) | environment: `LAKEBASE_BRANCH` (`production`), `LAKEBASE_ENDPOINT` (`primary`: the endpoint's id, not its path), `LAKEBASE_DATABASE_ID` (`databricks-postgres`: the database's resource id, from `databricks postgres list-databases projects/<project>/branches/<branch>`, not its Postgres name) |
| The instance's database (Provisioned) | environment: `LAKEBASE_DATABASE` (`databricks_postgres`) |
| The two groups, the target | environment: `GROUP_ADMIN` (`caos-admins`), `GROUP_ANALYST` (`caos-analysts`), `TARGET` (`prod` or `dev` only; `--provisioned` deploys its pair, `prod-provisioned` or `dev-provisioned`; the app is `caos` in both production targets, `caos-dev-<your user id>` in `dev`, `caos-devprov-<your user id>` in `dev-provisioned` and `caos-<target>` in any other, DP-6, DF-5) |

No grant is run by hand before the first deploy: the bundle's `CAN_CONNECT_AND_CREATE` gives the app's service principal `CREATE` on the database, and the app creates its own schemas there, `caos_store` and `caos_graph`, rather than writing to `public` (`docs/DEPLOYMENT.md` section 1, DL-1, MAX-22).

Choose the kind once. An app already deployed on one kind is not redeployed on the other: changing its database resource's form changes the Postgres role it connects as, and the new role owns nothing the old one created (`docs/DEPLOYMENT.md` section 7). The second production target is refused as a taken name; if that happens, stop and ask the owner.

Substitute real values; drop the angle brackets.

## The command

```bash
uv sync --locked --all-groups
npm --prefix frontend ci --ignore-scripts && npm --prefix frontend run build
scripts/enterprise_deploy.sh <profile> <catalog> <schema> <lakebase-project> <endpoint> <endpoint>,<in>,<out>,<date> 100.00
# or, for an existing Provisioned instance only:
scripts/enterprise_deploy.sh --provisioned <profile> <catalog> <schema> <lakebase-instance> <endpoint> <endpoint>,<in>,<out>,<date> 100.00
```

It stops at the first step that fails and writes `docs/rebuild/runs/<today>/enterprise/<time>/evidence.tsv`, one row per step, with each step's output in `E<n>.log` beside it:

| Row | What it proves | If it fails |
|---|---|---|
| E1 | The endpoint, schema, volume, Lakebase (the project, its read-write endpoint and its database; or the Provisioned instance) and both groups exist; the ceiling covers one call | The log names the missing resource and the command an administrator runs to create it; the volume you may create yourself once the schema exists. |
| E2 | `databricks bundle validate -o json` resolved the app's name, the endpoint, price and run ceiling you gave, and the Lakebase kind you chose with its values (`bundle.json` beside the rows) | The bundle or a variable value; the log is the CLI's own message, or names the resolved value that is not the one given. |
| E3 | `databricks bundle deploy` | Usually a grant the app's service principal lacks (`CAN_QUERY`, `CAN_CONNECT_AND_CREATE` on the Lakebase database, `WRITE_VOLUME`), or a Lakebase path the workspace does not hold. Record it as a blocker; do not edit `databricks.yml` to drop a resource. A deploy lock held by another deployer, or a CLI panic after the app was deleted out of band, has its recovery in `docs/DEPLOYMENT.md` section 7; run it only after asking the owner. |
| E4 | `databricks bundle run caos` | The app failed to start; `databricks apps logs caos -p <profile>` has the process output. |
| E5 | The app is RUNNING, has a URL, and reports `forward_user_access_token=True` | Same as E4; `forward_user_access_token=False` means the workspace has not enabled the preview feature (F53): ask Databricks to enable it, then `databricks apps stop caos` and `start`. |
| E6 | `/api/health` answers ready with `python_version` 3.13 and every code `OK`: store, bundle, blobs, identity, workers | A `python_version` that is not 3.13 means the platform did not install from `uv.lock`: check that no `requirements.txt` was added at the root. `store` not `OK` on a first deploy is most often the schema grant above. |
| E7 | The gateway smoke, JSON mode included (A31) | `json_mode=` other than `accepted` means the endpoint rejects `response_format`; ask the owner which endpoint to use, do not remove the parameter. |
| E8 | Lakebase `SELECT version()` as the deployer (the app's own access is E6's `store` code), through the chosen kind's API: the endpoint's host and a credential from the Postgres API, or the instance's from the database API | Copy the version line into `docs/rebuild/decisions.md` under D17 when it succeeds. |
| E9 | The event stream's first frame arrives through the Apps proxy, then frames keep arriving for 3 s, none more than 1.5 s apart, with the stream open (C42, DF-2). Leaves one case behind, `CAOS deployment check (safe to archive)` (N22): keep it or have an admin archive it. | `no frame within 20s`, `then no frame for 1.5s` or `then the stream closed` means the proxy buffers or cuts the stream: record it as a finding (`Fn`) and log the polling fallback in `docs/rebuild/next.md`; do not build it unasked. `unverified` (a 403) means your profile has no writer standing in the app: ask to be added to the analyst or admin group and rerun; any other status is the app failing and the row says which. |
| E10 | One model call through the app's own HTTP surface, not this command's process or credentials (CF-054), answered by the gateway: a tiny text source admitted to E9's case, a LITE run started, and its Run section read on each event until the first node's attempt is accepted, or a validated Blocked verdict ends the run (W1) | `the run parked <CODE>` names why the app's own call did not answer: a `PROVIDER_*` code is the gateway refusing or failing the app's service principal (its `CAN_QUERY` grant, the endpoint's rate limit or state), any other code is the answer the app refused. `no model call answered within <n>s` means the gateway did not answer in time: check `databricks apps logs caos -p <profile>` and the endpoint's own status; `unverified` follows E9's; any other status is the app failing and the row says which. |

## Afterwards

1. Open the app URL (row E5), upload a small public document, approve the run's gates, watch the Run section reach COMPLETE, open the deliverable. That is the one thing no stand-in can do for you.

   The live record so far (`qualification/PROVIDER_RUNBOOK.md`, D29–D45): one qualification set, `ccl-fy2025-market-dislocation`, qualified end to end on `openai/gpt-6-luna-pro` (D30's second attempt, widened by N52); CP-0, CP-3D and CP-5 have each been accepted live at least once (CP-5 as a validated `Blocked`, a legitimate terminal answer, not a refusal); stored CP-1 and CP-1A answers, also GPT-6 Luna Pro, pass under the current vendor fork on replay -- the first either module has produced that the contract accepts, though neither has been re-run live since the fork landed. No module past those five has been reached by a real model: every set to date stopped at or before CP-0, CP-1, CP-1A, CP-3D or CP-5, so CP-2 through CP-2H, CP-3 (other than CP-3D), CP-4/CP-4C, CP-5A, CP-6/CP-6A, CP-CF, CP-L10 and CP-DR remain untested against a real model.

   Every cheap or mid-tier model measured (GPT-5.6 luna, Claude Haiku 4.5, Gemini 2.5 Flash, Claude Opus 5 and 5.5) failed CP-0's own severity or confidence-cap rule on nearly every attempt; a capable model is expected to be needed past CP-0 (GPT-6 Luna Pro, the one model that has cleared it repeatedly, runs in its costlier reasoning mode, about $0.05 and three minutes a call). Since D30 a refused node gets one second attempt carrying the validator's own messages; if the node is still refused after it, the Run section shows the stop code (`HANDOFF_MALFORMED` or whichever it was): report it with the run id and do not retry more than once.

   D38: CP-3 and CP-6 take their portfolio, mandate, constraint and sector relative-value inputs only from the case's own sources (the bundle's sample workbooks are withheld from every prompt, named but never delivered); supply the enterprise's maintained workbook as a case source -- a CSV export or a PDF -- never as a live constraint or a placeholder.

2. If this release needs a rollback, first run `uv run python scripts/rollback_check.py <previous commit>` from this checkout, before checking anything else out. Only when it exits 0 is the rollback a redeploy of that commit through the same one command. Exit 1 means redeploying it would take production down or split the store. Either the release applied a migration the previous commit does not carry, and that app refuses the store at boot (`STORE_SCHEMA_DRIFT`); or the previous commit predates DL-1 (F219), and its app would start on an empty store. Do not redeploy it: stop and ask the owner whether to roll forward or restore (`docs/DEPLOYMENT.md` section 6).
3. Update `docs/rebuild/blockers.md` (B2 and B9 resolved, quoting the rows' last lines; the profile name is fine, the host and any token are not) and `docs/rebuild/decisions.md` (D17; any `Fn`), then:

```bash
uv run pre-commit run --all-files
git add -A && git commit -m "Enterprise deploy: E1-E10 against <profile>, D17 recorded"
```

Do not push unless told.

## Report back

One message, standing alone: the ten rows as written (id, exit, last line), each blocker you added or resolved verbatim, each `Fn` you added, which Lakebase kind you deployed, the Lakebase version, whether E9 held, whether E10's model call was answered (or the code it parked with), and the health line. Nothing in it may be a secret or a host name the owner has not already written down.

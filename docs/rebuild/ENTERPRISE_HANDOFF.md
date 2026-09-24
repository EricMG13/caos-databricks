# Enterprise handoff: the workspace values, one command

For the agent (Claude Code or equivalent) or the person who has a Databricks CLI profile for the enterprise workspace. Everything else has been built and verified without a workspace: the process boots the way Databricks Apps boots it, a governed run completes through the gateway seam, the bundle validates, deploys and runs, and the deployment command itself has been exercised, all against a loopback stand-in for the workspace (D28) and a Docker Postgres for Lakebase. Your job is to run that one command against the real workspace and report what it wrote.

Read first if anything is unclear: `docs/DEPLOYMENT.md` (the runbook the command follows), `docs/rebuild/blockers.md` (B2, B9), `docs/rebuild/decisions.md` (D17, D23, D28, F27–F31).

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
| Lakebase provisioned instance name | argument 4 |
| AI Gateway serving endpoint that serves a Claude model | argument 5 (default `databricks-claude-opus-5`) |
| That endpoint's dated per-token price from the enterprise contract | argument 6, as `<endpoint>,<input_per_token>,<output_per_token>,<YYYY-MM-DD>` |
| What one run may spend | argument 7 (default `100.00`: the widest profile at its section bounds plus one worst-case call, D29; it must cover at least one worst-case call, about 22.61 at the default price; raise it for large packs, since evidence is on top) |
| Lakebase database, the two groups, the target | environment: `LAKEBASE_DATABASE` (`databricks_postgres`), `GROUP_ADMIN` (`caos-admins`), `GROUP_ANALYST` (`caos-analysts`), `TARGET` (`prod`; the app is `caos` there, `caos-dev-<your user id>` in `dev` and `caos-<target>` in any other, DP-6, DF-5) |

No grant is run by hand before the first deploy: the bundle's `CAN_CONNECT_AND_CREATE` gives the app's service principal `CREATE` on the database, and the app creates its own schemas there, `caos_store` and `caos_graph`, rather than writing to `public` (`docs/DEPLOYMENT.md` section 1, DL-1, MAX-22).

Substitute real values; drop the angle brackets.

## The command

```bash
uv sync --locked --all-groups
npm --prefix frontend ci --ignore-scripts && npm --prefix frontend run build
scripts/enterprise_deploy.sh <profile> <catalog> <schema> <lakebase-instance> <endpoint> <endpoint>,<in>,<out>,<date> 100.00
```

It stops at the first step that fails and writes `docs/rebuild/runs/<today>/enterprise/<time>/evidence.tsv`, one row per step, with each step's output in `E<n>.log` beside it:

| Row | What it proves | If it fails |
|---|---|---|
| E1 | The endpoint, schema, volume, instance and both groups exist; the ceiling covers one call | The log names the missing resource and the command an administrator runs to create it; the volume you may create yourself once the schema exists. |
| E2 | `databricks bundle validate -o json` resolved the app's name, and the endpoint, price and run ceiling you gave (`bundle.json` beside the rows) | The bundle or a variable value; the log is the CLI's own message, or names the resolved value that is not the one given. |
| E3 | `databricks bundle deploy` | Usually a grant the app's service principal lacks (`CAN_QUERY`, `CAN_CONNECT_AND_CREATE`, `WRITE_VOLUME`). Record it as a blocker; do not edit `databricks.yml` to drop a resource. A deploy lock held by another deployer, or a CLI panic after the app was deleted out of band, has its recovery in `docs/DEPLOYMENT.md` section 6; run it only after asking the owner. |
| E4 | `databricks bundle run caos` | The app failed to start; `databricks apps logs caos -p <profile>` has the process output. |
| E5 | The app is RUNNING, has a URL, and reports `forward_user_access_token=True` | Same as E4; `forward_user_access_token=False` means the workspace has not enabled the preview feature (F53): ask Databricks to enable it, then `databricks apps stop caos` and `start`. |
| E6 | `/api/health` answers ready with `python_version` 3.13 and every code `OK`: store, bundle, blobs, identity, workers | A `python_version` that is not 3.13 means the platform did not install from `uv.lock`: check that no `requirements.txt` was added at the root. `store` not `OK` on a first deploy is most often the schema grant above. |
| E7 | The gateway smoke, JSON mode included (A31) | `json_mode=` other than `accepted` means the endpoint rejects `response_format`; ask the owner which endpoint to use, do not remove the parameter. |
| E8 | Lakebase `SELECT version()` as the deployer (the app's own access is E6's `store` code) | Copy the version line into `docs/rebuild/decisions.md` under D17 when it succeeds. |
| E9 | The event stream's first frame arrives through the Apps proxy, then frames keep arriving for 3 s, none more than 1.5 s apart, with the stream open (C42, DF-2) | `no frame within 20s`, `then no frame for 1.5s` or `then the stream closed` means the proxy buffers or cuts the stream: record it as a finding (`Fn`) and log the polling fallback in `docs/rebuild/next.md`; do not build it unasked. `unverified` (a 403) means your profile has no writer standing in the app: ask to be added to the analyst or admin group and rerun; any other status is the app failing and the row says which. |

## Afterwards

1. Open the app URL (row E5), upload a small public document, approve the run's gates, watch the Run section reach COMPLETE, open the deliverable. That is the one thing no stand-in can do for you. Every model measured so far wrote CP-0 answers the vendor's validator refuses (F111); since D30 a refused node gets one second attempt carrying the validator's own messages, which no live model has been measured against yet. If CP-0 is refused twice, the Run section shows `HANDOFF_MALFORMED`: report it with the run id; do not retry more than once.
2. Update `docs/rebuild/blockers.md` (B2 and B9 resolved, quoting the rows' last lines; the profile name is fine, the host and any token are not) and `docs/rebuild/decisions.md` (D17; any `Fn`), then:

```bash
uv run pre-commit run --all-files
git add -A && git commit -m "Enterprise deploy: E1-E9 against <profile>, D17 recorded"
```

Do not push unless told.

## Report back

One message, standing alone: the nine rows as written (id, exit, last line), each blocker you added or resolved verbatim, each `Fn` you added, the Lakebase version, whether E9 held, and the health line. Nothing in it may be a secret or a host name the owner has not already written down.

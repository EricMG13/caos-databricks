# Round 4 — Deploy path and frontend (DF)

**Scope.**
- **Reviewer.** Claude Opus 5.5 (`claude-opus-5-5`) at effort max, adversarial-reviewer skill. The harness refused the report file from the subagent ("Subagents should return findings as text, not write report files"); the orchestrator saved this text from the reviewer's final message verbatim.
- **Target.** Commit `653dc9ce91a73137360c43b81f14284d324de58f` (`git log --oneline -1`: `653dc9c Findings round 3: 100 findings patched across the store, worker, graph, model seam, deployment path, edge, evidence, deliverable and frontend`), in worktree `/Users/ericguei/Documents/caos-databricks/.claude/worktrees/agent-a7e961e2ccd93296f` (branch `worktree-agent-a7e961e2ccd93296f`, clean at start).
- **Read.** `CLAUDE.md`, `docs/rebuild/decisions.md` F71–F109, `docs/rebuild/round3/` (README, findings-round3, decisions-mine, decisions-frontend), `docs/DEPLOYMENT.md` and `docs/rebuild/next.md`. The scope files: `databricks.yml`, `app.yaml`, `scripts/enterprise_deploy.{sh,py}`, `scripts/preflight.py`, `scripts/gateway_smoke.py`, `scripts/check_gate_config.py`, `tests/workspace_stub.py`, `tests/platform_app.py`, `tests/test_platform_boot.py`, `tests/test_enterprise_deploy.py` and `.github/workflows/ci.yml`. In `frontend/src`: the command, confirm, transport, tail, workspace, announcer, heading, rail and section controls, plus the a11y and workbench gate scripts.
- **Setup.** `uv sync --locked --all-groups`, `npm --prefix frontend ci --ignore-scripts` and `npm --prefix frontend run build` all exited 0.
- **Frontend gates.** `lint` 0, `typecheck` 0, `test` 0 (32 files, 299 tests), `build:demo` 0.
  - `a11y`: 240/240 entries, 0 violation nodes, 0 scan errors, 0 layout failures. Run with `BASE` on a free 127.0.0.1 port and `A11Y_RESULT_FILE` in the scratchpad, so the tracked `a11y-results/matrix.json` was not rewritten.
  - `test:workbench`: 90 passed. Same specs and engines, through a temporary config on a free 127.0.0.1 port, removed afterwards.
- **Python tests.** `tests/test_enterprise_deploy.py`, `tests/test_platform_boot.py`, `tests/test_workspace_stub.py`, `tests/test_check_gate_config.py` and `tests/test_run_ceiling.py` with `-n 4 --no-cov`: 31 passed.
- **Stub gates.** All exited 0:
  - A34: validate with a non-default `BUNDLE_VAR_model_price`.
  - A35/A36: dev deploy and run in one stub.
  - A37: prod validate, deploy and run in one stub.
- **Other gates.** `check_gate_config.py` and `--shipped` for dev and prod pass. jscpd gives identical results in the CLAUDE.md form and the CI form (243 files, 2.33 %).
- **Probes.** Each prints its own evidence. All are in `docs/rebuild/round4/probes/deploy/`:
  - `uploaded_tree.py`, `price_values.py`, `redeploy_health.py`, `proxy_checks.py`, `preflight_posture.py`
  - `app_names.py`, `stub_fidelity.py`, `shipped_gap.py`, `baseline_on_push.py`, `cli_panic.sh`
  - `run_frontend_probes.sh` with `frontend/r4df-probe.test.tsx`
  - `run_armed_probe.sh` with `frontend/r4df-armed.spec.ts` and `frontend/playwright.r4df-armed.config.ts.in`
- **Isolation.** The Databricks CLI (v1.17.0) ran only against `tests/workspace_stub.py`, with `DATABRICKS_CONFIG_FILE` pointed at nothing. The only databases created were `r4_df_boot_dev`, `r4_df_boot_prod` and `r4_df_redeploy`; all were dropped `WITH (FORCE)`, and none is left.
- **Left alone.** No commit. No source change. Nothing under `vendor/deploy-v` was touched. The local `.databricks/` state the CLI wrote was removed at the end.

**Verdict: CONCERNS** — no verified CRITICAL. Eleven WARNINGs and two NOTEs, all verified.

## Findings

### DF-1 [WARNING] On a redeploy, E6 accepts the previous process's heartbeat as the new process's worker
- **Where:**
  - `caos/api/health.py:161-198`: in `probe_workers`, any fresh row counts as `OK` (line 193).
  - `caos/store/work.py:267`: `WORKER_STALE_AFTER = 300.0`. At `:311-330`, a stopped worker's last beat stays in the table.
  - `caos/graph/worker.py:482-503`: `start_in_process` prints the code and returns `None`, and the API keeps serving.
  - `scripts/enterprise_deploy.py:236-269`: E6 requires `workers=OK` (F54).
- **Verified:** yes — `uv run python docs/rebuild/round4/probes/deploy/redeploy_health.py`. Process A boots the platform way and is stopped with SIGTERM. Process B boots on the same database with a price its worker refuses. E6's own `_health` then runs against B:
  ```
  heartbeats after A stopped: [('worker-94618', 'POLLING', True)]
  B (worker refused) health: {'status': 'ready', 'workers': 'OK', 'store': 'OK', 'identity': 'OK'}
  B log says: ['PROVIDER_NOT_CONFIGURED']
  E6 on B: exit 0; row: Row(id='E6', command='GET /api/health', code=0, summary='answered 200 status=ready python_version=3.13.15 store=OK bundle=OK blobs=OK identity=OK workers=OK')
  ```
- **Failure:** Every release after the first runs E6 seconds after `bundle run`, while the old process's last POLLING beat is still fresh for 300 s.
  - Suppose a release's in-process worker does not start: a refused price or endpoint, `CAOS_REASONING_EFFORT` set, a checkpoint set-up fault, or a code regression in `_configured`.
  - The app still serves `ready` with `workers=OK`. E6 records exit 0, E7–E9 pass, and the one command prints `deployed: <url>`.
  - Runs queue and never execute. Health turns to `WORKERS_STALE` only five minutes later.
  - F54 fixed exactly this for the first deploy; the redeploy case is still open.
- **Fix:** Make the in-process worker's health a fact about this process. When `CAOS_WORKER_IN_PROCESS=1`, `probe_workers` should check that the row for this process's `worker-<pid>` is fresh, or that the worker thread is alive. The drain should delete or mark its own row on shutdown. Pin it in `tests/test_platform_boot.py`: boot, SIGTERM, boot again with a refused price, and assert `workers != "OK"` and E6 exit 1.

### DF-2 [WARNING] E9 proves neither "frames as they come" nor "still open two seconds later"
- **Where:**
  - `scripts/enterprise_deploy.py:382-409`: `_first_frame` reads one more line on a thread. It reports "open" if that read is still blocked after `LIVE_SECONDS`, or if it returned any bytes.
  - `:371-379`: `_streamed`.
- **Verified:** yes — `uv run python docs/rebuild/round4/probes/deploy/proxy_checks.py`. The upstream frames exactly as `caos/api/app.py` `_frame` does: `id: a.b` at once, then `:` every 0.5 s. E6 and E9 run through proxies:
  ```
  [first-then-hold] E9 exit 0 after 2.0s: first frame 'id: 0.0' with the stream open
  [cut-1s] E9 exit 0 after 0.5s: first frame 'id: 0.0' with the stream open
  [buffer-all] E9 exit 1 after 5.0s: no frame within 5.0s (TimeoutError), C42
  [html-200] E6 exit 1 ...; [html-200] E9 exit 1 after 0.0s: answered 200
  ```
- **Failure:** Two misbehaving proxies both pass, and both are recorded as verified deployments.
  - A proxy that forwards the first write and then holds everything else passes: the held read is taken as "open". This is the C42 risk E9 exists for. In production, no event arrives until the 300 s tail deadline.
  - A proxy that cuts every stream 1 s after it opens also passes, in 0.5 s. The first heartbeat arrives before the cut, and any bytes returned count as "open". In production, the tail reconnects and refetches on every browser retry.
- **Fix:** After the first frame, keep reading until `LIVE_SECONDS` have passed. Require a further frame within every `2 × POLL_INTERVAL` (the server heartbeats every 0.5 s), and fail on `b""` or on a gap. Pin it by adding the probe's `first-then-hold` and `cut-1s` modes to `test_the_stream_row_refuses_html_a_closed_stream_and_a_foreign_403`.

### DF-3 [WARNING] Preflight's payload-logging check misses the SDK's `telemetry_config` and the endpoint's `pending_config`
- **Where:** `scripts/preflight.py:159-185`. `gateway_problems` reads only `ai_gateway.inference_table_config`, `config.auto_capture_config`, `config.served_entities`, `config.traffic_config`, `ai_gateway.fallback_config` and `ai_gateway.guardrails`.
- **Verified:** yes — `uv run python docs/rebuild/round4/probes/deploy/preflight_posture.py`. The stub's endpoint answer was widened, and `preflight.main` ran the way E1 runs it, through `ServingEndpointDetailed.from_dict` of databricks-sdk 0.140.0. The SDK describes the field as "Telemetry configuration for the endpoint, including inference-table payload logging."
  ```
  SDK parses telemetry_config.inference_table_config: TelemetryInferenceTableConfig(name='main.caos.payloads', sampling_fraction=1.0)
  [control: ai_gateway inference table on] preflight exit 1: MISSING serving endpoint databricks-claude-opus-5: inference tables log every payload: ...
  [telemetry_config inference table, every request sampled] preflight exit 0: ok      serving endpoint databricks-claude-opus-5
  [telemetry_config all signals to UC tables] preflight exit 0: ok      serving endpoint databricks-claude-opus-5
  [pending_config turning auto-capture on and adding an entity] preflight exit 0: ok      serving endpoint databricks-claude-opus-5
  ```
- **Failure:** These endpoints pass E1:
  - payload logging configured through `telemetry_config` (sampling 1.0);
  - a pending update that turns auto-capture on;
  - a pending update that adds a second entity.

  Every prompt carries document text, so each one is copied into a Unity Catalog table outside case standing. That is the exposure F82 (DP-3/MX-5/TM-6) set this check up to refuse.

  Not promoted to CRITICAL: the exposure needs an endpoint configured that way, and the defect is the check that should flag it.
- **Fix:** Refuse `telemetry_config.inference_table_config` when it has a name or any `sampling_fraction > 0`. Refuse a `telemetry_config` that exports traces or logs. Run the same checks over `pending_config`. Pin it by extending `tests/test_workspace_stub.py::test_preflight_reads_the_gateway_posture_and_the_price_s_endpoint` with these shapes over the stub.

### DF-4 [WARNING] A sync that drops the export's scripts and styles passes every gate and boots `ready` with a blank UI; CI never deploys the real export, and its price step checks nothing
- **Where:**
  - `scripts/check_gate_config.py:79-98`: `SHIPPED` names only `frontend/dist/index.html` from the export. See also `:334-341` (`shipped_problems`) and `:214-238` (`_bundle_problems` checks excludes only against `SHIPPED`).
  - `caos/api/site.py:65-66`: boot checks only that `index.html` exists.
  - `.github/workflows/ci.yml:124`: `mkdir -p frontend/dist && touch frontend/dist/index.html` gives an empty page, and that job never builds the frontend. At `:127-130` the non-default price is only validated.
- **Verified:** yes.
  - `uv run python docs/rebuild/round4/probes/deploy/shipped_gap.py`:
    ```
    1. real record: 28 export files; crippled record: 1 (['frontend/dist/index.html'])
       --shipped on the crippled record -> no problems (gate passes)
    2. databricks.yml with sync.exclude ["*.js", "*.css"] -> _bundle_problems: no problems (gate passes)
    3. CI bundle job export step: mkdir -p frontend/dist && touch frontend/dist/index.html; builds the frontend in that job: False
    ```
  - `uv run python docs/rebuild/round4/probes/deploy/uploaded_tree.py --target dev --boot --drop-export-assets`. The uploaded tree boots under `uv run --offline --locked --no-dev`, with the export reduced to `index.html`:
    ```
    boot: health: {"status": "ready", ..., "store": "OK", "bundle": "OK", "blobs": "OK", "identity": "OK", "workers": "OK"}
    boot: GET / -> 200 text/html; charset=utf-8 437 bytes
    boot: GET /assets/index-CVF97vR3.js -> 404  0 bytes
    ```
  - CI's price step with the variable misspelt (`BUNDLE_VAR_model_prices=...`) under the stub prints `Validation OK!`. The resolved `CAOS_MODEL_PRICE` is `['databricks-claude-opus-5,0.000005,0.000025,2026-09-22']`, which is the default.
- **Failure:**
  - A sync change such as `exclude: ["*.js"]`, or any rule that drops `frontend/dist/assets/**`, ships an `index.html` whose script and stylesheet return 404. The workspace renders nothing.
  - Meanwhile `check_gate_config.py`, `--shipped` (locally and in CI), health, E6 and E9 are all green.
  - CI's bundle job cannot see this, because it never deploys a built export.
  - CI's non-default price step is green whether or not the price reaches the app.
  - Separately, `--shipped` runs in CI but is not in CLAUDE.md's gate list (R3-3 asked for it). So it can be red in CI and is never run locally.
- **Fix:**
  - In `shipped_problems`, derive the shipped set from the built export: every file under `frontend/dist`, or every asset `index.html` references.
  - Build the frontend in CI's bundle job instead of touching an empty page.
  - At boot, refuse an `index.html` whose referenced assets are missing.
  - In the price step, assert the resolved `CAOS_MODEL_PRICE` from `bundle validate -o json`.
  - Add `--shipped` to CLAUDE.md's gates.
  - Pin it with a `tests/test_check_gate_config.py` case on a record without `frontend/dist/assets/*`.

### DF-5 [WARNING] The per-target app name is set on `dev` only: developers share `caos-dev`, and any new target deploys over the prod app
- **Where:**
  - `databricks.yml:45` sets `name: caos` for every target. Only `dev` overrides it, to `caos-${bundle.target}`, at `:132-135`.
  - `scripts/enterprise_deploy.py:66-69`: `app_name` returns `caos-<target>` for any non-prod target.
  - `docs/DEPLOYMENT.md:81` promises "`caos-<target>` in any other".
- **Verified:** yes — `uv run python docs/rebuild/round4/probes/deploy/app_names.py`. One stub, two SCIM users, each with their own home and token. Then a tree copy with a `staging` target written like `prod`:
  ```
  dev deploy as alice@example.com: exit 0; ['Files: 572 uploaded, 0 deleted', 'Resources: 2 created, 0 changed, 0 deleted, 0 unchanged']
  dev deploy as bob@example.com: exit 1; ['Error: cannot create resources.apps.caos.permissions: dependency failed: resources.apps.caos', 'Files: 572 uploaded, 0 deleted']
  bundle roots: ['/Workspace/Users/alice@example.com/.bundle/caos/dev', '/Workspace/Users/bob@example.com/.bundle/caos/dev']
  a `staging` target written like `prod`: bundle app name = 'caos'; enterprise_deploy.app_name('staging') = 'caos-staging'
  ```
- **Failure:**
  - **Second developer.** `mode: development` gives each developer their own bundle root, but the app name is per target, not per developer. The second developer's `bundle deploy -t dev` uploads 572 files and then fails on the duplicate name. (The stub answers 409 as F81 intends; the SDK documents that app names must be unique within the workspace.)
  - **New target.** A `staging` target, or any third target, added without repeating the override deploys app `caos`, which is the production app: DP-6 again. The one command's E5 then looks up `caos-staging` and fails, after E3 has already taken over production.
- **Fix:** Put `name: caos-${bundle.target}` on the top-level resource and override `prod` to `caos`. For dev, either add a per-developer suffix that satisfies the name rule (lowercase alphanumerics and hyphens, for example the numeric `${workspace.current_user.id}`), or document dev as single-developer. Have E5 read the resolved name from `databricks bundle validate -o json` instead of recomputing it. Pin it with a bundle test that every non-prod target resolves to a name other than `caos`.

### DF-6 [WARNING] Six command controls never announce a success, and a repeated sentence is not announced again (FE-6 incomplete)
- **Where:**
  - Six controls pass `success=""`: `frontend/src/sections/directory/NewCase.tsx:109`, `CaseAccess.tsx:64` and `:129`, `sections/report/FilingControls.tsx:338`, `sections/upload/AdmitSources.tsx:108`, `sections/upload/WithdrawSource.tsx:55`.
  - The success notes those controls show instead (`AdmitSources.tsx:104`, `FilingControls.tsx:334`, `NewCase.tsx:104`) have no live role.
  - `frontend/src/sections/run/controls.tsx:216-218`: only a non-empty sentence is announced.
  - `frontend/src/states/Announcer.tsx:20`: calling `setSentence` with an equal string changes nothing.
- **Verified:** yes — `sh docs/rebuild/round4/probes/deploy/run_frontend_probes.sh`. It runs in the suite's own harness; the probe is copied in and removed afterwards.
  ```
  [DF-probe] admit success note="1 source(s) admitted." role=null live-region="" status-roles-with-text=0
  [DF-probe] withdraw: confirm focused=true; control after re-read=gone; activeElement=<body>; live-region=""
  [DF-probe] live-region mutations: first pin 1, second pin 0; region text "Subject pinned. Reading it back."
  ```
- **Failure:**
  - For a screen-reader user, these six succeed silently (WCAG 4.1.3): create case, admit sources, withdraw source, grant standing, revoke standing, save revision.
  - Pinning the subject a second time, or re-reading a preview, leaves the live region's text unchanged. So the second success is not announced either.
  - `npm test` stays green, because `test_a_command_success_is_announced_and_carries_role_status` renders `CommandOutcome` with a sentence and never these controls.
- **Fix:** Give each control a success sentence, for example "Sources admitted. Reading the pack back." Make `say` re-announce an equal sentence: clear the region, then set it on the next frame, or key the text node. Pin it per control: after an `ok`, `[data-announcer]` holds its sentence, and after a second `ok` the region has changed again.

### DF-7 [WARNING] Focus falls to `<body>` after a confirmed act removes its own control, and when leaving the absent page (FE-4 incomplete)
- **Where:**
  - `frontend/src/controls/ConfirmedControl.tsx:53-59`: focus returns to the opener, which the re-read then removes.
  - `frontend/src/sections/upload/WithdrawSource.tsx` and `sections/directory/CaseAccess.tsx:23-67`: withdraw and revoke re-read the section and drop the row's control.
  - `frontend/src/app/App.tsx:10-30`: `Absent` renders its own rail and never moves focus. `frontend/src/app/Workspace.tsx:271-275` does not treat the first render after mount as a navigation.
- **Verified:** yes — the same probe run:
  ```
  [DF-probe] withdraw: confirm focused=true; control after re-read=gone; activeElement=<body>; live-region=""
  [DF-probe] absent -> directory: link focused before=true; path=/directory/; activeElement=<body>; title="Directory · CAOS"
  ```
- **Failure:**
  - A keyboard user who confirms a withdrawal or a revocation is sent back to the top of the document, and nothing is said (WCAG 2.4.3; see also DF-6).
  - A reader on the "Unavailable" page who activates a rail link lands on the workspace with focus on `<body>`. That is the exact FE-4 symptom, on the one navigation the fix does not cover.
- **Fix:**
  - After a command whose success removes its own control, move focus to the row, the panel heading, or `focusSectionHeading()`.
  - Treat a mount that follows an `Absent` render as a navigation. A mount while `document.activeElement` is `<body>` right after a click counts too.
  - Pin both in `workspace-live.test.tsx`.

### DF-8 [WARNING] The event tail's retry has no floor: `Retry-After: 0` reconnects with no wait, and a unit test pins that
- **Where:**
  - `frontend/src/app/sse.ts:50-55`: `retryDelayMs` returns `retryAfterSeconds * 1000`, capped above but never floored.
  - `frontend/src/app/transport.ts:131-136`: `retryAfterOf` accepts `0`.
  - `frontend/tests/unit/sse.test.ts:118`: `expect(retryDelayMs(5, 0)).toBe(0)`.
- **Verified:** yes — the same probe run. A fake `EventSource` is refused at once, and `onRefused` answers with the document read's `Retry-After: 0`:
  ```
  [DF-probe] Retry-After "0" read as 0; retryDelayMs(0, 0)=0; retryDelayMs(0, null)=1000; EventSource opened 238 times in 300 ms
  ```
- **Failure:** Suppose the stream is refused and the document read answers `Retry-After: 0`. That is legal HTTP, and a proxy or load balancer might send it during a restart. Every tab then loops a stream open plus a document GET as fast as the network allows, for as long as the refusal lasts. That is the reconnect storm FE-3's backoff was meant to prevent. The gate cannot catch it, because the FE-3 test asserts the zero wait.
- **Fix:** Apply `Math.max(FIRST_RETRY_MS, …)` on the `Retry-After` branch, and keep doubling while refusals repeat. Change `sse.test.ts:118` to expect the floor.

### DF-9 [WARNING] The filing acts fail the WCAG 2.2 target size whenever they are available, and the a11y gate never renders them available
- **Where:**
  - `frontend/src/sections/report/FilingControls.tsx:179-213` uses `className="rb"`.
  - `frontend/src/styles/caos.css:93-106`: `.rb` is 19 px high. Only `.rb.solid` gets `min-height: 24px` (`:132-138`).
  - `frontend/scripts/fixture-routes.mjs`: no fixture state offers any of the six confirmed acts unrefused. The only one present anywhere is `REVOKE_STANDING`, refused `NOT_AUTHORISED`, in `fixtures/directory.json`.
- **Verified:** yes — `sh docs/rebuild/round4/probes/deploy/run_armed_probe.sh`. It uses the demo export on a free loopback port, patches the documents in flight to offer the act, and applies the gate's own axe tags and layout probe. Chromium and WebKit, at 320×640 and 1440×900:
  ```
  [DF-probe] sign opinion closed @320: axe=["target-size(2): button[aria-label=\"Sign opinion\"] :: ... Target has insufficient size (86.6px by 19px, should be at least 24px by 24px) ...
  [DF-probe] sign opinion ARMED @1440: axe=["target-size(2): .crit :: ... (132.3px by 19px, should be at least 24px by 24px) ...
  [DF-probe] cancel run ARMED @320: axe=[] layout={"page_overflow_px":0,"clipped":[],"small":[]}
  [DF-probe] tail paused banner: axe=[] layout={"page_overflow_px":0,"clipped":[],"small":[]}
  ```
- **Failure:**
  - For an approver who may sign, freeze or file, the Sign/Freeze/File controls and the armed "Confirm Sign opinion" button are 19 px targets stacked closer than 24 px. That fails WCAG 2.2 AA 2.5.8 at every viewport.
  - Yet `npm run a11y` reports 240/240 clean, because every route in the matrix renders these acts refused (`aria-disabled`).
  - The same blind spot means no gate has ever measured an armed confirm step or a `NotLive` banner. Both were measured here and are clean.
- **Fix:** Give `FilingAct`'s controls and the confirm step's buttons the 24 px target, using `.rb.solid`'s rule or enough spacing. Add to `STATE_ROUTES` fixture states with the filing acts, withdraw, revoke and cancel available, and a route with an armed step.

### DF-10 [WARNING] The price parser accepts a zero or negative-zero input price (also a future date and non-ASCII digits), and preflight passes them
- **Where:**
  - `caos/pricing.py:105-122`: `price_from_environment` applies `Decimal(...)` to each field and `date.fromisoformat` to the date.
  - `caos/pricing.py:94-96`: `priced_request` refuses only a zero total.
  - `scripts/preflight.py:115-147` uses the same parser.
- **Verified:** yes — `uv run python docs/rebuild/round4/probes/deploy/price_values.py`. Each value goes through the real CLI's `bundle validate -o json` under the stub, then the worker's parser, then E1:
  ```
  [zero input] CLI -> CAOS_MODEL_PRICE='databricks-claude-opus-5,0,0.000025,2026-09-22' (verbatim)
      app worker parser -> ACCEPTED input=0 output=0.000025 as_of=2026-09-22 worst_case=1.638400
      preflight E1 -> ok: ok      run ceiling 25.00 covers a worst-case call (1.638400)
  [negative zero input] ... ACCEPTED input=-0 output=0.000025 ...
  [future date] ... ACCEPTED input=0.000005 output=0.000025 as_of=2099-12-31 ...
  [arabic-indic / fullwidth digits] value='databricks-claude-opus-5,0.00000٥,0.0000２５,2026-09-22' ... ACCEPTED input=0.000005 output=0.000025
  ```
  Both the worker and preflight refuse every malformed value, with `PROVIDER_NOT_CONFIGURED` or `MONEY_INVALID`: spaces after commas, an empty field, a negative value, NaN, `1e-20000`, an extra or missing field, a non-ISO date, a trailing CR, another endpoint, and the empty string. Every value reaches the deployment verbatim, except the empty string, which becomes an env item with no value.
- **Failure:**
  - A price whose input part is `0` or `-0` passes E1 and the app.
  - Every reservation and every recorded charge then prices the request bytes at nothing. The run ceiling no longer bounds input spend, and the ledger understates each call's bill. That goes against the intent of invariant 8.
  - `priced_request` already refuses a "free price" for this reason, but only when both halves are zero.
  - A price dated 2099 is recorded next to every reservation as the dated price in force.
  - Digits a reviewer may misread are taken at their value.
- **Fix:** In `price_from_environment`, refuse a zero part and a negative sign, require ASCII `[0-9]+(\.[0-9]+)?` in each number field, and require a date no later than today (UTC). Doing it there keeps the app and E1 in agreement. Pin it with the probe's values in `tests/test_run_ceiling.py`.

### DF-11 [WARNING] "Suppressions may only fall" is enforced only on pull requests, which this branch never uses, and the baseline already has slack
- **Where:**
  - `.github/workflows/ci.yml:149-160`: `--against` runs only in the `size` job, under `if: github.event_name == 'pull_request'`.
  - `.github/workflows/ci.yml:7-9`: the push trigger names `rebuild/databricks`.
  - `scripts/check_gate_config.py:304-315`: `suppression_problems` compares counts with the committed baseline.
  - `tests/gate_baseline.json`.
- **Verified:** yes — `uv run python docs/rebuild/round4/probes/deploy/baseline_on_push.py`:
  ```
  lint job (suppression_problems vs the pushed baseline): no problems -> green
  size job (--against the base branch): ['baseline: noqa rose to 122 (base branch 121)']
  size job condition: github.event_name == 'pull_request'
  history: 17 commits, 0 merge commits
  ```
  The committed baseline against the tree: `noqa tree=122 baseline=125 slack=3`, `no_cover tree=5 baseline=6 slack=1`.
- **Failure:** CLAUDE.md says suppressions "may only fall" (F58's rule). Two gaps:
  - A push to `rebuild/databricks` that adds a suppression and raises `tests/gate_baseline.json` in the same commit is green in every CI job.
  - Three `noqa` and one `pragma: no cover` can be added today without touching the baseline at all, on a push or on a pull request.
- **Fix:** Run `--against` on push as well, against the previous commit's baseline (`git show HEAD^:tests/gate_baseline.json`). Make the budget a ratchet: fail when a count is below its baseline, so the change that lowers a count must also lower the baseline. Pin it in `tests/test_check_gate_config.py`.

### DF-12 [NOTE] The stand-in hides refusals the real Apps and workspace-files APIs give
- **Where:**
  - `tests/workspace_stub.py:374-376`: `_import` ignores `overwrite=false`.
  - `tests/workspace_stub.py:427-437`: `_create_app` accepts any name.
  - `tests/workspace_stub.py:155-167` and `:402-406`: every app is `RUNNING`/`ACTIVE`, every deployment is `SUCCEEDED`, and a deployment's `command` and `env_vars` are dropped.
  - `tests/platform_app.py:65-89`: the boot harness sets its own environment, not the one the CLI deployed.
- **Verified:** yes — `uv run python docs/rebuild/round4/probes/deploy/stub_fidelity.py` and `app_names.py`:
  ```
  lock writes seen: ["import-file Workspace/caos-bundle/prod/state/deploy.lock query={'overwrite': ['false']}"]
  A2 prod deploy over another deployer's lock: exit 0; ['Files: 0 uploaded, 0 deleted', 'Resources: 0 created, 2 changed, 0 deleted, 0 unchanged']
  B import-file overwrite=false over an existing file: stub answered 200; file now b'mine'
  stub create 'caos-qa_eu' (len 10): 200; documented rule (lowercase alphanumerics, hyphens) REFUSES
  ```
- **Failure:** A37 ("the prod target, lock and all") never exercises the lock's contended path.
  - After an interrupted prod deploy, the real workspace stops the next deploy with the lock holder's name until `--force-lock`. On the stub it succeeds, and the runbook says nothing about it.
  - The stub never answers an app name the Apps API refuses, a crashed app, or a failed deployment. So nothing but this probe has seen E4 or E5 on those paths.
  - E5 does fail closed: `app_status=CRASHED` and a missing forward flag both give code 1.
- **Fix:**
  - Answer `RESOURCE_ALREADY_EXISTS` (409) for `overwrite=false` over an existing path, and refuse app names outside `[a-z0-9-]`.
  - Record a deployment's `env_vars` and `command`, and boot `platform_app` from them.
  - Add stub switches for a failed deployment and a non-RUNNING app.
  - Add a stale-lock row to the runbook.

### DF-13 [NOTE] CLI 1.17.0 panics on a redeploy whose app has vanished and whose config changed; the documented stand-in commands reproduce it
- **Where:** The CLI's direct engine, at `github.com/databricks/cli/bundle/direct/dresources.(*ResourceApp).OverrideChangeDesc`. It is reached through `databricks.yml` `bundle.databricks_cli_version: ">= 1.17.0"` and the CLAUDE.md stand-in commands. Each `tests/workspace_stub.py --` run is a fresh workspace, while `.databricks/` persists between runs.
- **Verified:** yes — `sh docs/rebuild/round4/probes/deploy/cli_panic.sh`:
  ```
  2. same config, another fresh stub (app missing there): exit 0 (Created apps.caos)
  3. changed price, another fresh stub (app missing there): exit 2 (panic: runtime error: invalid memory address or nil pointer dereference [recovered, repanicked])
  github.com/databricks/cli/bundle/direct/dresources.(*ResourceApp).OverrideChangeDesc(...)
  ```
  When the app is present, a changed price redeploys normally (`Updated apps.caos`, same stub).
- **Failure:**
  - **Stand-in.** Running A35 with the default price, then again with the non-default `BUNDLE_VAR_model_price` that CLAUDE.md asks for, crashes the CLI with a Go stack trace.
  - **Real workspace.** An app deleted out of band, followed by a release that changes its config (the price rotation in runbook §6), crashes the same way at E3. No recovery step is documented.
- **Fix:** Clear `.databricks/bundle/<target>` before each stand-in run, or keep one stub state per state directory. Add the recovery to the runbook: `bundle deployment unbind`, or remove the stale state. Raise the CLI floor once a fixed release exists.

## What held up
- **The uploaded trees boot (item 1).** `uploaded_tree.py --target dev|prod --boot` uploads 572 files per target: `caos` 127, `icm` 64, `vendor` 349, `frontend/dist` 28 of 28, plus `app.yaml`, `pyproject.toml`, `uv.lock` and `.python-version`.
  - The CLI sends the bundle's `command` and all ten `CAOS_*` `env_vars` with the deployment. `app.yaml` carries only the command (F52).
  - The rebuilt tree boots from nothing else under `uv run --offline --locked --no-dev`. Health is `ready` with every code `OK`, and the export and its assets serve. This holds for dev and prod alike.
- **C1/F71.** The price travels whole in `BUNDLE_VAR_model_price`. No malformed value reached the app as a different price; DF-10 lists what does parse.
- **F81 dev/prod.** `caos-dev` and `caos` are distinct. E5 fails closed on a crashed app and on a forward flag that did not stick.
- **E6/E9 fail closed** on a sign-in page answered with 200, and on a proxy that buffers the whole response. E6 reads the health codes correctly through every proxy mode tried.
- **Preflight.** It reads attribute names that exist in databricks-sdk 0.140.0 (`ai_gateway.inference_table_config.enabled`, `config.auto_capture_config.enabled`, `fallback_config.enabled`, `served_entities`, `traffic_config.routes`, `guardrails`). It refuses the gateway payload-logging case.
- **F105 in-flight guard and the kept key.**
  - Under `StrictMode`, a double Confirm plus a press on the busy opener sends one POST.
  - Keys are per mounted control, and the view is keyed `case|run|revision`, so no key crosses a case or a run.
  - The confirm step has no bypass: the opener only arms it, and a refused control is inert.
  - The document title follows the section and the case.
- **320 px.** The armed cancel and withdraw steps and the tail-paused banner reflow with no overflow and no clipped control, in Chromium and WebKit. Only DF-9's target size fails.
- **No HTML sink** in `frontend/src`: no `dangerouslySetInnerHTML`, `innerHTML`, dynamic `href` or `eval`.
- **CI parity.** Every CLAUDE.md gate runs in CI with equivalent flags; `uv sync --locked` covers `uv lock --check`. The two jscpd invocation forms give identical results. Stub gates A34–A37 and both `--shipped` checks pass on this commit.

## Not covered
- **Real-workspace behaviour.** No profile was used, so none of this was observed:
  - the Apps proxy's stream handling (C42);
  - whether the Apps runtime provides `uv` and honours `uv run --locked --no-dev`;
  - the Apps API's exact duplicate-name code and name-length limit;
  - how workspace-files answers `overwrite=false` (inferred from the documented API and the CLI's request);
  - whether `telemetry_config` can be set on a pay-per-token Foundation Model endpoint;
  - Lakebase.
- **Frontend runs.** `npm run test:journey` was not run; it is not a listed gate. The armed-state probe ran in Chromium and WebKit only, not Firefox. All runs here were on macOS, so the Linux font metrics that CI's 320 px runs use were not tested.
- **Other Python gates.** The whole pytest suite and the Python gates outside this section (ruff, mypy, bandit, pip-audit, gitleaks, complexipy) were not run, per the targeted-tests rule.
- **next.md deferrals.** N22–N26 were not re-reported, and none of them hides a live defect found here. DF-2's idle-cut case is about E9's own check, not N26's keep-alive tuning.

# Final sweep before the enterprise handoff: the contract

The last local pass over `rebuild/databricks` before the app goes to the enterprise workspace (`docs/rebuild/ENTERPRISE_HANDOFF.md`). The condition that drives it is `docs/rebuild/final-sweep/goal.txt`; this file is what that condition points at.

Written 2026-09-23 against `c37733e`; revised the same day against `e4e4e01`, after D29–D34 and F147–F158 landed (§0, §2). It adapts the loop-library prompt *"Refactor until you are happy with the architecture. After each significant step, live-test the system, run autoreview, and commit. Track progress in /tmp/refactor-{projectname}.md"* and gives it an end point. Only confirmed defects are repaired. Only measured problems are refactored. Both are proven. The tree handed over has fresh evidence for every claim.

## 0. Owner decisions

The owner fills in the Choice column before launching. OD-1, OD-2, OD-4, OD-8 and OD-9 were decided and implemented before the sweep (D29–D34), and OD-6 and OD-7 in part: the sweep verifies them like any FIXED-AT-BASE row. Live proof of the modules no real model reached waits on OD-6's account credit. The sweep reads this table and may not edit it. A blank Choice means the Default. None of these is the sweep's to decide, because each one changes methodology bytes, parity, dependencies, design direction or spend.

| ID | Question | Choice | Default | Recommendation |
|---|---|---|---|---|
| OD-1 | **N32.** Every model tried writes CP-0 `qa_status: Passed` beside a MATERIAL finding, so the vendor validator refuses it (F111). No real run gets past CP-0. Options: (a) record only; (b) one bounded second attempt on that refusal code, with one extra reserved call and first-attempt prompt bytes unchanged; its `Dn` states what the retry carries, and no host text may restate a vendor rule; (c) a host final-check block naming the rule, which breaks prompt parity: a `Dn`, plus an exception to F57's legacy-only golden rule for the `prompt` group, with the procedure that re-baselines it. A vendor `SKILL.md` step is not an option, because it changes vendor bytes (invariant 4). | **(b), approved by the owner 2026-09-23 as D30; widened by the owner to `HANDOFF_INCOMPLETE` and anchoring's refusals (N52, D30 third addendum), with the fourth and fifth addenda** | (a) | done; measured live: `ccl-fy2025-market-dislocation` qualified end to end on it |
| OD-2 | **N31.** Under the 1 MiB request ceiling, a FULL route with real handoffs refuses `REQUEST_OVER_CEILING` at CP-5 by construction. Options: (a) record only; (b) raise `MAX_REQUEST_BYTES` to 4 MiB with a `Dn`, regenerate the pricing goldens from the legacy rule, and re-derive the default run ceiling (CF-008). | **(b), approved by the owner 2026-09-23; implemented pre-sweep as D29 (default ceiling 100.00)** | (a) | (b), if FULL routes are in the enterprise scope |
| OD-3 | **N11.** Replace `databricks-langchain` with one SDK `POST`. This reverses D7 and also retires CF-034/N25 (completion id) and CF-047 (content normalisation). | | no | no for this sweep |
| OD-4 | **Frontend design direction** (`.impeccable/critique/…frontend-src.md`, P1 items: hollow chrome bands, refusal copy, a type floor that changes `DESIGN.md`). Options: (a) defects only: the P0s and WCAG failures; (b) also the P1 redesign. | **(b), approved by the owner; implemented as D32 and D33 with F151–F158 (merge `0fa8a5e`)** | (a) | done |
| OD-5 | **N16.** Refuse-mutation triggers, and a migration role separate from the runtime role. | | record for the enterprise DBA | record |
| OD-6 | **Live provider spend** during the sweep, in USD. Only through `tests/` (the OpenRouter adapter, `tests/qualify_openrouter.py`), and never counted as gateway evidence. | **$15.00 for all combined testing (owner, 2026-09-23), cheapest adequate model (`openai/gpt-6-luna-pro`); $5.35 spent against key baseline 7.6424595; the OpenRouter account's credit is exhausted (`blockers.md`, Live qualification), so no live call until the owner adds credit** | 0 | add credit if S6 or the modules never reached live are to be proven live |
| OD-7 | **Record-shape and prompt-parity changes** (N10, N18, N19, N28). | **Host prompt text changed under D34 (N53 and the prompt review's host rows), goldens kept legacy-derived by mirroring the texts into a scratch copy of the legacy snapshot; N10, N18, N19, N28 still record only** | record only | record only |
| OD-8 | **Vendor bundle edits** (invariant 4). | **Authorised per change: the deployment fork D31 (build `99ed0dc3`) and fork r2 in D34 (build `b160c75e`), re-pinned; none for this sweep** | no edit | the N55 remainder (CP-1, CP-1B, CP-1C column sets that differ in more than spelling) needs the bundle owner's choice of one set |
| OD-9 | **N63.** A validated Blocked answer from a producer with only OPTIONAL or ADVISORY consumers ends the run. | **Kept failing closed (D34)** | keep | keep |

## 1. Operating mode

You are operating autonomously. Nobody can answer, approve or unblock you. Never ask, never wait, and never end a turn with a plan, a question or a promise. End only when §9 holds, or when every remaining item is blocked on something only the owner or the workspace can supply.

- **Scope is the deliverable.** Do §3–§9 in order. Do not narrow, widen or swap the scope. A new feature or requirement goes in `docs/rebuild/next.md`; it is not built. An owner decision is never taken for the owner.
- **Evidence.** Audit every claim against a tool result from this session. A failing command is reported with its output. The final message copies command, exit code and summary from tool output produced in that same final turn.
- **Blockers.** A missing credential, host, permission or workspace goes in `docs/rebuild/blockers.md` with the exact command and error; then continue with everything else. A failing test, gate, parity check or review finding is never a blocker.
- **Hard limits.**
  - Never push. Never edit `vendor/deploy-v/`: the owner's authorisations for D31 and D34 were per change and do not extend to this sweep (OD-8). Never print, log or persist a key, token, minted credential or password-bearing URL.
  - Never add a dependency without a `Dn`. Never write a root `requirements.txt`. Never name OpenRouter outside `tests/`. Never lower a threshold or add a suppression (`tests/gate_baseline.json` counts may only fall).
  - Never regenerate a parity golden except by the procedure an owner decision names.
  - Never contact a real workspace or a paid API beyond OD-6.
- **Committing.** Stage explicit paths, never `git add -A`. The tree may hold untracked owner files such as `.impeccable/`, and they are never committed. This overrides spec §1's `git add -A`. One concern per commit. Commit when green. Run `git status --short` after every commit.
- **Foreign changes.** Before every commit, `git log -1` must be your own last commit or BASE, and no tracked file you did not touch may have changed. Otherwise another writer is active: stop and report BLOCKED with the paths.
- **Working style.** Targeted edits, no whole-file rewrites, `uv run` for every tool. Long output goes to `docs/rebuild/runs/final-sweep/logs/` (git-ignored); print tails and counts.

## 2. Authority and inputs

**Authority, in order:**
- `CLAUDE.md`: the eleven invariants, the conventions and the gate list.
- `docs/rebuild/2026-09-22-caos-databricks-spec.md`.
- `docs/rebuild/decisions.md`: later entries override earlier ones and override an uncorrected spec page.
- `CONTEXT.md` (the vocabulary gate enforces it), `icm/CONTEXT.md`, `DESIGN.md`, `docs/DEPLOYMENT.md`, `docs/rebuild/ENTERPRISE_HANDOFF.md`, `docs/rebuild/next.md` and `docs/rebuild/blockers.md`.

**Ledgers to reconcile.** Each one uses its own ID families.

| Ledger | IDs |
|---|---|
| `findings.md` at the root (git-ignored). The 16-goal campaign is at the top between the `audit-campaign-2026-09-23` markers; the older reviews are below it. | CF-001–CF-106; C1, C2, W1–W7 and the other reviews' IDs |
| `docs/rebuild/findings.md` | AR-*, FP-* |
| `docs/rebuild/findings-round2.md` | DP-, SA-, MX-, MAX-, TM-, CR-, DL-, AS-, AI-, FE-, SI-, EI-, C, W |
| `docs/rebuild/round3/findings-round3.md` and `round3/decisions-*.md` | R3-1–R3-5 (N30, the remainder, was reviewed in round 4: F113–F146) |
| `.impeccable/critique/2026-09-23T11-45-42Z__frontend-src.md` | P0, P1 |
| `docs/rebuild/prompt-review-2026-09-23.md` | G1-1–G1-18, G2-1–G2-18, G3-1–G3-17 (status per row as of `e4e4e01`) |
| `docs/rebuild/next.md` | N1–N63 |
| `docs/rebuild/blockers.md` | B1–B9, and the Live qualification entry (OpenRouter account credit) |

The `Fn` entries in `decisions.md` (F1–F158) record what was fixed; D29–D34 record the owner's decisions of 23 September. Live-run evidence: `qualification/PROVIDER_RUNBOOK.md` (the 23 September sections) and `docs/rebuild/runs/live-2026-09-23/` (git-ignored).

**Evidence you may reuse** (git-ignored, under `docs/rebuild/runs/audit-2026-09-23/`):
- The goal texts: `QUALITY_GOAL_PROMPTS.md`.
- Per-goal evidence: `evidence/DB-NN/findings.json` (each finding's repro), `verify.json`, reproducers and `worktree-probes/`.
- The scenario harness: `evidence/DB-14/probe/{harness,flows}.py`. It boots the platform stand-in and drives cases, packs, gates, runs and filing over HTTP.
- The browser journeys: `evidence/DB-03/worktree-probes/frontend/audit-db03/*.mjs`.
- The shipped-set probe: `evidence/DB-13/probe_shipped_set.py`.

These are probes, not tests. Their paths and ports point at removed worktrees: adapt them under `docs/rebuild/runs/final-sweep/`, and copy them into `tests/` only as a regression test that fails before a fix.

## 3. Phase 0: freeze and baseline

1. Check the start state:
   - You are on `rebuild/databricks`.
   - `git diff --quiet && git diff --cached --quiet` passes.
   - Record every untracked path; leave them alone.
   - If `docs/rebuild/final-sweep/` is untracked, commit it first, by explicit path, as the sweep's own first commit.
   - Record `BASE=$(git rev-parse HEAD)` in `docs/rebuild/runs/final-sweep/progress.md`.
2. Set up the environment: `uv sync --locked --all-groups`, `docker compose up -d --wait`, then `npm --prefix frontend ci --ignore-scripts && npm --prefix frontend run build`. Record `uv run python -V`, `node -v`, the Databricks CLI version, and which `CAOS_*`, `DATABRICKS_*` and `OPENROUTER_API_KEY` variables are set (names only).
3. Run every gate in `CLAUDE.md` exactly as written; together they are acceptance rows A1–A37 (spec §11, plus A34–A37 from D28 and F73). Record each exit code and summary line in `progress.md`.
4. Record the baseline metrics:
   - passed test count and coverage;
   - each suppression count, as measured by `scripts/check_gate_config.py`;
   - `complexity_baselined` (25 at `e4e4e01`; 26 at `c37733e`) and the list of baselined functions;
   - the jscpd percentage;
   - lines of code per package.

A red gate at BASE becomes the first register row. It is repaired before any refactor.

## 4. Phase 1: one register of everything still open

Write `docs/rebuild/runs/final-sweep/register.md` with one row per **root cause**. Columns: row, root cause, every ledger ID that names it, severity after re-check, class, evidence at BASE, action, commit, and its `Fn`/`N`/`B` entry.

Classes:

| Class | Meaning |
|---|---|
| FIXED-AT-BASE | Cite the `Fn` and the test that pins the fix. For CRITICAL or HIGH, rerun the original reproducer at BASE and show that it no longer reproduces. |
| OPEN | Reproduced at BASE. |
| DUPLICATE | Of the named row. |
| DEFERRED | Names its N entry or OD. |
| DECISION | Waits on an OD. |
| NOT-A-DEFECT | With the reason. |
| PLATFORM-ONLY | Names the E-row or B entry that will reveal it. |

Rounds F71–F109 and round 4 (F113–F146) likely closed many CF rows: CF-001 by F72 and R3-3, CF-003 by F102, CF-005 by F93, CF-024 by F85, CF-050 by F97, CF-053 by F76. "Likely" is not evidence, so check each one.

N30 is done (round 4, F113–F146). Review instead what landed after `c37733e` that no review has covered: D29–D34 and F147–F158 (the second-attempt ledger and feedback, the vendor fork's checker and validator changes, the QA gate and Blocked order, the Analysis tables and charts). Use the `adversarial-reviewer` skill, or the `opus55-reviewer` agent, in a worktree at BASE. Its confirmed findings enter the register.

**Exit:** every ID in every ledger is on a row, with counts per class and severity, and the OPEN rows are ranked by §5's order.

## 5. Phase 2: repair confirmed defects, grouped by root cause

Work through the groups in this order. Within a group, higher severity goes first. The CF numbers are seeds; every ledger ID on the same row goes with them.

| Group | Scope | Seed rows |
|---|---|---|
| A | Deploy and first-run blockers: anything that stops `scripts/enterprise_deploy.sh` E1–E9 or the handoff's "Afterwards 1" | the deployed file set (CF-001, R3-3); migrations under the documented grant (CF-010); E5 and the preview flag (CF-033); E9 and model or volume reachability (CF-054) |
| B | Evidence integrity and citations (invariants 2, 11) | CF-002, CF-012–CF-017, CF-021, CF-072–CF-074 |
| C | Text and secret leakage | CF-022–CF-024, CF-077, CF-078 |
| D | Authority, human gates, filing and qualification (invariants 3, 5) | CF-018, CF-019, CF-026–CF-031, CF-081–CF-084 |
| E | Durability and exactly-once (invariant 6) | CF-005–CF-007, CF-037–CF-044 |
| F | Money and budgets (invariants 7, 8) | CF-008, CF-046, CF-048, CF-089–CF-091; OD-2 if chosen |
| G | Availability and resource bounds | CF-003, CF-004, CF-049–CF-053, CF-075 |
| H | The primary journey | OD-4 (b) is implemented (D32, D33, F151–F158): verify its P0 and WCAG repairs at BASE rather than redo them, then Start and Retry usable (CF-011), refusal text that is true (CF-056, and the operator hints G2-17), CF-057–CF-059, CF-097, CF-098; within `DESIGN.md` as it now stands |
| I | Gate and test credibility | CF-061–CF-071, CF-079, CF-092, CF-103–CF-106 |
| J | The prompt review's OPEN host rows | G1-12 (CP-6 workbook delivery), G1-16's remainder, G2-17, G3-9 (`FORECAST_DRIVER_NOT_READY`, comma figures); its OPEN vendor rows are DECISION under OD-8 |
| K | Everything else LOW | Fix it if the change is small; otherwise an N entry with the reason |

**Every repair** follows §8. In addition:
- Reproduce the defect at HEAD before editing anything.
- Write the failing test before the fix. It names the invariant or the behaviour, fails on the old code and passes on the new.
- Make the smallest fix at the shared cause, reusing existing refusal codes and helpers.
- Sweep the sibling paths of the same pattern.
- A change that makes an invariant pass vacuously is wrong even with a green suite.

## 6. Phase 3: refactor, with an end point

Only the changes below are allowed. Each must be shown to preserve behaviour:
- parity goldens byte-identical;
- the full suite green;
- the affected gates green;
- a before/after metric in `progress.md`.

| Item | What | Detail |
|---|---|---|
| R1 | Delete what the decisions already dropped, or what nothing uses | See below |
| R2 | One source for each duplicated fact | The deploy defaults, which live in `enterprise_deploy.sh`, `enterprise_deploy.py`, `databricks.yml` and the stub (N23); the duplicated status tables (N29); the duplicated block "store both bodies, or fail with STORE_UNAVAILABLE" at `caos/graph/runtime.py:405–414` and `caos/methodology/runner.py:120–129`, which becomes one helper (the read path behind CF-006 was fixed by F91 and is not part of this) |
| R3 | Complexity | Bring baselined functions to 15 or below and remove them from `complexipy-snapshot.json`, so the count falls. **Required**, on invariant paths: `deliverable/render.py::_list` (31, the AR-08 site), `methodology/handoff.py::stored_lineage` (30), `methodology/forecast.py::_mapped_rows` (27, money), `evidence/pdf.py::walk_pages` (23), `api/stream.py::case_tail` (22), `graph/route.py::dependency_order` (20, over `graphlib`, N29). **Then, as budget allows:** `store/run_inputs.py::_research`, `api/reads/analysis.py::read_analysis` (20 each), `methodology/selection.py::select_sources`, `api/reads/run.py::node_readiness` (17 each), `evidence/ingest.py::_prepare`, `deliverable/revisions.py::_span` (16 each). Only after those: the qualification matrix, harness and proof functions, and `methodology/invocation.py`, whose prompt bytes the prompt goldens pin. |
| R4 | Stage contracts | The 27 repeated stage-contract sections (N29), only through `scripts/icm_stages.py`. `check_icm` must stay green and prompt parity unchanged. |
| R5 | Frontend (not design) | The modal hook becomes a native `<dialog>` (N29), if the a11y matrix and the workbench stay green. |
| R6 | Documents that match the code | See below |

**R1 in detail:**
- The HMAC edge-assertion mode: 10 references in `caos/api/edge.py` (D10, N12, CF-080). The tests N12 names are removed by name in the `Fn`.
- `scripts/check_postgres.py` and `scan_floors --trivy` (N29).
- The dead overloads of `case_tail`, the dead branch of `_status_refusal`, and production definitions that only tests call (N29).
- Refusal codes no condition raises (CF-099).
- `FORECAST_CHAIN_BROKEN`: retire it or make it reachable (N6, 7 files). If a wire code goes, regenerate `frontend/src/wire/v1/schema.json` with `python -m caos.api.wire`.
- The stale journey configuration: fix or retire it within C67 (CF-102).

**R6 in detail:**
- Spec §4 and §11 statements the as-built system contradicts (CF-100): the `TypedDict` RunState, `interrupt()`, `caos-serve`, `graph/node.py`, `store/connect.py`, and A-rows that live only in decisions. Correct each in place with a "(corrected, Fn)" pointer.
- 71 files cite documents that are not in this repository (CF-101), and 3 frontend files still name `server/api`.
- B8: a key has been in use since F110. Bring B8 and B9 up to date.
- `docs/DEPLOYMENT.md`: a rollback path and a health smoke command that works (CF-096).
- `CLAUDE.md` stays under 120 lines and matches the gates.

**Architecture.** Beyond R1–R6, a structural change is allowed only where two or more confirmed register rows share one seam, and the commit names the rows it retires. No speculative redesign. No N1 parallelism. None of OD-3 or OD-7 unless chosen.

**Stop rule, per item.** Allow at most two attempts. Revert the item by explicit path and record it in `next.md` with the reason if either of these happens:
- it would need a golden, vendor byte, dependency or behaviour change;
- the same gate fails twice.

**Exit:**
- The six required R3 functions are out of the baseline, so the count is 20 or lower. The only exception is a required function whose two attempts the stop rule ended: its `next.md` entry names the golden, gate or behaviour that refused it, and the count is reported with that exception.
- R1, R2 and R6 are done or recorded.
- No suppression count is above BASE.
- The net line count is reported.

## 7. Phase 4: enterprise readiness

1. **The shipped set boots.**
   - Deploy through the stub (A35–A37).
   - Boot `python -m caos.serve` from the deployed file set itself, not the repository, and complete one governed LITE run through `ChatDatabricks` over the stub, with every health code OK.
   - Make this a CI step if none exists (CF-001's repair direction).
   - Run `tests/test_enterprise_deploy.py` green.
2. **Stand-in fidelity.** In `docs/DEPLOYMENT.md`, list every known gap between the stub and the platform, each with the E-row that will reveal it on the real workspace:
   - the presigned download (CF-095);
   - OAuth M2M (N7);
   - 429 and OTPM against `max_tokens` (CF-009);
   - Lakebase grants and the migration role (CF-010, OD-5);
   - `forward_user_access_token` (CF-033);
   - proxy buffering of the event stream (C42, E9).
3. **`docs/rebuild/ENTERPRISE_HANDOFF.md`.** State:
   - what is proven locally and what only the workspace can prove;
   - the state after D29–D34, and therefore what "Afterwards 1" will show: OD-1 is (b) widened by N52, the bundle is a re-pinned fork, and the live record (`qualification/PROVIDER_RUNBOOK.md`: one set qualified end to end on GPT-6 Luna Pro; CP-0, CP-3D and CP-5 accepted live; stored CP-1 and CP-1A answers pass under the fork) says a capable model is expected past CP-0, and names the modules no real model has yet reached;
   - the owner decisions still open;
   - the rollback path.
4. **CI.** `.github/workflows/ci.yml` runs the same gates as `CLAUDE.md`, with no local-only or CI-only drift (CF-066, CF-067).

## 8. The loop for every step

A step is one register row or one refactor item.

1. **Re-read** the row's sources. Reproduce it at HEAD, or record the before-metric. If it no longer reproduces, reclassify it and move on.
2. **Test first.** For a repair, write the failing test. For a refactor, name the tests and goldens that pin the behaviour; add a characterization test only where nothing pins it.
3. **Make the smallest change.**
4. **Run the targeted checks:** `uv run pytest --no-cov -n 4 <files>`, `tests/parity` when a parity-bound path is touched, and ruff, mypy and every gate the change could move.
5. **Live-test, according to what changed:**
   - Store, graph, worker, model seam or API: `tests/test_platform_boot.py` plus one scenario over HTTP through the adapted DB-14 harness.
   - Frontend: `npm --prefix frontend run test && npm --prefix frontend run build`, the adapted DB-03 journey against the real app, and `test:workbench` for chrome or section changes.
   - Deployment: A34–A37 and `tests/test_enterprise_deploy.py`.
6. **Autoreview:**
   - `confidence-review` on the change;
   - `adversarial-reviewer` (or the `opus55-reviewer` agent) on the step's diff;
   - `rewrite-tournament` on every non-trivial function changed.

   Fix what they confirm. A skill that is not installed is recorded as unavailable, never as run.
7. **Commit.** Stage explicit paths. The message names the register row and its ledger IDs, and the `Fn` entry goes in `docs/rebuild/decisions.md` in the same commit. Then check `git status --short`.
8. **Update `progress.md`:** the row, the commit, the tests, the live-test result, the review result and the metric delta.

At least every tenth commit, and at the end of every phase, run the full gate matrix. A red gate stops new work until it is green again.

## 9. Phase 5: final verification and report

On the final commit, in the final turn, in the main session:
1. Run A1–A37 as written, with a clean tracked tree.
2. Run the pytest suite and the frontend gates again from a fresh detached worktree at the final commit (`git worktree add --detach`). The pass counts must match: the proof that nothing depends on local state.
3. `git diff --stat BASE..HEAD -- tests/parity/golden vendor/deploy-v` is empty, except a change an owner decision named.
4. Compare metrics with BASE:
   - tests passed ≥ BASE minus the tests removed by name in `Fn` entries;
   - coverage ≥ 80%;
   - every suppression count ≤ BASE;
   - `complexity_baselined` ≤ 20, with the removed functions listed, or §6's recorded exception;
   - jscpd ≤ 3%.
5. The shipped-set boot and the governed run (§7.1).
6. Ten consecutive, distinct, realistic scenarios pass on the final commit, through the adapted DB-14 flows: LITE and FULL, gates, cancel, a restart mid-run, and filing through three actors. Set the ceiling as OD-2 and CF-008 leave it.
7. Run a final independent adversarial review of `git diff BASE..HEAD`. Every CRITICAL or HIGH it raises is fixed and re-reviewed; every MEDIUM is fixed or put in `next.md`.
8. The register has zero OPEN rows at CRITICAL or HIGH. Every other OPEN row is fixed or has an N entry. Every DEFERRED, DECISION or PLATFORM-ONLY row names its entry.
9. `git status --short` shows only the untracked paths recorded at BASE, and nothing has been pushed.

**The report**, which must stand alone:
- the EVIDENCE table;
- the register's counts, and every row that is not closed;
- `git log --oneline BASE..HEAD`;
- metrics before and after;
- the owner decisions still open;
- `docs/rebuild/blockers.md` verbatim.

## 10. Environment and parallel work

These are lessons from the 2026-09-23 runs.

- **Postgres.** The suite uses the compose `test-postgres` on 55437, which runs on tmpfs. The Docker VM has about 4 GB of RAM and 2 CPUs; a tmpfs server under a bulk load took the audit's database down. Run scale or load probes against a separate disposable disk-backed container, and stop it afterwards.
- **complexipy** rewrites `complexipy-snapshot.json` on every run (F25). Commit that file only when the baseline legitimately shrinks.
- **Port 4173.** `npm run test:workbench` and `npm run a11y` hard-code it (`--strictPort`), so only one of them runs at a time.
- **Parallel helpers** are allowed for read-only work only: register classification, reproduction and review.
  - Create each worktree yourself: `git worktree add --detach <path> <sha>`. The harness's own worktree isolation cannot run git under the `rtk` command hook.
  - Give each helper its own ports and databases.
  - Never SendMessage a running workflow agent: it starts a second copy in the same worktree.
  - Subagents cannot write report files. Have them return structured output, and write it yourself.
  - Only the lead session edits and commits.
- **Usage limits.** Commit every green step and update `progress.md` after every step. A resumed session starts from `progress.md`, `register.md` and `git log BASE..HEAD`. A resumed workflow replays its cache only if the script is unchanged, because the cache is an order prefix.
- **/goal.** The evaluator reads only the transcript, and background subagents defer evaluation. Run the final acceptance commands in the main session, in the final turn.
- **Live provider.** Use it only under OD-6, only through the test adapter, never as gateway evidence, and never print the key. Check `GET https://openrouter.ai/api/v1/credits` first: an exhausted account answers `PROVIDER_CALL_INVALID` with nothing billed. The cheapest adequate model on 2026-09-23 was `openai/gpt-6-luna-pro`; a run's ceiling holds about six times its actual spend, because every billed attempt keeps its reservation (CF-008).
- **Integrity regeneration.** `verify_package.py --refresh` and `scripts/host_manifest.py` rewrite pins; the permission classifier refuses them without the owner's authorisation in the session, and this sweep has none (OD-8).
- **Prompt goldens.** `tests/parity/goldens.py` refuses any golden not written by the legacy package. A host prompt-text change re-baselines by mirroring the host's texts into a scratch copy of the legacy snapshot (D34); only an owner decision permits it.
- **Other writers.** Other sessions share this checkout (the design session, a CI watcher). Before every commit check `git log -1`, `git status --short` and `.git/MERGE_HEAD`; a merge started from the app's terminal pane waits in vim for `:wq`.
- **`rtk` wrapper.** Some commands are rewritten by the `rtk` hook (`grep -h`, `find -exec`, counts through pipes); prefer Python or plain invocations when an output looks wrong.

## 11. Launch

1. Fill in §0.
2. Make sure no other session is writing this repository.
3. In a Claude Code session in the repository, version 2.1.259 or later (the desktop app qualifies; the `claude` on `PATH` is 2.1.246, B3), run:
   ```text
   /goal <the contents of docs/rebuild/final-sweep/goal.txt>
   ```
4. **Headless, after `claude update`:**
   ```bash
   claude -p "/goal $(cat docs/rebuild/final-sweep/goal.txt)" --permission-mode auto --permission-prompts none --output-format stream-json --verbose
   ```
   Do not use `--bare`: `/goal` runs on hooks. To resume:
   ```bash
   claude -p "Resume the active goal from where you stopped." --continue --permission-mode auto --permission-prompts none
   ```

# Optimization sweep: the contract

A bounded pass over `rebuild/databricks` that finds where the app spends round trips, time, bytes and money, proves which of those costs can fall without changing behaviour, and lands only the proven ones. The condition that drives it is `docs/rebuild/optimization-sweep/goal.txt`; this file is what that condition points at.

Written 2026-10-17 against `ddada2c0`; not yet run. The method is the owner's global one, `~/.claude/optimization-sweep.md`, the sibling of `~/.claude/refactoring-sweep.md`. Where this contract says "as the final sweep", it means `docs/rebuild/final-sweep/CONTRACT.md` at the same commit, which the two share: its operating mode, ledgers, environment lessons and agent rules apply here unless a section below replaces them.

## 0. Owner decisions

The owner fills in the Choice column before launching. A blank Choice means the Default. The sweep reads this table and may not edit it. Each row is a performance trade that changes methodology bytes, parity, the schema, dependencies, an owner-approved behaviour, design direction or spend, so none is the sweep's to make.

| ID | Question | Choice | Default | Recommendation |
|---|---|---|---|---|
| OP-1 | **Live spend for measurement.** Real model latency and tokens can only be measured live (OpenRouter through `tests/` only; no Copilot call, as the final sweep's OD-6). | | 0: measure offline with `tests/fake_chat.py` and the host's own pricing; read real call latency from the live reports already on the owner's machine (`docs/rebuild/runs/live-*`, N145, N209) | 0 |
| OP-2 | **Schema changes for speed:** an index, or a query shape that needs one, is a migration; `scripts/rollback_check.py` then refuses a rollback across it (C1), and the number must not collide (final sweep §1). | | none: a plan finding becomes a `next.md` proposal with its `EXPLAIN (ANALYZE, BUFFERS)` evidence | allow additive index-only migrations after the final sweep has landed |
| OP-3 | **Reductions that move pinned bytes:** prompt text, evidence framing or anything else the `prompt`, `forecast` or `render` goldens, the host manifest or the vendor bundle pin (invariant 4; final sweep OD-7, OD-8). Request bytes are cost, but every one of them is pinned. | | none: measured and proposed only | none; each proposal goes to the owner with its bytes and cost per run |
| OP-4 | **Caching beyond one request:** the verified bundle, verified blob bytes, section reads, or prompt prefixes across runs (D113 built prompt caching; F545 turned it off on OpenRouter). | | none beyond what exists at BASE; memoising inside one request or one node pass is allowed | none: invariant 4 verifies bytes at use, and a shared read cache crosses actors |
| OP-5 | **Code-splitting the workspace** (route- or section-level lazy loading), which adds a loading moment. | | allowed, with the existing `frontend/src/states/` loading view, if the a11y matrix and the workbench pass unchanged | allowed |
| OP-6 | **A profiling or benchmark dependency** (pyinstrument, py-spy, scalene, pytest-benchmark, rollup-plugin-visualizer, web-vitals, Lighthouse; none is pinned today). | | none: `cProfile`, `pstats`, `tracemalloc` and `time.perf_counter` (stdlib); `EXPLAIN` and `pg_stat_statements` in a disposable container; vite's manifest; Playwright's Performance API (pinned) | none |
| OP-7 | **Committed budgets beyond `IO_BUDGET`:** a frontend chunk-bytes check, a request-bytes budget per node, a statement count per worker pass, as new gates. | | each landed row leaves a work-counting test; no new gate script | a `scripts/` budget gate only where two landed rows share a dimension |
| OP-8 | **CI structure:** re-balancing the four test shards (`scripts/ci_tests.py`), splitting `frontend-a11y`, caching. | | allowed while every `CLAUDE.md` gate still runs in CI and `scripts/check_gate_config.py` passes without loosening what it requires | allowed |
| OP-9 | **Order.** Both sweeps change `caos/api/reads/run.py` (R3's `node_readiness`), the store and the reads. | | after the final sweep has merged | after |

## 1. Operating mode

As the final sweep's §1, with these replacements and additions:

- **Scope is the ranked register.** Do §3–§9 in order. Land only CONFIRMED rows at or above §4's floor, in rank order. A new feature, a defect found on the way (it goes to `next.md` with its reproduction, or to the final sweep's register if that sweep is open), or a FORBIDDEN row is not built.
- **No change without its before metric**, measured at HEAD on the harness in §3 immediately before the change, and its after metric on the same harness, data and machine.
- **Hard limits** add: never raise an `IO_BUDGET`, a `BLOB_BUDGET` or a value in `tests/io_measurements.json`; never add a wall-clock assertion to the suite (F444, F620, F621, N197: timed tests fail on CI's runners); never lower a limit that answers with a refusal (`MAX_REQUEST_BYTES`, `MAX_BODY_BYTES`, `extract.DEFAULT_LIMITS`, the stream limits) or change a deadline, lease, heartbeat or retry count: each is behaviour. Never log document text, including in a profile or a statement log (CLAUDE.md conventions): run Postgres statement logging with `log_parameter_max_length=0` and `log_parameter_max_length_on_error=0`, and keep profiles git-ignored.
- **Branch and commits:** `git worktree add -b optsweep/<date> <path> BASE`; one row per commit, each one pull request of at most 800 counted lines; its `Fn` entry states the dimension, the metric before and after, K and the spread.

## 2. Authority and inputs

**Authority:** as the final sweep's §2. A row that would alter what a `Dn` decided is FORBIDDEN, not an optimization.

**The performance ledger at `ddada2c0`.** Every existing budget, limit and measurement; Phase 0 re-reads each.

| Dimension | Artefact | What it measures or limits | Value | Enforced by |
|---|---|---|---|---|
| Section reads, commands | `IO_BUDGET` in every module under `caos/api/` (`scripts/io_budget.py`, CEILING 1024) | store round trips one request may cost; `BLOB_BUDGET` the verified-blob downloads | per module | `io_budget.py --assert` in CI's `lint`, `scripts/fast_gates.sh` and pre-commit; tests count real round trips against it (`tests/test_book_section.py:402`, `counter.executed == book_read.IO_BUDGET`) |
| Section reads, commands | `tests/io_measurements.json` (`MEASURED_MODULES`) | the measured cost a declaration may not fall under; `--record` re-snapshots it | model read 254 round trips, 41 blobs; analysis 251, 40; run 52, 4; `commands/deliverable` 57, 7; reports 46 / 22 / 53 / 42 (report, committee, frozen, unsaved); `reads/deliverable` 20 / 20 / 50; evidence 2, 1; book 2 | `--assert` |
| Commands | `caos/api/commands/execution.py` | the execution command's round trips | 35 | tests, `--assert` |
| Edge | `caos/api/commands/_request.py`, `caos/api/edge.py`, `caos/api/app.py`, `caos/api/stream.py` | body cap; body read grace and floor rate; event tail deadline and poll; streams | 16,384 B; 10 s, 128 KiB/s; 300 s, 0.5 s; 24 streams, 4 an actor, 500 a page | tests |
| Worker and graph | `caos/graph/worker.py`, `caos/store/work.py`, `caos/graph/checkpoint.py` | poll, backoff cap, heartbeat, statement timeout; lease, queued runs; checkpoint pool | 1.0 s, 30 s, 10 s, 30,000 ms; 900 s, 4 an actor; 1–4 connections, 30 s wait | tests; runs stay sequential (D42) |
| Model calls | `caos/provider.py`, `caos/methodology/canonical.py`, `caos/methodology/invocation.py` | request, response, completion caps; deadline; retry reserve; guided retries; bill retries; upstream sections | 4,194,304 B, 4,194,304 B, 65,536 tokens, 3 bytes a token floor; 720 s (D117); 65,536 B; 3; 3 tries 1.0 s apart; 98,304 B (131,072 with #271) | tests, refusals |
| Spend | `databricks.yml` `run_ceiling`, `caos/store/budget.py`, `scripts/preflight.py` | the default run ceiling; the store's fallback; the worst-case-call check | 120.00 (165.00 with #271, final sweep OD-12); 5.00; D29 | tests (invariant 8) |
| Evidence admission | `caos/evidence/extract.py` `DEFAULT_LIMITS`; `scripts/measure_admission.py` | pack and document limits; one large admission timed, extraction and store write apart | 50 documents, 20 MiB a document, 100 MiB a pack, 500 pages, 60 s a document, 300 s a pack; the script asserts nothing | tests (`SOURCE_EXTRACTION_TIMEOUT`); none |
| Store plans | `caos/store/*.sql` | indexes | 12 `CREATE [UNIQUE] INDEX` (7 in `schema.sql`; 0013, 0025, 0026, 0038, 0051 one each); one `EXPLAIN`, `tests/test_store_schema.py:1907` | that test |
| Frontend | `frontend/vite.config.ts`, `frontend/playwright.config.ts` | build: no sourcemap, `es2022`, manifest on, no chunk budget; tests: 30 s timeout, one worker, three browsers | none recorded | none |
| Tests and CI | `.github/workflows/ci.yml`; run 38894824725 on `ddada2c0` | jobs and their timeouts; per shard `-n auto --durations=25`; coverage combined in `test` | about 18 min wall: `frontend-a11y` 17.6 (the critical path), shards 4.5 / 5.5 / 6.4 / 11.0, `bundle` 5.7, `frontend-workbench` 4.9, `frontend-checks` 2.6, `lint` 1.8, `types` 1.0, `security` 0.5 | timeouts only |

Gaps nothing measures at BASE: wall-clock per route, real round trips on Lakebase (the stand-in is local Postgres 17; B5), worker throughput, per-call model latency on the host, frontend bundle bytes and render time, memory beyond the extraction limits, and a regression signal for test time.

**Ledgers.** Stage P's output (`docs/rebuild/perf-<date>/`) is this sweep's ledger, with the `next.md` entries it repeats. The final sweep's register is not reconciled here.

## 2a. Stage P: profile-driven discovery, before the sweep

One fresh lead, measurement helpers, then one finder and one verifier per lane, run before the sweep and not inside it. Its findings land as tracked files the owner reads before filling §0.

**Inputs**

| Layer | File | Section | Why |
|---|---|---|---|
| L0 | `CLAUDE.md` | invariants, conventions | what may never be traded |
| L3 | this contract | §0, §2, §4, §6 | owner trades, the ledger, scoring, the never-traded list |
| L3 | `docs/rebuild/final-sweep/CONTRACT.md` | §2a's sections, §10 | the code's sections and maps; the environment |
| L3 | `docs/rebuild/decisions.md`, `docs/rebuild/next.md` | entries that name a limit, budget or cost | decided limits are not findings; known costs are cited |
| L4 | `docs/rebuild/runs/perf-<date>/profiles/<lane>/` (git-ignored) | all | the lane's evidence, written by the helpers |

**Process**

1. **Start.** The in-flight condition of §11 step 1. Cut `perf/<date>` from the tip in its own worktree; record `PERF_BASE`. Re-index GitNexus (`gitnexus analyze --index-only <path>`, then `gitnexus status` current).
2. **Harness.** `mx-feature` helpers build the harness under `docs/rebuild/runs/perf-<date>/harness/` from what the tree already has: the tests' round-trip counter, `tests/platform_app.py` and `tests/platform_journey.py` (the stand-in platform and one governed run over HTTP), `tests/fake_chat.py` (`ScriptedChat`, the scripted model), `scripts/measure_admission.py`, the committed qualification sets under `qualification/`, the host's own request builders and `caos/pricing.py`, vite's manifest, Playwright against `build:demo`, and `gh run view --json jobs`. The database is a disposable disk-backed Postgres 17 container on its own port, started with `-c shared_preload_libraries=pg_stat_statements` and §1's logging settings, seeded at the scale D146 bounds (1,000 issuers, 100 history rows) with at least 20 finished runs across LITE and FULL routes; never 55436 (the live runs' store) or 55437 (the suite's tmpfs server). Every wall-clock figure is K repetitions (§3) with median and spread.
3. **Profiles.** Run every harness at `PERF_BASE` and file its output by lane.
4. **Find.** One `mx-architect` per lane. It reads its lane's profiles first, then the hot code in full and its callers, as two personas in one pass, written into the brief: the performance engineer (where the cost comes from) and the saboteur (what removing it would break: an invariant, a refusal, a golden, ordering). Lanes, each with the final sweep's sections it reaches:

   | Lane | Dimension | Starts from | Sections |
   |---|---|---|---|
   | L1 | Section reads and commands | the ledger's measured modules, hottest first: the model and analysis reads (about 250 round trips and 40 verified-blob downloads each), run, deliverable, reports, execution | 1, 2, 3, 9, 10 |
   | L2 | Store and Lakebase plans | the statements L1's routes and the worker issue, by total time in `pg_stat_statements`; `EXPLAIN (ANALYZE, BUFFERS)` of each at seeded scale | 3 |
   | L3 | Worker and node passes | host work per node of a FULL route on `ScriptedChat`, the model call excluded (`cProfile`); statements per node pass; checkpoint writes; one large admission (`measure_admission.py`) | 4, 5, 6, 7, 9, 10 |
   | L4 | Request bytes, tokens and cost per run | bytes per node per route over the qualification sets, from the host's own builders; the reservation per attempt against the call's real size (a run's ceiling holds about six times its spend, CF-008); the carried answer's share of a guided retry (D104, F649) | 5, 6, 7, 8 |
   | L5 | Frontend bundle and render | gzip bytes per chunk and the first route's bytes; time to section content and long tasks for Analysis, Model, Book and Run in Chromium | 12, 13, 14 |
   | L6 | Tests and CI | the last ten successful CI runs on `rebuild/databricks` per job; the shards' spread; `frontend-a11y`'s browsers and pages; the slowest 25 tests per shard; the local `-n auto` wall | 11, `tests/`, `.github/` |

   Its final message returns each finding in the method's format (`~/.claude/optimization-sweep.md`, "Finding format"), then a `Not verified:` line.
5. **Verify.** One `mx-adversary` per lane reproduces each finding's before metric on `PERF_BASE`, and where it can, measures the gain with a throwaway patch in a scratch worktree of its own. Verdicts: CONFIRMED, NOT-REPRODUCED, BELOW-THRESHOLD (under §4's threshold or within noise), FORBIDDEN (names the invariant, `Dn` or OP row it would need). A finding a `Dn` decided is FORBIDDEN, not a defect.
6. **Synthesis.** One `mx-architect` merges findings by cause, scores and ranks them by §4, maps each FORBIDDEN row to its OP row or a new owner question, and names the `next.md` entries each repeats.
7. **Write and commit.** The lead writes `docs/rebuild/perf-<date>/findings-<lane>.md` (every finding with its verdict and numbers), `synthesis.md` (the ranked list, the owner questions) and `harness.md` (how each lane was measured, so Phase 0 reruns it), and commits them on `perf/<date>`: documents only. Nothing is pushed; the owner merges.

If Fable is refused, retry once, then `mx-adversary` finds and `mx-precise` verifies, recorded as one model family. At most four agents at once: they share the Docker VM (about 4 GB, 2 CPUs; final sweep §10), and a wall-clock profile taken beside another agent's suite is noise, so the helpers take wall-clock profiles one at a time with nothing else running on the VM, and record the load they saw. No paid or Copilot call, no vendor edit, no gate touched.

**Done** when every lane has its findings file, every finding a verdict, `synthesis.md` and `harness.md` are written and committed on `perf/<date>`, and `git status --short` shows only the untracked paths recorded at the start.

**Launch.** A fresh session on Opus 5.5 at high, in the perf worktree: `Run Stage P of docs/rebuild/optimization-sweep/CONTRACT.md (section 2a), and nothing else.` Six finders, six verifiers and the synthesis exceed the ten-agent guideline for a workflow, so a workflow runs only when the owner asks for one.

## 3. Phase 0: freeze and baseline

1. Start state, environment and every gate exactly as the final sweep's §3 steps 1–3 (acceptance rows A1–A37, with `docs/rebuild/runs/optimization-sweep/` for its state). A red gate at BASE stops the sweep: this sweep repairs nothing; record it and end blocked on it.
2. Re-run Stage P's harness (`harness.md`) at BASE and write `docs/rebuild/runs/optimization-sweep/baseline.md`, one row per metric:

   | Metric | How | K |
   |---|---|---|
   | Round trips and blob downloads per measured route | the tests' counter on the widest seeded case; equals `IO_BUDGET` where the tests pin it | 1 (deterministic) |
   | Wall per hot route (model, analysis, run, event tail) and per cold route | stand-in platform over HTTP, disposable database; median and p95 | 20 |
   | Statements and host time per node pass | FULL route on `ScriptedChat`; `pg_stat_statements` and `cProfile` | 5 |
   | Plans of the top statements by total time | `EXPLAIN (ANALYZE, BUFFERS)` at seeded scale | 3 |
   | Request bytes per node per route; reservation per run | host builders and `caos/pricing.py` over the qualification sets | 1 |
   | Admission time, extraction and store apart | `scripts/measure_admission.py` | 5 |
   | Built bytes per chunk (gzip) and the first route's bytes | `npm --prefix frontend run build`, the manifest, `gzip` in Python | 1 |
   | Time to section content and long tasks | Playwright on `build:demo`, Chromium | 10 |
   | Suite wall | `CAOS_REQUIRE_POSTGRES=1 uv run pytest -n auto -m "not live_provider"` | 3 |
   | CI per job and critical path | the last ten successful runs, `gh run view --json jobs` | 10 runs |

3. Record the noise: the spread of every wall-clock metric, and the machine's load.

## 4. Phase 1: one register, ranked

Write `docs/rebuild/runs/optimization-sweep/register.md` from `synthesis.md`, one row per opportunity. Columns: row, opportunity, lane, dimension, metric before (at BASE), expected gain, impact, confidence, risk, score, class, action, commit, entry. Classes as Stage P's verdicts, plus DUPLICATE and DEFERRED (names its N entry). Re-measure each CONFIRMED row's before metric at BASE; a row whose cost has moved is re-scored.

**Threshold.** A gain counts when the after metric is at least 10% better than the before metric and, for a wall-clock metric, the medians differ by more than twice the larger spread. A deterministic count counts at any strict fall that clears 10%.

**Score = impact × confidence ÷ risk.**

| Impact | Means |
|---|---|
| 5 | ≥ 50% fewer round trips or ≥ 30% lower median on a hot route (model, analysis, run, the event tail) or on host work per node; ≥ 20% less reserved or billed per FULL run; ≥ 25% shorter CI wall |
| 4 | ≥ 25% on a hot route or host work per node; ≥ 10% per FULL run; ≥ 15% CI wall |
| 3 | ≥ 10% on a hot route; ≥ 25% on a cold route; ≥ 10% fewer first-route bytes; ≥ 10% CI wall |
| 2 | ≥ 10% on a cold route or an off-critical CI job |
| 1 | above the threshold, nowhere that matters yet |

| Confidence | Means |
|---|---|
| 3 | the verifier measured the gain with a patch |
| 2 | the profile attributes the cost and the change removes it |
| 1 | from reading alone (not worked) |

| Risk | Means |
|---|---|
| 1 | frontend leaf components, tests, CI configuration (`scripts/ci_tests.py`) |
| 2 | a section read's query composition, pinned by its tests and `IO_BUDGET`; frontend section code |
| 3 | a shared store helper; `caos/evidence` reads; host work in the canonical executor off the ledger path |
| 4 | the checkpoint pool or the worker's pacing; anything near the claim or the lease; OP-2, OP-4 or OP-5 work the owner allowed |
| 5 | `caos/store/budget.py` and reservations, the accepted-attempt ledger (`outcomes`), claim and settle, identity and grants (D147), `caos/copilot.py`'s bill |

Rows with confidence ≥ 2 and score ≥ 2.0 are worked, highest first, ties to the lower risk. FORBIDDEN rows are not scored; each names its OP row or becomes an owner question in `next.md`.

**Exit:** every Stage P finding is on a row, every row has a class, and the worked rows are ranked.

## 5. Phase 2: land, in rank order

For each worked row, §8's loop, and:
- Re-measure the before metric at HEAD; if the cost has gone, reclassify the row and move on.
- Name what pins the behaviour before editing: the route's tests and its `IO_BUDGET`, the parity goldens (`tests/parity`), the graph tests, the worker and race tests (`tests/test_postgres_races.py`), the frontend unit, a11y and workbench suites. Add a characterization test only where nothing pins it.
- Make the smallest change at the cost's cause. A round-trip cut lowers the module's `IO_BUDGET` (and `BLOB_BUDGET`) to the new measured cost and re-records `tests/io_measurements.json` (`uv run python scripts/io_budget.py --record`) in the same commit; a budget never rises.
- Measure the after metric on the same harness; then every other dimension's cheap metrics (round trips, statements, bytes) to show nothing regressed. Below the threshold: revert.
- Leave the guard (§6).

## 6. Guards, and what is never traded

**Guards.** Each landed row leaves a test that counts its work: a route's round trips against its lowered `IO_BUDGET`; a statement count per node pass; a request-bytes figure for a fixed input; a chunk's built bytes read from the manifest (in a test, under OP-7's Default). A guard names its row's `Fn`. No guard asserts wall-clock.

**Never traded,** each with the temptation it closes:
1. Pinned sources only: no prefetching, no discovery.
2. Evidence reads fail closed with a typed code: no cache that answers when the store refuses, no partial read.
3. The host owns identity: no read result shared across actors; no identity cached beyond what BASE does.
4. The bundle verified on the bytes at use: no skipped verification behind a process cache (OP-4).
5. Human gates digest-bound: no gate read from a cache.
6. Exactly-once: the accepted-attempt ledger is the truth; no merged, reordered or deferred ledger write; runs stay sequential (D42).
7. Calculation pure and finite, Decimal on money: no float, no approximation, for speed.
8. Budgets fail closed: a reservation before every call, never approximated, skipped or pooled.
9. The strict canonical envelope: no relaxed parsing.
10. The route resolved once and pinned.
11. Citations anchored or refused: no skipped or sampled anchoring.

And: typed refusals and their codes; every limit and timing contract in §1; the parity goldens and pinned bytes (OP-3); the I/O ceiling of 1024; never logging document text.

**Architecture.** A structural change only where two or more worked rows share one seam, and the commit names the rows. No speculative redesign.

**Stop rule, per row.** Two Sonnet attempts (`mx-feature`), then one by a fresh `mx-escalate` handed off through files. Revert by explicit path and record in `next.md` with the numbers if the gain misses the threshold, a golden, pinned byte or behaviour would have to change, or the `mx-escalate` attempt fails a gate.

**End point.** Phase 2 ends when every worked row is landed or recorded; or three consecutive rows fail to reproduce their gain (Stage P's profiles are stale: record it, stop landing, and recommend a new Stage P); or twelve rows have landed.

**Exit:** every worked row is LANDED with its metric and guard, or recorded with its reason; no `IO_BUDGET`, `BLOB_BUDGET` or `io_measurements.json` value is above BASE; no suppression count is above BASE.

## 7. Phase 3 and 4: re-measure, then readiness

1. **Re-measure** every metric in `baseline.md` at HEAD with the same K; write the after column. Each landed row's gain reproduces; no metric regressed beyond its noise. A regression is reverted or fixed under §8 before Phase 4.
2. **The shipped set boots:** `tests/shipped_boot.py` and `tests/test_enterprise_deploy.py` green (final sweep §7.1).
3. **Stand-in fidelity:** add to `docs/DEPLOYMENT.md` §8 a row for each measurement only the workspace can take, with the check that reveals it: round-trip latency to Lakebase and its pooled connections (B5, B9), the checkpoint pool under the App's process, and real model latency per node (OP-1).
4. **CI:** no local-only or CI-only drift (final sweep §7.4); a changed CI structure passes `check_gate_config.py` as written.

## 8. The loop for every row

As the final sweep's §8, with step 1 "re-measure the before metric at HEAD", step 4's targeted checks plus the row's harness, and step 8's `progress.md` line adding the dimension, the metric before and after, K and the spread. A row at risk 5 also runs `mutmut` over what it changed (D142; final sweep §8 step 4). The full gate matrix runs every fifth commit and at each phase end.

## 9. Phase 5: final verification and report

On the final commit, in the final turn, in the main session:
1. A1–A37 as written, with a clean tracked tree.
2. The suite and the frontend gates again from a fresh detached worktree at the final commit; the pass counts match.
3. `git diff --stat BASE..HEAD -- tests/parity/golden vendor/deploy-v icm/HOST_INTEGRITY_v1.json` is empty.
4. Metrics against BASE: tests passed ≥ BASE; coverage ≥ 80%; every suppression count ≤ BASE; every `IO_BUDGET`, `BLOB_BUDGET` and `tests/io_measurements.json` value ≤ BASE; `complexity_baselined` ≤ BASE; jscpd ≤ 3%.
5. Every landed row's metric measured again in this turn on its harness, its gain over BASE still above the threshold; the cheap metrics of every dimension (round trips, statements, request bytes, built bytes) not above BASE.
6. The shipped-set boot and the governed run (final sweep §7.1); then the final sweep's scenario streak (its §9 step 6) on the final commit.
7. The whole-branch review of `git diff BASE..HEAD`: `mx-architect` (if refused, `mx-adversary`), then `confidence-review` and `rewrite-tournament` on the same diff. CRITICAL and HIGH fixed and re-reviewed; MEDIUM under the final sweep's §8 step 6 rule.
8. `git status --short` shows only the untracked paths recorded at BASE; nothing pushed; no branch but the sweep's moved.

**The report**, standing alone: the EVIDENCE table; `baseline.md`'s before and after columns; the register's counts and every row not landed with its reason; the FORBIDDEN rows as owner questions; `git log --oneline BASE..HEAD` grouped as pull requests with counted lines; the stand-in rows only the workspace can measure.

## 10. Environment and agents

The final sweep's §10 lessons apply (the Docker VM, the stores on 55436 and 55437, port 4173, `complexipy`'s snapshot, the `rtk` wrapper, gates only the full matrix sees). In addition:
- **Noise.** Wall-clock on this machine moves with other sessions' suites and live runs. Take wall-clock measurements with nothing else on the Docker VM, record the load, and treat a gain inside twice the spread as no gain.
- **The stand-in is not Lakebase.** Local Postgres 17 has no network hop per round trip, so round trips, not milliseconds, are what a read optimization proves locally; the workspace measures the rest (§7.3).
- **Profiles hold no document text.** `cProfile` and statement logs name functions and statements; keep parameters out (§1) and keep profiles under `docs/rebuild/runs/` (git-ignored).

**Agents**, by the owner's rules of 2026-10-14 (`~/.claude/CLAUDE.md` §1): all implementation and fixes on Sonnet; a third fix to `mx-escalate`; Opus agents and `mx-architect` review only. Each is dispatched by its `mx-*` name.

| Work | Agent |
|---|---|
| The lead: register, `baseline.md`, `progress.md`, commits, the final turn | the session, Opus 5.5 at high; it writes no code |
| Stage P harness and profiles; Phase 0 and Phase 3 measurement (probes git-ignored) | `mx-feature` |
| Stage P finders and synthesis | `mx-architect` |
| Stage P verification, one per lane | `mx-adversary` |
| Landing a row at risk 1–4 | `mx-feature` (`mx-scaffold` for CI or configuration with a complete spec), reviewed by `mx-precise` |
| Landing a row at risk 5 | `mx-feature`, reviewed by `mx-precise` and `mx-adversary`, with `mutmut` |
| A row's third and later fix | a fresh `mx-escalate`, reading the failed rounds' reports the lead wrote under `docs/rebuild/runs/optimization-sweep/` |
| Whole-branch review | `mx-architect`; if refused, `mx-adversary` |

Every brief carries GitNexus `impact` for the symbols it changes (implementers have no MCP tools), the row's harness command, and: no stub or fake value standing in for real behaviour; no catch-all that hides a failure unless the fail-open is documented and logged; a report that ends with a `Not verified:` line.

## 11. Launch

1. Wait until in-flight work has merged or been parked (final sweep §11 step 1) and, by OP-9's Default, until the final sweep has merged. Make sure no other session is writing this repository and no live run is using the Docker VM. BASE is the tip after that.
2. Run Stage P (§2a) on that tip and merge its findings.
3. Fill in §0 with Stage P's synthesis in hand.
4. Start a session on Opus 5.5 at high effort in your worktree (§1) and run `/goal <the contents of docs/rebuild/optimization-sweep/goal.txt>`. Headless:
   ```bash
   claude -p "/goal $(cat docs/rebuild/optimization-sweep/goal.txt)" --model claude-opus-5-5 --effort high --permission-mode auto --permission-prompts none --output-format stream-json --verbose
   ```

# Final sweep before the enterprise handoff: the contract

The last local pass over `rebuild/databricks` before the app goes to the enterprise workspace (`docs/rebuild/ENTERPRISE_HANDOFF.md`). The condition that drives it is `docs/rebuild/final-sweep/goal.txt`; this file is what that condition points at.

Written 2026-09-23 against `c37733e`; revised the same day against `e4e4e01`, after D29–D34 and F147–F158 landed; revised 2026-09-25 against `9393940`, after D35–D73 and F159–F415 landed (the backlog pass, the R24 audit, reviews 1–5, vendor forks r3 and r4, the redesign and the design brief; §0, §2, §5, §6). It adapts the loop-library prompt *"Refactor until you are happy with the architecture. After each significant step, live-test the system, run autoreview, and commit. Track progress in /tmp/refactor-{projectname}.md"* and gives it an end point. Only confirmed defects are repaired. Only measured problems are refactored. Both are proven. The tree handed over has fresh evidence for every claim.

## 0. Owner decisions

The owner fills in the Choice column before launching. OD-1, OD-2, OD-3, OD-4, OD-8 and OD-9 were decided and implemented before the sweep (D29–D47, and D60–D73 for the design), and OD-5, OD-6 and OD-7 in part: the sweep verifies them like any FIXED-AT-BASE row. OD-10 and OD-11 are open. Live proof of the modules no real model reached waits on OD-6's account credit. The sweep reads this table and may not edit it. A blank Choice means the Default. None of these is the sweep's to decide, because each one changes methodology bytes, parity, dependencies, an owner-approved behaviour, design direction or spend.

| ID | Question | Choice | Default | Recommendation |
|---|---|---|---|---|
| OD-1 | **N32.** Every model tried writes CP-0 `qa_status: Passed` beside a MATERIAL finding, so the vendor validator refuses it (F111). No real run gets past CP-0. Options: (a) record only; (b) one bounded second attempt on that refusal code, with one extra reserved call and first-attempt prompt bytes unchanged; its `Dn` states what the retry carries, and no host text may restate a vendor rule; (c) a host final-check block naming the rule, which breaks prompt parity: a `Dn`, plus an exception to F57's legacy-only golden rule for the `prompt` group, with the procedure that re-baselines it. A vendor `SKILL.md` step is not an option, because it changes vendor bytes (invariant 4). | **(b), approved by the owner 2026-09-23 as D30; widened by the owner to `HANDOFF_INCOMPLETE` and anchoring's refusals (N52, D30 third addendum), with the fourth and fifth addenda, and to `HANDOFF_IDENTITY_MISMATCH` and `HANDOFF_UNDECLARED_FIELD` (D41, G1-16); the set is `canonical.SECOND_ATTEMPT_CODES`** | (a) | done; measured live: `ccl-fy2025-market-dislocation` qualified end to end on it |
| OD-2 | **N31.** Under the 1 MiB request ceiling, a FULL route with real handoffs refuses `REQUEST_OVER_CEILING` at CP-5 by construction. Options: (a) record only; (b) raise `MAX_REQUEST_BYTES` to 4 MiB with a `Dn`, regenerate the pricing goldens from the legacy rule, and re-derive the default run ceiling (CF-008). | **(b), approved by the owner 2026-09-23; implemented pre-sweep as D29 (default ceiling 100.00)** | (a) | (b), if FULL routes are in the enterprise scope |
| OD-3 | **N11.** Replace `databricks-langchain` with one SDK `POST`. This reverses D7 and also retires CF-034/N25 (completion id) and CF-047 (content normalisation). | **no: D7 kept (D39, the owner's backlog table, 2026-09-23); N11, N25 and N34 record only** | no | done |
| OD-4 | **Frontend design direction** (`.impeccable/critique/…frontend-src.md`, P1 items: hollow chrome bands, refusal copy, a type floor that changes `DESIGN.md`). Options: (a) defects only: the P0s and WCAG failures; (b) also the P1 redesign. | **(b), approved by the owner; implemented as D32 and D33 with F151–F158 (merge `0fa8a5e`). Then, by the owner's later decisions: shadcn/ui on Base UI, Geist, light and dark and the app shell (D35–D37, F159–F161); the model's Markdown drawn and charts by Recharts (D60–D62, F376–F388; D61 supersedes D33); desktop only (D63); the design brief's questions and its slices (D64–D73, F389–F415)** | (a) | done |
| OD-5 | **N16.** Refuse-mutation triggers, and a migration role separate from the runtime role. | **Triggers built in the backlog pass the owner ordered (F185, F220: migrations `0033` and `0037`); the separate migration role stays recorded for the enterprise DBA (N16)** | record for the enterprise DBA | record |
| OD-6 | **Live provider spend** during the sweep, in USD. Only through `tests/` (the OpenRouter adapter, `tests/qualify_openrouter.py`), and never counted as gateway evidence. | **$15.00 for all combined testing (owner, 2026-09-23), cheapest adequate model (`openai/gpt-6-luna-pro`); $5.35 spent against key baseline 7.6424595; the OpenRouter account's credit is exhausted (`blockers.md`, Live qualification), so no live call until the owner adds credit** | 0 | add credit if S6 or the modules never reached live are to be proven live |
| OD-7 | **Record-shape and prompt-parity changes** (N10, N18, N19, N28). | **Host prompt text changed under D34 (N53 and the prompt review's host rows) and D38 (the withheld sample workbooks); the prompt goldens stay legacy-derived by mirroring the texts into a scratch copy of the legacy snapshot, and were regenerated that way over forks r3 and r4 (D40, D47). N28 built as a host rule, not a record-shape change (D39, F235: `CanonicalRecord.citation_rule` is written only off `ANY_RUN`, so every stored record keeps its bytes); N10 and N18 record only (D39); N19 still record only** | record only | record only |
| OD-8 | **Vendor bundle edits** (invariant 4). | **Authorised per change, each re-pinned: the deployment fork D31 (build `99ed0dc3`), fork r2 in D34 (build `b160c75e`), fork r3 in D40 (build `e6fc7978`, closing N55, N57 and the prompt review's vendor rows) and fork r4 in D47 (build `820dfc7c`, closing N70); none for this sweep** | no edit | no edit |
| OD-9 | **N63.** A validated Blocked answer from a producer with only OPTIONAL or ADVISORY consumers ends the run. | **Kept failing closed (D34; N63 closed, D39)** | keep | keep |
| OD-10 | **N73.** The second attempt relays the T8 parser's lines as D30 and G1-16 wrote them, and some carry the answer's own values (`unknown or non-navigable module: {module_id}`, `{readiness!r}`). Withholding them, as F292 does for the research messages, narrows D30's relay. | | as built | none recorded |
| OD-11 | **N95**, with N98's remainder. A register of ten or more columns scrolls sideways inside its card; reading it a row at a time (a row's fields as a card, the id and figures first) waits on the owner's choice of form, and so does which columns of a wide table give way first. | | as built (F376 opens a register eight rows at a time; F394 holds its first column) | none recorded |

## 1. Operating mode

You are operating autonomously. Nobody can answer, approve or unblock you. Never ask, never wait, and never end a turn with a plan, a question or a promise. End only when §9 holds, or when every remaining item is blocked on something only the owner or the workspace can supply.

- **Scope is the deliverable.** Do §3–§9 in order. Do not narrow, widen or swap the scope. A new feature or requirement goes in `docs/rebuild/next.md`; it is not built. An owner decision is never taken for the owner.
- **Evidence.** Audit every claim against a tool result from this session. A failing command is reported with its output. The final message copies command, exit code and summary from tool output produced in that same final turn.
- **Blockers.** A missing credential, host, permission or workspace goes in `docs/rebuild/blockers.md` with the exact command and error; then continue with everything else. A failing test, gate, parity check or review finding is never a blocker.
- **Hard limits.**
  - Never push. Never edit `vendor/deploy-v/`: the owner's authorisations for D31, D34, D40 and D47 were per change and do not extend to this sweep (OD-8). Never print, log or persist a key, token, minted credential or password-bearing URL.
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
| `findings.md` at the root (git-ignored, so on the owner's machine only; no tracked file holds the CF ledger, which survives in the repository only as citations). The 16-goal campaign is at the top between the `audit-campaign-2026-09-23` markers; the older reviews are below it. | CF-001–CF-106; C1, C2, W1–W7 and the other reviews' IDs |
| `docs/rebuild/findings.md`: the R24 audit of 2026-09-24, with its status table (each ID's `Fn` or `Dn`); the reconciliation of the MAX list it replaced; the preserved FP review | R24-01–R24-18, R24-N01–R24-N03, R24-L01; MAX-01–MAX-22 and MAX-N01–MAX-N03 (their dispositions); FP-01–FP-41. AR-01–AR-25 were defined in an earlier version of this file and are only cited today (round 3, `decisions.md`): read them from its history |
| `docs/rebuild/findings-round2.md` | the deployment review's C1–C4, W1–W5, N1–N7; SA-C1–SA-C5; MX-1–MX-7; AS-1–AS-6, TM-1–TM-6, AI-1–AI-8, CR-1–CR-11, DL-1–DL-10, DP-1–DP-12, FE-1–FE-12, SI-1–SI-12; EI-W1–EI-W6, EI-N1–EI-N9 |
| `docs/rebuild/round3/findings-round3.md` and `round3/decisions-*.md` | R3-1–R3-5 (N30, the remainder, was reviewed in round 4: F113–F146) |
| `docs/rebuild/round4/findings-{store,edge,evidence,deliverable,deploy}.md` (60 findings; F113–F146 closed them but for what F146 lists) | ST-1–ST-15, ED-1–ED-9, EV-1–EV-8, DQ-1–DQ-15, DF-1–DF-13 |
| Reviews 1–5 of 2026-09-24, and the reviews of F310–F324 and of D60 and D61: no findings file; `decisions.md` and `next.md` cite each ID with its review, and the IDs repeat across reviews, so a register row writes `review 2: W5` | review 1 (F296–F304, F363, F364; N80), review 2 (F290–F294, F305–F309, F334, F341; N73), review 3 (F336–F346; N74), review 4 (D50, F353–F362; N81–N83), review 5 (W-A–W-C, N-1–N-3: F348–F352, F367; N74–N79); F325–F333 and F370–F375 by severity only |
| `.impeccable/critique/2026-09-23T11-45-42Z__frontend-src.md` (untracked owner file; `decisions.md`'s "Design critique plan", F151–F158), and the later `/impeccable` critique of the Analysis section (F376–F388) | P0, P1 |
| `docs/rebuild/prompt-review-2026-09-23.md` | G1-1–G1-18, G2-1–G2-18, G3-1–G3-17 (every row FIXED, DECIDED or NOT-A-DEFECT at `9393940`; the table was updated after `e4e4e01`, its "Status is as of `e4e4e01`" line was not) |
| `docs/rebuild/2026-09-25-design-brief.md` | section 5 (screen by screen), 6.1–6.13 and questions 1–6 (answered by D64–D69); tracked as N96–N106; 6.5's remainder is N98, and 6.13 and every phone item were withdrawn by D63 |
| `docs/rebuild/next.md` | N1–N106 (N66, N67 and N84–N89 unused) |
| `docs/rebuild/blockers.md` | B1–B9 (B9 with three addenda), and the Live qualification entry (OpenRouter account credit) |

The `Fn` entries in `decisions.md` (F1–F415; F162–F166 unused) record what was fixed; D29–D73 (D51–D59 unused) record the decisions since 23 September, the owner's among them as each entry says. Live-run evidence: `qualification/PROVIDER_RUNBOOK.md` (the 23 September sections; no live call since, its status line) and `docs/rebuild/runs/live-2026-09-23/` (git-ignored).

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
   - `docs/rebuild/final-sweep/` is tracked (since `0fa3c41`). If the owner's §0 choices left it with uncommitted edits, commit them first, by explicit path, as the sweep's own first commit.
   - Record `BASE=$(git rev-parse HEAD)` in `docs/rebuild/runs/final-sweep/progress.md`.
2. Set up the environment: `uv sync --locked --all-groups`, `docker compose up -d --wait`, then `npm --prefix frontend ci --ignore-scripts && npm --prefix frontend run build`. Record `uv run python -V`, `node -v`, the Databricks CLI version, and which `CAOS_*`, `DATABRICKS_*` and `OPENROUTER_API_KEY` variables are set (names only).
3. Run every gate in `CLAUDE.md` exactly as written; together they are acceptance rows A1–A37 (spec §11, plus A34–A37 from D28 and F73). The stand-in rows A34–A37 now run for all four targets, `dev` and `prod` on a Lakebase Autoscaling project and `dev-provisioned` and `prod-provisioned` on an instance (R24-14, D49), each deploy followed by its `--shipped` check (DF-4); `check_gate_config.py --against <an earlier commit>` runs as CLAUDE.md writes it, both trees under the current patterns and under that commit's own checker (F357, W5). Record each exit code and summary line in `progress.md`.
4. Record the baseline metrics:
   - passed test count and coverage;
   - each suppression count, as measured by `scripts/check_gate_config.py`;
   - `complexity_baselined` (21 at `9393940`; 25 at `e4e4e01`; 26 at `c37733e`) and the list of baselined functions (`tests/gate_baseline.json` keys each one, `complexity:<path>::<name>`);
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

At `9393940` a `decisions.md` entry names 77 of CF-001–CF-106 (§5 lists its seeds' entries per group), most of them from the backlog pass (D38–D48, F159–F249) and most as fixed; D39 keeps CF-034 as it is (N25). Of the 29 no entry names, rounds F71–F109 and round 4 (F113–F146) likely closed some: CF-001 by F72 and R3-3, CF-003 by F102, CF-005 by F93, CF-050 by F97, CF-053 by F76. Neither "likely" nor an entry naming a row is evidence, so check each one.

N30 is done (round 4, F113–F146), and most of what landed after `e4e4e01` has had a review: the R24 audit (from `01d4c57`, the backlog merge `9b591af` included), reviews 1–5 (review 5 on the snapshot `24d9ae8`), the adversarial review of F310–F324 and the inline review of D60 and D61. No review is recorded for what landed after review 5's snapshot: review 4's and review 5's fixes, review 1's residuals and the rest of F347–F369 and D50; the Analysis critique's changes (F376–F388, self-reviewed only); and the design brief's slices and decisions (F389–F415, D63–D73, among them D73's new wire field `RunView.edges`). Review those with the `adversarial-reviewer` skill, or the `opus55-reviewer` agent, in a worktree at BASE. Its confirmed findings enter the register.

**Exit:** every ID in every ledger is on a row, with counts per class and severity, and the OPEN rows are ranked by §5's order.

## 5. Phase 2: repair confirmed defects, grouped by root cause

Work through the groups in this order. Within a group, higher severity goes first. The CF numbers are seeds; every ledger ID on the same row goes with them. A seed followed by entries in brackets is one those `decisions.md` entries name at `9393940`, most as fixed (D29 derives the ceiling around CF-008 rather than changing it): reproduce the original at BASE and class it FIXED-AT-BASE only if it no longer reproduces. A bare seed is named by no entry.

| Group | Scope | Seed rows |
|---|---|---|
| A | Deploy and first-run blockers: anything that stops `scripts/enterprise_deploy.sh` E1–E10 (either Lakebase kind, D49) or the handoff's "Afterwards 1" | the deployed file set (CF-001, R3-3; no CI step boots the shipped set yet, §7.1); migrations under the documented grant (CF-010; F302 and F364 changed what a first boot needs); E5 and the preview flag (CF-033); model or volume reachability through the app (CF-054 (F246, F354: row E10)) |
| B | Evidence integrity and citations (invariants 2, 11) | CF-002 (F128), CF-012, CF-013 (F204), CF-014 (F125), CF-015 (F128), CF-016 (F235), CF-017 (F234), CF-021, CF-072 (F203), CF-073 (F203, F234), CF-074 (F202) |
| C | Text and secret leakage | CF-022 (F183), CF-023 (F120), CF-024 (F120), CF-077 (F214), CF-078 (F178) |
| D | Authority, human gates, filing and qualification (invariants 3, 5) | CF-018, CF-019, CF-026 (F222), CF-027 (F194), CF-028 (F131), CF-029 (F130), CF-030, CF-031 (F131), CF-081 (F199), CF-082 (F120), CF-083 (F133), CF-084 (F232) |
| E | Durability and exactly-once (invariant 6) | CF-005, CF-006, CF-007 (F117), CF-037 (F182), CF-038 (F115), CF-039 (F180), CF-040 (F116), CF-041 (F181), CF-042 (F114), CF-043, CF-044 (F186, F311) |
| F | Money and budgets (invariants 7, 8) | CF-008 (D29), CF-046 (F117), CF-048 (F179), CF-089 (F212), CF-090 (F117), CF-091 (F185, F220); OD-2 is implemented (D29) |
| G | Availability and resource bounds | CF-003, CF-004, CF-049 (F129), CF-050, CF-051 (F192), CF-052 (F119), CF-053, CF-075 (F193, F342) |
| H | The primary journey | OD-4 is implemented and the workspace redesigned since (D32–D37, D60–D73; F151–F161, F310–F333, F370–F415): verify the critique's P0 and WCAG repairs at BASE rather than redo them, then Start and Retry usable (CF-011; F261 and F314 changed both), refusal text that is true (CF-056 (F189), and the operator hints G2-17 (F200)), CF-057, CF-058 (F160), CF-059 (F161), CF-097, CF-098; within `DESIGN.md` as it now stands, desktop only (D63) |
| I | Gate and test credibility | CF-061, CF-062 (F242), CF-063 (F170), CF-064 (F172), CF-065, CF-066 (F140), CF-067 (F140), CF-068 (F134), CF-069 (F134), CF-070 (F198), CF-071 (F177, F240), CF-079 (F173), CF-092 (F184), CF-103, CF-104, CF-105 (F174), CF-106 (F184) |
| J | The prompt review | Every row of `docs/rebuild/prompt-review-2026-09-23.md` reads FIXED at `9393940` (G2-12 DECIDED, G3-15 NOT-A-DEFECT for the host), the four host rows this group seeded at `e4e4e01` among them: G1-12 (D38), G1-16 (the D30 fifth addendum, F210, D41), G2-17 (F200), G3-9 (F211). Verify each at BASE; no vendor row waits on OD-8 |
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
| R1 | Delete what the decisions already dropped, or what nothing uses | Done before BASE, item by item below: verify each, and delete only what a fresh search still finds |
| R2 | One source for each duplicated fact | Done before BASE; verify each. The deploy defaults live in `databricks.yml`, and `scripts/bundle_defaults.py` serves them to `enterprise_deploy.sh`, `enterprise_deploy.py` and the stub (N23, F245, F362); `PG_PORT` and `PG_SSLMODE` stay shell defaults, not bundle variables, and `enterprise_deploy.sh`'s header and `docs/DEPLOYMENT.md` §1 restate the defaults in prose. The status tables (N29, F251): `app.TRANSIENT` is derived from `_STATUS`, and `edge.EDGE_STATUS` stays because the edge cannot import the app, held to `_STATUS` by a test. "Store both bodies, or fail with `STORE_UNAVAILABLE`" is one helper, `BlobStore.put_both` (F253), called from `runtime._settle` and `ModuleProvider.execute` (the read path behind CF-006 was fixed by F91 and is not part of this) |
| R3 | Complexity | Bring baselined functions to 15 or below and remove them from `complexipy-snapshot.json`, and their `complexity:` keys from `tests/gate_baseline.json`, so the count falls. **Required**, on invariant paths: `deliverable/render.py::_list` (31, the AR-08 site), `methodology/handoff.py::stored_lineage` (30), `evidence/pdf.py::walk_pages` (23), `api/stream.py::case_tail` (22). `methodology/forecast.py::_mapped_rows` and `graph/route.py::dependency_order` (F250), required at `e4e4e01`, left the baseline before BASE. `render.py`'s bytes are pinned by `caos/deliverable/verify_package.py::RENDERER_SHA256`, which moves with them in the same commit, as F255 did (its comment: "Updated with render.py; the archived verifier retains its historical pin"); the `render` goldens stay byte-identical. **Then, as budget allows:** `store/run_inputs.py::_research` (20), `methodology/selection.py::select_sources`, `api/reads/run.py::node_readiness` (17 each), `deliverable/revisions.py::_span` (16); `read_analysis` and `ingest._prepare` already left. Only after those: the qualification matrix, harness, on-disk and proof functions, `methodology/vendor.py::_Loader::_import`, and `methodology/invocation.py`, whose prompt bytes the prompt goldens pin. |
| R4 | Stage contracts | Done before BASE (F254, SI-12): Process and Outputs are stated once in `icm/CONTEXT.md`, and each of the 27 stage contracts points at them through `scripts/icm_stages.py`. Verify `check_icm` and `icm_stages.py --check` green and prompt parity unchanged. |
| R5 | Frontend (not design) | Done before BASE, differently: the modal hook is deleted and the evidence drawer, source drawer and metric passport are one `evidence/Overlay.tsx` on Base UI's Dialog (F318, N64), not a native `<dialog>`. Verify the a11y matrix, the workbench and the opener focus return. |
| R6 | Documents that match the code | See below |

**R1 in detail**, each done before BASE; verify it:
- The HMAC edge-assertion mode is deleted (F188; D10, N12, CF-080), its tests removed by name in F188; boot refuses a leftover `CAOS_EDGE_TOKEN` (`edge.RETIRED_ENV`, F340).
- `scripts/check_postgres.py` and `scan_floors --trivy`/`--min-files` are deleted (F175).
- `case_tail`'s dead overloads and `_status_refusal`'s dead branch are gone, and `runs.fail_run`, which only tests called, lives in `tests/run_terminals.py` (F251). Look for any other production definition only tests call (N29).
- Seven refusal codes no condition raised are retired (D43, CF-099). Look for any other.
- `FORECAST_CHAIN_BROKEN` is retired with `cash_flow._check_chain` (D43, N6), and the wire schema and `documents.ts` followed (F217). If a sweep change drops another wire code, regenerate `frontend/src/wire/v1/schema.json` from `python -m caos.api.wire`, which prints the schema to stdout.
- The stale journey configuration is retired (F239, CF-102): `playwright.journey.config.ts`, `journey.spec.ts` and `test:journey` are gone; `tests/journey/pack.py` stays for the admission tests.

**R6 in detail:**
- Spec statements the as-built system contradicts (CF-100): F243 corrected §4, §6 and §12 in place. Still to correct: §5's G14, which baselines "the 26 legacy functions" (21 at `9393940`), and §11, whose A-rows stop at A33 while A34–A37 live only in decisions (D28, F73) and now cover the Provisioned pair (R24-14). Correct each in place with a "(corrected: Fn)" pointer.
- Citations of documents not in this repository (CF-101): F255 repointed 43 files in `caos/` and `scripts/` and three frontend files (no frontend file names `server/api` now), and F287 86 comments under `tests/`. Left at `9393940`: `IA_SPEC.md`, cited by 39 files, 35 of them under `frontend/src`; and older citations F255 did not reach, in `caos/store/schema.sql` (`docs/REBUILD_PLAN.md`, `SYSTEM_SPEC.md`, `docs/DECISIONS.md`, `docs/AI_CODE_QUALITY.md`), `caos/api/reads/run.py` and `caos/methodology/handoff.py` (`REPAIR_PLAN`), `scripts/check_vocabulary.py` (`SYSTEM_SPEC`, `DECISIONS.md`) and `frontend/src/ds/VENDORED.md`. The prompt goldens quote the bundle's own file names and are not citations.
- `blockers.md`: B1, B4 and B8 were brought up to date on 2026-09-24 (B8's recipe by F242, CF-062). B9's addenda stop at 2026-09-23, before E10 (F246, F354) and the Lakebase Autoscaling default (D49): bring B9 up to date.
- Ledgers that lag the code: `next.md`'s N29 is marked closed only for the modal hook, though F175, F250, F251, F253, F254 and F318 closed the rest; N52 still says "unmerged", though `canonical.SECOND_ATTEMPT_CODES` carries it; N99 still says "but for the node cards", the part D72 settled as N105; the prompt review's "Status is as of `e4e4e01`" line.
- `docs/DEPLOYMENT.md` has a rollback path (§6: `scripts/rollback_check.py`, F241, F353) and a health smoke that sends the bearer (§5, F241, CF-096): verify both work as written.
- `CLAUDE.md` stays under 120 lines (41 at `9393940`) and matches the gates.

**Architecture.** Beyond R1–R6, a structural change is allowed only where two or more confirmed register rows share one seam, and the commit names the rows it retires. No speculative redesign. No N1 parallelism (runs stay sequential, D42). Nothing of OD-3, OD-7, OD-10 or OD-11 beyond what its Choice says.

**Stop rule, per item.** Allow at most two attempts. Revert the item by explicit path and record it in `next.md` with the reason if either of these happens:
- it would need a golden, vendor byte, dependency or behaviour change;
- the same gate fails twice.

**Exit:**
- The four required R3 functions are out of the baseline, so the count is 17 or lower (21 at `9393940`). The only exception is a required function whose two attempts the stop rule ended: its `next.md` entry names the golden, gate or behaviour that refused it, and the count is reported with that exception.
- R1, R2, R4 and R5 are verified at BASE (or what a fresh search found is done or recorded), and R6 is done or recorded.
- No suppression count is above BASE.
- The net line count is reported.

## 7. Phase 4: enterprise readiness

1. **The shipped set boots.**
   - Deploy through the stub (A35–A37), on either Lakebase kind (D49).
   - Boot `python -m caos.serve` from the deployed file set itself, not the repository, and complete one governed LITE run through `ChatDatabricks` over the stub, with every health code OK.
   - Make this a CI step if none exists (CF-001's repair direction). At `9393940` none does: the `bundle` job deploys and runs all four targets through the stub and checks each deploy's synced files with `check_gate_config.py --shipped` (DF-4, F48), but the stub's `bundle run` starts no process, and `tests/platform_app.py` boots `caos.serve` from the repository.
   - Run `tests/test_enterprise_deploy.py` green.
2. **Stand-in fidelity.** In `docs/DEPLOYMENT.md`, list every known gap between the stub and the platform, each with the E-row that will reveal it on the real workspace. At `9393940` its §8 names some of them in one sentence, with no E-row per gap:
   - the presigned download (CF-095; F237 turned the SDK's experimental files client off, so say what is left);
   - OAuth M2M (N7; the stand-in runs the service principal's own M2M since F248);
   - 429 and OTPM against `max_tokens` (CF-009);
   - Lakebase grants and the migration role (CF-010, OD-5), and what the platform injects for each kind's resource (D49, E6);
   - `forward_user_access_token` (CF-033, E5);
   - proxy buffering of the event stream (C42, E9);
   - the app's own model call, which no real model has answered through E10 yet (F354, N82).
3. **`docs/rebuild/ENTERPRISE_HANDOFF.md`.** It already states what is proven locally, the live record and the rollback path; bring it up to date and add what it lacks:
   - what is proven locally and what only the workspace can prove;
   - the state after D29–D73 (it cites D29–D45 at `9393940`), and therefore what "Afterwards 1" will show: OD-1 is (b) widened by N52 and D41, the bundle is fork r4 (D47), and the live record (`qualification/PROVIDER_RUNBOOK.md`, unchanged since 23 September: one set qualified end to end on GPT-6 Luna Pro; CP-0, CP-3D and CP-5 accepted live; stored CP-1 and CP-1A answers pass under the fork) says a capable model is expected past CP-0, and names the modules no real model has yet reached;
   - the owner decisions still open (OD-10, OD-11, and the enterprise ones §0 records), which it does not list at `9393940`;
   - the rollback path (`scripts/rollback_check.py` first, F353).
4. **CI.** `.github/workflows/ci.yml` runs the same gates as `CLAUDE.md`, with no local-only or CI-only drift (CF-066, CF-067). Since F140 and F355, `check_gate_config.py` refuses a `CLAUDE.md` gate missing from CI, reading `ci.yml` as YAML. At `9393940` CI also runs two commands `CLAUDE.md` does not list, `scripts/document_register.py` (F69) and `vendor/deploy-v/verify_package.py` (spec A27): list them in `CLAUDE.md` or record in `next.md` why they stay CI-only.

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
   - `complexity_baselined` ≤ 17, with the removed functions listed, or §6's recorded exception;
   - jscpd ≤ 3%.
5. The shipped-set boot and the governed run (§7.1).
6. Ten consecutive, distinct, realistic scenarios pass on the final commit, through the adapted DB-14 flows: LITE and FULL, gates, cancel, a restart mid-run, and filing through three actors. Set the ceiling as OD-2 and CF-008 leave it. An actor holds at most four queued or running runs (D46, `QUEUED_RUNS_LIMIT_REACHED`), so end or cancel each scenario's run before the next.
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

These are lessons from the 2026-09-23 and 2026-09-24 runs.

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
- **Integrity regeneration.** `verify_package.py --refresh` and `scripts/host_manifest.py` rewrite pins; the permission classifier refuses them without the owner's authorisation in the session, and this sweep has none (OD-8). `caos/deliverable/verify_package.py::RENDERER_SHA256` is not one of these: it moves with `render.py`'s bytes (R3, F255).
- **Gates only the full matrix sees.** A comment-only edit to `render.py` moved `RENDERER_SHA256`, which only the suite catches (e66f2da); two names bandit's B105 reads as passwords failed the bandit floor on the merged tip (F369); an import the TypeScript vocabulary gate reads as a synonym left the base's `frontend` job red for several commits (F389). Run the full matrix on the merged result, not only on the branch.
- **Prompt goldens.** `tests/parity/goldens.py` refuses any golden not written by the legacy package. A host prompt-text change re-baselines by mirroring the host's texts into a scratch copy of the legacy snapshot (D34; forks r3 and r4 re-baselined the same way, D40, D47); only an owner decision permits it.
- **Other writers.** Other sessions share this checkout (the design session, the audits session, a CI watcher). Before every commit check `git log -1`, `git status --short` and `.git/MERGE_HEAD`; a merge started from the app's terminal pane waits in vim for `:wq`.
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

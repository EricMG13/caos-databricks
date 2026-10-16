# Final sweep before the enterprise handoff: the contract

The last local pass over `rebuild/databricks` before the app goes to the enterprise workspace (`docs/rebuild/ENTERPRISE_HANDOFF.md`). The condition that drives it is `docs/rebuild/final-sweep/goal.txt`; this file is what that condition points at.

Written 2026-09-23 against `c37733e`; revised the same day against `e4e4e01`, after D29–D34 and F147–F158 landed; revised 2026-09-25 against `9393940`, after D35–D73 and F159–F415 landed (the backlog pass, the R24 audit, reviews 1–5, vendor forks r3 and r4, the redesign and the design brief; §0, §2, §5, §6). Run once, on 2026-09-25 at BASE `2a4f983` in a cloud container (F416–F431; N107–N116; B10, B11). Revised 2026-10-11 against `78c4f17`, after D74–D142 and F432–F622 landed: the GitNexus review, the model selector, GitHub Copilot as the model, the live-run fixes with vendor forks r5–r14, citations as excerpts and markers, depth 1a, the chart series and the first Book/Model pull requests (every section). The method is the owner's global one, `~/.claude/refactoring-sweep.md`, and this is its worked example. It adapts the loop-library prompt *"Refactor until you are happy with the architecture. After each significant step, live-test the system, run autoreview, and commit. Track progress in /tmp/refactor-{projectname}.md"* and gives it an end point. Only confirmed defects are repaired. Only measured problems are refactored. Both are proven. The tree handed over has fresh evidence for every claim.

## 0. Owner decisions

The owner fills in the Choice column before launching. OD-1, OD-2, OD-3, OD-4, OD-8 and OD-9 were decided and implemented before the sweep (D29–D47, D60–D74, D82–D84, D99–D107, D111, D122–D141), and OD-5, OD-7, OD-16 and OD-17 in part: the sweep verifies them like any FIXED-AT-BASE row. OD-6 is not set for this sweep. OD-10 to OD-15 and OD-18 are open; OD-12 to OD-18 are the owner questions `next.md` has recorded since 25 September. The sweep reads this table and may not edit it. A blank Choice means the Default. None of these is the sweep's to decide, because each one changes methodology bytes, parity, dependencies, an owner-approved behaviour, design direction or spend.

| ID | Question | Choice | Default | Recommendation |
|---|---|---|---|---|
| OD-1 | **N32.** Every model tried writes CP-0 `qa_status: Passed` beside a MATERIAL finding, so the vendor validator refuses it (F111). No real run gets past CP-0. Options: (a) record only; (b) one bounded second attempt on that refusal code, with one extra reserved call and first-attempt prompt bytes unchanged; its `Dn` states what the retry carries, and no host text may restate a vendor rule; (c) a host final-check block naming the rule, which breaks prompt parity: a `Dn`, plus an exception to F57's legacy-only golden rule for the `prompt` group, with the procedure that re-baselines it. A vendor `SKILL.md` step is not an option, because it changes vendor bytes (invariant 4). | **(b), approved by the owner 2026-09-23 as D30; widened by the owner to `HANDOFF_INCOMPLETE` and anchoring's refusals (N52, D30 third addendum), with the fourth and fifth addenda, and to `HANDOFF_IDENTITY_MISMATCH` and `HANDOFF_UNDECLARED_FIELD` (D41, G1-16); then guided retries that name the true line (D82, the owner's 2 October decision), three of them, so four attempts a node (D82 amendment, `canonical.GUIDED_RETRIES`), each carrying the refused answer back (D104); D106 took anchoring's refusals out again (a citation fault refuses the citation, not the answer), so the set is `canonical.SECOND_ATTEMPT_CODES`, the four structural codes** | (a) | done; measured live: `ccl-fy2025-market-dislocation` qualified end to end on it (2026-09-23), and the CZR live loop of 2–7 October ran on D82 and D104 |
| OD-2 | **N31.** Under the 1 MiB request ceiling, a FULL route with real handoffs refuses `REQUEST_OVER_CEILING` at CP-5 by construction. Options: (a) record only; (b) raise `MAX_REQUEST_BYTES` to 4 MiB with a `Dn`, regenerate the pricing goldens from the legacy rule, and re-derive the default run ceiling (CF-008). | **(b), approved by the owner 2026-09-23; implemented pre-sweep as D29 (default ceiling 100.00); then `MAX_UPSTREAM_HANDOFF_BYTES` 98,304 and the default ceiling 120.00 (owner, 3 October; D83), raised to 165.00 for three guided retries (owner, D152 R6; OD-12)** | (a) | done |
| OD-3 | **N11.** Replace `databricks-langchain` with one SDK `POST`. This reverses D7 and also retires CF-034/N25 (completion id) and CF-047 (content normalisation). | **no: D7 kept (D39, the owner's backlog table, 2026-09-23); N11, N25 and N34 record only. GitHub Copilot is a second transport behind the same factory (D77), not a replacement of D7** | no | done |
| OD-4 | **Frontend design direction** (`.impeccable/critique/…frontend-src.md`, P1 items: hollow chrome bands, refusal copy, a type floor that changes `DESIGN.md`). Options: (a) defects only: the P0s and WCAG failures; (b) also the P1 redesign. | **(b), approved by the owner; implemented as D32 and D33 with F151–F158 (merge `0fa8a5e`). Then, by the owner's later decisions: shadcn/ui on Base UI, Geist, light and dark and the app shell (D35–D37, F159–F161); the model's Markdown drawn and charts by Recharts (D60–D62, F376–F388; D61 supersedes D33); desktop only (D63); the design brief's questions and its slices (D64–D73, F389–F415); the module workbench (D74, F458–F464); depth 1a "Layered" (D122, F613–F615, amending D37's primary and `DESIGN.md`'s signal-only colour); a chart for every module's registers (D123–D140, F616–F619; D139's risk matrix is the one exception to "drawn by Recharts")** | (a) | done |
| OD-5 | **N16.** Refuse-mutation triggers, and a migration role separate from the runtime role. | **Triggers built in the backlog pass the owner ordered (F185, F220: migrations `0033` and `0037`); the separate migration role stays recorded for the enterprise DBA (N16)** | record for the enterprise DBA | record |
| OD-6 | **Live provider spend** during the sweep, in USD. Only through `tests/` (the OpenRouter adapter, `tests/qualify_openrouter.py`), and never counted as gateway or Copilot evidence. No Copilot call at all: none may be made before the firm-seat spike (N177, D77 addendum 2), nor without an amount the owner authorises (N185). | **Not set for this sweep.** Standing: $75.00 for all combined live testing (owner, 2026-10-06; D141 cites it), $30.00 of it left at key usage 45.37 (owner, 2026-10-11), shared with every other session's live runs; the live loop's model is `openai/gpt-6-luna` at high effort on the `openai` tier (F479), priced by N152's pin rule | 0 | set an amount only if S6 or the modules no real model has reached are to be proven live |
| OD-7 | **Record-shape and prompt-parity changes** (N10, N18, N19, N28). | **Host prompt text changed under D34 (N53 and the prompt review's host rows) and D38 (the withheld sample workbooks), and since 2 October, by the owner's decisions, as deliberate departures from the legacy `prompt` group: D81 (F477), D93 (F481), D102, D105 (F500), D106 (F503), D107 (F505, with the `forecast` group), D113, and fork r14 (D141). Every one was regenerated by D34's procedure, mirroring the host's texts into a scratch copy of the legacy snapshot, as forks r3 and r4 were (D40, D47). N28 built as a host rule (D39, F235), then superseded for new answers by excerpts (D105). Record shape: `RECORD_CODEC_VERSION` 3 (D106, D107, D109), across which `rollback_check.py` refuses a rollback. N10 and N18 record only (D39); N19 still record only** | record only | record only |
| OD-8 | **Vendor bundle edits** (invariant 4). | **Authorised per change, each re-pinned by D31's procedure: the deployment fork D31 (build `99ed0dc3`), fork r2 in D34 (build `b160c75e`), fork r3 in D40 (build `e6fc7978`), fork r4 in D47 (build `820dfc7c`); then, under the owner's authorisation of 3 October to edit vendor files for performance and reliability (D84), forks r5–r12 (D84–D100, D103); r13 for D111's changes only; r14 for the CP-1 amendment only (D141: build `d73f4b91`, manifest `2f7e9635`, authority bundle `97106f19`). F432 and F452 refreshed the CP-0 validator copies by the same procedure. None for this sweep** | no edit | no edit; the vendor items `next.md` holds (N132, N133, N136 and N164, N163, N192, N196) wait for an owner-approved round |
| OD-9 | **N63.** A validated Blocked answer from a producer with only OPTIONAL or ADVISORY consumers ends the run. | **Kept failing closed (D34; N63 closed, D39)** | keep | keep |
| OD-10 | **N73.** The second attempt relays the T8 parser's lines as D30 and G1-16 wrote them, and some carry the answer's own values (`unknown or non-navigable module: {module_id}`, `{readiness!r}`). Withholding them, as F292 does for the research messages, narrows D30's relay. | | as built | none recorded |
| OD-11 | **N95**, with N98's remainder. A register of ten or more columns scrolls sideways inside its card; reading it a row at a time (a row's fields as a card, the id and figures first) waits on the owner's choice of form, and so does which columns of a wide table give way first. | | as built (F376 opens a register eight rows at a time; F394 holds its first column) | none recorded |
| OD-12 | **N129.** The default ceiling's headroom over the widest route (23.88) covers one worst-case guided retry (22.61), but D82's amendment allows three. Options: raise the default again, or accept that such a node may stop `BUDGET_CEILING_REACHED` (invariant 8). | | **raise to 165.00 (owner, D152 R6)** | done |
| OD-13 | **N130.** The proof checks a citation against every captured block, not the blocks the node was delivered. Bind it to the node's selection, or keep it. | | as built | none recorded |
| OD-14 | **N117.** Whether the model select offers models not qualified on the gateway: label each one's state, offer them to ADMIN only, or offer only qualified ones once one exists. | | as built (every approved model, D75) | none recorded |
| OD-15 | **N165, N166.** CP-0's page-coverage check refuses under-claims only, after the Blocked return (refusing over-claims too, or checking first, changes D106's order); and the same documents give the same layout but not the same bytes across runs (a content-derived `source_id`, or per-run ordinals in the evidence headers). | | as built | none recorded |
| OD-16 | **Copilot (N177, N183–N185).** Admit a bare `serverTools` provider tag per model family; keep or drop `copilot-cli:`; answer `BUDGET_CHARGE_OVER_RESERVATION` 409 rather than 500; whether an approved model the seat does not offer refuses the worker (F599) or parks its runs; the paid amount for the firm-seat proof (the plan proposed $5.00). | **(a)–(c) of 2026-10-06 (D77 addendum 2): the SDK transport only, `copilot-cli:` refused at readiness (D78); any answer carrying `serverTools` billed and refused; migration 0048, `BUDGET_CHARGE_OVER_RESERVATION` and the terminal park** | as built | measure on the firm's seat first (N177) |
| OD-17 | **Corpus (N126–N128, N147, N168, N191).** Confirm each CZR set's material key figures before a live run; supply the eligible-security universe; keep or drop the CP-4C `T4E.1` key; approve the downloads N147 names; author the portfolio sets' position and limits, or accept their restricted scope. | **D80 (the synthetic Test CLO I mandate, labelled SYNTHETIC) and D115 (three sec.gov files, which replaced it in three portfolio sets)** | record only | none recorded |
| OD-18 | **N125.** A Windows CI job for the analyst-PC worker (D79); `check_gate_config.py` pins every job to `ubuntu-latest`. | | none | none recorded |

## 1. Operating mode

You are operating autonomously. Nobody can answer, approve or unblock you. Never ask, never wait, and never end a turn with a plan, a question or a promise. End only when §9 holds, or when every remaining item is blocked on something only the owner or the workspace can supply.

- **Scope is the deliverable.** Do §3–§9 in order. Do not narrow, widen or swap the scope. A new feature or requirement goes in `docs/rebuild/next.md`; it is not built. An owner decision is never taken for the owner. A plan under `docs/superpowers/plans/` that BASE holds only in part (the Book/Model plans, D142) is not the sweep's to finish: verify what landed, and build nothing of the rest.
- **Evidence.** Audit every claim against a tool result from this session. A failing command is reported with its output. The final message copies command, exit code and summary from tool output produced in that same final turn.
- **Blockers.** A missing credential, host, permission or workspace goes in `docs/rebuild/blockers.md` with the exact command and error; then continue with everything else. A failing test, gate, parity check or review finding is never a blocker.
- **Hard limits.**
  - Never push, and never commit to or merge into `rebuild/databricks`: merges are the owner's. Never edit `vendor/deploy-v/`: every owner authorisation so far (D31, D34, D40, D47, D84's for the live-run fixes, D99, D111, D141) named its changes, and none names this sweep (OD-8). Never print, log or persist a key, token, minted credential or password-bearing URL.
  - Never add a dependency without a `Dn`. Never write a root `requirements.txt`. Never name OpenRouter outside `tests/`. Never lower a threshold or add a suppression (`tests/gate_baseline.json` counts may only fall).
  - Never regenerate a parity golden except by the procedure an owner decision names.
  - Never contact a real workspace, a Copilot seat or a paid API beyond OD-6.
  - A new migration takes the first number after the highest at BASE that no open branch holds: 0049 is the readiness-check branch's and 0050 and 0051 the Book/Model plans' (D142).
- **Branch and commits.** Work in a worktree of your own on a branch cut from BASE (`git worktree add -b sweep/<date> <path> BASE`); the owner ships it. Stage explicit paths, never `git add -A`. The tree may hold untracked owner files such as `.impeccable/`, and they are never committed. This overrides spec §1's `git add -A`. One concern per commit, each small enough to ship as one pull request of at most 800 counted lines (`scripts/check_pr_size.py`, CI's `size` job), so the branch ships as a stacked series. Commit when green. Run `git status --short` after every commit.
- **Foreign changes.** Before every commit, `git log -1` must be your own last commit or BASE, and no tracked file you did not touch may have changed. Otherwise another writer is active: stop and report BLOCKED with the paths.
- **Working style.** Targeted edits, no whole-file rewrites, `uv run` for every tool. Long output goes to `docs/rebuild/runs/final-sweep/logs/` (git-ignored); print tails and counts.

## 2. Authority and inputs

**Authority, in order:**
- `CLAUDE.md`: the eleven invariants, the conventions and the gate list.
- `docs/rebuild/2026-09-22-caos-databricks-spec.md`.
- `docs/rebuild/decisions.md`: later entries override earlier ones and override an uncorrected spec page.
- `CONTEXT.md` (the vocabulary gate enforces it), `icm/CONTEXT.md`, `DESIGN.md`, `docs/DEPLOYMENT.md`, `docs/COPILOT_WORKER.md` (the analyst-PC worker, D77–D79) and its plan `docs/superpowers/plans/2026-10-01-copilot-sdk-adapter.md` (the re-spec R1–R8), `docs/rebuild/ENTERPRISE_HANDOFF.md`, `docs/rebuild/next.md` and `docs/rebuild/blockers.md`.

**Ledgers to reconcile.** Each one uses its own ID families.

| Ledger | IDs |
|---|---|
| `findings.md` at the root (git-ignored, so on the owner's machine only; no tracked file holds the CF ledger, which survives in the repository only as citations; the 2026-09-25 run had no copy, B10, and N107 lists the 25 CF IDs no tracked document describes). The 16-goal campaign is at the top between the `audit-campaign-2026-09-23` markers; the older reviews are below it. | CF-001–CF-106; C1, C2, W1–W7 and the other reviews' IDs |
| `docs/rebuild/findings.md`: the R24 audit of 2026-09-24, with its status table (each ID's `Fn` or `Dn`); the reconciliation of the MAX list it replaced; the preserved FP review | R24-01–R24-18, R24-N01–R24-N03, R24-L01; MAX-01–MAX-22 and MAX-N01–MAX-N03 (their dispositions); FP-01–FP-41. AR-01–AR-25 were defined in an earlier version of this file and are only cited today (round 3, `decisions.md`): read them from its history |
| `docs/rebuild/findings-round2.md` | the deployment review's C1–C4, W1–W5, N1–N7; SA-C1–SA-C5; MX-1–MX-7; AS-1–AS-6, TM-1–TM-6, AI-1–AI-8, CR-1–CR-11, DL-1–DL-10, DP-1–DP-12, FE-1–FE-12, SI-1–SI-12; EI-W1–EI-W6, EI-N1–EI-N9 |
| `docs/rebuild/round3/findings-round3.md` and `round3/decisions-*.md` | R3-1–R3-5 (N30, the remainder, was reviewed in round 4: F113–F146) |
| `docs/rebuild/round4/findings-{store,edge,evidence,deliverable,deploy}.md` (60 findings; F113–F146 closed them but for what F146 lists) | ST-1–ST-15, ED-1–ED-9, EV-1–EV-8, DQ-1–DQ-15, DF-1–DF-13 |
| Reviews 1–5 of 2026-09-24, and the reviews of F310–F324 and of D60 and D61: no findings file; `decisions.md` and `next.md` cite each ID with its review, and the IDs repeat across reviews, so a register row writes `review 2: W5` | review 1 (F296–F304, F363, F364; N80), review 2 (F290–F294, F305–F309, F334, F341; N73), review 3 (F336–F346; N74), review 4 (D50, F353–F362; N81–N83), review 5 (W-A–W-C, N-1–N-3: F348–F352, F367; N74–N79); F325–F333 and F370–F375 by severity only |
| The final sweep of 2026-09-25 (BASE `2a4f983`): its register lived git-ignored in a cloud container and is gone; what it left is tracked | F416–F431; N107–N116 (its review's M1–M4 and L1–L4 are N108–N112); B10, B11 |
| The GitNexus review of 2026-09-27 (baseline `9393940`; the Codex snapshot is on the owner's machine, and `decisions.md` cites each ID) | R011, R014–R016, R031, R035, R040, R047, R050, R053, R059, V003 (F432–F443); AF-01–AF-06 (F452–F457) |
| The reviews since 2026-09-25, cited in `decisions.md` by their own labels, which repeat across reviews (a register row writes `Task 5b: V3`) | the live-run fixes' task reviews and audits (Tasks 1, 2, 4, 5, 5b V1–V14, 5c, 5d-3–5d-5, P; EX1, EX2, NB1, NB2, MK1, MK2; the reviews of D109, D110, D112, D113 (Q1, Q3), `34b6574` and `claude/d118`); the Copilot transport's audits of `45d755c`, `3b0da98` and `44ff021`, fix rounds 1–5, Tasks 3, 5 and 6 and the whole-branch review (MEDIUM-1, LOW-1–LOW-3, Info); the reviews of D74, D122 and the chart series (F616–F619) |
| Stage R (§2a), when it has run: `docs/rebuild/review-<date>/` | `<section>-NN` by verdict; `synthesis.md`'s root causes |
| `.impeccable/critique/2026-09-23T11-45-42Z__frontend-src.md` (untracked owner file; `decisions.md`'s "Design critique plan", F151–F158), and the later `/impeccable` critique of the Analysis section (F376–F388) | P0, P1 |
| `docs/rebuild/prompt-review-2026-09-23.md` | G1-1–G1-18, G2-1–G2-18, G3-1–G3-17 (every row FIXED, DECIDED or NOT-A-DEFECT; F426 corrected its status line) |
| `docs/rebuild/2026-09-25-design-brief.md` | section 5 (screen by screen), 6.1–6.13 and questions 1–6 (answered by D64–D69); tracked as N96–N106; 6.5's remainder is N98, and 6.13 and every phone item were withdrawn by D63 |
| `docs/rebuild/next.md` | N1–N197 (N66, N67, N84–N89 and N140 unused; N149, N173 and N175 never assigned; N121–N125, which the Copilot plan reserved and D77 and D79 cite, have no entry) |
| `docs/rebuild/blockers.md` | B1–B12 (B9 with four addenda; B10 and B11 from the 2026-09-25 run; B12 the gateway disabled), and the Live qualification entry of 2026-09-23 (the old key's account credit) |

The `Fn` entries in `decisions.md` (F1–F622; F162–F166, F483, F484, F490, F514–F519, F534, F537 and F554 unused; F467 is cited by D74 and has no entry) record what was fixed; D29–D142 (D51–D59, D108 and D114 unused) record the decisions since 23 September, the owner's among them as each entry says. Live-run evidence: `qualification/PROVIDER_RUNBOOK.md` (the 23 September sections; its status line was not updated for the October runs), `docs/rebuild/quality/2026-10-03-baseline.md` (the accepted artifacts of 2 and 3 October), and, git-ignored on the owner's machine, `docs/rebuild/runs/live-2026-09-23/`, `live-2026-10-02/`, `live-2026-10-03/` and `copilot-spike-2026-10-06/`.

**Evidence you may reuse.** The 2026-09-25 run rebuilt the scenario harness and the shipped-set probe from the suite's own harnesses (`tests/platform_journey.py`, `tests/shipped_boot.py`, F424); start from those. The audit's probes exist only on the owner's machine (B10), git-ignored under `docs/rebuild/runs/audit-2026-09-23/`:
- The goal texts: `QUALITY_GOAL_PROMPTS.md`.
- Per-goal evidence: `evidence/DB-NN/findings.json` (each finding's repro), `verify.json`, reproducers and `worktree-probes/`.
- The scenario harness: `evidence/DB-14/probe/{harness,flows}.py`. It boots the platform stand-in and drives cases, packs, gates, runs and filing over HTTP.
- The browser journeys: `evidence/DB-03/worktree-probes/frontend/audit-db03/*.mjs`.
- The shipped-set probe: `evidence/DB-13/probe_shipped_set.py`.

These are probes, not tests. Their paths and ports point at removed worktrees: adapt them under `docs/rebuild/runs/final-sweep/`, and copy them into `tests/` only as a regression test that fails before a fix.

## 2a. Stage R: the sectioned review, before the sweep

One fresh reviewer per section of the code, run before the sweep and not inside it, so that review cannot drift over the sweep's long session. Its findings land as tracked files the owner reads before filling §0 and launching; the sweep then treats them as a ledger (§2) and its review gap (§4) as covered. The method is the owner's global one (`~/.claude/refactoring-sweep.md`, "Stage R").

**Inputs**

| Layer | File | Section | Why |
|---|---|---|---|
| L0 | `CLAUDE.md` | invariants, conventions | what a finding is measured against |
| L3 | this contract | §0, §2, §4, §5 | owner decisions are not defects; the ledgers a finding may repeat; the invariant-moving changes; the group order |
| L3 | `docs/rebuild/decisions.md` | entries since `2a4f983` | what changed and why: deliberate, decided behaviour is not a defect |
| L3 | `docs/rebuild/next.md` | open N entries | what is already known or deferred: a finding that repeats one cites it |
| L4 | the GitNexus index at REVIEW_BASE | calls, processes, communities | each section's boundary |
| L4 | `docs/rebuild/runs/review-<date>/map-<n>.md` (git-ignored) | the whole map | the brief's section map, written by the lead |

**Process**

1. **Start.** The same in-flight condition as §11 step 1. Cut `review/<date>` from the tip of `rebuild/databricks` in a worktree of its own and record `REVIEW_BASE`. Re-index it: `gitnexus analyze --index-only <worktree path>`, then `gitnexus status` must show it current (the index read `064ef61` on 2026-10-11).
2. **Maps.** For each section below, the lead writes a map: its files and line counts, its entry points (routes, CLI mains, the worker), the calls into and out of it and the processes that cross it (GitNexus `context`, `impact`, `route_map`, and `cypher` over `CALLS` edges whose ends lie in different sections), and the communities it shares with another section, named as seams. GitNexus's own communities (638 at `064ef61`, the largest 361 symbols) are too fine to be sections; they show where the seams are. Sub-agents have no MCP tools: the map goes into the brief.
3. **Find.** One `mx-architect` (Fable 5.1 at high) per section, both lenses in one pass: correctness, and the adversarial review's three personas (saboteur, new hire, security auditor), stated in the brief because the agent cannot load skills. It reads its section in full and the far side of every boundary edge on its map. It runs probes only in the git-ignored `docs/rebuild/runs/review-<date>/probes/` or its scratchpad, on a database and ports of its own, and edits nothing tracked. Its final message returns each finding as: `<section>-NN` · CRITICAL, HIGH, MEDIUM or LOW · `file:line` · the invariant or behaviour · a concrete input and what goes wrong · a reproduction (command, probe or failing-test sketch) · confidence · the ledger IDs or N entries it repeats; then a `Not verified:` line.
4. **Across sections.** Three more `mx-architect` passes, each by invariant across the sections it names, each reading the §4 changes in its area:
   - money and exactly-once (invariants 6–8): sections 3, 5, 7 and 8 (D110, D118, D77 addendum 2);
   - evidence and citations (invariants 2 and 11): sections 4, 5, 9, 11 and 12 (D105–D107, D112);
   - identity, human gates and the pinned route (invariants 3, 5 and 10): sections 1, 3 and 9 (F468, D109, D124).
5. **Verify.** Every finding goes to `mx-adversary` (Opus 5.5 at xhigh), a different model from the finder's: it reproduces the finding on `REVIEW_BASE` by its reproduction or a probe of its own, and answers CONFIRMED, NOT-REPRODUCED, or NOT-A-DEFECT with the reason (a behaviour a `Dn` or §0 decided is NOT-A-DEFECT). An unverified finding stays unverified; it is never upgraded.
6. **Synthesis.** One `mx-architect` reads every verified finding, merges findings that share a root cause, ranks them by §5's group order and severity, and names the ledger IDs and N entries each repeats.
7. **Write and commit.** The lead writes the outputs below and commits them on `review/<date>` by explicit path: documents only, no code, no `Fn` (a finding is not a fix). Nothing is pushed; the owner merges the branch before the sweep starts.

If Fable is refused (a 403 on 2026-10-03 passed the same day), retry once, then the finder is `mx-adversary` and the verifier `mx-precise`, recorded in `synthesis.md` as one model family finding and checking. Run at most four reviewers at once: they share the Docker VM and its Postgres (§10). No paid or Copilot call, no vendor edit, no gate touched.

**Sections**

| # | Section | Scope | Lines at `78c4f17` |
|---|---|---|---|
| 1 | Edge, identity, commands | `caos/api`: `edge`, identity, `wire`, the governed-write commands | 11.1k with section 2 |
| 2 | Reads | `caos/api`: section reads, `stream`, `health`, `site` | (with section 1) |
| 3 | Store | `caos/store`, its migrations, `caos/blobs.py` | 7.6k |
| 4 | Evidence | `caos/evidence` | 6.2k |
| 5 | Execution | `caos/methodology`: the canonical executor, handoffs, citations, coverage | 10.6k with section 6 |
| 6 | Authority | `caos/methodology`: invocation, selection, the bundle and vendor loading; `caos/icm.py` | (with section 5) |
| 7 | Graph and model seam | `caos/graph`, `caos/models.py`, `caos/provider.py`, `caos/pricing.py` | 4.0k |
| 8 | Copilot | `caos/copilot.py` | 2.0k |
| 9 | Outputs | `caos/calculators`, `caos/deliverable`, `caos/qualification` | 7.6k |
| 10 | Deploy and gates | `scripts/`, `databricks.yml`, `app.yaml`, `tests/workspace_stub.py`, `tests/platform_app.py`, `tests/shipped_boot.py` | 8.1k and the bundle |
| 11 | Workspace chrome and sections | `frontend/src`: `app/`, `chrome/`, `sections/`, `controls/`, `states/` | 25.2k with section 12 |
| 12 | Evidence views and charts | `frontend/src`: `evidence/`, `ds/`, `charts/`, `components/`, `wire/` | (with section 11) |

The lead splits sections 1–2, 5–6 and 11–12 along their maps; a section over about 12k lines is split again.

**Outputs**

- `docs/rebuild/review-<date>/findings-<n>-<slug>.md`: one per section and per cross-section pass, every finding with its verifier's verdict.
- `docs/rebuild/review-<date>/synthesis.md`: the root causes, ranked, each with its finding IDs, the ledger IDs and N entries it repeats, and the models that found and verified it.
- Git-ignored, under `docs/rebuild/runs/review-<date>/`: the maps, probes and logs.

**Done** when every section and pass has its findings file, every finding a verdict, the synthesis is written, all of it is committed on `review/<date>`, and `git status --short` shows only the untracked paths recorded at the start.

**Launch.** A fresh session on Opus 5.5 at high, in the review worktree: `Run Stage R of docs/rebuild/final-sweep/CONTRACT.md (section 2a), and nothing else.` Its fifteen finders, a verifier per finding and the synthesis exceed the ten-agent guideline for a workflow, so a workflow runs only when the owner asks for one.

## 3. Phase 0: freeze and baseline

1. Check the start state:
   - `rebuild/databricks` has nothing in flight that §11 asks to land first, and your worktree's branch starts at its tip (§1).
   - `git diff --quiet && git diff --cached --quiet` passes.
   - Record every untracked path; leave them alone.
   - `docs/rebuild/final-sweep/` is tracked (since `0fa3c41`). If the owner's §0 choices left it with uncommitted edits, commit them first, by explicit path, as the sweep's own first commit.
   - Record `BASE=$(git rev-parse HEAD)` in `docs/rebuild/runs/final-sweep/progress.md`.
2. Set up the environment: `uv sync --locked --all-groups`, `docker compose up -d --wait` (first §10's check on the shared dev store), then `npm --prefix frontend ci --ignore-scripts && npm --prefix frontend run build`. Record `uv run python -V`, `node -v`, the Databricks CLI version, and which `CAOS_*`, `DATABRICKS_*` and `OPENROUTER_API_KEY` variables are set (names only).
3. Run every gate in `CLAUDE.md` exactly as written; together they are acceptance rows A1–A37 (spec §11 as F423 corrected it, A34–A37 from D28 and F73), with the shipped-set boot (`tests/shipped_boot.py`, F424), `scripts/document_register.py` and `vendor/deploy-v/verify_package.py`, which CLAUDE.md has listed since the 2026-09-25 run. The stand-in rows A34–A37 now run for all four targets, `dev` and `prod` on a Lakebase Autoscaling project and `dev-provisioned` and `prod-provisioned` on an instance (R24-14, D49), each deploy followed by its `--shipped` check (DF-4); `check_gate_config.py --against <an earlier commit>` runs as CLAUDE.md writes it, both trees under the current patterns and under that commit's own checker (F357, W5). Record each exit code and summary line in `progress.md`.
4. Record the baseline metrics:
   - passed test count and coverage;
   - each suppression count, as measured by `scripts/check_gate_config.py`;
   - `complexity_baselined` (15 at `78c4f17`, after F422, F497 and F504; 21 at `9393940`; 25 at `e4e4e01`; 26 at `c37733e`) and the list of baselined functions (`tests/gate_baseline.json` keys each one, `complexity:<path>::<name>`);
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

The 2026-09-25 run's register is gone (B10), so rebuild it from the tracked ledgers. At `9393940` a `decisions.md` entry named 77 of CF-001–CF-106 (§5 lists its seeds' entries per group), most from the backlog pass (D38–D48, F159–F249) and most as fixed; D39 keeps CF-034 as it is (N25). That run classed CF-001 FIXED (F424, F429) and CF-010 and CF-033 PLATFORM-ONLY, and left 25 CF IDs that no tracked document describes (N107): check each again, and class one that only the owner's `findings.md` describes DEFERRED to N107. Neither an entry naming a row nor a past run's class is evidence, so check each one.

Each change since `2a4f983` had its own task review, audit or adversarial pass (`decisions.md` names each), but nothing has reviewed them together, and some had none. Stage R (§2a) is that review: when it ran on BASE, or on a commit BASE contains with no change under `caos/`, `scripts/` or `frontend/src` since, its CONFIRMED findings enter the register as OPEN rows, each reproduced again at BASE, and its NOT-REPRODUCED and NOT-A-DEFECT ones are classed with their reasons. Otherwise, review in a worktree at BASE with `mx-adversary`, and `mx-architect` reads the second list's findings together (§10's agents):
- what records no review: F498–F500, F503, F507, F541–F543 and F581, and the Book/Model inputs (#153–#155: `caos/methodology/model_inputs.py`, `caos/calculators/credit_model/frame.py`), which landed with no `decisions.md` entry;
- the changes that move what an invariant means in practice, read together: citations as 8-word excerpts, kept unverified and cited by markers in the body (D105–D107; invariants 2 and 11); the run's pinned model and command (F468, D109; invariant 10); the drop re-attempts (D110, D118; invariant 6); the Copilot transport's bill, settlement and park (D77 addendum 2, F556–F612; invariants 7 and 8); and the typed registers, which call the bundle's private functions (D124; invariant 4).

Its confirmed findings enter the register.

**Exit:** every ID in every ledger is on a row, with counts per class and severity, and the OPEN rows are ranked by §5's order.

## 5. Phase 2: repair confirmed defects, grouped by root cause

Work through the groups in this order. Within a group, higher severity goes first. The CF numbers are seeds; every ledger ID on the same row goes with them. A seed followed by entries in brackets is one those `decisions.md` entries name, most as fixed (D29 and D83 derive the ceiling around CF-008 rather than changing it): reproduce the original at BASE and class it FIXED-AT-BASE only if it no longer reproduces. A bare seed is named by no entry.

| Group | Scope | Seed rows |
|---|---|---|
| A | Deploy and first-run blockers: anything that stops `scripts/enterprise_deploy.sh` E1–E10 (either Lakebase kind, D49), the handoff's "Afterwards 1", or the analyst-PC worker's start (`docs/COPILOT_WORKER.md` §2–§7) | the deployed file set (CF-001 (F424, F429), R3-3); the ordered migrations through 0048 under the documented grant (CF-010; F302, F364, F468, F528, F559, F584) and a rollback across `RECORD_CODEC_VERSION` 3 (F523); the store session's `SET idle_session_timeout = 0` on session-mode connections (D120, N176); E5 and the preview flag (CF-033); model or volume reachability through the app (CF-054 (F246, F354: row E10), F470, D117); the worker's readiness and its pinned runtime (F591, F595–F599); the byte-verified trees on a Windows checkout (D79, F607) |
| B | Evidence integrity and citations (invariants 2, 11) | CF-002 (F128), CF-012, CF-013 (F204), CF-014 (F125), CF-015 (F128), CF-016 (F235), CF-017 (F234), CF-021, CF-072 (F203), CF-073 (F203, F234), CF-074 (F202); the rule as D105–D107 left it: excerpts, unverified citations kept and labelled, markers in the body, calculation inputs still anchored (F501, F502, F504, F506); re-anchoring (D94); CP-0 page coverage (D112); the PDF reader's form text (F434, F435, F453–F455, F462); N130 (OD-13), N134, N138, N139, N141, N142 |
| C | Text and secret leakage | CF-022 (F183), CF-023 (F120), CF-024 (F120), CF-077 (F214), CF-078 (F178); hidden text in run commands and subjects (F524, F525); refusal lines that name and never quote (F499, F513); the Copilot child's environment allow-list and staged runtime (F583, F591, F594, F596, F597) |
| D | Authority, human gates, filing and qualification (invariants 3, 5, 10) | CF-018, CF-019, CF-026 (F222), CF-027 (F194), CF-028 (F131), CF-029 (F130), CF-030, CF-031 (F131), CF-081 (F199), CF-082 (F120), CF-083 (F133), CF-084 (F232); filing's re-proof (FP-04 (F427)); the run's pinned model and command (F468, D109, F523, F526); qualification retry and badge expiry (F440, F441); answer-key alternatives (D101) |
| E | Durability and exactly-once (invariant 6) | CF-005, CF-006, CF-007 (F117), CF-037 (F182), CF-038 (F115), CF-039 (F180), CF-040 (F116), CF-041 (F181), CF-042 (F114), CF-043, CF-044 (F186, F311); declared drops and cuts re-attempted once (D110, D118; F530, F553, F566); the over-reservation park and its replay (F585, F589, F610); an unsettled run behind the queue (F421, N116); the lease and the deadline (D117, F549, F550) |
| F | Money and budgets (invariants 7, 8) | CF-008 (D29, D83), CF-046 (F117), CF-048 (F179), CF-089 (F212), CF-090 (F117), CF-091 (F185, F220); the default ceiling 165.00 (D83, raised by D152 R6; OD-12); the Copilot bill in AI units at a run-pinned credit price (F558, F560, F564, F567–F579, F584, F592, F601, F604); context bounds per model (D116, D119, F609); the price pin for long-context calls (N152) |
| G | Availability and resource bounds | CF-003, CF-004, CF-049 (F129), CF-050, CF-051 (F192), CF-052 (F119), CF-053, CF-075 (F193, F342); pattern costs over model text (F418, F420, F428); a FULL CP-0 request at 95.4% of `MAX_REQUEST_BYTES` (F543, D116); leaked test databases (F521, F588); the tests still timed (N197) |
| H | The primary journey | OD-4 is implemented and the workspace redesigned since (D32–D37, D60–D74, D122–D140; F151–F161, F310–F333, F370–F415, F458–F464, F613–F619): verify the critique's P0 and WCAG repairs and the axe matrix at BASE rather than redo them, then Start and Retry usable (CF-011; F261 and F314 changed both), the model select (D75 addendum 2), refusal text that is true (CF-056 (F189), and the operator hints G2-17 (F200)), the unverified and blocked citation views (F504, F506), CF-057, CF-058 (F160), CF-059 (F161), CF-097, CF-098, and the 2026-09-25 review's frontend LOWs (N113); within `DESIGN.md` as D122 left it, desktop only (D63) |
| I | Gate and test credibility | CF-061, CF-062 (F242), CF-063 (F170), CF-064 (F172), CF-065, CF-066 (F140), CF-067 (F140), CF-068 (F134), CF-069 (F134), CF-070 (F198), CF-071 (F177, F240), CF-079 (F173), CF-092 (F184), CF-103, CF-104, CF-105 (F174), CF-106 (F184); the 2026-09-25 review's M1–M4 (N108–N111), N114 and N115; tests that count work instead of time (F444, F620, F621) and those still timed (N197); the uncommitted-tree secret scan (F465, F466) |
| J | The prompt review and prompt parity | Every row of `docs/rebuild/prompt-review-2026-09-23.md` reads FIXED (G2-12 DECIDED, G3-15 NOT-A-DEFECT for the host), the four host rows this group seeded at `e4e4e01` among them: G1-12 (D38), G1-16 (the D30 fifth addendum, F210, D41), G2-17 (F200), G3-9 (F211). Verify each at BASE; no vendor row waits on OD-8. Then verify that every golden moved since `2a4f983` moved under a decision OD-7 or OD-8 names, by D34's procedure: `prompt` (F477, F481, D102, F500, F503, F505, D113, and forks r5–r14: D84–D103, D111, D141), `forecast` (D95, F505), `render` (F504, F506, each with `RENDERER_SHA256`) |
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
| R2 | One source for each duplicated fact | Done before BASE; verify each. The deploy defaults live in `databricks.yml`, and `scripts/bundle_defaults.py` serves them to `enterprise_deploy.sh`, `enterprise_deploy.py` and the stub (N23, F245, F362); `PG_PORT` and `PG_SSLMODE` stay shell defaults, not bundle variables, and `enterprise_deploy.sh`'s header and `docs/DEPLOYMENT.md` §1 restate the defaults in prose. The status tables (N29, F251): `app.TRANSIENT` is derived from `_STATUS`, and `edge.EDGE_STATUS` stays because the edge cannot import the app, held to `_STATUS` by a test. "Store both bodies, or fail with `STORE_UNAVAILABLE`" is one helper, `BlobStore.put_both` (F253), called from `runtime._settle` and `ModuleProvider.execute` (the read path behind CF-006 was fixed by F91 and is not part of this). Since the last run, verify too: the default ceiling has one source for the stand-in (`tests/platform_app.py` reads `RUN_CEILING` from `tests/workspace_stub.py`, F487); the deadline constants D117 moved in `caos/provider.py`, `caos/store/work.py` and `scripts/enterprise_deploy.py` are held to each other by tests (F485, F549); the context bounds live once in `caos.provider` (`CONTEXT_TOKENS`, `COPILOT_CONTEXT_TOKENS`; D116, D119, F609) |
| R3 | Complexity | Bring baselined functions to 15 or below and remove them from `complexipy-snapshot.json`, and their `complexity:` keys from `tests/gate_baseline.json`, so the count falls. The 2026-09-25 run took the four it required (F422: `render._list`, `handoff.stored_lineage`, `pdf.walk_pages`, `stream.case_tail`), and F497 and F504 took `selection.select_sources` and `revisions._span` since. **Required** now, the two left on product paths: `store/run_inputs.py::_research` (20 in the snapshot) and `api/reads/run.py::node_readiness` (17). **Then, as budget allows:** the qualification matrix, harness, on-disk and proof functions (`matrix.py::_registers_met` and `_digested` 20, `_witnesses_contradict` 18, `_projections_met` and `_forecast_met` 16; `on_disk.py::_registers` 18; `harness.py::_consumers` 18; `proof.py::assert_orchestration_proof` 16), `methodology/vendor.py::_Loader::_import` (16), and last `methodology/invocation.py`'s four (`allowed_uses` 19, `_yaml` 17, `named_objects` and `lite_object_requirement` 16), whose prompt bytes the prompt goldens pin. The snapshot's figures are as it was last written: measure each function fresh before and after. If a change touches `render.py`, `verify_package.RENDERER_SHA256` moves with its bytes in the same commit (F255, F422) and the `render` goldens stay byte-identical. |
| R4 | Stage contracts | Done before BASE (F254, SI-12): Process and Outputs are stated once in `icm/CONTEXT.md`, and each of the 27 stage contracts points at them through `scripts/icm_stages.py`. Verify `check_icm` and `icm_stages.py --check` green and prompt parity unchanged. D104 added `validator_repair.md` to every contract the same way (`icm_stages.py --write`). |
| R5 | Frontend (not design) | Done before BASE, differently: the modal hook is deleted and the evidence drawer, source drawer and metric passport are one `evidence/Overlay.tsx` on Base UI's Dialog (F318, N64), not a native `<dialog>`. Verify the a11y matrix, the workbench and the opener focus return (F622). |
| R6 | Documents that match the code | See below |

**R1 in detail**, each done before BASE; verify it:
- The HMAC edge-assertion mode is deleted (F188; D10, N12, CF-080), its tests removed by name in F188; boot refuses a leftover `CAOS_EDGE_TOKEN` (`edge.RETIRED_ENV`, F340).
- `scripts/check_postgres.py` and `scan_floors --trivy`/`--min-files` are deleted (F175).
- `case_tail`'s dead overloads and `_status_refusal`'s dead branch are gone, and `runs.fail_run`, which only tests called, lives in `tests/run_terminals.py` (F251). Look for any other production definition only tests call (N29).
- Seven refusal codes no condition raised are retired (D43, CF-099). Look for any other.
- `FORECAST_CHAIN_BROKEN` is retired with `cash_flow._check_chain` (D43, N6), and the wire schema and `documents.ts` followed (F217). If a sweep change drops another wire code, regenerate `frontend/src/wire/v1/schema.json` from `python -m caos.api.wire`, which prints the schema to stdout.
- The stale journey configuration is retired (F239, CF-102): `playwright.journey.config.ts`, `journey.spec.ts` and `test:journey` are gone; `tests/journey/pack.py` stays for the admission tests.
- Since the last run: `CONTEXT_LISTED` and `declare_listed` are removed (F609), and F580 superseded F576. Look for anything else the Copilot transport's revisions left behind. `copilot-cli:` parses only to be refused at readiness (D78) and stays.

**R6 in detail:**
- `CLAUDE.md` says `complexipy-snapshot.json` baselines 17 functions; `tests/gate_baseline.json` holds 15 since F497 and F504. Correct it, and again after R3. It stays under 120 lines (41 at `78c4f17`) and matches the gates.
- `qualification/PROVIDER_RUNBOOK.md`'s status line still says no spend and live runs blocked, as of 23 September, though the CZR live loop ran from 2 October (the "Live-run fixes" entries, `docs/rebuild/quality/2026-10-03-baseline.md`).
- `blockers.md`: B12 says "Resolution in progress: D77", though the SDK transport is built and only the firm-seat proof is left (D77 addendum 3; N177, N185–N187). The "Live qualification, 2026-09-23" entry describes the old key's exhausted account, which the 2 October key replaced.
- `next.md` lines that lag: N135 waits for "the Copilot adapter", which landed; N145 says "the owner merges" F511 and F512, which are on the base; N183 asks readiness to call `declare_listed`, which F609 removed; N121–N125, which D77 and D79 cite, have no entry; N107's 25 IDs as the register now finds them.
- `decisions.md`: F467, which D74 cites, has no entry; the Book/Model inputs (#153–#155) landed with none: check whether their plan records them later, and record what is missing.
- Spec §2 and §3.3 as D77 amended them, and §11's A-rows as F423 corrected them: verify each against the tree.
- `docs/DEPLOYMENT.md` has a rollback path (§6: `scripts/rollback_check.py`, F241, F353) and a health smoke that sends the bearer (§5, F241, CF-096): verify both work as written, the rollback check's refusal across `RECORD_CODEC_VERSION` included (F523).

**Architecture.** Beyond R1–R6, a structural change is allowed only where two or more confirmed register rows share one seam, and the commit names the rows it retires. No speculative redesign. No N1 parallelism (runs stay sequential, D42). Nothing of OD-3, OD-7 or OD-10 to OD-18 beyond what its Choice says.

**Stop rule, per item.** Allow at most two attempts, the second one rung up the owner's ladder (§10's agents). Revert the item by explicit path and record it in `next.md` with the reason if either of these happens:
- it would need a golden, vendor byte, dependency or behaviour change;
- the same gate fails twice.

**Exit:**
- The two required R3 functions are out of the baseline, so the count is 13 or lower (15 at `78c4f17`). The only exception is a required function whose two attempts the stop rule ended: its `next.md` entry names the golden, gate or behaviour that refused it, and the count is reported with that exception.
- R1, R2, R4 and R5 are verified at BASE (or what a fresh search found is done or recorded), and R6 is done or recorded.
- No suppression count is above BASE.
- The net line count is reported.

## 7. Phase 4: enterprise readiness

Two topologies ship from one tree. The App on the workspace (FastAPI, the worker, `ChatDatabricks`) is the spec's, and B12 stops its model calls while AI Gateway is disabled. The worker on the analyst's PC (`python -m caos.graph.worker` against Lakebase and the volume, answered by GitHub Copilot through the SDK) is D77–D79's; whether Databricks Apps may host the API and UI there is still unknown (N124).

1. **The shipped set boots.**
   - `tests/shipped_boot.py` (F424, F429, F430) deploys the `dev` target through the stub, boots `python -m caos.serve` from the synced files, waits for every health code to read OK and completes one governed LITE run through `ChatDatabricks`; CLAUDE.md lists it and CI's `bundle` job runs it. Run it, and run `tests/test_enterprise_deploy.py` green.
   - The analyst-PC worker refuses to start without a ready seat: with a `copilot:` model approved and no runtime, it exits 2 `PROVIDER_NOT_CONFIGURED` before it reads the store (F599; `tests/test_copilot.py::test_the_worker_checks_readiness_on_every_approved_model_before_the_store`, `tests/test_pc_worker.py`). Confirm both run in the suite. Nothing here starts a Copilot runtime or calls a seat (OD-6, OD-16).
2. **Stand-in fidelity.** `docs/DEPLOYMENT.md` §8 lists each known gap between the stub and the platform with the row that reveals it (F425). Verify each row against the tree, and add what the October work opened:
   - the store session's `SET idle_session_timeout = 0` and session-mode connections on Lakebase (D120, N176; E6 `store`);
   - the 720-second deadline, measured only through the streaming test adapter (D117, N172);
   - whether production calls' drops are declared (N161, N174);
   - the declared 1,000,000-token contexts (D119, F609; N170's numeric-table floor).
   `docs/COPILOT_WORKER.md` says what the worker does not do (§8) and what to measure on the firm's seat (§9), with no row per gap: add one for each gap between the SDK fakes and a real seat, or between this checkout and the analyst's PC, with the check that reveals it: the events and fields the firm-seat spike must record (N177, N178, N180–N184; its §9); the AI-unit ratio (10**9, N177); prompt caching (N153); a Windows host (N125, N189).
3. **`docs/rebuild/ENTERPRISE_HANDOFF.md`.** It carries a status note of 2026-10-07 (Copilot, B12), a Do-not list (F472), and lists OD-5, OD-6, OD-10 and OD-11 as open. Bring it up to date:
   - what is proven locally (the shipped boot, the stand-in deploys, the Copilot transport against fakes the SDK's own types accept) and what only the workspace or the firm's seat can prove;
   - the state after D74–D142, and therefore what "Afterwards 1" will show: OD-1 as D82, D104 and D106 left it, the bundle at fork r14 (D141), citations as excerpts and markers (D105–D107), and the live record (one set end to end on 23 September; the CZR loop of 2–7 October and the quality record of 3 October), naming the modules no real model has yet reached;
   - the owner decisions still open, from §0 (OD-5's remainder, OD-10 to OD-15, OD-16 and OD-17's remainders, OD-18);
   - the rollback path (`scripts/rollback_check.py` first, F353, refusing across `RECORD_CODEC_VERSION`, F523).
4. **CI.** `.github/workflows/ci.yml` runs the same gates as `CLAUDE.md` (jobs `lint`, `types`, `test`, `security`, `bundle`, `size`, `frontend`), with no local-only or CI-only drift (CF-066, CF-067); `check_gate_config.py` refuses a `CLAUDE.md` gate missing from CI, reading `ci.yml` as YAML (F140, F355). CI runs three checks `CLAUDE.md` does not list: `scripts/check_pr_size.py` (the `size` job), and the pinned gitleaks workflows (`gitleaks.yml` on every branch, tag and pull request, `secrets-weekly.yml`'s weekly full-history scan; `4807cb0`). List each in `CLAUDE.md`, or record in `next.md` why it stays CI-only.

## 8. The loop for every step

A step is one register row or one refactor item.

1. **Re-read** the row's sources. Reproduce it at HEAD, or record the before-metric. If it no longer reproduces, reclassify it and move on.
2. **Test first.** For a repair, write the failing test. For a refactor, name the tests and goldens that pin the behaviour; add a characterization test only where nothing pins it.
3. **Make the smallest change**, through the implementer §10's table names for the work; the lead session writes no code.
4. **Run the targeted checks:** `uv run pytest --no-cov -n 4 <files>`, `tests/parity` when a parity-bound path is touched, and ruff, mypy and every gate the change could move. A change on a money, ordering or security path also runs `mutmut` (D142) over what it changed, and its `Fn` entry names each surviving mutant killed or justified.
5. **Live-test, according to what changed:**
   - Store, graph, worker, model seam or API: `tests/test_platform_boot.py` plus one scenario over HTTP through the scenario harness (`tests/platform_journey.py`, extended under `docs/rebuild/runs/final-sweep/`).
   - The Copilot transport or the PC worker: `tests/test_copilot.py` and `tests/test_pc_worker.py`; never a seat.
   - Frontend: `npm --prefix frontend run test && npm --prefix frontend run build`, the adapted DB-03 journey against the real app, and `build:demo` then `test:workbench` for chrome or section changes.
   - Deployment: A34–A37, `tests/shipped_boot.py` and `tests/test_enterprise_deploy.py`.
6. **Review**, once per level (the owner's global rules):
   - `mx-precise` reviews the step's diff against its brief, the spec verdict and the quality verdict apart; a small fix's re-review may go to `mx-feature`;
   - `mx-adversary` also reviews it when it touches money, ordering or concurrency, or security (groups C to F, the Copilot transport);
   - `confidence-review` and `rewrite-tournament` run once, on the branch diff, at §9's whole-branch review, not per step.

   Fix what they confirm. A skill or agent that is not available is recorded as unavailable, never as run.
7. **Commit** on the sweep branch. Stage explicit paths. The message names the register row and its ledger IDs, and the `Fn` entry goes in `docs/rebuild/decisions.md` in the same commit. Number each `Fn` and `N` from the first unused on `rebuild/databricks` at that moment, since other sessions' pull requests may have landed ids meanwhile. Then check `git status --short`.
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
   - `complexity_baselined` ≤ 13, with the removed functions listed, or §6's recorded exception;
   - jscpd ≤ 3%.
5. The shipped-set boot and the governed run (§7.1).
6. Ten consecutive, distinct, realistic scenarios pass on the final commit, through the scenario harness: LITE and FULL, gates, cancel, a restart mid-run, filing through three actors, and a run whose pinned model the deployment stops approving (F468). Set the ceiling as OD-2, D83 and CF-008 leave it (165.00). An actor holds at most four queued or running runs (D46, `QUEUED_RUNS_LIMIT_REACHED`), so end or cancel each scenario's run before the next.
7. Run the whole-branch review of `git diff BASE..HEAD`: `mx-architect` (if Fable is refused, record the error and use `mx-adversary`), then `confidence-review` and `rewrite-tournament` on the same diff. Every CRITICAL or HIGH they raise is fixed and re-reviewed; every MEDIUM is fixed or put in `next.md`.
8. The register has zero OPEN rows at CRITICAL or HIGH. Every other OPEN row is fixed or has an N entry. Every DEFERRED, DECISION or PLATFORM-ONLY row names its entry.
9. `git status --short` shows only the untracked paths recorded at BASE, nothing has been pushed, and no branch but the sweep's has moved.

**The report**, which must stand alone:
- the EVIDENCE table;
- the register's counts, and every row that is not closed;
- `git log --oneline BASE..HEAD`, grouped as the stacked pull requests the owner will ship, each with its counted lines (`scripts/check_pr_size.py`);
- metrics before and after;
- the owner decisions still open;
- `docs/rebuild/blockers.md` verbatim.

## 10. Environment and parallel work

These are lessons from the runs of 23 September to 11 October.

- **Postgres.** The suite uses the compose `test-postgres` on 55437, which runs on tmpfs. The Docker VM has about 4 GB of RAM and 2 CPUs; a tmpfs server under a bulk load took the audit's database down. Run scale or load probes against a separate disposable disk-backed container, and stop it afterwards. The persistent dev store on 55436 holds the live runs' databases: never point a test at it, and never run `docker compose up` from a new worktree while a live run uses it (a compose project from a new path re-created it on 2026-10-05). `tests/pg_reaper.py` drops only timestamped test databases over two hours old, and only on 55437 (F588).
- **complexipy** rewrites `complexipy-snapshot.json` on every run (F25). Commit that file only when the baseline legitimately shrinks.
- **Port 4173.** `npm run test:workbench` and `npm run a11y` hard-code it (`--strictPort`), so only one of them runs at a time. `test:workbench` serves the prebuilt `dist-demo`: run `build:demo` first, or it tests stale code. A container may lack Playwright's browsers for the pinned version (B11); CI installs them.
- **Agents.** See the table after this list.
- **Usage limits.** Commit every green step and update `progress.md` after every step. A resumed session starts from `progress.md`, `register.md` and `git log BASE..HEAD`. A resumed workflow replays its cache only if the script is unchanged, because the cache is an order prefix.
- **/goal.** The evaluator reads only the transcript, and background subagents defer evaluation. Run the final acceptance commands in the main session, in the final turn.
- **Live provider.** Use it only under OD-6, only through the test adapter, never as gateway or Copilot evidence, and never print the key. Read the key's usage (`GET https://openrouter.ai/api/v1/key`) before every run, and measure a run's spend from `GET /api/v1/generation`, because the usage figure lags. An exhausted account answers `PROVIDER_CALL_INVALID` with nothing billed. The live loop's model since 3 October is `openai/gpt-6-luna` at high effort on the `openai` tier (F479); its price pin must cover the highest input rate a prompt reaches, long-context cache writes included (N152). A run's ceiling holds about six times its actual spend, because every billed attempt keeps its reservation (CF-008), and a FULL node may now take four attempts (D82).
- **Integrity regeneration.** `verify_package.py --refresh` and `scripts/host_manifest.py` rewrite pins; the permission classifier refuses them without the owner's authorisation in the session, and this sweep has none (OD-8). `.gitattributes` keeps the byte-verified trees `-text` (D79, F607): a checkout that converts line endings breaks every pin. `caos/deliverable/verify_package.py::RENDERER_SHA256` is not one of these: it moves with `render.py`'s bytes (R3, F255).
- **Gates only the full matrix sees.** A comment-only edit to `render.py` moved `RENDERER_SHA256`, which only the suite catches (e66f2da); two names bandit's B105 reads as passwords failed the bandit floor on the merged tip (F369); an import the TypeScript vocabulary gate reads as a synonym left the base's `frontend` job red for several commits (F389). A wall-clock bound passed locally and failed on CI's runners until F620 and F621 made those tests count work; N197 lists the ones still timed. Run the full matrix on the merged result, not only on the branch.
- **Prompt goldens.** `tests/parity/goldens.py` refuses any golden not written by the legacy package. A host prompt-text change re-baselines by mirroring the host's texts into a scratch copy of the legacy snapshot (D34), verified first to reproduce the committed goldens byte for byte; forks r3–r14 and the departures OD-7 lists re-baselined the same way. Only an owner decision permits it.
- **Other writers.** Other sessions work in worktrees of their own and open pull requests against `rebuild/databricks`, which the owner merges; while documents-touching pull requests merge, `decisions.md` and `next.md` conflict on every base move. Before every commit check `git log -1`, `git status --short` and the worktree's `MERGE_HEAD`.
- **`rtk` wrapper.** Some commands are rewritten by the `rtk` hook (`grep -h`, `find -exec`, counts through pipes); prefer Python or plain invocations when an output looks wrong. `uv run pytest`'s output can come back as "No tests collected" through its filter: run the gate as written with its output redirected to a log under `docs/rebuild/runs/final-sweep/logs/`, and read the tail.

**Agents.** Every sub-agent is dispatched by its `mx-*` name (`~/.claude/agents/`, `~/.claude/model-matrix.md`), each of which pins its model and effort; never by a model alias or with the model left to inherit. `opus55-reviewer` inherits the session's effort, so the sweep does not use it.

| Sweep work | Agent |
|---|---|
| The lead session: register, ledgers, `progress.md`, commits, the final turn | the session itself, Opus 5.5 at high effort (§11) |
| Phase 1's classification, reproduction and ledger digests (read-only) | `mx-feature` |
| Stage R (§2a): finders, cross-section passes, synthesis; verification | `mx-architect`; `mx-adversary` |
| §4's review, when Stage R has not covered BASE | `mx-adversary`; then `mx-architect` reads the invariant-moving set together |
| Groups C, D, E and F (security, authority, durability, money; the Copilot transport's bill and park) | `mx-invariants`, reviewed by `mx-precise` and `mx-adversary`, with `mutmut` (§8 step 4) |
| Groups A, B, G, I, J and K | `mx-precise`; a multi-file change `mx-autonomous` |
| Group H, the frontend | `mx-feature`, reviewed by `mx-precise` |
| R1, R2 and R3 (behaviour-preserving; the parity goldens byte-identical) | `mx-precise` |
| R6 and the ledgers' text | `mx-scaffold` |
| Task review; a small fix's re-review | `mx-precise`; `mx-feature` |
| §9's whole-branch review | `mx-architect`; if refused, `mx-adversary` |

- A second attempt starts one rung up: `mx-scaffold` → `mx-feature` → `mx-precise` → `mx-invariants` (sensitive code) or `mx-autonomous` (multi-file). `mx-adversary` and `mx-architect` review; they never implement. A refused `mx-adversary` audit goes to `mx-architect`, not a retry.
- Fable 5.1 (`mx-architect`) refused once with a 403 `oauth_org_not_allowed` (2026-10-03) and answered later the same day: retry once, then use `mx-adversary` and record the refusal in `progress.md`.
- Parallel sub-agents only for read-only work: classification, reproduction and review. One writer at a time: one implementer in the sweep's worktree. Only the lead session commits.
- Create each helper's worktree yourself: `git worktree add --detach <path> <sha>`. The harness's own worktree isolation cannot run git under the `rtk` command hook. Give each helper its own ports and databases.
- Never SendMessage a running workflow agent: it starts a second copy in the same worktree.
- Sub-agents cannot write report files: `mx-adversary`'s definition asks for a report at a path, which this harness refuses. Every brief asks for the report in the final message, and the lead session writes it.
- Every brief and reviewer prompt states: no stub or fake value standing in for real behaviour; no catch-all that hides a failure unless the fail-open is documented and logged; a report ends with a `Not verified:` line naming what no gate or test exercised. `mx-*` implementers have no MCP tools: the lead session puts any library documentation a brief needs into it.

## 11. Launch

1. Wait until what is in flight against `rebuild/databricks` has merged or been parked: the Book/Model plans (`docs/superpowers/plans/2026-10-10-*`, migrations 0050 and 0051), the readiness-check branch (migration 0049) and the readiness default-run fix stacked on both. Make sure no other session is writing this repository. BASE is the tip after that.
2. Run Stage R (§2a) on that tip, and merge its findings.
3. Fill in §0, with Stage R's synthesis in hand.
4. Start the session on Opus 5.5 at high effort, chosen before launch (a session cannot raise its own effort): long-horizon coordination is the matrix's Opus row, and Fable is kept for §9's whole-branch review.
5. In a Claude Code session in the repository, version 2.1.259 or later (the desktop app qualifies; the `claude` on `PATH` read 2.1.246 at B3 and 2.1.296 on 2026-10-11), from your worktree (§1), run:
   ```text
   /goal <the contents of docs/rebuild/final-sweep/goal.txt>
   ```
6. **Headless:**
   ```bash
   claude -p "/goal $(cat docs/rebuild/final-sweep/goal.txt)" --model claude-opus-5-5 --effort high --permission-mode auto --permission-prompts none --output-format stream-json --verbose
   ```
   Do not use `--bare`: `/goal` runs on hooks. To resume:
   ```bash
   claude -p "Resume the active goal from where you stopped." --continue --model claude-opus-5-5 --effort high --permission-mode auto --permission-prompts none
   ```

# GPT workflow and Book/Model completion plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Configure this project's GPT subagent workflow, avoid overlapping active chats, and finish the remaining Book/Model proof against integrated fixes.

**Architecture:** Project AGENTS.md and `.codex` settings define explicit GPT roles while retaining the existing development gates. The Book/Model chat owns these settings and the live proof; other active chats own the PR stack, CP-4 repair and calculator follow-up. Work stays in the existing isolated worktrees.

**Tech stack:** Codex 0.162.0-alpha.17.2, project Markdown instructions and TOML custom agents; existing Python 3.13/FastAPI/Postgres and React/TypeScript application.

## Global constraints

- The current human request to use GPT models supersedes the historical Sonnet-only preference for Codex development. Claude's global files and production model transports remain outside this settings task.
- The controller plans and coordinates; a fresh GPT implementer owns each task and never spawns nested agents. Task review covers spec compliance and quality; sensitive code also gets an adversarial review. Implementers run confidence-review after code changes.
- For non-trivial changed functions, implementers hand the controller changed functions/absolute paths, actual diff, impact set/callers, invariants and focused test commands/output. The controller runs no-argument rewrite-tournament against the current changes and explicitly dispatches distinct Incumbent, Speed, Memory, Readability and Arbiter agents under the native dispatch rules. Preserve all skill steps, contract disqualifications, anonymous bracket and evidence; no silent inline fallback or weakened gate.
- The controller owns correctness and personally performs focused tests, a concrete invariant check, caller-contract verification and actual-diff inspection. An explicitly assigned fresh implementation agent backs up and applies winning candidates under the one-writer/file-ownership rules, adapting only the skill's in-tree apply step to the controller-does-not-write-source convention. The controller inspects the applied diff and verifies it; failed candidates are restored from backup by an assigned writer and the next candidate is re-verified as the skill requires. All required evidence must finish before completion, commit, merge or shipping. Pending reports say Awaiting controller rewrite-tournament and cannot claim completion. Review-only roles need no implementation handoff unless assigned implementation mode.
- Preserve all CLAUDE.md project invariants, commands and gates. No stub/fake value for real behavior and no catch-all that hides a failure unless fail-open behavior is documented and logged.
- Existing completed/frozen work is not reimplemented or repeatedly audited. Lower findings follow the owner's recorded stop rule.
- No new dependency, credential access, settings permission change, runtime provider migration, source-code edit or independent feature PR in Task 1.
- PR stack, D/F/N numbering and integration belong to “Resume Outstanding PRs review”; CP-4 prompt/pins/goldens belong to the CAOS “Resume Claude WIP”; calculator M-B belongs to “Resume quirky-darwin WIP”.
- Use a distinct worktree and test database per concurrent writer; do not kill other chats' processes or run overlapping full suites.

### Task 1: Configure GPT subagents

**Create:** `AGENTS.md`, `.codex/config.toml`, and seven `.codex/agents/mx-*.toml` files.

**Interfaces:** Consumes the existing CLAUDE.md and current native model availability. Produces project instructions and discoverable TOML role files; explicit spawn parameters remain required in harnesses whose tool has no custom-role selector.

- [ ] Read the task brief and binding instructions.
- [ ] Create project AGENTS.md with the GPT authority override, the role table below, native subagent dispatch rules, original gates/invariants, reporting/review obligations, ownership boundaries and isolated resource rules.
- [ ] Set project `[agents]` fields to `enabled = true`, `max_concurrent_threads_per_session = 3`, `default_subagent_model = "gpt-6.1-sol"`, `default_subagent_reasoning_effort = "medium"`. Set no permissions, credentials, MCP servers or primary-session model fields.
- [ ] Create each role TOML with required `name`, `description`, `developer_instructions`, and explicit `model` and `model_reasoning_effort`. Role instructions distinguish editing from reviewing, forbid nested delegation by implementers, require exact task paths and validation evidence, and specify the controller-owned tournament handoff above for non-trivial implementation changes. Reports awaiting that gate cannot claim completion and all reports end with `Not verified:`. Reviewers may write their report artifacts, but not source code; review-only roles need no implementation handoff unless assigned implementation mode.

| Role | Model | Effort | Responsibility |
|---|---|---|---|
| mx-scaffold | gpt-6-luna | high | Mechanical config, docs, fixtures and fully specified small tasks |
| mx-feature | gpt-6.1-sol | medium | Standard implementation and scoped fixes |
| mx-precise | gpt-6.1-sol | high | Task review, strict contracts and precise implementation |
| mx-invariants | gpt-6-astra | high | Money, security, ordering and concurrency implementation |
| mx-autonomous | gpt-6.1-sol | high | Coordinated multi-file implementation |
| mx-adversary | gpt-6-astra | high | Reproduce sensitive-code findings, source read-only |
| mx-architect | gpt-6-astra | high | Architecture and whole-branch review, source read-only |

- [ ] Validate TOML parsing, exact role names/models/efforts, required instructions and the three-child cap. Use the installed Codex CLI's real configuration validation when available; record any unsupported check rather than inventing a command. Run `git diff --check` and relevant pre-commit formatting/secret checks. No test file is needed for documentation/configuration-only changes.
- [ ] Write task report and a diff package, obtain a fresh task review, repair confirmed issues, then record confidence review. Rewrite tournament is skipped because Task 1 changes only docs/config.
- [ ] Publish identical reviewed project settings to the shared checkout without overwriting concurrent changes; provide concrete paths to the authorized peer chats. Commit only task-owned files in this branch.

### Task 2: Finish Book/Model proof and handoff

**Working artifacts:** `.superpowers/sdd/resume-2026-10-12/`; existing live-run protocol and spending authority in the project handoff.

- [ ] Inspect current active chat handles and exact PR/head state; retain the ownership map and use verified waits for ongoing work.
- [ ] Wait for the CP-4 repair and required calculator fixes to finish and integrate; inspect actual resulting code rather than treating a review verdict as integration evidence.
- [ ] Check the original design/ledgers for any remaining requirement owned by this chat; reconcile stale completion notes with current source and external state.
- [ ] Re-read the authorized live-run protocol and current spend/key limits without exposing credentials. Choose the permitted cheapest route carrying CP-1, CP-2G and CP-CF, with ceiling no greater than $6 and the recorded per-key headroom. Do not exceed the hard key/account or owner limit.
- [ ] Run the governed real provider proof using the integrated fixes and isolated data, then read the Model and assert both Base/Downside projections. Exercise digest-bound Add to Book end-to-end and verify the stored Book figures match the Model. Record exact run identity, artifacts, spend and any refusal.
- [ ] Reproduce and delegate any confirmed defect with a failing test, respecting other chats' ownership; verify the affected gates and required review workflows.
- [ ] Inspect all required deliverables and gates at the final current state. Mark the goal complete only when settings, conflict handling and the complete resumed work are proved. Preserve explicit unverified items and keep the goal active if evidence is missing.

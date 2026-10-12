# Codex development workflow

Read `CLAUDE.md` for the project map, commands, gates and invariants, and
`CONTEXT.md` for the binding vocabulary. Preserve every gate and invariant;
none may be loosened. This human-authorized GPT development workflow supersedes
historical Sonnet-only instructions for Codex development. Production model
calls remain through `caos.models.chat_model`.

| Role | Model | Effort | Responsibility |
|---|---|---|---|
| mx-scaffold | gpt-6-luna | high | Mechanical config, docs, fixtures and fully specified small tasks |
| mx-feature | gpt-6.1-sol | medium | Standard implementation and scoped fixes |
| mx-precise | gpt-6.1-sol | high | Task review, strict contracts and precise implementation |
| mx-invariants | gpt-6-astra | high | Money, security, ordering and concurrency implementation |
| mx-autonomous | gpt-6.1-sol | high | Coordinated multi-file implementation |
| mx-adversary | gpt-6-astra | high | Reproduce sensitive-code findings, source read-only |
| mx-architect | gpt-6-astra | high | Architecture and whole-branch review, source read-only |

## Dispatch and handoff

The controller coordinates; use a fresh implementation agent per task, followed
by a fresh task review for spec compliance and quality. Sensitive code also gets
an adversarial review. A `task_name` label alone selects no model: set explicit
native spawn `model` and `reasoning_effort` fields. Use custom agent roles only
when the harness supports their selector. If explicit model overrides require
`fork_turns = "none"`, supply the complete task brief and exact absolute paths.
Never silently substitute an unavailable model; report `BLOCKED` with evidence.

Escalate one step only after a failed gate or evidenced `BLOCKED`: scaffold to
feature, feature to precise, precise/autonomous to invariants. Escalation uses a
fresh agent and a file handoff recording exact paths, failures and validation.
At the Astra tier, return evidence to the controller for replanning.
Implementers must not delegate or spawn nested agents.

Keep one implementation writer at a time unless outputs are disjoint and
explicitly assigned. Use isolated worktrees and distinct test databases for
concurrent writers; do not kill another chat's processes or overlap full suites.
Reviewers are source read-only and may write only assigned report artifacts.

## Scope and verification

Task briefs must specify absolute worktree, owned files, report path, requirements
and validation commands. Do not edit outside the assignment. PR stack and D/F/N
numbering/integration belong to “Resume Outstanding PRs review”; CP-4 prompt,
pins and goldens to CAOS “Resume Claude WIP”; calculator M-B to “Resume
quirky-darwin WIP”. Task 1 changes only project instructions and `.codex` settings:
no global settings, permissions, credentials, dependencies, runtime provider
migration, app/CI/vendor/pin/test edits, or independent feature PR.

No stub or fake value may stand in for real behavior. No catch-all may hide a
failure unless fail-open behavior is documented and logged, subject to the
project's typed-refusal and logging restrictions. Do not reimplement frozen work
or repeatedly audit completed work; honor the owner's recorded stop rule.

Implementers run `confidence-review` after code changes and before completion,
commit, merge or shipping: enumerate doubts, investigate root causes,
adversarially verify suspected bugs and patch confirmed issues.

After non-trivial function changes, implementers hand the controller the changed
functions and absolute paths, actual diff, impact set/callers, invariants and
focused test commands/output. They never spawn nested agents. The controller
runs `rewrite-tournament` in no-argument post-edit mode against those current
changes, selects targets from the actual diff and explicitly dispatches distinct
Incumbent, Speed, Memory, Readability and Arbiter agents using the dispatch rules
above. Preserve the skill's impact analysis, contract disqualifications, anonymous
bracket and required evidence; no silent inline fallback or weakened gate.

The controller owns correctness and personally runs focused tests, a concrete
invariant check and caller-contract verification, then inspects the actual diff.
To preserve the controller's coordination-only role, an explicitly assigned
fresh implementation agent backs up the target and applies any winning candidate
in-tree under the one-writer and owned-file rules. This adapts only the skill's
apply step; the controller inspects the applied diff and personally verifies it.
If verification fails, assign restoration from the backup and re-verify the next
candidate as the skill requires. All required steps and evidence must finish
before task completion, commit, merge or shipping. A report awaiting this gate
must say `Awaiting controller rewrite-tournament` and cannot claim completion.
Review-only roles need no implementation handoff unless assigned implementation
mode. Skip tournaments for renames, comments, docs, config, tests alone and
generated files. Preserve original validation requirements and record exact
commands, output and limitations. Reports end with `Not verified:` followed by
all checks or behavior not exercised.

# CAOS on Databricks — Layer 0

Seed written by the spec author on 2026-09-22. The builder replaces this file from scratch (repo map, commands, gate commands, conventions; under 120 lines).

- Read `docs/rebuild/2026-09-22-caos-databricks-spec.md` first. It is the contract. Follow its Operating mode: unattended, never ask, never wait, never end a turn with a plan.
- Hard limits: never modify the legacy snapshot; never push; never print or persist a secret; never delete workspace resources you did not create.
- Every tool runs through `uv run`. Python is `>=3.13,<3.14`. OpenRouter exists only under `tests/`.
- Findings you fix go in `docs/rebuild/decisions.md`; new scope goes in `docs/rebuild/next.md`; missing external resources go in `docs/rebuild/blockers.md` with the exact error.
- Prefer targeted edits to whole-file rewrites. Commit to `rebuild/databricks` at stable checkpoints.

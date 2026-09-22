# ICM workspace — Layer 1

This folder is the agent-definition layer of CAOS (spec section 3.5, ICM paper arXiv 2603.16021). LangGraph owns execution, state, interrupts and persistence (`caos/graph/`); this folder owns what each graph node is.

## Layout

| Path | Layer | What it holds |
|---|---|---|
| `../CLAUDE.md` | 0 | the repo's identity file, always loaded |
| `CONTEXT.md` | 1 | this index |
| `stages/<slug>/CONTEXT.md` | 2 | one module's contract: Inputs (Source, File, Section, Why), Process, Outputs |
| `stages/<slug>/prompt.md` | 2 | the host prompt blocks that module's node renders, in order |
| `stages/cp-cf/references/` | 3 | host-owned authority (the CP-CF forecast contract) |
| `shared/prompt/*.md` | 3 | the host's prompt blocks, read byte for byte by `caos.icm.prompt_block` |
| `../vendor/deploy-v/` | 3 | the methodology bundle: never copied, read through the verified `Bundle` seam |
| `HOST_INTEGRITY_v1.json` | pin | digests of the two host-owned CP-CF files; `scripts/host_manifest.py` regenerates it |

## Rules

- **The pinned route is the execution order.** Folder names carry the bundle's layer numbers for reading, not for sequencing (Deploy V README: "a display grouping, not an execution order"). A run executes the nodes of its pinned `ResolvedRoute` in dependency order, one at a time.
- **A contract names exactly what the node loads.** The bundle rows of an Inputs table equal `delivered_authority(bundle, module_id)` in delivery order, `SKILL.md` first; `caos.icm.verify` refuses any drift.
- **Prompt blocks are data.** `caos/methodology/invocation.py` assembles the prompt from `shared/prompt/` blocks in the order `prompt.md` declares; the parity suite proves the rendered bytes equal the legacy host's.
- **Nothing here is an instruction to the model beyond the prompt blocks.** Vendor launcher text, Claude Code skill frontmatter and tool instructions are not loaded by any node.

## Stages

One folder per physical Deploy V module (25), plus `cp-parse` (CP-0's authority under its own route node) and `cp-cf` (the host's deterministic cash-flow forecast). `scripts/icm_stages.py --write` regenerates the folders from the bundle; `scripts/check_icm.py` verifies them.

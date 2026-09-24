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

## Process

Every stage's node runs the same six steps (its own `CONTEXT.md` points here rather than repeating them):

1. **Identity.** The host reads every host-owned fact from the store's pins (run input, pinned route, attempt ordinal, accepted upstream artifacts) and builds the front matter the module must copy (invariant 3).
2. **Context.** The node's evidence blocks are those CP-0's accepted T8 row names for this module, delivered whole; upstream handoffs are delivered as exact bytes labelled with their edge's `allowed_use`, with the host's register of their located citations.
3. **Prompt.** The blocks `prompt.md` declares, the authority files above each whole in its own tagged section, the upstream sections and the evidence; the whole encoded request is bounded before any attempt, reservation or call (`CONTEXT_OVER_CEILING`).
4. **Reserve, then call.** One attempt row, one reservation priced on the request that was built, one call through the model factory; the charge and producer identity are recorded with the call, before analysis (invariant 8).
5. **Validate.** The answer is parsed as the canonical envelope, the Markdown handoff is validated by the bundle's own validators and the host's ten checks, and every citation is re-located in the token index or refused (invariants 9 and 11).
6. **Accept.** The handoff and its host record are stored by digest and the attempt is accepted, state and event in one transaction (invariant 6).

## Outputs

What every stage's node writes on acceptance:

| Artifact | Location | Format |
|---|---|---|
| canonical Markdown handoff | blob store; `artifacts.artifact_sha256` | Markdown |
| host record | blob store; `artifacts.record_sha256` | JSON record |
| call outcome | `call_outcomes` | charge, producer identity, diagnostic digest |

## Stages

One folder per physical Deploy V module (25), plus `cp-parse` (CP-0's authority under its own route node) and `cp-cf` (the host's deterministic cash-flow forecast). `scripts/icm_stages.py --write` regenerates the folders from the bundle; `scripts/check_icm.py` verifies them.

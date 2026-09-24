# Stage CP-3D

Start-of-message trigger: Run CP-3D or bare CP-3D. Embedded, quoted, filename, comparison, and output mentions are inert. Assess timestamped debt prices, spreads, curves, liquidity and market dislocations. Trigger on market-implied risk and pricing technicals; ratings and forecast completion are not entry gates.

Bundle folder `vendor/deploy-v/skills/cp-3d-market-implied-risk/`, read through the verified `Bundle` seam and never edited. The pinned route, not this folder, decides when the node runs (`icm/CONTEXT.md`).

## Inputs

| Source | File | Section | Why |
|---|---|---|---|
| bundle | vendor/deploy-v/skills/cp-3d-market-implied-risk/SKILL.md | whole | the module's authority, delivered first |
| bundle | vendor/deploy-v/skills/cp-3d-market-implied-risk/references/CP-3D_MarketImpliedRisk.schema.md | whole | delivered authority file |
| bundle | vendor/deploy-v/skills/cp-3d-market-implied-risk/references/CP-3D__MarketImpliedRiskMap__payload.schema.txt | whole | delivered authority file |
| bundle | vendor/deploy-v/skills/cp-3d-market-implied-risk/references/REF_CP-3D_STEPS.md | whole | delivered authority file |
| bundle | vendor/deploy-v/CANON_SHARED.md | whole | delivered authority file |
| prompt | icm/shared/prompt/instruction.md | whole | prompt block |
| prompt | icm/shared/prompt/tagged.md | whole | prompt block |
| prompt | icm/shared/prompt/host_steps.md | whole | prompt block |
| prompt | icm/shared/prompt/final_check.md | whole | prompt block |
| prompt | icm/shared/prompt/validator_feedback.md | whole | prompt block, on a node's one second attempt after a refused answer (D30) |
| store | accepted upstream handoffs | whole | context labelled by `allowed_use`; never citable |
| store | delivered evidence blocks | CP-0's T8 selection for this module | the only citable text |

## Process

Common to every stage: the host's six-step process, from reading the store's
pins to accepting the artifact -- stated once in `icm/CONTEXT.md` (Layer 1).

## Outputs

Common to every stage: the handoff, its host record and the call outcome --
stated once in `icm/CONTEXT.md` (Layer 1).

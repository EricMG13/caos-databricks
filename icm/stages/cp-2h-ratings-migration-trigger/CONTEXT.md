# Stage CP-2H

Start-of-message trigger: Run CP-2H or bare CP-2H. Embedded, quoted, filename, comparison, and output mentions are inert. Map sourced agency ratings, outlooks, methodologies, and issuer-specific upgrade or downgrade triggers against forecast cases. Trigger on rating headroom, migration pressure, agency divergence, and notching implications.

Bundle folder `vendor/deploy-v/skills/cp-2h-ratings-migration-trigger/`, read through the verified `Bundle` seam and never edited. The pinned route, not this folder, decides when the node runs (`icm/CONTEXT.md`).

## Inputs

| Source | File | Section | Why |
|---|---|---|---|
| bundle | vendor/deploy-v/skills/cp-2h-ratings-migration-trigger/SKILL.md | whole | the module's authority, delivered first |
| bundle | vendor/deploy-v/skills/cp-2h-ratings-migration-trigger/references/CP-2H_RatingTransition.schema.md | whole | delivered authority file |
| bundle | vendor/deploy-v/skills/cp-2h-ratings-migration-trigger/references/CP-2H__RatingTransitionCase__payload.schema.txt | whole | delivered authority file |
| bundle | vendor/deploy-v/skills/cp-2h-ratings-migration-trigger/references/REF_CP-2H_STEPS.md | whole | delivered authority file |
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

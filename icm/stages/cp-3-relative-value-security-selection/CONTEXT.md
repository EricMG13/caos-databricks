# Stage CP-3

Start-of-message trigger: Run CP-3 or bare CP-3. Embedded, quoted, filename, comparison, and output mentions are inert. Compare priced bonds or loans, spread compensation, curve position, and instrument trade-offs after a credit view exists. Trigger on relative value, security selection, market pricing, and instrument recommendations.

Bundle folder `vendor/deploy-v/skills/cp-3-relative-value-security-selection/`, read through the verified `Bundle` seam and never edited. The pinned route, not this folder, decides when the node runs (`icm/CONTEXT.md`).

## Inputs

| Source | File | Section | Why |
|---|---|---|---|
| bundle | vendor/deploy-v/skills/cp-3-relative-value-security-selection/SKILL.md | whole | the module's authority, delivered first |
| bundle | vendor/deploy-v/skills/cp-3-relative-value-security-selection/references/CP-3A_RUNBOOK.md | whole | delivered authority file |
| bundle | vendor/deploy-v/skills/cp-3-relative-value-security-selection/references/CP-3A_SCHEMA_REFERENCE.md | whole | delivered authority file |
| bundle | vendor/deploy-v/skills/cp-3-relative-value-security-selection/references/CP-3A_SYSTEM_REFERENCE.md | whole | delivered authority file |
| bundle | vendor/deploy-v/skills/cp-3-relative-value-security-selection/references/CP-3B_RUNBOOK.md | whole | delivered authority file |
| bundle | vendor/deploy-v/skills/cp-3-relative-value-security-selection/references/CP-3B_SCHEMA_REFERENCE.md | whole | delivered authority file |
| bundle | vendor/deploy-v/skills/cp-3-relative-value-security-selection/references/CP-3B_SYSTEM_REFERENCE.md | whole | delivered authority file |
| bundle | vendor/deploy-v/skills/cp-3-relative-value-security-selection/references/CP-3_SCHEMA_REFERENCE.md | whole | delivered authority file |
| bundle | vendor/deploy-v/skills/cp-3-relative-value-security-selection/references/CP-3_SYSTEM_REFERENCE.md | whole | delivered authority file |
| bundle | vendor/deploy-v/skills/cp-3-relative-value-security-selection/references/REF_CP-3A_STEPS.md | whole | delivered authority file |
| bundle | vendor/deploy-v/skills/cp-3-relative-value-security-selection/references/REF_CP-3B_STEPS.md | whole | delivered authority file |
| bundle | vendor/deploy-v/skills/cp-3-relative-value-security-selection/references/REF_CP-3_STEPS.md | whole | delivered authority file |
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

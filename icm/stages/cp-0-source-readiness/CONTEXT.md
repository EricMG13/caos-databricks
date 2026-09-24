# Stage CP-0

Start-of-message trigger: Run CP-0 or bare CP-0. Embedded, quoted, filename, comparison, and output mentions are inert. Includes the CP-PARSE preparation phase and emits the source_readiness_register.

Bundle folder `vendor/deploy-v/skills/cp-0-source-readiness/`, read through the verified `Bundle` seam and never edited. The pinned route, not this folder, decides when the node runs (`icm/CONTEXT.md`).

## Inputs

| Source | File | Section | Why |
|---|---|---|---|
| bundle | vendor/deploy-v/skills/cp-0-source-readiness/SKILL.md | whole | the module's authority, delivered first |
| bundle | vendor/deploy-v/skills/cp-0-source-readiness/references/CP-0_SCHEMA_REFERENCE.md | whole | delivered authority file |
| bundle | vendor/deploy-v/skills/cp-0-source-readiness/references/CP-0_SYSTEM_REFERENCE.md | whole | delivered authority file |
| bundle | vendor/deploy-v/skills/cp-0-source-readiness/references/CP-0__SourceReadiness__payload.schema.txt | whole | delivered authority file |
| bundle | vendor/deploy-v/skills/cp-0-source-readiness/references/CP-PARSE_SCHEMA_REFERENCE.md | whole | delivered authority file |
| bundle | vendor/deploy-v/skills/cp-0-source-readiness/references/CP-PARSE__DataPreparation__payload.schema.txt | whole | delivered authority file |
| bundle | vendor/deploy-v/skills/cp-0-source-readiness/references/CP0_CAPACITY_RESUME_CONTRACT_v1.md | whole | delivered authority file |
| bundle | vendor/deploy-v/skills/cp-0-source-readiness/references/CP0_PROFILE_ANCHOR_CONTRACT_v1.md | whole | delivered authority file |
| bundle | vendor/deploy-v/skills/cp-0-source-readiness/references/REF_CP-0_STEPS.md | whole | delivered authority file |
| bundle | vendor/deploy-v/skills/cp-0-source-readiness/references/REF_CP-PARSE_STEPS.md | whole | delivered authority file |
| bundle | vendor/deploy-v/CANON_SHARED.md | whole | delivered authority file |
| prompt | icm/shared/prompt/instruction.md | whole | prompt block |
| prompt | icm/shared/prompt/gate_instruction.md | whole | prompt block |
| prompt | icm/shared/prompt/tagged.md | whole | prompt block |
| prompt | icm/shared/prompt/host_steps.md | whole | prompt block |
| prompt | icm/shared/prompt/final_check.md | whole | prompt block |
| prompt | icm/shared/prompt/cp0_final_check.md | whole | prompt block |
| prompt | icm/shared/prompt/validator_feedback.md | whole | prompt block, on a node's one second attempt after a refused answer (D30) |
| store | accepted upstream handoffs | whole | context labelled by `allowed_use`; never citable |
| store | delivered evidence blocks | CP-0's T8 selection for this module | the only citable text |

## Process

Common to every stage: the host's six-step process, from reading the store's
pins to accepting the artifact -- stated once in `icm/CONTEXT.md` (Layer 1).

## Outputs

Common to every stage: the handoff, its host record and the call outcome --
stated once in `icm/CONTEXT.md` (Layer 1).

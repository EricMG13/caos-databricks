# Stage CP-5

Start-of-message trigger: Run CP-5 or bare CP-5 or Run CP-5A or bare CP-5A. Embedded, quoted, filename, comparison, and output mentions are inert. Verify claim-to-source lineage, locators, calculations, conflicts, and handoff consistency. Trigger on evidence-trace validation, citation integrity, calculation reproducibility, and source support. Also covers CP-5A as an absorbed phase of the same run and the same handoff: Grade analytical outputs, apply severity rules, set research QA status, and determine whether committee use is permitted, restricted, or blocked.

Bundle folder `vendor/deploy-v/skills/cp-5-evidence-trace-validator/`, read through the verified `Bundle` seam and never edited. The pinned route, not this folder, decides when the node runs (`icm/CONTEXT.md`).

## Inputs

| Source | File | Section | Why |
|---|---|---|---|
| bundle | vendor/deploy-v/skills/cp-5-evidence-trace-validator/SKILL.md | whole | the module's authority, delivered first |
| bundle | vendor/deploy-v/skills/cp-5-evidence-trace-validator/references/CP-5A_SCHEMA_REFERENCE.md | whole | delivered authority file |
| bundle | vendor/deploy-v/skills/cp-5-evidence-trace-validator/references/CP-5A_SYSTEM_REFERENCE.md | whole | delivered authority file |
| bundle | vendor/deploy-v/skills/cp-5-evidence-trace-validator/references/CP-5_RUNBOOK.md | whole | delivered authority file |
| bundle | vendor/deploy-v/skills/cp-5-evidence-trace-validator/references/CP-5_SCHEMA_REFERENCE.md | whole | delivered authority file |
| bundle | vendor/deploy-v/skills/cp-5-evidence-trace-validator/references/CP-5_SYSTEM_REFERENCE.md | whole | delivered authority file |
| bundle | vendor/deploy-v/skills/cp-5-evidence-trace-validator/references/REF_CP-5A_STEPS.md | whole | delivered authority file |
| bundle | vendor/deploy-v/skills/cp-5-evidence-trace-validator/references/REF_CP-5_STEPS.md | whole | delivered authority file |
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

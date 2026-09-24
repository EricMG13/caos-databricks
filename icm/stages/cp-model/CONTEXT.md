# Stage CP-MODEL

Start-of-message trigger: Run CP-MODEL or bare CP-MODEL. Embedded, quoted, filename, comparison, and output mentions are inert. Build the canonical CP-MODEL Credit Snapshot plus historical/forecast Excel workbook from validated CP-1, CP-1A, CP-1B, CP-2, CP-2A and optional CP-2G handoffs. Use only when the user explicitly asks to create or populate the CP-MODEL workbook.

Bundle folder `vendor/deploy-v/skills/cp-model/`, read through the verified `Bundle` seam and never edited. The pinned route, not this folder, decides when the node runs (`icm/CONTEXT.md`).

## Inputs

| Source | File | Section | Why |
|---|---|---|---|
| bundle | vendor/deploy-v/skills/cp-model/SKILL.md | whole | the module's authority, delivered first |
| bundle | vendor/deploy-v/skills/cp-model/agents/openai.yaml | whole | delivered authority file |
| bundle | vendor/deploy-v/skills/cp-model/references/CP-MODEL_CP_WORKBOOK_EXPORT_HARD_GATE.md | whole | delivered authority file |
| bundle | vendor/deploy-v/skills/cp-model/references/CP-MODEL_CP_WORKBOOK_EXPORT_PAYLOAD_BASE.schema.txt | whole | delivered authority file |
| bundle | vendor/deploy-v/skills/cp-model/references/CP-MODEL_CP_WORKBOOK_EXPORT_SPEC.md | whole | delivered authority file |
| bundle | vendor/deploy-v/skills/cp-model/references/CP-MODEL_SCHEMA_REFERENCE.md | whole | delivered authority file |
| bundle | vendor/deploy-v/skills/cp-model/references/CP-MODEL_SYSTEM_REFERENCE.md | whole | delivered authority file |
| bundle | vendor/deploy-v/skills/cp-model/references/CP-MODEL__CreditSnapshotModelWorkbook__payload.schema.txt | whole | delivered authority file |
| bundle | vendor/deploy-v/skills/cp-model/references/REF_CP-MODEL_STEPS.md | whole | delivered authority file |
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

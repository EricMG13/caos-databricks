# Stage CP-2G

Start-of-message trigger: Run CP-2G or bare CP-2G. Embedded, quoted, filename, comparison, and output mentions are inert. Build auditable base, upside, and downside forecasts for earnings, free cash flow, debt, liquidity, leverage, coverage, and deleveraging. Trigger on multi-period forecast cases, credit-model assumptions, and financial breakpoints.

Bundle folder `vendor/deploy-v/skills/cp-2g-forward-credit-model/`, read through the verified `Bundle` seam and never edited. The pinned route, not this folder, decides when the node runs (`icm/CONTEXT.md`).

## Inputs

| Source | File | Section | Why |
|---|---|---|---|
| bundle | vendor/deploy-v/skills/cp-2g-forward-credit-model/SKILL.md | whole | the module's authority, delivered first |
| bundle | vendor/deploy-v/skills/cp-2g-forward-credit-model/references/CP-2G_ForwardCreditModel.schema.md | whole | delivered authority file |
| bundle | vendor/deploy-v/skills/cp-2g-forward-credit-model/references/CP-2G__ForwardCreditModel__payload.schema.txt | whole | delivered authority file |
| bundle | vendor/deploy-v/skills/cp-2g-forward-credit-model/references/REF_CP-2G_STEPS.md | whole | delivered authority file |
| bundle | vendor/deploy-v/CANON_SHARED.md | whole | delivered authority file |
| prompt | icm/shared/prompt/instruction.md | whole | prompt block |
| prompt | icm/shared/prompt/tagged.md | whole | prompt block |
| prompt | icm/shared/prompt/host_steps.md | whole | prompt block |
| prompt | icm/shared/prompt/final_check.md | whole | prompt block |
| prompt | icm/shared/prompt/forecast_extension.md | whole | prompt block, when the route carries CP-CF |
| prompt | icm/shared/prompt/validator_feedback.md | whole | prompt block, on a node's one second attempt after a refused answer (D30) |
| store | accepted upstream handoffs | whole | context labelled by `allowed_use`; never citable |
| store | delivered evidence blocks | CP-0's T8 selection for this module | the only citable text |

## Process

Common to every stage: the host's six-step process, from reading the store's
pins to accepting the artifact -- stated once in `icm/CONTEXT.md` (Layer 1).

## Outputs

Common to every stage: the handoff, its host record and the call outcome --
stated once in `icm/CONTEXT.md` (Layer 1).

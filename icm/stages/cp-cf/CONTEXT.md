# Stage CP-CF

CP-CF — Deterministic cash-flow forecast

CP-CF is host-owned: the calculator is repo code, byte-pinned by `icm/HOST_INTEGRITY_v1.json`. The pinned route, not this folder, decides when the node runs (`icm/CONTEXT.md`).

## Inputs

| Source | File | Section | Why |
|---|---|---|---|
| host | icm/stages/cp-cf/references/SKILL.md | whole | the module's authority, delivered first |
| host | caos/calculators/cash_flow.py | whole | delivered authority file |
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

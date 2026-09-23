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

1. **Identity.** The host reads every host-owned fact from the store's pins
   (run input, pinned route, attempt ordinal, accepted upstream artifacts) and
   builds the front matter the module must copy (invariant 3).
2. **Context.** The node's evidence blocks are those CP-0's accepted T8 row
   names for this module, delivered whole; upstream handoffs are delivered as
   exact bytes labelled with their edge's `allowed_use`, with the host's
   register of their located citations.
3. **Prompt.** The blocks `prompt.md` declares, the authority files above each
   whole in its own tagged section, the upstream sections and the evidence;
   the whole encoded request is bounded before any attempt, reservation or
   call (`CONTEXT_OVER_CEILING`).
4. **Reserve, then call.** One attempt row, one reservation priced on the
   request that was built, one call through the model factory; the charge and
   producer identity are recorded with the call, before analysis (invariant 8).
5. **Validate.** The answer is parsed as the canonical envelope, the Markdown
   handoff is validated by the bundle's own validators and the host's ten
   checks, and every citation is re-located in the token index or refused
   (invariants 9 and 11).
6. **Accept.** The handoff and its host record are stored by digest and the
   attempt is accepted, state and event in one transaction (invariant 6).

## Outputs

| Artifact | Location | Format |
|---|---|---|
| canonical Markdown handoff | blob store; `artifacts.artifact_sha256` | Markdown |
| host record | blob store; `artifacts.record_sha256` | JSON record |
| call outcome | `call_outcomes` | charge, producer identity, diagnostic digest |

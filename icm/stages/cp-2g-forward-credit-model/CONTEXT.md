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

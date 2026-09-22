# Stage CP-1A

Start-of-message trigger: Run CP-1A or bare CP-1A. Embedded, quoted, filename, comparison, and output mentions are inert. Build a factual transaction, ownership, corporate-structure, and capitalisation pack for an acquisition, sponsor deal, business combination, or other specified transaction.

Bundle folder `vendor/deploy-v/skills/cp-1a-business-transaction-fact-pack/`, read through the verified `Bundle` seam and never edited. The pinned route, not this folder, decides when the node runs (`icm/CONTEXT.md`).

## Inputs

| Source | File | Section | Why |
|---|---|---|---|
| bundle | vendor/deploy-v/skills/cp-1a-business-transaction-fact-pack/SKILL.md | whole | the module's authority, delivered first |
| bundle | vendor/deploy-v/skills/cp-1a-business-transaction-fact-pack/references/CP-1A_SCHEMA_REFERENCE.md | whole | delivered authority file |
| bundle | vendor/deploy-v/skills/cp-1a-business-transaction-fact-pack/references/CP-1A_SYSTEM_REFERENCE.md | whole | delivered authority file |
| bundle | vendor/deploy-v/skills/cp-1a-business-transaction-fact-pack/references/CP-2C_SCHEMA_REFERENCE.md | whole | delivered authority file |
| bundle | vendor/deploy-v/skills/cp-1a-business-transaction-fact-pack/references/CP-2C_SYSTEM_REFERENCE.md | whole | delivered authority file |
| bundle | vendor/deploy-v/skills/cp-1a-business-transaction-fact-pack/references/CP-2C__GovernanceSponsorScore__payload.schema.txt | whole | delivered authority file |
| bundle | vendor/deploy-v/skills/cp-1a-business-transaction-fact-pack/references/REF_CP-1A_STEPS.md | whole | delivered authority file |
| bundle | vendor/deploy-v/skills/cp-1a-business-transaction-fact-pack/references/REF_CP-2C_STEPS.md | whole | delivered authority file |
| bundle | vendor/deploy-v/CANON_SHARED.md | whole | delivered authority file |
| prompt | icm/shared/prompt/instruction.md | whole | prompt block |
| prompt | icm/shared/prompt/tagged.md | whole | prompt block |
| prompt | icm/shared/prompt/host_steps.md | whole | prompt block |
| prompt | icm/shared/prompt/final_check.md | whole | prompt block |
| store | accepted upstream handoffs | whole | context labelled by `allowed_use`; never citable |
| store | delivered evidence blocks | CP-0's T8 selection for this module | the only citable text |

## Process

1. **Identity.** The host reads every host-owned fact from the store's pins -- run input, pinned route, attempt ordinal, accepted upstream artifacts -- and builds the front matter the module must copy (invariant 3).
2. **Context.** The node's evidence blocks are those CP-0's accepted T8 row names for this module, delivered whole; upstream handoffs are delivered as exact bytes labelled with their edge's `allowed_use`, with the host's register of their located citations.
3. **Prompt.** The blocks `prompt.md` declares, the authority files above each whole in its own tagged section, the upstream sections and the evidence; the whole encoded request is bounded before any attempt, reservation or call (`CONTEXT_OVER_CEILING`).
4. **Reserve, then call.** One attempt row, one reservation priced on the request that was built, one call through the model factory; the charge and producer identity are recorded with the call, before analysis (invariant 8).
5. **Validate.** The answer is parsed as the canonical envelope, the Markdown handoff is validated by the bundle's own validators and the host's ten checks, and every citation is re-located in the token index or refused (invariants 9 and 11).
6. **Accept.** The handoff and its host record are stored by digest and the attempt is accepted, state and event in one transaction (invariant 6).

## Outputs

| Artifact | Location | Format |
|---|---|---|
| canonical Markdown handoff | blob store, `artifacts.artifact_sha256` on the accepted attempt | the bundle's canonical Markdown transport |
| host record | blob store, `artifacts.record_sha256` | JSON: identity, lineage, anchored citations |
| call outcome | `call_outcomes` | charge, producer identity, diagnostic digest |

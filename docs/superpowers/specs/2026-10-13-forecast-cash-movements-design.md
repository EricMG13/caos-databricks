# Forecast cash movements and segment revenue design

Date: 2026-10-13. Base: `e312e3a1f2ba3a853ef734e9e461749f4a2c924c`.
Worktree: `/Users/ericguei/.codex/worktrees/forecast-cash-movements/caos-databricks`.

## Purpose and authority

Extend the host-owned CP-CF contract so an honestly stated forecast can carry equity, other investing/financing, restricted-cash transfers, noncash debt carrying changes and differing operating-segment revenue assumptions. Make those values usable by the native Model. This is one compatibility feature, supporting the larger original CZR ten-node FULL_CREDIT_32 / RELATIVE_VALUE / model_extension proof and eventual real Book Add/replay.

The controller's task brief records the user's instruction to complete remaining tasks and apply reviewed recommendations. That supplies decision authority for this design; no additional design-confirmation pause is required. It does not supply new provider spending or a new live-testing window: the original 35 cash guard and expired window remain. The controller owns review and commits. Historical d92 worktrees, accepted cases and evidence remain immutable. Never repin an old run to this host.

This design does not adopt numerical analyst assumptions. Their revision must separately preserve otherFI −24/−26, first-year restricted-cash increase 15, noncash carrying +13 H1 plus +13 H2 = +26 FY, corporate-flat revenue, a normalized adjusted-EBITDA bridge and CFO after financing-lease principal but before debt interest/taxes. GAAP H1 EBITDA 1715 must not be labelled adjusted EBITDA 1807. Prospective software contingency must not claim nonexistent historical scope.

## Context and alternatives

Current `caos/calculators/cash_flow.py` admits 13 required movements; only acquisitions/disposals and fx/perimeter are signed. `caos/methodology/forecast.py` requires four CP-2G financial rows per case/year; the two unsupported rows map to READY zero. `caos/calculators/credit_model/projection.py` hardcodes equity zero, omits other investing/financing, closes cash at opening plus NCF and grows segments by their allocated division slot. Corporate/elimination segments are held flat. The existing layout already includes other investing/financing and FX/other cash rows.

1. **Recommended: optional, explicitly owned contract fields.** Preserve existing requests/results when fields are absent; enable additional movements and explicit segment revenue only on accepted, bounded input. This keeps host authority, quote binding and vendor registers intact. It adds focused host validation and calculation branches.
2. **Mandatory new contract version.** Require all callers to restate the new fields and rework transport and fixtures. This gives an obvious capability boundary but needlessly breaks accepted old requests and increases migration work. Host source identity already supplies the version boundary.
3. **Fit the assumptions into legacy fields.** Force otherFI to zero, alter the segment perimeter or encode restricted cash/carrying amortization as FX. Rejected: it changes economic meaning, can manufacture reconciliation and violates owner authority.

## Exact request and result contract

Keep the `caos-forecast-v1` fence and existing request/envelope keys. Each driver may additionally contain:

| Field | Type and sign | Effect | Conditional result location |
|---|---|---|---|
| `net_equity_issue_repay` | signed money string; positive receipt | cash only | `financing.net_equity_issue_repay` |
| `other_investing_financing` | signed money string; positive receipt | cash only | `financing.other_investing_financing` |
| `restricted_cash_change` | signed money string; positive increase in restriction | reduces accessible cash | `cash.restricted_cash_change` |
| `carrying_value_change` | signed money string; positive carrying increase | debt only, noncash | `debt.carrying_value_change` |
| `segment_revenue` | nonempty object from exact CP-1 segment ID to signed money string | explicit segment levels | `operating.segment_revenue` |

Each conditional key is emitted only when that input key is present, including explicit zero. The segment result map contains the input keys and six-decimal canonical amount strings. Absence means the legacy scope and arithmetic, never a new claim that an unstated economic item is zero. Existing required movements remain required and retain existing unavailable propagation. Unknown keys, explicit null, bool, numeric JSON, exponent notation, nonfinite values and invalid strings are refused. Money retains at most 18 integer and 6 fractional digits, current length bounds and Decimal precision 38 / ROUND_HALF_EVEN. No float arithmetic.

For a present map, check its shape and 1–40 entry ceiling before parsing any amounts. `MAX_FORECAST_SEGMENTS = 40` is a new host capability ceiling, not a claimed vendor schema limit: inspection found no segment-specific cap in CP-1's schema/parser. Existing handoff table/byte caps remain in force. Keys use the existing 64-character safe identifier constraints and must equal the accepted CP-1 IDs byte for byte; no normalization aliases or slash/tilde pointer ambiguity. Reject an unsafe CP-1 ID when this optional capability is requested. Existing requests without a map remain unaffected. All map values are parsed even on an unavailable driver so malformed hidden values cannot bypass validation.

The pure cash calculator checks exact Decimal equality of the map sum to driver revenue in request units. Because every leaf has at most six decimals and both sums run under precision 38, no additional rounding tolerance is needed. Do not reuse debt/cash reconciliation tolerance for segment sums. Governed use requires request scale `millions`, CP-1 unit `MILLIONS` and equal currency. Map values are forward currency millions, not percentages or current-period copied defaults.

Let E, O, R and C denote the four optional movements, with absent fields contributing zero only inside legacy arithmetic:

```text
FCF = cfo − capex − cash_interest − cash_taxes
financing_investing = issuance − contractual_repayment − optional_repayment
                       − acquisitions_disposals
closing_cash = opening_cash + FCF − distributions + financing_investing + E + O − R
closing_debt = opening_debt + issuance − contractual_repayment − optional_repayment
               + pik + capitalised_interest + fx_perimeter + C
```

Keep `financing_investing` itself unchanged; the additional components are separately visible and counted once. Cash opening/closing/accessible denote accessible cash under the declared perimeter. Restricted cash is a transfer outside that perimeter, not CFO, capex, FX or debt. Carrying changes never enter cash. Stated closes remain independent owner-supplied values, compared using the unchanged own-opening residual caps (absolute 1000, relative 0.001, request tolerance and zero-opening exactness). Prior failure still withholds subsequent periods of that case.

## Owner validation and data flow

Every new scalar leaf remains under `/drivers/<index>/...` and therefore CP-2G-owned through `_OWNERS`, `_leaves`, exact assignment lines and linked anchored citations. No blanket object quote substitutes for leaf ownership. The existing CP-1/CP-2G/CP-4 accepted dependency chain, header HMAC, citations, approval digests and replay verification remain mandatory.

Retain CP-2G's complete 42-row proposal interface and its four financial driver rows per case/year. `net_equity_issue_repay` and `other_investing_financing` map without negation to their matching optional request fields when present; when absent their financial rows must still be READY zero. Acquisitions/disposals and dividends retain existing reverse-sign mapping. READY, exact pair/year, CURRENCY_MM, uniqueness, null and NOT_APPLICABLE semantics are unchanged. Guidance must describe equality failures accurately for both negated and direct mappings.

Restricted cash, carrying changes and segment leaves use source-supplied supplemental pointer assignments plus the existing assumptions register; they do not invent vendor financial-driver IDs. Host instructions declare the capability in `icm/stages/cp-cf/references/SKILL.md` and `icm/shared/prompt/forecast_extension.md`. No vendor edit, dependency or database migration is required.

Add a pure forecast validation entry point `validate_segment_mapping(contract, markdown, owner)` where owner is accepted CP-1 Markdown. `canonical._forecast_inputs` already has those bytes and invokes this after existing binding and financial mapping validation for CP-CF. Parse with `handoff_tables` then `cp1_registers`; do not query SQL or trust provider-supplied duplicate registers. Map no-fields requests return before CP-1 parsing so old sparse CP-1 handoffs retain their behavior. Map requests refuse unreadable tables, missing/ambiguous base, missing segment history, inconsistent definitions, unrecognized period references, currency/unit mismatch or perimeter mismatch using `HANDOFF_INCOMPLETE` at the owner boundary.

Known IDs are the exact distinct segment IDs in the accepted CP-1 segment schedule. Require each map's key set to equal that set, and every known ID to have a finite latest-FY base value. Use the same latest labelled historical FY selection as projection, including its incomplete-period checks; no new fallback for this capability. All relevant segment period references must exist in CP-1. The latest FY must state an entity perimeter identical to request perimeter. Refuse conflicting segment types across periods. Corporate/elimination map values must equal their latest FY base values in every case/year. Operating segments may diverge even in the same division. Retain existing allocation IDs and do not change CP-1's grouping. The existing growth rows remain required by their own contracts; a declared division growth may describe weighted operating-segment growth, with corporate exclusion explained in the evidence, and is not reapplied to explicit segment amounts.

The projection path must independently enforce the same CP-1 map contract from its `ProjectionInputs.regs` and history before emitting cells, because direct pure callers do not obtain canonical acceptance automatically. Share a pure validation helper rather than duplicate semantics. Pure calculator shape errors remain `METHODOLOGY_INPUT_INVALID`; Model input-contract errors follow existing `HANDOFF_MALFORMED`; canonical converts expected malformed input to `HANDOFF_INCOMPLETE` without leaking text.

## Native Model behavior and limits

When a segment map is present, `_revenue` uses its validated amounts for `bu:<segment>` cells with PROJECTED basis and a note stating explicit CP-2G forecast assumption. The next year's state retains those values. When absent, `_grown` and all historical/base-span rules are unchanged. Do not synthesize CP-1 source references for CP-2G values; lineage must remain the accepted CP-CF request and its CP-2G bindings. API/Book source routes must still expose the accepted chain, never a current-source substitution.

`_cash_flow` uses signed explicit equity and otherFI values. Absent equity keeps the existing zero cell and note; absent otherFI preserves existing frame shape. NCF includes E and O exactly once. `_year` adds `fx_and_other_cash = −restricted_cash_change` only when the field is present, and cash closes at opening + NCF + that transfer. Explain the restricted-cash transfer in the cell note; it is not FX. Add carrying_value_change to `debt_non_cash`, never debt issuance or interest. Preserve legacy cells and their notes when new fields are absent.

Native Model still uses its facility/rate-deck interest and scheduled amortization; this feature does not silently replace them with company estimates or change the assumed-refinancing policy. The later proof must independently reconcile annual opening, FY2026 H1+H2, facility principal and rate-deck charges with adopted assumptions. A discrepancy, including FY2028 principal 767 versus held maturity balances, blocks the useful Model claim and requires a separately scoped decision; it cannot be repaired by relabeling carrying changes. Negative forecast cash remains an explicit unmet-funding result, never invented liquidity.

## Compatibility, authority and validation

Run `uv run python scripts/host_manifest.py` after source/instruction edits to generate `icm/HOST_INTEGRITY_v1.json` and `caos/methodology/host_pin.py`. The script also rewrites bundle_pin.py; its bytes must remain unchanged because vendor bytes do not change. Update only genuinely changed authority measurements/pins and prompt/route surfaces through their recorded generation procedures. Reproduce old prompt/forecast goldens using the D34 legacy mirror before legitimate prompt regeneration. Do not regenerate old cash_flow or forecast expectations merely to make tests pass. Old absent-field forecast bytes must match committed parity artifacts byte for byte; old host identities replay only with their old source.

Tests cover both signs and zero for each movement; no cash effect from carrying; restricted-cash increase and release; explicit-zero conditional shape; malformed leaves; collection limits before numeric parse; hostile ambient Decimal context; independent within/outside residual boundaries; multi-year/case chaining; nonuniform same-slot segments; corporate held flat; exact sums; unknown/missing IDs; missing history/perimeter and wrong units; per-leaf citations and owner tampering; changed upstream evidence; unchanged old bytes; new Model rows and algebra; accepted replay; cloned Model grid source lineage and actual Book figures. Use independent answer keys, not production helpers to construct expected money.

Fresh implementation agents run confidence-review; every nontrivial changed function goes through the controller's complete five-role rewrite-tournament and application by an assigned writer. Fresh spec and Astra adversarial review follow. The controller personally runs focused tests, concrete cash/debt/segment invariants, caller checks and diff review. Complete every CLAUDE gate in one assigned test database without overlapping another full suite; never weaken suppressions, coverage, IO or integrity checks. No provider call or paid/live proof is authorized by this document.

## Brainstorming checklist and self-review

- [x] Explore context: AGENTS/CLAUDE/CONTEXT, current cash/forecast/projection/canonical/model-input sources, tests, vendor segment validator and source reviews, latest commits.
- [x] Visual companion: no visual question needed.
- [x] Clarification: purpose, authority, compatibility and scope resolved by controller brief and recorded user authority.
- [x] Three approaches considered with explicit recommendation and tradeoffs.
- [x] Design presented in this written artifact under the user's delegated decision authority; controller reviews before code.
- [x] Design saved; controller retains commit ownership.
- [x] Self-review: fields, sign conventions, explicit/absent behavior, units, full coverage and refusal boundaries specified; no unresolved placeholders.
- [x] Written-spec review routed to controller; no renewed user permission is required by the supplied brief.
- [x] Transition to writing-plans for this same feature.

Not verified: implementation, tests/gates, legacy-mirror regeneration, changed-host replay, source adoption, facility/deck/calendar equivalence, Model/Book Add/replay proof, full ten-node completion, live provider operation, spending authorization, deployment or forecast realization.

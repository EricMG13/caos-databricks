# Owned forecast cash debt-service basis

Date: 2026-10-13. Worktree: `/Users/ericguei/.codex/worktrees/forecast-cash-movements/caos-databricks`.
Companion to `2026-10-13-forecast-cash-movements-design.md`; this document supersedes that design's later facility-equivalence blocker with an explicit new capability. It does not change any historical accepted artifact or claim the two projection methods are equivalent.

## Decision and evidence

Use an explicitly selected, source-bound aggregate cash debt-service basis. The user's delegated instruction to complete remaining tasks and apply recommendations authorizes the controller's scope decision; no new design-confirmation pause is required. No new spending or live-testing window follows. Original cash guard 35 and the expired window remain. Controller review precedes code and the controller owns commits.

The bounded review at `/Users/ericguei/.codex/worktrees/governed-proof-integration/caos-databricks/.superpowers/sdd/resume-2026-10-12/forecast-facility-equivalence-review.md` and its `forecast-facility-equivalence-scratch/native-diagnostic.json` show: native facility amortisation is 91.5 each year, native maturities are assumed refinanced, and missing opening history/deck/terms leave native interest unavailable. The analyst forecast requires actual H1 plus future H2, principal 55/114/767 and full-year cash interest 738/750/680 in Base. These are different methods, not a round-off or classification discrepancy.

Accepted CP-1 contains `net_debt_issue_repay | H1_2026 | -98`, calculation status Calculated, source Q10 p.4 [C3]. Its period register has FY2025 2025-01-01 through 2025-12-31, H1_2026 2026-01-01 through 2026-06-30, and PE2025 2025-12-31. Consequently no fabricated gross historical or per-facility leaf is needed. H1 issuance 885 less repayment 983 is net −98; 983 is not a future contractual repayment schedule. FY2026 net debt cash is −98−55=−153, while carrying +26 makes canonical debt 11784−153+26=11657. Cash opens at 887. The cost adjustment −8 in the actual PE2025 facility stack is a valid signed carrying balance, not a fabricated facility.

Options considered:

1. **Recommended: explicit owned aggregate basis.** Primary Model totals use accepted CP-CF cash debt service with a separately bound historical debt-cash bridge and future aggregate principal. Complete aggregate outputs are useful without claiming an instrument allocation. Existing facility basis remains unchanged when the selector is absent.
2. **Fully dated instrument model.** Add face/carrying schedules, actual gross issuance/repayment allocation, day counts, maturity decisions and forecast rates. This could produce instrument detail but requires unsupplied evidence and substantially broader scope; it cannot honestly be inferred from current aggregate sources.
3. **Solve rates or reclassify principal to fit old equations.** Rejected. Artificial deck rates, fabricated facility IDs, calling historical repayments optional, or passing 1038 as future contractual principal would manufacture equivalence.

## Closed request extension and ownership

Keep the existing transport and required legacy fields. Add only the following request keys/children; every scalar and empty array remains bound by the existing exact linked-citation assignment mechanism:

| Path | Owner | Contract |
|---|---|---|
| `/projection_basis` | CP-2G | Optional exact string `OWNED_CASH_DEBT_SERVICE`; no other value, null or inferred selector |
| `/actuals` | CP-1 | Present and closed in selected mode: exactly `debt_cash_movements` |
| `/actuals/debt_cash_movements` | CP-1 | Array of zero or one closed historical bridge; shared across scenarios |
| bridge `/period_id` | CP-1 | Exact first projected period ID, e.g. `FY2026` |
| bridge `/historical_period_id` | CP-1 | Exact accepted CP-1 actual YTD ID, e.g. `H1_2026` |
| bridge `/amount` | CP-1 | Signed strict money string, exactly accepted `net_debt_issue_repay` for the historical ID |
| `/periods/<i>/start_date`, `/end_date` | CP-1 | Required in selected mode, ISO dates; annual calendar-year boundaries |
| `/contractual/aggregate_amortisation` | CP-4 | Exactly one closed future principal row for every requested case/period |
| aggregate row | CP-4 | Exactly `case`, `period_id`, `start_date`, `end_date`, `amount`; nonnegative strict money amount |

Selected mode requires `actuals` and `contractual.aggregate_amortisation`, including explicit `actuals.debt_cash_movements=[]` for a wholly prospective forecast. Existing `contractual.amortisation` remains required but must be exactly `[]` in this mode. Aggregate and per-facility amortisation cannot coexist here, even as zero rows; there is no invented facility identifier. Without the selector, refuse these newly reserved structural keys and date additions instead of silently applying part of this capability. Earlier optional movement and segment fields remain independently usable without this selector.

The new mode initially supports full January–December annual periods only, consecutive years per case, with a common first period ID/year across cases and a prior December31 FY opening. This is an explicit capability boundary, not a change to legacy quarterly/fiscal-year handling. Each `days` value equals the actual inclusive span (365/366), fiscal_year equals that year and IDs/pairs retain existing uniqueness bounds. The requested opening `as_of_period_id` must identify the actual accepted FY historical column, `FY2025` in this proof, never rely on the existing PE-period fallback. CP-1 must supply and own these forecast calendar assignments; current proposal metadata is not a substitute.

The bridge array is shared to prevent independently restating historical actuals by scenario. If present, it applies once to each case's first requested period and to no later year. The CP-1 YTD must start on that forecast year's January1, end strictly before December31 and have fiscal_year, currency, MILLIONS unit, accounting basis and entity perimeter matching the accepted opening and request. Its day count must equal its dates. Refuse quarter, LTM, PERIOD_END, missing date, unknown ID, unavailable account, duplicate account or inconsistent footing. CP-1's finite account amount must equal the bridge exactly, including sign; no tolerance, scalar reassignment or inferred arithmetic from unrelated history.

Each CP-4 aggregate row covers the remaining forecast span: first year starts the day after actual YTD end when a bridge exists, otherwise January1; later years start January1; all end December31. It must match the requested pair and cover that span exactly once, with a supplied amount even when zero. No gaps, overlaps, unknown pairs, repeated actual bridge, or reuse of historical repayment as future principal. CP-4 owns amount and schedule classification; host source quote validation does not itself prove legal enforceability. Selected-mode driver `issuance` and `optional_repayment` apply only within this future span. For the intended scenario they are explicitly source-owned zero. They do not contain H1 issuance885 or repayment983 again.

All collections are bounded before the first Decimal parse: at most one bridge, aggregate rows no more than requested pairs (existing maximum240), exactly the existing40 periods per case /6 cases; existing facility40, amortisation2000, source text, IO and byte limits remain. Strict strings, maximum18 integer/6 fractional digits, 38-digit ROUND_HALF_EVEN arithmetic and all typed refusals remain. No new dependency, database schema, wire schema or vendor schema is required.

## Equations, result shape and provenance

In selected mode let H be the shared actual debt-cash bridge in the first period, otherwise zero, and P the CP-4 future aggregate principal. With the earlier design's E/O/R/C movements:

```text
future_net_debt_cash = issuance − optional_repayment − P
net_debt_cash = H + future_net_debt_cash
financing_investing = net_debt_cash − acquisitions_disposals
FCF = cfo − capex − cash_interest − cash_taxes
cash_close = cash_open + FCF − distributions + financing_investing + E + O − R
debt_close = debt_open + net_debt_cash + pik + capitalised_interest + fx_perimeter + C
```

`cash_interest` and `cfo` still cover the entire annual period; full-year cash interest is an explicitly sourced CP-2G assumption including the actual-year portion, not mechanically added to H. H is principal cash only, not interest. Preserve the M9 CFO convention after financing-lease principal and before debt cash interest/taxes. Separate operating financing rent and other financing interest remain in their stated CFO bridge. Negative ending cash remains an unmet-funding position.

In selected results only, add top-level `projection_basis`; add row `financing.actual_debt_cash_movement`. Keep `financing.contractual_repayment` equal P, explicitly described as future aggregate principal in this mode; no duplicate principal output or cash use. The actual field is zero after year1 because the explicitly scoped request bridge cannot recur. Do not add dates/IDs to numeric row groups; calendar/owner context remains the accepted request. Existing period result identity stays unchanged. Absent-selector result bytes and all earlier accepted request shapes stay byte-exact.

Maintain existing required independent stated debt/cash closes and own-opening tolerance caps unchanged. `forecast_projection` still recomputes and requires complete exact accepted JSON. Every new leaf uses `_OWNERS` with `projection_basis: CP-2G`, `actuals: CP-1`, and existing periods/contractual mappings. Accepted CP-1 validation runs through `canonical._forecast_inputs` using bytes already available there; no SQL. No accepted old source is amended.

A shared pure owner-contract validator in `caos/methodology/forecast_debt_service.py` validates selected-mode calendars, historical account and opening against `Cp1Registers`. Both canonical acceptance/replay and direct Model projection callers use it. It uses historical_columns/statement_frame and actual facility anchors to verify the explicit opening period exists, accessible cash equals request cash, and request `debt_by_facility` equals the exact accepted included canonical opening stack by ID and signed carrying value. Foreign/excluded facilities keep existing definitions; do not synthesize a single total row. Require an exact same-footing supported opening, not any fallback. Canonical translates expected malformed input to HANDOFF_INCOMPLETE; pure request shape uses METHODOLOGY_INPUT_INVALID and direct Model contract validation uses HANDOFF_MALFORMED. Integrity and other typed refusals propagate.

## Native Model selected basis

Selected mode branches explicitly before native `_schedule`/`_interest` can determine primary totals. Its cash interest is minus the accepted full-period driver, debt_raised_net is H+issuance−optional_repayment−P, and primary opening/cash/debt/FCF/NCF match the host-recomputed CP-CF result. Existing equity/otherFI/restricted/carrying and explicit segment capabilities remain active. CP-CF's six-decimal money output is exact here because all cash/debt inputs are limited to six decimals and formulas are additive; do not round native facility-basis calculations differently.

For selected projected columns, facilities and debt rank subtotals, secured debt and secured ratios, projected RCF drawing/undrawn/liquidity, reference rate, weighted average rate and interest-bearing base are NOT_PROJECTED, with note `Aggregate cash debt-service forecast; instrument allocation not supplied`. Historical facility figures remain intact. There is no projected claim of assumed refinancing, secured allocation, rate mix or available undrawn liquidity. No second numeric facility charge is displayed: the existing historical terms remain visible as context, while projected instrument diagnostics are explicitly unprojected. Generic coverage using actual selected cash-interest total may remain numeric, labelled with the selected aggregate basis; it is not a weighted-rate diagnostic.

Expose total projected debt explicitly as `debt:unallocated`, equal total debt with the allocation note. The layout must honor that explicit cell instead of recomputing it from null instrument rows. Do not count null projected instruments as numeric zero outside the existing declared optional bridge semantics. Preserve meaningful `total_debt = unallocated debt` and aggregate debt/cash roll-forward checks. The existing facility weighted-interest check remains unchanged for old mode.

Add immutable expected selected-mode checks to the pure CreditModel assembly, derived from fresh `cash_flow_forecast(request)` rather than the output frame: column ID with expected primary interest, principal/net debt cash, debt/cash opening/closing, noncash change, FCF and NCF. `reconciliation_faults` compares each independently to the served Model and requires the selected mode's unprojected diagnostic contract. Tampering with primary cash interest alone, or changing cash and interest together to retain an internal cash bridge, must fail against accepted inputs. Missing/corrupted expected checks must fail for selected columns, identified through structured internal mode metadata, never free-text notes. An unavailable native rate is not used to bypass this new accepted-input equality check. No global checker, tolerance or old-mode gate is disabled.

## Honest sources, display and Book binding without wire changes

The current cell adapter resolves SourceRef markers only against CP-1. Extend internal `SourceRef` with default `module_id="CP-1"` and optional `request_pointer=None`; existing constructors stay valid. Carry an optional pointer→SourceRef mapping through ModelInputs/ProjectionInputs, built in the API adapter from the already accepted CP-CF request bindings and the matching owner's verified linked `source_facts`. Require exact owner, pointer assignment and quote equality; refuse missing or ambiguous matches rather than emit a fake citation. Historical CP-1 sources retain their current resolution. New source locators include owner and pointer, e.g. `CP-2G /drivers/0/cash_interest`, while citation uses the real underlying source UUID/document/page/coordinates and real owner's marker. Do not attach a CP-1 citation to a CP-2G value merely because C3 exists in both modules.

The wire stays `ModelSourceView(source_id, source_locator, citation)`. Generalize its docstrings and the Model read adapter's citation index to `(module_id, marker)`; no new endpoint/read/database query. Forecast source references propagate through existing cell arithmetic into derived values; selector, first-period historical bridge, CP-4 principal and CP-2G interest/movements remain distinguishable. Pure calculator callers may omit UI citations, but the accepted API/Book path must supply and resolve them. Preserve MODEL_SOURCES_MAX and visible truncation warnings.

Use exact note `Cash debt-service basis: accepted CP-CF aggregate forecast` on selected primary cells and a top-level Model limitation. This existing limitations channel appears in Model, Book issuer disclosure, API documents and static exported app pages. It is included in EntryFigures and thus snapshot/Add-to-Book binding without a new storage column. Show selector ownership and input derivation in the cell passport, with working evidence links. The frontend must not add a weighted-rate/deck sentence when projected wa_rate is null. Any pinned deck remains historical/run metadata; it is not represented as the source of selected projected interest. The basis note must survive Book storage/reload and the exported Model/Book pages. No dedicated spreadsheet/PDF/CSV exporter was found in the inspected Model/Book paths; this scope covers existing API and static app exports, not a newly invented export feature.

## Proof matrix and compatibility

Independent numeric example, USD millions:

```text
opening debt11784, cash887; H1 net debt cash−98; future principal55;
future issuance0, optional repayment0; carrying26;
cfo1800, capex400, cash_interest738, taxes50, distributions82;
acquisitions0, equity0, otherFI−24, restriction15.
FCF612; debt cash−153; NCF353; cash change338; cash close1225;
debt close11657. Carrying26 changes no cash; restriction15 changes no debt.
```

This is a synthetic answer key, not adopted economic assumptions. Base and Downside both receive H once in2026. With2027 principal114 and carrying26, debt becomes11569; with2028 principal767 and carrying26 it becomes10828. Repeat H incorrectly and the discrepancy98 must be detected. Tests verify no future issuance885, no future principal1038, no fictitious facility allocations and no repeating actual bridge.

Test absent selector exact old bytes; closed mode/null/unknown selectors; mutually exclusive schedules; empty/duplicate/oversized bridges and aggregate rows before numeric parse; exact signed−98 CP-1 account versus−983/−43/98; calendar starts/ends/day counts and leap years; invalid/non-first historical spans; equal actuals across cases; correct future-only rows; per-leaf CP1/CP2G/CP4 ownership and wrong-owner marker collisions; missing/withdrawn/tampered evidence; deterministic replay; both signs for future financing and noncash; independent residual boundaries under hostile Decimal contexts; Model equality to accepted CP-CF; primary and expected-check tampering; null secured/rate/facility diagnostics; unallocated-debt bridge; actual grid source drill-through; real Book Add/read/replay; retained snapshot basis label and source lineage; static exported app view.

The frozen `analyst-assumptions-proposal-v2.json/.md` remain proposals. Later v3 native-boundary evidence must explicitly adopt the selector, CP1 historical−98, CP4 future55/114/767, honest dated spans and future issuance/optional repayment zeros. Its H1+H2 full-year interest bridge and six-decimal normalization need independent verification. It cannot copy v2 metadata into a governed request or claim economic adoption by successful parsing.

## Integration and workflow

Amend current uncommitted cash_flow Task1 before its rewrite-tournament, so bounded parsing, calendar keys, actual bridge and aggregate principal are reviewed/tournamented once with the movement additions. Do not overwrite another writer's changes; the controller dispatches one fresh writer with exact expanded ownership. Then implement accepted owner validation, native primary totals/checks, and source/UI/Book integration in reviewed tasks. Every nontrivial changed function receives confidence-review, complete controller-run five-role rewrite-tournament, independent spec/adversarial review and personal controller checks before commit. Preserve all CLAUDE gates in one assigned database.

Host declarations and generated HOST_INTEGRITY_v1.json/host_pin.py must state this mode and ownership, regenerated by scripts/host_manifest.py. Vendor and bundle pin bytes stay unchanged. Preserve D34 baseline reproduction and proper prompt regeneration; old cash_flow/forecast goldens are not overwritten to mask differences. Run old source for old host identity. No artificial deck or live resource authorization is introduced.

## Brainstorming and self-review

- [x] Read current project contracts and new bounded review/diagnostics; confirmed actual net debt account/calendar in accepted CP-1 source.
- [x] No visual question requires a companion.
- [x] Clarifications resolved from controller brief and delegated user authority.
- [x] Three approaches compared; explicit aggregate basis selected.
- [x] Exact fields, owners, classifications, time spans, refusal boundaries, output shape and limits fixed.
- [x] Written design presented to controller before implementation; no commit by this author.
- [x] Self-review removed classification ambiguity and distinguished aggregate usefulness from missing instrument projections.
- [x] Transition to companion writing-plans document; existing controller dispatch workflow retained.

Not verified: implementation, focused/full tests or mandatory gates; source adoption/v3 mapping; authoritative future principal ownership; new-mode Model/source passport/Book/replay/export behavior; baseline regeneration; live provider operation, resource-window/spending authorization, deployment or forecast realization.

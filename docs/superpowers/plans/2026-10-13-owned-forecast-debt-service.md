# Owned Forecast Debt Service Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. AGENTS.md requires controller-only dispatch; implementation agents never delegate.

**Goal:** Let an explicitly owned CP-CF aggregate cash debt-service forecast drive native Model and Book totals, without inventing facility allocations or altering legacy behavior.

**Architecture:** Add a closed selector, CP-1 historical net debt bridge and CP-4 future aggregate principal schedule. Validate source/calendar/ownership from accepted upstream bytes; selected native projections use those cash totals with independent input-equality checks and unprojected facility diagnostics. Resolve projected source passports through owner-scoped citations in the existing wire shape.

**Tech Stack:** Existing Python >=3.13,<3.14, Decimal38, pytest, FastAPI typed reads and React; no new dependencies, database/wire/vendor schema or store IO.

## Global Constraints

Worktree **W** is `/Users/ericguei/.codex/worktrees/forecast-cash-movements/caos-databricks`. Paths below are relative to W; the controller expands all paths in dispatched ownership. Report directory **R** is W `/.superpowers/sdd/forecast-cash-movements/`. Required design is W `/docs/superpowers/specs/2026-10-13-owned-forecast-debt-service-design.md` together with the companion cash-movements design.

- Strict strings, maximum18 integer/6 fractional digits, 38-digit ROUND_HALF_EVEN arithmetic and all typed refusals remain.
- All collections are bounded before the first Decimal parse: at most one bridge, aggregate rows no more than requested pairs (existing maximum240), exactly the existing40 periods per case /6 cases; existing facility40, amortisation2000, source text, IO and byte limits remain.
- No new dependency, database schema, wire schema or vendor schema is required.
- Original cash guard 35 and the expired window remain.
- No artificial deck or live resource authorization is introduced.
- Controller review precedes code and the controller owns commits.
- Old accepted artifacts and host identities stay immutable; absent mode means exact legacy behavior. Preserve every CLAUDE.md gate, same owner binding, HMAC, source withdrawal and approval digests.
- One implementation writer at a time. Fresh mx-invariants (`gpt-6-astra`, high) for money/ownership implementation; fresh mx-precise task review and mx-adversary review afterward. Every nontrivial changed function needs confidence-review and the complete controller-run five-role rewrite-tournament. Controller personally verifies focused tests, independent invariants and callers. Pending report says `Awaiting controller rewrite-tournament`; all reports end `Not verified:`.

---

### Task A: Amend current pure forecast Task1 before its tournament

**Owned files:** `caos/calculators/cash_flow.py`, `tests/test_cash_flow_forecast.py`, R `debt-service-task-a.md`. Preserve the current writer's finished uncommitted movement additions; controller hands off that exact diff before a fresh writer starts.
**Consumes:** existing `cash_flow_forecast(request)` / `forecast_bytes(request)` and newly added optional movement fields.
**Produces:** same APIs, selected mode structure and numeric results from the design.

- [ ] Add a new independent synthetic selected-mode request helper locally in the assigned test file. Use two or three annual BASE/DOWNSIDE periods, opening debt11784/cash887 and this first-year block, alongside every existing required movement:

```json
{
  "projection_basis": "OWNED_CASH_DEBT_SERVICE",
  "actuals": {"debt_cash_movements": [
    {"period_id": "FY2026", "historical_period_id": "H1_2026", "amount": "-98"}
  ]},
  "contractual": {"amortisation": [], "aggregate_amortisation": [
    {"case": "BASE", "period_id": "FY2026", "start_date": "2026-07-01", "end_date": "2026-12-31", "amount": "55"}
  ]}
}
```

This fragment is not a whole request. Test helper supplies exact per-case rows, full calendar spans on periods, full driver values, exact stated closes and signed opening facilities. Use cfo1800/capex400/interest738/taxes50/distributions82/otherFI−24/restriction15/carrying26, acquisitions/equity/future issuance/optional repayment/PIK/capitalized interest/FX zero. Assert FCF612, net debt cash−153, NCF353, cash1225 and debt11657 from arithmetic independently stated in the test.

- [ ] Run `uv run pytest --no-cov tests/test_cash_flow_forecast.py -q`; selected keys initially refuse. Record failing names.
- [ ] Extend `_enforce_work_factor` before Decimal construction: close selector/actuals/aggregate/calendar shapes, array caps and mode exclusions. Existing per-facility amortisation must be an explicit empty list in selected mode. Reserve all new structural keys for selected mode only. Unknown selector/null/bool/unknown objects refuse.
- [ ] Parse selected calendars with ISO dates and exact canonical spelling; require full calendar years, fiscal year/day count equality, consecutive years and common first-period identity across cases. Parse one shared first-year bridge and exactly one aggregate row per pair. Owner-dependent YTD dates are validated in Task B; pure input validation can enforce each aggregate span lies in its projected year and all first-year scenario spans agree. Do not invent missing span or principal values.
- [ ] Extend `_Inputs` with explicit mode, per-pair aggregate principal and shared first-period historical debt cash. In `_project_period` use the following additional terms, preserving old branch arithmetic/output when absent:

```python
# Within the existing isolated context; values already parsed and bounded.
net_debt_cash = historical_debt_cash + issuance - optional_repayment - principal
closing_debt = opening_debt + net_debt_cash + pik + capitalised_interest + fx_perimeter + carrying
financing_investing = net_debt_cash - acquisitions_disposals
closing_cash = opening_cash + fcf - distributions + financing_investing + equity + other - restricted
```

Emit top-level selector and row `financing.actual_debt_cash_movement` only in selected mode; existing `financing.contractual_repayment` is future principal. Keep result period identity unchanged rather than copying request calendar strings into numeric groups. H applies once to first projected period of each case, never to later years.
- [ ] Test exact signs, independent zero/explicit-empty rules, bridge duplication/repetition, aggregate mixed with per-facility rows, unknown/duplicate pair, bounds before parse, annual/leap/date errors, and signed opening COST−8. Under hostile ambient Decimal context, within/outside existing reconciliation boundaries must behave unchanged. With future principal114 then767 and carrying26 each year, independently assert debt11569 then10828. A repeated−98 must fail the intended stated closes.
- [ ] Run `uv run pytest --no-cov tests/test_cash_flow_forecast.py tests/parity/test_cash_flow.py -q`; expect PASS with old golden bytes unchanged. Controller completes original movement Task1 plus this amendment's confidence/tournament/reviews once on the final actual functions, then commits the combined pure contract. Generate temporary host pins only through the generator if focused integrity tests require them; final authority text/pins belong to Task E.

### Task B: Validate CP-1 history, opening and future CP-4 span

**Owned files:** new `caos/methodology/forecast_debt_service.py`; `caos/methodology/forecast.py`; `caos/methodology/canonical.py`; new `tests/test_forecast_debt_service.py`; `tests/test_forecast_handoff.py`; R `debt-service-task-b.md`.
**Interfaces:**

```python
# Pure module; no API or store imports.
def validate_owned_debt_service(request: Mapping[str, Any], regs: Cp1Registers) -> None:
    """No-op for legacy; HANDOFF_MALFORMED for an invalid selected owner contract."""

# Adapter in methodology/forecast.py; VendorContract is existing type.
def validate_debt_service_mapping(contract: VendorContract, markdown: bytes, owner: bytes) -> None:
    """Accepted CP-1 adapter; expected bad input becomes HANDOFF_INCOMPLETE."""
```

These are exact interfaces, not implementation stubs to commit. Required imports are collections.abc.Mapping, typing.Any and existing model_inputs.Cp1Registers.

- [ ] Add tests against actual typed register structure: an H1 YTD `net_debt_issue_repay=-98`, prior FY opening cash887 and signed facility stack11784, CP-4 future spans after June30. Assert−983,−43,+98 refuse; wrong period type, missing account, unavailable value, footings, dates, first-year placement and omitted actuals list refuse.
- [ ] Run `uv run pytest --no-cov tests/test_forecast_debt_service.py -q`; initial import fails until implementation exists.
- [ ] Implement no-mode early return. For selected mode parse the existing registers, require exact historical FY column identity and matching opening figures/facility IDs/amounts using existing historical statements and anchor rules. No PE fallback; no synthetic total facility. Validate dated YTD starts at first-year January1, ends before yearend, exact account equality, all relevant unit/currency/accounting/perimeter equality and complete calendar. Match aggregate starts to day after actuals end and later January1, ends to each projected December31. No SQL.
- [ ] Add `_OWNERS` entries for `projection_basis: CP-2G` and `actuals: CP-1`; retain periods CP-1 and contractual CP-4. Adapt accepted CP-1 parsing through `handoff_tables`/`cp1_registers` and invoke from canonical `_forecast_inputs`. Reuse already accepted bytes, bounded table parser and owner citations; no added IO. Match exact assignment lines for all selector/calendar/actual/aggregate leaves and explicit empty arrays.
- [ ] Add wrong-owner and same-marker-collision tests, changed bridge/amount/calendar with unchanged quote, missing owner, duplicate source attribution, hidden nonfinite values and replay tampering. Leave source withdrawal/HMAC/dependency gates unchanged.
- [ ] Run `uv run pytest --no-cov tests/test_forecast_debt_service.py tests/test_forecast_handoff.py tests/parity/test_forecast.py -q`. Controller runs the selected canonical acceptance/replay fixture tests with assigned isolated DB. Confidence-review, tournament, fresh spec/Astra review and controller-owned commit follow.

### Task C: Primary aggregate Model and mode-specific invariant checks

**Owned files:** `caos/calculators/credit_model/projection.py`; `caos/calculators/credit_model/assemble.py`; `caos/calculators/credit_model/layout.py`; `tests/test_credit_model_projection.py`; `tests/test_credit_model_assemble.py`; new `tests/test_credit_model_owned_debt_service.py`; R `debt-service-task-c.md`. The existing assembly test file was verified; the new dedicated file carries the selected-basis cases.
**Consumes:** Task B validator and Task A complete result, existing Cell/Frame/ModelInputs/ProjectionInputs.
**Produces:** unchanged public projection result shape; CreditModel gains default internal structured mode and immutable expected-check data, with no wire change.

- [ ] Add tests proving selected mode produces numeric cash interest−738 and debt11657/cash1225 even when no deck and native implied interest are unavailable; absent mode retains current unavailable interest and every old note/figure. New assertions fail before implementation.
- [ ] Invoke pure selected owner validation before projection, then dispatch an explicit owned-mode year path. Read accepted cash-interest/principal/actuals once; primary totals must equal recomputed `cash_flow_forecast(request)` rather than independently pricing facilities. Native `_schedule` and `_interest` retain their old behavior and tests in legacy mode.
- [ ] Set projected facilities/rank subtotals, secured debt/secured metrics, RCF drawing/undrawn/liquidity and reference/weighted rates/interest base to NOT_PROJECTED with the exact allocation note. Set explicit `debt:unallocated` to total projected debt and make layout honor that explicit value. Historical cells/terms stay unchanged. Preserve numeric aggregate cash-interest coverage with the selected basis note.
- [ ] Add internal frozen expected-check records to CreditModel, generated from original request via pure forecast calculator at assembly. Their mode marker must be structured and mandatory when selected. Compare interest, debt/cash opens/closes, net debt cash, noncash, FCF/NCF and diagnostic absence in `reconciliation_faults`. Keep `_interest_closes` unchanged for facility mode. Do not replace a positive invariant with only null fields.

```text
Required independent tests:
primary interest changed alone -> owned-input check fails;
interest and cash changed together -> owned-input check still fails;
expected-check record absent for selected column -> fails;
wrong debt:unallocated -> total-debt/owned-input check fails;
numeric secured debt or wa_rate introduced -> selected diagnostic check fails;
old facility interest perturbation -> existing weighted-rate check still fails.
```

- [ ] Verify first-year shared actual−98 once per case, no reuse in2027/28; no assumed-refinancing note on selected projected rows; complete Model primary equality to CP-CF, future principal correctly owned, old cells byte/value parity and precision isolation.
- [ ] Run `uv run pytest --no-cov tests/test_credit_model_projection.py tests/test_credit_model_assemble.py tests/test_credit_model_owned_debt_service.py -q`. Controller verifies independent arithmetic and actual diff, then confidence/tournament/reviews and commit. No instrument allocation is inferred to make a bridge close.

### Task D: Owner-specific source passports and durable basis disclosure

**Owned files:** `caos/calculators/credit_model/frame.py`; `caos/calculators/credit_model/assemble.py`; `caos/calculators/credit_model/projection.py`; `caos/api/reads/model.py`; `caos/api/wire.py` docstrings only; `frontend/src/sections/model/grid.ts`; `frontend/src/sections/model/ModelSection.tsx` only if existing notes do not suffice; `frontend/src/sections/book/IssuerHistory.tsx` only if stored notes are not visible; `tests/test_model_section.py`; `tests/test_book_section.py`; `frontend/tests/unit/model.test.tsx`; `frontend/tests/unit/book.test.tsx`; R `debt-service-task-d.md`.
**Consumes:** existing accepted AnalysisBody handoffs/source_facts and forecast_inputs bindings; no new fetch/query.
**Produces:** existing ModelSourceView wire shape with owner-correct citations; selected basis in existing notes/limitations and Book snapshot.

- [ ] Write tests with CP-1 C3, CP-2G C3 and CP-4 C3 deliberately naming different real source facts. Interest source must resolve CP-2G, historical−98 CP-1, principal55 CP-4. Each must carry its exact pointer and owner in locator, underlying true source UUID and complete matching linked quote. Swapping one marker/quote must refuse, not fall back to CP-1.
- [ ] Extend internal `SourceRef` with `module_id: str = "CP-1"` and `request_pointer: str | None = None`; preserve old constructor behavior. Add `forecast_sources: Mapping[str, SourceRef] | None = None` to ModelInputs and ProjectionInputs, passing it explicitly through assembly. No import of API CitationView into pure modules.
- [ ] In API model adapter, derive this map from accepted CP-CF exact bindings and owner source_facts. Index legacy markers by `(module_id, marker)`, resolve matching quote uniquely and require `linked`. SourceRef stores real source ID/locator/text plus owner/pointer, not a copied CP-1 source. Context assigns each driver/bridge/principal/selector reference to appropriate cells; existing arithmetic propagates references under existing source caps. API enforces attribution in accepted path while pure tests may omit presentation refs.
- [ ] Show `Cash debt-service basis: accepted CP-CF aggregate forecast` in Model notes/limitations and source passport. Explicit allocation note appears for missing instruments/rates/secured data. Inspect frontend `passportOfCell`: weighted-rate/deck prose must remain absent when wa_rate is null. Retain actual source citations and show owner/pointer even when citation is present (currently only unlocated sources are echoed into derivation).
- [ ] Exercise actual API Model grid, drill-through, cloned/read-only grid and real Add to Book on assigned DB. The stored EntryFigures limitations must include the basis and allocation notes; snapshot hashes differ if those notes/basis differ. Reload Book and replay accepted chain; verify figures equal served snapshot and source withdrawal/tampering refuses. No changes to store schema or snapshot algorithm are needed because it already includes limitations and accepted artifact digests.
- [ ] Run `CAOS_REQUIRE_POSTGRES=1 uv run pytest --no-cov tests/test_model_section.py tests/test_book_section.py -q` with the controller-assigned URL. Run `npm --prefix frontend run test -- tests/unit/model.test.tsx tests/unit/book.test.tsx`, plus existing frontend typecheck/build scripts. The inspected test script is `vitest run --mode demo`; do not install anything. Expect source owners, pointer labels and mode notes visible, no weighted-rate claim. Existing wire keys remain unchanged.
- [ ] Confirm `READ_IO`, `IO_BUDGET`, BLOB_BUDGET, Model source caps and visible truncation remain unchanged using existing budget tests. Confidence-review, changed-function tournaments, fresh source-read-only reviews and controller verification precede commit.

### Task E: Declare capability, regenerate authority and integrate proof inputs

**Owned files:** `icm/stages/cp-cf/references/SKILL.md`; `icm/shared/prompt/forecast_extension.md`; generated `icm/HOST_INTEGRITY_v1.json` and `caos/methodology/host_pin.py`; legitimately affected prompt/route goldens under `tests/parity/golden/`; `tests/test_forecast_extension.py`; `docs/rebuild/decisions.md` only controller-assigned numbering; R `debt-service-task-e.md`. Fold this into the original feature's authority task, not a second conflicting regeneration.

- [ ] State exact selector, CP-1 actual/calendar ownership, CP-4 future aggregate schedule, future-only issuance/optional driver semantics, full-year interest, and separate instrument limitations in host instructions. Existing42 CP-2G financial/growth rows remain; no vendor IDs are added. No false numeric default or source assignment is invented.
- [ ] Run `uv run python scripts/host_manifest.py`; verify bundle_pin.py/vendor unchanged. Recover and reproduce D34 pre-change prompt/forecast baseline before regenerating legitimately changed prompt/route surfaces. Preserve every absent-field cash_flow and forecast golden byte. Record actual paths/commands/hashes; unavailable legacy reproduction is an evidenced blocker, not permission to write new outputs as legacy expectations.
- [ ] Run `uv run pytest --no-cov tests/test_forecast_extension.py tests/test_forecast_route.py tests/parity/test_cash_flow.py tests/parity/test_forecast.py tests/parity/test_prompt.py tests/parity/test_routes.py -q`. Verify stale host pins, modified authority and altered request bindings refuse.
- [ ] Controller runs all CLAUDE mandatory gates with one assigned isolated database and no overlapping suite. Existing static app export scripts must retain Model/Book disclosure; no new PDF/CSV/spreadsheet export is promised. Build both required app exports and inspect their tested mode-rendering path.
- [ ] Commission separate v3 native-boundary source mapping from frozen v2 assumptions: FY2025 actual opening, shared H1_2026−98, future CP4 principal55/114/767 and spans, CP2G future issuance/optional0, full annual738/750/680 and Downside797.68/869.36/799.36 interest, earlier honest movements/adjusted EBITDA/segment amounts and six-decimal rounding. V2 metadata remains unadopted proposal data. Independent review must check every source assignment before admission or governed replay.
- [ ] Only after all implementation/review/gates and necessary source/resource authority does the controller execute the original full ten-node proof, native Model, real Book Add and replay. This plan supplies no live spending/window extension. No completion claim based solely on synthetic fixtures.

## Self-review and handoff

- [x] Contract names/signs/owners match companion design; no historical repayment relabelled as optional or future contractual.
- [x] CP-1 net−98 and actual calendar exist in inspected accepted source; no gross fallback needed.
- [x] Integration order avoids repeating Task1 tournament before pure contract amendment.
- [x] Every mode has positive checks: old weighted interest and new accepted aggregate identities coexist.
- [x] Pure source types avoid API imports; owner-specific citations preserve wire shape and IO bounds.
- [x] Absent-mode bytes, no fake facility allocation, Book snapshot disclosure and existing export paths are covered.
- [x] Implementation proceeds through existing controller dispatch; no new user confirmation is requested.

Not verified: implementation, precise future source adoption, v3 mapping, test/gate execution, actual UI/Book/replay/export behavior, authority/golden regeneration, live resource/spending approval, complete ten-node proof, deployment or forecast realization.

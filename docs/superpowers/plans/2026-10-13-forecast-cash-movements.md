# Forecast Cash Movements Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. AGENTS.md overrides nested delegation: only the controller dispatches, and implementation agents never delegate.

**Goal:** Support explicitly owned optional cash/debt movements and segment revenue without changing old absent-field results.

**Architecture:** Extend the host CP-CF driver contract, validate added leaves through existing owner bindings and accepted CP-1 registers, then consume them in the native Model. Keep pure shape/arithmetic validation separate from CP-1 identity/perimeter validation. Use existing accepted upstream bytes and tables; add no SQL.

**Tech Stack:** Python >=3.13,<3.14, Decimal precision 38, pytest, existing handoff/model types; no new dependency.

## Global Constraints

Worktree `/Users/ericguei/.codex/worktrees/forecast-cash-movements/caos-databricks`; base `e312e3a1f2ba3a853ef734e9e461749f4a2c924c`. Every relative path below is rooted at this exact worktree, and every dispatch brief must expand it to an absolute path. Design: `docs/superpowers/specs/2026-10-13-forecast-cash-movements-design.md`.

- Money retains at most 18 integer and 6 fractional digits, current length bounds and Decimal precision 38 / ROUND_HALF_EVEN. No float arithmetic.
- Existing handoff table/byte caps remain in force.
- Existing required movements remain required and retain existing unavailable propagation.
- No vendor edit, dependency or database migration is required.
- Historical d92 worktrees, accepted cases and evidence remain immutable. Never repin an old run to this host.
- The original 35 cash guard and expired window remain.
- No provider call or paid/live proof is authorized by this document.
- The controller owns review and commits. Each task is assigned to a fresh mx-invariants (`gpt-6-astra`, high) implementation agent because it handles money or ownership, followed by fresh mx-precise spec/quality and mx-adversary reviews. Reviewers are source read-only. Only one implementation writer runs at a time. Each report is under `.superpowers/sdd/forecast-cash-movements/` and ends with `Not verified:`.
- Every task includes confidence-review, actual diff and changed-function/caller handoff. The controller runs all five rewrite-tournament roles for nontrivial functions, assigns a fresh writer to apply a winner, and personally verifies focused tests, invariants and caller contracts before committing. A pending report says `Awaiting controller rewrite-tournament`.
- Every CLAUDE.md gate remains required at final integration, in one controller-assigned isolated test database. Do not run an unassigned full suite or another chat's database.

Controller execution amendment: the host checks the calculator's exact bytes even in Task 1's existing focused tests. After each completed calculator revision, the assigned writer may regenerate `icm/HOST_INTEGRITY_v1.json` and `caos/methodology/host_pin.py` with `scripts/host_manifest.py`, proving `bundle_pin.py` unchanged. This advances only Task 4's generated code-identity step; capability wording and final authority/parity verification remain Task 4. Never bypass the integrity check or repin an old run. Task commits below are proposed messages; source commits wait until required reviews, tournaments and mandatory gates pass.

---

## File responsibilities

`caos/calculators/cash_flow.py`: optional driver shape, numeric bounds, arithmetic and conditional output. `caos/methodology/forecast.py`: financial row mapping and accepted CP-1 adapter. New `caos/methodology/forecast_segments.py`: pure shared CP-1 map validation, independent of canonical/SQL/API. `caos/methodology/canonical.py`: invoke added owner check using its existing context. `caos/calculators/credit_model/projection.py`: explicit revenue/cash/debt frame values. Host skill/prompt: describe the exact owned interface. Tests use existing forecast/model/canonical fixtures without replacing old fixtures globally. Generated manifest/pin/goldens are updated only in the final authority task.

### Task 1: Optional movement and map shape in pure CP-CF

**Own:** `caos/calculators/cash_flow.py`; `tests/test_cash_flow_forecast.py`; report `.superpowers/sdd/forecast-cash-movements/task-1.md`.
**Consumes:** `cash_flow_forecast(request: Mapping[str, Any]) -> dict[str, Any]`; existing `forecast_request()` fixture.
**Produces:** same public signatures, optional fields specified in design, `MAX_FORECAST_SEGMENTS = 40`.

- [ ] Add independent signed-movement tests, including this concrete answer key (all other driver rows remain unchanged):

```python
def test_explicit_cash_and_carrying_movements_are_distinct() -> None:
    request = forecast_request()
    request["periods"] = request["periods"][:1]
    request["drivers"] = request["drivers"][:1]
    request["contractual"]["amortisation"] = [
        row for row in request["contractual"]["amortisation"]
        if (row["case"], row["period_id"])
        == (request["periods"][0]["case"], request["periods"][0]["period_id"])
    ]
    request["drivers"][0].update(
        net_equity_issue_repay="5", other_investing_financing="-24",
        restricted_cash_change="15", carrying_value_change="26",
        stated_closing_cash="92", stated_closing_debt="1026",
    )
    result = cash_flow_forecast(request)
    assert result["status"] == "complete"
    row = result["rows"][0]
    assert row["cash"]["closing"] == "92.000000"
    assert row["debt"]["closing"] == "1026.000000"
    assert row["fcf"] == "45.000000"
    assert row["financing"]["financing_investing"] == "-15.000000"
```

- [ ] Run `uv run pytest --no-cov tests/test_cash_flow_forecast.py -q`; new-field tests initially refuse with METHODOLOGY_INPUT_INVALID.
- [ ] Extend the driver optional key set, keeping required `_MOVEMENTS` unchanged. Parse every present scalar with `_decimal(..., signed=True)`; reject explicit null. Before any money parse, validate map type, nonempty size ≤40, safe bounded keys and scalar leaf shape. Parse map amounts signed, including negative corporate elimination, then require exact sum equals revenue. Preserve ordinary missing-required-driver behavior.

```python
# Semantic constants and arithmetic; preserve current public signatures.
_OPTIONAL_MOVEMENTS = (
    "net_equity_issue_repay", "other_investing_financing",
    "restricted_cash_change", "carrying_value_change",
)
# Within the existing isolated Decimal context:
debt += moves.get("carrying_value_change", Decimal(0))
cash += (
    moves.get("net_equity_issue_repay", Decimal(0))
    + moves.get("other_investing_financing", Decimal(0))
    - moves.get("restricted_cash_change", Decimal(0))
)
# Add only present fields at the result locations fixed by the design.
```

- [ ] Parameterize both signs, explicit zero/absence, null/bool/float/exponent/huge strings, unknown fields, maps of 0/40/41 entries, unsafe keys and exact/off-by-0.000001 sums. Prove malformed maps are checked before numeric work, including non-READY rows. Independently test restricted release, noncash debt, two cases over two years and hostile Decimal traps/context. Preserve own-opening tolerance tests at both sides of each boundary.
- [ ] Run `uv run pytest --no-cov tests/test_cash_flow_forecast.py tests/parity/test_cash_flow.py -q`. Expect all pass and committed old cash_flow parity bytes unchanged. Do not regenerate them.
- [ ] Confidence review and controller tournament/review/verification, then controller commit `feat(forecast): support explicit cash and carrying movements`.

### Task 2: Bind extensions to accepted owner contracts

**Own:** `caos/methodology/forecast.py`; new `caos/methodology/forecast_segments.py`; `caos/methodology/canonical.py`; `tests/test_forecast_handoff.py`; new `tests/test_forecast_segments.py`; `tests/test_canonical_execution.py` only for the new boundary case; report `task-2.md` under the report directory.
**Consumes:** Task 1 request fields; `handoff_tables(contract, markdown)`, `cp1_registers(tables)`, `Cp1Registers`, `historical_columns(regs)` and existing linked citation bindings.
**Produces:** the following exact new interfaces:

```python
# caos/methodology/forecast_segments.py
from collections.abc import Mapping
from typing import Any
from caos.methodology.model_inputs import Cp1Registers

def validate_segment_revenue(
    request: Mapping[str, Any], regs: Cp1Registers
) -> None:
    """Refuse invalid explicit segment forecasts with HANDOFF_MALFORMED."""

# caos/methodology/forecast.py
# VendorContract already exists in this module.
def validate_segment_mapping(
    contract: VendorContract, markdown: bytes, owner: bytes
) -> None:
    """Validate explicit maps against accepted CP-1; HANDOFF_INCOMPLETE."""
```

The displayed declarations are interface contracts, not permission to commit unimplemented functions.

- [ ] Add tests proving direct-signed equity/otherFI map exactly; absent fields still demand READY zero; NOT_APPLICABLE/null/missing/duplicate/wrong-unit/opposite-sign rows refuse. Preserve negated acquisition/dividend tests. Run `uv run pytest --no-cov tests/test_forecast_handoff.py -q` and record the new failures.
- [ ] Change `_DRIVER_ROWS` to map the two optional fields by name. In `_faults`, use Decimal zero only when those explicitly optional fields are absent; required mappings continue indexed access. `_row_fault` error text must distinguish direct equality from negated equality. Never coerce an explicitly bad field to zero.

```python
_DriverRow("net_equity_issue_repay", "net_equity_issue_repay", negated=False)
_DriverRow("other_investing_financing", "other_investing_financing", negated=False)
# Missing optional fields preserve the old READY-zero restriction;
# required fields do not use this default.
```

- [ ] Implement the shared segment validator with a no-map fast return, shared numeric/key validation from Task 1 as needed, strict millions/currency/perimeter checks, existing latest-FY selection, finite complete base segment coverage, known period references and consistent segment types. Require full known ID set and corporate values exactly equal base. Recheck exact consolidated sum under an explicit Decimal context. Do not weaken existing sparse-history behavior for old requests.
- [ ] Implement the adapter using already accepted CP-1 Markdown, `handoff_tables` and `cp1_registers`. If table read returns a reason, refuse. Translate only expected typed malformed-input refusals at this owner boundary. Invoke it from `canonical._forecast_inputs` after binding and financial mapping checks with `upstream["CP-1"]`. No SQL or extra store read.
- [ ] New segment tests use `credit_model_fixture.example_registers()` and replace individual fields through `dataclasses.replace`; verify unknown/omitted IDs, absent latest-FY segment, conflicting type, changed CORP, wrong currency/unit/perimeter, exact sum, unsafe IDs and nonuniform same-slot growth. Use a real accepted-markdown fixture to prove wrong CP-1 ownership/refused CP-2G leaf citation and tampering fail at canonical acceptance and replay. Plain object quotes must not satisfy scalar bindings.
- [ ] Run `uv run pytest --no-cov tests/test_forecast_handoff.py tests/test_forecast_segments.py tests/parity/test_forecast.py -q`. Run new canonical test with controller-provided `CAOS_TEST_POSTGRES_URL` and `CAOS_REQUIRE_POSTGRES=1`. Expect all pass with old forecast goldens unchanged.
- [ ] Confidence review and full controller tournament/spec/adversarial verification, then controller commit `feat(forecast): validate owned segment and financial inputs`.

### Task 3: Native Model consumes the explicit assumptions

**Own:** `caos/calculators/credit_model/projection.py`; `tests/test_credit_model_projection.py`; `tests/test_model_section.py`; `tests/test_book_section.py`; report `task-3.md`.
**Consumes:** validated optional driver fields, `validate_segment_revenue(request, regs)`, `ProjectionInputs`; existing `Cell`, `calc`, `CONTEXT` and accepted-forecast API source lineage.
**Produces:** unchanged `projection(inputs: ProjectionInputs) -> tuple[tuple[Column, ...], Frame]` signature with conditional new movement cells and explicit `bu:` values.

- [ ] Add a projection test that changes only first-year equity by +5, otherFI by −24, restriction by +15 and carrying by +26. Independently assert cash changes −34 and debt +26 relative to old output, while FCF and interest remain identical for that first year. Assert no fake CP-1 source reference is created. Run `uv run pytest --no-cov tests/test_credit_model_projection.py -q`; new assertions must fail before implementation.
- [ ] Invoke shared map validation before projected figures can be withheld for a bad base. In `_revenue`, present maps produce explicit PROJECTED segment cells and a CP-2G-assumption note; absent maps preserve `_grown` exactly. Corporate must already be validated, not overwritten to silently fix bad input.
- [ ] Extend `_cash_flow` and `_year` with the following frame algebra. Use `_driver`/existing typed cells for present inputs and preserve old absent equity note, absent otherFI shape and old notes.

```text
equity_raised_net = net_equity_issue_repay
other_investing_financing = other_investing_financing
ncf = fcf + acquisitions_net + debt_raised_net + equity_raised_net
      + dividends + other_investing_financing
fx_and_other_cash = −restricted_cash_change
cash_closing = cash_opening + ncf + fx_and_other_cash
debt_non_cash = pik + capitalised_interest + fx_perimeter + carrying_value_change
```

- [ ] Verify explicit zero preserves the new explanatory cells; absent fields preserve all original cells/notes. Test two-year/case state chaining, negative funding balances, exact segment sum, differing DIG/MB-like same-slot forecasts, corporate base held flat and hostile ambient Decimal context. Keep existing incomplete-FY withholding and rate-deck/facility tests.
- [ ] Add Model-section and Book-section tests through their existing real route fixtures: serve the changed Model grid, follow accepted CP-CF bindings to CP-2G quotes, inspect source-linked drill-through, clone/read the model, Add to Book, then assert Book cash/debt/forecast metric figures match the served accepted snapshot. The real line IDs and existing helpers are discovered within those assigned tests; do not invent fixture APIs. Check changed-source/tampered-artifact reads refuse. No current-source substitution and no historical CP-1 citation attached to new CP-2G amount.
- [ ] Run `uv run pytest --no-cov tests/test_credit_model_projection.py -q`, then `CAOS_REQUIRE_POSTGRES=1 uv run pytest --no-cov tests/test_model_section.py tests/test_book_section.py -q` with the assigned URL. If source drill-through needs an API schema or API code change, report BLOCKED with the failing test and exact missing behavior to the controller before editing outside ownership.
- [ ] Confidence review, five-role tournament, fresh spec/Astra review and controller checks, then controller commit `feat(model): project owned cash movements and segment revenue`.

### Task 4: Declare, pin and verify the capability

**Own:** `icm/stages/cp-cf/references/SKILL.md`; `icm/shared/prompt/forecast_extension.md`; generated `icm/HOST_INTEGRITY_v1.json`, `caos/methodology/host_pin.py`; relevant files under `tests/parity/golden/prompt/` and `tests/parity/golden/routes/`; `tests/test_forecast_extension.py`; `docs/rebuild/decisions.md`; `docs/rebuild/next.md` only for actual remaining scope; report `task-4.md`.
**Consumes:** Tasks 1–3 finished and reviewed, existing D34 mirror procedure and `scripts/host_manifest.py`.
**Produces:** accurate delivered host authority, generated new host identity, deterministic compatibility and integration evidence.

- [ ] Replace the obsolete unconditional READY-zero instruction with the precise absent-field rule; document signed E/O, restricted transfer, noncash carrying and exact segment map semantics. Require every explicit leaf assignment to cite its owner and retain all existing vendor vocabulary, 42 rows and approvals. State that explicit segment levels replace slot multiplication only for that driver, with corporate unchanged.
- [ ] Generate host authority with `uv run python scripts/host_manifest.py`. Verify bundle_pin.py is byte-unchanged and vendor integrity remains untouched. Do not hand-edit hashes.
- [ ] Reproduce pre-change prompt and forecast goldens using the recovered D34 legacy mirror as documented in decisions.md, then regenerate only legitimately affected prompt/route artifacts by that verified procedure. Record the exact mirror path, commands, baseline reproduction, changed cases and hashes in task-4.md. If the legacy environment is unavailable, report the exact failure; do not generate purported legacy expectations from the new implementation. Cash_flow and forecast absent-field goldens stay unchanged.
- [ ] Run `uv run pytest --no-cov tests/test_forecast_extension.py tests/test_forecast_route.py tests/parity/test_prompt.py tests/parity/test_routes.py tests/parity/test_forecast.py tests/parity/test_cash_flow.py -q`. Expect old bytes preserved, new manifest verified, stale pins and modified authority refused. Register exact new scope and confirmed fixes in decisions.md under controller-assigned numbering; no independent D/F/N claims.
- [ ] Controller reruns focused task tests and checks cash, debt and segment arithmetic against independent fixtures and current callers. Fresh task review and sensitive-code adversarial review inspect the actual final diff. Docs/generated-only task skips tournament; any function repair re-enters its required tournament.
- [ ] Controller executes every gate listed in CLAUDE.md, using one assigned database and the existing runner/stub procedures. Preserve full command/output logs; no suppression budget or invariant changes. Commit only when mandatory results and rewrite tournaments are complete.

## Larger proof handoff and stop rules

After this feature passes, separately revised analyst assumptions must show adjusted EBITDA, post-financing-principal CFO, fixed corporate elimination and distinct operating-segment revenue. Normalize to six decimals at the request boundary with explicit ROUND_HALF_EVEN and independently recalculate stated closes. Preserve historical evidence and author actual source assignments for every new leaf.

The controller must then establish facility/rate-deck/calendar equivalence before claiming a useful native Model: inspect the FY2026 full-year opening, actual H1 plus proposed H2, scheduled principal and FY2028 maturity treatment. This feature intentionally does not change facility refinancing or annual-interest policy. A failure is a concrete new scope decision, not permission to hide it in carrying/FX/otherFI. The ten-node/real Book/replay proof remains incomplete until that check, authority/pin compatibility and any live resource authorization are satisfied.

## Plan self-review

- [x] Every design requirement maps to Tasks 1–4 or the explicit later-proof boundary.
- [x] Exact field names, sign rules, result locations and new helper interfaces agree with the design.
- [x] Changed files and existing test paths were inspected; no vendor/schema/dependency change proposed.
- [x] Controller-only commits, one writer, confidence-review, tournament and fresh reviews retained.
- [x] Commands record expected failure/pass and the distinction between pure tests and assigned-DB tests.
- [x] Execution uses the existing controller dispatch workflow; no new execution-choice pause is needed.

Not verified: code implementation or tests, gate results, recovered legacy mirror availability, host regeneration, changed-host replay, source admission, facility/deck/calendar equivalence, actual Model/Book Add/replay, full ten-node proof, live provider window/budget approval, deployment or economic outcomes.

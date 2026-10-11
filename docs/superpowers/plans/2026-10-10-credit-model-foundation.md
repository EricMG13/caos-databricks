# Credit model foundation: implementation plan (Plan 1 of 4)

> **For agentic workers:** REQUIRED SUB-SKILL: use superpowers:subagent-driven-development to implement this plan task by task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** amend CP-1 (owner-authorised 2026-10-10) and build a pure Decimal credit-model calculator that turns accepted CP-1, CP-2G and CP-CF outputs plus a rate deck into one ordered, fully reconciling grid of columns × lines. Plan 2 serves the grid as the Model; Plan 3 persists its headline metrics as book entries.

**Architecture:** parsing lives in `caos/methodology/model_inputs.py` (tagged tables → frozen dataclasses). Arithmetic lives in `caos/calculators/credit_model/`, which is pure: no I/O, Decimal only. Each stage writes into a **frame**, `dict[column_id, dict[key, Cell]]`: history → pro forma → projection → metrics. A final layout step maps frame keys to ordered `Line`s. Computation and presentation stay separate, and every bridge can be checked on the frame.

**Tech stack:** Python 3.13, `decimal`, `dataclasses`, pytest, hypothesis (pre-approved), mutmut (pre-approved, money code).

**Spec:** `docs/superpowers/specs/2026-10-10-book-model-redesign-design.md`, plus the worked example `docs/superpowers/specs/2026-10-10-model-layout-example.html`. Its generator, whose row order and bridges are the target, is at `.superpowers/sdd/2026-10-10-credit-model-foundation/model-layout-example.py` (and in git at 357a809e).

## Global constraints

- **Gates** are every gate in `CLAUDE.md` § Gates. "Done" means they ran and exited 0. Coverage ≥ 80%. `uv run python scripts/check_tested.py` requires every public definition to be named by a test. `uv run complexipy caos scripts icm --max-complexity-allowed 15` applies to new code.
- **Suppressions only fall** (`tests/gate_baseline.json`). There's no new `noqa`, `type: ignore` or `pragma`. A function with ≥ 6 parameters would need a `noqa: PLR0913`, so pass a frozen dataclass instead.
- **Decimal, never float**, on money and ratios (invariant 7). The context is `Context(prec=38, rounding=ROUND_HALF_EVEN, traps=[InvalidOperation, DivisionByZero, Overflow])`, as in `caos/calculators/cash_flow.py:89`. A ratio is `None` with reason `ZERO_OR_NEGATIVE_DENOMINATOR` when its denominator is ≤ 0. There is no rounding inside the calculator: round only at display.
- **Vocabulary:** never `benchmark` (forbidden; use `reference_rate`), `pipeline`, `workflow`, `chunk` or `deal`. One term per concept, per `CONTEXT.md`.
- **Never edit** `caos/calculators/cash_flow.py` (it's byte-pinned in `icm/HOST_INTEGRITY_v1.json`, with parity goldens).
- **Every task brief and report:** no stub or fake value stands in for real behaviour, and no catch-all hides a failure unless the fail-open is documented and logged. Each report ends with a `Not verified:` line.
- **No PR and no merge** until `claude/n94-typed-registers` has merged into `rebuild/databricks`. Commit on `claude/book-model-redesign-7ce1fc` only.
- **Commit trailer:** `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Shared types (Task 2 defines them; every later task uses them verbatim)

```python
# caos/calculators/credit_model/frame.py
ColumnKind = Literal["QUARTER", "PYTD", "YTD", "FY", "LTM", "PF_LTM", "PROJECTED"]
Case = Literal["BASE", "DOWNSIDE"]
Basis = Literal["REPORTED", "CALCULATED", "PRO_FORMA", "PROJECTED", "DRIVER"]
Reason = Literal[
    "NOT_PROJECTED", "NOT_APPLICABLE", "NOT_SOURCED", "COMPONENT_MISSING",
    "ZERO_OR_NEGATIVE_DENOMINATOR", "NOT_STATED",
]

@dataclass(frozen=True, slots=True)
class SourceRef:
    source_id: str
    source_locator: str
    cell_text: str            # the CP-1 cell text verbatim, [C<n>] markers kept (D107)

@dataclass(frozen=True, slots=True)
class Cell:
    value: Decimal | None
    reason: Reason | None = None          # set iff value is None
    basis: Basis | None = None
    stated: Decimal | None = None         # CP-1's own figure where the host recomputed one
    sources: tuple[SourceRef, ...] = ()
    note: str | None = None               # "implied rate", "assumed refinanced", "held flat", "differs from CP-1 stated"

@dataclass(frozen=True, slots=True)
class Column:
    column_id: str            # "Q:<period_id>", "PYTD:<period_id>", "YTD:<period_id>", "FY:<period_id>", "LTM:<period_id>", "PF:<period_id>", "BASE:<fiscal_year>", "DOWNSIDE:<fiscal_year>"
    kind: ColumnKind
    label: str                # "Q2 26", "PYTD H1 25", "YTD H1 26", "FY25", "LTM Q2 26", "PF-LTM", "FY26E"
    period_id: str | None
    fiscal_year: str
    end_date: str | None      # ISO date
    days: int | None
    case: Case | None

Frame = dict[str, dict[str, Cell]]   # column_id -> key -> Cell
```

**Frame keys.** These are fixed strings, plus dynamic keys with a prefix:
- **Accounts and lines:** `revenue`, `cogs`, `gross_profit`, `opex_ex_da`, `da`, `opex_total`, `ebit`, `ebitda`, `adjusted_ebitda`, `operating_lease_cost`, `adjusted_ebitdar`.
- **Cash:** `cash_interest`, `lease_cash_not_in_ebitda`, `cash_taxes`, `other_operating` (residual), `ffo`, `working_capital_change`, `cfo_adjusted`, `cfo_reported`, `capex`, `fcf`.
- **Net cash flow:** `acquisitions_net`, `debt_raised_net`, `equity_raised_net`, `dividends`, `other_investing_financing` (residual), `ncf`, `cash_opening`, `fx_and_other_cash` (residual), `cash_closing`.
- **Liquidity and debt totals:** `undrawn_rcf`, `liquidity`, `total_debt`, `lease_liabilities`, `lease_adjusted_debt`, `net_debt`, `lease_adjusted_net_debt`, `secured_debt`, `debt_opening`, `debt_non_cash` (residual), `debt_closing`.
- **Working capital:** `accounts_receivable`, `inventory`, `accounts_payable`, `dso`, `dio`, `dpo`, `ccc`, `days`.
- **Interest:** `reference_rate`, `interest_bearing_debt_opening`, `wa_rate`.
- **Dynamic:** `bu:<segment_id>`, `bu_growth:<segment_id>`, `addback:<addback_id>`, `kpi:<kpi_id>`, `fac:<facility_id>`, `acct:<metric_id>`, `pf:<adjustment_id>`, `metric:<name>`, `revenue_growth`, `adjusted_ebitda_growth`.

---

### Task 1: CP-1 fork amendment and re-pin

**Agent:** `mx-autonomous`. It's multi-file vendor work under D31; the owner authorised it on 2026-10-10.

**Files:**
- Modify `vendor/deploy-v/skills/cp-1-canonical-data-foundation/references/REF_CP-1_STEPS.md`: the account ids around :378-390, the debt columns below :396, and a new "Pro forma adjustment register" section.
- Modify `vendor/deploy-v/skills/cp-1-canonical-data-foundation/SKILL.md`: T4.18 `columns` at :140-145, and the new table as an *optional when applicable* stable table, like `cp1.operating_kpi_schedule`.
- Modify `vendor/deploy-v/skills/cp-1-canonical-data-foundation/references/CP-1_SCHEMA_REFERENCE.md:22`.
- Modify `vendor/deploy-v/skills/cp-model/scripts/validate_cp_model_inputs.py`: `METRIC_IDS` at :180-213 gets the 3 new ids. Do **not** make the new debt columns required in `STABLE_TABLE_REQUIRED_COLUMNS`, so older runs stay valid.
- Modify the vendor tests: `vendor/deploy-v/tests/test_regressions.py` (:277 T4.18 column list, :815-819, :1165-1175).
- Modify the host fixtures and tests that carry CP-1 tables: `tests/cp1b_route_fixtures.py:383-470`, `tests/test_vendor_fork.py` (:882-886, :1032-1170), `frontend/fixtures/analysis.json`, and `frontend/tests/unit/figures.test.tsx` if a column count is asserted.
- Re-pin: `icm/HOST_INTEGRITY_v1.json`, `caos/methodology/host_pin.py` and `caos/methodology/bundle_pin.py` (all via `scripts/host_manifest.py`), plus the build-id pins in `tests/test_bundle_pin.py:56`, `tests/test_methodology_bundle.py:58,200`, `tests/test_qualification_matrix.py:234`, `tests/test_loop_charges.py:237`, `tests/test_canonical_proof.py:204` and `tests/test_delivered_authority.py:70` (re-measure).
- Regenerate the prompt goldens: `tests/parity/golden/prompt/**` (all 27 carry the authority digest).

**Amendment text.** Write it in the house style of the surrounding file.
1. **Controlled account metric ids**: add three.
   - `operating_lease_cost`: lease cost recognised inside operating expenses (ASC 842 operating lease cost; under IFRS 16 only short-term and variable lease expense).
   - `lease_payments_in_financing`: lease cash the issuer classified in financing activities (IFRS 16 principal; ASC 842 finance-lease principal).
   - `interest_paid_in_financing`: interest paid that the issuer classified in financing activities (an IFRS option; `0` under US GAAP).

   Sign convention as for the existing ids (outflows negative).
2. **Debt register columns**, appended after `lease_classification` and before `source_id`:
   - `rate_type`: `FIXED | FLOATING | NOT_STATED`;
   - `reference_rate`: `SOFR | TERM_SOFR | EURIBOR | SONIA | NONE`;
   - `spread_bps`: an integer basis-point spread over the reference rate, or `null`;
   - `floor_bps`: an integer floor on the reference rate, or `null` when there is none;
   - `fixed_rate`: a decimal percent coupon for `FIXED`, otherwise `null`;
   - `annual_amortisation`: scheduled principal amortisation per year in the register's currency and unit, `null` for a bullet.

   Each must be sourced like every other column. `NOT_STATED` or `null` is never inferred from the instrument name.
3. **Rule:** a lease liability is a debt-register row with `lease_classification` `FINANCE_LEASE` or `OPERATING_LEASE`, and the account metric `total_debt` **excludes** lease liabilities. Add a reconciliation check, `check_type` `DEBT_TOTAL_EX_LEASES`: the sum of carrying values of `NOT_LEASE` and `NOT_STATED` rows, plus any `DEBT ADJUSTMENT` row, equals `total_debt`.
4. **New optional tagged table** `<!-- table-id: cp1.pro_forma_adjustment_register -->`, with columns `adjustment_id | label | period_id | effective_date | classification | metric_id | value | source_id | source_locator`.
   - `classification` is one of `ACQUISITION`, `DISPOSAL`, `REFINANCING`, `SUBSEQUENT_EVENT`, `LENDER_UPDATE`, `OTHER_EXPLICIT`.
   - `period_id` names the LTM period the adjustment applies to.
   - `metric_id` is one of `revenue`, `ebitda`, `adjusted_ebitda`, `cash_interest_paid`, `cash_and_equivalents`, `total_debt`, or a facility's `facility_id` prefixed `facility:`.
   - The table is emitted only when a source states an adjustment for activity outside the reported LTM (a lender presentation for a primary transaction, a post-period acquisition, disposal or refinancing). Otherwise it's an empty table.
5. **Limitation note:** income taxes classified outside operating activities are recorded in Gaps and Conflicts as a limitation. There is no metric id for them.

- [ ] **Step 1:** Write a failing vendor regression test asserting that the T4.18 column list includes the six new columns in order, and that `METRIC_IDS` contains the three new ids. Run `python3 -B -m unittest discover -s vendor/deploy-v/tests -k debt` and expect a FAIL.
- [ ] **Step 2:** Make the text edits in REF/SKILL/SCHEMA and update `validate_cp_model_inputs.py` `METRIC_IDS`. Run the same test and expect a PASS.
- [ ] **Step 3:** Run `python3 -B vendor/deploy-v/verify_package.py --refresh`. Expect exit 0, a new `build_id`, and refreshed manifest and baseline.
- [ ] **Step 4:** Run `uv run python scripts/host_manifest.py`, then update every build-id or manifest pin listed under Files with the new values printed by Step 3.
- [ ] **Step 5:** Update the host CP-1 fixtures so every `cp1.debt_facility_register` row carries the six new columns (use real-looking values: an RCF `FLOATING|SOFR|225|null|null|null`, a TLB `FLOATING|SOFR|275|50|null|<1% of principal>`, notes `FIXED|NONE|null|null|6.500|null`, leases `NOT_STATED|NONE|null|null|null|null`). Missing contract columns are critical in `completeness_check.py`.
- [ ] **Step 6:** Regenerate the prompt goldens using D34's procedure (`docs/rebuild/decisions.md:251,868`). Work on a scratch clone of the legacy snapshot (`$LEGACY_RO/repo`, `b5a3932f…`) with `vendor/deploy-v` replaced by the fork and the host prompt blocks and fixtures mirrored. First prove it reproduces the current 27 `prompt` and 16 `forecast` goldens byte for byte from the **pre-edit** bundle; then run `tests/parity/generate_goldens.py --package server --root <copy> --out <dir> --group prompt` over the edited bundle and copy the output in.
  - If `$LEGACY_RO` is unavailable, stop and report BLOCKED with the exact command and error. Do not hand-edit goldens.
- [ ] **Step 7:** Run every CLAUDE.md gate, including `uv run python -B vendor/deploy-v/verify_package.py` (A27), `uv run python scripts/check_icm.py` and the full pytest with Postgres.
- [ ] **Step 8:** Commit: `CP-1 fork amendment: PF register, lease and interest classification ids, rate and amortisation terms (owner-authorised 2026-10-10)`.

**Not verified (expected):** a live CP-1 run emitting the new columns. That runs once at the end of Plan 2 within the $75 budget.

---

### Task 2: frame types and CP-1, CP-2G and CP-CF input parsing

**Agent:** `mx-precise`.

**Files:**
- Create `caos/calculators/credit_model/__init__.py` (docstring: "Pure credit-model arithmetic: Decimal only, no I/O.") and `caos/calculators/credit_model/frame.py` (the shared types above, verbatim).
- Create `caos/methodology/model_inputs.py`.
- Test: `tests/test_model_inputs.py`.

**Interfaces produced:**

```python
# caos/methodology/model_inputs.py
@dataclass(frozen=True, slots=True)
class PeriodRow:  period_id: str; fiscal_year: str; fiscal_quarter: str | None; period_type: str  # QUARTER|YTD|FY|LTM|PERIOD_END
                  start_date: str | None; end_date: str | None; day_count: int | None; currency: str; unit: str
                  component_period_ids: tuple[str, ...]
@dataclass(frozen=True, slots=True)
class AccountRow: metric_id: str; period_id: str; value: Decimal | None; calculation_status: str; source: SourceRef | None
@dataclass(frozen=True, slots=True)
class AddbackRow: addback_id: str; label: str; classification: str; realization_status: str; display_priority: int; period_id: str; value: Decimal | None; source: SourceRef | None
@dataclass(frozen=True, slots=True)
class SegmentRow: segment_id: str; segment_name: str; segment_type: str; display_priority: int; period_id: str; revenue: Decimal | None; source: SourceRef | None
@dataclass(frozen=True, slots=True)
class KpiRow:     kpi_id: str; kpi_label: str; display_priority: int; period_id: str; value: Decimal | None; unit: str; value_type: str; source: SourceRef | None  # PERIOD_END|PERIOD_FLOW|RATE
@dataclass(frozen=True, slots=True)
class FacilityRow: facility_id: str; facility_name: str; period_id: str; facility_type: str; carrying_value: Decimal | None
                   commitment: Decimal | None; drawn_amount: Decimal | None; secured_status: str; seniority: str; lease_classification: str
                   maturity_date: str | None; margin_or_coupon: str; rate_type: str; reference_rate: str; spread_bps: Decimal | None
                   floor_bps: Decimal | None; fixed_rate: Decimal | None; annual_amortisation: Decimal | None; source: SourceRef | None
@dataclass(frozen=True, slots=True)
class PfAdjustmentRow: adjustment_id: str; label: str; period_id: str; classification: str; metric_id: str; value: Decimal; source: SourceRef | None
@dataclass(frozen=True, slots=True)
class Cp1Registers: periods: tuple[PeriodRow, ...]; accounts: tuple[AccountRow, ...]; addbacks: tuple[AddbackRow, ...]
                    segments: tuple[SegmentRow, ...]; kpis: tuple[KpiRow, ...]; facilities: tuple[FacilityRow, ...]
                    pro_forma: tuple[PfAdjustmentRow, ...]; currency: str; unit: str
@dataclass(frozen=True, slots=True)
class DivisionGrowth: case: Case; fiscal_year: str; slot_id: str; value: Decimal          # PERCENT_DECIMAL, READY rows only
@dataclass(frozen=True, slots=True)
class SlotAllocation: slot_id: str; component_segment_ids: tuple[str, ...]

def cp1_registers(tables: Sequence[HandoffTable]) -> Cp1Registers: ...
def division_growth(tables: Sequence[HandoffTable]) -> tuple[DivisionGrowth, ...]: ...   # cp2g.cp_model_forecast_drivers
def slot_allocation(tables: Sequence[HandoffTable]) -> tuple[SlotAllocation, ...]: ...   # cp1.cp_model_segment_allocation
```

**Rules:**
- A row's figure is `TableCell.value` parsed with `Decimal(...)`. The text is kept in `SourceRef.cell_text`.
- Columns added by Task 1 that are **absent** from an older run's table read as `NOT_STATED`/`NONE`/`None`, never as an error.
- A required column absent from a present table raises `Refusal(RefusalCode.TABLES_MALFORMED)`. If that code doesn't exist, use the code `handoff_tables` already returns for a malformed table (`caos/methodology/tables.py:93`).
- A missing optional table gives an empty tuple.
- `currency` and `unit` come from the period register (all rows must agree, or raise the same malformed refusal).
- Lowercase or uppercase enumerations are normalised to upper case.

- [ ] **Step 1:** Write the failing tests in `tests/test_model_inputs.py`. Build `HandoffTable`s inline (`HandoffTable(table_id="cp1.model_account_register", columns=(...), rows=((TableCell("1,250.0 [C3]","1250.0"), ...),))`). Cover:
  - `test_cp1_registers_reads_each_register_into_typed_rows`;
  - `test_a_debt_register_without_the_rate_columns_reads_them_as_not_stated` (an older run);
  - `test_a_missing_pro_forma_register_is_empty`;
  - `test_a_present_table_missing_a_required_column_is_refused`;
  - `test_division_growth_keeps_ready_rows_only`;
  - `test_mixed_currencies_in_the_period_register_are_refused`.
- [ ] **Step 2:** Run `uv run pytest tests/test_model_inputs.py -q` and expect FAIL (an import error).
- [ ] **Step 3:** Implement `frame.py` and `model_inputs.py` (the functions stay under complexity 15; use one small per-table row function each).
- [ ] **Step 4:** Run `uv run pytest tests/test_model_inputs.py -q` and expect PASS. Then run `uv run ruff check . && uv run mypy caos scripts tests && uv run python scripts/check_tested.py`.
- [ ] **Step 5:** Commit: `Credit model: frame types and CP-1/CP-2G register inputs`.

---

### Task 3: historical columns and derived periods

**Agent:** `mx-precise`. This is money code: hypothesis property tests, then mutmut on the file.

**Files:** create `caos/calculators/credit_model/history.py`; test `tests/test_credit_model_history.py`.

**Interfaces:**
- Consumes `Cp1Registers`, `Column`, `Cell` and `Frame`.
- Produces:

```python
FLOW_METRICS: frozenset[str]      # summed: revenue, cogs, gross_profit, opex_including_da, ebit, depreciation_amortization, ebitda,
                                  # adjusted_ebitda, cash_interest_paid, cash_lease_payments, cash_taxes_paid, cfo_ncfo, working_capital_change,
                                  # capex_and_intangible_investment, acquisitions_disposals, net_debt_issue_repay, net_equity_issue_repay,
                                  # dividends_paid, other_investing_financing, net_cash_change, pretax_income, income_tax_expense,
                                  # operating_lease_cost, lease_payments_in_financing, interest_paid_in_financing
BALANCE_METRICS: frozenset[str]   # last observation: cash_and_equivalents, rcf_commitment, rcf_drawn, senior_secured_debt, unsecured_debt,
                                  # total_debt, net_accounts_receivable, inventory, accounts_payable
def historical_columns(regs: Cp1Registers) -> tuple[Column, ...]
def account_frame(regs: Cp1Registers, columns: tuple[Column, ...]) -> Frame   # keys: "acct:<metric_id>", "bu:<segment_id>", "addback:<id>", "kpi:<id>", "fac:<facility_id>"
def ltm_frames(regs: Cp1Registers, columns: tuple[Column, ...]) -> dict[str, dict[str, Cell]]   # column_id of each QUARTER -> frame of the LTM ending it
```

**Column rules** (the spec's M2 order: Quarters → PYTD, YTD → FY → LTM):
- **QUARTER** columns: every `QUARTER` period in the register, plus a calculated quarter wherever CP-1 calculation rules apply and the components exist (Q2 = H1 − Q1, Q3 = 9M − H1, Q4 = FY − 9M, only when no reported quarter exists). Sorted by `end_date`. Label `Q{n} {yy}`.
- **YTD** is the latest `YTD` period (or the latest H1 or 9M). **PYTD** is the `YTD` period of the prior fiscal year with the same `fiscal_quarter`. Omit them when the latest period is a FY end.
- **FY** columns: every `FY` period (label `FY{yy}`).
- **LTM** is the period-register `LTM` row when present. Otherwise derive it from the latest FY + YTD − PYTD; with no YTD, LTM equals the latest FY.

**Value rules:**
- **Flows:** reported values pass through with `basis="REPORTED"` and their source. A derived column sums or subtracts its components with `basis="CALCULATED"`. When CP-1 also stated that column's value, put it in `stated=`, and if `abs(stated − host) > Decimal("0.5") * 10 ** -decimals_of(stated)` (beyond rounding), set `note="differs from CP-1 stated"`. A missing component gives `Cell(None, "COMPONENT_MISSING")`.
- **Balances:** the end-of-column period's value. For LTM, the latest period end. For PYTD, the prior-year period end.
- **Business units** (`bu:`) and **add-backs** (`addback:`) follow the flow rules.
- **KPIs** by `value_type`:
  - `PERIOD_FLOW` sums;
  - `PERIOD_END` takes the last observation;
  - `RATE` is shown only where a row exists for exactly that period, otherwise `Cell(None, "NOT_SOURCED")`.
- **Facilities** (`fac:`): the carrying value at the column's end period.

- [ ] **Step 1:** Write the failing tests, using a CP-1 fixture builder `_regs(quarters=..., fy=..., ytd=...)` in the test module:
  - `test_ltm_equals_fy_plus_ytd_minus_pytd_for_every_flow`
  - `test_a_reported_quarter_is_never_replaced_by_a_calculated_one`
  - `test_q4_is_calculated_from_fy_minus_9m_only_without_a_reported_q4`
  - `test_a_derived_column_with_a_missing_component_is_component_missing`
  - `test_a_stated_ltm_that_differs_beyond_rounding_is_noted`
  - `test_balances_take_the_column_end_period`
  - `test_a_rate_kpi_is_not_sourced_on_a_derived_column`
  - `test_columns_are_ordered_quarters_pytd_ytd_fy_ltm`
  - **Hypothesis:** `test_derived_flows_reconcile_for_any_quarter_values` generates integer-cent quarter values and asserts `FY == ΣQ`, `YTD == Q1+Q2`, `LTM == FY + YTD − PYTD`.
- [ ] **Step 2:** Run `uv run pytest tests/test_credit_model_history.py -q` and expect FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Expect PASS. Run `uv run mutmut run --paths-to-mutate caos/calculators/credit_model/history.py` and kill or justify the survivors in the report.
- [ ] **Step 5:** Commit: `Credit model: historical columns, derived periods, stated-vs-host notes`.

---

### Task 4: statements, waterfall, liquidity, debt stack and working capital (historical and PF-LTM)

**Agent:** `mx-precise` (money).

**Files:** create `caos/calculators/credit_model/statements.py` and `caos/calculators/credit_model/debt.py`; tests `tests/test_credit_model_statements.py` and `tests/test_credit_model_debt.py`.

**Interfaces produced:**

```python
def statement_frame(accounts: Frame, columns: tuple[Column, ...], regs: Cp1Registers, exclude_unrealised: bool = False) -> Frame     # adds the fixed keys listed under "Frame keys"
PAYMENT_RANKS: tuple[str, ...] = ("Super senior", "Senior secured", "Senior, security not stated", "Senior unsecured",
                                  "Subordinated", "Junior", "Not stated", "Finance leases", "Debt adjustments")
def payment_rank(row: FacilityRow) -> str
def debt_frame(regs: Cp1Registers, columns: tuple[Column, ...]) -> Frame      # total_debt, lease_liabilities, secured_debt, undrawn_rcf, roll-forward keys
def pro_forma_column(regs: Cp1Registers, ltm: Column, frame: Frame) -> tuple[Column, Frame]   # PF:<period_id>, or none when the register is empty
```

**Formulas.** Signs follow the worked example: outflows are negative in the frame. **Normalise sign-agnostically.** The frame value of each expense or outflow metric (`cogs`, `opex_including_da`, `depreciation_amortization`, `cash_interest_paid`, `cash_lease_payments`, `cash_taxes_paid`, `capex_and_intangible_investment`, `operating_lease_cost`, `lease_payments_in_financing`, `interest_paid_in_financing`, `dividends_paid`) is `−abs(value)`, so a CP-1 run that wrote them positive reads the same. Signed flows (`acquisitions_disposals`, `net_debt_issue_repay`, `net_equity_issue_repay`, `other_investing_financing`, `working_capital_change`, `net_cash_change`, `cfo_ncfo`) keep their CP-1 sign. Here `da` means the normalised `depreciation_amortization` (negative).
- `gross_profit = revenue + cogs`, with `cogs` negative.
- `opex_ex_da = opex_including_da − da` (both negative). `ebit = gross_profit + opex_including_da`. `ebitda = ebit − da`.
- Each of these has a stated-vs-host note against the CP-1 account where it exists.
- `adjusted_ebitda = ebitda + Σ addback`. The stated `adjusted_ebitda` goes in `stated=`. With `exclude_unrealised=True` (spec M7), add-backs whose `realization_status` is `UNREALIZED` or `NOT_STATED` are left out of the sum on every column; their `addback:` cells keep their values with `note="excluded"`, and `stated=` is not compared.
- `adjusted_ebitdar = adjusted_ebitda − operating_lease_cost` (operating lease cost is negative, so this adds it back).
- `lease_cash_not_in_ebitda = lease_payments_in_financing`. `cfo_adjusted = cfo_ncfo + lease_payments_in_financing + interest_paid_in_financing` (both negative, so CFO falls).
- `ffo` and `other_operating`:
  - `other_operating = cfo_adjusted − working_capital_change − (adjusted_ebitda + cash_interest + lease_cash_not_in_ebitda + cash_taxes)`;
  - then `ffo = adjusted_ebitda + cash_interest + lease_cash_not_in_ebitda + cash_taxes + other_operating`;
  - assert `ffo + working_capital_change == cfo_adjusted`.
- `fcf = cfo_adjusted + capex`.
- `debt_raised_net = net_debt_issue_repay`. `equity_raised_net = net_equity_issue_repay`. `dividends = dividends_paid`. `acquisitions_net = acquisitions_disposals`.
- `other_investing_financing = net_cash_change − (fcf + acquisitions_net + debt_raised_net + equity_raised_net + dividends)`. This is a residual, so `ncf == net_cash_change`.
- `cash_opening` is the previous column-period end cash, or the CP-1 balance at the period start. `fx_and_other_cash = cash_closing − cash_opening − ncf`.
- `undrawn_rcf = rcf_commitment − rcf_drawn`, and `liquidity = cash_closing + undrawn_rcf`.
- **Debt:**
  - `total_debt` is the sum of carrying values of rows whose `lease_classification ∈ {NOT_LEASE, NOT_STATED}`, plus `FINANCE_LEASE` rows. It excludes `OPERATING_LEASE`. CP-1's amended `total_debt` account excludes **all** leases, so compare (host `total_debt` − `FINANCE_LEASE` rows) with it via `stated=` (ledger ruling).
  - `lease_liabilities` is the sum of `OPERATING_LEASE` rows.
  - A facility whose `currency` differs from `Cp1Registers.currency` is left out of every total and subtotal. Its `fac:` cell keeps its own value with `note="different currency; not converted"` (spec B13: no FX).
  - `lease_adjusted_debt = total_debt + lease_liabilities`, and `net_debt = total_debt − cash_closing`.
  - `secured_debt` sums the `Super senior` and `Senior secured` ranks.
  - Roll-forward: `debt_opening` is the previous column's `total_debt`; `debt_raised_net` comes from the NCF; `debt_non_cash = debt_closing − debt_opening − debt_raised_net` (a residual).
- **Working capital:** `dso = AR / revenue × days`, `dio = inventory / −cogs × days`, `dpo = AP / −cogs × days`, `ccc = dso + dio − dpo`. A denominator ≤ 0 gives `ZERO_OR_NEGATIVE_DENOMINATOR`. `days` is the column's `days`.
- **PF-LTM:**
  - Every LTM key is copied.
  - Each register row becomes a `pf:<adjustment_id>` cell on the PF column only.
  - `adjusted_ebitda`, `cash_interest`, `cash_closing`, `total_debt` and the named `fac:` keys add the matching adjustments.
  - Waterfall keys below `cash_interest` (`ffo` to `ncf`) are `Cell(None, "NOT_APPLICABLE")`.
  - `adjusted_ebitda` margin on PF is `NOT_APPLICABLE` (no revenue PF unless a `revenue` adjustment exists, in which case `revenue` adds it).

- [ ] **Step 1:** Write the failing tests. Use the worked example's Q2 26 and LTM column as fixtures (`.superpowers/sdd/2026-10-10-credit-model-foundation/model-layout-example.py`; translate its Example Gaming Co. quarter inputs into CP-1 account rows):
  - `test_the_waterfall_reconciles_ffo_plus_wc_to_cfo_adjusted`
  - `test_cfo_adjusted_removes_lease_and_interest_classified_in_financing`
  - `test_ncf_equals_reported_net_cash_change`
  - `test_total_debt_excludes_operating_leases_and_includes_finance_leases`
  - `test_payment_rank_maps_seniority_and_security` (table-driven over all `SENIORITY_STATUSES` × `secured_status`)
  - `test_debt_roll_forward_closes_to_the_stack`
  - `test_pro_forma_adds_each_adjustment_once_and_blanks_the_waterfall`
  - `test_dio_and_dpo_are_null_when_cogs_is_not_negative`
  - `test_exclude_unrealised_leaves_unrealised_and_not_stated_addbacks_out`
  - **Hypothesis:** `test_every_bridge_reconciles_for_any_consistent_accounts`.
- [ ] **Step 2:** Run the two test files and expect FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Expect PASS. Run mutmut on both files.
- [ ] **Step 5:** Commit: `Credit model: statements, waterfall, debt stack, working capital, PF-LTM`.

---

### Task 5: projections, amortisation and interest

**Agent:** `mx-precise` (money).

**Files:** create `caos/calculators/credit_model/projection.py`; test `tests/test_credit_model_projection.py`.

**Interfaces:**
- Consumes `Cp1Registers`, `DivisionGrowth`, `SlotAllocation`, the CP-CF request (`caos.methodology.forecast.forecast_inputs(markdown)[0]`, a `Mapping`), and `Frame`.
- Produces:

```python
@dataclass(frozen=True, slots=True)
class RateDeckYear: reference_rate: str; fiscal_year_offset: int; base: Decimal; downside: Decimal   # rates as decimals (0.0380)
@dataclass(frozen=True, slots=True)
class RateDeck: deck_id: str; as_of: str; years: tuple[RateDeckYear, ...]
def rate_for(deck: RateDeck | None, reference_rate: str, case: Case, offset: int) -> Decimal | None   # last stated year held flat
def facility_rate(row: FacilityRow, deck: RateDeck | None, case: Case, offset: int, implied: Decimal | None) -> tuple[Decimal | None, str | None]
def projection(regs: Cp1Registers, request: Mapping[str, Any], growth: tuple[DivisionGrowth, ...],
               slots: tuple[SlotAllocation, ...], deck: RateDeck | None, history: Frame) -> tuple[tuple[Column, ...], Frame]
```

`projection` takes six parameters, so bundle them: define `@dataclass(frozen=True, slots=True) class ProjectionInputs` with those six fields and make the signature `projection(inputs: ProjectionInputs)`. This avoids a new `noqa`.

**Rules** (spec M11–M14; the order is per case, per year, chained):
- **Columns:** one per (case, period) in the CP-CF request's `periods`. `column_id` is `BASE:<fiscal_year>` or `DOWNSIDE:<fiscal_year>`, label `FY{yy}E`.
- **Business-unit revenue:**
  - `bu:<segment>` = prior-year value × (1 + the growth of the slot that contains the segment). The prior year is the last historical FY, then the previous projected year.
  - A segment in no slot is held flat with `note="held flat"`. Corporate and eliminations are held flat.
  - `revenue = Σ bu`. If CP-CF's `revenue` driver for that period differs beyond rounding, set `note="differs from CP-CF revenue"` on `revenue`.
- **From CP-CF drivers** (signed into frame convention): `adjusted_ebitda` = the driver `ebitda`; `capex` = −driver `capex`; `cash_taxes` = −driver `cash_taxes`. `other_operating` = driver `cfo` − driver `ebitda`; it carries working capital and other operating items and is noted "includes working capital".
- **Debt schedule:**
  - The opening facility balances are the last historical period-end `fac:` values (operating leases excluded).
  - Each year, scheduled amortisation is `min(annual_amortisation, balance)`. Per the r14 ruling, `0` means a bullet, and `None` means not stated: treat it as 0 and set `note="amortisation not stated"` on that facility's cells.
  - A facility whose `maturity_date` falls in that fiscal year keeps its balance, with `note="assumed refinanced"` on that `fac:` cell.
  - Aggregate debt: `debt_closing = debt_opening − Σ scheduled + driver issuance − driver optional_repayment`.
  - Finance leases are held flat (`note="held flat"`).
- **Rate-term validation** (carried from the Task 2 review): a `rate_type` or `reference_rate` outside its value set, or a negative `spread_bps`, `floor_bps`, `fixed_rate` or `annual_amortisation`, is treated as not stated (implied rate, or amortisation not stated) with `note="term out of range"`. It is never used as given.
- **Interest:**
  - `interest_bearing_debt_opening` = Σ opening `fac:` balances over non-lease facilities, excluding `DEBT ADJUSTMENT` rows.
  - `wa_rate` = Σ(amortised facility balance × facility rate) / Σ amortised balances.
  - `facility_rate` gives `fixed_rate` for `FIXED`. For `FLOATING`, it gives `max(rate_for(deck, reference_rate, case, offset), floor) + spread`. Otherwise, which includes `rate_type` `NOT_STATED` and `FLOATING` with `reference_rate` `NOT_STATED` or `NONE`, the implied rate (note "implied rate"), where implied = −LTM `cash_interest` / average(LTM opening and closing `total_debt`).
  - With no deck, floating facilities use the implied rate with reason note "no rate deck".
  - `cash_interest = −(wa_rate × interest_bearing_debt_opening)`.
- **Cash:**
  - `lease_cash_not_in_ebitda` = `Cell(None, "NOT_PROJECTED")`. `cfo_adjusted = adjusted_ebitda + other_operating + cash_interest + cash_taxes`. `fcf = cfo_adjusted + capex`.
  - `ffo` and `working_capital_change` are `NOT_PROJECTED`.
  - `debt_raised_net = issuance − optional_repayment − Σ scheduled`. `equity_raised_net = 0` unless a CP-2G `net_equity_issue_repay` driver exists. `dividends = −distributions`. `acquisitions_net = acquisitions_disposals`.
  - `ncf = fcf + acquisitions_net + debt_raised_net + equity_raised_net + dividends`. `cash_closing = cash_opening + ncf`.
- **Not projected:** lease balances, working-capital balances, days and KPIs.

- [ ] **Step 1:** Write the failing tests, translating the worked example's Base and Downside inputs:
  - `test_interest_is_weighted_rate_times_opening_interest_bearing_debt`
  - `test_a_floating_facility_uses_deck_rate_floor_and_spread`
  - `test_terms_not_stated_fall_back_to_the_implied_rate_with_a_note`
  - `test_no_rate_deck_uses_the_implied_rate_for_floating_facilities`
  - `test_a_year_beyond_the_deck_holds_the_last_rate`
  - `test_amortisation_stops_at_zero_balance`
  - `test_a_maturity_in_the_horizon_is_assumed_refinanced`
  - `test_bu_revenue_compounds_the_slot_growth_and_sums_to_revenue`
  - **Hypothesis:** `test_projected_cash_and_debt_roll_forward_for_any_drivers` asserts `cash_closing == cash_opening + ncf` and that the debt roll-forward closes, every year, for both cases.
- [ ] **Step 2:** Expect FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Expect PASS, then run mutmut.
- [ ] **Step 5:** Commit: `Credit model: projections with rate-deck interest and amortisation schedule`.

---

### Task 6: metrics on every column

**Agent:** `mx-precise` (money).

**Files:** create `caos/calculators/credit_model/metrics.py`; test `tests/test_credit_model_metrics.py`.

**Interfaces:** `def metric_frame(columns: tuple[Column, ...], frame: Frame, ltm_ending: Mapping[str, dict[str, Cell]]) -> Frame`. It adds `metric:<name>` keys plus `revenue_growth`, `adjusted_ebitda_growth` and `bu_growth:<segment>`. `ltm_ending[column_id]` is the frame of the LTM ending that quarter. `ltm_frames` comes from Task 3.

**Metric names and definitions:**
- **12-month basis:** a QUARTER column uses the LTM ending that quarter; FY, LTM, PF and PROJECTED use themselves; PYTD and YTD leverage and coverage are `NOT_APPLICABLE`.
- **Leverage:**
  - `total_leverage_reported = total_debt / ebitda` and `total_leverage_adjusted = total_debt / adjusted_ebitda`;
  - `net_leverage_reported`, `net_leverage_adjusted`;
  - `senior_secured_leverage = secured_debt / adjusted_ebitda`, `senior_secured_net_leverage = (secured_debt − cash) / adjusted_ebitda`;
  - `lease_adjusted_leverage = lease_adjusted_debt / adjusted_ebitdar`, `lease_adjusted_net_leverage`.
- **Coverage:**
  - `interest_coverage_reported = ebitda / −cash_interest` and `interest_coverage_adjusted`;
  - `capex_adjusted_coverage = (adjusted_ebitda + capex) / −cash_interest`;
  - `ebitdar_coverage = (adjusted_ebitdar + capex) / (−cash_interest − operating_lease_cost)`.
- **Cash flow and liquidity:** `ffo_to_debt`, `ffo_to_lease_adjusted_debt`, `fcf_to_debt`, `fcf_to_adjusted_ebitda`, `capex_to_revenue = −capex / revenue`, `liquidity_to_debt`.
- **Margins:** `gross_margin`, `ebitda_margin` and `adjusted_ebitda_margin`, on the column's own period.
- **Growth:** a quarter is compared with the same quarter a year earlier, YTD with PYTD, FY with the prior FY, LTM with the LTM a year earlier, and a projection with the prior year. With no prior, the reason is `NOT_APPLICABLE`.
- **Units:** the leverage and coverage metrics are `MULTIPLE`; the rest are `PERCENT`.
- **Propagation:** any input cell that is `None` gives the input's reason; a denominator ≤ 0 gives `ZERO_OR_NEGATIVE_DENOMINATOR`.

- [ ] **Step 1:** Write the failing tests:
  - `test_quarter_leverage_uses_the_ltm_ending_that_quarter`
  - `test_ytd_leverage_is_not_applicable`
  - `test_each_metric_has_reported_and_adjusted_variants_where_named`
  - `test_a_non_positive_denominator_is_zero_or_negative`
  - `test_growth_compares_like_periods`
  - `test_pf_leverage_uses_pf_debt_and_pf_ebitda`
- [ ] **Step 2:** Expect FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Expect PASS, then run mutmut.
- [ ] **Step 5:** Commit: `Credit model: credit metrics on a 12-month basis`.

---

### Task 7: layout, the assembled model and reconciliation

**Agent:** `mx-precise`.

**Files:** create `caos/calculators/credit_model/layout.py` and `caos/calculators/credit_model/assemble.py`; test `tests/test_credit_model_assemble.py`.

**Interfaces produced** (consumed by Plan 2's Model read and Plan 3's book entry):

```python
LineKind = Literal["ACCOUNT", "SUBTOTAL", "RATIO", "MEMO", "PF", "GROWTH"]
Unit = Literal["MONEY", "PERCENT", "MULTIPLE", "DAYS", "COUNT", "RATE", "KPI"]
@dataclass(frozen=True, slots=True)
class FacilityTerms: reference_rate: str; spread_or_coupon: str; floor: str; maturity: str; amortisation: str
@dataclass(frozen=True, slots=True)
class Line: line_id: str; band: str; label: str; kind: LineKind; unit: Unit; unit_label: str | None
            rank: str | None; terms: FacilityTerms | None; cells: tuple[Cell, ...]
@dataclass(frozen=True, slots=True)
class CreditModel: currency: str; unit: str; columns: tuple[Column, ...]; lines: tuple[Line, ...]
                   rate_deck_id: str | None; limitations: tuple[str, ...]
@dataclass(frozen=True, slots=True)
class ModelInputs: registers: Cp1Registers; request: Mapping[str, Any] | None; growth: tuple[DivisionGrowth, ...]
                   slots: tuple[SlotAllocation, ...]; deck: RateDeck | None; exclude_unrealised: bool = False
def credit_model(inputs: ModelInputs) -> CreditModel
def reconciliation_faults(model: CreditModel) -> tuple[str, ...]     # empty when every bridge closes
BANDS: tuple[str, ...]
```

**Layout.** The bands and their rows follow the worked example exactly, as amended by the spec's row economy:
- KPIs;
- revenue by business unit (each BU, then its growth row) and total revenue with growth;
- gross profit and margin;
- operating expenses to EBITDA: opex excluding D&A, D&A, total, EBIT, EBITDA, margin;
- adjusted EBITDA: each add-back, then PF rows, adjusted EBITDA, margin, operating lease cost, adjusted EBITDAR;
- adjusted EBITDA to FCF: cash interest and its PF row, lease cash not in EBITDA, cash taxes, other operating, FFO, change in WC, CFO after all interest and lease cash, CFO-as-reported memo, capex, FCF;
- net cash flow, cash and liquidity: acquisitions net, debt raised net, equity raised net, dividends, other, NCF, opening cash, FX and other, closing cash, PF cash, undrawn RCF, liquidity;
- debt stack by `PAYMENT_RANKS`: facilities with terms, a subtotal only when a rank has more than one line, PF rows under their facility; then total debt, operating lease liabilities, lease-adjusted debt, less cash, net debt, lease-adjusted net debt;
- debt roll-forward: opening, debt raised net, non-cash and lease movements, PF, closing;
- interest calculation (projections): reference rate, interest-bearing debt opening, WA rate;
- working capital: AR, inventory, AP, DSO, DIO, DPO, CCC;
- credit metrics, in Task 6's order.

Hiding zero rows is the frontend's job, not this layer's, so every line is emitted. `limitations` collects every distinct `note` with the columns it applies to.

**Reconciliation.** `reconciliation_faults` asserts on the model:
- revenue = Σ BU (where BU rows exist and reconcile on CP-1's own segment check);
- EBIT + D&A = EBITDA;
- EBITDA + Σ add-backs + PF = adjusted EBITDA;
- the FFO and CFO bridges;
- FCF;
- NCF;
- the cash bridge;
- liquidity;
- each rank subtotal and total debt = Σ;
- the debt roll-forward;
- projected interest = WA × opening.

Each fault reads `"<column_id>:<bridge>"`.

- [ ] **Step 1:** Write the failing tests:
  - `test_the_worked_example_reconciles_with_no_faults`: build `ModelInputs` from the worked example's inputs (port them from `.superpowers/sdd/2026-10-10-credit-model-foundation/model-layout-example.py` into a test fixture module, `tests/credit_model_fixture.py`) and assert `reconciliation_faults(credit_model(...)) == ()`;
  - `test_band_and_line_order_matches_the_layout`;
  - `test_a_rank_with_one_facility_has_no_subtotal`;
  - `test_a_run_without_cp_cf_has_no_projection_columns`;
  - `test_limitations_list_each_note_once`;
  - `test_exclude_unrealised_drops_unrealised_addbacks_from_adjusted_ebitda_everywhere`;
  - **Hypothesis:** `test_any_consistent_inputs_reconcile`.
- [ ] **Step 2:** Expect FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Expect PASS. Then run every CLAUDE.md gate.
- [ ] **Step 5:** Commit: `Credit model: layout, assembly and reconciliation`.

---

## After Plan 1

- `mx-adversary` audits the calculator diff (money code). Then `mx-architect` runs the whole-branch review at the end of Plan 4, with `confidence-review` and `rewrite-tournament`.
- Plan 2 (Model read, rate deck store and pin, wire and grid), Plan 3 (book entries, desk-wide grant, source flag) and Plan 4 (Book UI) are written after this plan lands. They consume `credit_model()`, `CreditModel`, `RateDeck` and `reconciliation_faults` exactly as named here.

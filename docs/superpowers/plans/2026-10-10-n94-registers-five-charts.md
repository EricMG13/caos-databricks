# N94 and N190's first five charts — plan

Spec: the owner's brief of 2026-10-10 ("Step 2: N94 and the first five charts"), `CLAUDE.md` (invariants, conventions, gates), D32 (typed tables), D61 (charts), D123 (the chart map), `docs/rebuild/next.md` N94 and N190–N193, `DESIGN.md` § Charts.

Then (owner, 2026-10-10: "add to plans building all the charts stated") every other chart of N190's map, Tasks 8–17. Not here: what needs the owner-authorised bundle fork (N192: split packed columns, add currency columns, tag tables under D31). Where a column packs two figures (`4.2x / 3.9x`), the bundle's `parse_figure` reads none and the chart draws a gap carrying the cell's text.

A stacked series of pull requests, because CI's `size` job caps one at 800 counted lines (`scripts/check_pr_size.py`; `docs/**`, `vendor/**` and lockfiles uncounted). Each PR is cut where its measured size nears the cap; the first is fixed:

| PR | Branch | Base | Tasks |
| :-- | :-- | :-- | :-- |
| 1 N94 | `claude/n94-typed-registers` | `claude/charts-visualizations-modules-n4mezr` (#125) | 1, 2 |
| 2… | `claude/n94-charts-<k>` | the PR before | 3–17 in order, cut by measured size |

## Global Constraints

- Invariant 4: never edit `vendor/deploy-v`. Read it through `caos.methodology.vendor.VendorContract` (`contract.completeness_check`, `contract.cp_tables`) and verified bytes only.
- Invariant 7: a figure's value is `caos.methodology.tables.figure_value` (Decimal, plain notation), never the vendor's float. In the browser a value prints as served (`formatDecimal`); a float only places a mark; sums are exact (BigInt, `charts/decimal.ts`).
- Compute nothing a module did not state. Exceptions: exact sums and counts of rows, each clearly labelled as such; the bridge sign rule in Task 7 (a use the method subtracts is drawn as a decrease, its magnitude as served); and a float that only places or orders a mark.
- Invariant 2: a vendor exception never leaves the host reader and its message is never read; a refusal is a typed code (`TablesUnavailable`: `TABLES_MALFORMED`, `TABLES_TOO_LARGE`).
- D32's bounds apply to registers unchanged: `TABLES_MAX`, `TABLE_COLUMNS_MAX`, `TABLE_ROWS_MAX`, `TABLE_ID_CHARS`, `CELL_CHARS`, `FIGURE_CHARS` in `caos/methodology/tables.py`.
- Every module under `caos/api/` keeps a correct `IO_BUDGET`; every public Python definition is named by a test (`scripts/check_tested.py`).
- No new dependency. Recharts: only the APIs `frontend/src/charts` already imports (`Bar`, `BarChart`, `CartesianGrid`, `XAxis`, `YAxis`, `Curve`, `Line`, `LineChart`, `usePlotArea`).
- Charts (`DESIGN.md` § Charts, D61): provenance in the mark (model-authored = outlined and hatched; a model line dashed, a model point hollow); a null value is a gap marked n/a with its reason, never zero; every chart has a title, one summary line and a table twin; every mark is a button named for its series, category, exact value, unit and origin, with a hit target of at least 24px, reachable by Tab and the arrow keys; no gradients, shadows or rounded ends; one value axis holding zero.
- Register figures live in `frontend/src/sections/analysis/register-figures.tsx` (from Task 5); a register is read only for its own module (`handoff.module_id`), since register ids repeat across modules.
- No invented figures for a real issuer: tests use made-up values; the demo fixtures gain no register rows (N191).
- No stub or fake value standing in for real behaviour; no catch-all that hides a failure unless the fail-open is documented and logged.
- Never loosen a gate, never add a suppression (`noqa`, `type: ignore`, `nosec`, `pragma`, skip; `tests/gate_baseline.json`).
- Never run `docker compose` (the shared test Postgres is up on 127.0.0.1:55437); never `playwright install`; never `git push`; never edit `.claude/settings.json`.
- Python through `uv run`. Postgres tests: `CAOS_TEST_POSTGRES_URL=postgresql://postgres:local-test-admin-only@127.0.0.1:55437/postgres CAOS_REQUIRE_POSTGRES=1`.
- Each task report ends with a `Not verified:` line.

## Task 1: the host reads the module's declared registers

Files: `caos/methodology/tables.py`, `tests/test_handoff_tables.py`.

Add, beside `handoff_tables`:

- `HandoffRegister` (frozen, slots): `register_id: str`, `columns: tuple[str, ...]` (the header as written), `declared: tuple[str | None, ...]` (per header cell, the profile's column the bundle binds to it, else `None`), `rows: tuple[tuple[TableCell, ...], ...]` (header order).
- `HandoffRegisters` (frozen, slots): `registers: tuple[HandoffRegister, ...]`, `unavailable_reason: TablesUnavailable | None`.
- `handoff_registers(contract: VendorContract, skill: str, module_id: str, markdown: str) -> HandoffRegisters`:
  1. `loaded = contract.completeness_check.load_contract(skill, module_id)`. Its `ValueError` (no `## Output profile`) means the module declares no registers: `HandoffRegisters((), None)`, not a refusal.
  2. `found = contract.completeness_check.find_registers(markdown, loaded["registers"], loaded.get("retired_registers", ()))`: the call `caos/qualification/matrix.py` `module_registers` and `caos/methodology/handoff.py` `_width_faults` make, so the host reads the table the acceptance check verified.
  3. Past any D32 bound (more than `TABLES_MAX` registers; a register past `TABLE_ID_CHARS`, `TABLE_COLUMNS_MAX`, `TABLE_ROWS_MAX`, or a header or cell past `CELL_CHARS`): `HandoffRegisters((), "TABLES_TOO_LARGE")`. Share one bound check with `handoff_tables` (refactor `_bounded` to take an id, columns and rows) rather than copying it.
  4. If any call in `find_registers` or `_resolve_columns` can raise `ValueError` on model text, catch it as `HandoffRegisters((), "TABLES_MALFORMED")` with a test that drives it; if none can, add no `try` and say so in the report.
  5. Registers in the order the profile declares them (`loaded["registers"]`), only those found.
  6. Cells exactly as `_table` serves a tagged table's: `TableCell(row[c], figure_value(contract, row[c]))` per header cell, header order. Share that code with `_table`.
  7. `declared`: from `contract.completeness_check._resolve_columns(spec["columns"], header)` (`{contract column: [header cells]}`), each header cell gets the contract column bound to it; a template column (one `contract.completeness_check.TEMPLATE_COLUMN_RE` matches, e.g. `Period 1…N`) binds none, so its cells keep their own header text as their key. A comment states why the private `_resolve_columns` is called: precedent (`handoff._pipe_tables` calls `cp_tables._split_row` and `_row_cells`), the bytes are pinned (invariant 4) so it cannot change without a re-pin, and it is the resolution `check()` applied at acceptance, so a figure reads the cell the gate verified.
  - The module docstring gains a paragraph on registers.

Tests (`tests/test_handoff_tables.py`, the real bundle and contract as the file's existing tests load them, `SKILL.md` bytes through `caos.methodology.bundle.verified_bytes`):
- A CP-4 answer with `### T4C.4 — Covenant headroom` over a table headed `Test | Test Type | Threshold | Current Basis | Formula | Headroom (x) | Status | Limitation | Risk Mechanic | Credit Implication | Evidence ID` and two made-up rows: served as `T4C.4`; `declared` maps `Headroom (x)` to `Headroom` and every other cell to itself; `5.00x` has value `5.00`; `[Insufficient Information] — current tested ratio` has value `None`.
- CP-1's `T4.6` (`Line Item`, `Period 1…N`) written `Line Item | FY2024 | FY2025`: `declared == ("Line Item", None, None)`.
- A register the answer does not write is absent; two written registers come back in the profile's order.
- A skill text with no output profile: `HandoffRegisters((), None)`.
- A register past `TABLE_ROWS_MAX` rows: `((), "TABLES_TOO_LARGE")`.
- Every register id every profile in `vendor/deploy-v/skills/*/SKILL.md` declares (`profile_bodies`, `load_contract`) matches `^[A-Za-z0-9_.]+$` and fits `TABLE_ID_CHARS`.

## Task 2: the wire serves them

Files: `caos/api/wire.py`, `caos/api/reads/analysis.py`, `frontend/src/wire/v1/schema.json` (regenerated: `uv run python -m caos.api.wire > frontend/src/wire/v1/schema.json`), `frontend/src/wire/v1/documents.ts`, `frontend/fixtures/analysis.json`, `frontend/fixtures/states/analysis.partial.json`, every other fixture or test builder carrying a `HandoffView`, `tests/test_wire_contract.py`, `frontend/tests/unit/wire-contract.test.ts`, `tests/test_analysis_section.py`.

- `wire.py`: `RegisterView` (closed): `register_id` (bounds and pattern as `TableView.table_id`), `columns` (as `TableView.columns`), `declared: list[CellText | None]` (max `TABLE_COLUMNS_MAX`), `rows` (as `TableView.rows`); docstring: a register the module's output profile declares, located by the bundle's own `find_registers`, `declared` the profile column the bundle binds to each header cell. `HandoffView` gains, after `tables_unavailable_reason`: `registers: list[RegisterView]` (max `TABLES_MAX`) and `registers_unavailable_reason: TablesUnavailable | None`, with a comment as `tables` has.
- `analysis.py` `_handoff_view`: when `with_tables`, also `handoff_registers(cached_contract(bundle), verified_bytes(bundle, projections.module_id, "SKILL.md").decode("utf-8"), projections.module_id, markdown)`; otherwise `[]` and `None`. A `_register_view` mapper beside `_table_view`. The comment under `BLOB_BUDGET` says registers cost no store or blob read either (the `SKILL.md` bytes are the bundle's own tree). Confirm CP-CF (the host's `MODEL_MODULE`, whose `SKILL.md` is `verified_host_bytes`) serves no registers and no refusal.
- Browser decoder `documents.ts`: `RegisterView`, the two `HandoffView` fields, the exported type, in the file's existing style.
- Fixtures: every `HandoffView` gains `"registers": []` and `"registers_unavailable_reason": null`. No register rows (N191).
- Tests: the pinned wire key sets and the browser's contract test updated; an analysis read over a seeded CP-4 handoff whose Markdown carries `T4C.4` serves it in `registers` with its `declared` columns; the Model and Book readers (`with_tables=False`) serve none; the analysis I/O budget tests still pass unchanged.

## Task 3: the bullet chart

Files: `frontend/src/charts/band.tsx`, `frontend/src/charts/types.ts`, `frontend/src/charts/BulletChart.tsx` (new), `frontend/src/charts/index.ts`, `frontend/src/charts/marks.tsx` if a shape is added there, `frontend/tests/unit/charts.test.tsx`.

- `band.tsx`: `BandSpec` gains `markers?: readonly BandMarker[]`. `BandMarker`: `key`, `category`, `at: number`, `tone`, `origin`, `gap: boolean`, `shape: "rule" | "dot"`, `name`, `readout?`, `selection`. A rule is a line across the category's band at `at`, perpendicular to the value axis, dashed for a model mark and solid for a host one; a dot is a circle, hollow for a model mark and filled for a host one. Each is reported with `Reported` (its box, so the frame's button is at least 24px), is in the keyboard order after its category's bars, and counts in `extentOf`. A marker with `gap` draws the existing `GapMark` n/a in its row, with its name.
- `types.ts`: `BulletRow` = `{ key; label; direction: "max" | "min" | null; threshold: Datum; current: Datum; headroom: Datum; origin: Origin }`.
- `BulletChart({ title, summary, unit, rows, categoryLabel, onSelect })`: horizontal `bandPlot`, one category per row, labelled with the row and its direction ("ceiling", "floor", or "direction not stated"); the current basis a bar from zero (`series-1`, the row's origin, its exact value as label); the threshold a `rule` marker (`neutral`). Headroom is not drawn and never computed: it prints as served in the marks' names and readouts and in the table twin. Names: `<label>: current basis <value unit> against a <ceiling|floor|threshold> of <value unit>, headroom <served text> (<origin word>)`, n/a with the reason for a null. Table twin columns: `[categoryLabel ?? "Test", "Direction", "Threshold, <unit>", "Current basis, <unit>", "Headroom, <unit>", "Origin"]`. Legend: "Current basis" (fill), "Threshold" (line).
- Tests: names, gaps with their reasons, the table twin's exact cells, the keyboard order (bar, then marker, row by row), a marker's hit box at least 24px.

## Task 4: the range strip

Files: `frontend/src/charts/RangeStripChart.tsx` (new), `frontend/src/charts/types.ts`, `frontend/src/charts/index.ts`, `frontend/src/charts/marks.tsx` and `types.ts` `LegendEntry` if a dot swatch is needed, `frontend/tests/unit/charts.test.tsx`.

- `RangeRow` = `{ key; label; min?: Datum; q1?: Datum; median?: Datum; q3?: Datum; max?: Datum; marker?: Datum; origin: Origin }`. A statistic absent from the row is one the register does not declare: nothing is drawn for it and its twin cell is empty. A statistic present with a null value is a gap with its reason.
- `RangeStripChart({ title, summary, unit, rows, markerLabel = "Borrower", categoryLabel, onSelect })`: horizontal `bandPlot`, one row per metric: the interquartile range a floating bar Q1 to Q3 (`series-1`): an interval, not a magnitude, so it floats as a bridge's steps do; min, median and max `rule` markers (`neutral`); the marker (the borrower, or CP-1C T4.10's implied EV) a `dot` marker (`series-3`); a thin non-interactive line from min to max at the row's centre. A null Q1 or Q3 makes the bar a gap; a null marker is a gap; each with its reason. Rows without quartiles draw no bar.
- Names say the statistic, the metric, the exact value and unit, and the origin. Table twin: `[categoryLabel ?? "Metric", "Min", "Q1", "Median", "Q3", "Max", markerLabel, "Origin"]`, the columns of statistics no row carries left out, exact. Legend: "Interquartile range" (fill, when drawn), "Min, median, max" (line), the marker label (dot).
- Tests as Task 3's.

## Task 5: covenant headroom and peer ranges

Files: `frontend/src/sections/analysis/register-figures.tsx` (new), `frontend/src/sections/analysis/figures.tsx`, `frontend/tests/unit/register-figures.test.tsx` (new), `frontend/tests/unit/figures.test.tsx`.

- The register figures live in `register-figures.tsx`, beside the tagged tables' `figures.tsx` (which exports what both share: `Figure`, `oversized`, `sumOf`, the cell readers); `figuresOf` calls its `registerFigures(handoff)`. Thirty figures would triple `figures.tsx`.
- `registerRows(handoff, moduleId, registerId)`: `null` unless `handoff.module_id === moduleId` and the register is served (register ids repeat across modules: `T4.6` is CP-1's, CP-1B's and CP-1C's); else its rows keyed by `declared[i] ?? columns[i]`.
- A row's unit: the suffix its figure cell's text ends in, `x` or `%`, past any trailing citation markers (`[C1]`), else none. Rows of one unit share a figure (one value axis); a figure per unit in first-appearance order; its title carries the unit.
- `covenantHeadroom(handoff): Figure[]`: CP-4 `T4C.4`, one `BulletRow` per row: label `Test`; direction from `Test Type`, trimmed and casefolded, through the aliases `vendor/deploy-v/skills/cp-4-legal-covenant-interpreter/scripts/covenant_headroom.py` `TEST_TYPE_ALIASES` names (restated with a comment pointing there): `max-ratio`, `max_ratio`, `maximum`, `maintenance`, `ceiling`, `incurrence-max` → `max`; `min-ratio`, `min_ratio`, `minimum`, `coverage`, `floor`, `incurrence-min` → `min`; anything else `null`, never inferred from the test's name. Threshold, current basis and headroom from `Threshold`, `Current Basis`, `Headroom`. Unit from `Current Basis`, else `Threshold`. Summary: each test's headroom as served. Source: `Formula`, `Status`, `Evidence ID`.
- `peerRanges(handoff): Figure[]`: CP-1C `T4.6`, one `RangeRow` per `Metric` from `Min`, `Q1`, `Median`, `Q3`, `Max`, and `Borrower Value` as the marker; unit from `Borrower Value`, else `Median`. Summary: each metric's borrower value and `Borrower Position` as served. Source: `Peer Avg` and `N`, as served.
- `Figure` gains kinds `"bullet"` and `"range"` and their rows; `Chart` draws them; `ModelKey` keys a rule and a dot when drawn.
- `figuresOf`: register figures after the table figures. `tables_unavailable_reason` withholds the table figures only and `registers_unavailable_reason` the register figures only; the note names each reason present (`data-tables-unavailable`, `data-registers-unavailable`).
- Tests: made-up values; the five fixture-free cases: a ceiling, a floor, an unknown direction, a null threshold, two units splitting into two figures; peer ranges with a null quartile; a register of another module's id draws nothing.

## Task 6: the EBITDA quality bridge

Files: `frontend/src/charts/types.ts`, `frontend/src/charts/WaterfallChart.tsx`, `frontend/src/sections/analysis/register-figures.tsx`, `frontend/tests/unit/charts.test.tsx`, `frontend/tests/unit/register-figures.test.tsx`.

- `WaterfallStep` gains `color?: ChartColor`, overriding the pole's tone for that step, and `status?: string`, the word the colour stands for: it is in the step's accessible name and its table-twin row (colour is never the only carrier). `WaterfallChart` gains `statuses?: readonly { color: ChartColor; label: string }[]`: given, they replace the Increase and Decrease legend entries.
- `ebitdaQuality(handoff)`: CP-1D `T1D.4` (`Step`, `Amount`, `Basis`, `Supported / Challenged / Rejected`, `Cumulative EBITDA`, `Evidence ID`). The first row is the opening total (its `Amount`, else its `Cumulative EBITDA`); a later row with an `Amount` figure is a delta, as served; a later row with no `Amount` figure but a `Cumulative EBITDA` figure is a stated total; a row with neither is a delta gap carrying its `Amount` text. When the last row is a delta and states a `Cumulative EBITDA`, a closing total "Cumulative EBITDA" follows. Status: `Supported` → `positive`, `Challenged` → `series-3`, `Rejected` → `negative`, `Insufficient Information` → `series-4` (exact, after trim, case-insensitive); anything else no colour. The CP-1D schema's empty bridge (one row whose `Step` is `NONE`) draws nothing. Title "EBITDA quality bridge". Source: `Basis`, `Evidence ID`.
- Reading order: with the other register figures, after the table figures (a handoff is one module's, so it draws no CP-1 figure beside it).

## Task 7: the liquidity bridge and the value allocation

Files: `frontend/src/sections/analysis/register-figures.tsx`, `frontend/tests/unit/register-figures.test.tsx`.

- An exact sign helper: a decimal string's magnitude negated (`"800"` and `"-800"` both give `"-800"`, `"0"` gives `"0"`), no float.
- `liquidityBridge(handoff)`: CP-2D `T2E.5` (`Bridge Item`, `Amount`, `Source / Calculation`, `Status`, `Credit Comment`, `Source Trace`). A row whose `Bridge Item`, trimmed and casefolded, starts with `beginning accessible liquidity` or `ending accessible liquidity` is a stated total; one that starts with `cash interest`, `cash taxes`, `mandatory capex`, `debt amortization`, `debt amortisation` or `other cash uses` is a use the method subtracts (`REF_CP-2D_STEPS.md` step 05 instruction 5; `liquidity_bridge.py`), drawn as its magnitude negated; every other row is a delta as served. Rows before the beginning total bridge from zero (beginning cash and revolver availability). Title "Liquidity bridge, 12 months". Summary: beginning to ending accessible liquidity, as served. Source: `Source / Calculation`, `Status`, `Source Trace`.
- `valueAllocation(handoff)`: CP-4C `T4E.5` (`scenario`, `entity`, `available value`, `priority claim`, `allocation`, `residual`, `legal evidence ID`), one waterfall per scenario and entity in first-appearance order: opening total "Available value" (the group's first row's `available value`), a step per row labelled by `priority claim`, its `allocation`'s magnitude negated, and a closing total "Residual" (the group's last row's `residual`). Fulcrum: the `T4E.6` row whose `scenario/EV range`, casefolded, starts with the scenario, casefolded; its `fulcrum class/range` is named in the summary, and the step whose `priority claim`, casefolded, starts its text gets " (fulcrum)" on its label. Title `Value allocation, <scenario>`, with `, <entity>` when the scenario has more than one entity.
- Reading order: with the other register figures, after the table figures.

## Task 8: the adjusted-debt bridge and implied EV ranges

Files: `frontend/src/sections/analysis/register-figures.tsx`, `frontend/tests/unit/register-figures.test.tsx`.

- `adjustedDebtBridge(handoff)`: CP-1D `T1E.3` (`Step`, `Amount`, `Basis`, `Cumulative Adjusted Debt`, `Evidence ID`), read as Task 6 reads `T1D.4`, with `Cumulative Adjusted Debt` as the stated running level and no status colour (the register has no status column). One function serves both bridges, parameterised by the cumulative column and an optional status column: not a copy. Title "Adjusted debt bridge"; the empty-bridge `NONE` row draws nothing. Source: `Basis`, `Evidence ID`.
- `impliedEv(handoff)`: CP-1C `T4.10` (`Method`, `Multiple Source`, `Multiple Value`, `Borrower Metric`, `Period`, `Implied EV`, `Low`, `Median`, `High`, `Calc Status`, `Limitations`): a `RangeRow` per row labelled by `Method`: `min` = `Low`, `median` = `Median`, `max` = `High`, `marker` = `Implied EV` (`markerLabel` "Implied EV"), no quartiles. Unit and grouping as Task 5. Title "Implied enterprise value by method". Summary: each method's implied EV as served. Source: `Multiple Source`, `Multiple Value`, `Borrower Metric`, `Period`, `Calc Status`.

## Task 9: stacks by a second key, and maturity walls

Files: `frontend/src/sections/analysis/figures.tsx` (the maturity wall's core), `frontend/src/sections/analysis/register-figures.tsx`, `frontend/tests/unit/figures.test.tsx`, `frontend/tests/unit/register-figures.test.tsx`.

- Extract from CP-1's `maturityLadder` a stack builder: rows, a category key, a series key and an amount cell, giving a `StackedBarChart` figure whose segment is the exact sum of its rows' amounts (`sumOf`); a category and series with no row is zero, one whose every row's amount is unstated is a gap; each segment's source names every row it sums. `maturityLadder` then uses it, unchanged in output (its tests stand).
- `liquiditySources(handoff)`: CP-2D `T2E.2`: categories `Accessibility Status`, series `Liquidity Component`, amount `Source-Supported Amount`. Title "Liquidity by accessibility". Source: `Source Trace`, `Limitation / Restriction`.
- `cashUses(handoff)`: CP-2D `T2E.3`: categories `Timing`, series `Mandatory / Discretionary`, amount `Amount`. Title "Cash uses by timing". Source: each summed `Cash Use` and its `Source Trace`.
- `rateMix(handoff)`: CP-2E `T2F.2`: one figure per `Currency` (an amount in one currency never shares an axis with another's), categories `Fixed / Floating`, series `Debt Instrument`, amount `Amount`, unit the currency. Title "Fixed and floating debt, <currency>". Source: `Base Rate`, `Margin / Coupon`, `Hedge Status`, `Source Trace`.
- `refinancingWall(handoff)`: CP-3C `T3D.2`: one figure per `Currency`, categories the year of `Maturity Date` (`Undated` when it has none, as CP-1's), series `Seniority / Lien`, amount `Amount`. Title "Maturities by seniority, <currency>". Summary as CP-1's maturity wall.
- Categories in first-appearance order, except years, which sort.

## Task 10: grouped and stacked registers of CP-3C, CP-4 and CP-4C

Files: `frontend/src/sections/analysis/register-figures.tsx`, `frontend/tests/unit/register-figures.test.tsx`.

- `lmeExposure(handoff)`: CP-3C `T3D.8`: grouped bars (`BarChart`), categories `Creditor Class`, series Base, Stress and LME from `Exposure: Base Case`, `Exposure: Stress Case`, `Exposure: LME Case`, values as served; grouped by unit (Task 5's rule over the three cells). Title "Exposure by case". Source: `Recovery Implication`, `Priming / Subordination Risk`, `Source Trace`.
- `basketCapacity(handoff)`: CP-4 `T4C.5`: `StackedBarChart`, categories `Basket / Test`, series `Usage` and `Remaining Capacity`, values as served; grouped by unit. `Estimated Capacity` is named in the source, never drawn or checked against the two. Title "Baskets, used and remaining". Source: `Estimated Capacity`, `Status`, `Severity`, `Evidence ID`.
- `recoveryByClass(handoff)`: CP-4C `T4E.7`: grouped bars, one figure per `scenario` and `currency`, categories `class/instrument`, series `allowed claim` and `total recovery`. The packed `cash/debt/equity/warrant value` is not drawn (N192). Title "Recovery by class, <scenario>". Source: `timing`, `cash/debt/equity/warrant value` as served.
- CP-4C `T4E.2` draws nothing: its one amount column, `principal/accrued/PIK`, packs three figures (N192). A test says so.

## Task 11: forecast and credit-path lines

Files: `frontend/src/sections/analysis/register-figures.tsx`, `frontend/tests/unit/register-figures.test.tsx`.

- One helper: rows with `period` and `case` columns and a list of metric columns, giving one `LineChart` figure per metric, categories the periods in first-appearance order, series the cases (BASE, then DOWNSIDE, then the rest, matched trimmed and case-insensitive, as `forecastDrivers` orders them), values as served, each figure's unit its metric cells' suffix.
- `forecastCases(handoff)`: CP-2G `T2H.4`, metrics `revenue`, `EBITDA`, `FCF`. Titles "Revenue, base and downside" and so on. Source: `evidence/assumption IDs`.
- `creditPath(handoff)`: CP-2G `T2H.6`, metrics `gross/net leverage`, `coverage`, `FCF/debt`. A packed cell (`4.2x / 3.9x`) is a gap carrying its text (N192). Source: `definition IDs`.

## Task 12: tornadoes and rating-trigger bullets

Files: `frontend/src/sections/analysis/register-figures.tsx`, `frontend/tests/unit/register-figures.test.tsx`.

- A tornado is a `DivergingBarChart` whose categories run by the size of their value, largest first (a float orders marks, never states one), gaps last; grouped by unit.
- `rateSensitivities(handoff)`: CP-2E `T2F.5`: categories `Sensitivity`, value `Estimated Cash Impact`. Title "Rate and FX sensitivities". Source: `Formula`, `Status`, `Source Trace`.
- `downsideSensitivities(handoff)`: CP-2A `T2B.6`: categories `Sensitivity`, value `Result`. Title "Downside sensitivities". Source: `Formula / Method`, `Status`, `Source Trace`.
- `scenarioMoves(handoff)`: CP-3D `T3E.8`: one figure per `scenario`, categories `driver`, value `calculated move`. Title "Scenario moves, <scenario>". Source: `spread/yield/price assumption`, `convexity/call limitation`.
- `ratingTriggers(handoff)`: CP-2H `T2R.4`: one `BulletChart` figure per `agency` (and unit): a row per row labelled `<metric> (<rating type>)`, threshold `threshold`, current basis `case/period value` (packed: a gap with its text, N192), headroom `headroom` as served. Direction from `trigger direction` only for the values CP-2H's references declare that name a ceiling or a floor (the implementer lists that vocabulary, with file:line, in the report); any other value is `null`. Title "Rating triggers, <agency>". Source: `status`.

## Task 13: scores

Files: `frontend/src/sections/analysis/register-figures.tsx`, `frontend/tests/unit/register-figures.test.tsx`.

- Horizontal `BarChart` figures, values as served, the summary naming the highest and the lowest (a float orders them):
  - CP-3 `T3.3`: categories `Factor`, value `Weighted Score`. Title "Weighted factor scores". Source: `Category`, `Weight`, `Raw Score 1–5`, `Confidence`.
  - CP-3 `T3.7`: categories `<Issuer> <Security / Tranche>` in `Rank` order (a rank that is not a number last), value `Composite Score /100`. Title "Composite score /100". Source: `Credit Tier`, `Final Recommendation`.
  - CP-4 `T4.11`: categories `Area`, value `Score 1–5`. Title "Legal area scores, 1 to 5". Source: `Confidence`, `Evidence ID`.
  - CP-6 `T6A.6`: categories `Dimension`, value `Score (1-5)`. Title "Debate scores by dimension, 1 to 5". Source: `Chair Assessment`.

## Task 14: the dumbbell

Files: `frontend/src/charts/DumbbellChart.tsx` (new), `frontend/src/charts/types.ts`, `frontend/src/charts/index.ts`, `frontend/tests/unit/charts.test.tsx`, `frontend/src/sections/analysis/register-figures.tsx`, `frontend/tests/unit/register-figures.test.tsx`.

- `DumbbellRow` = `{ key; label; from: Datum; to: Datum; origin }`. `DumbbellChart({ title, summary, unit, rows, fromLabel, toLabel, categoryLabel, onSelect })`: horizontal `bandPlot`, a row per metric: two `dot` markers (from `neutral`, to `series-1`) and a thin non-interactive line between them; gaps as Task 3's. Table twin `[categoryLabel ?? "Metric", fromLabel, toLabel, "Origin"]`. Legend: the two dots.
- `expectedRealised(handoff)`: CP-8 `T7.4`: a row per `Metric`, from `Expected` to `Realized`; grouped by unit. Title "Expected against realised". Summary: each metric's `Variance (direction + magnitude)` as served. Source: `Variance (direction + magnitude)`, `Confidence`, `Evidence ID`.

## Task 15: the spread curve

Files: `frontend/src/charts/ScatterChart.tsx` (new), `frontend/src/charts/types.ts`, `frontend/src/charts/index.ts`, `frontend/tests/unit/charts.test.tsx`, `frontend/src/sections/analysis/register-figures.tsx`, `frontend/tests/unit/register-figures.test.tsx`. Declared input: `.superpowers/sdd/2026-10-10-n94-registers-five-charts/recharts-scatter-docs.md` (Recharts `ScatterChart`, `Scatter`, new to this repo; confirm every prop against `frontend/node_modules/recharts/types`).

- `ScatterPoint` = `{ key; label; at: string; value: Datum; group: string; origin }`, `at` a date as served. `ScatterChart({ title, summary, unit, points, xLabel, onSelect })`: a time axis placed from each `at` (a float only places a mark; ticks label years) against a value axis holding zero; a point per `ScatterPoint`, hollow for a model one, coloured by `group` (series colours by first appearance, neutral past the fifth); a point without a readable date or value is not placed and is listed in the table twin with its reason, and the caption counts them. Marks as every chart's (buttons, 24px, keyboard order by date).
- `spreadCurve(handoff)`: CP-3D `T3E.3`: a point per row, label `security_id`, `at` `maturity/call date`, value `spread/yield`, group `seniority`. Title "Spread against maturity". Source: `curve residual`, `explanation status`.

## Task 16: the probability and impact matrix

Files: `frontend/src/charts/RiskMatrix.tsx` (new), `frontend/src/charts/index.ts`, `frontend/tests/unit/charts.test.tsx`, `frontend/src/sections/analysis/register-figures.tsx`, `frontend/tests/unit/register-figures.test.tsx`.

- `RiskMatrix({ title, summary, events, onSelect })`, events `{ key; label; description; probability; impact; classification; origin }`: a grid of Probability (High, Medium, Low, Unknown, top to bottom) against Impact (Low, Medium, High, Unknown, left to right), the ordinal labels `REF_CP-2B_STEPS.md` step 05 declares, matched trimmed and case-insensitive; any other text counts as Unknown and keeps its text in the names. A cell holding events is a mark (a button at least 24px) printing its count and named with both labels, the count and the event ids; an empty cell is drawn and is not a mark. Drawn as SVG through `ChartFrame`'s `plot`, a grid Recharts has no chart for (no Recharts API beyond those already imported). Table twin: `Event ID`, `Description`, `Probability`, `Impact`, `P/I Classification`.
- `riskMatrix(handoff)`: CP-2A `T5.4`. Title "Probability and impact". Summary: the High/High count as served from the rows, and their ids.

## Task 17: counts in the Audit tab

Files: `frontend/src/sections/analysis/register-figures.tsx`, `frontend/src/sections/analysis/module.tsx`, `frontend/tests/unit/register-figures.test.tsx`, `frontend/tests/unit/analysis.test.tsx`.

- `auditCounts(handoff): Figure[]`, drawn in the module's Audit tab as a group "Counts" (`module.tsx`, after its existing groups), with the same mark-press handling the Figures use:
  - CP-5 `T5.9` (the Issue Log, which consolidates T5.2–T5.8, so those are not counted again): `StackedBarChart`, categories `Module`, series `Severity`, each segment the count of rows, an exact integer. Title "Issues by module and severity, count".
  - CP-L10 each `TL*.2` the answer writes (`TL10.2`, `TL20.2`, `TL23.2`, `TL30.2`, `TL40.2`): categories `materiality`, series `disposition`, counts. Title "Topics by materiality, count (<register id>)".
- A count is the one figure computed here, and every title says it is a count.

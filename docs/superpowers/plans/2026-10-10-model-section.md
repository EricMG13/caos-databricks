# Model section: implementation plan (Plan 2 of 4)

> **For agentic workers:** REQUIRED SUB-SKILL: use superpowers:subagent-driven-development to implement this plan task by task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** serve Plan 1's `CreditModel` as the Model section: a credit-workbook grid with a chart strip and per-cell passports. It's backed by a desk rate deck that an `ADMIN` saves and every run pins at creation.

**Architecture:**
- A new global table, `rate_decks`, holds immutable decks; `run_rate_decks` pins one per run in the run-start transaction.
- The Model read assembles `ModelInputs` from the accepted CP-1, CP-2G and CP-CF handoffs plus the pinned deck, calls `credit_model()`, and serves a closed v1 wire shape.
- The frontend replaces `ModelSection` with a grid built from the existing table CSS (`tbl dense`, `.tscroll`, `pin-first`), plus sticky headers.

**Tech stack:** FastAPI and Pydantic (wire), psycopg (store), React 19 and react-router 7.18.3, Vitest, Playwright, axe.

**Spec:** `docs/superpowers/specs/2026-10-10-book-model-redesign-design.md` (M1–M14, row economy, layout rule); worked example `docs/superpowers/specs/2026-10-10-model-layout-example.html`.

## Global constraints

- Everything in Plan 1's Global Constraints applies (gates, suppressions only fall, Decimal, vocabulary, no PR and no merge until N94 merges, commit trailer, the "no stub, no catch-all" rule, and `Not verified:`).
- **Wire:** `caos/api/wire.py` models are closed (`_CLOSED`). Regenerate `frontend/src/wire/v1/schema.json` with `uv run python -m caos.api.wire > frontend/src/wire/v1/schema.json`. Mirror each new or changed model by its exact backend name in `frontend/src/wire/v1/documents.ts` (`V1_SHAPES`) or `commands.ts` (`V1_COMMAND_SHAPES`). Update `PINNED` in `tests/test_wire_contract.py:119` and the command count at `:828`.
- **Routes:** every route is identity-first (`dependencies=[IDENTITY_FIRST]`) and is listed in `tests/test_api_routes.py:1065`.
- **I/O budget:** every `caos/api/**` module declares `IO_BUDGET` (≤ 1024). Measured modules are ratcheted in `tests/io_measurements.json`.
- **Refusals:** a new `RefusalCode` needs `CLEARS` (`wire.py:168`) and `_STATUS` (`caos/api/app.py:146`).
- **Migrations:** add `caos/store/0050_*.sql` and append it to `MIGRATIONS` (`caos/store/__init__.py:27-258`).
- **CSP** is `style-src 'self'`: no inline `<style>`, no `innerHTML`, no new UI dependency.
- **Frontend gates:** `npm --prefix frontend run lint|typecheck|test|build|build:demo|a11y|test:workbench`. `scripts/check-tested.mjs` requires every runtime export to be named in a test.

---

### Task 1: rate deck store, admin command and run pin

**Agent:** `mx-invariants` (the deck is pinned inside run creation's transaction, so ordering matters).

**Files:**
- Create `caos/store/0050_rate_decks.sql`, `caos/store/rate_decks.py`, `caos/api/commands/rate_decks.py` and `caos/api/reads/rate_decks.py`.
- Modify `caos/store/__init__.py` (`MIGRATIONS`), the run-start path in `caos/store/runs.py` (`start_run`: pin the latest deck), `caos/api/wire.py`, `caos/api/app.py` (register the routers), `frontend/src/wire/v1/schema.json`, `frontend/src/wire/v1/commands.ts` and `documents.ts`.
- Tests: `tests/test_rate_decks.py` and the `tests/test_api_routes.py` route list.

**Schema:**

```sql
CREATE TABLE rate_decks (
  deck_id     uuid PRIMARY KEY,
  as_of       date NOT NULL,
  saved_by    uuid NOT NULL,
  saved_at    timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE rate_deck_rates (
  deck_id        uuid NOT NULL REFERENCES rate_decks(deck_id),
  reference_rate text NOT NULL CHECK (reference_rate IN ('SOFR','TERM_SOFR','EURIBOR','SONIA')),
  year_offset    integer NOT NULL CHECK (year_offset BETWEEN 1 AND 5),
  base_rate      numeric NOT NULL CHECK (base_rate > -1 AND base_rate < 1),
  downside_rate  numeric NOT NULL CHECK (downside_rate > -1 AND downside_rate < 1),
  PRIMARY KEY (deck_id, reference_rate, year_offset)
);
CREATE TABLE run_rate_decks (
  run_id  uuid PRIMARY KEY REFERENCES runs(run_id),
  deck_id uuid NOT NULL REFERENCES rate_decks(deck_id)
);
```

Add an immutability trigger on all three tables, rejecting UPDATE and DELETE, in the style of `run_inputs` (find its trigger in the existing migrations and copy the pattern).

**Behaviour:**
- **Save:** `POST /api/v1/rate-decks` with body `SaveRateDeck{as_of: date, rates: list[RateDeckRateView{reference_rate, year_offset, base_rate: decimal-string, downside_rate: decimal-string}]}`.
  - Only a global `ADMIN` may save (`at_least(actor.role, GlobalRole.ADMIN)`). Anyone else is refused as not found, following `commands/qualification.py:66-84`.
  - Rates are decimals (`0.0380`), at most 1–20 rows, with no duplicate (reference_rate, year_offset).
  - The receipt is `RateDeckSaved{deck_id}`, under `NIL_SCOPE` (`store/commands.py:42`), idempotent by key.
  - There's no case audit chain (the deck is global). Log `rate_deck_saved deck_id=<id> rows=<n>` with no rates in the log line.
- **Read:** `GET /api/v1/rate-decks/latest` returns `RateDeckView{deck_id, as_of, saved_at, rates}` or `null`. Any signed-in user may read it.
- **Pin:** `start_run` inserts `run_rate_decks(run_id, latest deck_id)` in the same transaction when a deck exists. With no deck, nothing is inserted.
- **Store API:** `latest_deck(conn) -> RateDeck | None`, `deck_for_run(conn, run_id) -> RateDeck | None` and `save_deck(conn, actor_id, as_of, rates) -> UUID`. Each returns Plan 1's `caos.calculators.credit_model.projection.RateDeck` (convert `year_offset` to `RateDeckYear.fiscal_year_offset`).

- [ ] **Step 1:** Write the failing tests (Postgres, using the `empty_database` and `case` fixtures in `tests/conftest.py`):
  - `test_an_admin_saves_a_deck_and_it_reads_back_as_latest`
  - `test_a_non_admin_save_is_refused_as_not_found`
  - `test_a_saved_deck_cannot_be_updated_or_deleted`
  - `test_a_run_pins_the_latest_deck_at_creation_and_keeps_it_after_a_newer_save`
  - `test_a_run_created_with_no_deck_pins_none`
  - `test_duplicate_rate_rows_are_refused`
- [ ] **Step 2:** Run `CAOS_REQUIRE_POSTGRES=1 uv run pytest tests/test_rate_decks.py -q` and expect FAIL.
- [ ] **Step 3:** Implement the migration, store, command, read and wire models, then regenerate the schema and mirror the TypeScript shapes.
- [ ] **Step 4:** Expect PASS. Then run the full gates, including `tests/test_wire_contract.py`, `tests/test_api_routes.py` and `tests/test_postgres_races.py`.
- [ ] **Step 5:** Commit: `Rate deck: admin-saved immutable decks, pinned per run at creation`.

---

### Task 2: Model read v2 (backend wire and assembly)

**Agent:** `mx-autonomous` (multi-file: read, wire, inputs and fixtures).

**Files:**
- Modify `caos/api/reads/model.py` (rewrite), `caos/api/wire.py` (replace `ModelBody`'s contents and add the line, column and cell views), and `tests/test_model_section.py`.
- Modify `frontend/src/wire/v1/documents.ts` and `schema.json`.

**Wire** (closed models; decimals as strings matching `^-?[0-9]+(\.[0-9]+)?$`):

```python
class ModelSourceView(BaseModel): source_id: str; source_locator: str; citation: CitationView | None   # citation resolved from the CP-1 handoff's [C<n>] marker
class ModelCellView(BaseModel): value: DecimalText | None; reason: Literal[...Plan 1 Reason...] | None; basis: Literal[...Plan 1 Basis...] | None
                                stated: DecimalText | None; note: str | None; sources: list[ModelSourceView]
class ModelColumnView(BaseModel): column_id: str; kind: Literal["QUARTER","PYTD","YTD","FY","LTM","PF_LTM","PROJECTED"]; label: str
                                  period_id: str | None; fiscal_year: str; end_date: str | None; days: int | None; case: Literal["BASE","DOWNSIDE"] | None
class ModelTermsView(BaseModel): reference_rate: str; spread_or_coupon: str; floor: str; maturity: str; amortisation: str
class ModelLineView(BaseModel): line_id: str; band: str; label: str; kind: Literal["ACCOUNT","SUBTOTAL","RATIO","MEMO","PF","GROWTH"]
                                unit: Literal["MONEY","PERCENT","MULTIPLE","DAYS","COUNT","RATE","KPI"]; unit_label: str | None
                                rank: str | None; terms: ModelTermsView | None; cells: list[ModelCellView]
class ModelBody(BaseModel): case_id: UUID; latest_run_id: UUID | None; displayed_run_id: UUID | None; displayed_run_status: RunStatus | None
                            subject: RunSubjectView | None; currency: str | None; unit: str | None; exclude_unrealised: bool
                            rate_deck: RateDeckRefView | None   # {deck_id, as_of}
                            columns: list[ModelColumnView]; lines: list[ModelLineView]; limitations: list[str]
                            forecast: ModelForecast | None      # kept: the accepted CP-CF record, shown in the passport for comparison
```

Bounds: columns ≤ 64, lines ≤ 400, cells == len(columns) per line (assert in a `model_validator`), sources ≤ 8 per cell.

**Read** (`GET /api/v1/cases/{case_id}/model?run=&exclude_unrealised=`):
1. `read_analysis_without_tables(AnalysisQuery(...))` (unchanged authorisation for now; Plan 3 adds the desk-wide grant).
2. Pick the accepted handoffs by `module_id`: `CP-1`, `CP-2G`, `CP-CF`.
3. No accepted CP-1 means `observed_empty=True`, with empty columns and lines and the note `HANDOFFS_PENDING` (spec M1).
4. Otherwise build `ModelInputs`:
   - `cp1_registers(handoff_tables(cached_contract(bundle), cp1.model_analysis).tables)`;
   - CP-2G growth and slots from the same calls on the CP-2G and CP-1 handoffs;
   - `request` = `forecast_inputs(cpcf.model_analysis)[0]` when CP-CF is accepted, otherwise `None` (no projection columns, with a limitation noting "No projections: this route did not run CP-2G/CP-CF");
   - `deck = deck_for_run(conn, run_id)`, and `exclude_unrealised` from the query.
5. `model = credit_model(inputs)`. Map it 1:1 to the wire. A `SourceRef` whose `cell_text` contains `[C<n>]` resolves `citation` to the CP-1 handoff's `source_facts` entry with `marker == "C<n>"`; with none, `citation` is null.
6. Add the limitation "PIK notes carry only their cash coupon in the rate terms; PIK interest is not modelled" whenever a facility's `margin_or_coupon` mentions PIK (case-insensitive).
7. Keep `accepted_forecast()` for `forecast`. Its `pinned_live_sources` refusal (`ARTIFACT_RECORD_MISMATCH`) still applies to the whole read (spec B8).
8. **`IO_BUDGET`:** `analysis.IO_BUDGET + PIN_IO + 1` (the deck read). Recompute and update `tests/io_measurements.json` by measurement, never by guess.

- [ ] **Step 1:** Write the failing tests in `tests/test_model_section.py`. Reuse the harness helpers it already imports (`_complete`, `route`, `harness`, `_as`).
  - `test_a_run_with_cp1_serves_columns_and_lines_in_layout_order`
  - `test_a_run_without_cp1_is_observed_empty_with_handoffs_pending`
  - `test_a_route_without_cp_cf_serves_history_only_with_a_limitation`
  - `test_projection_interest_uses_the_runs_pinned_deck_not_a_newer_one`
  - `test_exclude_unrealised_changes_adjusted_ebitda`
  - `test_a_marker_resolves_to_the_cp1_citation`
  - `test_every_line_has_one_cell_per_column`
  - `test_the_model_reads_within_its_declared_io_budget`
  - Also keep or adapt the existing `ARTIFACT_RECORD_MISMATCH` test.
- [ ] **Step 2:** Expect FAIL.
- [ ] **Step 3:** Implement, regenerate the schema, mirror `documents.ts`, and update `PINNED`.
- [ ] **Step 4:** Expect PASS. Run all backend gates and `npm --prefix frontend run typecheck && npm --prefix frontend run test -- wire-contract`.
- [ ] **Step 5:** Commit: `Model read v2: the credit model grid on the v1 wire`.

---

### Task 3: Model grid UI

**Agent:** `mx-feature`. It's UI wiring against a fixed wire, and the design is fixed by the worked example.

**Files:**
- Rewrite `frontend/src/sections/model/ModelSection.tsx`.
- Create `frontend/src/sections/model/ModelGrid.tsx`, `frontend/src/sections/model/grid.ts` (pure helpers) and `frontend/src/sections/model/ChartStrip.tsx`.
- Modify `frontend/src/styles/caos.css` (grid classes under `@layer components`).
- Rewrite `frontend/fixtures/model.json` to the new wire. Generate it from the worked example via a committed script, `frontend/scripts/model-fixture.mjs`, or by hand from the example HTML values. Either way it must parse with `parseModelDocument`.
- Test: `frontend/tests/unit/model.test.tsx` (rewrite).

**Behaviour** (spec M2, M3, row economy):
- Header rows are **column groups** (Quarters · YTD · FY · LTM · Base case · Downside case), each collapsible, then the column labels.
  - By default it shows the last 4 quarters, the last 3 FYs and everything else.
  - Group state lives in the URL query `mcols=` (comma-separated collapsed groups) via `useSearchParams` with `{replace: true}`.
- **Bands** are collapsible `<tbody>` groups with a band header row (a `<button aria-expanded>`).
- **Debt rank** header rows have an 8px spacer above them. Facility terms render in five narrow left columns, shown only inside the debt band (other rows leave them empty).
- **The first column is pinned** (`pin-first` inside `.tscroll` with `tabIndex={0} role="region" aria-label="Model grid"`), and both header rows are sticky (`position: sticky; top: 0` and the measured row height, set by a CSS custom property on the table via a class, not an inline style).
- **Row hiding** (row economy): `hiddenLine(line)` is true when every cell's value is null or zero **and** `line.terms === null`. Facilities always show.
- **Cells:** a `ModelCellButton` reusing `MetricCell`'s pattern (`button.cellbtn`) opens `openPassport` with the value, basis, stated value, note, sources (citation → evidence) and, for projected interest, the WA rate and deck. A null value shows `n.p.`, `n.a.` or `n.s.` per reason, with the reason spelled out in `title` and the passport.
- **Formatting:**
  - MONEY: `displayDecimal(value, 0)`, negatives in parentheses;
  - PERCENT: `hundredfold`, 1 dp, with `%`;
  - MULTIPLE: 1 dp with `x`;
  - DAYS: 0 dp;
  - RATE: 2 dp with `%`.

  The exact value goes in `title`.
- **Shading:** PF and projected columns are tinted via classes (`.col-pf`, `.col-base`, `.col-down`), and a refinanced facility cell gets `.cell-refi`. The tokens come from `tokens.css` (add `--pf`, `--base`, `--down`, `--refi` for light and dark).
- **Chart strip:** three small `LineChart`s from `src/charts` showing adjusted net leverage, adjusted interest coverage and liquidity. Historical points are the FY and LTM columns; Base and Downside are two projected series.
- **Header row:** currency and unit, "rate deck <as_of>" or "no rate deck", an "Exclude unrealised add-backs" checkbox (`<input type="checkbox">`, URL query `exclude_unrealised=1`, which refetches via the Workspace's query), and the limitations list as `NoteRows` (existing component, F400).

- [ ] **Step 1:** Write the failing tests in `frontend/tests/unit/model.test.tsx`:
  - `hides a line whose cells are all zero or null unless it is a facility`
  - `renders band headers that collapse their rows`
  - `collapsing a column group writes mcols to the URL`
  - `formats money in brackets and multiples with x`
  - `a cell opens the passport with its stated value and sources`
  - `the debt band shows facility terms in their own columns`
  - `the fixture parses with parseModelDocument`
- [ ] **Step 2:** Run `npm --prefix frontend run test -- model` and expect FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Expect PASS. Run `npm --prefix frontend run lint && npm --prefix frontend run typecheck && npm --prefix frontend run test && npm --prefix frontend run build:demo && npm --prefix frontend run a11y && npm --prefix frontend run test:workbench`. Update the workbench specs that reference the old Model (`tests/workbench/navigation.spec.ts:68-88`, `chrome.spec.ts:40-68`) to the new grid.
- [ ] **Step 5:** Commit: `Model section: credit workbook grid with chart strip and passports`.

---

### Task 4: Admin rate deck card

**Agent:** `mx-feature`.

**Files:**
- Modify `frontend/src/sections/admin/AdminSection.tsx` (it renders `null` today). Create `frontend/src/sections/admin/RateDeckCard.tsx`.
- Modify `frontend/src/app/commands.ts` (`saveRateDeck`), and `src/app/views.tsx`, `transport.ts` and `authority.ts` if Admin needs a document. Because Admin is excluded from `ENABLED_SECTIONS`, prefer a self-contained fetch of `GET /api/v1/rate-decks/latest` inside the card through the existing transport helpers, and render the card for every viewer. Non-admins see it read-only; the server refuses a non-admin save.
- Test: `frontend/tests/unit/rate-deck.test.tsx`.

**Behaviour** (spec M14):
- The grid has rows SOFR, Term SOFR, EURIBOR and SONIA × FY+1–5, each with a Base and a Downside `<input inputmode="decimal">` entered as a percent (3.80).
- It also has an "As of" `<input type="date">`.
- **Save** posts `SaveRateDeck` (percent ÷ 100 as decimal strings; empty cells are left out).
- It shows the current deck's as-of date and saved time. Validation is inline: a value must be a number between −100 and 100, the as-of date is required, and an error appears next to the field.
- The command outcome is shown inline (CSP: no toasts).

- [ ] **Step 1:** Write the failing tests:
  - `prefills the grid from the latest deck`
  - `refuses a non-numeric rate inline`
  - `posts percent values as decimals`
  - `shows the server refusal for a non-admin`
- [ ] **Step 2:** Expect FAIL.
- [ ] **Step 3:** Implement. Remove or replace `fixtures/admin.json` and its test if the Admin section now serves the card.
- [ ] **Step 4:** Expect PASS. Run the full frontend gates and the a11y run on `/admin/`.
- [ ] **Step 5:** Commit: `Admin: rate deck card`.

---

### Task 5: one live CP-1 run (owner budget)

**Agent:** `mx-feature`.

Run a single live LITE run, on a route that includes CP-1, over the CZR set `qualification/czr-2026q2-lite-full-credit-screen`. Use the documented local procedure (`docs/DEPLOYMENT.md` and `scripts/qualify.py` with `tests/qualify_openrouter.py`), within the $75 live budget.

Assert:
- CP-1's debt register carries the six new columns with sourced values or explicit `NOT_STATED`/`null`;
- the account register carries the three new ids;
- the Model read serves a grid with no `reconciliation_faults`.

Record the spend and outcome in the report. If credentials are unavailable, report BLOCKED with the exact command and error. Do not stub the run.

---

## After Plan 2

The task reviews run per task. `mx-adversary` reviews Task 1 (it's a global write path) and Task 2 (the read assembles money figures). Plans 3 and 4 follow.

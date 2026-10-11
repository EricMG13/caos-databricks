# Book, Model and readiness check: design (grilled 2026-10-10)

Owner decisions from one grilling session. Decision (`Dn`) and next (`Nn`) numbers are assigned when each PR is cut, after `claude/n94-typed-registers` merges (it holds D123, D124, N190–N194). Glossary terms added in `CONTEXT.md`: **issuer**, **book entry**, **readiness check**, **rate deck**.

**Framing.** The app's Model assists the analyst's own Excel model; it does not replace it. Prefer the simple calculation with a stated ceiling over completeness.

**Layout rule (Book and Model).** One account per row and one value per cell: never two entries in one row or column (each agency's rating and outlook, each basis, each facility term and each reported or adjusted variant gets its own). Figures reconcile through visible bridges, in this order: KPIs › business-unit revenue › total revenue › cost of revenue › gross profit and margin › operating expenses › EBIT › EBITDA › add-backs › adjusted EBITDA and margin › FFO › working capital › CFO › capex › FCF › net cash flow › cash and liquidity › debt stack by payment rank › debt roll-forward › working-capital balances and days › credit metrics. Worked example: `2026-10-10-model-layout-example.html` (fake numbers; its generator, in git at 357a809e, asserts every bridge).

**Row economy.** No row repeats a figure shown elsewhere, and detail a passport can carry stays there:
- the change in working capital is one row (the balances section reconciles it);
- the CFO memo is one row (CFO as reported);
- net cash flow below FCF is five rows: acquisitions and disposals, net · debt raised, net of repayments · equity raised, net of buybacks · dividends paid · other investing and financing;
- the debt roll-forward is opening → debt raised, net of repayments → non-cash and lease movements → PF → closing;
- liquidity is closing cash → undrawn RCF → liquidity;
- a payment rank with one facility has no subtotal;
- a row that is zero or empty in every column is hidden until an issuer has the item. Debt facilities always show.

## 1. Book

| # | Decision |
|---|---|
| B1 | One row per **issuer**, keyed by `issuer_id` (upper-cased, trimmed). One issuer spans many cases. |
| B2 | The Book is **desk-wide**: every viewer sees every book entry. A run joins the Book only through **Add to Book**. Runs nobody added stay private to their case. |
| B3 | **Add to Book** needs `WRITER` standing or above on the run's case, a run that is `COMPLETE` with CP-1 accepted, and the run's snapshot digest (refused on mismatch, invariant 5). No second person: filing stays the four-eyes gate. The entry records who added it and when. |
| B4 | An issuer's row is its newest live book entry by `analysis_date`, then `added_at`. Older entries stay in the issuer's history. A **Filed** badge shows when that run's deliverable is filed. |
| B5 | The Add to Book dialog takes **analyst-stated classification**, pre-filled from the issuer's previous entry and recorded as of the add date: GICS sector (required) › industry group (optional); domicile (ISO 3166); Moody's, S&P and Fitch issuer ratings, each optional, each with an outlook (`STABLE`, `POSITIVE`, `NEGATIVE`, `DEVELOPING`, `WATCH_POS`, `WATCH_NEG`, `WATCH_DEV`). The fields are labelled "analyst-stated". Create run is unchanged. |
| B6 | **Composite rating:** the middle of three, the lower of two, or the single rating; none means `NR`. A 1–22 notch ordinal is a pure function with a property test. Filters: composite bucket (`IG`, `BB`, `B`, `CCC & below`, `NR`), a notch range **per agency**, and outlook. Sort by composite notch. |
| B7 | **Withdraw, never delete.** A `WRITER`+ withdraws with a reason (`ADDED_IN_ERROR`, `DATA_ERROR`, `SUPERSEDED_SOURCES`, `OTHER` plus a note), digest-bound and audited. The previous entry becomes the row again. |
| B8 | A cited source withdrawn from the case flags the entry **Sources withdrawn**; opening it shows the Model's existing refusal. The entry is not withdrawn automatically. |
| B9 | **An entry's run is readable desk-wide, read-only:** its Analysis, its Model and the evidence its citations point to. The case's other runs, uncited sources, revisions, the deliverable and every command stay member-only. Every read is audited. An adversarial security review is required. |
| B10 | **Persisted:** a `book_entries` row is written by the Add to Book command, holding the classification, subject, the metric set on each basis as `numeric`, the artifact digests and the rate deck it used. Model and Book call one calculator, and a test asserts the Book row equals the run's Model. No backfill. |
| B11 | **Bases:** LTM, PF-LTM (when present), and FY+1, FY+2 and FY+3 for Base and Downside. A basis switch swaps every metric column at once. Segments and KPIs are not persisted. |
| B12 | **Columns** (one value per column: each agency's rating and outlook, and each basis of a metric, are separate columns): issuer name and reporting period are locked. Every other identifier and metric (B5, the M5 metric set) can be added, removed and filtered (numeric min–max, categorical multi-select). Defaults: LTM revenue, LTM adjusted EBITDA, adjusted EBITDA margin, total debt, liquidity, adjusted net leverage, lease-adjusted net leverage, adjusted EBITDA/interest, FCF/debt, FFO/debt, and net leverage FY+1 Base and FY+1 Downside. |
| B13 | **Currency:** amounts are native, normalised to millions, with a currency column. Sorting or filtering an amount column first asks for a currency. No FX conversion. |
| B14 | **View state** (columns, filters, sort, basis) lives in the URL, and the last view is remembered in the browser. |
| B15 | **Opening a row** goes to the run's Analysis. A secondary action opens its Model, and a disclosure lists the issuer's other entries, withdrawn ones included. The server returns every issuer's displayed row; the client filters and sorts. |

## 2. Model

| # | Decision |
|---|---|
| M1 | A Model exists once **CP-1 is accepted**, on any route and at any run status (with a "run in progress" banner, updated over SSE). Projection columns appear when CP-CF is accepted; otherwise one line says "No projections: this route did not run CP-2G/CP-CF". |
| M2 | **Columns, in this order:** Quarters → PYTD, YTD → FY → LTM → PF-LTM → Base FY+1–3 · Downside FY+1–3. Groups collapse. The default shows the last 4 quarters, the last 3 FYs and everything else. |
| M3 | **Rows, in collapsible bands with frozen labels:** P&L summary with business units · adjusted EBITDA bridge · cash flow waterfall · capital structure (debt by seniority, leases, cash, liquidity) · credit metrics · working capital · KPIs. A chart strip above shows net leverage, interest coverage and liquidity across historicals and the Base and Downside cases (the existing `LineChart`). Clicking a cell opens the metric passport; a null cell shows its typed reason. |
| M4 | **Derived periods are host arithmetic** (invariant 7), from CP-1's `component_period_ids`: calculated quarters, LTM = FY + YTD − PYTD, and add-backs on each. Reported values pass through with their citation. Where CP-1 also stated a derived value, the passport shows both, and a difference beyond rounding shows a visible "differs from CP-1 stated" limitation without refusing. A missing component makes the value null with a typed reason. |
| M5 | **Metric set** (host Decimal), each EBITDA-based metric on both reported and adjusted EBITDA: total, net, senior secured and senior secured net leverage; EBITDA/cash interest; (EBITDA − capex)/cash interest; EBITDAR; lease-adjusted gross and net leverage (debt + balance-sheet lease liabilities, over EBITDAR); (EBITDAR − capex)/(cash interest + cash lease payments); FCF; FCF/debt; FCF/EBITDA; FFO/debt; FFO/lease-adjusted debt; capex % revenue; liquidity (cash + RCF commitment − RCF drawn); liquidity/debt; gross, EBITDA and adjusted EBITDA margins; revenue and EBITDA YoY; DSO, DIO, DPO and cash conversion cycle. A denominator ≤ 0 gives null with `ZERO_OR_NEGATIVE_DENOMINATOR`. |
| M6 | **Basis rules:** leverage and coverage use 12-month EBITDA only. A quarter column uses the LTM ending that quarter; YTD and PYTD carry no leverage. Working-capital days use period-end balances over the period's own `day_count`; DIO and DPO are null when COGS is null or ≤ 0. Lease balances, lease-adjusted metrics, working-capital balances and days on projected columns are null with "not projected". Projected lease cash is a driver, and finance lease liabilities are held flat (new leases replace principal paid). |
| M7 | **Adjusted EBITDA is a line in every period**, built from the add-back bridge. The default includes all issuer add-backs; one toggle, "exclude unrealised", drops `UNREALIZED` and `NOT_STATED` everywhere. |
| M8 | **PF-LTM** = adjusted LTM plus the pro forma adjustments from `cp1.pro_forma_adjustment_register` (C1) for each metric. It is shown only when the register has rows for that LTM. |
| M9 | **Cash flow waterfall:** adjusted EBITDA − cash interest − **lease cash not in EBITDA** − cash taxes ± other operating cash items (a computed residual) = FFO; ± each working-capital account = CFO, after all interest and lease cash. Memo rows reconcile it to CFO as reported: reported − lease payments in financing − interest paid in financing. CFO − capex = **FCF**. Lease cash not in EBITDA is all lease cash under IFRS 16, but only finance-lease cash under ASC 842, because ASC 842 operating lease cost is already inside EBITDA; deducting all of it would double count. Cash taxes are not reclassified: a tax tied to a disposal stays with the disposal, below FCF. Below FCF: acquisitions/disposals, net debt, net equity, dividends and other = net cash change. |
| M10 | **Business units and KPIs** come from `cp1.segment_revenue_schedule` and `cp1.operating_kpi_schedule`, recomputed for derived periods. Flow KPIs are summed, period-end KPIs take the last observation, and rates are shown only where sourced. YoY growth applies. Projected business-unit revenue = prior year × (1 + CP-2G's division growth driver), shown with the growth row beneath; total revenue is their sum, and a difference from CP-CF's revenue is a visible limitation. KPIs are "not projected". |
| M11 | **Projections:** annual, three FYs (or as pinned by D109's qualifiers), Base and Downside, from CP-2G and CP-CF. The year in progress is marked, with YTD actuals beside it. |
| M12 | **Amortisation:** from CP-1's per-facility `annual_amortisation` (C1), the host builds a schedule: each projected FY a balance falls by its amount, never below zero. The schedule feeds CP-CF's `contractual` input, which CP-4 never supplied. A maturity inside the horizon is **assumed refinanced at the same terms** and flagged "matures FYxxxx: assumed refinanced". |
| M13 | **Interest:** one weighted-average all-in rate per projected year and case, weighted on the amortised facility balances. Each facility's rate is fixed, or the reference rate from the pinned rate deck plus the spread (with the floor applied), or the **implied rate** (LTM cash interest / average total debt), labelled as such, when terms are not stated or no deck exists. Interest = the rate × opening interest-bearing debt (facilities, excluding finance leases and the discount row) from CP-CF's roll-forward, so there is no circularity. Scheduled amortisation stops once a facility is repaid. It replaces CP-2G's `cash_interest` driver in CP-CF; CP-2G's figure stays visible in the passport. Ceiling: refinancing and issuance mix are ignored. No hedges. |
| M14 | **Rate deck:** one Admin card with a grid (SOFR, Term SOFR, EURIBOR, SONIA × FY+1–5 × Base and Downside rows), an as-of date and Save. Each save is a new immutable deck; only `ADMIN` can save, and saves are audited. A run pins the latest deck at creation. A year past the deck's last column holds the last rate flat, labelled. No CSV upload and no interpolation. |

## 3. CP-1 fork amendment (owner-authorised 2026-10-10)

C1. One amendment, re-pinned per D31: `verify_package.py --refresh`, `host_manifest.py`, the build pins and the prompt goldens. It is verified by one live CP-1 run on CZR, within the $75 budget.
- New tagged table **`cp1.pro_forma_adjustment_register`**: `adjustment_id | label | period_id | effective_date | classification | metric_id | value | source_id | source_locator`. Classifications: `ACQUISITION`, `DISPOSAL`, `REFINANCING`, `SUBSEQUENT_EVENT`, `LENDER_UPDATE`, `OTHER_EXPLICIT`. Each value is an adjustment to the LTM `period_id` it names.
- **New account metric ids:** `operating_lease_cost`, `lease_payments_in_financing`, `interest_paid_in_financing`.
- **New debt register columns:** `rate_type` (`FIXED`, `FLOATING`, `NOT_STATED`), `reference_rate` (`SOFR`, `TERM_SOFR`, `EURIBOR`, `SONIA`, `NONE`; not "benchmark", a forbidden identifier reserved by CONTEXT.md), `spread_bps`, `floor_bps`, `fixed_rate`, `annual_amortisation`. `margin_or_coupon` stays as the issuer's own wording.
- **Rules:** lease liabilities are debt register rows with `lease_classification` `FINANCE_LEASE` or `OPERATING_LEASE`, and the `total_debt` account excludes them. Taxes classified outside operating are noted as a limitation.
- The new values are CP-CF calculation inputs, so their citations must anchor (D106/D107).

## 4. Readiness check (separate session, own PR series)

R1. A host-defined route made of CP-0 alone. Its T8 rates every module in the union of the advertised routes, and the host's T8 verification expects exactly that union. It is pinned to the current source set version and costs one CP-0 call.
R2. Results are shown per route: *Available* (every node `READY`), *Available with limitations*, or *Blocked* (naming the blocking modules, CP-0's reason and "sources to attach"). A module table appears as a Run section card. The result goes stale when sources change.
R3. Create run groups routes by readiness when a current check exists, and shows the catalog's `menu_label`. A blocked route can be started after an explicit, audited acknowledgement naming the blocking modules. The check is optional.

## 5. Order and constraints

1. CP-1 amendment.
2. Host model calculator: pure Decimal, with property tests, and mutation-tested because it is money.
3. Model read and grid. This stacks on N94 (`claude/n94-typed-registers`) after it merges.
4. Book entries: the store, Add to Book and Withdraw, the desk-wide read grant (with adversarial review), the source flag and the rate deck.
5. Book UI.
6. Readiness check, in a parallel session.

PRs are ≤ 800 lines and stacked. **No PR and no merge until N94 merges.**

## 6. Deferred (to `next.md` at PR time)

- A current-year stub of quarterly projections (needs a CP-2G amendment).
- A CP-2G amendment stating whether its CFO driver is before or after lease cash.
- Transaction PF beyond the register.
- Excel export.
- Named, server-saved Book views.
- Reusing the readiness check's CP-0 artifact in the run that follows.

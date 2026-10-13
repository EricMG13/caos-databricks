# CP-CF — Deterministic cash-flow forecast

Host extension v1. The only calculator is `cash_flow_forecast`; the host owns
its code and recomputes every result. Never supply code, a filename or a tool.
Use the canonical six-heading Markdown transport and exact host front matter.

In Analysis include exactly one fenced `caos-forecast-v1` JSON object with
exactly `request`, `bindings` and `forecast`. `request` follows the closed
contract in the delivered calculator source. `forecast` must equal the host's
deterministic result. Incomplete or unreconciled output cannot be accepted.
Each case's periods run in fiscal-year order after the opening's period.

`bindings` is one object per scalar leaf of request, keyed by JSON pointer.
Each binding is exactly `{module_id, quote}`. Every quote must be an exact
accepted upstream anchored quote that its owner's handoff cites by marker
(shown upstream as `[CP-1 C3]`; the register lists it as `CP-1 C3`) and contain
the exact line `/<pointer> = <JSON scalar>` with only one leading slash.
Empty arrays likewise bind their exact `/<pointer> = []` assignment. Cite those
quotes again in this handoff's citations and their `[C<n>]` in the Evidence Trace;
quote no other source text in the Markdown. No unrelated number, missing movement
or unstated zero is authority.

Keep the existing transport, tagged tables, vocabulary and all 42 CP-2G
financial/growth rows. Required legacy movements remain required. Every scalar
leaf and empty array needs its exact source-supplied JSON-pointer assignment
(/path = JSON value), with a linked anchored citation from its owner. Cite the
complete assignment line; put its marker in the source column or Evidence Trace,
never a value cell. CP-1 owns opening/periods/units/perimeter/actuals; CP-2G owns
drivers/tolerance/projection_basis; CP-4 owns contractual. No object-level quote
replaces leaf assignments. Missing, null and NOT_APPLICABLE never become zero.

Four optional signed money fields on each driver are net_equity_issue_repay
(cash + E), other_investing_financing (cash + O), restricted_cash_change
(accessible cash - R), and carrying_value_change (debt + C, no cash).
Explicit zero remains present in input and output; absent optional fields
preserve legacy result shape and arithmetic, without asserting an economic zero.
Money is finite plain decimal strings, at most 18 integer and 6 fractional digits;
JSON numbers, null, bool, exponent notation and nonfinite values are refused.
The four financial rows for each exact case/period/year remain READY CURRENCY_MM.
Present equity and otherFI fields equal their matching financial rows directly,
with the same sign; only absent corresponding fields require READY zero rows.
CP-2G's driver table keeps the vendor's signs, inflows positive and outflows
negative. Acquisitions/disposals and dividends retain reversed signs, mapping
to request fields each with its sign reversed: a `(45)` acquisition is acquisitions_disposals 45 and
a `45` disposal is -45; a `(45)` dividend is distributions 45. In vendor-table
and request order, a 45 dividend is `dividends_paid` (45) and distributions 45,
and a 45 disposal `acquisitions_disposals` 45 and -45. All zeros need explicit
sources. Division growth is not revenue; never infer movements from growth or
reinterpret vendor columns. Financial values may be plain, comma-grouped or
parenthesised figures (`1,250.0`, `(45)`); request money uses the plain decimal
contract above. A NOT_APPLICABLE row leaves the forecast not ready.
Restricted cash, carrying changes and segment maps use supplemental assignments
and the assumptions register; never invent vendor financial-driver IDs for them.

Optional driver.segment_revenue is a complete exact known CP-1 segment-ID to
signed money map, with 1-40 safe IDs (up to 64 ASCII letters/digits/underscore/
dot/hyphen, starting alphanumeric). Its sum equals consolidated driver revenue
exactly. Currency and perimeter match CP-1; request scale is millions and CP-1
unit MILLIONS. Every segment needs a latest-FY base; corporate/elimination values
stay equal to that base. Every map leaf is CP-2G-owned and explicitly sourced.
Present maps supply levels, replacing slot growth only for that driver; operating
segments in one division may diverge. Existing growth rows/registers remain
required by their own contracts and must not be applied twice.

Optional projection_basis is exactly "OWNED_CASH_DEBT_SERVICE", CP-2G-owned.
When selected, actuals is closed and contains only debt_cash_movements: zero or
one shared bridge, explicitly [] for a wholly future forecast. Each bridge has
exactly period_id (first projected period), historical_period_id (accepted
same-year actual YTD), and amount (exact signed CP-1 net_debt_issue_repay).
CP-1 owns every bridge leaf and the explicit empty array. The actual YTD starts
January 1 and ends before December 31 with matching currency, unit, basis and
perimeter. Apply its principal cash once per scenario's first year, never later.
Periods require CP-1-owned start_date/end_date: consecutive full January 1 to
December 31 calendars with exact days 365/366 and matching fiscal_year. Opening
as_of_period_id identifies the actual prior December 31 FY column, exact accepted
included signed facility stack and accessible cash. Same-date PE balance anchors
are allowed by existing rules; PE cannot replace the FY column. Forecast calendar
assignments are supplemental owner statements, not future historical actual columns.

In selected mode contractual.amortisation remains required and exactly [].
CP-4 owns contractual.aggregate_amortisation: exactly one closed row per requested
case/period, with exactly case, period_id, start_date, end_date, amount; amount is
nonnegative money. The first future span starts the day after actual YTD ends
when a bridge exists, otherwise January 1; later spans are January 1-December 31.
No fabricated facility IDs or mixed aggregate/per-facility schedules. Selected
issuance and optional_repayment cover this future span only; never repeat
historical gross issuance/repayment. Without the selector, actuals, aggregate
amortisation and these period date additions are refused; optional movements and
segment maps remain independently usable.

`cfo` is operating cash flow before cash interest and cash taxes. Here
`cash_interest` denotes debt cash interest only. Non-debt financing cash uses,
including financing-lease principal already included by the stated CFO
convention, remain in cfo; do not add back full lease budgets or contingencies
or charge them twice. cfo and cash_interest cover the full annual period,
including its actual-year portion.
The calculator deducts interest/taxes once: reported CFO already after them must
be reconciled explicitly, not used unchanged. Let H be the first-year historical
principal cash bridge and P future aggregate principal. H is never interest;
net debt cash = H + issuance - optional_repayment - P. Historical net principal
is not historical gross repayment or future P. E/O/R/C retain distinct meanings:
FCF = cfo - capex - cash_interest - cash_taxes;
cash close = cash open + FCF - distributions + net debt cash
             - acquisitions_disposals + E + O - R;
debt close = debt open + net debt cash + pik + capitalised_interest
             + fx_perimeter + C.
Required independent stated closes remain: each stated close reconciles within
the tolerance, never wider than one part in a thousand of its own opening
balance: debt of the opening debt, cash of the opening cash. Existing caps
remain: request tolerance, absolute 1000, relative 0.001, exact at zero opening.
Keep Decimal precision 38 / ROUND_HALF_EVEN and existing IO, HMAC, approval,
source-byte and request limits: 6 cases, 40 periods per case, 40 opening facilities,
2000 legacy amortisation rows; selected aggregate rows at most 240, one bridge.
Collections are bounded before parsing money; no permission or budget is widened.

Primary Model selected totals use accepted CP-CF aggregate cash/debt/interest:
"Cash debt-service basis: accepted CP-CF aggregate forecast". Instrument/rank,
secured, rate, RCF and liquidity forecast allocation is unsupplied, NOT_PROJECTED;
total debt is explicitly unallocated. No assumed refinance, synthetic rate deck
or facility cash-charge claim. Negative cash is unmet funding. Exact owner and
request-pointer attribution survives into Model sources. Citations verify source
location, not economic or legal approval. No economic adoption or paid-window
authority follows from a complete forecast.

Forecasts are projections over supplied assumptions, not credit qualification.
Carry every upstream restriction. Set committee_status to Draft Only for Passed
or Restricted for Restricted; neither is committee clearance.

# CP-CF — Deterministic cash-flow forecast

Host extension v1. The only calculator is `cash_flow_forecast`; the host owns
its code and recomputes every result. Never supply code, a filename or a tool.
Use the canonical six-heading Markdown transport and exact host front matter.

In Analysis include exactly one fenced `caos-forecast-v1` JSON object with
exactly `request`, `bindings` and `forecast`. `request` follows the closed
contract in the delivered calculator source. `forecast` must equal the host's
deterministic result. Incomplete or unreconciled output cannot be accepted.

`bindings` is one object per scalar leaf of request, keyed by JSON pointer.
Each binding is exactly `{module_id, quote}`. CP-1 owns opening, periods,
units and perimeter; CP-4 owns contractual amortisation; CP-2G owns drivers
and tolerance. Every quote must be an exact accepted upstream anchored quote
and must contain the exact line `/<pointer> = <JSON scalar>` (with only one
leading slash). Include those same quotes in this handoff and its citations.
No unrelated number, missing movement or unstated zero is authority.

CP-2G's accepted forecast_driver_table retains its vendor vocabulary. For the
exact case/period/year, all four of `acquisitions_disposals`, `dividends_paid`,
`net_equity_issue_repay` and `other_investing_financing` must be READY and
CURRENCY_MM, each value a plain, comma-grouped or parenthesised figure
(`1,250.0`, `(45)`). `acquisitions_disposals` is that movement and
`dividends_paid` is distributions. net_equity_issue_repay and
other_investing_financing must be a READY 0: this contract has no
corresponding movement. A NOT_APPLICABLE row leaves the forecast not ready
until CP-2G states it. Division growth is not revenue. Obtain every
other movement, independent stated close, and policy-free zero explicitly
from CP-2G's accepted evidence-anchored supplemental assignments. Never infer
them from growth or reinterpret vendor columns. CP-1's opening and CP-4's
amortisation must be explicitly supplied in the same assignment form.

Forecasts are projections over supplied assumptions, not credit qualification.
Carry every upstream restriction. Set committee_status to Draft Only for Passed
or Restricted for Restricted; neither is committee clearance.

# CCL FY2025 relative-value screen qualification — one authorized run, 18 September 2026 (below)

**Before 18 September 2026 no run had been performed against this set;** the authorized run is recorded at the end. It is authored, loadable and
digested; nothing here reports a result, a verdict or a provider. The live run
is Phase 9 Task 9.2 step 7 and needs the owner's explicit authorization — it
costs real money and calls a real model.

## The set

- Qualification-set digest:
  `fb20188605c957ec7b91079bd98f0002a627d15f633586eb39f7349e1f4bbf4b`
- Route: `LITE_CREDIT_22 / LITE_RELATIVE_VALUE` (`CP-0` → `CP-L10` → `CP-1C`,
  three REQUIRED edges, `decision_scope: SCREENING_ONLY`). CP-1C is a FULL
  module held behind the named-LITE-object boundary until CP-L10's
  `lite_financial_change_screen` is accepted (§46.1); the offline contract is
  `tests/test_lite_relative_value_route.py` and
  `tests/test_lite_cp1c_contract.py`.
- Documents:
  - `CCL_FY2025_10K.txt` — the Carnival Corporation & plc FY2025 Form 10-K text
    extract, the same bytes as `qualification/ccl-fy2025/`
    (`8fa7fceda34be50b3b9b5406e0c9269b5269870d1cd8c2bdafb682755a1c88e6`),
    copied because `server/qualification/on_disk._document` refuses a declared
    path outside the set's own directory.
  - `RCL_Q4_2025_Earnings_Release.txt`
    (`43005bdbd3a05fd62ef4107dd7dd4e97977c135d1f5902b68d45996cb6e2c592`) —
    Royal Caribbean Group, "Royal Caribbean Group Reports 2025 Results, Issues
    2026 Guidance", 29 January 2026; a text extract of
    <https://www.prnewswire.com/news-releases/royal-caribbean-group-reports-2025-results-issues-2026-guidance-302673898.html>,
    also filed as the Item 2.02 8-K, accession 0000884887-26-000003.
  - `NCLH_Q4_2025_Earnings_Release.txt`
    (`dd9a0eb7211c111b8180ea10f95416066c3e714a7390e0424799b6f522981b88`) —
    Norwegian Cruise Line Holdings, fourth-quarter and full-year 2025 results,
    2 March 2026; a text extract of
    <https://www.nclhltd.com/investors/news-events/press-releases/detail/768/norwegian-cruise-line-holdings-reports-fourth-quarter-and>,
    Item 2.02 8-K accession 0001171843-26-001220.

## Where the peer documents came from

The two peer releases were sourced by the coordinator on 18 September 2026
under the owner's authorization "web search for equivalent versions to test".
**The peer choice — RCL and NCLH, the other two listed major cruise operators
— is the coordinator's recommendation applied under that instruction**, not a
peer set the owner named and not one CP-1C derived; CP-1C's own Peer Discovery
Gate may judge it differently, and the owner may replace it. Both files are
HTML-to-text conversions made by the coordinator, so for these two documents
the file *is* the text: no issuer typography, page layout or table geometry
survives, and a table's cells arrive one per line. Both digests were verified
after copying into the set.

## Keys, and where each came from

**Keys authored by the implementer from the documents; material figures
pending owner confirmation.** Nothing has been run on this route, so there was
no output to copy from. Every quote below was checked against the real
plain-text extractor's token index: each matches whole tokens and matches
**once**, on one page, so it anchors rather than refusing
`CITATION_AMBIGUOUS`.

- `expects_ready: ["CP-L10", "CP-1C"]` — the route's two pinned consumers,
  which is what CP-0's T8 is asked to report.
- `expects_projection` — `decision_scope` = `SCREENING_ONLY` for CP-L10 and
  CP-1C, the catalog pathway's scope, which the host projects and the bundle
  now enforces against `Committee Ready` (§92).
- `expects` (citations):
  - CP-L10, 10-K page 11: the liquidity sentence ("As of November 30, 2025, we
    had $6.4 billion of liquidity …"), the fact the LIQUIDITY_MATURITIES topic
    turns on.
  - CP-1C, 10-K page 17: `Total Debt, net of unamortized debt issuance costs
    and discounts | 26,640 | 27,475 |` — the balance-sheet carrying value
    CP-1C's canon rule 5 names as the debt figure (not the 27,383 face total
    two lines above it).
  - CP-1C, NCLH page 1: "Total Debt was $14.6 billion. Net Debt was $14.4
    billion. Net Leverage was 5.3x at December 31, 2025."
  - CP-1C, RCL page 1: the full-year headline sentence ending "and Adjusted
    EBITDA was $7.0 billion."
- `expects_register`:
  - CP-L10 `TL10.2`, row `topic_id = LIQUIDITY_MATURITIES`, `evidence_status`
    = `SUFFICIENT`. Read from the 10-K: the liquidity sentence above, the
    $4.5 billion Revolving Facility, and a scheduled debt-maturity table
    (page 17, "As of November 30, 2025, the scheduled maturities of our debt
    are as follows:"). This is the register key the portfolio-screen set
    recorded as owed "with the reading"; this is that reading, for this set.
  - CP-1C `T4.5`, row `Entity = Carnival Corporation & plc`,
    `Total/Net/Sr Sec Leverage` = `[Calculated] 3.66x / 3.40x`. Debt 26,640
    (2,603 current + 24,037 long-term, carrying value); cash 1,928; EBITDA is
    not reported in the 10-K, so it is derived as operating income 4,483 + D&A
    2,790 = 7,273. Gross 26,640 / 7,273 = 3.66x; net 24,712 / 7,273 = 3.40x.
    The same figures stand in the owner's key source
    (`ANSWER_KEY_3ISSUER.md`, CCL core facts), which was read to confirm them,
    not admitted.
  - CP-1C `T4.5`, row `Entity = Norwegian Cruise Line Holdings Ltd.`,
    `Total/Net/Sr Sec Leverage` = `[Calculated] 5.35x / 5.3x (reported)`.
    Total debt 14,606,176 and Adjusted EBITDA 2,730,226 (thousands, the
    release's Net Leverage reconciliation) give a calculated 5.35x gross; the
    5.3x net is the issuer's own reported Net Leverage.

What the register keys cost, stated so a miss is read rather than counted:
the matrix compares a cell **exactly** (whitespace- and NFC-normalised, case
kept), and both the `Entity` row key and the leverage cell are free text a
module may spell differently while being right — `Carnival Corporation`,
`3.7x`, a senior-secured leg, or no `[Calculated]` label. The spellings above
are the implementer's; the owner may restate them before the run, which moves
the digest. RCL is cited but carries no register key: its release gives debt
(3,180 current + 18,165 long-term = 21,345) and Adjusted EBITDA 7,025, so
`[Calculated]` 3.04x gross, but a third free-text key adds a third chance to
miss for spelling rather than substance.

Two comparability traps a sound CP-1C should name rather than blend: CCL's
fiscal year ends 30 November 2025 and both peers' 31 December 2025; and the
peers' leverage denominators are their own **Adjusted** EBITDA while CCL's is
derived from operating income plus D&A.

## What is owed

- The owner's confirmation of the material figures and of the key spellings.
- **The run itself** (step 7, authorization required), and a signed verdict or
  a recorded reason why not.

## First authorized run — 18 September 2026

Authorized by the owner on 18 September 2026 (key figures confirmed, `$5`
per run). Provider `openrouter/openai/flex/high/65536`, model
`openai/gpt-5.6-terra`, `$0.000002` / `$0.000012` per token dated
2026-09-18, `--attempts 2`, bundle build `78c24be4` (§96 with §98). The run
database is on the persistent dev server (§100).

- Run `95dd27e1-31a4-4a3f-a3f0-3c25fc4c8e17`; database
  `caos_qualify_990bb204ec6e404db9845268f89c104d`; capture
  `run-2026-09-18-capture.json`; evidence `f43f0a6804020e85…`.
- Charges: CP-0 attempt 1 `$0.2278985`, attempt 2 `$0.22095525`. Total
  **`$0.44885375`**. CP-L10 and CP-1C were not called.

**Not signable; the run stopped with CP-0 unaccepted.**

- Attempt 1 was refused `CITATION_NOT_LOCATED`, correctly: it quoted "At
  November 30, 2025, we had $6.4 billion of liquidity" where the 10-K reads
  "As of November 30, 2025, …". A model error.
- Attempt 2 was refused `HANDOFF_MALFORMED` for a **host defect**: the body
  quoted every citation correctly inside Markdown backticks, and the body
  check forgave quotation marks around a quote but not a code span. Fixed in
  `d7ddbf0` (`tests/test_handoff_record.py::test_a_quote_the_body_wraps_in_quotation_marks_is_still_quoted`).
  The vendor's own validators accepted both answers.

## Second authorized run — 18 September 2026

Same authorization and settings as the run above; bundle build `78c24be4` with
§101 (CP-DR is delivered its research contract) and §102 (every source is
labelled `WHOLE` or `PAGE_MAP`); database on the persistent server (§100).

- Run `edf2b6e5-4e6c-44a2-9006-c370c508ceb3`; database `caos_qualify_5e6bfcd3f21f40d093690c693b349bda`;
  capture `run-2026-09-18b-capture.json`; evidence `9e445a9e27588aa5…`.
- Charges: CP-0 attempt 1 `$0.23433475` (refused `HANDOFF_MALFORMED`), attempt 2
  `$0.2157915` (accepted); total **`$0.45012625`**. CP-L10 and CP-1C were not called.

**Not signable.** The run ended BLOCKED at CP-0's readiness gate (`ready_met`
false); every downstream key missed because nothing downstream ran. Why attempt
1 was refused and why CP-0 blocked its consumers is under investigation; this
record is updated with the finding.

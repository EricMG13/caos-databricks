# CZR Q2 2026 LITE portfolio-screen qualification set — prepared offline

Status: **OFFLINE / UNVERIFIED / NOT QUALIFIED**.

This immutable set prepares `LITE_CREDIT_22 / LITE_PORTFOLIO_DECISION` for
Caesars Entertainment, Inc. (CZR) at an analysis date of 2026-10-02, with a
proposed position in the CZR 6.50% Senior Secured Notes due 2032 held against a
**SYNTHETIC** test mandate. Its qualification-set digest is
`bdd14c50113c6f4a49f1ce4b9f214791e2e3982573c9ea351af542ab7024cb52`.

## The mandate is synthetic (D80)

The "Test CLO I Ltd" mandate, exposure report and compliance monitor are
synthetic. The owner adopted them on 2 October 2026 as test input (D80): the
workbook describes itself as packaged sample data only, no figure in it is a
real holding, and the CZR position is an owner-adopted adaptation. A run over
this set measures how the route handles a mandate; it may never ground a real
decision. The CCL portfolio set (`ccl-fy2025-portfolio`) measures CP-0's
refusal of CP-L10 over a 10-K alone; this set, like `vmo2-fy2025-portfolio`,
measures the ready path, now with a mandate in the pack.

## Corpus provenance

The 10-Q and the CZR earnings release were fetched from SEC EDGAR on
2 October 2026 and converted from HTML to plain text the same day; both are
byte-identical to the `czr-2026q2` set's copies. The text SHA-256 is the
digest the keys bind; the raw SHA-256 is the HTML as fetched.

| document | source | accession | text SHA-256 | raw HTML SHA-256 |
|---|---|---|---|---|
| `CZR_Q2_2026_10Q.txt` (Form 10-Q, quarter ended 30 June 2026) | https://www.sec.gov/Archives/edgar/data/1590895/000159089526000028/czr-20260630.htm | 0001590895-26-000028 | `1b2027659f255471d41243180c9b550c6915348b7aea79619634c5a9d7b0187c` | `9dd3fca867c49936c65c9729bd7f9478d4c98b7c60569b74864a839bdeed8500` |
| `CZR_Q2_2026_Earnings_Release.txt` (Ex. 99.1, 28 July 2026) | https://www.sec.gov/Archives/edgar/data/1590895/000159089526000027/ex991-2026q2ceiearningsrel.htm | 0001590895-26-000027 | `17f1795b42b4b7aa32ef72582813986c3b98ea9c205d2b4cb446944bcf494ffc` | `a8982154b99b023b526261f7626022e96ac642834d1d65704629946acecc8a1f` |

The mandate is a text extract of the owner's workbook
`REF_CP-6A_Portfolio_Debate_Inputs.xlsx`, converted on 2 October 2026, with
the owner-adopted adaptation appended under its own heading. It is admitted
here for the first time. The FINRA TRACE observation is a coordinator-authored
transcription of the official public FINRA page, admitted byte for byte and
byte-identical to the `czr-2026q2-relative-value` set's copy.

| document | source | as of | SHA-256 | raw SHA-256 |
|---|---|---|---|---|
| `TEST_CLO_I_Mandate_and_Exposures_2026-10-02.txt` (SYNTHETIC) | owner-adopted synthetic test mandate (workbook, not a URL) | exposure report 29 May 2026; adaptation 2 October 2026 | `44903b2c253cdd731ee9d1355427e4601a1d109fe64a58b61efca8b1fc848c49` | `05a32699b39cedce58dd9475ea938c3dd592bd8a327426b1c2150f57579cfe22` (workbook) |
| `CZR_FINRA_TRACE_12769GAC4_2026-10-02.txt` (CZR 6.50% due 2032) | https://www.finra.org/finra-data/fixed-income/bond?symbol=ERI5740550&bondType=CORP | observed 2026-10-02T09:31:13Z | `4018aaa62309df6cd66a9b5fc766c4a9429e886e649023de2bad8673baf8aa51` | — |

All four are under 500 KiB and inside `MAX_REQUEST_BYTES`.

## Keys

Keys authored from the documents; material figures pending owner confirmation.

- CP-L10, issuer: the 10-Q's `$1.9 billion` of available CEI revolver
  capacity at 30 June 2026; the release's Adjusted EBITDA (`$920` million for
  the quarter, `$1,807` million for the six months).
- CP-L10, position: the mandate's proposed position (`USD 5,000,000` par of
  the CZR 6.50% 2032 notes, CUSIP 12769GAC4); its weight on par
  (`5,000,000 / 630,928,502 = 0.7925%` of NAV); the compliance monitor's C-01
  row (single name, `≤ 2.5% NAV`, hard, largest current exposure `2.37%`,
  status `Watch` at 29 May 2026); and FINRA's last trade price, `$93.28`.

Every key is one whole evidence line of its page, unique in its document: an
answer is accepted only as a whole line (`WHOLE_LINE`) and scored by exact
equality, so a fragment could never be met (F235, F475). Where a fact sits
inside a longer line, the key is that whole line.

The readiness key expects CP-0 to clear CP-L10, the route's one pinned
consumer. CP-L10 is expected at `SCREENING_ONLY` decision scope, the catalog
pathway's scope, and `Restricted`: the mandate is synthetic, its NAV and
compliance check are dated 29 May 2026 while the price is dated 1 October
2026, the price is a single last trade rather than a bid, mid or evaluated
price, and the notes' indenture is not in this pack.

The one register key expects CP-L10's `TL10.2` `LIQUIDITY_MATURITIES` row to
read `SUFFICIENT`: the 10-Q carries both the revolver availability and the
full maturity ladder, so the evidence status is unambiguous.

The arithmetic the mandate states, checked: `5,000,000 / 630,928,502 =
0.0079248…`, so `0.7925%` of NAV on par; headroom to C-01's `2.5%` is
`2.5 − 0.7925 = 1.7075` percentage points. At the last trade price,
`5,000,000 × 93.28 / 100 = 4,664,000.00`, and `4,664,000 / 630,928,502 =
0.7392%` of NAV. None of these figures is keyed as a register cell: the
module's own sizing register is not pinned here, and the NAV is not restated
pro forma for the position.

## Stated facts the screen must not misread

- **Synthetic, not a holding.** The document says "Existing Caesars
  Entertainment exposure: none." and that the position is synthetic.
- **As-of mismatch.** The workbook's NAV and compliance check are dated
  29 May 2026; the price is dated 1 October 2026; the 10-Q reports the
  quarter ended 30 June 2026.
- **The pending take-private.** The 10-Q discloses the 27 May 2026 Agreement
  and Plan of Merger with Fertitta Gaming; the FINRA last trade postdates it.

No provider call, run, snapshot, evidence record, reviewer verdict, or
qualification claim exists; no run has been performed.

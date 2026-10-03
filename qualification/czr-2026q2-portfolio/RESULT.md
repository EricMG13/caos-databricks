# CZR Q2 2026 FULL portfolio-decision qualification set — prepared offline

Status: **OFFLINE / UNVERIFIED / NOT QUALIFIED**.

This immutable set prepares `FULL_CREDIT_32 / PORTFOLIO_DECISION` for
Caesars Entertainment, Inc. (CZR) at an analysis date of 2026-10-02, with a
proposed position in the CZR 6.50% Senior Secured Notes due 2032 held against a
**SYNTHETIC** test mandate. Its qualification-set digest is
`e8587d90af968ee265cdddf8b63be01ed97d93ff1f9c8c17914336dfa961c7d0`.

## The mandate is synthetic (D80)

The "Test CLO I Ltd" mandate, exposure report and compliance monitor are
synthetic. The owner adopted them on 2 October 2026 as test input (D80): the
workbook describes itself as packaged sample data only, no figure in it is a
real holding, and the CZR position is an owner-adopted adaptation. A run over
this set measures how the FULL route carries a credit view through to an
allocation decision against a mandate; it may never ground a real decision.
The LITE sibling is `czr-2026q2-lite-portfolio`.

## Corpus provenance

The EDGAR documents were fetched on 2 October 2026 and converted from HTML to
plain text the same day. The 10-Q and the 10-K are byte-identical to the
`czr-2026q2` set's copies, the credit agreement to the `czr-2026q2-liquidity`
set's copy, and the indenture to the `czr-2026q2-covenant-refinancing` set's
copy. No document is admitted here for the first time. The text SHA-256 is the
digest the keys bind; the raw SHA-256 is the HTML as fetched.

| document | source | accession | text SHA-256 | raw HTML SHA-256 |
|---|---|---|---|---|
| `CZR_Q2_2026_10Q.txt` (Form 10-Q, quarter ended 30 June 2026) | https://www.sec.gov/Archives/edgar/data/1590895/000159089526000028/czr-20260630.htm | 0001590895-26-000028 | `9af04315eddd61ee7655445939d21bc91780c57c3689134c7c77d85c3dfb7e01` | `9dd3fca867c49936c65c9729bd7f9478d4c98b7c60569b74864a839bdeed8500` |
| `CZR_FY2025_10K.txt` (Form 10-K, fiscal year ended 31 December 2025) | https://www.sec.gov/Archives/edgar/data/1590895/000159089526000011/czr-20251231.htm | 0001590895-26-000011 | `4738e21322c565366a5e68be47fbacb894b869611ba9b52a353ed69b648abc48` | `41328bdfa2486cfb53b831c2ddba6009528d8dca3a0d868c98c2cb113142b05f` |
| `CZR_2020_Credit_Agreement.txt` (Ex. 10.1, Credit Agreement dated 20 July 2020) | https://www.sec.gov/Archives/edgar/data/1590895/000119312520196232/d940333dex101.htm | 0001193125-20-196232 | `4b3013342047cf6928ad18a3518180bb160c2e5251b5414eee71d95e8b95cf97` | `6600ab5bec479091f68dc04b2db65a54ef1013944c94af0ec135335b374c7dba` |
| `CZR_2024_650_Senior_Secured_Notes_2032_Indenture.txt` (Ex. 10.1, 6.500% Senior Secured Notes due 2032 indenture, 6 February 2024) | https://www.sec.gov/Archives/edgar/data/1590895/000119312524026847/d739529dex101.htm | 0001193125-24-026847 | `85ca330865d6ed47de838cbd3e45a69d29b57640e91782a71f2639721ac665db` | `a4661727edc48361dd7290772e62412c389b8ad8d215a96aa58facfe9e356c2c` |

The two FINRA TRACE observations are coordinator-authored transcriptions of
the official public FINRA pages, admitted byte for byte and byte-identical to
the `czr-2026q2-relative-value` set's copies. The mandate is a text extract of
the owner's workbook `REF_CP-6A_Portfolio_Debate_Inputs.xlsx`, converted on
2 October 2026 with the owner-adopted adaptation appended under its own
heading, byte-identical to the `czr-2026q2-lite-portfolio` set's copy.

| document | source | as of | SHA-256 | raw SHA-256 |
|---|---|---|---|---|
| `CZR_FINRA_TRACE_12769GAC4_2026-10-02.txt` (CZR 6.50% due 2032) | https://www.finra.org/finra-data/fixed-income/bond?symbol=ERI5740550&bondType=CORP | observed 2026-10-02T09:31:13Z | `4018aaa62309df6cd66a9b5fc766c4a9429e886e649023de2bad8673baf8aa51` | — |
| `CZR_FINRA_TRACE_12769GAD2_2026-10-02.txt` (CZR 6.00% due 2032) | https://www.finra.org/finra-data/fixed-income/bond?symbol=ERI5909471&bondType=CORP | observed 2026-10-02T09:31:27Z | `256c646128b7b670ebeb2e795aaced255373b488261b7f5c9111f933e2226b24` | — |
| `TEST_CLO_I_Mandate_and_Exposures_2026-10-02.txt` (SYNTHETIC) | owner-adopted synthetic test mandate (workbook, not a URL) | exposure report 29 May 2026; adaptation 2 October 2026 | `864ee90ab21372bcf89c8b27e02cd5d691d9095a64d507c7f656d5963cfe3207` | `05a32699b39cedce58dd9475ea938c3dd592bd8a327426b1c2150f57579cfe22` (workbook) |

The credit agreement (935,517 bytes) and the indenture (758,385 bytes) are over
500 KiB, so their paths are pinned in the large-file excludes; both are under
1.5 MiB, so they reach CP-0 whole rather than as a page map. All seven are
inside `MAX_REQUEST_BYTES`. The mandate's compliance monitor cites "Indenture
§7.11": that is the CLO's own indenture, not the Caesars notes indenture, and a
SYNTHETIC line in the adaptation says so.

## Keys

Keys authored from the documents; material figures pending owner confirmation.

- CP-1: the 10-Q's cash and cash equivalents, `$965` million at 30 June 2026
  and `$887` million at 31 December 2025.
- CP-2: operating cash flow, `675` for the six months to 30 June 2026 (10-Q)
  and `1,302` for FY2025 (10-K).
- CP-4: the 10-Q's statement that the revolver, term loans and both secured
  note series are guaranteed on a senior secured basis while the CEI Senior
  Notes due 2029 and 2032 are guaranteed on a senior unsecured basis; the
  indenture's Section 2.01 issue amount (`$1,500,000,000`) and its Section
  4.08(a) Change of Control repurchase offer at `101%`; the credit agreement's
  "(g) there shall have occurred a Change in Control;" event of default.
- CP-3D: the last trade prices of the two CZR notes, `$93.28` (6.50% 2032)
  and `$84.94` (6.00% 2032).
- CP-3: the last trade yields of the same notes, `8.063520%` (6.50% 2032,
  the proposed position) and `9.318398%` (6.00% 2032).
- CP-5: the 10-Q's Note 6 total debt (`11,807` face, `11,705` book at
  30 June 2026; `11,792` book at 31 December 2025).
- CP-6: the mandate's proposed position (`USD 5,000,000` par of the CZR 6.50%
  2032 notes, CUSIP 12769GAC4); its weight on par (`5,000,000 / 630,928,502 =
  0.7925%` of NAV); and the compliance monitor's C-01 row (single name,
  `≤ 2.5% NAV`, hard, largest current exposure `2.37%`, status `Watch` at
  29 May 2026).

The 2020 credit agreement's commitment, margins and covenant were changed by
amendments not in this set and are not keyed; the current revolver
(`$2.25 billion`, maturing 31 January 2028) is stated in the 10-Q.

Every key is one whole evidence line of its page, unique in its document: an
answer is accepted only as a whole line (`WHOLE_LINE`) and scored by exact
equality, so a fragment could never be met (F235, F475). Where a fact sits
inside a longer line, the key is that whole line.

The readiness key expects CP-0 to clear the route's seven consumers (CP-1,
CP-2, CP-4, CP-3D, CP-3, CP-5, CP-6). CP-6, the terminal deliverable, is
expected at `FULL` decision scope, the catalog pathway's scope. CP-3D, CP-3
and CP-6 are expected `Restricted`: each FINRA observation is a single last
trade, not bid, mid, ask, an evaluated price, a spread or a curve; the mandate
is synthetic; and its NAV and compliance check are dated 29 May 2026 while the
price is dated 1 October 2026.

**Readiness risk: the eligible-security universe.** CP-0's recorded refusal on
`ccl-fy2025-portfolio` asked for holdings or exposure, a mandate and limits,
an "eligible-security universe", current security-market evidence and the
applicable executed governing security documents. This set carries all but
the eligible-security universe, which is owner content (N127). The workbook's
only related content is two lien buckets of the compliance monitor, quoted as
they stand:

    C-09 | Instrument | Min 1st Lien / Senior Secured | ≥ 90.0% NAV | Hard | Indenture §7.11 | 99.39% | 9.39% | Pass | 29-May-2026 | E. Guei |
    C-10 | Instrument | Max 2nd Lien / Unsecured | ≤ 10.0% NAV | Soft | Indenture §7.11 | 0.61% | 9.39% | Pass | 29-May-2026 | E. Guei |

No eligibility statement is invented to close the gap: no admitted document
says whether a senior secured bond is an eligible asset of this CLO. CP-0 may
therefore hold CP-3 and CP-6 `CONDITIONAL` rather than `READY`, and the
readiness key would then be missed.

No register key is set: the module's sizing register is not pinned here, and
the NAV is not restated pro forma for the position. The arithmetic the mandate
states, checked: `5,000,000 / 630,928,502 = 0.0079248…`, so `0.7925%` of NAV on
par; headroom to C-01's `2.5%` is `2.5 − 0.7925 = 1.7075` percentage points. At
the last trade price, `5,000,000 × 93.28 / 100 = 4,664,000.00`, and
`4,664,000 / 630,928,502 = 0.7392%` of NAV.

## Stated facts the decision must not misread

The documents state the following; this set draws no conclusion from them.

- **Synthetic, not a holding.** The mandate says "Existing Caesars
  Entertainment exposure: none." and that the position is synthetic.
- **Seniority.** The 10-Q lists the 6.50% 2032 notes under "Secured Debt" and
  the 6.00% 2032 notes under "Unsecured Debt"; FINRA displayed no seniority.
- **As-of mismatch.** The workbook's NAV and compliance check are dated
  29 May 2026; the FINRA last trades are dated 1 October 2026; the 10-Q
  reports the quarter ended 30 June 2026.
- **The pending take-private.** The 10-Q discloses the 27 May 2026 Agreement
  and Plan of Merger with Fertitta Gaming; both FINRA last trades postdate it.

No provider call, run, snapshot, evidence record, reviewer verdict, or
qualification claim exists; no run has been performed.

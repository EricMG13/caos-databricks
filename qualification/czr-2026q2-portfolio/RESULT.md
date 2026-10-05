# CZR Q2 2026 FULL portfolio-decision qualification set — prepared offline

Status: **OFFLINE / UNVERIFIED / NOT QUALIFIED**.

This immutable set prepares `FULL_CREDIT_32 / PORTFOLIO_DECISION` for
Caesars Entertainment, Inc. (CZR) at an analysis date of 2026-10-02, with a
proposed position in the CZR 6.50% Senior Secured Notes due 2032 held against a
**SYNTHETIC** test mandate. Its qualification-set digest is
`4efe51e74a3ccda9f4a51b92c0e470723763e3e00decee916ec615234006157a`.

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
| `CZR_Q2_2026_10Q.txt` (Form 10-Q, quarter ended 30 June 2026) | https://www.sec.gov/Archives/edgar/data/1590895/000159089526000028/czr-20260630.htm | 0001590895-26-000028 | `f369ce5f1ebeddd9a0d4ce02ce3958112267d8701d1a348dfd6dc82d2034793a` | `9dd3fca867c49936c65c9729bd7f9478d4c98b7c60569b74864a839bdeed8500` |
| `CZR_FY2025_10K.txt` (Form 10-K, fiscal year ended 31 December 2025) | https://www.sec.gov/Archives/edgar/data/1590895/000159089526000011/czr-20251231.htm | 0001590895-26-000011 | `172309048af2a6a2dab515d765f00a7c89bf8c874c6104a5e3a052b66cad4512` | `41328bdfa2486cfb53b831c2ddba6009528d8dca3a0d868c98c2cb113142b05f` |
| `CZR_2020_Credit_Agreement.txt` (Ex. 10.1, Credit Agreement dated 20 July 2020) | https://www.sec.gov/Archives/edgar/data/1590895/000119312520196232/d940333dex101.htm | 0001193125-20-196232 | `cdfeb87c9b57914f4c2e89dbb2ec80de52564b1817b35fe15e332e67a13039b5` | `6600ab5bec479091f68dc04b2db65a54ef1013944c94af0ec135335b374c7dba` |
| `CZR_2024_Credit_Agreement_Incremental_Assumption_No3.txt` (Ex. 10.2, Incremental Assumption Agreement No. 3, 6 February 2024, with Exhibit A, the Credit Agreement conformed through it; Ex. 10.36 in the FY2025 10-K) | https://www.sec.gov/Archives/edgar/data/1590895/000119312524026847/d739529dex102.htm | 0001193125-24-026847 | `9f95f4a696471fcb1c16e5c6026880544356931806a939ffd999456bd8c4b757` | `aa48bc94b634de6386579791df7de831314785f007398546dd5c5fba415f2cfa` |
| `CZR_2024_650_Senior_Secured_Notes_2032_Indenture.txt` (Ex. 10.1, 6.500% Senior Secured Notes due 2032 indenture, 6 February 2024) | https://www.sec.gov/Archives/edgar/data/1590895/000119312524026847/d739529dex101.htm | 0001193125-24-026847 | `0809ab3981090bd2c23950da9530adb10e96882ddfa7db4404635e014d4c1119` | `a4661727edc48361dd7290772e62412c389b8ad8d215a96aa58facfe9e356c2c` |
| `CZR_2024_650_Notes_First_Supplemental_Indenture.txt` (Ex. 4.2, First Supplemental Indenture to the 6.500% 2032 notes indenture, 1 March 2024; Ex. 4.11 in the FY2025 10-K) | https://www.sec.gov/Archives/edgar/data/1590895/000159089524000088/exhibit42firstsupplemental.htm | 0001590895-24-000088 | `0af4615b9a52e91e2675adacbbc90ecc7b21a61dc8205b4b2459cf4b9db0a219` | `18d810c415aef677f867ac73dee07a04382e71db794f3bfbc91cdd185e4b0dc4` |
| `CZR_2024_650_Notes_Second_Supplemental_Indenture.txt` (Ex. 4.17, Second Supplemental Indenture to the 6.500% 2032 notes indenture, 23 August 2024; Ex. 4.12 in the FY2025 10-K) | https://www.sec.gov/Archives/edgar/data/1590895/000159089525000068/exhibit417-6500seniorsecur.htm | 0001590895-25-000068 | `3621f08611f4c6a6faed734993a3f2d9c97041693053ffa97624cbe5b7299aea` | `0eedd7d398ee15f45dabc99df2003249d4dbe232be456767e7b972d355326b3c` |

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
1.5 MiB, so they reach CP-0 whole rather than as a page map. All ten are inside
`MAX_REQUEST_BYTES`. The mandate's compliance monitor cites "Indenture §7.11":
that is the CLO's own indenture, not the Caesars notes indenture, and a
SYNTHETIC line in the adaptation says so. The exhibits F508 adds were fetched
from SEC EDGAR on 5 October 2026 and converted the same day, split by sentence
(F492) and by clause (F498); they are byte-identical to the
`czr-2026q2-covenant-refinancing` set's copies. Since F508 Incremental
Assumption Agreement No. 3 (1,077,810 bytes) is pinned there too and, under 1.5
MiB, reaches CP-0 whole; the supplemental indentures are 11,774 and 15,684
bytes. The set's CP-0 request, encoded with CP-0's delivered authority, is
3,745,516 bytes (89.3% of `MAX_REQUEST_BYTES`, up from 2,581,092), and no
source is shown as a page map.

## Why the pack carries the current legal chain (F508)

Live runs C5 (`czr-2026q2-covenant-refinancing`) and LCR1
(`czr-2026q2-lite-covenant-refinancing`) held back the covenant modules at CP-0
(CP-4, then CP-L10): the sets carried the 2020 credit agreement with only its
Fourth and Fifth Amendments, and the 6.50% 2032 notes indenture without its
supplemental indentures, though the FY2025 10-K's exhibit index lists them. On
the owner's ruling of 5 October 2026 ("Latest chain only"), every CZR set that
carries one of those instruments now carries Incremental Assumption Agreement
No. 3 and the 2032 notes' First and Second Supplemental Indentures beside it.

Incremental Assumption Agreement No. 3 (6 February 2024) adds the
`$2,900.0 million` Incremental Term B-1 Loans. Its Exhibit A is the credit
agreement conformed through Incremental Assumption Agreement No. 1, the First
to Third Amendments and Incremental Assumption Agreements No. 2 and No. 3; with
the Fourth and Fifth Amendments, which this set does not carry, it is the
current chain, and where Exhibit A and a later amendment differ, the later
amendment governs. Exhibit A is a changed copy, Agreement No. 3's insertions
double-underlined and its deletions struck through. On the owner's ruling of 5
October 2026 the text renders the agreement as amended: every struck run from
Exhibit A's cover on is removed with its content (295 runs, 167 of them with
text, 484 characters: superseded table-of-contents page numbers and 38 words,
labels or punctuation) and the insertions are kept as plain text, so
`Section 2.01(e)` and `Section 2.11(a)(iv)` read as amended. The one struck run
before the cover, the word `strikethrough` in the Agreement's own Section 3
legend, deletes nothing and is kept.

The First Supplemental Indenture (1 March 2024) adds two guarantors and amends
clause (44) of the Permitted Liens definition and Section 8.01(b); the Second
(23 August 2024) adds the guarantors on its Schedule A.

No key is added or changed: a key binds the digest of the document it was
authored from. Exhibit A repeats the 2020 agreement's
`(g) there shall have occurred a Change in Control;`, so a citation of that
line in Exhibit A does not meet the CP-4 key, which binds the 2020 agreement.

## Keys

Keys authored from the documents; material figures pending owner confirmation.

- CP-1: the 10-Q's cash and cash equivalents, `$965` million at 30 June 2026
  and `$887` million at 31 December 2025.
- CP-2: operating cash flow, `675` for the six months to 30 June 2026 (10-Q)
  and `1,302` for FY2025 (10-K).
- CP-4: the 10-Q's sentence that the revolver, term loans and both secured
  note series are guaranteed on a senior secured basis and secured by
  substantially all assets, and its next sentence, that the CEI Senior Notes
  due 2029 and 2032 are guaranteed on a senior unsecured basis (one key each
  since the F492 sentence split); the
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
amendments the set carries only as Incremental Assumption Agreement No. 3's
conformed Exhibit A (F508) and are not keyed; the current revolver
(`$2.25 billion`, maturing 31 January 2028) is stated in the 10-Q.

Alternative lines (D101). A figure key is also met by another whole evidence
line, cited under the same module, that states the key's lead figures -- the
current figure and the comparative the key line leads with -- for the same
measure, period and consolidated scope; a % change, a further period or a third
year on the key line need not be on it. Prose keys have none: a statement is
its sentence. Each alternative is one whole evidence line, unique in its
document (F475), and is listed with why it states the key's figures:

- CP-2, the 10-Q's `Net cash provided by operating activities | 675 | 680`:
  - the 10-Q's `During the six months ended June 30, 2026, our operating
    activities generated operating cash inflows of $675 million, as compared to
    operating cash inflows of $680 million during the six months ended June 30,
    2025, primarily due to changes in working capital, coupled with the results
    of operations described above.`, its liquidity sentence, the six months
    against the prior six months.

The other figure keys (`Cash and cash equivalents`, `Net cash provided by
operating activities`, `Total debt`, `C-01`) have none: no other whole line
states their figures for the same measure, period and basis (rounded prose such
as `$11.8 billion` or `$1.3 billion` is not the figure).

Every key is one whole evidence line of its page, unique in its document
(F475). Since D105 an answer cites an excerpt of a line (at least 8 words, or
the whole line), and a key is met by any citation anchored in the key's line,
compared by exact equality with that line (F502); a record from before D105 is
scored by its quote. Where a fact sits inside a longer line, the key is that
whole line. Since F492 a prose line of a
converted filing is one sentence, so a key is the sentence that carries its
fact.
Since F498 a sentence of a legal instrument (the credit agreement, its
amendments, the indenture, the merger 8-K) over 400 characters is cut further
at its clause boundaries (`; (b)`, `, (b)`, `; and`, `, and (c)`, `; provided`,
`, provided that`, `: (a)`), so a key there is the clause that carries its
fact. The indenture's Section 4.08(a) key is so restated as the clause that
grants the `101%` repurchase right, ending
`in accordance with the terms contemplated in this Section 4.08;`; its
`provided, however,` proviso (no repurchase of Notes the Company has exercised
its right to redeem) is now the next line and is not keyed, as it carries none
of the key's figures.

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

# CZR Q2 2026 FULL credit-assessment qualification set — prepared offline

Status: **LIVE-RUN 2026-10-05 / NOT QUALIFIED (stopped at CP-2G; citation keys)**. Prepared offline; the live results are in the last section.

This immutable set prepares `FULL_CREDIT_32 / FULL_CREDIT_ASSESSMENT` for
Caesars Entertainment, Inc. (CZR) at an analysis date of 2026-10-02, against
peers MGM Resorts International (MGM) and PENN Entertainment, Inc. (PENN) from
the owner's "Public Leveraged Loan Issuers Benchmark", with a proposed position
in the CZR 6.50% Senior Secured Notes due 2032 held against a **SYNTHETIC**
test mandate. Its qualification-set digest is
`5e0a1f7d45f61cf66ab435da206caa4f9acabc3589ed51ff880e7a019c9670e5`.

## The mandate is synthetic (D80)

The "Test CLO I Ltd" mandate, exposure report and compliance monitor are
synthetic. The owner adopted them on 2 October 2026 as test input (D80): the
workbook describes itself as packaged sample data only, no figure in it is a
real holding, and the CZR position is an owner-adopted adaptation. CP-6, the
route's terminal deliverable, reads it; a run over this set may never ground a
real decision.

## Corpus provenance

The set carries every admitted CZR document, both peer releases, all four FINRA
TRACE observations and the synthetic mandate. The EDGAR documents were fetched
on 2 October 2026 and converted from HTML to plain text the same day. The 10-Q,
the 10-K and the CZR earnings release are byte-identical to the `czr-2026q2`
set's copies,  the Fourth and Fifth Amendments, the indenture and the merger
8-K and press release to the `czr-2026q2-covenant-refinancing` set's copies,
and the MGM and PENN releases to the `czr-2026q2-lite-relative-value` set's
copies. No document is admitted here for the first time. The text SHA-256 is
the digest the keys bind; the raw SHA-256 is the HTML as fetched.

| document | source | accession | text SHA-256 | raw HTML SHA-256 |
|---|---|---|---|---|
| `CZR_Q2_2026_10Q.txt` (Form 10-Q, quarter ended 30 June 2026) | https://www.sec.gov/Archives/edgar/data/1590895/000159089526000028/czr-20260630.htm | 0001590895-26-000028 | `f369ce5f1ebeddd9a0d4ce02ce3958112267d8701d1a348dfd6dc82d2034793a` | `9dd3fca867c49936c65c9729bd7f9478d4c98b7c60569b74864a839bdeed8500` |
| `CZR_FY2025_10K.txt` (Form 10-K, fiscal year ended 31 December 2025) | https://www.sec.gov/Archives/edgar/data/1590895/000159089526000011/czr-20251231.htm | 0001590895-26-000011 | `172309048af2a6a2dab515d765f00a7c89bf8c874c6104a5e3a052b66cad4512` | `41328bdfa2486cfb53b831c2ddba6009528d8dca3a0d868c98c2cb113142b05f` |
| `CZR_Q2_2026_Earnings_Release.txt` (Ex. 99.1, 28 July 2026) | https://www.sec.gov/Archives/edgar/data/1590895/000159089526000027/ex991-2026q2ceiearningsrel.htm | 0001590895-26-000027 | `b385f76ff631243d1053fa8073ebde4f8886b4a50c9ce34ce3498d6b2ac3e9f8` | `a8982154b99b023b526261f7626022e96ac642834d1d65704629946acecc8a1f` |
| `CZR_2024_Credit_Agreement_Incremental_Assumption_No3.txt` (Ex. 10.2, Incremental Assumption Agreement No. 3, 6 February 2024, with Exhibit A, the Credit Agreement conformed through it; Ex. 10.36 in the FY2025 10-K) | https://www.sec.gov/Archives/edgar/data/1590895/000119312524026847/d739529dex102.htm | 0001193125-24-026847 | `25bea1d14fd9bb22838775f6fe056cd00741dc3d50eb1b79cc53498db502941c` | `aa48bc94b634de6386579791df7de831314785f007398546dd5c5fba415f2cfa` |
| `CZR_2024_Credit_Agreement_Fourth_Amendment.txt` (Ex. 10.1, Fourth Amendment, 9 May 2024) | https://www.sec.gov/Archives/edgar/data/1590895/000119312524135268/d827488dex101.htm | 0001193125-24-135268 | `32f91de6ef3ff93d9924eb8d4e3dc4734d28b68ed1da0f816a085ffdcb085c95` | `b0e9fc14d481410dd2fa3cb6bc28e4f9c3b8751d720777ab2bbf943143f6d0fb` |
| `CZR_2024_Credit_Agreement_Fifth_Amendment.txt` (Ex. 10.1, Fifth Amendment, 25 November 2024) | https://www.sec.gov/Archives/edgar/data/1590895/000119312524265157/d858083dex101.htm | 0001193125-24-265157 | `7f2b5c777dc3347938a007eaea63a623b299a1188dbcfbe8980d389a0bcfc5b3` | `0936486e71264a9b752d5977c003bfc9a89ec5eb4ca8e5b09107a7870ebf86e8` |
| `CZR_2024_650_Senior_Secured_Notes_2032_Indenture.txt` (Ex. 10.1, 6.500% Senior Secured Notes due 2032 indenture, 6 February 2024) | https://www.sec.gov/Archives/edgar/data/1590895/000119312524026847/d739529dex101.htm | 0001193125-24-026847 | `0809ab3981090bd2c23950da9530adb10e96882ddfa7db4404635e014d4c1119` | `a4661727edc48361dd7290772e62412c389b8ad8d215a96aa58facfe9e356c2c` |
| `CZR_2024_650_Notes_First_Supplemental_Indenture.txt` (Ex. 4.2, First Supplemental Indenture to the 6.500% 2032 notes indenture, 1 March 2024; Ex. 4.11 in the FY2025 10-K) | https://www.sec.gov/Archives/edgar/data/1590895/000159089524000088/exhibit42firstsupplemental.htm | 0001590895-24-000088 | `0af4615b9a52e91e2675adacbbc90ecc7b21a61dc8205b4b2459cf4b9db0a219` | `18d810c415aef677f867ac73dee07a04382e71db794f3bfbc91cdd185e4b0dc4` |
| `CZR_2024_650_Notes_Second_Supplemental_Indenture.txt` (Ex. 4.17, Second Supplemental Indenture to the 6.500% 2032 notes indenture, 23 August 2024; Ex. 4.12 in the FY2025 10-K) | https://www.sec.gov/Archives/edgar/data/1590895/000159089525000068/exhibit417-6500seniorsecur.htm | 0001590895-25-000068 | `3621f08611f4c6a6faed734993a3f2d9c97041693053ffa97624cbe5b7299aea` | `0eedd7d398ee15f45dabc99df2003249d4dbe232be456767e7b972d355326b3c` |
| `CZR_2026_Merger_Agreement_8K.txt` (Form 8-K, Item 1.01, 27 May 2026) | https://www.sec.gov/Archives/edgar/data/1590895/000119312526242995/d143382d8k.htm | 0001193125-26-242995 | `6808734cfbb19b56c5624e5a69e7209ccaad8a5039de94ad64563efdedf93169` | `aabda22b745ac6c2e5d8462be19fbc47b6cafbe58d21f8c2750a1c195cf24f96` |
| `CZR_2026_Merger_Press_Release.txt` (Ex. 99.1, 28 May 2026) | https://www.sec.gov/Archives/edgar/data/1590895/000119312526242995/d143382dex991.htm | 0001193125-26-242995 | `4fbecbd5f5a10b15911b5749daee41b3e40090e43ed54bf33aee07a21877e68b` | `2a4ed12c96147f2171451c93524bea31ecad37247448d27039f755a3cf85f51f` |
| `MGM_Q2_2026_Earnings_Release.txt` (MGM Ex. 99.1, 29 July 2026) | https://www.sec.gov/Archives/edgar/data/789570/000078957026000075/mgmex991q22026earningrelea.htm | 0000789570-26-000075 | `795ac68aa1c51a7e0a6799a6e1ca053ee597dc9a1a9a6550a2438280a6e76cdb` | `d23f2410e475eca7e0dfe2fdcca0210f449e4c1a93fb93a14549592c4554173c` |
| `PENN_Q2_2026_Earnings_Release.txt` (PENN Ex. 99.1, 6 August 2026) | https://www.sec.gov/Archives/edgar/data/921738/000092173826000019/pennex991-q22026.htm | 0000921738-26-000019 | `4d12fff94b066f73e6eccce84eec937e8fd4fdc38d6061704db66a40511a210c` | `be60f25fec25022c2fd6f48c2cf9bb99912b8f78356cebc4a7719bdcae9120bc` |

The four FINRA TRACE observations are coordinator-authored transcriptions of
the official public FINRA pages, admitted byte for byte and byte-identical to
the `czr-2026q2-relative-value` set's copies; each file states its own source
URL and observation time, and the file is the text. The mandate is a text
extract of the owner's workbook `REF_CP-6A_Portfolio_Debate_Inputs.xlsx`,
converted on 2 October 2026 with the owner-adopted adaptation appended under
its own heading, byte-identical to the `czr-2026q2-lite-portfolio` set's copy.

| document | source | as of | SHA-256 | raw SHA-256 |
|---|---|---|---|---|
| `CZR_FINRA_TRACE_12769GAC4_2026-10-02.txt` (CZR 6.50% due 2032) | https://www.finra.org/finra-data/fixed-income/bond?symbol=ERI5740550&bondType=CORP | observed 2026-10-02T09:31:13Z | `4018aaa62309df6cd66a9b5fc766c4a9429e886e649023de2bad8673baf8aa51` | — |
| `CZR_FINRA_TRACE_12769GAD2_2026-10-02.txt` (CZR 6.00% due 2032) | https://www.finra.org/finra-data/fixed-income/bond?symbol=ERI5909471&bondType=CORP | observed 2026-10-02T09:31:27Z | `256c646128b7b670ebeb2e795aaced255373b488261b7f5c9111f933e2226b24` | — |
| `MGM_FINRA_TRACE_552953CK5_2026-10-02.txt` (MGM 6.125% due 2029) | https://www.finra.org/finra-data/fixed-income/bond?symbol=MGM5885613&bondType=CORP | observed 2026-10-02T09:32:08Z | `e17cea1bb90debdeb8c1fea9c352132b57ae9b27ee0d3225fb67c6466d7d0e4a` | — |
| `PENN_FINRA_TRACE_707569AV1_2026-10-02.txt` (PENN 4.125% due 2029) | https://www.finra.org/finra-data/fixed-income/bond?symbol=PENN5210723&bondType=CORP | observed 2026-10-02T09:32:31Z | `666c0f36ace32336dffbcff324eaec5b4657edade407bb0b8a0e8d8fb405de6d` | — |
| `TEST_CLO_I_Mandate_and_Exposures_2026-10-02.txt` (SYNTHETIC) | owner-adopted synthetic test mandate (workbook, not a URL) | exposure report 29 May 2026; adaptation 2 October 2026 | `864ee90ab21372bcf89c8b27e02cd5d691d9095a64d507c7f656d5963cfe3207` | `05a32699b39cedce58dd9475ea938c3dd592bd8a327426b1c2150f57579cfe22` (workbook) |

The indenture (758,385 bytes) and Incremental Assumption Agreement No. 3
(1,077,810 bytes) are over 500 KiB, so their paths are pinned in the large-file
excludes; both are under 1.5 MiB, so they reach CP-0 whole rather than as a
page map. All eighteen are inside `MAX_REQUEST_BYTES`. The mandate's compliance
monitor cites "Indenture §7.11": that is the CLO's own indenture, not the
Caesars notes indenture, and a SYNTHETIC line in the adaptation says so. The
exhibits F508 adds were fetched from SEC EDGAR on 5 October 2026 and converted
the same day, split by sentence (F492) and by clause (F498); they are
byte-identical to the `czr-2026q2-covenant-refinancing` set's copies. Since
F508 the conformed copy in Agreement No. 3's Exhibit A replaces the 2020 credit
agreement (Ex. 10.1, accession 0001193125-20-196232, 935,517 bytes); the
supplemental indentures are 11,774 and 15,684 bytes. The set's CP-0 request,
encoded with CP-0's delivered authority, is 2,975,932 bytes (71.0% of
`MAX_REQUEST_BYTES`, up from 2,793,515), and no source is shown as a page map.

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
the Fourth and Fifth Amendments it is the current chain, and where Exhibit A
and a later amendment differ, the later amendment governs. Exhibit A comes
without the credit agreement's own exhibits and schedules: after its Annex A
Pricing Grid the file goes straight to Agreement No. 3's own Exhibit B, a form
of solvency certificate. Exhibit A is a changed copy, Agreement No. 3's
insertions double-underlined and its deletions struck through. On the owner's
ruling of 5 October 2026 the text renders the agreement as amended: every
struck run from Exhibit A's cover on is removed with its content (295 runs, 167
of them with text, 484 characters: superseded table-of-contents page numbers
and 38 words, labels or punctuation) and the insertions are kept as plain text,
with the spacing the filing renders once a run is gone (one space restored
where a run carried the only space between two words, three places; none left
before closing punctuation, three places), so `Section 2.01(e)` and
`Section 2.11(a)(iv)` read as amended. The one struck run before the cover, the
word `strikethrough` in the Agreement's own Section 3 legend, deletes nothing
and is kept.

The First Supplemental Indenture (1 March 2024) adds two guarantors and amends
clause (44) of the Permitted Liens definition and Section 8.01(b); the Second
(23 August 2024) adds the guarantors on its Schedule A.

No key is added. On the owner's ruling of 5 October 2026 ("Replace the 2020
base"), the conformed copy replaces the 2020 credit agreement (Ex. 10.1,
accession 0001193125-20-196232), which this set no longer carries: the
agreement as amended is the one in force, and the superseded 2020 text cost
about 0.9 MB of every request. The Fourth and Fifth Amendments post-date
Agreement No. 3 and stay. The CP-4 key on the event of default
`(g) there shall have occurred a Change in Control;` is re-keyed to Exhibit A's
same line, one whole line unique in it, whose words are unchanged. The Change
in Control definition it relies on was amended since 2020: clause (a) now names
the 2027 Senior Unsecured, 2025 Senior Secured and 2029 Senior Unsecured Notes
Indentures, the 2029 one added as (iii), and a proviso now deems a person or
group not to beneficially own Equity Interests subject to a merger agreement
until the acquisition is consummated.

## Keys

Keys authored from the documents; material figures pending owner confirmation.

- CP-1: the 10-Q's cash and cash equivalents, `$965` million at 30 June 2026.
- CP-1A, the named transaction: the 8-K's Item 1.01 paragraph recording the
  27 May 2026 Agreement and Plan of Merger with Fertitta Gaming Holdco, LLC,
  and the press release's opening line (`$17.6 billion`, including the
  assumption of approximately `$11.9 billion` of Caesars' debt).
- CP-1B: the release's Caesars net revenues (`$2,993` against `$2,907`
  million, `3.0%`) and Adjusted EBITDA (`$920` against `$955` million for the
  quarter); the 10-K's net revenues (`11,486` for FY2025).
- CP-1C: MGM's long-term debt, net (`6,068,442` thousand) and Consolidated
  Adjusted EBITDA of `$610 million` for the quarter; PENN's traditional net
  leverage of `2.9x` at 30 June 2026.
- CP-2: operating cash flow, `675` for the six months (10-Q) and `1,302` for
  FY2025 (10-K).
- CP-2E: the 10-Q's two Item 3 sentences: `$6.0 billion` of long-term
  variable-rate borrowings at 30 June 2026, and about `51%` of consolidated
  long-term debt at weighted average rates of `5.87%` variable and `6.18%`
  fixed (one key each since the F492 sentence split).
- CP-4: the 10-Q's senior secured guarantee and lien sentence and its next
  sentence, the senior unsecured guarantee of the CEI Senior Notes due 2029
  and 2032 (one key each); the indenture's Section 2.01
  issue amount (`$1,500,000,000`); the credit agreement's Change in Control
  event of default; the Fifth Amendment's Term B and B-1 margins (`2.25%` Term
  Benchmark, `1.25%` ABR).
- CP-2D: the 10-Q's maturity ladder (`$11,807` million in total) and its
  `$1.9 billion` of available CEI revolver capacity at 30 June 2026.
- CP-2H: FINRA's displayed Moody's rating for each CZR note, `B1` (6.50% 2032)
  and `Caa1` (6.00% 2032).
- CP-3D: the last trade prices of the two CZR notes, `$93.28` and `$84.94`.
- CP-3C: the 10-Q's paragraph on the amended CEI Credit Agreement (revolver of
  `$2.25 billion` maturing 31 January 2028); the indenture's Section 4.08(a)
  Change of Control offer at `101%`; the press release's statement that the
  transaction has no financing condition.
- CP-4C: the 10-Q's statement that at 30 June 2026 the Company was in
  compliance with all applicable financial covenants.
- CP-3: the last trade yields of the proposed position (`8.063520%`) and of
  the peer notes, `6.722997%` (MGM 6.125% 2029) and `6.644415%` (PENN 4.125%
  2029).
- CP-5: the 10-Q's Note 6 total debt (`11,807` face, `11,705` book).
- CP-6: the mandate's proposed position (`USD 5,000,000` par, CUSIP
  12769GAC4); its weight on par (`0.7925%` of NAV); the compliance monitor's
  C-01 row (`≤ 2.5% NAV`, hard, `2.37%`, `Watch` at 29 May 2026).

CP-1D, CP-2A and CP-2G carry no key: none of their outputs is a single fact a
document states. The conformed credit agreement's commitment, margins and
covenant are not keyed: the Fourth and Fifth Amendments post-date it, and the
current revolver is stated in the 10-Q.

Alternative lines (D101). A figure key is also met by another whole evidence
line, cited under the same module, that states the key's lead figures -- the
current figure and the comparative the key line leads with -- for the same
measure, period and consolidated scope; a % change, a further period or a third
year on the key line need not be on it. Prose keys have none: a statement is
its sentence. Each alternative is one whole evidence line, unique in its
document (F475), and is listed with why it states the key's figures:

- CP-1, the 10-Q's `Cash and cash equivalents | $965 | $887`:
  - the release's `Cash and cash equivalents | $965 | $887`, its balance sheet
    row, the same two dates.
  Not alternatives: the 10-Q's `Cash and cash equivalents | $965 | $982` (its
    comparative is 30 June 2025) and the one-figure `Cash and cash equivalents
    | $965` rows of the liquidity tables (no comparative, and not a unique
    run).
- CP-1B, the release's `Caesars | $2,993 | $2,907 | 3.0%`:
  - the 10-Q's `Net revenues | 2,993 | 2,907 | 5,863 | 5,701`, its consolidated
    statement of operations row;
  - the 10-Q's `Total | $2,993 | $2,907 | $5,863 | $5,701`, the total of its
    segment table's net revenues, the consolidated figure;
  - the 10-Q's `Net revenues | $2,993 | $2,907 | $86 | 3.0% | $5,863 | $5,701 |
    $162 | 2.8%`, its MD&A net revenues row;
  - the release's `Net revenues | 2,993 | 2,907 | 5,863 | 5,701`, its
    consolidated statement of operations row.
  Not alternatives: the release's `GAAP net revenues of $3.0 billion versus
    $2.9 billion` (rounded, not the figures) and its six-month `Caesars |
    $5,863 | $5,701 | 2.8%` (another period).
- CP-1B, the release's `Adjusted EBITDA | $920 | $955 | $1,807 | $1,839`:
  - the 10-Q's `Total | $920 | $955 | $1,807 | $1,839`, the total of its
    segment table's Adjusted EBITDA, the consolidated figure;
  - the 10-Q's `Total Adjusted EBITDA | $920 | $955 | $1,807 | $1,839`, its
    MD&A reconciliation's total;
  - the release's `Consolidated Adjusted EBITDA of $920 million versus $955
    million for the comparable prior-year period.`, its highlight sentence:
    consolidated, the quarter against the prior-year quarter;
  - the release's `Caesars | $920 | $955 | (3.7)%`, the consolidated row of its
    quarterly Adjusted EBITDA table;
  - the 10-Q's `Adjusted EBITDA | $920 | $955 | $1,807 | $1,839`, the
    consolidated line its segment note reconciles net loss to. Its words also
    run inside the MD&A's `Total Adjusted EBITDA` row, which no longer bars a
    whole line (K2, F502).
  Not alternatives: the release's six-month `Caesars | $1,807 | $1,839 |
    (1.7)%` (the six months alone).
- CP-1B, the 10-K's `Net revenues | 11,486 | 11,245 | 11,528`:
  - the 10-K's `Total | $11,486 | $11,245 | $11,528`, the total of its segment
    table's net revenues, the consolidated figure;
  - the 10-K's `Net Revenues | $11,486 | $11,245 | $11,528 | $241 | 2.1% |
    $(283) | (2.5)%`, its MD&A net revenues row.
- CP-2, the 10-Q's `Net cash provided by operating activities | 675 | 680`:
  - the 10-Q's `During the six months ended June 30, 2026, our operating
    activities generated operating cash inflows of $675 million, as compared to
    operating cash inflows of $680 million during the six months ended June 30,
    2025, primarily due to changes in working capital, coupled with the results
    of operations described above.`, its liquidity sentence, the six months
    against the prior six months.

The other figure keys (`Long-term debt, net`, `Traditional net leverage (1)`,
`Net cash provided by operating activities`, `Annual maturities of long-term
debt`, `Total debt`, `C-01`) have none: no other whole line states their
figures for the same measure, period and basis (rounded prose such as `$11.8
billion` or `$1.3 billion` is not the figure).

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

The readiness key expects CP-0 to clear all eighteen of the route's consumers
(CP-1, CP-1A, CP-1B, CP-1D, CP-1C, CP-2, CP-2A, CP-2E, CP-4, CP-2D, CP-2G,
CP-2H, CP-3D, CP-3C, CP-4C, CP-3, CP-5, CP-6). CP-6 is expected at `FULL`
decision scope, the catalog pathway's scope. Expected `Restricted`:

- **CP-2H.** No rating action document for CZR is admitted (owner decision,
  2 October 2026). The only rating evidence is what FINRA displayed: Moody's
  `B1` and S&P `BB-` for the 6.50% 2032 notes, Moody's `Caa1` and S&P `B-` for
  the 6.00% 2032 notes, with last-rated dates but no outlook, watch, criteria
  or agency publication. Its blocking rule is security identity, and the pack
  carries two CZR notes with different ratings, so a run that names no
  instrument could block rather than restrict.
- **CP-1A.** The 8-K's Exhibit 2.1 (the Merger Agreement), the financing
  commitments and a pro forma capital structure are not admitted.
- **CP-3D and CP-3.** Each FINRA observation is a single last trade, not bid,
  mid, ask, an evaluated price, a spread or a curve.
- **CP-6.** The mandate is synthetic, and its NAV and compliance check are
  dated 29 May 2026 while the prices are dated 1 October 2026.

**Readiness risks.** The eligible-security universe CP-0 asked for on
`ccl-fy2025-portfolio` does not exist: it is owner content (N127), and the
workbook has only the compliance monitor's C-09 (`Min 1st Lien / Senior
Secured`, `≥ 90.0% NAV`) and C-10 (`Max 2nd Lien / Unsecured`, `≤ 10.0% NAV`)
lien buckets. No admitted document says whether a senior secured bond is an
eligible asset of this CLO, and none is invented, so CP-0 may hold CP-3 and
CP-6 `CONDITIONAL`. CP-4C has no distress evidence: no payment default, failed
refinancing, distressed exchange, covenant breach or filing is documented, so
CP-0 may rate it not applicable rather than ready. Either would miss the
readiness key. No CP-4C register or projection key is set.

No register key is set: no figure here is a single unambiguous register cell.
The mandate's arithmetic is checked in `czr-2026q2-portfolio/RESULT.md`.

## Stated facts the assessment must not misread

The documents state the following; this set draws no conclusion from them.

- **Synthetic, not a holding.** The mandate says "Existing Caesars
  Entertainment exposure: none." and that the position is synthetic.
- **The pending take-private.** The merger would make Caesars a direct wholly
  owned subsidiary of Fertitta Gaming Holdco, LLC; the press release states
  that the transaction is not subject to a financing condition. The
  indenture's Change of Control definition carves out Permitted Holders and
  does not treat a merger agreement as beneficial ownership until
  consummation. All four FINRA last trades postdate the agreement.
- **Seniority.** The 10-Q lists the 6.50% 2032 notes under "Secured Debt" and
  the 6.00% 2032 notes under "Unsecured Debt". No admitted document states the
  seniority of the MGM or PENN notes.
- **As-of dates.** The 10-Q and the releases report the quarter ended
  30 June 2026; the workbook is dated 29 May 2026; the FINRA observations are
  dated 2 October 2026 and their last trades 1 October 2026.

At preparation no provider call, run, snapshot, evidence record, reviewer
verdict, or qualification claim existed; the live runs follow.

## Live results (3–5 October 2026)

| run (file) | build / tip | status | modules accepted | attempts | citations | keys met | ready / projection / register | stop cause | key usage Δ / recorded charge |
|---|---|---|---|---|---|---|---|---|---|
| FCA1 (`FCA1-czr-full-credit-assessment.json`) | 9043ba7f / ~14b9bec | STOPPED | 4/19 | 11 | 122 (121 anch., 5 unver.) | not scored | — | CP-1B attempt 3 dropped, PROVIDER_UNAVAILABLE (re-run once per the owner's ruling) | +0.76 / $0.79 |
| FCA2 (`FCA2-czr-full-credit-assessment.json`) | 9043ba7f / ~14b9bec | BLOCKED | 11 of 19 accepted; CP-2G Blocked; 7 not run | 22 | 295 (294 anch., 15 unver.) | 8/35 | met / missed / — | CP-2G answered Blocked (forecast scope); 7 modules not run | +1.79 / $2.05 |

Reading the table: "build" is the first eight hex digits of the methodology build id in the run JSON; "tip" is the git tip the ledger names (`—` where the ledger names none; tips marked ~ are the base of the next fix task, so the run ran on that tree or its predecessor). "Attempts" is the run JSON's attempt list (every provider call recorded, including a dropped one). "Citations" is the run proof's total with its anchored and unverified counts (`n/r`: the run stopped before a proof was recorded). "Keys met" is the scored matrix row; a run that stopped before COMPLETE or BLOCKED is not scored (`not scored`). "Key usage Δ" is the OpenRouter key-usage change the ledger recorded for the run (`n/l`: not in the ledger); "recorded charge" is the sum of the run's attempt charges at the pinned price. The two disagree and the usage counter lags (ledger), so the key usage is the budget measure. Run files are git-ignored, under `docs/rebuild/runs/live-2026-10-03/`; the model is `openai/gpt-6-luna`, effort high, provider pinned to `openai`, in every row.

Verdict: The set is **NOT QUALIFIED**. FCA2 reached CP-2G and stopped there with a Blocked answer (QA and committee Blocked, confidence 0): "Forecast horizon and base-period choice are not established by the current command or accepted upstream handoffs". The ready key was met and the projection key missed. Of 35 keys 8 were met; 15 are not run (the modules after CP-2G) and the other 12 are "not cited". The 14 Blocked quotes persisted as anchored (D106); 295 citations, 15 of them unverified. 11 modules were accepted (CP-0 to CP-2D, 11 artifacts); CP-2G's single attempt answered Blocked and 7 route modules were not run.

Owner-decision stops and provider limits: **CP-2G forecast-scope gate (owner input):** the case supplies no forecast horizon and no base period, so the module cannot establish its scope; this is an owner input, recorded as N144. FCA1's CP-1B drop is the provider limit: Provider drops: PROVIDER_UNAVAILABLE after about 195 to 299 s on large non-streamed calls, never billed; the owner ruled on 5 October to run without streaming and re-run a dropped module once (L9, streaming in the test adapter, stays unmerged: `PROVIDER_RUNBOOK.md` and N145).

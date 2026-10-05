# CZR Q2 2026 FULL relative-value qualification set — prepared offline

Status: **OFFLINE / UNVERIFIED / NOT QUALIFIED**.

This immutable set prepares `FULL_CREDIT_32 / RELATIVE_VALUE` for Caesars
Entertainment, Inc. (CZR) at an analysis date of 2026-10-02, against peers
MGM Resorts International (MGM) and PENN Entertainment, Inc. (PENN) from the
owner's "Public Leveraged Loan Issuers Benchmark". Its qualification-set
digest is
`a645d01e13330854836b371a4096cf4637b527bf06784151005ef9f5d0745c91`.

## Corpus provenance

The EDGAR documents were fetched on 2 October 2026 and converted from HTML to
plain text the same day. The 10-Q, the 10-K and the CZR earnings release are
byte-identical to the `czr-2026q2` set's copies,  the indenture to the
`czr-2026q2-covenant-refinancing` set's copy, and the MGM and PENN releases to
the `czr-2026q2-lite-relative-value` set's copies. The text SHA-256 is the
digest the keys bind; the raw SHA-256 is the HTML as fetched.

| document | source | accession | text SHA-256 | raw HTML SHA-256 |
|---|---|---|---|---|
| `CZR_Q2_2026_10Q.txt` (Form 10-Q, quarter ended 30 June 2026) | https://www.sec.gov/Archives/edgar/data/1590895/000159089526000028/czr-20260630.htm | 0001590895-26-000028 | `f369ce5f1ebeddd9a0d4ce02ce3958112267d8701d1a348dfd6dc82d2034793a` | `9dd3fca867c49936c65c9729bd7f9478d4c98b7c60569b74864a839bdeed8500` |
| `CZR_FY2025_10K.txt` (Form 10-K, fiscal year ended 31 December 2025) | https://www.sec.gov/Archives/edgar/data/1590895/000159089526000011/czr-20251231.htm | 0001590895-26-000011 | `172309048af2a6a2dab515d765f00a7c89bf8c874c6104a5e3a052b66cad4512` | `41328bdfa2486cfb53b831c2ddba6009528d8dca3a0d868c98c2cb113142b05f` |
| `CZR_Q2_2026_Earnings_Release.txt` (Ex. 99.1, 28 July 2026) | https://www.sec.gov/Archives/edgar/data/1590895/000159089526000027/ex991-2026q2ceiearningsrel.htm | 0001590895-26-000027 | `b385f76ff631243d1053fa8073ebde4f8886b4a50c9ce34ce3498d6b2ac3e9f8` | `a8982154b99b023b526261f7626022e96ac642834d1d65704629946acecc8a1f` |
| `CZR_2024_Credit_Agreement_Incremental_Assumption_No3.txt` (Ex. 10.2, Incremental Assumption Agreement No. 3, 6 February 2024, with Exhibit A, the Credit Agreement conformed through it; Ex. 10.36 in the FY2025 10-K) | https://www.sec.gov/Archives/edgar/data/1590895/000119312524026847/d739529dex102.htm | 0001193125-24-026847 | `25bea1d14fd9bb22838775f6fe056cd00741dc3d50eb1b79cc53498db502941c` | `aa48bc94b634de6386579791df7de831314785f007398546dd5c5fba415f2cfa` |
| `CZR_2024_650_Senior_Secured_Notes_2032_Indenture.txt` (Ex. 10.1, 6.500% Senior Secured Notes due 2032 indenture, 6 February 2024) | https://www.sec.gov/Archives/edgar/data/1590895/000119312524026847/d739529dex101.htm | 0001193125-24-026847 | `0809ab3981090bd2c23950da9530adb10e96882ddfa7db4404635e014d4c1119` | `a4661727edc48361dd7290772e62412c389b8ad8d215a96aa58facfe9e356c2c` |
| `CZR_2024_650_Notes_First_Supplemental_Indenture.txt` (Ex. 4.2, First Supplemental Indenture to the 6.500% 2032 notes indenture, 1 March 2024; Ex. 4.11 in the FY2025 10-K) | https://www.sec.gov/Archives/edgar/data/1590895/000159089524000088/exhibit42firstsupplemental.htm | 0001590895-24-000088 | `0af4615b9a52e91e2675adacbbc90ecc7b21a61dc8205b4b2459cf4b9db0a219` | `18d810c415aef677f867ac73dee07a04382e71db794f3bfbc91cdd185e4b0dc4` |
| `CZR_2024_650_Notes_Second_Supplemental_Indenture.txt` (Ex. 4.17, Second Supplemental Indenture to the 6.500% 2032 notes indenture, 23 August 2024; Ex. 4.12 in the FY2025 10-K) | https://www.sec.gov/Archives/edgar/data/1590895/000159089525000068/exhibit417-6500seniorsecur.htm | 0001590895-25-000068 | `3621f08611f4c6a6faed734993a3f2d9c97041693053ffa97624cbe5b7299aea` | `0eedd7d398ee15f45dabc99df2003249d4dbe232be456767e7b972d355326b3c` |
| `MGM_Q2_2026_Earnings_Release.txt` (MGM Ex. 99.1, 29 July 2026) | https://www.sec.gov/Archives/edgar/data/789570/000078957026000075/mgmex991q22026earningrelea.htm | 0000789570-26-000075 | `795ac68aa1c51a7e0a6799a6e1ca053ee597dc9a1a9a6550a2438280a6e76cdb` | `d23f2410e475eca7e0dfe2fdcca0210f449e4c1a93fb93a14549592c4554173c` |
| `PENN_Q2_2026_Earnings_Release.txt` (PENN Ex. 99.1, 6 August 2026) | https://www.sec.gov/Archives/edgar/data/921738/000092173826000019/pennex991-q22026.htm | 0000921738-26-000019 | `4d12fff94b066f73e6eccce84eec937e8fd4fdc38d6061704db66a40511a210c` | `be60f25fec25022c2fd6f48c2cf9bb99912b8f78356cebc4a7719bdcae9120bc` |

The four FINRA TRACE observations are coordinator-authored transcriptions of
the official public FINRA pages, admitted byte for byte; each file states its
own source URL and observation time, and the file is the text.

| document | source | observed at | SHA-256 |
|---|---|---|---|
| `CZR_FINRA_TRACE_12769GAC4_2026-10-02.txt` (CZR 6.50% due 2032) | https://www.finra.org/finra-data/fixed-income/bond?symbol=ERI5740550&bondType=CORP | 2026-10-02T09:31:13Z | `4018aaa62309df6cd66a9b5fc766c4a9429e886e649023de2bad8673baf8aa51` |
| `CZR_FINRA_TRACE_12769GAD2_2026-10-02.txt` (CZR 6.00% due 2032) | https://www.finra.org/finra-data/fixed-income/bond?symbol=ERI5909471&bondType=CORP | 2026-10-02T09:31:27Z | `256c646128b7b670ebeb2e795aaced255373b488261b7f5c9111f933e2226b24` |
| `MGM_FINRA_TRACE_552953CK5_2026-10-02.txt` (MGM 6.125% due 2029) | https://www.finra.org/finra-data/fixed-income/bond?symbol=MGM5885613&bondType=CORP | 2026-10-02T09:32:08Z | `e17cea1bb90debdeb8c1fea9c352132b57ae9b27ee0d3225fb67c6466d7d0e4a` |
| `PENN_FINRA_TRACE_707569AV1_2026-10-02.txt` (PENN 4.125% due 2029) | https://www.finra.org/finra-data/fixed-income/bond?symbol=PENN5210723&bondType=CORP | 2026-10-02T09:32:31Z | `666c0f36ace32336dffbcff324eaec5b4657edade407bb0b8a0e8d8fb405de6d` |

The indenture (758,385 bytes) and Incremental Assumption Agreement No. 3
(1,077,810 bytes) are over 500 KiB, so their paths are pinned in the large-file
excludes; both are under 1.5 MiB, so they reach CP-0 whole rather than as a
page map. All thirteen are inside `MAX_REQUEST_BYTES`. The exhibits F508 adds
were fetched from SEC EDGAR on 5 October 2026 and converted the same day, split
by sentence (F492) and by clause (F498); they are byte-identical to the
`czr-2026q2-covenant-refinancing` set's copies. Since F508 the conformed copy
in Agreement No. 3's Exhibit A replaces the 2020 credit agreement (Ex. 10.1,
accession 0001193125-20-196232, 935,517 bytes); the supplemental indentures are
11,774 and 15,684 bytes. The set's CP-0 request, encoded with CP-0's delivered
authority, is 2,841,974 bytes (67.8% of `MAX_REQUEST_BYTES`, up from
2,659,557), and no source is shown as a page map.

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
amendment governs. Exhibit A comes without the credit agreement's own exhibits
and schedules: after its Annex A Pricing Grid the file goes straight to
Agreement No. 3's own Exhibit B, a form of solvency certificate. Exhibit A is a
changed copy, Agreement No. 3's insertions double-underlined and its deletions
struck through. On the owner's ruling of 5 October 2026 the text renders the
agreement as amended: every struck run from Exhibit A's cover on is removed
with its content (295 runs, 167 of them with text, 484 characters: superseded
table-of-contents page numbers and 38 words, labels or punctuation) and the
insertions are kept as plain text, with the spacing the filing renders once a
run is gone (one space restored where a run carried the only space between two
words, three places; none left before closing punctuation, three places), so
`Section 2.01(e)` and `Section 2.11(a)(iv)` read as amended. The one struck run
before the cover, the word `strikethrough` in the Agreement's own Section 3
legend, deletes nothing and is kept.

The First Supplemental Indenture (1 March 2024) adds two guarantors and amends
clause (44) of the Permitted Liens definition and Section 8.01(b); the Second
(23 August 2024) adds the guarantors on its Schedule A.

No key is added. On the owner's ruling of 5 October 2026 ("Replace the 2020
base"), the conformed copy replaces the 2020 credit agreement (Ex. 10.1,
accession 0001193125-20-196232), which this set no longer carries: the
agreement as amended is the one in force, and the superseded 2020 text cost
about 0.9 MB of every request. The CP-4 key on the event of default
`(g) there shall have occurred a Change in Control;` is re-keyed to Exhibit A's
same line, one whole line unique in it, whose words are unchanged. The Change
in Control definition it relies on was amended since 2020: clause (a) now names
the 2027 Senior Unsecured, 2025 Senior Secured and 2029 Senior Unsecured Notes
Indentures, the 2029 one added as (iii), and a proviso now deems a person or
group not to beneficially own Equity Interests subject to a merger agreement
until the acquisition is consummated.

## Keys

Keys authored from the documents; material figures pending owner confirmation.

- CP-1: the 10-Q's cash and cash equivalents, `$965` million at 30 June 2026
  and `$887` million at 31 December 2025.
- CP-1C: the 10-Q's Note 6 total debt (`11,807` face, `11,705` book at
  30 June 2026); the CZR release's Adjusted EBITDA (`$920` million for the
  quarter); MGM's long-term debt, net (`6,068,442` thousand at 30 June 2026)
  and its Consolidated Adjusted EBITDA of `$610 million` for the quarter;
  PENN's traditional net leverage of `2.9x` at 30 June 2026.
- CP-2: operating cash flow, `675` for the six months to 30 June 2026 (10-Q)
  and `1,302` for FY2025 (10-K).
- CP-4: the 10-Q's sentence that the revolver, term loans and both secured
  note series are guaranteed on a senior secured basis and secured by
  substantially all assets, and its next sentence, that the CEI Senior Notes
  due 2029 and 2032 are guaranteed on a senior unsecured basis (one key each
  since the F492 sentence split); the
  indenture's Section 2.01 issue amount (`$1,500,000,000`); the credit
  agreement's "(g) there shall have occurred a Change in Control;" event of
  default.
- CP-3D: the last trade prices of the two CZR notes, `$93.28` (6.50% 2032)
  and `$84.94` (6.00% 2032).
- CP-3: the last trade yields of the peer notes, `6.722997%` (MGM 6.125%
  2029) and `6.644415%` (PENN 4.125% 2029).

The conformed credit agreement's commitment, margins and covenant (Agreement
No. 3's Exhibit A, F508) are not keyed: the Fourth and Fifth Amendments, which
this set does not carry, post-date it; the current revolver (`$2.25 billion`,
maturing 31 January 2028) is stated in the 10-Q.

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
- CP-1C, the release's `Adjusted EBITDA | $920 | $955 | $1,807 | $1,839`:
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
- CP-2, the 10-Q's `Net cash provided by operating activities | 675 | 680`:
  - the 10-Q's `During the six months ended June 30, 2026, our operating
    activities generated operating cash inflows of $675 million, as compared to
    operating cash inflows of $680 million during the six months ended June 30,
    2025, primarily due to changes in working capital, coupled with the results
    of operations described above.`, its liquidity sentence, the six months
    against the prior six months.

The other figure keys (`Total debt`, `Long-term debt, net`, `Traditional net
leverage (1)`, `Net cash provided by operating activities`) have none: no other
whole line states their figures for the same measure, period and basis (rounded
prose such as `$11.8 billion` or `$1.3 billion` is not the figure).

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
fact.

The readiness key expects CP-0 to clear the route's eight consumers (CP-1,
CP-1C, CP-2, CP-4, CP-3D, CP-2A, CP-2G, CP-3). CP-3 is expected at `FULL`
decision scope, the catalog pathway's scope, and CP-3D and CP-3 must remain
`Restricted`: each FINRA observation is a single last trade, not bid, mid,
ask, an evaluated price, a spread or a curve. No register key is set: no
figure here is a single unambiguous register cell.

## Comparability traps (stated facts only)

The documents state the following; this set draws no conclusion from them.

- **Tenor and seniority.** The CZR 6.50% notes mature 15 February 2032 and are
  listed under "Secured Debt" in the 10-Q; the CZR 6.00% notes mature
  15 October 2032 and are listed under "Unsecured Debt". The MGM 6.125% notes
  mature 15 September 2029 and the PENN 4.125% notes 1 July 2029. No admitted
  document states the MGM or PENN notes' seniority: FINRA displayed none, the
  PENN release lists "4.125% Notes due 2029" without a seniority label, and
  the MGM release names no note.
- **The 144A label.** FINRA showed "transactions effected pursuant to SEC Rule
  144A" for both CZR notes and the PENN note. The MGM observation shows no
  offering-status line.
- **The pending take-private.** The 10-Q states that on 27 May 2026 Caesars
  entered into an Agreement and Plan of Merger under which Merger Sub "will
  merge with and into the Company, with the Company continuing as the
  surviving corporation and direct wholly owned subsidiary of Fertitta Gaming
  (the “Merger”)". Both CZR last trades are dated 1 October 2026, after that
  agreement: `$93.28` / `8.063520%` (6.50% 2032) and `$84.94` / `9.318398%`
  (6.00% 2032). The peers' last trades are dated the same day: MGM `$98.42` /
  `6.722997%`, PENN `$93.76` / `6.644415%`.

The peers' periods match CZR's: each release reports the quarter ended
30 June 2026.

No provider call, run, snapshot, evidence record, reviewer verdict, or
qualification claim exists; no run has been performed.

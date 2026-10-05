# CZR Q2 2026 FULL relative-value qualification set — prepared offline

Status: **OFFLINE / UNVERIFIED / NOT QUALIFIED**.

This immutable set prepares `FULL_CREDIT_32 / RELATIVE_VALUE` for Caesars
Entertainment, Inc. (CZR) at an analysis date of 2026-10-02, against peers
MGM Resorts International (MGM) and PENN Entertainment, Inc. (PENN) from the
owner's "Public Leveraged Loan Issuers Benchmark". Its qualification-set
digest is
`0b78114a7cfd6a1de01f089e7ee5e1d70d01e33534e29c0b5f1abd752d70ee43`.

## Corpus provenance

The EDGAR documents were fetched on 2 October 2026 and converted from HTML to
plain text the same day. The 10-Q, the 10-K and the CZR earnings release are
byte-identical to the `czr-2026q2` set's copies, the credit agreement to the
`czr-2026q2-liquidity` set's copy, the indenture to the
`czr-2026q2-covenant-refinancing` set's copy, and the MGM and PENN releases to
the `czr-2026q2-lite-relative-value` set's copies. The text SHA-256 is the
digest the keys bind; the raw SHA-256 is the HTML as fetched.

| document | source | accession | text SHA-256 | raw HTML SHA-256 |
|---|---|---|---|---|
| `CZR_Q2_2026_10Q.txt` (Form 10-Q, quarter ended 30 June 2026) | https://www.sec.gov/Archives/edgar/data/1590895/000159089526000028/czr-20260630.htm | 0001590895-26-000028 | `9af04315eddd61ee7655445939d21bc91780c57c3689134c7c77d85c3dfb7e01` | `9dd3fca867c49936c65c9729bd7f9478d4c98b7c60569b74864a839bdeed8500` |
| `CZR_FY2025_10K.txt` (Form 10-K, fiscal year ended 31 December 2025) | https://www.sec.gov/Archives/edgar/data/1590895/000159089526000011/czr-20251231.htm | 0001590895-26-000011 | `4738e21322c565366a5e68be47fbacb894b869611ba9b52a353ed69b648abc48` | `41328bdfa2486cfb53b831c2ddba6009528d8dca3a0d868c98c2cb113142b05f` |
| `CZR_Q2_2026_Earnings_Release.txt` (Ex. 99.1, 28 July 2026) | https://www.sec.gov/Archives/edgar/data/1590895/000159089526000027/ex991-2026q2ceiearningsrel.htm | 0001590895-26-000027 | `98f970cb6b12ade42729b4d926792a5e866a724878d1ce4f76de06cf4aa58d1d` | `a8982154b99b023b526261f7626022e96ac642834d1d65704629946acecc8a1f` |
| `CZR_2020_Credit_Agreement.txt` (Ex. 10.1, Credit Agreement dated 20 July 2020) | https://www.sec.gov/Archives/edgar/data/1590895/000119312520196232/d940333dex101.htm | 0001193125-20-196232 | `4b3013342047cf6928ad18a3518180bb160c2e5251b5414eee71d95e8b95cf97` | `6600ab5bec479091f68dc04b2db65a54ef1013944c94af0ec135335b374c7dba` |
| `CZR_2024_650_Senior_Secured_Notes_2032_Indenture.txt` (Ex. 10.1, 6.500% Senior Secured Notes due 2032 indenture, 6 February 2024) | https://www.sec.gov/Archives/edgar/data/1590895/000119312524026847/d739529dex101.htm | 0001193125-24-026847 | `85ca330865d6ed47de838cbd3e45a69d29b57640e91782a71f2639721ac665db` | `a4661727edc48361dd7290772e62412c389b8ad8d215a96aa58facfe9e356c2c` |
| `MGM_Q2_2026_Earnings_Release.txt` (MGM Ex. 99.1, 29 July 2026) | https://www.sec.gov/Archives/edgar/data/789570/000078957026000075/mgmex991q22026earningrelea.htm | 0000789570-26-000075 | `e1b78fe31d332f0aa176cb34bc7e534d8653af5655f556add085bb4b24414902` | `d23f2410e475eca7e0dfe2fdcca0210f449e4c1a93fb93a14549592c4554173c` |
| `PENN_Q2_2026_Earnings_Release.txt` (PENN Ex. 99.1, 6 August 2026) | https://www.sec.gov/Archives/edgar/data/921738/000092173826000019/pennex991-q22026.htm | 0000921738-26-000019 | `8b28aee4b06aee46e9f99486ca71608149c1fb5544d7f915c3b287bb0f31a5d1` | `be60f25fec25022c2fd6f48c2cf9bb99912b8f78356cebc4a7719bdcae9120bc` |

The four FINRA TRACE observations are coordinator-authored transcriptions of
the official public FINRA pages, admitted byte for byte; each file states its
own source URL and observation time, and the file is the text.

| document | source | observed at | SHA-256 |
|---|---|---|---|
| `CZR_FINRA_TRACE_12769GAC4_2026-10-02.txt` (CZR 6.50% due 2032) | https://www.finra.org/finra-data/fixed-income/bond?symbol=ERI5740550&bondType=CORP | 2026-10-02T09:31:13Z | `4018aaa62309df6cd66a9b5fc766c4a9429e886e649023de2bad8673baf8aa51` |
| `CZR_FINRA_TRACE_12769GAD2_2026-10-02.txt` (CZR 6.00% due 2032) | https://www.finra.org/finra-data/fixed-income/bond?symbol=ERI5909471&bondType=CORP | 2026-10-02T09:31:27Z | `256c646128b7b670ebeb2e795aaced255373b488261b7f5c9111f933e2226b24` |
| `MGM_FINRA_TRACE_552953CK5_2026-10-02.txt` (MGM 6.125% due 2029) | https://www.finra.org/finra-data/fixed-income/bond?symbol=MGM5885613&bondType=CORP | 2026-10-02T09:32:08Z | `e17cea1bb90debdeb8c1fea9c352132b57ae9b27ee0d3225fb67c6466d7d0e4a` |
| `PENN_FINRA_TRACE_707569AV1_2026-10-02.txt` (PENN 4.125% due 2029) | https://www.finra.org/finra-data/fixed-income/bond?symbol=PENN5210723&bondType=CORP | 2026-10-02T09:32:31Z | `666c0f36ace32336dffbcff324eaec5b4657edade407bb0b8a0e8d8fb405de6d` |

The credit agreement (935,517 bytes) and the indenture (758,385 bytes) are over
500 KiB, so their paths are pinned in the large-file excludes; both are under
1.5 MiB, so they reach CP-0 whole rather than as a page map. All eleven are
inside `MAX_REQUEST_BYTES`.

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
- CP-4: the 10-Q's statement that the revolver, term loans and both secured
  note series are guaranteed on a senior secured basis while the CEI Senior
  Notes due 2029 and 2032 are guaranteed on a senior unsecured basis; the
  indenture's Section 2.01 issue amount (`$1,500,000,000`); the credit
  agreement's "(g) there shall have occurred a Change in Control;" event of
  default.
- CP-3D: the last trade prices of the two CZR notes, `$93.28` (6.50% 2032)
  and `$84.94` (6.00% 2032).
- CP-3: the last trade yields of the peer notes, `6.722997%` (MGM 6.125%
  2029) and `6.644415%` (PENN 4.125% 2029).

The 2020 credit agreement's commitment, margins and covenant were changed by
amendments not in this set and are not keyed; the current revolver
(`$2.25 billion`, maturing 31 January 2028) is stated in the 10-Q.

Every key is one whole evidence line of its page, unique in its document: an
answer is accepted only as a whole line (`WHOLE_LINE`) and scored by exact
equality, so a fragment could never be met (F235, F475). Where a fact sits
inside a longer line, the key is that whole line.

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

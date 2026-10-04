# CZR Q2 2026 LITE relative-value qualification set — prepared offline

Status: **OFFLINE / UNVERIFIED / NOT QUALIFIED**.

This immutable set prepares `LITE_CREDIT_22 / LITE_RELATIVE_VALUE` for
Caesars Entertainment, Inc. (CZR) at an analysis date of 2026-10-02, against
peers MGM Resorts International (MGM) and PENN Entertainment, Inc. (PENN) from
the owner's "Public Leveraged Loan Issuers Benchmark". Its qualification-set
digest is
`e76f4b0f4ff423e170792110f41e453214e24aa5207eeb8f6374a93623e03b97`.

## Corpus provenance

Each document is an official SEC EDGAR filing or exhibit, fetched on
2 October 2026 and converted from HTML to plain text the same day. The 10-Q
and the CZR earnings release are byte-identical to the `czr-2026q2` set's
copies, the credit agreement to the `czr-2026q2-liquidity` set's copy, and the
indenture to the `czr-2026q2-covenant-refinancing` set's copy. The MGM and
PENN releases are admitted here for the first time. The text SHA-256 is the
digest the keys bind; the raw SHA-256 is the HTML as fetched.

| document | source | accession | text SHA-256 | raw HTML SHA-256 |
|---|---|---|---|---|
| `CZR_Q2_2026_10Q.txt` (Form 10-Q, quarter ended 30 June 2026) | https://www.sec.gov/Archives/edgar/data/1590895/000159089526000028/czr-20260630.htm | 0001590895-26-000028 | `f369ce5f1ebeddd9a0d4ce02ce3958112267d8701d1a348dfd6dc82d2034793a` | `9dd3fca867c49936c65c9729bd7f9478d4c98b7c60569b74864a839bdeed8500` |
| `CZR_Q2_2026_Earnings_Release.txt` (Ex. 99.1, 28 July 2026) | https://www.sec.gov/Archives/edgar/data/1590895/000159089526000027/ex991-2026q2ceiearningsrel.htm | 0001590895-26-000027 | `b385f76ff631243d1053fa8073ebde4f8886b4a50c9ce34ce3498d6b2ac3e9f8` | `a8982154b99b023b526261f7626022e96ac642834d1d65704629946acecc8a1f` |
| `CZR_2020_Credit_Agreement.txt` (Ex. 10.1, Credit Agreement dated 20 July 2020) | https://www.sec.gov/Archives/edgar/data/1590895/000119312520196232/d940333dex101.htm | 0001193125-20-196232 | `47f555d66a20792e3cb727303403d172e0a73f7bcadf513fb77cd055d69b333c` | `6600ab5bec479091f68dc04b2db65a54ef1013944c94af0ec135335b374c7dba` |
| `CZR_2024_650_Senior_Secured_Notes_2032_Indenture.txt` (Ex. 10.1, 6.500% Senior Secured Notes due 2032 indenture, 6 February 2024) | https://www.sec.gov/Archives/edgar/data/1590895/000119312524026847/d739529dex101.htm | 0001193125-24-026847 | `8b91b49c89df261cb7c49dc85c3693f8d6ccbbfabc4698aa240c8b71750412a5` | `a4661727edc48361dd7290772e62412c389b8ad8d215a96aa58facfe9e356c2c` |
| `MGM_Q2_2026_Earnings_Release.txt` (MGM Ex. 99.1, 29 July 2026) | https://www.sec.gov/Archives/edgar/data/789570/000078957026000075/mgmex991q22026earningrelea.htm | 0000789570-26-000075 | `795ac68aa1c51a7e0a6799a6e1ca053ee597dc9a1a9a6550a2438280a6e76cdb` | `d23f2410e475eca7e0dfe2fdcca0210f449e4c1a93fb93a14549592c4554173c` |
| `PENN_Q2_2026_Earnings_Release.txt` (PENN Ex. 99.1, 6 August 2026) | https://www.sec.gov/Archives/edgar/data/921738/000092173826000019/pennex991-q22026.htm | 0000921738-26-000019 | `4d12fff94b066f73e6eccce84eec937e8fd4fdc38d6061704db66a40511a210c` | `be60f25fec25022c2fd6f48c2cf9bb99912b8f78356cebc4a7719bdcae9120bc` |

The credit agreement (935,517 bytes) and the indenture (758,385 bytes) are over
500 KiB, so their paths are pinned in the large-file excludes; both are under
1.5 MiB, so they reach CP-0 whole rather than as a page map. All six are
inside `MAX_REQUEST_BYTES`.

## Why the pack carries a credit agreement and an indenture

The CCL LITE relative-value set (`ccl-fy2025-relative-value`) stopped at CP-0's
readiness gate (N54): its pack held no instrument and no governing document, so
CP-0 could not clear its consumers to compare instruments. This set adds CZR's
credit agreement and the indenture of the 6.50% 2032 senior secured notes for
that reason. Neither carries a key: the 2020 credit agreement's commitment,
margins and covenant were changed by amendments not in this set, and the
current revolver is keyed from the 10-Q instead.

## Keys

Keys authored from the documents; material figures pending owner confirmation.

- CP-L10: the 10-Q's `$1.9 billion` of available CEI revolver capacity at
  30 June 2026, and its annual maturities of long-term debt totalling
  `$11,807` million.
- CP-1C, CZR: the 10-Q's Note 6 total debt (`11,807` face, `11,705` book at
  30 June 2026; `11,792` book at 31 December 2025) and its row for the CEI
  Senior Secured Notes due 2032 (`6.50%`, `1,500` face); the release's
  Adjusted EBITDA (`$920` million for the quarter, `$1,807` million for the
  six months).
- CP-1C, MGM: long-term debt, net, `6,068,442` thousand at 30 June 2026, and
  the highlight bullet for Consolidated Adjusted EBITDA of `$610 million` in
  the quarter.
- CP-1C, PENN: traditional net leverage of `2.9x` at 30 June 2026 (`4.5x` at
  31 December 2025).

Alternative lines (D101). A figure key is also met by another whole evidence
line, cited under the same module, that states the key's lead figures -- the
current figure and the comparative the key line leads with -- for the same
measure, period and consolidated scope; a % change, a further period or a third
year on the key line need not be on it. Prose keys have none: a statement is
its sentence. Each alternative is one whole evidence line, unique in its
document (F475), and is listed with why it states the key's figures:

- CP-1C, the release's `Adjusted EBITDA | $920 | $955 | $1,807 | $1,839`:
  - the 10-Q's `Total | $920 | $955 | $1,807 | $1,839`, the total of its
    segment table's Adjusted EBITDA, the consolidated figure;
  - the 10-Q's `Total Adjusted EBITDA | $920 | $955 | $1,807 | $1,839`, its
    MD&A reconciliation's total;
  - the release's `Consolidated Adjusted EBITDA of $920 million versus $955
    million for the comparable prior-year period.`, its highlight sentence:
    consolidated, the quarter against the prior-year quarter;
  - the release's `Caesars | $920 | $955 | (3.7)%`, the consolidated row of its
    quarterly Adjusted EBITDA table.
  Not alternatives: the 10-Q's `Adjusted EBITDA | $920 | $955 | $1,807 |
    $1,839` (its words recur inside the 10-Q's `Total Adjusted EBITDA` row, so
    it is not a unique run, F475) and the release's six-month `Caesars | $1,807
    | $1,839 | (1.7)%` (the six months alone).

The other figure keys (`Annual maturities of long-term debt`, `Total debt`,
`CEI Senior Secured Notes due 2032`, `Long-term debt, net`, `Traditional net
leverage (1)`) have none: no other whole line states their figures for the same
measure, period and basis (rounded prose such as `$11.8 billion` or `$1.3
billion` is not the figure).

Every key is one whole evidence line of its page, unique in its document: an
answer is accepted only as a whole line (`WHOLE_LINE`) and scored by exact
equality, so a fragment could never be met (F235, F475). Where a fact sits
inside a longer line, the key is that whole line. Since F492 a prose line of a
converted filing is one sentence, so a key is the sentence that carries its
fact.
Since F498 a sentence of a legal instrument (the credit agreement, its
amendments, the indenture, the merger 8-K) over 400 characters is cut further
at its clause boundaries (`; (b)`, `; and`, `; provided`, `, provided that`,
`: (a)`), so a key there is the clause that carries its fact.

The readiness key expects CP-0 to clear CP-L10 and CP-1C, both at
`SCREENING_ONLY` decision scope, the catalog pathway's scope. The one register
key expects CP-L10's `TL10.2` `LIQUIDITY_MATURITIES` row to read `SUFFICIENT`:
the 10-Q carries both the revolver availability and the full maturity ladder,
so the evidence status is unambiguous. No arithmetic is keyed; no leverage
cell is keyed, because each issuer's denominator is its own non-GAAP measure.

## Comparability traps (stated facts only)

The documents state the following; this set draws no conclusion from them.

- **Tenor and seniority.** The 10-Q lists the CEI Senior Secured Notes due
  2032 (`6.50%`, final maturity 2032) under "Secured Debt" and the CEI Senior
  Notes due 2032 (`6.00%`) under "Unsecured Debt". The PENN release lists
  "4.125% Notes due 2029" without a seniority label. The MGM release names no
  note. The peer instruments compared in the FULL set
  (`czr-2026q2-relative-value`) are MGM's 6.125% notes maturing 15 September
  2029 and PENN's 4.125% notes maturing 1 July 2029; no admitted document
  states their seniority, and FINRA displayed none.
- **The 144A label.** FINRA showed "transactions effected pursuant to SEC Rule
  144A" for both CZR notes and the PENN note, and no offering-status line for
  the MGM note. Those observations are in the FULL set, not this pack.
- **The pending take-private.** The 10-Q states that on 27 May 2026 Caesars
  entered into an Agreement and Plan of Merger under which Merger Sub "will
  merge with and into the Company, with the Company continuing as the
  surviving corporation and direct wholly owned subsidiary of Fertitta Gaming
  (the “Merger”)". The CZR last trades the FULL set records (1 October 2026)
  were printed after that agreement.

The peers' periods match CZR's: each release reports the quarter ended
30 June 2026.

No provider call, run, snapshot, evidence record, reviewer verdict, or
qualification claim exists; no run has been performed.

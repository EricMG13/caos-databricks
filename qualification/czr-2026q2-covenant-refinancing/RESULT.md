# CZR Q2 2026 FULL covenant-refinancing qualification set — prepared offline

Status: **OFFLINE / UNVERIFIED / NOT QUALIFIED**.

This immutable set prepares `FULL_CREDIT_32 / COVENANT_REFINANCING` for
Caesars Entertainment, Inc. (CZR) at an analysis date of 2026-10-02. Its
qualification-set digest is
`d9b9f7a2b8b437ef254b0d3ec56a74270f501557b75b02dd0436ef1a190cd599`.

## Corpus provenance

Each document is an official SEC EDGAR filing or exhibit, fetched on
2 October 2026 and converted from HTML to plain text the same day. The 10-K
and 10-Q are byte-identical to the `czr-2026q2` set's copies and the credit
agreement to the `czr-2026q2-liquidity` set's copy; the other five are first
admitted here. The text SHA-256 is the digest the keys bind; the raw SHA-256
is the HTML as fetched.

| document | source | accession | text SHA-256 | raw HTML SHA-256 |
|---|---|---|---|---|
| `CZR_FY2025_10K.txt` (Form 10-K, year ended 31 December 2025) | https://www.sec.gov/Archives/edgar/data/1590895/000159089526000011/czr-20251231.htm | 0001590895-26-000011 | `172309048af2a6a2dab515d765f00a7c89bf8c874c6104a5e3a052b66cad4512` | `41328bdfa2486cfb53b831c2ddba6009528d8dca3a0d868c98c2cb113142b05f` |
| `CZR_Q2_2026_10Q.txt` (Form 10-Q, quarter ended 30 June 2026) | https://www.sec.gov/Archives/edgar/data/1590895/000159089526000028/czr-20260630.htm | 0001590895-26-000028 | `f369ce5f1ebeddd9a0d4ce02ce3958112267d8701d1a348dfd6dc82d2034793a` | `9dd3fca867c49936c65c9729bd7f9478d4c98b7c60569b74864a839bdeed8500` |
| `CZR_2020_Credit_Agreement.txt` (Ex. 10.1, Credit Agreement dated 20 July 2020) | https://www.sec.gov/Archives/edgar/data/1590895/000119312520196232/d940333dex101.htm | 0001193125-20-196232 | `47f555d66a20792e3cb727303403d172e0a73f7bcadf513fb77cd055d69b333c` | `6600ab5bec479091f68dc04b2db65a54ef1013944c94af0ec135335b374c7dba` |
| `CZR_2024_Credit_Agreement_Fourth_Amendment.txt` (Ex. 10.1, Fourth Amendment, 9 May 2024) | https://www.sec.gov/Archives/edgar/data/1590895/000119312524135268/d827488dex101.htm | 0001193125-24-135268 | `201febfc086288265481ff3d0ba0635799acefe923b12e4827959070c018da51` | `b0e9fc14d481410dd2fa3cb6bc28e4f9c3b8751d720777ab2bbf943143f6d0fb` |
| `CZR_2024_Credit_Agreement_Fifth_Amendment.txt` (Ex. 10.1, Fifth Amendment, 25 November 2024) | https://www.sec.gov/Archives/edgar/data/1590895/000119312524265157/d858083dex101.htm | 0001193125-24-265157 | `a8bd93197f87e2b86375472c0d0d0e8da3bb1f7f852766c8ff746b81a496eaf6` | `0936486e71264a9b752d5977c003bfc9a89ec5eb4ca8e5b09107a7870ebf86e8` |
| `CZR_2024_650_Senior_Secured_Notes_2032_Indenture.txt` (Ex. 10.1, 6.500% Senior Secured Notes due 2032 indenture, 6 February 2024) | https://www.sec.gov/Archives/edgar/data/1590895/000119312524026847/d739529dex101.htm | 0001193125-24-026847 | `8b91b49c89df261cb7c49dc85c3693f8d6ccbbfabc4698aa240c8b71750412a5` | `a4661727edc48361dd7290772e62412c389b8ad8d215a96aa58facfe9e356c2c` |
| `CZR_2026_Merger_Agreement_8K.txt` (Form 8-K, Item 1.01, 27 May 2026) | https://www.sec.gov/Archives/edgar/data/1590895/000119312526242995/d143382d8k.htm | 0001193125-26-242995 | `52bbcf8fbb8bcf29cfba66d358c67a9b1585516d11b1a30922c0cea02b812c8b` | `aabda22b745ac6c2e5d8462be19fbc47b6cafbe58d21f8c2750a1c195cf24f96` |
| `CZR_2026_Merger_Press_Release.txt` (Ex. 99.1, press release, 28 May 2026) | https://www.sec.gov/Archives/edgar/data/1590895/000119312526242995/d143382dex991.htm | 0001193125-26-242995 | `4fbecbd5f5a10b15911b5749daee41b3e40090e43ed54bf33aee07a21877e68b` | `2a4ed12c96147f2171451c93524bea31ecad37247448d27039f755a3cf85f51f` |

The credit agreement (935,517 bytes) and the indenture (758,385 bytes) are over
500 KiB, so their paths are pinned in the large-file excludes; both are under
1.5 MiB, so they reach CP-0 whole rather than as a page map. All eight are
inside `MAX_REQUEST_BYTES`.

## Keys

Keys authored from the documents; material figures pending owner confirmation.

- CP-1: the 10-Q's cash and cash equivalents, `$965` / `$887` million at
  30 June 2026 / 31 December 2025; and the 10-K's total debt, `11,905` face and
  `11,792` book at 31 December 2025, `12,154` book at 31 December 2024.
- CP-2: the 10-Q's six-month operating cash flow, `675` / `680` million.
- CP-2D: the 10-Q's annual maturities of long-term debt, `$55` / `$114` /
  `$767` / `$1,574` / `$3,962` / `$5,335` million for the rest of 2026,
  2027–2030 and thereafter, totalling `$11,807` million; and its `$1.9 billion`
  of available CEI revolver capacity at 30 June 2026.
- CP-4: the 10-Q's Note 6 statement that the Company was in compliance with
  all of the applicable financial covenants at 30 June 2026 (the covenant
  levels themselves, `6.50:1` net total leverage and `2.0:1` fixed charge
  coverage, sit on a line the 10-Q repeats in its MD&A, so neither copy is a
  unique whole line); the credit agreement's event of default `(g) there shall have occurred a
  Change in Control;`; the Fourth Amendment's restated Term SOFR Adjustment
  (`0.10%` for Term A and the Initial Revolving Facility, `0.00%` for Term B
  and Term B-1); the Fifth Amendment's restated Applicable Margin (`2.25%` Term
  Benchmark, `1.25%` ABR for Term B and Term B-1); and the indenture's
  `$1,500,000,000` issue amount and Section 4.08(a) repurchase right at `101%`.
- CP-3C: the 10-Q's statement that the CEI Credit Agreement, as amended,
  provides for a `$2.25 billion` revolver maturing on 31 January 2028, and its
  risk-factor sentence on change-in-control provisions; the indenture's
  Change of Control clause (2) and its merger-agreement beneficial-ownership
  proviso; the 8-K's merger structure; and the press release's transaction
  value, assumed debt and financing sources.
- CP-5: the 10-Q's Note 6 total debt, `11,807` face and `11,705` book at
  30 June 2026, `11,792` book at 31 December 2025.

Each amendment is keyed for what it changes and what is still in force: the
Fourth Amendment's Term B margin of `2.75%` is superseded by the Fifth's
`2.25%`, so only its Term SOFR Adjustment is keyed; the 10-Q confirms both
current terms (a `0.10%` adjustment on the revolver and Term Loan A, a
`2.25%` / `1.25%` margin on Term B and Term B-1). The 2020 credit agreement's
commitment, margins and financial covenant are not keyed: the First to Third
Amendments and the incremental assumption agreements that changed them are
not in this set. Its Change in Control event of default is keyed as executed;
Amendments 1–3 are not in this set (the 10-K's exhibit index lists them), and
neither amendment in the set alters it.

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

The other figure keys (`Cash and cash equivalents`, `Total debt`, `Annual
maturities of long-term debt`, `Total debt`) have none: no other whole line
states their figures for the same measure, period and basis (rounded prose such
as `$11.8 billion` or `$1.3 billion` is not the figure).

Every key is one whole evidence line of its page, unique in its document: an
answer is accepted only as a whole line (`WHOLE_LINE`) and scored by exact
equality, so a fragment could never be met (F235, F475). Where a fact sits
inside a longer line, the key is that whole line. Since F492 a prose line of a
converted filing is one sentence, so a key is the sentence that carries its
fact.
Since F498 a sentence of a legal instrument (the credit agreement, its
amendments, the indenture, the merger 8-K) over 400 characters is cut further
at its clause boundaries (`; (b)`, `; and`, `; provided`, `, provided that`,
`: (a)`), so a key there is the clause that carries its fact. The indenture's
Section 4.08(a) key is so restated as the clause that grants the `101%`
repurchase right, ending
`in accordance with the terms contemplated in this Section 4.08;`; its
`provided, however,` proviso (no repurchase of Notes the Company has exercised
its right to redeem) is now the next line and is not keyed, as it carries none
of the key's figures.

The readiness key expects CP-0 to clear CP-1, CP-4, CP-2, CP-2D, CP-3C and
CP-5, and CP-4 and CP-3C to carry `FULL` decision scope. No register key is
set: no single covenant or maturity cell is the unambiguous answer to a
covenant-and-refinancing question.

## Change-of-control relevance of the pending merger (stated facts only)

The documents state the following; this set draws no conclusion from them.

- The 8-K (Item 1.01) says Merger Sub "will merge with and into the Company,
  with the Company continuing as the surviving corporation and direct wholly
  owned subsidiary of Parent (the “Merger”)", Parent being Fertitta Gaming
  Holdco, LLC.
- The press release says the transaction is "valued at approximately $17.6
  billion, including the assumption of approximately $11.9 billion of
  Caesars’ outstanding debt", and that it "will be financed through a
  combination of equity contributed by Fertitta Entertainment, assumed
  Caesars’ debt, and new committed debt financing arranged by a group
  consisting of 10 banks."
- The indenture defines a Change of Control to include any person or group,
  other than Permitted Holders, becoming the beneficial owner "directly or
  indirectly, of more than 50% of the Equity Interests of the Company entitled
  to vote for members of the board of directors (or equivalent governing
  body).", and provides that a person "shall be deemed not to beneficially own
  Equity Interests subject to a stock or asset purchase agreement, merger
  agreement, ... until the consummation of the acquisition of the Equity
  Interests in connection with the transactions contemplated by such
  agreement."
- Section 4.08(a) of the indenture: "Upon the occurrence of a Change of
  Control, each holder shall have the right to require the Company to
  repurchase all or any part of such holder’s Notes at a purchase price in
  cash equal to 101% of the principal amount thereof, plus accrued and unpaid
  interest".
- The credit agreement lists "(g) there shall have occurred a Change in
  Control;" among its events of default. Its Change in Control definition
  (as executed; Amendments 1–3, which the 10-K's exhibit index lists, are not
  in this set) covers a "“change of control” (or similar event)" under the notes
  indentures it names (those of 6 July 2020, and indentures for Permitted
  Refinancing Indebtedness or Junior Financing constituting Material
  Indebtedness) and any person or group, other than Permitted Holders,
  acquiring "more than 50% of the Equity Interests of the Borrower entitled to
  vote".
- The 10-Q's risk factors say: "The Company may incur additional costs or
  suffer loss of business under third-party contracts that are terminated or
  that contain change in control or other provisions that may be triggered by
  the completion of the Merger,".

Whether the Merger, if completed, is a Change of Control under the indenture
or a Change in Control under the credit agreement is not determined here, and
no key asserts either. The 10-Q discloses the merger as pending; no fact about
it after the 10-Q's filing is in this set.

No provider call, run, snapshot, evidence record, reviewer verdict, or
qualification claim exists; no run has been performed.

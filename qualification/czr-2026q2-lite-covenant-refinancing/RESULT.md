# CZR Q2 2026 LITE covenant-refinancing qualification set — prepared offline

Status: **OFFLINE / UNVERIFIED / NOT QUALIFIED**.

This immutable set prepares `LITE_CREDIT_22 / LITE_COVENANT_REFINANCING` for
Caesars Entertainment, Inc. (CZR) at an analysis date of 2026-10-02. Its
qualification-set digest is
`35eb452da5a30ccddc768b707f9c3239526931498d58e0568ded03a09c590fe0`.

## Corpus provenance

Each document is an official SEC EDGAR filing or exhibit, fetched on
2 October 2026 and converted from HTML to plain text the same day. The 10-Q is
byte-identical to the `czr-2026q2` set's copy, the credit agreement to the
`czr-2026q2-liquidity` set's copy, and the other four to the
`czr-2026q2-covenant-refinancing` set's copies. The text SHA-256 is the digest
the keys bind; the raw SHA-256 is the HTML as fetched.

| document | source | accession | text SHA-256 | raw HTML SHA-256 |
|---|---|---|---|---|
| `CZR_Q2_2026_10Q.txt` (Form 10-Q, quarter ended 30 June 2026) | https://www.sec.gov/Archives/edgar/data/1590895/000159089526000028/czr-20260630.htm | 0001590895-26-000028 | `1b2027659f255471d41243180c9b550c6915348b7aea79619634c5a9d7b0187c` | `9dd3fca867c49936c65c9729bd7f9478d4c98b7c60569b74864a839bdeed8500` |
| `CZR_2020_Credit_Agreement.txt` (Ex. 10.1, Credit Agreement dated 20 July 2020) | https://www.sec.gov/Archives/edgar/data/1590895/000119312520196232/d940333dex101.htm | 0001193125-20-196232 | `b4f124cb0e058b06453f2037bb70e4455600a6006b6559c03721918b5e36f2e2` | `6600ab5bec479091f68dc04b2db65a54ef1013944c94af0ec135335b374c7dba` |
| `CZR_2024_Credit_Agreement_Fourth_Amendment.txt` (Ex. 10.1, Fourth Amendment, 9 May 2024) | https://www.sec.gov/Archives/edgar/data/1590895/000119312524135268/d827488dex101.htm | 0001193125-24-135268 | `41ade7909f87770dcfaeaa4d4967d4b43ce23b1974a833b95709b6d1cced2fe1` | `b0e9fc14d481410dd2fa3cb6bc28e4f9c3b8751d720777ab2bbf943143f6d0fb` |
| `CZR_2024_Credit_Agreement_Fifth_Amendment.txt` (Ex. 10.1, Fifth Amendment, 25 November 2024) | https://www.sec.gov/Archives/edgar/data/1590895/000119312524265157/d858083dex101.htm | 0001193125-24-265157 | `ffe543a0655c04005e4f4db2cc14fcfb9340656d3dc2e96f6536678fbf096288` | `0936486e71264a9b752d5977c003bfc9a89ec5eb4ca8e5b09107a7870ebf86e8` |
| `CZR_2024_650_Senior_Secured_Notes_2032_Indenture.txt` (Ex. 10.1, 6.500% Senior Secured Notes due 2032 indenture, 6 February 2024) | https://www.sec.gov/Archives/edgar/data/1590895/000119312524026847/d739529dex101.htm | 0001193125-24-026847 | `62fbb236862a09f068f8bdcab86459fa7eed0fc0f2501297b85f41029c4e431c` | `a4661727edc48361dd7290772e62412c389b8ad8d215a96aa58facfe9e356c2c` |
| `CZR_2026_Merger_Agreement_8K.txt` (Form 8-K, Item 1.01, 27 May 2026) | https://www.sec.gov/Archives/edgar/data/1590895/000119312526242995/d143382d8k.htm | 0001193125-26-242995 | `b583f857bec68d0c027b571b14c1280530e602c124e052f4a8ca3fc1e2b6a808` | `aabda22b745ac6c2e5d8462be19fbc47b6cafbe58d21f8c2750a1c195cf24f96` |

The credit agreement (936,079 bytes) and the indenture (759,535 bytes) are over
500 KiB, so their paths are pinned in the large-file excludes; both are under
1.5 MiB, so they reach CP-0 whole rather than as a page map. All six are
inside `MAX_REQUEST_BYTES`.

## Keys

Keys authored from the documents; material figures pending owner confirmation.

- CP-L10: the 10-Q's `$1.9 billion` of available CEI revolver capacity at
  30 June 2026 (after `$96` million of letters of credit and `$56` million
  committed for regulatory purposes); and its annual maturities of long-term
  debt, `$55` / `$114` / `$767` / `$1,574` / `$3,962` / `$5,335` million for
  the rest of 2026, 2027–2030 and thereafter, totalling `$11,807` million.
- CP-3C: the 10-Q's statement that the CEI Credit Agreement, as amended,
  provides for a `$2.25 billion` revolver maturing on 31 January 2028; the
  Fifth Amendment's restated Term B and Term B-1 Applicable Margin (`2.25%`
  Term Benchmark, `1.25%` ABR), which the 10-Q confirms is current; the
  indenture's Section 4.08(a) repurchase right at `101%` upon a Change of
  Control; and the 8-K's merger structure.
- CP-5: the 10-Q's Note 6 total debt, `11,807` face and `11,705` book at
  30 June 2026, `11,792` book at 31 December 2025.

The credit agreement and the Fourth Amendment carry no key here. The 2020
commitment, margins and financial covenant were changed by amendments not in
this set; the Fourth Amendment's Term B margin is superseded by the Fifth's.
Both are admitted for the facility's controlling terms.

Every key is one whole evidence line of its page, unique in its document: an
answer is accepted only as a whole line (`WHOLE_LINE`) and scored by exact
equality, so a fragment could never be met (F235, F475). Where a fact sits
inside a longer line, the key is that whole line.

The readiness key expects CP-0 to clear CP-L10, CP-3C and CP-5, with CP-L10
and CP-3C at `SCREENING_ONLY` decision scope, and CP-3C and CP-5 to remain
`Restricted`: this pack holds no market or LME evidence, and screening scope
cannot be promoted to FULL. The one register key expects CP-L10's `TL10.2`
`LIQUIDITY_MATURITIES` row to read `SUFFICIENT`: the 10-Q carries both the
revolver availability and the full maturity ladder above, so the evidence
status is unambiguous. No arithmetic is keyed.

## Change-of-control relevance of the pending merger (stated facts only)

The documents state the following; this set draws no conclusion from them.

- The 8-K (Item 1.01) says Merger Sub "will merge with and into the Company,
  with the Company continuing as the surviving corporation and direct wholly
  owned subsidiary of Parent (the “Merger”)", Parent being Fertitta Gaming
  Holdco, LLC.
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
  Control;" among its events of default, its Change in Control definition
  (as executed; Amendments 1–3, which the 10-K's exhibit index lists, are not
  in this set) covering any person or group, other than Permitted Holders, acquiring "more
  than 50% of the Equity Interests of the Borrower entitled to vote".
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

# CZR Q2 2026 LITE covenant-refinancing qualification set — prepared offline

Status: **LIVE-RUN 2026-10-05 / NOT QUALIFIED (citation and register keys)**. Prepared offline; the live results are in the last section.

Corpus changed 2026-10-06, D115; earlier runs were on the old corpus. See "Corpus changed 2026-10-06 (D115)" below.

This immutable set prepares `LITE_CREDIT_22 / LITE_COVENANT_REFINANCING` for
Caesars Entertainment, Inc. (CZR) at an analysis date of 2026-10-02. Its
qualification-set digest is
`5ee867579762d61ce42a5665fc7e0d7adb35e42e1fea503a44f932c725c902f1`.

## Corpus changed 2026-10-06 (D115)

On the owner's approval of 6 October 2026 (D115) exactly three files were downloaded from sec.gov (User-Agent declared on every request; the SEC's 111-byte script tag removed, so each size equals the filing index's) and admitted. They were converted with the F498 converter (sentence per line, F492; clause split for the Merger Agreement, F498). **Every live run, verdict and snapshot recorded below was made on the old corpus and is not comparable with a run of this set as it now stands**; the set digest above is the new one.

| document | source | accession | text SHA-256 | raw HTML SHA-256 |
|---|---|---|---|---|
| `CZR_2026_Merger_Agreement.txt` (Ex. 2.1 to the 8-K of 28 May 2026, Agreement and Plan of Merger, 27 May 2026) | https://www.sec.gov/Archives/edgar/data/1590895/000119312526242995/d143382dex21.htm | 0001193125-26-242995 | `e01077c1ed37c5b08c4d2dbfc15da19b78d50b4b38a42e3da22c3cf0e4c3038c` | `fcc680b30487f2abd9d753125e09a0844b05285ddb718f1c43428b2ab60fff1b` |

Text bytes: `CZR_2026_Merger_Agreement.txt` 411,229. None is over 500 KiB as text, so no large-file pin moves; none is near the 1.5 MiB page-map threshold. The set's CP-0 request, encoded with CP-0's delivered authority, is 2,833,485 bytes (67.6% of `MAX_REQUEST_BYTES`); no source is shown as a page map.

The Merger Agreement is the full agreement beside the 8-K's summary where the set carries it. Schedules are omitted under Item 601(b)(2) and the debt commitment letters are not in this exhibit, so a claim about commitment-letter terms stays unsupported. No key is added: every existing key binds its own document and is unchanged.

## Corpus provenance

Each document is an official SEC EDGAR filing or exhibit, fetched on 2 October
2026 and converted from HTML to plain text the same day. The 10-Q is
byte-identical to the `czr-2026q2` set's copy and the other four to the
`czr-2026q2-covenant-refinancing` set's copies. The text SHA-256 is the digest
the keys bind; the raw SHA-256 is the HTML as fetched.

| document | source | accession | text SHA-256 | raw HTML SHA-256 |
|---|---|---|---|---|
| `CZR_Q2_2026_10Q.txt` (Form 10-Q, quarter ended 30 June 2026) | https://www.sec.gov/Archives/edgar/data/1590895/000159089526000028/czr-20260630.htm | 0001590895-26-000028 | `f369ce5f1ebeddd9a0d4ce02ce3958112267d8701d1a348dfd6dc82d2034793a` | `9dd3fca867c49936c65c9729bd7f9478d4c98b7c60569b74864a839bdeed8500` |
| `CZR_2024_Credit_Agreement_Incremental_Assumption_No3.txt` (Ex. 10.2, Incremental Assumption Agreement No. 3, 6 February 2024, with Exhibit A, the Credit Agreement conformed through it; Ex. 10.36 in the FY2025 10-K) | https://www.sec.gov/Archives/edgar/data/1590895/000119312524026847/d739529dex102.htm | 0001193125-24-026847 | `25bea1d14fd9bb22838775f6fe056cd00741dc3d50eb1b79cc53498db502941c` | `aa48bc94b634de6386579791df7de831314785f007398546dd5c5fba415f2cfa` |
| `CZR_2024_Credit_Agreement_Fourth_Amendment.txt` (Ex. 10.1, Fourth Amendment, 9 May 2024) | https://www.sec.gov/Archives/edgar/data/1590895/000119312524135268/d827488dex101.htm | 0001193125-24-135268 | `32f91de6ef3ff93d9924eb8d4e3dc4734d28b68ed1da0f816a085ffdcb085c95` | `b0e9fc14d481410dd2fa3cb6bc28e4f9c3b8751d720777ab2bbf943143f6d0fb` |
| `CZR_2024_Credit_Agreement_Fifth_Amendment.txt` (Ex. 10.1, Fifth Amendment, 25 November 2024) | https://www.sec.gov/Archives/edgar/data/1590895/000119312524265157/d858083dex101.htm | 0001193125-24-265157 | `7f2b5c777dc3347938a007eaea63a623b299a1188dbcfbe8980d389a0bcfc5b3` | `0936486e71264a9b752d5977c003bfc9a89ec5eb4ca8e5b09107a7870ebf86e8` |
| `CZR_2024_650_Senior_Secured_Notes_2032_Indenture.txt` (Ex. 10.1, 6.500% Senior Secured Notes due 2032 indenture, 6 February 2024) | https://www.sec.gov/Archives/edgar/data/1590895/000119312524026847/d739529dex101.htm | 0001193125-24-026847 | `0809ab3981090bd2c23950da9530adb10e96882ddfa7db4404635e014d4c1119` | `a4661727edc48361dd7290772e62412c389b8ad8d215a96aa58facfe9e356c2c` |
| `CZR_2024_650_Notes_First_Supplemental_Indenture.txt` (Ex. 4.2, First Supplemental Indenture to the 6.500% 2032 notes indenture, 1 March 2024; Ex. 4.11 in the FY2025 10-K) | https://www.sec.gov/Archives/edgar/data/1590895/000159089524000088/exhibit42firstsupplemental.htm | 0001590895-24-000088 | `0af4615b9a52e91e2675adacbbc90ecc7b21a61dc8205b4b2459cf4b9db0a219` | `18d810c415aef677f867ac73dee07a04382e71db794f3bfbc91cdd185e4b0dc4` |
| `CZR_2024_650_Notes_Second_Supplemental_Indenture.txt` (Ex. 4.17, Second Supplemental Indenture to the 6.500% 2032 notes indenture, 23 August 2024; Ex. 4.12 in the FY2025 10-K) | https://www.sec.gov/Archives/edgar/data/1590895/000159089525000068/exhibit417-6500seniorsecur.htm | 0001590895-25-000068 | `3621f08611f4c6a6faed734993a3f2d9c97041693053ffa97624cbe5b7299aea` | `0eedd7d398ee15f45dabc99df2003249d4dbe232be456767e7b972d355326b3c` |
| `CZR_2026_Merger_Agreement_8K.txt` (Form 8-K, Item 1.01, 27 May 2026) | https://www.sec.gov/Archives/edgar/data/1590895/000119312526242995/d143382d8k.htm | 0001193125-26-242995 | `6808734cfbb19b56c5624e5a69e7209ccaad8a5039de94ad64563efdedf93169` | `aabda22b745ac6c2e5d8462be19fbc47b6cafbe58d21f8c2750a1c195cf24f96` |

The indenture (758,385 bytes) and Incremental Assumption Agreement No. 3
(1,077,810 bytes) are over 500 KiB, so their paths are pinned in the large-file
excludes; both are under 1.5 MiB, so they reach CP-0 whole rather than as a
page map. All eight are inside `MAX_REQUEST_BYTES`. The exhibits F508 adds were
fetched from SEC EDGAR on 5 October 2026 and converted the same day, split by
sentence (F492) and by clause (F498); they are byte-identical to the
`czr-2026q2-covenant-refinancing` set's copies. Since F508 the conformed copy
in Agreement No. 3's Exhibit A replaces the 2020 credit agreement (Ex. 10.1,
accession 0001193125-20-196232, 935,517 bytes); the supplemental indentures are
11,774 and 15,684 bytes. The set's CP-0 request, encoded with CP-0's delivered
authority, is 2,400,057 bytes (57.2% of `MAX_REQUEST_BYTES`, up from
2,217,640), and no source is shown as a page map.

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

No key is added or changed. On the owner's ruling of 5 October 2026 ("Replace
the 2020 base"), the conformed copy replaces the 2020 credit agreement (Ex.
10.1, accession 0001193125-20-196232), which this set no longer carries: the
agreement as amended is the one in force, and the superseded 2020 text cost
about 0.9 MB of every request. The Fourth and Fifth Amendments post-date
Agreement No. 3 and stay. No key here bound it.

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

The conformed credit agreement (Agreement No. 3's Exhibit A, F508) and the
Fourth Amendment carry no key here: the Fourth and Fifth Amendments post-date
the conformed copy and amend its pricing, and the Fourth Amendment's Term B
margin is superseded by the Fifth's. Both are admitted for the facility's
controlling terms.

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
  Control;" among its events of default, the line as executed in 2020; the
  Change in Control definition it relies on, amended since (conformed in
  Agreement No. 3's Exhibit A), covers any person or group, other than
  Permitted Holders, acquiring "more than 50% of the Equity Interests of the
  Borrower entitled to vote", and a proviso added since 2020 deems a person or
  group not to beneficially own Equity Interests subject to a merger agreement
  "until the consummation of the acquisition of the Equity Interests in
  connection with the transactions contemplated by such agreement."
- The 10-Q's risk factors say: "The Company may incur additional costs or
  suffer loss of business under third-party contracts that are terminated or
  that contain change in control or other provisions that may be triggered by
  the completion of the Merger,".

Whether the Merger, if completed, is a Change of Control under the indenture
or a Change in Control under the credit agreement is not determined here, and
no key asserts either. The 10-Q discloses the merger as pending; no fact about
it after the 10-Q's filing is in this set.

At preparation no provider call, run, snapshot, evidence record, reviewer
verdict, or qualification claim existed; the live runs follow.

## Live results (3–5 October 2026)

| run (file) | build / tip | status | modules accepted | attempts | citations | keys met | ready / projection / register | stop cause | key usage Δ / recorded charge |
|---|---|---|---|---|---|---|---|---|---|
| LCR1 (`LCR1-czr-lite-covenant-refinancing.json`) | 9043ba7f / 3c36acc era | BLOCKED | 1/4 | 1 | 16 (16 anch., 1 unver.) | 0/7 | missed / missed / missed | CP-0 marked CP-L10 CONDITIONAL / DO NOT RUN: the legal chain was incomplete (the 2020 credit agreement with only its 4th and 5th amendments, no conformed copy, no compliance certificate); CP-L10 precedes CP-3C, so the run ended BLOCKED after CP-0; the gap F508 closed | n/l / $0.12 |
| LCR2 (`LCR2-czr-lite-covenant-refinancing.json`) | 9043ba7f / 79c550d era | STOPPED | 1/4 | 3 | 18 (18 anch., 0 unver.) | not scored | — | PROVIDER_UNAVAILABLE on CP-L10 after ~195 s, no charge | n/l / $0.26 |
| LCR3 (`LCR3-czr-lite-covenant-refinancing.json`) | 9043ba7f / 79c550d era | STOPPED | 2/4 | 3 | 46 (44 anch., 1 unver.) | not scored | — | PROVIDER_UNAVAILABLE on CP-3C after ~299 s, no charge | +0.30 / $0.26 |
| LCR4 (`LCR4-czr-lite-covenant-refinancing.json`) | 9043ba7f / ~79c550d | STOPPED | 2/4 | 7 | 54 (54 anch., 0 unver.) | not scored | — | CP-3C refused 4x HANDOFF_INCOMPLETE (a register row one cell short; F509) | +1.01 / $0.93 |
| LCR5 (`LCR5-czr-lite-covenant-refinancing.json`) | 9043ba7f / 14b9bec | COMPLETE | 4/4 | 6 | 98 (98 anch., 8 unver.) | 2/7 | met / met / missed | — | +0.67 / $0.73 |
| LCR6 (`LCR6-stream.json`) | branch rca-prov (F511, F512) | STOPPED | 2/4 | 7 | n/r | 2/7 (both CP-L10 met; 4 CP-3C and 1 CP-5 not run) | — | CP-3C HANDOFF_MALFORMED after 3x HANDOFF_INCOMPLETE (T3D.2 row 7 at 11 of 12 cells; F522); no provider drop over 7 streamed calls (longest 327 s, 544k prompt tokens) | n/l / $0.9270 (billed $1.0795) |
| LCR7 (`LCR7-rca.json`) | branch rca (all fixes) | BLOCKED | 1/4 | 2 | n/r | 0/7 (all not run) | — | CP-0 said the conformed credit agreement (`c27bddbf`) showed pages 1-59 ending at Section 8.16 and marked CP-L10 DO NOT RUN; the prompt held all 67 pages (N156) | n/l / $0.3057 (billed $0.2957) |

Reading the table: "build" is the first eight hex digits of the methodology build id in the run JSON; "tip" is the git tip the ledger names (`—` where the ledger names none; tips marked ~ are the base of the next fix task, so the run ran on that tree or its predecessor). "Attempts" is the run JSON's attempt list (every provider call recorded, including a dropped one). "Citations" is the run proof's total with its anchored and unverified counts (`n/r`: the run stopped before a proof was recorded). "Keys met" is the scored matrix row; a run that stopped before COMPLETE or BLOCKED is not scored (`not scored`). "Key usage Δ" is the OpenRouter key-usage change the ledger recorded for the run (`n/l`: not in the ledger); "recorded charge" is the sum of the run's attempt charges at the pinned price. The two disagree and the usage counter lags (ledger), so the key usage is the budget measure. Run files are git-ignored, under `docs/rebuild/runs/live-2026-10-03/`; the model is `openai/gpt-6-luna`, effort high, provider pinned to `openai`, in every row except LCR7, which ran at a $0.25/$1.00 pin. LCR6 and LCR7 are the 5 October runs; "billed" is the sum of OpenRouter `GET /api/v1/generation` `total_cost` for the run. A first LCR7 attempt died STORE_UNAVAILABLE at start with $0 spent (a compose command re-created the dev Postgres container; see `PROVIDER_RUNBOOK.md`).

Verdict: The set is **NOT QUALIFIED**. LCR5 completed and was proven with the ready and projection keys met, but met 2 of 7 citation keys and missed the register key (cause not analysed). Since then: LCR6, the first run with streaming (F511, F512), stopped at CP-3C on a T3D.2 row one cell short that three retries did not repair (the hint was correct but not actionable; F522 now names the row and shows the shifted columns; no live retry has yet shown it repairs the row). LCR7, on all the fixes, was BLOCKED after CP-0: the model's claim that the conformed credit agreement ended at Section 8.16 was a slip, since the prompt held all 67 pages and three direct probes found Sections 9.23 to 9.27 on page 66 (N156). No run since LCR5 reached COMPLETE.

Owner-decision stops and provider limits: Provider drops: PROVIDER_UNAVAILABLE after about 195 to 299 s on large non-streamed calls (LCR2, LCR3), never billed. The cause is undecided (`PROVIDER_RUNBOOK.md`, "Root-cause pass, 5 October 2026"). Streaming (F511, F512) completed 7 calls in LCR6 with no drop; whether it replaces the owner's 5 October ruling to run without streaming is an open owner decision (N145).

# CZR Q2 2026 FULL portfolio-decision qualification set — prepared offline

Status: **NOT RUN LIVE (synthetic mandate, since replaced by the real fund's documents, D115) / NOT QUALIFIED**. Prepared offline; the live results are in the last section.

Corpus changed 2026-10-06, D115; earlier runs were on the old corpus. See "Corpus changed 2026-10-06 (D115)" below.

Corpus changed 2026-10-16, R27 (D152, N147); earlier runs were on the old corpus. See "Corpus changed 2026-10-16 (R27, N147)" below.

This immutable set prepares `FULL_CREDIT_32 / PORTFOLIO_DECISION` for
Caesars Entertainment, Inc. (CZR) at an analysis date of 2026-10-02, with a
proposed position in the CZR 6.50% Senior Secured Notes due 2032 held against a real
fund's holdings and policies (D115; the synthetic test mandate of D80 is unused). Its qualification-set digest is
`d5af56fb5fd0fd89be17635993f219b7eb795a2ee94f497d56fba3ec5144316c`.

## Corpus changed 2026-10-16 (R27, N147)

On the owner's ruling R27 of 16 October 2026 (D152; N147) 9 documents already admitted to other CZR sets are added to this set. Nothing was downloaded for them: each is a byte-identical copy of the file in `czr-2026q2-covenant-refinancing`, `czr-2026q2-liquidity`, `czr-2026q2-lite-relative-value`, `czr-2026q2-relative-value`, copied because the on-disk loader refuses a path outside the set root. CP-0 of the latest run declared that documents in hand would close its gaps: the credit agreement's Fourth and Fifth Amendments (the F508 class, for CP-4), the Q2 2026 earnings release, the merger 8-K and press release, and the MGM and PENN releases and TRACE observations RELATIVE_VALUE carries (for CP-3).

| document | source | accession | text SHA-256 | raw HTML SHA-256 |
|---|---|---|---|---|
| `CZR_2024_Credit_Agreement_Fourth_Amendment.txt` (Ex. 10.1, Fourth Amendment, 9 May 2024) | https://www.sec.gov/Archives/edgar/data/1590895/000119312524135268/d827488dex101.htm | 0001193125-24-135268 | `32f91de6ef3ff93d9924eb8d4e3dc4734d28b68ed1da0f816a085ffdcb085c95` | `b0e9fc14d481410dd2fa3cb6bc28e4f9c3b8751d720777ab2bbf943143f6d0fb` |
| `CZR_2024_Credit_Agreement_Fifth_Amendment.txt` (Ex. 10.1, Fifth Amendment, 25 November 2024) | https://www.sec.gov/Archives/edgar/data/1590895/000119312524265157/d858083dex101.htm | 0001193125-24-265157 | `7f2b5c777dc3347938a007eaea63a623b299a1188dbcfbe8980d389a0bcfc5b3` | `0936486e71264a9b752d5977c003bfc9a89ec5eb4ca8e5b09107a7870ebf86e8` |
| `CZR_Q2_2026_Earnings_Release.txt` (Ex. 99.1, 28 July 2026) | https://www.sec.gov/Archives/edgar/data/1590895/000159089526000027/ex991-2026q2ceiearningsrel.htm | 0001590895-26-000027 | `b385f76ff631243d1053fa8073ebde4f8886b4a50c9ce34ce3498d6b2ac3e9f8` | `a8982154b99b023b526261f7626022e96ac642834d1d65704629946acecc8a1f` |
| `CZR_2026_Merger_Agreement_8K.txt` (Form 8-K, Item 1.01, 27 May 2026) | https://www.sec.gov/Archives/edgar/data/1590895/000119312526242995/d143382d8k.htm | 0001193125-26-242995 | `6808734cfbb19b56c5624e5a69e7209ccaad8a5039de94ad64563efdedf93169` | `aabda22b745ac6c2e5d8462be19fbc47b6cafbe58d21f8c2750a1c195cf24f96` |
| `CZR_2026_Merger_Press_Release.txt` (Ex. 99.1, press release, 28 May 2026) | https://www.sec.gov/Archives/edgar/data/1590895/000119312526242995/d143382dex991.htm | 0001193125-26-242995 | `4fbecbd5f5a10b15911b5749daee41b3e40090e43ed54bf33aee07a21877e68b` | `2a4ed12c96147f2171451c93524bea31ecad37247448d27039f755a3cf85f51f` |
| `MGM_Q2_2026_Earnings_Release.txt` (MGM Ex. 99.1, 29 July 2026) | https://www.sec.gov/Archives/edgar/data/789570/000078957026000075/mgmex991q22026earningrelea.htm | 0000789570-26-000075 | `795ac68aa1c51a7e0a6799a6e1ca053ee597dc9a1a9a6550a2438280a6e76cdb` | `d23f2410e475eca7e0dfe2fdcca0210f449e4c1a93fb93a14549592c4554173c` |
| `PENN_Q2_2026_Earnings_Release.txt` (PENN Ex. 99.1, 6 August 2026) | https://www.sec.gov/Archives/edgar/data/921738/000092173826000019/pennex991-q22026.htm | 0000921738-26-000019 | `4d12fff94b066f73e6eccce84eec937e8fd4fdc38d6061704db66a40511a210c` | `be60f25fec25022c2fd6f48c2cf9bb99912b8f78356cebc4a7719bdcae9120bc` |

The two FINRA TRACE observations are coordinator-authored transcriptions of the official public FINRA pages, byte-identical to the `czr-2026q2-relative-value` set's copies.

| document | source | as of | SHA-256 | raw SHA-256 |
|---|---|---|---|---|
| `MGM_FINRA_TRACE_552953CK5_2026-10-02.txt` (MGM 6.125% due 2029) | https://www.finra.org/finra-data/fixed-income/bond?symbol=MGM5885613&bondType=CORP | observed 2026-10-02T09:32:08Z | `e17cea1bb90debdeb8c1fea9c352132b57ae9b27ee0d3225fb67c6466d7d0e4a` | — |
| `PENN_FINRA_TRACE_707569AV1_2026-10-02.txt` (PENN 4.125% due 2029) | https://www.finra.org/finra-data/fixed-income/bond?symbol=PENN5210723&bondType=CORP | observed 2026-10-02T09:32:31Z | `666c0f36ace32336dffbcff324eaec5b4657edade407bb0b8a0e8d8fb405de6d` | — |

None is over 500 KiB as text, so no large-file pin moves; none is near the 1.5 MiB page-map threshold. The set's CP-0 request, encoded with CP-0's delivered authority (measured with the host's own builders, `check_context` on the pinned route), is 3,600,476 bytes (85.8% of `MAX_REQUEST_BYTES`), up from 3,377,783 (80.5%); no source is shown as a page map on a model with no declared context. For `openai/gpt-6-luna` (request ceiling 2,953,392 bytes under D116) the fitted request is 2,863,087 bytes with 2 sources shown as declared page maps (before: 2,868,944 bytes, 2 page maps). Set digest `1ec818789e1b5a50a9ae40038f6084f40af576917cdfa33955586292de4074fe` -> `d5af56fb5fd0fd89be17635993f219b7eb795a2ee94f497d56fba3ec5144316c`.

Keys re-checked (all 16 keys and their one alternative, each scanned against every added document for a whole-line twin and for its figures): one key gains a D101 alternative and none is re-sourced. CP-1's `Cash and cash equivalents | $965 | $887` (the 10-Q) is also a whole line of the added release, the same two dates, so the release line is its alternative, as in `czr-2026q2-full-credit-assessment`. No other key line or alternative has a twin or the same figures in the added documents. The Fourth and Fifth Amendments post-date Incremental Assumption Agreement No. 3 and restate only the Term B and Term B-1 margins and the repricing premium, which no key reads, so CP-4's `(g) there shall have occurred a Change in Control;` and its other keys keep their source; the merger 8-K and press release restate the transaction, not a line any key reads; CP-3D and CP-3 keep the two CZR notes' TRACE lines, the position under review being the CZR 6.50% 2032 notes, so the MGM and PENN releases and observations are peers' evidence for CP-3 that no key reads. No key is added: a key for a peer line would be new scope, and no run has measured the set over these documents.

## Corpus changed 2026-10-06 (D115)

On the owner's approval of 6 October 2026 (D115) exactly three files were downloaded from sec.gov (User-Agent declared on every request; the SEC's 111-byte script tag removed, so each size equals the filing index's) and admitted. They were converted with the F498 converter (sentence per line, F492; clause split for the Merger Agreement, F498). **Every live run, verdict and snapshot recorded below was made on the old corpus and is not comparable with a run of this set as it now stands**; the set digest above is the new one.

| document | source | accession | text SHA-256 | raw HTML SHA-256 |
|---|---|---|---|---|
| `FHSUHY_NPORT_Schedule_of_Investments_2026-06-30.txt` (NPORT-EX, schedule of investments of the Federated Hermes Sustainable High Yield Bond Fund, Inc. at 30 June 2026 (filed 25 August 2026)) | https://www.sec.gov/Archives/edgar/data/225318/000022531826000020/poi_fhsushybondfund.htm | 0000225318-26-000020 | `e2490912d9cc688135e15732e0fcf4aafd715e91e4d580edd577483535507bab` | `45dbee32a946cf9b582e22e97461735def3b5b8447f77d193ca0b08d92437df5` |
| `FHSUHY_Prospectus_and_SAI_2026-05-26.txt` (485BPOS, the same fund's prospectus and SAI (filed 26 May 2026)) | https://www.sec.gov/Archives/edgar/data/225318/000162363226000742/fhsuhy2481-form.htm | 0001623632-26-000742 | `10455d54958421c56b4902f2fa41bfc08873bb9d16ee9fb22ab31ded215846ea` | `ace0ea46f895f93d9fa863dc43a7d5f402e689cf0b6fdb3c8c71f6893821f9cc` |

Text bytes: `FHSUHY_NPORT_Schedule_of_Investments_2026-06-30.txt` 49,398; `FHSUHY_Prospectus_and_SAI_2026-05-26.txt` 501,405. None is over 500 KiB as text, so no large-file pin moves; none is near the 1.5 MiB page-map threshold. The set's CP-0 request, encoded with CP-0's delivered authority, is 3,357,221 bytes (80.0% of `MAX_REQUEST_BYTES`); no source is shown as a page map.

The Federated Hermes Sustainable High Yield Bond Fund's N-PORT schedule and its prospectus and SAI replace the SYNTHETIC Test CLO I mandate (D80) in this set. The synthetic file stays on disk and in the register, unused. The schedule lists four Caesars positions (6.500% 2/15/2032 secured notes, `550,000` principal, `536,927` value; 6.000% 10/15/2032 notes, `1,650,000`, `1,496,434`; 7.000% 2/15/2030; 4.625% 10/15/2029); the prospectus carries the fund's 80% policy, investment limitations and concentration restriction. What the real documents do not carry: a proposed position, a CLO's compliance monitor, or a single-name limit. The three keys that bound the synthetic mandate (position, weight on NAV, C-01) are re-keyed to one whole unique line each of the new documents (below); the set's other expectations (readiness, projections, register) do not depend on the mandate's text and are unchanged, but no run has measured them over the new corpus.

## The synthetic mandate (D80), unused since D115 (historical)

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
`czr-2026q2` set's copies,  and the indenture to the
`czr-2026q2-covenant-refinancing` set's copy. No document is admitted here for
the first time. The text SHA-256 is the digest the keys bind; the raw SHA-256
is the HTML as fetched.

| document | source | accession | text SHA-256 | raw HTML SHA-256 |
|---|---|---|---|---|
| `CZR_Q2_2026_10Q.txt` (Form 10-Q, quarter ended 30 June 2026) | https://www.sec.gov/Archives/edgar/data/1590895/000159089526000028/czr-20260630.htm | 0001590895-26-000028 | `f369ce5f1ebeddd9a0d4ce02ce3958112267d8701d1a348dfd6dc82d2034793a` | `9dd3fca867c49936c65c9729bd7f9478d4c98b7c60569b74864a839bdeed8500` |
| `CZR_FY2025_10K.txt` (Form 10-K, fiscal year ended 31 December 2025) | https://www.sec.gov/Archives/edgar/data/1590895/000159089526000011/czr-20251231.htm | 0001590895-26-000011 | `172309048af2a6a2dab515d765f00a7c89bf8c874c6104a5e3a052b66cad4512` | `41328bdfa2486cfb53b831c2ddba6009528d8dca3a0d868c98c2cb113142b05f` |
| `CZR_2024_Credit_Agreement_Incremental_Assumption_No3.txt` (Ex. 10.2, Incremental Assumption Agreement No. 3, 6 February 2024, with Exhibit A, the Credit Agreement conformed through it; Ex. 10.36 in the FY2025 10-K) | https://www.sec.gov/Archives/edgar/data/1590895/000119312524026847/d739529dex102.htm | 0001193125-24-026847 | `25bea1d14fd9bb22838775f6fe056cd00741dc3d50eb1b79cc53498db502941c` | `aa48bc94b634de6386579791df7de831314785f007398546dd5c5fba415f2cfa` |
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

The indenture (758,385 bytes) and Incremental Assumption Agreement No. 3
(1,077,810 bytes) are over 500 KiB, so their paths are pinned in the large-file
excludes; both are under 1.5 MiB, so they reach CP-0 whole rather than as a
page map. All nine are inside `MAX_REQUEST_BYTES`. The mandate's compliance
monitor cites "Indenture §7.11": that is the CLO's own indenture, not the
Caesars notes indenture, and a SYNTHETIC line in the adaptation says so. The
exhibits F508 adds were fetched from SEC EDGAR on 5 October 2026 and converted
the same day, split by sentence (F492) and by clause (F498); they are
byte-identical to the `czr-2026q2-covenant-refinancing` set's copies. Since
F508 the conformed copy in Agreement No. 3's Exhibit A replaces the 2020 credit
agreement (Ex. 10.1, accession 0001193125-20-196232, 935,517 bytes); the
supplemental indentures are 11,774 and 15,684 bytes. The set's CP-0 request,
encoded with CP-0's delivered authority, is 2,763,509 bytes (65.9% of
`MAX_REQUEST_BYTES`, up from 2,581,092), and no source is shown as a page map.

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
the Fourth and Fifth Amendments (carried here since 16 October 2026, R27), it is the
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

Keys authored from the documents; material figures stand as authored by the owner's ruling of 2026-10-17 (N126, F702).

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
- CP-6, position: the fund's schedule line for the CZR 6.50% 2032 notes (`550,000` principal, `536,927` value at 30 June 2026), its net-assets line (`NET ASSETS—100% | $491,554,960`, the weight denominator) and the prospectus's 80% policy line (`at least 80% of its net assets … in sustainable lower-rated fixed-income investments`), which replace the synthetic mandate's three keys (D115). The schedule and the prospectus are the real fund's, not a CLO mandate: there is no proposed position size and no single-name limit to key, and no key claims one. The prospectus line is fragile: the summary prospectus words the policy `sustainable, lower-rated` (twice, not unique), so an answer citing that wording misses the key, and that wording cannot be a D101 alternative.

The conformed credit agreement's commitment, margins and covenant (Agreement
No. 3's Exhibit A, F508) are not keyed: the Fourth and Fifth Amendments, which
this set carries since 16 October 2026 (R27), post-date it; the current revolver (`$2.25 billion`,
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
    row, the same two dates (added 16 October 2026, R27, with the release).
- CP-2, the 10-Q's `Net cash provided by operating activities | 675 | 680`:
  - the 10-Q's `During the six months ended June 30, 2026, our operating
    activities generated operating cash inflows of $675 million, as compared to
    operating cash inflows of $680 million during the six months ended June 30,
    2025, primarily due to changes in working capital, coupled with the results
    of operations described above.`, its liquidity sentence, the six months
    against the prior six months.

The other figure keys (`Net cash provided by
operating activities` of the 10-K, `Total debt`, `C-01`) have none: no other whole line
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

- **Synthetic, not a holding (historical; superseded by D115, which replaced the mandate: the fund now holds four Caesars positions).** The mandate says "Existing Caesars
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

## Live results (3–5 October 2026)

Verdict: The set was **never run live**. It carries the same self-declared synthetic mandate (D80) that blocks its LITE twin, `czr-2026q2-lite-portfolio`, at CP-0 (LP1), and the owner ruled on 5 October 2026 to leave the portfolio sets and record the stop, so a FULL portfolio run was not spent. No run file exists for it.

Owner-decision stops and provider limits: **Owner decision, 5 October 2026:** "Leave them, record the stop".

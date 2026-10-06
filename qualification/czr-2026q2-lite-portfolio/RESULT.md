# CZR Q2 2026 LITE portfolio-screen qualification set — prepared offline

Status: **BLOCKED AT CP-0 (synthetic mandate, since replaced by the real fund's documents, D115)**. Prepared offline; the live results are in the last section.

Corpus changed 2026-10-06, D115; earlier runs were on the old corpus. See "Corpus changed 2026-10-06 (D115)" below.

This immutable set prepares `LITE_CREDIT_22 / LITE_PORTFOLIO_DECISION` for
Caesars Entertainment, Inc. (CZR) at an analysis date of 2026-10-02, with a
proposed position in the CZR 6.50% Senior Secured Notes due 2032 held against a real
fund's holdings and policies (D115; the synthetic test mandate of D80 is unused). Its qualification-set digest is
`a1b09b156bead903eed0fa30ad2ae4341123f7dd9b407b02b41a9702de19fc12`.

## Corpus changed 2026-10-06 (D115)

On the owner's approval of 6 October 2026 (D115) exactly three files were downloaded from sec.gov (User-Agent declared on every request; the SEC's 111-byte script tag removed, so each size equals the filing index's) and admitted. They were converted with the F498 converter (sentence per line, F492; clause split for the Merger Agreement, F498). **Every live run, verdict and snapshot recorded below was made on the old corpus and is not comparable with a run of this set as it now stands**; the set digest above is the new one.

| document | source | accession | text SHA-256 | raw HTML SHA-256 |
|---|---|---|---|---|
| `FHSUHY_NPORT_Schedule_of_Investments_2026-06-30.txt` (NPORT-EX, schedule of investments of the Federated Hermes Sustainable High Yield Bond Fund, Inc. at 30 June 2026 (filed 25 August 2026)) | https://www.sec.gov/Archives/edgar/data/225318/000022531826000020/poi_fhsushybondfund.htm | 0000225318-26-000020 | `e2490912d9cc688135e15732e0fcf4aafd715e91e4d580edd577483535507bab` | `45dbee32a946cf9b582e22e97461735def3b5b8447f77d193ca0b08d92437df5` |
| `FHSUHY_Prospectus_and_SAI_2026-05-26.txt` (485BPOS, the same fund's prospectus and SAI (filed 26 May 2026)) | https://www.sec.gov/Archives/edgar/data/225318/000162363226000742/fhsuhy2481-form.htm | 0001623632-26-000742 | `10455d54958421c56b4902f2fa41bfc08873bb9d16ee9fb22ab31ded215846ea` | `ace0ea46f895f93d9fa863dc43a7d5f402e689cf0b6fdb3c8c71f6893821f9cc` |

Text bytes: `FHSUHY_NPORT_Schedule_of_Investments_2026-06-30.txt` 49,398; `FHSUHY_Prospectus_and_SAI_2026-05-26.txt` 501,405. None is over 500 KiB as text, so no large-file pin moves; none is near the 1.5 MiB page-map threshold. The set's CP-0 request, encoded with CP-0's delivered authority, is 1,794,693 bytes (42.8% of `MAX_REQUEST_BYTES`); no source is shown as a page map.

The Federated Hermes Sustainable High Yield Bond Fund's N-PORT schedule and its prospectus and SAI replace the SYNTHETIC Test CLO I mandate (D80) in this set. The synthetic file stays on disk and in the register, unused. The schedule lists four Caesars positions (6.500% 2/15/2032 secured notes, `550,000` principal, `536,927` value; 6.000% 10/15/2032 notes, `1,650,000`, `1,496,434`; 7.000% 2/15/2030; 4.625% 10/15/2029); the prospectus carries the fund's 80% policy, investment limitations and concentration restriction. What the real documents do not carry: a proposed position, a CLO's compliance monitor, or a single-name limit. The three keys that bound the synthetic mandate (position, weight on NAV, C-01) are re-keyed to one whole unique line each of the new documents (below); the set's other expectations (readiness, projections, register) do not depend on the mandate's text and are unchanged, but no run has measured them over the new corpus.

## The synthetic mandate (D80), unused since D115 (historical)

The "Test CLO I Ltd" mandate, exposure report and compliance monitor are
synthetic. The owner adopted them on 2 October 2026 as test input (D80): the
workbook describes itself as packaged sample data only, no figure in it is a
real holding, and the CZR position is an owner-adopted adaptation. A run over
this set measures how the route handles a mandate; it may never ground a real
decision. The CCL portfolio set (`ccl-fy2025-portfolio`) measures CP-0's
refusal of CP-L10 over a 10-K alone; this set, like `vmo2-fy2025-portfolio`,
measures the ready path, now with a mandate in the pack.

## Corpus provenance

The 10-Q, the CZR earnings release and the indenture were fetched from SEC
EDGAR on 2 October 2026 and converted from HTML to plain text the same day.
The 10-Q and the release are byte-identical to the `czr-2026q2` set's copies,
and the indenture to the `czr-2026q2-covenant-refinancing` set's copy. The text SHA-256 is the
digest the keys bind; the raw SHA-256 is the HTML as fetched.

| document | source | accession | text SHA-256 | raw HTML SHA-256 |
|---|---|---|---|---|
| `CZR_Q2_2026_10Q.txt` (Form 10-Q, quarter ended 30 June 2026) | https://www.sec.gov/Archives/edgar/data/1590895/000159089526000028/czr-20260630.htm | 0001590895-26-000028 | `f369ce5f1ebeddd9a0d4ce02ce3958112267d8701d1a348dfd6dc82d2034793a` | `9dd3fca867c49936c65c9729bd7f9478d4c98b7c60569b74864a839bdeed8500` |
| `CZR_Q2_2026_Earnings_Release.txt` (Ex. 99.1, 28 July 2026) | https://www.sec.gov/Archives/edgar/data/1590895/000159089526000027/ex991-2026q2ceiearningsrel.htm | 0001590895-26-000027 | `b385f76ff631243d1053fa8073ebde4f8886b4a50c9ce34ce3498d6b2ac3e9f8` | `a8982154b99b023b526261f7626022e96ac642834d1d65704629946acecc8a1f` |
| `CZR_2024_650_Senior_Secured_Notes_2032_Indenture.txt` (Ex. 10.1, 6.500% Senior Secured Notes due 2032 indenture, 6 February 2024) | https://www.sec.gov/Archives/edgar/data/1590895/000119312524026847/d739529dex101.htm | 0001193125-24-026847 | `0809ab3981090bd2c23950da9530adb10e96882ddfa7db4404635e014d4c1119` | `a4661727edc48361dd7290772e62412c389b8ad8d215a96aa58facfe9e356c2c` |
| `CZR_2024_650_Notes_First_Supplemental_Indenture.txt` (Ex. 4.2, First Supplemental Indenture to the 6.500% 2032 notes indenture, 1 March 2024; Ex. 4.11 in the FY2025 10-K) | https://www.sec.gov/Archives/edgar/data/1590895/000159089524000088/exhibit42firstsupplemental.htm | 0001590895-24-000088 | `0af4615b9a52e91e2675adacbbc90ecc7b21a61dc8205b4b2459cf4b9db0a219` | `18d810c415aef677f867ac73dee07a04382e71db794f3bfbc91cdd185e4b0dc4` |
| `CZR_2024_650_Notes_Second_Supplemental_Indenture.txt` (Ex. 4.17, Second Supplemental Indenture to the 6.500% 2032 notes indenture, 23 August 2024; Ex. 4.12 in the FY2025 10-K) | https://www.sec.gov/Archives/edgar/data/1590895/000159089525000068/exhibit417-6500seniorsecur.htm | 0001590895-25-000068 | `3621f08611f4c6a6faed734993a3f2d9c97041693053ffa97624cbe5b7299aea` | `0eedd7d398ee15f45dabc99df2003249d4dbe232be456767e7b972d355326b3c` |

The mandate is a text extract of the owner's workbook
`REF_CP-6A_Portfolio_Debate_Inputs.xlsx`, converted on 2 October 2026, with
the owner-adopted adaptation appended under its own heading. It is admitted
here for the first time. The FINRA TRACE observation is a coordinator-authored
transcription of the official public FINRA page, admitted byte for byte and
byte-identical to the `czr-2026q2-relative-value` set's copy.

| document | source | as of | SHA-256 | raw SHA-256 |
|---|---|---|---|---|
| `TEST_CLO_I_Mandate_and_Exposures_2026-10-02.txt` (SYNTHETIC) | owner-adopted synthetic test mandate (workbook, not a URL) | exposure report 29 May 2026; adaptation 2 October 2026 | `864ee90ab21372bcf89c8b27e02cd5d691d9095a64d507c7f656d5963cfe3207` | `05a32699b39cedce58dd9475ea938c3dd592bd8a327426b1c2150f57579cfe22` (workbook) |
| `CZR_FINRA_TRACE_12769GAC4_2026-10-02.txt` (CZR 6.50% due 2032) | https://www.finra.org/finra-data/fixed-income/bond?symbol=ERI5740550&bondType=CORP | observed 2026-10-02T09:31:13Z | `4018aaa62309df6cd66a9b5fc766c4a9429e886e649023de2bad8673baf8aa51` | — |

The indenture (758,385 bytes) is over 500 KiB, so its path is pinned in the
large-file excludes; it is under 1.5 MiB, so it reaches CP-0 whole rather than
as a page map. All seven are inside `MAX_REQUEST_BYTES`. The exhibits F508 adds
were fetched from SEC EDGAR on 5 October 2026 and converted the same day, split
by sentence (F492) and by clause (F498); they are byte-identical to the
`czr-2026q2-covenant-refinancing` set's copies. Since F508 the set also carries
the supplemental indentures, 11,774 and 15,684 bytes. The set's CP-0 request,
encoded with CP-0's delivered authority, is 1,200,981 bytes (28.6% of
`MAX_REQUEST_BYTES`, up from 1,167,482), and no source is shown as a page map.

The indenture is the executed governing document of the proposed position,
admitted because CP-0's recorded refusal on `ccl-fy2025-portfolio` asked for
"applicable executed governing security documents". It carries no key. The
mandate's compliance monitor cites "Indenture §7.11": that is the CLO's own
indenture, not this one, and a SYNTHETIC line in the adaptation says so.

## Why the pack carries the current legal chain (F508)

Live runs C5 (`czr-2026q2-covenant-refinancing`) and LCR1
(`czr-2026q2-lite-covenant-refinancing`) held back the covenant modules at CP-0
(CP-4, then CP-L10): the sets carried the 2020 credit agreement with only its
Fourth and Fifth Amendments, and the 6.50% 2032 notes indenture without its
supplemental indentures, though the FY2025 10-K's exhibit index lists them. On
the owner's ruling of 5 October 2026 ("Latest chain only"), every CZR set now
carries the exhibits beside the instrument each modifies; this set, which holds
the indenture but not the credit agreement, carries the 2032 notes' First and
Second Supplemental Indentures.

The First Supplemental Indenture (1 March 2024) adds two guarantors and amends
clause (44) of the Permitted Liens definition and Section 8.01(b); the Second
(23 August 2024) adds the guarantors on its Schedule A.

No key is added or changed: a key binds the digest of the document it was
authored from.

## Keys

Keys authored from the documents; material figures pending owner confirmation.

- CP-L10, issuer: the 10-Q's `$1.9 billion` of available CEI revolver
  capacity at 30 June 2026; the release's Adjusted EBITDA (`$920` million for
  the quarter, `$1,807` million for the six months).
- CP-L10, position: the fund's schedule line for the CZR 6.50% 2032 notes (`550,000` principal, `536,927` value at 30 June 2026), its net-assets line (`NET ASSETS—100% | $491,554,960`, the weight denominator) and the prospectus's 80% policy line (`at least 80% of its net assets … in sustainable lower-rated fixed-income investments`), which replace the synthetic mandate's three keys (D115). The schedule and the prospectus are the real fund's, not a CLO mandate: there is no proposed position size and no single-name limit to key, and no key claims one. The prospectus line is fragile: the summary prospectus words the policy `sustainable, lower-rated` (twice, not unique), so an answer citing that wording misses the key, and that wording cannot be a D101 alternative. Also FINRA's last trade price, `$93.28`.

Alternative lines (D101). A figure key is also met by another whole evidence
line, cited under the same module, that states the key's lead figures -- the
current figure and the comparative the key line leads with -- for the same
measure, period and consolidated scope; a % change, a further period or a third
year on the key line need not be on it. Prose keys have none: a statement is
its sentence. Each alternative is one whole evidence line, unique in its
document (F475), and is listed with why it states the key's figures:

- CP-L10, the release's `Adjusted EBITDA | $920 | $955 | $1,807 | $1,839`:
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

The other figure keys (`C-01`) have none: no other whole line states their
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
fact.

The readiness key expects CP-0 to clear CP-L10, the route's one pinned
consumer. CP-L10 is expected at `SCREENING_ONLY` decision scope, the catalog
pathway's scope, and `Restricted`: the mandate is synthetic, its NAV and
compliance check are dated 29 May 2026 while the price is dated 1 October
2026, the price is a single last trade rather than a bid, mid or evaluated
price.

**Readiness risk: the eligible-security universe.** The same CCL refusal also
asked for an "eligible-security universe". The workbook has none; its only
related content is two lien buckets of the compliance monitor, quoted as they
stand:

    C-09 | Instrument | Min 1st Lien / Senior Secured | ≥ 90.0% NAV | Hard | Indenture §7.11 | 99.39% | 9.39% | Pass | 29-May-2026 | E. Guei |
    C-10 | Instrument | Max 2nd Lien / Unsecured | ≤ 10.0% NAV | Soft | Indenture §7.11 | 0.61% | 9.39% | Pass | 29-May-2026 | E. Guei |

No eligibility statement is invented to close the gap. CP-0 may therefore hold
CP-L10 `CONDITIONAL` rather than `READY`, and the readiness key, which only a
`READY` verdict meets, would then be missed.

The one register key expects CP-L10's `TL10.2` `LIQUIDITY_MATURITIES` row to
read `SUFFICIENT`: the 10-Q carries both the revolver availability and the
full maturity ladder, so the evidence status is unambiguous.

The arithmetic the mandate states, checked: `5,000,000 / 630,928,502 =
0.0079248…`, so `0.7925%` of NAV on par; headroom to C-01's `2.5%` is
`2.5 − 0.7925 = 1.7075` percentage points. At the last trade price,
`5,000,000 × 93.28 / 100 = 4,664,000.00`, and `4,664,000 / 630,928,502 =
0.7392%` of NAV. None of these figures is keyed as a register cell: the
module's own sizing register is not pinned here, and the NAV is not restated
pro forma for the position.

## Stated facts the screen must not misread

- **Synthetic, not a holding (historical; superseded by D115, which replaced the mandate: the fund now holds four Caesars positions).** The document says "Existing Caesars
  Entertainment exposure: none." and that the position is synthetic.
- **As-of mismatch.** The workbook's NAV and compliance check are dated
  29 May 2026; the price is dated 1 October 2026; the 10-Q reports the
  quarter ended 30 June 2026.
- **The pending take-private.** The 10-Q discloses the 27 May 2026 Agreement
  and Plan of Merger with Fertitta Gaming; the FINRA last trade postdates it.

At preparation no provider call, run, snapshot, evidence record, reviewer
verdict, or qualification claim existed; the live runs follow.

## Live results (3–5 October 2026)

| run (file) | build / tip | status | modules accepted | attempts | citations | keys met | ready / projection / register | stop cause | key usage Δ / recorded charge |
|---|---|---|---|---|---|---|---|---|---|
| LP1 (`LP1-czr-lite-portfolio.json`) | 9043ba7f / ~14b9bec | BLOCKED | 1/2 (CP-0; CP-L10 not run) | 1 | 24 (23 anch., 0 unver.) | 0/6 | missed / missed / missed | CP-0 blocked on the self-declared synthetic mandate | n/l / $0.08 |

Reading the table: "build" is the first eight hex digits of the methodology build id in the run JSON; "tip" is the git tip the ledger names (`—` where the ledger names none; tips marked ~ are the base of the next fix task, so the run ran on that tree or its predecessor). "Attempts" is the run JSON's attempt list (every provider call recorded, including a dropped one). "Citations" is the run proof's total with its anchored and unverified counts (`n/r`: the run stopped before a proof was recorded). "Keys met" is the scored matrix row; a run that stopped before COMPLETE or BLOCKED is not scored (`not scored`). "Key usage Δ" is the OpenRouter key-usage change the ledger recorded for the run (`n/l`: not in the ledger); "recorded charge" is the sum of the run's attempt charges at the pinned price. The two disagree and the usage counter lags (ledger), so the key usage is the budget measure. Run files are git-ignored, under `docs/rebuild/runs/live-2026-10-03/`; the model is `openai/gpt-6-luna`, effort high, provider pinned to `openai`, in every row.

Verdict: The set is **NOT QUALIFIED**: 0 of 6 keys met, all six on CP-L10, which did not run, and the ready, projection and register keys missed. LP1 sent about 1.2 MB requests; CP-0 stopped the route because the mandate document declares itself synthetic (D80).

Owner-decision stops and provider limits: **Owner decision, 5 October 2026:** "Leave them, record the stop". The portfolio sets stay blocked at CP-0 on the self-declared synthetic mandate; removing the fixture's self-declared labels was not pursued.

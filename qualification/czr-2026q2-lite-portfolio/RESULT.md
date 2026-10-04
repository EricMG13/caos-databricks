# CZR Q2 2026 LITE portfolio-screen qualification set — prepared offline

Status: **OFFLINE / UNVERIFIED / NOT QUALIFIED**.

This immutable set prepares `LITE_CREDIT_22 / LITE_PORTFOLIO_DECISION` for
Caesars Entertainment, Inc. (CZR) at an analysis date of 2026-10-02, with a
proposed position in the CZR 6.50% Senior Secured Notes due 2032 held against a
**SYNTHETIC** test mandate. Its qualification-set digest is
`2b259fc2deee688087eb5698ff348e912497a2aaf2416161847bdf81309170d1`.

## The mandate is synthetic (D80)

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
as a page map. All five are inside `MAX_REQUEST_BYTES`.

The indenture is the executed governing document of the proposed position,
admitted because CP-0's recorded refusal on `ccl-fy2025-portfolio` asked for
"applicable executed governing security documents". It carries no key. The
mandate's compliance monitor cites "Indenture §7.11": that is the CLO's own
indenture, not this one, and a SYNTHETIC line in the adaptation says so.

## Keys

Keys authored from the documents; material figures pending owner confirmation.

- CP-L10, issuer: the 10-Q's `$1.9 billion` of available CEI revolver
  capacity at 30 June 2026; the release's Adjusted EBITDA (`$920` million for
  the quarter, `$1,807` million for the six months).
- CP-L10, position: the mandate's proposed position (`USD 5,000,000` par of
  the CZR 6.50% 2032 notes, CUSIP 12769GAC4); its weight on par
  (`5,000,000 / 630,928,502 = 0.7925%` of NAV); the compliance monitor's C-01
  row (single name, `≤ 2.5% NAV`, hard, largest current exposure `2.37%`,
  status `Watch` at 29 May 2026); and FINRA's last trade price, `$93.28`.

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
    whole line (K2, F501).
  Not alternatives: the release's six-month `Caesars | $1,807 | $1,839 |
    (1.7)%` (the six months alone).

The other figure keys (`C-01`) have none: no other whole line states their
figures for the same measure, period and basis (rounded prose such as `$11.8
billion` or `$1.3 billion` is not the figure).

Every key is one whole evidence line of its page, unique in its document: an
answer is accepted only as a whole line (`WHOLE_LINE`) and scored by exact
equality, so a fragment could never be met (F235, F475). Where a fact sits
inside a longer line, the key is that whole line. Since F492 a prose line of a
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

- **Synthetic, not a holding.** The document says "Existing Caesars
  Entertainment exposure: none." and that the position is synthetic.
- **As-of mismatch.** The workbook's NAV and compliance check are dated
  29 May 2026; the price is dated 1 October 2026; the 10-Q reports the
  quarter ended 30 June 2026.
- **The pending take-private.** The 10-Q discloses the 27 May 2026 Agreement
  and Plan of Merger with Fertitta Gaming; the FINRA last trade postdates it.

No provider call, run, snapshot, evidence record, reviewer verdict, or
qualification claim exists; no run has been performed.

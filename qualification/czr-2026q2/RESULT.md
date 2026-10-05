# CZR Q2 2026 LITE earnings-update qualification set — prepared offline

Status: **LIVE-RUN 2026-10-05 / NOT QUALIFIED (citation keys)**. Prepared offline; the live results are in the last section.

This immutable set prepares `LITE_CREDIT_22 / LITE_EARNINGS_UPDATE` for
Caesars Entertainment, Inc. (CZR) at an analysis date of 2026-10-02. Its
qualification-set digest is
`927d45cf483827717ed2f322c7ff7b5a81dd7c8ab9d3e7d06c2f8d2414127c68`.

## Corpus provenance

Each document is an official SEC EDGAR filing or exhibit, fetched on
2 October 2026 and converted from HTML to plain text the same day. The text
SHA-256 is the digest the keys bind; the raw SHA-256 is the HTML as fetched.

| document | source | accession | text SHA-256 | raw HTML SHA-256 |
|---|---|---|---|---|
| `CZR_FY2025_10K.txt` (Form 10-K, year ended 31 December 2025) | https://www.sec.gov/Archives/edgar/data/1590895/000159089526000011/czr-20251231.htm | 0001590895-26-000011 | `172309048af2a6a2dab515d765f00a7c89bf8c874c6104a5e3a052b66cad4512` | `41328bdfa2486cfb53b831c2ddba6009528d8dca3a0d868c98c2cb113142b05f` |
| `CZR_Q2_2026_10Q.txt` (Form 10-Q, quarter ended 30 June 2026) | https://www.sec.gov/Archives/edgar/data/1590895/000159089526000028/czr-20260630.htm | 0001590895-26-000028 | `f369ce5f1ebeddd9a0d4ce02ce3958112267d8701d1a348dfd6dc82d2034793a` | `9dd3fca867c49936c65c9729bd7f9478d4c98b7c60569b74864a839bdeed8500` |
| `CZR_Q2_2026_Earnings_Release.txt` (Ex. 99.1, 28 July 2026) | https://www.sec.gov/Archives/edgar/data/1590895/000159089526000027/ex991-2026q2ceiearningsrel.htm | 0001590895-26-000027 | `b385f76ff631243d1053fa8073ebde4f8886b4a50c9ce34ce3498d6b2ac3e9f8` | `a8982154b99b023b526261f7626022e96ac642834d1d65704629946acecc8a1f` |

All three are under 1.5 MiB, so each reaches CP-0 whole rather than as a page
map, and all are inside `MAX_REQUEST_BYTES`.

## Keys

Keys authored from the documents; material figures pending owner confirmation.

- CP-0: the release's Q2 2026 consolidated net revenues, `$2,993` million
  against `$2,907` million (+3.0%).
- CP-L10: the release's consolidated Adjusted EBITDA (a non-GAAP measure),
  `$920` / `$955` million for the quarter and `$1,807` / `$1,839` million for
  the six months; total outstanding indebtedness `$11,807` million at
  30 June 2026 against `$11,905` million at 31 December 2025; and the 10-K's
  net revenues `11,486` / `11,245` / `11,528` million for 2025 / 2024 / 2023.
- CP-5: the 10-Q's Note 6 total debt, `11,807` face and `11,705` book at
  30 June 2026, `11,792` book at 31 December 2025.

Alternative lines (D101). A figure key is also met by another whole evidence
line, cited under the same module, that states the key's lead figures -- the
current figure and the comparative the key line leads with -- for the same
measure, period and consolidated scope; a % change, a further period or a third
year on the key line need not be on it. Prose keys have none: a statement is
its sentence. Each alternative is one whole evidence line, unique in its
document (F475), and is listed with why it states the key's figures:

- CP-0, the release's `Caesars | $2,993 | $2,907 | 3.0%`:
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
- CP-L10, the 10-K's `Net revenues | 11,486 | 11,245 | 11,528`:
  - the 10-K's `Total | $11,486 | $11,245 | $11,528`, the total of its segment
    table's net revenues, the consolidated figure;
  - the 10-K's `Net Revenues | $11,486 | $11,245 | $11,528 | $241 | 2.1% |
    $(283) | (2.5)%`, its MD&A net revenues row.

The other figure keys (`Total outstanding indebtedness`, `Total debt`) have
none: no other whole line states their figures for the same measure, period and
basis (rounded prose such as `$11.8 billion` or `$1.3 billion` is not the
figure).

The readiness key expects CP-0 to clear CP-L10 and CP-5, and CP-L10 to carry
`SCREENING_ONLY` decision scope. No register key is set: a Q2 update has more
than one defensible comparator (quarter, six months, or the fiscal year), so no
single register cell is unambiguous.

The 10-Q discloses the 27 May 2026 merger agreement with Fertitta Gaming
Holdco, LLC as pending; no fact about it after the 10-Q's filing is in this set.

At preparation no provider call, run, snapshot, evidence record, reviewer
verdict, or qualification claim existed; the live runs follow.

## Live results (3–5 October 2026)

| run (file) | build / tip | status | modules accepted | attempts | citations | keys met | ready / projection / register | stop cause | key usage Δ / recorded charge |
|---|---|---|---|---|---|---|---|---|---|
| E1 (`E1-czr-lite-earnings.json`) | 9043ba7f / 80028e8 | COMPLETE | 3/3 | 7 | 77 (77 anch., 0 unver.) | 2/5 | met / met / — | — | +0.17 / $0.42 |
| E2 (`E2-czr-lite-earnings.json`) | 9043ba7f / D105-D107 | COMPLETE | 3/3 | 5 | 73 (72 anch., 1 unver.) | 1/5 | met / met / — | — | +0.14 / $0.29 |

Reading the table: "build" is the first eight hex digits of the methodology build id in the run JSON; "tip" is the git tip the ledger names (`—` where the ledger names none; tips marked ~ are the base of the next fix task, so the run ran on that tree or its predecessor). "Attempts" is the run JSON's attempt list (every provider call recorded, including a dropped one). "Citations" is the run proof's total with its anchored and unverified counts (`n/r`: the run stopped before a proof was recorded). "Keys met" is the scored matrix row; a run that stopped before COMPLETE or BLOCKED is not scored (`not scored`). "Key usage Δ" is the OpenRouter key-usage change the ledger recorded for the run (`n/l`: not in the ledger); "recorded charge" is the sum of the run's attempt charges at the pinned price. The two disagree and the usage counter lags (ledger), so the key usage is the budget measure. Run files are git-ignored, under `docs/rebuild/runs/live-2026-10-03/`; the model is `openai/gpt-6-luna`, effort high, provider pinned to `openai`, in every row.

Verdict: The set is **NOT QUALIFIED**. Both LITE earnings-update runs completed and were proven with the ready and projection keys met. E1 met 2 of 5 keys in its run JSON (3 of 5 after the K2 rescoring of the 10-Q Adjusted EBITDA line as an alternative, per the ledger); E2, the later run on the D105 to D107 build, met 1 of 5. E1's misses: Total outstanding indebtedness (the model cited the 10-Q's Total debt, a different comparative: a real miss) and FY revenue (not used). E2's four misses are all "not cited". Compared as a single sample each, E2 lost the Caesars revenue key (CP-0) and the total-debt key (CP-5), both not cited: read as selection variance. Records `q7`.

Owner-decision stops and provider limits: None.

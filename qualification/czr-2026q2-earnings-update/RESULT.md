# CZR Q2 2026 FULL earnings-update qualification set — prepared offline

Status: **OFFLINE / UNVERIFIED / NOT QUALIFIED**.

This immutable set prepares `FULL_CREDIT_32 / EARNINGS_UPDATE` for Caesars
Entertainment, Inc. (CZR) at an analysis date of 2026-10-02. Its
qualification-set digest is
`03b43aad16b19c0c3ce2d66b3b949a5b21f2708831b1e293ad0efe94c2677d75`.

## Corpus provenance

Each document is an official SEC EDGAR filing or exhibit, fetched on
2 October 2026 and converted from HTML to plain text the same day; the copies
here are byte-identical to the `czr-2026q2` set's. The text SHA-256 is the
digest the keys bind; the raw SHA-256 is the HTML as fetched.

| document | source | accession | text SHA-256 | raw HTML SHA-256 |
|---|---|---|---|---|
| `CZR_FY2025_10K.txt` (Form 10-K, year ended 31 December 2025) | https://www.sec.gov/Archives/edgar/data/1590895/000159089526000011/czr-20251231.htm | 0001590895-26-000011 | `172309048af2a6a2dab515d765f00a7c89bf8c874c6104a5e3a052b66cad4512` | `41328bdfa2486cfb53b831c2ddba6009528d8dca3a0d868c98c2cb113142b05f` |
| `CZR_Q2_2026_10Q.txt` (Form 10-Q, quarter ended 30 June 2026) | https://www.sec.gov/Archives/edgar/data/1590895/000159089526000028/czr-20260630.htm | 0001590895-26-000028 | `f369ce5f1ebeddd9a0d4ce02ce3958112267d8701d1a348dfd6dc82d2034793a` | `9dd3fca867c49936c65c9729bd7f9478d4c98b7c60569b74864a839bdeed8500` |
| `CZR_Q2_2026_Earnings_Release.txt` (Ex. 99.1, 28 July 2026) | https://www.sec.gov/Archives/edgar/data/1590895/000159089526000027/ex991-2026q2ceiearningsrel.htm | 0001590895-26-000027 | `b385f76ff631243d1053fa8073ebde4f8886b4a50c9ce34ce3498d6b2ac3e9f8` | `a8982154b99b023b526261f7626022e96ac642834d1d65704629946acecc8a1f` |

All three are under 1.5 MiB, so each reaches CP-0 whole rather than as a page
map, and all are inside `MAX_REQUEST_BYTES`.

## Keys

Keys authored from the documents; material figures pending owner confirmation.

- CP-1: the 10-Q's net revenues, `2,993` / `2,907` million for the quarter and
  `5,863` / `5,701` million for the six months ended 30 June 2026 / 2025; and
  operating income, `513` / `526` and `1,013` / `1,014` million.
- CP-1B: the release's consolidated net revenues, `$2,993` / `$2,907` million
  (+3.0%); its consolidated Adjusted EBITDA (a non-GAAP measure), `$920` /
  `$955` million for the quarter and `$1,807` / `$1,839` million for the six
  months; and the 10-K's annual net revenues `11,486` / `11,245` / `11,528`
  million for 2025 / 2024 / 2023.
- CP-2: the 10-Q's six-month operating cash flow, `675` / `680` million, and
  purchase of property and equipment, `(335)` / `(453)` million; and its
  statement that the pending Merger may have significant effects on the
  company, keyed as that whole sentence, which names the diversion of
  management and employee attention (F475; one sentence per line, F492).
- CP-5: the 10-Q's Note 6 total debt, `11,807` face and `11,705` book at
  30 June 2026, `11,792` book at 31 December 2025.

Alternative lines (D101). A figure key is also met by another whole evidence
line, cited under the same module, that states the key's lead figures -- the
current figure and the comparative the key line leads with -- for the same
measure, period and consolidated scope; a % change, a further period or a third
year on the key line need not be on it. Prose keys have none: a statement is
its sentence. Each alternative is one whole evidence line, unique in its
document (F475), and is listed with why it states the key's figures:

- CP-1, the 10-Q's `Net revenues | 2,993 | 2,907 | 5,863 | 5,701`:
  - the 10-Q's `Total | $2,993 | $2,907 | $5,863 | $5,701`, the total of its
    segment table's net revenues, the consolidated figure;
  - the 10-Q's `Net revenues | $2,993 | $2,907 | $86 | 3.0% | $5,863 | $5,701 |
    $162 | 2.8%`, its MD&A net revenues row;
  - the release's `Net revenues | 2,993 | 2,907 | 5,863 | 5,701`, its
    consolidated statement of operations row;
  - the release's `Caesars | $2,993 | $2,907 | 3.0%`, the consolidated row of
    its quarterly net revenues table.
  Not alternatives: the release's `GAAP net revenues of $3.0 billion versus
    $2.9 billion` (rounded, not the figures) and its six-month `Caesars |
    $5,863 | $5,701 | 2.8%` (the six months alone).
- CP-1, the 10-Q's `Operating income | 513 | 526 | 1,013 | 1,014`:
  - the release's `Operating income | 513 | 526 | 1,013 | 1,014`, its
    consolidated statement of operations row.
- CP-1B, the release's `Caesars | $2,993 | $2,907 | 3.0%`:
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
- CP-1B, the release's `Adjusted EBITDA | $920 | $955 | $1,807 | $1,839`:
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
- CP-1B, the 10-K's `Net revenues | 11,486 | 11,245 | 11,528`:
  - the 10-K's `Total | $11,486 | $11,245 | $11,528`, the total of its segment
    table's net revenues, the consolidated figure;
  - the 10-K's `Net Revenues | $11,486 | $11,245 | $11,528 | $241 | 2.1% |
    $(283) | (2.5)%`, its MD&A net revenues row.
- CP-2, the 10-Q's `Net cash provided by operating activities | 675 | 680`:
  - the 10-Q's `During the six months ended June 30, 2026, our operating
    activities generated operating cash inflows of $675 million, as compared to
    operating cash inflows of $680 million during the six months ended June 30,
    2025, primarily due to changes in working capital, coupled with the results
    of operations described above.`, its liquidity sentence, the six months
    against the prior six months.
- CP-2, the 10-Q's `Purchase of property and equipment | (335) | (453)`:
  - the 10-Q's `Cash used for capital expenditures totaled $335 million and
    $453 million for the six months ended June 30, 2026 and 2025, respectively,
    related to our growth, renovation, maintenance, and other capital
    projects.`, its capital-expenditure sentence: the same cash measure and six
    months.
  Not alternatives: the 10-Q's `Total | $167 | $230 | $335 | $453` under
    `Capital Expenditures, Net - By Segment` (a net segment measure, not the
    cash-flow line, though the figures agree).

The other figure keys (`Total debt`) have none: no other whole line states
their figures for the same measure, period and basis (rounded prose such as
`$11.8 billion` or `$1.3 billion` is not the figure).

The readiness key expects CP-0 to clear CP-1, CP-1B, CP-2 and CP-5, and CP-5
to carry `FULL` decision scope. No register key is set: a Q2 update has more
than one defensible comparator (quarter, six months, or the fiscal year), so no
single CP-1B comparator cell is unambiguous.

The 10-Q discloses the 27 May 2026 merger agreement with Fertitta Gaming
Holdco, LLC as pending; no fact about it after the 10-Q's filing is in this set.

No provider call, run, snapshot, evidence record, reviewer verdict, or
qualification claim exists; no run has been performed.

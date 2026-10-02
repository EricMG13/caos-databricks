# CZR Q2 2026 FULL earnings-update qualification set — prepared offline

Status: **OFFLINE / UNVERIFIED / NOT QUALIFIED**.

This immutable set prepares `FULL_CREDIT_32 / EARNINGS_UPDATE` for Caesars
Entertainment, Inc. (CZR) at an analysis date of 2026-10-02. Its
qualification-set digest is
`42a2439e6b8be320c6c3ef8d91b4baa88e2fc34a72402528d65144f37c2b373f`.

## Corpus provenance

Each document is an official SEC EDGAR filing or exhibit, fetched on
2 October 2026 and converted from HTML to plain text the same day; the copies
here are byte-identical to the `czr-2026q2` set's. The text SHA-256 is the
digest the keys bind; the raw SHA-256 is the HTML as fetched.

| document | source | accession | text SHA-256 | raw HTML SHA-256 |
|---|---|---|---|---|
| `CZR_FY2025_10K.txt` (Form 10-K, year ended 31 December 2025) | https://www.sec.gov/Archives/edgar/data/1590895/000159089526000011/czr-20251231.htm | 0001590895-26-000011 | `204904832a3a51442a5c33d791ea35265586f43fac34530cd4d051787d0c0874` | `41328bdfa2486cfb53b831c2ddba6009528d8dca3a0d868c98c2cb113142b05f` |
| `CZR_Q2_2026_10Q.txt` (Form 10-Q, quarter ended 30 June 2026) | https://www.sec.gov/Archives/edgar/data/1590895/000159089526000028/czr-20260630.htm | 0001590895-26-000028 | `1b2027659f255471d41243180c9b550c6915348b7aea79619634c5a9d7b0187c` | `9dd3fca867c49936c65c9729bd7f9478d4c98b7c60569b74864a839bdeed8500` |
| `CZR_Q2_2026_Earnings_Release.txt` (Ex. 99.1, 28 July 2026) | https://www.sec.gov/Archives/edgar/data/1590895/000159089526000027/ex991-2026q2ceiearningsrel.htm | 0001590895-26-000027 | `17f1795b42b4b7aa32ef72582813986c3b98ea9c205d2b4cb446944bcf494ffc` | `a8982154b99b023b526261f7626022e96ac642834d1d65704629946acecc8a1f` |

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
  company.
- CP-5: the 10-Q's Note 6 total debt, `11,807` face and `11,705` book at
  30 June 2026, `11,792` book at 31 December 2025.

The readiness key expects CP-0 to clear CP-1, CP-1B, CP-2 and CP-5, and CP-5
to carry `FULL` decision scope. No register key is set: a Q2 update has more
than one defensible comparator (quarter, six months, or the fiscal year), so no
single CP-1B comparator cell is unambiguous.

The 10-Q discloses the 27 May 2026 merger agreement with Fertitta Gaming
Holdco, LLC as pending; no fact about it after the 10-Q's filing is in this set.

No provider call, run, snapshot, evidence record, reviewer verdict, or
qualification claim exists; no run has been performed.

# CZR Q2 2026 LITE earnings-update qualification set — prepared offline

Status: **OFFLINE / UNVERIFIED / NOT QUALIFIED**.

This immutable set prepares `LITE_CREDIT_22 / LITE_EARNINGS_UPDATE` for
Caesars Entertainment, Inc. (CZR) at an analysis date of 2026-10-02. Its
qualification-set digest is
`f32370aa8e4ed3b367073ed11fbf858fae1f13b0069bd8cbfb57617664a04339`.

## Corpus provenance

Each document is an official SEC EDGAR filing or exhibit, fetched on
2 October 2026 and converted from HTML to plain text the same day. The text
SHA-256 is the digest the keys bind; the raw SHA-256 is the HTML as fetched.

| document | source | accession | text SHA-256 | raw HTML SHA-256 |
|---|---|---|---|---|
| `CZR_FY2025_10K.txt` (Form 10-K, year ended 31 December 2025) | https://www.sec.gov/Archives/edgar/data/1590895/000159089526000011/czr-20251231.htm | 0001590895-26-000011 | `204904832a3a51442a5c33d791ea35265586f43fac34530cd4d051787d0c0874` | `41328bdfa2486cfb53b831c2ddba6009528d8dca3a0d868c98c2cb113142b05f` |
| `CZR_Q2_2026_10Q.txt` (Form 10-Q, quarter ended 30 June 2026) | https://www.sec.gov/Archives/edgar/data/1590895/000159089526000028/czr-20260630.htm | 0001590895-26-000028 | `1b2027659f255471d41243180c9b550c6915348b7aea79619634c5a9d7b0187c` | `9dd3fca867c49936c65c9729bd7f9478d4c98b7c60569b74864a839bdeed8500` |
| `CZR_Q2_2026_Earnings_Release.txt` (Ex. 99.1, 28 July 2026) | https://www.sec.gov/Archives/edgar/data/1590895/000159089526000027/ex991-2026q2ceiearningsrel.htm | 0001590895-26-000027 | `17f1795b42b4b7aa32ef72582813986c3b98ea9c205d2b4cb446944bcf494ffc` | `a8982154b99b023b526261f7626022e96ac642834d1d65704629946acecc8a1f` |

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

The readiness key expects CP-0 to clear CP-L10 and CP-5, and CP-L10 to carry
`SCREENING_ONLY` decision scope. No register key is set: a Q2 update has more
than one defensible comparator (quarter, six months, or the fiscal year), so no
single register cell is unambiguous.

The 10-Q discloses the 27 May 2026 merger agreement with Fertitta Gaming
Holdco, LLC as pending; no fact about it after the 10-Q's filing is in this set.

No provider call, run, snapshot, evidence record, reviewer verdict, or
qualification claim exists; no run has been performed.

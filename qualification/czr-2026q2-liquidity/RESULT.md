# CZR Q2 2026 FULL liquidity qualification set — prepared offline

Status: **OFFLINE / UNVERIFIED / NOT QUALIFIED**.

This immutable set prepares `FULL_CREDIT_32 / LIQUIDITY_REVIEW` for Caesars
Entertainment, Inc. (CZR) at an analysis date of 2026-10-02. Its
qualification-set digest is
`e4d02a674e1df2be9e100a1a21374da9b8dc2307ab357f0de3075cbfe03fc723`.

## Corpus provenance

Each document is an official SEC EDGAR filing or exhibit, fetched on
2 October 2026 and converted from HTML to plain text the same day; the first
three are byte-identical to the `czr-2026q2` set's copies. The text SHA-256 is
the digest the keys bind; the raw SHA-256 is the HTML as fetched.

| document | source | accession | text SHA-256 | raw HTML SHA-256 |
|---|---|---|---|---|
| `CZR_FY2025_10K.txt` (Form 10-K, year ended 31 December 2025) | https://www.sec.gov/Archives/edgar/data/1590895/000159089526000011/czr-20251231.htm | 0001590895-26-000011 | `204904832a3a51442a5c33d791ea35265586f43fac34530cd4d051787d0c0874` | `41328bdfa2486cfb53b831c2ddba6009528d8dca3a0d868c98c2cb113142b05f` |
| `CZR_Q2_2026_10Q.txt` (Form 10-Q, quarter ended 30 June 2026) | https://www.sec.gov/Archives/edgar/data/1590895/000159089526000028/czr-20260630.htm | 0001590895-26-000028 | `1b2027659f255471d41243180c9b550c6915348b7aea79619634c5a9d7b0187c` | `9dd3fca867c49936c65c9729bd7f9478d4c98b7c60569b74864a839bdeed8500` |
| `CZR_Q2_2026_Earnings_Release.txt` (Ex. 99.1, 28 July 2026) | https://www.sec.gov/Archives/edgar/data/1590895/000159089526000027/ex991-2026q2ceiearningsrel.htm | 0001590895-26-000027 | `17f1795b42b4b7aa32ef72582813986c3b98ea9c205d2b4cb446944bcf494ffc` | `a8982154b99b023b526261f7626022e96ac642834d1d65704629946acecc8a1f` |
| `CZR_2020_Credit_Agreement.txt` (Ex. 10.1, Credit Agreement dated 20 July 2020) | https://www.sec.gov/Archives/edgar/data/1590895/000119312520196232/d940333dex101.htm | 0001193125-20-196232 | `b4f124cb0e058b06453f2037bb70e4455600a6006b6559c03721918b5e36f2e2` | `6600ab5bec479091f68dc04b2db65a54ef1013944c94af0ec135335b374c7dba` |

The credit agreement is 936,079 bytes: over 500 KiB, so its path is pinned in
the large-file excludes, but under 1.5 MiB, so it reaches CP-0 whole rather
than as a page map. All four are inside `MAX_REQUEST_BYTES`.

## Keys

Keys authored from the documents; material figures pending owner confirmation.

- CP-1: the 10-Q's cash and cash equivalents, `$965` / `$887` million at
  30 June 2026 / 31 December 2025; and its Note 6 total debt, `11,807` face
  and `11,705` book at 30 June 2026, `11,792` book at 31 December 2025.
- CP-2: the 10-Q's six-month operating cash flow, `675` / `680` million, and
  purchase of property and equipment, `(335)` / `(453)` million.
- CP-2D: the release's CEI Revolving Credit Facility capacity net of
  outstanding balance, `2,130` million at 30 June 2026; the 10-Q's CEI
  Revolving Credit Facility row (2028 maturity, `$120` million face and book
  at 30 June 2026, `$160` million book at 31 December 2025); the 10-Q's annual
  maturities of long-term debt, `$55` / `$114` / `$767` / `$1,574` / `$3,962`
  / `$5,335` million for the rest of 2026, 2027–2030 and thereafter, totalling
  `$11,807` million; and the 10-Q's statement that the CEI Credit Agreement,
  as amended, provides for a `$2.25 billion` CEI Revolving Credit Facility
  maturing on 31 January 2028.

The credit agreement carries no key. Its revolving commitment is stated as at
the 2020 signing date, and the Fourth (9 May 2024) and Fifth (25 November 2024)
Amendments are not in this set, so the current commitment is keyed to the
10-Q; the agreement is admitted for the facility's controlling terms.

The readiness key expects CP-0 to clear CP-1, CP-2 and CP-2D, and CP-2D to
carry `FULL` decision scope. No register key is set: the release's liquidity
total (`$2,928` million) adds the CVA facility and deducts revolver capacity
committed to letters of credit, specific reserves and regulatory requirements,
so cash plus net CEI revolver capacity (`$3,095` million) is an equally
defensible reading and no single bridge cell is unambiguous.

The 10-Q discloses the 27 May 2026 merger agreement with Fertitta Gaming
Holdco, LLC as pending; no fact about it after the 10-Q's filing is in this set.

No provider call, run, snapshot, evidence record, reviewer verdict, or
qualification claim exists; no run has been performed.

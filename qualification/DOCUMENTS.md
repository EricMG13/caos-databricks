# The document register

Emitted 17 September 2026 against `codex/execute-repair-plan`, re-emitted after Task 9.1 added the portfolio-screen set's document copies, and again after Task 9.2 added the relative-value set and its two peer releases; Task 9.3's public decision-record stand-in was admitted and then removed on the owner's instruction, the same day; re-emitted on 18 September 2026 after §98 brought the Boeing and Ford 10-K texts into their own sets, and on 19 September 2026 for the offline FULL deep-research, CCL liquidity, and CCL earnings-update sets, the owner-authorised SEC, Fitch and FINRA evidence tranche, and the complete Phase 2 route inventory.

> **How this file is made.** The hand-authored half is
> [`documents.json`](documents.json) — the demand, the public location, the status,
> the note. The table below is emitted by `scripts/document_register.py --report`,
> which reads that file plus every `qualification/*/qualification.json` and
> computes each document's size and SHA-256 from the bytes on disk. Do not
> hand-edit the table: change `documents.json` and re-emit. The same script is a
> gate — it exits non-zero when a qualification set names a document the
> register does not list, and when a row claims `in_hand` for something that is
> not a file under `qualification/`.

Nothing here is fetched during a model run. Invariant 1 keeps runtime web
discovery structurally absent. The owner authorised the coordinator to source
public equivalents for qualification on 19 September 2026; each admitted
document therefore remains fixed local evidence under its own digest. A
`to_source` row still requires owner-provided private data or a later explicit
source decision.

## Why a register

When this register was created, twelve of the catalog's twenty-three modules
were proven and eleven were not (`docs/COMPLETION_PLAN.md` §2). All eighteen
routes are now deterministically enabled, but the evidence demands remain
independent of code coverage: CP-4 needs executed instruments, CP-2H needs
dated agency actions, CP-3D needs timestamped prices, and CP-8 needs a decision
that was actually taken. Those demands were read out of the vendored
`SKILL.md` files once. Without the register that reading is re-derived per task
and drifts; with it, one artefact holds the evidence boundary to the tree.

Each row's `demand_verified` says whether the module's own `SKILL.md` states a
document gate, or whether the demand is inferred from its purpose and register
names. Seventeen rows are inferred; the note says from what.

## The register

<!-- emitted: register table. Everything between these markers is what
`scripts/document_register.py --report` prints; a test holds them equal, so
a row typed here is a row that fails. -->
| id | issuer | document | status | modules | pathways | bytes | fits ceiling | sha256 |
|---|---|---|---|---|---|---|---|---|
| `vmo2-q3-2025-earnings` | VMO2 | Virgin Media O2 Q3 2025 earnings release | in_hand | CP-0, CP-L10, CP-5, CP-1, CP-1B, CP-2, CP-8 | LITE_EARNINGS_UPDATE, LITE_PORTFOLIO_DECISION, EARNINGS_UPDATE | 144538 | yes | `505bf1a0f4181c9c…` |
| `vmo2-q4-2025-earnings` | VMO2 | Virgin Media O2 Q4 2025 earnings release | in_hand | CP-0, CP-L10, CP-5, CP-1, CP-1B, CP-2, CP-8 | LITE_EARNINGS_UPDATE, LITE_PORTFOLIO_DECISION, EARNINGS_UPDATE | 178368 | yes | `66055bbb8d27721d…` |
| `ccl-fy2025-10k` | CCL | Carnival Corporation & plc FY2025 Form 10-K (text extract) | in_hand | CP-0, CP-L10, CP-1, CP-1A, CP-1B, CP-1D, CP-2, CP-2A, CP-2D, CP-2E, CP-2G, CP-3C, CP-5 | LITE_EARNINGS_UPDATE, LITE_PORTFOLIO_DECISION, LIQUIDITY_REVIEW, EARNINGS_UPDATE, COVENANT_REFINANCING, PORTFOLIO_DECISION, FULL_CREDIT_ASSESSMENT | 311896 | yes | `8fa7fceda34be50b…` |
| `vmo2-q3-2025-earnings-portfolio` | VMO2 | Virgin Media O2 Q3 2025 earnings release (portfolio-screen set copy) | in_hand | CP-0, CP-L10 | LITE_PORTFOLIO_DECISION | 144538 | yes | `505bf1a0f4181c9c…` |
| `vmo2-q4-2025-earnings-portfolio` | VMO2 | Virgin Media O2 Q4 2025 earnings release (portfolio-screen set copy) | in_hand | CP-0, CP-L10 | LITE_PORTFOLIO_DECISION | 178368 | yes | `66055bbb8d27721d…` |
| `ccl-fy2025-10k-portfolio` | CCL | Carnival Corporation & plc FY2025 Form 10-K (text extract, portfolio-screen set copy) | in_hand | CP-0, CP-L10 | LITE_PORTFOLIO_DECISION | 311896 | yes | `8fa7fceda34be50b…` |
| `ccl-fy2025-10k-liquidity` | CCL | Carnival Corporation & plc FY2025 Form 10-K (text extract, FULL liquidity set copy) | in_hand | CP-0, CP-1, CP-2, CP-2D | LIQUIDITY_REVIEW | 311896 | yes | `8fa7fceda34be50b…` |
| `ccl-fy2025-10k-earnings-update` | CCL | Carnival Corporation & plc FY2025 Form 10-K (text extract, FULL earnings-update set copy) | in_hand | CP-0, CP-1, CP-1B, CP-2, CP-5 | EARNINGS_UPDATE | 311896 | yes | `8fa7fceda34be50b…` |
| `ba-fy2025-10k` | BA | The Boeing Company FY2025 Form 10-K (text extract) | in_hand | CP-0, CP-1, CP-1A, CP-1B, CP-1D, CP-2, CP-2A, CP-2D, CP-2E, CP-2G, CP-3C, CP-5 | LIQUIDITY_REVIEW, EARNINGS_UPDATE, COVENANT_REFINANCING, FULL_CREDIT_ASSESSMENT | 1177234 | yes | `0446b367110afddc…` |
| `f-fy2025-10k` | F | Ford Motor Company FY2025 Form 10-K (text extract) | in_hand | CP-0, CP-1, CP-1B, CP-1D, CP-2, CP-2A, CP-2D, CP-2E, CP-2G, CP-3C, CP-5 | LIQUIDITY_REVIEW, EARNINGS_UPDATE, FULL_CREDIT_ASSESSMENT | 1922743 | yes | `97a38bc17e505cd1…` |
| `ccl-fy2025-10k-covenant-refinancing` | CCL | Carnival Corporation & plc FY2025 Form 10-K (text extract, covenant-refinancing set copy) | in_hand | CP-0, CP-1, CP-2, CP-2D, CP-3C, CP-5 | COVENANT_REFINANCING | 311896 | yes | `8fa7fceda34be50b…` |
| `ccl-2025-revolving-credit-agreement` | CCL | Carnival Corporation & plc $4.5 billion Revolving Credit Agreement dated 13 June 2025 (SEC exhibit text extract) | in_hand | CP-4, CP-3C | COVENANT_REFINANCING, PORTFOLIO_DECISION, FULL_CREDIT_ASSESSMENT | 757831 | yes | `0f5a7510e20cbf71…` |
| `ccl-2025-575-notes-2030-indenture` | CCL | Carnival Corporation & plc 5.750% Senior Unsecured Notes due 2030 indenture dated 28 February 2025 (SEC exhibit text extract) | in_hand | CP-4, CP-3C | COVENANT_REFINANCING, PORTFOLIO_DECISION, FULL_CREDIT_ASSESSMENT | 336377 | yes | `2340549fd4f215df…` |
| `ba-2003-senior-debt-indenture` | BA | The Boeing Company senior debt securities indenture dated 26 February 2003 (SEC exhibit text extract) | to_source | CP-4, CP-3C | COVENANT_REFINANCING, PORTFOLIO_DECISION, FULL_CREDIT_ASSESSMENT | — | — | — |
| `ba-2024-first-supplemental-indenture` | BA | The Boeing Company first supplemental indenture dated 1 May 2024 (SEC exhibit text extract) | to_source | CP-4, CP-3C | COVENANT_REFINANCING, PORTFOLIO_DECISION, FULL_CREDIT_ASSESSMENT | — | — | — |
| `ba-2025-364-day-credit-agreement` | BA | The Boeing Company 364-day credit agreement dated 8 August 2025 (SEC exhibit text extract) | to_source | CP-4, CP-3C | COVENANT_REFINANCING, PORTFOLIO_DECISION, FULL_CREDIT_ASSESSMENT | — | — | — |
| `ccl-2025-fitch-rating-action` | CCL | Fitch rating action: Carnival Corporation IDR upgraded to BBB-/Stable, 1 October 2025 | in_hand | CP-2H | LITE_DISTRESSED_RESTRUCTURING, LITE_FULL_CREDIT_SCREEN, FULL_CREDIT_ASSESSMENT, DISTRESSED_RESTRUCTURING | 134938 | yes | `33863f60a0f6c945…` |
| `ccl-finra-trace-143658by7-2026-09-19` | CCL | FINRA TRACE observation for Carnival 5.75% notes due 2030, CUSIP 143658BY7 | in_hand | CP-3D, CP-3 | MARKET_DISLOCATION, PORTFOLIO_DECISION, RELATIVE_VALUE | 1304 | yes | `28f9289818978608…` |
| `ccl-portfolio-mandate-exposures` | CCL | Current portfolio mandate, holdings/exposures, limits, and proposed-position inputs | to_source | CP-3, CP-6 | PORTFOLIO_DECISION, FULL_CREDIT_ASSESSMENT | — | — | — |
| `ccl-fy2025-10k-relative-value` | CCL | Carnival Corporation & plc FY2025 Form 10-K (text extract, relative-value set copy) | in_hand | CP-0, CP-L10, CP-1C | LITE_RELATIVE_VALUE | 311896 | yes | `8fa7fceda34be50b…` |
| `rcl-q4-2025-earnings` | RCL | Royal Caribbean Group, "Royal Caribbean Group Reports 2025 Results, Issues 2026 Guidance" (29 January 2026 earnings release, text extract) | in_hand | CP-1C | LITE_RELATIVE_VALUE, LITE_FULL_CREDIT_SCREEN, RELATIVE_VALUE | 41861 | yes | `43005bdbd3a05fd6…` |
| `nclh-q4-2025-earnings` | NCLH | Norwegian Cruise Line Holdings Q4 and full-year 2025 results (2 March 2026 earnings release, text extract) | in_hand | CP-1C | LITE_RELATIVE_VALUE, LITE_FULL_CREDIT_SCREEN, RELATIVE_VALUE | 52268 | yes | `dd9a0eb7211c111b…` |
| `ccl-decision-record` | CCL | A completed decision record at T0: thesis, expectations, dissent, and the decision date | to_author | CP-8 | LITE_DECISION_LEDGER, DECISION_LEDGER | — | — | — |
| `vmo2-q3-2025-earnings-deep-research` | VMO2 | Virgin Media O2 Q3 2025 earnings release (deep-research set copy) | in_hand | CP-0, CP-DR | LITE_DEEP_RESEARCH | 144538 | yes | `505bf1a0f4181c9c…` |
| `vmo2-q4-2025-earnings-deep-research` | VMO2 | Virgin Media O2 Q4 2025 earnings release (deep-research set copy) | in_hand | CP-0, CP-DR | LITE_DEEP_RESEARCH | 178368 | yes | `66055bbb8d27721d…` |
| `cp-dr-research-brief` | VMO2 | A CP-DR research brief (the vmo2-fy2025-deep-research set's manifest, whose `research_brief` object it is) | in_hand | CP-DR | LITE_DEEP_RESEARCH | 4607 | yes | `0c46b5b983cb2875…` |
| `vmo2-q3-2025-earnings-full-deep-research` | VMO2 | Virgin Media O2 Q3 2025 earnings release (FULL deep-research set copy) | in_hand | CP-0, CP-DR | DEEP_RESEARCH | 144538 | yes | `505bf1a0f4181c9c…` |
| `vmo2-q4-2025-earnings-full-deep-research` | VMO2 | Virgin Media O2 Q4 2025 earnings release (FULL deep-research set copy) | in_hand | CP-0, CP-DR | DEEP_RESEARCH | 178368 | yes | `66055bbb8d27721d…` |
| `cp-dr-full-research-brief` | VMO2 | The FULL deep-research set manifest carrying the reused CP-DR research brief | in_hand | CP-DR | DEEP_RESEARCH | 4592 | yes | `2c42e8297388bada…` |
| `save-2024-chapter-11-8k` | SAVE | Spirit Airlines Chapter 11 announcement, Form 8-K filed 18 November 2024 (SEC filing text extract) | in_hand | CP-0, CP-4C | DISTRESSED_RESTRUCTURING, LITE_DISTRESSED_RESTRUCTURING | 45612 | yes | `9d3c7ba8d1632130…` |
| `save-2024-rsa-with-chapter-11-plan` | SAVE | Spirit Airlines Restructuring Support Agreement with attached Joint Chapter 11 Plan, dated 18 November 2024 (SEC exhibit text extract) | in_hand | CP-4C | DISTRESSED_RESTRUCTURING, LITE_DISTRESSED_RESTRUCTURING | 714222 | yes | `6b40ff57e904068b…` |
| `ccl-fy2025-10k-market-dislocation` | CCL | Carnival Corporation & plc FY2025 Form 10-K (market-dislocation set copy) | in_hand | CP-0 | MARKET_DISLOCATION | 311896 | yes | `8fa7fceda34be50b…` |
| `ccl-finra-trace-market-dislocation` | CCL | FINRA CCL 5.75% 2030 note observation at 19 September 2026 (market-dislocation set copy) | in_hand | CP-3D | MARKET_DISLOCATION | 1304 | yes | `28f9289818978608…` |
| `ccl-fy2025-10k-lite-covenant-refinancing` | CCL | Carnival Corporation & plc FY2025 Form 10-K (LITE covenant-refinancing set copy) | in_hand | CP-0, CP-L10, CP-3C, CP-5 | LITE_COVENANT_REFINANCING | 311896 | yes | `8fa7fceda34be50b…` |
| `ccl-2025-revolver-lite-covenant-refinancing` | CCL | 13 June 2025 revolving credit agreement (LITE covenant-refinancing set copy) | in_hand | CP-3C | LITE_COVENANT_REFINANCING | 757831 | yes | `0f5a7510e20cbf71…` |
| `ccl-2025-notes-lite-covenant-refinancing` | CCL | 28 February 2025 5.75% 2030 notes indenture (LITE covenant-refinancing set copy) | in_hand | CP-3C | LITE_COVENANT_REFINANCING | 336377 | yes | `2340549fd4f215df…` |
| `ccl-fy2025-10k-lite-full-credit-screen` | CCL | Carnival Corporation & plc FY2025 Form 10-K (LITE full-credit-screen set copy) | in_hand | CP-0, CP-L10, CP-1A, CP-1C, CP-2A, CP-3C, CP-4C, CP-5 | LITE_FULL_CREDIT_SCREEN | 311896 | yes | `8fa7fceda34be50b…` |
| `ccl-2025-revolver-lite-full-credit-screen` | CCL | 13 June 2025 revolving credit agreement (LITE full-credit-screen set copy) | in_hand | CP-3C | LITE_FULL_CREDIT_SCREEN | 757831 | yes | `0f5a7510e20cbf71…` |
| `ccl-2025-notes-lite-full-credit-screen` | CCL | 28 February 2025 5.75% 2030 notes indenture (LITE full-credit-screen set copy) | in_hand | CP-3C | LITE_FULL_CREDIT_SCREEN | 336377 | yes | `2340549fd4f215df…` |
| `ccl-fitch-lite-full-credit-screen` | CCL | Fitch 2025 CCL rating action (LITE full-credit-screen set copy) | in_hand | CP-2H | LITE_FULL_CREDIT_SCREEN | 134938 | yes | `33863f60a0f6c945…` |
| `rcl-lite-full-credit-screen` | RCL | Royal Caribbean Group FY2025 results (LITE full-credit-screen set copy) | in_hand | CP-1C | LITE_FULL_CREDIT_SCREEN | 41861 | yes | `43005bdbd3a05fd6…` |
| `nclh-lite-full-credit-screen` | NCLH | Norwegian Cruise Line Holdings FY2025 results (LITE full-credit-screen set copy) | in_hand | CP-1C | LITE_FULL_CREDIT_SCREEN | 52268 | yes | `dd9a0eb7211c111b…` |
| `save-2024-8k-lite-distressed` | SAVE | Spirit Airlines 18 November 2024 Chapter 11 8-K (LITE distressed set copy) | in_hand | CP-0, CP-4C | LITE_DISTRESSED_RESTRUCTURING | 45612 | yes | `9d3c7ba8d1632130…` |
| `save-2024-rsa-lite-distressed` | SAVE | Spirit Airlines RSA and attached Joint Chapter 11 Plan (LITE distressed set copy) | in_hand | CP-4C | LITE_DISTRESSED_RESTRUCTURING | 714222 | yes | `6b40ff57e904068b…` |
| `ccl-fy2025-10k-full-relative-value` | CCL | Carnival Corporation & plc FY2025 Form 10-K (FULL relative-value set copy) | in_hand | CP-0, CP-1, CP-1C, CP-2, CP-2A, CP-2G, CP-3 | RELATIVE_VALUE | 311896 | yes | `8fa7fceda34be50b…` |
| `ccl-2025-revolver-full-relative-value` | CCL | 13 June 2025 revolving credit agreement (FULL relative-value set copy) | in_hand | CP-4 | RELATIVE_VALUE | 757831 | yes | `0f5a7510e20cbf71…` |
| `ccl-2025-notes-full-relative-value` | CCL | 28 February 2025 5.75% 2030 notes indenture (FULL relative-value set copy) | in_hand | CP-4, CP-3 | RELATIVE_VALUE | 336377 | yes | `2340549fd4f215df…` |
| `ccl-finra-full-relative-value` | CCL | FINRA CCL 5.75% 2030 note observation at 19 September 2026 (FULL relative-value set copy) | in_hand | CP-3D, CP-3 | RELATIVE_VALUE | 1304 | yes | `28f9289818978608…` |
| `rcl-full-relative-value` | RCL | Royal Caribbean Group FY2025 results (FULL relative-value set copy) | in_hand | CP-1C, CP-3 | RELATIVE_VALUE | 41861 | yes | `43005bdbd3a05fd6…` |
| `nclh-full-relative-value` | NCLH | Norwegian Cruise Line Holdings FY2025 results (FULL relative-value set copy) | in_hand | CP-1C, CP-3 | RELATIVE_VALUE | 52268 | yes | `dd9a0eb7211c111b…` |
| `czr-fy2025-10k` | CZR | Caesars Entertainment, Inc. FY2025 Form 10-K (SEC filing text extract) | in_hand | CP-0, CP-L10 | LITE_EARNINGS_UPDATE | 405745 | yes | `172309048af2a6a2…` |
| `czr-q2-2026-10q` | CZR | Caesars Entertainment, Inc. Form 10-Q for the quarter ended 30 June 2026 (SEC filing text extract) | in_hand | CP-0, CP-5 | LITE_EARNINGS_UPDATE | 166976 | yes | `f369ce5f1ebeddd9…` |
| `czr-q2-2026-earnings` | CZR | Caesars Entertainment, Inc. second quarter 2026 earnings release, Exhibit 99.1, 28 July 2026 (SEC exhibit text extract) | in_hand | CP-0, CP-L10 | LITE_EARNINGS_UPDATE | 15590 | yes | `b385f76ff631243d…` |
| `czr-2026-merger-agreement-lite-earnings-update` | CZR | Caesars Entertainment, Inc. Agreement and Plan of Merger with Fertitta Gaming Holdco, LLC, Exhibit 2.1 to the Form 8-K of 28 May 2026 (SEC exhibit text extract) | in_hand | CP-0, CP-L10 | LITE_EARNINGS_UPDATE | 411229 | yes | `e01077c1ed37c5b0…` |
| `czr-fy2025-10k-earnings-update` | CZR | Caesars Entertainment, Inc. FY2025 Form 10-K (SEC filing text extract, FULL earnings-update set copy) | in_hand | CP-0, CP-1B | EARNINGS_UPDATE | 405745 | yes | `172309048af2a6a2…` |
| `czr-q2-2026-10q-earnings-update` | CZR | Caesars Entertainment, Inc. Form 10-Q for the quarter ended 30 June 2026 (SEC filing text extract, FULL earnings-update set copy) | in_hand | CP-0, CP-1, CP-2, CP-5 | EARNINGS_UPDATE | 166976 | yes | `f369ce5f1ebeddd9…` |
| `czr-q2-2026-earnings-earnings-update` | CZR | Caesars Entertainment, Inc. second quarter 2026 earnings release, Exhibit 99.1, 28 July 2026 (SEC exhibit text extract, FULL earnings-update set copy) | in_hand | CP-0, CP-1B | EARNINGS_UPDATE | 15590 | yes | `b385f76ff631243d…` |
| `czr-fy2025-10k-liquidity` | CZR | Caesars Entertainment, Inc. FY2025 Form 10-K (SEC filing text extract, FULL liquidity set copy) | in_hand | CP-0 | LIQUIDITY_REVIEW | 405745 | yes | `172309048af2a6a2…` |
| `czr-q2-2026-10q-liquidity` | CZR | Caesars Entertainment, Inc. Form 10-Q for the quarter ended 30 June 2026 (SEC filing text extract, FULL liquidity set copy) | in_hand | CP-0, CP-1, CP-2, CP-2D | LIQUIDITY_REVIEW | 166976 | yes | `f369ce5f1ebeddd9…` |
| `czr-q2-2026-earnings-liquidity` | CZR | Caesars Entertainment, Inc. second quarter 2026 earnings release, Exhibit 99.1, 28 July 2026 (SEC exhibit text extract, FULL liquidity set copy) | in_hand | CP-0, CP-2D | LIQUIDITY_REVIEW | 15590 | yes | `b385f76ff631243d…` |
| `czr-2024-credit-agreement-incremental-assumption-no3-liquidity` | CZR | Caesars Entertainment, Inc. Incremental Assumption Agreement No. 3 dated 6 February 2024, JPMorgan Chase Bank, N.A. as administrative agent, with Exhibit A, the Credit Agreement dated 20 July 2020 conformed through it (SEC exhibit text extract, FULL liquidity set copy) | in_hand | CP-2D | LIQUIDITY_REVIEW | 1077810 | yes | `25bea1d14fd9bb22…` |
| `czr-2026-merger-agreement-liquidity` | CZR | Caesars Entertainment, Inc. Agreement and Plan of Merger with Fertitta Gaming Holdco, LLC, Exhibit 2.1 to the Form 8-K of 28 May 2026 (SEC exhibit text extract) | in_hand | CP-2D | LIQUIDITY_REVIEW | 411229 | yes | `e01077c1ed37c5b0…` |
| `czr-fy2025-10k-covenant-refinancing` | CZR | Caesars Entertainment, Inc. FY2025 Form 10-K (SEC filing text extract, FULL covenant-refinancing set copy) | in_hand | CP-0, CP-1 | COVENANT_REFINANCING | 405745 | yes | `172309048af2a6a2…` |
| `czr-q2-2026-10q-covenant-refinancing` | CZR | Caesars Entertainment, Inc. Form 10-Q for the quarter ended 30 June 2026 (SEC filing text extract, FULL covenant-refinancing set copy) | in_hand | CP-0, CP-1, CP-2, CP-2D, CP-4, CP-3C, CP-5 | COVENANT_REFINANCING | 166976 | yes | `f369ce5f1ebeddd9…` |
| `czr-2024-credit-agreement-incremental-assumption-no3` | CZR | Caesars Entertainment, Inc. Incremental Assumption Agreement No. 3 dated 6 February 2024, JPMorgan Chase Bank, N.A. as administrative agent, with Exhibit A, the Credit Agreement dated 20 July 2020 conformed through it (SEC exhibit text extract) | in_hand | CP-4 | COVENANT_REFINANCING | 1077810 | yes | `25bea1d14fd9bb22…` |
| `czr-2024-credit-agreement-fourth-amendment` | CZR | Caesars Entertainment, Inc. Fourth Amendment to Credit Agreement dated 9 May 2024 (SEC exhibit text extract) | in_hand | CP-4 | COVENANT_REFINANCING | 25431 | yes | `32f91de6ef3ff93d…` |
| `czr-2024-credit-agreement-fifth-amendment` | CZR | Caesars Entertainment, Inc. Fifth Amendment to Credit Agreement dated 25 November 2024 (SEC exhibit text extract) | in_hand | CP-4 | COVENANT_REFINANCING | 38797 | yes | `7f2b5c777dc33479…` |
| `czr-2024-650-notes-2032-indenture` | CZR | Caesars Entertainment, Inc. Indenture for the 6.500% Senior Secured Notes due 2032, dated 6 February 2024, U.S. Bank Trust Company, N.A. as trustee (SEC exhibit text extract) | in_hand | CP-4, CP-3C | COVENANT_REFINANCING | 758385 | yes | `0809ab3981090bd2…` |
| `czr-2024-650-notes-2032-first-supplemental-indenture` | CZR | Caesars Entertainment, Inc. First Supplemental Indenture dated 1 March 2024 to the Indenture for the 6.500% Senior Secured Notes due 2032 (SEC exhibit text extract) | in_hand | CP-4, CP-3C | COVENANT_REFINANCING | 11774 | yes | `0af4615b9a52e91e…` |
| `czr-2024-650-notes-2032-second-supplemental-indenture` | CZR | Caesars Entertainment, Inc. Second Supplemental Indenture dated 23 August 2024 to the Indenture for the 6.500% Senior Secured Notes due 2032 (SEC exhibit text extract) | in_hand | CP-4, CP-3C | COVENANT_REFINANCING | 15684 | yes | `3621f08611f4c6a6…` |
| `czr-2026-merger-8k` | CZR | Caesars Entertainment, Inc. Form 8-K, Item 1.01, Agreement and Plan of Merger with Fertitta Gaming Holdco, LLC, 27 May 2026 (SEC filing text extract) | in_hand | CP-3C | COVENANT_REFINANCING | 30809 | yes | `6808734cfbb19b56…` |
| `czr-2026-merger-press-release` | CZR | Caesars Entertainment, Inc. press release announcing the Fertitta Entertainment merger agreement, Exhibit 99.1, 28 May 2026 (SEC exhibit text extract) | in_hand | CP-3C | COVENANT_REFINANCING | 19048 | yes | `4fbecbd5f5a10b15…` |
| `czr-2026-merger-agreement` | CZR | Caesars Entertainment, Inc. Agreement and Plan of Merger with Fertitta Gaming Holdco, LLC, Exhibit 2.1 to the Form 8-K of 28 May 2026 (SEC exhibit text extract) | in_hand | CP-3C, CP-4 | COVENANT_REFINANCING | 411229 | yes | `e01077c1ed37c5b0…` |
| `czr-q2-2026-10q-lite-covenant-refinancing` | CZR | Caesars Entertainment, Inc. Form 10-Q for the quarter ended 30 June 2026 (SEC filing text extract, LITE covenant-refinancing set copy) | in_hand | CP-0, CP-L10, CP-3C, CP-5 | LITE_COVENANT_REFINANCING | 166976 | yes | `f369ce5f1ebeddd9…` |
| `czr-2024-credit-agreement-incremental-assumption-no3-lite-covenant-refinancing` | CZR | Caesars Entertainment, Inc. Incremental Assumption Agreement No. 3 dated 6 February 2024, JPMorgan Chase Bank, N.A. as administrative agent, with Exhibit A, the Credit Agreement dated 20 July 2020 conformed through it (SEC exhibit text extract, LITE covenant-refinancing set copy) | in_hand | CP-3C | LITE_COVENANT_REFINANCING | 1077810 | yes | `25bea1d14fd9bb22…` |
| `czr-2024-credit-agreement-fourth-amendment-lite-covenant-refinancing` | CZR | Caesars Entertainment, Inc. Fourth Amendment to Credit Agreement dated 9 May 2024 (SEC exhibit text extract, LITE covenant-refinancing set copy) | in_hand | CP-3C | LITE_COVENANT_REFINANCING | 25431 | yes | `32f91de6ef3ff93d…` |
| `czr-2024-credit-agreement-fifth-amendment-lite-covenant-refinancing` | CZR | Caesars Entertainment, Inc. Fifth Amendment to Credit Agreement dated 25 November 2024 (SEC exhibit text extract, LITE covenant-refinancing set copy) | in_hand | CP-3C | LITE_COVENANT_REFINANCING | 38797 | yes | `7f2b5c777dc33479…` |
| `czr-2024-650-notes-2032-indenture-lite-covenant-refinancing` | CZR | Caesars Entertainment, Inc. Indenture for the 6.500% Senior Secured Notes due 2032, dated 6 February 2024, U.S. Bank Trust Company, N.A. as trustee (SEC exhibit text extract, LITE covenant-refinancing set copy) | in_hand | CP-3C | LITE_COVENANT_REFINANCING | 758385 | yes | `0809ab3981090bd2…` |
| `czr-2024-650-notes-2032-first-supplemental-indenture-lite-covenant-refinancing` | CZR | Caesars Entertainment, Inc. First Supplemental Indenture dated 1 March 2024 to the Indenture for the 6.500% Senior Secured Notes due 2032 (SEC exhibit text extract, LITE covenant-refinancing set copy) | in_hand | CP-3C | LITE_COVENANT_REFINANCING | 11774 | yes | `0af4615b9a52e91e…` |
| `czr-2024-650-notes-2032-second-supplemental-indenture-lite-covenant-refinancing` | CZR | Caesars Entertainment, Inc. Second Supplemental Indenture dated 23 August 2024 to the Indenture for the 6.500% Senior Secured Notes due 2032 (SEC exhibit text extract, LITE covenant-refinancing set copy) | in_hand | CP-3C | LITE_COVENANT_REFINANCING | 15684 | yes | `3621f08611f4c6a6…` |
| `czr-2026-merger-8k-lite-covenant-refinancing` | CZR | Caesars Entertainment, Inc. Form 8-K, Item 1.01, Agreement and Plan of Merger with Fertitta Gaming Holdco, LLC, 27 May 2026 (SEC filing text extract, LITE covenant-refinancing set copy) | in_hand | CP-3C | LITE_COVENANT_REFINANCING | 30809 | yes | `6808734cfbb19b56…` |
| `czr-2026-merger-agreement-lite-covenant-refinancing` | CZR | Caesars Entertainment, Inc. Agreement and Plan of Merger with Fertitta Gaming Holdco, LLC, Exhibit 2.1 to the Form 8-K of 28 May 2026 (SEC exhibit text extract) | in_hand | CP-3C | LITE_COVENANT_REFINANCING | 411229 | yes | `e01077c1ed37c5b0…` |
| `czr-q2-2026-10q-lite-relative-value` | CZR | Caesars Entertainment, Inc. Form 10-Q for the quarter ended 30 June 2026 (SEC filing text extract, LITE relative-value set copy) | in_hand | CP-0, CP-L10, CP-1C | LITE_RELATIVE_VALUE | 166976 | yes | `f369ce5f1ebeddd9…` |
| `czr-q2-2026-earnings-lite-relative-value` | CZR | Caesars Entertainment, Inc. second quarter 2026 earnings release, Exhibit 99.1, 28 July 2026 (SEC exhibit text extract, LITE relative-value set copy) | in_hand | CP-0, CP-1C | LITE_RELATIVE_VALUE | 15590 | yes | `b385f76ff631243d…` |
| `czr-2024-credit-agreement-incremental-assumption-no3-lite-relative-value` | CZR | Caesars Entertainment, Inc. Incremental Assumption Agreement No. 3 dated 6 February 2024, JPMorgan Chase Bank, N.A. as administrative agent, with Exhibit A, the Credit Agreement dated 20 July 2020 conformed through it (SEC exhibit text extract, LITE relative-value set copy) | in_hand | CP-0 | LITE_RELATIVE_VALUE | 1077810 | yes | `25bea1d14fd9bb22…` |
| `czr-2024-650-notes-2032-indenture-lite-relative-value` | CZR | Caesars Entertainment, Inc. Indenture for the 6.500% Senior Secured Notes due 2032, dated 6 February 2024, U.S. Bank Trust Company, N.A. as trustee (SEC exhibit text extract, LITE relative-value set copy) | in_hand | CP-0 | LITE_RELATIVE_VALUE | 758385 | yes | `0809ab3981090bd2…` |
| `czr-2024-650-notes-2032-first-supplemental-indenture-lite-relative-value` | CZR | Caesars Entertainment, Inc. First Supplemental Indenture dated 1 March 2024 to the Indenture for the 6.500% Senior Secured Notes due 2032 (SEC exhibit text extract, LITE relative-value set copy) | in_hand | CP-0 | LITE_RELATIVE_VALUE | 11774 | yes | `0af4615b9a52e91e…` |
| `czr-2024-650-notes-2032-second-supplemental-indenture-lite-relative-value` | CZR | Caesars Entertainment, Inc. Second Supplemental Indenture dated 23 August 2024 to the Indenture for the 6.500% Senior Secured Notes due 2032 (SEC exhibit text extract, LITE relative-value set copy) | in_hand | CP-0 | LITE_RELATIVE_VALUE | 15684 | yes | `3621f08611f4c6a6…` |
| `mgm-q2-2026-earnings` | MGM | MGM Resorts International second quarter 2026 earnings release, Exhibit 99.1, 29 July 2026 (SEC exhibit text extract) | in_hand | CP-1C | LITE_RELATIVE_VALUE | 29214 | yes | `795ac68aa1c51a7e…` |
| `penn-q2-2026-earnings` | PENN | PENN Entertainment, Inc. second quarter 2026 earnings release, Exhibit 99.1, 6 August 2026 (SEC exhibit text extract) | in_hand | CP-1C | LITE_RELATIVE_VALUE | 33608 | yes | `4d12fff94b066f73…` |
| `czr-finra-trace-12769gac4-2026-10-02-lite-relative-value` | CZR | FINRA TRACE observation for Caesars Entertainment 6.50% notes due 2032, CUSIP 12769GAC4 (LITE relative-value set copy) | in_hand | CP-L10 | LITE_RELATIVE_VALUE | 1361 | yes | `4018aaa62309df6c…` |
| `czr-finra-trace-12769gad2-2026-10-02-lite-relative-value` | CZR | FINRA TRACE observation for Caesars Entertainment 6.00% notes due 2032, CUSIP 12769GAD2 (LITE relative-value set copy) | in_hand | CP-L10 | LITE_RELATIVE_VALUE | 1364 | yes | `256c646128b7b670…` |
| `mgm-finra-trace-552953ck5-2026-10-02-lite-relative-value` | MGM | FINRA TRACE observation for MGM Resorts International 6.125% notes due 2029, CUSIP 552953CK5 (LITE relative-value set copy) | in_hand | CP-L10 | LITE_RELATIVE_VALUE | 1277 | yes | `e17cea1bb90debde…` |
| `penn-finra-trace-707569av1-2026-10-02-lite-relative-value` | PENN | FINRA TRACE observation for PENN Entertainment 4.125% notes due 2029, CUSIP 707569AV1 (LITE relative-value set copy) | in_hand | CP-L10 | LITE_RELATIVE_VALUE | 1354 | yes | `666c0f36ace32336…` |
| `czr-q2-2026-10q-relative-value` | CZR | Caesars Entertainment, Inc. Form 10-Q for the quarter ended 30 June 2026 (SEC filing text extract, FULL relative-value set copy) | in_hand | CP-0, CP-1, CP-1C, CP-2, CP-4 | RELATIVE_VALUE | 166976 | yes | `f369ce5f1ebeddd9…` |
| `czr-fy2025-10k-relative-value` | CZR | Caesars Entertainment, Inc. FY2025 Form 10-K (SEC filing text extract, FULL relative-value set copy) | in_hand | CP-0, CP-2 | RELATIVE_VALUE | 405745 | yes | `172309048af2a6a2…` |
| `czr-q2-2026-earnings-relative-value` | CZR | Caesars Entertainment, Inc. second quarter 2026 earnings release, Exhibit 99.1, 28 July 2026 (SEC exhibit text extract, FULL relative-value set copy) | in_hand | CP-0, CP-1C | RELATIVE_VALUE | 15590 | yes | `b385f76ff631243d…` |
| `czr-2024-credit-agreement-incremental-assumption-no3-relative-value` | CZR | Caesars Entertainment, Inc. Incremental Assumption Agreement No. 3 dated 6 February 2024, JPMorgan Chase Bank, N.A. as administrative agent, with Exhibit A, the Credit Agreement dated 20 July 2020 conformed through it (SEC exhibit text extract, FULL relative-value set copy) | in_hand | CP-4 | RELATIVE_VALUE | 1077810 | yes | `25bea1d14fd9bb22…` |
| `czr-2024-650-notes-2032-indenture-relative-value` | CZR | Caesars Entertainment, Inc. Indenture for the 6.500% Senior Secured Notes due 2032, dated 6 February 2024, U.S. Bank Trust Company, N.A. as trustee (SEC exhibit text extract, FULL relative-value set copy) | in_hand | CP-4 | RELATIVE_VALUE | 758385 | yes | `0809ab3981090bd2…` |
| `czr-2024-650-notes-2032-first-supplemental-indenture-relative-value` | CZR | Caesars Entertainment, Inc. First Supplemental Indenture dated 1 March 2024 to the Indenture for the 6.500% Senior Secured Notes due 2032 (SEC exhibit text extract, FULL relative-value set copy) | in_hand | CP-4 | RELATIVE_VALUE | 11774 | yes | `0af4615b9a52e91e…` |
| `czr-2024-650-notes-2032-second-supplemental-indenture-relative-value` | CZR | Caesars Entertainment, Inc. Second Supplemental Indenture dated 23 August 2024 to the Indenture for the 6.500% Senior Secured Notes due 2032 (SEC exhibit text extract, FULL relative-value set copy) | in_hand | CP-4 | RELATIVE_VALUE | 15684 | yes | `3621f08611f4c6a6…` |
| `czr-finra-trace-12769gac4-2026-10-02` | CZR | FINRA TRACE observation for Caesars Entertainment 6.50% notes due 2032, CUSIP 12769GAC4 | in_hand | CP-3D, CP-3 | RELATIVE_VALUE | 1361 | yes | `4018aaa62309df6c…` |
| `czr-finra-trace-12769gad2-2026-10-02` | CZR | FINRA TRACE observation for Caesars Entertainment 6.00% notes due 2032, CUSIP 12769GAD2 | in_hand | CP-3D, CP-3 | RELATIVE_VALUE | 1364 | yes | `256c646128b7b670…` |
| `mgm-q2-2026-earnings-relative-value` | MGM | MGM Resorts International second quarter 2026 earnings release, Exhibit 99.1, 29 July 2026 (SEC exhibit text extract, FULL relative-value set copy) | in_hand | CP-1C | RELATIVE_VALUE | 29214 | yes | `795ac68aa1c51a7e…` |
| `penn-q2-2026-earnings-relative-value` | PENN | PENN Entertainment, Inc. second quarter 2026 earnings release, Exhibit 99.1, 6 August 2026 (SEC exhibit text extract, FULL relative-value set copy) | in_hand | CP-1C | RELATIVE_VALUE | 33608 | yes | `4d12fff94b066f73…` |
| `mgm-finra-trace-552953ck5-2026-10-02` | MGM | FINRA TRACE observation for MGM Resorts International 6.125% notes due 2029, CUSIP 552953CK5 | in_hand | CP-3D, CP-3 | RELATIVE_VALUE | 1277 | yes | `e17cea1bb90debde…` |
| `penn-finra-trace-707569av1-2026-10-02` | PENN | FINRA TRACE observation for PENN Entertainment 4.125% notes due 2029, CUSIP 707569AV1 | in_hand | CP-3D, CP-3 | RELATIVE_VALUE | 1354 | yes | `666c0f36ace32336…` |
| `czr-q2-2026-10q-lite-full-credit-screen` | CZR | Caesars Entertainment, Inc. Form 10-Q for the quarter ended 30 June 2026 (SEC filing text extract, LITE full-credit-screen set copy) | in_hand | CP-0, CP-L10, CP-3C, CP-4C, CP-5 | LITE_FULL_CREDIT_SCREEN | 166976 | yes | `f369ce5f1ebeddd9…` |
| `czr-q2-2026-earnings-lite-full-credit-screen` | CZR | Caesars Entertainment, Inc. second quarter 2026 earnings release, Exhibit 99.1, 28 July 2026 (SEC exhibit text extract, LITE full-credit-screen set copy) | in_hand | CP-0, CP-L10 | LITE_FULL_CREDIT_SCREEN | 15590 | yes | `b385f76ff631243d…` |
| `czr-2026-merger-8k-lite-full-credit-screen` | CZR | Caesars Entertainment, Inc. Form 8-K, Item 1.01, Agreement and Plan of Merger with Fertitta Gaming Holdco, LLC, 27 May 2026 (SEC filing text extract, LITE full-credit-screen set copy) | in_hand | CP-1A | LITE_FULL_CREDIT_SCREEN | 30809 | yes | `6808734cfbb19b56…` |
| `czr-2026-merger-press-release-lite-full-credit-screen` | CZR | Caesars Entertainment, Inc. press release announcing the Fertitta Entertainment merger agreement, Exhibit 99.1, 28 May 2026 (SEC exhibit text extract, LITE full-credit-screen set copy) | in_hand | CP-1A | LITE_FULL_CREDIT_SCREEN | 19048 | yes | `4fbecbd5f5a10b15…` |
| `mgm-q2-2026-earnings-lite-full-credit-screen` | MGM | MGM Resorts International second quarter 2026 earnings release, Exhibit 99.1, 29 July 2026 (SEC exhibit text extract, LITE full-credit-screen set copy) | in_hand | CP-1C | LITE_FULL_CREDIT_SCREEN | 29214 | yes | `795ac68aa1c51a7e…` |
| `penn-q2-2026-earnings-lite-full-credit-screen` | PENN | PENN Entertainment, Inc. second quarter 2026 earnings release, Exhibit 99.1, 6 August 2026 (SEC exhibit text extract, LITE full-credit-screen set copy) | in_hand | CP-1C | LITE_FULL_CREDIT_SCREEN | 33608 | yes | `4d12fff94b066f73…` |
| `czr-2024-credit-agreement-incremental-assumption-no3-lite-full-credit-screen` | CZR | Caesars Entertainment, Inc. Incremental Assumption Agreement No. 3 dated 6 February 2024, JPMorgan Chase Bank, N.A. as administrative agent, with Exhibit A, the Credit Agreement dated 20 July 2020 conformed through it (SEC exhibit text extract, LITE full-credit-screen set copy) | in_hand | CP-0, CP-3C | LITE_FULL_CREDIT_SCREEN | 1077810 | yes | `25bea1d14fd9bb22…` |
| `czr-2024-650-notes-2032-indenture-lite-full-credit-screen` | CZR | Caesars Entertainment, Inc. Indenture for the 6.500% Senior Secured Notes due 2032, dated 6 February 2024, U.S. Bank Trust Company, N.A. as trustee (SEC exhibit text extract, LITE full-credit-screen set copy) | in_hand | CP-0, CP-3C | LITE_FULL_CREDIT_SCREEN | 758385 | yes | `0809ab3981090bd2…` |
| `czr-2024-650-notes-2032-first-supplemental-indenture-lite-full-credit-screen` | CZR | Caesars Entertainment, Inc. First Supplemental Indenture dated 1 March 2024 to the Indenture for the 6.500% Senior Secured Notes due 2032 (SEC exhibit text extract, LITE full-credit-screen set copy) | in_hand | CP-0, CP-3C | LITE_FULL_CREDIT_SCREEN | 11774 | yes | `0af4615b9a52e91e…` |
| `czr-2024-650-notes-2032-second-supplemental-indenture-lite-full-credit-screen` | CZR | Caesars Entertainment, Inc. Second Supplemental Indenture dated 23 August 2024 to the Indenture for the 6.500% Senior Secured Notes due 2032 (SEC exhibit text extract, LITE full-credit-screen set copy) | in_hand | CP-0, CP-3C | LITE_FULL_CREDIT_SCREEN | 15684 | yes | `3621f08611f4c6a6…` |
| `czr-finra-trace-12769gac4-2026-10-02-lite-full-credit-screen` | CZR | FINRA TRACE observation for Caesars Entertainment 6.50% notes due 2032, CUSIP 12769GAC4 (LITE full-credit-screen set copy) | in_hand | CP-2H | LITE_FULL_CREDIT_SCREEN | 1361 | yes | `4018aaa62309df6c…` |
| `czr-finra-trace-12769gad2-2026-10-02-lite-full-credit-screen` | CZR | FINRA TRACE observation for Caesars Entertainment 6.00% notes due 2032, CUSIP 12769GAD2 (LITE full-credit-screen set copy) | in_hand | CP-2H | LITE_FULL_CREDIT_SCREEN | 1364 | yes | `256c646128b7b670…` |
| `czr-q2-2026-10q-lite-portfolio` | CZR | Caesars Entertainment, Inc. Form 10-Q for the quarter ended 30 June 2026 (SEC filing text extract, LITE portfolio set copy) | in_hand | CP-0, CP-L10 | LITE_PORTFOLIO_DECISION | 166976 | yes | `f369ce5f1ebeddd9…` |
| `czr-q2-2026-earnings-lite-portfolio` | CZR | Caesars Entertainment, Inc. second quarter 2026 earnings release, Exhibit 99.1, 28 July 2026 (SEC exhibit text extract, LITE portfolio set copy) | in_hand | CP-0, CP-L10 | LITE_PORTFOLIO_DECISION | 15590 | yes | `b385f76ff631243d…` |
| `fhsuhy-nport-2026-06-30` | Federated Hermes Sustainable High Yield Bond Fund, Inc. | Federated Hermes Sustainable High Yield Bond Fund, Inc. N-PORT schedule of investments at 30 June 2026 (SEC exhibit text extract) | in_hand | CP-0, CP-L10 | LITE_PORTFOLIO_DECISION | 49398 | yes | `e2490912d9cc6881…` |
| `fhsuhy-prospectus-sai-2026-05-26` | Federated Hermes Sustainable High Yield Bond Fund, Inc. | Federated Hermes Sustainable High Yield Bond Fund, Inc. prospectus and statement of additional information, Form 485BPOS of 26 May 2026 (SEC filing text extract) | in_hand | CP-0, CP-L10 | LITE_PORTFOLIO_DECISION | 501405 | yes | `10455d54958421c5…` |
| `test-clo-i-mandate-2026-10-02` | Test CLO I (synthetic) | SYNTHETIC test mandate: Test CLO I Ltd mandate, exposure report and compliance monitor, with the owner-adopted CZR position adaptation of 2 October 2026 (text extract) | in_hand | CP-0, CP-L10 | LITE_PORTFOLIO_DECISION | 10979 | yes | `864ee90ab21372bc…` |
| `czr-finra-trace-12769gac4-2026-10-02-lite-portfolio` | CZR | FINRA TRACE observation for Caesars Entertainment 6.50% notes due 2032, CUSIP 12769GAC4 (LITE portfolio set copy) | in_hand | CP-0, CP-L10 | LITE_PORTFOLIO_DECISION | 1361 | yes | `4018aaa62309df6c…` |
| `czr-2024-650-notes-2032-indenture-lite-portfolio` | CZR | Caesars Entertainment, Inc. Indenture for the 6.500% Senior Secured Notes due 2032, dated 6 February 2024, U.S. Bank Trust Company, N.A. as trustee (SEC exhibit text extract, LITE portfolio set copy) | in_hand | CP-0, CP-L10 | LITE_PORTFOLIO_DECISION | 758385 | yes | `0809ab3981090bd2…` |
| `czr-2024-650-notes-2032-first-supplemental-indenture-lite-portfolio` | CZR | Caesars Entertainment, Inc. First Supplemental Indenture dated 1 March 2024 to the Indenture for the 6.500% Senior Secured Notes due 2032 (SEC exhibit text extract, LITE portfolio set copy) | in_hand | CP-0, CP-L10 | LITE_PORTFOLIO_DECISION | 11774 | yes | `0af4615b9a52e91e…` |
| `czr-2024-650-notes-2032-second-supplemental-indenture-lite-portfolio` | CZR | Caesars Entertainment, Inc. Second Supplemental Indenture dated 23 August 2024 to the Indenture for the 6.500% Senior Secured Notes due 2032 (SEC exhibit text extract, LITE portfolio set copy) | in_hand | CP-0, CP-L10 | LITE_PORTFOLIO_DECISION | 15684 | yes | `3621f08611f4c6a6…` |
| `czr-q2-2026-10q-portfolio` | CZR | Caesars Entertainment, Inc. Form 10-Q for the quarter ended 30 June 2026 (SEC filing text extract, FULL portfolio set copy) | in_hand | CP-0, CP-1, CP-2, CP-4, CP-5 | PORTFOLIO_DECISION | 166976 | yes | `f369ce5f1ebeddd9…` |
| `czr-fy2025-10k-portfolio` | CZR | Caesars Entertainment, Inc. FY2025 Form 10-K (SEC filing text extract, FULL portfolio set copy) | in_hand | CP-0, CP-2 | PORTFOLIO_DECISION | 405745 | yes | `172309048af2a6a2…` |
| `fhsuhy-nport-2026-06-30-portfolio` | Federated Hermes Sustainable High Yield Bond Fund, Inc. | Federated Hermes Sustainable High Yield Bond Fund, Inc. N-PORT schedule of investments at 30 June 2026 (SEC exhibit text extract) | in_hand | CP-0, CP-6 | PORTFOLIO_DECISION | 49398 | yes | `e2490912d9cc6881…` |
| `fhsuhy-prospectus-sai-2026-05-26-portfolio` | Federated Hermes Sustainable High Yield Bond Fund, Inc. | Federated Hermes Sustainable High Yield Bond Fund, Inc. prospectus and statement of additional information, Form 485BPOS of 26 May 2026 (SEC filing text extract) | in_hand | CP-0, CP-6 | PORTFOLIO_DECISION | 501405 | yes | `10455d54958421c5…` |
| `czr-2024-credit-agreement-incremental-assumption-no3-portfolio` | CZR | Caesars Entertainment, Inc. Incremental Assumption Agreement No. 3 dated 6 February 2024, JPMorgan Chase Bank, N.A. as administrative agent, with Exhibit A, the Credit Agreement dated 20 July 2020 conformed through it (SEC exhibit text extract, FULL portfolio set copy) | in_hand | CP-4 | PORTFOLIO_DECISION | 1077810 | yes | `25bea1d14fd9bb22…` |
| `czr-2024-650-notes-2032-indenture-portfolio` | CZR | Caesars Entertainment, Inc. Indenture for the 6.500% Senior Secured Notes due 2032, dated 6 February 2024, U.S. Bank Trust Company, N.A. as trustee (SEC exhibit text extract, FULL portfolio set copy) | in_hand | CP-4 | PORTFOLIO_DECISION | 758385 | yes | `0809ab3981090bd2…` |
| `czr-2024-650-notes-2032-first-supplemental-indenture-portfolio` | CZR | Caesars Entertainment, Inc. First Supplemental Indenture dated 1 March 2024 to the Indenture for the 6.500% Senior Secured Notes due 2032 (SEC exhibit text extract, FULL portfolio set copy) | in_hand | CP-4 | PORTFOLIO_DECISION | 11774 | yes | `0af4615b9a52e91e…` |
| `czr-2024-650-notes-2032-second-supplemental-indenture-portfolio` | CZR | Caesars Entertainment, Inc. Second Supplemental Indenture dated 23 August 2024 to the Indenture for the 6.500% Senior Secured Notes due 2032 (SEC exhibit text extract, FULL portfolio set copy) | in_hand | CP-4 | PORTFOLIO_DECISION | 15684 | yes | `3621f08611f4c6a6…` |
| `czr-finra-trace-12769gac4-2026-10-02-portfolio` | CZR | FINRA TRACE observation for Caesars Entertainment 6.50% notes due 2032, CUSIP 12769GAC4 (FULL portfolio set copy) | in_hand | CP-3D, CP-3, CP-6 | PORTFOLIO_DECISION | 1361 | yes | `4018aaa62309df6c…` |
| `czr-finra-trace-12769gad2-2026-10-02-portfolio` | CZR | FINRA TRACE observation for Caesars Entertainment 6.00% notes due 2032, CUSIP 12769GAD2 (FULL portfolio set copy) | in_hand | CP-3D, CP-3 | PORTFOLIO_DECISION | 1364 | yes | `256c646128b7b670…` |
| `test-clo-i-mandate-2026-10-02-portfolio` | Test CLO I (synthetic) | SYNTHETIC test mandate: Test CLO I Ltd mandate, exposure report and compliance monitor, with the owner-adopted CZR position adaptation of 2 October 2026 (text extract, FULL portfolio set copy) | in_hand | CP-0, CP-6 | PORTFOLIO_DECISION | 10979 | yes | `864ee90ab21372bc…` |
| `czr-q2-2026-10q-full-credit-assessment` | CZR | Caesars Entertainment, Inc. Form 10-Q for the quarter ended 30 June 2026 (SEC filing text extract, FULL credit-assessment set copy) | in_hand | CP-0, CP-1, CP-2, CP-2E, CP-4, CP-2D, CP-3C, CP-4C, CP-5 | FULL_CREDIT_ASSESSMENT | 166976 | yes | `f369ce5f1ebeddd9…` |
| `czr-fy2025-10k-full-credit-assessment` | CZR | Caesars Entertainment, Inc. FY2025 Form 10-K (SEC filing text extract, FULL credit-assessment set copy) | in_hand | CP-0, CP-1B, CP-2 | FULL_CREDIT_ASSESSMENT | 405745 | yes | `172309048af2a6a2…` |
| `czr-q2-2026-earnings-full-credit-assessment` | CZR | Caesars Entertainment, Inc. second quarter 2026 earnings release, Exhibit 99.1, 28 July 2026 (SEC exhibit text extract, FULL credit-assessment set copy) | in_hand | CP-0, CP-1B | FULL_CREDIT_ASSESSMENT | 15590 | yes | `b385f76ff631243d…` |
| `fhsuhy-nport-2026-06-30-full-credit-assessment` | Federated Hermes Sustainable High Yield Bond Fund, Inc. | Federated Hermes Sustainable High Yield Bond Fund, Inc. N-PORT schedule of investments at 30 June 2026 (SEC exhibit text extract) | in_hand | CP-6 | FULL_CREDIT_ASSESSMENT | 49398 | yes | `e2490912d9cc6881…` |
| `fhsuhy-prospectus-sai-2026-05-26-full-credit-assessment` | Federated Hermes Sustainable High Yield Bond Fund, Inc. | Federated Hermes Sustainable High Yield Bond Fund, Inc. prospectus and statement of additional information, Form 485BPOS of 26 May 2026 (SEC filing text extract) | in_hand | CP-6 | FULL_CREDIT_ASSESSMENT | 501405 | yes | `10455d54958421c5…` |
| `czr-2024-credit-agreement-incremental-assumption-no3-full-credit-assessment` | CZR | Caesars Entertainment, Inc. Incremental Assumption Agreement No. 3 dated 6 February 2024, JPMorgan Chase Bank, N.A. as administrative agent, with Exhibit A, the Credit Agreement dated 20 July 2020 conformed through it (SEC exhibit text extract, FULL credit-assessment set copy) | in_hand | CP-4 | FULL_CREDIT_ASSESSMENT | 1077810 | yes | `25bea1d14fd9bb22…` |
| `czr-2024-credit-agreement-fourth-amendment-full-credit-assessment` | CZR | Caesars Entertainment, Inc. Fourth Amendment to Credit Agreement dated 9 May 2024 (SEC exhibit text extract, FULL credit-assessment set copy) | in_hand | CP-4 | FULL_CREDIT_ASSESSMENT | 25431 | yes | `32f91de6ef3ff93d…` |
| `czr-2024-credit-agreement-fifth-amendment-full-credit-assessment` | CZR | Caesars Entertainment, Inc. Fifth Amendment to Credit Agreement dated 25 November 2024 (SEC exhibit text extract, FULL credit-assessment set copy) | in_hand | CP-4 | FULL_CREDIT_ASSESSMENT | 38797 | yes | `7f2b5c777dc33479…` |
| `czr-2024-650-notes-2032-indenture-full-credit-assessment` | CZR | Caesars Entertainment, Inc. Indenture for the 6.500% Senior Secured Notes due 2032, dated 6 February 2024, U.S. Bank Trust Company, N.A. as trustee (SEC exhibit text extract, FULL credit-assessment set copy) | in_hand | CP-4, CP-3C | FULL_CREDIT_ASSESSMENT | 758385 | yes | `0809ab3981090bd2…` |
| `czr-2024-650-notes-2032-first-supplemental-indenture-full-credit-assessment` | CZR | Caesars Entertainment, Inc. First Supplemental Indenture dated 1 March 2024 to the Indenture for the 6.500% Senior Secured Notes due 2032 (SEC exhibit text extract, FULL credit-assessment set copy) | in_hand | CP-4, CP-3C | FULL_CREDIT_ASSESSMENT | 11774 | yes | `0af4615b9a52e91e…` |
| `czr-2024-650-notes-2032-second-supplemental-indenture-full-credit-assessment` | CZR | Caesars Entertainment, Inc. Second Supplemental Indenture dated 23 August 2024 to the Indenture for the 6.500% Senior Secured Notes due 2032 (SEC exhibit text extract, FULL credit-assessment set copy) | in_hand | CP-4, CP-3C | FULL_CREDIT_ASSESSMENT | 15684 | yes | `3621f08611f4c6a6…` |
| `czr-2026-merger-8k-full-credit-assessment` | CZR | Caesars Entertainment, Inc. Form 8-K, Item 1.01, Agreement and Plan of Merger with Fertitta Gaming Holdco, LLC, 27 May 2026 (SEC filing text extract, FULL credit-assessment set copy) | in_hand | CP-1A | FULL_CREDIT_ASSESSMENT | 30809 | yes | `6808734cfbb19b56…` |
| `czr-2026-merger-press-release-full-credit-assessment` | CZR | Caesars Entertainment, Inc. press release announcing the Fertitta Entertainment merger agreement, Exhibit 99.1, 28 May 2026 (SEC exhibit text extract, FULL credit-assessment set copy) | in_hand | CP-1A, CP-3C | FULL_CREDIT_ASSESSMENT | 19048 | yes | `4fbecbd5f5a10b15…` |
| `czr-2026-merger-agreement-full-credit-assessment` | CZR | Caesars Entertainment, Inc. Agreement and Plan of Merger with Fertitta Gaming Holdco, LLC, Exhibit 2.1 to the Form 8-K of 28 May 2026 (SEC exhibit text extract) | in_hand | CP-1A, CP-3C, CP-4 | FULL_CREDIT_ASSESSMENT | 411229 | yes | `e01077c1ed37c5b0…` |
| `mgm-q2-2026-earnings-full-credit-assessment` | MGM | MGM Resorts International second quarter 2026 earnings release, Exhibit 99.1, 29 July 2026 (SEC exhibit text extract, FULL credit-assessment set copy) | in_hand | CP-1C | FULL_CREDIT_ASSESSMENT | 29214 | yes | `795ac68aa1c51a7e…` |
| `penn-q2-2026-earnings-full-credit-assessment` | PENN | PENN Entertainment, Inc. second quarter 2026 earnings release, Exhibit 99.1, 6 August 2026 (SEC exhibit text extract, FULL credit-assessment set copy) | in_hand | CP-1C | FULL_CREDIT_ASSESSMENT | 33608 | yes | `4d12fff94b066f73…` |
| `czr-finra-trace-12769gac4-2026-10-02-full-credit-assessment` | CZR | FINRA TRACE observation for Caesars Entertainment 6.50% notes due 2032, CUSIP 12769GAC4 (FULL credit-assessment set copy) | in_hand | CP-2H, CP-3D, CP-3, CP-6 | FULL_CREDIT_ASSESSMENT | 1361 | yes | `4018aaa62309df6c…` |
| `czr-finra-trace-12769gad2-2026-10-02-full-credit-assessment` | CZR | FINRA TRACE observation for Caesars Entertainment 6.00% notes due 2032, CUSIP 12769GAD2 (FULL credit-assessment set copy) | in_hand | CP-2H, CP-3D | FULL_CREDIT_ASSESSMENT | 1364 | yes | `256c646128b7b670…` |
| `mgm-finra-trace-552953ck5-2026-10-02-full-credit-assessment` | MGM | FINRA TRACE observation for MGM Resorts International 6.125% notes due 2029, CUSIP 552953CK5 (FULL credit-assessment set copy) | in_hand | CP-3 | FULL_CREDIT_ASSESSMENT | 1277 | yes | `e17cea1bb90debde…` |
| `penn-finra-trace-707569av1-2026-10-02-full-credit-assessment` | PENN | FINRA TRACE observation for PENN Entertainment 4.125% notes due 2029, CUSIP 707569AV1 (FULL credit-assessment set copy) | in_hand | CP-3 | FULL_CREDIT_ASSESSMENT | 1354 | yes | `666c0f36ace32336…` |
| `test-clo-i-mandate-2026-10-02-full-credit-assessment` | Test CLO I (synthetic) | SYNTHETIC test mandate: Test CLO I Ltd mandate, exposure report and compliance monitor, with the owner-adopted CZR position adaptation of 2 October 2026 (text extract, FULL credit-assessment set copy) | in_hand | CP-0, CP-6 | FULL_CREDIT_ASSESSMENT | 10979 | yes | `864ee90ab21372bc…` |
| `answer-key-3issuer` | CCL, BA, F | ANSWER_KEY_3ISSUER.md — human-authored core facts, derived values and 24 traps per issuer | **key source, never admitted** | — | — | — | — | — |
<!-- /emitted -->

One hundred and sixty documents: one hundred and fifty-five `in_hand`,
four `to_source`, and one `to_author`; plus one key source. One hundred and
eleven of the one hundred and fifty-five in hand are byte-identical route-local
copies of already admitted evidence: eleven from the earlier sets, nineteen added
for the Phase 2 route inventory, and eighty-one in the CZR earnings-update, liquidity,
FULL and LITE covenant-refinancing, FULL and LITE relative-value, LITE
full-credit-screen, FULL and LITE portfolio, and FULL credit-assessment sets.
Fifteen more are the documents admitted on 2 October 2026: the three CZR Q2
2026 filings (`czr-2026q2`), the Fourth and Fifth Amendments, the 6.50% 2032
notes indenture, and the merger 8-K and its press release
(`czr-2026q2-covenant-refinancing`), the MGM and PENN Q2 2026 earnings
releases (`czr-2026q2-lite-relative-value`), the four FINRA TRACE
observations of the CZR, MGM and PENN notes (`czr-2026q2-relative-value`), and
the SYNTHETIC Test CLO I mandate (`test-clo-i-mandate-2026-10-02`,
`czr-2026q2-lite-portfolio`), owner-adopted test input that may never ground a
real decision (D80); since 6 October 2026 (D115) it is registered but unused:
the real fund's N-PORT schedule and prospectus replace it in all three
portfolio sets, and no set names it. Eleven more are the files the owner
approved on 6 October 2026 (D115, F541, F542): the full Merger Agreement
(`czr-2026-merger-agreement` and its copies in five sets) and the Federated
Hermes Sustainable High Yield Bond Fund's N-PORT schedule and its prospectus
and SAI (`fhsuhy-nport-2026-06-30`, `fhsuhy-prospectus-sai-2026-05-26` and
their copies in three sets). Three more are the legal exhibits admitted on 5 October
2026 on the owner's ruling (F508), first in `czr-2026q2-covenant-refinancing`:
Incremental Assumption Agreement No. 3, whose Exhibit A is the credit agreement
conformed through it, and the 2032 notes' First and Second Supplemental
Indentures. The 2020 credit agreement admitted on 2 October 2026
(`czr-2026q2-liquidity`) is no longer carried: the conformed copy replaces it
in every set that held it (F508). The on-disk
loader requires those copies because it refuses a declared path resolving
outside its set root. Two more, `cp-dr-research-brief` and
`cp-dr-full-research-brief`, are the
deep-research set manifests: each brief is its manifest's `research_brief`
object, so the measured bytes are the whole manifest. The two cruise peer releases
(`rcl-q4-2025-earnings`, `nclh-q4-2025-earnings`) replace the former
`cruise-peer-pack` row. A blank measurement means the document is not in the
tree: only a file under `qualification/` is
measured, so the table is the same on every machine. `ba-fy2025-10k` and
`f-fy2025-10k` are in the tree since §98 (`qualification/ba-fy2025/`,
`qualification/f-fy2025/`), and their `fits ceiling` is **no**: neither reaches
a prompt whole, which is what page-level selection is for (**Size** below).

## Sourcing status

The coordinator records exact official URLs only after verifying them. The
19 September evidence tranche closed the public-source rows for executed debt
documents, a dated rating action, a limited TRACE observation, and a distressed
issuer pack. What remains needs private owner data or a real prior decision.

1. ~~**`ba-fy2025-10k`, `f-fy2025-10k` — copy in from the owner's document register.**~~
   Done on 18 September 2026 (§98): copied byte-for-byte into
   `qualification/ba-fy2025/documents/` and `qualification/f-fy2025/documents/`,
   digests verified on copy, under a large-file hook exclusion naming exactly
   those two paths. The original item:
   Both are already held, read-only, at
   `/Users/ericguei/Documents/Co-Pilot Agents/assessment_3issuer_20260719/corpus/`,
   with their raw HTML and SEC XBRL company facts in `raw/` beside them. This
   repository has not copied them. The coordinator admits each under its own
   digest (`0446b367…` and `97a38bc1…` as measured on 17 September 2026) and
   records the provenance in the receiving set's `RESULT.md` header. Neither
   fits the request ceiling; see **Size** below. The folder was renamed from
   `document register/` to `corpus/` after it was recorded; both digests were
   re-measured there on 18 September 2026 and are unchanged. They stay out of
   the tree until per-node evidence selection (§88.2, with the vendor) can run
   them: before that a copy frees no work, and at 1.1 and 1.8 MB each would
   need an exemption from the large-file hook.
2. ~~**Executed CCL and BA debt documents.**~~ Sourced from official SEC
   exhibits on 19 September 2026. CCL now has its $4.5 billion revolver and
   5.75% 2030 notes indenture; BA has its 2003 base indenture, 2024 supplement,
   and 2025 364-day credit agreement. These close the public document-gate
   request; they do not assert that each issuer's entire capital structure is
   represented. The CCL revolver and Spirit RSA/Plan exceed 500 KiB, so the
   large-file hook names those two original paths and each of the four
   byte-identical Phase 2 route-local copies exactly; no directory-wide
   evidence exclusion was added.

   FP-29 (24 September 2026): the BA three were held under
   `qualification/ba-fy2025-covenant-refinancing/`, which never carried a
   financial-statements document. Every covenant-refinancing pathway --
   `COVENANT_REFINANCING` and `LITE_COVENANT_REFINANCING` alike -- routes
   through CP-1 or CP-L10, both of which need one, so no complete,
   honest `qualification.json` could be written for that set from the debt
   instruments alone; the same gap rules out `PORTFOLIO_DECISION` and
   `FULL_CREDIT_ASSESSMENT`. The directory was removed and the three rows
   above moved back to `to_source`.
3. ~~**A dated CCL rating action.**~~ The official Fitch 1 October 2025 rating
   disclosure is in hand. Current criteria and a complete cross-agency history
   are not, so CP-2H must retain those limitations.
4. ~~**A dated market observation.**~~ The official FINRA page for CUSIP
   143658BY7 was transcribed at `2026-09-19T16:51:57Z`. It supplies a dated last
   trade, not bid/mid/ask, an evaluated price, spreads, or a full curve. It can
   support a deliberately restricted market analysis, not a complete CP-3D
   market pack.
5. ~~**`cruise-peer-pack` — the peers' own FY2025 filings.**~~ Sourced on 18
   September 2026 as `rcl-q4-2025-earnings` and `nclh-q4-2025-earnings` (Task
   9.2), by the coordinator under the owner's authorization "web search for
   equivalent versions to test": the other two listed major cruise operators'
   FY2025 earnings releases, as text extracts. The peer choice is the
   coordinator's recommendation applied under that instruction, not a peer set
   CP-1C derived; the owner may replace it. CP-1C's steps 0 and 1 are a Peer
   Discovery Gate and a Peer Data Gate, so each peer figure it benchmarks has
   to be citable -- which is why each release is admitted whole rather than
   summarised into a table.
6. **`ccl-decision-record` — an owner-authored decision record (to author).**
   CP-8 is explicit: *"Blocked: No decision record available to attribute.
   STOP — do not reconstruct a thesis after the fact."* So it must be a real,
   dated record from before the outcome window. A public rating-action news
   report was admitted as a stand-in on 18 September 2026 and removed the same
   day on the owner's instruction not to include the third-party excerpt;
   `LITE_DECISION_LEDGER` stays enabled on its contract and route tests, and
   has no qualification set until a memo exists.
7. **`cp-dr-research-brief` — implementer-authored research briefs (in
   hand).** Materialized from
   `vendor/deploy-v/skills/cp-os-credit-os/references/CP_DR_RESEARCH_BRIEF_V1.md`
   by the Task 9.4 implementer for the VMO2 releases, in place of an
   owner-authored one: the owner asked for equivalent versions to test with and
   the coordinator recommended authoring, because a brief is a run control the
   host pins rather than evidence. It declares `supplied_only`, which the pin
   now requires (invariant 1: CP-DR's capability gate blocks `web_only` and
   `hybrid` when web research is unavailable, and here that is structural). Its
   three questions -- two the Q4 release answers, one neither release can --
   were owner-confirmed for the historical LITE run. The FULL set reuses the
   brief but remains unconfirmed for a FULL run; no new verdict may be signed
   over it without that confirmation.
8. ~~**A distressed issuer pack.**~~ The official Spirit Airlines 18 November
   2024 Chapter 11 8-K and the RSA with its attached Joint Chapter 11 Plan are
   in hand. The separate backstop agreement was not admitted because these two
   documents already establish the distress trigger and plan evidence needed
   for the smallest honest CP-4C qualification pack.
9. ~~**A second public issuer, with peers.**~~ The public-issuer part is closed
   by the 2 October 2026 CZR tranche; the real portfolio mandate is not (see
   below). **Source:** eleven official SEC EDGAR documents (Caesars
   Entertainment's FY2025 10-K, Q2 2026 10-Q and earnings release, the 2020
   credit agreement with its Fourth and Fifth Amendments, the 6.50% 2032 notes
   indenture, the 27 May 2026 merger 8-K and its press release, and the MGM
   and PENN Q2 2026 earnings releases), fetched on 2 October 2026 with the SEC
   CDN's injected script tag stripped, each matching the size in its filing's
   `index.json`, converted from HTML to plain text the same day; and four FINRA
   TRACE observations transcribed from the official public pages that day.
   Each set's `RESULT.md` records every URL, accession, raw and text SHA-256.
   **The owner's choices:** CZR, with peers MGM and PENN, from the owner's
   "Public Leveraged Loan Issuers Benchmark" (FYBR excluded: it no longer
   files); the synthetic "Test CLO I" mandate adapted to carry a CZR position,
   labelled SYNTHETIC everywhere and never to ground a real decision (D80). It
   is owner-adopted test input and does not close the real-portfolio row
   `ccl-portfolio-mandate-exposures`, which stays `to_source`; no
   CZR rating action, so CP-2H runs restricted on FINRA's displayed ratings and
   last-rated dates; and an analysis date of 2026-10-02 for every case.
   **SEC fair access:** SEC asks every automated request to declare a
   User-Agent naming the requester and a contact email address. That address
   is not recorded anywhere in this repository; whoever re-fetches supplies
   their own. **What remains:** `DECISION_LEDGER` and `LITE_DECISION_LEDGER`
   still need a real, dated decision record (to author, item 6), and CZR is not
   a distressed issuer, so the two distressed pathways keep only the Spirit
   sets (item 8); a distressed issuer's pack beyond Spirit remains to source. The real
   portfolio mandate (`ccl-portfolio-mandate-exposures`) also remains to
   source; the synthetic mandate stands in for tests only. **Owner approval of
   6 October 2026 (D115):** the full Merger Agreement (Ex. 2.1 to the 8-K of
   28 May 2026) joins five CZR sets, and Federated Hermes Sustainable High
   Yield Bond Fund, Inc.'s N-PORT schedule at 30 June 2026 and its 485BPOS
   prospectus and SAI replace the synthetic mandate in the three portfolio
   sets: real holdings (it holds four Caesars positions) and real policies, but
   no CLO mandate and no limits on a single name. The synthetic file stays in
   the sets' directories and the register, unused.
   `DEEP_RESEARCH` still waits on the owner's confirmation of its FULL brief
   (item 7), and the CZR portfolio sets' eligible-security universe is owner
   content (N127).

## Route qualification inventory

This is an input inventory, not a verdict table. `offline` means a loadable,
digested set exists but has no current performed evidence or signed verdict;
`blocked set` means the case deliberately measures CP-0 refusing unsupported
work. A route with no set remains enabled and deterministically tested, but is
not qualified.

| Profile | Pathway | Set or explicit reason | Phase 2 state |
|---|---|---|---|
| `FULL_CREDIT_32` | `COVENANT_REFINANCING` | `ccl-fy2025-covenant-refinancing`, `czr-2026q2-covenant-refinancing` | offline |
| `FULL_CREDIT_32` | `DECISION_LEDGER` | No genuine dated T0 decision record; retrospective reconstruction is prohibited | no set / owner input |
| `FULL_CREDIT_32` | `DEEP_RESEARCH` | `vmo2-fy2025-full-deep-research`; FULL brief confirmation outstanding | offline / owner confirmation |
| `FULL_CREDIT_32` | `DISTRESSED_RESTRUCTURING` | `save-2024-distressed-restructuring` | blocked set |
| `FULL_CREDIT_32` | `EARNINGS_UPDATE` | `ccl-fy2025-earnings-update`, `czr-2026q2-earnings-update` | offline |
| `FULL_CREDIT_32` | `FULL_CREDIT_ASSESSMENT` | `czr-2026q2-full-credit-assessment`, over a real fund's N-PORT schedule and prospectus (D115; the synthetic mandate of D80 is unused); no eligible-security universe (N127) | offline, restricted |
| `FULL_CREDIT_32` | `LIQUIDITY_REVIEW` | `ccl-fy2025-liquidity`, `czr-2026q2-liquidity` | offline |
| `FULL_CREDIT_32` | `MARKET_DISLOCATION` | `ccl-fy2025-market-dislocation` | offline, market-restricted |
| `FULL_CREDIT_32` | `PORTFOLIO_DECISION` | `czr-2026q2-portfolio`, over a real fund's N-PORT schedule and prospectus (D115; the synthetic mandate of D80 is unused); no eligible-security universe (N127) | offline, market-restricted |
| `FULL_CREDIT_32` | `RELATIVE_VALUE` | `ccl-fy2025-full-relative-value`, `czr-2026q2-relative-value` | offline, market-restricted |
| `LITE_CREDIT_22` | `LITE_COVENANT_REFINANCING` | `ccl-fy2025-lite-covenant-refinancing`, `czr-2026q2-lite-covenant-refinancing` | offline |
| `LITE_CREDIT_22` | `LITE_DECISION_LEDGER` | No genuine dated T0 decision record; retrospective reconstruction is prohibited | no set / owner input |
| `LITE_CREDIT_22` | `LITE_DEEP_RESEARCH` | `vmo2-fy2025-deep-research` | retained historical run; current release status is store-derived |
| `LITE_CREDIT_22` | `LITE_DISTRESSED_RESTRUCTURING` | `save-2024-lite-distressed-restructuring` | blocked set |
| `LITE_CREDIT_22` | `LITE_EARNINGS_UPDATE` | `vmo2-fy2025`, `ccl-fy2025`, `ba-fy2025`, `f-fy2025`, `czr-2026q2` | current VMO2 and CZR sets offline; historical runs retained |
| `LITE_CREDIT_22` | `LITE_FULL_CREDIT_SCREEN` | `ccl-fy2025-lite-full-credit-screen`, `czr-2026q2-lite-full-credit-screen` | offline, restricted |
| `LITE_CREDIT_22` | `LITE_PORTFOLIO_DECISION` | `ccl-fy2025-portfolio`, `vmo2-fy2025-portfolio`, `czr-2026q2-lite-portfolio` (a real fund's N-PORT schedule and prospectus, D115) | blocked and historical-run cases retained; CZR set offline |
| `LITE_CREDIT_22` | `LITE_RELATIVE_VALUE` | `ccl-fy2025-relative-value`, `czr-2026q2-lite-relative-value` | historical runs retained; CZR set offline; no signed verdict |

## Size

`MAX_REQUEST_BYTES` is **1,048,576** (`server/provider.py`), and it bounds the
*whole encoded request* — model, parameters, the module's delivered authority
files, every upstream record, and the evidence — not the document alone. So a
document comfortably under the ceiling can still put a wide route's prompt over
it, and `CONTEXT_OVER_CEILING` refuses before any attempt, reservation or call.

The `bytes` column is the document's own bytes on disk. For the two PDFs that
is the file, which overstates what reaches a prompt: the pinned extractor
yields 38,360 bytes of text from the Q3 release and 51,942 from Q4 (measured
with the vendored pdfminer). For the `.txt` extracts the file *is* the text.

| Document | Bytes reaching a prompt | Fits alone |
|---|---|---|
| `vmo2-q3-2025-earnings` | 38,360 (extracted text) | yes, with ample room |
| `vmo2-q4-2025-earnings` | 51,942 (extracted text) | yes, with ample room |
| `ccl-fy2025-10k` | 311,896 | yes — 30% of the ceiling |
| `ba-fy2025-10k` | 905,758 of block text (1,177,234 on disk) | **no** — whole, with CP-0's authority, past the ceiling |
| `f-fy2025-10k` | 1,435,471 of block text (1,922,743 on disk) | **no** — 137% of the ceiling in text alone |

Which pathway tasks may run before per-node evidence selection exists:

- **VMO2 (two releases, ~90 KB of text together)** — any pathway whose nodes
  are served by earnings releases. The LITE earnings route already has a
  complete live snapshot here.
- **CCL (312 KB)** — runnable whole today, with roughly 700 KB left for
  authority files and upstream records. That headroom shrinks with every node
  on the route, so the long routes (`FULL_CREDIT_ASSESSMENT`'s 19 nodes) are
  the ones to measure rather than assume.
- **BA and F** — not runnable whole, and since §98 runnable by page. The gate
  is shown each as its page map (the leading lines of every fixed-pitch page:
  16 of 108 pages' lines for BA, 10 of 146 for F, measured), and names in T8
  the pages each consumer is handed. Measured on the LITE earnings route: the
  gate's whole request, and a consumer handed the statements' pages, both fit
  the ceiling (`tests/test_large_documents.py`); the whole document named
  whole still refuses `CONTEXT_OVER_CEILING`, as it must. None of this has met
  a live model: whether a real CP-0 names useful pages from a map of a page's
  first lines is unmeasured.

## The key source

`ANSWER_KEY_3ISSUER.md` (8,268 bytes, as of 19 July 2026) holds the owner's
independent reading of the three 10-Ks: core facts, derived values and 24 traps
per issuer. It is a **key source** — a qualification set's `expects` rows may
be authored from it — and it is **never an admitted document**. Admitting it
would put the answers inside the evidence the modules read, and a key measured
against a document register that contains the key measures nothing. It has no row in the
documents table for exactly that reason; the script emits it in its own line,
labelled.

One thing it cannot do: `ExpectedCitation` is
`(module_id, document_sha256, matched_text)`, so a key's derived values and
traps become citation expectations, not value comparisons. The known-gaps
ledger entry "An answer key names citations, not figures" is the standing
statement of that limit, and it applies to every key authored from this
document.

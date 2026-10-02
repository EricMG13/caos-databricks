# CZR qualification corpus — implementation plan (2 October 2026)

**Goal.** Admit an owner-approved public corpus for Caesars Entertainment (CZR) and two peers (MGM, PENN), plus an owner-adopted synthetic portfolio mandate. Build one qualification set per remaining pathway that public evidence can serve. No live model run happens in this plan.

**Spec / authority.**
- `qualification/DOCUMENTS.md` (the document register and its rules).
- `docs/rebuild/2026-09-22-caos-databricks-spec.md` (the app).
- The repo `CLAUDE.md` invariants: pinned sources only, citations coordinate-anchored or refused, and the bundle under `vendor/` is never edited.

## Owner decisions (2 October 2026, binding)

- **Issuer pack:** CZR plus peers MGM and PENN, from the owner's "Public Leveraged Loan Issuers Benchmark". FYBR is excluded (no longer files).
- **Mandate:** adopt the synthetic "Test CLO I" mandate from `/Users/ericguei/Documents/Co-Pilot Agents/Co-Pilot Agents/CP-6A/REF_CP-6A_Portfolio_Debate_Inputs.xlsx`, adapted to carry a CZR position.
- **Out of scope:**
  - `DECISION_LEDGER` and `LITE_DECISION_LEDGER` need a real decision record.
  - The two distressed pathways need a distressed issuer, which CZR is not.
  - `DEEP_RESEARCH` needs the owner to confirm its brief.
  - `MARKET_DISLOCATION` is already qualified.
- **No CZR rating action:** CP-2H runs restricted. FINRA's displayed ratings and their last-rated dates are the only rating evidence.
- **analysis_date:** `2026-10-02` for every new case.

## Corpus (already fetched; do not re-fetch)

Raw files sit under `$S/edgar/raw/`, where `S=/private/tmp/claude-501/-Users-ericguei-Documents-caos-databricks/04e63e72-b02c-46a5-a89e-286c3020d16f/scratchpad`. Each matches SEC's `index.json` size exactly; SHA-256s are in `$S/edgar/raw/SHA256SUMS`. All were fetched 2026-10-02 with the SEC CDN's injected script tag stripped. The source URL is `https://www.sec.gov/Archives/edgar/data/<cik>/<accession-no-dashes>/<file>`.

| file | cik | accession | what |
|---|---|---|---|
| `czr-20251231.htm` | 1590895 | 0001590895-26-000011 | CZR FY2025 Form 10-K (filed 2026-02-17) |
| `czr-20260630.htm` | 1590895 | 0001590895-26-000028 | CZR Q2 2026 Form 10-Q (filed 2026-07-28) |
| `ex991-2026q2ceiearningsrel.htm` | 1590895 | 0001590895-26-000027 | CZR Q2 2026 earnings release, Ex. 99.1 (2026-07-28) |
| `d940333dex101.htm` | 1590895 | 0001193125-20-196232 | Credit Agreement dated 20 July 2020 (JPMorgan, administrative agent) |
| `d827488dex101.htm` | 1590895 | 0001193125-24-135268 | Fourth Amendment to Credit Agreement, 9 May 2024 |
| `d858083dex101.htm` | 1590895 | 0001193125-24-265157 | Fifth Amendment to Credit Agreement, 25 Nov 2024 |
| `d739529dex101.htm` | 1590895 | 0001193125-24-026847 | Indenture, 6.50% Senior Secured Notes due 2032, 6 Feb 2024 |
| `d143382d8k.htm` | 1590895 | 0001193125-26-242995 | 8-K Item 1.01: merger agreement with Fertitta Gaming, 27 May 2026 |
| `d143382dex991.htm` | 1590895 | 0001193125-26-242995 | Ex. 99.1 press release for that 8-K |
| `mgmex991q22026earningrelea.htm` | 789570 | 0000789570-26-000075 | MGM Q2 2026 earnings release, Ex. 99.1 (2026-07-29) |
| `pennex991-q22026.htm` | 921738 | 0000921738-26-000019 | PENN Q2 2026 earnings release, Ex. 99.1 (2026-08-06) |

The TRACE observations are already plain text under `$S/edgar/trace/`, in the same format as `qualification/ccl-fy2025-market-dislocation/documents/CCL_FINRA_TRACE_143658BY7_2026-09-19.txt`:
- `CZR_FINRA_TRACE_12769GAC4_2026-10-02.txt` (6.50% 2032 secured)
- `CZR_FINRA_TRACE_12769GAD2_2026-10-02.txt` (6.00% 2032 unsecured)
- `MGM_FINRA_TRACE_552953CK5_2026-10-02.txt`
- `PENN_FINRA_TRACE_707569AV1_2026-10-02.txt`

Admit them byte for byte.

## Global constraints (every task)

- Work only in the worktree `$S/wt-czr` (branch `claude/czr-corpus`). Never edit `vendor/`.
- Use `uv run` for every tool, and `CAOS_TEST_POSTGRES_URL=postgresql://postgres:local-test-admin-only@127.0.0.1:55437/postgres` for Postgres tests.
- Commit only what the task names. No push. End every commit message with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- **One set per pathway**, in `qualification/<set>/`:
  - `documents/` holds byte-identical route-local copies; the loader refuses paths outside the set root.
  - `qualification.json` follows the closest existing set for that pathway; copy its shape, never its figures.
  - `RESULT.md` follows the existing sets' header style: provenance per document (URL, accession, SHA-256), "keys authored from the documents; material figures pending owner confirmation", and the statement that no run has been performed.
- **Every key quote** is copied from the converted text. It must pass `tests/test_qualification_on_disk.py::test_every_committed_answer_key_names_its_route_and_exact_source`: whole tokens, a unique match, one page.
  - Every key's `matched_text` is **one whole evidence line** of its page (F235, `caos/evidence/citations.py` `WHOLE_LINE`). The matrix compares keys by exact equality with accepted citations (`caos/qualification/matrix.py` `_matches`), so a fragment or a two-line key can never be met.
  - `expects_ready` lists the route's pinned consumers of CP-0 (read the route in `vendor/deploy-v/skills/cp-os-credit-os/references/CREDIT_OS_V_MODULE_CATALOG_v2.json`).
  - `expects_projection` gives `decision_scope` as the catalog pathway states it.
  - `expects_register` keys are optional. Add them only where the figure is a single unambiguous cell, and state the arithmetic in `RESULT.md`.
- **Register:**
  - Every document copy gets a row in `qualification/documents.json` (`status: in_hand`, `demand_verified`, a note saying "Official EDGAR exhibit converted from HTML to plain text on 2 October 2026" or the TRACE/mandate equivalent).
  - Then re-emit `qualification/DOCUMENTS.md` with `uv run python scripts/document_register.py --report`. Never hand-edit the emitted table.
- **Pins that must move together:**
  - Each new set's digest goes into `COMMITTED_SET_DIGESTS` in `tests/test_qualification_on_disk.py`.
  - Each new `qualification/<set>/documents/**` goes into `EXCLUSIONS` in `scripts/check_pr_size.py`.
  - Each text file over 500 KiB gets its exact path added to the `check-added-large-files` exclude in `.pre-commit-config.yaml` **and** to `_LARGE_FILES_EXCLUDE` in `scripts/check_gate_config.py`.
  - Any other pin a gate names when it fails.
- **Size:** any converted document over `MAX_REQUEST_BYTES` (4,194,304) is a BLOCKER: report it, do not admit it. Documents over 1.5 MiB reach CP-0 as a page map (`caos/methodology/selection.py`); note that in `RESULT.md`.
- **Task gates:** these must exit 0:
  - `uv run ruff check .`
  - `uv run ruff format --check .`
  - `uv run mypy caos scripts tests`
  - `CAOS_REQUIRE_POSTGRES=1 uv run pytest -n auto -m "not live_provider" tests/test_qualification_on_disk.py tests/test_document_register.py tests/test_check_gate_config.py tests/test_qualification_matrix.py tests/parity`
  - `uv run python scripts/document_register.py`
  - `uv run python scripts/check_gate_config.py`
  - `uv run python scripts/check_vocabulary.py`
  - `uv run pre-commit run --all-files`
  - `gitleaks git --no-banner`
- The last task also runs the whole CLAUDE.md gate list.
- **Ledger:** use the next free numbers, D80 and later (D78–D79 are reserved by the Copilot plan), F475 and later, and N126 and later.

## Tasks

### Task 1: Convert the corpus to text (staging only, no repo change)

Write a stdlib-only converter (no new dependency) in `$S/edgar/convert.py`. It stays outside the repo. Run it over every file in `$S/edgar/raw/` into `$S/edgar/text/`, one `.txt` per `.htm`. Use these names:

| Source | Text file |
|---|---|
| 10-K | `CZR_FY2025_10K.txt` |
| 10-Q | `CZR_Q2_2026_10Q.txt` |
| CZR release | `CZR_Q2_2026_Earnings_Release.txt` |
| `d940333dex101.htm` | `CZR_2020_Credit_Agreement.txt` |
| `d827488dex101.htm` | `CZR_2024_Credit_Agreement_Fourth_Amendment.txt` |
| `d858083dex101.htm` | `CZR_2024_Credit_Agreement_Fifth_Amendment.txt` |
| `d739529dex101.htm` | `CZR_2024_650_Senior_Secured_Notes_2032_Indenture.txt` |
| `d143382d8k.htm` | `CZR_2026_Merger_Agreement_8K.txt` |
| `d143382dex991.htm` | `CZR_2026_Merger_Press_Release.txt` |
| MGM release | `MGM_Q2_2026_Earnings_Release.txt` |
| PENN release | `PENN_Q2_2026_Earnings_Release.txt` |

**Output format.** Match the existing extracts, e.g. `qualification/ccl-fy2025/documents/CCL_FY2025_10K.txt`:
- one line per block element;
- a table row is its cells joined with ` | ` and ending ` | `;
- HTML entities decoded;
- no markup, no `<script>`/`<style>` content, no hidden inline-XBRL header (`ix:header`) content;
- whitespace inside a line collapsed;
- UTF-8, ending with one newline.

It must be deterministic (same bytes on re-run).

**Report.** Write `$S/edgar/text/MANIFEST.json` with, per file: source URL, accession, raw SHA-256, text SHA-256, text bytes. Flag files over 500 KiB, over 1.5 MiB and over 4 MiB.

**Checks.**
- Spot-check that a balance-sheet table row and a debt table row from each of the 10-K and the 10-Q read as one line each.
- Spot-check that the credit agreement's "Consolidated" definitions and the indenture's change-of-control section are present.
- Commit nothing.

### Task 2: The owner-adopted synthetic mandate (staging only)

Read the xlsx with stdlib `zipfile` + `xml.etree`. Write `$S/edgar/text/TEST_CLO_I_Mandate_and_Exposures_2026-10-02.txt` containing every sheet's content as text tables.

**Header.** It states:
- that it is a SYNTHETIC test mandate (the workbook says "packaged sample data only") that the owner adopted for CAOS qualification on 2 October 2026;
- the source path;
- that no figure in it is a real holding.

**Adaptation.** Add one clearly labelled section, "Owner-adopted test adaptation (2 October 2026)", with:
- no existing Caesars Entertainment exposure;
- a proposed position: Caesars Entertainment, Inc. 6.50% Senior Secured Notes due 2032, CUSIP 12769GAC4, par USD 5,000,000, with its weight against the workbook's stated NAV and the single-name limit it is tested against, both computed from the workbook's own figures.

**Report.** Append it to MANIFEST.json and commit nothing. If the workbook's NAV or limits are missing, report NEEDS_CONTEXT.

### Task 3: Earnings and liquidity sets

Create three sets:

| Set | Profile / selection | Documents |
|---|---|---|
| `czr-2026q2` | LITE `LITE_EARNINGS_UPDATE` | 10-K, 10-Q, CZR release |
| `czr-2026q2-earnings-update` | FULL `EARNINGS_UPDATE` | 10-K, 10-Q, CZR release |
| `czr-2026q2-liquidity` | FULL `LIQUIDITY_REVIEW` | 10-K, 10-Q, CZR release, credit agreement |

Models: `ccl-fy2025`, `ccl-fy2025-earnings-update`, `ccl-fy2025-liquidity`.

Everything per the Global constraints (copies, keys, RESULT.md, register rows, re-emitted DOCUMENTS.md, the four pins), then the task gates. One commit per set.

### Task 4: Covenant and refinancing sets

| Set | Pathway | Documents |
|---|---|---|
| `czr-2026q2-covenant-refinancing` | FULL `COVENANT_REFINANCING` | 10-K, 10-Q, credit agreement, Fourth and Fifth Amendments, the 6.50% 2032 indenture, the merger 8-K and its press release |
| `czr-2026q2-lite-covenant-refinancing` | LITE `LITE_COVENANT_REFINANCING` | 10-Q plus the same debt documents and the merger 8-K |

Models: `ccl-fy2025-covenant-refinancing` and `ccl-fy2025-lite-covenant-refinancing`.

`RESULT.md` must name the change-of-control relevance of the pending Fertitta merger as a fact the documents state (quote it). It must not draw a conclusion.

### Task 5: Relative-value sets

| Set | Pathway | Documents |
|---|---|---|
| `czr-2026q2-lite-relative-value` | LITE `LITE_RELATIVE_VALUE` | 10-Q, CZR release, credit agreement, indenture, MGM release, PENN release |
| `czr-2026q2-relative-value` | FULL `RELATIVE_VALUE` | the LITE set's documents, the 10-K, and all four TRACE observations |

Models: `ccl-fy2025-relative-value` and `ccl-fy2025-full-relative-value`.

`RESULT.md` names the comparability traps:
- the peers' different note tenors and seniority (CZR 2032 secured vs MGM/PENN 2029 unsecured);
- MGM's missing 144A label;
- that the CZR prints reflect the pending take-private.

### Task 6: Screen and LITE portfolio sets

| Set | Pathway | Documents |
|---|---|---|
| `czr-2026q2-lite-full-credit-screen` | LITE `LITE_FULL_CREDIT_SCREEN` | 10-Q, CZR release, merger 8-K and press release (CP-1A's named transaction), MGM and PENN releases, credit agreement, indenture, both CZR TRACE observations |
| `czr-2026q2-lite-portfolio` | LITE `LITE_PORTFOLIO_DECISION` | 10-Q, CZR release, the synthetic mandate, the CZR 6.50% 2032 TRACE observation |

For the screen set, the TRACE observations are CP-2H's only rating evidence; expect CP-2H restricted and say so in `RESULT.md`.

Models: `ccl-fy2025-lite-full-credit-screen` and `vmo2-fy2025-portfolio` / `ccl-fy2025-portfolio`.

In this task, also add **D80** to `docs/rebuild/decisions.md`. It records the owner's 2 October 2026 decision:
- the synthetic mandate is admitted as owner-adopted test input, labelled synthetic everywhere;
- it may never ground a real decision;
- the register row's `status` is `in_hand` with a note naming it synthetic.

### Task 7: FULL portfolio and full-credit-assessment sets

| Set | Pathway | Documents |
|---|---|---|
| `czr-2026q2-portfolio` | FULL `PORTFOLIO_DECISION` | 10-K, 10-Q, credit agreement, indenture, both CZR TRACE observations, the synthetic mandate |
| `czr-2026q2-full-credit-assessment` | FULL `FULL_CREDIT_ASSESSMENT` | every CZR document, both peer releases, all four TRACE observations, the synthetic mandate |

Also update `qualification/DOCUMENTS.md`'s hand-written "Sourcing status" prose (outside the emitted table) with one item on the 2 October 2026 CZR tranche. It covers:
- the source, the owner's choices, and the SEC User-Agent policy (no email address in the repo);
- what remains `to_source` or `to_author` (the decision record; a distressed issuer).

Add an N-item (N126) to `docs/rebuild/next.md` for the owner's confirmation of every new set's material key figures before any live run.

Then run the **whole** CLAUDE.md gate list that runs locally (the full pytest suite with coverage, scan floors, complexipy, jscpd, check_tested, io_budget, bandit floor, pip-audit, `uv lock --check`, the frontend gates only if a frontend file changed, which it should not) and report every exit code.

# Live-run fixes — implementation plan (2 October 2026)

**Goal.** Remove the root causes behind the 2 October live-run failures on the CZR sets, then run the sets one at a time. Each run stops at the first failing module (`--attempts 1`), and its fault is patched before the run goes on.

**Evidence.** The root-cause analysis is in the session scratchpad `rca/` (inventory, classifier and replay outputs). Its summary:
- `CITATION_NOT_LOCATED`: 41 citations failed. 19 were a whole sentence taken from a longer evidence line; 17 cited the wrong page (14 off by one); 9 dropped the trailing ` |` or a glued `•`/`(a)`.
- `HANDOFF_MALFORMED`: 6 had a body quote that was not verbatim (we/our turned into "the Company"); 2 had no `citations` key.
- CP-1 structure slips. The authority's `REF_CP-1_STEPS.md:282` says Evidence Trace and Source Registry are "sub-sections", while the validator needs them as H2. The vendor binds a register heading to its table only within 4 lines, and the model is never told this.
- 240 s timeouts on the default tier: 26% of its calls.
- CP-1 handoffs of 50–86 KB run over the 52 KiB upstream bound.
- A body quote wrapped in `**…**` is not carried (`caos/methodology/handoff.py:790-794`).

**Owner decision, 2 October 2026:** "Apply your recommendation to all. Run only one module at a time, and patch the faults before moving on to the next." That covers:
- **Option 1, evidence presentation:** adopted.
- **Option 2, retry feedback:** adopted. This amends N52 ("never by text") and D30 (one second attempt).
- **Option 3, limits:** adopted. `TIMEOUT_SECONDS` goes to 420 and `MAX_UPSTREAM_HANDOFF_BYTES` to 96 KiB.
- **Option 4, bundle-fork contract fixes:** adopted for the two clarity fixes only (the CP-1 sub-section contradiction and the 4-line binding rule). The owner authorises this edit under D31/D34. Restructuring CP-1's duplicate tables is not recommended and not done; the raised bound covers it.
- **Option 5, accept a whole sentence:** not applied. My recommendation was "not needed if option 1 works". Revisit only if the live loop still shows sentence fragments.
- **Within-authority fixes:** emphasis around a quote; converter cleanup and re-admission of the 11 CZR sets; run config (`:nitro`, honest price pin).

## Global constraints

- Work only in the worktree `$S/wt-fix`, on branch `claude/live-fixes` from `rebuild/databricks` at `313f13f`. `$S` is `/private/tmp/claude-501/-Users-ericguei-Documents-caos-databricks/04e63e72-b02c-46a5-a89e-286c3020d16f/scratchpad`.
- Use `uv run` for every tool. Postgres tests run with `CAOS_TEST_POSTGRES_URL=postgresql://postgres:local-test-admin-only@127.0.0.1:55437/postgres CAOS_REQUIRE_POSTGRES=1`.
- `vendor/` is edited **only** in Task 5, under the owner authorisation above, and is re-pinned there by D31's procedure.
- **Repo invariants:**
  - Typed refusals only; never `str(exc)`.
  - No document text in logs. Feedback lines inside a model prompt are prompt content, not logs.
  - Every public definition is named by a test.
  - Every `caos/api/` module declares `IO_BUDGET`.
  - No new dependency.
  - Targeted edits.
  - Suppressions may only fall (`tests/gate_baseline.json`).
- **Ledger:** use the next free numbers, D81 and later, F476 and later, N129 and later. D78–D79 stay reserved. A deliberate departure from a legacy parity golden gets an F-entry naming the group and why. Regenerate only the affected group, by the documented command.
- **Task gates:** these must exit 0:
  - `uv run ruff check .`
  - `uv run ruff format --check .`
  - `uv run mypy caos scripts tests`
  - the tests the task touches, plus `tests/parity`, run with `--no-cov`
  - `uv run python scripts/check_tested.py`
  - `uv run python scripts/check_vocabulary.py`
  - `uv run python scripts/io_budget.py --assert`
  - `uv run python scripts/check_gate_config.py`
  - `uv run python scripts/check_icm.py`
  - `uv run pre-commit run --all-files`
  - `gitleaks git --no-banner`
- The last task runs the whole CLAUDE.md gate list, including the full suite with coverage.
- **Commits:** one per task (fix commits allowed), in the repo style, ending with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. No push.

## Tasks

### Task 1: Accept Markdown emphasis around a body quote (F476)

`caos/methodology/handoff.py:790-794` (`_QUOTATION`/`_OPENING`/`_CLOSING`) carries a quote wrapped in quotation marks or backticks, but not in Markdown emphasis. `**For the period 2026**.` is refused while `"For the period 2026".` is carried. Extend the edge typography to `*`, `**`, `_` and `__`, in the same family as F148/F149.
- Add a test beside the existing quotation-mark and backtick tests in `tests/test_handoff_record.py`. It must show emphasis is carried and that an inner word changed is still refused.
- Record F476.

### Task 2: Evidence presentation the model can quote from (D81, F477)

The problem: the model never sees what "one evidence line" is. A line can be a 900-character paragraph. The `page:` header is printed once per run of up to 60 lines (a `.txt` page is 60 lines), often kilobytes above the line it covers.

1. In `caos/methodology/invocation.py` (`_evidence_section`, `_evidence_header`, `evidence_sizes`), repeat the run's header (source_id, page and hidden note) before every **8th line** of a run, counted from the run's first line. The header text and format stay unchanged.
   - Keep W3: `evidence_sizes` must still count every host byte, so a line's size is now a function of its position in its run.
   - Keep the `selection.gate_view` property: the sizes of a delivery are the sizes of any leading lines of each of its pages. That still holds because positions count from the page's run start; prove it with a test.
   - Update the docstrings. Keep the 8 in one named constant.
2. Rewrite the quoting sentence in `icm/shared/prompt/final_check.md` with one definition:
   - An evidence line is all the text between two blank lines in the evidence section. It may be a whole paragraph or a whole table row.
   - `matched_text` copies that entire line character for character, including any leading bullet or footnote marker and any trailing `|`. Never only a sentence of it.
   - `page` is the page in the nearest evidence header **above** that line.
   - Body quotes keep the source's own wording ("we", "our", "us"), never rephrased into the third person.

   Keep the template's placeholders, keep `check_icm.py` green, and update `HOST_INTEGRITY_v1.json` or the ICM manifests if they pin these bytes.
3. **Goldens.** The `prompt` parity group (and any other group whose bytes change) is a deliberate departure from legacy. Regenerate only that group from the new package by the documented command (`tests/parity/generate_goldens.py --package caos --root . --group prompt …`). Record F477 naming the departure, and D81 recording the owner's decision.
4. **Size.** Re-run the size and selection tests (`tests/test_handoff_invocation.py`, `tests/test_selection*.py`, the widest-node test) and report the added bytes on the largest CZR request. The header repeat adds about 60 bytes per 8 lines; it must not push any committed CZR route over `MAX_REQUEST_BYTES`.

### Task 3: Retry feedback that says what was wrong and allows two guided retries (D82)

- **Today:** `anchoring_line` (`handoff.py:1235-1270`) says only "citation N is not one evidence line of its cited page". N52 says "never by text". `canonical._feedback_source` allows exactly one guided second attempt (D30).
- **Owner decision:** name the reason and the line, and allow up to **two** guided retries per node.

Implement the following.
- **For `CITATION_NOT_LOCATED`, name which case applies:**
  - (a) the quote is part of a longer evidence line on its cited page: give that line's first 12 words and say "quote the whole line";
  - (b) the quote is a whole evidence line on another page delivered to this node: name that page;
  - (c) no delivered line contains it: say so.
- Use the host's own anchoring code (`caos/evidence/citations.py`, `_page_run`/ANY_RUN) to decide the case. Never guess.
- **Ambiguous and not-delivered** keep their current wording.
- **Retry allowance:** generalise `_feedback_source` and `second_attempt_due` so that a node's 2nd and 3rd attempts each carry feedback from the attempt just before them, when that attempt was refused with a `SECOND_ATTEMPT_CODES` code. The cap is two guided retries per node. Keep it ledger-derived and crash-safe, as D30's docstring states, and keep the prospective (priced) prompt identical to the rebuilt one.
- **Docs:** update D30/N52 references in docstrings and record D82.
- **Tests:** cover each case's line, the two-retry cap, and crash-safety (a crash between a refusal and the retry gives the same feedback).

### Task 4: Limits — call deadline and upstream bound (D83)

1. Raise `TIMEOUT_SECONDS` in `caos/provider.py` from 240 to **420**.
   - Verify it still fits the work lease (`LEASE_SECONDS = 600`, `caos/store/work.py`; `CALL_HOLD_SECONDS`, `caos/store/runs.py:60`) with room to bill and accept.
   - Update every test and docstring that states 240, and the adapter's timeout in `tests/openrouter_adapter.py`, which uses the same constant.
2. Raise `MAX_UPSTREAM_HANDOFF_BYTES` in `caos/methodology/invocation.py:106` from 53,248 to **98,304** (96 KiB).
   - Rewrite the bound's comment with the new arithmetic: 9 of 11 CZR and 6 of 6 CCL CP-1 answers were 50–86 KB. A CP-5 with 16 upstreams at 96 KiB leaves about 2.42 MB of the 4 MiB request for evidence.
   - Rewrite the widest-node test in `tests/test_handoff_invocation.py`. It currently only asserts the old floor; make it prove the 16-upstream node at the new bound fits beside the delivered authority. Also correct its docstring, which names CP-3 where CP-5 is the widest.
3. Record D83 (the owner's decision, with the measured evidence).

### Task 5: Bundle-fork clarity fixes, re-pinned (D84)

The owner authorises this edit to the deployment fork `vendor/deploy-v` (D31/D34).
1. **CP-1 headings.** `vendor/deploy-v/skills/cp-1-canonical-data-foundation/references/REF_CP-1_STEPS.md:282` tells the model the Audit Appendix holds Evidence Trace and Source Registry "as sub-sections". The validator requires both as H2. Reword that line to match the H2 contract; read the validator to quote its exact rule.
2. **Register binding.** State the vendor completeness checker's binding rule where the module contract describes registers: a register's heading must be within the 4 lines above its table (`completeness_check.py`, `find_registers`, `recent[-4:]`). Put it in the shared reference the CP skills use for register layout if one exists; otherwise in each affected SKILL's register section. Keep the change minimal.
3. **Re-pin**, per CLAUDE.md and D31's procedure:
   - `python3 -B vendor/deploy-v/verify_package.py --refresh`
   - `uv run python scripts/host_manifest.py`
   - the build pins in the tests
   - the `prompt` goldens regenerated from the legacy snapshot's code over the fork (D31's command)

   If the legacy snapshot is not available, report it as BLOCKED. Do not improvise.
4. Record D84.

### Task 6: Converter cleanup and re-admission of the 11 CZR sets (F478)

1. **Converter changes.** In `$S/edgar/convert.py`, which stays outside the repo:
   - end a table row at its last cell, with no trailing ` |`;
   - drop a leading list bullet glyph (`•`, `◦`, `▪`), which is layout;
   - put one space between a leading footnote marker such as `(a)` and the word it is glued to.

   Re-convert every source deterministically. The TRACE observations and the mandate are unaffected; leave their bytes alone.
2. **Re-admit** in every `qualification/czr-2026q2*/` set:
   - replace each converted document copy byte for byte;
   - update the register rows' SHA-256 and bytes;
   - re-state every answer key whose source line changed as the new whole line (F475 keeps this honest);
   - update RESULT.md provenance hashes and set digests;
   - move `COMMITTED_SET_DIGESTS`;
   - recheck the large-file pins (paths unchanged; sizes may cross 500 KiB);
   - re-emit DOCUMENTS.md with its count paragraph.
3. Record F478.

### Task 7: Whole gate list

Run every gate in CLAUDE.md that runs locally, including the full suite with coverage, scan floors, bandit floor, pip-audit, complexipy, jscpd, `check_gate_config --against 313f13f`, the stub bundle runs and `shipped_boot.py`. Report every exit code. Frontend gates run only if a frontend file changed.

## Live loop (controller, after Task 7; no SDD task)

- **Run config:**
  - wrapper `$S/live_run.sh` with `REPO=$S/wt-fix`;
  - model `openai/gpt-6-luna-pro:nitro`;
  - price pinned at `0.0000004`/`0.000002`, dated 2026-10-02 (conservative over the observed priority-tier billing of about $0.31/$1.55 per million);
  - `--attempts 1`.
- **Order:** one set at a time, in this order: `czr-2026q2-earnings-update`, `czr-2026q2-liquidity`, `czr-2026q2-covenant-refinancing`, `czr-2026q2-lite-relative-value`.
- **On a module's first failure:** replay the stored answer to find the rule (the `rca/replay.py` / `classify.py` method). Patch the cause through an SDD fix task with review, then re-run the same set. Move to the next set only when the current set completes or stops on a methodology verdict (e.g. a valid `Blocked`) rather than a fault.
- **Budget:** $50 on the key (`limit_remaining` checked before every run).
- **Record:** results go into `qualification/PROVIDER_RUNBOOK.md` and each set's `RESULT.md` at the end.

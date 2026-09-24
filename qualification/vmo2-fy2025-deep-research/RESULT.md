# VMO2 FY2025 deep-research qualification — one authorized run, 18 September 2026 (below)

**Before 18 September 2026 no run had been performed against this set;** the authorized run is recorded at the end. It is authored, loadable and
digested; nothing here reports a result, a verdict or a provider. The live run
is Phase 9 Task 9.4 step 7 and needs the owner's explicit authorization — it
costs real money and calls a real model. **The material figures in the keys
below await the owner's confirmation** before that run.

## The set

- Qualification-set digest:
  `1881fcf6818e623322b52679268906a624d9ad4b4026c759f74bdcf9435e9bdd`
- Route: `LITE_CREDIT_22 / LITE_DEEP_RESEARCH` (`CP-0` → `CP-DR`, one
  REQUIRED edge, `decision_scope: SCREENING_ONLY`, terminal deliverable
  `CP-DR`), enabled by `docs/DECISIONS.md` §96 at build `6a5f1050`.
- `tests/test_deep_research_set.py` holds the digest, the document digests,
  that the brief is one the pin accepts, that every citation key anchors
  exactly once, and that the UNRESOLVED question names a fact neither
  document carries.

## The documents

The two Virgin Media O2 earnings releases of `qualification/vmo2-fy2025/`,
the same bytes, copied because `server/qualification/on_disk._document`
refuses a declared path outside the set root:

- `documents/Virgin-Media-O2-Q3-2025-Earnings-Release.pdf`, SHA-256
  `505bf1a0f4181c9cdffeeac7e6af3253d1883788e9cd1a81e65952e008aa17a1`
- `documents/Virgin-Media-O2-Q4-2025-Earnings-Release.pdf`, SHA-256
  `66055bbb8d27721d07a5e8cb834c9b96a256ada45a0812ea4fb2e7202ee4f64d`

## The brief

**Implementer-authored**, not sourced: the owner's instruction was to search
for equivalent versions to test with; the coordinator recommended authoring
one, because a brief is a run control the host pins rather than evidence, and
a sourced brief would still have needed rewriting to this issuer and pack. It
is `CP_DR_RESEARCH_BRIEF_V1`, `mode: linked`, scoped to `VMO2` / `Virgin Media
O2`, `source_mode: supplied_only` (invariant 1: the host has no web access, and
the pin refuses any other mode), `budget: standard`. The host writes `run_id`,
`cp0_sha256` and `authority_sha256` when CP-DR is invoked; the manifest carries
none of them, and the pin refuses a brief that does. Every question is placed
`consumer_module_id: NONE` after `CP-0`: on this pathway CP-DR is the
terminal deliverable, so no downstream module adopts the research.

Three locked questions, two the pack answers and one it cannot:

1. `RQ-impairment` — the stated cause of the Q4 2025 non-cash goodwill
   impairment. Answered by the Q4 release, page 7: "In Q4 2025, we recorded a
   non-cash goodwill impairment of £1,021.7 million primarily related to the
   impacts of the UK market and" / "macroeconomic conditions in the UK on
   estimated future cash flows."
2. `RQ-undrawn` — maximum undrawn commitments at 31 December 2025. Answered by
   the Q4 release, page 3: "At 31 December 2025, the company had maximum
   undrawn commitments of £1,378.0 million" / "equivalent." The Q3 release
   states the same amount at 30 September 2025, which is the contrary evidence
   a sound dossier searches and does not contradict.
3. `RQ-rating` — Moody's current corporate family rating and outlook. **Neither
   release names a rating agency or a rating**, so a supplied-only dossier must
   record it `UNRESOLVED` rather than answer from model memory.

## Keys, and where each came from

Authored from the two documents and the brief only, never from any run output,
capture file or result section; nothing has been run on this route.

- `expects_ready: ["CP-DR"]` — the route's one pinned consumer, which CP-0's
  T8 must report as ready.
- `expects_projection` — CP-DR `decision_scope` = `SCREENING_ONLY`, which the
  catalog declares for this pathway.
- `expects` — two CP-DR citation keys on the Q4 release, the first line of
  each answer above (each anchors exactly once in the extracted tokens).
- `expects_register` — TDR.3 `resolution_status` per question:
  `RQ-impairment` ANSWERED, `RQ-undrawn` ANSWERED, `RQ-rating` UNRESOLVED.
  Coverage is therefore expected at 67 (two of three), which the vendor's
  `validate_dossier` requires to be reported `Complete with Gaps`; that is not
  keyed, because it follows from the three rows.

## What awaits the owner

The two figures above (£1,021.7 million and £1,378.0 million) and the choice of
questions, before the step 7 run is authorized.

## First authorized run — 18 September 2026

Authorized by the owner on 18 September 2026 (key figures confirmed, `$5`
per run). Provider `openrouter/openai/flex/high/65536`, model
`openai/gpt-5.6-terra`, `$0.000002` / `$0.000012` per token dated
2026-09-18, `--attempts 2`, bundle build `78c24be4` (§96 with §98). The run
database is on the persistent dev server (§100).

- Run `94590ea4-5153-4826-8bf7-55fbcb7de4d2`; database
  `caos_qualify_2d850367a8fc4b5992990babe6b89e8d`; capture
  `run-2026-09-18-capture.json`; evidence `19acbea58c75cba1…`.
- Charges: CP-0 `$0.14397725` (accepted); CP-DR attempt 1 `$0.11225975`,
  attempt 2 `$0.11388875`, both refused. Total **`$0.37012575`**.

**Not signable; the run stopped with CP-DR unaccepted.** Both CP-DR answers
were refused `HANDOFF_INCOMPLETE` by the vendor's dossier check, which
reports that the research approved-plan hash differs from the current brief.
Whether the host showed CP-DR one brief and validated it against another is
under investigation; this record is updated with the finding.

## Second authorized run — 18 September 2026

Same authorization and settings as the run above; bundle build `78c24be4` with
§101 (CP-DR is delivered its research contract) and §102 (every source is
labelled `WHOLE` or `PAGE_MAP`); database on the persistent server (§100).

- Run `de27f93c-be52-4c6c-9a45-2ab75286dbe0`; database `caos_qualify_ee63927485004c75b20949af48fed495`;
  capture `run-2026-09-18b-capture.json`; evidence `af4bdf5af6cd1cfe…`.
- Charges: CP-0 `$0.14204925`, CP-DR `$0.1178595`, both accepted first time; total
  **`$0.25990875`**.

Route COMPLETE, 2 artifacts, 7 citations all re-located; both citation keys met;
readiness and projection keys met; CP-DR's findings answer RQ-impairment and
RQ-undrawn and leave RQ-rating UNRESOLVED (coverage 67%) -- exactly the keyed
statuses. `complete` is nevertheless **false** because of a **host scoring
defect**: the three `TDR.3` register keys cannot be located by the vendor's
heading-based register locator, since CP-DR's tables are tagged by `table-id`
comments. Being fixed; the retained run will be re-scored without a provider
call and this record updated.

## Re-scored and signed — 18 September 2026: QUALIFIED

The scoring defect (§103) fixed, the retained run `de27f93c…` was re-scored with
no provider call: the rebuilt prepared and performed documents are byte-identical
to the stored snapshot and the matrix differs only in `registers_met` (false ->
true). The new snapshot was recorded through the store's own
`record_performed` / `record_evidence`: performed `e48f39d96e78a22e…`,
**complete**, evidence
`0bacb1a105f617d21e089adf4dac7825553b6ae3bb69f7428101ec7d5d07e4f6`; the
original rows are untouched.

**Verdict**, on the owner's instruction "Signed and approved": recorded through
`record_verdict` in database `caos_qualify_ee63927485004c75b20949af48fed495`,
reviewer "Eric Guei (owner)", decided `2026-09-18T16:58:48+00:00`, expires
`2026-10-18T16:58:48+00:00` (a 30-day term the coordinator chose), provider
`openrouter/openai/flex/high/65536:openai/gpt-5.6-terra`, set `09807efb…`,
build `78c24be4…`. `reviewer_id` is the documented local dev actor
`00000000-0000-4000-8000-00000000d001`: the owner's local configuration carries
no dev user id, so the host held no other identity for them. The release pack
read against that store reports `LITE_CREDIT_22 / LITE_DEEP_RESEARCH` as
`QUALIFIED` -- the first qualified pathway, scoped to this set, this build and
this execution profile, until the verdict expires or the build moves.

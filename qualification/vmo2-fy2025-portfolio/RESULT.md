# VMO2 FY2025 portfolio-screen qualification — authorized runs, 18–20 September 2026

**Before 18 September 2026 no run had been performed against this set.** The
authorized runs are recorded below.

## The set

- Qualification-set digest:
  `a46a1b4f597885e8…` (moved from `8e53fe3d…` when the register key below was
  added; a digest covers the keys, so the two are different sets)
- Route: `LITE_CREDIT_22 / LITE_PORTFOLIO_DECISION` (`CP-0` → `CP-L10`, one
  REQUIRED edge, `decision_scope: SCREENING_ONLY`, terminal deliverable
  `CP-L10`)
- Documents: the Virgin Media O2 Q3 and Q4 2025 earnings releases, the same
  bytes as `qualification/vmo2-fy2025/`
  (`505bf1a0f4181c9c…` and `66055bbb8d27721d…`). They are copied rather than
  referenced because `server/qualification/on_disk._document` refuses a
  declared path that resolves outside the set's own directory; the register
  (`qualification/documents.json`) carries a row per copy.

## Keys, and where each came from

Authored from the documents, never from any run output, capture file or result
section. Nothing has been run on this route, so there was nothing to copy from.

- `expects_ready: ["CP-L10"]` — the route's one pinned consumer, which is
  exactly what CP-0's T8 is asked to report here (`_gate_expects`).
- `expects_projection` — CP-L10 `decision_scope` = `SCREENING_ONLY`, which the
  catalog declares for this pathway and the host projects beside the status;
  and CP-L10 `qa_status` = `Restricted`, the honest expectation over a
  two-release extract, as in the earnings sets.
- `expects` — one citation, CP-L10 against the Q4 release
  (`66055bbb8d27721d07a5e8cb834c9b96a256ada45a0812ea4fb2e7202ee4f64d`):

      we recorded a non-cash goodwill impairment of £1,021.7 million

  Q4 2025 release, page 7 of the extraction, the line reading
  `In Q4 2025, we recorded a non-cash goodwill impairment of £1,021.7 million
  primarily related to the impacts of the UK market and`. The quote was checked
  against the real extractor's token index for that page: it matches whole
  tokens exactly and matches **once**, so it anchors rather than refusing
  `CITATION_AMBIGUOUS`. It is the fact-carrying span of the line rather than the
  whole line, whose tail is a subordinate clause carrying no figure — the defect
  `CLAUDE.md`'s "borrowing-capacity key names a subordinate clause" entry
  records.

## What is owed

- ~~**Register keys.**~~ The `ExpectedRegister` form landed with Task 8.1 and
  this set now carries one key: CP-L10's `TL10.2`, row
  `topic_id=LIQUIDITY_MATURITIES`, `evidence_status` must be `PARTIAL`. It is
  the key Task 8.1 justified from these same two releases -- they give undrawn
  commitments and covenant leverage, so the topic is not `MISSING`, and neither
  carries a maturity profile of the third-party debt, so it is not
  `SUFFICIENT`. Same module, same register, same documents, so the conclusion
  carries to this pathway unchanged. A `TL10.1` source-row key is still owed and
  is not guessed here.
- **The run itself**, and a signed verdict or a recorded reason why not.

## First authorized run — 18 September 2026

Authorized by the owner the same day ("authorize the two portfolio runs with the
Terra settings above, a $5 ceiling per run, today"). **Not signable:**
`complete` is false because the one citation key was missed.

- Provider/model: `openrouter/openai/flex/high/65536` / `openai/gpt-5.6-terra`
- Price: `$0.000002` input, `$0.000012` output per token, dated 2026-09-18,
  read from OpenRouter's published model list that day
- Run ceiling `$5.00`; `--attempts 2`; build
  `62a94ccd0ef6439f797d60ebb72e6a44e1d42db16cd8af217fc41b7f1d6ea72c` (§92)
- Run `2ab8b2e2-b577-45ca-87bd-8c45e3f7b9f2`; set `a46a1b4f597885e8…`
  (unchanged); evidence `1b9df866631eb3d8…`; performed `65701fdf5f8863c9…`
- Retained database `caos_qualify_9b87b7104a8d49f1badeffc12d47b3c4`, blob root
  `/var/folders/81/bwblpst93lb6wb3lwrk8k6800000gn/T/caos-qualify-fi8rdqvn`;
  capture `run-2026-09-18-capture.json`
- Charges: CP-0 `$0.13946575`; CP-L10 attempt 1 `$0.1660905` (refused
  `CITATION_NOT_LOCATED`), attempt 2 `$0.16364625` (accepted). Total
  **`$0.46920250`**.

| | |
|---|---|
| Route | COMPLETE, 2 artifacts |
| Proof | 5 citations, every one re-located |
| `ready_met` / `projections_met` | true / true |
| Citation key | `met=0, missed=1` — CP-L10 did not quote the £1,021.7m goodwill impairment line |

CP-L10 cited the adjusted EBITDA guidance, adjusted FCF and undrawn commitments
lines instead. The key is unchanged: it was authored from the documents before
any run, and moving it to what the model quoted would measure the model against
itself.

**Retention, corrected 18 September 2026 (§100):** the retained database named above was on the in-memory test server and was erased when that server restarted. The capture and blob root survive; a matrix can no longer be re-derived from the store for this run.

## Second authorized run (re-run) — 18 September 2026

Authorized by the owner on 18 September 2026 (key figures confirmed, `$5`
per run). Provider `openrouter/openai/flex/high/65536`, model
`openai/gpt-5.6-terra`, `$0.000002` / `$0.000012` per token dated
2026-09-18, `--attempts 2`, bundle build `78c24be4` (§96 with §98). The run
database is on the persistent dev server (§100).

- Run `cf5464dd-734c-436b-ad97-97a45f29943f`; database
  `caos_qualify_9023b9f626384bbfb1d5d1cc30a34ca4`; capture
  `run-2026-09-18b-capture.json`; evidence `34a66ebf10fbc4bb…`.
- Charge: CP-0 `$0.134558`, one call. Nothing else was called.

**Not signable.** CP-0 answered a validated `qa_status: Blocked` and marked
CP-L10 `DO NOT RUN / BLOCKED`, saying the effective-source set carries no
fidelity-validated active representation for either earnings release. The
run ended BLOCKED with nothing accepted (`ORCHESTRATION_NOTHING_TO_PROVE`).
The same set's CP-0 on build `62a94ccd` that morning was accepted and judged
CP-L10 ready, so whether the host's source-preparation section changed
between builds is under investigation; this record is updated with the
finding.

## Third authorized run — 18 September 2026

Same authorization and settings as the run above; bundle build `78c24be4` with
§101 (CP-DR is delivered its research contract) and §102 (every source is
labelled `WHOLE` or `PAGE_MAP`); database on the persistent server (§100).

- Run `98ebf917-8546-4ca2-a1b3-596a8970460e`; database `caos_qualify_b8856d531d4c44529692b69c62bc1d1b`;
  capture `run-2026-09-18c-capture.json`; evidence `d407f44d1f598f77…`.
- Charges: CP-0 `$0.129597`, CP-L10 `$0.17191075`; total **`$0.30150775`**.

**Not signable.** §102's label worked: CP-0 was accepted and judged CP-L10 ready,
the route COMPLETE, 2 artifacts, 5 citations all re-located, readiness and
projection keys met. The one citation key was **missed a second time**: CP-L10
did not quote the £1,021.7m goodwill impairment line. A model outcome, measured
twice.

## Pinned Phase 4 smoke run — 19 September 2026

The owner authorized the 19 September provider and spend recommendation for all
sets. This set was launched once with model `openai/gpt-5.6-sol`, provider tag
`openai`, reasoning `high`, identity `openrouter/openai/high/65536`, dated price
`0.000005` input / `0.000015` output, ceiling `18.677760`, and `--attempts 2`.
`OPENROUTER_BASE_URL` was explicitly unset. The driver exited **1** after the
second permitted attempt; it was not launched again.

- Run `b54bc007-e6c8-4798-b266-e975aa143f5f`; build
  `78c24be4483612e75d9a0809fcb1cb7c2dd5617e669491de13be9c0123e3ff93`;
  set `a46a1b4f597885e8f6937b47f9da7eba5ec266f4a43818d5f9fa1d42337b87ea`.
- Final evidence `961940c10eabb9589d7a8aedf168a4ed7b4fbe3f749b1a6a6758c45273028dd8`;
  performed `75e303228c1ab10a3be7e8f0de8368e634213d39a26c19fa841127e50620bf79`.
- Retained database `caos_qualify_f68731cc5b584def9975852b55cb0283`;
  blob root
  `/Users/ericguei/.codex/worktrees/gpt-model-routing/caos-workbench/.dev-data/qualification-blobs/caos-qualify-c_gsmhvk`.
- Capture `run-2026-09-19-a-capture.json`; driver log
  `run-2026-09-19-a-driver.log`.
- Two CP-0 calls were made. Attempt 1 charged `$0.3288035` and stopped
  `CITATION_NOT_LOCATED`; attempt 2 charged `$0.325751` and stopped
  `HANDOFF_MALFORMED`; total charge **`$0.6545545`**. Their retained
  reservations total `$4.524080`. Both outcomes record model
  `openai/gpt-5.6-sol`; neither produced an accepted artifact, and CP-L10 was
  never called.
- Final capture: `complete: false`, run status `RUNNING`, stopped
  `HANDOFF_MALFORMED`, refusal `ORCHESTRATION_NOTHING_TO_PROVE`, and no matrix.

The pre-run citation, readiness, projection and register keys remain unchanged.
Because neither CP-0 handoff was accepted, CP-L10 did not run and none of those
keys was evaluated through a matrix. No authenticated human verdict exists;
the pathway remains **NOT_QUALIFIED**. This second two-node smoke set also
stopped `HANDOFF_MALFORMED` at CP-0, so Phase 4 stopped here without another
launch.

This was a deliberate second smoke after the CCL run's unexpected refusal: the
owner's all-set authorization covered it, and it tested whether the shared CP-0
failure reproduced on a different corpus. It is the sole diagnostic exception
to the runbook's default stop-after-first-unexpected-refusal rule. Its failure
confirmed the early stop; no wider or third set was launched.

Post-run diagnostic classification: attempt 1 passed the closed transport,
Markdown text and vendor validation gates, and all four citations were quoted
in the handoff. Three citations re-anchor uniquely on their declared pages; the
third (quote SHA-256 prefix `9e463ad4efe1`) occurs on none of the declared
source's 18 pages, so `CITATION_NOT_LOCATED` is a model quotation miss rather
than extraction drift. Attempt 2 passed the transport and text gates with all
five citations quoted, but a MATERIAL finding required
`qa_status: Restricted` at body line 123. That is a second model-contract miss,
not a host, parser or key defect.

## Authorized Sol/xhigh retry — 19–20 September 2026

After the CCL retry reconciled as a model-contract miss rather than a host or
provider defect, the owner-authorized second smoke set was launched once with
the same model and endpoint at reasoning `xhigh`: model
`openai/gpt-5.6-sol`, provider tag `openai`, identity
`openrouter/openai/xhigh/65536`, dated price `0.000005` input / `0.000015`
output, ceiling `$12.451840`, and `--attempts 1`. `OPENROUTER_BASE_URL` was
explicitly unset. The run began on 19 September and finished after local
midnight; its `-b` stamp preserves the authorized launch date.

- Run `802ae485-54a8-4f4c-96c8-2f1cd9f80d2d`; build
  `78c24be4483612e75d9a0809fcb1cb7c2dd5617e669491de13be9c0123e3ff93`;
  unchanged set
  `a46a1b4f597885e8f6937b47f9da7eba5ec266f4a43818d5f9fa1d42337b87ea`.
- Final evidence `5aff20e9bcde08f4ae3dcf0c409150afeb764191edc8152f3e2cf6f183418bef`;
  performed `27fe9ca5706ca2188138e96967e4b9c9402e32b42eb3afe1742d6d58ad7b0fb9`.
- Retained database `caos_qualify_cc7b22d0e73745f3918abf44cbb9ed6e`;
  blob root
  `/Users/ericguei/.codex/worktrees/gpt-model-routing/caos-workbench/.dev-data/qualification-blobs/caos-qualify-tob16vnx`.
- Capture `run-2026-09-19-b-capture.json`; driver log
  `run-2026-09-19-b-driver.log`. Their SHA-256 digests are respectively
  `d31cc3ff5df652166b414e3110b52b3bda8fc211bfce52d7c1e1978300d7e6ef`
  and `57e279d75a18b2e9a48e0dd44a198d974e8b51efe64bbb789fc83bdeb4a0a4ae`.
- CP-0 reserved `$2.262045` and charged `$0.4218235`; CP-L10 reserved `$2.721770`
  and charged `$0.4381285`. Total reservation was `$4.983815`; total charge was
  **`$0.8599520`**. Both outcomes record model `openai/gpt-5.6-sol`.
- The run reached `COMPLETE` with two accepted artifacts, eleven re-anchored
  citations and a sound proof. The matrix reports `proven: true`,
  `ready_met: true`, `projections_met: true`, `registers_met: true`, citation
  keys `met: 0` / `missed: 1`, and no refusal. The performed snapshot is
  `complete: false` because the one pre-run CP-L10 citation key was missed.

The citation, readiness, projection and register keys are unchanged. No
authenticated human verdict exists, so the pathway remains
**NOT_QUALIFIED**. The xhigh retry improved structural completion over the
Sol/high smoke run but did not satisfy the qualification matrix; it does not
justify continuing Phase 4 to wider sets without a new owner decision.

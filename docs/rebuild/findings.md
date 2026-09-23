# Adversarial review findings — 2026-09-23

**Verdict: BLOCK.** **18 open findings: 10 CRITICAL after persona promotion, 8 WARNING.** All ten promoted findings have a base severity of WARNING; their concrete impact and conditions are stated below. Promotion follows the requested adversarial-reviewer rule when two or more personas identify the same issue.

**Scope:** the current working tree at base commit `6aef8509b30203af425afa7ce9666613c54ba275`, including existing uncommitted changes: API edge and identity; store and graph; model seam, methodology and evidence; deployment and stand-ins; deliverables, qualification, calculators and gate scripts. This is a system review, not only a diff review. Finding-source hashes and locations were rechecked on 2026-09-23 at 05:32 UTC.

**Method:** five separate `gpt-6-astra` agents at `xhigh`, with at most three sub-agents running concurrently because of the session limit. Four completed Saboteur → New Hire → Security Auditor passes. The model/methodology/evidence agent stopped when the service flagged content for possible cybersecurity risk; its confirmed correctness observations were independently checked by the coordinating reviewer. Its unfinished PDF decoder candidate is excluded. That scope has incomplete review coverage.

**Changes:** this audit writes only this findings list. No code, tests, configuration or vendor files were edited by the reviewers. Another session modified source and tests during the audit; withdrawn observations are recorded separately rather than counted as open findings. Existing `decisions.md` entries F1–F31 describe fixed findings and are not relabeled as outstanding.

## Critical findings

### AR-01 — A dropped database connection can terminate the worker permanently

**Base WARNING → CRITICAL; Saboteur + New Hire.** Location: [worker.py:271](/Users/ericguei/Documents/caos-databricks/caos/graph/worker.py:271), with recovery at line 304.

`_beat()` catches a database failure and then calls `conn.rollback()` without protecting that call. The worker's recovery handler invokes `_beat()` again on the broken connection before closing it, so a second rollback error escapes the reconnect loop. A probe terminated only its own connection in a disposable UUID database: `worker_escaped=OperationalError`, `connections_opened=1`. The in-process worker stops while the API process remains alive.

**Repair direction:** use the existing `rollback_or_close()` and ensure the BACKOFF heartbeat cannot escape connection recovery. Cover a real dropped connection, not only an exception double.

### AR-02 — Real connection authentication failures retain the rejected cached credential

**Base WARNING → CRITICAL; Saboteur + Security Auditor.** Location: [lakebase.py:66](/Users/ericguei/Documents/caos-databricks/caos/store/lakebase.py:66); also the checkpoint connection path in [checkpoint.py](/Users/ericguei/Documents/caos-databricks/caos/graph/checkpoint.py).

`note_connect_failure()` invalidates only `InvalidPassword` and `InvalidAuthorizationSpecification` subclasses. A real local PostgreSQL connection with an invalid password produced `OperationalError`, `sqlstate=None`; passing it to this function left the cache populated. An early-invalidated Lakebase credential can consequently keep being reused until the 14-minute cache expiry. Checkpoint connection failures do not invoke this hook either. The existing test constructs the more specific exception subclasses and misses the actual driver behavior.

**Repair direction:** perform bounded credential invalidation/remint/retry at the connection boundary, including the checkpoint pool, without depending on unavailable connection SQLSTATE. This is an availability finding; no authentication bypass was demonstrated. Actual Lakebase token revocation was not exercised.

### AR-03 — The capped retry delay overflows after a prolonged outage

**Base WARNING → CRITICAL; Saboteur + New Hire.** Location: [worker.py:251](/Users/ericguei/Documents/caos-databricks/caos/graph/worker.py:251).

`pause_seconds()` calculates `float(2 ** (failures - 1))` before applying its cap. Calling it with the default worker configuration and `failures=1025` raises `OverflowError`. `run_worker()` calls it outside the fault handler, so persistent immediate failures eventually kill the worker instead of remaining at the capped delay—roughly 8.5 hours at the default timing. The existing cap test checks only nine failures.

**Repair direction:** cap before exponentiation or bound the exponent, and verify a large consecutive-failure count.

### AR-04 — Rejected identity tokens accumulate outside the cache bound

**Base WARNING → CRITICAL; Saboteur + New Hire.** Location: [identity.py:229](/Users/ericguei/Documents/caos-databricks/caos/api/identity.py:229).

The refusal path inserts into `_NEGATIVE` without enforcing `CACHE_CAPACITY` or removing expired entries. Cleanup happens only after a successful uncached lookup; continuing refusals and positive-cache hits do not clean it. A small isolated check with capacity 2 and time advanced beyond expiry between rejections retained 6 entries, including 5 expired entries. Memory therefore grows with distinct rejected tokens, and a later successful lookup must scan that accumulation.

**Repair direction:** prune and bound negative entries on insertion under the existing lock. Remote exploitability was not established: the real Apps proxy's handling of caller-supplied forwarded-token headers was not tested.

### AR-05 — Deployment E9 accepts closed HTML as proof of streaming

**Base WARNING → CRITICAL; Saboteur + New Hire.** Location: [enterprise_deploy.py:301](/Users/ericguei/Documents/caos-databricks/scripts/enterprise_deploy.py:301).

After successful case creation, E9 accepts any nonempty first line from an HTTP 200 response. An actual loopback response with `Content-Type: text/html`, body `<html>not an event stream</html>`, then EOF produced exit 0 and `first frame '<html>not an event stream</html>' with the stream open`. The code checks neither SSE content type/frame syntax nor continued connection liveness. This cannot substantiate the C42 streaming assertion.

**Repair direction:** validate an SSE response and complete frame, then establish continued streaming before recording the proxy as verified. Keep error-page and closed-response negative cases.

### AR-06 — Preflight accepts an endpoint/price mismatch that stops the deployed worker

**Base WARNING → CRITICAL; Saboteur + New Hire.** Location: [preflight.py:34](/Users/ericguei/Documents/caos-databricks/scripts/preflight.py:34), with the ineffective comparison at line 105.

`affordable()` extracts the endpoint from the price string itself rather than validating against `args.endpoint`. Against the workspace stub, `--endpoint enterprise-claude` with a valid price for `databricks-claude-opus-5` passed every check and exited 0. Production `from_environment()` rejects that same configuration with `PROVIDER_NOT_CONFIGURED`. E1 thus permits the bundle deployment/restart before the invalid worker configuration is detected.

**Repair direction:** validate the price against the requested endpoint before any deployment mutation.

### AR-07 — The gate-integrity checker misses effective gate weakening

**Base WARNING → CRITICAL; Saboteur + Security Auditor.** Location: [check_gate_config.py:58](/Users/ericguei/Documents/caos-databricks/scripts/check_gate_config.py:58).

The checker tests positive rule selections and option substrings, without resolving overrides or requiring the intended coverage source. Three isolated configuration mutations each returned no problems:

- `lint.ignore=["F821"]`: installed Ruff changed an undefined-name check from exit 1 to exit 0.
- Append `--cov-fail-under=0` after the existing threshold: installed pytest parsed an effective floor of 0.
- Set coverage `source=["caos.boundary_text"]`: Coverage resolved that narrowed scope. CI's scanner floor requires only one measured file and does not restore whole-package coverage.

**Repair direction:** check effective rules/options, conflicting overrides, exclusions and coverage source. This is a weakness in the guard against configuration regression; the current project was not changed to disable its gates. `ignore=["ALL"]` alone was counterchecked and rejected as an effective-disable example because the more specific selected families still won.

### AR-08 — Rendered lists change the author's numbering

**Base WARNING → CRITICAL; Saboteur + New Hire.** Location: [render.py:408](/Users/ericguei/Documents/caos-databricks/caos/deliverable/render.py:408).

The narrative `7. First`, `9. Second`, `10. Third` renders as an ordered list starting at 7 with items `First`, `9. Second`, `Third`. Browser counters remain 7, 8, 9: the second item gains an unauthored 8 and the third loses its authored 10. A transition from `- Bullet` to `7. Numbered` and `8. Next` stays inside an unordered list and drops the 8. Tests that strip HTML tags do not observe the generated counters.

**Repair direction:** preserve ordinals with native list-item values and reopen lists when their type changes; check the successor after a numbering gap.

### AR-09 — Qualification loading allocates the whole document set before aggregate limits apply

**Base WARNING → CRITICAL; Saboteur + Security Auditor.** Location: [on_disk.py:193](/Users/ericguei/Documents/caos-databricks/caos/qualification/on_disk.py:193).

`_case()` eagerly reads and retains every listed document. Individual reads are bounded, but document count and aggregate bytes are not checked at this boundary. A scratch manifest listing one small file 51 times loaded 51 distinct byte objects successfully; only the later admission step refused the 50-document limit with `SOURCE_TOO_LARGE`. Larger repeated allowed files can consume substantial memory before rejection.

**Repair direction:** enforce document counts and aggregate byte limits before/during reads, including a bound across the eagerly materialized qualification set. Exposure is an operator-loaded, potentially untrusted directory, not a remote API. No memory-exhaustion workload was run.

### AR-10 — Concurrent identical qualification signatures do not replay idempotently

**Base WARNING → CRITICAL; Saboteur + New Hire.** Locations: [qualification.py:137](/Users/ericguei/Documents/caos-databricks/caos/api/commands/qualification.py:137) and [store.py:520](/Users/ericguei/Documents/caos-databricks/caos/qualification/store.py:520).

Both requests can miss the initial receipt, but the later twin-receipt recovery is reachable only after inserting the verdict. Two real connections synchronized after those misses, with identical actor/key/document, returned one `201/replayed=False` and one `VERDICT_BINDING_INVALID` (HTTP 400). A later identical retry correctly returned `201/replayed=True`. The existing `(evidence_sha256, reviewer_id)` primary key collides first; only the newer evidence-only constraint is mapped as already recorded. Exactly one verdict and receipt persisted, so this is a false response and concurrent-idempotency failure, not duplicate state or data corruption.

**Repair direction:** serialize the idempotency scope before mutation or recover the committed receipt after the specific duplicate rollback, preserving different-request conflict checks.

## Warnings

### AR-11 — A cancelled, queued health probe can block every future probe round

**WARNING; Saboteur.** Location: [health.py:255](/Users/ericguei/Documents/caos-databricks/caos/api/health.py:255).

`inflight` is incremented before submitting the thread job, but only the thread body decrements it. If the executor is occupied until `wait_for` cancels a still-queued job, that body never runs. With a deliberately occupied one-worker executor and five healthy probes, `inflight` remained 5 after the executor recovered; three further rounds still reported `PROBE_TIMEOUT` without running. The process needs a restart to recover readiness in that condition.

**Repair direction:** account for cancellation before execution, or retain/shield tasks and observe actual completion. This requires a small or saturated asyncio executor; ordinary Starlette sync routes use AnyIO's separate pool. Normal HTTP traffic was not shown to trigger it.

### AR-12 — Malformed SCIM groups escape the typed identity refusal

**WARNING; Saboteur.** Location: [identity.py:309](/Users/ericguei/Documents/caos-databricks/caos/api/identity.py:309).

`_scim_user(b'{"id":"42","groups":true}')` raises an unhandled `TypeError` while iterating groups. An upstream malformed response becomes `INTERNAL_FAULT` rather than the documented `IDENTITY_UNAVAILABLE` response. The same applies to an integer groups value.

**Repair direction:** validate the groups container before iterating and map an invalid response to the typed refusal. This is an upstream-response condition, not a demonstrated authorization bypass.

### AR-13 — Cancellation during the last provider call is acknowledged but finishes COMPLETE

**WARNING; Saboteur.** Location: [runs.py:457](/Users/ericguei/Documents/caos-databricks/caos/store/runs.py:457); cancellation contract in [work.py:206](/Users/ericguei/Documents/caos-databricks/caos/store/work.py:206).

`_transition()` discards the cancellation flag returned by `require_lease()`. If cancellation arrives during the final call, there is no subsequent attempt to notice it. A real three-node LITE run with deterministic completions and cancellation from another connection during call three returned `request_cancel=True`, then `status=COMPLETE`, queue `('DONE', True)`, and only `RUN_COMPLETE`. Existing coverage cancels the first call and relies on the next start to observe cancellation.

**Repair direction:** resolve pending cancellation under the existing terminal-transition locks while retaining the completed call's accepted artifact and bill.

### AR-14 — Negative token counts can produce an accepted zero charge

**WARNING; Saboteur, independently reproduced by the coordinator.** Location: [models.py:179](/Users/ericguei/Documents/caos-databricks/caos/models.py:179).

`_charge()` converts each count with `int()` and validates only the combined monetary amount. A real `AIMessage` with input tokens -5, output tokens 1 and total tokens -4 at rates 0.000005/0.000025 yielded `Completion(charge=Decimal('0.000000'), refusal=None)` through `complete()`. Malformed upstream accounting therefore becomes an accepted response with an incorrect known charge. The store still retains the reservation via `max(reserved, charged)`; this probe did not demonstrate released capacity or overspending.

**Repair direction:** require nonnegative integral usage fields before pricing and reject invalid metadata through the existing unknown-charge/refusal path.

### AR-15 — Qualification identity records reasoning effort that the model never receives

**WARNING; New Hire, confirmed across the provider and qualification paths.** Locations: [models.py:104](/Users/ericguei/Documents/caos-databricks/caos/models.py:104) and [models.py:270](/Users/ericguei/Documents/caos-databricks/caos/models.py:270).

With `CAOS_REASONING_EFFORT=high`, the provider reports `databricks/audit-model/high/65536`. An isolated trace showed factory options `{'endpoint': 'audit-model'}` and invocation options containing only `response_format`; no reasoning parameter was sent. The qualification harness persists this identity and signed verdicts bind it. `next.md` N2 explicitly says the identity should record `none` when the parameter is not sent.

**Repair direction:** reject or ignore the setting until supported passthrough is verified, and derive the qualification identity from parameters actually used.

### AR-16 — Explicit infinite PDF deadlines still raise an untyped exception

**WARNING; Saboteur.** Locations: [pdf.py:163](/Users/ericguei/Documents/caos-databricks/caos/evidence/pdf.py:163) and [pdf.py:191](/Users/ericguei/Documents/caos-databricks/caos/evidence/pdf.py:191).

The new `_finite()` helper replaces `None`, but passes `float('inf')` through. `_in_child()` then gives the infinite timeout to `Popen.communicate()`, which raises `OverflowError: cannot convert float infinity to integer` in the selector. The current existing test `test_page_frame_runs_in_the_killed_budgeted_child` reproduces this. The earlier default-`None` crash has been fixed concurrently and is not included as an open finding.

**Repair direction:** normalize or refuse non-finite deadlines before spawning the child, preserving typed refusal and bounded cleanup. Production ingestion supplies a finite deadline; ordinary PDF uploads were not shown to fail by this remaining case.

### AR-17 — The JSON-mode smoke test passes on non-JSON output

**WARNING; Saboteur.** Location: [gateway_smoke.py:42](/Users/ericguei/Documents/caos-databricks/scripts/gateway_smoke.py:42).

Real `ChatDatabricks` against a loopback `WorkspaceStub` returning `definitely not JSON` produced `json_mode=accepted` and exit 0. The completion adapter leaves JSON parsing to the canonical executor, but the smoke script never performs that parsing. E7 proves parameter acceptance while leaving the required structured-output behavior unchecked.

**Repair direction:** parse and verify the second completion's requested JSON object before reporting JSON-mode success.

### AR-18 — The qualification CLI cannot admit a multi-case set

**WARNING; Saboteur.** Location: [qualify.py:279](/Users/ericguei/Documents/caos-databricks/scripts/qualify.py:279), checked by [harness.py:481](/Users/ericguei/Documents/caos-databricks/caos/qualification/harness.py:481).

The CLI sets both the whole-set ceiling and each run's ceiling to `args.ceiling`. The harness correctly requires `run_ceiling × case_count ≤ set_ceiling`, so every positive-budget invocation with more than one case is impossible. A direct check passed one case with both ceilings 22 and refused two with `QUALIFICATION_SET_OVER_CEILING`. Raising the shared value cannot fix the inequality. CLI happy-path tests use one case.

**Repair direction:** expose or derive a distinct run ceiling, and validate the set before creating persistent resources.

## Verification

All Python checks used the installed environment via `uv run --no-sync`, with `PYTHONDONTWRITEBYTECODE=1`. Pytest runs disabled coverage and its cache provider to avoid modifying repository reports. Database checks used the documented local test PostgreSQL and disposable UUID databases. No paid provider calls, enterprise deployment, or real workspace authorization tests were performed. The following runs overlap and must not be summed as unique coverage.

| Run | Result |
| --- | --- |
| Store/graph: graph, worker, heartbeat, PostgreSQL races, budget, outcomes, idempotency and schema suites | **356 passed**, 1 live-provider test deselected; 92.45 s |
| Deliverable, calculator, qualification and gate-script selection | **608 passed**; 247.99 s |
| Initial deployment/boot/stub selection | 12 passed, 1 failed: outdated app-forwarding fixture; subsequently repaired outside this audit |
| Initial model/evidence selection reported before the agent interruption | 186 passed, 31 failed on the then-current default-PDF-deadline regression; that regression was subsequently repaired |
| Coordinator's intermediate model/PDF/API/health selection | 82 passed, 5 failed; subsequent external edits repaired the identity/health test fixtures |
| **Final coordinator rerun:** identity platform, health, enterprise deploy and PDF page-frame suites | **34 passed, 1 failed** in 25.40 s; remaining failure is AR-16 |
| Final focused mypy check of `caos/evidence/pdf.py` | **Passed**, no issues in 1 source file |

The final coordinator test command was:

```sh
PYTHONDONTWRITEBYTECODE=1 UV_NO_SYNC=1 \
CAOS_TEST_POSTGRES_URL=postgresql://postgres:local-test-admin-only@127.0.0.1:55437/postgres \
CAOS_REQUIRE_POSTGRES=1 uv run --no-sync pytest --no-cov -p no:cacheprovider --tb=short \
  tests/test_identity_platform.py tests/test_health.py \
  tests/test_enterprise_deploy.py tests/test_pdf_page_frame.py
```

The store/graph selection was:

```sh
uv run --no-sync pytest --no-cov -p no:cacheprovider \
  tests/graph/test_graph.py tests/test_worker.py tests/test_worker_heartbeat.py \
  tests/test_postgres_races.py tests/test_budget.py tests/test_call_outcomes.py \
  tests/test_command_idempotency.py tests/test_store_schema.py
```

The deliverable/qualification/calculator/gate selection was:

```sh
uv run --no-sync pytest --no-cov -p no:cacheprovider \
  tests/test_deliverable_render.py tests/test_deliverable_package.py \
  tests/test_deliverable_canonical.py tests/test_revisions.py tests/test_filing_chain.py \
  tests/test_cash_flow_forecast.py tests/parity/test_cash_flow.py \
  tests/test_qualification.py tests/test_qualification_store.py \
  tests/test_qualification_matrix.py tests/test_qualification_on_disk.py \
  tests/test_qualification_harness.py tests/test_qualification_execution.py \
  tests/test_qualification_prepare.py tests/test_qualification_sign.py \
  tests/test_check_gate_config.py tests/test_release_pack.py tests/test_qualify_script.py
```

The latter two commands used the same local test database and bytecode settings as the final coordinator run. These were focused review checks, not a full CI run. Passing existing tests does not cover the additional counterexamples described above.

## Withdrawn observations and limits

- The default PDF `None` deadline caused 31 failures early in the audit. Concurrent edits added a finite default and repaired the resulting annotation error; only AR-16 remains open.
- The original SCIM SDK discovery/authentication configuration concern was replaced by direct HTTP during the audit. The suspicion that ordinary SDK authentication errors escaped `except OSError` was separately disproved.
- The original accumulation of timed-out health threads was replaced by `inflight` gating; AR-11 records the narrower remaining cancellation-before-start issue.
- Deployment E9 originally treated every non-201 case response, including 500, as successful but unverified. Concurrent edits now fail non-201 responses other than the explicitly unverified 403 path.
- The deployment test's missing `forward_user_access_token` fixture and the identity/health fixture expectations were repaired outside this audit. The final rerun passed those suites, so their earlier failures are not counted as open findings.
- CLI validation disproved the suspicion that the dev target changes the actual app name from `caos`. The `ignore=["ALL"]` Ruff example was also disproved; AR-07 uses confirmed effective overrides.
- Stand-ins do not establish actual enterprise grants, Apps proxy behavior, Lakebase token revocation or live model quality. The boot harness manually constructs its environment and starts working-tree source, rather than installing and starting the uploaded bundle snapshot. These coverage limits are not new production vulnerabilities.
- No additional confirmed calculator or filing-authority defect was found. The portable package verifier explicitly proves internal consistency rather than external signer authenticity; that documented boundary was not reported as a bug.
- Model/methodology/evidence coverage remains partial because the dedicated agent was interrupted. No conclusion is claimed for its unfinished PDF decoder investigation or for every methodology helper.

## Summary

The first operational repair is the worker's broken-connection recovery: an ordinary disconnect can stop processing until restart. Qualification execution, identity/billing records and deployment evidence also contain reproducible gaps that existing passing tests do not catch. The list records findings and repair directions only; no fixes were applied by this audit.

---

# Focused pass — deliverable chain, qualification, calculators and gate scripts — 2026-09-23

**Verdict: BLOCK.** **41 open findings (FP-01…FP-41): 11 CRITICAL, 12 WARNING, 18 NOTE.** Only FP-01 is CRITICAL at base severity. The other ten are base WARNING promoted because two or more personas raised them. Sort by base severity to rank by impact alone.

**Scope:**
- `caos/deliverable/` (all seven modules)
- `caos/qualification/` (all seven modules)
- `caos/calculators/cash_flow.py`
- the gate scripts `scripts/{scan_floors,check_gate_config,check_tested,check_vocabulary,io_budget,check_icm,check_pr_size,tracked,icm_stages,host_manifest,document_register}.py`
- `scripts/qualify.py` and `scripts/release_pack.py`
- the gate wiring: `.github/workflows/ci.yml`, `.pre-commit-config.yaml`, the `pyproject.toml` tool tables and `tests/gate_baseline.json`

Every file was read in full. Callers and tests were read for their contracts and to find test gaps. The tree reviewed is `rebuild/databricks` at `6aef850` plus the uncommitted changes as they stood at about 05:50 UTC.

**Method:**
- Claude Opus 5.5 coordinated four sub-agents, each running Saboteur → New Hire → Security Auditor:
  - the deliverable chain;
  - qualification matrix and harness;
  - qualification store, proof and verdict, with `qualify.py` and `release_pack.py`;
  - the gate scripts.
- The coordinator reviewed the calculator itself and re-read the code behind every CRITICAL.
- "Proven" means a probe reproduced the finding, either against disposable databases on the local test PostgreSQL (port 55437) or against scratch fixtures.
- The probe scripts are in the session scratchpad (`scratchpad/{deliverable,qual-a,qual-b,gates,calc}/`), not in the repo.
- No full suite or gate run was performed in this pass.
- This section is the only repo change made.

**Moving tree:** a concurrent session edited files in scope during the pass. Findings are stated against the tree as it ended. The concurrent fixes are listed under *Closed or narrowed during the pass*.

**Overlap with the first pass:** AR-07, AR-08, AR-09, AR-10, AR-15 and AR-18 still stand and are not counted again here. FP-10 extends AR-07. The separate "Second pass" below, appended by another session at the same time, overlaps in two places: AR-22 with FP-14 (the pack drops the model identity) and AR-25 with FP-08's forecast-value bullet. Its `R2-E1`, `R2-N1` and `R2-N2` are its own IDs, not part of this section.

## Critical findings

### FP-01 — A declared refusal is "met" by runs that did not end that way

**Base CRITICAL; Saboteur (two reviewers) + New Hire.** Location: `caos/qualification/matrix.py:481-519` (`_refusal_met`). The waiver that consumes it is `caos/qualification/store.py:122` (`PerformedEvidence.complete`).

`complete` skips its COMPLETE-status requirement for any row with `expected_refusal_met`. This one predicate therefore decides whether an unfinished or successful run can be signed as the refusal its case declared. It returns true in three situations where the run did not end in that refusal:

- **A stale attempt refusal on a COMPLETE run.**
  - `_ENDED` includes COMPLETE, and the final query matches any `attempt_refusals` row on any attempt of the run.
  - `qualify.py`'s `_perform_until` re-enters `perform` after a stop. A retried node then succeeds, the run completes, and the first attempt's refusal still matches.
  - Proven: `SECOND: stopped= None status= COMPLETE` → `expected_refusal_met=True` → `SNAPSHOT complete (signable): True`.
- **The proof-refusal branch runs before the "run must have ended" guard.**
  - `if proof_refusal is expected: return True` comes before the `_ENDED` check that the comment below it describes.
  - A run that was started and never driven (RUNNING), or was CANCELLED, fails its proof with `ORCHESTRATION_NOTHING_TO_PROVE`, and so meets a key declaring that code. Proven for both statuses.
  - `proof_refusal` is also overwritten by later reader refusals (`matrix.py:437-455`).
  - The loader (`on_disk.py:390-398`) accepts any `RefusalCode` as an expected refusal, including `STORE_UNAVAILABLE`.
- **`HANDOFF_BLOCKED` is met by the run status alone.**
  - Any BLOCKED run meets it, including one that CP-0 blocked before any handoff returned Blocked (no `run_blocking_verdicts` rows).
  - Proven: `run_blocking_verdicts rows: (0,)` → `signable: True`.

Tests assert the waiver only over a COMPLETE run (`tests/test_qualification_store.py:340`). No test exercises the `attempt_refusals` branch or the `_ENDED` guard.

**Repair direction:** answer a declared refusal from how the run actually ended:
- the run is BLOCKED or FAILED, never COMPLETE, RUNNING or CANCELLED;
- the code sits on the terminal attempt of a node that stayed unaccepted;
- `HANDOFF_BLOCKED` requires a `run_blocking_verdicts` row.

Also apply the ended check before every branch, keep the proof's own refusal separate from reader refusals, and restrict `expected_refusal` to methodology codes.

### FP-02 — The release pack marks a pathway QUALIFIED through any run in a signed snapshot

**Base WARNING → CRITICAL; Saboteur + Security Auditor.** Location: `scripts/release_pack.py:173-232` (`_snapshot_pins`, `qualified_pathways`).

A verdict covers every pathway that any run in its snapshot was pinned to. So a case on pathway P2 that met a declared refusal, or that FP-01 let through, makes P2 QUALIFIED although no run on P2 produced an output. Proven through the normal `record_verdict` path: `artifacts on ('FULL_CREDIT_32', 'DECISION_LEDGER') run: 0` → `QUALIFIED ('FULL_CREDIT_32', 'DECISION_LEDGER')`.

The pin is looked up by `(run_id, route_digest)` and never validated:
- A row with `resolved='{}'` is accepted, although `route_pin` refuses it with `ROUTE_IDENTITY_INVALID`.
- A run on the CP-CF-extended route qualifies the base pathway.
- The digest is never compared with what the current catalog resolves.

The test fixture `_pin` (`tests/test_release_pack.py:151-166`) itself inserts `resolved='{}'`.

**Repair direction:** count a pathway only through a case on that pathway that proved, answered its keys and reached COMPLETE. Read the pin through `route_pin`, and require its digest to equal the current catalog's resolution with the same extensions.

### FP-03 — Signing, reading and the release pack trust stored derived state

**Base WARNING → CRITICAL; Saboteur + Security Auditor.** Locations: `caos/qualification/store.py:505` and `:554`; `scripts/release_pack.py:198-215`; `evidence_at` at `store.py:229-246`.

Three things are trusted without being re-checked:
- `qualification_performed.complete` is computed once, by whatever code recorded the snapshot, and trusted from then on.
- `performed_json` is never re-digested against `performed_sha256`.
- The pack re-runs neither `_models_recorded` nor any proof.

Two consequences:
- **Stale snapshots stay signable.** A snapshot recorded as complete under the old short-circuit `_answered` (fixed concurrently as F64) can still be signed, stays current and appears in the pack. Proven: `current code: complete = False` / `record_verdict: accepted; current_verdict: QUALIFIED`.
- **Inserted rows can forge QUALIFIED.**
  - The migrations block UPDATE and DELETE but not INSERT.
  - The app role can insert a verdict/evidence/performed triple with self-consistent, unkeyed SHA-256 digests over a FAILED run that has no artifacts.
  - Proven: `digest(performed_json) == performed_sha256 ? False` → `pack row status: QUALIFIED`.
  - The docstring's promise that tampered rows are refused holds only for inconsistent tampering.

**Repair direction:**
- Re-derive `complete` from `performed_json` in `record_verdict`, in `current_verdict` and in the pack, and refuse when it disagrees with the stored flag.
- Re-digest `performed_json`.
- In the pack, re-run `_models_recorded` and `assert_orchestration_proof` for each run.
- Longer term, key the verdict digest (HMAC or KMS).

### FP-04 — Filing does not re-prove the revision it files

**Base WARNING → CRITICAL; Saboteur + Security Auditor.** Location: `caos/deliverable/filing.py:192-240` (`file_deliverable_in`); the route is `caos/api/commands/deliverable.py:319-367`.

`freeze_in` re-derives the revision and compares it with the stored bytes. Filing only compares rows, and the route's `_reviewed` only checks the digest the client sent.

Scenario:
1. A revision is signed and frozen.
2. A WRITER withdraws a cited source. `withdraw_source` says every gate bound to that source reopens.
3. An approver files anyway, and `DELIVERABLE_FILED` enters the permanent audit chain for a deliverable the host can no longer prove.

Proven: `prove_revision after withdrawal: refused ARTIFACT_RECORD_MISMATCH` / `file_deliverable after withdrawal: FILED` / `DELIVERABLE_FILED events: (1,)`. The only record of this trade-off is the read budget `FILE_IO = 16`.

**Repair direction:** call `prove_revision` in `file_deliverable_in` and require its bytes to hash to the frozen digest, as `freeze_in` does. Raise `FILE_IO` to match.

### FP-05 — A filed deliverable becomes unreadable when live state moves

**Base WARNING → CRITICAL; Saboteur + New Hire + Security Auditor.** Locations: `caos/deliverable/receipts.py:38-39` and `:101-105`; `caos/deliverable/revisions.py:196-222`.

Every Committee read of a filed revision re-runs `prove_revision` against the current sources, the current bundle bytes and the current narrative rules. When that fails it refuses with the same codes tampering produces (`ARTIFACT_RECORD_MISMATCH`, `NARRATIVE_FIGURE_UNREFERENCED`).

Three ordinary events each lock every filed record out of the Committee section permanently:
- a WRITER withdrawing a source;
- a routine `vendor/deploy-v` upgrade;
- a tightened narrative rule, such as FP-06's fix.

The user is then shown remediation advice for a record that is immutable. Proven for withdrawal (FP-04's probe, and the existing `test_filed_receipt_requires_live_saved_payload_proof`) and for a rule change (`read after rule fix: refused NARRATIVE_FIGURE_UNREFERENCED`).

**Repair direction:**
- Serve a filed revision from its digest-checked bytes and its verified audit chain.
- Report live re-checks as a separate status, such as "evidence withdrawn since filing".
- Validate each revision under the rule and bundle version it was saved with.

This must land before FP-06's fix.

### FP-06 — Non-ASCII digits pass the every-figure-is-cited rule

**Base WARNING → CRITICAL; Saboteur + Security Auditor.** Location: `caos/deliverable/revisions.py:41`.

`any("0" <= character <= "9" ...)` only sees ASCII digits. `BoundaryText` applies NFC, which keeps fullwidth and other-script digits. So all of these are stored as uncited figures in committee prose, against invariant 11:
- `Leverage is ４.２x` (fullwidth)
- `٤٫٢x` (Arabic-Indic)
- `½`, `Ⅳ` and `𝟒`

Fullwidth digits arrive by pasting from Japanese or Chinese statements. Proven end to end through `save_revision`: `saved narrative: 'Net leverage is ４.２x, headroom ٤٥%.'`.

**Repair direction:** refuse any character for which `str.isnumeric()` is true, or test the NFKC form. Land it after FP-05, so revisions already saved stay readable.

### FP-07 — A store or bundle that moves mid-set discards every paid run

**Base WARNING → CRITICAL; Saboteur + New Hire.** Locations: `caos/qualification/matrix.py:472-474`, with `_gate_readiness` at `:527` and `_projections_met` at `:636`; `caos/qualification/harness.py:631-636` and `:672-676`.

The harness promises that a store or bundle moving under a running set stops the set and returns what it performed. Two paths raise instead, so `_persist_performed` never runs and the spend is left with no snapshot:
- **Unguarded readers.** `_cited` catches `ROUTE_IDENTITY_INVALID`; the readiness and projection readers do not. Proven: `perform RAISED: ROUTE_IDENTITY_INVALID after 6 paid calls` / `qualification_performed rows: (0,) call_outcomes: (6,)`.
- **Bundle re-verification.** `_record` → `_unrun` → `named_objects` re-verifies the bundle, but only `ROUTE_IDENTITY_INVALID` is caught. Proven: `perform RAISED: AUTHORITY_BYTES_MISMATCH after 4 paid calls` / `qualification_performed rows: (0,)`.

The readers also catch different exception sets:
- projections catch `Refusal` only;
- registers also catch `ValueError`, `TypeError` and `UnicodeDecodeError`;
- forecast also catches `ValueError` and `TypeError`.

Tests cover only `ROUTE_IDENTITY_INVALID`, and only through a monkeypatched `_cited`.

**Repair direction:** read the route once per row under the `_ROW_REFUSALS` guard and pass it to every reader. Record any `Refusal` raised by `_unrun`, or compute `named_objects` once before the loop.

### FP-08 — The answer-key loader leaves fields unchecked; one path discards a paid snapshot

**Base WARNING → CRITICAL; Saboteur (two reviewers) + New Hire.** Locations: `caos/qualification/on_disk.py:269` (`ForecastValue(**_closed(...))`) and `:439` (`_text` used for `matched_text` and labels); `caos/qualification/matrix.py:296`, `:309` and `:1282-1283`.

- **`matched_text` is unbounded and may contain NUL.** The key passes `prepare` and the whole route is paid for. Then `record_performed` fails with psycopg `UntranslatableCharacter`, which surfaces as `STORE_UNAVAILABLE`. The snapshot is lost and `qualify.py` writes no capture. Proven.
- **Forecast values load as JSON floats.** Host values are strings, so such a key can never match, and this shows only after the spend. `NaN` makes the digest raise an untyped `ValueError`. Proven.
- **Labels are handled differently in two places.**
  - A 200-character label loads, then the digest refuses it with `BOUNDARY_TEXT_TOO_LONG`, although the `_LABEL_LIMIT` comment says the loader bounds labels.
  - The digest strips and NFC-normalises labels, but `assert_unambiguous` compares raw labels. So `"A"` and `"A "` both pass, then collide.
  - The digest's sort then compares a `list` with a `str` and raises a raw `TypeError`.
  - Proven: `'<' not supported between instances of 'str' and 'list'`.

The manifest is written by the operator, but the loader is the boundary that is meant to catch these mistakes before any spend. Related to AR-09.

**Repair direction:** put forecast values, `_expect` fields and labels through `_bounded`/`BoundaryText` at load. Accept strings only. Normalise labels identically in `assert_unambiguous` and in the digest, and sort on `json.dumps(entry)`.

### FP-09 — The receipt and the filing event name only the latest signer

**Base WARNING → CRITICAL; New Hire + Security Auditor.** Locations: `caos/deliverable/filing.py:235` (`signatures[0][0]`) with `:289` (`ORDER BY signed_at DESC,signed_by`); rebuilt the same way in `caos/deliverable/receipts.py:74`.

Several approvers may sign before the freeze (`one_opinion_per_signer`). But the detached receipt, and the `filing_payload` that `DELIVERABLE_FILED` binds, carry one `signed_by`: whoever signed last.
- Earlier co-signers are absent from the portable proof and from the filing event.
- The offline verifier can prove the independence of only one signer.
- Nothing in the field name or the docstring says "latest".

Proven: `signers on revision: 2` / `first signer named anywhere in receipt: False`.

**Repair direction:** carry the sorted list of all signers in the receipt and in the filing payload, and have the verifier require that list to be disjoint from `frozen_by` and `filed_by`.

### FP-10 — Gate definitions come from the change under test

**Base WARNING → CRITICAL; Saboteur + Security Auditor. Extends AR-07.**

Locations:
- `scripts/check_gate_config.py:107-125`, `:141` and `:211`
- `scripts/check_pr_size.py:85`
- `scripts/tracked.py:39`
- `scripts/host_manifest.py:57-60`
- `.github/workflows/ci.yml:103-107`
- there is no CODEOWNERS file

`check_gate_config` reads a few `pyproject.toml` keys, while each tool also reads files and keys that the PR controls. In scratch fixtures, each item below passed `check_gate_config` and loosened its gate:

- **Sibling config files:**
  - `pytest.ini`, `mypy.ini`, a nested `caos/ruff.toml`, `.coveragerc` and `complexipy.toml`;
  - `caos/.bandit`, after which bandit reported `issues 0` on `os.system`, `shell=True` and `eval`.
- **`pyproject` keys the gate never reads:** ruff `per-file-ignores`, `[[tool.mypy.overrides]] ignore_errors`, coverage `source` and `exclude_also`, complexipy `ignore-complexity`.
- **The `addopts` substring test:** `--cov-fail-under=80 --cov-fail-under=0` passes it, and the last value wins.
- **The secret scan:** `gitleaks git` uses the PR's own `.gitleaks.toml`. One `[[allowlists]] paths` block turned `leaks found: 1` (exit 1) into `no leaks found` (exit 0).
- **PR size:** `* -diff` in `.gitattributes` makes `--numstat` print `-\t-` for every file, and line 85 skips such rows. `changed lines: 5000` became `0`.
- **The `vendor` hole:**
  - `tracked.py` excludes all of `vendor/`;
  - ruff's `extend-exclude = ["vendor"]` matches at any depth;
  - mypy, coverage and the PR-size check exclude `vendor/`.

  So a new `vendor/helpers/x.py` escapes every gate, and `caos/vendor/x.py` escapes ruff.
- **Wiring checked for presence only:**
  - Hooks are matched by `id:` alone, so `entry: "true"`, `--exit-zero` or `stages: [manual]` all pass.
  - CI steps are not checked at all: deleting the mypy step, or appending `|| true` to pytest, passes.
- **The host pin:** `host_manifest.py` rewrites both `icm/HOST_INTEGRITY_v1.json` and `caos/methodology/host_pin.py`. An edit to `cash_flow.py` or a prompt block plus one regeneration is therefore green. The pin catches drift in a deployed copy, not an unreviewed change. (Reasoned from the code, not run.)

None of this is invisible in a diff, but nothing routes such a diff to a required reviewer.

**Repair direction:**
- Evaluate the gates with the base branch's `scripts/`, tool configs, `.gitleaks.toml`, `.gitattributes`, baselines and `ci.yml`.
- Refuse sibling config files at any depth, and compare whole `[tool.*]` tables.
- Allow only `vendor/deploy-v/**` under `vendor/`.
- Count `-` and binary numstat rows as failures.
- Add CODEOWNERS for all of these files and for the host pin.

### FP-11 — The suppression budget undercounts, and the new ratchet compares mismatched counters

**Base WARNING → CRITICAL; Saboteur + New Hire.** Locations: `scripts/check_gate_config.py:67-76` (`SUPPRESSIONS`), `:271` and `:281-294`; `.github/workflows/ci.yml:140-148`; `tests/gate_baseline.json`.

- **Forms that are not counted, some already in the tree:**
  - `#\s*noqa\b` misses `# ruff: noqa`. Seven test fixtures carry `# ruff: noqa: E501` (e.g. `tests/cp1a_contract_fixtures.py:3`) and each counts zero.
  - Also uncounted: `# flake8: noqa`, `# mypy: ignore-errors`, `# complexipy: ignore`, `@unittest.skip`, `skipIf`, `SkipTest`, `@typing.no_type_check`, and `@pytest.mark.live_provider` (which conftest drops from every default run).
  - Each form was shown to silence its tool while counting zero.
- **Totals per kind:** a harmless `E501` noqa can be swapped for an `S608` or `BLE001` one without changing the count.
- **The complexity baseline counts entries, not values:** editing a recorded complexity to 500 let a function grow from 15 to 28 while complexipy exited 0.
- **The `--against` ratchet (added concurrently):**
  - The base numbers were produced by the old regexes. A tightened regex therefore reads as new suppressions, and a narrowed one frees budget.
  - The working tree already rises against `HEAD` (`no_cover` 5→6, `noqa` 124→125, `skip` 0→7), so the ratchet fails its own change.
  - The job runs only on `pull_request`, not on pushes to `rebuild/databricks` or `main`.
  - The PR `types` list omits `edited`, so a PR retargeted after going green is not re-checked.

**Repair direction:**
- Count every form listed above.
- Budget suppressions per rule code and per path.
- Ratchet complexity per `(path, function, value)`.
- Count the base tree with the PR's counter.
- Run the job on push and on `edited`.

## Warnings

### FP-12 — `_eligible` never compares the pinned subject with the case's subject

**WARNING; Security Auditor.** Location: `caos/qualification/harness.py:459-477`.

The transplant check compares title, ceilings, profile and selection, model extension, research and documents, but not `pin.subject`.

A real approved input pinned for issuer OTHER / FY2019 executes under a case signed for ACME / FY2026, and the evidence binds the ACME set digest. Proven: `evidence set digest == signed set digest: True` / `signable: True`.

`test_real_approved_input_transplants_are_refused` checks ten faults, none of them the subject.

**Repair direction:** add `pin.subject != case.subject` to `_eligible`, and a `"subject"` fault to that test.

### FP-13 — Verdicts are not bound to their evidence, can be backdated and cannot be withdrawn

**WARNING; Security Auditor.** Locations: `caos/qualification/verdict.py:38-45` and `:105-112`; `caos/qualification/store.py:486-505`, `:496` and `:567`.

- The reviewer's document names the set, build and provider:model, but not `performed_sha256` or `adapter_version`. One document therefore records against any number of complete snapshots, including snapshots from another adapter version.
- `decided_at` need only be ≤ now. Proven: evidence recorded 2026-09-23, verdict decided 2001-01-01.
- `expires_at` has no upper bound.
- Verdict rows are immutable and no revocation exists.
- `provider + ":" + model` is not injective: `("openrouter:x", "m")` and `("openrouter", "x:m")` give the same string. Proven.

**Repair direction:**
- Bind `evidence_sha256` inside the document.
- Require `decided_at ≥ recorded_at`, by the store's clock.
- Cap the validity window.
- Add a revocation record.
- Compare provider and model as a pair.

### FP-14 — The release pack omits who signed and which model was qualified

**Base NOTE → WARNING; Security Auditor + New Hire.** Location: `scripts/release_pack.py:216-221`.

Each entry carries `{evidence_sha256, reviewer, decided_at, expires_at}`. `reviewer` is free text an ADMIN types. The authenticated `reviewer_id`, the provider, the model and the set digest are all absent. Production's model is set by environment (D7), so a pack's QUALIFIED does not say what it covers. Proven: `signer's reviewer_id in pack? False`.

**Repair direction:** emit `reviewer_id`, provider, model and set digest in each entry, and mark QUALIFIED only for the deployed model's identity.

### FP-15 — `qualify.py` resolves paid routes from a catalog it never verifies

**WARNING; Security Auditor (invariant 4).** Location: `scripts/qualify.py:276`.

`catalog=json.loads((bundle.root / CATALOG).read_text())` bypasses the verified reader `caos.methodology.vendor.catalog(bundle)`. Execution later checks only the pin's build, manifest and adapter.

Proven on a scratch copy of the bundle with its catalog tampered:
- the verified reader: `AUTHORITY_BYTES_MISMATCH`;
- the `qualify.py`-style read: accepted, `FULL_CREDIT_32 pathways now 9`.

**Repair direction:** use `catalog=catalog(bundle)` after `bundle.verify_pinned()`.

### FP-16 — `qualify.py` keeps a paid run's blobs in the OS temp directory

**WARNING; Saboteur.** Location: `scripts/qualify.py:286` (`blob_root = Path(mkdtemp(prefix="caos-qualify-"))`).

The script insists on a persistent PostgreSQL server, but it puts blobs in `$TMPDIR`, which macOS purges. `assert_orchestration_proof` re-reads those blobs, so the evidence can't be re-proven once they are purged. The purge itself was not triggered.

**Repair direction:** require an explicit persistent blob root, as is already done for `CAOS_QUALIFY_POSTGRES_URL`, and refuse temp directories.

### FP-17 — The portable verifier never checks the narrative against the records it binds

**WARNING; Security Auditor.** Locations: `caos/deliverable/verify_package.py:131-164` (`_contents`); `caos/deliverable/render.py:552-553` and `:571`.

A narrative figure is rendered from its own copy of `document_sha256`, `page` and `matched_text`. That copy is never checked against the bound record's `citations[citation_index]`, and a plain-string narrative with arbitrary figures is also accepted. This is the payload's one internal cross-reference, and it goes unchecked while the verifier reports that the package is internally consistent.

Proven:
- `narrative figure not in its record -> Verification(verified=True, reason=None)`, and the page shows the forged quote and page 99;
- `string narrative with uncited figures -> Verification(verified=True, reason=None)`.

**Repair direction:** in `_contents`, resolve each figure's `route_node_id` and `citation_index` in the bound record and require all three fields to match. Refuse a string narrative when the receipt carries identity fields.

### FP-18 — `check_tested` can be satisfied without a test driving the code

**WARNING; Saboteur.** Location: `scripts/check_tested.py:56`, `:66` and `:92`.

The checker walks only `tree.body`, so these escape it:
- a public lambda assigned at module level;
- a `def` inside an `if` or `try`.

Two other ways to satisfy it:
- `@anything.get(...)` reads as a route.
- Referenced names form one set for the whole suite, so a name that matches another module's (e.g. `verify`) counts.

Proven: six untested public functions in a scratch module passed. The real tree does not currently rely on any of these forms.

**Repair direction:** resolve references per module (import source plus attribute), walk `If`/`Try` bodies and module-level assignments, and match routes by the actual router object.

### FP-19 — `io_budget --assert` accepts declarations that declare nothing

**WARNING; Saboteur.** Location: `scripts/io_budget.py:43`, `:48` and `:69`.

It passes in all of these cases:
- a router in `reports/__init__.py` (`__init__.py` files are skipped);
- `IO_BUDGET: int` with no value;
- `IO_BUDGET = float("inf")`;
- `IO_BUDGET = None`;
- routes moved outside `caos/api/`, where "no request paths yet; nothing to budget" exits 0.

All of these were proven.

**Repair direction:** include `__init__.py`, require a non-negative int, and fail when `caos/api` is missing.

### FP-20 — The document register checks paths as strings

**WARNING; Security Auditor.** Location: `scripts/document_register.py:109` and `:157`.

`relative_to(root.parent)` does not normalise `..`, and the containment test is a `startswith("qualification/")` string check. `qualification/set-a/../../../../../../../../../../etc/hosts` marked `in_hand` is emitted as a register row with its size and digest, and the script exits 0. Proven.

**Repair direction:** `resolve()` the path, require `is_relative_to(repo / "qualification")`, and refuse symlinks.

### FP-21 — Two security tests always skip in CI

**WARNING; Saboteur (CI environment).** Location: `tests/test_frontend_modes.py:44-48`.

CI's backend job installs no Node, and the frontend job runs no pytest. These two tests therefore never run anywhere, and the run passes:
- `test_the_dev_proxy_strips_client_identity_and_injects_the_local_actor` (invariant 3);
- `test_production_build_contains_no_fixture_or_demo_route`.

Proven: `SKIPPED [2] tests/test_frontend_modes.py:48`.

**Repair direction:** run them in the frontend job, or fail on skips when `CI=1`.

### FP-22 — The forecast refuses negative EBITDA, negative CFO and tax refunds

**WARNING; Saboteur.** Location: `caos/calculators/cash_flow.py:50` (`_SIGNED`) and `:272-274`.

Every movement except `acquisitions_disposals` and `fx_perimeter` must be non-negative. A driver with `ebitda`, `cfo` or `cash_taxes` of `"-5"` refuses the whole request with `METHODOLOGY_INPUT_INVALID`. So any borrower with negative EBITDA or cash burn cannot be forecast, although CP-CF is an opt-in extension on any route that carries CP-1, CP-2G and CP-4, the distressed-restructuring pathways included. This fails closed, but the refusal tells the user their input is invalid when it is a supported credit profile. Proven by probe.

**Repair direction:** sign `ebitda`, `cfo` and `cash_taxes` (the ratios already return null on a non-positive denominator). If the refusal is deliberate, give it a named reason and record it in `decisions.md`.

### FP-23 — The new tolerance cap is absolute, not relative to the balances

**Base NOTE → WARNING; Saboteur + Security Auditor.** Location: `caos/calculators/cash_flow.py:34-36` (`MAX_TOLERANCE`, F62) and `_tolerance`.

`validate_driver_mapping` requires `scale = millions`, so a tolerance of `1000` means 1bn. With the current tree, a debt residual of 999m on a 1,000m balance passes with `outcome: PASS` and `status: complete`. Proven by probe.

This is mitigated because the tolerance must be an evidence-anchored CP-2G quote (`validate_forecast_bindings`). The cap is still wide enough to switch the one arithmetic check off for most borrowers.

**Repair direction:** bound the tolerance relative to the opening balances, or to a fixed amount per scale, and test the limit.

## Notes

| ID | Location | Issue | Repair direction |
| --- | --- | --- | --- |
| FP-24 | `harness.py:326-343` | Recorded producers are never compared with the prepared model, so a run whose calls used another model builds a `complete` snapshot. `record_verdict`'s `_models_recorded` refuses it at signing. | Check `call_outcomes.model` before building the matrix, so the snapshot is not recorded as complete. |
| FP-25 | `matrix.py:323-352` | The set digest appends optional fields untagged and by position, so a subject and an `expects_ready` list encode identically. Proven collision; blocked in practice by `valid_subject` and `_consumers`. | Tag each optional entry. |
| FP-26 | `harness.py:740-741` | `_answerable` checks that a citation's document digest is a member, but not that its `matched_text` occurs in that document, so an impossible key is paid for and then reads as a model miss. | Check each `matched_text` against the admitted text before any spend. |
| FP-27 | `on_disk.py:246` | A symlinked document is recorded under its target's filename, not the declared path's last segment. Proven. | Use `Path(declared).name` after the containment check, or refuse symlinks. |
| FP-28 | `release_pack.py:173-181`, `:212-215` | `except Refusal: continue` swallows `VERDICT_BINDING_INVALID`, contradicting the docstring. A malformed `prepared` item raises a raw `KeyError`/`ValueError`. | Skip only `VERDICT_EXPIRED`; refuse with a typed code otherwise. |
| FP-29 | `qualify.py:216`, `:273`; `qualification/ba-fy2025-covenant-refinancing/` | `--attempts 0` or a negative number means 1. A missing `CAOS_MODEL_PRICE` is a `KeyError` traceback. The set has tracked documents but no `qualification.json`, so it refuses `QUALIFICATION_SET_FILE_INVALID`; the other 18 sets reproduce their `RESULT.md` digests. | Validate the arguments; add or remove the set. |
| FP-30 | `matrix.py:29`, `:168`, `:960`, `:1001-1009`; `harness.py:106`; `proof.py:289`; `store.py:219`, `:245` | The docstrings say "seven" projection fields, but there are eight. `_LABEL_LIMIT` is defined three times. The guard at `matrix.py:960` cannot fire. The per-node artifact query is written four times. `proof.py:289`'s pragma comment claims a lock that is not taken. `asdict(...).values()` and `Evidence(*row)` depend on field order matching the SQL columns. | Tidy while fixing FP-01/FP-07; use named columns. |
| FP-31 | `render.py:189-193` | On a CP-CF route, the other sections print "None performed by the host on this route." while the CP-CF section says the host performed a projection. | Say "for this module". |
| FP-32 | `deliverable/canonical.py:197-207` and three other places | `selection=("LITE_CREDIT_22", "LITE_FULL_CREDIT_SCREEN")` is repeated four times without explanation. The deliverable proof re-checks owner restrictions for CP-5 only, never CP-CF. | One named table next to `verify_owner_restrictions`. |
| FP-33 | `filing.py:65-85` | The narrative's `saved_by` is never compared with the signers, so an approver can write and sign the same opinion; the test harness does exactly that. | Decide; if unintended, refuse with `APPROVER_NOT_INDEPENDENT`. |
| FP-34 | `receipts.py:83-100` | `read_filed_receipt` checks only `DELIVERABLE_FILED`. The sign and freeze event checks live in the one caller, `_publication`. | Move them in, or state the required order in its contract. |
| FP-35 | `deliverable/*.py` docstrings | Rationale cites `docs/DECISIONS.md` and `SYSTEM_SPEC.md` sections; neither file exists in this repo. | Point at `docs/rebuild/decisions.md` entries. |
| FP-36 | `cash_flow.py:32`, `:195`, `:311-316` | Two guards cannot fire. `MAX_WORK = 100_000` is unreachable: the ceilings allow at most 40 × 6 × 41 = 9,840. `_check_chain` compares a closing with its own six-decimal serialisation of add/subtract results. Tests reach them only by monkeypatching `MAX_WORK` to 1 or calling `_check_chain` directly. | Delete, or set `MAX_WORK` to a bound that binds; say what `_check_chain` guards. |
| FP-37 | `cash_flow.py:222`, `:83-97` | `opening.as_of_period_id` is validated and then ignored, and period order within a case is the caller's. Reordered periods chain in the given order, and only the residual check catches them. | Check that `as_of` precedes each case's first period and that fiscal years ascend. |
| FP-38 | `cash_flow.py:288-296` | The duplicate key includes the amount, so two equal instalments (e.g. two quarterly 10s in one annual period) refuse, while 9 + 11 sums. Now documented as the legacy rule; fails closed. | Key by `(pair, facility, instalment_id)`, or require one aggregated row per facility. |
| FP-39 | `cash_flow.py:351` | `fcf = cfo − capex − cash_interest − cash_taxes` treats `cfo` as pre-interest and pre-tax, and nothing documents that. A reported US GAAP CFO double-counts both; the residual catches it only if stated closes are independent. | Name the definition in SKILL.md and the calculator docstring. |
| FP-40 | `ci.yml:146`, `:148` | `${{ github.base_ref }}` is interpolated into `run:` scripts. Exploiting it needs the right to create branches in the base repository. | Pass it through `env:`. |
| FP-41 | `check_vocabulary.py:76`, `:121`; `check_gate_config.py` `_bundle_problems`; `.pre-commit-config.yaml`; `tests/test_icm.py:110-112`; `tests/test_gate_scripts.py:533`; `tests/test_ci_hygiene.py:22-27` | Vocabulary misses acronym prefixes (`PDFChunk`, `LLMWorkflow`) and directory names. The bundle-sync check parses YAML with a regex. pre-commit hooks are pinned by mutable tags. `test_icm.py:110-112` compares output with itself. The io-budget guard test runs without `--assert`. `test_ci_hygiene` refers to a Dockerfile and a Makefile that do not exist. | Fix in passing. |

## Closed or narrowed during the pass

The concurrent session landed these while the review ran; they are not counted:
- F62 capped the tolerance (FP-23 is the remaining gap).
- F64 made `_answered` a conjunct (FP-03 covers snapshots already stored).
- F65 fixed the renderer hash truncated after escaping.
- F70 made `freeze_in` check every signature.
- F58 widened the suppression regexes to `NOQA`, `skipif` and `pytest.skip(...)`.
- `check_tested` now counts only names that are read.
- `on_disk.py` dropped its duplicate `MAX_MANIFEST_BYTES`.

For a while during the pass, `render.py` changed without the renderer-hash constant in `verify_package.py`, and 12 package tests failed; the constant has since been updated.

What held up:
- A 40,000-case fuzz of `render._markdown` produced no crash and no unclosed tag.
- HTML escaping and the ZIP limits (size, ratio and overlap) held.
- At the stated ceilings, the calculator cannot overflow its 38-digit context: the largest debt is about 2e20 and the largest ratio about 4e26.
- The calculator uses Decimal only and normalises negative zero.

## Summary of the focused pass

Fix FP-01 first. It is the only finding that is CRITICAL at base severity, and `qualify.py`'s retry loop makes it routine: a case can be signed QUALIFIED over a run that concluded, never finished, or blocked for another reason.

Next, make every reader of a verdict re-derive it from the stored document and the runs (FP-02, FP-03). Then settle the filing contract: re-prove at filing (FP-04) and serve filed records from their own bytes (FP-05).

On the gate side, FP-10 and FP-11 share one root cause: take gate definitions and baselines from the base branch and route their changes to a CODEOWNER.

---

## Second pass — audit, architecture and Databricks skills

**Verdict: BLOCK.** Added **7 new findings: 5 CRITICAL after persona promotion and 2 WARNING**, plus **1 material extension** to an externally reported finding and **2 notes**. All five new CRITICAL findings have base severity WARNING; promotion is the adversarial-reviewer rule, not a claim that each demonstrates a security breach. The first-pass counts above describe their earlier snapshot.

**Scope and method:** five separate Astra xhigh scope assignments, at most three sub-agents concurrently. API/identity, store/graph, deployment/stand-ins and deliverables/qualification/calculators/gates completed sequential Saboteur → New Hire → Security Auditor passes. The model/methodology/evidence reviewer completed a focused test selection but was interrupted by the service's cybersecurity filter before completing its review. Its unfinished citation-performance observation is excluded. No code, tests, configuration, dependencies or vendor files were edited by this audit; only this report was appended. Another session continued editing the working tree. Finding-bearing source was re-read, with coordinating fingerprints taken on **2026-09-23 at 05:55 UTC**, against base commit 6aef8509b30203af425afa7ce9666613c54ba275.

**Skills applied:** [Adversarial Reviewer](/Users/ericguei/.codex/skills/adversarial-reviewer/SKILL.md), [Codebase Design](/Users/ericguei/.codex/skills/codebase-design/SKILL.md), [Senior Fullstack](/Users/ericguei/.codex/skills/senior-fullstack/SKILL.md), [Code Reviewer](/Users/ericguei/.codex/skills/code-reviewer/SKILL.md), its universal/Python/TypeScript guidance where relevant, and the repository's [Databricks Core](/Users/ericguei/Documents/caos-databricks/.claude/skills/databricks-core/SKILL.md), [Apps Python](/Users/ericguei/Documents/caos-databricks/.claude/skills/databricks-apps-python/SKILL.md), [Lakebase](/Users/ericguei/Documents/caos-databricks/.claude/skills/databricks-lakebase/SKILL.md), [Python SDK](/Users/ericguei/Documents/caos-databricks/.claude/skills/databricks-python-sdk/SKILL.md), [Model Serving](/Users/ericguei/Documents/caos-databricks/.claude/skills/databricks-model-serving/SKILL.md) and [DABs](/Users/ericguei/Documents/caos-databricks/.claude/skills/databricks-dabs/SKILL.md) with relevant references. These informed contract, configuration, concurrency and evidence checks; generic architecture/style preferences were not reported as bugs.

Deduplication covered AR-01–18 and the external store, model/evidence and deployment reports observed in the root findings.md. That file was replaced by another session during this review; external identifiers below name those observed reports, not necessarily the file's eventual contents.

### New critical findings

#### AR-19 — Losing a successful response body changes the retry's idempotency key

**Base WARNING → CRITICAL; Saboteur + New Hire.** Locations: [transport.ts:123](/Users/ericguei/Documents/caos-databricks/frontend/src/app/transport.ts:123), [commands.ts:127](/Users/ericguei/Documents/caos-databricks/frontend/src/app/commands.ts:127), [controls.tsx:148](/Users/ericguei/Documents/caos-databricks/frontend/src/sections/run/controls.tsx:148).

After a create command commits, the browser can receive HTTP 201 headers and then lose the response body. bodyOf() converts that transport failure to null; sendCommand() reports RESPONSE_INVALID; useCommand() reuses an intent only for offline. Retrying the unchanged request therefore sends a fresh key, permitting a second case or run.

**Evidence:** a temporary Vitest test mounted the real hook and called real createCase(), with a genuine Response whose stream failed during consumption. A simulated server ledger keyed by the actual outgoing headers recorded two different keys: first=RESPONSE_INVALID, keyReused=false, committed=2. The test passed. Duplicate database writes were not separately reproduced; the backend's keyed receipt lookup and fresh case UUID establish the consequence of sending a different key.

**Repair direction:** retain the intent for an unchanged request until a validated receipt or definitive refusal is received, including body-transfer and invalid-response outcomes. This is the Fullstack request/response contract and Codebase Design error-interface issue, not a defect in the server's same-key replay.

#### AR-20 — Concurrent checkpoint setup can leave one process without a worker

**Base WARNING → CRITICAL; Saboteur + New Hire.** Locations: [checkpoint.py:73](/Users/ericguei/Documents/caos-databricks/caos/graph/checkpoint.py:73), [checkpoint.py:79](/Users/ericguei/Documents/caos-databricks/caos/graph/checkpoint.py:79), [worker.py:446](/Users/ericguei/Documents/caos-databricks/caos/graph/worker.py:446).

Two processes initializing the checkpoint schema can read the same migration version and both insert its successor. The factory calls PostgresSaver.setup() without cross-process serialization; the store's separate migration lock does not cover this schema. The losing process's start_in_process() catches the database error and returns None. Uvicorn starts anyway, with no worker-start retry.

**Evidence:** two actual checkpointer(url) calls against one disposable database were synchronized immediately after the real migration-version query. Results were one UniqueViolation, SQLSTATE 23505, and one successful saver. SQL results were not mocked.

**Impact and repair:** one process loses its worker; the other can continue, so this is not proof of a fleet-wide outage. Serialize the complete checkpoint initialization through a database advisory lock and clean up failed initialization. No persistent pool-resource leak was established. The skill basis is concurrency analysis and keeping initialization constraints inside the factory's interface.

#### AR-21 — The deployment command cannot target Lakebase Autoscaling

**Base WARNING → CRITICAL; Saboteur + New Hire.** Locations: [preflight.py:67](/Users/ericguei/Documents/caos-databricks/scripts/preflight.py:67), [databricks.yml:71](/Users/ericguei/Documents/caos-databricks/databricks.yml:71), [databricks.yml:92](/Users/ericguei/Documents/caos-databricks/databricks.yml:92), [enterprise_deploy.py:252](/Users/ericguei/Documents/caos-databricks/scripts/enterprise_deploy.py:252).

Spec §4 permits Autoscaling endpoints, and the runtime supports LAKEBASE_AUTOSCALING_ENDPOINT. The deployment interface nevertheless requires an instance, uses the Provisioned lookup in preflight and E8, always declares a database resource, and sets CAOS_LAKEBASE_INSTANCE. That variable takes precedence over the runtime's Autoscaling setting.

**Evidence:** the installed SDK successfully fetched an Autoscaling endpoint and minted its credential from a loopback stand-in. Supplying the same endpoint to preflight instead requested /api/2.0/database/instances/projects/... and failed with an instruction to create an instance. With the bundle-shaped instance environment, credential minting used /database/credentials and refused; with only LAKEBASE_AUTOSCALING_ENDPOINT it succeeded through /postgres/credentials.

**Impact and repair:** valid new Autoscaling deployments cannot traverse the documented command. Databricks currently prohibits creation of new Provisioned databases after March 12, 2026, while supporting existing ones. Carry the selected resource type through deployment and verification; preserve existing Provisioned bindings, because changing an existing app's resource type changes its Postgres role. This is not a claim that existing Provisioned deployments fail. [Official Lakebase Apps documentation](https://docs.databricks.com/aws/en/dev-tools/databricks-apps/lakebase).

#### AR-22 — The release pack removes the provider/model scope of qualification

**Base WARNING → CRITICAL; Saboteur + Security Auditor.** Locations: [release_pack.py:203](/Users/ericguei/Documents/caos-databricks/scripts/release_pack.py:203), [release_pack.py:216](/Users/ericguei/Documents/caos-databricks/scripts/release_pack.py:216), [release_pack.py:258](/Users/ericguei/Documents/caos-databricks/scripts/release_pack.py:258).

qualified_pathways() selects by build and adapter, validates the supplied evidence, then drops its provider/model bindings from the emitted verdict. The pathway gets the general status QUALIFIED without showing which execution identity was qualified.

**Evidence:** a valid signed fixture in a disposable database used provider openrouter/google-ai-studio/high/65536 and model google/gemini-3.8-flash. Its release-pack row marked FULL_CREDIT_32/COVENANT_REFINANCING QUALIFIED and included only evidence digest, reviewer and dates. Neither provider nor model survived. Spec §3.4 explicitly distinguishes OpenRouter tests from gateway coverage.

**Impact and repair:** misleading release evidence, not an API qualification-binding bypass; current_verdict() still validates the exact evidence it receives. Preserve provider/model in the emitted verdict and status, and require the expected execution identity when claiming qualification for a deployment. This is distinct from AR-15's unsent reasoning-effort setting and follows the model-serving identity and interface-preservation checks.

#### AR-23 — Contradictory scalar answer keys reach model execution

**Base WARNING → CRITICAL; Saboteur + New Hire.** Locations: [matrix.py:1280](/Users/ericguei/Documents/caos-databricks/caos/qualification/matrix.py:1280), [on_disk.py:305](/Users/ericguei/Documents/caos-databricks/caos/qualification/on_disk.py:305), [harness.py:730](/Users/ericguei/Documents/caos-databricks/caos/qualification/harness.py:730).

The ambiguity check covers register and readiness conflicts but ignores projection expectations. The loader rejects identical triples, yet accepts both CP-0 qa_status=Passed and CP-0 qa_status=Restricted. Those conjunctive scalar expectations are impossible to satisfy.

**Evidence:** a valid one-case LITE fixture with that pair passed real prepare(), with zero calls so far, then real perform() made three scripted-provider calls and completed. Only the resulting matrix reported projections_met=False and signable=False. The database and gate approvals were real; no paid provider was contacted.

**Impact and repair:** an authoring error consumes a route's model work before being exposed, contrary to the preflight promise. Reject different expected values for the same module/scalar-field pair at the shared preflight interface; preserve multiple membership expectations for tuple/list fields. Existing spend ceilings still apply, and the failed case does not become signable.

### New warnings

#### AR-24 — Healthy long-running nodes report stale workers

**WARNING; Saboteur.** Locations: [work.py:259](/Users/ericguei/Documents/caos-databricks/caos/store/work.py:259), [worker.py:183](/Users/ericguei/Documents/caos-databricks/caos/graph/worker.py:183), [runtime.py:177](/Users/ericguei/Documents/caos-databricks/caos/graph/runtime.py:177), [health.py:183](/Users/ericguei/Documents/caos-databricks/caos/api/health.py:183).

Heartbeats run before each node but not during its execution. They become stale after 30 seconds even though the provider timeout is 120 seconds and the normal lease lasts 300 seconds. In a disposable database, a WORKING beat aged to 31 seconds produced WORKERS_STALE while the run's lease remained live.

This creates false operational alarms; E6 also requires the worker code to be OK. Worker status does not change API readiness, and no load-balancer outage was demonstrated. Align freshness with supported uninterrupted work or send independent bounded heartbeats using a separate connection. This is distinct from PID collisions and AR-11's queued-probe cancellation.

#### AR-25 — Malformed forecast keys escape the loader's typed refusal

**WARNING; Saboteur.** Locations: [on_disk.py:269](/Users/ericguei/Documents/caos-databricks/caos/qualification/on_disk.py:269), [matrix.py:1289](/Users/ericguei/Documents/caos-databricks/caos/qualification/matrix.py:1289).

The forecast loader checks field names and constructs ForecastValue without validating the annotated string types. A small scratch manifest containing values=[{name: [], value: {}}] loaded successfully; the harness's first ambiguity check then raised TypeError because the list name is unhashable.

Validate both fields at the loading interface and return QUALIFICATION_SET_FILE_INVALID. Exposure is an operator-loaded manifest, not a remote API; the failure needs no provider call. This is separate from AR-09's allocation problem.

### Material extension to an existing finding

#### R2-E1 — The shipping gate accepts the uploaded tree from external deployment C2

**Base WARNING → CRITICAL; Saboteur + New Hire.** Locations: [check_gate_config.py:79](/Users/ericguei/Documents/caos-databricks/scripts/check_gate_config.py:79), [check_gate_config.py:171](/Users/ericguei/Documents/caos-databricks/scripts/check_gate_config.py:171), [check_gate_config.py:304](/Users/ericguei/Documents/caos-databricks/scripts/check_gate_config.py:304).

External C2 already reports that sync exclusions remove caos/qualification and the uploaded app cannot import. This pass additionally tested the proposed protection: _bundle_problems() returned no problems, its matcher said qualification/** did not match caos/qualification/store.py, and SHIPPED contained no qualification-package path. The actual CLI v1.17.0 uploaded 450 files from a scratch checkout, including zero qualification-package files. The shipped-file gate still returned an empty problem list; importing caos.api.site from the reconstructed upload raised ModuleNotFoundError for caos.qualification.

The protection therefore does not close C2. Validate the actual complete runtime file set and import from the uploaded tree, instead of relying on separately approximated CLI glob semantics and a small sentinel list. This applies Codebase Design's requirement that tests exercise the same interface as callers. It is counted as an extension, not a second copy of the missing-package finding.

### Notes

- **R2-N1 — The UUID-parser architecture guard scans a removed directory. NOTE; New Hire.** [test_api_routes.py:1274](/Users/ericguei/Documents/caos-databricks/tests/test_api_routes.py:1274) scans server/api, which does not exist. It inspected zero files while caos/api contained 29. Point it at the current package and require a nonempty scan. No current parser vulnerability was established.
- **R2-N2 — Qualification capture omits register-key failures. NOTE; New Hire.** [qualify.py:165](/Users/ericguei/Documents/caos-databricks/scripts/qualify.py:165) emits the other comparison outcomes but omits registers_met. A probe whose only failed comparison was registers_met=False emitted complete=false and a proven row with no visible failed comparison. The persisted snapshot retains the field; add it to the CLI capture. This is lost diagnostics, not lost underlying evidence.

### Prior findings and rejected leads

- **Reconfirmed open:** AR-04 and AR-12 through isolated identity probes; AR-07, AR-08, AR-09 and AR-18 through bounded configuration/render/manifest/ceiling counterexamples. AR-16 produced four failing explicit-infinity PDF cases in the model review's focused suite.
- **Relevant fault paths remain present:** AR-01, AR-02, AR-03 and AR-13 after current-source rechecks; AR-10's verdict-before-receipt ordering is unchanged, but its race was not rerun. AR-05, AR-06 and AR-17's relevant deployment code is unchanged. Other first-pass entries were not closed by this review.
- **External deployment duplicates reproduced:** C1's comma-containing model_price fails real CLI parsing; C2's upload cannot import the app; C3's production stand-in deploy fails on the missing workspace/export lock route. These are existing findings, not added again to the new count.
- **External reports resolved in current bytes:** model ME-C4's host calculator/manifest pin mismatch is repaired. ME-N1's missing decision entries is repaired: decisions.md now records F1–F70. Deployment N4 is partly repaired: its preflight example now includes price and run ceiling.
- **Rejected stale skill assumptions:** uv.lock plus pyproject.toml supports the pinned Python interpreter without a root requirements.txt; DAB app.config.env is supported. Those patterns are not defects merely because older skill examples use another configuration. [Databricks dependency documentation](https://docs.databricks.com/aws/en/dev-tools/databricks-apps/dependencies), [bundle resource reference](https://docs.databricks.com/aws/en/dev-tools/bundles/resources#app).
- No additional confirmed calculator arithmetic or filing-authority defect was found. No new runtime access-control bypass was demonstrated. The unfinished model-review observation is excluded rather than presented as a completed security finding.

### Verification and limits for this pass

| Check | Result |
| --- | --- |
| API/identity/admission/idempotency/wire/site selection | 136 passed |
| Store/graph/Lakebase/PostgreSQL race selection | 56 passed |
| Deployment/workspace/platform selection | 15 passed |
| Model/methodology/evidence selection reported before service interruption | 233 passed, 4 failed on existing AR-16 |
| Isolated render/package rerun | 62 passed, 1 database-dependent test skipped |
| Frontend response-body-loss counterexample | 1 passed, demonstrating the defect |
| Checkpoint race, heartbeat and qualification counterexamples | Completed in disposable UUID databases before the test database outage |

The larger deliverable/qualification/calculator/gate selection was interrupted when the shared local PostgreSQL entered recovery mode. It had an earlier untriaged failure and later cascading connection/setup failures; interruption and teardown produced no reliable final counts or first-failure traceback. It is not reported as passing. The shared database was not restarted. These infrastructure errors are not added as application findings.

The coordinating reviewer ran Ruff without its cache and the read-only check_icm, check_gate_config, check_tested, check_vocabulary and io_budget --assert gates; all returned success at their check times. Counterexamples above show why those successes do not establish correctness of the shipping and architecture guards. The Fullstack analyzer scanned 453 files; its heuristic secret alerts were test fixtures, its production HTTP alert was loopback-only, and its SQL pattern flagged parameter placeholders. Its scores and alerts were used as leads, not accepted as findings or measured coverage.

Python checks used PYTHONDONTWRITEBYTECODE=1, uv run --no-sync, and pytest --no-cov -p no:cacheprovider. Database probes used only disposable caos_test_<uuid> databases on the existing local test server. CLI deployment probes used a scratch checkout and loopback workspace, with CLI state outside this repository. No live workspace deployment, paid model call, package installation or code fix was performed. Actual enterprise grants, Apps proxy behavior and live model quality remain unverified. This was a focused audit, not a passing full-CI certification.

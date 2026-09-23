# Round 4 — Deliverable and qualification (DQ)

**Scope.**
- **Reviewer:** Claude Opus 5.5 (`claude-opus-5-5`) at effort max, adversarial-reviewer skill. The harness refused the report file from the subagent; the orchestrator saved this text from the reviewer's final message verbatim.
- **Commit:** `git log --oneline -1` gives `653dc9c Findings round 3: 100 findings patched across the store, worker, graph, model seam, deployment path, edge, evidence, deliverable and frontend` (full hash `653dc9ce91a73137360c43b81f14284d324de58f`).
- **Worktree:** `pwd` gives `/Users/ericguei/Documents/caos-databricks/.claude/worktrees/agent-a3c651bc6f897ace4`.
- **Read in full:**
  - `caos/deliverable/{canonical,filing,package,receipts,render,revisions,verify_package}.py`
  - `caos/qualification/{harness,matrix,on_disk,proof,store,verdict}.py`
  - `caos/api/commands/{deliverable,qualification}.py` and `caos/api/reads/{reports,qualification}.py`
  - `scripts/{qualify,release_pack,document_register,io_budget,check_gate_config,check_tested}.py`
  - the run, attempt and command store paths these call, and their tests.
- **Baseline tests** (targeted, `-n 4`, `--no-cov`):
  - deliverable, filing, package, render, revision, release-pack, gate-script and parity-render suites: 320 passed.
  - qualification suites, including `test_qualify_script.py`: 364 passed.
  - `test_governed_write_routes.py`, `test_revision_sections.py`, `tests/parity/test_render.py` and `test_deliverable_render.py`: 109 passed.
  - On the tree, `check_tested.py`, `io_budget.py --assert`, `check_gate_config.py` and `document_register.py` all exit 0.
- **Probes:** 26 pytest probes and one script under `docs/rebuild/round4/probes/deliverable/`. All pass, meaning each reproduces what it states. Run each from the worktree root with:
  `PYTHONPATH=tests CAOS_TEST_POSTGRES_URL=postgresql://postgres:local-test-admin-only@127.0.0.1:55437/postgres CAOS_REQUIRE_POSTGRES=1 uv run pytest --no-cov -p no:cacheprovider -p conftest -s -q docs/rebuild/round4/probes/deliverable/probe_<name>.py`
  `probe_qualify_leak.py` is a plain script: `uv run python <file>` with `CAOS_TEST_POSTGRES_URL` set.
- **Hygiene:**
  - The probes use the suite's own fixtures, so every database they touch is a fixture-made `caos_test_<uuid>` that is dropped afterwards.
  - No `r4_dq_` database was made by hand and no paid call was made.
  - Nothing under `vendor/deploy-v` was written; vendored-file mutations happen in a `tmp_path` copy.
  - Three databases from the reviewer's baseline run are still on the shared server, because the reviewer could not prove sole ownership: `caos_qualify_17bd2121b00c4be98678a197e1262be4`, `caos_qualify_bc396e28d4334be28aeed08ed699d469`, `caos_qualify_250a4518f87f41d78380c0206768a4ad`. They were created 10:45:20–22 UTC by `tests/test_qualify_script.py`, which never drops the database it creates (DQ-12).
- **F108 comparison** (`git diff 04c10a9` over the scope: 17 files, +1095/−241):
  - **Claimed and done:**
    - FP-01's three rules and the list of codes a case may declare.
    - FP-02: pins read through `route_pin`, and coverage only by cases that produced output.
    - FP-04: the re-proof sits in the route, as its docstring says.
    - FP-05, FP-08, FP-12, FP-15, FP-17 and FP-20.
    - FP-16: a named blob root is required, though temp directories are not refused.
    - AR-09, AR-10, AR-18, AR-23, AR-25 and SI-5/R2-N2.
    - FP-14/AR-22, in the JSON only.
  - **Claimed and not done:**
    - N8/SI-4: `_digested` is untouched (DQ-14).
    - FP-18: `check_tested.py` is untouched (DQ-11).
    - The loader's typed code for readiness ids (DQ-14).
    - FP-19's `__init__.py` bullet and its spellings other than `float(...)` (DQ-10).
    - FP-13's backdating half (DQ-13).
    - FP-14/AR-22 in `RELEASE_PACK.md` (DQ-4).
    - FP-03's forged-row half (DQ-3).
  - **Done and not claimed:**
    - FP-06 (`_is_figure`).
    - FP-07 (`_guarded`, `_record`), but incomplete (DQ-5).
    - FP-27 and FP-29.
    - FP-28, in part (DQ-3).
  - **Done differently:**
    - FP-09 keeps naming the latest signer (documented).
    - FP-14's deployed identity is an optional filter, not a requirement.

**Verdict: CONCERNS.** No finding meets this round's CRITICAL bar: data loss, a breach, a CLAUDE.md invariant, or an outage. DQ-1 is the most serious: the qualification gate fails open for a declared key exactly when the host could not measure it.

## Findings

### DQ-1 [WARNING] A declared key the matrix could not compare is waived beside a met HANDOFF_BLOCKED, so a wrong answer is recorded complete and signed
- **Where:**
  - `caos/qualification/matrix.py:480-500`: `_guarded` returns `None` for any `_ROW_REFUSALS` code.
  - `caos/qualification/matrix.py:530-547`: every reader is now guarded.
  - `caos/qualification/store.py:68-79`: `_answered` tests declared keys with `is False`, and under an expected refusal it never reads `proven`.
  - `caos/qualification/store.py:83-103`: `answered_document` applies the same rule.
  - `caos/qualification/store.py:177-212`: `complete`.
  - `caos/qualification/store.py:596-599`: `record_verdict` re-derives with that same rule.
- **Verified:** yes, with `probe_waived_key.py` (two scenarios, real harness runs, real store):
  ```
  control row: proven=True refusal=None expected_refusal_met=True registers_met=False complete=False
  faulted row: proven=False refusal=AUTHORITY_BYTES_MISMATCH expected_refusal_met=True registers_met=None complete=True
  stored complete=True document_complete(stored)=True
  record_verdict accepted; current_verdict -> BoundaryText(value='Probe reviewer')
  control: projections_met=False blocked_met=False complete=False
  faulted: refusal=ROUTE_IDENTITY_INVALID expected_refusal_met=True projections_met=None blocked_met=None complete=True
  ```
- **Failure:**
  - **Setup:** a case declares `expected_refusal=HANDOFF_BLOCKED` plus keys the run answers wrongly:
    - CP-0's T8 cell for CP-5 expected `BLOCKED`; the run wrote `READY`.
    - CP-0's `qa_status` expected `Restricted`; it said `Passed`.
    - `expects_blocked=["CP-5"]`; CP-0 cleared CP-5.
  - **With working readers**, the snapshot is unsignable.
  - **Fault:** while the matrix is being built, either:
    - a vendored file moves under an unchanged manifest, so the register reader's `load_vendor_contract` refuses `AUTHORITY_BYTES_MISMATCH`; or
    - the pin stops reading, so `resolved_route` refuses `ROUTE_IDENTITY_INVALID` in the projection and readiness readers.
  - **What goes wrong:**
    - Each declared key becomes `None`.
    - `_answered` returns `expected_refusal_met and not missed`, so `complete` is True.
    - `_persist_performed` stores `complete=true`, `record_verdict` accepts a QUALIFIED verdict, and `current_verdict` serves it.
  - F64's rule ("keys declared beside an expected refusal are measured too") therefore fails open precisely when the host could not measure them.
  - The row does show the refusal, but `complete` is the host's guard against signing unmeasured work.
  - The register path predates round 3. FP-07's `_guarded` extended it to the forecast, readiness, blocked and projection readers.
- **Fix:**
  - Make an unmeasured declared key block signing: have `_row` either mark the declared keys whose reader refused, or answer `False` while keeping the reader's refusal separate from the proof's, as `proof_refusal` already is.
  - Have `_answered` and `answered_document` refuse such a row even beside a met refusal.
  - Pin both probe scenarios as tests in `tests/test_qualification_harness.py`.

### DQ-2 [WARNING] Sixteen of the seventeen declarable refusals can never be met, yet a set declaring one is prepared and paid for
- **Where:**
  - `caos/qualification/matrix.py:78` (`_REFUSED`), `:89-109` (`DECLARABLE_REFUSALS`), `:613-639` (`_refusal_met`).
  - `caos/qualification/harness.py:756-761` (`_answerable`).
  - `caos/qualification/on_disk.py:481-498` (`_refusal`).
  - `caos/graph/runtime.py:561-567`: a node refusal is explained and re-raised, and the run stays RUNNING.
  - `caos/store/runs.py:425-429`: `fail_run`, whose only callers are tests.
- **Verified:** yes, with `probe_declared_refusal.py`. `grep -rn "fail_run\|RunStatus.FAILED" caos` finds no production transition to FAILED.
  ```
  prepare accepted expected_refusal=CITATION_NOT_LOCATED
  perform #1: stopped=CITATION_NOT_LOCATED matrix=None complete=False
  perform #2 (the retry): stopped=CITATION_NOT_LOCATED matrix=None complete=False
  provider calls paid for this case: 2
  run status after both performs: RUNNING
  last attempt's recorded refusal=CITATION_NOT_LOCATED on_last_attempt=True
  _refusal_met(RUNNING run, declared code) = False
  attempt ordinal=3 started_at=2026-09-23 10:22:45.757508+00:00 refused=False
  after fail_run (test-only transition) and a skewed retry with no refusal as the last ordinal: _refusal_met = True
  ```
- **Failure:**
  - **Setup:** a case declares `CITATION_NOT_LOCATED` over a document that lacks the quote.
  - **What happens:**
    - `_refusal` and `_answerable` accept the case.
    - The node refuses exactly as declared, and the code is written on its last attempt.
    - A refused node never ends a run, and nothing in production writes FAILED, so the run stays RUNNING.
    - `perform` stops with no matrix, and every retry that `qualify.py --attempts` buys does the same.
  - **Consequence:** `_refusal_met` is reachable only through BLOCKED or FAILED, so the key cannot be answered by any run the host produces.
    - FP-01's rule "a stored code must sit where the run stopped" is dead outside tests.
    - The harness's own rule, that an unanswerable key is refused before the first call, is broken for 16 codes.
    - Only HANDOFF_BLOCKED, through `run_blocking_verdicts`, can be met.
  - **Secondary, where the branch is reachable:**
    - The "last attempt" is chosen by `ORDER BY started_at DESC, attempt_id DESC`, i.e. the clock, then a random UUID.
    - `run_attempts.ordinal` is unique per run and node and assigned under the run lock, but is not used.
    - A retry whose clock read earlier lets an earlier attempt's stale refusal match.
- **Fix:**
  - Either restrict `DECLARABLE_REFUSALS` to `{HANDOFF_BLOCKED}` until a declared node refusal can end a run, or give that refusal a terminal outcome recorded the way `run_blocking_verdicts` records a Blocked answer, and read that.
  - Order the last attempt by `ordinal`.
  - Test: `prepare` refuses a set declaring `CITATION_NOT_LOCATED`, or the probe's run meets it.

### DQ-3 [WARNING] Verdict and pack re-derivation stops at the snapshot's own flags: a stale FP-01-shape snapshot and a forged self-consistent one both qualify a pathway
- **Where:**
  - `caos/qualification/store.py:106-153`: in `document_complete` and `_record_finished`, `expected_refusal_met is True` waives the record's status.
  - `caos/qualification/store.py:632-661`: `current_verdict`.
  - `scripts/release_pack.py:180-238`: `_snapshot_pins` and `_covers` read `status`, `proven` and the row flags from `performed_json`.
  - `scripts/release_pack.py:307-332`: in `_current`, `evidence_at` returning `None` means a silent skip.
- **Verified:** yes, with `probe_release_pack.py`:
  ```
  record status=COMPLETE row expected_refusal_met=True complete=True document_complete=True
  signed, current, pack covers [('FULL_CREDIT_32', 'COVENANT_REFINANCING')]
  store says run status=RUNNING artifacts=0
  pack covers [('FULL_CREDIT_32', 'COVENANT_REFINANCING')]
  a verdict over evidence contradicting its snapshot -> {}
  ```
- **Failure:**
  - **(1) Stale snapshot.** A snapshot whose row says `expected_refusal_met=True` over a COMPLETE record passes `document_complete`, `record_verdict` and `current_verdict`, and the pack marks its pathway QUALIFIED.
    - This is the shape pre-FP-01 code recorded for a run that finished after a stale attempt refusal. Today's `_refusal_met` cannot produce it.
    - F108 says completeness is re-derived "rather than trusting stored flags". In fact it re-reads the flags the old code wrote.
  - **(2) Forged snapshot.** A self-consistent set of three rows is inserted directly: a `performed_json` that digests to its key, a matching evidence row, and a verdict row. It sits over a run the store holds as RUNNING with zero artifacts, and the pack relays it as QUALIFIED.
    - The pack takes the run's status and `proven` from the document.
    - It never reads `runs` or `artifacts`, and never re-runs `_models_recorded` or the proof.
    - FP-03's forged-row half is neither fixed nor listed in next.md.
  - **(3) Contradictory row.** An evidence row that contradicts its snapshot is dropped without a word. Yet `_current`'s comment says every refusal other than "not current" is raised (FP-28).
- **Fix:**
  - In `document_complete`, refuse a row whose `expected_refusal_met` is True unless its record is BLOCKED or FAILED.
  - In the pack, compare each covering run's `runs.status` and artifact count with the document, and call `_models_recorded`.
  - Raise `VERDICT_BINDING_INVALID` for a verdict whose evidence exists but does not join its snapshot.
  - Log the keyed-digest (HMAC/KMS) item FP-03 named in next.md.

### DQ-4 [WARNING] The release pack is not a function of its stated inputs: the identity filter is unrecorded, the reader's copy drops the identity, and the bytes follow the session time zone
- **Where:**
  - `scripts/release_pack.py:403-423`: `build_pack` records only `store.as_of`.
  - `scripts/release_pack.py:319-320`: the identity filter.
  - `scripts/release_pack.py:430-478`: `render_markdown` prints only the evidence prefix and the expiry.
  - `scripts/release_pack.py:342-343`: `decided_at.isoformat()` renders in the connection's time zone.
- **Verified:** yes, with `probe_release_pack.py`:
  ```
  filtered pack == empty-store pack: True
  filtered pack row: NOT_QUALIFIED -- enabled; no current verdict for this build and adapter in the store read
  RELEASE_PACK.md row: | `FULL_CREDIT_32` | `COVENANT_REFINANCING` | QUALIFIED | enabled; a current signed verdict for this build and adapter covers it | `7a0026581d8af7fb…` until 2026-10-18T00:00:00+00:00 |
  PGTZ=UTC: decided_at=2026-09-18T00:00:00+00:00
  PGTZ=Asia/Tokyo: decided_at=2026-09-18T09:00:00+09:00
  packs identical: False
  ```
- **Failure:**
  - **Two inputs, one pack:**
    - `--provider/--model` naming an identity other than the verdict's emits a pack byte-identical to one over an empty store.
    - Its reason ("no current verdict for this build and adapter") is false for that pack.
    - Nothing records that a filter ran, or which adapter version was judged.
  - **The reader's copy drops the identity:** `RELEASE_PACK.md` ("the same facts for a reader") shows QUALIFIED with no provider or model. FP-14/AR-22 is closed in the JSON only.
  - **One input, two packs:**
    - The same store read under `PGTZ=UTC` and under `PGTZ=Asia/Tokyo` emits different bytes, against the module's "reproducible by construction".
    - The byte-identity test covers only the pack built without a store.
- **Fix:**
  - Record the identity (or "any") and `CANONICAL_ADAPTER_VERSION` under `store`, and in the NOT_QUALIFIED reason.
  - Print provider and model in the Markdown verdict cell.
  - Render every timestamp as `.astimezone(UTC).isoformat()`.
  - Add a byte-identity test for a store pack across `PGTZ`.

### DQ-5 [WARNING] FP-07's bundle half still discards a paid snapshot, and FP-07 is absent from F108
- **Where:**
  - `caos/qualification/matrix.py:469-477`: `build_matrix` ends with `build_id=bundle.build_id`, which re-reads the manifest.
  - `caos/qualification/harness.py:370-383`: `perform` builds the matrix before `_persist_performed`.
- **Verified:** yes, with `probe_lost_snapshot.py`:
  ```
  perform raised AUTHORITY_BYTES_MISMATCH
  qualification_performed rows=0 call_outcomes=3 artifacts=3 provider calls=3
  ```
- **Failure:**
  - FP-07 asked that a store or bundle moving under a running set stop the set and keep what it performed.
  - Round 3 guarded the row readers and `_record`'s `_unrun`.
  - When the manifest itself moves after the proofs (the shape of the suite's own `test_matrix_refuses_manifest_changed_after_its_last_proof`):
    - `build_matrix` raises out of `perform`, and `_persist_performed` never runs.
    - Three paid calls leave no snapshot.
    - `qualify.py` dies before writing its capture.
  - The code carries FP-07 comments, but F108 neither claims nor defers FP-07.
- **Fix:**
  - In `perform`, catch a `Refusal` from `build_matrix` and persist `PerformedSet(performed, None)`, as a stopped set is persisted.
  - Test that a manifest mutated mid-matrix leaves exactly one `qualification_performed` row.
  - Add FP-07 to the ledger.

### DQ-6 [WARNING] `qualify.py` captures the attempts, charges and generation ids of the first case's run only
- **Where:**
  - `scripts/qualify.py:400-401`: `run_id = prepared[0].input.run_id`.
  - `scripts/qualify.py:129-136`: `_capture` selects attempts `WHERE t.run_id=%s`.
- **Verified:** yes, with `probe_qualify.py::test_a_multi_case_capture_carries_the_first_runs_attempts_only`. This drives `qualify.main` as an operator runs it, with the fake provider:
  ```
  exit=0 cases in result=2
  provider calls=6
  store run 3fefd1f2-becc-4edc-a505-6f21285cd112: attempts=3 charged=3
  store run 85de7dca-344b-4f82-b66e-61fdc7e79832: attempts=3 charged=3
  capture run_id=3fefd1f2-becc-4edc-a505-6f21285cd112 attempts=3
  ```
- **Failure:**
  - AR-18 made multi-case sets admissible.
  - The capture is documented as what "reconciles a vendor bill", yet it lists only the first run's three attempts.
  - The second run's three charged calls are missing, and the script still exits 0.
- **Fix:**
  - Select attempts for every prepared run (`t.run_id = ANY(%s)`, with `run_id` in each row).
  - Extend `test_a_set_of_more_than_one_case_can_be_admitted` to assert that both runs' attempts appear.

### DQ-7 [WARNING] `qualify.py --run-ceiling 0` is replaced by `ceiling / cases`, and the run spends
- **Where:** `scripts/qualify.py:309-311` (`args.run_ceiling = args.run_ceiling or (...)`).
- **Verified:** yes, with `probe_qualify.py::test_a_run_ceiling_of_zero_is_replaced_and_the_run_spends`:
  ```
  --run-ceiling 0 -> preamble run_ceiling=5.000000
  stored budget_ceiling=5.000000 spent=0.0000123 calls=3 exit=0
  ```
- **Failure:**
  - `Decimal("0")` is falsy, as are `0.00` and `-0`.
  - So an operator who caps each run at zero, the natural way to ask for "spend nothing", gets `ceiling / cases` instead, and three paid calls go out.
  - Had the zero reached the harness, it would have been refused: `validate_spend(0)` accepts zero, and `_affordable` then refuses the set.
  - The budget therefore fails open at the CLI: invariant 8's rule, broken one layer above the store. The set ceiling still bounds the total.
- **Fix:**
  - Derive the run ceiling only `if args.run_ceiling is None`; pass an explicit value through and let `_affordable` refuse it.
  - Test that `--run-ceiling 0` exits 2 with nothing spent.

### DQ-8 [WARNING] The portable verifier checks the five central-directory members, not the whole archive: a hidden sixth `deliverable.html` verifies, and a streaming extractor shows it
- **Where:**
  - `caos/deliverable/verify_package.py:33-54`: `_directory` pins the central directory to the end and counts five entries.
  - `caos/deliverable/verify_package.py:72-94`: `_member` reads each member through its central-directory offset.
  - Nothing requires the local entries to cover the archive without gaps.
- **Verified:** yes, with `probe_package.py::test_a_sixth_local_entry_is_invisible_to_the_verifier`:
  ```
  genuine package verify -> (True, None)
  smuggled package verify -> (True, None)
  local headers in file order: ['deliverable.html', 'payload.json', 'receipt.json', 'render.py', 'verify_package.py', 'deliverable.html']
  `/usr/bin/tar -xf -` (reading a pipe) exit=0 extracted deliverable.html == forged: True
  ```
- **Failure:**
  - **Attack:**
    - Take a genuine package.
    - Insert one extra local entry, `deliverable.html` holding forged HTML, between the last member and the central directory.
    - Update the end-of-central-directory record's offset.
  - **Why it passes:**
    - `payload.json` and `receipt.json` are untouched, so the payload digest still equals the digest the host filed. That is the one out-of-band check a committee has.
    - The archived verifier reports verified.
  - **What a reader sees:** `tar -xf -` (bsdtar reading a pipe), or any reader that walks local headers in order, extracts the forged page.
  - Exposure is limited today because nothing routes package production (N4).
- **Fix:**
  - In `_directory`, require the members' local entries to cover the archive without gaps:
    - sorted by `header_offset`, the first entry starts at 0;
    - each next header starts where the previous entry ends (30 + name + extra + compressed size);
    - the last entry ends at the central-directory offset;
    - refuse any gap.
  - Test with the probe's archive.

### DQ-9 [WARNING] `check_gate_config` passes three `sync.exclude` spellings the bundle carries into the upload
- **Where:**
  - `scripts/check_gate_config.py:188-199`: `_sync_lists` reads block-style lists only.
  - `scripts/check_gate_config.py:176-185`: `_matches` escapes `[...]` into a literal.
  - `scripts/check_gate_config.py:214-238`: `_bundle_problems` tests excludes only against the SHIPPED sample.
  - `scripts/check_gate_config.py:79-98`: SHIPPED.
  - `scripts/check_gate_config.py:334-341`: `--shipped` checks the same sample.
- **Verified:** yes, with `probe_gates.py::test_bundle_gate_misses_excludes_the_cli_honours`, using the repo's `databricks.yml` plus one line each:
  ```
  flow-style list: YAML sync.exclude=['caos/qualification/**'] gate problems=[]
  character class: YAML sync.exclude=['caos/[q]ualification/**'] gate problems=[]
  runtime file SHIPPED omits: YAML sync.exclude=['caos/deliverable/render.py'] gate problems=[]
  ```
- **Failure:**
  - The gate exists so that no exclude hides a path the app needs (F48, F72). Three spellings get through:
    - **Flow-style list:** `exclude: ["caos/qualification/**"]` is invisible to the gate's line parser, although the YAML the CLI reads contains it.
    - **Character class:** a gitignore class like `[q]` is matched as literal brackets.
    - **File outside the sample:** excluding any runtime file not in the 17-path SHIPPED sample passes both this check and `--shipped`. Example: `caos/deliverable/render.py`, which `renderer_sha256()` reads on every filing (`caos/deliverable/filing.py:195-197`, `:253`).
  - Each one ships an app that fails at run time while the gate is green.
  - That the CLI honours the character class is reasoned from gitignore semantics; the reviewer did not run it against the CLI.
- **Fix:**
  - Now that `paths` is an allowlist, refuse any `exclude` key in the sync block, found by a text search of the block.
  - Compare the CLI's deployment record with every tracked file under the `paths` roots, not with a sample.

### DQ-10 [WARNING] `io_budget --assert` still accepts declarations that declare nothing, and never reads `__init__.py`
- **Where:**
  - `scripts/io_budget.py:39-56`: `is_budget` returns True for any attribute, any binary operation, and any unary operation other than negation.
  - `scripts/io_budget.py:83`: `__init__.py` is skipped.
- **Verified:** yes, with `probe_gates.py::test_io_budget_accepts_declarations_that_declare_nothing`:
  ```
  io_budget --assert over inf, ~0, 10**100 and an __init__ route -> exit 0
  ```
- **Failure:**
  - F108 claims FP-19 is fixed ("refuses a declaration that declares nothing").
  - Each of these still passes:
    - `IO_BUDGET = math.inf`
    - `IO_BUDGET = ~0`, which is −1
    - `IO_BUDGET = 10 ** 100`
  - A route declared in `caos/api/reads/__init__.py` is never read at all. That was FP-19's first bullet, and it is unaddressed.
  - Only the spelling `float("inf")` was closed.
- **Fix:**
  - Resolve the declared value to a number (module-level int constants and their arithmetic) and require `0 <= value <= ceiling`.
  - Include `__init__.py`.

### DQ-11 [WARNING] `check_tested` is unchanged although F108 cites FP-18; every FP-18 counterexample still passes
- **Where:**
  - `scripts/check_tested.py:51-58`: in `_is_route`, any `@x.get(...)` counts as a route.
  - `scripts/check_tested.py:61-75`: only `tree.body` is walked.
  - `scripts/check_tested.py:84-97`: one set of referenced names serves the whole suite.
  - `git diff 04c10a9 -- scripts/check_tested.py` is empty, while F108 says "... resolves paths (FP-18, FP-19, FP-20)".
- **Verified:** yes, with `probe_gates.py::test_check_tested_passes_untested_public_code`:
  ```
  public definitions the gate sees: ['verify']
  check_tested findings for the module: []
  ```
- **Failure:**
  - A module holding these four passes the gate, although no test calls any of them:
    - a public lambda (`normalise = lambda ...`);
    - a `def` under `if True:`;
    - a function decorated with `@cache.get("key")`;
    - a `def verify(...)`.
  - The first three are invisible to the gate.
  - `verify` is cleared by the suite's references to `caos.deliverable.verify_package.verify`.
  - CLAUDE.md's "every public definition is named by a test" rests on this gate.
  - The probe's scan found no in-scope definition that currently relies on such a name collision.
- **Fix:**
  - Apply FP-18's own repair:
    - resolve references per module (import source plus attribute);
    - walk `If` and `Try` bodies and module-level callable assignments;
    - recognise routes by the `APIRouter` object.
  - Correct F108's citation.

### DQ-12 [NOTE] `qualify.py` creates its database before the checks that can refuse the set, and its tests never drop theirs
- **Where:**
  - `scripts/qualify.py:362-370` runs `CREATE DATABASE` before `:395` calls `prepare`, which runs `_affordable`, `_answerable`, `_consumers` and `_subjects`.
  - `tests/test_qualify_script.py:207-403`.
- **Verified:** yes, with `probe_qualify.py::test_an_unaffordable_set_is_refused_after_its_database_exists` and `probe_qualify_leak.py`:
  ```
  before the refusal: ['CREATE DATABASE (intercepted)']
  qualify.main raised QUALIFICATION_SET_OVER_CEILING (no exit code; a traceback)
  caos_qualify_* before=25 after=26 new=['caos_qualify_6a2a7fc4e0c94675abc26c5ebafd453d']
  dropped this probe's own caos_qualify_6a2a7fc4e0c94675abc26c5ebafd453d
  ```
- **Failure:**
  - **Orphan database:**
    - `--ceiling 10 --run-ceiling 9` over two cases, or any set that `prepare` refuses, leaves an empty `caos_qualify_<hex>` database on the operator's persistent server.
    - The script then exits through a traceback, whereas every other pre-spend refusal prints "nothing was spent" and exits 2.
    - AR-18's "validate the set before creating persistent resources" is not done.
  - **Test leak:**
    - The three happy-path tests each leave one such database on the shared server; 25 were present during this review.
    - Three of them are from the reviewer's own baseline run, created 10:45:20–22 UTC: `caos_qualify_17bd2121b00c4be98678a197e1262be4`, `caos_qualify_bc396e28d4334be28aeed08ed699d469` and `caos_qualify_250a4518f87f41d78380c0206768a4ad`.
    - The reviewer left them in place because it could not prove sole ownership.
- **Fix:**
  - Before `CREATE DATABASE`, run the harness's checks that make no writes: `assert_measurable`, `assert_unambiguous`, `_answerable`, route resolution, `_consumers` and `_affordable`.
  - Map a `Refusal` to exit 2.
  - Drop the database in the tests' teardown.

### DQ-13 [NOTE] FP-13 is half done: a verdict dated before its evidence existed is accepted, current and relayed, and no row records when it was signed
- **Where:**
  - `caos/qualification/verdict.py:112-118`: `decided_at` need only be at or before now, and within `MAX_VALIDITY` of `expires_at`.
  - `caos/qualification/store.py:567-630`: `record_verdict` never compares `decided_at` with the evidence's or the snapshot's `recorded_at`.
  - `caos/store/0018_qualification_verdicts.sql`: no column records when the verdict was signed.
- **Verified:** yes, with `probe_verdict_dates.py`:
  ```
  snapshot recorded_at=2026-09-23 11:23:30.130157+00:00 evidence recorded_at=2026-09-23 11:23:30.155359+00:00
  verdict decided_at=2025-11-27 11:23:30.155359+00:00 (accepted, current)
  qualification_verdicts columns: ['evidence_sha256', 'reviewer_id', 'reviewer', 'decided_at', 'expires_at']
  pack entry decided_at: 2025-11-27T11:23:30.155359+00:00
  ```
- **Failure:**
  - F108 lists FP-13 as done ("verdicts bind their evidence").
  - What is done: the validity window is capped, and provider and model are compared as a pair.
  - What is not:
    - A reviewer can date a decision 300 days before the snapshot it signs; `current_verdict` serves it and the pack relays that date.
    - The true signing time survives only in `command_requests.created_at`, and only for signatures made through the API.
    - FP-13's other items are neither done nor in next.md: the reviewer's document naming its evidence, `decided_at >= recorded_at`, and revocation.
- **Fix:**
  - In `record_verdict`, refuse `decided_at < qualification_performed.recorded_at`.
  - Add `recorded_at DEFAULT now()` to `qualification_verdicts` and emit it in the pack.
  - Log the remaining items in next.md.

### DQ-14 [NOTE] F108's loader and digest claims overstate the patch
- **Where:**
  - `caos/qualification/matrix.py:366-444`: `_digested` is unchanged since 04c10a9.
    - Subject, forecast, expected refusal, readiness, projection and register keys are appended without tags.
    - Only `expects_blocked` and `research_brief` are tagged.
  - `docs/rebuild/next.md:12`: N8 is still open.
  - `caos/qualification/on_disk.py:475`: `_ready` calls `BoundaryText.of` outside the `try` that retypes boundary refusals.
- **Verified:** yes, with `probe_loader.py`:
  ```
  set A research_brief='{"question":"q"}' expects_ready=()
  set B research_brief=None expects_ready=('research_brief', '{"question":"q"}')
  digests equal: True (03bf72b742bbfdd0...)
  expects_ready of 200 characters -> BOUNDARY_TEXT_TOO_LONG
  label of 200 characters -> QUALIFICATION_SET_FILE_INVALID
  ```
- **Failure:**
  - **Digest tags:**
    - F108 says "every optional field in the set digest is tagged (SI-4, N8 closed)".
    - The function is untouched, and two different sets that `load_qualification_set` accepts share one digest.
    - `prepare`'s `_consumers` then refuses set B. The collision is therefore closed only by a validator outside the digest, which is why this is a NOTE.
  - **Typed code:**
    - F108 also says the loader's code for a string the boundary refuses is `QUALIFICATION_SET_FILE_INVALID`.
    - Readiness ids still leak `BOUNDARY_TEXT_TOO_LONG`.
- **Fix:**
  - Correct F108 and keep N8 open. Tagging the remaining fields moves every committed set's digest, so it needs its own decision against the `RESULT.md` digests.
  - Wrap `_ready`'s `BoundaryText.of` in the same retyping `_bounded` uses.

### DQ-15 [NOTE] The offline verifier does not re-apply the figure rule, and `_figure_error` relies on the renderer for type strictness
- **Where:**
  - `caos/deliverable/verify_package.py:152-199`: `_figure_error` compares with `!=`, and `_narrative_error` returns `None` for a non-list narrative and never reads text spans.
  - `caos/deliverable/revisions.py:47-58`: the save boundary's rule.
- **Verified:** yes, with `probe_figures.py::test_edge_shaped_figures`:
  ```
  page 1.0: (False, 'the archive is not a readable package')
  page True: (False, 'the archive is not a readable package')
  text span with numerals: (True, None)
  string narrative with numerals: (True, None)
  ```
- **Failure:**
  - **Uncited figures verify:**
    - A package whose narrative carries "Net leverage is 4.2x, headroom 45%", as a text span or as a string narrative, verifies.
    - That is exactly the uncited figure the save boundary refuses (invariant 11), and it passes the portable check.
  - **The stated reason does not hold:**
    - F108 keeps string narratives for "a revision filed before spans existed".
    - No such revision can exist: no production path builds a `Revision` with a string narrative, and `prove_revision` refuses a non-list.
  - **Type strictness is borrowed:**
    - `_figure_error` itself accepts page `1.0` and `True` as page 1, by Python equality.
    - Only the archived renderer's `_page` refuses them, and the reason it reports is "not a readable package".
- **Fix:**
  - Apply `_is_figure` to text spans in `_narrative_error`, and refuse a non-list narrative.
  - Compare figure fields with `type(a) is type(b) and a == b`.

## What held up
- **Filing re-proof (FP-04):**
  - The route re-derives the payload under the case lock through `prove_revision`. Every artifact is re-verified and re-anchored, and narrative figures are re-resolved.
  - It refuses unless the result hashes to the digest the filer reviewed (`caos/api/commands/deliverable.py:344-356`).
  - `FILE_IO = 56` is the measured count (`test_governed_write_routes.py`).
- **Filed Committee read from its snapshot (FP-05):**
  - `read_filed_receipt` and `read_revision` serve stored bytes whose digest is checked; `BlobStore.get` re-hashes them.
  - A source withdrawal or a bundle move after filing leaves the read unchanged: `test_a_filed_receipt_survives_live_state_moving_under_it[source|authority]` and the damage matrix in `test_revision_sections` pass.
  - The served signers, freezer, filer and receipt agree with what was filed.
- **Signatures and migration 0029** (`probe_signatures.py`):
  - Two approvers signing at once are both recorded.
  - One approver signing twice at once gets one `DELIVERABLE_ALREADY_SIGNED`.
  - One governed SIGN sent twice at once under one key answers one fresh 200 and one replayed 200.
  - A request naming another digest gets `DELIVERABLE_MOVED_SINCE_SIGNING`, which is invariant 5's route half.
  - The receipt names the newest signer, `read_filed_receipt` rebuilds it byte-exactly, and ties break on signer id.
  - AR-10's twin-replay test passes.
- **Loader and register bounds:**
  - `probe_loader.py`:
    - 51 documents are refused after 0 reads.
    - The set's byte total is refused on `st_size`, before any read.
    - A symlink is admitted under its declared name.
  - `probe_gates.py`: the document register refuses traversal, absolute and symlinked paths.
- **Package verifier bounds:**
  - A sixth central-directory entry, a traversal name and missing member bytes are all refused (`probe_package.py`). Size, ratio and encryption limits are covered by the existing suite.
  - `_figure_error` refuses `-0.0`, NaN, Infinity, `"1"`, bool and float indices, and unknown nodes.
- **Invariant 7:** no float reaches money anywhere in scope. `qualify._capture` renders charges from `Decimal` with `str`, and the render prints no amounts.
- **Render parity:**
  - `tests/parity/test_render.py` and `tests/test_deliverable_render.py` pass.
  - The divergence tried was a GFM-escaped pipe in a table body cell. The page refuses with `DELIVERABLE_MARKDOWN_UNSUPPORTED` rather than drawing a table nobody wrote (`probe_render.py`).
  - The vendor's own reader truncates that cell to `covenant \`.

## Not covered
- **Frontend rendering:** the React Committee section's rendering of the served body is frontend scope. Render and the audit package have no route (N4), so in production the committee sees only the JSON body.
- **Real CLI deploy:** not run, so the character-class exclude in DQ-9 is unconfirmed against the CLI.
- **Suite and whole-tree gates:** the full suite and the whole-tree gates (ruff, mypy, complexipy, coverage) were not run; targeted tests only.
- **Probe files:** they are review evidence, not suite. ruff reports 45 issues in them, and `check_tested` would flag their public test functions if they were committed outside `tests/`.
- **AR-08 (observation, not re-reported):**
  - F108 keeps AR-08 declined, and it is still live.
  - `7. First / 9. Second / 10. Third` renders as `<ol start="7">`, and the browser draws the third item as 9.
  - Meanwhile `render._list`'s comment says a run that isn't consecutive is written as its own characters.
- **Legacy filings and host binding:** legacy filings (`legacy_filing_events`) were not exercised. Nor was whether the pack should bind the host code or prompt pins; N10 covers the record side.

# Adversarial review, round 3 — the uncommitted patch on `rebuild/databricks`

**Scope.** The uncommitted working tree of the main checkout at
`/Users/ericguei/Documents/caos-databricks` (branch `rebuild/databricks`, HEAD
`04c10a929ad6ec293bb3d56c574cec5b73655b38`), snapshotted into a disposable worktree at
**2026-09-23 07:28-07:31 UTC**. The sandbox refuses a worktree-isolated agent any git
command aimed at the shared checkout, so the patch could not be taken with
`git diff --binary HEAD`; both trees sit on the same commit, so it was taken instead by
comparing the two working trees file by file and copying every file whose bytes differ
(`scratchpad/snapshot.py`, `scratchpad/apply.py`; sha256 digests in
`scratchpad/snapshot-manifest.txt`). **90 files** were taken: the 84 modified tracked
files that `git diff --stat` in the worktree then reports (**4,384 insertions, 816
deletions**) plus 6 untracked source files - `frontend/src/app/heading.ts`,
`frontend/src/controls/ConfirmedControl.tsx`, `frontend/src/states/Announcer.tsx`,
`frontend/tests/unit/workspace-live.test.tsx`, `tests/test_checkpoint.py`,
`tests/test_stream_slots.py`. Skipped as local state rather than patch:
`.complexipy_cache/`, `.databricks/` (28 CLI files, side-copied to the scratchpad as
evidence only), `frontend/test-results/.last-run.json`, and everything under `.claude/`,
`node_modules`, `dist*`, `.venv*`, `docs/rebuild/runs/`. No file was deleted relative
to HEAD.

**This is a moment in time, and the main checkout has already moved.** Re-running the
same comparison at the end of the review (about 09:15 UTC) shows **67 tracked files
differing again**, including `caos/graph/checkpoint.py`, `caos/store/lakebase.py`,
`caos/serve.py`, `caos/boundary_text.py`, `caos/evidence/ingest.py`,
`caos/evidence/page.py`, `caos/deliverable/{filing,receipts,verify_package}.py`,
`caos/qualification/{on_disk,store,verdict}.py`, `caos/api/commands/deliverable.py`,
`databricks.yml`, `app.yaml`, `pyproject.toml`, `CLAUDE.md`, `.github/workflows/ci.yml`,
`.pre-commit-config.yaml`, `docs/DEPLOYMENT.md`, `docs/rebuild/ENTERPRISE_HANDOFF.md`,
`findings.md`, `scripts/{enterprise_deploy.sh,enterprise_deploy.py,preflight.py,`
`gateway_smoke.py,check_gate_config.py,release_pack.py,dev_doctor.py}`,
`tests/workspace_stub.py`, `tests/platform_app.py`, `tests/graph/test_graph.py`,
`tests/test_lakebase_and_blobs.py` and 20 further test files (full list:
`scratchpad/drift-list.txt`). Several findings below may already be closed upstream.
Every finding is stated against the 07:31 snapshot and should be re-checked against the
current tree before it is acted on. Nothing was ever written to the main checkout.

Read first: `CLAUDE.md`; the root `findings.md` (deployment C1-C4/W1-W5/N1-N7, the
eight-auditor sweep SA-C*/MX-*/AS-*/TM-*/AI-*/CR-*/DL-*/DP-*/FE-*/SI-*, and the
restored edge/identity review EI-*); and `docs/rebuild/findings.md` (AR-01..AR-25,
FP-01..FP-41, R2-*).

**Method.** Three personas (Saboteur, New Hire, Security Auditor) over the whole patch,
plus two sub-reviews in the same worktree (the frontend, and the deployment path).
Environment: `uv sync --locked --all-groups` in the worktree's own `.venv`,
`npm --prefix frontend ci --ignore-scripts`, and the shared Postgres 17.11 at
`127.0.0.1:55437` using only disposable databases, all dropped. Probe scripts are in
the session scratchpad (`probe_ckpt.py`, `probe_ckpt2.py`, `probe_logged.py`,
`probe_forget.py`, `probe_mint.py`, `probe_misc.py`); no paid model call, no real
workspace, no write to `vendor/deploy-v`.

---

## Verdict: **BLOCK**

Five mandatory gates are red on this snapshot - `uv run ruff check .`,
`uv run complexipy ... --max-complexity-allowed 15`,
`uv run python scripts/check_tested.py`, `pytest`, and
`npm --prefix frontend run lint` - and the 23 pytest failures are
deterministic, not flakes. Two of them are product defects the patch introduced: the
new AR-20 advisory lock **deadlocks** three checkpoint set-ups out of four, and the new
FP-17 narrative check makes the **portable package verifier refuse every genuine
deliverable package**. A third break sits outside pytest: the new `sync.paths`
allowlist drops the git-ignored `frontend/dist`, so the tree the CLI uploads has no
static export and the App fails its lifespan with `EDGE_CONFIG_INVALID` - C2 is closed
and replaced by a total boot failure.

Much of the patch is good and does close what it claims: the strict checkpoint
serializer (SA-C2/TM-1), the bounded single-flight mint with a live-token fallback
(MX-3/DL-4), the identity single-flight and negative-cache bound (EI-W3/AR-04/CR-7),
the per-actor stream share (MX-2), the NFC split in the citation matcher (CR-4), the
ReDoS bound on whitespace runs (AI-1/SA-C5), the citation index (AI-5), the DP-4 drain,
and the FP-01/FP-03/FP-07/FP-09/FP-12/FP-15/FP-16/FP-20 repairs. What follows is what
breaks, what is asserted but is not true, and what the patch made worse.

---

## Findings

### R3-1 [CRITICAL] The AR-20 advisory lock deadlocks: three checkpoint set-ups out of four now fail where one used to

- **Where:** `caos/graph/checkpoint.py:74-83` (`_set_up`, `pg_advisory_lock` held across
  `saver.setup()`), reached from `:97-104` and `:125-132`; the failing test is
  `tests/test_checkpoint.py:56`.
- **Verified: yes.**

      $ CAOS_TEST_POSTGRES_URL=... CAOS_REQUIRE_POSTGRES=1 uv run pytest --no-cov -q tests/test_checkpoint.py
      FAILED tests/test_checkpoint.py::test_concurrent_set_up_on_a_fresh_database_all_succeed
      E  AssertionError: assert ([DeadlockDete...] == [])

  Reproduced standalone (`scratchpad/probe_ckpt.py`) with the server's full DETAIL:

      savers=1 failures=3
      DeadlockDetected sqlstate: 40P01
      message_detail:
        Process 43888 waits for ExclusiveLock on advisory lock [751243,1,3060640805,1]; blocked by process 43887.
        Process 43887 waits for ShareLock on virtual transaction 31/1960; blocked by process 43890.
        Process 43890 waits for ExclusiveLock on advisory lock [751243,1,3060640805,1]; blocked by process 43888.

  `pg_stat_activity`, sampled during the race (`scratchpad/probe_ckpt2.py`), names the
  holder's statement:

      44332 idle    Client ClientRead | CREATE TABLE IF NOT EXISTS checkpoint_migrations ( v INTEGER PRIMARY KEY );
      44333 active  Lock   advisory   | SELECT pg_advisory_lock($1)
      44334 active  Lock   advisory   | SELECT pg_advisory_lock($1)
      44335 active  Lock   advisory   | SELECT pg_advisory_lock($1)

  The mechanism: LangGraph's migrations contain `CREATE INDEX CONCURRENTLY`
  (`.venv/.../langgraph/checkpoint/postgres/base.py:82,85,88`). CIC waits for **every**
  concurrent virtual transaction in the database to end. The other processes are parked
  inside `SELECT pg_advisory_lock(...)`, each holding an open virtual transaction that
  cannot end until the holder finishes - a guaranteed cycle, which the deadlock detector
  breaks by killing the waiters.
- **Failure:** AR-20 was "two processes racing `setup()` leaves one without a worker".
  After the fix, on a fresh Lakebase database **every process but one** gets
  `DeadlockDetected` out of `checkpointer()`; `start_in_process` catches the database
  error and returns None, so uvicorn serves with no worker while health stays `ready`.
  With the in-process worker (D11) plus any second process - a standalone worker, a
  second App replica, a `bundle run` - first boot is now strictly worse than before the
  patch. The lock is also ineffective on the pooled path even when it does not deadlock:
  `PostgresSaver.setup()` over a pool checks a *second* connection out of the pool, so
  the DDL does not run in the session that holds the lock.
- **Fix:** do not block inside a statement while the holder runs CIC. Poll with
  `pg_try_advisory_lock` and sleep *between* statements, so a waiting process holds no
  virtual transaction; or drop the lock and make `setup()` idempotent under
  `UniqueViolation` with a bounded retry. Keep the new test and run it against a pool as
  well as a single connection.

### R3-2 [CRITICAL] FP-17's narrative check makes the portable verifier refuse every genuine package

- **Where:** `caos/deliverable/verify_package.py:186-196` (`_narrative_error`, "the
  narrative is not this host's spans"), against `caos/deliverable/canonical.py:140-141`
  (`payload["narrative"] = revision.narrative.value`, a plain string) and
  `caos/deliverable/render.py:552-553`, which renders a string narrative as a
  first-class shape.
- **Verified: yes.** Ten of `tests/test_deliverable_package.py`'s tests fail, including
  the plain round trip:

      FAILED tests/test_deliverable_package.py::test_a_highly_compressible_valid_package_round_trips
      E  assert False
      E   + where False = Verification(verified=False, reason="the narrative is not this host's spans").verified
      FAILED tests/test_deliverable_package.py::test_a_refused_archive_says_why_and_a_verified_one_has_nothing_to_say
      E  assert (False, "the ...host's spans") == (True, None)

  and `test_a_package_is_published_whole_or_not_at_all`,
  `test_a_failed_write_leaves_no_file_at_the_destination`,
  `test_the_archived_verifier_must_be_this_verifier`,
  `test_a_package_verifies_with_a_fresh_interpreter_outside_the_repository`,
  `test_archived_renderer_is_used_and_receipt_renderer_hash_is_checked`,
  `test_a_current_receipt_identity_must_match_its_payload` and both
  `test_declared_and_actual_member_sizes_must_match` parameters.
- **Failure:** every deliverable whose narrative is the canonical string form - which is
  what `caos/deliverable/canonical.py` writes and what the shipped renderer explicitly
  supports - is reported "not verified" by the verifier that travels with it. The
  offline proof of a filed deliverable, the one artefact a committee can check without
  this host, no longer works for any package. FP-17's real hole (a figure not
  cross-checked against `citations[citation_index]`) is closed by `_figure_error`; the
  blanket refusal of string narratives is collateral.
- **Fix:** keep `_figure_error`, and treat a string narrative as carrying no figures
  (return None) rather than as a fault. If string narratives really must go, stop
  `canonical.py` writing one and migrate the renderer first, in that order.

### R3-3 [CRITICAL] `sync.paths` drops the git-ignored `frontend/dist`, so the uploaded App cannot boot

- **Where:** `databricks.yml:109-117` (the `paths:` allowlist; `frontend/dist` at `:113`)
  against `.gitignore:13` (`frontend/dist/`) and `databricks.yml:59-60`
  (`CAOS_SITE_ROOT: frontend/dist`).
- **Verified: yes** (sub-review, against the loopback stand-in).
  `uv run python tests/workspace_stub.py -- databricks bundle deploy -t dev --var uc_catalog=main --var uc_schema=caos --var lakebase_instance=caos-lb`
  reports `Files: 546 uploaded`; rebuilding the uploaded tree from the stub's
  `workspace-files/import-file` paths gives `349 vendor, 128 caos, 65 icm, app.yaml,
  pyproject.toml, uv.lock, .python-version` and **zero** `frontend/**` entries, with the
  real 28-file `frontend/dist` present on disk. A/B: removing `frontend/dist/` from
  `.gitignore` raised the same deploy to `574` files including
  `frontend/dist/index.html`; restoring the line returned it to `546`. Booting the
  reconstructed tree gives
  `{'type': 'lifespan.startup.failed', 'message': 'EDGE_CONFIG_INVALID'}`. The repo's own
  CI step agrees:
  `uv run python scripts/check_gate_config.py --shipped .databricks/bundle/dev/deployment.json`
  -> `shipped: frontend/dist/index.html was not synced` (exit 1). Confirmed
  independently here: `git check-ignore -v frontend/dist/index.html` ->
  `.gitignore:13:frontend/dist/`, and `databricks.yml:113` does list `frontend/dist`.
  `sync.paths` is a set of sync roots and, unlike the old `sync.include`, does not
  re-admit git-ignored paths.
- **Failure:** the deployed App has no UI and never starts (`caos/api/site.py:102-104`
  fails the lifespan when `CAOS_SITE_ROOT` is set and holds no `index.html`). C2 (155
  files missing) is traded for a total boot failure. Second consequence: with
  `frontend/dist` absent - its normal state in a clean checkout - the documented D28
  gate `databricks bundle validate -t dev` now **fails** with
  `Error: cannot list files: stat frontend/dist: no such file or directory`, where
  HEAD's `databricks.yml` exits 0 with a warning. A `sync.paths` entry must exist on
  disk; an `include` glob need not.
- **Fix:** keep `sync.paths` for the source roots and re-admit the export with
  `sync.include: ["frontend/dist/**"]` (verify the CLI honours both), or stop
  git-ignoring the deployed build output. Add
  `scripts/check_gate_config.py --shipped ...` to the local gate list in `CLAUDE.md`,
  not only to CI.

### R3-4 [CRITICAL] Five mandatory gates are red

`CLAUDE.md`: "Gates (all must exit 0; none may be loosened)."

- **Where / Verified: yes**, each command run from the worktree:
  1. `uv run ruff check .` -> **exit 1**:
     `I001 Import block is un-sorted or un-formatted --> tests/test_lakebase_and_blobs.py:3:1`
     (`import os` placed after `from pathlib import Path`).
  2. `uv run complexipy caos scripts icm --max-complexity-allowed 15` -> **exit 1**:
     `_prepare 18  FAILED` and
     `Snapshot watermark: caos/evidence/ingest.py/ingest.py:_prepare increased from 16 to 18`
     (`caos/evidence/ingest.py:293-300`, the new `hides_text` branch).
     `complexipy-snapshot.json` was **not** edited, so the baseline was not loosened -
     the function simply grew past it.
  3. `uv run python scripts/check_tested.py` -> **exit 1**; four new public definitions
     are named by no test: `caos/boundary_text.py:41 hides_text`,
     `caos/qualification/store.py:99 document_complete`,
     `scripts/document_register.py:109 held_path`, `scripts/io_budget.py:39 is_budget`.
  4. `pytest` -> **23 deterministic failures** across two selections (`-n 4`,
     `CAOS_REQUIRE_POSTGRES=1`, the documented database):
     `tests/test_checkpoint.py::test_concurrent_set_up_on_a_fresh_database_all_succeed`
     (R3-1);
     `tests/graph/test_graph.py::test_the_app_s_shutdown_hooks_run_after_the_probes_stop`;
     ten in `tests/test_deliverable_package.py` (R3-2);
     `tests/test_filing_chain.py::test_sign_freeze_file_refusals_preserve_one_chain`;
     `tests/test_qualification_harness.py::test_a_late_invalid_pin_clears_proof_and_preserves_the_stopped_record`;
     four in `tests/test_qualify_script.py`; three io-budget tests and
     `test_check_tested_module_guard_exits_with_mains_return_code` in
     `tests/test_gate_scripts.py`; and
     `tests/test_check_gate_config.py::test_a_sync_exclude_that_hides_the_methodology_is_named`.
  5. `npm --prefix frontend run lint` -> **exit 1**, three independent causes:
     eslint `4 problems (4 errors)`, all
     `` `tabIndex` should only be declared on interactive elements  jsx-a11y/no-noninteractive-tabindex ``
     at `frontend/src/sections/book/BookSection.tsx:143`,
     `frontend/src/sections/directory/CaseRegister.tsx:44`,
     `frontend/src/sections/model/ModelSection.tsx:65`,
     `frontend/src/sections/upload/SourcePack.tsx:114` (the repo's own
     `frontend/eslint.config.mjs:32-35` allows this only for `roles: ["tabpanel","region"]`
     and the patch used `role="group"`; `ReportSection.tsx:30,42` does the same thing
     with `role="region"` and passes); prettier
     `Code style issues found in 2 files` (`frontend/src/sections/model/ModelSection.tsx:65`,
     `frontend/tests/unit/chrome.test.tsx:180`); and
     `node scripts/check-tested.mjs` -> `src/app/transport.ts:131: 'retryAfterOf' has no test naming it`.
     `typecheck`, `test` (31 files, 286 tests), `build`, `build:demo`, `a11y`
     (240/240 entries, 0 violations) and `test:workbench` (90 passed) all pass.
- **Failure:** the patch cannot land. Two failures are product defects (R3-1, R3-2); the
  rest are tests the patch changed behaviour under and did not update -
  `io_budget --assert` on a tree with no `caos/api` now returns 2 where
  `tests/test_gate_scripts.py:150-152` asserts 0;
  `test_a_sync_exclude_that_hides_the_methodology_is_named` asserts on a `sync ...
  exclude:` block `databricks.yml` no longer has; `tests/test_qualify_script.py` does
  not set the newly required `CAOS_QUALIFY_BLOB_ROOT`. `tests/graph/test_graph.py:219`
  enters the real FastAPI lifespan with no store configured and dies on
  `caos/store/lakebase.py:73: Refusal: STORE_NOT_CONFIGURED` - it needs the store
  fixture or a stubbed `_lifespan`.
- **Fix:** run the gate list before proposing the patch. Every failure above is a
  one-file change except R3-1 and R3-2.

### R3-5 [CRITICAL] FP-09's receipt shape change makes every already-filed multi-signer deliverable unreadable

- **Where:** `caos/deliverable/filing.py:280-310` (`_wire`, `filing_payload`,
  `receipt_bytes`; `signed_by` is now `tuple[UUID, ...]` joined on `,`), read back at
  `caos/deliverable/receipts.py:80-91` (`data != receipt_bytes(receipt)` ->
  `DELIVERABLE_PAYLOAD_INVALID`) and `:98-106`
  (`payload_digests(... payload=filing_payload(receipt) ...)`).
- **Verified: yes** (`scratchpad/probe_misc.py`):

      one signer  -> 00000000-0000-4000-8000-00000000000a
      two signers -> 00000000-0000-4000-8000-00000000000a,00000000-0000-4000-8000-00000000000b
      filing_payload two signers -> 00000000-...a,00000000-...b
      a pre-patch two-signer receipt named one -> 00000000-0000-4000-8000-00000000000b
      so the stored bytes and the rebuilt bytes differ: True

  A one-signer receipt is byte-identical (`",".join([str(u)]) == str(u)`), so only
  multi-signer filings are affected.
- **Failure:** `one_opinion_per_signer` explicitly allows several approvers to sign
  before the freeze. Every deliverable filed with two or more signers before this patch
  stored receipt bytes and a command-payload digest naming the **latest** signer alone.
  `read_filed_receipt` now rebuilds the receipt with all signers sorted, so the stored
  bytes no longer match and the Committee section refuses it
  `DELIVERABLE_PAYLOAD_INVALID` - permanently, with no migration and no operator path.
  That is precisely the failure mode FP-05 exists for, reintroduced by FP-09's fix in
  the same patch. There is no version field in the receipt to tell the two shapes apart.
- **Fix:** version the receipt (`receipt_format`) and have `read_filed_receipt` accept
  the stored bytes if they match **either** the sorted-list form or the historical
  single-signer form; or migrate stored receipts and their audit payloads under the case
  lock. Add a regression test that files with two signers and reads it back.

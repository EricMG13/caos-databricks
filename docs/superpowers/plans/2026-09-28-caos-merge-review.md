# Confidence review — interface integration with the moved default branch

The user asked to check conflicts and merge. The repository's actual default branch is `rebuild/databricks`; no `main` branch exists. Fetched origin tip: `908f6c7`. The interface work began at `9393940`. The user previously said “no tournaments”; that instruction remains in force.

## Checkpoint review

Least confident about, ranked:

1. **Accidentally committing another task's artifacts.** Inspected the tracked diff and the complete untracked inventory. The code-review.md and docs/rebuild/gitnexus-review tree are unrelated work and are excluded. Only the interface changes, its three plans/reviews, approved PRODUCT.md, DESIGN.md and persistent frontend live configuration are staged. Transient Impeccable state stays local. Verdict: fine by explicit path selection.
2. **Stale async evidence or gate preview state.** Re-read sourceRegister, the drawer close/open handoff, GatePanelControl and their callers. Existing focused regression checks cover exact citation identity, connected openers and accepted preview propagation. The full 517-test suite passes. Verdict: fine for the checkpoint; the new main sourcesEpoch behavior must be preserved during integration.
3. **Invented or missing product data.** Re-read compose.ts and the wire Tab extension. Module names come from the catalog; blank names fall back to their IDs. Pending counts, warnings, restricted states, book availability and gate types come from served facts. Full unit checks include concrete blank-name and partial/unavailable cases. Verdict: fine.
4. **Motion implying work after it stops.** The accepted graph reuses runningOf/blockingOf, gates active edges on accepted sources and gate state, and disables animation for ended runs. Its concrete state-transition and visibility lifecycle tests pass. The previous live review records three-engine reduced-motion/selection checks. Verdict: fine.
5. **Narrow desktop layout hiding the selected detail or controls.** The previous browser review verified 320 CSS px reflow, title visibility, controlled module selection, graph bounds, and the 1080px compact Run detail. Unit checks still pass. Verdict: fine for the checkpoint; full browser checks will run on the integrated tree.
6. **Live tooling leaking into production.** index.html is identical to the committed original; live source wrappers and param variables were removed. The normal helper stop and rebuilt demo export were verified in the live review. Verdict: fine; production and demo exports will be rebuilt after integration.
7. **Losing changes from the moved default branch.** Read the incoming Workspace source epoch/draft provider changes, Analysis parser fixes, shared types and CSS changes. Integration is still pending at this checkpoint; conflicts will be resolved by preserving both intents, then tested and reviewed before publication. Verdict: open until integration.
8. **Skipping the PR size gate.** Read scripts/check_pr_size.py from the fetched tip: maximum 800 changed lines with explicit exclusions. The full interface change exceeds it. Publication will use three coherent PRs, each measured against its actual base, with CI gates intact. Verdict: open until publication checks.

Fixed: no additional bug confirmed before checkpoint.

Verified fine: current behavior and contracts, source cleanup and explicit commit scope by the evidence above.

By-design: this checkpoint preserves the fully tested work before integrating main; it is not a claim that the merge has been validated.

Still open at the checkpoint: integration conflicts, integrated checks and three gated PRs.

Validation before checkpoint:

- `npm run test` → 517 passed in 43 files.
- `npm run typecheck` → passed.
- `npm run lint` → passed; formatting, vocabulary and coverage checks have zero findings.
- `git diff --check` → passed.

## Integrated review

`git merge --no-commit origin/rebuild/databricks` completed automatically with no unmerged paths. Reviewed the result against the fetched default branch and the interface checkpoint, rather than treating the absence of textual conflicts as the verdict.

- **Source events and citation handoff.** Workspace still increments the request-keyed source epoch before a section refetch; the visible snapshot passes it to the evidence provider. The inventory adds only stored citation identities and defers opening until its drawer closes. Existing withdrawal/recheck tests and the case-switch-during-close regression pass together. No lost invalidation or stale-case opening confirmed.
- **Report editing and presentation.** The default branch's report draft provider remains above the section boundary, keyed on case and displayed run. The interface change only moves the saved narrative before filing controls and folds identities into a native disclosure. The incoming refetch/draft preservation tests pass with the presentation checks. No draft-lifetime change confirmed.
- **Graph and layout.** Default-branch changes in the same files remove obsolete comments; accepted graph state, visibility cleanup and compact detail ordering are preserved. State transitions remain governed by existing running/blocking helpers and served accepted attempts, including ended runs and gates.
- **Publication scope.** Prepared three independent area patches from the integrated tree against `908f6c7`, keeping CSS with its owning area. PR #6 contains only Analysis/evidence/chrome changes and approved product context, with 603 counted lines. Its clean checkout passes 523 unit tests, lint, type checking and the duplicate-code gate. The repository size checker and CI policy remain unchanged.

Integrated validation: 528 unit tests in 43 files, type checking, lint, production export and demo export all pass. All 129 workbench browser tests pass across Chromium, Firefox and WebKit. All 720 accessibility scans pass with zero violation nodes, scan errors or layout failures. Production source/export searches found no live helper injection. The integrated tree has no diff from the fetched default branch in backend code, tests, scripts, vendored bytes, workflow or CLAUDE.md.

The workflow patch passes 526 unit tests, lint, type checking and both exports independently, and measures 416 counted lines against the Analysis patch. Book's plain-language basis is fixed because the wire parser requires the three corresponding literal values; it cannot accept a different basis and describe it this way. Traced every preview callback through useCommand: no lifecycle guard was removed; approvals remain bound to the server's preview digest and input fingerprint. The three prepared patches reconstruct all 38 changed interface files byte for byte.

Confidence verdict: no additional integration bug confirmed; source invalidation, draft lifetime, evidence focus handoff, graph state, narrow layout, production cleanup and publication scope verified fine. Still open: all three PRs must pass hosted CI and merge into the actual default branch. No tournaments were run after the user's prohibition.

## Publication follow-up

PR #6 passed all seven hosted CI jobs and merged as `6b7ec1c`. Hosted checks exposed two issues after the initial integrated review:

- The existing quote-normalization timing regression repeatedly failed on the default branch and the first patch. F446 rejects a mismatching final edge before normalizing the first edge. The separate quote-match confidence review records the differential correctness checks; the full hosted backend jobs passed afterward.
- Splitting the interface changes placed the Upload timestamp test's updated URL in the final graph patch while the fixture change shipped in the workflow patch. F447 moves the existing one-line URL correction alongside its fixture. All three browser engines pass the unchanged timestamp assertions. The workflow merge review records the investigation and the 526 passing unit tests.

PR #7 passed all seven hosted CI jobs in run `36392593716` and merged as `3e05c85`. Its frontend job passed 526 unit tests, 108 browser tests and the accessibility matrix with zero violation nodes, scan errors or layout failures.

The graph patch was rebased onto that merged default branch without conflicts and measures 585 counted lines against it. All application code, tests, scripts, product/design context and persistent frontend configuration match the fully reviewed source tree at `1ece1ea` exactly; the only additional files or lines are these publication review records and F447. No interface behavior was lost or newly introduced during splitting. Fresh hosted graph checks are the final publication gate.

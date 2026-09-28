# CAOS critique remediation implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task by task. Use superpowers:subagent-driven-development only when delegation is authorized. Steps use checkbox syntax for tracking.

**Goal:** Resolve the five priority findings and the actionable minor findings from the 2026-09-27 Impeccable rerun without changing financial, approval, or evidence authority.

**Execution status (2026-09-27):** Tasks 1–5 are implemented in the current worktree. The original checkboxes preserve the implementation sequence; the verification record and new follow-up scope are at the end of this plan.

**Architecture:** Reorder existing React sections with a Run-specific CSS grid, compose truthful summaries from existing wire fields, and connect the source register to the existing evidence provider. Reuse the shared drawer, native disclosures, existing design tokens, and existing test suites. No new dependencies, backend endpoints, wire fields, or generic UI abstractions.

**Tech stack:** React 19, TypeScript, Tailwind 4, Base UI Dialog, Vite, Vitest/Testing Library, Playwright; Node >=24.

## Global constraints

- Repository: `/Users/ericguei/Documents/caos-databricks`. Commands below run from its `frontend` directory unless stated otherwise.
- `DESIGN.md` remains the authority: “Desktop only (D63).” Support desktop windows at least 1024 px wide; 320×640 is desktop zoom reflow, not a new mobile layout.
- “One evidence surface.” Never leave a source inventory drawer stacked with a source-page drawer.
- “Dialog openers are passed explicitly, never inferred from `document.activeElement`.” Preserve Escape, focus return, and reduced motion.
- “A refused control stays visible and refused, with its reason named.” Preserve command authorization, command outcomes, refusal codes, and observed timestamps.
- “Figures are printed as served.” No calculations on financial values, changed precision, invented module names, or missing-value substitution.
- Keep nine workspace sections and route-ordered Analysis views. Keep light and dark themes, Geist/Geist Mono, semantic colors, and paper only for filed output/evidence.
- Preserve CSP, closed Markdown rendering, snapshot-bound evidence identities, withdrawn-source fetch restrictions, and the existing Book ledger.
- No production code is changed by this planning task. Do not commit, deploy, publish, or alter vendored skill/source bundles as part of writing the plan.
- Before implementation completion or any commit, run `confidence-review`; after non-trivial code changes, also run `rewrite-tournament` in no-argument post-edit mode. Fix confirmed defects before claiming completion.

## Evidence and scope

The fresh critique scored **28/40 (Good)**. Independent A/B reviews used new browser tabs; the deterministic scan of `frontend/src` returned `[]`, exit 0. Parent verification reproduced the following issues against the demo:

| ID | Priority | Finding | Completion condition |
|---|---|---|---|
| F1 | P1 | At 1024×768, selecting CP-5 leaves its detail at document y≈1649, below the action group ending y≈1633. The summary also says “Gates released” while CP-6 awaits its QA gate. | Selected detail precedes action controls when stacked; input approvals and QA gates have distinct, factual copy. |
| F2 | P2 | Analysis’s “What this run rests on” lists sources/pages but offers only Close. | Every citation can open the existing source drawer, with one dialog and correct focus/withdrawal behavior. |
| F3 | P2 | Report’s first 720 px show summary, four identities, revisions, and the artifact heading; saved narrative is later. | Saved narrative leads the report body; filing follows; identities and historical material remain reachable. |
| F4 | P2 | Book says “3 credits on accepted projections” while one credit has `NO_ACCEPTED_FORECAST`. Generic partial copy replaces the specific evidence caveat. Basis shows raw enums and `true`. | Summary separates listed credits from available accepted forecasts; specific caveats survive partial status; basis reads in ordinary words. |
| F5 | P2 | At 320 px, Book’s visible h1 truncates to “Bo…” while the case breadcrumb consumes space. AX still has the full title. | Complete section title remains visible at zoom width alongside warning and theme controls. |
| M1 | P3 | The Analysis source-register drawer body starts flush against its left edge. | Reuse the existing `.db` inset and scrolling body. |
| M2 | P3 | Run’s `READY_WITH_LIMITATIONS` leaves a solitary final `S` in the narrow detail value column. | Give the Reason label/value full rows; keep the raw verdict and edge identities intact. |
| M3 | P3 | Directory leads with an opaque case ID before the issuer title. | Title becomes the first column; the ID remains adjacent and the row action stays unchanged. |

The CP-6A/CP-7 names are a **demo-data limitation**, not a confirmed missing-name frontend bug. The fixtures serve `module_name` equal to the ID; the renderer intentionally avoids repeating it. The catalog marks CP-6A absorbed into CP-6, and no canonical CP-7 display name was established. Do not invent names or modify the vendor catalog to improve the demo. Graph reason clamping is acceptable when the full selected-node explanation and existing tooltip remain available; no graph redesign is planned.

## File map and order

All paths in the task lists are relative to the repository root. No new application files are required.

1. Run layout and status: `RunSection.tsx`, `NodeDetail.tsx`, `styles/caos.css`, `chrome/compose.ts`; extend existing compose/layout tests.
2. Evidence register: `AnalysisSection.tsx`; extend existing analysis/evidence workbench tests. Reuse `EvidenceContext.tsx` and `Overlay.tsx` without extending their public APIs.
3. Book truth and basis: `chrome/compose.ts`, `BookSection.tsx`; extend compose/book tests.
4. Report order: `ReportSection.tsx`; extend report/layout tests.
5. Header reflow and Directory order: `SiteHeader.tsx`, `CaseRegister.tsx`; extend the existing browser layout check for the header, retain Directory tests.
6. Review, checks, and visual verification.

Tasks 1–5 are independently reviewable. Execute sequentially because Tasks 1 and 3 share `compose.ts`, and browser checks share the preview port.

## Task 1: Keep Run selection near its explanation

**Files**

- Modify: `frontend/src/sections/run/RunSection.tsx`
- Modify: `frontend/src/sections/run/NodeDetail.tsx`
- Modify: `frontend/src/styles/caos.css`
- Modify: `frontend/src/chrome/compose.ts`
- Test: `frontend/tests/unit/compose.test.tsx`
- Test: `frontend/tests/workbench/layout.spec.ts`
- Retain: `frontend/tests/unit/run.test.tsx`, `frontend/tests/unit/run-reason.test.ts`, `frontend/tests/workbench/run.spec.ts`

**Interfaces**

- Consume `RunView`, current selected node, gates, attempts, `isParked`, `NodeDetail`, and all existing command controls.
- Produce the same Run component and `composeChrome` output types. Add only Run-specific CSS classes; no new exported API.

- [ ] Add a failing workbench test at 1024×768. Abort the demo event stream using the existing Run test pattern, open the canonical case, click `button.node[data-node="CP-5"]`, and wait for `[data-node-detail="CP-5"]`.
- [ ] Assert rendered ordering: selected detail begins after the route group and ends before `.run-actions`. At 1280×720, assert the detail is to the right of the route group. Use bounding boxes; jsdom cannot validate this defect.
- [ ] Restructure the existing root into three direct children in DOM order: route group, detail group, actions group. Move the existing `actgroup` intact; preserve form state, handlers, refusal text, and stable keys.

```css
.run-layout {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 300px;
  grid-template-areas: "route detail" "actions detail";
  align-items: start;
  gap: 1rem;
  min-width: 0;
}
.run-route { grid-area: route; }
.run-detail { grid-area: detail; }
.run-actions { grid-area: actions; min-width: 0; }
@media (max-width: 1080px) {
  .run-layout {
    grid-template-columns: minmax(0, 1fr);
    grid-template-areas: "route" "detail" "actions";
  }
}
```

- [ ] Keep route controls/help in `.run-route`; keep `NodeDetail` first in `.run-detail`, followed by Run metadata/gates. Do not change the global `.cols.two` breakpoint or use JavaScript viewport detection.
- [ ] Give the selected-node Reason pair classes `node-reason-label` and `node-reason`. Scope both to `grid-column: 1 / -1` under `[data-node-detail] .kv`; left-align `.node-reason`. This gives the long explanation the card width while preserving exact reason text and the separate raw Gate verdict field. Keep overflow wrapping for arbitrarily long tokens.
- [ ] Extend the Run compose tests for open input gates, released input gates plus a waiting QA gate, no input gates, and parked/ended runs.
- [ ] Change the approval ribbon to distinguish input gates: `1 input gate open`, plural equivalent, or `Input gates released` when gates exist and all are released. With no input gates, return `null` rather than claim a release.
- [ ] Name the QA gate in the verdict: `In progress · CP-6 at its QA gate`. After the existing parked/open-input-gate action branches, a RUNNING run with gated nodes gets `Select CP-6 to inspect its QA gate.` Use the first gated module ID already computed. Ended runs must not suggest pending work. Do not create an approve button for a route QA gate.
- [ ] Run `npm run test -- tests/unit/compose.test.tsx tests/unit/run.test.tsx tests/unit/run-reason.test.ts`. Expect exit 0, with ended/parked semantics unchanged. Run the new layout test after rebuilding the demo in Task 6.

**Acceptance:** Selecting any node still updates detail and Attempts; at 1024 px, command forms no longer intervene between the graph and selected detail. Copy never implies that release of an input gate also releases a QA gate.

## Task 2: Make the source register lead to evidence

**Files**

- Modify: `frontend/src/sections/analysis/AnalysisSection.tsx`
- Test: `frontend/tests/unit/analysis.test.tsx`
- Test: `frontend/tests/workbench/evidence.spec.ts`
- Reuse unchanged: `frontend/src/evidence/EvidenceContext.tsx`, `frontend/src/evidence/Overlay.tsx`, `frontend/src/evidence/SourceDrawer.tsx`

**Interfaces**

- Consume `FactIdentity = { record_sha256: string; source_id: string; page: number; index: number }` and `useEvidence().openFact(identity, opener)`.
- Extend the existing `sourceRegister(handoffs)` return entries with `citations: { moduleId: string; identity: FactIdentity }[]`; retain digest, filename, sorted unique pages, count, withdrawn, and current sorting.
- Extend local `SourceRegister` props with optional `onOpen(identity: FactIdentity, opener: HTMLElement): void` and `closeOnOpen?: boolean` (default false). Default opening uses the existing evidence provider. No new provider method.

- [ ] Add a failing unit test that every returned identity points to the original handoff record and its **per-handoff** source-fact index. Include two records citing the same document/page; they must remain independently addressable while the document stays grouped once.
- [ ] Replace the flattened loop with nested iteration over handoffs and `handoff.source_facts.entries()`. Build the identity from the source record, source ID, page and index; never reconstruct it from filename/page alone.

```ts
entry.citations.push({
  moduleId: handoff.module_id,
  identity: {
    record_sha256: handoff.record_sha256,
    source_id: fact.source_id,
    page: fact.page,
    index,
  },
});
```

- [ ] Add one existing-style citation chip per citation beneath its document. Visible text is `CP-1 · p.4`; accessible name is `Read <filename> p.4 cited by CP-1`, with withdrawal announced when applicable. Keep document/page counts and the Withdrawn badge. Add `data-register-fact={identity.source_id}` for stable browser selection.
- [ ] Prefix the inventory opener with `Run evidence ·` so its global scope is clear while a single module is selected.
- [ ] In the inline Audit register, open through `openFact(identity, event.currentTarget)` immediately.
- [ ] For the inventory drawer, use the already-installed `Dialog.Close` from `@base-ui/react/dialog`, rendering each citation chip as its button. The chip callback sets `pendingFact: FactIdentity | null` in `ModuleView`; the native Close starts the existing close animation. Do not call `openFact` while that drawer is open.
- [ ] In the inventory Overlay’s `onClose`, clear the pending identity and inventory opener, then open the pending fact with the **original evidence-count button** as opener. `Overlay.onClose` already runs after `onOpenChangeComplete(false)`, so no timeout or new overlay lifecycle API is necessary. Escape without a pending identity simply closes the inventory.
- [ ] Wrap the drawer’s introductory paragraph and register in `<div className="db">`. This reuses the existing 1rem inset, vertical spacing, and scroll container; no new padding rules.
- [ ] Add a browser flow: open `[data-documents-open]`, select a register citation, wait for `[data-documents-drawer]` to detach, expect `[data-evidence-drawer]` and exactly one visible dialog, then Escape and expect the evidence-count button to regain focus. Reuse the existing event-stream abort pattern and source fixture in `evidence.spec.ts`.
- [ ] Add withdrawal coverage using fixture source `216ec234-c70c-4a5f-8ae6-f4a0262bbe84`, page 12. Observe requests for its `/sources/<id>/pages/` route: selecting the withdrawn citation must produce zero page fetches while retaining the warning and stored citation text.
- [ ] Retain the provider’s snapshot-switch coverage: changing the visible case/run cannot leave an old record open. Add a pending-transition case if existing coverage does not exercise closing the inventory during navigation.
- [ ] Run `npm run test -- tests/unit/analysis.test.tsx tests/unit/evidence.test.tsx tests/unit/evidence-page.test.tsx`. Expect exit 0. Run evidence browser checks in Task 6.

**Acceptance:** A document register is a usable evidence index. No stacked drawers, copied citation objects, stale identity resolution, extra page-fetch path, or focus target that disappears with the inventory.

## Task 3: Make Book coverage and basis truthful

**Files**

- Modify: `frontend/src/chrome/compose.ts`
- Modify: `frontend/src/sections/book/BookSection.tsx`
- Test: `frontend/tests/unit/compose.test.tsx`
- Test: `frontend/tests/unit/book.test.tsx`

**Interfaces**

- Consume `BookDocument.body.rows`, including `snapshot`, `unavailable_reason`, and `refusal`; consume the existing literal `basis` fields. Keep the same `Chrome` and `BookSection` interfaces.
- This summary describes the served document. It does not override local ledger refusal or promise that every period/cell is usable.

- [ ] Import `parseBookDocument` into compose tests and use `fixtures/book.json`. Add a mixed 3-credit/2-forecast test, all-unavailable test, empty-book test, and a typed refused-row case. Do not count periods as credits.
- [ ] Compute available forecasts from rows with a non-null snapshot, null unavailable reason, and null refusal. Use `plural` for all counts. For the current fixture, the Change text begins `3 credits · 2 accepted forecasts · 1 credit unavailable.` Empty books say `No credits to compare.`

```ts
const available = rows.filter(
  (row) => row.snapshot !== null && row.unavailable_reason === null && row.refusal === null,
).length;
const unavailable = rows.length - available;
```

- [ ] For unavailable rows, evidence says `<count> credit(s) unavailable for comparison.` Preserve row-level `NO_ACCEPTED_FORECAST` and refusal details where the Book already renders them; do not imply all refusals mean no forecast exists.
- [ ] Fix the shared partial-evidence composition at its root: combine the section-specific evidence and partial note rather than replacing the evidence.

```ts
evidence: [facts.brief.evidence, notes].filter(Boolean).join(" ") || null,
```

- [ ] Update the existing Analysis partial-status test to retain its citation/withdrawal counts plus the partial note. Cover null evidence and empty notes, and check all `composeChrome` callers remain on the same type.
- [ ] Replace the always-visible Basis definition list with `All accepted periods · All accepted scenarios · Accepted projections only`. Keep the exact original fields in a native `<details className="help">` with summary `Exact comparison basis`; retain existing data attributes. These are fixed wire literals, so do not add a mapping framework.
- [ ] Run `npm run test -- tests/unit/compose.test.tsx tests/unit/book.test.tsx`. Expect exit 0, with passports, unavailable cells, ledger behavior and exact decimal assertions unchanged.

**Acceptance:** A missing/refused forecast reduces the accepted-forecast count and remains explained even in a partial document. Basis wording is clear without inventing filters or altering comparison rules.

## Task 4: Put the saved report before its machinery

**Files**

- Modify: `frontend/src/sections/report/ReportSection.tsx`
- Test: `frontend/tests/unit/report.test.tsx`
- Test: `frontend/tests/workbench/layout.spec.ts`

**Interfaces**

- Keep `Narrative`, `Revisions`, `Artifact`, `FilingControls`, `live`, and `setLive` unchanged. No new exported component and no changes to Committee’s shared narrative rendering.

- [ ] Add an ordering assertion using the existing report mount helpers: `[data-report-narrative]` precedes Filing, revisions and artifacts. Retain tests for all governed actions and inert hostile text.
- [ ] Keep the compact case-title/report-state header first. Put the existing four identity rows inside a closed native `<details>` named `Revision identities`; all exact digests and copy controls remain available after expansion.
- [ ] Move the existing Narrative panel directly after that compact context. Put the existing Filing controls next, followed by Revisions and Artifacts. Move JSX blocks; do not duplicate them or remount the filing editor with changing keys.
- [ ] When `revision_id === null` and narrative is empty, show `No saved narrative yet. Write the draft below and save a revision.` If a saved revision carries no narrative, say `This revision contains no saved narrative.` Do not synthesize narrative from artifacts or overwrite draft text.
- [ ] Extend the browser layout check with the saved fixture at 1280×720: the Narrative heading and beginning of the saved text are visible without first scrolling through revision history/artifacts. Test document order separately from this fixture-specific geometry.
- [ ] Run `npm run test -- tests/unit/report.test.tsx tests/unit/report-figures.test.tsx`. Expect exit 0. Verify citation chips still open existing evidence and saved/frozen/filed authority still controls the same actions.

**Acceptance:** The first reading task is the saved report; identity/history remain one disclosure or a later section away. Drafting, signing, freezing and filing retain their existing authority and outcomes.

## Task 5: Preserve orientation at zoom and in the case list

**Files**

- Modify: `frontend/src/chrome/SiteHeader.tsx`
- Modify: `frontend/src/sections/directory/CaseRegister.tsx`
- Test: `frontend/tests/workbench/layout.spec.ts`
- Retain: `frontend/tests/unit/chrome.test.tsx`, `frontend/tests/unit/directory.test.tsx`

**Interfaces**

- No changed props, routes, header height, or case-link semantics. Keep the section h1 as the navigation focus destination.

- [ ] Add a failing 320×640 Book test with a selected case. Assert the h1’s complete text fits its box (`scrollWidth <= clientWidth`), its bounds stay inside the viewport, and Partial/theme controls remain visible. Run in both themes through the existing theme-selection pattern.
- [ ] Below 640 px hide the issuer breadcrumb and its separator using the existing responsive utilities. Reserve the h1’s intrinsic width with `shrink-0`; remove its truncation. Keep the desktop issuer trail unchanged, the 56px header height unchanged, and all warnings/actions reachable. Do not solve this by reducing type size or hiding the warning.
- [ ] In `CaseRegister`, swap the Title and Case header/cell pairs so the issuer title is the first column, which is also the pinned column. Preserve the adjacent shortened ID/full-ID title and the single `Open case <title>` action. Retain long-title wrapping and the named keyboard-scroll region.
- [ ] Run `npm run test -- tests/unit/chrome.test.tsx tests/unit/directory.test.tsx`. Expect exit 0. Adjust any column-order assertions only to reflect the deliberate order change; do not weaken row-action, identity, or overflow assertions.

**Acceptance:** Book remains visually identifiable at zoom width; desktop trails still show issuer context. Directory scanning begins with a recognizable title while retaining case identity.

## Task 6: Review and validate the integrated result

- [ ] Run `$impeccable polish` on the implemented findings with this plan as the scope. Apply only the final spacing, hierarchy, copy and reflow corrections supported by the acceptance conditions; then perform the required code reviews below.
- [ ] Run the required `confidence-review` skill before declaring completion. Investigate: drawer close/open ordering and focus; pending identity during case/run changes; withdrawal fetch suppression; Run grid with long metadata; parked/ended QA copy; Book zero/refused/mixed counts and all partial-summary callers; unsaved/saved Report flow; narrow h1 and Directory long titles. Patch confirmed bugs and rerun only the affected checks.
- [ ] Run `rewrite-tournament` in no-argument post-edit mode on changed non-trivial functions, following its bounded candidate/scope rules. Prioritize the actual changed `sourceRegister`/drawer-transition logic and Book summary composition. Do not tournament JSX movement, CSS, docs, tests, or generated files. Apply only proven improvements, then rerun relevant checks.
- [ ] Run the full unit suite once after the final code/review edits: `npm run test`. Expect exit 0.
- [ ] Run `npm run typecheck` and `npm run lint`. Expect exit 0, no TypeScript errors, lint warnings, formatting failures, or vocabulary/test-coverage failures. Fix formatting with the existing formatter, without unrelated file churn.
- [ ] Run `npm run build:demo`. Expect a successful `dist-demo` export.
- [ ] Run `npm run test:workbench -- tests/workbench/layout.spec.ts tests/workbench/evidence.spec.ts tests/workbench/chrome.spec.ts tests/workbench/run.spec.ts`. Expect every selected test to pass in Chromium, Firefox and WebKit with no retries. The config owns port 4173; stop a manually started preview first.
- [ ] Run `npm run a11y`. Expect the complete configured route × engine × viewport × theme matrix, zero scan errors, and zero violations. Do not reduce the matrix to obtain a pass.
- [ ] Use one bounded native-browser visual pass: Run/Analysis/Report/Book at 1280 and 1024, header/evidence at 320×640, and affected surfaces in light/dark. Check keyboard evidence opening, Escape, focus return, and horizontal Book/Directory table scrolling. Preserve original theme/viewport and close temporary tabs afterward.
- [ ] Run the Impeccable post-edit checks required by the installed skill, once on the final changed UI scope; reuse valid detector output instead of rescanning unchanged files. A clean detector does not substitute for the behavioral checks above.
- [ ] Update `DESIGN.md` only where the approved behavior changes its documented examples: distinguish input/QA gates in summary copy and explain the issuer breadcrumb’s zoom-only hiding. Do not rewrite the design system.
- [ ] Re-run `$impeccable critique` after implementation to record a comparable snapshot and confirm F1–F5/M1–M3 against the acceptance conditions. The numerical score is supporting evidence, not the pass condition.
- [ ] Review the final diff for unrelated changes and report tests, remaining limitations and the new critique snapshot. Commit only if the user requests it; no deployment is included.

## Tooling update disposition

`npx impeccable update` was attempted on 2026-09-27 and exited 1 because signed-bundle verification returned HTTP 404. The installed skill remains **4.3.1**; npm reports CLI **4.1.0** as latest. The updater’s requested `skill-v4.4.0` release/signature URL returned 404; the latest published signed skill release found was `skill-v4.3.1`.

Retry the official updater when that release is available, then verify the installed version before another critique. Do not bypass signature checks or substitute an unsigned main-branch bundle. This upstream failure does not block the application remediation above.

## Plan self-review

- All five priority findings and three actionable minor findings map to explicit tasks and observable completion conditions.
- The unnamed demo modules and graph supporting-text clamp are accounted for without speculative changes.
- New evidence identities use the provider’s existing type; the close transition uses the Overlay’s existing completion callback; no API is invented.
- Shared partial-copy behavior is fixed once in `composeChrome` and exercised beyond Book.
- At planning time, no application changes or tests had been run; the execution record below supersedes that status.

## Execution record

The Run route/detail/actions reading order, input-versus-QA gate copy, source-register citation links, Book coverage and basis copy, Report narrative order, zoomed header, and Directory column order are implemented. The source-register review also found and fixed two edge cases: each grouped citation retains its own withdrawal state, and nested inline citation rows no longer inherit the document-row border/padding. A pending inventory-close case switch test confirms an old evidence drawer does not survive the new visible case. The final full-suite run exposed a Run preview timing gap: the preview could render before its fingerprint reached Start. The preview now updates that fingerprint before displaying its receipt; the timing test passed three consecutive focused runs. The existing source provider, financial values, command authority, and route identity checks remain unchanged.

Verification: **512 unit tests across 43 files** (including the final navigation-during-close test), typecheck, lint, and demo build passed; **75 selected browser tests** passed in Chromium, Firefox and WebKit; after the Run timing fix, all **30 focused Run/layout browser tests** passed across those engines. The full axe matrix completed **720/720 entries** with zero violation nodes, scan errors or layout failures. The final CSS selector change passed all 12 focused evidence browser tests and lint. The post-edit Impeccable detector returned `[]`, exit 0. The no-argument rewrite tournament considered `sourceRegister` and `book`; the incumbents held because allocation-saving alternatives reduced clarity without improving these bounded workflows. Confidence review confirmed and patched the per-citation withdrawal, nested-selector and preview-order defects; drawer transition, snapshot guard, Book counts, Report order and zoom reflow were verified with code tracing and focused browser/unit checks.

The comparable post-edit critique is archived at `.impeccable/critique/2026-09-27T21-33-13Z__frontend-src-app-app-tsx.md`. Its independent design score was **20/40** versus the earlier **28/40**; this pass followed Directory's primary action and found a pre-existing demo fixture mismatch that the earlier pass did not test, so the score change is not evidence of a remediation regression. Assessment B verified every planned F1–F5/M1–M3 condition. The browser detector overlay was unavailable because mutable injection was rejected by the read-only browser API; screenshots, DOM and geometry were used. No code was committed or deployed.

## Follow-up plan from the post-edit critique

These findings are newly recorded scope, not a reason to weaken wire identity validation or change the financial/approval rules.

1. **P1 — make the demo's Directory case links lead to served case journeys.** The Directory Carvana row uses `ff1fbf5a-…`, while Analysis and Run fixtures use `00000000-…0001`; the split is present in `HEAD`. Inventory fixture case/run identities and the demo route lookup first. Choose one coherent canonical demo case or serve a valid fixture for each linked case; if other case journeys are not served, make that unavailability explicit at the row rather than offering a broken Open case link. Add a browser test that follows the visible Directory action and receives matching Analysis/Run identity, while the existing wrong-identity refusal test still passes.
2. **P2 — explain Analysis readiness without inventing a gate.** Trace the conclusion, accepted count and CP-1C limitation fields to distinguish “accepted” from “needs review.” Name the issue beside the ready verdict and offer a link to CP-1C. Test complete, restricted and partial states against the served wire facts; do not call a review an approval or block filing unless the backend says so.
3. **P2 — expose module names during Analysis navigation.** Keep all twelve route-ordered tabs and their keyboard behavior. Show the selected module's name and warning meaning adjacent to the selector in both desktop and zoom reflow. Verify the name is visible without hover at 1280 and 320 px and remains announced to assistive tech.
4. **P2 — shorten selected-node context at zoom widths.** The original 1024 px defect is fixed: CP-5 detail begins at y807 after the route ends at y698 and before actions at y1542. Test a compact selected-node anchor or similarly small summary before the horizontally scrollable graph, preserving the full detail, graph and command order. Accept when the selected node and its reason are visible in the first 1024×768 viewport after selection, with no duplicate controls or stale state.
5. **P3 — strengthen the inventory-close regression check.** The current jsdom test switches cases after clicking a citation but does not establish that the inventory is still in its 200ms close phase. Add a browser check that first observes the `data-ending-style` attribute, then switches cases and asserts zero dialogs, zero old-source page requests, and focus on the section heading. The current flow was independently exercised in Chromium, Firefox and WebKit with those assertions and passed; this is coverage work, not a confirmed runtime defect.

## Astra adversarial-review closure

The requested Astra xhigh three-persona review returned two warnings and one test-gap note. Both warnings were reproduced and fixed. An unbroken Directory title in the new pinned first column could cover `Open case` after horizontal scrolling. A bounded title span now lets that text wrap without expanding or collapsing the sticky cell; a browser hit-target check passes in Chromium, Firefox and WebKit, and manual checks at 320, 768, 1024 and 1280 px all hit the action. Two source facts from the same module, document and page produced identical citation-chip labels; each chip now includes its ordinal within the document, with a unit test asserting distinct visible and accessible names. The pending-close note is recorded in the follow-up plan above. The review's wrong-document-digest probe was refused with `WIRE_IDENTITY_MISMATCH` and no page text rendered.

After these patches, the full unit suite passed **513/513 tests in 43 files**, typecheck and lint passed, the demo build succeeded, and the full workbench passed **114/114 browser cases** across Chromium, Firefox and WebKit. The final axe matrix passed **720/720 entries** with zero violation nodes, scan errors or layout failures. The final Impeccable detector returned `[]` with exit 0. No new non-trivial function was added in this closure, so the prior no-argument rewrite-tournament result still covers the material functions; the title wrapper and citation label edits are below the skill's materiality threshold.

Final confidence review: the sticky table sizing and same-page citation-label collisions were confirmed with concrete browser/fixture cases, patched at their rendering roots, and covered by regression checks. The bounded title was also checked at four viewport widths; the action remained the pointer target. The inventory-close navigation concern was exercised during its actual ending phase in all three engines and found safe; its weaker jsdom assertion remains follow-up coverage work. The citation identity still resolves through the snapshot guard, and the adversarial wrong-digest probe failed closed. The demo Directory identity split, Analysis readiness copy, CP-code navigation and long Run canvas remain in the follow-up plan; they predate these patches or lie outside this remediation's acceptance scope. `git diff --check` passed. No commit or deployment was made.

## Follow-up closure — Impeccable 4.4.0

All five follow-up items are complete. The new GitHub-main Impeccable bundle reports **4.4.0** and is pinned to [upstream commit 9d715cc](https://github.com/pbakaus/impeccable/commit/9d715cc4f5564a990ca8345abfdd5df6dc9b41c8). It is installed in both `/Users/ericguei/.agents/skills/impeccable` and `/Users/ericguei/.codex/skills/impeccable`; the prior Codex copy is backed up. The launcher context and final detector used the new bundle. This is the main-branch bundle, not a claim that a signed 4.4.0 release exists.

| Follow-up | Status | Delivered and verified |
| --- | --- | --- |
| Demo Directory journey | Complete | Carvana's Directory, Analysis, Run and Upload fixtures share one case UUID; Directory's latest run matches Run. The three unserved case rows say “Unavailable in demo.” A browser follows the visible case action through Analysis, Run and Upload in all three engines. Real API links and identity refusal remain intact. |
| Analysis readiness | Complete | The compact summary names CP-1C's served warning and links to it. Partial Analysis leads with accepted/pending counts and labels the conclusion as the latest accepted module. Complete, restricted and partial wire variants pass their assertions. No approval gate was added. |
| Selected Analysis module | Complete | The selected module's name and warning/limitation appear beside the selector at 1280 and 320 px, with a polite live announcement. A blank note now falls back to the severity meaning; a regression assertion reproduced the failure before the fix. Route order and keyboard selection remain intact. |
| Run context at zoom | Complete | A compact selected-node summary precedes the graph below 1080 px, using the full card's existing reason helper. After CP-5 selection, the entire summary fits in the first 1024×768 and 320×640 viewports. The full detail and command order are preserved. |
| Inventory close coverage | Complete | The browser observes the actual empty `data-ending-style` attribute before switching case during close. Chromium, Firefox and WebKit all verify zero dialogs, zero old-source page requests and heading focus. |

Verification: the full unit suite passed **514/514 tests in 43 files**, and the full workbench passed **123/123 browser cases** across Chromium, Firefox and WebKit. The full accessibility matrix passed **720/720 entries** with zero violation nodes, scan errors or layout failures. After the final blank-note fallback and copy separator, **38 focused unit tests**, **9 focused browser cases** and **24 focused Analysis accessibility entries** passed; final typecheck, lint and demo build passed. A batched desktop/mobile screenshot inspection confirmed both changed surfaces, and the final Impeccable detector returned `[]`, exit 0.

The required confidence review patched the blank-note fallback and warning/link separator, then closed the identity, readiness, query-preservation, selected-node and drawer-order concerns. The no-argument rewrite tournament covered `analysis` and `SectionTabs`; both incumbents held. The ranked review, impact sets, tournament justification, final code and exact verification commands are recorded in [the follow-up review](2026-09-27-caos-follow-up-review.md). No commit or deployment was made.

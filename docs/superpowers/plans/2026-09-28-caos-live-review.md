# CAOS live review — 2026-09-28

Accepted in Impeccable 4.4.0 live mode:

- `5c932a69`, variant 2: module names replace codes in the compact Analysis strip and zoomed native select; 28px rows, 6px inline padding, 13px names. A catalog without a name keeps its code. Route-node IDs, QA shapes/words, selected-name announcement and review reasons remain intact.
- `837d0336`, variant 2: the header's case name uses 16px/24px Geist, weight 500 and foreground ink. Its title/case ID, truncation, header layout and zoom hiding remain intact.

Existing PRODUCT.md was copied unchanged from `/Users/ericguei/Claude/Projects/CAOS/PRODUCT.md` into this worktree. No product assumptions were invented. Both accept sessions reached `phase: completed`; source previews, inline preview CSS and parameter markers were removed. Accepted styles use existing Tailwind utilities.

## Confidence review — accepted module strip and case name

Least confident about (ranked):

1. A missing catalog name could leave an unnamed control.
   investigated → the parser accepts a required but empty/whitespace-only string (`wire/v1/documents.ts:26`). A raw fixture with `module_name: " "` parsed successfully and the new tab had only `, success`, confirming the bug before the patch.
   verdict → CONFIRMED bug.
   patch → normalize blank names to `cp: null` once in `compose.analysis`; the desktop tab, select, selected-name text and summary all reuse the fallback. The regression now passes. Nonblank catalog names are returned verbatim.
2. Display names could accidentally replace route identity.
   investigated → Workspace resolves selection and writes the `tab` query by `Tab.id`; option values, trigger IDs and `aria-controls` still use that ID. ArrowRight selects `rn-cp-1`; End selects `rn-cp-cf`; zoomed selection reaches `rn-cp-1c` in all three engines.
   verdict → fine (69 focused unit checks, typecheck and browser checks).
   patch → n/a.
3. Baking preview CSS might lose the chosen density, active state or contrast.
   investigated → the accepted 28/6 values map directly to existing `h-7`/`px-1.5` utilities. Browser computed values were 28px height, 6px padding and 13px font; both themes passed the same assertions. Active tabs retain their border and muted fill. Names use the existing muted-foreground token and active/issuer text uses foreground; these are the established text-safe theme tokens. Names stay sans, fallback codes mono.
   verdict → fine (computed styles plus browser assertions).
   patch → removed all preview CSS and used existing utilities; no custom stylesheet or new token was needed.
4. The larger case name could displace the heading or break zoom reflow.
   investigated → the original min-width/truncation and zoom-hiding rules remain. In both themes the issuer is 16px, weight 500 and 24px high; at 320px it is hidden, the Analysis heading remains visible and the page has no sideways overflow.
   verdict → fine (Chromium, Firefox, WebKit).
   patch → n/a.
5. The two responsive controls might lose keyboard or screen-reader semantics.
   investigated → Base UI's controlled value, activateOnFocus, one tab stop and panel relationships are unchanged. The native control is announced as `combobox "Analysis view"`; role-based selection verifies its accessible name and preserves module QA words. Selected warnings remain visible and aria-live at desk/zoom widths.
   verdict → fine (focused unit and browser checks).
   patch → the regression uses the native control's accessible role rather than exact label text, because the enclosing label's DOM text also contains option text.
6. Test browsers might interfere with the active live session.
   investigated → the temporary injection also appears in a build made during live mode. Headless Firefox/WebKit selected the right module but lost focus while the overlay attached. Blocking only `live.js` in the keyboard test made the exact previously failing check pass without any product change; the final three-engine run passed.
   verdict → confirmed test-environment interference, not a product focus bug.
   patch → the keyboard regression aborts the optional live overlay request. The user's live browser remains connected. Rebuild once the live injection is removed before shipping a build.
7. A picker scaffold might point at a different occurrence of `truncate`.
   investigated → the second preflight proposed AppSidebar's `{item.label}`, which did not match the picked header's `data-case` and `{crumb}`. Before publication, an explicit SiteHeader target re-scaffolded the correct span. No sidebar code was changed.
   verdict → fine after source verification.
   patch → corrected the live helper's target, preserving exact issuer content and case metadata.
8. Cleanup or a readability rewrite could leave temporary markup or alter unrelated work.
   investigated → both official completion gates passed; neither target contains live variant/carbonize/parameter markup. A backup preceded the tournament winner. Current references and caller contracts were checked, and the final diff retained prior work. A readonly-fixture test mutation initially failed typecheck; it now changes the raw JSON before parsing.
   verdict → fine (typecheck, lint, build, diff check and focused tests).
   patch → complete source cleanup and raw-fixture test setup.

Fixed: blank-name fallback, test-overlay focus interference and readonly test setup.
Verified fine: identity/query mapping, controlled selection, keyboard focus, zoom reflow, accepted dimensions, case metadata and preview cleanup.
By-design: CP-6A/CP-7 retain codes because this catalog supplies no descriptive names; the user accepted a horizontally scrolling name strip. Live injection remains only while the session is active.
Still open: none in the accepted changes. GitNexus is 23 commits behind, so it was used for discovery and checked against current references and the compiler.

## Rewrite tournament — no-argument post-edit mode

Targets: `SectionTabs` and the new blank-name guard in `compose.analysis`. The SiteHeader change is styling only, so it was skipped. Prior branch work was not re-tournamented.

Impact set: SectionTabs → Workspace → App.Resolve → App.Shell; chrome/compose unit tests. analysis → factsOf → composeChrome → Workspace.chromeOf; analysis/compose tests and Workspace's selected review. GitNexus context/impact identified these; current references were read and the typechecker checked the complete caller contract.

Distinct Incumbent, Speed, Memory, Readability and blind Arbiter roles reviewed the actual source and invariants. Blind bracket: speed beat the indexed-loop memory version; the direct-render readability version beat the mutable-array speed version; readability beat the incumbent. No measured performance gain was claimed.

Winner: Snippet A in the final match (anonymous candidate D, Readability), `frontend/src/chrome/SectionTabs.tsx:10`. Its compose guard stays unchanged.

Justification:

- Names the accepted density classes once, making the 28px/6px/13px rule easy to inspect.
- Keeps direct maps beside their controls, avoiding manual arrays, loop indices, caches and new dependencies.
- Preserves signatures, IDs, controlled callbacks, all class tokens and conditional output under the declared types.

Final code:

```tsx
// The section's own views. Never navigation between sections. Arrow keys move
// between them and select as they go; at a zoomed width (400%, D63) they are a
// native select, since a dozen wrapped tabs were taller than the window.
import type { ReactNode } from "react";
import { SeverityMark } from "./SeverityMark";
import { NativeSelect, NativeSelectOption } from "@/components/ui/native-select";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import type { Tab } from "@/wire";

export function SectionTabs({
  label,
  tabs,
  active,
  onSelect,
}: {
  label: string;
  tabs: Tab[];
  active: string | null;
  onSelect: (id: string) => void;
}) {
  // A tab list of no tabs is a widget with nothing in it, announced on every
  // page for nothing: a v1 document declares none (FE-11).
  if (tabs.length === 0) return null;
  // Past eight views, module names stay in a compact strip under the header.
  // The selected name and review reason remain visible below it.
  const dense = tabs.length > 8;
  const tabSize = dense ? "h-7 px-1.5 text-[13px] text-muted-foreground" : "h-8 px-2.5";
  const selected = tabs.find((tab) => tab.id === active);
  const meaning =
    selected?.note?.trim() ||
    (selected?.severity === "RESTRICTED"
      ? "Accepted with limitations"
      : selected?.severity === "WARNING"
        ? "Needs review"
        : selected?.severity === "CRITICAL"
          ? "Blocked or failed"
          : null);
  return (
    <div
      data-section-tabs
      data-dense={dense || undefined}
      className={dense ? "sticky top-14 z-10 -mx-1 bg-background px-1 py-1" : undefined}
    >
      <label className="block sm:hidden">
        <span className="sr-only">{label} view</span>
        <NativeSelect
          className="w-full"
          value={active ?? ""}
          onChange={(event) => onSelect(event.target.value)}
          data-tab-select
        >
          {tabs.map((tab) => (
            <NativeSelectOption key={tab.id} value={tab.id}>
              {tab.cp ?? tab.label}
              {tab.severity && tab.severity !== "SUCCESS" ? ` · ${tab.severity.toLowerCase()}` : ""}
            </NativeSelectOption>
          ))}
        </NativeSelect>
      </label>
      <Tabs
        value={active}
        onValueChange={(value) => onSelect(String(value))}
        className="max-sm:hidden"
      >
        <TabsList
          variant="line"
          aria-label={`${label} views`}
          activateOnFocus
          className={`w-full justify-start gap-1 group-data-horizontal/tabs:h-auto ${dense ? "flex-nowrap overflow-x-auto" : "flex-wrap"}`}
        >
          {tabs.map((tab) => (
            <TabsTrigger
              key={tab.id}
              value={tab.id}
              id={`tab-${tab.id}`}
              aria-controls={`tabpanel-${tab.id}`}
              title={dense && tab.cp ? `${tab.cp} · ${tab.label}` : undefined}
              // Keep the accepted density in existing utilities, with no preview CSS.
              className={`flex-none after:hidden data-active:border-border! data-active:bg-muted! data-active:shadow-none ${tabSize}`}
            >
              {tab.severity && <SeverityMark severity={tab.severity} decorative />}
              <span className={tab.cp ? "font-normal" : "font-mono text-[13px]"}>
                {tab.cp ?? tab.label}
              </span>
              {tab.severity && <span className="sr-only">, {tab.severity.toLowerCase()}</span>}
            </TabsTrigger>
          ))}
        </TabsList>
      </Tabs>
      {dense && selected && (
        <p className="px-2 pt-1 text-sm text-foreground" data-selected-view aria-live="polite">
          {selected.cp ?? selected.label}
          {meaning ? ` · ${meaning}` : null}
        </p>
      )}
    </div>
  );
}
```

The reviewed guard remains:

```tsx
cp:
  !handoff.module_name.trim() || handoff.module_name === handoff.module_id
    ? null
    : handoff.module_name,
```

Verification:

- `npm test -- tests/unit/compose.test.tsx tests/unit/chrome.test.tsx tests/unit/analysis.test.tsx` → 69 passed in 3 files.
- `npm run typecheck` → passed; all impact-set caller contracts compile.
- `npm run lint` → passed; formatting, vocabulary and test coverage checks have zero findings.
- `npm run build:demo` → passed, 25 routes exported. Existing chunk-size advisory remains.
- `npm run test:workbench -- tests/workbench/layout.spec.ts -g 'Analysis.*(name|names)'` → 6 passed across Chromium, Firefox and WebKit, including both themes, keyboard selection, exact dimensions and 320px reflow.
- Concrete boundary invariant: blank catalog name parses and falls back to the original module ID in both tab controls; meaningful names remain verbatim.
- `git diff --check` → passed. Root re-read the actual diff after applying the winner; no caller signature, route or financial fact changed.

## Confidence review — accepted Run dependency flow

Scope: live event `24b7290b`, variant 2, with `pace=1.2`, `flow-weight=1.75`, and `focus-weight=3`. The selected preview is permanent in `RouteGraph.tsx` and the existing route section of `caos.css`. Unselected stage counters and all preview wrappers, CSS scopes, manifests and parameter attributes were removed. `live-complete --id 24b7290b` returned `phase: completed`.

Least confident about, ranked:

1. **Showing motion after work ends or while a gate is holding it.** Investigated the complete call chain from RunSection through RouteGraph to runningOf/blockingOf. Flow requires an accepted source, an actually running target, no waiting gate, and no blocking verdict. Verified active work, gate waits, accepted restricted work, and all four ended run statuses by rerendering the graph with concrete fixture states. Verdict: fine. No new execution flag or status inference was introduced.
2. **Confusing module IDs with route node IDs.** The existing edgesOf resolver remains authoritative; the new metadata map uses the resolved route node IDs. The host-shaped unit check still draws every pinned edge and names `CP-5 → CP-6` correctly. Missing endpoints still skip before routing. Verdict: fine.
3. **Pausing loops and cleaning up observers.** The visibility effect observes the graph, combines intersection with document visibility, and disconnects/removes its listener on unmount. A concrete observer callback test verifies on/offscreen and visible/hidden transitions, then unmount cleanup. In environments without IntersectionObserver the effect uses document visibility; the normal jsdom tests exercise that fallback. Verdict: fine; no timers or motion dependency.
4. **CSS layers changing the chosen parameters or overriding reduced motion.** Inspected the real stylesheet and the global tokens motion rules. Computed browser styles verify the chosen 1.92s pulse, 3px connected edge and no animation under reduced motion in Chromium, Firefox and WebKit. The global reduced-motion transition rule remains authoritative. Verdict: fine.
5. **Breaking controlled selection or pulling readers back after refetch.** RunSection still owns selection. The graph calls onSelect with the same route node ID and keeps aria-pressed. Existing once-per-route scrolling tests and new keyboard Enter tests pass; the compact detail still precedes actions and the desktop detail remains alongside the canvas. Verdict: fine.
6. **SVG arrow fragments failing in an engine.** React useId provides the marker identity. The unit and three-engine browser checks verify each edge references the actual marker; the bounded screenshot inspection shows arrowheads at the ends of square edges. Verdict: fine.
7. **Stage labels, reasons or page width becoming clipped.** The existing graph geometry is unchanged. Browser measurements find no overlapping stage labels or clipped reason lines; both themes reflow at 320 CSS px without page overflow. One batched visual inspection covered light/dark desktop and zoom screenshots. Verdict: fine; the two-dimensional graph scrolls within its panel.
8. **Expanding the runtime for visual feedback.** Reused existing status helpers and the existing opacity pulse. Derived maps/lines stay local to rendering, with one observer per mounted graph and no package additions. Verdict: by-design. No speculative animation framework or performance refactor was added.
9. **Leaving live scaffolding in source.** The official completion gate verified clean source. The real CSS contains semantic route-flow selectors and literal accepted values; no preview selector or parameter variable remains. Verdict: fine. The live script remains injected only while live mode is active and must be removed by the normal stop command before the final clean export.

Fixed: no confirmed product bug found in this accepted graph change. Cleanup removed unused variant-only stage counters and baked the accepted parameters.

Verified fine: status/gate transitions, restricted acceptance, ended run guards, host endpoint IDs, observer lifecycle, reduced motion, keyboard selection, marker references, geometry, theme/reflow and carbonize cleanup by the concrete checks above.

By-design: one visibility observer per graph, native SVG/CSS feedback and existing helper semantics. No new dependencies.

Still open: none. At the user's “end live” request, the foreground poll was interrupted and the official helper stop removed its injected script. The demo export was rebuilt successfully; source and exported HTML/JavaScript scans found no live scaffolding. The stop command left extra closing-tag indentation in index.html, which Prettier restored to the original formatting.

The user said “no tournaments” while the post-edit tournament was starting. Both running roles were interrupted immediately; no candidate was applied and no further roles were started. Direct confidence review and focused checks continued.

Verification:

- `npm run test -- tests/unit/route-graph.test.tsx tests/unit/run-reason.test.ts tests/unit/run.test.tsx tests/unit/workspace-live.test.tsx tests/unit/helpers.test.ts` → 92 passed in 5 files.
- `npm run typecheck` → passed; impact-set callers compile.
- `npm run lint` → passed after the browser-test addition; formatting, vocabulary and coverage checks have zero findings.
- `npm run build:demo` → passed; 25 routes exported, with the existing chunk-size advisory.
- `npm run test:workbench -- tests/workbench/run.spec.ts tests/workbench/layout.spec.ts -g 'dependency flow|route stage headers|selected Run node'` → 9 passed across Chromium, Firefox and WebKit.
- GitNexus context/upstream impact identifies RunSection and the graph test helper directly, plus run/workspace-live tests indirectly. The index is 24 commits behind and lower-bound; current `rg` reference discovery and TypeScript checking supplement it.
- `git diff --check` → passed; root inspected the actual RouteGraph/CSS diff.

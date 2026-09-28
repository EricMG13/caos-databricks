# Follow-up post-edit reviews

## Confidence review — five critique follow-ups

Least confident about (ranked):

1. Demo versus real case identity — a fixture-only fix could hide a real transport defect.
   investigated → Directory and Upload default/variant fixtures now share Analysis/Run's canonical case UUID. Directory's latest run UUID, timestamp and RUNNING status match the served Run. The browser follows Directory → Analysis → Run → Upload; the existing wrong-identity refusal checks still pass. The unavailable guard applies only in demo mode.
   verdict → fine (fixture inspection, full unit suite and three-engine journey test).
   patch → coherent fixtures and explicit unavailable rows; transport validation unchanged.
2. Analysis readiness and QA semantics — an accepted conclusion can look final while work remains, and review copy must not invent an approval gate.
   investigated → pending work takes precedence in the verdict; the brief labels Committee Ready as the latest accepted module's conclusion. Complete and restricted variants retain their served committee status. The summary names the first non-success accepted handoff and links to it. A rendered warning lacking punctuation ran into its link.
   verdict → fine for readiness; CONFIRMED copy defect for the missing separator.
   patch → a visible separator before Review; complete/restricted/partial composer assertions and browser review-link checks pass.
3. Empty warning text — wire text permits blank strings, which could suppress the selected module's severity meaning.
   investigated → a WARNING tab with note=" " reproduced “Module 0 ·” rather than “Needs review”; the regression assertion failed before the patch.
   verdict → CONFIRMED bug.
   patch → trim and truthy fallback in SectionTabs; the same assertion now passes.
4. Review navigation and accessible naming — the new link and selected-name line must preserve the current case and tab controls.
   investigated → the link clones URLSearchParams and changes only tab; SectionTabs retains native selection, arrow activation, aria-controls and full accessible names. The selected name/reason is aria-live polite and fits at 1280 and 320 px.
   verdict → fine (source/caller tracing, typecheck, focused unit/browser checks and 24 final axe entries).
   patch → n/a.
5. Run selection, stale state and reflow — the short summary could disagree with the full card or duplicate a command.
   investigated → both render the same selected node from the current run; choice is keyed by run and validated against current nodes. Both use reasonOf and blockingOf. The summary has no controls, is hidden above 1080 px, and precedes the graph at zoom widths. CP-5's summary ends at y634 at 1024×768 and y246 at 320×640 after selection; no horizontal page overflow.
   verdict → fine (source tracing, three-engine geometry checks and batched desktop/mobile screenshots).
   patch → n/a.
6. Inventory close ordering — passing after the animation would not prove the pending-open guard.
   investigated → the browser first observes Base UI's actual empty data-ending-style attribute, then switches case during that close. All three engines report zero dialogs, zero old-source page requests and focus on the section heading.
   verdict → fine; this was a coverage gap, not a runtime defect.
   patch → browser regression coverage.

Fixed: blank-note severity fallback and review-link separator.
Verified fine: identity validation, readiness precedence, case-preserving review navigation, selected-node consistency, responsive geometry, close-phase guard (checks above).
By-design: one complete demo case journey; the other rows explicitly say Unavailable in demo. Real API rows retain their links.
Still open: none within the five follow-up acceptance conditions.

## Rewrite tournament — no-argument post-edit mode

Scope came from git diff HEAD --stat. The two most material changed symbols were analysis and SectionTabs. Workspace/CaseRegister's small rendering branches were below these in impact and excluded by the two-symbol cap; Run reuses existing reasonOf/blockingOf. Prior sourceRegister/book work was already tournamented. The roles ran inline sequentially to keep this long session bounded.

Impact set: GitNexus context and upstream impact found analysis → factsOf → composeChrome → chromeOf, and SectionTabs → Workspace → Resolve → Shell. The index is 22 commits behind a sibling checkout, so current rg references and TypeScript compilation were authoritative. Current consumers additionally include SectionSummary's review props, the Tab wire interface, and compose/chrome unit tests. Signatures, route order, conclusion selection, QA severity precedence, accepted/pending semantics, URL identity, native select/keyboard behavior and aria contracts must remain unchanged. No financial calculations or authority rules are in these targets.

### analysis

Winner: Incumbent holds, frontend/src/chrome/compose.ts:264–335; no tournament replacement.

Justification:

- Speed and memory candidates combine citations, severity and tabs in a manual loop; both keep O(handoffs + citations) and trade bounded temporary arrays for substantially more mutable state.
- The readability candidate moves the verdict into an if-chain. It lengthens the same precedence rules without removing any state or caller contract.
- The incumbent keeps route order and screening/weak/pending precedence explicit, with focused fixture assertions. No challenger established a useful benefit for the twelve-module workflow.

Bracket: memory over speed (fewer intermediate objects); readability over memory (clearer domain states); incumbent over readability (less code with the same verified behavior).

Final code:

```ts
function analysis(document: AnalysisDocument): Facts {
  const { handoffs, pending, displayed_run_status: status, blocked_by: blocked } = document.body;
  const conclusion = conclusionOf(handoffs);
  const weak = handoffs.filter((handoff) => handoffSeverity(handoff) !== "SUCCESS");
  const citations = handoffs.flatMap((handoff) => handoff.source_facts);
  const documents = new Set(citations.map((fact) => fact.document_sha256)).size;
  const withdrawn = citations.filter((fact) => fact.withdrawn_at !== null).length;
  const ready = conclusion
    ? `${conclusion.committee_status} · ${scopeOf(conclusion.decision_scope)}`
    : null;
  // Only restricted modules to review is a ring; any warning or failure among
  // them is the warning it always was.
  const worst = weak.every((handoff) => handoffSeverity(handoff) === "RESTRICTED")
    ? "RESTRICTED"
    : "WARNING";
  const severity: Verdict["severity"] = blocked
    ? "CRITICAL"
    : weak.length
      ? worst
      : pending.length
        ? "RUNNING"
        : conclusion
          ? "SUCCESS"
          : "IDLE";
  // The modules are the section's views, in route order, each with its state
  // as shape and hue; the section opens on its conclusion.
  const tabs: Tab[] = handoffs.map((handoff) => ({
    id: handoff.route_node_id,
    label: handoff.module_id,
    // A module the catalog names only by its id reads as its id once, not twice.
    cp: handoff.module_name === handoff.module_id ? null : handoff.module_name,
    severity: handoffSeverity(handoff),
    note:
      handoff.validation_warnings[0] ??
      (handoff.limitation_flags[0] ? sentence(handoff.limitation_flags[0]) : null),
    opens: handoff === conclusion,
  }));
  return {
    tabs,
    ribbon: { ...QUIET, execution: status, approval: conclusion?.committee_status ?? null },
    brief: {
      change: `${plural(handoffs.length, "module")} accepted, ${pending.length} pending.`,
      impact:
        pending.length && conclusion ? `Latest accepted ${conclusion.module_id}: ${ready}.` : ready,
      action: weak.length
        ? `Review ${weak.map((handoff) => handoff.module_id).join(", ")} before committee.`
        : pending.length
          ? `Waiting on ${pending[0]!.module_name}.`
          : conclusion
            ? "Open Report to save a revision."
            : null,
      evidence: citations.length
        ? `${plural(citations.length, "citation")} across ${plural(documents, "document")}${withdrawn ? `, ${withdrawn} withdrawn` : ""}.`
        : null,
      headline: `${handoffs.length}/${handoffs.length + pending.length}`,
      headline_label: "modules accepted",
    },
    verdict: {
      severity,
      conclusion: conclusion
        ? pending.length
          ? `${plural(handoffs.length, "module")} accepted · ${plural(pending.length, "module")} pending`
          : conclusion.screening_only
            ? "Screening only · not committee clearance"
            : weak.length
              ? `${ready ?? ""}, with ${plural(weak.length, "module")} to review`
              : (ready ?? "")
        : "Nothing accepted yet",
      blocked_on: blocked?.module_id ?? null,
    },
  };
}
```

### SectionTabs

Winner: Incumbent holds, frontend/src/chrome/SectionTabs.tsx:10–106; no tournament replacement.

Justification:

- The speed candidate skips selected lookup on sparse lists, saving at most eight comparisons while adding another conditional to the render.
- The memory candidate has no allocation to remove from the severity fallback; a label dictionary allocates or introduces a separate type contract.
- A readability helper/switch separates three local labels from their only caller. The current fallback is short, handles blank notes and leaves the native controls untouched.

Bracket: speed over memory (the only measurable work reduction); speed over readability (no new helper); incumbent over speed (simpler control flow and no demonstrated latency benefit).

Final code:

```tsx
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
  // Past eight views (Analysis's thirteen modules) the names wrapped the list
  // to three rows above the view: each tab is its label, one row that stays
  // in reach under the header, and its name is said on hover and to a
  // screen reader.
  const dense = tabs.length > 8;
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
              {tab.label}
              {tab.cp ? ` · ${tab.cp}` : ""}
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
              title={dense && tab.cp ? `${tab.label} · ${tab.cp}` : undefined}
              // A hairline edge on the active pill: its muted fill alone all but
              // vanished against the dark page (brief 6.12).
              className="h-8 flex-none px-2.5 after:hidden data-active:border-border! data-active:bg-muted! data-active:shadow-none"
            >
              {tab.severity ? <SeverityMark severity={tab.severity} decorative /> : null}
              <span className="font-mono text-[13px]">{tab.label}</span>
              {tab.cp ? (
                <span className={dense ? "sr-only" : "font-normal text-muted-foreground"}>
                  {dense ? `, ${tab.cp}` : tab.cp}
                </span>
              ) : null}
              {tab.severity ? (
                <span className="sr-only">, {tab.severity.toLowerCase()}</span>
              ) : null}
            </TabsTrigger>
          ))}
        </TabsList>
      </Tabs>
      {dense && selected ? (
        <p className="px-2 pt-1 text-sm text-foreground" data-selected-view aria-live="polite">
          {selected.cp ?? selected.label}
          {meaning ? ` · ${meaning}` : null}
        </p>
      ) : null}
    </div>
  );
}
```

Verification: npx vitest run --mode demo tests/unit/compose.test.tsx tests/unit/chrome.test.tsx — 38/38 passed after the blank-note fix. npm run typecheck — exit 0; every current caller compiles. The concrete invariant check is Partial · 7 modules accepted · 3 modules pending with Latest accepted CP-5: Committee Ready · full scope., while CP-CF remains excluded from reasoning conclusion selection. npx playwright test tests/workbench/layout.spec.ts tests/workbench/navigation.spec.ts -g 'Analysis keeps|served Directory|fixture HTTP' — 9/9 passed in Chromium, Firefox and WebKit. The orchestrator reread the diff; no rewrite was applied. Scratch copies were retained at /var/folders/81/bwblpst93lb6wb3lwrk8k6800000gn/T/caos-followup-review-38c_cc3_.

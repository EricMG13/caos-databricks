// The section's own views. Never navigation between sections. Arrow keys move
// between them and select as they go. The module index is vertical on wide
// desks; a native select keeps narrower windows and zoom reflow compact.
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
  // Past eight views, keep the selected name and review reason above the index.
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
      <label className="block min-[1200px]:hidden">
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
      {dense && selected && (
        <p className="px-2 pt-1 text-sm text-foreground" data-selected-view aria-live="polite">
          {selected.cp ?? selected.label}
          {meaning ? ` · ${meaning}` : null}
        </p>
      )}
      <Tabs
        value={active}
        orientation="vertical"
        onValueChange={(value) => onSelect(String(value))}
        className="max-[1200px]:hidden"
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
    </div>
  );
}

/** The region a tab controls, named so the tab's `aria-controls` reaches it
    and labelled by that tab (finding FE-11). A section with no tabs has no
    panel: its region is the landmark it already sits in. */
export function SectionPanel({ tab, children }: { tab: string | null; children: ReactNode }) {
  if (tab === null) return <>{children}</>;
  return (
    <div role="tabpanel" id={`tabpanel-${tab}`} aria-labelledby={`tab-${tab}`}>
      {children}
    </div>
  );
}

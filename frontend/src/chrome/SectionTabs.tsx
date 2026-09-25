// The section's own views. Never navigation between sections. Arrow keys move
// between them and select as they go; on a phone they are a native select,
// since a dozen wrapped tabs were taller than the screen.
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
  // Past eight views (Analysis's thirteen modules) the names wrapped the list
  // to three rows above the view: each tab is its label, one row that stays
  // in reach under the header, and its name is said on hover and to a
  // screen reader.
  const dense = tabs.length > 8;
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
              className="h-8 flex-none px-2.5 after:hidden data-active:bg-muted! data-active:shadow-none"
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

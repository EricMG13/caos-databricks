// Band 3: the section's own views. Never navigation between sections.
import type { KeyboardEvent, ReactNode } from "react";
import { SeverityMark } from "./SeverityMark";
import type { Tab } from "@/wire";

// Roving tabindex: one tab stop, arrows move between the views.
function moveFocus(event: KeyboardEvent<HTMLButtonElement>, tabs: Tab[], active: string | null) {
  const index = Math.max(
    0,
    tabs.findIndex((tab) => tab.id === active),
  );
  const step = { ArrowRight: 1, ArrowLeft: -1, Home: -index, End: tabs.length - 1 - index }[
    event.key
  ];
  if (step === undefined || tabs.length === 0) return null;
  event.preventDefault();
  return tabs[(index + step + tabs.length) % tabs.length] ?? null;
}

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
  return (
    <section className="tabs" aria-label={`${label} views`}>
      {/* Focusable, never a tab stop: it is where focus lands after a
          navigation, a Reload, or a drawer whose opener has gone (FE-4). */}
      <h1 className="tl" tabIndex={-1}>
        {label}
      </h1>
      {/* A tab list of no tabs is a widget with nothing in it, announced on
          every page for nothing: a v1 document declares none (FE-11). */}
      {tabs.length === 0 ? null : (
        <label className="tabpick fld">
          <span className="sr-only">{label} view</span>
          <select
            value={active ?? ""}
            onChange={(event) => onSelect(event.target.value)}
            data-tab-select
          >
            {tabs.map((tab) => (
              <option key={tab.id} value={tab.id}>
                {tab.label}
                {tab.cp ? ` · ${tab.cp}` : ""}
                {tab.severity && tab.severity !== "SUCCESS"
                  ? ` · ${tab.severity.toLowerCase()}`
                  : ""}
              </option>
            ))}
          </select>
        </label>
      )}
      {tabs.length === 0 ? null : (
        <div role="tablist" aria-label={`${label} views`}>
          {tabs.map((tab) => {
            const on = tab.id === active;
            return (
              <button
                key={tab.id}
                type="button"
                role="tab"
                id={`tab-${tab.id}`}
                aria-controls={`tabpanel-${tab.id}`}
                aria-selected={on}
                tabIndex={on ? 0 : -1}
                className={`tab${on ? " on" : ""}`}
                onClick={() => onSelect(tab.id)}
                onKeyDown={(event) => {
                  const next = moveFocus(event, tabs, active);
                  if (next) {
                    onSelect(next.id);
                    document.getElementById(`tab-${next.id}`)?.focus();
                  }
                }}
              >
                {tab.severity ? <SeverityMark severity={tab.severity} decorative /> : null}
                <span className="lb">{tab.label}</span>
                {tab.cp ? <span className="cp">{tab.cp}</span> : null}
                {tab.severity ? (
                  <span className="sr-only">, {tab.severity.toLowerCase()}</span>
                ) : null}
              </button>
            );
          })}
        </div>
      )}
    </section>
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

// Band 1: what am I looking at, and is it trustworthy? Brand, context chips,
// then execution, persistence and approval state, then at most three actions
// of which exactly one is primary (IA_SPEC.md 3).
import { RefusedControl } from "@/controls/RefusedControl";
import type { Ribbon as RibbonWire, Subject } from "@/wire";

/** Execution, persistence and approval: each drawn only when the document
    says something about it. */
const STATE_CELLS = [
  { key: "execution", label: "exec" },
  { key: "persistence", label: "saved" },
  { key: "approval", label: "approval" },
] as const;

const TONE: Record<string, string> = {
  ok: "ok",
  warn: "warn",
  crit: "crit",
  acc: "acc",
  neutral: "",
};

export function Ribbon({
  ribbon,
  subject,
  tabs,
  onTab,
}: {
  ribbon: RibbonWire;
  subject: Subject | null;
  /** The section's own tabs. An action naming any other tab opens nothing, so it
      stays refused, for that reason, rather than becoming a live control that
      does nothing. */
  tabs?: readonly string[];
  /** Opens a tab of this section: the one kind of action the workspace performs itself. */
  onTab?: (tab: string) => void;
}) {
  const actions = ribbon.actions.slice(0, 3);
  return (
    <header className="ribbon" aria-label="Ribbon">
      <div className="brand">
        <span className="mark" aria-hidden="true">
          C
        </span>
        <span className="wordmark">CAOS</span>
      </div>
      {/* The issuer is what a reader recognises; the case id stays reachable. */}
      {subject ? (
        <span className="rb acc subject" title={subject.case_id} data-case={subject.case_id}>
          {subject.issuer}
        </span>
      ) : null}
      {ribbon.chips.map((chip, index) => (
        <span key={index} className={`rb ${TONE[chip.tone] ?? ""}`}>
          {chip.label}
        </span>
      ))}
      <div className="state">
        {STATE_CELLS.map(({ key, label }) =>
          ribbon[key] === null ? null : (
            <span key={key} className="rb ghost" data-state-cell={key}>
              <span className="lbl">{label}</span>
              {ribbon[key]}
            </span>
          ),
        )}
        {actions.map((action, index) => {
          const tab = action.tab !== undefined && tabs?.includes(action.tab) ? action.tab : null;
          // A tab the section does not have is the reason, not a missing route.
          const refusal =
            action.refusal ??
            (action.tab !== undefined && tab === null
              ? { code: "VIEW_UNPLACED", clears: `this section has a ${action.tab} tab` }
              : null);
          return (
            <RefusedControl
              key={index}
              refusal={refusal}
              onClick={tab !== null && onTab ? () => onTab(tab) : undefined}
              reasonDisplay="hidden"
              className={`rb ${action.primary ? "solid" : ""}`}
              data-primary={action.primary || undefined}
            >
              {action.label}
            </RefusedControl>
          );
        })}
      </div>
    </header>
  );
}

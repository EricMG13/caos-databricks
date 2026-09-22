import type { ReactNode } from "react";
import { SeverityMark } from "@/chrome/SeverityMark";
import type { Severity } from "@/wire";

/** The seven states of IA_SPEC.md 6. `ready` is not a state of this component:
    a ready region renders its children with no marker. */
export type SurfaceStateKind =
  "loading" | "observed-empty" | "error" | "unavailable" | "stale" | "offline" | "partial";

const PRESENTATION: Record<SurfaceStateKind, { label: string; severity: Severity; tone: string }> =
  {
    loading: { label: "Loading", severity: "RUNNING", tone: "run" },
    "observed-empty": { label: "No material change", severity: "IDLE", tone: "" },
    unavailable: { label: "Unavailable", severity: "WARNING", tone: "warn" },
    stale: { label: "Stale", severity: "WARNING", tone: "warn" },
    partial: { label: "Partial", severity: "WARNING", tone: "warn" },
    offline: { label: "Offline", severity: "CRITICAL", tone: "crit" },
    error: { label: "Refused", severity: "CRITICAL", tone: "crit" },
  };

type SurfaceStateProps = {
  kind: SurfaceStateKind;
  title?: string;
  detail?: ReactNode;
  supporting?: ReactNode;
  headingLevel?: 2 | 3 | 4;
  className?: string;
};

const HEADINGS = { 2: "h2", 3: "h3", 4: "h4" } as const;
const LIVE_STATES = new Set<SurfaceStateKind>(["loading"]);
const ALERT_STATES = new Set<SurfaceStateKind>(["error", "offline"]);

function surfaceSemantics(kind: SurfaceStateKind) {
  const live = LIVE_STATES.has(kind);
  return { live, role: live ? "status" : ALERT_STATES.has(kind) ? "alert" : "status" } as const;
}

/**
 * Presentation-only contract for non-ready surface states. Callers retain
 * authority over the state kind, copy, and recovery actions; this component
 * never infers live, ratified, or actionable status.
 */
export function SurfaceState({
  kind,
  title,
  detail,
  supporting,
  headingLevel = 2,
  className = "",
}: SurfaceStateProps) {
  const semantics = surfaceSemantics(kind);
  const presentation = PRESENTATION[kind];
  const Heading = HEADINGS[headingLevel];
  return (
    <section
      role={semantics.role}
      aria-live={semantics.live ? "polite" : undefined}
      className={`rs ${presentation.tone}${className ? ` ${className}` : ""}`}
      data-surface-state={kind}
    >
      <div className="st">
        <SeverityMark severity={presentation.severity} pulse={semantics.live} />
        <span>{presentation.label}</span>
      </div>
      {title ? <Heading>{title}</Heading> : null}
      {detail ? <p>{detail}</p> : null}
      {supporting ? <div className="mt-2">{supporting}</div> : null}
    </section>
  );
}

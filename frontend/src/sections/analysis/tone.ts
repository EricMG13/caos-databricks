// Node states, handoffs and confidence tiers as shape-and-hue classes
// (DESIGN.md), and which handoff concludes the route. A module's name is the
// bundle catalog's own, served on the wire as `module_name` (N61).
import { toneOf } from "@/chrome/SeverityMark";
import type { NodeState, Severity } from "@/wire";
import type { HandoffView } from "@/wire/v1";

/** The bundle's four node states, each read through a severity shape. */
export const NODE_SEVERITY: Record<NodeState, Severity> = {
  COMPLETE: "SUCCESS",
  RUNNABLE: "RUNNING",
  RESTRICTED: "RESTRICTED",
  BLOCKED: "CRITICAL",
};

export function nodeTone(state: NodeState): string {
  return toneOf(NODE_SEVERITY[state]);
}

/** A confidence is a number and a tier; the hue follows the tier. */
export function confidenceTier(pct: number): { tone: string; word: string } {
  if (pct >= 85) return { tone: "ok", word: "HIGH" };
  if (pct >= 60) return { tone: "warn", word: "MEDIUM" };
  return { tone: "crit", word: "LOW" };
}

/** Modules that calculate rather than reason: the model extension's. */
const CALCULATORS = new Set(["CP-CF", "CP-MODEL"]);

/** The route's conclusion: its last module that reasons. The calculators run
    after it and conclude nothing; a route of calculators alone ends on one. */
export function conclusionOf(handoffs: readonly HandoffView[]): HandoffView | null {
  const reasoning = handoffs.filter(
    (handoff) => handoff.host_calculation === "NONE" && !CALCULATORS.has(handoff.module_id),
  );
  return reasoning.at(-1) ?? handoffs.at(-1) ?? null;
}

/** What a QA reading needs: a handoff, or CP-CF's accepted forecast. */
export type QaRecord = Pick<
  HandoffView,
  "qa_status" | "limitation_flags" | "validation_warnings"
> & {
  screening_only?: boolean;
};

/** A handoff's state as a severity, in the bundle's own terms (D71). A QA
    status that did not pass is critical. A validation warning is a warning:
    `validation_warnings` is the bundle's field for it. A module that ran
    carrying a limitation forward -- QA `Restricted`, the normalised word for
    every "with limitations" (CANON_SHARED D1), or a stated limitation flag, or
    a screening-only scope that can never be Committee Ready -- is RESTRICTED's
    ring, never a warning. A QA word the bundle does not declare is a warning. */
export function handoffSeverity(record: QaRecord): Severity {
  const qa = record.qa_status.toUpperCase();
  if (qa === "FAILED" || qa === "BLOCKED") return "CRITICAL";
  if (record.validation_warnings.length > 0 || (qa !== "PASSED" && qa !== "RESTRICTED")) {
    return "WARNING";
  }
  if (qa === "RESTRICTED" || record.limitation_flags.length > 0 || record.screening_only) {
    return "RESTRICTED";
  }
  return "SUCCESS";
}

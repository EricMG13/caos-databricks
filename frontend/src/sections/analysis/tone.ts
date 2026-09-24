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

/** A handoff's state as a severity: passed and clean is success; restricted,
    screening only or carrying flags or warnings is a warning; a QA status
    that did not pass is critical. */
export function handoffSeverity(handoff: HandoffView): Severity {
  const qa = handoff.qa_status.toUpperCase();
  if (qa === "FAILED" || qa === "BLOCKED") return "CRITICAL";
  if (
    qa !== "PASSED" ||
    handoff.screening_only ||
    handoff.limitation_flags.length > 0 ||
    handoff.validation_warnings.length > 0
  ) {
    return "WARNING";
  }
  return "SUCCESS";
}

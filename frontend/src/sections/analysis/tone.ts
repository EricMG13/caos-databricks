// Node states and confidence tiers as shape-and-hue classes (DESIGN.md).
import { toneOf } from "@/chrome/SeverityMark";
import type { NodeState, Severity } from "@/wire";

/** The bundle's four node states, each read through a severity shape. */
export const NODE_SEVERITY: Record<NodeState, Severity> = {
  COMPLETE: "SUCCESS",
  RUNNABLE: "RUNNING",
  RESTRICTED: "WARNING",
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

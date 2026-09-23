// What a module is called and how its accepted handoff reads at a glance. The
// names mirror the bundle's stage slugs (`icm/stages/<slug>/`); an id the map
// does not know is shown as itself.
// ponytail: a display map, not methodology. The bundle's own catalog could
// serve these names on the wire if a module is ever renamed upstream.
import type { Severity } from "@/wire";
import type { HandoffView } from "@/wire/v1";

const NAMES: Record<string, string> = {
  "CP-0": "Source readiness",
  "CP-PARSE": "Data preparation",
  "CP-1": "Canonical data foundation",
  "CP-1A": "Business and transaction facts",
  "CP-1B": "Earnings delta",
  "CP-1C": "Peer benchmark",
  "CP-1D": "Earnings quality",
  "CP-2": "Fundamental credit",
  "CP-2A": "Downside pathways",
  "CP-2B": "Events and catalysts",
  "CP-2C": "Governance and sponsor",
  "CP-2D": "Liquidity and cash-flow bridge",
  "CP-2E": "Macro, FX and hedging",
  "CP-2F": "ESG credit risk",
  "CP-2G": "Forward credit model",
  "CP-2H": "Rating migration triggers",
  "CP-3": "Relative value",
  "CP-3C": "Refinancing and LME risk",
  "CP-3D": "Market-implied risk",
  "CP-4": "Legal and covenants",
  "CP-4C": "Restructuring fulcrum",
  "CP-5": "Evidence trace",
  "CP-6": "IC debate",
  "CP-8": "Decision ledger",
  "CP-CF": "Cash-flow forecast",
  "CP-DR": "Deep research",
  "CP-MEMO": "Credit research report",
  "CP-MODEL": "Credit snapshot model",
};

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

export function moduleName(moduleId: string): string {
  return NAMES[moduleId] ?? moduleId;
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

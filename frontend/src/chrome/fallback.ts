// The header is on every section (IA_SPEC.md 3), including the states in which
// there is no document to fill it. This chrome carries the state and invents
// nothing: no subject, no actions, no role, and no run, revision or approval.
import { OFFLINE_WORDING, UNAVAILABLE_WORDING, type RegionStatus } from "@/app/transport";
import { regionSentence } from "@/states/RegionState";
import type { Brief, Ribbon, Severity, Tone, Verdict } from "@/wire";

export interface FallbackChrome {
  ribbon: Ribbon;
  brief: Brief;
  verdict: Verdict;
}

function describe(status: RegionStatus): {
  label: string;
  sentence: string;
  clears: string;
  severity: Severity;
  tone: Tone;
} {
  switch (status.kind) {
    case "offline":
      return {
        label: "Offline",
        sentence: OFFLINE_WORDING,
        clears: "the server answers",
        severity: "CRITICAL",
        tone: "crit",
      };
    case "unavailable":
      return {
        label: "Unavailable",
        sentence: UNAVAILABLE_WORDING,
        clears: "the case exists and you are a member of it",
        severity: "WARNING",
        tone: "warn",
      };
    case "choose":
      return status.need === "run"
        ? {
            label: "Choose a run",
            sentence: "Choose a run to open this section.",
            clears: "a run is chosen in Run",
            severity: "IDLE",
            tone: "neutral",
          }
        : {
            label: "Choose a revision",
            sentence: "Choose a frozen revision to open Committee.",
            clears: "a frozen revision is chosen in Report",
            severity: "IDLE",
            tone: "neutral",
          };
    case "error":
      return {
        label: status.refusal.code,
        sentence: regionSentence(status.refusal),
        clears: status.refusal.clears,
        severity: "CRITICAL",
        tone: "crit",
      };
    default:
      return {
        label: "Loading",
        sentence: "Loading the section document.",
        clears: "the document lands",
        severity: "RUNNING",
        tone: "acc",
      };
  }
}

/** One closing mark, whether or not the refusal brought its own -- and its own
    kept when it is not a full stop. Marks compared by `endsWith`, not a regex
    of the /\.+$/ shape SonarQube flags (typescript:S8786). */
function sentenceOf(clause: string): string {
  const trimmed = clause.trim();
  return [".", "!", "?"].some((mark) => trimmed.endsWith(mark)) ? trimmed : `${trimmed}.`;
}

export function fallbackChrome(status: RegionStatus): FallbackChrome {
  const state = describe(status);
  // One sentence per state, in one place: the verdict strip for an observed
  // 404 or a refusal, the page-level alert for offline (IA_SPEC.md 6). The
  // brief's four cells say what was observed, which is nothing.
  const conclusion = status.kind === "offline" ? "Offline" : state.sentence;
  return {
    ribbon: {
      chips: [{ label: state.label, tone: state.tone }],
      execution: null,
      persistence: null,
      approval: null,
      actions: [],
    },
    brief: {
      change: "Nothing observed.",
      impact: "No conclusion is supported.",
      action: `Clears when ${sentenceOf(state.clears)}`,
      evidence: "Nothing observed.",
      headline: "—",
    },
    verdict: { severity: state.severity, conclusion, blocked_on: null },
  };
}

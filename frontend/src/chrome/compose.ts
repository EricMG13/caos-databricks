// The four bands and the rail for a v1 section document (brief 4.1, decision 5).
// The server sends authority facts only -- the subject and the served role --
// and the client composes the rest from section constants and body facts. The
// served role is displayed and enables nothing: no field here reads it but
// `served_role` itself, and 4.1 offers no action.
import {
  ENABLED_SECTIONS,
  SECTION_LABELS,
  isEnabledSection,
  type EnabledSection,
} from "@/app/sections";
import { SECTIONS, type Chrome, type RailEntry } from "@/wire";
import type { SectionDocument } from "@/wire/v1";

const PURPOSE: Record<EnabledSection, string> = {
  directory: "The cases you hold live standing on.",
  upload: "The admitted sources and their set versions.",
  run: "The pinned route, its gates and its attempts.",
  analysis: "Accepted handoffs, their citations and the nodes still pending.",
  book: "The credits you hold standing on, on their accepted projections.",
  model: "The accepted CP-CF projection, exactly as the server supplied it.",
  report: "The exact saved revision, exactly as the server supplied it.",
  committee: "The frozen or filed saved revision, exactly as the server supplied it.",
};

/** Every enabled section is served, with no count: the v1 wire carries no
    per-section tally, and a rail entry is what keeps a served section from
    reading as `off`. */
const SERVED: RailEntry[] = ENABLED_SECTIONS.map((section) => ({
  section,
  count: null,
  state: "Served",
}));

/** Rail entries with every disabled section marked unavailable. */
export function markDisabled(entries: readonly RailEntry[] | null): RailEntry[] {
  const kept = (entries ?? []).filter((entry) => isEnabledSection(entry.section));
  const disabled = SECTIONS.filter((section) => !isEnabledSection(section)).map(
    (section): RailEntry => ({ section, count: null, state: "Unavailable" }),
  );
  return [...kept, ...disabled];
}

export function composeChrome(section: EnabledSection, document: SectionDocument): Chrome {
  const { subject, served_role: role } = document.chrome;
  const partial = document.status === "partial";
  const observed = document.observed_empty ? "Observed empty" : "Observed";
  return {
    subject: subject ? { case_id: subject.case_id, issuer: subject.title } : null,
    ribbon: {
      chips: [{ label: partial ? "PARTIAL" : "COMPLETE", tone: partial ? "warn" : "ok" }],
      execution: "—",
      persistence: "—",
      approval: "—",
      actions: [],
    },
    brief: {
      change: `${observed} at ${document.observed_at}.`,
      impact: PURPOSE[section],
      action: "No action is offered on this surface yet.",
      evidence: partial ? `Partial: ${document.notes.join(", ")}.` : "Complete as observed.",
      headline: SECTION_LABELS[section],
    },
    tabs: [],
    verdict: {
      severity: partial ? "WARNING" : "IDLE",
      conclusion: partial ? "Partial document." : `${observed}.`,
      blocked_on: null,
    },
    rail: markDisabled(SERVED),
    rail_local: null,
    served_role: { role: role.global_role, standing: role.standing },
  };
}

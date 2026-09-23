// The four bands and the rail for a v1 section document (brief 4.1, decision 5).
// The server sends authority facts only -- the subject and the served role --
// and the client composes the rest from the document's own body facts. A band
// cell with nothing the document supports is null and is not drawn: before,
// every section said "—", "No action is offered on this surface yet." and its
// own name as the headline figure (critique P1). The served role is displayed
// and enables nothing.
import {
  ENABLED_SECTIONS,
  committeeRevisionOf,
  isEnabledSection,
  type EnabledSection,
} from "@/app/sections";
import { stamp } from "@/ds/format";
import { conclusionOf, handoffSeverity, moduleName } from "@/sections/analysis/modules";
import {
  SECTIONS,
  type Brief,
  type Chrome,
  type RailEntry,
  type Ribbon,
  type Tab,
  type Verdict,
} from "@/wire";
import type {
  AnalysisDocument,
  BookDocument,
  CommitteeDocument,
  DirectoryDocument,
  ModelDocument,
  ReportDocument,
  RunSectionDocument,
  SectionDocument,
  UploadDocument,
} from "@/wire/v1";

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

/** `FULL_COMMITTEE` reads "full committee". */
export function words(code: string): string {
  return code.replaceAll("_", " ").toLowerCase();
}

/** `FULL_COMMITTEE` reads "Full committee": a code shown as a label. */
export function sentence(code: string): string {
  const said = words(code);
  return said.charAt(0).toUpperCase() + said.slice(1);
}

const plural = (count: number, one: string, many = `${one}s`) =>
  `${count} ${count === 1 ? one : many}`;
/** The noun a count takes, without the count: a headline figure's label. */
const noun = (count: number, one: string, many = `${one}s`) => (count === 1 ? one : many);

/** What a section's own body says, before the partial and empty overlays. */
interface Facts {
  ribbon: Omit<Ribbon, "actions">;
  brief: Brief;
  verdict: Verdict;
  /** The section's own views: Analysis's modules. */
  tabs?: Tab[];
}

const QUIET: Omit<Ribbon, "actions"> = {
  chips: [],
  execution: null,
  persistence: null,
  approval: null,
};
const verdict = (severity: Verdict["severity"], conclusion: string): Verdict => ({
  severity,
  conclusion,
  blocked_on: null,
});

function directory(document: DirectoryDocument): Facts {
  const cases = document.body.cases;
  const running = cases.filter((row) => row.latest_run?.status === "RUNNING").length;
  return {
    ribbon: QUIET,
    brief: {
      change: cases.length
        ? `${plural(cases.length, "case")} you hold standing on.`
        : "You hold standing on no case yet.",
      impact: null,
      action: cases.length
        ? "Open a case to read its analysis."
        : "Create a case, or ask an administrator for standing on one.",
      evidence: running ? `${plural(running, "run")} in progress.` : null,
      headline: String(cases.length),
      headline_label: noun(cases.length, "case"),
    },
    verdict: verdict("IDLE", cases.length ? `${plural(cases.length, "case")}.` : "No cases yet."),
  };
}

function upload(document: UploadDocument): Facts {
  const { sources, set_versions: versions } = document.body;
  const withdrawn = sources.filter((source) => source.withdrawn_at !== null).length;
  const admitted = sources.length - withdrawn;
  const pinned = versions.at(-1) ?? null;
  return {
    ribbon: {
      ...QUIET,
      chips: withdrawn ? [{ label: `${withdrawn} withdrawn`, tone: "warn" }] : [],
    },
    brief: {
      change: pinned
        ? `Set version ${pinned.version} pins ${plural(pinned.member_count, "source")}.`
        : "No source set is pinned yet.",
      impact: null,
      action: admitted ? null : "Admit the case's source documents.",
      evidence: `${admitted} admitted · ${withdrawn} withdrawn.`,
      headline: String(admitted),
      headline_label: `${noun(admitted, "source")} admitted`,
    },
    verdict: withdrawn
      ? verdict(
          "WARNING",
          `${plural(withdrawn, "withdrawn source")} stay cited where they were used.`,
        )
      : verdict("IDLE", `${plural(admitted, "source")} admitted.`),
  };
}

/** What a run's status says in words; the severity beside it already says
    its tone, so the conclusion never repeats the status word. */
const RUN_WORDS = {
  RUNNING: "In progress",
  COMPLETE: "Complete",
  FAILED: "Failed",
  BLOCKED: "Blocked",
  CANCELLED: "Cancelled",
} as const;

export const RUN_SEVERITY = {
  RUNNING: "RUNNING",
  COMPLETE: "SUCCESS",
  FAILED: "CRITICAL",
  BLOCKED: "WARNING",
  CANCELLED: "IDLE",
} as const;

function run(document: RunSectionDocument): Facts {
  const view = document.body.run;
  if (!view) {
    return {
      ribbon: QUIET,
      brief: {
        change: "This case has no run yet.",
        impact: null,
        action: "Create a run to execute the pinned route.",
        evidence: null,
        headline: null,
      },
      verdict: verdict("IDLE", "No run yet."),
    };
  }
  const done = view.nodes.filter((node) => node.state === "COMPLETE").length;
  const open = view.gates.filter((gate) => gate.state === "OPEN");
  const restricted = view.nodes.filter((node) => node.state === "RESTRICTED").length;
  // A human gate open, else a module held at its QA gate: the thing the run
  // waits on, which the chrome never named (critique).
  const gated = view.nodes
    .filter((node) => node.awaiting_gate && node.state !== "COMPLETE")
    .map((node) => node.module_id);
  const waiting = open.length
    ? `waiting on the ${words(open[0]!.gate)} gate`
    : gated.length
      ? `${gated.join(", ")} at ${gated.length === 1 ? "its" : "their"} gate`
      : null;
  return {
    ribbon: {
      ...QUIET,
      execution: view.status,
      approval: open.length ? `${plural(open.length, "gate")} open` : "gates released",
    },
    brief: {
      change: `${done} of ${plural(view.nodes.length, "module")} complete.`,
      impact: view.blocked_by
        ? `Blocked at ${view.blocked_by.module_id}.`
        : restricted
          ? `${plural(restricted, "module")} restricted.`
          : null,
      action: open.length ? `Review the ${words(open[0]!.gate)} gate.` : null,
      evidence: null,
      headline: `${done}/${view.nodes.length}`,
      headline_label: "modules complete",
    },
    verdict: {
      severity: open.length && view.status === "RUNNING" ? "WARNING" : RUN_SEVERITY[view.status],
      conclusion: [RUN_WORDS[view.status], waiting].filter(Boolean).join(" · "),
      blocked_on: view.blocked_by?.module_id ?? null,
    },
  };
}

function analysis(document: AnalysisDocument): Facts {
  const { handoffs, pending, displayed_run_status: status, blocked_by: blocked } = document.body;
  const conclusion = conclusionOf(handoffs);
  const weak = handoffs
    .filter((handoff) => handoffSeverity(handoff) !== "SUCCESS")
    .map((handoff) => handoff.module_id);
  const citations = handoffs.flatMap((handoff) => handoff.source_facts);
  const documents = new Set(citations.map((fact) => fact.document_sha256)).size;
  const withdrawn = citations.filter((fact) => fact.withdrawn_at !== null).length;
  const ready = conclusion
    ? `${conclusion.committee_status} · ${words(conclusion.decision_scope)}`
    : null;
  const severity: Verdict["severity"] = blocked
    ? "CRITICAL"
    : weak.length
      ? "WARNING"
      : pending.length
        ? "RUNNING"
        : conclusion
          ? "SUCCESS"
          : "IDLE";
  // The modules are the section's views, in route order, each with its state
  // as shape and hue; the section opens on its conclusion.
  const tabs: Tab[] = handoffs.map((handoff) => ({
    id: handoff.route_node_id,
    label: handoff.module_id,
    // A module the name map does not know reads as its id once, not twice.
    cp: moduleName(handoff.module_id) === handoff.module_id ? null : moduleName(handoff.module_id),
    severity: handoffSeverity(handoff),
    opens: handoff === conclusion,
  }));
  return {
    tabs,
    ribbon: { ...QUIET, execution: status, approval: conclusion?.committee_status ?? null },
    brief: {
      change: `${plural(handoffs.length, "module")} accepted, ${pending.length} pending.`,
      impact: ready,
      action: weak.length
        ? `Review ${weak.join(", ")} before committee.`
        : pending.length
          ? `Waiting on ${pending[0]!.module_id}.`
          : conclusion
            ? "Open Report to save a revision."
            : null,
      evidence: citations.length
        ? `${plural(citations.length, "citation")} across ${plural(documents, "document")}${withdrawn ? `, ${withdrawn} withdrawn` : ""}.`
        : null,
      headline: `${handoffs.length}/${handoffs.length + pending.length}`,
      headline_label: "modules accepted",
    },
    verdict: {
      severity,
      conclusion: conclusion
        ? conclusion.screening_only
          ? "Screening only: not committee clearance."
          : weak.length
            ? `${ready ?? ""}, with ${plural(weak.length, "module")} to review`
            : (ready ?? "")
        : "Nothing accepted yet.",
      blocked_on: blocked?.module_id ?? null,
    },
  };
}

function book(document: BookDocument): Facts {
  const rows = document.body.rows;
  const without = rows.filter((row) => row.unavailable_reason !== null).length;
  return {
    ribbon: QUIET,
    brief: {
      change: `${plural(rows.length, "credit")} on accepted projections.`,
      impact: null,
      action: null,
      evidence: without ? `${without} without an accepted forecast.` : null,
      headline: String(rows.length),
      headline_label: noun(rows.length, "credit"),
    },
    verdict: verdict("IDLE", `${plural(rows.length, "credit")}.`),
  };
}

function model(document: ModelDocument): Facts {
  const forecast = document.body.forecast;
  if (!forecast) {
    return {
      ribbon: QUIET,
      brief: {
        change: "This run has no accepted forecast.",
        impact: null,
        action: "Run a route that includes CP-CF.",
        evidence: null,
        headline: null,
      },
      verdict: verdict("IDLE", "No accepted forecast."),
    };
  }
  const flags = forecast.limitation_flags.length;
  return {
    ribbon: { ...QUIET, approval: forecast.qa_status },
    brief: {
      change: `${plural(forecast.periods.length, "period")} in ${forecast.currency} ${forecast.scale}.`,
      impact: forecast.perimeter,
      action: null,
      evidence: flags ? `${plural(flags, "limitation")} stated.` : null,
      headline: String(forecast.periods.length),
      headline_label: noun(forecast.periods.length, "period"),
    },
    verdict: verdict(flags ? "WARNING" : "SUCCESS", "Accepted CP-CF projection."),
  };
}

const NEXT_FILING = {
  saved: "Sign, then freeze, to send it to committee.",
  frozen: "Open it in Committee.",
  filed: null,
} as const;

function report(document: ReportDocument): Facts {
  const { revision_id: shown, revisions, artifacts } = document.body;
  const row = revisions.find((revision) => revision.revision_id === shown) ?? null;
  const state = row?.state ?? (shown ? "saved" : null);
  const ready = committeeRevisionOf(revisions, shown);
  return {
    ribbon: {
      ...QUIET,
      persistence: shown ? "saved" : "not saved",
      approval: state && state !== "saved" ? state : null,
    },
    brief: {
      change: row
        ? `Revision saved ${stamp(row.saved_at)}.`
        : shown
          ? "Revision saved."
          : "Nothing saved from this run yet.",
      impact: ready && ready !== shown ? "An earlier revision is frozen for committee." : null,
      action: state ? NEXT_FILING[state] : "Save a revision to start the filing chain.",
      evidence: `${plural(artifacts.length, "module artifact")}.`,
      headline: String(revisions.length),
      headline_label: noun(revisions.length, "revision"),
    },
    verdict:
      state === "filed"
        ? verdict("SUCCESS", "Filed.")
        : state === "frozen"
          ? verdict("RUNNING", "Frozen, awaiting committee.")
          : verdict("IDLE", state ? "Saved, not yet frozen." : "Not yet saved."),
  };
}

function committee(document: CommitteeDocument): Facts {
  const { state, signed_by: signers, receipt } = document.body;
  return {
    ribbon: { ...QUIET, persistence: "saved", approval: state },
    brief: {
      change: state === "filed" ? "Filed." : "Frozen for committee.",
      impact: `${plural(signers.length, "signature")}.`,
      action: state === "filed" ? null : "Filing follows, by an independent approver.",
      evidence: receipt ? "Filing receipt verified." : null,
      headline: String(signers.length),
      headline_label: noun(signers.length, "signature"),
    },
    verdict:
      state === "filed"
        ? verdict("SUCCESS", "Filed deliverable.")
        : verdict("RUNNING", "Frozen, awaiting filing."),
  };
}

// ponytail: one cast per branch. The parser registry has already checked each
// document against its own section, so the section names its shape.
function factsOf(section: EnabledSection, document: SectionDocument): Facts {
  switch (section) {
    case "directory":
      return directory(document as DirectoryDocument);
    case "upload":
      return upload(document as UploadDocument);
    case "run":
      return run(document as RunSectionDocument);
    case "analysis":
      return analysis(document as AnalysisDocument);
    case "book":
      return book(document as BookDocument);
    case "model":
      return model(document as ModelDocument);
    case "report":
      return report(document as ReportDocument);
    case "committee":
      return committee(document as CommitteeDocument);
  }
}

export function composeChrome(section: EnabledSection, document: SectionDocument): Chrome {
  const { subject, served_role: role } = document.chrome;
  const facts = factsOf(section, document);
  const partial = document.status === "partial";
  const notes = partial
    ? document.notes.length
      ? `Partial: ${document.notes.join(", ")}.`
      : "Some parts of this document could not be read."
    : null;
  return {
    subject: subject ? { case_id: subject.case_id, issuer: subject.title } : null,
    ribbon: {
      ...facts.ribbon,
      chips: partial
        ? [{ label: "Partial", tone: "warn" }, ...facts.ribbon.chips]
        : facts.ribbon.chips,
      actions: [],
    },
    brief: {
      ...facts.brief,
      change: `${facts.brief.change ?? ""} Observed ${stamp(document.observed_at)}.`.trim(),
      evidence: notes ?? facts.brief.evidence,
    },
    tabs: facts.tabs ?? [],
    verdict: partial
      ? {
          ...facts.verdict,
          severity: "WARNING",
          conclusion: `Partial · ${facts.verdict.conclusion}`,
        }
      : facts.verdict,
    rail: markDisabled(SERVED),
    rail_local: null,
    served_role: { role: role.global_role, standing: role.standing },
  };
}

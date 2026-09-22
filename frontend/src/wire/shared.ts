// The wire, client half. Every section document is `{chrome, body, observed_at}`
// (CLAUDE.md "Wire strictness": one document per section, never per widget).
// Names follow CONTEXT.md; the bundle's own words for node states and edge
// types are unchanged.

export const SECTIONS = [
  "directory",
  "upload",
  "analysis",
  "book",
  "run",
  "model",
  "report",
  "committee",
  "admin",
] as const;
export type Section = (typeof SECTIONS)[number];

export type Severity = "SUCCESS" | "RUNNING" | "WARNING" | "CRITICAL" | "IDLE";
export type NodeState = "COMPLETE" | "RUNNABLE" | "RESTRICTED" | "BLOCKED";
export type EdgeType = "REQUIRED" | "CONDITIONAL" | "QA_GATE" | "OPTIONAL" | "ADVISORY";
export type Standing = "READER" | "WRITER" | "APPROVER" | "ADMIN";
export type Tone = "ok" | "warn" | "crit" | "acc" | "neutral";

/** A rectangle on a page: x, y, width, height as fractions of the page box. */
export type BBox = [number, number, number, number];

/** Invariant 11: coordinate-anchored. The chip reads `D-04 p.68 ¶2`. */
export interface Citation {
  chip: string;
  document_sha256: string;
  source_label: string;
  page: number;
  bboxes: BBox[];
  matched_text: string;
  observed_at: string;
  /** The host's render of that page, or null when none is served. */
  render_url: string | null;
  /** When the cited source was withdrawn, if it has been (invariant 1: checked
      live). The citation stays so the conclusion is explicable; the chip says so. */
  withdrawn_at?: string | null;
}

/** A typed refusal and what would clear it. Never an exception. */
export interface Refusal {
  code: string;
  clears: string;
}

/** Every ready conclusion carries these five (DESIGN.md "Rules with teeth"). */
export interface ConclusionAuthority {
  observed_at: string;
  origin: string;
  method: string;
  approval: string;
  freshness: string;
}

export interface RibbonChip {
  label: string;
  tone: Tone;
}
export interface RibbonAction {
  label: string;
  primary: boolean;
  refusal: Refusal | null;
  /** A tab of this section the action opens. Such an action is performed in the
      workspace, so it is live unless the document refuses it. */
  tab?: string;
}
export interface Ribbon {
  chips: RibbonChip[];
  execution: string;
  persistence: string;
  approval: string;
  /** At most three; exactly one primary (IA_SPEC.md 3). */
  actions: RibbonAction[];
}
export interface Brief {
  change: string;
  impact: string;
  action: string;
  evidence: string;
  headline: string;
}
export interface Verdict {
  severity: Severity;
  conclusion: string;
  blocked_on: string | null;
}
export interface Tab {
  id: string;
  label: string;
  cp: string | null;
}
export interface RailEntry {
  section: Section;
  count: number | null;
  state: string;
}
export interface RailLocalItem {
  label: string;
  meta: string;
  on: boolean;
}
export interface RailLocal {
  title: string;
  items: RailLocalItem[];
}
export interface ServedRole {
  role: string;
  /** Null when the actor holds no standing on the case (the v1 directory). */
  standing: Standing | null;
}
export interface Subject {
  case_id: string;
  issuer: string;
}
export interface Chrome {
  subject: Subject | null;
  ribbon: Ribbon;
  brief: Brief;
  tabs: Tab[];
  verdict: Verdict;
  rail: RailEntry[];
  rail_local: RailLocal | null;
  served_role: ServedRole;
}

export interface SectionDocument<B> {
  chrome: Chrome;
  body: B;
  observed_at: string;
  observed_empty?: boolean;
  status?: "partial";
  notes?: string[];
}

/** The ten passport fields, IA_SPEC.md 4.4. Rendering is keyed on this list. */
export const PASSPORT_FIELDS = [
  "definition",
  "period",
  "scenario",
  "reporting_period",
  "computed_at",
  "snapshot",
  "method",
  "derivation",
  "citations",
  "supporting_research",
] as const;
export type PassportField = (typeof PASSPORT_FIELDS)[number];

export interface ResearchLink {
  title: string;
  module_id: string;
  state: string;
}
/** A projected figure names the driver that produced it and that driver's evidence. */
export interface Driver {
  name: string;
  value: string;
  citation: Citation;
}
export interface Deviation {
  amount: string;
  restatement: string;
}
export interface Passport {
  label: string;
  value: string;
  unit: string | null;
  definition: string;
  period: string;
  scenario: string;
  reporting_period: string;
  computed_at: string;
  snapshot: string;
  method: string;
  derivation: string;
  citations: Citation[];
  supporting_research: ResearchLink[];
  driver: Driver | null;
  deviation: Deviation | null;
}

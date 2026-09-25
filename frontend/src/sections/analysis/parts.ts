// A module's canonical Markdown, split into the places the page draws it
// (D60). Every module writes one skeleton (`vendor/deploy-v/CANON_SHARED.md`):
// front matter, then six H2 sections -- Audit Summary, Analysis, Evidence
// Trace, Source Registry, Gaps & Conflicts, QA Validation -- and inside
// Analysis a conclusion-first H3, the reader-facing sections, and
// `### Analytical appendix — complete canonical registers`. The page puts the
// opening first, the registers by what they are, and every audit section in
// one place in one order, the same in every module.
//
// Placement is display only. Every block is drawn somewhere, and "As written"
// keeps the exact text; no figure is read from any of it (D32).
import { tableTag, type Block, type MdTable } from "@/ds/markdown";

export interface Part {
  title: string;
  blocks: Block[];
}

/** A register: a table and what labels it. */
export interface Register {
  /** `T4C.4`, `cp1b.model_comparator_register`; `null` when unlabelled. */
  id: string | null;
  title: string;
  /** Prose written between the register's heading and its table. */
  notes: Block[];
  table: MdTable;
  shape: Shape;
}

export type Shape =
  | "sources"
  | "qa"
  | "gaps"
  | "conflicts"
  | "trace"
  | "readiness"
  | "tests"
  | "scores"
  | "bridge"
  | "series"
  | "comparison"
  | "peers"
  | "capital"
  | "market"
  | "timeline"
  | "debate"
  | "research"
  | "findings"
  | "triggers"
  | "profile"
  | "definitions"
  | "table";

export interface ModuleParts {
  /** The host-owned front matter as written. */
  front: string | null;
  /** The conclusion-first opening: its heading and what follows it. */
  lead: Part | null;
  /** The reader-facing sections after the opening. */
  reader: Part[];
  /** Every register, the appendix's and any other tagged table's. */
  registers: Register[];
  /** The audit sections, in the canonical order. */
  audit: Part[];
}

export const AUDIT_SECTIONS = [
  "Audit summary",
  "Evidence trace",
  "Source registry",
  "Gaps and conflicts",
  "QA validation",
] as const;

// The audit H2s as the canon names them and as deployed modules write them:
// a Copilot run heads its summary "Module Result" and its QA "QA &
// Governance", and titles a gaps register "Conflicts & gaps register".
const H2_AUDIT: [RegExp, (typeof AUDIT_SECTIONS)[number]][] = [
  [/^(audit summary|module result)\b/, "Audit summary"],
  [/^evidence trace\b/, "Evidence trace"],
  [/^source regist(ry|er)\b/, "Source registry"],
  [/^(gaps? (&|and) conflicts?|conflicts? (&|and) gaps?)\b/, "Gaps and conflicts"],
  [/^qa (validation|(&|and) governance)\b/, "QA validation"],
];
const auditOf = (title: string) => H2_AUDIT.find(([rule]) => rule.test(title.toLowerCase()))?.[1];

const APPENDIX = /^analytical appendix\b/i;
// `T4C.4`, `TL40.2`, `TDR.1`, and the one-letter series deployed modules
// write (`A1`, `B8`, `R10`).
// `[A-Z][0-9]+[A-Z]?[0-9A-Z]*` read as `[A-Z][0-9][0-9A-Z]*`, the same ids: two
// quantifiers over one run of digits cost a pass per split, seconds a heading.
const REGISTER_ID = /^((?:TDR|TL[0-9]|[A-Z][0-9])[0-9A-Z]*(?:\.[0-9A-Z]+)*)(?=$|[\s.:—–-])/;
// A line that is nothing but bold labels the table under it, as a heading
// would: `**T1 — CP-PARSE handoff / lineage validation**`, a parenthetical
// after it kept.
const BOLD_LABEL = /^\*\*([^*]+)\*\*\s*(\([^)]*\))?$/;
/** A short line naming a register id, directly above a table, labels it:
    `T4.1 — Peer Universe Register`. */
const ID_LABEL_MAX = 160;

function labelOf(entry: Block, next: Block | undefined): string | null {
  if (entry.kind !== "paragraph") return null;
  const text = entry.text.trim();
  const bold = BOLD_LABEL.exec(text);
  if (bold) return bold[2] ? `${bold[1]!} ${bold[2]}` : bold[1]!;
  return next?.kind === "table" && text.length <= ID_LABEL_MAX && REGISTER_ID.test(text)
    ? text
    : null;
}

// A register's shape from its title and columns, first rule first. The
// patterns name the columns the methodology's registers carry (their output
// profiles, `vendor/deploy-v/skills/*/SKILL.md`).
const SHAPE_TITLE_MAX = 300;
// The bundle's widest register head joins to 261 characters (CP-3's T3.7).
const SHAPE_HEAD_MAX = 2_000;
const SHAPES: [Shape, RegExp][] = [
  [
    "sources",
    /source_document_id|source file name|source document id|subject_identity|:: (authority rank|source; status; authority|source id; source class|document; parties|agency; criteria|source; reliability|source_id; upstream|security_id; issuer)|source (register|hierarchy)|authority hierarchy|input sources|document authority/,
  ],
  [
    "qa",
    /:: (severity|issue id|check_id|module; handoff)|qa status|traceab|master index|pipeline|workspace record|package record|parse jobs|prepared artifacts|representation catalog|input gate|triage/,
  ],
  [
    "gaps",
    /:: (gaps?\b|gap id|gap description|missing|claim\/legal\/value\/process gap|item; conflict\/gap)|gaps?\/conflicts|gaps? (&|and) conflicts?|gaps_ledger/,
  ],
  ["conflicts", /:: (conflict|issue; agency|metric name; canonical definition)|conflict_log/],
  ["trace", /:: statement|citation present|evidence trace|:: evidence_id; question_id/],
  [
    "readiness",
    /:: (downstream module|downstream_module|module; status)|readiness|command sheet|content-to-module|module map|target_full_module_id|:: event id; description; priority; (receiving|monitoring)/,
  ],
  ["tests", /headroom|threshold; .*(current|case\/period value)/],
  ["scores", /score|:: category; factor; weight/],
  // A title that calls itself a walk or a bridge is one, whatever its columns.
  ["bridge", /:: step; amount|cumulative|bridge item|\b(walk|bridge)\b(?=.* :: )/],
  // Periods across the columns (`FY2023`, `Dec-24`, `LTM Mar-26`) read as a
  // financial series.
  [
    "series",
    /period 1…n|case; period_id|:: period; case|:: period_id; fiscal_year|:: metric_id; period_id; value|:: case; trajectory|:: assumption_id|segment_id; segment_name|derived period type|:: metric; historical actual|business line; revenue mix|:: metric; realized value|:: [^;]+; (fy ?[0-9]{2,4}|ltm|ytd|q[1-4]\b|(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[-' ]?[0-9]{2}|20[0-9]{2})/,
  ],
  [
    "comparison",
    /on reported|prior value|expected; realized|cp1_value|borrower value|current_value; reference_value|:: metric; expected|:: comparator|:: description; source; type; before; after|agency \/ convention|\bdelta\b(?=.* :: )|; from; to\b/,
  ],
  [
    "peers",
    /:: entity; (revenue|fcf|total\/net|metric)|peer avg|mkt cap|txn name|:: entity name; peer|:: method; multiple source/,
  ],
  [
    "capital",
    /facility_id|debt instrument|:: instrument; type; amount|creditor class|class\/claim id|claim\/tranche|:: scenario; (entity|class|valuation)|scenario\/ev range|entity × |hedge type|liquidity component|cash use|:: item; category; reported amount|:: add-back id; description; amount|:: item; debt-like|:: entity; role; jurisdiction|:: tranche;|\b(debt|tranche|liquidity|capitali[sz]ation)\b(?=.* :: )/,
  ],
  ["market", /spread(?! effect)|bid|quote|market level|security_id|price/],
  [
    "timeline",
    /date\/window|date \/ window|:: event; date|event\/milestone|events_timeline|:: event id; source document/,
  ],
  ["debate", /bull|bear|rv position|compliance|rv bullet/],
  ["research", /question_id/],
  [
    "triggers",
    /:: (trigger|trigger id|red flag|nearest trigger|observable|flag;|flag id|driver shock|instrument; kpi\b)/,
  ],
  [
    "findings",
    /risk mechanic|credit implication|credit relevance|pd effect|implication|topic_id; topic_label|attribution label|:: pattern; target module|sizing posture|path type|:: path; process|:: mechanism|:: provision|:: effect; direction|:: exposure|:: factor|:: operating stress|achievability basis|:: agency; (factor|case)|hit rate/,
  ],
  [
    "profile",
    /:: (row label|entity name; entity role|issuer; business|dimension; assessment; credit rationale|business quality factor|action bias|thesis|owner \/ class|transaction;)/,
  ],
  ["definitions", /definition|formula|criteria|agency metric/],
];

/** The bundle's tagged tables (`<!-- table-id: -->`), each with its schema
    reference's name and its shape: a declared table is placed by its id, never
    guessed from its columns, where `source_definition` once read as a
    definition. `markdown.test` fails on a declared id missing here. */
export const STABLE_TABLES: Readonly<Record<string, { title: string; shape: Shape }>> = {
  "cp1.model_period_register": { title: "Period register", shape: "series" },
  "cp1.model_account_register": { title: "Account register", shape: "series" },
  "cp1.segment_revenue_schedule": { title: "Segment revenue", shape: "series" },
  "cp1.operating_kpi_schedule": { title: "Operating KPIs", shape: "series" },
  "cp1.adjusted_ebitda_bridge": { title: "Adjusted EBITDA bridge", shape: "bridge" },
  "cp1.cp_model_segment_allocation": { title: "Segment forecast slots", shape: "definitions" },
  "cp1.debt_facility_register": { title: "Debt facilities", shape: "capital" },
  "cp1.model_reconciliation_register": { title: "Reconciliation checks", shape: "qa" },
  "cp1.downstream_readiness": { title: "Downstream readiness", shape: "readiness" },
  "cp1a.cp_model_snapshot_fields": { title: "Model snapshot fields", shape: "profile" },
  "cp1b.model_comparator_register": { title: "Period comparisons", shape: "comparison" },
  "cp1b.model_validation_register": { title: "Metric validation", shape: "tests" },
  "cp1b.addback_validation_register": { title: "Add-back validation", shape: "tests" },
  "cp1b.model_readiness": { title: "Downstream readiness", shape: "readiness" },
  "cp1b.cp_model_snapshot_fields": { title: "Model snapshot fields", shape: "profile" },
  "cp2.cp_model_strengths_weaknesses": { title: "Strengths and weaknesses", shape: "findings" },
  "cp2b.cp_model_catalysts": { title: "Catalysts", shape: "timeline" },
  "cp2g.cp_model_forecast_drivers": { title: "Forecast drivers", shape: "series" },
  "cpdr.questions": { title: "Research questions", shape: "research" },
  "cpdr.evidence": { title: "Research evidence", shape: "trace" },
  "cpdr.findings": { title: "Research findings", shape: "research" },
  "cpdr.adoptions": { title: "Research adoptions", shape: "research" },
};

/** A register's shape, from its title and its columns. */
export function shapeOf(title: string, head: readonly string[]): Shape {
  // A title past a sentence, and the columns past the bound, name no shape:
  // the rules' `[^;]+` and `.*` runs cost a pass per `::` or per column, and
  // 120,000 characters of `:: x` in either took seconds. A title cut short
  // instead could end on half a word (`walkthrough` read as a walk).
  const named = title.length > SHAPE_TITLE_MAX ? "" : title;
  let columns = 0;
  for (let length = -2; columns < head.length; columns += 1) {
    length += head[columns]!.length + 2;
    if (length > SHAPE_HEAD_MAX) break;
  }
  const key = `${named} :: ${head.slice(0, columns).join("; ")}`.toLowerCase();
  return SHAPES.find(([, rule]) => rule.test(key))?.[0] ?? "table";
}

/** A heading's register id and the words after it: `T4C.4 — Covenant
    headroom` is `T4C.4` and `Covenant headroom`. */
export function registerHeading(text: string): { id: string | null; title: string } {
  const match = REGISTER_ID.exec(text.trim());
  if (!match) return { id: null, title: text.trim() };
  const title = text
    .trim()
    .slice(match[1]!.length)
    .replace(/^[\s.:—–-]+/, "");
  return { id: match[1]!, title };
}

function registersOf(blocks: readonly Block[]): { registers: Register[]; rest: Block[] } {
  const registers: Register[] = [];
  const rest: Block[] = [];
  let heading: { id: string | null; title: string } | null = null;
  let tagged: string | null = null;
  let notes: Block[] = [];
  for (const [index, entry] of blocks.entries()) {
    const label = labelOf(entry, blocks[index + 1]);
    if (entry.kind === "heading" || label !== null) {
      rest.push(...notes);
      notes = [];
      heading = registerHeading(label ?? (entry as { text: string }).text);
      tagged = null;
    } else if (entry.kind === "comment" && tableTag(entry.text) !== null) {
      const tag = tableTag(entry.text)!;
      tagged = tag.id;
      // A caveat the model wrote beside the tag is its own text: it stays a
      // note of the register the tag labels, never consumed with the tag.
      if (!tag.bare) notes.push(entry);
    } else if (entry.kind === "table") {
      const id = tagged ?? heading?.id ?? null;
      const stable = tagged === null ? undefined : STABLE_TABLES[tagged];
      const title = heading?.title || stable?.title || id || "Table";
      registers.push({
        id,
        title,
        notes,
        table: entry.table,
        shape: stable?.shape ?? shapeOf(title, entry.table.head),
      });
      // A heading labels the table under it, not the next register's.
      heading = null;
      notes = [];
      tagged = null;
    } else {
      notes.push(entry);
    }
  }
  rest.push(...notes);
  return { registers, rest };
}

/** The H2 sections as written, each with its heading block; text before
    the first H2 is its own part. */
function sectionsOf(blocks: readonly Block[]): (Part & { heading: Block | null })[] {
  const parts: (Part & { heading: Block | null })[] = [];
  for (const entry of blocks) {
    if (entry.kind === "heading" && entry.level === 2) {
      parts.push({ title: entry.text.trim(), heading: entry, blocks: [] });
    } else if (parts.length === 0) parts.push({ title: "", heading: null, blocks: [entry] });
    else parts.at(-1)!.blocks.push(entry);
  }
  return parts;
}

/** Split at each heading of the shallowest level present. */
function byHeading(blocks: readonly Block[]): Part[] {
  const levels = blocks.flatMap((entry) => (entry.kind === "heading" ? [entry.level] : []));
  const top = Math.min(...levels);
  const parts: Part[] = [];
  for (const entry of blocks) {
    if (entry.kind === "heading" && entry.level === top)
      parts.push({ title: entry.text.trim(), blocks: [] });
    else if (parts.length === 0) parts.push({ title: "", blocks: [entry] });
    else parts.at(-1)!.blocks.push(entry);
  }
  return parts;
}

/** A module's Markdown in the page's places. A document without the six H2s
    (an older handoff, a demonstration excerpt) is read as its Analysis. */
export function moduleParts(blocks: readonly Block[]): ModuleParts {
  const front = blocks.find((entry) => entry.kind === "front");
  const body = blocks.filter((entry) => entry.kind !== "front");
  const sections = sectionsOf(body);
  const named = sections.find((part) => part.title.toLowerCase() === "analysis");
  const audit = new Map<string, Block[]>();
  const loose: Part[] = [];
  // Without an `## Analysis`, every section that is not an audit one is read
  // as the analysis, its own H2 kept as its opening heading.
  const unnamed: Block[] = [];
  // An appendix a module wrote as its own H2 is the appendix all the same,
  // and so is one it wrote inside another section: deployed runs put
  // `### Analytical appendix` under `## Evidence Trace` or `## Source Registry`.
  // What follows that heading, to the section's end, is registers.
  const appendixH2: Block[] = [];
  // Sections written before `## Analysis` (CP-3's `## Recommendation`) come
  // first, in the order the module wrote them.
  const before: Part[] = [];
  const analysisAt = named ? sections.indexOf(named) : -1;
  for (const [index, part] of sections.entries()) {
    if (part === named) continue;
    // Text before the first H2 that is only the document's H1 is its title,
    // which the module's header already says; As written keeps it.
    if (!part.heading && part.blocks.every((b) => b.kind === "heading" && b.level === 1)) {
      continue;
    }
    const inner = part.blocks.findIndex(
      (entry) => entry.kind === "heading" && APPENDIX.test(entry.text),
    );
    const own = inner < 0 ? part.blocks : part.blocks.slice(0, inner);
    if (inner >= 0) appendixH2.push(...part.blocks.slice(inner + 1));
    const name = auditOf(part.title);
    if (name) audit.set(name, [...(audit.get(name) ?? []), ...own]);
    else if (APPENDIX.test(part.title)) appendixH2.push(...own);
    else if (named && index < analysisAt) before.push({ title: part.title, blocks: own });
    else if (named) loose.push({ title: part.title, blocks: own });
    else unnamed.push(...(part.heading ? [part.heading] : []), ...own);
  }

  const inAnalysis = named ? named.blocks : unnamed;
  const cut = inAnalysis.findIndex(
    (entry) => entry.kind === "heading" && APPENDIX.test(entry.text),
  );
  const front_ = cut < 0 ? inAnalysis : inAnalysis.slice(0, cut);
  const appendix = cut < 0 ? [] : inAnalysis.slice(cut + 1);
  // Before the appendix, a table with a register id is a register too; the
  // reader-facing compact table carries none and stays where it was written.
  const tagged = front_.flatMap((entry, index) =>
    entry.kind === "table" &&
    front_[index - 1]?.kind === "comment" &&
    tableTag((front_[index - 1] as { text: string }).text) !== null
      ? [index - 1, index]
      : [],
  );
  const reading = front_.filter((_, index) => !tagged.includes(index));
  const { registers, rest } = registersOf([
    ...tagged.map((index) => front_[index]!),
    ...appendix,
    ...appendixH2,
  ]);

  const parts = reading.some((entry) => entry.kind === "heading")
    ? byHeading(reading)
    : reading.length
      ? [{ title: "", blocks: reading }]
      : [];
  const ordered = [...before, ...parts];
  const lead = ordered[0] ?? null;
  const reader = [
    ...ordered.slice(1),
    ...loose,
    ...(rest.length ? [{ title: "Appendix notes", blocks: rest }] : []),
  ];
  return {
    front: front?.kind === "front" ? front.text : null,
    lead,
    reader,
    registers,
    audit: AUDIT_SECTIONS.filter((name) => audit.has(name)).map((name) => ({
      title: name,
      blocks: audit.get(name)!,
    })),
  };
}

// ---- the opening, as the canon orders it ----

/** One decision driver: the claim its bold opens with, and what supports it. */
export interface Driver {
  claim: string;
  support: string;
}

/** The opening view as the page leads with it (CANON_SHARED, reading order:
    a conclusion-first view, then up to three decision drivers): the view's
    first sentence, the rest of its first paragraph, the drivers where they are
    written as a bold-led list, and everything else the opening holds. Text is
    split, never rewritten; As written keeps it whole. */
export interface Opening {
  lede: string | null;
  continuation: string | null;
  drivers: { intro: string | null; items: Driver[] } | null;
  rest: Block[];
}

const LEDE_MIN = 40;
const LEDE_MAX = 360;
// The closers after a sentence's end are one character class, never `**` and
// `*` as two alternatives: a run of stars then paired in a Fibonacci number
// of ways before a failed match gave up, and 44 stars froze the page.
const SENTENCE_END = /[.!?][*"”’)]*\s+(?=["“(*]*[A-Z0-9$])/g;
// A period that ends an abbreviation or an initial ends no sentence.
const ABBREVIATION =
  /(?:\b(?:e\.g|i\.e|vs|No|Inc|Ltd|Co|Corp|approx|cf|St|Mr|Ms|Dr|pp?|etc|U\.S|U\.K)|\b[A-Z])\.$/;
const BOLD_LED = /^\*\*(.+?)\*\*\s*(.*)$/s;

/** A paragraph's first sentence and the rest; `null` for the lede when no
    sentence of a readable length opens it. */
export function splitLede(text: string): { lede: string | null; continuation: string | null } {
  for (const match of text.matchAll(SENTENCE_END)) {
    const end = match.index + match[0].trimEnd().length;
    const lede = text.slice(0, end);
    if (lede.length < LEDE_MIN) continue;
    if (lede.length > LEDE_MAX) break;
    if (ABBREVIATION.test(lede.replace(/[*"”’)]+$/, ""))) continue;
    // Never inside a strong span: its delimiters must pair on each side.
    if ((lede.match(/\*\*/g)?.length ?? 0) % 2) continue;
    return { lede, continuation: text.slice(end).trim() || null };
  }
  return text.length <= LEDE_MAX
    ? { lede: text, continuation: null }
    : { lede: null, continuation: text };
}

function driversOf(list: Block): Driver[] | null {
  if (list.kind !== "list") return null;
  const items = list.list.items;
  if (items.length === 0 || items.some((item) => item.lists.length)) return null;
  const led = items.map((item) => BOLD_LED.exec(item.text));
  if (led.some((match) => match === null)) return null;
  return led.map((match) => ({ claim: match![1]!, support: match![2]! }));
}

/** The opening part read in the canon's order. */
export function openingOf(lead: Part): Opening {
  const [first, ...after] = lead.blocks;
  if (first?.kind !== "paragraph") {
    return { lede: null, continuation: null, drivers: null, rest: [...lead.blocks] };
  }
  const { lede, continuation } = splitLede(first.text);
  const at = after.findIndex((entry) => entry.kind === "list");
  const items = at < 0 ? null : driversOf(after[at]!);
  if (items === null) return { lede, continuation, drivers: null, rest: after };
  // "Three facts govern:" introduces the drivers and goes with them.
  const before = after[at - 1];
  const intro = before?.kind === "paragraph" && /:\s*$/.test(before.text) ? before.text : null;
  const rest = after.filter((_, index) => index !== at && !(intro && index === at - 1));
  return { lede, continuation, drivers: { intro, items }, rest };
}

/** A section that argues against the module's own view, headed so. The canon
    requires one in every module and names no heading for it. */
export const CONTRARY = /\b(contrary|counter-?argument|counter-?case)\b/i;

/** Where a register's shape puts it on the page. */
export type Place = "lead" | "appendix" | (typeof AUDIT_SECTIONS)[number];

const AUDIT_PLACE: Partial<Record<Shape, Place>> = {
  sources: "Source registry",
  trace: "Evidence trace",
  gaps: "Gaps and conflicts",
  conflicts: "Gaps and conflicts",
  qa: "QA validation",
  readiness: "QA validation",
};

// The two modules whose conclusion is an audit-shaped register: CP-0's is
// which modules can run, CP-5's is its issue log.
const LEAD_REGISTERS: Record<string, readonly string[]> = {
  "CP-0": ["T4", "T8"],
  "CP-5": ["T5.9"],
};

/** Where a register sits: the lead (debate, research questions, and CP-0's
    and CP-5's conclusions), an audit section, or the appendix. */
export function placeOf(moduleId: string, register: Register): Place {
  if (register.id && LEAD_REGISTERS[moduleId]?.includes(register.id)) return "lead";
  if (register.shape === "debate" || register.shape === "research") return "lead";
  return AUDIT_PLACE[register.shape] ?? "appendix";
}

/** The appendix's groups, in reading order; what no rule recognised is last,
    and called what it is. */
export const APPENDIX_GROUPS: readonly { name: string; shapes: readonly Shape[] }[] = [
  { name: "Financials", shapes: ["series", "bridge"] },
  { name: "Comparisons", shapes: ["comparison", "peers"] },
  { name: "Capital structure", shapes: ["capital"] },
  { name: "Market", shapes: ["market"] },
  { name: "Findings", shapes: ["findings", "profile"] },
  { name: "Tests and scores", shapes: ["tests", "scores"] },
  { name: "Triggers and timeline", shapes: ["triggers", "timeline"] },
  { name: "Definitions", shapes: ["definitions"] },
  {
    name: "Unsorted",
    shapes: [
      "table",
      "debate",
      "research",
      "sources",
      "trace",
      "gaps",
      "conflicts",
      "qa",
      "readiness",
    ],
  },
];

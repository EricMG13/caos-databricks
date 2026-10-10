// A module's figures drawn from the registers its output profile declares
// (N94), located by the host with the bundle's own reader. A register id is
// the module's own, not the bundle's (CP-1, CP-1B and CP-1C each declare a
// `T4.6`), so a register is read only for the module that serves it. Like the
// tagged tables, every value is the model's, printed exactly as served; a
// float only places a mark. Rows of one unit share a figure, so no axis
// holds a multiple beside a percentage.
import {
  formatDecimal,
  type ChartColor,
  type ChartSelection,
  type RangeRow,
  type WaterfallStep,
} from "@/charts";
import { bridgeOf } from "@/charts/bridge";
import type { HandoffView } from "@/wire/v1";
import {
  MAX_MARKS,
  datum,
  groupBy,
  oversized,
  text,
  type Cell,
  type Figure,
  type Row,
} from "./figure-core";

/** A register's rows keyed by the profile column the bundle binds to each
    header cell, else by the header as written; `null` unless `handoff` is
    `moduleId`'s and serves `registerId`. */
export function registerRows(
  handoff: HandoffView,
  moduleId: string,
  registerId: string,
): Row[] | null {
  if (handoff.module_id !== moduleId) return null;
  const register = handoff.registers.find((entry) => entry.register_id === registerId);
  if (!register) return null;
  const keys = register.columns.map((column, index) => {
    const declared = register.declared[index] ?? null;
    return { key: declared ?? column, index, declared: declared !== null };
  });
  // A declared column wins over a header cell spelled like it: the cells no
  // column is bound to are keyed first, so a bound one overwrites them.
  const order = [...keys.filter((key) => !key.declared), ...keys.filter((key) => key.declared)];
  return register.rows.map((row) =>
    Object.fromEntries(order.map(({ key, index }) => [key, row[index]])),
  );
}

type Unit = "x" | "%";

/** A citation marker as a cell may end in: `[C1]`, `[C1, C2]`, escaped or not. */
const MARKER = /^\\?\[C[0-9]+(?:\\?, ?C[0-9]+)*\\?\]$/;

/** `written` without the citation markers that trail it: `3.25x [C1]` is
    `3.25x`, as the host reads it for a figure. */
function unmarked(written: string): string {
  let rest = written.trimEnd();
  for (;;) {
    const open = rest.lastIndexOf("[");
    const from = open > 0 && rest[open - 1] === "\\" ? open - 1 : open;
    if (open < 0 || !MARKER.test(rest.slice(from))) return rest;
    rest = rest.slice(0, from).trimEnd();
  }
}

/** The unit a figure cell's text ends in, `x` or `%`, past its citation
    markers and a negative's brackets, as the host's reader strips them; none
    for a cell the host read no figure from. */
function suffixOf(cell: Cell | undefined): Unit | undefined {
  if (cell?.value == null) return undefined;
  const written = unmarked(cell.text);
  const bare =
    written.startsWith("(") && written.endsWith(")") ? written.slice(1, -1).trim() : written;
  if (/[xX]$/.test(bare)) return "x";
  return bare.endsWith("%") ? "%" : undefined;
}

/** A cell as a summary says it: its figure as served, else n/a and its text. */
const served = (cell: Cell | undefined) =>
  cell?.value != null ? formatDecimal(cell.value) : `n/a (${cell?.text || "not stated"})`;

/** The columns a row states, each named: "Formula: …; Status: …". */
function stated(row: Row, columns: readonly string[]): string | null {
  const parts = columns.filter((column) => text(row, column)).map((c) => `${c}: ${text(row, c)}`);
  return parts.length ? parts.join("; ") : null;
}

/** A register row and its place in the register, which keys its marks. */
interface Entry {
  row: Row;
  index: number;
}

/** What a figure of one unit's rows is called, and where it comes from. */
interface Head {
  key: string;
  table: string;
  title: string;
  unit: Unit | undefined;
}

const UNIT_KEY: Record<Unit, string> = { x: "x", "%": "percent" };

/** A figure per unit, in the order each unit first appears; its title
    carries the unit. A figure past `MAX_MARKS` is stated, not drawn. */
function perUnit(
  rows: readonly Row[],
  base: { key: string; table: string; title: string },
  unitOf: (row: Row) => Unit | undefined,
  marksPerRow: number,
  draw: (entries: readonly Entry[], head: Head) => Figure,
): Figure[] {
  const entries = rows.map((row, index) => ({ row, index }));
  return [...groupBy(entries, (entry) => unitOf(entry.row) ?? "").values()].map((group) => {
    const unit = unitOf(group[0]!.row);
    const head = {
      key: unit ? `${base.key}-${UNIT_KEY[unit]}` : base.key,
      table: base.table,
      title: unit ? `${base.title}, ${unit}` : base.title,
      unit,
    };
    const marks = group.length * marksPerRow;
    return marks > MAX_MARKS
      ? oversized(head.key, head.table, head.title, marks)
      : draw(group, head);
  });
}

/** The mark a figure's selection names, by its place in the figure. */
const pickedRow = (entries: readonly Entry[], selection: ChartSelection) =>
  entries[selection.index]?.row;

// The directions the bundle reads a covenant's test type as: its
// `TEST_TYPE_ALIASES` in
// vendor/deploy-v/skills/cp-4-legal-covenant-interpreter/scripts/covenant_headroom.py,
// looked up as its `normalise_test_type` looks them up (trimmed, casefolded,
// a space read as a hyphen). Anything else has no direction: one is never
// inferred from a test's name. A Map, so no inherited key is ever a type.
const TEST_TYPE_ALIASES = new Map<string, "max" | "min">([
  ["max-ratio", "max"],
  ["max_ratio", "max"],
  ["maximum", "max"],
  ["maintenance", "max"],
  ["ceiling", "max"],
  ["incurrence-max", "max"],
  ["min-ratio", "min"],
  ["min_ratio", "min"],
  ["minimum", "min"],
  ["coverage", "min"],
  ["floor", "min"],
  ["incurrence-min", "min"],
]);

function directionOf(row: Row): "max" | "min" | null {
  const key = unmarked(text(row, "Test Type")).trim().toLowerCase().replaceAll(" ", "-");
  return TEST_TYPE_ALIASES.get(key) ?? null;
}

/** CP-4's covenant headroom (`T4C.4`): each test's current basis against its
    threshold, the headroom the module stated printed as served. */
export function covenantHeadroom(handoff: HandoffView): Figure[] {
  const rows = registerRows(handoff, "CP-4", "T4C.4");
  if (!rows?.length) return [];
  const unitOf = (row: Row) => suffixOf(row["Current Basis"]) ?? suffixOf(row["Threshold"]);
  const base = { key: "covenant-headroom", table: "T4C.4", title: "Covenant headroom" };
  // A bar and a rule a test.
  return perUnit(rows, base, unitOf, 2, (entries, head) => ({
    ...head,
    kind: "bullet",
    summary: `Headroom as served: ${entries
      .map(({ row }) => `${text(row, "Test")} ${served(row["Headroom"])}`)
      .join("; ")}.`,
    bullets: entries.map(({ row, index }) => ({
      key: `${index}`,
      label: text(row, "Test"),
      direction: directionOf(row),
      threshold: datum(row["Threshold"]),
      current: datum(row["Current Basis"]),
      headroom: datum(row["Headroom"]),
      origin: "model",
    })),
    sourceOf: (selection) => {
      const row = pickedRow(entries, selection);
      return row ? stated(row, ["Formula", "Status", "Evidence ID"]) : null;
    },
  }));
}

/** A range strip's statistics and the `T4.6` column each is read from. */
const PEER_STATISTICS = [
  ["min", "Min"],
  ["q1", "Q1"],
  ["median", "Median"],
  ["q3", "Q3"],
  ["max", "Max"],
  ["marker", "Borrower Value"],
] as const;

/** A metric's range: each statistic its register declares, as served. */
function peerRange({ row, index }: Entry): RangeRow {
  const range: RangeRow = { key: `${index}`, label: text(row, "Metric"), origin: "model" };
  for (const [statistic, column] of PEER_STATISTICS) {
    const cell = row[column];
    if (cell !== undefined) range[statistic] = datum(cell);
  }
  return range;
}

/** CP-1C's peer statistics (`T4.6`): each metric's peer range, min to max
    with its quartiles and median, the borrower's value marked against it. */
export function peerRanges(handoff: HandoffView): Figure[] {
  const rows = registerRows(handoff, "CP-1C", "T4.6");
  if (!rows?.length) return [];
  const unitOf = (row: Row) => suffixOf(row["Borrower Value"]) ?? suffixOf(row["Median"]);
  const declares = (column: string) => rows[0]![column] !== undefined;
  // One bar for the quartiles, and a rule or a dot for each other statistic.
  const marks =
    (declares("Q1") || declares("Q3") ? 1 : 0) +
    ["Min", "Median", "Max", "Borrower Value"].filter(declares).length;
  const base = { key: "peer-ranges", table: "T4.6", title: "Peer ranges" };
  return perUnit(rows, base, unitOf, marks, (entries, head) => ({
    ...head,
    kind: "range",
    summary: `Borrower value as served: ${entries
      .map(({ row }) => {
        const position = text(row, "Borrower Position");
        return `${text(row, "Metric")} ${served(row["Borrower Value"])}${position ? ` (${position})` : ""}`;
      })
      .join("; ")}.`,
    ranges: entries.map(peerRange),
    markerLabel: "Borrower value",
    categoryLabel: "Metric",
    sourceOf: (selection) => {
      const row = pickedRow(entries, selection);
      return row ? stated(row, ["Peer Avg", "N"]) : null;
    },
  }));
}

// The colour each of CP-1D's closed statuses wears
// (vendor/deploy-v/skills/cp-1d-earnings-quality/references/CP-1D_SCHEMA_REFERENCE.md),
// read trimmed and casefolded, in the schema's order. Any other word wears
// no colour; its name and row still say it.
const STATUSES: readonly { color: ChartColor; label: string }[] = [
  { color: "positive", label: "Supported" },
  { color: "series-3", label: "Challenged" },
  { color: "negative", label: "Rejected" },
  { color: "series-4", label: "Insufficient Information" },
];
const STATUS_COLOR = new Map(STATUSES.map(({ color, label }) => [label.toLowerCase(), color]));

/** What a bridge register is: whose, which, its running-level column (which
    names the closing total) and its status column, if it has one. */
interface BridgeRegister {
  module: string;
  register: string;
  cumulative: string;
  status?: string;
  key: string;
  title: string;
}

/** A row's step: the first opens the bridge on its `Amount`, else its
    running level; a later one with an `Amount` figure moves the level, as
    served; one with only a running level states a total; one with neither is
    a change with a gap, its `Amount` text the reason. */
function bridgeStep(row: Row, index: number, spec: BridgeRegister): WaterfallStep {
  const amount = row["Amount"];
  const level = row[spec.cumulative];
  const total = index === 0 || (amount?.value == null && level?.value != null);
  const cell = amount?.value != null || level?.value == null ? amount : level;
  const step: WaterfallStep = {
    key: `${index}`,
    label: text(row, "Step"),
    kind: total ? "total" : "delta",
    origin: "model",
    ...datum(cell),
  };
  // A total stays neutral: only a change wears its status's colour.
  const status = spec.status ? text(row, spec.status).trim() : "";
  const color = total ? undefined : STATUS_COLOR.get(status.toLowerCase());
  return { ...step, ...(color ? { color } : {}), ...(status ? { status } : {}) };
}

/** A bridge register drawn as a waterfall, every figure as served. Where the
    last row is a change and states its running level, that level closes the
    bridge as a total named for its column. The schema's empty bridge (one
    `NONE` row) draws nothing. */
function bridgeFigure(handoff: HandoffView, spec: BridgeRegister): Figure[] {
  const rows = registerRows(handoff, spec.module, spec.register);
  if (!rows?.length) return [];
  if (rows.length === 1 && text(rows[0]!, "Step").trim().toUpperCase() === "NONE") return [];
  const steps = rows.map((row, index) => bridgeStep(row, index, spec));
  const last = rows.at(-1)!;
  if (steps.at(-1)!.kind === "delta" && last[spec.cumulative]?.value != null) {
    const level = last[spec.cumulative]!.value!;
    steps.push({
      key: "closing",
      label: spec.cumulative,
      kind: "total",
      value: level,
      origin: "model",
    });
  }
  const marks = bridgeOf(steps).length;
  if (marks > MAX_MARKS) return [oversized(spec.key, spec.register, spec.title, marks)];
  const ends = [steps[0]!, steps.at(-1)!].map(
    (step) =>
      `${step.label} ${step.value === null ? `n/a (${step.reason})` : formatDecimal(step.value)}`,
  );
  const rowOf = (key: string) => (key === "closing" ? last : rows[Number(key)]);
  const used = new Set(steps.map((step) => step.color));
  const statuses = spec.status ? STATUSES.filter(({ color }) => used.has(color)) : undefined;
  return [
    {
      key: spec.key,
      table: spec.register,
      kind: "waterfall",
      title: spec.title,
      summary: `${steps.length > 1 ? ends.join(" to ") : ends[0]}, as served.`,
      steps,
      ...(statuses ? { statuses } : {}),
      sourceOf: (selection) => {
        const row = /^(closing|[0-9]+)$/.test(selection.series)
          ? rowOf(selection.series)
          : undefined;
        return row ? stated(row, ["Basis", "Evidence ID"]) : null;
      },
    },
  ];
}

/** CP-1D's EBITDA quality bridge (`T1D.4`): reported to adjusted EBITDA, each
    add-back coloured by whether the module supports, challenges or rejects it. */
export function ebitdaQuality(handoff: HandoffView): Figure[] {
  return bridgeFigure(handoff, {
    module: "CP-1D",
    register: "T1D.4",
    cumulative: "Cumulative EBITDA",
    status: "Supported / Challenged / Rejected",
    key: "ebitda-quality",
    title: "EBITDA quality bridge",
  });
}

/** Every figure a handoff's registers support, in reading order. A handoff
    is one module's, so only its own module's figures draw for it. */
export function registerFigures(handoff: HandoffView): Figure[] {
  return [...covenantHeadroom(handoff), ...peerRanges(handoff), ...ebitdaQuality(handoff)];
}

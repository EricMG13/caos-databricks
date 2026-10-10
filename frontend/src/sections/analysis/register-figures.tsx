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
  negatedMagnitude,
  oversized,
  pair,
  text,
  type Cell,
  type Figure,
  type Row,
  type WaterfallFigure,
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

/** What a figure of one group's rows is called, and where it comes from. */
interface Head {
  key: string;
  table: string;
  title: string;
  unit: string | undefined;
}

/** How a register's rows split into figures: a row's group (none: the
    figure whose key and title carry no suffix), the suffix a group adds to
    its figure's key and title, and the figure's unit. */
interface Grouping<G extends string> {
  of: (row: Row) => G | undefined;
  key: (group: G) => string;
  title: (group: G) => string;
  unit: (group: G) => string | undefined;
}

const UNIT_KEY: Record<Unit, string> = { x: "x", "%": "percent" };

/** Rows grouped by the unit their figure is written in, `x` or `%`. */
const bySuffix = (unitOf: (row: Row) => Unit | undefined): Grouping<Unit> => ({
  of: unitOf,
  key: (unit) => UNIT_KEY[unit],
  title: (unit) => unit,
  unit: (unit) => unit,
});

/** A register's rows split by `grouping`, in the order each group first
    appears, each with its figure's head. */
function groupsOf<G extends string>(
  rows: readonly Row[],
  base: { key: string; table: string; title: string },
  grouping: Grouping<G>,
): { entries: Entry[]; head: Head }[] {
  const entries = rows.map((row, index) => ({ row, index }));
  return [...groupBy(entries, (entry) => grouping.of(entry.row) ?? "").values()].map((group) => {
    const at = grouping.of(group[0]!.row);
    const head = {
      key: at ? `${base.key}-${grouping.key(at)}` : base.key,
      table: base.table,
      title: at ? `${base.title}, ${grouping.title(at)}` : base.title,
      unit: at ? grouping.unit(at) : undefined,
    };
    return { entries: group, head };
  });
}

/** A figure per group; a figure past `MAX_MARKS` is stated, not drawn. */
function perGroup<G extends string>(
  rows: readonly Row[],
  base: { key: string; table: string; title: string },
  grouping: Grouping<G>,
  marksPerRow: number,
  draw: (entries: readonly Entry[], head: Head) => Figure,
): Figure[] {
  return groupsOf(rows, base, grouping).map(({ entries, head }) => {
    const marks = entries.length * marksPerRow;
    return marks > MAX_MARKS
      ? oversized(head.key, head.table, head.title, marks)
      : draw(entries, head);
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
  return perGroup(rows, base, bySuffix(unitOf), 2, (entries, head) => ({
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

type Statistic = Exclude<keyof RangeRow, "key" | "label" | "origin">;

/** A range strip's statistics, each with the register column it is read from. */
type Statistics = readonly (readonly [Statistic, string])[];

/** A row's range, labelled by its `label` column: each statistic its
    register declares, as served. */
const rangeOf =
  (statistics: Statistics, label: string) =>
  ({ row, index }: Entry): RangeRow => {
    const range: RangeRow = { key: `${index}`, label: text(row, label), origin: "model" };
    for (const [statistic, column] of statistics) {
      const cell = row[column];
      if (cell !== undefined) range[statistic] = datum(cell);
    }
    return range;
  };

/** A row's marks: one bar for the quartiles, where either is declared, and a
    rule or a dot for each other statistic `row` declares. */
function rangeMarks(row: Row, statistics: Statistics): number {
  const declared = statistics.filter(([, column]) => row[column] !== undefined);
  const quartiles = declared.filter(([statistic]) => statistic === "q1" || statistic === "q3");
  return (quartiles.length ? 1 : 0) + declared.length - quartiles.length;
}

/** `T4.6`'s statistics. */
const PEER_STATISTICS: Statistics = [
  ["min", "Min"],
  ["q1", "Q1"],
  ["median", "Median"],
  ["q3", "Q3"],
  ["max", "Max"],
  ["marker", "Borrower Value"],
];

/** CP-1C's peer statistics (`T4.6`): each metric's peer range, min to max
    with its quartiles and median, the borrower's value marked against it. */
export function peerRanges(handoff: HandoffView): Figure[] {
  const rows = registerRows(handoff, "CP-1C", "T4.6");
  if (!rows?.length) return [];
  const unitOf = (row: Row) => suffixOf(row["Borrower Value"]) ?? suffixOf(row["Median"]);
  const marks = rangeMarks(rows[0]!, PEER_STATISTICS);
  const base = { key: "peer-ranges", table: "T4.6", title: "Peer ranges" };
  return perGroup(rows, base, bySuffix(unitOf), marks, (entries, head) => ({
    ...head,
    kind: "range",
    summary: `Borrower value as served: ${entries
      .map(({ row }) => {
        const position = text(row, "Borrower Position");
        return `${text(row, "Metric")} ${served(row["Borrower Value"])}${position ? ` (${position})` : ""}`;
      })
      .join("; ")}.`,
    ranges: entries.map(rangeOf(PEER_STATISTICS, "Metric")),
    markerLabel: "Borrower value",
    categoryLabel: "Metric",
    sourceOf: (selection) => {
      const row = pickedRow(entries, selection);
      return row ? stated(row, ["Peer Avg", "N"]) : null;
    },
  }));
}

/** `T4.10`'s statistics: it states no quartiles. */
const IMPLIED_STATISTICS: Statistics = [
  ["min", "Low"],
  ["median", "Median"],
  ["max", "High"],
  ["marker", "Implied EV"],
];

/** CP-1C's implied enterprise value (`T4.10`): each method's range, low to
    high with its median, the implied EV it states marked against it. */
export function impliedEv(handoff: HandoffView): Figure[] {
  const rows = registerRows(handoff, "CP-1C", "T4.10");
  if (!rows?.length) return [];
  const unitOf = (row: Row) => suffixOf(row["Implied EV"]) ?? suffixOf(row["Median"]);
  const marks = rangeMarks(rows[0]!, IMPLIED_STATISTICS);
  const base = { key: "implied-ev", table: "T4.10", title: "Implied enterprise value by method" };
  return perGroup(rows, base, bySuffix(unitOf), marks, (entries, head) => ({
    ...head,
    kind: "range",
    summary: `Implied EV as served: ${entries
      .map(({ row }) => `${text(row, "Method")} ${served(row["Implied EV"])}`)
      .join("; ")}.`,
    ranges: entries.map(rangeOf(IMPLIED_STATISTICS, "Method")),
    markerLabel: "Implied EV",
    categoryLabel: "Method",
    sourceOf: (selection) => {
      const row = pickedRow(entries, selection);
      return row
        ? stated(row, [
            "Multiple Source",
            "Multiple Value",
            "Borrower Metric",
            "Period",
            "Calc Status",
          ])
        : null;
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

/** A step as a summary says it: its label and its value as served, else
    n/a and why. */
const said = (step: WaterfallStep) =>
  `${step.label} ${step.value === null ? `n/a (${step.reason})` : formatDecimal(step.value)}`;

/** A waterfall figure of `steps`; a pressed step's source is the columns
    `rowOf` its key states. Past `MAX_MARKS` it is stated, not drawn. */
function waterfallFigure(
  head: Omit<WaterfallFigure, "kind" | "steps" | "sourceOf">,
  steps: WaterfallStep[],
  rowOf: (key: string) => Row | undefined,
  columns: readonly string[],
): Figure {
  const marks = bridgeOf(steps).length;
  if (marks > MAX_MARKS) return oversized(head.key, head.table, head.title, marks);
  // An unreconciled residual is the chart's own: no row stands behind it.
  const keys = new Set(steps.map((step) => step.key));
  return {
    ...head,
    kind: "waterfall",
    steps,
    sourceOf: (selection) => {
      const row = keys.has(selection.series) ? rowOf(selection.series) : undefined;
      return row ? stated(row, columns) : null;
    },
  };
}

/** A change drawn as a decrease of the magnitude served, its note saying
    so; a cell with no figure is a gap, as served. */
function decrease(cell: Cell | undefined, step: Omit<WaterfallStep, "value">, what: string) {
  if (cell?.value == null) return { ...step, ...datum(cell) };
  const note = `served ${formatDecimal(cell.value)}, ${what}`;
  return { ...step, value: negatedMagnitude(cell.value), note };
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
  // Only a total may be named as the bridge's end: a last change with no
  // running level of its own is said to state none.
  const [first, end] = [steps[0]!, steps.at(-1)!];
  const level = spec.cumulative.charAt(0).toLowerCase() + spec.cumulative.slice(1);
  const summary =
    steps.length === 1
      ? `${said(first)}, as served.`
      : end.kind === "total"
        ? `${said(first)} to ${said(end)}, as served.`
        : `${said(first)}; the last change, ${end.label}, states no ${level}.`;
  const used = new Set(steps.map((step) => step.color));
  const statuses = spec.status ? STATUSES.filter(({ color }) => used.has(color)) : undefined;
  const head = { key: spec.key, table: spec.register, title: spec.title, summary };
  return [
    waterfallFigure(
      { ...head, ...(statuses ? { statuses } : {}) },
      steps,
      (key) => (key === "closing" ? last : rows[Number(key)]),
      ["Basis", "Evidence ID"],
    ),
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

/** CP-1D's adjusted debt bridge (`T1E.3`): reported to adjusted debt, each
    adjustment as served; the register states no status. */
export function adjustedDebtBridge(handoff: HandoffView): Figure[] {
  return bridgeFigure(handoff, {
    module: "CP-1D",
    register: "T1E.3",
    cumulative: "Cumulative Adjusted Debt",
    key: "adjusted-debt-bridge",
    title: "Adjusted debt bridge",
  });
}

// CP-2D's stated totals and the uses its method subtracts
// (REF_CP-2D_STEPS.md step 05, instruction 5; liquidity_bridge.py), as a
// `Bridge Item` starts, trimmed and casefolded.
const LIQUIDITY_TOTALS = ["beginning accessible liquidity", "ending accessible liquidity"] as const;
const LIQUIDITY_USES = [
  "cash interest",
  "cash taxes",
  "mandatory capex",
  "debt amortization",
  "debt amortisation",
  "other cash uses",
];

/** CP-2D's 12-month liquidity bridge (`T2E.5`): beginning to ending
    accessible liquidity, each use drawn as its magnitude subtracted. Rows
    before the beginning total bridge from zero. */
export function liquidityBridge(handoff: HandoffView): Figure[] {
  const rows = registerRows(handoff, "CP-2D", "T2E.5");
  if (!rows?.length) return [];
  const steps = rows.map((row, index): WaterfallStep => {
    const label = text(row, "Bridge Item").trim();
    const item = label.toLowerCase();
    const base = { key: `${index}`, label, origin: "model" as const };
    if (LIQUIDITY_TOTALS.some((total) => item.startsWith(total))) {
      return { ...base, kind: "total", ...datum(row["Amount"]) };
    }
    if (LIQUIDITY_USES.some((use) => item.startsWith(use))) {
      return decrease(row["Amount"], { ...base, kind: "delta" }, "a use the method subtracts");
    }
    return { ...base, kind: "delta", ...datum(row["Amount"]) };
  });
  const total = (which: string) =>
    steps.filter((step) => step.kind === "total" && step.label.toLowerCase().startsWith(which));
  const begin = total(LIQUIDITY_TOTALS[0])[0];
  const end = total(LIQUIDITY_TOTALS[1]).at(-1);
  const summary = `${begin ? said(begin) : "No beginning accessible liquidity stated"} to ${
    end ? said(end) : "no ending accessible liquidity stated"
  }, as served.`;
  const head = { key: "liquidity-bridge", table: "T2E.5", title: "Liquidity bridge, 12 months" };
  return [
    waterfallFigure({ ...head, summary }, steps, (key) => rows[Number(key)], [
      "Source / Calculation",
      "Status",
      "Source Trace",
    ]),
  ];
}

/** The fulcrum `T4E.6` states for `scenario`: its `fulcrum class/range` on
    the first row whose `scenario/EV range` starts with the scenario. */
function fulcrumOf(fulcrums: readonly Row[], scenario: string): string | undefined {
  const key = scenario.trim().toLowerCase();
  if (!key) return undefined;
  const row = fulcrums.find((fulcrum) =>
    text(fulcrum, "scenario/EV range").trim().toLowerCase().startsWith(key),
  );
  return row ? text(row, "fulcrum class/range").trim() || undefined : undefined;
}

/** The row whose `priority claim` starts the fulcrum's text; the longest
    such claim, so "Senior" never takes "Senior notes"'s mark. */
function fulcrumClaim(group: readonly Entry[], fulcrum: string): number | undefined {
  const named = fulcrum.toLowerCase();
  let best: Entry | undefined;
  for (const entry of group) {
    const claim = text(entry.row, "priority claim").trim().toLowerCase();
    const length = best ? text(best.row, "priority claim").trim().length : 0;
    if (claim && named.startsWith(claim) && claim.length > length) best = entry;
  }
  return best?.index;
}

/** CP-4C's priority waterfall (`T4E.5`): per scenario and entity, the
    available value, each claim's allocation drawn as a decrease, and the
    residual, the fulcrum `T4E.6` names marked. */
export function valueAllocation(handoff: HandoffView): Figure[] {
  const rows = registerRows(handoff, "CP-4C", "T4E.5");
  if (!rows?.length) return [];
  const fulcrums = registerRows(handoff, "CP-4C", "T4E.6") ?? [];
  const entries = rows.map((row, index) => ({ row, index }));
  const groups = [
    ...groupBy(entries, ({ row }) => pair(text(row, "scenario"), text(row, "entity"))).values(),
  ];
  const entities = groupBy(groups, (group) => text(group[0]!.row, "scenario"));
  return groups.map((group, n) => {
    const [first, last] = [group[0]!.row, group.at(-1)!.row];
    const scenario = text(first, "scenario");
    const entity = entities.get(scenario)!.length > 1 ? `, ${text(first, "entity")}` : "";
    const fulcrum = fulcrumOf(fulcrums, scenario);
    const marked = fulcrum ? fulcrumClaim(group, fulcrum) : undefined;
    const steps: WaterfallStep[] = [
      {
        key: "opening",
        label: "Available value",
        kind: "total",
        origin: "model",
        ...datum(first["available value"]),
      },
      ...group.map(({ row, index }) =>
        decrease(
          row["allocation"],
          {
            key: `${index}`,
            label: `${text(row, "priority claim").trim()}${index === marked ? " (fulcrum)" : ""}`,
            kind: "delta",
            origin: "model",
          },
          "an allocation of the available value",
        ),
      ),
      {
        key: "closing",
        label: "Residual",
        kind: "total",
        origin: "model",
        ...datum(last["residual"]),
      },
    ];
    const named = fulcrum ? `fulcrum: ${fulcrum}.` : "T4E.6 names no fulcrum for this scenario.";
    const summary = `${said(steps[0]!)} to ${said(steps.at(-1)!)}, as served; ${named}`;
    const head = {
      key: `value-allocation-${n}`,
      table: "T4E.5",
      title: `Value allocation, ${scenario}${entity}`,
      summary,
    };
    const rowOf = (key: string) =>
      key === "opening" ? first : key === "closing" ? last : rows[Number(key)];
    return waterfallFigure(head, steps, rowOf, ["legal evidence ID"]);
  });
}

/** Every figure a handoff's registers support, in reading order. A handoff
    is one module's, so only its own module's figures draw for it. */
export function registerFigures(handoff: HandoffView): Figure[] {
  return [
    ...covenantHeadroom(handoff),
    ...peerRanges(handoff),
    ...impliedEv(handoff),
    ...ebitdaQuality(handoff),
    ...adjustedDebtBridge(handoff),
    ...liquidityBridge(handoff),
    ...valueAllocation(handoff),
  ];
}

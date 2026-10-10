// A module's figures drawn from the registers its output profile declares
// (N94), located by the host with the bundle's own reader. A register id is
// the module's own, not the bundle's (CP-1, CP-1B and CP-1C each declare a
// `T4.6`), so a register is read only for the module that serves it. Like the
// tagged tables, every value is the model's, printed exactly as served; a
// float only places a mark. Rows of one unit share a figure, so no axis
// holds a multiple beside a percentage, and amounts of one currency share
// one, so no axis holds a dollar beside a euro.
import {
  formatDecimal,
  type ChartColor,
  type ChartSelection,
  type ChartSeries,
  type Datum,
  type RangeRow,
  type WaterfallStep,
} from "@/charts";
import { bridgeOf } from "@/charts/bridge";
import type { HandoffView } from "@/wire/v1";
import {
  MAX_MARKS,
  caseRank,
  datum,
  groupBy,
  negatedMagnitude,
  oversized,
  pair,
  stackFigure,
  sumOf,
  text,
  unique,
  wallSummary,
  yearOf,
  type Cell,
  type Figure,
  type Row,
  type StackSpec,
  type Wall,
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

/** How a register's rows split into figures: a row's groups, each once
    (none: the figure whose key and title carry no suffix), the suffix a
    group adds to its figure's key and title, and the figure's unit. */
interface Grouping<G extends string> {
  of: (row: Row) => readonly (G | undefined)[];
  key: (group: G) => string;
  title: (group: G) => string;
  unit: (group: G) => string | undefined;
}

const UNIT_KEY: Record<Unit, string> = { x: "x", "%": "percent" };

const BY_UNIT = {
  key: (unit: Unit) => UNIT_KEY[unit],
  title: (unit: Unit) => unit,
  unit: (unit: Unit) => unit,
};

/** Rows grouped by the unit their figure is written in, `x` or `%`. */
const bySuffix = (unitOf: (row: Row) => Unit | undefined): Grouping<Unit> => ({
  of: (row) => [unitOf(row)],
  ...BY_UNIT,
});

/** Rows grouped by the units their `columns`' figures are written in. A row
    whose cells agree joins that unit's figure; one whose cells disagree
    joins each of its units' figures, a cell drawn only in its own unit's and
    a gap naming it in the others (`inUnit`): no unit is invented and no axis
    holds two. A row stating no figure joins the figure of no unit. */
const byCellUnits = (columns: readonly string[]): Grouping<Unit> => ({
  of: (row) => {
    const units = columns.filter((column) => row[column]?.value != null);
    return units.length ? [...new Set(units.map((column) => suffixOf(row[column])))] : [undefined];
  },
  ...BY_UNIT,
});

/** A cell as the figure of unit `at` draws it: its figure where written in
    `at`, else a gap naming it, drawn in its own unit's figure. */
function inUnit(cell: Cell | undefined, at: Unit | undefined): Datum {
  if (cell?.value != null && suffixOf(cell) !== at) {
    return { value: null, reason: `${cell.text}, drawn in its unit's figure` };
  }
  return datum(cell);
}

/** Rows grouped by their `Currency`, as written: one currency's amounts
    never share an axis with another's. */
const BY_CURRENCY: Grouping<string> = {
  of: (row) => [text(row, "Currency") || undefined],
  key: (currency) => currency,
  title: (currency) => currency,
  unit: (currency) => currency,
};

/** A register's rows split by `grouping`, in the order each group first
    appears, each with its figure's head. */
function groupsOf<G extends string>(
  rows: readonly Row[],
  base: { key: string; table: string; title: string },
  grouping: Grouping<G>,
): { entries: Entry[]; head: Head; at: G | undefined }[] {
  const groups = new Map<G | undefined, Entry[]>();
  rows.forEach((row, index) => {
    for (const at of grouping.of(row)) {
      const group = groups.get(at);
      if (group) group.push({ row, index });
      else groups.set(at, [{ row, index }]);
    }
  });
  return [...groups].map(([at, group]) => {
    const head = {
      key: at ? `${base.key}-${grouping.key(at)}` : base.key,
      table: base.table,
      title: at ? `${base.title}, ${grouping.title(at)}` : base.title,
      unit: at ? grouping.unit(at) : undefined,
    };
    return { entries: group, head, at };
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
  const summary =
    steps.length === 1
      ? `${said(first)}, as served.`
      : end.kind === "total"
        ? `${said(first)} to ${said(end)}, as served.`
        : `${said(first)}; the last change, ${end.label}, states no ${spec.cumulative}.`;
  // A gap is drawn with no colour: only a drawn step's colour is listed.
  const used = new Set(steps.filter((step) => step.value !== null).map((step) => step.color));
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

/** A title and its parts, a blank part left out: "Value allocation, Base". */
const titled = (title: string, ...parts: readonly string[]) =>
  [title, ...parts.filter((part) => part.trim())].join(", ");

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
  let best: { index: number; claim: string } | undefined;
  for (const { row, index } of group) {
    const claim = text(row, "priority claim").trim().toLowerCase();
    if (claim && named.startsWith(claim) && claim.length > (best?.claim.length ?? 0)) {
      best = { index, claim };
    }
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
    const entity = entities.get(scenario)!.length > 1 ? text(first, "entity") : "";
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
      title: titled("Value allocation", scenario, entity),
      summary,
    };
    const rowOf = (key: string) =>
      key === "opening" ? first : key === "closing" ? last : rows[Number(key)];
    return waterfallFigure(head, steps, rowOf, ["legal evidence ID"]);
  });
}

/** A register stacked by its columns: what each row adds where, and how a
    pressed segment names each row it sums. */
interface StackColumns {
  category: string;
  series: string;
  amount: string;
  /** The column naming a row in a segment's source. */
  name: string;
  /** The columns a segment's source states for each row. */
  source: readonly string[];
}

/** A stack's readers for `columns`. A segment's source names each row it
    sums with the columns that row states; a segment of several rows says it
    is their sum, and how many of them state no amount. */
function byColumns(columns: StackColumns): Omit<StackSpec, "head"> {
  const amountOf = (row: Row) => row[columns.amount]?.value;
  return {
    categoryOf: (row) => text(row, columns.category),
    seriesOf: (row) => text(row, columns.series),
    amountOf,
    sourceOf: (rows) => {
      const lines = rows.map((row) => {
        const details = stated(row, columns.source);
        const name = text(row, columns.name);
        return name && details ? `${name} (${details})` : name || details || "";
      });
      if (rows.length === 1) return lines[0] || null;
      const unstated = rows.filter((row) => amountOf(row) == null).length;
      const short = unstated ? `, ${unstated} stating no amount` : "";
      return `Sum of ${rows.length} rows${short}: ${lines.filter(Boolean).join("; ")}`;
    },
  };
}

/** A register stack's summary: the exact sum of its `column`, labelled as a
    sum, and how many rows state none. */
function summed(rows: readonly Row[], column: string, unit: string | undefined): string {
  const total = sumOf(rows.map((row) => row[column]?.value));
  if (total.value === null) return `None of ${rows.length} rows states a figure for ${column}.`;
  const known = rows.filter((row) => row[column]?.value != null).length;
  const over = total.complete
    ? `${rows.length} rows`
    : `the ${known} of ${rows.length} rows that state one`;
  return `${column}, summed over ${over}: ${formatDecimal(total.value)}${unit ? ` ${unit}` : ""}.`;
}

/** CP-2D's beginning liquidity (`T2E.2`): each component's source-supported
    amount, stacked by how accessible it is. */
export function liquiditySources(handoff: HandoffView): Figure[] {
  const rows = registerRows(handoff, "CP-2D", "T2E.2");
  if (!rows?.length) return [];
  const amount = "Source-Supported Amount";
  const head = { key: "liquidity-sources", table: "T2E.2", title: "Liquidity by accessibility" };
  return [
    stackFigure(rows, {
      head: {
        ...head,
        summary: summed(rows, amount, undefined),
        categoryLabel: "Accessibility Status",
      },
      ...byColumns({
        category: "Accessibility Status",
        series: "Liquidity Component",
        amount,
        name: "Liquidity Component",
        source: ["Source Trace", "Limitation / Restriction"],
      }),
    }),
  ];
}

/** CP-2D's mandatory cash uses (`T2E.3`): each timing's uses, mandatory
    stacked against discretionary. */
export function cashUses(handoff: HandoffView): Figure[] {
  const rows = registerRows(handoff, "CP-2D", "T2E.3");
  if (!rows?.length) return [];
  const head = { key: "cash-uses", table: "T2E.3", title: "Cash uses by timing" };
  return [
    stackFigure(rows, {
      head: { ...head, summary: summed(rows, "Amount", undefined), categoryLabel: "Timing" },
      ...byColumns({
        category: "Timing",
        series: "Mandatory / Discretionary",
        amount: "Amount",
        name: "Cash Use",
        source: ["Source Trace"],
      }),
    }),
  ];
}

/** CP-2E's debt and rate exposure (`T2F.2`): per currency, fixed against
    floating debt, stacked by instrument. */
export function rateMix(handoff: HandoffView): Figure[] {
  const rows = registerRows(handoff, "CP-2E", "T2F.2");
  if (!rows?.length) return [];
  const base = { key: "rate-mix", table: "T2F.2", title: "Fixed and floating debt" };
  return groupsOf(rows, base, BY_CURRENCY).map(({ entries, head }) => {
    const group = entries.map((entry) => entry.row);
    return stackFigure(group, {
      head: {
        ...head,
        summary: summed(group, "Amount", head.unit),
        categoryLabel: "Fixed / Floating",
      },
      ...byColumns({
        category: "Fixed / Floating",
        series: "Debt Instrument",
        amount: "Amount",
        name: "Debt Instrument",
        source: ["Base Rate", "Margin / Coupon", "Hedge Status", "Source Trace"],
      }),
    });
  });
}

/** CP-3C's maturity wall (`T3D.2`): per currency, the amount falling due
    each year, stacked by seniority, said as CP-1's maturity wall is. */
export function refinancingWall(handoff: HandoffView): Figure[] {
  const rows = registerRows(handoff, "CP-3C", "T3D.2");
  if (!rows?.length) return [];
  const wall: Wall = {
    amountOf: (row) => row["Amount"]?.value,
    dateOf: (row) => text(row, "Maturity Date"),
    nameOf: (row) => text(row, "Instrument"),
    noun: "instruments",
    word: "amount",
  };
  const base = { key: "refinancing-wall", table: "T3D.2", title: "Maturities by seniority" };
  return groupsOf(rows, base, BY_CURRENCY).map(({ entries, head }) => {
    const group = entries.map((entry) => entry.row);
    return stackFigure(group, {
      head: { ...head, summary: wallSummary(group, wall, head.unit), categoryLabel: "Year" },
      ...byColumns({
        category: "Maturity Date",
        series: "Seniority / Lien",
        amount: "Amount",
        name: "Instrument",
        source: ["Source Trace"],
      }),
      // A category is its maturity's year, not the date `byColumns` reads.
      categoryOf: (row) => yearOf(wall.dateOf(row)),
      sorted: true,
    });
  });
}

/** A series read from a register column, keyed and labelled. */
interface ColumnSeries {
  key: string;
  label: string;
  column: string;
}

/** A series per column, a datum per entry as `read` draws its cell. */
const columnSeries = (
  entries: readonly Entry[],
  columns: readonly ColumnSeries[],
  read: (cell: Cell | undefined) => Datum,
): ChartSeries[] =>
  columns.map(({ key, label, column }) => ({
    key,
    label,
    origin: "model",
    data: entries.map(({ row }) => read(row[column])),
  }));

/** "Exposure as served, Base / Stress: Senior 100 / n/a (TBD); …": each
    category's values, as drawn. */
function seriesSummary(noun: string, categories: readonly string[], series: ChartSeries[]) {
  const say = (value: Datum | undefined) =>
    value?.value != null ? formatDecimal(value.value) : `n/a (${value?.reason ?? "not stated"})`;
  const rows = categories.map(
    (category, index) => `${category} ${series.map((one) => say(one.data[index])).join(" / ")}`,
  );
  return `${noun} as served, ${series.map((one) => one.label).join(" / ")}: ${rows.join("; ")}.`;
}

/** How a register is drawn a series per column: as grouped bars or a stack,
    the column naming each row's category, the series, what the summary calls
    the values, and the columns a mark's source states. */
interface ColumnFigure {
  kind: "bars" | "stack";
  category: string;
  columns: readonly ColumnSeries[];
  noun: string;
  source: readonly string[];
}

/** A figure of `entries`, a category a row and a series a column, every
    value as served; past `MAX_MARKS` it is stated, not drawn. */
function columnFigure(
  entries: readonly Entry[],
  head: Head,
  spec: ColumnFigure,
  read: (cell: Cell | undefined) => Datum,
): Figure {
  const marks = entries.length * spec.columns.length;
  if (marks > MAX_MARKS) return oversized(head.key, head.table, head.title, marks);
  const categories = entries.map(({ row }) => text(row, spec.category));
  const series = columnSeries(entries, spec.columns, read);
  const sourceOf = (selection: ChartSelection) => {
    const row = pickedRow(entries, selection);
    return row ? stated(row, spec.source) : null;
  };
  const summary = seriesSummary(spec.noun, categories, series);
  const figure = { ...head, categories, series, summary, sourceOf, categoryLabel: spec.category };
  return { ...figure, kind: spec.kind };
}

/** A register drawn a series per column, a figure per unit its `columns`'
    cells are written in; the figure of no such unit is in `plain`. */
function byUnitFigures(
  rows: readonly Row[],
  base: Omit<Head, "unit">,
  spec: ColumnFigure,
  plain?: string,
) {
  const grouping = byCellUnits(spec.columns.map(({ column }) => column));
  return groupsOf(rows, base, grouping).map(({ entries, head, at }) =>
    columnFigure(entries, at ? head : { ...head, unit: plain }, spec, (cell) => inUnit(cell, at)),
  );
}

/** CP-3C's exposure by case (`T3D.8`): each creditor class's base, stress
    and LME exposure, side by side. */
export function lmeExposure(handoff: HandoffView): Figure[] {
  const rows = registerRows(handoff, "CP-3C", "T3D.8");
  if (!rows?.length) return [];
  return byUnitFigures(
    rows,
    { key: "lme-exposure", table: "T3D.8", title: "Exposure by case" },
    {
      kind: "bars",
      category: "Creditor Class",
      columns: [
        { key: "base", label: "Base", column: "Exposure: Base Case" },
        { key: "stress", label: "Stress", column: "Exposure: Stress Case" },
        { key: "lme", label: "LME", column: "Exposure: LME Case" },
      ],
      noun: "Exposure",
      source: ["Recovery Implication", "Priming / Subordination Risk", "Source Trace"],
    },
  );
}

/** CP-4's basket capacity (`T4C.5`): each basket's usage stacked on its
    remaining capacity. Its `Estimated Capacity` is named in a mark's source,
    never drawn, nor checked against the two. */
export function basketCapacity(handoff: HandoffView): Figure[] {
  const rows = registerRows(handoff, "CP-4", "T4C.5");
  if (!rows?.length) return [];
  return byUnitFigures(
    rows,
    { key: "basket-capacity", table: "T4C.5", title: "Baskets, used and remaining" },
    {
      kind: "stack",
      category: "Basket / Test",
      columns: [
        { key: "usage", label: "Usage", column: "Usage" },
        { key: "remaining", label: "Remaining Capacity", column: "Remaining Capacity" },
      ],
      noun: "Baskets",
      source: ["Estimated Capacity", "Status", "Severity", "Evidence ID"],
    },
  );
}

/** CP-4C's recovery by class (`T4E.7`): per scenario and currency, each
    class's allowed claim beside its total recovery, a cell written in `x` or
    `%` drawn in its own unit's figure. The packed
    `cash/debt/equity/warrant value` holds several figures the bundle's
    reader cannot split (N192): a mark's source states it, nothing draws it.
    CP-4C's `T4E.2` draws nothing for the same reason: its one amount column,
    `principal/accrued/PIK`, packs three. */
export function recoveryByClass(handoff: HandoffView): Figure[] {
  const rows = registerRows(handoff, "CP-4C", "T4E.7");
  if (!rows?.length) return [];
  const entries = rows.map((row, index) => ({ row, index }));
  const groups = [
    ...groupBy(entries, ({ row }) => pair(text(row, "scenario"), text(row, "currency"))).values(),
  ];
  const currencies = groupBy(groups, (group) => text(group[0]!.row, "scenario"));
  return groups.flatMap((group, n) => {
    const [scenario, currency] = [text(group[0]!.row, "scenario"), text(group[0]!.row, "currency")];
    const named = currencies.get(scenario)!.length > 1 ? currency : "";
    const base = {
      key: `recovery-by-class-${n}`,
      table: "T4E.7",
      title: titled("Recovery by class", scenario, named),
    };
    const spec: ColumnFigure = {
      kind: "bars",
      category: "class/instrument",
      columns: [
        { key: "claim", label: "allowed claim", column: "allowed claim" },
        { key: "recovery", label: "total recovery", column: "total recovery" },
      ],
      noun: "Recovery",
      source: ["timing", "cash/debt/equity/warrant value"],
    };
    const rows = group.map(({ row }) => row);
    return byUnitFigures(rows, base, spec, currency || undefined);
  });
}

/** A CP-2G register of a row a period and case, drawn a line a case. */
interface CaseLines {
  register: string;
  key: string;
  metrics: readonly string[];
  /** The column a point's source states. */
  source: string;
}

/** A metric as a figure's key part: "gross/net leverage" is "gross-net-leverage". */
const slug = (metric: string) => metric.toLowerCase().replace(/[^a-z0-9]+/g, "-");

/** A CP-2G register's cases as lines over its periods, a figure a metric and
    a unit its cells are written in: periods in the order they first appear,
    a line a case (BASE, then DOWNSIDE, then the rest), every value as
    served. A cell in another unit is a gap naming it, drawn in its own
    unit's figure; a cell the host read no figure from is a gap carrying its
    text. Past `MAX_MARKS` a figure is stated, not drawn. */
function caseLines(handoff: HandoffView, spec: CaseLines): Figure[] {
  const rows = registerRows(handoff, "CP-2G", spec.register);
  if (!rows?.length) return [];
  const caseOf = (row: Row) => text(row, "case").trim();
  const periods = unique(rows.map((row) => text(row, "period")));
  const cases = unique(rows.map(caseOf)).sort((a, b) => caseRank(a) - caseRank(b));
  const cells = groupBy(rows, (row) => pair(caseOf(row), text(row, "period")));
  const rowAt = (kase: string, period: string) => cells.get(pair(kase, period))?.[0];
  const marks = cases.length * periods.length;
  return spec.metrics.flatMap((metric) => {
    const label = `${metric.charAt(0).toUpperCase()}${metric.slice(1)}`;
    const [key, title] = [`${spec.key}-${slug(metric)}`, `${label}, base and downside`];
    const units = [
      ...new Set(
        rows.filter((row) => row[metric]?.value != null).map((row) => suffixOf(row[metric])),
      ),
    ];
    const heads =
      units.length > 1
        ? units.map((unit) => ({
            key: unit ? `${key}-${UNIT_KEY[unit]}` : key,
            title: unit ? `${title}, ${unit}` : title,
            unit,
          }))
        : [{ key, title, unit: units[0] }];
    return heads.map((head): Figure => {
      if (marks > MAX_MARKS) return oversized(head.key, spec.register, head.title, marks);
      const series = cases.map((kase) => ({
        key: kase,
        label: kase,
        origin: "model" as const,
        data: periods.map((period) => inUnit(rowAt(kase, period)?.[metric], head.unit)),
      }));
      return {
        ...head,
        table: spec.register,
        kind: "line",
        summary: seriesSummary(label, periods, series),
        categories: periods,
        series,
        sourceOf: (selection) => {
          const row = rowAt(selection.series, selection.category);
          return row ? stated(row, [spec.source]) : null;
        },
      };
    });
  });
}

/** CP-2G's forecast (`T2H.4`): revenue, EBITDA and FCF, base against downside. */
export function forecastCases(handoff: HandoffView): Figure[] {
  return caseLines(handoff, {
    register: "T2H.4",
    key: "forecast-cases",
    metrics: ["revenue", "EBITDA", "FCF"],
    source: "evidence/assumption IDs",
  });
}

/** CP-2G's credit path (`T2H.6`): leverage, coverage and FCF/debt, base
    against downside. A leverage cell packing gross and net (`4.2x / 3.9x`)
    is a gap carrying its text: the host reads no figure from it (N192). */
export function creditPath(handoff: HandoffView): Figure[] {
  return caseLines(handoff, {
    register: "T2H.6",
    key: "credit-path",
    metrics: ["gross/net leverage", "coverage", "FCF/debt"],
    source: "definition IDs",
  });
}

/** Every figure a handoff's registers support, in reading order. A handoff
    is one module's, so only its own module's figures draw for it. */
export function registerFigures(handoff: HandoffView): Figure[] {
  return [
    ...covenantHeadroom(handoff),
    ...basketCapacity(handoff),
    ...peerRanges(handoff),
    ...impliedEv(handoff),
    ...ebitdaQuality(handoff),
    ...adjustedDebtBridge(handoff),
    ...liquiditySources(handoff),
    ...cashUses(handoff),
    ...liquidityBridge(handoff),
    ...forecastCases(handoff),
    ...creditPath(handoff),
    ...rateMix(handoff),
    ...refinancingWall(handoff),
    ...lmeExposure(handoff),
    ...valueAllocation(handoff),
    ...recoveryByClass(handoff),
  ];
}

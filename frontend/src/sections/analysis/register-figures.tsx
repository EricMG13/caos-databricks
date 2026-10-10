// A module's figures drawn from the registers its output profile declares
// (N94), located by the host with the bundle's own reader. A register id is
// the module's own, not the bundle's (CP-1, CP-1B and CP-1C each declare a
// `T4.6`), so a register is read only for the module that serves it. Like the
// tagged tables, every value is the model's, printed exactly as served; a
// float only places a mark. Rows of one unit share a figure, so no axis
// holds a multiple beside a percentage.
import { formatDecimal, type ChartSelection } from "@/charts";
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

/** Every figure a handoff's registers support, in reading order. A handoff
    is one module's, so at most one of these draws for it. */
export function registerFigures(handoff: HandoffView): Figure[] {
  return [...covenantHeadroom(handoff)];
}

// What a module's figures share, whether drawn from its tagged tables
// (`figures.tsx`) or its declared registers (`register-figures.tsx`): the
// figure each draws, the served cell and its readers, exact sums, the bounds
// on how much is drawn, and the stack and maturity wall both build. A leaf:
// it imports neither.
import type {
  BulletRow,
  ChartColor,
  ChartSelection,
  ChartSeries,
  Datum,
  DumbbellRow,
  Orientation,
  RangeRow,
  RiskEvent,
  ScatterPoint,
  WaterfallStep,
} from "@/charts";
import { formatDecimal, fromScaled, placesOf, toScaled } from "@/charts/decimal";
import type { HandoffView } from "@/wire/v1";

/** A served cell, a table's or a register's: its text as written and the
    host's exact figure, or null. */
export type Cell = HandoffView["tables"][number]["rows"][number][number];
/** A row keyed by column name. */
export type Row = Record<string, Cell | undefined>;

/** A cell's text as written, or "" where the row has no such column. */
export const text = (row: Row, column: string) => row[column]?.text ?? "";
/** A cell's figure as served, or a gap whose reason is the cell's text. */
export const datum = (cell: Cell | undefined): Datum =>
  cell?.value != null
    ? { value: cell.value }
    : { value: null, reason: cell?.text ? cell.text : "not stated" };

/** The exact sum of a set of values that may include unknown members
    (R24-13): `value` sums only the known ones (null when none are known),
    and `complete` says whether every member was known -- a caller states
    this partial-sum distinction rather than let an aggregate stand in
    silently for a total that may be missing components. */
export interface PartialSum {
  value: string | null;
  complete: boolean;
}

/** The exact sum of decimal strings, and whether every input was known. */
export function sumOf(values: readonly (string | null | undefined)[]): PartialSum {
  const known = values.filter((value): value is string => typeof value === "string");
  const complete = known.length === values.length;
  if (known.length === 0) return { value: null, complete };
  const places = Math.max(...known.map(placesOf));
  return {
    value: fromScaled(
      known.reduce((sum, value) => sum + toScaled(value, places), 0n),
      places,
    ),
    complete,
  };
}

/** An exact decimal's magnitude negated, by string work alone: "800" and
    "-800" are both "-800", and a zero stays unsigned ("-0.00" is "0.00"). */
export function negatedMagnitude(value: string): string {
  const magnitude = value.startsWith("-") ? value.slice(1) : value;
  return /[1-9]/.test(magnitude) ? `-${magnitude}` : magnitude;
}

/** Rows grouped by `key`, in table order, built once: a `find` or `filter`
    per mark made the figures cubic in a table's rows. */
export function groupBy<T>(rows: readonly T[], key: (row: T) => string): Map<string, T[]> {
  const groups = new Map<string, T[]>();
  for (const row of rows) {
    const k = key(row);
    const group = groups.get(k);
    if (group) group.push(row);
    else groups.set(k, [row]);
  }
  return groups;
}
/** Two cells as one key; the separator cannot occur in a served cell's text. */
export const pair = (a: string, b: string) => `${a}\u0000${b}`;
/** Each value once, in the order it first appears. */
export const unique = (values: readonly string[]) => [...new Set(values)];
/** A maturity's year: the four digits its date starts with, else "Undated",
    which sorts after every year. */
export const yearOf = (date: string) => /^\d{4}/.exec(date)?.[0] ?? "Undated";

const CASE_ORDER = ["BASE", "DOWNSIDE"];
/** A forecast case's place among its lines: BASE, then DOWNSIDE, then any
    case the bundle does not name, never before BASE; read trimmed and
    case-insensitive. */
export function caseRank(kase: string): number {
  const at = CASE_ORDER.indexOf(kase.trim().toUpperCase());
  return at < 0 ? CASE_ORDER.length : at;
}

/** What every figure has, whatever draws it. */
interface FigureBase {
  key: string;
  table: string;
  title: string;
  summary: string;
  unit?: string;
  /** Where the model says a mark's figure came from: its source locator. */
  sourceOf: (selection: ChartSelection) => string | null;
  /** Past `MAX_MARKS`: stated, not drawn. */
  oversized?: boolean;
  /** What a mark's figure is where this host computed it, not served: "a
      count of the model's rows". Said in place of the mark's origin. */
  computed?: string;
  /** The unit said of a value of exactly 1: "issue" beside "issues". */
  unitOne?: string;
}

/** Bars stacked by series over categories. */
export interface StackFigure extends FigureBase {
  kind: "stack";
  categories: string[];
  series: ChartSeries[];
  /** What the categories are, heading the table twin. */
  categoryLabel?: string;
}

/** A bar per series in each category, grouped side by side. */
export interface BarsFigure extends FigureBase {
  kind: "bars";
  categories: string[];
  series: ChartSeries[];
  /** Which way the bars run; upright where unsaid. */
  orientation?: Orientation;
  /** What the categories are, heading the table twin. */
  categoryLabel?: string;
}

/** A line per series over categories. */
export interface LineFigure extends FigureBase {
  kind: "line";
  categories: string[];
  series: ChartSeries[];
}

/** One series' bars above or below zero. */
export interface DivergingFigure extends FigureBase {
  kind: "diverging";
  categories: string[];
  series: [ChartSeries];
}

/** A bridge's steps, in bridge order. */
export interface WaterfallFigure extends FigureBase {
  kind: "waterfall";
  steps: WaterfallStep[];
  /** What the steps' colours stand for, where they wear a status's. */
  statuses?: { color: ChartColor; label: string }[];
}

/** A bullet chart's tests, one a row. */
export interface BulletFigure extends FigureBase {
  kind: "bullet";
  bullets: BulletRow[];
  /** What the rows are, heading the table twin. */
  categoryLabel?: string;
}

/** A range strip's rows, one a metric. */
export interface RangeFigure extends FigureBase {
  kind: "range";
  ranges: RangeRow[];
  /** What the dot is: "Borrower value", "Implied EV". */
  markerLabel: string;
  /** What the rows are, heading the table twin. */
  categoryLabel?: string;
}

/** A dumbbell's rows, one a metric: two of its values, joined. */
export interface DumbbellFigure extends FigureBase {
  kind: "dumbbell";
  dumbbells: DumbbellRow[];
  /** What each end is: "Expected", "Realized". */
  fromLabel: string;
  toLabel: string;
  /** What the rows are, heading the table twin. */
  categoryLabel?: string;
}

/** A scatter's points, each a value against the date it is served with. */
export interface ScatterFigure extends FigureBase {
  kind: "scatter";
  points: ScatterPoint[];
  /** What the dates are, naming the time axis. */
  xLabel: string;
  /** What the table twin calls the points, their values and their groups. */
  pointLabel?: string;
  valueLabel?: string;
  groupLabel?: string;
}

/** Events by probability and impact, a cell a pair of labels. */
export interface MatrixFigure extends FigureBase {
  kind: "matrix";
  events: RiskEvent[];
}

/** One figure: what it shows, drawn by which chart, from which table. Each
    kind carries its own rows, so a figure without them does not build. */
export type Figure =
  | StackFigure
  | BarsFigure
  | LineFigure
  | DivergingFigure
  | WaterfallFigure
  | BulletFigure
  | RangeFigure
  | DumbbellFigure
  | ScatterFigure
  | MatrixFigure;

/** A figure past this many marks is stated, not drawn, and past this many
    figures a module's are stated too. The tables are model-authored and may
    run to 2,000 rows: a cross product of two of their columns is millions of
    marks, and drawing them froze the tab (security review, F327). */
export const MAX_MARKS = 2_000;
export const MAX_FIGURES = 24;

/** A figure stated, not drawn: past `MAX_MARKS` it would freeze the tab. The
    Figures view says its summary in place of a chart, so it has no rows. */
export function oversized(key: string, table: string, title: string, marks: number): StackFigure {
  return {
    key,
    table,
    kind: "stack",
    title,
    summary: `${marks} marks: too many to draw. The Appendix tab lists every row.`,
    categories: [],
    series: [],
    sourceOf: () => null,
    oversized: true,
  };
}

/** What a stack is built from: each row's category, series and amount. */
export interface StackSpec {
  head: Omit<StackFigure, "kind" | "categories" | "series" | "sourceOf">;
  categoryOf: (row: Row) => string;
  seriesOf: (row: Row) => string;
  amountOf: (row: Row) => string | null | undefined;
  /** Categories sorted (years), else in the order they first appear. */
  sorted?: boolean;
  /** A series' label and colour; by default its key, in the ramp's colour. */
  look?: (series: string) => { label: string; color?: ChartColor };
  /** A segment's source, from every row it sums (never none). */
  sourceOf: (rows: readonly Row[]) => string | null;
}

/** Rows stacked by series over categories, series in the order they first
    appear. A segment is the exact sum of its rows' amounts (`sumOf`): a
    category and series with no row is genuinely zero; one whose every row's
    amount is unstated is unknown, never silently zero. Past `MAX_MARKS` the
    stack is stated, not drawn. */
export function stackFigure(rows: readonly Row[], spec: StackSpec): StackFigure {
  const { head, categoryOf, seriesOf } = spec;
  const categories = unique(rows.map(categoryOf));
  if (spec.sorted) categories.sort();
  const keys = unique(rows.map(seriesOf));
  const marks = keys.length * categories.length;
  if (marks > MAX_MARKS) return oversized(head.key, head.table, head.title, marks);
  const segments = groupBy(rows, (row) => pair(seriesOf(row), categoryOf(row)));
  const segment = (series: string, category: string): Datum => {
    const summed = segments.get(pair(series, category));
    if (!summed) return { value: "0" };
    const sum = sumOf(summed.map(spec.amountOf));
    return sum.value === null ? { value: null, reason: "not stated" } : { value: sum.value };
  };
  return {
    ...head,
    kind: "stack",
    categories,
    series: keys.map((key) => ({
      key,
      ...(spec.look?.(key) ?? { label: key }),
      origin: "model" as const,
      data: categories.map((category) => segment(key, category)),
    })),
    // A segment sums every row of its series and category, so it names each
    // one's stated source, not the first's (rewrite tournament).
    sourceOf: (selection) => {
      const summed = segments.get(pair(selection.series, selection.category));
      return summed ? spec.sourceOf(summed) : null;
    },
  };
}

/** How a maturity wall reads a row, and what it calls its rows. */
export interface Wall {
  amountOf: (row: Row) => string | null | undefined;
  dateOf: (row: Row) => string;
  nameOf: (row: Row) => string;
  /** What one row is called, and several: "facility", "facilities". */
  noun: readonly [string, string];
  /** What the register calls its amount; by default CP-1's "principal". */
  word?: string;
}

/** The row falling due first: the earliest of those whose date has a year,
    else the first by its date's text; `dated` says whether any has a year. */
export function nearestOf(
  rows: readonly Row[],
  dateOf: (row: Row) => string,
): { row: Row; dated: boolean } {
  const dated = rows.filter((row) => yearOf(dateOf(row)) !== "Undated");
  const [row] = [...(dated.length ? dated : rows)].sort((a, b) =>
    dateOf(a).localeCompare(dateOf(b)),
  );
  return { row: row!, dated: dated.length > 0 };
}

/** A maturity wall's summary (CP-1's): its amount summed exactly, said as
    known where some is unstated (R24-13), and the nearest dated maturity,
    chosen whether or not its amount is known. */
export function wallSummary(rows: readonly Row[], wall: Wall, unit: string | undefined): string {
  const values = rows.map(wall.amountOf);
  const total = sumOf(values);
  const unknown = values.filter((value) => value == null).length;
  const [n, word] = [rows.length, wall.word ?? "principal"];
  const noun = wall.noun[n === 1 ? 0 : 1];
  const principal =
    total.value === null
      ? `${word.charAt(0).toUpperCase()}${word.slice(1)} unstated for ${n === 1 ? "the" : "all"} ${n} ${noun}`
      : `${formatDecimal(total.value)}${unit ? ` ${unit}` : ""}${
          total.complete
            ? ` ${word} in ${n} ${noun}`
            : ` known ${word} across ${n - unknown} of ${n} ${noun} (${unknown} unstated)`
        }`;
  const { row, dated } = nearestOf(rows, wall.dateOf);
  return `${principal}${dated ? `; the nearest, ${wall.nameOf(row)}, falls due ${wall.dateOf(row)}` : ""}.`;
}

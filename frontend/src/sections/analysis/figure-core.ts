// What a module's figures share, whether drawn from its tagged tables
// (`figures.tsx`) or its declared registers (`register-figures.tsx`): the
// figure each draws, the served cell and its readers, exact sums and the
// bounds on how much is drawn. A leaf: it imports neither.
import type {
  BulletRow,
  ChartSelection,
  ChartSeries,
  Datum,
  RangeRow,
  WaterfallStep,
} from "@/charts";
import { fromScaled, placesOf, toScaled } from "@/charts/decimal";
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
}

/** Bars stacked by series over categories. */
export interface StackFigure extends FigureBase {
  kind: "stack";
  categories: string[];
  series: ChartSeries[];
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

/** One figure: what it shows, drawn by which chart, from which table. Each
    kind carries its own rows, so a figure without them does not build. */
export type Figure =
  StackFigure | LineFigure | DivergingFigure | WaterfallFigure | BulletFigure | RangeFigure;

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

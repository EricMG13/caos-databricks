// What every series chart shares: the colour a series wears, how a mark is
// named, and the table twin. One copy, so a bar and a line name a value the
// same way.
import { formatDecimal, readDatum } from "./decimal";
import type {
  ChartColor,
  ChartSelection,
  ChartSeries,
  Decimal,
  LegendEntry,
  Origin,
  TableTwin,
} from "./types";

const RAMP: readonly ChartColor[] = ["series-1", "series-2", "series-3", "series-4", "series-5"];

/** The colour a series wears: its own, else its place on the validated ramp.
    Past the fifth no hue is left that stays distinct from its neighbours, so
    a sixth series is neutral: fold the tail into one series instead. */
export function seriesColor(series: Pick<ChartSeries, "color">, index: number): ChartColor {
  return series.color ?? RAMP[index] ?? "neutral";
}

/** The pole a value leans to: `positive` above zero, `negative` below,
    `neutral` at zero or unavailable. Read off the string, never a float. */
export function poleOf(value: Decimal | null): ChartColor {
  if (value === null || !/[1-9]/.test(value)) return "neutral";
  return value.startsWith("-") ? "negative" : "positive";
}

/** The words for an origin, as the Analysis section says them. */
export const ORIGIN_WORD: Record<Origin, string> = {
  host: "host-verified",
  model: "model-authored",
};

/** "3,412.0 USD m": the value as served, grouped, with its unit. */
export function valueText(value: Decimal, unit: string | undefined, signed = false): string {
  const text = formatDecimal(value, signed);
  return unit ? `${text} ${unit}` : text;
}

/** One (series, category) pair, read for drawing. */
export interface Cell {
  series: ChartSeries;
  /** The series' position, which picks its slot in a group. */
  slot: number;
  category: string;
  index: number;
  value: Decimal | null;
  reason: string | null;
  origin: Origin;
  color: ChartColor;
}

/** Every (series, category) pair, series by series. */
export function cellsOf(categories: readonly string[], series: readonly ChartSeries[]): Cell[] {
  return series.flatMap((one, slot) =>
    categories.map((category, index) => {
      const read = readDatum(one.data[index]);
      return {
        series: one,
        slot,
        category,
        index,
        value: read.value,
        reason: read.reason,
        origin: read.origin ?? one.origin,
        color: seriesColor(one, slot),
      };
    }),
  );
}

/** What pressing the cell's mark hands to `onSelect`. */
export function cellSelection(cell: Cell): ChartSelection {
  return {
    series: cell.series.key,
    category: cell.category,
    index: cell.index,
    value: cell.value,
    origin: cell.origin,
  };
}

/** "Revenue, Q2 2026: 3,412.0 USD m (model-authored)", or
    "Revenue, Q3 2026: n/a (ZERO_OR_NEGATIVE_DENOMINATOR)". `extra` follows
    the value: a share of a stack. */
export function cellName(cell: Cell, unit: string | undefined, extra = "", signed = false): string {
  const head = `${cell.series.label}, ${cell.category}`;
  if (cell.value === null) return `${head}: n/a (${cell.reason})`;
  return `${head}: ${valueText(cell.value, unit, signed)}${extra} (${ORIGIN_WORD[cell.origin]})`;
}

/** A table cell: the value as the mark prints it, its origin said where it
    differs from its column's, or "n/a" and why. */
export function cellText(cell: Cell, extra = "", signed = false): string {
  if (cell.value === null) return `n/a: ${cell.reason}`;
  const own = cell.origin === cell.series.origin ? "" : ` (${ORIGIN_WORD[cell.origin]})`;
  return `${formatDecimal(cell.value, signed)}${extra}${own}`;
}

/** The table twin of a series chart: a row per category, a column per series
    headed by its label, unit and origin. `text` prints one cell. */
export function seriesTable(
  categoryLabel: string,
  categories: readonly string[],
  series: readonly ChartSeries[],
  cells: readonly Cell[],
  unit: string | undefined,
  text: (cell: Cell) => string = (cell) => cellText(cell),
): TableTwin {
  const head = [
    categoryLabel,
    ...series.map((one) => `${one.label}${unit ? `, ${unit}` : ""} (${ORIGIN_WORD[one.origin]})`),
  ];
  const rows = categories.map((category, index) => ({
    key: `${index}`,
    cells: [category, ...cells.filter((cell) => cell.index === index).map((cell) => text(cell))],
  }));
  return { head, rows };
}

/** A legend entry per series once there are two; one series is named by the
    title, and a box with one swatch would only repeat it. */
export function seriesLegend(
  series: readonly ChartSeries[],
  shape: LegendEntry["shape"],
): LegendEntry[] {
  if (series.length < 2) return [];
  return series.map((one, index) => ({
    key: one.key,
    label: one.label,
    tone: seriesColor(one, index),
    shape,
    origin: one.origin,
  }));
}

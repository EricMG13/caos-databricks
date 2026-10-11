// Two values of one metric, a row each: each a dot on one value axis (an
// expected value and the one realised), joined by a thin line where both are
// available. Each is the register's own figure, printed as served; nothing is
// computed between them. An unavailable end is a gap with its reason, and a
// row with one is not joined.
import { ChartFrame } from "./ChartFrame";
import { bandPlot, type BandMarker } from "./band";
import { readDatum, toNumber, type ReadValue } from "./decimal";
import { ORIGIN_WORD, cellOf, said } from "./series";
import type { ChartProps, DumbbellRow, LegendEntry, TableTwin, Tone } from "./types";

type End = "from" | "to";

/** Each end with the tone its dot wears. */
const ENDS: readonly (readonly [End, Tone])[] = [
  ["from", "neutral"],
  ["to", "series-1"],
];

/** A row's two ends, read for drawing. */
type Read = Record<End, ReadValue>;

const readRow = (row: DumbbellRow): Read => ({ from: readDatum(row.from), to: readDatum(row.to) });

/** A row's two dots, the first end first. */
function dotsOf(
  row: DumbbellRow,
  index: number,
  unit: string | undefined,
  labels: Record<End, string>,
): BandMarker[] {
  const read = readRow(row);
  return ENDS.map(([end, tone]) => {
    const value = read[end];
    const origin = value.origin ?? row.origin;
    return {
      key: `${row.key}:${end}`,
      category: index,
      at: value.value === null ? 0 : toNumber(value.value),
      tone,
      origin,
      gap: value.value === null,
      shape: "dot",
      name: `${row.label}: ${labels[end]} ${said(value, unit)} (${ORIGIN_WORD[origin]})`,
      selection: { series: end, category: row.label, index, value: value.value, origin },
    };
  });
}

/** The line between a row's two ends, where both are available. */
function spanOf(row: DumbbellRow, index: number) {
  const { from, to } = readRow(row);
  if (from.value === null || to.value === null) return [];
  return [{ category: index, from: toNumber(from.value), to: toNumber(to.value) }];
}

function tableOf(
  rows: readonly DumbbellRow[],
  categoryLabel: string,
  labels: Record<End, string>,
): TableTwin {
  return {
    head: [categoryLabel, labels.from, labels.to, "Origin"],
    rows: rows.map((row) => ({
      key: row.key,
      cells: [
        row.label,
        ...ENDS.map(([end]) => cellOf(readRow(row)[end], row.origin)),
        ORIGIN_WORD[row.origin],
      ],
    })),
  };
}

export function DumbbellChart({
  title,
  summary,
  unit,
  rows,
  fromLabel,
  toLabel,
  categoryLabel = "Metric",
  onSelect,
}: ChartProps & {
  /** One metric per row, in the order given. */
  rows: readonly DumbbellRow[];
  /** What each end is: "Expected", "Realized". */
  fromLabel: string;
  toLabel: string;
  /** What the rows are, heading the table twin's first column. Default "Metric". */
  categoryLabel?: string;
}) {
  const labels = { from: fromLabel, to: toLabel };
  const markers = rows.flatMap((row, index) => dotsOf(row, index, unit, labels));
  const spans = rows.flatMap(spanOf);
  const categories = rows.map((row) => row.label);
  const legend: LegendEntry[] = ENDS.map(([end, tone]) => ({
    key: end,
    label: labels[end],
    tone,
    shape: "dot",
  }));
  return (
    <ChartFrame
      kind="dumbbell"
      title={title}
      summary={summary}
      legend={legend}
      provenance="line"
      table={tableOf(rows, categoryLabel, labels)}
      plot={(kit) =>
        bandPlot({ orientation: "horizontal", categories, slots: 1, bars: [], markers, spans }, kit)
      }
      onSelect={onSelect}
    />
  );
}

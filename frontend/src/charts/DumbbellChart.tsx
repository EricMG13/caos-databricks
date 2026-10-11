// Two values of one metric, a row each: each a dot on one value axis (an
// expected value and the one realised), joined by a thin line where both are
// available, or, where the two coincide and are set apart, by a short line
// across the row. Each is the register's own figure, printed as served;
// nothing is computed between them. An unavailable end is a gap with its
// reason, and a row with one is not joined.
import { ChartFrame } from "./ChartFrame";
import { bandPlot, rowMarker, type BandMarker } from "./band";
import { readDatum, toNumber, type ReadValue } from "./decimal";
import { DOT } from "./marks";
import { ORIGIN_WORD, cellOf } from "./series";
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

/** How far each of two coinciding dots stands off its band's centre: apart
    by more than a dot, so neither hides the other. */
const APART = DOT + 1;

/** Both ends available and at one place on the value axis. */
const coincide = ({ from, to }: Read): boolean =>
  from.value !== null && to.value !== null && toNumber(from.value) === toNumber(to.value);

/** A row's two dots, the first end first; two at one value set apart across
    the band, the first above its centre and the second below. */
function dotsOf(
  row: DumbbellRow,
  index: number,
  read: Read,
  unit: string | undefined,
  labels: Record<End, string>,
): BandMarker[] {
  const apart = coincide(read);
  return ENDS.map(([end, tone]) => {
    const dot = rowMarker(row, index, end, labels[end], read[end], unit, { tone, shape: "dot" });
    return apart ? { ...dot, offset: end === "from" ? -APART : APART } : dot;
  });
}

/** The line between a row's two ends, where both are available: across
    the row where they coincide and are set apart. */
function spanOf(read: Read, index: number) {
  const { from, to } = read;
  if (from.value === null || to.value === null) return [];
  const across = coincide(read) ? { across: APART } : {};
  return [{ category: index, from: toNumber(from.value), to: toNumber(to.value), ...across }];
}

function tableOf(
  reads: readonly { row: DumbbellRow; read: Read }[],
  categoryLabel: string,
  labels: Record<End, string>,
): TableTwin {
  return {
    head: [categoryLabel, labels.from, labels.to, "Origin"],
    rows: reads.map(({ row, read }) => ({
      key: row.key,
      cells: [
        row.label,
        ...ENDS.map(([end]) => cellOf(read[end], row.origin)),
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
  // Each row read once, for its dots, its line and its table row.
  const reads = rows.map((row) => ({ row, read: readRow(row) }));
  const markers = reads.flatMap(({ row, read }, index) => dotsOf(row, index, read, unit, labels));
  const spans = reads.flatMap(({ read }, index) => spanOf(read, index));
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
      provenance="dot"
      table={tableOf(reads, categoryLabel, labels)}
      plot={(kit) =>
        bandPlot({ orientation: "horizontal", categories, slots: 1, bars: [], markers, spans }, kit)
      }
      onSelect={onSelect}
    />
  );
}

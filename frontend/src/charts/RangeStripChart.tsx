// A range per metric, one row each: the interquartile range a bar floating
// from Q1 to Q3 (an interval, not a magnitude, so it floats as a bridge's
// steps do), min, median and max rules across the row, a thin line from min
// to max, and the value held against the range (the borrower's, an implied
// EV) a dot. Every statistic is the register's own figure, printed as served;
// one the register does not declare is not drawn, one it declares null is a
// gap with its reason.
import { ChartFrame } from "./ChartFrame";
import { bandPlot, rowMarker, type BandBar, type BandMarker } from "./band";
import { readDatum, toNumber, type ReadValue } from "./decimal";
import { ORIGIN_WORD, cellOf, valueText } from "./series";
import type {
  ChartProps,
  ChartSelection,
  Datum,
  LegendEntry,
  Origin,
  RangeRow,
  TableTwin,
} from "./types";

type Statistic = "min" | "q1" | "median" | "q3" | "max" | "marker";

/** The statistics drawn as rules, in the order they are reached, with the
    word a name says for each. */
const RULES = [
  ["min", "min"],
  ["median", "median"],
  ["max", "max"],
] as const;

/** A statistic's value read for drawing, or `undefined` where its register
    does not declare it. */
type Read = Partial<Record<Statistic, ReadValue>>;

function readRow(row: RangeRow): Read {
  const read: Read = {};
  for (const statistic of ["min", "q1", "median", "q3", "max", "marker"] as const) {
    const datum: Datum | undefined = row[statistic];
    if (datum !== undefined) read[statistic] = readDatum(datum);
  }
  return read;
}

const originOf = (value: ReadValue, row: RangeRow): Origin => value.origin ?? row.origin;

/** The interquartile bar, where either quartile is declared: Q1 to Q3, or a
    gap naming each unavailable end (an undeclared end is "Not served").
    Host-verified only where both ends are; the model's where either is. */
function barOf(row: RangeRow, index: number, read: Read, unit: string | undefined): BandBar[] {
  if (read.q1 === undefined && read.q3 === undefined) return [];
  const q1 = read.q1 ?? readDatum(undefined);
  const q3 = read.q3 ?? readDatum(undefined);
  const origin: Origin =
    originOf(q1, row) === "model" || originOf(q3, row) === "model" ? "model" : "host";
  const head = `${row.label}: interquartile range`;
  const tail = `(${ORIGIN_WORD[origin]})`;
  const selection: ChartSelection = {
    series: "interquartile",
    category: row.label,
    index,
    value: null,
    origin,
  };
  const base = { key: `${row.key}:iqr`, category: index, slot: 0, tone: "series-1" as const };
  if (q1.value === null || q3.value === null) {
    const reasons = [
      ["Q1", q1],
      ["Q3", q3],
    ] as const;
    const why = reasons
      .filter(([, end]) => end.value === null)
      .map(([word, end]) => `${word}: ${end.reason}`)
      .join("; ");
    return [
      {
        ...base,
        from: 0,
        to: 0,
        origin,
        gap: true,
        name: `${head} n/a (${why}) ${tail}`,
        label: null,
        selection,
      },
    ];
  }
  return [
    {
      ...base,
      from: toNumber(q1.value),
      to: toNumber(q3.value),
      origin,
      gap: false,
      name: `${head} ${valueText(q1.value, unit)} to ${valueText(q3.value, unit)} ${tail}`,
      // Two ends and no one figure: the name, the readout and the table say them.
      label: null,
      selection: { ...selection, interval: { from: q1.value, to: q3.value } },
    },
  ];
}

/** A row's rules and dot, in the order they are reached: min, median, max,
    then the marker. */
function markersOf(
  row: RangeRow,
  index: number,
  read: Read,
  unit: string | undefined,
  markerLabel: string,
): BandMarker[] {
  const stated = [...RULES, ["marker", markerLabel] as const];
  return stated.flatMap(([statistic, word]) => {
    const value = read[statistic];
    if (value === undefined) return [];
    const look =
      statistic === "marker"
        ? ({ tone: "series-3", shape: "dot" } as const)
        : ({ tone: "neutral", shape: "rule" } as const);
    return [rowMarker(row, index, statistic, word, value, unit, look)];
  });
}

/** The line from min to max, where both are drawn. */
function spanOf(index: number, read: Read) {
  const min = read.min?.value;
  const max = read.max?.value;
  if (min === undefined || min === null || max === undefined || max === null) return [];
  return [{ category: index, from: toNumber(min), to: toNumber(max) }];
}

function tableOf(
  rows: readonly RangeRow[],
  reads: readonly Read[],
  categoryLabel: string,
  markerLabel: string,
): TableTwin {
  const columns = (
    [
      ["min", "Min"],
      ["q1", "Q1"],
      ["median", "Median"],
      ["q3", "Q3"],
      ["max", "Max"],
      ["marker", markerLabel],
    ] as const
  ).filter(([statistic]) => reads.some((read) => read[statistic] !== undefined));
  return {
    head: [categoryLabel, ...columns.map(([, head]) => head), "Origin"],
    rows: rows.map((row, index) => ({
      key: row.key,
      cells: [
        row.label,
        ...columns.map(([statistic]) => cellOf(reads[index]?.[statistic], row.origin)),
        ORIGIN_WORD[row.origin],
      ],
    })),
  };
}

/** A key for each kind of mark the chart draws. */
function legendOf(reads: readonly Read[], markerLabel: string): LegendEntry[] {
  const declares = (statistics: readonly Statistic[]) =>
    reads.some((read) => statistics.some((statistic) => read[statistic] !== undefined));
  return [
    ...(declares(["q1", "q3"])
      ? [{ key: "iqr", label: "Interquartile range", tone: "series-1", shape: "fill" } as const]
      : []),
    ...(declares(["min", "median", "max"])
      ? [{ key: "rules", label: "Min, median, max", tone: "neutral", shape: "rule" } as const]
      : []),
    ...(declares(["marker"])
      ? [{ key: "marker", label: markerLabel, tone: "series-3", shape: "dot" } as const]
      : []),
  ];
}

export function RangeStripChart({
  title,
  summary,
  unit,
  rows,
  markerLabel = "Borrower",
  categoryLabel = "Metric",
  onSelect,
}: ChartProps & {
  /** One metric per row, in the order given. */
  rows: readonly RangeRow[];
  /** What the dot is: "Borrower", "Implied EV". Default "Borrower". */
  markerLabel?: string;
  /** What the rows are, heading the table twin's first column. Default "Metric". */
  categoryLabel?: string;
}) {
  const reads = rows.map(readRow);
  const bars = rows.flatMap((row, index) => barOf(row, index, reads[index] ?? {}, unit));
  const markers = rows.flatMap((row, index) =>
    markersOf(row, index, reads[index] ?? {}, unit, markerLabel),
  );
  const spans = reads.flatMap((read, index) => spanOf(index, read));
  const categories = rows.map((row) => row.label);
  return (
    <ChartFrame
      kind="range"
      title={title}
      summary={summary}
      legend={legendOf(reads, markerLabel)}
      // A bar's key where the quartiles are drawn, else the rules' and dots'.
      provenance={bars.length ? "fill" : "line"}
      table={tableOf(rows, reads, categoryLabel, markerLabel)}
      plot={(kit) =>
        bandPlot({ orientation: "horizontal", categories, slots: 1, bars, markers, spans }, kit)
      }
      onSelect={onSelect}
    />
  );
}

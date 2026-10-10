// A test against its threshold, one row per test: the current basis a bar
// from zero, the threshold a rule across the row. The row says which way the
// test runs (a ceiling, a floor, or not stated); the headroom is the module's
// own figure, printed as served in every name, readout and table cell, and
// never drawn or computed here: no subtraction of the two values stands in
// for what the module stated.
import { ChartFrame } from "./ChartFrame";
import { bandPlot, type BandBar, type BandMarker } from "./band";
import { formatDecimal, readDatum, toNumber, type ReadValue } from "./decimal";
import { ORIGIN_WORD, valueText } from "./series";
import type {
  BulletRow,
  ChartProps,
  ChartSelection,
  LegendEntry,
  Origin,
  TableTwin,
} from "./types";

const DIRECTION_WORD = { max: "ceiling", min: "floor" } as const;

const LEGEND: readonly LegendEntry[] = [
  { key: "current", label: "Current basis", tone: "series-1", shape: "fill" },
  { key: "threshold", label: "Threshold", tone: "neutral", shape: "line" },
];

/** A row read for drawing: each value exact or null with its reason, and the
    origin each mark wears (a datum's own, else the row's). */
interface Read {
  row: BulletRow;
  index: number;
  category: string;
  threshold: ReadValue;
  current: ReadValue;
  headroom: ReadValue;
}

/** "ceiling", "floor", or "direction not stated": never inferred. */
function directionOf(row: BulletRow): string {
  return row.direction ? DIRECTION_WORD[row.direction] : "direction not stated";
}

function readRow(row: BulletRow, index: number): Read {
  return {
    row,
    index,
    category: `${row.label}, ${directionOf(row)}`,
    threshold: readDatum(row.threshold),
    current: readDatum(row.current),
    headroom: readDatum(row.headroom),
  };
}

/** "3.25 x", or "n/a (NOT_DISCLOSED)". */
function said(read: ReadValue, unit: string | undefined): string {
  return read.value === null ? `n/a (${read.reason})` : valueText(read.value, unit);
}

/** The headroom as served, without a unit of its own: "1.25", "n/a (…)". */
function headroomText(read: ReadValue): string {
  return read.value === null ? `n/a (${read.reason})` : formatDecimal(read.value);
}

/** Each mark's name: what it is first, then the other value it is held
    against, the headroom as served and who stands behind the mark. */
function namesOf(read: Read, unit: string | undefined) {
  const { row } = read;
  const word = row.direction ? DIRECTION_WORD[row.direction] : "threshold";
  const headroom = `headroom ${headroomText(read.headroom)}`;
  const current = said(read.current, unit);
  const threshold = said(read.threshold, unit);
  const of = (value: ReadValue) => ORIGIN_WORD[value.origin ?? row.origin];
  return {
    current: `${row.label}: current basis ${current} against a ${word} of ${threshold}, ${headroom} (${of(read.current)})`,
    threshold: `${row.label}: ${word} ${threshold} against a current basis of ${current}, ${headroom} (${of(read.threshold)})`,
  };
}

function selectionOf(read: Read, series: string, value: ReadValue, origin: Origin): ChartSelection {
  return { series, category: read.row.label, index: read.index, value: value.value, origin };
}

function barOf(read: Read, name: string): BandBar {
  const { current, row } = read;
  const origin = current.origin ?? row.origin;
  return {
    key: `${row.key}:current`,
    category: read.index,
    slot: 0,
    from: 0,
    to: current.value === null ? 0 : toNumber(current.value),
    tone: "series-1",
    origin,
    gap: current.value === null,
    name,
    label: current.value === null ? null : formatDecimal(current.value),
    selection: selectionOf(read, "current", current, origin),
  };
}

function markerOf(read: Read, name: string): BandMarker {
  const { threshold, row } = read;
  const origin = threshold.origin ?? row.origin;
  return {
    key: `${row.key}:threshold`,
    category: read.index,
    at: threshold.value === null ? 0 : toNumber(threshold.value),
    tone: "neutral",
    origin,
    gap: threshold.value === null,
    shape: "rule",
    name,
    selection: selectionOf(read, "threshold", threshold, origin),
  };
}

/** A table cell: the value as served, its origin said where it differs from
    its row's, or "n/a" and why. */
function cellOf(read: ReadValue, row: BulletRow): string {
  if (read.value === null) return `n/a: ${read.reason}`;
  const own = read.origin && read.origin !== row.origin ? ` (${ORIGIN_WORD[read.origin]})` : "";
  return `${formatDecimal(read.value)}${own}`;
}

function tableOf(
  reads: readonly Read[],
  unit: string | undefined,
  categoryLabel: string,
): TableTwin {
  const unitOf = unit ? `, ${unit}` : "";
  return {
    head: [
      categoryLabel,
      "Direction",
      `Threshold${unitOf}`,
      `Current basis${unitOf}`,
      `Headroom${unitOf}`,
      "Origin",
    ],
    rows: reads.map((read) => ({
      key: read.row.key,
      cells: [
        read.row.label,
        directionOf(read.row),
        cellOf(read.threshold, read.row),
        cellOf(read.current, read.row),
        cellOf(read.headroom, read.row),
        ORIGIN_WORD[read.row.origin],
      ],
    })),
  };
}

export function BulletChart({
  title,
  summary,
  unit,
  rows,
  categoryLabel = "Test",
  onSelect,
}: ChartProps & {
  /** One test per row, in the order given. */
  rows: readonly BulletRow[];
  /** What the rows are, heading the table twin's first column. Default "Test". */
  categoryLabel?: string;
}) {
  const reads = rows.map(readRow);
  const named = reads.map((read) => ({ read, names: namesOf(read, unit) }));
  const bars = named.map(({ read, names }) => barOf(read, names.current));
  const markers = named.map(({ read, names }) => markerOf(read, names.threshold));
  const categories = reads.map((read) => read.category);
  return (
    <ChartFrame
      kind="bullet"
      title={title}
      summary={summary}
      legend={LEGEND}
      provenance="fill"
      table={tableOf(reads, unit, categoryLabel)}
      plot={(kit) =>
        bandPlot({ orientation: "horizontal", categories, slots: 1, bars, markers }, kit)
      }
      onSelect={onSelect}
    />
  );
}

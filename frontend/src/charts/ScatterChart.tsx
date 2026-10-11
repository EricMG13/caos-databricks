// Values against time: a point per value at the date it is served with,
// drawn by Recharts (D61) on a time axis whose ticks label years, against one
// value axis holding zero. A date is read only as `YYYY-MM-DD`, `YYYY-MM` or
// `YYYY` (a month or a year placed at its first day); any other spelling,
// `03/04/2031` above all, is never guessed. A point with no readable date or
// no value, or a value too large for a float to place, is not placed: the
// table twin lists it with its reason and the caption counts it. Placed points
// wear their group's colour, the host's filled and the model's hollow; the
// arrow keys take them in date order.
import { CartesianGrid, Scatter, ScatterChart as Chart, XAxis, YAxis } from "recharts";
import { ChartFrame, Focus, Reported } from "./ChartFrame";
import { valueTick, valueTicks, type Tick } from "./axes";
import { formatDecimal, readDatum, toNumber } from "./decimal";
import { DOT } from "./marks";
import { TICK_SIZE, textWidth } from "./scale";
import { ORIGIN_WORD, seriesColor, valueText } from "./series";
import type {
  ChartColor,
  ChartProps,
  Decimal,
  LegendEntry,
  Origin,
  Plot,
  PlotKit,
  ScatterPoint,
  TableTwin,
} from "./types";

const AXIS_BAND = 22;
// Room for half a year label past the last tick, which stands at the edge.
const EDGE = Math.ceil(textWidth("0000", TICK_SIZE) / 2) + 2;
const TOP = 8;
const HEIGHT = 240;
const YEAR_STEPS = [1, 2, 5, 10, 20, 50, 100, 200, 500, 1000];
const DATE = /^(\d{4})(?:-(\d{2})(?:-(\d{2}))?)?$/;
const UNDATED = "No readable date (YYYY-MM-DD, YYYY-MM or YYYY)";
const UNPLACEABLE = "Value too large to place";

/** The first instant of a day, UTC; years below 100 kept as written. */
function dayStart(year: number, month = 1, day = 1): Date {
  const date = new Date(0);
  date.setUTCFullYear(year, month - 1, day);
  return date;
}

/** A date's time in ms, UTC, or null where it is not one of the three
    spellings read or names no real day (`2031-02-30`). A float that only
    places a mark. */
export function readDate(at: string): number | null {
  const match = DATE.exec(at);
  if (!match) return null;
  const [year, month, day] = [match[1], match[2] ?? "1", match[3] ?? "1"].map(Number) as [
    number,
    number,
    number,
  ];
  const date = dayStart(year, month, day);
  const real = date.getUTCMonth() === month - 1 && date.getUTCDate() === day;
  return real ? date.getTime() : null;
}

/** A point read for drawing: its place in time and its value, or why it is
    not placed. */
interface Read {
  point: ScatterPoint;
  index: number;
  time: number | null;
  value: Decimal | null;
  reason: string | null;
  origin: Origin;
  unplaced: string;
}

/** A point that has both: drawn in its group's colour and reached by its date. */
type Placed = Read & { time: number; value: Decimal; color: ChartColor };

const placeable = (read: Read): read is Omit<Placed, "color"> => !read.unplaced;

/** Why a value is not placed: none, or one a float cannot place (past
    about 1.8e308, where Recharts would draw no point). */
function valueWhy(value: Decimal | null): string {
  if (value === null) return "No value";
  return Number.isFinite(toNumber(value)) ? "" : UNPLACEABLE;
}

function readPoints(points: readonly ScatterPoint[]): Read[] {
  return points.map((point, index) => {
    const read = readDatum(point.value);
    const time = readDate(point.at);
    const why = [time === null ? UNDATED : "", valueWhy(read.value)];
    return {
      point,
      index,
      time,
      value: read.value,
      reason: read.reason,
      origin: read.origin ?? point.origin,
      unplaced: why.filter(Boolean).join("; "),
    };
  });
}

/** The placed points in date order, coloured by group as the groups first
    appear among them. */
function placedOf(reads: readonly Read[]): Placed[] {
  const drawn = reads.filter(placeable);
  const groups = [...new Set(drawn.map((read) => read.point.group))];
  return drawn
    .map((read) => ({ ...read, color: seriesColor({}, groups.indexOf(read.point.group)) }))
    .sort((a, b) => a.time - b.time || a.index - b.index);
}

/** Year ticks across `[first, last]`, every year that fits in `width`, else
    every 2nd, 5th, 10th, … */
function yearTicks(first: number, last: number, width: number): number[] {
  const room = textWidth("0000", TICK_SIZE) + 12;
  const fits = (step: number) =>
    (Math.floor(last / step) - Math.ceil(first / step) + 1) * room <= width;
  const step = YEAR_STEPS.find(fits) ?? YEAR_STEPS.at(-1)!;
  const years: number[] = [];
  for (let year = Math.ceil(first / step) * step; year <= last; year += step) years.push(year);
  return years;
}

interface ScatterSpec {
  placed: Placed[];
  unit: string | undefined;
  xLabel: string;
}

const nameOf = (read: Placed, spec: ScatterSpec) => {
  const { label, group, at } = read.point;
  const head = group ? `${label}, ${group}` : label;
  const value = valueText(read.value, spec.unit);
  return `${head}, ${spec.xLabel} ${at}: ${value} (${ORIGIN_WORD[read.origin]})`;
};

/** A point Recharts placed, filled for the host and hollow for the model,
    and reported so a button can be laid over it. */
function Point({
  read,
  cx,
  cy,
  spec,
}: {
  read: Placed;
  cx: number;
  cy: number;
  spec: ScatterSpec;
}) {
  const { key, label, group } = read.point;
  return (
    <>
      <circle
        className={`chart-point chart-tone-${read.color}${read.origin === "model" ? " chart-hollow" : ""}`}
        data-mark={key}
        data-origin={read.origin}
        cx={cx}
        cy={cy}
        r={DOT}
      />
      <Reported
        mark={{
          key,
          name: nameOf(read, spec),
          box: { x: cx - DOT, y: cy - DOT, width: 2 * DOT, height: 2 * DOT },
          round: true,
          guide: cx,
          selection: {
            series: group,
            category: label,
            index: read.index,
            value: read.value,
            origin: read.origin,
          },
        }}
      />
    </>
  );
}

function scatterPlot(spec: ScatterSpec, kit: PlotKit): Plot {
  const bottom = HEIGHT - AXIS_BAND;
  const values = spec.placed.map((read) => toNumber(read.value));
  const axis = valueTicks([Math.min(0, ...values), Math.max(0, ...values)], [bottom, TOP], 44);
  const left = axis.widest + 10;
  const years = spec.placed.map((read) => new Date(read.time).getUTCFullYear());
  // Whole years, the last one's end included; with nothing placed, an epoch
  // year only spans the empty axis, and no year is labelled.
  const [first, last] = years.length ? [Math.min(...years), Math.max(...years) + 1] : [1970, 1971];
  const across = kit.width - EDGE - left;
  const ticks = years.length ? yearTicks(first, last, across) : [];
  const [start, end] = [dayStart(first).getTime(), dayStart(last).getTime()];
  const yearAxis: Tick[] = ticks.map((year) => {
    const time = dayStart(year).getTime();
    const position = left + ((time - start) / (end - start)) * across;
    return { value: time, position, text: `${year}`.padStart(4, "0") };
  });
  const byKey = new Map(spec.placed.map((read) => [read.point.key, read]));
  const zero = axis.at(0);
  const chart = (
    <Chart
      {...kit.svg}
      className="chart-svg"
      width={kit.width}
      height={HEIGHT}
      margin={{ top: TOP, right: EDGE, bottom: 0, left: 0 }}
      accessibilityLayer={false}
    >
      <CartesianGrid
        className="chart-grid"
        vertical={false}
        horizontalPoints={axis.ticks.map((tick) => tick.position)}
      />
      <XAxis
        type="number"
        dataKey="x"
        domain={[start, end]}
        ticks={yearAxis.map((tick) => tick.value)}
        tick={valueTick(yearAxis, "bottom")}
        height={AXIS_BAND}
        axisLine={false}
        tickLine={false}
        interval={0}
        allowDataOverflow
      />
      <YAxis
        type="number"
        dataKey="y"
        domain={axis.domain}
        ticks={axis.ticks.map((tick) => tick.value)}
        tick={valueTick(axis.ticks, "left")}
        width={left}
        axisLine={false}
        tickLine={false}
        interval={0}
        allowDataOverflow
      />
      <line className="chart-zero" x1={left} x2={kit.width - EDGE} y1={zero} y2={zero} />
      <Scatter
        data={spec.placed.map((read) => ({
          x: read.time,
          y: toNumber(read.value),
          key: read.point.key,
        }))}
        isAnimationActive={false}
        shape={(props: { cx?: number; cy?: number; payload?: { key?: string } }) => {
          const read = byKey.get(props.payload?.key ?? "");
          // Every point here has a finite time and value (`valueWhy`), so
          // Recharts gives each its cx and cy; the type still allows none.
          if (!read || props.cx == null || props.cy == null) return <g />;
          return <Point read={read} cx={props.cx} cy={props.cy} spec={spec} />;
        }}
      />
      <Focus />
    </Chart>
  );
  return { height: HEIGHT, chart, order: spec.placed.map((read) => read.point.key) };
}

function tableOf(
  rows: readonly Read[],
  labels: { point: string; x: string; value: string; group: string },
  unit: string | undefined,
): TableTwin {
  return {
    head: [
      labels.point,
      labels.x,
      `${labels.value}${unit ? `, ${unit}` : ""}`,
      labels.group,
    ].concat(["Origin", "Not placed"]),
    rows: rows.map((read) => ({
      key: read.point.key,
      cells: [
        read.point.label,
        read.point.at,
        read.value === null ? `n/a: ${read.reason}` : formatDecimal(read.value),
        read.point.group,
        ORIGIN_WORD[read.origin],
        read.unplaced,
      ],
    })),
  };
}

export function ScatterChart({
  title,
  summary,
  unit,
  points,
  xLabel,
  pointLabel = "Point",
  valueLabel = "Value",
  groupLabel = "Group",
  onSelect,
}: ChartProps & {
  /** A point per value, in the order given; drawn and reached by date. */
  points: readonly ScatterPoint[];
  /** What the dates are: "Maturity/call date". */
  xLabel: string;
  /** What the table twin calls the points, their values and their groups. */
  pointLabel?: string;
  valueLabel?: string;
  groupLabel?: string;
}) {
  const reads = readPoints(points);
  const placed = placedOf(reads);
  const unplaced = reads.filter((read) => read.unplaced);
  const spec: ScatterSpec = { placed, unit, xLabel };
  const legend: LegendEntry[] = [...new Map(placed.map((read) => [read.point.group, read]))].map(
    ([group, read]) => ({ key: group, label: group, tone: read.color, shape: "dot" }),
  );
  const note = unplaced.length
    ? `${unplaced.length} of ${reads.length} points not placed; the table lists each with its reason.`
    : null;
  const labels = { point: pointLabel, x: xLabel, value: valueLabel, group: groupLabel };
  return (
    <ChartFrame
      kind="scatter"
      title={title}
      summary={summary}
      note={note}
      legend={legend}
      provenance="line"
      table={tableOf([...placed, ...unplaced], labels, unit)}
      plot={(kit) => scatterPlot(spec, kit)}
      onSelect={onSelect}
    />
  );
}

// Change across periods: one line per series, drawn by Recharts (D61). A
// missing value is a gap in its line, never a value drawn in between; it is
// marked "n/a" on the axis below, its reason in the mark's name. The host's
// lines are solid with filled points, the model's dashed with hollow ones.
// Hovering or focusing a point reads out every series at that period.
import { CartesianGrid, Curve, Line, LineChart as Chart, XAxis, YAxis } from "recharts";
import { Focus, Reported } from "./ChartFrame";
import { ChartFrame } from "./ChartFrame";
import { Label, TickText, shownCategories, valueTick, valueTicks, type Tick } from "./axes";
import { formatDecimal, toNumber } from "./decimal";
import { GapMark } from "./marks";
import { VALUE_SIZE, textWidth } from "./scale";
import {
  ORIGIN_WORD,
  cellName,
  cellSelection,
  cellsOf,
  seriesLegend,
  seriesTable,
  valueText,
  type Cell,
} from "./series";
import type { Box, ChartSeries, Plot, PlotKit, SeriesChartProps } from "./types";

const AXIS_BAND = 22;
const EDGE = 8;
const TOP = 8;
const POINT = 4; // a point is 8px across
const APART = VALUE_SIZE + 1; // end labels nearer than this would collide
const STACKED_GAP = VALUE_SIZE + 3; // gap marks of several series at one period, stacked up

interface LineSpec {
  categories: readonly string[];
  series: readonly ChartSeries[];
  cells: readonly Cell[];
  unit: string | undefined;
  includeZero: boolean;
  height: number;
}

/** Every series at one period: the one readout for a hovered or focused point. */
function readoutAt(spec: LineSpec, index: number): string {
  const said = spec.cells
    .filter((cell) => cell.index === index)
    .map((cell) =>
      cell.value === null
        ? `${cell.series.label} n/a (${cell.reason})`
        : `${cell.series.label} ${valueText(cell.value, spec.unit)} (${ORIGIN_WORD[cell.origin]})`,
    );
  return `${spec.categories[index] ?? ""}: ${said.join("; ")}`;
}

function extentOf(spec: LineSpec): [number, number] {
  const values = [
    ...(spec.includeZero ? [0] : []),
    ...spec.cells.flatMap((cell) => (cell.value === null ? [] : [toNumber(cell.value)])),
  ];
  return values.length ? [Math.min(...values), Math.max(...values)] : [0, 0];
}

interface Layout {
  area: Box;
  axis: { domain: [number, number]; ticks: readonly Tick[]; at: (value: number) => number };
  /** A period's place along the axis: the centre of its share of the width. */
  x: (index: number) => number;
  step: number;
  bottom: number;
  ends: { cell: Cell; y: number; text: string }[];
  apart: boolean;
  room: number;
}

function layoutOf(spec: LineSpec, width: number): Layout {
  const bottom = spec.height - AXIS_BAND;
  const axis = valueTicks(extentOf(spec), [bottom, TOP], 44);
  const left = axis.widest + 10;
  // The last value of each series, labelled at its line's end when no two
  // ends crowd each other; otherwise the legend and the readout carry them.
  const ends = spec.series.flatMap((_, slot) => {
    const last = spec.cells.filter((cell) => cell.slot === slot && cell.value !== null).at(-1);
    if (!last || last.value === null) return [];
    return [{ cell: last, y: axis.at(toNumber(last.value)), text: formatDecimal(last.value) }];
  });
  const heights = ends.map((end) => end.y).sort((a, b) => a - b);
  const apart = heights.every((y, at) => at === 0 || y - (heights[at - 1] ?? y) >= APART);
  const room =
    apart && ends.length ? Math.max(...ends.map((end) => textWidth(end.text, VALUE_SIZE))) + 10 : 0;
  const area = { x: left, y: TOP, width: width - EDGE - room - left, height: bottom - TOP };
  const step = area.width / Math.max(1, spec.categories.length);
  return {
    area,
    axis,
    x: (index) => area.x + step * (index + 0.5),
    step,
    bottom,
    ends,
    apart,
    room,
  };
}

/** A point Recharts placed, drawn solid for the host and hollow for the model,
    and reported so a button can be laid over it. */
function Point({ cell, cx, cy, spec }: { cell: Cell; cx: number; cy: number; spec: LineSpec }) {
  const key = `${cell.series.key}:${cell.index}`;
  return (
    <>
      <circle
        className={`chart-point chart-tone-${cell.color}${cell.origin === "model" ? " chart-hollow" : ""}`}
        data-mark={key}
        data-origin={cell.origin}
        cx={cx}
        cy={cy}
        r={POINT}
      />
      <Reported
        mark={{
          key,
          name: cellName(cell, spec.unit),
          readout: readoutAt(spec, cell.index),
          box: { x: cx - POINT, y: cy - POINT, width: 2 * POINT, height: 2 * POINT },
          round: true,
          guide: cx,
          selection: cellSelection(cell),
        }}
      />
    </>
  );
}

/** What Recharts has no word for: each unavailable value's "n/a", the end
    labels, and the zero baseline. */
function Annotations({ spec, layout }: { spec: LineSpec; layout: Layout }) {
  const gapsBefore = (cell: Cell) =>
    spec.cells.filter(
      (other) => other.index === cell.index && other.value === null && other.slot < cell.slot,
    ).length;
  const { area } = layout;
  return (
    <g className="chart-annotations">
      {spec.includeZero ? (
        <line
          className="chart-zero"
          x1={area.x}
          x2={area.x + area.width}
          y1={layout.axis.at(0)}
          y2={layout.axis.at(0)}
        />
      ) : null}
      {spec.cells.map((cell) => {
        if (cell.value !== null) return null;
        const key = `${cell.series.key}:${cell.index}`;
        const x = layout.x(cell.index);
        const y = layout.bottom - gapsBefore(cell) * STACKED_GAP;
        return (
          <g key={key}>
            <GapMark mark={key} x={x} y={y} vertical />
            <Reported
              mark={{
                key,
                name: cellName(cell, spec.unit),
                readout: readoutAt(spec, cell.index),
                box: { x: x - 10, y: y - 20, width: 20, height: 20 },
                guide: x,
                selection: cellSelection(cell),
              }}
            />
          </g>
        );
      })}
      {layout.apart
        ? layout.ends.map((end) => (
            <Label
              key={`end-${end.cell.series.key}`}
              className="chart-value"
              placed={{
                text: end.text,
                x: layout.x(end.cell.index) + POINT + 6,
                y: end.y + VALUE_SIZE / 2 - 2,
                anchor: "start",
              }}
            />
          ))
        : null}
    </g>
  );
}

function linePlot(spec: LineSpec, kit: PlotKit): Plot {
  const layout = layoutOf(spec, kit.width);
  const rows = spec.categories.map((category, index) => {
    const row: Record<string, unknown> = { category, index };
    spec.series.forEach((_, slot) => {
      const cell = spec.cells.find((entry) => entry.slot === slot && entry.index === index);
      row[`v${slot}`] = cell?.value == null ? null : toNumber(cell.value);
    });
    return row;
  });
  const cellAt = new Map(spec.cells.map((cell) => [`${cell.slot}:${cell.index}`, cell]));
  const shown = shownCategories(spec.categories, layout.step);
  const chart = (
    <Chart
      {...kit.svg}
      className="chart-svg"
      width={kit.width}
      height={spec.height}
      data={rows}
      margin={{ top: TOP, right: EDGE + layout.room, bottom: 0, left: 0 }}
      accessibilityLayer={false}
    >
      <CartesianGrid
        className="chart-grid"
        vertical={false}
        horizontalPoints={layout.axis.ticks.map((tick) => tick.position)}
      />
      <XAxis
        dataKey="category"
        type="category"
        scale="point"
        padding={{ left: layout.step / 2, right: layout.step / 2 }}
        height={AXIS_BAND}
        axisLine={false}
        tickLine={false}
        interval={0}
        tick={(props: {
          x?: number | string;
          y?: number | string;
          payload?: { value?: unknown };
        }) => (
          <TickText
            x={props.x}
            y={props.y}
            dy={10}
            anchor="middle"
            text={shown[spec.categories.indexOf(String(props.payload?.value ?? ""))] ?? null}
          />
        )}
      />
      <YAxis
        type="number"
        domain={layout.axis.domain}
        ticks={layout.axis.ticks.map((tick) => tick.value)}
        tick={valueTick(layout.axis.ticks, "left")}
        width={layout.area.x}
        axisLine={false}
        tickLine={false}
        interval={0}
        allowDataOverflow
      />
      {spec.series.map((one, slot) => {
        const tone = spec.cells.find((cell) => cell.slot === slot)?.color ?? "neutral";
        return (
          <Line
            key={one.key}
            dataKey={`v${slot}`}
            isAnimationActive={false}
            connectNulls={false}
            activeDot={false}
            shape={(props: object) => (
              <Curve
                {...props}
                className={`chart-line chart-tone-${tone}${one.origin === "model" ? " chart-dashed" : ""}`}
                data-series={one.key}
              />
            )}
            dot={(props: { cx?: number; cy?: number; payload?: { index?: number } }) => {
              const cell = cellAt.get(`${slot}:${props.payload?.index ?? -1}`);
              if (!cell || cell.value === null || props.cx == null || props.cy == null) {
                return <g key={`${one.key}-${props.payload?.index ?? "none"}`} />;
              }
              return (
                <Point
                  key={`${one.key}-${cell.index}`}
                  cell={cell}
                  cx={props.cx}
                  cy={props.cy}
                  spec={spec}
                />
              );
            }}
          />
        );
      })}
      <Annotations spec={spec} layout={layout} />
      <Focus />
    </Chart>
  );
  const order = [...spec.cells]
    .sort((a, b) => a.index - b.index || a.slot - b.slot)
    .map((cell) => `${cell.series.key}:${cell.index}`);
  return { height: spec.height, chart, order };
}

export function LineChart({
  title,
  summary,
  unit,
  categories,
  series,
  categoryLabel = "Category",
  includeZero = true,
  height = 240,
  onSelect,
}: SeriesChartProps & {
  /** Hold zero on the value axis (the default). A small multiple of a ratio
      may drop it to show its movement; its axis then says where it starts. */
  includeZero?: boolean;
  /** The chart's height, axes included. */
  height?: number;
}) {
  const cells = cellsOf(categories, series);
  const spec: LineSpec = { categories, series, cells, unit, includeZero, height };
  return (
    <ChartFrame
      kind="line"
      title={title}
      summary={summary}
      legend={seriesLegend(series, "line")}
      provenance="line"
      table={seriesTable(categoryLabel, categories, series, cells, unit)}
      plot={(kit) => linePlot(spec, kit)}
      onSelect={onSelect}
    />
  );
}

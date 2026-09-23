// Change across periods: one line per series. A missing value is a gap in its
// line (`line().defined()`), never a value drawn in between; it is marked
// "n/a" on the axis below, its reason in the mark's name. The host's lines
// are solid with filled points, the model's dashed with hollow ones. Hovering
// or focusing a point reads out every series at that period.
import { scalePoint } from "d3-scale";
import { line } from "d3-shape";
import { ChartFrame } from "./ChartFrame";
import { Label, ValueGrid, acrossLabels, valueTicks } from "./axes";
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
import type { ChartSeries, MarkHit, Plot, SeriesChartProps } from "./types";

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

function linePlot(spec: LineSpec, width: number): Plot {
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
  const x = scalePoint<number>()
    .domain(spec.categories.map((_, index) => index))
    .range([left, width - EDGE - room])
    .padding(0.5);
  const at = (cell: Cell) => x(cell.index) ?? left;
  const area = { x: left, y: TOP, width: width - EDGE - room - left, height: bottom - TOP };
  const path = line<Cell>()
    .defined((cell) => cell.value !== null)
    .x(at)
    .y((cell) => axis.at(toNumber(cell.value ?? "0")));
  const gapsBefore = (cell: Cell) =>
    spec.cells.filter(
      (other) => other.index === cell.index && other.value === null && other.slot < cell.slot,
    ).length;
  const marks: MarkHit[] = spec.cells.map((cell) => {
    const cx = at(cell);
    const box =
      cell.value === null
        ? { x: cx - 10, y: bottom - gapsBefore(cell) * STACKED_GAP - 20, width: 20, height: 20 }
        : {
            x: cx - POINT,
            y: axis.at(toNumber(cell.value)) - POINT,
            width: 2 * POINT,
            height: 2 * POINT,
          };
    return {
      key: `${cell.series.key}:${cell.index}`,
      name: cellName(cell, spec.unit),
      readout: readoutAt(spec, cell.index),
      box,
      round: cell.value !== null,
      guide: cx,
      selection: cellSelection(cell),
    };
  });
  const body = (
    <>
      <ValueGrid
        ticks={axis.ticks}
        area={area}
        vertical
        zero={spec.includeZero ? axis.at(0) : null}
      />
      {acrossLabels(spec.categories, (index) => x(index) ?? left, x.step(), bottom + 14).map(
        (placed, index) => (
          <Label key={`category-${index}`} className="chart-tick" placed={placed} />
        ),
      )}
      {spec.series.map((one, slot) => {
        const own = spec.cells.filter((cell) => cell.slot === slot);
        const tone = own[0]?.color ?? "neutral";
        return (
          <path
            key={one.key}
            className={`chart-line chart-tone-${tone}${one.origin === "model" ? " chart-dashed" : ""}`}
            data-series={one.key}
            d={path(own) ?? undefined}
          />
        );
      })}
      {spec.cells.map((cell) => {
        const key = `${cell.series.key}:${cell.index}`;
        if (cell.value === null) {
          const y = bottom - gapsBefore(cell) * STACKED_GAP;
          return <GapMark key={key} mark={key} x={at(cell)} y={y} vertical />;
        }
        return (
          <circle
            key={key}
            className={`chart-point chart-tone-${cell.color}${cell.origin === "model" ? " chart-hollow" : ""}`}
            data-mark={key}
            data-origin={cell.origin}
            cx={at(cell)}
            cy={axis.at(toNumber(cell.value))}
            r={POINT}
          />
        );
      })}
      {apart
        ? ends.map((end) => (
            <Label
              key={`end-${end.cell.series.key}`}
              className="chart-value"
              placed={{
                text: end.text,
                x: at(end.cell) + POINT + 6,
                y: end.y + VALUE_SIZE / 2 - 2,
                anchor: "start",
              }}
            />
          ))
        : null}
    </>
  );
  return { height: spec.height, area, body, marks, hatched: [] };
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
      plot={(width) => linePlot(spec, width)}
      onSelect={onSelect}
    />
  );
}

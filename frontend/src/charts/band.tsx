// Band charts: bars on a band axis against one linear value axis, either way
// up. The bar, stacked, waterfall and diverging charts are this one geometry
// with different bars: each chart says what its bars mean, this says where
// they go. One value axis always, holding zero (no dual axis, no floating
// baseline); bars no thicker than 24px, with square ends.
import { scaleBand, type ScaleBand } from "d3-scale";
import { Label, ValueGrid, acrossLabels, valueTicks, type Placed, type Tick } from "./axes";
import { formatDecimal, toNumber } from "./decimal";
import { BarShape, GapMark } from "./marks";
import { TICK_SIZE, VALUE_SIZE, fitText, textWidth } from "./scale";
import { cellName, cellSelection, type Cell } from "./series";
import type { Box, ChartSelection, Hatch, MarkHit, Orientation, Origin, Plot, Tone } from "./types";

/** One bar, in value space. */
export interface BandBar {
  key: string;
  category: number;
  /** Its place in a group: a grouped bar chart's series position, else 0. */
  slot: number;
  /** Where the bar starts (the baseline, or the segment it sits on) and
      ends; its label sits past `to`. Numbers for geometry only. */
  from: number;
  to: number;
  tone: Tone;
  /** `null`: the waterfall's unreconciled residual. */
  origin: Origin | null;
  /** Unavailable: the labelled gap is drawn at the baseline instead. */
  gap: boolean;
  /** Sits on another segment of a stack: the 2px surface gap comes off its
      `from` end. */
  stacked?: boolean;
  name: string;
  readout?: string;
  /** Printed past the bar's end when it fits whole; `null` prints nothing. */
  label: string | null;
  /** The label is status copy, drawn in the critical text tint. */
  alarm?: boolean;
  selection: ChartSelection;
}

export interface BandSpec {
  orientation: Orientation;
  categories: readonly string[];
  /** Bars per category side by side: the series of a grouped bar chart. */
  slots: number;
  bars: readonly BandBar[];
  /** Printed past each stack's end: its total. */
  totals?: readonly { category: number; at: number; text: string }[];
  /** Ticks read as percent, over 0 to 100. */
  percent?: boolean;
  /** Join each bar's end to the next bar that spans that level (a bridge). */
  connect?: boolean;
  /** A vertical chart's height, axes included. */
  height?: number;
}

const GAP = 2; // the surface gap between touching marks
const THICK = 24; // no bar is thicker
const LABEL_GAP = 4;
const ROW = 26; // a horizontal chart's least row
const AXIS_BAND = 22; // the band beside the plot its tick labels sit in
const EDGE = 8;
// How far each further gap in one slot steps off the baseline: past the one
// before it, "n/a" and its tick.
const GAP_STEP = { vertical: 14, horizontal: 34 };

/** A series value as a bar from zero: the bar and grouped bar charts' mark,
    and the diverging chart's with its pole's tone and a signed label. */
export function cellBar(
  cell: Cell,
  unit: string | undefined,
  options: { tone?: Tone; signed?: boolean } = {},
): BandBar {
  const { value } = cell;
  return {
    key: `${cell.series.key}:${cell.index}`,
    category: cell.index,
    slot: cell.slot,
    from: 0,
    to: value === null ? 0 : toNumber(value),
    tone: options.tone ?? cell.color,
    origin: cell.origin,
    gap: value === null,
    name: cellName(cell, unit, "", options.signed),
    label: value === null ? null : formatDecimal(value, options.signed),
    selection: cellSelection(cell),
  };
}

const indices = (count: number) => Array.from({ length: count }, (_, index) => index);

/** Which way a bar grows: towards larger values. */
function grows(bar: BandBar): boolean {
  return bar.to >= bar.from;
}

/** Room past the bars on one side for their labels, capped at a share of the width. */
function labelRoom(spec: BandSpec, larger: boolean, width: number): number {
  const texts = [
    ...spec.bars.filter((bar) => !bar.gap && bar.label && grows(bar) === larger),
    ...(larger ? (spec.totals ?? []).map((total) => ({ label: total.text })) : []),
  ].map((item) => textWidth(item.label ?? "", VALUE_SIZE));
  return texts.length ? Math.min(Math.max(...texts) + LABEL_GAP + GAP, width * 0.28) : 0;
}

interface Layout {
  vertical: boolean;
  height: number;
  area: Box;
  /** Value to pixel along the value axis. */
  at: (value: number) => number;
  ticks: readonly Tick[];
  band: ScaleBand<number>;
  /** Room kept for labels past the bars, towards larger and smaller values. */
  room: { up: number; down: number };
}

function extentOf(spec: BandSpec): [number, number] {
  if (spec.percent) return [0, 100];
  const values = [
    0,
    ...spec.bars.filter((bar) => !bar.gap).flatMap((bar) => [bar.from, bar.to]),
    ...(spec.totals ?? []).map((total) => total.at),
  ];
  return [Math.min(...values), Math.max(...values)];
}

function bandOf(count: number, range: [number, number]): ScaleBand<number> {
  return scaleBand<number>()
    .domain(indices(count))
    .range(range)
    .paddingInner(0.2)
    .paddingOuter(0.1);
}

function verticalLayout(spec: BandSpec, width: number): Layout {
  const height = spec.height ?? 240;
  const above = spec.bars.some((bar) => bar.gap || (bar.label && grows(bar)));
  const up = above || spec.totals?.length ? 16 : 4;
  const down = spec.bars.some((bar) => bar.label && !grows(bar)) ? 16 : 0;
  const top = 4;
  const bottom = height - AXIS_BAND;
  const axis = valueTicks(extentOf(spec), [bottom - down, top + up], 44, spec.percent);
  const left = axis.widest + 10;
  return {
    vertical: true,
    height,
    area: { x: left, y: top, width: width - EDGE - left, height: bottom - top },
    at: axis.at,
    ticks: axis.ticks,
    band: bandOf(spec.categories.length, [left, width - EDGE]),
    room: { up, down },
  };
}

function horizontalLayout(spec: BandSpec, width: number): Layout {
  const widest = Math.max(0, ...spec.categories.map((category) => textWidth(category, TICK_SIZE)));
  const left = Math.min(widest, width * 0.38) + 10;
  const up = labelRoom(spec, true, width);
  const down = labelRoom(spec, false, width);
  const axis = valueTicks(extentOf(spec), [left + down, width - EDGE - up], 90, spec.percent);
  const top = 6;
  const bottom = top + spec.categories.length * Math.max(ROW, spec.slots * 14 + 10);
  return {
    vertical: false,
    height: bottom + AXIS_BAND,
    area: { x: left, y: top, width: width - EDGE - left, height: bottom - top },
    at: axis.at,
    ticks: axis.ticks,
    band: bandOf(spec.categories.length, [top, bottom]),
    room: { up, down },
  };
}

/** The drawn box of a bar: centred in its slot, no thicker than 24px, never
    shorter than a 1px hairline (a zero still shows), less the 2px surface
    gap where it sits on another segment. */
function barBox(bar: BandBar, layout: Layout, slots: number): Box {
  const sub = layout.band.bandwidth() / slots;
  const thick = Math.max(1, Math.min(THICK, sub - GAP));
  const along = (layout.band(bar.category) ?? 0) + bar.slot * sub + (sub - thick) / 2;
  let start = layout.at(bar.from);
  let end = layout.at(bar.to);
  if (bar.stacked && Math.abs(end - start) > GAP) start += Math.sign(end - start) * GAP;
  if (Math.abs(end - start) < 1) end = start + (layout.vertical ? -1 : 1);
  const low = Math.min(start, end);
  const length = Math.abs(end - start);
  return layout.vertical
    ? { x: along, y: low, width: thick, height: length }
    : { x: low, y: along, width: length, height: thick };
}

/** Where an unavailable bar's gap is marked: its slot, on the baseline, or
    stepped off it past the `earlier` gaps already marked in that slot (two
    segments of one stack), so no two "n/a" marks overprint. */
function gapPoint(
  bar: BandBar,
  layout: Layout,
  slots: number,
  earlier: number,
): { x: number; y: number } {
  const sub = layout.band.bandwidth() / slots;
  const along = (layout.band(bar.category) ?? 0) + (bar.slot + 0.5) * sub;
  const base = layout.at(0);
  return layout.vertical
    ? { x: along, y: base - earlier * GAP_STEP.vertical }
    : { x: base + earlier * GAP_STEP.horizontal, y: along };
}

function gapBox(point: { x: number; y: number }, vertical: boolean): Box {
  return vertical
    ? { x: point.x - 10, y: point.y - 20, width: 20, height: 20 }
    : { x: point.x, y: point.y - 8, width: 30, height: 16 };
}

/** A value label past the bar's end, or nothing when it would not fit whole:
    a label is never clipped by its mark or crowded into its neighbour's. */
function labelOf(bar: BandBar, box: Box, layout: Layout, slots: number): Placed | null {
  if (!bar.label) return null;
  const up = grows(bar);
  const wide = textWidth(bar.label, VALUE_SIZE);
  if (layout.vertical) {
    const room = slots === 1 ? layout.band.step() : layout.band.bandwidth() / slots;
    if (wide > room - GAP) return null;
    const x = box.x + box.width / 2;
    const y = up ? box.y - LABEL_GAP : box.y + box.height + LABEL_GAP + VALUE_SIZE - 2;
    return { text: bar.label, x, y, anchor: "middle" };
  }
  if (wide + LABEL_GAP > (up ? layout.room.up : layout.room.down)) return null;
  const y = box.y + box.height / 2 + VALUE_SIZE / 2 - 2;
  return up
    ? { text: bar.label, x: box.x + box.width + LABEL_GAP, y, anchor: "start" }
    : { text: bar.label, x: box.x - LABEL_GAP, y, anchor: "end" };
}

function totalOf(
  total: { category: number; at: number; text: string },
  layout: Layout,
): Placed | null {
  const centre = (layout.band(total.category) ?? 0) + layout.band.bandwidth() / 2;
  const end = layout.at(total.at);
  if (layout.vertical) {
    if (textWidth(total.text, VALUE_SIZE) > layout.band.step() - GAP) return null;
    return { text: total.text, x: centre, y: end - LABEL_GAP, anchor: "middle" };
  }
  return { text: total.text, x: end + LABEL_GAP, y: centre + VALUE_SIZE / 2 - 2, anchor: "start" };
}

/** Category labels: along a vertical chart's axis, thinned to what fits;
    beside a horizontal chart's rows, each cut to its room. */
function categoryLabels(spec: BandSpec, layout: Layout): Placed[] {
  const { band, area } = layout;
  const centre = (index: number) => (band(index) ?? 0) + band.bandwidth() / 2;
  if (layout.vertical) {
    return acrossLabels(spec.categories, centre, band.step(), area.y + area.height + 14);
  }
  return spec.categories.map((category, index) => ({
    text: fitText(category, area.x - 10, TICK_SIZE),
    x: area.x - 8,
    y: centre(index) + TICK_SIZE / 2 - 1.5,
    anchor: "end",
  }));
}

/** A bridge's running level, carried from each bar to the next that spans it. */
function connectors(spec: BandSpec, boxes: ReadonlyMap<string, Box>, layout: Layout) {
  const bars = spec.bars.filter((bar) => !bar.gap);
  return bars.slice(1).flatMap((next, index) => {
    const bar = bars[index];
    const from = bar && boxes.get(bar.key);
    const to = boxes.get(next.key);
    if (!bar || !from || !to || next.category !== bar.category + 1) return [];
    if (bar.to < Math.min(next.from, next.to) || bar.to > Math.max(next.from, next.to)) return [];
    const level = layout.at(bar.to);
    return [
      layout.vertical
        ? { key: bar.key, x1: from.x + from.width, x2: to.x, y1: level, y2: level }
        : { key: bar.key, x1: level, x2: level, y1: from.y + from.height, y2: to.y },
    ];
  });
}

/** Lay out and draw a band chart at `width`. */
export function bandPlot(spec: BandSpec, width: number, hatch: Hatch): Plot {
  const vertical = spec.orientation === "vertical";
  const layout = vertical ? verticalLayout(spec, width) : horizontalLayout(spec, width);
  const boxes = new Map<string, Box>();
  const gaps = new Map<string, { x: number; y: number }>();
  const marked = new Map<string, number>();
  for (const bar of spec.bars) {
    if (!bar.gap) {
      boxes.set(bar.key, barBox(bar, layout, spec.slots));
      continue;
    }
    const slot = `${bar.category}:${bar.slot}`;
    const earlier = marked.get(slot) ?? 0;
    marked.set(slot, earlier + 1);
    gaps.set(bar.key, gapPoint(bar, layout, spec.slots, earlier));
  }
  // Tab follows the eye: category by category, and slot by slot within one.
  const marks: MarkHit[] = [...spec.bars]
    .sort((a, b) => a.category - b.category || a.slot - b.slot)
    .flatMap((bar) => {
      const point = gaps.get(bar.key);
      const box = point ? gapBox(point, vertical) : boxes.get(bar.key);
      if (!box) return [];
      return [
        { key: bar.key, name: bar.name, readout: bar.readout, box, selection: bar.selection },
      ];
    });
  const shapes = spec.bars.map((bar) => {
    const point = gaps.get(bar.key);
    if (point) {
      return <GapMark key={bar.key} mark={bar.key} x={point.x} y={point.y} vertical={vertical} />;
    }
    const box = boxes.get(bar.key);
    return box ? (
      <BarShape
        key={bar.key}
        mark={bar.key}
        box={box}
        tone={bar.tone}
        origin={bar.origin}
        hatch={hatch}
      />
    ) : null;
  });
  const labels = spec.bars.flatMap((bar) => {
    const box = boxes.get(bar.key);
    const placed = box ? labelOf(bar, box, layout, spec.slots) : null;
    return placed ? [{ key: bar.key, alarm: bar.alarm, placed }] : [];
  });
  const totals = (spec.totals ?? []).flatMap((total) => {
    const placed = totalOf(total, layout);
    return placed ? [{ key: `${total.category}`, placed }] : [];
  });
  const hatched = [
    ...new Set(spec.bars.filter((bar) => !bar.gap && bar.origin !== "host").map((bar) => bar.tone)),
  ];
  const body = (
    <>
      <ValueGrid ticks={layout.ticks} area={layout.area} vertical={vertical} zero={layout.at(0)} />
      {categoryLabels(spec, layout).map((placed, index) => (
        <Label key={`category-${index}`} className="chart-tick" placed={placed} />
      ))}
      {spec.connect
        ? connectors(spec, boxes, layout).map(({ key, ...ends }) => (
            <line key={`join-${key}`} className="chart-connector" {...ends} />
          ))
        : null}
      {shapes}
      {labels.map(({ key, alarm, placed }) => (
        <Label
          key={`label-${key}`}
          className={alarm ? "chart-value chart-alarm" : "chart-value"}
          placed={placed}
        />
      ))}
      {totals.map(({ key, placed }) => (
        <Label key={`total-${key}`} className="chart-value" placed={placed} />
      ))}
    </>
  );
  return { height: layout.height, area: layout.area, body, marks, hatched };
}

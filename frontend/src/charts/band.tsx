// Band charts: bars on a band axis against one linear value axis, either way
// up. The bar, stacked, waterfall and diverging charts are this one geometry
// with different bars: each chart says what its bars mean, this says where
// they go. Recharts draws the axes, grid and bars (D61); the bars are this
// module's shapes, so provenance stays in the mark, and what Recharts has no
// word for -- an unavailable value's "n/a", a label that is left out rather
// than clipped, a stack's total, a bridge's joins, a value marked across its
// row (a threshold's rule, a borrower's dot) -- is drawn here from the same
// geometry. One value axis always, holding zero (no dual axis, no
// floating baseline); bars no thicker than 24px, with square ends.
import { Bar, BarChart, CartesianGrid, XAxis, YAxis } from "recharts";
import { Focus, Reported, useMarks } from "./ChartFrame";
import {
  Label,
  TickText,
  shownCategories,
  valueTick,
  valueTicks,
  type Placed,
  type Tick,
} from "./axes";
import { formatDecimal, toNumber } from "./decimal";
import { BarShape, DOT, GapMark, HatchPatterns, MarkerShape } from "./marks";
import { TICK_SIZE, VALUE_SIZE, fitLines, textWidth } from "./scale";
import { cellName, cellSelection, type Cell } from "./series";
import type { Box, ChartSelection, Orientation, Origin, Plot, PlotKit, Tone } from "./types";

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

/** One value marked across its category's band rather than as a bar from
    zero: a threshold's `rule`, a statistic's or an end's `dot`. */
export interface BandMarker {
  key: string;
  category: number;
  /** Where it stands on the value axis. A number for geometry only. */
  at: number;
  tone: Tone;
  origin: Origin;
  /** Unavailable: the labelled gap is drawn in its row instead. */
  gap: boolean;
  /** A line across the band, perpendicular to the value axis; or a point at
      the band's centre. */
  shape: "rule" | "dot";
  name: string;
  readout?: string;
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
  /** Values marked across their rows, reached after their category's bars. */
  markers?: readonly BandMarker[];
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
const BAND_FILL = 0.8; // a band's share its bars may take; the rest parts them
const RULE_OVER = 4; // how far a rule stands past its bars each side
const RULE_WIDTH = 2; // a rule's stroke (.chart-line)
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

function extentOf(spec: BandSpec): [number, number] {
  if (spec.percent) return [0, 100];
  const values = [
    0,
    ...spec.bars.filter((bar) => !bar.gap).flatMap((bar) => [bar.from, bar.to]),
    ...(spec.totals ?? []).map((total) => total.at),
    ...(spec.markers ?? []).filter((marker) => !marker.gap).map((marker) => marker.at),
  ];
  return [Math.min(...values), Math.max(...values)];
}

/** Where everything goes: the plot area Recharts lays out from the same
    margins and axis sizes, the value axis, and the band geometry. */
interface Layout {
  vertical: boolean;
  width: number;
  height: number;
  /** The plot area inside the axes. */
  area: Box;
  /** The category axis's width beside a horizontal chart. */
  across: number;
  /** Room kept inside the plot for labels past the bars. */
  room: { up: number; down: number };
  axis: { domain: [number, number]; ticks: readonly Tick[]; at: (value: number) => number };
  /** A category band's length, and a bar's thickness. */
  step: number;
  thick: number;
}

function layoutOf(spec: BandSpec, width: number): Layout {
  const vertical = spec.orientation === "vertical";
  const count = Math.max(1, spec.categories.length);
  if (vertical) {
    const height = spec.height ?? 240;
    const above =
      spec.bars.some((bar) => bar.gap || (bar.label && grows(bar))) ||
      (spec.markers ?? []).some((marker) => marker.gap);
    const up = above || spec.totals?.length ? 16 : 4;
    const down = spec.bars.some((bar) => bar.label && !grows(bar)) ? 16 : 0;
    const top = 4;
    const bottom = height - AXIS_BAND;
    const axis = valueTicks(extentOf(spec), [bottom - down, top + up], 44, spec.percent);
    const left = axis.widest + 10;
    const area = { x: left, y: top, width: width - EDGE - left, height: bottom - top };
    const step = area.width / count;
    return {
      vertical,
      width,
      height,
      area,
      across: left,
      room: { up, down },
      axis,
      step,
      thick: Math.max(1, Math.min(THICK, (step * BAND_FILL) / spec.slots - GAP)),
    };
  }
  const widest = Math.max(0, ...spec.categories.map((category) => textWidth(category, TICK_SIZE)));
  const left = Math.min(widest, width * 0.38) + 10;
  const up = labelRoom(spec, true, width);
  const down = labelRoom(spec, false, width);
  const axis = valueTicks(extentOf(spec), [left + down, width - EDGE - up], 90, spec.percent);
  const top = 6;
  // A row is tall enough for the most lines any category name wraps to.
  const lines = Math.max(
    1,
    ...spec.categories.map((category) => fitLines(category, left - 10, TICK_SIZE).length),
  );
  const row = Math.max(ROW, spec.slots * 14 + 10, lines * (TICK_SIZE + 1) + 6);
  const area = { x: left, y: top, width: width - EDGE - left, height: count * row };
  return {
    vertical,
    width,
    height: top + area.height + AXIS_BAND,
    area,
    across: left,
    room: { up, down },
    axis,
    step: row,
    thick: Math.max(1, Math.min(THICK, (row * BAND_FILL) / spec.slots - GAP)),
  };
}

/** The centre of a category's band, across the band axis. */
function centreOf(layout: Layout, category: number): number {
  const start = layout.vertical ? layout.area.x : layout.area.y;
  return start + layout.step * (category + 0.5);
}

/** The centre of a slot within its category's band, as Recharts places a
    group of bars `thick` wide, `GAP` apart, centred. */
function slotCentre(layout: Layout, category: number, slot: number, slots: number): number {
  const group = slots * layout.thick + (slots - 1) * GAP;
  return centreOf(layout, category) - group / 2 + slot * (layout.thick + GAP) + layout.thick / 2;
}

/** The drawn box of a bar from Recharts' rectangle: never shorter than a 1px
    hairline (a zero still shows), less the 2px surface gap where it sits on
    another segment. */
function drawnBox(bar: BandBar, rect: Box, vertical: boolean): Box {
  let x = Math.min(rect.x, rect.x + rect.width);
  let y = Math.min(rect.y, rect.y + rect.height);
  let width = Math.abs(rect.width);
  let height = Math.abs(rect.height);
  const up = grows(bar);
  if (bar.stacked) {
    if (vertical && height > GAP) {
      height -= GAP;
      if (!up) y += GAP;
    } else if (!vertical && width > GAP) {
      width -= GAP;
      if (up) x += GAP;
    }
  }
  if (vertical && height < 1) {
    if (up) y -= 1 - height;
    height = 1;
  }
  if (!vertical && width < 1) {
    if (!up) x -= 1 - width;
    width = 1;
  }
  return { x, y, width, height };
}

/** Where an unavailable value's gap is marked: `along` its band (a bar's
    slot, a marker's centre), on the baseline, or stepped off it past the
    `earlier` gaps already marked there (two segments of one stack, a bar and
    its marker), so no two "n/a" marks overprint. */
function gapPoint(along: number, layout: Layout, earlier: number) {
  const base = layout.axis.at(0);
  return layout.vertical
    ? { x: along, y: base - earlier * GAP_STEP.vertical }
    : { x: base + earlier * GAP_STEP.horizontal, y: along };
}

function gapBox(point: { x: number; y: number }, vertical: boolean): Box {
  return vertical
    ? { x: point.x - 10, y: point.y - 20, width: 20, height: 20 }
    : { x: point.x, y: point.y - 8, width: 30, height: 16 };
}

/** A stretch along the value axis, in plot pixels, low end first. */
type Span = readonly [number, number];

/** A rule's length across its band: past its bars by `RULE_OVER` each side,
    but never into the next band. */
function ruleSpan(layout: Layout, slots: number): number {
  const group = slots * layout.thick + (slots - 1) * GAP;
  return Math.min(layout.step - 2 * GAP, group + 2 * RULE_OVER);
}

/** Where a marker is drawn: a rule's two ends (a dot sits at their midpoint),
    its box, and the stretch of the value axis it covers. */
function markerPlace(marker: BandMarker, layout: Layout, slots: number) {
  const centre = centreOf(layout, marker.category);
  const at = layout.axis.at(marker.at);
  const dot = marker.shape === "dot";
  const half = dot ? 0 : ruleSpan(layout, slots) / 2; // the rule's half-length
  const reach = dot ? DOT : half; // the box's half-extent across the band
  const across = dot ? DOT : RULE_WIDTH / 2; // and along the value axis
  const span: Span = [at - across, at + across];
  return layout.vertical
    ? {
        line: { x1: centre - half, x2: centre + half, y1: at, y2: at },
        box: { x: centre - reach, y: at - across, width: 2 * reach, height: 2 * across },
        span,
      }
    : {
        line: { x1: at, x2: at, y1: centre - half, y2: centre + half },
        box: { x: at - across, y: centre - reach, width: 2 * across, height: 2 * reach },
        span,
      };
}

/** A label's stretch along the value axis: across its text sideways, its
    height upright. */
function labelSpan(placed: Placed, wide: number, vertical: boolean): Span {
  if (vertical) return [placed.y - VALUE_SIZE, placed.y];
  return placed.anchor === "start" ? [placed.x, placed.x + wide] : [placed.x - wide, placed.x];
}

/** A value label past the bar's end, or nothing when it would not fit whole
    or a marker in its row would cross it: a label is never clipped by its
    mark, crowded into its neighbour's or struck through. */
function labelOf(
  bar: BandBar,
  box: Box,
  layout: Layout,
  slots: number,
  marked: readonly Span[],
): Placed | null {
  if (!bar.label) return null;
  const up = grows(bar);
  const wide = textWidth(bar.label, VALUE_SIZE);
  let placed: Placed;
  if (layout.vertical) {
    const room = slots === 1 ? layout.step : (layout.step * BAND_FILL) / slots;
    if (wide > room - GAP) return null;
    const x = box.x + box.width / 2;
    const y = up ? box.y - LABEL_GAP : box.y + box.height + LABEL_GAP + VALUE_SIZE - 2;
    placed = { text: bar.label, x, y, anchor: "middle" };
  } else {
    if (wide + LABEL_GAP > (up ? layout.room.up : layout.room.down)) return null;
    const y = box.y + box.height / 2 + VALUE_SIZE / 2 - 2;
    placed = up
      ? { text: bar.label, x: box.x + box.width + LABEL_GAP, y, anchor: "start" }
      : { text: bar.label, x: box.x - LABEL_GAP, y, anchor: "end" };
  }
  const [low, high] = labelSpan(placed, wide, layout.vertical);
  const struck = marked.some(([from, to]) => from < high + GAP && low < to + GAP);
  return struck ? null : placed;
}

function totalOf(
  total: { category: number; at: number; text: string },
  layout: Layout,
): Placed | null {
  const centre = centreOf(layout, total.category);
  const end = layout.axis.at(total.at);
  if (layout.vertical) {
    if (textWidth(total.text, VALUE_SIZE) > layout.step - GAP) return null;
    return { text: total.text, x: centre, y: end - LABEL_GAP, anchor: "middle" };
  }
  return { text: total.text, x: end + LABEL_GAP, y: centre + VALUE_SIZE / 2 - 2, anchor: "start" };
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
    const level = layout.axis.at(bar.to);
    return [
      layout.vertical
        ? { key: bar.key, x1: from.x + from.width, x2: to.x, y1: level, y2: level }
        : { key: bar.key, x1: level, x2: level, y1: from.y + from.height, y2: to.y },
    ];
  });
}

/** Every unavailable value's gap: a bar's in its slot, a marker's at its
    band's centre past every gap already marked in that band. */
function gapsOf(spec: BandSpec, layout: Layout) {
  // `slot` null: a marker's, which steps past every gap in its band.
  const unavailable: { mark: BandBar | BandMarker; slot: number | null; along: number }[] = [
    ...spec.bars
      .filter((bar) => bar.gap)
      .map((bar) => ({
        mark: bar,
        slot: bar.slot,
        along: slotCentre(layout, bar.category, bar.slot, spec.slots),
      })),
    ...(spec.markers ?? [])
      .filter((marker) => marker.gap)
      .map((marker) => ({ mark: marker, slot: null, along: centreOf(layout, marker.category) })),
  ];
  return unavailable.map((gap, index) => {
    const earlier = unavailable
      .slice(0, index)
      .filter(
        (other) =>
          other.mark.category === gap.mark.category &&
          (gap.slot === null || other.slot === gap.slot),
      ).length;
    return { mark: gap.mark, point: gapPoint(gap.along, layout, earlier) };
  });
}

/** A marker drawn in its shape and reported to the frame, so a button can be
    laid over it. */
function Marker({ marker, place }: { marker: BandMarker; place: ReturnType<typeof markerPlace> }) {
  return (
    <>
      <MarkerShape
        mark={marker.key}
        shape={marker.shape}
        line={place.line}
        tone={marker.tone}
        origin={marker.origin}
      />
      <Reported
        mark={{
          key: marker.key,
          name: marker.name,
          readout: marker.readout,
          box: place.box,
          round: marker.shape === "dot",
          selection: marker.selection,
        }}
      />
    </>
  );
}

/** Everything drawn past the bars: markers, gaps, labels, totals, joins and
    the zero baseline. Labels and joins follow the bars' boxes as Recharts
    drew them. */
function Annotations({ spec, layout }: { spec: BandSpec; layout: Layout }) {
  const marks = useMarks();
  const boxes = new Map(
    spec.bars.flatMap((bar) => {
      const mark = marks.get(bar.key);
      return !bar.gap && mark ? [[bar.key, mark.box] as const] : [];
    }),
  );
  const markers = (spec.markers ?? [])
    .filter((marker) => !marker.gap)
    .map((marker) => ({ marker, place: markerPlace(marker, layout, spec.slots) }));
  const markedIn = (category: number) =>
    markers.filter((drawn) => drawn.marker.category === category).map((drawn) => drawn.place.span);
  const gaps = gapsOf(spec, layout);
  const { area, vertical } = layout;
  const zero = layout.axis.at(0);
  return (
    <g className="chart-annotations">
      {vertical ? (
        <line className="chart-zero" x1={area.x} x2={area.x + area.width} y1={zero} y2={zero} />
      ) : (
        <line className="chart-zero" x1={zero} x2={zero} y1={area.y} y2={area.y + area.height} />
      )}
      {spec.connect
        ? connectors(spec, boxes, layout).map(({ key, ...ends }) => (
            <line key={`join-${key}`} className="chart-connector" {...ends} />
          ))
        : null}
      {markers.map(({ marker, place }) => (
        <Marker key={marker.key} marker={marker} place={place} />
      ))}
      {gaps.map(({ mark, point }) => (
        <g key={mark.key}>
          <GapMark mark={mark.key} x={point.x} y={point.y} vertical={vertical} />
          <Reported
            mark={{
              key: mark.key,
              name: mark.name,
              readout: mark.readout,
              box: gapBox(point, vertical),
              selection: mark.selection,
            }}
          />
        </g>
      ))}
      {spec.bars.map((bar) => {
        const box = boxes.get(bar.key);
        const placed = box ? labelOf(bar, box, layout, spec.slots, markedIn(bar.category)) : null;
        return placed ? (
          <Label
            key={`label-${bar.key}`}
            className={bar.alarm ? "chart-value chart-alarm" : "chart-value"}
            placed={placed}
          />
        ) : null;
      })}
      {(spec.totals ?? []).map((total) => {
        const placed = totalOf(total, layout);
        return placed ? (
          <Label key={`total-${total.category}`} className="chart-value" placed={placed} />
        ) : null;
      })}
    </g>
  );
}

/** A bar as Recharts places it, drawn in this module's shape and reported to
    the frame so a button can be laid over it. */
function BandMark({
  bar,
  rect,
  vertical,
  hatch,
}: {
  bar: BandBar;
  rect: Box;
  vertical: boolean;
  hatch: PlotKit["hatch"];
}) {
  const box = drawnBox(bar, rect, vertical);
  return (
    <>
      <BarShape mark={bar.key} box={box} tone={bar.tone} origin={bar.origin} hatch={hatch} />
      <Reported
        mark={{
          key: bar.key,
          name: bar.name,
          readout: bar.readout,
          box,
          selection: bar.selection,
        }}
      />
    </>
  );
}

interface RectProps {
  x?: number;
  y?: number;
  width?: number;
  height?: number;
  payload?: Record<string, unknown>;
}

/** Lay out and draw a band chart. */
export function bandPlot(spec: BandSpec, kit: PlotKit): Plot {
  const layout = layoutOf(spec, kit.width);
  const { vertical } = layout;
  const byKey = new Map(spec.bars.map((bar) => [bar.key, bar]));
  // A lane is one Recharts `<Bar>`: a slot of a group, and within a slot one
  // layer of a stack. A category holds at most one bar per lane; stacked
  // layers share their slot's place, so they are laid over one another.
  const layers = new Map<string, number>();
  const laneOf = new Map<string, string>();
  for (const bar of spec.bars) {
    const at = `${bar.category}:${bar.slot}`;
    const layer = layers.get(at) ?? 0;
    layers.set(at, layer + 1);
    laneOf.set(bar.key, `l${bar.slot}_${layer}`);
  }
  const lanes = [...new Set(laneOf.values())].sort();
  const stacked = Math.max(0, ...layers.values()) > 1;
  const rows = spec.categories.map((category, index) => {
    const row: Record<string, unknown> = { category, index };
    for (const bar of spec.bars) {
      if (bar.category !== index || bar.gap) continue;
      const lane = laneOf.get(bar.key)!;
      row[lane] = [bar.from, bar.to];
      row[`${lane}_key`] = bar.key;
    }
    return row;
  });
  const shown = vertical ? shownCategories(spec.categories, layout.step) : null;
  const tickText = (index: number) =>
    vertical
      ? (shown?.[index] ?? null)
      : fitLines(spec.categories[index] ?? "", layout.across - 10, TICK_SIZE);
  const values = {
    type: "number" as const,
    domain: layout.axis.domain,
    ticks: layout.axis.ticks.map((tick) => tick.value),
    tick: valueTick(layout.axis.ticks, vertical ? "left" : "bottom"),
    axisLine: false,
    tickLine: false,
    allowDataOverflow: true,
    interval: 0 as const,
  };
  const categoryTick = (props: {
    x?: number | string;
    y?: number | string;
    payload?: { value?: unknown };
  }) => {
    const index = spec.categories.indexOf(String(props.payload?.value ?? ""));
    return vertical ? (
      <TickText x={props.x} y={props.y} dy={10} text={tickText(index)} anchor="middle" />
    ) : (
      <TickText
        x={props.x}
        y={props.y}
        dy={TICK_SIZE / 2 - 1.5}
        text={tickText(index)}
        anchor="end"
      />
    );
  };
  const hatched = [
    ...new Set(spec.bars.filter((bar) => !bar.gap && bar.origin !== "host").map((bar) => bar.tone)),
  ];
  const chart = (
    <BarChart
      {...kit.svg}
      className="chart-svg"
      width={layout.width}
      height={layout.height}
      data={rows}
      layout={vertical ? "horizontal" : "vertical"}
      margin={{ top: layout.area.y, right: EDGE, bottom: 0, left: 0 }}
      barSize={layout.thick}
      barGap={stacked ? -layout.thick : GAP}
      accessibilityLayer={false}
    >
      <HatchPatterns id={kit.patternId} tones={hatched} />
      <CartesianGrid
        className="chart-grid"
        horizontal={vertical}
        vertical={!vertical}
        horizontalPoints={vertical ? layout.axis.ticks.map((tick) => tick.position) : undefined}
        verticalPoints={vertical ? undefined : layout.axis.ticks.map((tick) => tick.position)}
      />
      {vertical ? (
        <>
          <XAxis
            dataKey="category"
            type="category"
            height={AXIS_BAND}
            axisLine={false}
            tickLine={false}
            interval={0}
            tick={categoryTick}
          />
          <YAxis
            {...values}
            width={layout.across}
            padding={{ top: layout.room.up, bottom: layout.room.down }}
          />
        </>
      ) : (
        <>
          <XAxis
            {...values}
            height={AXIS_BAND}
            padding={{ left: layout.room.down, right: layout.room.up }}
          />
          <YAxis
            dataKey="category"
            type="category"
            width={layout.across}
            axisLine={false}
            tickLine={false}
            interval={0}
            tick={categoryTick}
          />
        </>
      )}
      {lanes.map((lane) => (
        <Bar
          key={lane}
          dataKey={lane}
          isAnimationActive={false}
          minPointSize={1}
          shape={(props: RectProps) => {
            const bar = byKey.get(String(props.payload?.[`${lane}_key`] ?? ""));
            if (!bar) return <g />;
            const rect = {
              x: props.x ?? 0,
              y: props.y ?? 0,
              width: props.width ?? 0,
              height: props.height ?? 0,
            };
            return <BandMark bar={bar} rect={rect} vertical={vertical} hatch={kit.hatch} />;
          }}
        />
      ))}
      <Annotations spec={spec} layout={layout} />
      <Focus />
    </BarChart>
  );
  // Tab follows the eye: category by category, slot by slot within one, then
  // the category's markers in the order given (the sort is stable).
  const order = [
    ...spec.bars.map((bar) => ({ key: bar.key, category: bar.category, rank: bar.slot })),
    ...(spec.markers ?? []).map((marker) => ({
      key: marker.key,
      category: marker.category,
      rank: spec.slots,
    })),
  ]
    .sort((a, b) => a.category - b.category || a.rank - b.rank)
    .map((entry) => entry.key);
  return { height: layout.height, chart, order };
}

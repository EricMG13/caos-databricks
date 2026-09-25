// The chart data contract. Types only: this file is erased at build and ships
// nothing. Values are the API's exact decimal strings; a chart converts one to
// a number only to place a mark, never to print it.
import type { ReactNode } from "react";

/** An exact decimal as the wire serves it: `^-?[0-9]+(\.[0-9]+)?$`. */
export type Decimal = string;

/** Who stands behind a figure: `host` is host-verified; `model` is
    model-authored and not host-verified. Drawn in the mark: solid for the
    host, outlined and hatched for the model. */
export type Origin = "host" | "model";

/** One value, or `null` with the reason it is unavailable. */
export interface Datum {
  value: Decimal | null;
  /** Why the value is null, in the document's own words. */
  reason?: string | null;
  /** Overrides the series' origin for this one mark. */
  origin?: Origin;
}

/** A colour a series may wear. Every one is a token (`styles/charts.css`,
    `styles/tokens.css`): `series-1..5` the validated categorical ramp,
    `tranche-*` debt seniority, `neutral` a stated total or a series past the
    fifth, `positive`/`negative` the two diverging poles. */
export type ChartColor =
  | "series-1"
  | "series-2"
  | "series-3"
  | "series-4"
  | "series-5"
  | "neutral"
  | "positive"
  | "negative"
  | "tranche-1l"
  | "tranche-2l"
  | "tranche-unsec"
  | "tranche-sub"
  | "tranche-eq";

/** A mark's colour: a series colour, or the reserved critical hue of a
    waterfall's unreconciled residual. */
export type Tone = ChartColor | "residual";

export interface ChartSeries {
  /** Stable identity, returned in a selection. */
  key: string;
  label: string;
  origin: Origin;
  /** Colour follows the series, not its position: pass one when a series
      must keep its hue across charts. Default: `series-N` by position, and
      `neutral` past the fifth. A single-series chart defaults to `series-1`. */
  color?: ChartColor;
  /** One datum per category, in the categories' order. */
  data: readonly Datum[];
}

/** What a pressed mark hands to `onSelect`. */
export interface ChartSelection {
  /** The series key; a waterfall step's key. */
  series: string;
  /** The category as labelled: a period, a source, a step. */
  category: string;
  /** The category's position. */
  index: number;
  value: Decimal | null;
  /** `null` only for a waterfall's unreconciled residual: nobody served it. */
  origin: Origin | null;
  /** A waterfall step's kind; absent elsewhere. */
  kind?: "total" | "delta" | "residual";
}

export type OnSelect = (selection: ChartSelection, opener: HTMLElement) => void;

export type Orientation = "vertical" | "horizontal";

export interface ChartProps {
  /** The figure's title: what is plotted. */
  title: string;
  /** One plain-language sentence: what the chart shows. */
  summary: string;
  /** Printed after every value: "USD m", "x", "%". */
  unit?: string;
  onSelect?: OnSelect;
}

export interface SeriesChartProps extends ChartProps {
  /** Labels along the category axis, in order: periods, sources, line items. */
  categories: readonly string[];
  series: readonly ChartSeries[];
  /** What the categories are, heading the table twin's first column:
      "Period", "Source". Default "Category". */
  categoryLabel?: string;
}

/** One step of a bridge. A `total` is stated by the data; a `delta` moves the
    running level from the step before it. */
export interface WaterfallStep {
  key?: string;
  label: string;
  kind: "total" | "delta";
  value: Decimal | null;
  reason?: string | null;
  origin: Origin;
}

// What a chart hands its frame: the drawing, and every mark a reader can reach.

export interface Box {
  x: number;
  y: number;
  width: number;
  height: number;
}

/** One focusable mark. */
export interface MarkHit {
  key: string;
  /** The accessible name: series, category, exact value, unit, origin. */
  name: string;
  /** What the readout line shows while the mark is active; the name if absent. */
  readout?: string;
  /** The drawn mark, in plot pixels; the hit target grows from it to 24px. */
  box: Box;
  /** A point: circled, not boxed, when selected. */
  round?: boolean;
  /** Where a vertical guide runs while the mark is active (a line chart's x). */
  guide?: number;
  selection: ChartSelection;
}

/** The fill that hatches a model-authored mark of `tone`, as a `url(#…)`. */
export type Hatch = (tone: Tone) => string;

/** What the frame lends a chart to draw with (D61). */
export interface PlotKit {
  /** The container's width in CSS pixels: the chart draws at it, unscaled. */
  width: number;
  hatch: Hatch;
  /** The `<pattern>` id a hatched tone's fill refers to. */
  patternId: (tone: Tone) => string;
  /** The picture's role and name, for the chart's SVG. */
  svg: { role: "img"; "aria-labelledby": string };
}

/** A chart as drawn: Recharts' element, its height, and the order Tab and the
    arrow keys take through its marks, which report themselves from inside it. */
export interface Plot {
  height: number;
  chart: ReactNode;
  /** Mark keys in reading order: category by category, slot by slot. */
  order: readonly string[];
}

export interface LegendEntry {
  key: string;
  label: string;
  tone: Tone;
  /** A swatch for bars, a stroke for lines. */
  shape: "fill" | "line";
  /** Drawn in the series' own form; solid when absent, outlined when `null`
      (the residual, which nobody served). */
  origin?: Origin | null;
}

/** The chart's table twin: `head` names the columns, each row's first cell is
    its header. Every cell is text the chart printed, exact. */
export interface TableTwin {
  head: readonly string[];
  rows: readonly { key: string; cells: readonly string[] }[];
}

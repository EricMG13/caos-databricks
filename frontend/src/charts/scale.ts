// Scales and type metrics. d3-scale is maths only (decision: charts are drawn
// by React as SVG); nothing here touches the DOM.
import { scaleLinear } from "d3-scale";
import { formatDecimal, isDecimal } from "./decimal";

/** The width a chart draws at before its container has been measured, and
    wherever there is nothing to measure with (jsdom). */
export const FALLBACK_WIDTH = 640;

/** Chart type (DESIGN.md): ticks 11px mono, data labels 12px mono, titles
    14px sans. SVG text is drawn at these pixel sizes and never scaled. */
export const TICK_SIZE = 11;
export const VALUE_SIZE = 12;

// Every face in --font-mono advances within 0.62em per glyph (Geist Mono,
// SF Mono and Menlo 0.60, Consolas 0.55), so a width estimated at 0.62 is
// never short. Estimated, not measured: jsdom has no layout to measure.
const ADVANCE = 0.62;

/** The width `text` takes in the mono face at `size` px. */
export function textWidth(text: string, size: number): number {
  return text.length * size * ADVANCE;
}

/** `text` cut to fit `room` px at `size`, ending in an ellipsis when cut. The
    whole label stays in the accessible name, the readout and the table. */
export function fitText(text: string, room: number, size: number): string {
  const fits = Math.floor(room / (size * ADVANCE));
  if (text.length <= fits) return text;
  return fits <= 1 ? "…" : `${text.slice(0, fits - 1)}…`;
}

/** A linear scale over `extent` with nice ends, and its ticks. An extent with
    no length (every value zero, or none) is widened to [0, 1] so it draws. */
export function valueScale(
  extent: readonly [number, number],
  range: readonly [number, number],
  count: number,
) {
  const [low, high] = extent[0] === extent[1] ? [Math.min(0, extent[0]), 1] : extent;
  const scale = scaleLinear().domain([low, high]).range(range).nice(count);
  return { scale, ticks: scale.ticks(count) };
}

/** Tick labels at the fewest decimals that state every tick: `toFixed` prints
    the nice number d3 meant, not its float residue, so 0.30000000000000004
    on a 0.1 step reads "0.3". Digits grouped like every other figure. */
export function tickLabels(ticks: readonly number[]): string[] {
  let places = 0;
  while (
    places < 12 &&
    !ticks.every(
      (tick) => Math.abs(Number(tick.toFixed(places)) - tick) <= 1e-9 * Math.max(1, Math.abs(tick)),
    )
  ) {
    places += 1;
  }
  return ticks.map((tick) => {
    const text = (Object.is(tick, -0) ? 0 : tick).toFixed(places);
    return isDecimal(text) ? formatDecimal(text) : text;
  });
}

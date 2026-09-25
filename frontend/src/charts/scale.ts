// Scales and type metrics: plain maths, no DOM. Recharts draws the axes
// (D61); the ticks it draws are the ones chosen here, so a chart's axis reads
// the same nice numbers whatever library places them.

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
  // The room is often `textWidth` of the widest label itself, and 13 × 6.82
  // ÷ 6.82 is 12.999… in floating point: without the tolerance the widest
  // label was always cut by its last character.
  const fits = Math.floor(room / (size * ADVANCE) + 1e-9);
  if (text.length <= fits) return text;
  return fits <= 1 ? "…" : `${text.slice(0, fits - 1)}…`;
}

/** `text` in at most `most` lines of `room` px, broken between words; only
    what still does not fit is cut, the last line ending in an ellipsis. A
    category name reads whole where a single line would have cut it. */
export function fitLines(text: string, room: number, size: number, most = 3): string[] {
  const fits = Math.floor(room / (size * ADVANCE) + 1e-9);
  const words = text.split(" ");
  const lines: string[] = [];
  while (words.length && lines.length < most - 1) {
    let line = "";
    while (words.length && `${line} ${words[0]}`.trim().length <= fits) {
      line = `${line} ${words.shift()}`.trim();
    }
    // A word longer than the line: the rest is one cut line, as `fitText` draws it.
    if (!line) break;
    lines.push(line);
  }
  return words.length ? [...lines, fitText(words.join(" "), room, size)] : lines;
}

// The nice-number step: 1, 2 or 5 times a power of ten, whichever puts about
// `count` ticks across the extent. A port of d3-array's `tickSpec` (ISC), so
// the axes read as they did when d3 drew them (D33, D61).
const E10 = Math.sqrt(50);
const E5 = Math.sqrt(10);
const E2 = Math.sqrt(2);

function tickSpec(start: number, stop: number, count: number): [number, number, number] {
  const step = (stop - start) / Math.max(0, count);
  const power = Math.floor(Math.log10(step));
  const error = step / 10 ** power;
  const factor = error >= E10 ? 10 : error >= E5 ? 5 : error >= E2 ? 2 : 1;
  let i1: number;
  let i2: number;
  let inc: number;
  if (power < 0) {
    inc = 10 ** -power / factor;
    i1 = Math.round(start * inc);
    i2 = Math.round(stop * inc);
    if (i1 / inc < start) i1 += 1;
    if (i2 / inc > stop) i2 -= 1;
    inc = -inc;
  } else {
    inc = 10 ** power * factor;
    i1 = Math.round(start / inc);
    i2 = Math.round(stop / inc);
    if (i1 * inc < start) i1 += 1;
    if (i2 * inc > stop) i2 -= 1;
  }
  if (i2 < i1 && count >= 0.5 && count < 2) return tickSpec(start, stop, count * 2);
  return [i1, i2, inc];
}

/** The step between nice ticks: positive a whole step, negative the
    reciprocal of a fractional one (d3's convention, which keeps 0.1 exact). */
function tickIncrement(start: number, stop: number, count: number): number {
  return tickSpec(start, stop, count)[2];
}

function ticksOf(start: number, stop: number, count: number): number[] {
  if (start === stop) return [start];
  const [i1, i2, inc] = tickSpec(start, stop, count);
  if (!(i2 >= i1)) return [];
  return Array.from({ length: i2 - i1 + 1 }, (_, i) =>
    inc < 0 ? (i1 + i) / -inc : (i1 + i) * inc,
  );
}

/** A linear scale over `extent` with nice ends, its ticks, and the map from
    value to pixel along `range`. An extent with no length (every value zero,
    or none) is widened to [0, 1] so it draws. d3-scale's `nice`, ported. */
export function valueScale(
  extent: readonly [number, number],
  range: readonly [number, number],
  count: number,
) {
  let [start, stop] = extent[0] === extent[1] ? [Math.min(0, extent[0]), 1] : extent;
  let previous: number | undefined;
  for (let tries = 0; tries < 10; tries += 1) {
    const step = tickIncrement(start, stop, count);
    if (step === previous || step === 0 || !Number.isFinite(step)) break;
    if (step > 0) {
      start = Math.floor(start / step) * step;
      stop = Math.ceil(stop / step) * step;
    } else {
      start = Math.ceil(start * step) / step;
      stop = Math.floor(stop * step) / step;
    }
    previous = step;
  }
  const domain: [number, number] = [start, stop];
  const at = (value: number) =>
    range[0] + ((value - start) / (stop - start || 1)) * (range[1] - range[0]);
  return { domain, at, ticks: ticksOf(start, stop, count) };
}

/** Tick labels at the fewest decimals that state every tick: `toFixed` prints
    the nice number meant, not its float residue, so 0.30000000000000004 on a
    0.1 step reads "0.3". Digits grouped like every other figure. */
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

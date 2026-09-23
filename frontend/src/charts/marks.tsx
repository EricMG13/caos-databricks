// The marks every chart draws the same way. Provenance is in the mark: the
// host's figures are solid, the model's are outlined and hatched, and a
// waterfall's unreconciled residual is cross-hatched in the critical hue. An
// unavailable value is a labelled gap at the baseline, never a zero bar.
// Colour comes from a `chart-tone-*` class (styles/charts.css), so every hue
// is a token and nothing here writes a style string (the CSP's style-src).
import { TICK_SIZE } from "./scale";
import type { Box, Hatch, Origin, Tone } from "./types";

/** A bar: solid for the host, outlined and hatched for the model and the
    residual. An outlined bar is inset by half its stroke, so it never spills into
    the 2px gap that separates the bar from its neighbour. */
export function BarShape({
  box,
  tone,
  origin,
  hatch,
  mark,
}: {
  box: Box;
  tone: Tone;
  /** `null`: the unreconciled residual, which nobody served. */
  origin: Origin | null;
  hatch: Hatch;
  mark: string;
}) {
  if (origin === "host") {
    return (
      <rect
        className={`chart-bar chart-host chart-tone-${tone}`}
        data-mark={mark}
        data-origin="host"
        x={box.x}
        y={box.y}
        width={box.width}
        height={box.height}
      />
    );
  }
  const inset = box.width > 1.5 && box.height > 1.5 ? 0.75 : 0;
  return (
    <rect
      className={`chart-bar chart-outline chart-tone-${tone}`}
      data-mark={mark}
      data-origin={origin ?? "residual"}
      x={box.x + inset}
      y={box.y + inset}
      width={box.width - 2 * inset}
      height={box.height - 2 * inset}
      fill={hatch(tone)}
    />
  );
}

/** An unavailable value: a short tick off the baseline, labelled "n/a". Its
    reason is in the mark's accessible name, the readout and the table. */
export function GapMark({
  x,
  y,
  vertical,
  mark,
}: {
  x: number;
  y: number;
  vertical: boolean;
  mark: string;
}) {
  return (
    <g className="chart-gap" data-mark={mark} data-gap="">
      {vertical ? (
        <>
          <line x1={x} y1={y} x2={x} y2={y - 6} />
          <text x={x} y={y - 9} textAnchor="middle">
            n/a
          </text>
        </>
      ) : (
        <>
          <line x1={x} y1={y} x2={x + 6} y2={y} />
          <text x={x + 9} y={y + TICK_SIZE / 2 - 1.5} textAnchor="start">
            n/a
          </text>
        </>
      )}
    </g>
  );
}

/** The hatch each outlined tone is filled with: 45° lines in the tone, and
    the residual's 45° and 135° cross in the critical hue. */
export function HatchPatterns({
  id,
  tones,
}: {
  id: (tone: Tone) => string;
  tones: readonly Tone[];
}) {
  return (
    <defs>
      {tones.map((tone) => (
        <pattern
          key={tone}
          id={id(tone)}
          className={`chart-tone-${tone}`}
          width={5}
          height={5}
          patternUnits="userSpaceOnUse"
          patternTransform="rotate(45)"
        >
          <line className="chart-hatch" x1={0} y1={0} x2={0} y2={5} />
          {tone === "residual" ? (
            <line className="chart-hatch" x1={0} y1={0} x2={5} y2={0} />
          ) : null}
        </pattern>
      ))}
    </defs>
  );
}

/** A legend key in the mark's own form: a swatch for a bar, a stroke with its
    point for a line; outlined and hatched, or dashed and hollow, for the model. */
export function Swatch({
  tone,
  shape,
  origin,
}: {
  tone: Tone;
  shape: "fill" | "line";
  origin: Origin | null;
}) {
  const outlined = origin !== "host";
  return (
    <svg
      className={`chart-swatch chart-tone-${tone}`}
      width={16}
      height={10}
      aria-hidden="true"
      focusable="false"
    >
      {shape === "line" ? (
        <>
          <line
            className={outlined ? "chart-line chart-dashed" : "chart-line"}
            x1={0}
            y1={5}
            x2={16}
            y2={5}
          />
          <circle
            className={outlined ? "chart-point chart-hollow" : "chart-point"}
            cx={8}
            cy={5}
            r={3}
          />
        </>
      ) : outlined ? (
        <>
          <rect
            className="chart-bar chart-outline"
            x={1.75}
            y={1.75}
            width={12.5}
            height={6.5}
            fill="none"
          />
          <line className="chart-hatch" x1={4} y1={8} x2={9} y2={2} />
          <line className="chart-hatch" x1={9} y1={8} x2={14} y2={2} />
        </>
      ) : (
        <rect className="chart-bar chart-host" x={1} y={1} width={14} height={8} />
      )}
    </svg>
  );
}

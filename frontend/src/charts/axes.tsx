// Axes, minimal: one value axis of hairline gridlines with its tick labels,
// a zero baseline, and category labels thinned to what fits. Shared by the
// band charts and the line chart so the two read alike.
import { TICK_SIZE, fitText, textWidth, tickLabels, valueScale } from "./scale";
import type { Box } from "./types";

/** A text placed in plot pixels. */
export interface Placed {
  text: string;
  x: number;
  y: number;
  anchor: "start" | "middle" | "end";
}

export interface Tick {
  position: number;
  text: string;
}

export function Label({ placed, className }: { placed: Placed; className: string }) {
  return (
    <text className={className} x={placed.x} y={placed.y} textAnchor={placed.anchor}>
      {placed.text}
    </text>
  );
}

/** A nice value scale over `extent` along `range`, its ticks placed and
    labelled, and the widest label's width (the room a left axis needs). */
export function valueTicks(
  extent: readonly [number, number],
  range: readonly [number, number],
  spacing: number,
  percent = false,
) {
  const count = Math.max(2, Math.round(Math.abs(range[1] - range[0]) / spacing));
  const { scale, ticks } = valueScale(extent, range, count);
  const texts = tickLabels(ticks);
  const placed: Tick[] = ticks.map((tick, index) => ({
    position: scale(tick),
    text: `${texts[index] ?? ""}${percent ? "%" : ""}`,
  }));
  const widest = Math.max(0, ...placed.map((tick) => textWidth(tick.text, TICK_SIZE)));
  return { at: (value: number) => scale(value), ticks: placed, widest };
}

/** Category labels along a horizontal axis at `y`: every one that fits, the
    rest skipped at an even step so none overlaps, each cut to its room. */
export function acrossLabels(
  categories: readonly string[],
  centre: (index: number) => number,
  step: number,
  y: number,
): Placed[] {
  const widest = Math.max(0, ...categories.map((category) => textWidth(category, TICK_SIZE)));
  const every = Math.max(1, Math.ceil((widest + 6) / Math.max(1, step)));
  return categories.flatMap((category, index) =>
    index % every === 0
      ? [
          {
            text: fitText(category, every * step - 6, TICK_SIZE),
            x: centre(index),
            y,
            anchor: "middle" as const,
          },
        ]
      : [],
  );
}

/** Gridlines across `area` at each tick, the tick labels outside it, and the
    zero baseline one step brighter. `vertical`: values run up the left edge;
    otherwise along the bottom. */
export function ValueGrid({
  ticks,
  area,
  vertical,
  zero,
}: {
  ticks: readonly Tick[];
  area: Box;
  vertical: boolean;
  /** Where zero sits, when the axis holds it. */
  zero: number | null;
}) {
  const right = area.x + area.width;
  const bottom = area.y + area.height;
  return (
    <>
      <g className="chart-grid">
        {ticks.map((tick) =>
          vertical ? (
            <line
              key={tick.position}
              x1={area.x}
              x2={right}
              y1={tick.position}
              y2={tick.position}
            />
          ) : (
            <line
              key={tick.position}
              x1={tick.position}
              x2={tick.position}
              y1={area.y}
              y2={bottom}
            />
          ),
        )}
      </g>
      {ticks.map((tick) => (
        <Label
          key={`tick-${tick.position}`}
          className="chart-tick"
          placed={
            vertical
              ? {
                  text: tick.text,
                  x: area.x - 6,
                  y: tick.position + TICK_SIZE / 2 - 1.5,
                  anchor: "end",
                }
              : { text: tick.text, x: tick.position, y: bottom + 14, anchor: "middle" }
          }
        />
      ))}
      {zero === null ? null : vertical ? (
        <line className="chart-zero" x1={area.x} x2={right} y1={zero} y2={zero} />
      ) : (
        <line className="chart-zero" x1={zero} x2={zero} y1={area.y} y2={bottom} />
      )}
    </>
  );
}

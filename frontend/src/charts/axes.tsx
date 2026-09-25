// Axes, minimal: one value axis whose nice ticks are chosen here and drawn by
// Recharts (D61), and category labels thinned to what fits, each cut to its
// room. Shared by the band charts and the line chart so the two read alike.
import { TICK_SIZE, fitText, textWidth, tickLabels, valueScale } from "./scale";

/** A text placed in plot pixels. */
export interface Placed {
  text: string;
  x: number;
  y: number;
  anchor: "start" | "middle" | "end";
}

export interface Tick {
  value: number;
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

/** A nice value axis over `extent` along `range`: its domain, its ticks placed
    and labelled, and the widest label's width (the room a left axis needs). */
export function valueTicks(
  extent: readonly [number, number],
  range: readonly [number, number],
  spacing: number,
  percent = false,
) {
  const count = Math.max(2, Math.round(Math.abs(range[1] - range[0]) / spacing));
  const { domain, at, ticks } = valueScale(extent, range, count);
  const texts = tickLabels(ticks);
  const placed: Tick[] = ticks.map((tick, index) => ({
    value: tick,
    position: at(tick),
    text: `${texts[index] ?? ""}${percent ? "%" : ""}`,
  }));
  const widest = Math.max(0, ...placed.map((tick) => textWidth(tick.text, TICK_SIZE)));
  return { at, domain, ticks: placed, widest };
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

/** The label each category shows under a vertical axis, or `null` where it
    is skipped so its neighbours fit. */
export function shownCategories(categories: readonly string[], step: number): (string | null)[] {
  const shown = new Map(
    acrossLabels(categories, (index) => index, step, 0).map((placed) => [placed.x, placed.text]),
  );
  return categories.map((_, index) => shown.get(index) ?? null);
}

interface TickProps {
  x?: number | string;
  y?: number | string;
  payload?: { value?: unknown };
}

/** A value axis's tick for Recharts, labelled as `valueTicks` labelled it:
    beside a left axis, or under a bottom one. */
export function valueTick(ticks: readonly Tick[], side: "left" | "bottom") {
  const text = new Map(ticks.map((tick) => [tick.value, tick.text]));
  return function ValueTick(props: TickProps) {
    return (
      <TickText
        x={props.x}
        y={props.y}
        dy={side === "left" ? TICK_SIZE / 2 - 1.5 : 10}
        anchor={side === "left" ? "end" : "middle"}
        text={text.get(Number(props.payload?.value)) ?? null}
      />
    );
  };
}

/** Recharts' tick, drawn in the chart's own type: `text` is the label to
    print, already cut to fit, or its lines (`fitLines`), or nothing. Two
    lines sit centred on the tick, one above it and one below. */
export function TickText({
  x,
  y,
  text,
  anchor,
  dy = 0,
}: {
  x?: number | string;
  y?: number | string;
  text: string | readonly string[] | null;
  anchor: Placed["anchor"];
  dy?: number;
}) {
  if (text === null) return null;
  const lines = typeof text === "string" ? [text] : text;
  const leading = TICK_SIZE + 1;
  return (
    <text className="chart-tick" x={Number(x)} y={Number(y) + dy} textAnchor={anchor}>
      {lines.length === 1
        ? lines[0]
        : lines.map((line, index) => (
            <tspan
              key={index}
              x={Number(x)}
              dy={index === 0 ? (-(lines.length - 1) * leading) / 2 : leading}
            >
              {line}
            </tspan>
          ))}
    </text>
  );
}

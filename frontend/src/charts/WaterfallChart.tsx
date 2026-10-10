// A bridge: stated totals and the steps between them, floating on one running
// level. Totals are neutral; increases and decreases wear the two poles and
// print their sign. Where the steps do not reach the next stated total, an
// "Unreconciled" residual step says by exactly how much, cross-hatched in the
// critical hue, and the caption says so too. A change may wear its status's
// colour in place of its pole's, the status word in its name and its row.
// The sum is exact (`bridge.ts`).
import { ChartFrame } from "./ChartFrame";
import { bandPlot, type BandBar } from "./band";
import { UNRECONCILED, bridgeOf, type BridgeStep } from "./bridge";
import { formatDecimal, toNumber } from "./decimal";
import { ORIGIN_WORD, poleOf, valueText } from "./series";
import type { ChartColor, ChartProps, LegendEntry, TableTwin, Tone, WaterfallStep } from "./types";

const KIND_WORD: Record<BridgeStep["kind"], string> = {
  total: "stated total",
  delta: "change",
  residual: "unreconciled residual",
};

const NOT_SERVED = "the stated total less the running level: computed here, not served";

function toneOf(step: BridgeStep): Tone {
  if (step.kind === "residual") return "residual";
  if (step.kind === "total") return "neutral";
  return step.color ?? poleOf(step.value);
}

/** ", Challenged": a step's status as its name says it. */
const statusOf = (step: BridgeStep) => (step.status ? `, ${step.status}` : "");

/** A step's accessible name: its amount and unit, what kind of step it is,
    where the running level stands after it, and who stands behind it. */
function nameOf(step: BridgeStep, unit: string | undefined): string {
  if (step.value === null) return `${step.label}: n/a (${step.reason})${statusOf(step)}`;
  if (step.kind === "residual") {
    return `${UNRECONCILED} before ${step.before ?? ""}: ${valueText(step.value, unit, true)}, ${NOT_SERVED}`;
  }
  const origin = step.origin ? ORIGIN_WORD[step.origin] : "";
  if (step.kind === "total") {
    return `${step.label}: ${valueText(step.value, unit)}, stated total${statusOf(step)} (${origin})`;
  }
  const level = step.end === null ? "" : `, running level ${formatDecimal(step.end)}`;
  return `${step.label}: ${valueText(step.value, unit, true)}${level}${statusOf(step)} (${origin})`;
}

function barOf(step: BridgeStep, index: number, unit: string | undefined): BandBar {
  const placed = step.start !== null && step.end !== null;
  return {
    key: step.key,
    category: index,
    slot: 0,
    from: step.start === null ? 0 : toNumber(step.start),
    to: step.end === null ? 0 : toNumber(step.end),
    tone: toneOf(step),
    origin: step.origin,
    gap: !placed,
    name: nameOf(step, unit),
    label: step.value === null ? null : formatDecimal(step.value, step.kind !== "total"),
    alarm: step.kind === "residual",
    selection: {
      series: step.key,
      category: step.label,
      index,
      value: step.value,
      origin: step.origin,
      kind: step.kind,
    },
  };
}

/** The table twin; a Status column where any step states one. */
function tableOf(bridge: readonly BridgeStep[], unit: string | undefined): TableTwin {
  const statused = bridge.some((step) => step.status);
  return {
    head: [
      "Step",
      "Kind",
      `Amount${unit ? `, ${unit}` : ""}`,
      "Running level",
      ...(statused ? ["Status"] : []),
      "Origin",
    ],
    rows: bridge.map((step) => ({
      key: step.key,
      cells: [
        step.kind === "residual" ? `${UNRECONCILED} before ${step.before ?? ""}` : step.label,
        KIND_WORD[step.kind],
        step.value === null
          ? `n/a: ${step.reason}`
          : formatDecimal(step.value, step.kind !== "total"),
        step.end === null ? "n/a" : formatDecimal(step.end),
        ...(statused ? [step.status ?? ""] : []),
        step.origin ? ORIGIN_WORD[step.origin] : NOT_SERVED,
      ],
    })),
  };
}

export function WaterfallChart({
  title,
  summary,
  unit,
  steps,
  height,
  statuses,
  onSelect,
}: ChartProps & {
  /** Totals and deltas in bridge order: an opening total, the steps, the
      closing total. */
  steps: readonly WaterfallStep[];
  /** The chart's height, axes included. */
  height?: number;
  /** What the steps' colours stand for: given, they replace the Increase and
      Decrease entries, which stay only while a change wears no colour. */
  statuses?: readonly { color: ChartColor; label: string }[];
}) {
  const bridge = bridgeOf(steps);
  const residuals = bridge.filter((step) => step.kind === "residual");
  const poled = bridge.some((step) => step.kind === "delta" && !step.color);
  const legend: LegendEntry[] = [
    { key: "total", label: "Stated total", tone: "neutral", shape: "fill" },
    ...(statuses ?? []).map(({ color, label }) => ({
      key: `status:${label}`,
      label,
      tone: color,
      shape: "fill" as const,
    })),
  ];
  if (!statuses || poled) {
    legend.push(
      { key: "increase", label: "Increase", tone: "positive", shape: "fill" },
      { key: "decrease", label: "Decrease", tone: "negative", shape: "fill" },
    );
  }
  if (residuals.length) {
    legend.push({
      key: "residual",
      label: UNRECONCILED,
      tone: "residual",
      shape: "fill",
      origin: null,
    });
  }
  const note = residuals.length
    ? `Does not reconcile: ${residuals
        .map(
          (step) =>
            `${valueText(step.value ?? "0", unit, true)} unexplained before ${step.before ?? ""}`,
        )
        .join("; ")}.`
    : null;
  const bars = bridge.map((step, index) => barOf(step, index, unit));
  const categories = bridge.map((step) => step.label);
  return (
    <ChartFrame
      kind="waterfall"
      title={title}
      summary={summary}
      note={note}
      legend={legend}
      provenance="fill"
      table={tableOf(bridge, unit)}
      plot={(kit) =>
        bandPlot(
          { orientation: "vertical", categories, slots: 1, bars, connect: true, height },
          kit,
        )
      }
      onSelect={onSelect}
    />
  );
}

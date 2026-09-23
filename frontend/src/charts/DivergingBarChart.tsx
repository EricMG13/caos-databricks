// Values either side of zero: actual against model, a variance per line item.
// Position carries the sign, the two poles' hues repeat it, and every label,
// name and table cell says it again as "+" or "-": colour is never alone.
import { ChartFrame } from "./ChartFrame";
import { bandPlot, cellBar } from "./band";
import { cellText, cellsOf, poleOf, seriesTable } from "./series";
import type { ChartProps, ChartSeries, LegendEntry, Orientation } from "./types";

const POLES: readonly LegendEntry[] = [
  { key: "positive", label: "Above zero", tone: "positive", shape: "fill" },
  { key: "negative", label: "Below zero", tone: "negative", shape: "fill" },
];

export function DivergingBarChart({
  title,
  summary,
  unit,
  categories,
  series,
  categoryLabel = "Category",
  orientation = "horizontal",
  height,
  onSelect,
}: ChartProps & {
  /** The items the values belong to: line items, periods. */
  categories: readonly string[];
  /** One series of signed values; its colour is the poles', not its own. */
  series: ChartSeries;
  categoryLabel?: string;
  /** Bars run along beside each row (the default), or stand up from the axis. */
  orientation?: Orientation;
  /** A vertical chart's height, axes included. */
  height?: number;
}) {
  const cells = cellsOf(categories, [series]);
  const bars = cells.map((cell) => cellBar(cell, unit, { tone: poleOf(cell.value), signed: true }));
  return (
    <ChartFrame
      kind="diverging"
      title={title}
      summary={summary}
      legend={POLES}
      provenance="fill"
      table={seriesTable(categoryLabel, categories, [series], cells, unit, (cell) =>
        cellText(cell, "", true),
      )}
      plot={(width, hatch) =>
        bandPlot({ orientation, categories, slots: 1, bars, height }, width, hatch)
      }
      onSelect={onSelect}
    />
  );
}

// Magnitude by category, one bar per series in each, grouped, either way up:
// citations per source, a forecast by period.
import { ChartFrame } from "./ChartFrame";
import { bandPlot, cellBar } from "./band";
import { cellsOf, seriesLegend, seriesTable } from "./series";
import type { Orientation, SeriesChartProps } from "./types";

export function BarChart({
  title,
  summary,
  unit,
  categories,
  series,
  categoryLabel = "Category",
  orientation = "vertical",
  height,
  onSelect,
}: SeriesChartProps & {
  /** Bars stand up from the category axis, or run along beside each row. */
  orientation?: Orientation;
  /** A vertical chart's height, axes included. */
  height?: number;
}) {
  const cells = cellsOf(categories, series);
  const bars = cells.map((cell) => cellBar(cell, unit));
  return (
    <ChartFrame
      kind="bar"
      title={title}
      summary={summary}
      legend={seriesLegend(series, "fill")}
      provenance="fill"
      table={seriesTable(categoryLabel, categories, series, cells, unit)}
      plot={(kit) =>
        bandPlot({ orientation, categories, slots: Math.max(1, series.length), bars, height }, kit)
      }
      onSelect={onSelect}
    />
  );
}

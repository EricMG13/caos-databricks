// Part to whole by category: segments stacked in series order. `absolute`
// draws the amounts, each stack's net total past its end; `normalised` makes
// every stack its category's whole and every segment its share, the printed
// shares summing to exactly 100.0 (`stack.ts`). A debt stack passes each
// tranche its `tranche-*` colour; a segment mix takes the ramp.
import { ChartFrame } from "./ChartFrame";
import { bandPlot, type BandBar } from "./band";
import { formatDecimal, toNumber } from "./decimal";
import { cellName, cellSelection, cellText, cellsOf, seriesLegend, seriesTable } from "./series";
import { stackOf, type Segment } from "./stack";
import type { Orientation, SeriesChartProps, TableTwin } from "./types";

function segmentBar(segment: Segment, unit: string | undefined): BandBar {
  const { cell, share, gap } = segment;
  const said = share === null ? "" : `, ${share}% of the whole`;
  return {
    key: `${cell.series.key}:${cell.index}`,
    category: cell.index,
    slot: 0,
    from: segment.from,
    to: segment.to,
    stacked: segment.stacked,
    tone: cell.color,
    origin: cell.origin,
    gap: gap !== null,
    name:
      gap !== null && cell.value !== null
        ? `${cellName(cell, unit)}; not drawn: ${gap}`
        : cellName(cell, unit, said),
    label: null,
    selection: cellSelection(cell),
  };
}

export function StackedBarChart({
  title,
  summary,
  unit,
  categories,
  series,
  categoryLabel = "Category",
  mode = "absolute",
  orientation = "vertical",
  height,
  onSelect,
}: SeriesChartProps & {
  /** Amounts, or each stack as its whole and each segment as its share. */
  mode?: "absolute" | "normalised";
  orientation?: Orientation;
  /** A vertical chart's height, axes included. */
  height?: number;
}) {
  const normalised = mode === "normalised";
  const cells = cellsOf(categories, series);
  const { segments, totals } = stackOf(cells, categories.length, normalised);
  const bars = segments.map((segment) => segmentBar(segment, unit));
  const bySegment = new Map(segments.map((segment) => [segment.cell, segment]));
  const twin = seriesTable(categoryLabel, categories, series, cells, unit, (cell) => {
    const segment = bySegment.get(cell);
    if (!normalised || cell.value === null) return cellText(cell);
    return cellText(cell, segment?.share ? ` (${segment.share}%)` : ` (${segment?.gap ?? ""})`);
  });
  const table: TableTwin = normalised
    ? twin
    : {
        head: [...twin.head, `Total${unit ? `, ${unit}` : ""}`],
        rows: twin.rows.map((row, index) => {
          const total = totals[index];
          return {
            ...row,
            cells: [...row.cells, total ? formatDecimal(total.net) : "n/a: a value is unavailable"],
          };
        }),
      };
  const labelled = normalised
    ? []
    : totals.flatMap((total, category) =>
        total ? [{ category, at: toNumber(total.at), text: formatDecimal(total.net) }] : [],
      );
  return (
    <ChartFrame
      kind={normalised ? "stacked-normalised" : "stacked"}
      title={title}
      summary={summary}
      legend={seriesLegend(series, "fill")}
      provenance="fill"
      table={table}
      plot={(kit) =>
        bandPlot(
          {
            orientation,
            categories,
            slots: 1,
            bars,
            totals: labelled,
            percent: normalised,
            height,
          },
          kit,
        )
      }
      onSelect={onSelect}
    />
  );
}

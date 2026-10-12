// Three small charts over the credit model: adjusted net leverage, adjusted
// interest coverage and liquidity. Drawn from the same served cells the grid
// shows, so a chart never disagrees with a row.
import { LineChart } from "@/charts";
import type { ModelDocument } from "@/wire/v1";
import { stripCharts } from "./grid";

export function ChartStrip({ body }: { body: ModelDocument["body"] }) {
  const charts = stripCharts(body);
  if (charts.length === 0) return null;
  return (
    <div className="model-strip" data-model-strip>
      {charts.map((chart) => (
        <section className="pnl" key={chart.key} data-strip-chart={chart.key}>
          <div className="pb">
            <LineChart
              title={chart.title}
              summary={`${chart.title}: ${chart.categories[0]} to ${chart.categories.at(-1)}, actual and projected cases.`}
              unit={chart.unit}
              categories={chart.categories}
              series={chart.series}
              height={180}
              includeZero={false}
            />
          </div>
        </section>
      ))}
    </div>
  );
}

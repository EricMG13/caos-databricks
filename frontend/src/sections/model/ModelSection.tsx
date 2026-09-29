// The accepted CP-CF projection, read only. Values are server strings: this
// view deliberately performs no model arithmetic or evidence navigation.
import { LineChart, type ChartSeries } from "@/charts";
import { NoteRows } from "@/ds/atoms";
import type { ModelDocument } from "@/wire/v1";
import { displayDecimal } from "@/ds/format";
import { Digest } from "@/ds/Digest";

type Forecast = NonNullable<ModelDocument["body"]["forecast"]>;
type ForecastValue = Forecast["periods"][number]["values"][number];
type ForecastUnit = ForecastValue["unit"];

/** How each of a chart's own dimensions reads (R24-12): money keeps the
    forecast's stated currency and scale, exactly as before; the
    leverage/coverage family reads as a multiple, and the one margin as an
    explicit ratio -- neither relabelled as money, and the ratio shown
    unscaled, since this view performs no arithmetic on the server's decimal
    strings. */
const UNIT_LABEL: Record<ForecastUnit, (forecast: Forecast) => string> = {
  MONEY: (forecast) => `${forecast.currency} ${forecast.scale}`,
  MULTIPLE: () => "multiple",
  RATIO: () => "ratio",
};

/** One figure per projected value and unit, with one line per case. A missing
    case value stays a gap. These are CP-CF host figures; each line carries its
    own `unit`, and needs two distinct periods before it is drawn. */
export function forecastSeries(
  forecast: Forecast,
): { title: string; categories: string[]; series: ChartSeries[]; unit: ForecastUnit }[] {
  const cases = [...new Set(forecast.periods.map((period) => period.case))];
  const periodsByCase = new Map(
    cases.map((name) => [name, forecast.periods.filter((period) => period.case === name)]),
  );
  const periodKey = (period: Forecast["periods"][number]) =>
    `${period.fiscal_year}\0${period.period_id}`;
  const labels = (periods: readonly Forecast["periods"][number][]) => {
    const counts = new Map<string, number>();
    for (const period of periods)
      counts.set(period.period_id, (counts.get(period.period_id) ?? 0) + 1);
    return periods.map((period) =>
      counts.get(period.period_id)! > 1
        ? `${period.period_id} · FY${period.fiscal_year}`
        : period.period_id,
    );
  };
  const valueOf = (period: Forecast["periods"][number], name: string, unit: ForecastUnit) => {
    const value = period.values.find((entry) => entry.name === name && entry.unit === unit);
    return value?.value != null
      ? { value: value.value }
      : {
          value: null,
          reason: value?.unavailable_reason ?? period.unavailable_reason ?? "not served",
        };
  };
  const dimensions = [
    ...new Map(
      forecast.periods.flatMap((period) =>
        period.values.map((value) => [`${value.name}\0${value.unit}`, value] as const),
      ),
    ).values(),
  ];
  const reference = periodsByCase.get(cases[0]!) ?? [];
  const referenceSchedule = reference.map(periodKey);
  const schedulesAlign = cases.every((name) => {
    const own = periodsByCase.get(name) ?? [];
    const schedule = own.map(periodKey);
    return (
      new Set(schedule).size === schedule.length &&
      schedule.length === referenceSchedule.length &&
      schedule.every((key, index) => key === referenceSchedule[index])
    );
  });
  return dimensions.flatMap((dimension) => {
    const hasValue = (period: Forecast["periods"][number]) =>
      period.values.some((value) => value.name === dimension.name && value.unit === dimension.unit);
    const populated = forecast.periods.filter(hasValue);
    if (new Set(populated.map(periodKey)).size < 2) return [];
    if (schedulesAlign) {
      const series = cases.map((name) => {
        const own = periodsByCase.get(name) ?? [];
        return {
          key: `${name}:${dimension.name}:${dimension.unit}`,
          label: `${dimension.name} · ${name}`,
          origin: "host" as const,
          data: own.map((period) => valueOf(period, dimension.name, dimension.unit)),
        };
      });
      return [
        {
          // Several cases name themselves in the legend; one case has no
          // legend, so the title names it.
          title: cases.length > 1 ? dimension.name : `${dimension.name} · ${cases[0]}`,
          categories: labels(reference),
          series,
          unit: dimension.unit,
        },
      ];
    }
    return cases.flatMap((name) => {
      const own = periodsByCase.get(name) ?? [];
      if (new Set(own.filter(hasValue).map(periodKey)).size < 2) return [];
      return {
        title: `${dimension.name} · ${name}`,
        categories: labels(own),
        series: [
          {
            key: `${name}:${dimension.name}:${dimension.unit}`,
            label: `${dimension.name} · ${name}`,
            origin: "host" as const,
            data: own.map((period) => valueOf(period, dimension.name, dimension.unit)),
          },
        ],
        unit: dimension.unit,
      };
    });
  });
}

export function ModelSection({ document }: { document: ModelDocument; tab: string | null }) {
  const { body } = document;
  const forecast = body.forecast;
  if (!forecast) {
    return (
      <section className="pnl" data-model-v1 data-run={body.displayed_run_id ?? ""}>
        <header>
          <h2>Model</h2>
          <span className="cp">CP-CF</span>
        </header>
        {/* Why there is none, not only that there is none: an ended run is not
            waiting for a forecast, and a verdict that ended it has a name. */}
        <div className="pb note" data-model-unavailable>
          {body.unavailable_reason}
          {body.displayed_run_status !== null && body.displayed_run_status !== "RUNNING"
            ? ` · the run ended ${body.displayed_run_status}`
            : ""}
          {body.blocked_by ? ` on ${body.blocked_by.module_id}` : ""}
        </div>
      </section>
    );
  }
  return (
    <div className="col" data-model-v1 data-run={body.displayed_run_id ?? ""}>
      <section className="pnl">
        <header>
          <h2>Accepted forecast</h2>
          <span className="cp">{forecast.route_node_id}</span>
        </header>
        <div className="pb">
          <dl className="kv">
            <dt>Accepted</dt>
            <dd>
              <time dateTime={forecast.accepted_at}>{forecast.accepted_at}</time>
            </dd>
            <dt>Artifact</dt>
            <dd>
              <Digest value={forecast.artifact_sha256} prefix="sha256:" />
            </dd>
            <dt>Record</dt>
            <dd>
              <Digest value={forecast.record_sha256} prefix="sha256:" />
            </dd>
            <dt>QA</dt>
            <dd data-qa-status>{forecast.qa_status}</dd>
            <dt>Units</dt>
            <dd>
              {forecast.currency} · {forecast.scale}
            </dd>
            <dt>Perimeter</dt>
            <dd>{forecast.perimeter}</dd>
            <NoteRows label="Limitations" values={forecast.limitation_flags} />
            <NoteRows label="Validation warnings" values={forecast.validation_warnings} />
          </dl>
        </div>
      </section>
      {forecastSeries(forecast).map((chart) => (
        <section
          key={chart.series[0]!.key}
          className="pnl"
          data-forecast-chart={chart.series[0]!.key}
        >
          <div className="pb">
            <LineChart
              title={chart.title}
              summary={`The host's projection over ${chart.categories.length} periods, ${chart.categories[0]} to ${chart.categories.at(-1)}.`}
              unit={UNIT_LABEL[chart.unit](forecast)}
              categories={chart.categories}
              series={chart.series}
            />
          </div>
        </section>
      ))}
      <section className="pnl">
        <header>
          <h2>Periods</h2>
          <span className="tag">{forecast.periods.length}</span>
        </header>
        {/* A scroll region is reached by keyboard, so it is focusable and
            named rather than a silent box only a pointer can move (FE-5). */}
        <div
          className="pb flush scroll"
          tabIndex={0}
          role="region"
          aria-label="Projection period rows"
        >
          <table className="dense" data-model-periods>
            <thead>
              <tr>
                <th>Case</th>
                <th>Period</th>
                <th>Year</th>
                <th>Days</th>
                <th className="l">Line</th>
                <th>Value</th>
                <th className="l">Unavailable reason</th>
              </tr>
            </thead>
            <tbody>
              {forecast.periods.flatMap((period) => {
                const rows = period.values.length ? period.values : [null];
                return rows.map((value, index) => (
                  <tr key={`${period.case}-${period.period_id}-${value?.name ?? index}`}>
                    <td className="l">{period.case}</td>
                    <td className="l">{period.period_id}</td>
                    <td className="l">{period.fiscal_year}</td>
                    <td>{period.days}</td>
                    <td className="l">{value?.name ?? "—"}</td>
                    {/* The figure rounded for reading; its exact decimal is
                        its accessible name and title (numeric truth). */}
                    <td title={value?.value ?? undefined}>
                      {value?.value ? displayDecimal(value.value) : "—"}
                    </td>
                    <td className="l">
                      {value?.unavailable_reason ?? period.unavailable_reason ?? "—"}
                    </td>
                  </tr>
                ));
              })}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}

import { render, screen, within } from "@testing-library/react";
import { ModelSection, forecastSeries } from "@/sections/model/ModelSection";
import { parseModelDocument, type ModelDocument } from "@/wire/v1";

const CASE = "00000000-0000-4000-8000-000000000001";
const RUN = "00000000-0000-4000-8000-0000000000a1";
const HASH = "a".repeat(64);

function model(overrides: Record<string, unknown> = {}): ModelDocument {
  const body = {
    case_id: CASE,
    latest_run_id: RUN,
    displayed_run_id: RUN,
    subject: null,
    displayed_run_status: "COMPLETE",
    blocked_by: null,
    forecast: {
      route_node_id: "CP-CF",
      artifact_sha256: HASH,
      record_sha256: "b".repeat(64),
      accepted_at: "2026-09-14T10:00:00Z",
      qa_status: "ACCEPTED",
      limitation_flags: ["LIMITED_HISTORY"],
      validation_warnings: ["Hostile <img src=x> warning"],
      currency: "USD",
      scale: "millions",
      perimeter: "Consolidated <img src=x>",
      periods: [
        {
          case: "Base",
          period_id: "Q1",
          fiscal_year: "2026",
          days: "90",
          values: [
            { name: "cash", unit: "MONEY", value: "123.45", unavailable_reason: null },
            {
              name: "coverage",
              unit: "MULTIPLE",
              value: null,
              unavailable_reason: "ZERO_OR_NEGATIVE_DENOMINATOR",
            },
          ],
          unavailable_reason: "A required input is unavailable",
        },
      ],
    },
    unavailable_reason: null,
    ...overrides,
  };
  return parseModelDocument({
    chrome: {
      subject: { case_id: CASE, title: "Issuer" },
      served_role: { global_role: "READER", standing: "READER" },
      actions: [],
    },
    body,
    observed_at: "2026-09-14T10:00:00Z",
    observed_empty: false,
    status: "complete",
    notes: [],
  });
}

describe("Model v1", () => {
  test("renders the accepted projection as server strings with every explicit limitation", () => {
    const { container } = render(<ModelSection document={model()} tab={null} />);
    expect(container.querySelector("[data-model-v1]")).toHaveAttribute("data-run", RUN);
    expect(container).toHaveTextContent("CP-CF");
    expect(container).toHaveTextContent(`sha256:${HASH}`);
    expect(container).toHaveTextContent("123.45");
    expect(container).toHaveTextContent("ZERO_OR_NEGATIVE_DENOMINATOR");
    expect(container).toHaveTextContent("A required input is unavailable");
    expect(container).toHaveTextContent("LIMITED_HISTORY");
    // A row of the forecast's own list (NoteRows), not a loose sentence below it.
    const limits = within(container).getByText("Limitations");
    expect(limits.tagName).toBe("DT");
    expect(limits.nextElementSibling).toHaveTextContent("LIMITED_HISTORY");
    expect(container.querySelector("[data-qa-status]")).toHaveTextContent("ACCEPTED");
  });

  test("renders partial and hostile server text as text, never markup", () => {
    const partial = parseModelDocument({
      ...model(),
      status: "partial",
      notes: ["HANDOFFS_PENDING"],
    });
    const { container } = render(<ModelSection document={partial} tab={null} />);
    expect(container).toHaveTextContent("Consolidated <img src=x>");
    expect(container).toHaveTextContent("Hostile <img src=x> warning");
    expect(container.querySelector("img")).toBeNull();
    expect(container.querySelector("button, input, select, textarea")).toBeNull();
  });

  test("renders the declared no-forecast reason without projecting a value", () => {
    const { container } = render(
      <ModelSection
        document={model({ forecast: null, unavailable_reason: "NO_ACCEPTED_FORECAST" })}
        tab={null}
      />,
    );
    expect(container.querySelector("[data-model-unavailable]")).toHaveTextContent(
      "NO_ACCEPTED_FORECAST",
    );
    expect(screen.queryByText("123.45")).toBeNull();
  });

  test("test_an_absent_forecast_says_whether_the_run_can_still_produce_one", () => {
    // "No accepted forecast" reads as "not yet" on a run that has ended, which
    // is the same blindness the Analysis page carried until it named the node
    // whose verdict stopped the run.
    const { container } = render(
      <ModelSection
        document={model({
          forecast: null,
          unavailable_reason: "NO_ACCEPTED_FORECAST",
          displayed_run_status: "BLOCKED",
          blocked_by: { route_node_id: "rn-cp-5", module_id: "CP-5", attempt_id: RUN },
        })}
        tab={null}
      />,
    );
    const note = container.querySelector("[data-model-unavailable]")!;
    expect(note).toHaveTextContent("the run ended BLOCKED");
    expect(note).toHaveTextContent("on CP-5");

    const { container: working } = render(
      <ModelSection
        document={model({
          forecast: null,
          unavailable_reason: "NO_ACCEPTED_FORECAST",
          displayed_run_status: "RUNNING",
        })}
        tab={null}
      />,
    );
    expect(working.querySelector("[data-model-unavailable]")).not.toHaveTextContent(
      "the run ended",
    );
  });

  test("renders a period-level unavailable reason even when it has no values", () => {
    const source = model();
    const document = parseModelDocument({
      ...source,
      body: {
        ...source.body,
        forecast: {
          ...source.body.forecast!,
          periods: [
            {
              ...source.body.forecast!.periods[0]!,
              values: [],
              unavailable_reason: "INPUT_MISSING",
            },
          ],
        },
      },
    });
    render(<ModelSection document={document} tab={null} />);
    expect(screen.getByText("INPUT_MISSING")).toBeInTheDocument();
  });
});

describe("the host's forecast, drawn", () => {
  test("test_forecastSeries_joins_two_or_more_periods_of_one_case_as_host_lines", () => {
    const single = model().body.forecast!;
    // One period has nothing to join: no chart.
    expect(forecastSeries(single)).toEqual([]);
    const second = {
      ...single.periods[0]!,
      period_id: "Q2",
      values: [
        { name: "cash", unit: "MONEY" as const, value: "130.00", unavailable_reason: null },
        { name: "coverage", unit: "MULTIPLE" as const, value: "1.8", unavailable_reason: null },
      ],
      unavailable_reason: null,
    };
    const two = { ...single, periods: [single.periods[0]!, second] };
    const charts = forecastSeries(two);
    expect(charts.map((chart) => chart.series[0]!.key)).toEqual(["Base:cash", "Base:coverage"]);
    expect(charts[0]!.series[0]!.origin).toBe("host");
    expect(charts[0]!.series[0]!.data).toEqual([{ value: "123.45" }, { value: "130.00" }]);
    // A value the host could not compute is a gap with its reason, never zero.
    expect(charts[1]!.series[0]!.data[0]).toEqual({
      value: null,
      reason: "ZERO_OR_NEGATIVE_DENOMINATOR",
    });
    // R24-12: a dimensionless ratio is not a monetary amount. `unit` is
    // carried per line, not the forecast's currency/scale for every chart.
    expect(charts[0]!.unit).toBe("MONEY");
    expect(charts[1]!.unit).toBe("MULTIPLE");
    const { container } = render(<ModelSection document={model({ forecast: two })} tab={null} />);
    expect(container.querySelectorAll("[data-forecast-chart]")).toHaveLength(2);
    // Each mark's accessible name states the value with its own unit label
    // (`@/charts/series.ts` `cellName`/`valueText`): money keeps "USD
    // millions"; the coverage ratio is labelled "multiple", never money. Two
    // elements share each `data-mark` key (a focus target and the drawn
    // point); the one carrying the announced name is what a reader hears.
    const labelled = (mark: string) =>
      Array.from(container.querySelectorAll(`[data-mark="${mark}"]`))
        .map((el) => el.getAttribute("aria-label"))
        .find((label): label is string => label !== null);
    expect(labelled("Base:cash:0")).toContain("USD millions");
    expect(labelled("Base:coverage:1")).toContain("multiple");
    expect(labelled("Base:coverage:1")).not.toContain("USD");
  });
});

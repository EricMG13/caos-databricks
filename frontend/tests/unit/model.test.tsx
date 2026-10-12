import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter, useLocation } from "react-router";
import { EvidenceProvider } from "@/evidence/EvidenceContext";
import { ChartStrip } from "@/sections/model/ChartStrip";
import { ModelCellButton, ModelGrid } from "@/sections/model/ModelGrid";
import {
  GROUP_IDS,
  columnGroups,
  groupList,
  groupOf,
  hiddenLine,
  passportOfCell,
  refinanced,
  shownCell,
  stripCharts,
  tintOf,
  toggled,
} from "@/sections/model/grid";
import { sectionUrl } from "@/app/transport";
import { parseBookDocument } from "@/wire/v1";
import { ModelSection, forecastSeries } from "@/sections/model/ModelSection";
import { parseModelDocument, type ModelDocument } from "@/wire/v1";

const CASE = "00000000-0000-4000-8000-000000000001";
const RUN = "00000000-0000-4000-8000-0000000000a1";
const HASH = "a".repeat(64);

const FIXTURE = resolve(process.cwd(), "fixtures", "model.json");

function fixture(): ModelDocument {
  return parseModelDocument(JSON.parse(readFileSync(FIXTURE, "utf8")));
}

function Probe() {
  return <output data-search>{useLocation().search}</output>;
}

function renderModel(document: ModelDocument, url = "/model/") {
  return render(
    <MemoryRouter initialEntries={[url]}>
      <EvidenceProvider>
        <ModelSection document={document} tab={null} />
        <Probe />
      </EvidenceProvider>
    </MemoryRouter>,
  );
}

function indexOfColumn(body: ModelDocument["body"], columnId: string): number {
  const index = body.columns.findIndex((column) => column.column_id === columnId);
  expect(index).toBeGreaterThanOrEqual(0);
  return index;
}

function cellOf(container: HTMLElement, line: string, column: string): HTMLElement {
  return container.querySelector<HTMLElement>(`[data-line="${line}"] [data-cell="${column}"]`)!;
}

function model(overrides: Record<string, unknown> = {}): ModelDocument {
  const body = {
    case_id: CASE,
    latest_run_id: RUN,
    displayed_run_id: RUN,
    displayed_run_status: "COMPLETE",
    subject: null,
    currency: null,
    unit: null,
    exclude_unrealised: false,
    rate_deck: null,
    columns: [],
    lines: [],
    limitations: [],
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
    const { container } = renderModel(model());
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
    const { container } = renderModel(partial);
    expect(container).toHaveTextContent("Consolidated <img src=x>");
    expect(container).toHaveTextContent("Hostile <img src=x> warning");
    expect(container.querySelector("img")).toBeNull();
    expect(container.querySelector("button, input, select, textarea")).toBeNull();
  });

  test("says there is no accepted forecast without projecting a value", () => {
    const { container } = renderModel(model({ forecast: null }));
    expect(container.querySelector("[data-model-unavailable]")).toHaveTextContent(
      "No accepted CP-CF forecast",
    );
    expect(screen.queryByText("123.45")).toBeNull();
  });

  test.each([
    ["CP-1 model tables unreadable", true],
    ["CP-1 model tables unreadable", false],
    ["model exceeds the grid bounds", true],
    ["model exceeds the grid bounds", false],
  ])("renders empty-grid limitation %s with forecast %s", (limitation, hasForecast) => {
    const source = model();
    const document = parseModelDocument({
      ...source,
      status: "partial",
      body: {
        ...source.body,
        limitations: [limitation],
        forecast: hasForecast ? source.body.forecast : null,
      },
    });
    const { container } = renderModel(document);
    expect(container.querySelector("[data-model-limitations]")).toHaveTextContent(limitation);
    expect(container.querySelector("[data-model-lines]")).toBeNull();
    if (hasForecast) {
      expect(container).toHaveTextContent("Accepted forecast");
      expect(container).toHaveTextContent("123.45");
    } else {
      expect(container.querySelector("[data-model-unavailable]")).toHaveTextContent(
        "No accepted CP-CF forecast",
      );
    }
  });

  test("test_an_absent_forecast_says_whether_the_run_can_still_produce_one", () => {
    // "No accepted forecast" reads as "not yet" on a run that has ended.
    const { container } = renderModel(model({ forecast: null, displayed_run_status: "BLOCKED" }));
    const note = container.querySelector("[data-model-unavailable]")!;
    expect(note).toHaveTextContent("the run ended BLOCKED");

    const { container: working } = renderModel(
      model({ forecast: null, displayed_run_status: "RUNNING" }),
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
    renderModel(document);
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
    expect(charts.map((chart) => chart.series[0]!.key)).toEqual([
      "Base:cash:MONEY",
      "Base:coverage:MULTIPLE",
    ]);
    expect(charts[0]!.series[0]!.origin).toBe("host");
    // One case draws one line and no legend, so the title names the case.
    expect(charts.map((chart) => chart.title)).toEqual(["cash · Base", "coverage · Base"]);
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
    const { container } = renderModel(model({ forecast: two }));
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
    expect(labelled("Base:cash:MONEY:0")).toContain("USD millions");
    expect(labelled("Base:coverage:MULTIPLE:1")).toContain("multiple");
    expect(labelled("Base:coverage:MULTIPLE:1")).not.toContain("USD");
  });

  test("compares cases only when their forecast period schedules align", () => {
    const forecast = model().body.forecast!;
    const baseQ1 = forecast.periods[0]!;
    const baseQ2 = {
      ...baseQ1,
      period_id: "Q2",
      fiscal_year: "2027",
      values: [{ name: "cash", unit: "MONEY" as const, value: "140", unavailable_reason: null }],
      unavailable_reason: null,
    };
    const downsideQ1 = { ...baseQ1, case: "Downside", values: [baseQ1.values[0]!] };
    const downsideQ2 = {
      ...baseQ2,
      case: "Downside",
      values: [
        {
          name: "cash",
          unit: "MONEY" as const,
          value: "0",
          unavailable_reason: null,
        },
      ],
    };
    const aligned = forecastSeries({
      ...forecast,
      periods: [baseQ1, baseQ2, downsideQ1, downsideQ2],
    });
    expect(aligned).toHaveLength(1);
    expect(aligned[0]!.categories).toEqual(["Q1", "Q2"]);
    expect(aligned[0]!.series.map((series) => series.label)).toEqual([
      "cash · Base",
      "cash · Downside",
    ]);
    expect(aligned[0]!.series[1]!.data).toEqual([{ value: "123.45" }, { value: "0" }]);
    // One chart carries both cases, so its title is the value, not the first case.
    expect(aligned[0]!.title).toBe("cash");

    const mismatched = forecastSeries({
      ...forecast,
      periods: [
        baseQ1,
        baseQ2,
        { ...downsideQ1, period_id: "D-Q1" },
        { ...downsideQ2, period_id: "D-Q2" },
      ],
    });
    expect(mismatched).toHaveLength(2);
    expect(mismatched.map((chart) => chart.categories)).toEqual([
      ["Q1", "Q2"],
      ["D-Q1", "D-Q2"],
    ]);
    expect(mismatched.every((chart) => chart.series.length === 1)).toBe(true);
    expect(mismatched.map((chart) => chart.title)).toEqual(["cash · Base", "cash · Downside"]);
  });
});

describe("the credit workbook grid", { timeout: 30_000 }, () => {
  test("the fixture parses with parseModelDocument", () => {
    const document = fixture();
    expect(document.body.columns).toHaveLength(23);
    expect(document.body.lines.length).toBeGreaterThan(100);
    expect(document.body.rate_deck?.as_of).toBe("2026-10-01");
  });

  test("hides a line whose cells are all zero or null unless it is a facility", () => {
    const { lines } = fixture().body;
    const line = (id: string) => lines.find((entry) => entry.line_id === id)!;
    expect(hiddenLine(line("acquisitions_net"))).toBe(true);
    expect(hiddenLine(line("revenue"))).toBe(false);
    // Revolver drawn nowhere: every cell is zero, and it is still a facility.
    expect(hiddenLine(line("fac:rcf"))).toBe(false);
    const { container } = renderModel(fixture());
    expect(container.querySelector('[data-line="acquisitions_net"]')).toBeNull();
    expect(container.querySelector('[data-line="fac:rcf"]')).not.toBeNull();
  });

  test("renders band headers that collapse their rows", () => {
    const { container } = renderModel(fixture());
    const band = within(container).getByRole("button", { name: /Revenue by business unit/ });
    expect(band).toHaveAttribute("aria-expanded", "true");
    expect(container.querySelector('[data-line="revenue"]')).not.toBeNull();
    fireEvent.click(band);
    expect(band).toHaveAttribute("aria-expanded", "false");
    expect(container.querySelector('[data-line="revenue"]')).toBeNull();
    expect(container.querySelector('[data-line="cogs"]')).not.toBeNull();
    fireEvent.click(band);
    expect(container.querySelector('[data-line="revenue"]')).not.toBeNull();
  });

  test("collapsing a column group writes mcols to the URL", () => {
    const { container } = renderModel(fixture());
    const region = screen.getByRole("region", { name: "Model grid" });
    expect(region).toHaveAttribute("tabindex", "0");
    // Ten quarters are served; the default window shows the last four.
    expect(cellOf(container, "revenue", "Q:Q2_2026")).not.toBeNull();
    expect(cellOf(container, "revenue", "Q:Q1_2025")).toBeNull();
    const quarters = within(region).getByRole("button", { name: /^▾ Quarters/ });
    fireEvent.click(quarters);
    expect(container.querySelector("[data-search]")).toHaveTextContent("?mcols=quarters");
    expect(cellOf(container, "revenue", "Q:Q2_2026")).toBeNull();
    expect(within(region).getByRole("button", { name: /^▸ Quarters \(10\)/ })).toHaveAttribute(
      "aria-expanded",
      "false",
    );
    // Opening it again takes it back out of the URL; older history is asked for.
    fireEvent.click(within(region).getByRole("button", { name: /Quarters/ }));
    expect(container.querySelector("[data-search]")).toHaveTextContent(/^$/);
    fireEvent.click(within(region).getByRole("button", { name: "all" }));
    expect(container.querySelector("[data-search]")).toHaveTextContent("?mall=quarters");
    expect(cellOf(container, "revenue", "Q:Q1_2024")).not.toBeNull();
  });

  test("opens with the groups the URL names collapsed", () => {
    const { container } = renderModel(fixture(), "/model/?mcols=base,downside");
    expect(cellOf(container, "revenue", "BASE:2026")).toBeNull();
    expect(cellOf(container, "revenue", "FY:FY2025")).not.toBeNull();
  });

  test("formats money in brackets and multiples with x", () => {
    const { container } = renderModel(fixture());
    // Outflows in brackets, whole units, the exact decimal as the title.
    const interest = cellOf(container, "cash_interest", "FY:FY2025");
    expect(interest).toHaveTextContent("(870)");
    expect(interest).toHaveAttribute("title", "-870");
    expect(cellOf(container, "revenue", "FY:FY2025")).not.toHaveTextContent("(");
    const leverage = cellOf(container, "metric:net_leverage_adjusted", "PF:LTM_Q2_2026");
    expect(leverage).toHaveTextContent(/^3\.3x$/);
    expect(leverage.getAttribute("title")).toMatch(/^3\.327/);
    expect(cellOf(container, "metric:gross_margin", "FY:FY2025")).toHaveTextContent(/^58\.0%$/);
    expect(cellOf(container, "reference_rate", "BASE:2026")).toHaveTextContent(/^3\.80%$/);
    expect(cellOf(container, "dso", "FY:FY2024")).toHaveTextContent(/^\d+$/);
  });

  test("shows n.p., n.a. and n.s. with the reason in the title", () => {
    const { lines } = fixture().body;
    const line = lines.find((entry) => entry.line_id === "dso")!;
    const cell = (reason: NonNullable<(typeof line.cells)[number]["reason"]>) => ({
      ...line.cells[0]!,
      value: null,
      reason,
    });
    expect(shownCell(line, cell("NOT_PROJECTED"))).toEqual({
      text: "n.p.",
      title: "Not projected",
      figure: false,
    });
    expect(shownCell(line, cell("NOT_APPLICABLE")).text).toBe("n.a.");
    expect(shownCell(line, cell("NOT_SOURCED")).text).toBe("n.s.");
    expect(shownCell(line, cell("COMPONENT_MISSING")).text).toBe("n.s.");
    expect(shownCell(line, cell("NOT_STATED")).text).toBe("n.s.");
    expect(shownCell(line, cell("ZERO_OR_NEGATIVE_DENOMINATOR")).text).toBe("n.a.");
    expect(shownCell(line, { ...line.cells[0]!, value: null, reason: null }).title).toBe(
      "No figure served",
    );
    const { container } = renderModel(fixture());
    const marker = cellOf(container, "dso", "BASE:2026");
    expect(marker).toHaveTextContent("n.p.");
    expect(marker).toHaveAttribute("title", "Not projected");
  });

  test("a cell opens the passport with its stated value and sources", () => {
    const { container } = renderModel(fixture());
    fireEvent.click(cellOf(container, "bu:las_vegas", "PYTD:H1_2025"));
    const dialog = screen.getByRole("dialog");
    expect(dialog).toHaveTextContent("Stated in the sources");
    expect(dialog).toHaveTextContent("Sources: ");
    expect(dialog).toHaveTextContent("PYTD H1 25");
  });

  test("a source with a citation opens as a chip, and projected interest names its rate and deck", () => {
    const book = parseBookDocument(
      JSON.parse(readFileSync(resolve(process.cwd(), "fixtures", "book.json"), "utf8")),
    );
    const citation = book.body.rows[0]!.periods[0]!.cells[0]!.passport.citations[0]!;
    const base = fixture();
    const fy25 = indexOfColumn(base.body, "FY:FY2025");
    const lines = base.body.lines.map((line) =>
      line.line_id === "revenue"
        ? {
            ...line,
            cells: line.cells.map((cell, index) =>
              index === fy25
                ? {
                    ...cell,
                    stated: "1001",
                    note: "stated total differs",
                    sources: [{ source_id: "S1", source_locator: "10-K p.4", citation }],
                  }
                : cell,
            ),
          }
        : line,
    );
    const document = parseModelDocument({ ...base, body: { ...base.body, lines } });
    const { container } = renderModel(document);
    fireEvent.click(cellOf(container, "revenue", "FY:FY2025"));
    const dialog = screen.getByRole("dialog");
    expect(dialog).toHaveTextContent("Stated in the sources: 1001");
    expect(dialog).toHaveTextContent("stated total differs");
    expect(dialog).toHaveTextContent(`${citation.filename} p.${citation.page}`);
    const { body } = base;
    const column = body.columns.findIndex((entry) => entry.column_id === "BASE:2026");
    const interest = body.lines.find((line) => line.line_id === "cash_interest")!;
    const passport = passportOfCell({
      body,
      line: interest,
      column: body.columns[column]!,
      cell: interest.cells[column]!,
      index: column,
      observedAt: base.observed_at,
    });
    expect(passport.derivation).toContain(
      "Weighted-average rate 6.12%, rate deck as of 2026-10-01",
    );
    expect(passport.scenario).toBe("BASE");
    expect(passport.unit).toBe("USD MILLIONS");
    const bare = passportOfCell({
      body: { ...body, rate_deck: null },
      line: interest,
      column: body.columns[column]!,
      cell: interest.cells[column]!,
      index: column,
      observedAt: base.observed_at,
    });
    expect(bare.derivation).toContain("no rate deck");
  });

  test("the debt band shows facility terms in their own columns", () => {
    const { container } = renderModel(fixture());
    const terms = (line: string) =>
      [...container.querySelectorAll(`[data-line="${line}"] td[data-term]`)].map(
        (element) => element.textContent,
      );
    expect(terms("fac:tlb")).toEqual(["SOFR", "+275 bp", "0.50%", "2030-02-28", "24 p.a."]);
    // Outside the debt band the five columns are there and empty.
    expect(terms("revenue")).toEqual(["", "", "", "", ""]);
    const heading = container.querySelector("thead th.terms")!;
    expect(heading).toHaveTextContent("Facility terms");
    expect(heading).toHaveAttribute("colspan", "5");
    // A rank opens with an 8px spacer row and its own heading row.
    const rank = [...container.querySelectorAll("tr.rank")].find((row) =>
      row.textContent?.includes("Senior secured"),
    )!;
    expect(rank.previousElementSibling).toHaveClass("gap");
    expect(container.querySelectorAll("tr.rank").length).toBeGreaterThan(2);
  });

  test("tints the pro forma, Base and Downside columns and a refinanced facility cell", () => {
    const { container } = renderModel(fixture());
    expect(cellOf(container, "revenue", "PF:LTM_Q2_2026").parentElement).toHaveClass("col-pf");
    expect(cellOf(container, "revenue", "BASE:2026").parentElement).toHaveClass("col-base");
    expect(cellOf(container, "revenue", "DOWNSIDE:2026").parentElement).toHaveClass("col-down");
    expect(cellOf(container, "revenue", "FY:FY2025").parentElement).not.toHaveClass("col-base");
    expect(container.querySelectorAll("td.cell-refi").length).toBeGreaterThan(0);
    // Only a facility wears the refinanced tint, and only on the host's note.
    const { lines } = fixture().body;
    const facility = lines.find((line) => line.line_id === "fac:tlb")!;
    const revenue = lines.find((line) => line.line_id === "revenue")!;
    const assumed = { ...facility.cells[0]!, note: "assumed refinanced" };
    expect(refinanced(facility, assumed)).toBe(true);
    expect(refinanced(revenue, assumed)).toBe(false);
    expect(refinanced(facility, facility.cells[0]!)).toBe(false);
    const { columns } = fixture().body;
    expect(tintOf(columns.find((column) => column.kind === "PF_LTM")!)).toBe("pf");
    expect(tintOf(columns.find((column) => column.kind === "FY")!)).toBeNull();
    expect(tintOf(columns.find((column) => column.case === "BASE")!)).toBe("base");
    expect(tintOf(columns.find((column) => column.case === "DOWNSIDE")!)).toBe("down");
  });

  test("two header rows sit on the grid's own sticky classes with a pinned first column", () => {
    const { container } = renderModel(fixture());
    const table = container.querySelector("table")!;
    expect(table).toHaveClass("tbl", "dense", "pin-first", "model-grid");
    expect(table.querySelectorAll("thead tr")).toHaveLength(2);
    expect(table.closest(".tscroll")).toHaveAttribute("role", "region");
    expect(table.closest(".tscroll")!.querySelector("[style]")).toBeNull();
  });

  test("shows the header: unit, rate deck and the unrealised add-backs switch", () => {
    const { container } = renderModel(fixture());
    expect(container.querySelector("[data-model-unit]")).toHaveTextContent("USD millions");
    expect(container.querySelector("[data-model-deck]")).toHaveTextContent("rate deck 2026-10-01");
    const box = screen.getByRole("checkbox", { name: /Exclude unrealised add-backs/ });
    expect(box).not.toBeChecked();
    fireEvent.click(box);
    expect(container.querySelector("[data-search]")).toHaveTextContent("?exclude_unrealised=1");
    expect(screen.getByRole("checkbox", { name: /Exclude unrealised/ })).toBeChecked();
    fireEvent.click(box);
    expect(container.querySelector("[data-search]")).toHaveTextContent(/^$/);
    const bare = fixture();
    const none = parseModelDocument({ ...bare, body: { ...bare.body, rate_deck: null } });
    const { container: other } = renderModel(none);
    expect(other.querySelector("[data-model-deck]")).toHaveTextContent("no rate deck");
  });

  test("the unrealised switch reaches the model read and no other", () => {
    expect(sectionUrl("model", { case: "c", excludeUnrealised: "1" })).toBe(
      "/api/v1/cases/c/model?exclude_unrealised=1",
    );
    expect(sectionUrl("model", { case: "c", excludeUnrealised: "yes" })).toBe(
      "/api/v1/cases/c/model",
    );
    expect(sectionUrl("analysis", { case: "c", excludeUnrealised: "1" })).toBe(
      "/api/v1/cases/c/analysis",
    );
  });

  test("limitations render without any line, beside the accepted forecast", () => {
    const { container } = renderModel(
      model({ limitations: ["CP-1 tables could not be read"], currency: null }),
    );
    expect(container.querySelector("[data-model-limitations]")).toHaveTextContent(
      "CP-1 tables could not be read",
    );
    expect(container.querySelector("[data-model-grid]")).toBeNull();
    expect(container).toHaveTextContent("Accepted forecast");
    expect(container.querySelector("[data-model-strip]")).toBeNull();
    // No model: no switch to flip.
    expect(screen.queryByRole("checkbox")).toBeNull();
  });

  test("draws three charts from the same cells: history as Actual, two projected cases", () => {
    const body = fixture().body;
    const charts = stripCharts(body);
    expect(charts.map((chart) => chart.key)).toEqual([
      "metric:net_leverage_adjusted",
      "metric:interest_coverage_adjusted",
      "liquidity",
    ]);
    const [leverage, , liquidity] = charts;
    expect(leverage!.categories).toEqual([
      "FY23",
      "FY24",
      "FY25",
      "LTM Q2 26",
      "FY26E",
      "FY27E",
      "FY28E",
    ]);
    expect(leverage!.series.map((series) => series.label)).toEqual([
      "Actual",
      "Base case",
      "Downside case",
    ]);
    expect(leverage!.unit).toBe("multiple");
    expect(liquidity!.unit).toBe("USD MILLIONS");
    // A cell with no figure is a gap with its reason.
    expect(leverage!.series[1]!.data[0]).toEqual({ value: null, reason: "not projected" });
    const { container } = render(<ChartStrip body={body} />);
    expect(container.querySelectorAll("[data-strip-chart]")).toHaveLength(3);
    const empty = render(<ChartStrip body={{ ...body, lines: [] }} />);
    expect(empty.container.querySelector("[data-model-strip]")).toBeNull();
  });

  test("column groups: names, trimming and the URL list", () => {
    const { columns } = fixture().body;
    expect(GROUP_IDS).toEqual(["quarters", "ytd", "fy", "ltm", "pf", "base", "downside"]);
    expect(columns.map(groupOf)).toContain("downside");
    // LTM and PF-LTM are separate groups, so they collapse on their own.
    const ltm = columns.find((column) => column.kind === "LTM")!;
    const pf = columns.find((column) => column.kind === "PF_LTM")!;
    expect([groupOf(ltm), groupOf(pf)]).toEqual(["ltm", "pf"]);
    const groups = columnGroups(columns, new Set(), new Set());
    expect(groups.map((group) => group.id)).toEqual([...GROUP_IDS]);
    expect(groups[0]!.columns).toHaveLength(4);
    expect(groups[0]!.total).toBe(10);
    expect(groups[0]!.trimmed).toBe(true);
    expect(groups[2]!.columns).toHaveLength(3);
    expect(groups[2]!.trimmed).toBe(false);
    expect(groups[3]!.columns.map((entry) => entry.column.kind)).toEqual(["LTM"]);
    expect(groups[4]!.columns.map((entry) => entry.column.kind)).toEqual(["PF_LTM"]);
    expect(groups[0]!.columns[0]!.column.column_id).toBe("Q:Q3_2025");
    expect(columnGroups(columns, new Set(), new Set(["quarters"]))[0]!.columns).toHaveLength(10);
    expect(columnGroups(columns, new Set(["fy"]), new Set())[2]).toMatchObject({
      collapsed: true,
      columns: [],
      total: 3,
    });
    expect([...groupList("fy,nonsense,quarters")]).toEqual(["quarters", "fy"]);
    expect([...groupList("pf,ltm")]).toEqual(["ltm", "pf"]);
    expect([...groupList(null)]).toEqual([]);
    expect(toggled(new Set(["fy"]), "quarters")).toBe("quarters,fy");
    expect(toggled(new Set(["fy"]), "fy")).toBe("");
  });

  test("a cell button and the grid stand alone", () => {
    const body = fixture().body;
    const line = body.lines.find((entry) => entry.line_id === "revenue")!;
    const { container } = render(
      <MemoryRouter>
        <EvidenceProvider>
          <ModelCellButton
            body={body}
            line={line}
            index={indexOfColumn(body, "FY:FY2025")}
            observedAt="2026-10-10T00:00:00Z"
          />
          <ModelGrid body={body} observedAt="2026-10-10T00:00:00Z" />
        </EvidenceProvider>
      </MemoryRouter>,
    );
    expect(container.querySelector("button.cellbtn")).toHaveAccessibleName(/Total revenue · FY25/);
  });

  test("a negative percent and rate keep their minus; money that rounds to zero has no bracket", () => {
    const { lines } = fixture().body;
    const template = lines.find((entry) => entry.line_id === "dso")!;
    const read = (unit: typeof template.unit, value: string, label: string | null = null) =>
      shownCell(
        { ...template, unit, unit_label: label },
        { ...template.cells[0]!, value, reason: null },
      ).text;
    expect(read("PERCENT", "-0.0512")).toBe("-5.1%");
    expect(read("RATE", "-0.0125")).toBe("-1.25%");
    expect(read("MULTIPLE", "-1.04")).toBe("-1.0x");
    expect(read("MONEY", "-1234.4")).toBe("(1,234)");
    // A small outflow that rounds to nothing reads 0, not (0).
    expect(read("MONEY", "-0.4")).toBe("0");
    expect(read("MONEY", "0.4")).toBe("0");
    // Half rounds away from zero, on the digits.
    expect(read("MONEY", "0.5")).toBe("1");
    expect(read("MONEY", "-0.5")).toBe("(1)");
    expect(read("MONEY", "2.4999")).toBe("2");
    expect(read("MULTIPLE", "3.25")).toBe("3.3x");
    expect(read("PERCENT", "0.12345")).toBe("12.3%");
    expect(read("PERCENT", "0.12350")).toBe("12.4%");
    expect(read("KPI", "90.95", "PERCENT")).toBe("91.0%");
    expect(read("DAYS", "9.5")).toBe("10");
  });

  test("a marker's accessible name carries its reason; rows and columns are scoped headers", () => {
    const { container } = renderModel(fixture());
    const marker = cellOf(container, "dso", "BASE:2026");
    expect(marker).toHaveAccessibleName("DSO · FY26E · n.p. (not projected)");
    expect(cellOf(container, "revenue", "FY:FY2025")).toHaveAccessibleName(
      /^Total revenue · FY25 · [\d,]+$/,
    );
    const rowHead = container.querySelector('[data-line="revenue"] > th')!;
    expect(rowHead).toHaveAttribute("scope", "row");
    expect(rowHead).toHaveClass("lab");
    const heads = [...container.querySelectorAll("thead th")];
    expect(
      heads.every(
        (head) => (head.textContent ?? "").trim() !== "" || head.hasAttribute("aria-label"),
      ),
    ).toBe(true);
    expect(container.querySelector("tr.p th:not(:first-child)")).toHaveAttribute("scope", "col");
    expect(container.querySelector("tr.g th.lab")).toHaveTextContent("Line");
  });

  test("LTM and PF-LTM collapse independently", () => {
    const { container } = renderModel(fixture(), "/model/?mcols=pf");
    expect(cellOf(container, "revenue", "LTM:LTM_Q2_2026")).not.toBeNull();
    expect(cellOf(container, "revenue", "PF:LTM_Q2_2026")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: /^▸ PF-LTM/ }));
    expect(container.querySelector("[data-search]")).toHaveTextContent(/^$/);
    expect(cellOf(container, "revenue", "PF:LTM_Q2_2026")).not.toBeNull();
  });
});

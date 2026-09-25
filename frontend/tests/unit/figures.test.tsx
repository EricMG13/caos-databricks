// A module's figures come from the tables the server served, exactly: the
// right chart per table, periods in the register's order, exact sums, and a
// pressed mark named in the right column (plan step 5).
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { fireEvent, render, within } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { AnalysisSection } from "@/sections/analysis/AnalysisSection";
import {
  addbackValidation,
  addbacks,
  comparatorChanges,
  figuresOf,
  forecastDrivers,
  kpiLines,
  maturityLadder,
  recordsOf,
  segmentMix,
  sumOf,
  unitOf,
} from "@/sections/analysis/figures";
import { parseAnalysisDocument } from "@/wire/v1";

const document = parseAnalysisDocument(
  JSON.parse(readFileSync(resolve(process.cwd(), "fixtures/analysis.json"), "utf8")),
);
const cp1 = document.body.handoffs.find((handoff) => handoff.module_id === "CP-1")!;

test("test_sumOf_is_exact_and_unitOf_reads_the_register", () => {
  expect(sumOf(["0.1", "0.2"])).toEqual({ value: "0.3", complete: true });
  expect(sumOf(["9007199254740993", "1"])).toEqual({
    value: "9007199254740994",
    complete: true,
  });
  expect(sumOf([null, undefined])).toEqual({ value: null, complete: false });
  // R24-13: a partial sum states what is known and that it is not the whole
  // -- never a number silently standing in for a total with a missing member.
  expect(sumOf(["1", null])).toEqual({ value: "1", complete: false });
  expect(sumOf([])).toEqual({ value: null, complete: true });
  expect(unitOf("USD", "MILLIONS")).toBe("USD m");
  expect(unitOf("", "MILLIONS")).toBeUndefined();
  expect(recordsOf(cp1.tables[0]!)[0]!["period_id"]?.text).toBe("FY2025");
});

test("test_segmentMix_stacks_revenue_by_period_in_the_register_order", () => {
  const figure = segmentMix(cp1.tables)!;
  expect(figure.kind).toBe("stack");
  expect(figure.categories).toEqual(["Q2-2025", "Q3-2025", "Q4-2025", "Q1-2026", "Q2-2026"]);
  expect(figure.series.map((series) => series.key)).toEqual(["RETAIL", "WHOLESALE", "OTHER"]);
  expect(figure.series.every((series) => series.origin === "model")).toBe(true);
  expect(figure.unit).toBe("USD m");
  expect(figure.summary).toBe("Q2-2026: 7,394 USD m across 3 segments.");
});

test("test_kpiLines_draws_each_operating_kpi_on_its_own_axis", () => {
  const figures = kpiLines(cp1.tables);
  expect(figures.map((figure) => figure.kind)).toEqual(figures.map(() => "line"));
  const units = figures.find((figure) => figure.key === "kpi-retail_units_sold")!;
  expect(units.series[0]!.data.map((datum) => datum.value)).toEqual([
    "143280",
    "155941",
    "163522",
    "184114",
    "197325",
  ]);
  expect(units.unit).toBe("units");
});

test("test_addbacks_and_maturityLadder_read_the_latest_period", () => {
  const items = addbacks(cp1.tables)!;
  expect(items.kind).toBe("diverging");
  expect(items.title).toMatch(/^Add-backs to EBITDA, /);
  // A bracketed figure is negative, and the net is summed exactly.
  expect(items.series[0]!.data.some((datum) => datum.value?.startsWith("-"))).toBe(true);
  expect(items.summary).toMatch(/^Net [+-][\d,]+ USD m across \d+ add-backs\.$/);
  const ladder = maturityLadder(cp1.tables)!;
  expect(ladder.categories).toEqual([...ladder.categories].sort());
  expect(ladder.series.find((series) => series.key === "SECURED SENIOR")?.color).toBe("tranche-1l");
  // Every underscore goes, and a status stated twice is said once.
  expect(ladder.series.find((series) => series.key === "NOT_STATED NOT_STATED")?.label).toBe(
    "Not stated",
  );
  expect(figuresOf(cp1).map((figure) => figure.key)[0]).toBe("segment-mix");
  // A module with no tables draws nothing.
  expect(figuresOf({ ...cp1, tables: [] })).toEqual([]);
});

test("the change chart is drawn only past what the key figures already print", () => {
  const cp1b = document.body.handoffs.find((handoff) => handoff.module_id === "CP-1B")!;
  const register = cp1b.tables.find(
    (table) => table.table_id === "cp1b.model_comparator_register",
  )!;
  // Six comparisons: every one is a key figure beside the view.
  expect(register.rows).toHaveLength(6);
  expect(figuresOf(cp1b).map((figure) => figure.key)).not.toContain("comparator");
  const seven = {
    ...cp1b,
    tables: cp1b.tables.map((table) =>
      table === register ? { ...table, rows: [...table.rows, table.rows[0]!] } : table,
    ),
  };
  expect(figuresOf(seven).map((figure) => figure.key)).toContain("comparator");
  // The figures share one key, in their header, with what the host calculated.
  const { container } = render(
    <MemoryRouter>
      <AnalysisSection document={document} tab={cp1b.route_node_id} />
    </MemoryRouter>,
  );
  const head = container.querySelector("[data-figures] > header")!;
  expect(head.querySelector("[data-figures-key]")).toHaveTextContent(
    "Outlined: model-authored, not host-verified",
  );
  expect(head.querySelector("[data-host-calculation]")).not.toBeNull();
  expect(container.querySelector("[data-figures] .chart .chart-provenance")).toBeNull();
  // A module whose tables draw nothing has no Figures heading, only the
  // host's calculation statement.
  const only = { ...cp1b, tables: [register] };
  const { container: bare } = render(
    <MemoryRouter>
      <AnalysisSection
        document={{ ...document, body: { ...document.body, handoffs: [only] } }}
        tab={only.route_node_id}
      />
    </MemoryRouter>,
  );
  expect(bare.querySelector("[data-figures]")).toBeNull();
  // Drawn as a caveat on the module, not a loose line between its cards.
  expect(bare.querySelector(".calc-caveat > [data-host-calculation]")).not.toBeNull();
});

test("pressing a mark names it beside the figures, with its stated source", () => {
  const { container } = render(
    <MemoryRouter>
      <AnalysisSection document={document} tab={cp1.route_node_id} />
    </MemoryRouter>,
  );
  const figure = container.querySelector("[data-figure='segment-mix']")!;
  const mark = within(figure as HTMLElement).getAllByRole("button", { name: /Q2-2026/ })[0]!;
  fireEvent.click(mark);
  const picked = container.querySelector("[data-figures] ~ [data-picked]")!;
  expect(picked).toHaveTextContent("Revenue by segment");
  expect(picked).toHaveTextContent("Model-authored, not host-verified");
  expect(picked.querySelector("[data-picked-value]")!.textContent).toMatch(/USD m$/);
  expect(picked).toHaveTextContent("CVNA_10Q");
});

test("a module whose tables could not be read says so and draws none", () => {
  const refused = { ...cp1, tables: [], tables_unavailable_reason: "TABLES_MALFORMED" as const };
  const { container } = render(
    <MemoryRouter>
      <AnalysisSection
        document={{ ...document, body: { ...document.body, handoffs: [refused] } }}
        tab={refused.route_node_id}
      />
    </MemoryRouter>,
  );
  expect(container.querySelector("[data-tables-unavailable='TABLES_MALFORMED']")).not.toBeNull();
  expect(container.querySelector("[data-figures]")).toBeNull();
});

test("add-backs the model labelled alike stay two bars, and undated debt is not the nearest", () => {
  const bridge = cp1.tables.find((table) => table.table_id === "cp1.adjusted_ebitda_bridge")!;
  const label = bridge.columns.indexOf("addback_label");
  const period = bridge.columns.indexOf("period_id");
  const latest = bridge.rows.at(-1)![period]!.text;
  const twins = {
    ...bridge,
    rows: bridge.rows.map((row) =>
      row[period]!.text === latest
        ? row.map((cell, index) => (index === label ? { text: "Other", value: null } : cell))
        : row,
    ),
  };
  const figure = addbacks(cp1.tables.map((table) => (table === bridge ? twins : table)))!;
  expect(new Set(figure.categories).size).toBe(figure.categories.length);
  const debt = cp1.tables.find((table) => table.table_id === "cp1.debt_facility_register")!;
  const maturity = debt.columns.indexOf("maturity_date");
  const undatedFirst = {
    ...debt,
    rows: debt.rows.map((row, index) =>
      index === 0
        ? row.map((cell, at) => (at === maturity ? { text: "", value: null } : cell))
        : row,
    ),
  };
  const ladder = maturityLadder(
    cp1.tables.map((table) => (table === debt ? undatedFirst : table)),
  )!;
  expect(ladder.categories.at(-1)).toBe("Undated");
  expect(ladder.summary).toMatch(/falls due \d{4}-\d{2}-\d{2}\.$/);
});

test("a maturity segment summing two facilities names both stated sources", () => {
  const ladder = maturityLadder(cp1.tables)!;
  const secured = ladder.series.find((series) => series.key === "SECURED SENIOR")!;
  const index = ladder.categories.indexOf("2028");
  const source = ladder.sourceOf({
    series: secured.key,
    category: "2028",
    index,
    value: secured.data[index]!.value,
    origin: "model",
  })!;
  expect(source).toContain("Floor Plan");
  expect(source.split("; ")).toHaveLength(2);
});

// R24-13: a caption that sums known segment values without saying one is
// missing presents an incomplete aggregate as complete.
test("a segment caption states a partial sum as known, not as the total", () => {
  const revenue = cp1.tables.find((table) => table.table_id === "cp1.segment_revenue_schedule")!;
  const segment = revenue.columns.indexOf("segment_id");
  const value = revenue.columns.indexOf("revenue");
  const withheld = {
    ...revenue,
    rows: revenue.rows.map((row) =>
      row[segment]!.text === "OTHER"
        ? row.map((cell, index) => (index === value ? { text: "n/a", value: null } : cell))
        : row,
    ),
  };
  const complete = segmentMix(cp1.tables)!;
  expect(complete.summary).toBe("Q2-2026: 7,394 USD m across 3 segments.");
  const figure = segmentMix(cp1.tables.map((table) => (table === revenue ? withheld : table)))!;
  // The two known segments' own sum, not the fixture's full total, and
  // explicitly short of "3 segments" rather than silently across all of them.
  expect(figure.summary).toBe("Q2-2026: 6,806 USD m known across 2 of 3 segments (1 unavailable).");
  // The chart's own mark for the withheld segment is still a stated gap, not
  // a silent zero (unaffected by this fix; the caption was the only defect).
  const withheldSeries = figure.series.find((series) => series.key === "OTHER")!;
  expect(withheldSeries.data.at(-1)).toEqual({ value: null, reason: "n/a" });
});

// R24-13: a facility with an unknown amount (the fixture's own
// FINANCE_LEASES row, principal "Not applicable") must not vanish from the
// maturity chart -- it belongs to a real class and year (here, undated) that
// a facility-dropping filter would silently omit from `categories`/`series`
// altogether -- and the caption must say the total is a known subtotal, not
// present it as every facility's principal.
test("an unstated principal keeps its facility on the ladder instead of vanishing", () => {
  const ladder = maturityLadder(cp1.tables)!;
  expect(ladder.categories).toContain("Undated");
  const unstatedClass = ladder.series.find((series) => series.key === "NOT_STATED NOT_STATED")!;
  const index = ladder.categories.indexOf("Undated");
  expect(unstatedClass.data[index]).toEqual({ value: null, reason: "not stated" });
  expect(
    ladder.sourceOf({
      series: unstatedClass.key,
      category: "Undated",
      index,
      value: null,
      origin: "model",
    }),
  ).toContain("Finance lease");
  expect(ladder.summary).toBe(
    "5,530 USD m known principal across 5 of 6 facilities (1 unstated); the nearest," +
      " 5.50% Senior Notes due 2027, falls due 2027-04-15.",
  );
});

// R24-13: the nearest-maturity claim must not depend on whether the nearest
// facility's principal happens to be known -- a maturity date is not less
// near for it.
test("the nearest maturity date does not move when its own principal is unstated", () => {
  const debt = cp1.tables.find((table) => table.table_id === "cp1.debt_facility_register")!;
  const facility = debt.columns.indexOf("facility_id");
  const principal = debt.columns.indexOf("principal");
  // SUN_2027 (2027-04-15) is the nearest maturity in the fixture, ahead of
  // Floor Plan (2028-03-31); this states its principal unknown without
  // touching its maturity date.
  const unstated = {
    ...debt,
    rows: debt.rows.map((row) =>
      row[facility]!.text === "SUN_2027"
        ? row.map((cell, index) =>
            index === principal ? { text: "Not stated", value: null } : cell,
          )
        : row,
    ),
  };
  const ladder = maturityLadder(cp1.tables.map((table) => (table === debt ? unstated : table)))!;
  // Still the nearest: principal availability never enters that choice.
  expect(ladder.summary).toMatch(
    /the nearest, 5\.50% Senior Notes due 2027, falls due 2027-04-15\.$/,
  );
  // A second facility now unstated, its own class/year cell retained as a
  // gap rather than dropped or silently folded into 0.
  expect(ladder.summary).toBe(
    "5,455 USD m known principal across 4 of 6 facilities (2 unstated); the nearest," +
      " 5.50% Senior Notes due 2027, falls due 2027-04-15.",
  );
  expect(ladder.categories).toContain("2027");
  const unsecured = ladder.series.find((series) => series.key === "UNSECURED SENIOR")!;
  const index = ladder.categories.indexOf("2027");
  expect(unsecured.data[index]).toEqual({ value: null, reason: "not stated" });
});

// N56: the three modules the demo route now carries, each read from the
// table the bundle names, in its exact columns.
const handoffOf = (module: string) =>
  document.body.handoffs.find((handoff) => handoff.module_id === module)!;

test("comparatorChanges: each metric's change in percent, an uncalculable one a gap", () => {
  const figure = comparatorChanges(handoffOf("CP-1B").tables)!;
  expect(figure.kind).toBe("diverging");
  expect(figure.unit).toBe("%");
  // One basis names the figure, so each bar is only its metric.
  expect(figure.title).toBe("Change year on year, %");
  expect(figure.categories).toEqual([
    "Revenue",
    "Adjusted EBITDA",
    "Net income",
    "CFO",
    "Net debt",
    "FCF",
  ]);
  const data = figure.series[0]!.data;
  // The bundle's fraction (0.1545) read as a percent on its digits.
  expect(data[0]).toEqual({ value: "15.45" });
  expect(data[3]).toEqual({ value: "-23.72" });
  expect(data.at(-1)).toEqual({ value: null, reason: "Not Calculable" });
  expect(figure.summary).toMatch(/^Largest move: Net income .*166\.67%\. 1 not calculable\.$/);
  expect(
    figure.sourceOf({
      series: "change",
      category: figure.categories[0]!,
      index: 0,
      value: "15.45",
      origin: "model",
    }),
  ).toBe("Q2-2026 against Q2-2025: 6,112/5,294");
});

test("addbackValidation: every period's differences, with what the module ruled", () => {
  const figure = addbackValidation(handoffOf("CP-1B").tables)!;
  expect(figure.title).toBe("Add-backs against CP-1");
  expect(figure.categories).toHaveLength(8);
  expect(figure.categories[6]).toBe("Restructuring, Q2-2026");
  expect(figure.series[0]!.data[6]).toEqual({ value: "2" });
  expect(figure.summary).toBe("7 of 8 pass, 1 warn across 2 periods.");
  expect(
    figure.sourceOf({
      series: "difference",
      category: "Restructuring, Q2-2026",
      index: 6,
      value: "2",
      origin: "model",
    }),
  ).toMatch(/^WARN · The 10-Q books 2 of site costs/);
});

// Security and saboteur review: the figures read what the model wrote, so
// each of these is a table a model can write.
const table = (table_id: string, columns: string[], rows: string[][]) => ({
  table_id,
  columns,
  rows: rows.map((row) =>
    row.map((text) => ({
      text,
      value: /^-?[0-9]+(\.[0-9]+)?%?$/.test(text) ? text.replace("%", "") : null,
    })),
  ),
});
const COMPARATOR = [
  "metric_id",
  "current_period_id",
  "reference_period_id",
  "comparison_basis",
  "percentage_change",
  "calculation_status",
];

test("a rate written with a percent sign is not scaled again (it is points, not a fraction)", () => {
  const figure = comparatorChanges([
    table("cp1b.model_comparator_register", COMPARATOR, [
      ["revenue", "Q2-2026", "Q2-2025", "YOY_SAME_QUARTER", "15.45%", "Calculated"],
      ["ebitda", "Q2-2026", "Q2-2025", "YOY_SAME_QUARTER", "0.2379", "Calculated"],
    ]),
  ])!;
  expect(figure.series[0]!.data).toEqual([{ value: "15.45" }, { value: "23.79" }]);
  const [growth] = forecastDrivers([
    table(
      "cp2g.cp_model_forecast_drivers",
      ["driver_id", "slot_id", "case", "fiscal_year", "value", "status"],
      [
        ["division_growth", "DIVISION_1", "BASE", "2026", "8%", "READY"],
        ["division_growth", "DIVISION_1", "BASE", "2027", "0.06", "READY"],
      ],
    ),
  ]);
  expect(growth!.series[0]!.data).toEqual([{ value: "8" }, { value: "6" }]);
  expect(growth!.summary).toMatch(/^Base \+?8(\.0+)?% to \+?6(\.0+)?%/);
});

test("a metric compared twice on one basis is two named bars, not two alike", () => {
  const figure = comparatorChanges([
    table("cp1b.model_comparator_register", COMPARATOR, [
      ["revenue", "Q1-2026", "Q1-2025", "YOY_SAME_QUARTER", "0.1", "Calculated"],
      ["revenue", "Q2-2026", "Q2-2025", "YOY_SAME_QUARTER", "0.2", "Calculated"],
    ]),
  ])!;
  expect(figure.categories).toEqual(["Revenue, Q1-2026", "Revenue, Q2-2026"]);
});

test("a BLOCK in any period shows, whatever order the register lists its periods in", () => {
  const columns = ["addback_id", "period_id", "difference", "status", "explanation"];
  const figure = addbackValidation([
    table("cp1b.addback_validation_register", columns, [
      ["SBC", "Q2-2026", "5", "BLOCK", "unreconciled"],
      ["SBC", "Q1-2026", "0", "PASS", ""],
    ]),
  ])!;
  expect(figure.categories).toEqual(["SBC, Q2-2026", "SBC, Q1-2026"]);
  expect(figure.summary).toBe("1 of 2 pass, 1 block model readiness across 2 periods.");
});

test("an unknown case sorts after base and downside, and rank 0 is a rank", () => {
  const [growth] = forecastDrivers([
    table(
      "cp2g.cp_model_forecast_drivers",
      ["driver_id", "slot_id", "case", "fiscal_year", "value", "status"],
      [
        ["division_growth", "DIVISION_1", "STRESS", "2026", "0.01", "READY"],
        ["division_growth", "DIVISION_1", "DOWNSIDE", "2026", "0.02", "READY"],
        ["division_growth", "DIVISION_1", "BASE", "2026", "0.03", "READY"],
      ],
    ),
  ]);
  expect(growth!.series.map((series) => series.key)).toEqual(["BASE", "DOWNSIDE", "STRESS"]);
});

test("the catalyst list sorts by rank, whatever order the model wrote", () => {
  const cp2b = handoffOf("CP-2B");
  const [catalysts] = cp2b.tables;
  const shuffled = {
    ...document,
    body: {
      ...document.body,
      handoffs: document.body.handoffs.map((handoff) =>
        handoff === cp2b
          ? { ...handoff, tables: [{ ...catalysts!, rows: [...catalysts!.rows].reverse() }] }
          : handoff,
      ),
    },
  };
  const { container } = render(
    <MemoryRouter>
      <AnalysisSection document={shuffled} tab="rn-cp-2b" />
    </MemoryRouter>,
  );
  expect(
    [...container.querySelectorAll("[data-catalyst]")].map((item) =>
      item.getAttribute("data-catalyst"),
    ),
  ).toEqual(["1", "2", "3", "4"]);
});

test("a table built to be expensive is stated, not drawn, and costs no more than its rows", () => {
  // 2,000 facilities, each in its own class and year: 4 million marks drawn
  // as a stack, and seconds of nested lookups, before F327.
  const rows = Array.from({ length: 2000 }, (_, index) => [
    `F${index}`,
    "Q2-2026",
    `CLASS_${index}`,
    "SENIOR",
    `${3000 + index}-01-01`,
    "100",
  ]);
  const started = performance.now();
  const ladder = maturityLadder([
    table(
      "cp1.debt_facility_register",
      ["facility_name", "period_id", "secured_status", "seniority", "maturity_date", "principal"],
      rows,
    ),
  ])!;
  expect(performance.now() - started).toBeLessThan(1000);
  expect(ladder.oversized).toBe(true);
  expect(ladder.series).toEqual([]);
  expect(ladder.summary).toMatch(/^4000000 marks: too many to draw/);
});

test("forecastDrivers: one figure a division, base against downside, in percent", () => {
  const figures = forecastDrivers(handoffOf("CP-2G").tables);
  expect(figures.map((figure) => figure.title)).toEqual([
    "Division 1 growth, %",
    "Division 2 growth, %",
    "Division 3 growth, %",
  ]);
  const first = figures[0]!;
  expect(first.categories).toEqual(["2026", "2027", "2028"]);
  expect(first.series.map((series) => series.label)).toEqual(["Base", "Downside"]);
  expect(first.series[0]!.data).toEqual([{ value: "8" }, { value: "7" }, { value: "6" }]);
  expect(first.series[1]!.data).toEqual([{ value: "-6" }, { value: "-2" }, { value: "1" }]);
  expect(first.summary).toMatch(
    /^Base .*8.*% to .*6.*%; Downside .*6.*% to .*1.*%, 2026 to 2028\.$/,
  );
  // The currency drivers carry no division and draw nothing here.
  expect(figuresOf(handoffOf("CP-2G")).map((figure) => figure.table)).toEqual([
    "cp2g.cp_model_forecast_drivers",
    "cp2g.cp_model_forecast_drivers",
    "cp2g.cp_model_forecast_drivers",
  ]);
});

test("CP-2B's catalysts are a ranked, dated list, not a chart", () => {
  const { container } = render(
    <MemoryRouter>
      <AnalysisSection document={document} tab="rn-cp-2b" />
    </MemoryRouter>,
  );
  const list = container.querySelector("[data-catalysts]")!;
  expect(
    within(list as HTMLElement).getByRole("heading", { name: "Catalysts, ranked" }),
  ).toBeVisible();
  const items = [...list.querySelectorAll("li")];
  expect(items.map((item) => item.getAttribute("data-catalyst"))).toEqual(["1", "2", "3", "4"]);
  expect(items[0]).toHaveTextContent("2027-03-31");
  expect(items[0]).toHaveTextContent("Springing leverage test on the revolver");
  expect(items[0]).toHaveTextContent("p.22, Note 9 Debt, financial covenants");
  expect(container.querySelector("[data-figure]")).toBeNull();
});

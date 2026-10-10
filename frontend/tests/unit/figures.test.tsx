// A module's figures come from the tables the server served, exactly: the
// right chart per table, periods in the register's order, exact sums, and a
// pressed mark named in the right column (plan step 5).
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { fireEvent, render, within } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { AnalysisSection } from "@/sections/analysis/AnalysisSection";
import { bridgeOf } from "@/charts";
import {
  MAX_FIGURES,
  MAX_MARKS,
  datum,
  groupBy,
  oversized,
  pair,
  sumOf,
  text,
} from "@/sections/analysis/figure-core";
import {
  accountLines,
  addbackValidation,
  addbacks,
  cashFlowBridge,
  comparatorChanges,
  figuresOf,
  forecastDrivers,
  kpiLines,
  maturityLadder,
  recordsOf,
  segmentMix,
  unitOf,
} from "@/sections/analysis/figures";
import { parseAnalysisDocument, type HandoffView } from "@/wire/v1";

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

test("the readers the register figures share: groupBy, pair, text, datum, oversized", () => {
  // Groups in the order each key first appears, rows in their own order.
  expect([...groupBy(["b1", "a1", "b2"], (value) => value[0]!)]).toEqual([
    ["b", ["b1", "b2"]],
    ["a", ["a1"]],
  ]);
  // Two cells as one key: no split of one text into two reads as another.
  expect(pair("a b", "c")).not.toBe(pair("a", "b c"));
  const row = {
    Threshold: { text: "4.50x [C1]", value: "4.50" },
    Headroom: { text: "", value: null },
  };
  expect(text(row, "Threshold")).toBe("4.50x [C1]");
  expect(text(row, "Formula")).toBe("");
  expect(datum(row.Threshold)).toEqual({ value: "4.50" });
  // A gap keeps the cell's text as its reason; an empty or absent cell is
  // not stated, never zero.
  expect(datum({ text: "Not Calculable", value: null })).toEqual({
    value: null,
    reason: "Not Calculable",
  });
  expect(datum(row.Headroom)).toEqual({ value: null, reason: "not stated" });
  expect(datum(undefined)).toEqual({ value: null, reason: "not stated" });
  const stated = oversized("k", "T4C.4", "Covenant headroom", MAX_MARKS + 1);
  expect(stated).toMatchObject({ oversized: true, table: "T4C.4", title: "Covenant headroom" });
  expect(stated.summary).toBe("2001 marks: too many to draw. The Appendix tab lists every row.");
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

test("past MAX_FIGURES a module's figures are stated, the last saying how many more", () => {
  // A line a KPI: MAX_FIGURES + 2 KPIs would be as many figures.
  const rows = Array.from({ length: MAX_FIGURES + 2 }, (_, index) => [`K${index}`, "FY", "1"]);
  const kpis = table("cp1.operating_kpi_schedule", ["kpi_id", "period_id", "value"], rows);
  const figures = figuresOf({ ...cp1, tables: [kpis] });
  expect(figures).toHaveLength(MAX_FIGURES);
  expect(figures.at(-1)).toMatchObject({ oversized: true, title: "3 more figures" });
  expect(figures.at(-1)!.summary).toBe(
    "3 more figures are not drawn. The Appendix tab lists every row.",
  );
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

// CP-1's account register, served typed since D32 and drawn nowhere until
// now. Its figures here are made up for the test: the demo fixture carries no
// account register. The periods are the fixture's own register.
const ACCOUNT = [
  "metric_id",
  "period_id",
  "value",
  "calculation_status",
  "source_id",
  "source_locator",
];
const periodRegister = cp1.tables.find((t) => t.table_id === "cp1.model_period_register")!;
const accountRegister = (rows: string[][]) => [
  periodRegister,
  table(
    "cp1.model_account_register",
    ACCOUNT,
    rows.map(([metric, period, value, status = "REPORTED"]) => [
      metric!,
      period!,
      value!,
      status,
      "S1",
      `p.${period}`,
    ]),
  ),
];

test("accountLines: earnings keep to one type of period, balances to one point a date", () => {
  const tables = accountRegister([
    ...["2400", "520", "560", "610", "690", "758", "1448", "2618"].map((value, index) => [
      "ebitda",
      ["FY2025", "Q2-2025", "Q3-2025", "Q4-2025", "Q1-2026", "Q2-2026", "H1-2026", "LTM-Q2-2026"][
        index
      ]!,
      value,
    ]),
    ["adjusted_ebitda", "Q2-2025", "530"],
    ["adjusted_ebitda", "Q3-2025", "575"],
    ["adjusted_ebitda", "Q4-2025", "620"],
    ["adjusted_ebitda", "Q1-2026", "null", "NOT_AVAILABLE"],
    ["adjusted_ebitda", "Q2-2026", "769"],
    ["total_debt", "FY2025", "5600"],
    ["total_debt", "Q2-2026", "5790"],
    ["total_debt", "H1-2026", "5790"],
    ["total_debt", "LTM-Q2-2026", "5790"],
    ["cash_and_equivalents", "FY2025", "2410"],
    ["cash_and_equivalents", "Q2-2025", "1900"],
    ["cash_and_equivalents", "Q2-2026", "2630"],
  ]);
  const [earnings, balances, ...rest] = accountLines(tables);
  // No revolver row: no revolver figure.
  expect(rest).toEqual([]);
  // A year, a half-year and a twelve-month period beside the quarters would
  // draw falls that are only their lengths; the quarters are the most.
  expect(earnings!.key).toBe("earnings");
  expect(earnings!.categories).toEqual(["Q2-2025", "Q3-2025", "Q4-2025", "Q1-2026", "Q2-2026"]);
  expect(earnings!.series.map((series) => series.key)).toEqual(["ebitda", "adjusted_ebitda"]);
  expect(earnings!.series.every((series) => series.origin === "model")).toBe(true);
  expect(earnings!.series[1]!.data[3]).toEqual({ value: null, reason: "NOT_AVAILABLE" });
  expect(earnings!.unit).toBe("USD m");
  expect(earnings!.summary).toBe(
    "Q2-2026: EBITDA 758 USD m; Adjusted EBITDA 769 USD m, over 5 quarters.",
  );
  expect(
    earnings!.sourceOf({
      series: "ebitda",
      category: "Q2-2026",
      index: 4,
      value: "758",
      origin: "model",
    }),
  ).toBe("S1, p.Q2-2026");
  // Three periods ending 2026-06-30 state one balance once, and the register
  // listing FY2025 first does not put December before June.
  expect(balances!.key).toBe("debt-cash");
  expect(balances!.categories).toEqual(["Q2-2025", "FY2025", "Q2-2026"]);
  expect(balances!.series[0]!.data).toEqual([
    { value: null, reason: "not stated" },
    { value: "5600" },
    { value: "5790" },
  ]);
  expect(balances!.summary).toBe(
    "Q2-2026: Total debt 5,790 USD m; Cash and equivalents 2,630 USD m, over 3 period ends.",
  );
  // A register with none of these accounts draws none of them.
  expect(accountLines(accountRegister([["revenue", "Q2-2026", "7394"]]))).toEqual([]);
});

test("cashFlowBridge: the latest period with both ends, bridged as CP-MODEL bridges it", () => {
  const tables = accountRegister([
    ["cfo_ncfo", "FY2025", "1300"],
    ["net_cash_change", "FY2025", "220"],
    // The latest period by date, but with no stated change in cash.
    ["cfo_ncfo", "LTM-Q2-2026", "1500"],
    ["cfo_ncfo", "Q2-2026", "412"],
    ["capex_and_intangible_investment", "Q2-2026", "-180"],
    ["acquisitions_disposals", "Q2-2026", "null", "NOT_DISCLOSED"],
    ["net_debt_issue_repay", "Q2-2026", "-95"],
    ["other_investing_financing", "Q2-2026", "-12"],
    ["net_cash_change", "Q2-2026", "100"],
  ]);
  const figure = cashFlowBridge(tables)!;
  expect(figure.kind).toBe("waterfall");
  expect(figure.title).toBe("Cash flow, Q2-2026");
  // No dividend or equity row: left out, not drawn as a zero.
  expect(figure.steps!.map((step) => [step.label, step.kind])).toEqual([
    ["Operating cash flow", "total"],
    ["Capex and intangibles", "delta"],
    ["Acquisitions and disposals", "delta"],
    ["Debt issued less repaid", "delta"],
    ["Other investing and financing", "delta"],
    ["Net change in cash", "total"],
  ]);
  expect(figure.steps![2]).toMatchObject({ value: null, reason: "NOT_DISCLOSED" });
  expect(figure.summary).toBe(
    "Operating cash flow 412 USD m to a net change in cash of +100 USD m.",
  );
  // The undisclosed acquisitions leave 412 - 180 - 95 - 12 = 125 against a
  // stated 100: the chart says the 25 it cannot place, never bends a bar.
  const residual = bridgeOf(figure.steps!).find((step) => step.kind === "residual")!;
  expect(residual).toMatchObject({ value: "-25", before: "Net change in cash" });
  expect(
    figure.sourceOf({
      series: "net_debt_issue_repay",
      category: "Debt issued less repaid",
      index: 3,
      value: "-95",
      origin: "model",
    }),
  ).toBe("S1, p.Q2-2026");
  // No period states both ends: no bridge.
  expect(cashFlowBridge(accountRegister([["cfo_ncfo", "Q2-2026", "412"]]))).toBeNull();
});

test("the account figures read in place, and a residual is said as computed, not served", () => {
  const register = accountRegister([
    ["ebitda", "Q1-2026", "690"],
    ["ebitda", "Q2-2026", "758"],
    ["total_debt", "Q2-2026", "5790"],
    ["cfo_ncfo", "Q2-2026", "412"],
    ["capex_and_intangible_investment", "Q2-2026", "-180"],
    ["net_cash_change", "Q2-2026", "200"],
  ])[1]!;
  const handoff = { ...cp1, tables: [...cp1.tables, register] };
  // Earnings beside the add-backs that bridge them; balances before maturities.
  expect(figuresOf(handoff).map((figure) => figure.key)).toEqual([
    "segment-mix",
    ...kpiLines(cp1.tables).map((figure) => figure.key),
    "earnings",
    "addbacks",
    "cash-flow",
    "debt-cash",
    "maturities",
  ]);
  const { container } = render(
    <MemoryRouter>
      <AnalysisSection
        document={{ ...document, body: { ...document.body, handoffs: [handoff] } }}
        tab={handoff.route_node_id}
      />
    </MemoryRouter>,
  );
  const bridge = container.querySelector("[data-figure='cash-flow']") as HTMLElement;
  fireEvent.click(within(bridge).getByRole("button", { name: /^Unreconciled before/ }));
  const picked = container.querySelector("[data-figures] ~ [data-picked]")!;
  expect(picked).toHaveTextContent("Cash flow, Q2-2026");
  expect(picked).toHaveTextContent("Computed here: the stated total less the running level");
  expect(picked).not.toHaveTextContent("Model-authored");
  fireEvent.click(within(bridge).getByRole("button", { name: /^Operating cash flow/ }));
  expect(container.querySelector("[data-picked]")).toHaveTextContent(
    "Model-authored, not host-verified",
  );
});

// Registers (N94), with made-up values only (N191): CP-4's covenant headroom
// and CP-1C's peer statistics, each under its profile's own columns.
type Register = HandoffView["registers"][number];
const served = (text: string, value: string | null = null) => ({ text, value });
const COVENANT = [
  "Test",
  "Test Type",
  "Threshold",
  "Current Basis",
  "Formula",
  "Headroom",
  "Status",
  "Limitation",
  "Risk Mechanic",
  "Credit Implication",
  "Evidence ID",
];
const headroom: Register = {
  register_id: "T4C.4",
  columns: COVENANT,
  declared: COVENANT,
  rows: [
    [
      served("Senior leverage"),
      served("Maintenance"),
      served("4.50x", "4.50"),
      served("3.25x", "3.25"),
      served("Net debt / EBITDA"),
      served("1.25x", "1.25"),
      served("Compliant"),
      served(""),
      served(""),
      served(""),
      served("E-1"),
    ],
  ],
};
const PEERS = ["Metric", "Borrower Value", "Peer Avg", "Median", "Min", "Max", "Q1", "Q3", "N"];
const peers: Register = {
  register_id: "T4.6",
  columns: PEERS,
  declared: PEERS,
  rows: [
    [
      served("EV / EBITDA"),
      served("9.1x", "9.1"),
      served("7.4x", "7.4"),
      served("7.5x", "7.5"),
      served("5.0x", "5.0"),
      served("11.0x", "11.0"),
      served("6.25x", "6.25"),
      served("8.75x", "8.75"),
      served("12", "12"),
    ],
  ],
};

function shown(handoff: HandoffView) {
  return render(
    <MemoryRouter>
      <AnalysisSection
        document={{ ...document, body: { ...document.body, handoffs: [handoff] } }}
        tab={handoff.route_node_id}
      />
    </MemoryRouter>,
  ).container;
}

test("register figures follow the table figures, and each refusal withholds only its own", () => {
  // CP-1's tables under CP-4's module: a table figure and a register figure.
  const both = { ...handoffOf("CP-4"), tables: cp1.tables, registers: [headroom] };
  const tableKeys = figuresOf(cp1).map((figure) => figure.key);
  expect(figuresOf(both).map((figure) => figure.key)).toEqual([
    ...tableKeys,
    "covenant-headroom-x",
  ]);
  const noTables = { ...both, tables_unavailable_reason: "TABLES_MALFORMED" as const };
  const noRegisters = { ...both, registers_unavailable_reason: "TABLES_TOO_LARGE" as const };
  expect(figuresOf(noTables).map((figure) => figure.key)).toEqual(["covenant-headroom-x"]);
  expect(figuresOf(noRegisters).map((figure) => figure.key)).toEqual(tableKeys);
  // The note names each refusal; the figures the other source supports draw.
  const tablesRefused = shown(noTables);
  expect(
    tablesRefused.querySelector("[data-tables-unavailable='TABLES_MALFORMED']"),
  ).not.toBeNull();
  expect(tablesRefused.querySelector("[data-registers-unavailable]")).toBeNull();
  expect(tablesRefused.querySelector("[data-figure='covenant-headroom-x']")).not.toBeNull();
  expect(tablesRefused.querySelector("[data-figure='segment-mix']")).toBeNull();
  const registersRefused = shown(noRegisters);
  expect(
    registersRefused.querySelector("[data-registers-unavailable='TABLES_TOO_LARGE']"),
  ).toHaveTextContent("registers could not be read (TABLES_TOO_LARGE)");
  expect(registersRefused.querySelector("[data-figure='covenant-headroom-x']")).toBeNull();
  expect(registersRefused.querySelector("[data-figure='segment-mix']")).not.toBeNull();
  const neither = shown({ ...noTables, registers_unavailable_reason: "TABLES_MALFORMED" });
  const note = neither.querySelector(
    "[data-tables-unavailable='TABLES_MALFORMED'][data-registers-unavailable='TABLES_MALFORMED']",
  );
  expect(note).toHaveTextContent(
    "This module's tables (TABLES_MALFORMED) and registers (TABLES_MALFORMED) could not be read",
  );
  expect(neither.querySelector("[data-figures]")).toBeNull();
});

test("pressing an interquartile bar names both ends, Q1 to Q3, never n/a", () => {
  const container = shown({ ...handoffOf("CP-1C"), registers: [peers] });
  const figure = container.querySelector("[data-figure='peer-ranges-x']") as HTMLElement;
  fireEvent.click(
    within(figure).getByRole("button", { name: /interquartile range 6\.25 x to 8\.75 x/ }),
  );
  const picked = container.querySelector("[data-figures] ~ [data-picked]")!;
  expect(picked.querySelector("[data-picked-value]")!.textContent).toBe("6.25 x to 8.75 x");
  expect(picked).toHaveTextContent("Interquartile range · EV / EBITDA");
  expect(picked).toHaveTextContent("Peer ranges, x");
  expect(picked).toHaveTextContent("T4.6");
  expect(picked).toHaveTextContent("Peer Avg: 7.4x; N: 12");
  // The borrower's dot is one value, named as the figure names it.
  fireEvent.click(within(figure).getByRole("button", { name: /Borrower value 9\.1 x/ }));
  expect(container.querySelector("[data-picked-value]")!.textContent).toBe("9.1 x");
  expect(container.querySelector("[data-picked]")).toHaveTextContent(
    "Borrower value · EV / EBITDA",
  );
});

test("pressing a covenant's bar names its current basis and stated source", () => {
  const container = shown({ ...handoffOf("CP-4"), registers: [headroom] });
  const figure = container.querySelector("[data-figure='covenant-headroom-x']") as HTMLElement;
  fireEvent.click(within(figure).getByRole("button", { name: /current basis 3\.25 x/ }));
  const picked = container.querySelector("[data-picked]")!;
  expect(picked.querySelector("[data-picked-value]")!.textContent).toBe("3.25 x");
  expect(picked).toHaveTextContent("Current basis · Senior leverage");
  expect(picked).toHaveTextContent(
    "Formula: Net debt / EBITDA; Status: Compliant; Evidence ID: E-1",
  );
});

test("the figures' key keys a rule and a dot only where one is drawn", () => {
  const key = (container: HTMLElement) =>
    container.querySelector("[data-figures-key]")!.textContent ?? "";
  const bullets = key(shown({ ...handoffOf("CP-4"), registers: [headroom] }));
  expect(bullets).toContain("Outlined: model-authored, not host-verified");
  expect(bullets).toContain("Dashed rule: model-authored, not host-verified");
  expect(bullets).not.toContain("Hollow dot");
  const ranges = key(shown({ ...handoffOf("CP-1C"), registers: [peers] }));
  expect(ranges).toContain("Dashed rule: model-authored, not host-verified");
  expect(ranges).toContain("Hollow dot: model-authored, not host-verified");
  expect(key(shown(cp1))).not.toContain("rule");
});

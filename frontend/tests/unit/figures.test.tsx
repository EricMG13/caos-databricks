// A module's figures come from the tables the server served, exactly: the
// right chart per table, periods in the register's order, exact sums, and a
// pressed mark named in the right column (plan step 5).
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { fireEvent, render, within } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { AnalysisSection } from "@/sections/analysis/AnalysisSection";
import {
  addbacks,
  figuresOf,
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
  expect(figuresOf(cp1).map((figure) => figure.key)[0]).toBe("segment-mix");
  // A module with no tables draws nothing.
  expect(figuresOf({ ...cp1, tables: [] })).toEqual([]);
});

test("pressing a mark names it in the right column, with its stated source", () => {
  const { container } = render(
    <MemoryRouter>
      <AnalysisSection document={document} tab={cp1.route_node_id} />
    </MemoryRouter>,
  );
  const figure = container.querySelector("[data-figure='segment-mix']")!;
  const mark = within(figure as HTMLElement).getAllByRole("button", { name: /Q2-2026/ })[0]!;
  fireEvent.click(mark);
  const picked = container.querySelector(".pane.context [data-picked]")!;
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

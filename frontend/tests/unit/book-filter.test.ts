// The Book's pure filtering and sorting (spec B12-B15).
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { applyView, cellOf } from "@/sections/book/filter";
import { DEFAULT_VIEW, type BookView } from "@/sections/book/view";
import { parseBookDocument, type BookEntryView, type BookIssuerView } from "@/wire/v1";

const FIXTURE = resolve(process.cwd(), "fixtures", "book.json");
const base = parseBookDocument(JSON.parse(readFileSync(FIXTURE, "utf8")));
const template = base.body.issuers[0]!;
const CATALOGUE = [
  { line_id: "revenue", label: "Total revenue", unit: "MONEY" as const },
  { line_id: "metric:net_leverage_adjusted", label: "Net leverage", unit: "MULTIPLE" as const },
];

function issuer(
  key: string,
  patch: Partial<BookEntryView> = {},
  ltm: Record<string, string | null> = {},
): BookIssuerView {
  const displayed: BookEntryView = {
    ...template.displayed,
    issuer_key: key,
    issuer_name: key,
    currency: "USD",
    ...patch,
    metrics: { LTM: ltm },
    fiscal_years: {},
  };
  return { issuer_key: key, displayed, history: [] };
}

const view = (patch: Partial<BookView>): BookView => ({
  ...DEFAULT_VIEW,
  columns: [],
  ...patch,
});
const keys = (rows: BookIssuerView[]) => rows.map((row) => row.issuer_key);
const run = (rows: BookIssuerView[], patch: Partial<BookView>) =>
  keys(applyView(rows, view(patch), CATALOGUE));

describe("book filter and sort", () => {
  it("range filters compare decimals exactly", () => {
    const rows = [
      issuer("A", {}, { metric_x: "0.1000000000000000001" }),
      issuer("B", {}, { metric_x: "0.1" }),
      issuer("C", {}, { metric_x: null }),
      issuer("D", {}, { metric_x: "-2.50" }),
    ];
    const col = "m:metric_x" as const;
    expect(run(rows, { filters: [{ kind: "range", column: col, min: "0.1", max: null }] })).toEqual(
      ["A", "B"],
    );
    expect(run(rows, { filters: [{ kind: "range", column: col, min: null, max: "0.1" }] })).toEqual(
      ["B", "D"],
    );
    expect(
      run(rows, { filters: [{ kind: "range", column: col, min: "-2.5", max: "-2.50" }] }),
    ).toEqual(["D"]);
  });

  it("money filters need a currency", () => {
    const rows = [
      issuer("A", { currency: "USD" }, { revenue: "10" }),
      issuer("B", { currency: "EUR" }, { revenue: "500" }),
      issuer("C", { currency: "USD" }, { revenue: "900" }),
    ];
    const filters: BookView["filters"] = [
      { kind: "range", column: "m:revenue", min: "5", max: "100" },
    ];
    expect(run(rows, { filters })).toEqual(["A", "B", "C"]);
    expect(run(rows, { filters, currency: "USD" })).toEqual(["A"]);
    expect(run(rows, { filters, currency: "EUR" })).toEqual([]);
    const sort = { column: "m:revenue", dir: "desc" } as const;
    expect(run(rows, { sort })).toEqual(["A", "B", "C"]);
    expect(run(rows, { sort, currency: "USD" })).toEqual(["C", "A", "B"]);
  });

  it("notch filter keeps ratings between best and worst inclusive", () => {
    const rows = [
      issuer("A", { moodys: "A3" }),
      issuer("B", { moodys: "Baa2" }),
      issuer("C", { moodys: "Ba1" }),
      issuer("D", { moodys: null }),
      issuer("E", { moodys: "Baa1" }),
    ];
    const filters: BookView["filters"] = [
      { kind: "notch", agency: "moodys", best: "Baa1", worst: "Baa2" },
    ];
    expect(run(rows, { filters })).toEqual(["B", "E"]);
    const sp = [issuer("S", { sp: "BBB-" }), issuer("T", { sp: "BB+" })];
    expect(
      run(sp, { filters: [{ kind: "notch", agency: "sp", best: "AAA", worst: "BBB-" }] }),
    ).toEqual(["S"]);
  });

  it("sorts nulls last in both directions", () => {
    const rows = [
      issuer("A", {}, { metric_x: "2" }),
      issuer("B", {}, { metric_x: null }),
      issuer("C", {}, { metric_x: "10" }),
      issuer("D", {}, { metric_x: "-1.5" }),
    ];
    const column = "m:metric_x" as const;
    expect(run(rows, { sort: { column, dir: "asc" } })).toEqual(["D", "A", "C", "B"]);
    expect(run(rows, { sort: { column, dir: "desc" } })).toEqual(["C", "A", "D", "B"]);
  });

  it("composite sorts by notch not by label", () => {
    const rows = [
      issuer("A", { composite: "BB+", composite_notch: 11 }),
      issuer("B", { composite: "AA", composite_notch: 3 }),
      issuer("C", { composite: "BBB", composite_notch: 9 }),
      issuer("D", { composite: "NR", composite_notch: null }),
    ];
    const column = "id:composite" as const;
    expect(run(rows, { sort: { column, dir: "asc" } })).toEqual(["B", "C", "A", "D"]);
    expect(run(rows, { sort: { column, dir: "desc" } })).toEqual(["A", "C", "B", "D"]);
  });

  it("ties keep the document order and agency columns sort by scale index", () => {
    const rows = [
      issuer("A", { moodys: "Ba1" }),
      issuer("B", { moodys: "Aa1" }),
      issuer("C", { moodys: "Ba1" }),
    ];
    const column = "id:moodys" as const;
    expect(run(rows, { sort: { column, dir: "asc" } })).toEqual(["B", "A", "C"]);
    expect(run(rows, { sort: { column, dir: "desc" } })).toEqual(["A", "C", "B"]);
  });

  it("MONEY stays inert without a currency when the catalogue is passed", () => {
    const rows = [
      issuer("A", { currency: "USD" }, { revenue: "10" }),
      issuer("B", { currency: "EUR" }, { revenue: "500" }),
    ];
    const filters: BookView["filters"] = [
      { kind: "range", column: "m:revenue", min: "5", max: "100" },
    ];
    const out = applyView(rows, view({ filters, currency: null }), CATALOGUE);
    expect(keys(out)).toEqual(["A", "B"]);
  });

  it("a notch filter works for Fitch and excludes an off-scale label", () => {
    const rows = [
      issuer("A", { fitch: "BBB" }),
      issuer("B", { fitch: "BB" }),
      issuer("C", { moodys: "WR", fitch: null }),
    ];
    expect(
      run(rows, { filters: [{ kind: "notch", agency: "fitch", best: "A", worst: "BBB" }] }),
    ).toEqual(["A"]);
    expect(
      run(rows.slice(2), {
        filters: [{ kind: "notch", agency: "moodys", best: "Aaa", worst: "C" }],
      }),
    ).toEqual([]);
  });

  it("a set filter on a MONEY column matches the figure text in any currency", () => {
    const rows = [
      issuer("A", { currency: "USD" }, { revenue: "10" }),
      issuer("B", { currency: "EUR" }, { revenue: "10" }),
      issuer("C", { currency: "USD" }, { revenue: "11" }),
    ];
    expect(run(rows, { filters: [{ kind: "set", column: "m:revenue", values: ["10"] }] })).toEqual([
      "A",
      "B",
    ]);
  });

  it("fails closed, without throwing, on text that is not a decimal", () => {
    const rows = [
      issuer("A", {}, { metric_x: "5" }),
      issuer("B", { issuer_name: "Acme" }, { metric_x: "abc" }),
    ];
    const text: BookView["filters"] = [
      { kind: "range", column: "id:issuer_name", min: "1", max: null },
    ];
    expect(run(rows, { filters: text })).toEqual([]);
    const figure: BookView["filters"] = [
      { kind: "range", column: "m:metric_x", min: "1", max: null },
    ];
    expect(run(rows, { filters: figure })).toEqual(["A"]);
  });

  it("set filters match exactly", () => {
    const rows = [issuer("A", { sector: "Gaming" }), issuer("B", { sector: "gaming" })];
    const filters: BookView["filters"] = [
      { kind: "set", column: "id:sector", values: ["Gaming", "Telecom"] },
    ];
    expect(run(rows, { filters })).toEqual(["A"]);
  });

  it("cellOf reads identifier fields and metrics by basis, and stored line ids as served", () => {
    const entry = issuer("A", { moodys: null, filed: true }, { revenue: "7", "metric:x": "1.5" });
    entry.displayed.metrics.BASE_FY1 = { "metric:x": "2.5" };
    expect(cellOf(entry, "id:issuer_name", "LTM")).toBe("A");
    expect(cellOf(entry, "id:moodys", "LTM")).toBeNull();
    expect(cellOf(entry, "id:filed", "LTM")).toBe("true");
    expect(cellOf(entry, "m:revenue", "LTM")).toBe("7");
    expect(cellOf(entry, "m:metric:x", "LTM")).toBe("1.5");
    expect(cellOf(entry, "m:metric:x", "BASE_FY1")).toBe("2.5");
    expect(cellOf(entry, "m:metric:x@BASE_FY1", "LTM")).toBe("2.5");
    expect(cellOf(entry, "m:metric:x@DOWNSIDE_FY1", "LTM")).toBeNull();
    expect(cellOf(entry, "m:absent", "LTM")).toBeNull();
  });
});

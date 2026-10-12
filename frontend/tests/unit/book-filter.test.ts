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

describe("book filter and sort", () => {
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

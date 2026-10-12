import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { render, screen, within } from "@testing-library/react";
import { BookSection } from "@/sections/book/BookSection";
import {
  BASES,
  BASIS_LABELS,
  IDENTIFIERS,
  IDENTIFIER_LABELS,
  agencyOf,
  columnLabel,
  unitLookup,
  unitOf,
} from "@/sections/book/columns";
import { metricOf } from "@/sections/book/filter";
import { analyticalIdentity, tailed } from "@/app/authority";
import { WireShapeError, parseBookDocument, type BookDocument } from "@/wire/v1";

const FIXTURE = resolve(process.cwd(), "fixtures", "book.json");

function raw() {
  return JSON.parse(readFileSync(FIXTURE, "utf8"));
}

function document(): BookDocument {
  return parseBookDocument(raw());
}

describe("the book", () => {
  test("the column vocabulary names every column once", () => {
    const units = document().body.metric_catalogue;
    expect(IDENTIFIERS).toHaveLength(Object.keys(IDENTIFIER_LABELS).length);
    expect(BASES.map((basis) => BASIS_LABELS[basis])).toEqual([
      "LTM",
      "PF LTM",
      "Base FY1",
      "Downside FY1",
    ]);
    expect(columnLabel("id:moodys", units)).toBe("Moody's");
    expect(columnLabel("m:revenue", units)).toBe("Total revenue");
    expect(columnLabel("m:revenue@BASE_FY1", units)).toBe("Total revenue · Base FY1");
    expect(unitOf("m:revenue", units)?.unit).toBe("MONEY");
    expect(unitOf("id:sector", units)).toBeUndefined();
    expect(unitLookup(units)("m:revenue@PF_LTM")?.label).toBe("Total revenue");
    expect(unitLookup(units)("id:unit")).toBeUndefined();
    expect(columnLabel("id:unit", units)).toBe("Unit");
    expect(columnLabel("id:fiscal_year_base_fy1", units)).toBe("Fiscal year · Base FY1");
    expect(agencyOf("id:sp")).toBe("sp");
    expect(agencyOf("id:sp_outlook")).toBeNull();
    expect(metricOf("m:revenue@PF_LTM", "LTM")).toEqual({ lineId: "revenue", basis: "PF_LTM" });
  });

  test("the served fixture is the declared v2 shape: issuers and the metric catalogue", () => {
    const doc = document();
    expect(doc.body.issuers.map((issuer) => issuer.issuer_key)).toEqual([
      "CVNA",
      "CZR",
      "VMO2",
      "NGE",
      "RCH",
      "PFL",
      "ALH",
      "MRG",
      "SLU",
    ]);
    expect(doc.body.metric_catalogue[0]).toEqual({
      line_id: "revenue",
      label: "Total revenue",
      unit: "MONEY",
    });
    // A projected basis names its fiscal year apart from the figures.
    const cvna = doc.body.issuers[0]!.displayed;
    expect(cvna.fiscal_years).toEqual({ BASE_FY1: "2026", DOWNSIDE_FY1: "2026" });
    expect(Object.keys(cvna.metrics)).toEqual(["LTM", "BASE_FY1", "PF_LTM", "DOWNSIDE_FY1"]);
  });

  test("a metrics leaf is decimal text or null, never a number", () => {
    const fixture = raw();
    fixture.body.issuers[0].displayed.metrics.LTM.revenue = 20322;
    expect(() => parseBookDocument(fixture)).toThrow(WireShapeError);
  });

  test("each issuer is one row: its displayed entry's name, period, sector and composite", () => {
    const doc = document();
    render(<BookSection document={doc} tab={null} />);
    const table = screen.getByRole("table", { name: "Issuers in the Book" });
    const rows = within(table).getAllByRole("row").slice(1);
    expect(rows).toHaveLength(doc.body.issuers.length);
    for (const { issuer_key: key, displayed } of doc.body.issuers) {
      const row = table.querySelector(`[data-issuer="${key}"]`)!;
      expect(row).toHaveAttribute("data-entry", displayed.entry_id);
      for (const cell of [
        displayed.issuer_name,
        displayed.reporting_period,
        displayed.sector,
        displayed.composite,
      ]) {
        expect(row).toHaveTextContent(cell);
      }
    }
    // VMO2's withdrawn entry is history, never the row.
    const vmo2 = doc.body.issuers[2]!;
    expect(vmo2.history[0]!.withdrawal_reason).toBe("DATA_ERROR");
    expect(table.querySelector(`[data-entry="${vmo2.history[0]!.entry_id}"]`)).toBeNull();
  });

  test("LTM revenue is served decimal text, spelled with its currency and unit", () => {
    render(<BookSection document={document()} tab={null} />);
    const table = screen.getByRole("table", { name: "Issuers in the Book" });
    expect(within(table).getByRole("columnheader", { name: "Total revenue · LTM" })).toBeVisible();
    const row = table.querySelector('[data-issuer="CVNA"]')!;
    const cells = within(row as HTMLElement).getAllByRole("cell");
    expect(cells[3]).toHaveTextContent("USD");
    expect(cells[4]).toHaveTextContent("MILLIONS");
    expect(cells[5]).toHaveTextContent("20,322");
    expect(within(cells[5]!).getByTitle("20322")).toBeVisible();
    expect(cells[5]).not.toHaveAttribute("aria-description");
  });

  test.each([null, "0"])("LTM revenue %s preserves missing values and zero", (value) => {
    const fixture = raw();
    fixture.body.issuers[0].displayed.metrics.LTM.revenue = value;
    render(<BookSection document={parseBookDocument(fixture)} tab={null} />);
    const row = screen.getByRole("table").querySelector('[data-issuer="CVNA"]')!;
    const cell = within(row as HTMLElement).getAllByRole("cell")[5]!;
    if (value === null) {
      expect(cell).toHaveTextContent("Not stated");
      expect(cell).not.toHaveTextContent("0");
    } else {
      expect(cell).toHaveTextContent("0");
      expect(cell).not.toHaveTextContent("Not stated");
      expect(within(cell).getByTitle("0")).toBeVisible();
    }
  });

  test("a moved displayed entry is a new analytical identity", () => {
    const doc = document();
    const moved: BookDocument = {
      ...doc,
      body: {
        ...doc.body,
        issuers: doc.body.issuers.map((issuer, index) =>
          index === 0
            ? { ...issuer, displayed: { ...issuer.displayed, snapshot_sha256: "f".repeat(64) } }
            : issuer,
        ),
      },
    };
    expect(analyticalIdentity("book", moved)).not.toBe(analyticalIdentity("book", doc));
    expect(analyticalIdentity("book", document())).toBe(analyticalIdentity("book", doc));
  });

  test("no case event names the book, so it holds no stream", () => {
    // `tailed` is what `Workspace` asks before opening a per-case SSE tail. A
    // tail over Book could never usefully fire -- `REFETCHES` maps no event to
    // it -- and would hold a worker thread and one of the API's 32
    // concurrency slots for its whole deadline.
    expect(tailed("book")).toBe(false);
    expect(tailed("directory")).toBe(false);
    expect(tailed("analysis")).toBe(true);
    expect(tailed("committee")).toBe(true);
  });
});

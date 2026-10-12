import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { render, screen, within } from "@testing-library/react";
import { BookSection } from "@/sections/book/BookSection";
import { analyticalIdentity } from "@/app/authority";
import { WireShapeError, parseBookDocument, type BookDocument } from "@/wire/v1";

const FIXTURE = resolve(process.cwd(), "fixtures", "book.json");

function raw() {
  return JSON.parse(readFileSync(FIXTURE, "utf8"));
}

function document(): BookDocument {
  return parseBookDocument(raw());
}

describe("the book", () => {
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
});

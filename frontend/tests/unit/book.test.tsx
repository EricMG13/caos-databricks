import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { vi } from "vitest";
import type * as Grid from "@/sections/model/grid";
import { MemoryRouter, useLocation } from "react-router";
import { analyticalIdentity, tailed } from "@/app/authority";
import { displayDecimal } from "@/ds/format";
import { BookSection } from "@/sections/book/BookSection";
import { spelled } from "@/sections/model/grid";
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
import { DEFAULT_VIEW, LOCKED } from "@/sections/book/view";
import { WireShapeError, parseBookDocument, type BookDocument } from "@/wire/v1";

// Global setup preloads every section; reload this one under the real spelling spy.
vi.hoisted(() => {
  vi.resetModules();
});

vi.mock("@/sections/model/grid", async (original) => {
  const actual = await original<typeof Grid>();
  return { ...actual, spelled: vi.fn(actual.spelled) };
});

const FIXTURE = resolve(process.cwd(), "fixtures", "book.json");
const EMPTY = resolve(process.cwd(), "fixtures", "states", "book.observed-empty.json");

function raw() {
  return JSON.parse(readFileSync(FIXTURE, "utf8"));
}

function document(): BookDocument {
  return parseBookDocument(raw());
}

function Probe() {
  return <output data-search>{useLocation().search}</output>;
}

function renderBook(doc: BookDocument = document(), url = "/book/") {
  return render(
    <MemoryRouter initialEntries={[url]}>
      <BookSection document={doc} tab={null} />
      <Probe />
    </MemoryRouter>,
  );
}

function search(): URLSearchParams {
  return new URLSearchParams(document_().querySelector("[data-search]")!.textContent ?? "");
}

function document_(): HTMLElement {
  return globalThis.document.body;
}

function rows(): HTMLElement[] {
  const table = screen.getByRole("table", { name: "Issuers in the Book" });
  return within(table).getAllByRole("row").slice(1);
}

function cell(issuer: string, column: string): HTMLElement {
  return document_().querySelector<HTMLElement>(
    `tr[data-issuer="${issuer}"] [data-column="${column}"]`,
  )!;
}

beforeEach(() => {
  window.localStorage.clear();
});

beforeEach(() => {
  vi.clearAllMocks();
});

afterEach(() => {
  vi.restoreAllMocks();
});

/** Open the column chooser and scope every query to it. */
function chooser() {
  fireEvent.click(screen.getByRole("button", { name: "Columns" }));
  return within(document_().querySelector<HTMLElement>("[data-column-chooser]")!);
}

/** What the table should show for a figure, from the fixture alone. */
function figure(issuer: string, column: string, basis: string): string | null {
  const doc = document();
  const entry = doc.body.issuers.find((row) => row.issuer_key === issuer)!.displayed;
  const at = column.lastIndexOf("@");
  const lineId = at < 0 ? column.slice(2) : column.slice(2, at);
  const value = entry.metrics[at < 0 ? basis : column.slice(at + 1)]?.[lineId] ?? null;
  const unit = doc.body.metric_catalogue.find((u) => u.line_id === lineId)!.unit;
  return value === null ? null : spelled({ unit, unit_label: null }, value);
}

describe("the book", () => {
  test("shows one row per issuer with the default columns", () => {
    const doc = document();
    renderBook(doc);
    expect(rows()).toHaveLength(doc.body.issuers.length);
    const table = screen.getByRole("table", { name: "Issuers in the Book" });
    const headers = within(table).getAllByRole("columnheader");
    expect(headers).toHaveLength(DEFAULT_VIEW.columns.length);
    for (const { issuer_key: key, displayed } of doc.body.issuers) {
      const row = table.querySelector(`[data-issuer="${key}"]`)!;
      expect(row).toHaveAttribute("data-entry", displayed.entry_id);
      for (const text of [displayed.issuer_name, displayed.reporting_period, displayed.sector]) {
        expect(row).toHaveTextContent(text);
      }
    }
    // One value per cell: each agency's rating and its outlook are two columns.
    expect(cell("VMO2", "id:moodys")).toHaveTextContent(/^B1$/);
    expect(cell("VMO2", "id:moodys_outlook")).toHaveTextContent(/^STABLE$/);
    // A money figure reads as the Model grid reads it, and nothing else is in its cell:
    // the currency and the unit are columns of their own.
    const revenue = doc.body.issuers[2]!.displayed.metrics.LTM!.revenue!;
    expect(cell("VMO2", "m:revenue").textContent).toBe(displayDecimal(revenue, 0));
    expect(cell("VMO2", "id:currency")).toHaveTextContent(/^GBP$/);
    expect(cell("VMO2", "id:unit")).toHaveTextContent(/^MILLIONS$/);
    expect(DEFAULT_VIEW.columns.slice(0, 4)).toEqual([
      "id:issuer_name",
      "id:reporting_period",
      "id:currency",
      "id:unit",
    ]);
    expect(cell("VMO2", "m:metric:net_leverage_adjusted")).toHaveTextContent("5.5x");
    expect(spelled({ unit: "MULTIPLE", unit_label: null }, "5.45")).toBe("5.5x");
    // The footer counts the issuers kept.
    expect(screen.getByText("9 of 9 issuers")).toBeInTheDocument();
    // VMO2's withdrawn entry is history, never the row.
    const vmo2 = doc.body.issuers[2]!;
    expect(table.querySelector(`[data-entry="${vmo2.history[0]!.entry_id}"]`)).toBeNull();
    // Badges
    expect(within(table.querySelector('[data-issuer="CVNA"]')!).getByText("Filed")).toBeVisible();
    expect(
      within(table.querySelector('[data-issuer="CZR"]')!).getByText("Sources withdrawn"),
    ).toBeVisible();
  });

  test("the basis switch changes every metric column", () => {
    renderBook();
    const followers = DEFAULT_VIEW.columns.filter((c) => c.startsWith("m:") && !c.includes("@"));
    expect(followers.length).toBeGreaterThan(8);
    const pinnedColumn = "m:metric:net_leverage_adjusted@BASE_FY1";
    const pinnedShown = figure("CVNA", pinnedColumn, "LTM")!;
    expect(cell("CVNA", pinnedColumn).textContent).toBe(pinnedShown);
    expect(search().get("basis")).toBeNull();
    for (const [radio, basis] of [
      ["Base FY1", "BASE_FY1"],
      ["PF LTM", "PF_LTM"],
      ["Downside FY1", "DOWNSIDE_FY1"],
      ["LTM", "LTM"],
    ] as const) {
      fireEvent.click(screen.getByRole("radio", { name: radio }));
      expect(search().get("basis")).toBe(basis);
      for (const column of followers) {
        const expected = figure("CVNA", column, basis);
        const text = cell("CVNA", column).textContent;
        if (expected === null) expect(text).not.toMatch(/\d/);
        else expect(text).toBe(expected);
      }
      // A column pinned to a basis does not follow the switch.
      expect(cell("CVNA", pinnedColumn).textContent).toBe(pinnedShown);
    }
    // The figures really differ between bases, so the loop above could fail.
    expect(figure("CVNA", "m:revenue", "PF_LTM")).not.toBe(figure("CVNA", "m:revenue", "LTM"));
    // A projected basis names its fiscal year as the cell's description, not in its text.
    fireEvent.click(screen.getByRole("radio", { name: "Base FY1" }));
    expect(cell("CVNA", "m:revenue")).toHaveAttribute("aria-description", "FY2026");
    expect(cell("CVNA", "m:revenue").textContent).not.toContain("FY");
    fireEvent.click(screen.getByRole("radio", { name: "PF LTM" }));
    expect(cell("CVNA", "m:revenue")).not.toHaveAttribute("aria-description");
    // A basis with no figure shows no number.
    expect(cell("CZR", "m:revenue")).not.toHaveTextContent(/\d/);
  });

  test("a fiscal year is a column of its own, offered per projected basis", () => {
    renderBook();
    const box = chooser();
    expect(DEFAULT_VIEW.columns.some((c) => c.startsWith("id:fiscal_year"))).toBe(false);
    fireEvent.click(box.getByLabelText("Fiscal year · Base FY1"));
    expect(search().getAll("col")).toContain("id:fiscal_year_base_fy1");
    expect(cell("CVNA", "id:fiscal_year_base_fy1")).toHaveTextContent(/^2026$/);
    expect(box.getByLabelText("Fiscal year · Downside FY1")).toBeInTheDocument();
    expect(box.getByLabelText("Unit")).toBeChecked();
  });

  test("adding and removing a column updates the URL", () => {
    renderBook();
    const box = chooser();
    expect(box.getByLabelText("Domicile")).not.toBeChecked();
    fireEvent.click(box.getByLabelText("Domicile"));
    expect(search().getAll("col")).toContain("id:domicile");
    expect(cell("VMO2", "id:domicile")).toHaveTextContent("GB");
    fireEvent.click(box.getByLabelText("Domicile"));
    expect(search().getAll("col")).not.toContain("id:domicile");
    expect(cell("VMO2", "id:domicile")).toBeNull();
    // A metric of a chosen basis is a column of its own.
    fireEvent.click(box.getByLabelText("Total revenue · Downside FY1"));
    expect(search().getAll("col")).toContain("m:revenue@DOWNSIDE_FY1");
  });

  test("issuer name and period cannot be removed", () => {
    renderBook();
    const box = chooser();
    expect(LOCKED).toEqual(["id:issuer_name", "id:reporting_period"]);
    for (const name of ["Issuer", "Reporting period"]) {
      const check = box.getByLabelText(name);
      expect(check).toBeChecked();
      expect(check).toHaveAttribute("aria-disabled", "true");
      fireEvent.click(check);
      expect(box.getByLabelText(name)).toBeChecked();
      expect(search().getAll("col")).toEqual([]);
    }
  });

  test("a column outside the catalogue can still be removed", () => {
    renderBook(document(), "/book/?col=m%3Aadjusted_ebitda_margin");
    expect(search().getAll("col")).toContain("m:adjusted_ebitda_margin");
    const box = chooser();
    const orphan = box.getByLabelText("adjusted_ebitda_margin (not in this Book's catalogue)");
    expect(orphan).toBeChecked();
    fireEvent.click(orphan);
    expect(search().getAll("col")).not.toContain("m:adjusted_ebitda_margin");
  });

  test("a range filter hides issuers outside it", () => {
    renderBook();
    fireEvent.click(screen.getByRole("button", { name: "Add filter" }));
    fireEvent.change(screen.getByLabelText("Filter column"), {
      target: { value: "m:metric:net_leverage_adjusted" },
    });
    fireEvent.change(screen.getByLabelText("Minimum"), { target: { value: "5" } });
    fireEvent.click(screen.getByRole("button", { name: "Apply filter" }));
    expect(rows().map((row) => row.getAttribute("data-issuer"))).toEqual(["VMO2", "ALH", "MRG"]);
    expect(screen.getByText("3 of 9 issuers")).toBeInTheDocument();
    expect(search().getAll("f")).toEqual(["range|m%3Ametric%3Anet_leverage_adjusted|5|"]);
    // The chip removes it again.
    fireEvent.click(screen.getByRole("button", { name: /^Remove filter/ }));
    expect(rows()).toHaveLength(9);
    expect(search().getAll("f")).toEqual([]);
  });

  test("history lists earlier entries including withdrawn ones", () => {
    const doc = document();
    renderBook(doc);
    const vmo2 = doc.body.issuers[2]!;
    expect(screen.queryByText("DATA_ERROR")).toBeNull();
    const toggle = screen.getByRole("button", { name: /^History \(1\).*Virgin Media O2/ });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    fireEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    const history = document_().querySelector<HTMLElement>('[data-history="VMO2"]')!;
    const earlier = vmo2.history[0]!;
    expect(history).toHaveTextContent(earlier.analysis_date);
    expect(history).toHaveTextContent(earlier.reporting_period);
    expect(history).toHaveTextContent(earlier.route);
    expect(history).toHaveTextContent("Withdrawn");
    expect(history).toHaveTextContent("Data error");
    expect(history).not.toHaveTextContent("DATA_ERROR");
    // An issuer with no earlier entry has no history control.
    expect(screen.queryByRole("button", { name: /^History.*Northgate/ })).toBeNull();
    // A limitation stored with an entry is reachable from its row.
    const mrg = document_().querySelector<HTMLElement>('tr[data-issuer="MRG"]')!;
    fireEvent.click(within(mrg).getByRole("button", { name: /^Limited/ }));
    expect(document_().querySelector('[data-limitations="MRG"]')).toHaveTextContent(
      "interim period annualised by the host",
    );
  });

  test("links open the entry run's analysis and model", () => {
    const doc = document();
    renderBook(doc);
    const { case_id: caseId, run_id: runId } = doc.body.issuers[2]!.displayed;
    expect(screen.getByRole("link", { name: "Virgin Media O2" })).toHaveAttribute(
      "href",
      `/analysis/?case=${caseId}&run=${runId}`,
    );
    expect(screen.getByRole("link", { name: "Open model for Virgin Media O2" })).toHaveAttribute(
      "href",
      `/model/?case=${caseId}&run=${runId}`,
    );
  });

  test("sorting sets aria-sort and a money sort asks for a currency", () => {
    renderBook();
    const sort = screen.getByRole("button", { name: /^Net leverage, adjusted EBITDA\s+LTM/ });
    fireEvent.click(sort);
    const header = sort.closest("th")!;
    expect(header).toHaveAttribute("aria-sort", "ascending");
    expect(rows()[0]).toHaveAttribute("data-issuer", "CVNA");
    fireEvent.click(sort);
    expect(header).toHaveAttribute("aria-sort", "descending");
    expect(rows()[0]).toHaveAttribute("data-issuer", "MRG");
    expect(screen.queryByLabelText("Currency")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: /^Total revenue/ }));
    // The sort waits for a currency: it claims no order it does not perform.
    const money = screen.getByRole("button", { name: /^Total revenue/ }).closest("th")!;
    expect(money).toHaveAttribute("aria-sort", "none");
    expect(money).not.toHaveTextContent(/[▲▼]/);
    expect(screen.getByText(/choose a currency to compare/i)).toBeInTheDocument();
    const currency = screen.getByLabelText("Currency");
    fireEvent.change(currency, { target: { value: "GBP" } });
    expect(search().get("cur")).toBe("GBP");
    expect(money).toHaveAttribute("aria-sort", "ascending");
    expect(rows()[0]).toHaveAttribute("data-issuer", "SLU");
    fireEvent.click(screen.getByRole("button", { name: "Reset view" }));
    expect(search().get("sort")).toBeNull();
    expect(search().get("cur")).toBeNull();
  });

  test("the last view is restored from the browser when the URL names none", () => {
    window.localStorage.setItem("caos.book.view", "basis=BASE_FY1&col=id%3Asector");
    renderBook();
    expect(search().get("basis")).toBe("BASE_FY1");
    expect(search().getAll("col")).toEqual(["id:issuer_name", "id:reporting_period", "id:sector"]);
    fireEvent.click(screen.getByRole("radio", { name: "LTM" }));
    expect(window.localStorage.getItem("caos.book.view")).toContain("basis=LTM");
  });

  test("an empty Book says so and counts none", () => {
    const empty = parseBookDocument(JSON.parse(readFileSync(EMPTY, "utf8")));
    renderBook(empty);
    expect(screen.getByText("0 of 0 issuers")).toBeInTheDocument();
    expect(screen.getByText("No issuers in the Book.")).toBeInTheDocument();
  });

  test("the currency select offers only currencies a displayed issuer holds", () => {
    renderBook(document(), "/book/?sort=asc%7Cm%3Arevenue&cur=CHF");
    const select = screen.getByLabelText<HTMLSelectElement>("Currency");
    expect([...select.options].map((o) => o.value)).toEqual(["", "EUR", "GBP", "JPY", "USD"]);
    // A currency nobody holds is no currency: the select says so and the order is the document's.
    expect(select.value).toBe("");
    expect(rows()[0]).toHaveAttribute("data-issuer", "CVNA");
  });

  test("a filter chip names the basis its column follows", () => {
    renderBook();
    fireEvent.click(screen.getByRole("button", { name: "Add filter" }));
    fireEvent.change(screen.getByLabelText("Filter column"), {
      target: { value: "m:metric:net_leverage_adjusted" },
    });
    fireEvent.change(screen.getByLabelText("Minimum"), { target: { value: "5" } });
    fireEvent.click(screen.getByRole("button", { name: "Apply filter" }));
    expect(screen.getByRole("button", { name: /^Remove filter.*\(LTM\)/ })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("radio", { name: "Base FY1" }));
    expect(
      screen.getByRole("button", { name: /^Remove filter.*\(Base FY1\)/ }),
    ).toBeInTheDocument();
  });

  test("a money range filter does nothing until a currency is chosen", () => {
    renderBook();
    fireEvent.click(screen.getByRole("button", { name: "Add filter" }));
    fireEvent.change(screen.getByLabelText("Filter column"), { target: { value: "m:revenue" } });
    fireEvent.change(screen.getByLabelText("Minimum"), { target: { value: "1000000" } });
    fireEvent.click(screen.getByRole("button", { name: "Apply filter" }));
    expect(screen.getByText("9 of 9 issuers")).toBeInTheDocument();
    expect(screen.getByText(/choose a currency to compare/i)).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Currency"), { target: { value: "JPY" } });
    expect(rows().map((row) => row.getAttribute("data-issuer"))).toEqual(["PFL"]);
  });

  test("Apply filter does nothing while its bounds are refused", () => {
    renderBook();
    fireEvent.click(screen.getByRole("button", { name: "Add filter" }));
    fireEvent.change(screen.getByLabelText("Filter column"), {
      target: { value: "m:metric:net_leverage_adjusted" },
    });
    fireEvent.change(screen.getByLabelText("Minimum"), { target: { value: "abc" } });
    const apply = screen.getByRole("button", { name: "Apply filter" });
    expect(apply).toHaveAttribute("aria-disabled", "true");
    expect(screen.getByRole("alert")).toHaveTextContent("decimal");
    fireEvent.click(apply);
    expect(search().getAll("f")).toEqual([]);
    expect(screen.getByText("9 of 9 issuers")).toBeInTheDocument();
  });

  test("the URL beats the remembered view", () => {
    window.localStorage.setItem("caos.book.view", "basis=BASE_FY1");
    renderBook(document(), "/book/?basis=PF_LTM");
    expect(search().get("basis")).toBe("PF_LTM");
  });

  test("a browser that refuses storage still shows and changes the view", () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new DOMException("denied", "SecurityError");
    });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new DOMException("denied", "SecurityError");
    });
    renderBook();
    expect(rows()).toHaveLength(9);
    fireEvent.click(screen.getByRole("radio", { name: "Base FY1" }));
    expect(search().get("basis")).toBe("BASE_FY1");
  });

  test("a chooser or row toggle does not redraw every row", () => {
    renderBook();
    const draws = vi.mocked(spelled);
    const full = draws.mock.calls.length;
    expect(full).toBeGreaterThan(30);
    draws.mockClear();
    fireEvent.click(screen.getByRole("button", { name: "Columns" }));
    expect(draws).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: /^History \(1\).*Virgin Media O2/ }));
    expect(draws.mock.calls.length).toBeLessThan(full / 2);
  });

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

  test("the fixture parses with parseBookDocument", () => {
    const doc = document();
    expect(doc.body.issuers.length).toBeGreaterThanOrEqual(8);
    expect(
      new Set(doc.body.issuers.map((issuer) => issuer.displayed.currency)).size,
    ).toBeGreaterThan(2);
    expect(doc.body.issuers.some((issuer) => issuer.history.some((e) => e.withdrawn_at))).toBe(
      true,
    );
    expect(doc.body.issuers.filter((issuer) => issuer.displayed.sources_withdrawn)).toHaveLength(1);
    expect(parseBookDocument(JSON.parse(readFileSync(EMPTY, "utf8"))).body.issuers).toEqual([]);
  });

  test("a metrics leaf is decimal text or null, never a number", () => {
    const fixture = raw();
    fixture.body.issuers[0].displayed.metrics.LTM.revenue = 20322;
    expect(() => parseBookDocument(fixture)).toThrow(WireShapeError);
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

  test("URL columns and filters remain editable without losing context", () => {
    renderBook(
      document(),
      "/book/?case=keep&tag=one&tag=two&col=id%3Afiled&col=id%3Afiscal_year_base_fy1&f=set%7Cid%253Aissuer_id%7CCVNA",
    );
    expect(rows()).toHaveLength(1);
    expect(cell("CVNA", "id:filed")).toHaveTextContent(/^Yes$/);
    expect(cell("CVNA", "id:fiscal_year_base_fy1")).toHaveTextContent(/^2026$/);
    expect(screen.getByText("1 of 9 issuers")).toBeVisible();
    expect(screen.getByRole("button", { name: "Columns" })).toBeVisible();
    expect(screen.getByRole("button", { name: "Add filter" })).toBeVisible();
    expect(screen.getByRole("button", { name: /^Remove filter/ })).toBeVisible();
    const entry = document().body.issuers[0]!;
    expect(entry.displayed.actions).toContain("WITHDRAW_BOOK_ENTRY");
    expect(screen.getByRole("button", { name: "Withdraw Carvana Co." })).toBeVisible();
    expect(entry.history).toHaveLength(0);
    expect(screen.queryByRole("button", { name: /^History/ })).toBeNull();
    expect(entry.displayed.limitations).toHaveLength(1);
    expect(screen.getByRole("button", { name: /^Limited/ })).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Reset view" }));
    expect(search().get("case")).toBe("keep");
    expect(search().getAll("tag")).toEqual(["one", "two"]);
    expect(search().getAll("f")).toEqual([]);
    expect(rows()).toHaveLength(9);
  });

  test("a URL money range waits for a native currency", () => {
    renderBook(document(), "/book/?f=range%7Cm%253Arevenue%7C1000000%7C");
    expect(rows()).toHaveLength(9);
    expect(screen.getByText(/choose a currency to compare/i)).toBeVisible();
    fireEvent.change(screen.getByLabelText("Currency"), { target: { value: "JPY" } });
    expect(rows().map((row) => row.getAttribute("data-issuer"))).toEqual(["PFL"]);
    expect(cell("PFL", "id:currency")).toHaveTextContent(/^JPY$/);
  });

  test("a set editor applies served values and refuses an empty selection", () => {
    renderBook();
    fireEvent.click(screen.getByRole("button", { name: "Add filter" }));
    fireEvent.change(screen.getByLabelText("Filter column"), { target: { value: "id:currency" } });
    const apply = screen.getByRole("button", { name: "Apply filter" });
    expect(apply).toHaveAttribute("aria-disabled", "true");
    fireEvent.click(apply);
    expect(search().getAll("f")).toEqual([]);
    fireEvent.click(screen.getByRole("checkbox", { name: "GBP" }));
    fireEvent.click(apply);
    expect(search().getAll("f")).toEqual(["set|id%3Acurrency|GBP"]);
    expect(rows().map((row) => row.getAttribute("data-issuer"))).toEqual(["VMO2", "NGE", "SLU"]);
    expect(screen.getByText("3 of 9 issuers")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: /^Remove filter.*GBP/ }));
    expect(rows()).toHaveLength(9);
  });

  test("a notch editor rejects inverted ratings then filters within its scale", () => {
    renderBook();
    fireEvent.click(screen.getByRole("button", { name: "Add filter" }));
    fireEvent.change(screen.getByLabelText("Filter column"), { target: { value: "id:moodys" } });
    fireEvent.change(screen.getByLabelText("Best rating"), { target: { value: "B1" } });
    fireEvent.change(screen.getByLabelText("Worst rating"), { target: { value: "Ba1" } });
    const apply = screen.getByRole("button", { name: "Apply filter" });
    expect(apply).toHaveAttribute("aria-disabled", "true");
    expect(screen.getByRole("alert")).toHaveTextContent("best rating is below the worst");
    fireEvent.click(apply);
    expect(search().getAll("f")).toEqual([]);
    fireEvent.change(screen.getByLabelText("Best rating"), { target: { value: "Ba1" } });
    fireEvent.change(screen.getByLabelText("Worst rating"), { target: { value: "B1" } });
    fireEvent.click(apply);
    expect(search().getAll("f")).toEqual(["notch|moodys|Ba1|B1"]);
    const expected = document().body.issuers.filter((issuer) =>
      ["Ba1", "Ba2", "Ba3", "B1"].includes(issuer.displayed.moodys ?? ""),
    );
    expect(expected.length).toBeGreaterThan(0);
    expect(expected.length).toBeLessThan(9);
    expect(rows().map((row) => row.getAttribute("data-issuer"))).toEqual(
      expected.map((issuer) => issuer.issuer_key),
    );
  });

  test.each([
    ["", "", "Enter a minimum"],
    ["5", "2", "minimum is above"],
  ])("a range editor refuses bounds %s and %s", (minimum, maximum, problem) => {
    renderBook();
    fireEvent.click(screen.getByRole("button", { name: "Add filter" }));
    fireEvent.change(screen.getByLabelText("Filter column"), {
      target: { value: "m:metric:net_leverage_adjusted" },
    });
    fireEvent.change(screen.getByLabelText("Minimum"), { target: { value: minimum } });
    fireEvent.change(screen.getByLabelText("Maximum"), { target: { value: maximum } });
    const apply = screen.getByRole("button", { name: "Apply filter" });
    expect(apply).toHaveAttribute("aria-disabled", "true");
    if (minimum || maximum) expect(screen.getByRole("alert")).toHaveTextContent(problem);
    fireEvent.click(apply);
    expect(search().getAll("f")).toEqual([]);
    expect(rows()).toHaveLength(9);
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

  test("each issuer is one row: its displayed entry's name, period, sector and composite", () => {
    const doc = document();
    renderBook(doc);
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
    renderBook();
    const table = screen.getByRole("table", { name: "Issuers in the Book" });
    expect(within(table).getByRole("columnheader", { name: "Total revenue LTM" })).toBeVisible();
    const row = table.querySelector('[data-issuer="CVNA"]')!;
    expect(within(row as HTMLElement).getByText("USD")).toBeVisible();
    expect(cell("CVNA", "id:currency")).toHaveTextContent(/^USD$/);
    expect(cell("CVNA", "id:unit")).toHaveTextContent(/^MILLIONS$/);
    expect(cell("CVNA", "m:revenue")).toHaveTextContent("20,322");
    expect(within(cell("CVNA", "m:revenue")).getByTitle("20322")).toBeVisible();
    expect(cell("CVNA", "m:revenue")).not.toHaveAttribute("aria-description");
  });

  test.each([null, "0"])("LTM revenue %s preserves missing values and zero", (value) => {
    const fixture = raw();
    fixture.body.issuers[0].displayed.metrics.LTM.revenue = value;
    renderBook(parseBookDocument(fixture));
    const revenue = cell("CVNA", "m:revenue");
    if (value === null) {
      expect(revenue).toHaveTextContent("Not stated");
      expect(revenue).not.toHaveTextContent("0");
    } else {
      expect(revenue).toHaveTextContent("0");
      expect(revenue).not.toHaveTextContent("Not stated");
      expect(within(revenue).getByTitle("0")).toBeVisible();
    }
  });
});

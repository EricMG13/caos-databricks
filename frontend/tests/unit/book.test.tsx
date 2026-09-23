import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { LedgerProvider } from "@/app/ledger";
import { EvidenceProvider } from "@/evidence/EvidenceContext";
import { PASSPORT_FIELDS } from "@/wire";
import { BookSection } from "@/sections/book/BookSection";
import { citationOf, passportOf, shownValue } from "@/sections/book/passport";
import { tailed } from "@/app/authority";
import { parseBookDocument, type BookDocument } from "@/wire/v1";

const FIXTURE = resolve(process.cwd(), "fixtures", "book.json");

function document(): BookDocument {
  return parseBookDocument(JSON.parse(readFileSync(FIXTURE, "utf8")));
}

function mount(doc: BookDocument = document()) {
  return render(
    <LedgerProvider>
      <EvidenceProvider>
        <BookSection document={doc} tab={null} />
      </EvidenceProvider>
    </LedgerProvider>,
  );
}

describe("the book", () => {
  test("the served fixture is the declared v1 shape", () => {
    const doc = document();
    expect(doc.body.basis).toEqual({
      period: "EVERY_ACCEPTED_PERIOD",
      scenario: "EVERY_ACCEPTED_CASE",
      accepted_only: true,
    });
    expect(doc.body.columns.map((column) => column.key)).toContain("operating.margin");
  });

  test("a credit is one row per accepted period, on its own units", () => {
    mount();
    const table = screen.getByRole("table", { name: /BASE · FY2026/ });
    const row = within(table).getByRole("row", { name: /Carvana/ });
    expect(within(row).getByRole("button", { name: /EBITDA margin.*0\.20$/ })).toBeVisible();
    expect(row).toHaveTextContent("USD · millions");
  });

  test("a credit with no accepted forecast says so and shows no figure", () => {
    mount();
    const table = screen.getByRole("table", { name: /BASE · FY2026/ });
    const row = within(table).getByRole("row", { name: /Terra Firma/ });
    expect(row).toHaveTextContent("NO_ACCEPTED_FORECAST");
    expect(row).toHaveTextContent("the run ended BLOCKED");
    expect(within(row).queryAllByRole("button")).toEqual([]);
  });

  test("selecting a cell opens the passport with its ten fields", () => {
    mount();
    fireEvent.click(screen.getAllByRole("button", { name: /EBITDA margin.*0\.20$/ })[0]!);
    const dialog = screen.getByRole("dialog");
    const fields = [...dialog.querySelectorAll("[data-passport] > [data-passport-field]")].map(
      (element) => element.getAttribute("data-passport-field"),
    );
    for (const field of PASSPORT_FIELDS) expect(fields).toContain(field);
    expect(dialog).toHaveTextContent("operating.ebitda / operating.revenue");
    expect(dialog).toHaveTextContent("cash_flow_forecast · VERIFIED");
    // The scenario the record names, so a base case and a downside are told
    // apart in the passport rather than both reading NOT_DECLARED.
    expect(dialog).toHaveTextContent("Scenario");
    expect(dialog).toHaveTextContent("BASE");
    expect(within(dialog).getByText("USD millions")).toBeVisible();
    // The analyst's declared reporting period, labelled as what it is: the
    // host derives no date from any admitted document.
    expect(dialog).toHaveTextContent("Reporting period");
    expect(dialog).not.toHaveTextContent("Evidence date");
    expect(fields).toContain("reporting_period");
  });

  test("a refused cell value shows its typed reason, never a blank", () => {
    const doc = document();
    const cell = doc.body.rows[0]!.periods[0]!.cells[0]!;
    // Rounded for reading; the passport keeps the exact decimal.
    expect(shownValue(cell)).toBe("500.00");
    expect(cell.value).toBe("500.000000");
    expect(
      shownValue({
        ...cell,
        value: null,
        unavailable_reason: "ZERO_OR_NEGATIVE_DENOMINATOR",
      }),
    ).toBe("ZERO_OR_NEGATIVE_DENOMINATOR");
    expect(shownValue({ ...cell, value: null })).toBe("NOT SERVED");
  });

  test("a passport citation names its document, page and quote and claims no rectangle", () => {
    const doc = document();
    const row = doc.body.rows[0]!;
    const cell = row.periods[0]!.cells[0]!;
    const [fact] = cell.passport.citations;
    const citation = citationOf(fact!, doc.observed_at);
    expect(citation.chip).toBe("issuer-pack.txt p.1");
    // The Book serves no page frame, so no rectangle is claimed for one.
    expect(citation.bboxes).toEqual([]);
    // The revenue cell cites the revenue driver: a passport whose stated
    // derivation and cited line disagree is the dishonesty this section exists
    // to prevent, and the fixture used to carry one.
    expect(citation.matched_text).toContain("/drivers/0/revenue");

    const passport = passportOf(row, doc.body.columns[0]!, cell, doc.observed_at);
    expect(passport.label).toBe("Carvana Co. · Revenue");
    expect(passport.unit).toBe("USD millions");
    // One calculator, one spelling: nothing here deviates, and no cell is a
    // projection with a driver the derivation does not already name.
    expect(passport.deviation).toBeNull();
    expect(passport.driver).toBeNull();
    expect(passport.supporting_research.map((link) => link.module_id)).toContain("CP-2G");
  });

  // `test_book_binds_one_snapshot_per_compared_case` is the pure-function
  // half, in `authority.test.ts`, and is the name `tests/test_phase_exits.py`
  // pins. This is the same rule through the section that now calls it.
  test("the lens stays on the snapshot a credit is bound to until it is switched", () => {
    const doc = document();
    const { rerender } = mount(doc);
    const moved: BookDocument = {
      ...doc,
      body: {
        ...doc.body,
        rows: doc.body.rows.map((row) =>
          row.snapshot === null ? row : { ...row, snapshot: "f".repeat(64) },
        ),
      },
    };
    // The same ledger, a later document naming another snapshot for credits
    // already bound: the lens does not move on its own, and each bound credit
    // says so on its own row.
    rerender(
      <LedgerProvider>
        <EvidenceProvider>
          <BookSection document={moved} tab={null} />
        </EvidenceProvider>
      </LedgerProvider>,
    );
    const bound = doc.body.rows.filter((row) => row.snapshot !== null);
    expect(bound.length).toBeGreaterThan(1);
    for (const row of bound) {
      const note = window.document.querySelector(`[data-lens-refused="${row.case_id}"]`);
      expect(note, row.case_id).not.toBeNull();
      expect(note).toHaveTextContent(row.snapshot!);
    }
    // Only the explicit switch moves it.
    fireEvent.click(screen.getAllByRole("button", { name: "Switch the lens" })[0]!);
    expect(window.document.querySelector(`[data-lens-refused="${bound[0]!.case_id}"]`)).toBeNull();
  });

  test("every credit is named when none of them has a forecast to compare", () => {
    // The ordinary state, not an edge: CP-CF runs only on
    // `FULL_CREDIT_32/RELATIVE_VALUE`, so every credit of a case on a LITE
    // route is `NO_ACCEPTED_FORECAST`. The page used to draw a credit count
    // over nothing at all and say why for none of them.
    const doc = document();
    const unrun: BookDocument = {
      ...doc,
      body: {
        ...doc.body,
        rows: doc.body.rows.map((row) => ({
          ...row,
          periods: [],
          snapshot: null,
          unavailable_reason: "NO_ACCEPTED_FORECAST" as const,
        })),
      },
    };
    mount(unrun);

    for (const row of unrun.body.rows) {
      expect(screen.getByText(row.title)).toBeVisible();
    }
    // And why, for each of them, rather than a bare list of titles.
    expect(screen.getAllByText(/NO_ACCEPTED_FORECAST/).length).toBe(unrun.body.rows.length);
  });

  test("test_the_demonstration_book_names_the_one_pathway_that_can_serve_it", () => {
    // The fixture shows a populated Book, and only a run on
    // FULL_CREDIT_32 / RELATIVE_VALUE created with the model extension can
    // produce a forecast to compare. The demonstration says so on the page;
    // the real workspace, which shows what the store holds, does not.
    // Stubbed rather than taken from the runner, as the directory's note is:
    // `npm test` runs in demo mode.
    try {
      vi.stubEnv("MODE", "demo");
      const demo = mount();
      const note = demo.container.querySelector("[data-demo-book-note]");
      expect(note).not.toBeNull();
      expect(note).toHaveTextContent("FULL_CREDIT_32 / RELATIVE_VALUE");
      expect(note).toHaveTextContent("model extension");
      demo.unmount();

      vi.stubEnv("MODE", "production");
      const real = mount();
      expect(real.container.querySelector("[data-demo-book-note]")).toBeNull();
    } finally {
      vi.unstubAllEnvs();
    }
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

// Analysis, /analysis/ (IA_SPEC.md 4.3), v1 wire (brief 4.1, slice 4.1j):
// every accepted handoff in route order, its host-verified source facts, the
// model's own analysis rendered as text and never as markup, and the
// reminder that the host performs no calculation. Pending nodes are named
// with the state the route left them in.
import { readFileSync } from "node:fs";
import type { ReactNode } from "react";
import { fireEvent, render, within } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { composeChrome, words } from "@/chrome/compose";
import { stamp } from "@/ds/format";
import { clampExcerpt } from "@/evidence/compact";
import { readMarkdown } from "@/ds/markdown";
import { ReaderParts } from "@/sections/analysis/module";
import { AnalysisSection, PROSE_SHOWN, sourceRegister } from "@/sections/analysis/AnalysisSection";
import { conclusionOf, handoffSeverity } from "@/sections/analysis/tone";
import { parseAnalysisDocument } from "@/wire/v1";
import type { AnalysisDocument, HandoffView } from "@/wire/v1";

const load = (path: string): unknown =>
  JSON.parse(readFileSync(new URL(path, import.meta.url), "utf8"));

const complete = parseAnalysisDocument(load("../../fixtures/analysis.json"));
const partial = parseAnalysisDocument(load("../../fixtures/states/analysis.partial.json"));

// The section links to Model, so it renders inside a router.
const routed = (node: ReactNode) => render(<MemoryRouter>{node}</MemoryRouter>);

function mount(document: AnalysisDocument) {
  return routed(<AnalysisSection document={document} tab={null} />);
}

/** One module is shown at a time (the section's tabs pick it): this renders
    the section with `moduleId`'s module selected. */
function mountAt(document: AnalysisDocument, moduleId: string) {
  const handoff = document.body.handoffs.find((entry) => entry.module_id === moduleId)!;
  return routed(<AnalysisSection document={document} tab={handoff.route_node_id} />);
}

/** Opens one of the module's three tabs: Appendix, Audit, As written. */
function openTab(container: HTMLElement, tab: "appendix" | "audit" | "written") {
  fireEvent.click(container.querySelector(`[data-depth-tab="${tab}"]`)!);
}

describe("Analysis", () => {
  test("labelled columns retain nested caveats as a list", () => {
    const blocks = readMarkdown(
      "- **Strength** Core cash flow\n  - Subject to refinancing\n- **Risk** Leverage",
    )!;
    const { container } = routed(<ReaderParts parts={[{ title: "Assessment", blocks }]} />);
    expect(container.querySelector("[data-reader-part] .cols")).toBeNull();
    expect(container).toHaveTextContent("Subject to refinancing");
  });

  test("test_every_enabled_demo_fixture_is_a_valid_v1_document", () => {
    const fixtures = [
      "../../fixtures/analysis.json",
      "../../fixtures/states/analysis.partial.json",
    ];
    for (const path of fixtures) {
      expect(() => parseAnalysisDocument(load(path))).not.toThrow();
    }
  });

  test("test_analysis_renders_markdown_formatted_with_limitations_visible", () => {
    const { container } = mountAt(complete, "CP-1");
    const { container: restricted } = mountAt(complete, "CP-1C");
    const cp1c = restricted.querySelector('[data-handoff="CP-1C"]')!;
    // The model's prose is drawn as the host renderer's closed element set
    // (D60): its opening heading heads the view, its emphasis is <strong>,
    // its numbered list a list, its code a code span -- and no Markdown
    // delimiter is left on the page.
    const cp1 = container.querySelector('[data-handoff="CP-1"]')!;
    const view = cp1.querySelector("[data-model-analysis]")!;
    expect(view.querySelector("header h3")).toHaveTextContent("Normalised financials");
    expect(view.querySelector("strong")).toHaveTextContent("$769M");
    expect(view.querySelectorAll("ol > li")).toHaveLength(2);
    expect(view.querySelector("code")).toHaveTextContent("net_leverage");
    expect(view.textContent).not.toContain("**");
    expect(view.textContent).not.toContain("##");
    // The exact text stays one tab away, every character as written.
    openTab(container, "written");
    const written = cp1.querySelector("[data-as-written]")!;
    expect(written.textContent).toContain("## Normalised financials");
    expect(written.textContent).toContain("**$769M**");
    expect(written.querySelector("h1,h2,h3,h4,h5,h6,strong,em,code,ul,ol,li")).toBeNull();
    // Limitation flags are always visible, whether empty or carrying a flag.
    const cp1Flags = cp1.querySelector("[data-limitation-flags]")!;
    expect(cp1Flags.textContent).toContain("none");
    const cp1cFlags = cp1c.querySelector("[data-limitation-flags]")!;
    expect(cp1cFlags.textContent).toContain("1");
    // Each flag is a caveat, in words, its identifier kept on hover.
    expect(cp1c.querySelector('[data-limitation-flag="PEER_SET_INCOMPLETE"]')).toHaveTextContent(
      "Peer set incomplete",
    );
    expect(cp1cFlags).toBeVisible();
    expect(cp1Flags).toBeVisible();
    // A warning written as prose stands as written; only identifiers are renamed.
    expect(cp1c.textContent).toContain("one peer's most recent filing is more than 200 days old");
  });

  test("test_the_demo_tables_arrive_as_typed_data_the_section_can_chart", () => {
    // The server reads a handoff's tagged tables with the bundle's own reader;
    // the browser receives text and exact decimal strings and parses nothing.
    const cp1 = complete.body.handoffs.find((h) => h.module_id === "CP-1")!;
    expect(cp1.tables_unavailable_reason).toBeNull();
    expect(cp1.tables.map((t) => t.table_id)).toEqual([
      "cp1.model_period_register",
      "cp1.segment_revenue_schedule",
      "cp1.operating_kpi_schedule",
      "cp1.adjusted_ebitda_bridge",
      "cp1.debt_facility_register",
    ]);
    for (const table of cp1.tables) {
      expect(cp1.model_analysis).toContain(`<!-- table-id: ${table.table_id} -->`);
      expect(cp1.model_analysis).toContain(`| ${table.columns.join(" | ")} |`);
      for (const row of table.rows) expect(row).toHaveLength(table.columns.length);
    }
    const kpis = cp1.tables.find((t) => t.table_id === "cp1.operating_kpi_schedule")!;
    const id = kpis.columns.indexOf("kpi_id");
    const value = kpis.columns.indexOf("value");
    const series = (kpi: string) =>
      kpis.rows.filter((row) => row[id]?.text === kpi).map((row) => row[value]);
    expect(series("retail_units_sold").map((cell) => cell?.value)).toEqual([
      "143280",
      "155941",
      "163522",
      "184114",
      "197325",
    ]);
    expect(series("total_gpu").at(-1)).toEqual({ text: "$7,125", value: "7125" });
    // A null is "no figure", never zero; a bracketed figure is negative.
    const cells = cp1.tables.flatMap((t) => t.rows.flat());
    expect(cells.find((c) => c.text === "Not applicable")!.value).toBeNull();
    expect(cells.find((c) => c.text === "(14)")!.value).toBe("-14");
    // Tables the bundle's reader refused are withheld whole, the reason named.
    const cf = partial.body.handoffs.find((h) => h.module_id === "CP-CF")!;
    expect([cf.tables, cf.tables_unavailable_reason]).toEqual([[], "TABLES_MALFORMED"]);
  });

  test("the three labelled parts render for every handoff, in their places", () => {
    for (const handoff of complete.body.handoffs) {
      const { container, unmount } = mountAt(complete, handoff.module_id);
      const card = container.querySelector(`[data-handoff="${handoff.module_id}"]`)!;
      // The model's view, labelled as the model's; the host's calculation
      // note; route identifiers stay out of the header's facts.
      expect(card.querySelector("[data-model-analysis] header")).toHaveTextContent(
        "model-authored, not host-verified",
      );
      expect(card.querySelector("[data-host-calculation]")).toHaveTextContent(
        "Deterministic calculations: none performed by the host",
      );
      expect(card.querySelector(".modfacts [data-route-node]")).toBeNull();
      expect(card.querySelector(".modfacts")).not.toHaveTextContent(handoff.route_node_id);
      // Its host-verified citations lead the Audit tab, in every module.
      openTab(container, "audit");
      const audit = card.querySelector('[data-depth-panel="audit"]')!;
      expect(audit.querySelector('[data-audit-part="Source facts"] h3')).toHaveTextContent(
        "Source facts",
      );
      expect(audit.querySelector("[data-source-facts]")).not.toBeNull();
      // The node and the digests left the header's facts; the Audit tab names them.
      const record = audit.querySelector('[data-audit-part="Record"]')!;
      expect(record).toHaveTextContent(handoff.route_node_id);
      expect(
        record.querySelector(`[data-digest="sha256:${handoff.artifact_sha256}"]`),
      ).not.toBeNull();
      expect(
        record.querySelector(`[data-digest="sha256:${handoff.record_sha256}"]`),
      ).not.toBeNull();
      unmount();
    }
  });

  test("the Audit tab counts CP-5's issues, a pressed segment said as computed here", () => {
    // Made-up issues under a fixture handoff relabelled CP-5.
    const columns = ["Issue ID", "Severity", "Module", "Issue Type"];
    const cell = (text: string) => ({ text, value: null });
    const handoff: HandoffView = {
      ...complete.body.handoffs[0]!,
      module_id: "CP-5",
      registers: [
        {
          register_id: "T5.9",
          columns,
          declared: columns,
          rows: [
            ["I-1", "CRITICAL", "CP-1", "Citation"].map(cell),
            ["I-2", "MINOR", "CP-1", "Math"].map(cell),
          ],
        },
      ],
    };
    const document = { ...complete, body: { ...complete.body, handoffs: [handoff] } };
    const { container } = mountAt(document, "CP-5");
    openTab(container, "audit");
    const audit = container.querySelector('[data-depth-panel="audit"]')!;
    const group = audit.querySelector('[data-audit-part="Counts"]') as HTMLElement;
    // After every other group.
    expect([...audit.querySelectorAll("[data-audit-part]")].at(-1)).toBe(group);
    expect(group.querySelector("h3")).toHaveTextContent("Counts");
    const figure = group.querySelector("[data-figure='issue-counts']") as HTMLElement;
    expect(figure).toHaveTextContent("Issues by module and severity, count");
    fireEvent.click(within(figure).getByRole("button", { name: /^CRITICAL, CP-1: 1 issues/ }));
    const picked = container.querySelector("[data-picked]")!;
    expect(picked.querySelector("[data-picked-value]")!.textContent).toBe("1 issues");
    expect(picked).toHaveTextContent("Computed here: a count of the model's rows, not served");
    expect(picked).toHaveTextContent("Issues by module and severity, count");
  });

  test("model markup reaches the page as its own text, never as an element", () => {
    const hostile = [
      '# Heading <img src=x onerror="window.pwned=1">',
      "",
      "Text with <script>window.pwned=2</script> and <svg onload=alert(1)> in it.",
      "",
      "| Metric | Value |",
      "| --- | --- |",
      '| <a href="javascript:alert(1)">link</a> | 3.5x |',
    ].join("\n");
    const handoff = { ...complete.body.handoffs[0]!, model_analysis: hostile };
    const { container } = routed(
      <AnalysisSection
        document={{ ...complete, body: { ...complete.body, handoffs: [handoff] } }}
        tab={handoff.route_node_id}
      />,
    );
    expect(container.querySelector("img, script, svg[onload], a[href^='javascript']")).toBeNull();
    expect(container.textContent).toContain("<script>window.pwned=2</script>");
    expect(container.textContent).toContain('<img src=x onerror="window.pwned=1">');
    expect(container.querySelector("[data-model-analysis] table td")).toHaveTextContent(
      '<a href="javascript:alert(1)">link</a>',
    );
    expect((window as { pwned?: number }).pwned).toBeUndefined();
  });

  test("the section opens on its conclusion, not on the calculator that runs after it", () => {
    const { container } = mount(complete);
    // CP-CF is last in route order, but it calculates; CP-7 concludes.
    expect(container.querySelectorAll("[data-handoff]")).toHaveLength(1);
    expect(container.querySelector("[data-handoff]")).toHaveAttribute("data-handoff", "CP-7");
  });

  test("test_sourceRegister_names_each_cited_document_once_with_its_pages", () => {
    const register = sourceRegister(complete.body.handoffs);
    const facts = complete.body.handoffs.flatMap((handoff) => handoff.source_facts);
    expect(register.reduce((sum, entry) => sum + entry.count, 0)).toBe(facts.length);
    expect(new Set(register.map((entry) => entry.digest)).size).toBe(register.length);
    const withdrawn = facts.find((fact) => fact.withdrawn_at !== null)!;
    expect(register.find((entry) => entry.digest === withdrawn.document_sha256)!.withdrawn).toBe(
      true,
    );
    // Counted in the module's header; listed whole in the evidence drawer and
    // in the Audit tab (the rail they once filled is gone).
    const { container } = mount(complete);
    const count = container.querySelector("[data-documents-open]")!;
    expect(count).toHaveTextContent(
      `Run evidence · ${register.length} documents · ${facts.length} citations`,
    );
    expect(count).toHaveTextContent("1 withdrawn");
    fireEvent.click(count);
    const drawer = document.querySelector("[data-documents-drawer]")!;
    expect(drawer.querySelectorAll("[data-register-document]")).toHaveLength(register.length);
    openTab(container, "audit");
    expect(container.querySelectorAll("[data-depth-panel] [data-register-document]")).toHaveLength(
      register.length,
    );
  });

  test("a grouped source retains each citation's record and local index", () => {
    const base = complete.body.handoffs.find((handoff) => handoff.source_facts.length > 0)!;
    const other = complete.body.handoffs.find(
      (handoff) =>
        handoff.source_facts[0]?.document_sha256 !== base.source_facts[0]!.document_sha256,
    )!;
    const cited = base.source_facts[0]!;
    const first = { ...base, record_sha256: "a".repeat(64), source_facts: [cited] };
    const second = {
      ...base,
      module_id: "CP-X",
      record_sha256: "b".repeat(64),
      source_facts: [other.source_facts[0]!, cited],
    };
    const grouped = sourceRegister([first, second]).find(
      (entry) => entry.digest === cited.document_sha256,
    )!;
    expect(grouped.count).toBe(2);
    expect(grouped.citations).toEqual([
      {
        moduleId: base.module_id,
        withdrawn: cited.withdrawn_at !== null,
        identity: {
          record_sha256: first.record_sha256,
          source_id: cited.source_id,
          page: cited.page,
          index: 0,
        },
      },
      {
        moduleId: "CP-X",
        withdrawn: cited.withdrawn_at !== null,
        identity: {
          record_sha256: second.record_sha256,
          source_id: cited.source_id,
          page: cited.page,
          index: 1,
        },
      },
    ]);
  });

  test("same-page citations have distinct visible and accessible register labels", () => {
    const base = complete.body.handoffs.find((handoff) => handoff.source_facts.length > 0)!;
    const fact = base.source_facts[0]!;
    const changed = {
      ...complete,
      body: {
        ...complete.body,
        handoffs: complete.body.handoffs.map((handoff) =>
          handoff === base
            ? { ...handoff, source_facts: [fact, { ...fact, matched_text: "Another quote" }] }
            : handoff,
        ),
      },
    };
    const { container } = mountAt(changed, base.module_id);
    fireEvent.click(container.querySelector("[data-documents-open]")!);
    const chips = [
      ...document.querySelectorAll<HTMLButtonElement>(
        `[data-documents-drawer] [data-register-fact='${fact.source_id}']`,
      ),
    ];
    expect(chips).toHaveLength(2);
    expect(new Set(chips.map((chip) => chip.textContent)).size).toBe(2);
    expect(new Set(chips.map((chip) => chip.getAttribute("aria-label"))).size).toBe(2);
  });

  test("grouped citations retain their own withdrawal state", () => {
    const base = complete.body.handoffs.find((handoff) => handoff.source_facts.length > 0)!;
    const cited = base.source_facts[0]!;
    const other = {
      ...base,
      module_id: "CP-X",
      source_facts: [
        {
          ...cited,
          source_id: "different-admission",
          withdrawn_at: cited.withdrawn_at === null ? "2026-09-01T00:00:00Z" : null,
        },
      ],
    };
    const citations = sourceRegister([base, other]).find(
      (entry) => entry.digest === cited.document_sha256,
    )!.citations;
    expect(citations.map((citation) => citation.withdrawn)).toEqual([
      cited.withdrawn_at !== null,
      cited.withdrawn_at === null,
    ]);
  });

  test("long model prose is shown in part, and the rest on request", () => {
    const long = { ...complete.body.handoffs[0]!, model_analysis: "x".repeat(PROSE_SHOWN + 5) };
    const { container } = routed(
      <AnalysisSection
        document={{ ...complete, body: { ...complete.body, handoffs: [long] } }}
        tab={long.route_node_id}
      />,
    );
    openTab(container, "written");
    const pre = container.querySelector("[data-as-written]")!;
    expect(pre.textContent).toHaveLength(PROSE_SHOWN);
    fireEvent.click(container.querySelector("[data-prose-rest]")!);
    expect(container.querySelector("[data-as-written]")!.textContent).toHaveLength(PROSE_SHOWN + 5);
  });

  test("the appendix is an index: a register a line, opened one at a time, eight rows first", () => {
    const rows = Array.from({ length: 10 }, (_, index) => `| FY${index} | ${index} |`);
    const indexed = {
      ...complete.body.handoffs[0]!,
      model_analysis: [
        "## Analysis",
        "### View",
        "Prose.",
        "### Analytical appendix — complete canonical registers",
        "#### T4.14 — Period register",
        "| period_id | Revenue |",
        "| --- | --- |",
        ...rows,
        "<!-- table-id: cp1.adjusted_ebitda_bridge -->",
        "| addback_id | source_definition |",
        "| --- | --- |",
        "| A1 | as defined |",
      ].join("\n"),
    };
    const { container } = routed(
      <AnalysisSection
        document={{ ...complete, body: { ...complete.body, handoffs: [indexed] } }}
        tab={indexed.route_node_id}
      />,
    );
    const panel = container.querySelector('[data-depth-panel="appendix"]')!;
    // Opens on the index, every register closed: no table until one is asked
    // for. The bridge is Financials; a register no rule knows is last.
    const entries = [...panel.querySelectorAll("[data-register-entry]")];
    expect(entries.map((entry) => entry.textContent)).toEqual([
      "cp1.adjusted_ebitda_bridgeAdjusted EBITDA bridge1 row",
      "T4.14Period register10 rows",
    ]);
    expect(panel.querySelector("table")).toBeNull();
    const [bridge, period] = [...panel.querySelectorAll<HTMLElement>("[data-register-open]")];
    fireEvent.click(period!);
    expect(period).toHaveAttribute("aria-expanded", "true");
    expect(panel.querySelectorAll("tbody tr")).toHaveLength(8);
    // Its column heads read in words; the identifier stays on hover.
    expect(panel.querySelector("th span[title='period_id']")).toHaveTextContent("Period ID");
    fireEvent.click(panel.querySelector("[data-register-rest]")!);
    expect(panel.querySelectorAll("tbody tr")).toHaveLength(10);
    // Opening another closes the first.
    fireEvent.click(bridge!);
    expect(period).toHaveAttribute("aria-expanded", "false");
    expect(panel.querySelectorAll("table")).toHaveLength(1);
    expect(panel.querySelector("[data-register-rest]")).toBeNull();
  });

  test("the opening leads, its drivers are key points, the contrary view sits beside it", () => {
    const [cp1b, target] = [complete.body.handoffs[0]!, complete.body.handoffs[1]!];
    const opening = {
      ...cp1b,
      model_analysis: [
        "## Analysis",
        "### Credit view",
        "A single first-lien LBO whose credit is defined by leverage. It delevers slowly.",
        "",
        "Three facts govern:",
        "",
        `1. **Leverage is a spread.** 4.0x against 7.3x on one balance sheet. [${target.module_id} T9 / CP-99]`,
        "2. **Deleveraging is slow.** ~22% conversion.",
        "",
        "### Strongest contrary view",
        "On the management basis this is a ~4.0x credit.",
        "### Risks",
        "Consulting timing.",
      ].join("\n"),
    };
    const { container } = routed(
      <AnalysisSection
        document={{ ...complete, body: { ...complete.body, handoffs: [opening, target] } }}
        tab={opening.route_node_id}
      />,
    );
    const view = container.querySelector("[data-model-analysis]")!;
    expect(view.querySelector("[data-opening] .lede")).toHaveTextContent(
      "A single first-lien LBO whose credit is defined by leverage.",
    );
    const points = [...view.querySelectorAll("[data-key-point] .claim")];
    expect(points.map((point) => point.textContent)).toEqual([
      "Leverage is a spread.",
      "Deleveraging is slow.",
    ]);
    // Beside the view, not among the sections after it.
    expect(container.querySelector(".side [data-contrary] h3")).toHaveTextContent(
      "Strongest contrary view",
    );
    expect(container.querySelector('[data-reader-part="Strongest contrary view"]')).toBeNull();
    expect(container.querySelector('[data-reader-part="Risks"]')).not.toBeNull();
    // A reference is a way to the module it names, and to its register; a
    // module this run did not accept reads as its name alone.
    const link = view.querySelector<HTMLAnchorElement>(`a.ref[data-ref="${target.module_id}"]`)!;
    expect(link).toHaveTextContent(`${target.module_id} · T9`);
    expect(link.getAttribute("href")).toContain(`tab=${target.route_node_id}`);
    expect(link.getAttribute("href")).toContain("#register-T9");
    expect(view.querySelector('span.ref[data-ref="CP-99"]')).toHaveTextContent("CP-99");
  });

  test("an address naming a register opens it in the module's appendix", () => {
    const rows = ["| FY24 | 1 |", "| FY25 | 2 |"];
    const handoff = {
      ...complete.body.handoffs[0]!,
      model_analysis: [
        "## Analysis",
        "### View",
        "Prose.",
        "### Analytical appendix — complete canonical registers",
        "#### B2 — EBITDA walk",
        "| Period | Value |",
        "| --- | --- |",
        ...rows,
        "#### B3 — Build",
        "| Period | Value |",
        "| --- | --- |",
        ...rows,
      ].join("\n"),
    };
    const { container } = render(
      <MemoryRouter initialEntries={["/analysis/#register-B3"]}>
        <AnalysisSection
          document={{ ...complete, body: { ...complete.body, handoffs: [handoff] } }}
          tab={handoff.route_node_id}
        />
      </MemoryRouter>,
    );
    const opened = [...container.querySelectorAll('[data-register-open][aria-expanded="true"]')];
    expect(opened.map((button) => button.textContent)).toEqual(["B3Build2 rows"]);
  });

  test("a module with no appendix register opens on its audit; asked for, the appendix says so", () => {
    const { container } = mountAt(complete, "CP-4");
    expect(container.querySelector('[data-depth-tab="appendix"]')).toHaveTextContent("0");
    expect(container.querySelector('[data-depth-tab="audit"]')).toHaveAttribute(
      "aria-selected",
      "true",
    );
    openTab(container, "appendix");
    expect(container.querySelector('[data-depth-panel="appendix"]')).toHaveTextContent(
      "This module's text carries no appendix register.",
    );
  });

  test("a screening-only handoff shows the screening notice; a full-committee one does not", () => {
    const screening: HandoffView = {
      ...complete.body.handoffs[0]!,
      decision_scope: "SCREENING_ONLY",
      screening_only: true,
    };
    const document: AnalysisDocument = {
      ...complete,
      body: { ...complete.body, handoffs: [screening] },
    };
    const { container } = mount(document);
    const card = container.querySelector(`[data-handoff="${screening.module_id}"]`)!;
    expect(card.querySelector("[data-screening-only]")).toHaveTextContent(
      "Screening only: a screen, not committee clearance.",
    );
    // The fixture's own handoffs are all full-committee: none carries the notice.
    const { container: full } = mount(complete);
    expect(full.querySelector("[data-screening-only]")).toBeNull();
  });

  test("a fact whose record holds no line is labelled a quote, compact and never marked", () => {
    const { container } = mountAt(complete, "CP-1");
    openTab(container, "audit");
    const facts = container.querySelectorAll("[data-source-facts] [data-citation]");
    const quoteOnly = complete.body.handoffs.find((h) => h.module_id === "CP-1")!.source_facts[1]!;
    expect(quoteOnly.line.recorded).toBe(false);
    const fact = facts[1]!;
    expect(fact.querySelector("[data-line-not-recorded]")).toHaveTextContent(
      "Quote (source line not recorded)",
    );
    expect(fact.querySelector("[data-fact-excerpt] q")!.textContent).toBe(
      clampExcerpt(quoteOnly.matched_text),
    );
    expect(fact.querySelector("blockquote, mark")).toBeNull();
  });

  test("source facts name the file, page, the excerpt compact and withdrawn state", () => {
    const { container } = mountAt(complete, "CP-4");
    openTab(container, "audit");
    const fact = container.querySelector("[data-source-facts] [data-citation]")!;
    const withdrawn = complete.body.handoffs.find((h) => h.module_id === "CP-4")!.source_facts[0]!;
    expect(fact).toHaveTextContent(withdrawn.filename);
    expect(fact).toHaveTextContent(`p.${withdrawn.page}`);
    expect(fact).toHaveTextContent(withdrawn.matched_text);
    // D107: compact -- the excerpt alone, about one line; the whole source
    // line, its excerpt marked, is the source drawer's to show.
    const { before, excerpt, after } = withdrawn.line;
    expect(before).not.toBe("");
    expect(fact.querySelector("[data-fact-excerpt] q")!.textContent).toBe(
      clampExcerpt(withdrawn.matched_text),
    );
    expect(fact.textContent).not.toContain(before + excerpt + after);
    expect(fact.querySelector("blockquote, mark")).toBeNull();
    expect(fact.querySelector("[data-line-not-recorded]")).toBeNull();
    expect(fact.getAttribute("data-withdrawn")).toBe("true");
    expect(fact).toHaveTextContent(stamp(withdrawn.withdrawn_at!));

    const { container: cp0 } = mountAt(complete, "CP-0");
    openTab(cp0, "audit");
    const notWithdrawn = cp0.querySelector("[data-source-facts] [data-citation]")!;
    expect(notWithdrawn.getAttribute("data-withdrawn")).toBe("false");
  });

  test("a handoff with no citation says so rather than rendering nothing", () => {
    const { container } = mountAt(complete, "CP-5");
    openTab(container, "audit");
    expect(container.querySelector("[data-source-facts]")).toHaveTextContent(
      "No citation is carried on this handoff.",
    );
  });

  test("host_calculation keeps LITE as NONE and labels a host CP-CF forecast", () => {
    for (const handoff of complete.body.handoffs) {
      expect(handoff.host_calculation).toBe("NONE");
      const { container, unmount } = mountAt(complete, handoff.module_id);
      expect(container.querySelector("[data-host-calculation]")).toHaveTextContent(
        "Deterministic calculations: none performed by the host",
      );
      unmount();
    }
    const forecast: HandoffView = {
      ...complete.body.handoffs[0]!,
      module_id: "CP-CF",
      module_name: "Cash-flow forecast",
      host_calculation: "CP_CF_FORECAST",
    };
    const { container: forecastPage } = mount({
      ...complete,
      body: { ...complete.body, handoffs: [forecast] },
    });
    expect(forecastPage.querySelector("[data-host-calculation]")).toHaveTextContent(
      "Deterministic calculations: CP-CF forecast projection performed by the host",
    );
  });

  test("qa status, committee status, decision scope and confidence are all shown", () => {
    const { container } = mountAt(complete, "CP-1C");
    const cp1c = complete.body.handoffs.find((h) => h.module_id === "CP-1C")!;
    const card = container.querySelector('[data-handoff="CP-1C"]')!;
    expect(card.querySelector("[data-qa-status]")).toHaveTextContent(cp1c.qa_status);
    expect(card.querySelector("[data-committee-status]")).toHaveTextContent(cp1c.committee_status);
    expect(card.querySelector("[data-committee-status]")).toHaveTextContent(
      words(cp1c.decision_scope),
    );
    expect(card.querySelector("[data-confidence]")).toHaveTextContent(
      String(cp1c.confidence_score),
    );
    expect(card.querySelector("[data-confidence]")).toHaveTextContent(words(cp1c.confidence_band));
  });

  test("validation warnings render only when carried", () => {
    expect(
      mountAt(complete, "CP-1C").container.querySelector("[data-validation-warnings]"),
    ).not.toBeNull();
    expect(
      mountAt(complete, "CP-0").container.querySelector("[data-validation-warnings]"),
    ).toBeNull();
  });

  test("the modules are the section's tabs, in route order, each with its state", () => {
    const tabs = composeChrome("analysis", complete).tabs;
    expect(tabs.map((tab) => tab.label)).toEqual(complete.body.handoffs.map((h) => h.module_id));
    expect(tabs.find((tab) => tab.label === "CP-1C")).toMatchObject({
      severity: "WARNING",
      cp: "Peer benchmark",
    });
    expect(tabs.filter((tab) => tab.opens).map((tab) => tab.label)).toEqual(["CP-7"]);
  });

  test("a module is named by the bundle catalog's name on the wire, its id once when that is all (N61)", () => {
    const cp1c = complete.body.handoffs.find((h) => h.module_id === "CP-1C")!;
    expect(cp1c.module_name).toBe("Peer benchmark");
    const { container } = mountAt(complete, "CP-1C");
    expect(container.querySelector("#module-heading")).toHaveTextContent("Peer benchmark");
    const unnamed = parseAnalysisDocument({
      ...complete,
      body: {
        ...complete.body,
        handoffs: complete.body.handoffs.map((h) =>
          h === cp1c ? { ...h, module_name: h.module_id } : h,
        ),
      },
    });
    const tab = composeChrome("analysis", unnamed).tabs.find((entry) => entry.label === "CP-1C");
    expect(tab?.cp).toBeNull();
  });

  test("test_handoffSeverity_and_conclusionOf", () => {
    const cp1c = complete.body.handoffs.find((h) => h.module_id === "CP-1C")!;
    // In the bundle's terms (D71): a validation warning is a warning; QA
    // Restricted, a stated limitation or a screening-only scope is carried
    // forward, RESTRICTED's ring; a QA word the bundle does not declare is a
    // warning; one that did not pass is critical.
    expect(handoffSeverity(cp1c)).toBe("WARNING");
    expect(handoffSeverity({ ...cp1c, validation_warnings: [] })).toBe("RESTRICTED");
    const passed = complete.body.handoffs[0]!;
    expect(handoffSeverity(passed)).toBe("SUCCESS");
    expect(handoffSeverity({ ...passed, limitation_flags: ["LIMITED_HISTORY"] })).toBe(
      "RESTRICTED",
    );
    expect(handoffSeverity({ ...passed, screening_only: true })).toBe("RESTRICTED");
    expect(handoffSeverity({ ...passed, validation_warnings: ["x"] })).toBe("WARNING");
    expect(handoffSeverity({ ...passed, qa_status: "Ready" })).toBe("WARNING");
    expect(handoffSeverity({ ...cp1c, qa_status: "Failed" })).toBe("CRITICAL");
    expect(conclusionOf(complete.body.handoffs)?.module_id).toBe("CP-7");
    expect(conclusionOf([])).toBeNull();
  });

  test("unaccepted route nodes are named as pending, with the state the route left them in", () => {
    const { container } = mount(partial);
    expect(partial.status).toBe("partial");
    expect(partial.notes).toContain("HANDOFFS_PENDING");
    const rows = [...container.querySelectorAll("[data-pending-node]")];
    expect(rows).toHaveLength(partial.body.pending.length);
    partial.body.pending.forEach((node, index) => {
      const row = rows[index]!;
      expect(row.getAttribute("data-pending-node")).toBe(node.module_id);
      expect(row.getAttribute("data-state")).toBe(node.state);
      expect(row).toHaveTextContent(node.state);
    });
    // A pending node is never also a handoff.
    const handoffIds = new Set(partial.body.handoffs.map((h) => h.module_id));
    for (const node of partial.body.pending) expect(handoffIds.has(node.module_id)).toBe(false);
  });

  test("test_the_pending_list_names_the_node_whose_verdict_ended_the_run", () => {
    // A Blocked verdict accepts nothing, so the node that answered sits in the
    // same list as the nodes that never started. Told apart, or the page says
    // the opposite of what happened about the one node that did run.
    const [answered, ...never] = partial.body.pending;
    const blocked: AnalysisDocument = {
      ...partial,
      body: {
        ...partial.body,
        displayed_run_status: "BLOCKED",
        blocked_by: {
          route_node_id: answered!.route_node_id,
          module_id: answered!.module_id,
          attempt_id: "00000000-0000-4000-8000-0000000000c1",
          quotes_recorded: false,
          quotes_refusal: null,
          verified: [],
          unverified: [],
        },
      },
    };
    const { container } = mount(blocked);

    const panel = container.querySelector("[data-pending]")!;
    expect(panel).toHaveAttribute("data-run-ended", "yes");
    expect(panel).toHaveTextContent(`the run ended BLOCKED on ${answered!.module_id}`);
    const named = container.querySelector(`[data-pending-node="${answered!.module_id}"]`)!;
    expect(named).toHaveAttribute("data-blocking", "yes");
    expect(named).toHaveTextContent("its verdict ended the run");
    for (const node of never) {
      const row = container.querySelector(`[data-pending-node="${node.module_id}"]`)!;
      expect(row).toHaveAttribute("data-blocking", "no");
      expect(row).not.toHaveTextContent("its verdict ended the run");
    }
  });

  test("a run still working names no blocking node", () => {
    const { container } = mount(partial);
    const rows = [...container.querySelectorAll("[data-pending-node]")];
    expect(rows.length).toBeGreaterThan(0);
    for (const row of rows) expect(row).toHaveAttribute("data-blocking", "no");
  });

  test("a run with nothing pending says every pinned node has been accepted", () => {
    const { container } = mount(complete);
    expect(complete.body.pending).toEqual([]);
    expect(container.querySelector("[data-pending]")).toHaveTextContent(
      "Every pinned node on this run has been accepted.",
    );
  });

  test("displayed and latest run are named separately", () => {
    const superseded: AnalysisDocument = {
      ...complete,
      body: { ...complete.body, latest_run_id: "00000000-0000-4000-8000-0000000000b2" },
    };
    const { container } = mount(superseded);
    const stale = container.querySelector("[data-stale-run]");
    expect(stale).not.toBeNull();
    expect(stale).toHaveTextContent(superseded.body.displayed_run_id!);
    expect(stale).toHaveTextContent(superseded.body.latest_run_id!);

    const { container: current } = mount(complete);
    expect(current.querySelector("[data-stale-run]")).toBeNull();
  });

  test("an observed-empty analysis (no handoff, nothing pending) renders no card", () => {
    const empty: AnalysisDocument = {
      ...complete,
      body: {
        case_id: complete.body.case_id,
        latest_run_id: null,
        displayed_run_id: null,
        subject: null,
        displayed_run_status: null,
        blocked_by: null,
        handoffs: [],
        pending: [],
      },
      observed_empty: true,
    };
    const { container } = mount(empty);
    expect(container.querySelectorAll("[data-handoff]")).toHaveLength(0);
    expect(container).toHaveTextContent("No handoff has been accepted on this run yet.");
  });
});

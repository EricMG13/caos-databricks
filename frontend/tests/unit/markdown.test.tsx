// The model's Markdown in the page's own elements (D60): `readMarkdown` and
// `readInline` hold `caos/deliverable/render.py`'s grammar rule for rule, the
// renderer draws only that element set, and a module's text is split into the
// places every module shares (`moduleParts`, `shapeOf`, `placeOf`).
import { readFileSync, readdirSync } from "node:fs";
import { resolve } from "node:path";
import { render, renderHook } from "@testing-library/react";
import { plainHead, plainName } from "@/ds/format";
import { readInline, readMarkdown, readRefs, type Block } from "@/ds/markdown";
import { Markdown } from "@/ds/ModelMarkdown";
import { keyFigures } from "@/sections/analysis/figures";
import { PROSE_SHOWN, registerOfHash, useModuleParts } from "@/sections/analysis/module";
import {
  APPENDIX_GROUPS,
  AUDIT_SECTIONS,
  CONTRARY,
  moduleParts,
  openingOf,
  placeOf,
  registerHeading,
  shapeOf,
  splitLede,
  STABLE_TABLES,
} from "@/sections/analysis/parts";
import { parseAnalysisDocument } from "@/wire/v1";

const md = (...lines: string[]) => lines.join("\n");

describe("readMarkdown holds render.py's grammar", () => {
  test("headings, paragraphs, quotes, rules and code fences with both labels", () => {
    const blocks = readMarkdown(
      md(
        "### Credit view",
        "",
        "One line",
        "and its continuation.",
        "",
        "> quoted",
        "> twice",
        "",
        "---",
        "",
        "```caos-forecast-v1",
        '{"a": 1}',
        "``` tail",
      ),
    )!;
    expect(blocks.map((block) => block.kind)).toEqual([
      "heading",
      "paragraph",
      "quote",
      "rule",
      "code",
    ]);
    expect(blocks[0]).toEqual({ kind: "heading", level: 3, text: "Credit view" });
    expect(blocks[1]).toEqual({ kind: "paragraph", text: "One line and its continuation." });
    expect(blocks[2]).toEqual({ kind: "quote", text: "quoted twice" });
    expect(blocks[4]).toEqual({
      kind: "code",
      info: "caos-forecast-v1",
      text: '{"a": 1}',
      tail: "tail",
    });
  });

  test("front matter and comments are kept as written, never dropped", () => {
    const blocks = readMarkdown(md("---", "module_id: CP-1", "---", "<!-- table-id: cp1.x -->"))!;
    expect(blocks).toEqual([
      { kind: "front", text: "module_id: CP-1" },
      { kind: "comment", text: "<!-- table-id: cp1.x -->" },
    ]);
  });

  test("a list nests by indent, keeps a written start, and never renumbers a gap", () => {
    const [nested] = readMarkdown(md("- a", "  - b", "    1. c", "- d"))! as Extract<
      Block,
      { kind: "list" }
    >[];
    expect(nested!.list.items.map((item) => item.text)).toEqual(["a", "d"]);
    expect(nested!.list.items[0]!.lists[0]!.items[0]!.lists[0]!.ordered).toBe(true);
    const [started] = readMarkdown(md("3. x", "4. y"))! as Extract<Block, { kind: "list" }>[];
    expect([started!.list.start, started!.list.literal]).toEqual([3, false]);
    // 7 then 9: an <ol start=7> would draw an 8 nobody wrote.
    const [gap] = readMarkdown(md("7. x", "9. y"))! as Extract<Block, { kind: "list" }>[];
    expect(gap!.list.literal).toBe(true);
    expect(gap!.list.items.map((item) => item.marker)).toEqual(["7.", "9."]);
  });

  test("a table is its header and rows, as written", () => {
    const [table] = readMarkdown(md("| Metric | Value |", "| --- | ---: |", "| EBITDA | 562 |"))!;
    expect(table).toEqual({
      kind: "table",
      table: { head: ["Metric", "Value"], rows: [["EBITDA", "562"]] },
    });
    // A pipe in prose above a bare rule is not a one-column table (render.py's
    // DELIMITER note): the rule joins the paragraph, as the host's does.
    expect(readMarkdown(md("a | b", "---"))).toEqual([{ kind: "paragraph", text: "a | b ---" }]);
  });

  test("refuses whatever the host refuses: no faithful drawing exists", () => {
    expect(readMarkdown(md("```", "never closed"))).toBeNull();
    expect(readMarkdown(md("<!-- never closed"))).toBeNull();
    expect(readMarkdown(md("---", "front matter never closed"))).toBeNull();
    expect(readMarkdown(md("| a | b |", "| - | - |", "| only one |"))).toBeNull();
    expect(readMarkdown(md("- 1", " - 2", "  - 3", "   - 4", "    - 5"))).toBeNull();
    expect(readMarkdown(md("- 1", " - 2", "  - 3", "   - 4"))).not.toBeNull();
  });
});

describe("readInline holds render.py's _inline", () => {
  test("strong, emphasis and code, each where its flanking rule says", () => {
    expect(readInline("a **b** c")).toEqual(["a ", { mark: "strong", children: ["b"] }, " c"]);
    expect(readInline("an *x* and `y`")).toEqual([
      "an ",
      { mark: "em", children: ["x"] },
      " and ",
      { mark: "code", children: ["y"] },
    ]);
    // Arithmetic is not emphasis.
    expect(readInline("2 * 3 * 4")).toEqual(["2 * 3 * 4"]);
  });

  test("a code span is literal, and a delimiter that would close out of order is text", () => {
    expect(readInline("`a*b*c`")).toEqual([{ mark: "code", children: ["a*b*c"] }]);
    expect(readInline("*a **b* c**")).toEqual(["*a **b* c**"]);
    expect(readInline("**never closed")).toEqual(["**never closed"]);
  });
});

describe("the renderer draws only the element set, and model markup as text", () => {
  test("hostile markup is text; figures align; status words carry their shape", () => {
    const { container } = render(
      <Markdown
        text={md(
          "#### Heading <img src=x onerror=alert(1)>",
          "",
          '<script>window.pwned = 1</script> and <a href="javascript:x">a link</a>',
          "",
          "| Test | Headroom | Status | Severity |",
          "| --- | --- | --- | --- |",
          "| Net leverage | 1.40x | PASS | Low |",
          "| Coverage | (0.2x) | FAIL | High |",
        )}
        base={3}
        label="Sample"
      />,
    );
    expect(container.querySelector("img, script, a")).toBeNull();
    expect(container.textContent).toContain("<script>window.pwned = 1</script>");
    // `####` alone under a card's h3 closes up to h4 and keeps its level.
    expect(container.querySelector("h4")).toHaveAttribute("data-level", "4");
    const cells = container.querySelectorAll("tbody tr:first-child td");
    // A figure column is mono and right aligned; a text column is not.
    expect(cells[0]).toHaveClass("l");
    expect(cells[1]).not.toHaveClass("l");
    expect(cells[2]!.querySelector(".tag.ok .glyph.ok")).not.toBeNull();
    expect(container.querySelector("tbody tr:last-child .tag.crit")).toHaveTextContent("FAIL");
    // Severity words carry a tone only under a severity heading.
    expect(
      container.querySelector("tbody tr:last-child td:last-child .tag.crit"),
    ).toHaveTextContent("High");
  });

  test("a text the host would refuse is shown as written, with why", () => {
    const { container } = render(<Markdown text={md("```", "open")} base={2} label="Sample" />);
    expect(container.querySelector("[data-markdown='as-written'] pre")).toHaveTextContent("open");
  });
});

describe("a module's text in the places every module shares", () => {
  const canonical = md(
    "---",
    "module_id: CP-4",
    "---",
    "## Audit Summary",
    "Scope stated.",
    "## Analysis",
    "### Creditor implication",
    "The package protects creditors.",
    "1. **Controlling documents.** The indenture.",
    "### Risks and monitoring",
    "- **Springing test.** Tested past 35% drawn.",
    "- **Leakage.** Baskets are wide.",
    "### Analytical appendix — complete canonical registers",
    "#### T4C.4 — Covenant tests",
    "| Test | Test Type | Threshold | Current Basis | Formula | Headroom | Status |",
    "| --- | --- | --- | --- | --- | --- | --- |",
    "| Net leverage | Maintenance | 3.50x | 2.10x | f | 1.40x | Pass |",
    "#### T4.13 — Gaps",
    "| Gap | Missing Document / Clause / Schedule | Why It Matters | Impact on Output | Required Follow-Up |",
    "| --- | --- | --- | --- | --- |",
    "| Intercreditor | missing | order inferred | medium | request |",
    "## QA Validation",
    "All checks pass.",
  );

  test("the opening leads, the rest reads after it, registers by shape, audit in order", () => {
    const parts = moduleParts(readMarkdown(canonical)!);
    expect(parts.front).toBe("module_id: CP-4");
    expect(parts.lead!.title).toBe("Creditor implication");
    expect(parts.reader.map((part) => part.title)).toEqual(["Risks and monitoring"]);
    expect(parts.registers.map((register) => [register.id, register.shape])).toEqual([
      ["T4C.4", "tests"],
      ["T4.13", "gaps"],
    ]);
    expect(parts.audit.map((part) => part.title)).toEqual(["Audit summary", "QA validation"]);
    expect(AUDIT_SECTIONS.indexOf("Audit summary")).toBeLessThan(
      AUDIT_SECTIONS.indexOf("QA validation"),
    );
    expect(placeOf("CP-4", parts.registers[1]!)).toBe("Gaps and conflicts");
    expect(placeOf("CP-4", parts.registers[0]!)).toBe("appendix");
    // Every shape a register can take has a group in the appendix.
    const grouped = APPENDIX_GROUPS.flatMap((group) => group.shapes);
    expect(grouped).toContain("tests");
  });

  test("a text without the six H2s is read as its analysis, its tagged tables as registers", () => {
    const parts = moduleParts(
      readMarkdown(
        md(
          "## Normalised financials",
          "Prose.",
          "<!-- table-id: cp1.x -->",
          "| a | b |",
          "| - | - |",
          "| 1 | 2 |",
        ),
      )!,
    );
    expect(parts.lead!.title).toBe("Normalised financials");
    expect(parts.registers.map((register) => register.id)).toEqual(["cp1.x"]);
  });

  test("register headings and shapes read the methodology's own ids and columns", () => {
    expect(registerHeading("T4C.4 — Covenant headroom")).toEqual({
      id: "T4C.4",
      title: "Covenant headroom",
    });
    expect(registerHeading("TL40.2: topics")).toEqual({ id: "TL40.2", title: "topics" });
    expect(registerHeading("PD effect")).toEqual({ id: null, title: "PD effect" });
    expect(shapeOf("", ["Legal Topic", "Supported Fact", "Risk Mechanic", "PD Effect"])).toBe(
      "findings",
    );
    expect(shapeOf("", ["source_document_id", "source_document_name", "period"])).toBe("sources");
    expect(shapeOf("", ["Severity", "Module", "Issue"])).toBe("qa");
    expect(shapeOf("", ["Step", "Amount", "Basis", "Cumulative EBITDA"])).toBe("bridge");
    expect(shapeOf("", ["Line Item", "Period 1…N"])).toBe("series");
    expect(shapeOf("", ["Date / window", "Event", "Status"])).toBe("timeline");
    expect(shapeOf("", ["Bull Claim Attacked", "Bear Counter-Evidence"])).toBe("debate");
    expect(shapeOf("", ["anything", "else"])).toBe("table");
  });

  test("every table the bundle tags is placed by its id, under its schema reference's name", () => {
    // Every `<!-- table-id: -->` the methodology's Markdown declares.
    const declared = new Set<string>();
    const walk = (dir: string) => {
      for (const entry of readdirSync(dir, { withFileTypes: true })) {
        const path = resolve(dir, entry.name);
        if (entry.isDirectory()) walk(path);
        else if (entry.name.endsWith(".md")) {
          for (const match of readFileSync(path, "utf8").matchAll(/table-id:\s*([a-z0-9_.-]+)/g)) {
            declared.add(match[1]!);
          }
        }
      }
    };
    walk(resolve(process.cwd(), "..", "vendor", "deploy-v"));
    expect(declared.size).toBeGreaterThanOrEqual(22);
    const group = (shape: string) =>
      APPENDIX_GROUPS.find((entry) => entry.shapes.some((each) => each === shape))!.name;
    for (const id of declared) {
      const stable = STABLE_TABLES[id];
      expect(stable, id).toBeDefined();
      expect(stable!.shape, id).not.toBe("table");
      // Wherever it is placed -- the lead, an audit section, or a named
      // appendix group -- it is never Unsorted.
      const register = { id, title: stable!.title, notes: [], table: { head: [], rows: [] } };
      if (placeOf("CP-1", { ...register, shape: stable!.shape }) === "appendix") {
        expect(group(stable!.shape), id).not.toBe("Unsorted");
      }
    }
    // The two the columns misfiled: `source_definition` read as a definition,
    // and a KPI schedule matched no rule at all.
    const tagged = (id: string, head: string) =>
      moduleParts(
        readMarkdown(md(`<!-- table-id: ${id} -->`, `| ${head} |`, "| - | - |", "| a | b |"))!,
      ).registers[0]!;
    const bridge = tagged("cp1.adjusted_ebitda_bridge", "addback_id | source_definition");
    expect([bridge.title, group(bridge.shape)]).toEqual(["Adjusted EBITDA bridge", "Financials"]);
    const kpis = tagged("cp1.operating_kpi_schedule", "kpi_id | kpi_label");
    expect([kpis.title, group(kpis.shape)]).toEqual(["Operating KPIs", "Financials"]);
    // What no rule recognises is last, and called what it is.
    expect(APPENDIX_GROUPS.at(-1)!.name).toBe("Unsorted");
  });

  test("a deployed module's own headings land in the same places as the canon's", () => {
    // As a Copilot run of Deploy V writes it: an H1 title, "Module Result" for
    // the audit summary, bold-line register labels with one-letter ids, an
    // appendix as its own H2, and "QA & Governance".
    const parts = moduleParts(
      readMarkdown(
        md(
          "# CP-1B — EarningsDelta — Issuer",
          "## Module Result",
          "**Result: PASS.**",
          "## Analysis",
          "### Conclusion-first read-through",
          "Prose.",
          "## Analytical appendix — variance bridges (B1–B8)",
          "**B2 — Consolidated EBITDA walk — LTM Dec-25 → LTM Mar-26**",
          "",
          "| Line ($m) | LTM Dec-25 | LTM Mar-26 |",
          "| --- | --- | --- |",
          "| Reported EBITDA | 190 | 189 |",
          "#### T7 — Gaps & conflicts log",
          "| ID | Type | Detail |",
          "| --- | --- | --- |",
          "| G1 | Coverage | license |",
          "## QA & Governance",
          "- Lineage matched.",
        ),
      )!,
    );
    expect(parts.lead!.title).toBe("Conclusion-first read-through");
    expect(parts.reader).toEqual([]);
    expect(parts.audit.map((part) => part.title)).toEqual(["Audit summary", "QA validation"]);
    expect(parts.registers.map((r) => [r.id, r.shape])).toEqual([
      ["B2", "bridge"],
      ["T7", "gaps"],
    ]);
    expect(shapeOf("A4 Balance sheet", ["Line", "Dec-24", "Mar-25"])).toBe("series");
    // A sustainability-linked ratchet's spread effect is a trigger, not a market level.
    expect(
      shapeOf("", ["Instrument", "KPI", "SPT + Test Date", "Ratchet", "Expected Spread Effect"]),
    ).toBe("triggers");
    expect(shapeOf("", ["Security_ID", "Spread", "Price"])).toBe("market");
  });

  test("an appendix written inside another section is the appendix; a section before Analysis leads", () => {
    // As a newer Deploy V sample run wrote it: the appendix heading under
    // `## Evidence Trace`, and CP-3's recommendation as an H2 before Analysis.
    const parts = moduleParts(
      readMarkdown(
        md(
          "## Recommendation",
          "Requires More Work, with a market preference for Y.",
          "## Analysis",
          "### Fundamental credit profile",
          "Stretched.",
          "## Evidence Trace",
          "Primary evidence first.",
          "### Analytical appendix — complete canonical registers",
          "#### T3.5 Relative Value Table",
          "| Security | Market Level |",
          "| --- | --- |",
          "| Y | 86.88 |",
          "## QA Validation",
          "- Identity: PASS.",
        ),
      )!,
    );
    expect(parts.lead!.title).toBe("Recommendation");
    expect(parts.reader.map((part) => part.title)).toEqual(["Fundamental credit profile"]);
    expect(parts.registers.map((register) => register.id)).toEqual(["T3.5"]);
    const trace = parts.audit.find((part) => part.title === "Evidence trace")!;
    expect(trace.blocks).toEqual([{ kind: "paragraph", text: "Primary evidence first." }]);
  });

  test("module references are picked out of a line; anything else stays as written", () => {
    expect(readRefs("EBITDA fell. [CP-1B B2/B5]")).toEqual([
      "EBITDA fell. ",
      {
        text: "[CP-1B B2/B5]",
        refs: [
          { module: "CP-1B", register: "B2", note: null },
          { module: "CP-1B", register: "B5", note: null },
        ],
      },
    ]);
    const [, many] = readRefs("x [CP-1 / CP-1C T4.10; CP-2A calc]") as [
      string,
      { refs: unknown[] },
    ];
    expect(many.refs).toEqual([
      { module: "CP-1", register: null, note: null },
      { module: "CP-1C", register: "T4.10", note: null },
      { module: "CP-2A", register: null, note: "calc" },
    ]);
    // Not a reference: a file name, an external source, a gap label.
    for (const text of [
      "[RatingsDirect_Jan-21-2026.pdf]",
      "[external: CoreWeave]",
      "[Insufficient Information]",
    ]) {
      expect(readRefs(text)).toEqual([text]);
    }
  });

  test("the opening reads in the canon's order: first sentence, the rest, the drivers", () => {
    expect(
      splitLede(
        "The credit is **stable, not strong, and slow to delever.** Cash builds. More follows.",
      ),
    ).toEqual({
      lede: "The credit is **stable, not strong, and slow to delever.**",
      continuation: "Cash builds. More follows.",
    });
    // No sentence ends at an abbreviation or an initial.
    expect(
      splitLede("Leverage rose vs. the prior year on the J. Crew blocker read. Cash builds.").lede,
    ).toBe("Leverage rose vs. the prior year on the J. Crew blocker read.");
    const opening = openingOf({
      title: "Credit view",
      blocks: readMarkdown(
        md(
          "A single first-lien LBO whose credit is defined by leverage. It delevers slowly.",
          "",
          "Three facts govern:",
          "",
          "1. **Leverage is a spread.** 4.0x vs 7.3x. [CP-1]",
          "2. **Deleveraging is slow.** ~22% conversion.",
          "",
          "Net: grow or refinance wide.",
        ),
      )!,
    });
    expect(opening.lede).toBe("A single first-lien LBO whose credit is defined by leverage.");
    expect(opening.continuation).toBe("It delevers slowly.");
    expect(opening.drivers!.intro).toBe("Three facts govern:");
    expect(opening.drivers!.items.map((item) => item.claim)).toEqual([
      "Leverage is a spread.",
      "Deleveraging is slow.",
    ]);
    expect(opening.rest).toEqual([{ kind: "paragraph", text: "Net: grow or refinance wide." }]);
    // A list whose items do not all open in bold stays in the text.
    const plain = openingOf({
      title: "",
      blocks: readMarkdown(md("View.", "", "1. one", "2. two"))!,
    });
    expect([plain.drivers, plain.rest.length]).toEqual([null, 1]);
    expect(CONTRARY.test("Strongest contrary view (and what would make it win)")).toBe(true);
    expect(CONTRARY.test("Risks and monitoring")).toBe(false);
    // CP-6's debate is its analysis, not an argument against it.
    expect(CONTRARY.test("Bull case")).toBe(false);
    // An address that names no decodable register opens none, and never throws.
    expect(registerOfHash("#register-T2H.4")).toBe("T2H.4");
    expect(registerOfHash("#register-%E0%A4%A")).toBeNull();
    expect(registerOfHash("#top")).toBeNull();
  });

  test("a column head the model wrote as an identifier reads in words", () => {
    expect(plainHead("period_id")).toBe("Period ID");
    expect(plainHead("YOY_SAME_QUARTER")).toBe("YoY same quarter");
    expect(plainHead("cp1b_comparison_value")).toBe("CP-1B comparison value");
    expect(plainHead("status")).toBe("Status");
    expect(plainHead("Credit implication")).toBeNull();
    expect(plainHead("EBITDA")).toBeNull();
    expect(plainName("adjusted_ebitda")).toBe("Adjusted EBITDA");
    const { container } = render(
      <Markdown
        text={md("| period_id | Value |", "| - | - |", "| FY24 | 1 |")}
        base={3}
        label="t"
      />,
    );
    const head = container.querySelector("th span[title]")!;
    expect([head.textContent, head.getAttribute("title")]).toEqual(["Period ID", "period_id"]);
  });

  test("CP-0's and CP-5's conclusions lead, though their shape is audit's", () => {
    const readiness = {
      id: "T8",
      title: "",
      notes: [],
      table: { head: [], rows: [] },
      shape: "readiness" as const,
    };
    expect(placeOf("CP-0", readiness)).toBe("lead");
    expect(placeOf("CP-1", { ...readiness, id: "T4.13" })).toBe("QA validation");
  });
});

describe("the module's figures and text as the section reads them", () => {
  const document = parseAnalysisDocument(
    JSON.parse(readFileSync(resolve(process.cwd(), "fixtures", "analysis.json"), "utf8")),
  );
  const cp1b = document.body.handoffs.find((handoff) => handoff.module_id === "CP-1B")!;

  test("keyFigures prints CP-1B's typed comparator as served, never from its prose", () => {
    const figures = keyFigures(cp1b.tables);
    expect(figures[0]).toMatchObject({ label: "Revenue", value: "6,112", reference: "5,294" });
    expect(figures[0]!.change.value).toBe("15.45");
    expect(figures.find((figure) => figure.label === "FCF")!.change.value).toBeNull();
    expect(keyFigures([])).toEqual([]);
    // A metric compared over two periods is told apart by its period.
    const twice = {
      ...cp1b.tables.find((t) => t.table_id === "cp1b.model_comparator_register")!,
    };
    const period = twice.columns.indexOf("current_period_id");
    const percent = twice.columns.indexOf("percentage_change");
    const row = twice.rows[0]!;
    const again = row.map((cell, index) =>
      index === period
        ? { text: "H1_2026", value: null }
        : index === percent
          ? { text: "(5.1%) reported", value: null }
          : cell,
    );
    twice.rows = [row, again];
    const [first, second] = keyFigures([twice]);
    expect(first!.label).toBe(`Revenue · ${plainName(row[period]!.text)}`);
    expect(second!.label).toBe("Revenue · H1 2026");
    // A change the host could not type prints as written, never as a figure.
    expect(second!.change).toEqual({ value: null, reason: "(5.1%) reported" });
  });

  test("useModuleParts reads once, and declines what it will not format", () => {
    const { result } = renderHook(() => useModuleParts(cp1b));
    expect(result.current!.parts.lead!.title).toBe("Earnings delta");
    expect(result.current!.placed.map((entry) => entry.register.id)).toContain(
      "cp1b.model_comparator_register",
    );
    const long = { ...cp1b, model_analysis: "x".repeat(PROSE_SHOWN * 30) };
    expect(renderHook(() => useModuleParts(long)).result.current).toBeNull();
  });
});

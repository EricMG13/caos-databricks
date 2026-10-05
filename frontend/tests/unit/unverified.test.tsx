// D106 in the workspace: a citation the host could not anchor is shown as the
// model's own -- "unverified – page N", its claim Untraced, why in plain
// words -- apart from the host-verified source facts and never marked, never
// in the host's well, never called a source line, never opened in a drawer;
// and an anchored citation the answer's body does not carry says so.
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { fireEvent, render } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { EvidenceDrawer } from "@/evidence/EvidenceDrawer";
import { Narrative } from "@/evidence/Narrative";
import { SourceDrawer } from "@/evidence/SourceDrawer";
import { NOT_LINKED, UNVERIFIED_REASONS, unverifiedLabel } from "@/evidence/Unverified";
import { AnalysisSection, sourceNames } from "@/sections/analysis/AnalysisSection";
import { citationOf } from "@/sections/book/passport";
import { parseAnalysisDocument, type CitationView, type ReportDocument } from "@/wire/v1";

const complete = parseAnalysisDocument(
  JSON.parse(readFileSync(resolve(process.cwd(), "fixtures/analysis.json"), "utf8")),
);

function auditOf(moduleId: string) {
  const handoff = complete.body.handoffs.find((entry) => entry.module_id === moduleId)!;
  const view = render(
    <MemoryRouter>
      <AnalysisSection document={complete} tab={handoff.route_node_id} />
    </MemoryRouter>,
  );
  fireEvent.click(view.container.querySelector('[data-depth-tab="audit"]')!);
  return { ...view, handoff };
}

/** Nothing in `element` is styled or worded as host-verified. */
function neverVerified(element: Element) {
  expect(element.querySelector("mark")).toBeNull();
  expect(element.querySelector(".matched")).toBeNull();
  expect(element.textContent).not.toMatch(/host-verified|source line/i);
}

describe("unverified citations (D106)", () => {
  test("test_an_unverified_citation_is_listed_apart_labelled_and_never_marked", () => {
    const { container, handoff } = auditOf("CP-1B");
    const entry = handoff.unverified_facts[0]!;
    // The source facts say no citation was located; the unverified list is
    // its own audit part, after them.
    expect(container.querySelector("[data-source-facts]")).toHaveTextContent(
      "No citation of this handoff was located by the host",
    );
    const part = container.querySelector('[data-audit-part="Unverified citations"]')!;
    expect(part.querySelector("h3")).toHaveTextContent(
      "Unverified citations the model's own locators and quotes",
    );
    const item = part.querySelector("[data-unverified-citation]")!;
    expect(item.querySelector(".lbl")).toHaveTextContent(
      `unverified – page 14 · the model's quote · claim lineage: Untraced · not located · source ${entry.source_id}`,
    );
    // The model's markup is text: one blockquote, no element inside it.
    const quote = item.querySelector("blockquote.unverified-quote")!;
    expect(quote.textContent).toBe(entry.matched_text);
    expect(quote.children).toHaveLength(0);
    neverVerified(part);
    expect(item.querySelector("button")).toBeNull();
    // Said up front, in the module's caveats.
    expect(container.querySelector('[data-caveat="unverified"]')).toHaveTextContent(
      "1 of this module's citations was not located by the host",
    );
  });

  test("test_a_module_with_no_unverified_citation_has_no_such_part", () => {
    const { container } = auditOf("CP-0");
    expect(container.querySelector('[data-audit-part="Unverified citations"]')).toBeNull();
    expect(container.querySelector('[data-caveat="unverified"]')).toBeNull();
  });

  test("test_an_unverified_citation_is_named_by_a_located_source_file_where_known", () => {
    const names = sourceNames(complete.body.handoffs);
    const fact = complete.body.handoffs[0]!.source_facts[0]!;
    expect(names.get(fact.source_id)).toBe(fact.filename);
    expect(UNVERIFIED_REASONS.CITATION_NOT_DELIVERED).toBe("not in the delivered evidence");
    expect(unverifiedLabel({ page: 2, code: "CITATION_AMBIGUOUS" })).toBe(
      "unverified – page 2 · the model's quote · claim lineage: Untraced · ambiguous",
    );
  });

  test("test_an_anchored_citation_not_linked_to_the_answer_says_so", () => {
    const { container } = auditOf("CP-1");
    const facts = container.querySelectorAll("[data-source-facts] [data-citation]");
    expect(facts[0]!.querySelector("[data-not-linked]")).toHaveTextContent(NOT_LINKED);
    expect(facts[1]!.querySelector("[data-not-linked]")).toBeNull();

    const fact: CitationView = complete.body.handoffs[1]!.source_facts[0]!;
    expect(fact.linked).toBe(false);
    const citation = citationOf(fact, "2026-09-14T10:00:00Z");
    expect(citation.linked).toBe(false);
    render(<EvidenceDrawer citation={citation} opener={null} onClose={() => {}} />);
    expect(document.querySelector("[data-evidence-drawer] [data-not-linked]")).toHaveTextContent(
      NOT_LINKED,
    );
  });

  test("test_the_source_drawer_says_a_fact_is_not_linked", () => {
    const fact = complete.body.handoffs[1]!.source_facts[0]!;
    const opener = document.createElement("button");
    document.body.append(opener);
    const drawer = (linked: boolean) =>
      render(
        <SourceDrawer
          fact={{ ...fact, linked }}
          address={null}
          withdrawnAt={null}
          opener={opener}
          onClose={() => {}}
        />,
      );
    const { unmount } = drawer(true);
    expect(document.querySelector("[data-evidence-drawer] [data-not-linked]")).toBeNull();
    unmount();
    drawer(false);
    expect(document.querySelector("[data-evidence-drawer] [data-not-linked]")).toHaveTextContent(
      NOT_LINKED,
    );
  });

  test("test_a_narrative_figure_naming_an_unverified_citation_is_labelled_without_a_chip", () => {
    const narrative: ReportDocument["body"]["narrative"] = [
      [
        { text: "Leverage: ", figure: null, unverified: null },
        {
          text: null,
          figure: null,
          unverified: {
            route_node_id: "CP-1",
            record_sha256: "c".repeat(64),
            unverified_index: 0,
            source_id: "00000000-0000-4000-8000-0000000000a1",
            page: 9,
            matched_text: '</q><mark>3.1x</mark><script>alert("x")</script>',
            code: "CITATION_AMBIGUOUS",
          },
        },
      ],
    ];
    const { container } = render(<Narrative narrative={narrative} />);
    const figure = container.querySelector('[data-unverified-figure="CP-1"]')!;
    expect(figure.querySelector(".lbl")).toHaveTextContent(
      "unverified – page 9 · the model's quote · claim lineage: Untraced · ambiguous:",
    );
    expect(figure.querySelector("q")!.textContent).toBe(
      '</q><mark>3.1x</mark><script>alert("x")</script>',
    );
    expect(figure.querySelector("script")).toBeNull();
    expect(figure.querySelector("button")).toBeNull();
    neverVerified(figure);
  });
});

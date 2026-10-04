// D106 in the workspace: a citation the host could not anchor is shown as the
// model's own -- "unverified – page N", its claim Untraced, why in plain
// words -- apart from the host-verified source facts and never marked, never
// in the host's well, never called a source line, never opened in a drawer;
// and an anchored citation the answer's body does not carry says so.
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { resolveFact } from "@/evidence/EvidenceContext";
import { EvidenceDrawer } from "@/evidence/EvidenceDrawer";
import { Narrative } from "@/evidence/Narrative";
import { SourceDrawer } from "@/evidence/SourceDrawer";
import {
  BlockedQuotes,
  blockedRecord,
  shortExcerpt,
  NOT_LINKED,
  UNVERIFIED_REASONS,
  unverifiedLabel,
} from "@/evidence/Unverified";
import { AnalysisSection, sourceNames } from "@/sections/analysis/AnalysisSection";
import { citationOf } from "@/sections/book/passport";
import { RunSection } from "@/sections/run/RunSection";
import {
  parseAnalysisDocument,
  parseCommitteeDocument,
  parseRunSectionDocument,
  type CitationView,
  type ReportDocument,
} from "@/wire/v1";

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
            linked: true,
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

describe("the Blocked answer's quotes (owner: Show its quotes)", () => {
  const blocked = {
    route_node_id: "rn-cp-5",
    module_id: "CP-5",
    attempt_id: "00000000-0000-4000-8000-0000000000d1",
    quotes_recorded: true,
    quotes_refusal: null,
    verified: [
      {
        document_sha256: "d".repeat(64),
        source_id: "00000000-0000-4000-8000-0000000000a2",
        withdrawn_at: null,
        page: 4,
        matched_text: "<script>alert(1)</script> that revenue will grow",
        line: {
          before: "We do not believe ",
          excerpt: "<script>alert(1)</script> that revenue will grow",
          after: " next year.",
          recorded: true,
        },
        linked: false,
      },
    ],
    unverified: [
      {
        source_id: "00000000-0000-4000-8000-0000000000a1",
        page: 9,
        matched_text: "</q><mark>INJECT</mark> | **bold**",
        code: "CITATION_NOT_DELIVERED" as const,
        linked: false,
      },
    ],
  };

  test("test_each_quote_is_marked_verified_or_unverified_compactly_and_escaped", () => {
    // D107: document · page · a short excerpt; the line is the drawer's.
    const { container } = render(<BlockedQuotes blocked={blocked} />);
    const verified = container.querySelector('[data-blocked-quote="verified"]')!;
    expect(verified).toHaveTextContent(/^p\.4 Verified · sha256:dddd.* · page 4 ·/);
    expect(verified.querySelector("q")!.textContent).toBe(
      shortExcerpt(blocked.verified[0]!.matched_text),
    );
    expect(verified.querySelector("blockquote, mark, script")).toBeNull();
    expect(verified).toHaveTextContent("not linked to a statement in the answer");
    expect(
      screen.getByRole("button", { name: "Open the source of verified quote 1, page 4" }),
    ).toHaveAttribute("aria-haspopup", "dialog");
    const model = container.querySelector('[data-blocked-quote="unverified"]')!;
    expect(model.querySelector(".lbl")).toHaveTextContent(
      "unverified \u2013 page 9 · the model's quote · claim lineage: Untraced · not in the delivered evidence · not linked to a statement in the answer",
    );
    expect(model.querySelector("q")!.textContent).toBe(blocked.unverified[0]!.matched_text);
    neverVerified(model);
    expect(
      shortExcerpt("one two three four five six seven eight nine ten eleven twelve thirteen"),
    ).toBe("one two three four five six seven eight nine ten eleven twelve\u2026");
  });

  test("test_a_verified_blocked_quote_resolves_to_the_source_drawer", () => {
    // Its identity is the verdict's attempt; the drawer gets its source,
    // page and line, with no rectangle.
    const snapshot = {
      key: "analysis|c|r",
      caseId: "c",
      displayedRunId: "r",
      document: { ...complete, body: { ...complete.body, blocked_by: blocked } },
      withdrawals: new Map(),
    };
    const identity = {
      record_sha256: blockedRecord(blocked),
      source_id: blocked.verified[0]!.source_id,
      page: 4,
      index: 0,
    };
    const resolved = resolveFact(snapshot, identity)!;
    expect(resolved.fact).toMatchObject({
      source_id: blocked.verified[0]!.source_id,
      page: 4,
      line: blocked.verified[0]!.line,
      rects: [],
      linked: false,
    });
    expect(resolveFact(snapshot, { ...identity, index: 1 })).toBeNull();
    expect(resolveFact(snapshot, { ...identity, record_sha256: "blocked:other" })).toBeNull();
  });

  test("test_a_block_whose_quotes_were_not_kept_or_cannot_be_read_says_so", () => {
    const old = render(
      <BlockedQuotes
        blocked={{ ...blocked, quotes_recorded: false, verified: [], unverified: [] }}
      />,
    );
    expect(old.container.querySelector('[data-blocked-quotes="not-recorded"]')).toHaveTextContent(
      "Quotes not recorded for this block.",
    );
    const lost = render(
      <BlockedQuotes
        blocked={{
          ...blocked,
          quotes_refusal: { code: "ARTIFACT_RECORD_MISMATCH", clears: "Re-run the node." },
          verified: [],
          unverified: [],
        }}
      />,
    );
    expect(lost.container.querySelector('[data-blocked-quotes="unreadable"]')).toHaveTextContent(
      "This block's quotes could not be read (ARTIFACT_RECORD_MISMATCH).",
    );
  });

  test("test_a_committee_figure_not_linked_to_the_answer_says_so", () => {
    const committee = parseCommitteeDocument(
      JSON.parse(readFileSync(resolve(process.cwd(), "fixtures/committee-v1.json"), "utf8")),
    );
    const { container } = render(<Narrative narrative={committee.body.narrative} />);
    expect(container.querySelector("[data-figure] [data-not-linked]")).toHaveTextContent(
      "not linked to a statement in the answer",
    );
    expect(container.querySelector("[data-unverified-figure] .lbl")).toHaveTextContent(
      "· not located · not linked to a statement in the answer:",
    );
  });
});

test("test_the_run_panel_lists_a_blocked_answers_quotes", () => {
  // The demo's blocked state (the a11y gate scans it): one located quote and
  // one unverified, each compact, the located one a drawer chip.
  const blocked = parseRunSectionDocument(
    JSON.parse(readFileSync(resolve(process.cwd(), "fixtures/states/run.blocked.json"), "utf8")),
  );
  const { container } = render(
    <MemoryRouter>
      <RunSection document={blocked} tab={null} />
    </MemoryRouter>,
  );
  const quotes = container.querySelector('[data-blocked-quotes="recorded"]')!;
  expect(quotes.querySelectorAll('[data-blocked-quote="verified"] button')).toHaveLength(1);
  expect(quotes.querySelectorAll('[data-blocked-quote="unverified"]')).toHaveLength(1);
  expect(quotes.querySelector("blockquote, mark")).toBeNull();
});

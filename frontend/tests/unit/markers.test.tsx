// D107 in the workspace (owner, 4 October 2026: "Compact, source on click"):
// a module's body cites by `[C<n>]`, drawn as a chip; an anchored citation's
// chip opens the source drawer, an unverified one's is labelled and inert; a
// marker no citation holds stays text; and no surface but the drawer shows a
// citation's whole source line.
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { Markdown } from "@/ds/ModelMarkdown";
import { readMarkers } from "@/ds/markdown";
import { ArtifactMarkers, HandoffMarkers, unverifiedMarkerLabel } from "@/evidence/Markers";
import { Narrative } from "@/evidence/Narrative";
import { AnalysisSection } from "@/sections/analysis/AnalysisSection";
import { citationsOf, choiceText } from "@/sections/report/figures";
import {
  parseAnalysisDocument,
  parseCommitteeDocument,
  parseReportDocument,
  type HandoffView,
} from "@/wire/v1";

const fixture = (path: string): unknown =>
  JSON.parse(readFileSync(resolve(process.cwd(), path), "utf8"));
const complete = parseAnalysisDocument(fixture("fixtures/analysis.json"));
const handoffOf = (moduleId: string) =>
  complete.body.handoffs.find((handoff) => handoff.module_id === moduleId)!;

function drawn(handoff: HandoffView, text: string) {
  return render(
    <HandoffMarkers handoff={handoff}>
      <Markdown text={text} base={2} label="Analysis" />
    </HandoffMarkers>,
  ).container;
}

/** A handoff whose two source facts are [C1] and [C2] and whose unverified
    citation is [C3]. */
function marked(): HandoffView {
  const cp0 = handoffOf("CP-0");
  const fact = cp0.source_facts[0]!;
  return {
    ...cp0,
    source_facts: [
      { ...fact, marker: 1 },
      { ...fact, page: 2, marker: 2, filename: '<img src=x onerror="window.pwned=1">.htm' },
    ],
    unverified_facts: [{ ...handoffOf("CP-1B").unverified_facts[0]!, marker: 3 }],
  };
}

describe("citation markers (D107)", () => {
  test("test_a_marker_is_read_exactly_as_the_host_reads_it", () => {
    expect(readMarkers("Leverage is 3.2x [C3]; cash [C2, C5] and [C1,C4].")).toEqual([
      "Leverage is 3.2x ",
      { text: "[C3]", numbers: [3] },
      "; cash ",
      { text: "[C2, C5]", numbers: [2, 5] },
      " and ",
      { text: "[C1,C4]", numbers: [1, 4] },
      ".",
    ]);
    // A body's backslash escape is the mark it writes (F149).
    expect(readMarkers("\\[C3\\]")).toEqual([{ text: "\\[C3\\]", numbers: [3] }]);
    // Near misses are text, as `handoff._MARKER` leaves them.
    for (const text of ["[c3]", "[C 3]", "[C3-C5]", "[C3–C5]", "[C3,4]", "[C]", "[C٣]"]) {
      expect(readMarkers(text)).toEqual([text]);
    }
    expect(readMarkers("[C1234567890]")).toEqual(["[C1234567890]"]);
  });

  test("test_a_marker_is_a_chip_named_citation_n_that_opens_its_source", () => {
    const container = drawn(marked(), "Net leverage fell [C1]; both [C1, C2].");
    const chip = screen.getAllByRole("button", {
      name: "citation 1: CVNA_10K_Annual_Report_FY2025.htm, page 1",
    })[0]!;
    expect(chip).toHaveTextContent(/^C1$/);
    expect(chip).toHaveAttribute("aria-haspopup", "dialog");
    expect(chip).toHaveAttribute("aria-expanded", "false");
    // Several in one bracket are one chip each, grouped.
    const group = container.querySelector('[data-markers="[C1, C2]"]')!;
    expect([...group.querySelectorAll("button")].map((b) => b.textContent)).toEqual(["C1", "C2"]);
    expect(container.textContent).not.toContain("[C1]");
  });

  test("test_an_unverified_marker_is_labelled_and_inert", () => {
    const container = drawn(marked(), "Covenant headroom [C3].");
    const chip = container.querySelector("[data-unverified-marker]")!;
    expect(chip).toHaveTextContent("citation 3, C3 · unverified – page 14");
    expect(chip.tagName).toBe("SPAN");
    expect(chip.closest("button, a")).toBeNull();
    expect(chip.querySelector("button, a, [tabindex]")).toBeNull();
    expect(chip.hasAttribute("tabindex")).toBe(false);
    expect(chip.hasAttribute("role")).toBe(false);
    expect(unverifiedMarkerLabel(14)).toBe("unverified – page 14");
    fireEvent.click(chip);
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  test("test_a_marker_no_citation_holds_stays_as_written", () => {
    // MK1 refuses such an answer; a page still never invents a chip for one.
    const container = drawn(marked(), "Gone [C9]; half [C1, C9]; old [C0].");
    expect(container.textContent).toBe("Gone [C9]; half [C1, C9]; old [C0].");
    expect(container.querySelector("button, [data-marker-chip]")).toBeNull();
    // A record from before markers names none: its brackets are text.
    const old = drawn(handoffOf("CP-1"), "Prior [C1] and [C2].");
    expect(old.textContent).toBe("Prior [C1] and [C2].");
    expect(old.querySelector("[data-marker-chip]")).toBeNull();
    // With no markers in scope at all (filed output), every bracket stays.
    const bare = render(<Markdown text="Plain [C1]." base={2} label="x" />).container;
    expect(bare.querySelector("[data-marker-chip]")).toBeNull();
  });

  test("test_markers_and_excerpts_reach_the_page_as_text", () => {
    const hostile = marked();
    const container = drawn(
      hostile,
      'Row [C2]<script>alert(1)</script> | **[C1]** `[C3]` <img src=x onerror="window.pwned=1">',
    );
    expect(container.querySelector("script, img")).toBeNull();
    expect(container.textContent).toContain("<script>alert(1)</script>");
    // Inside emphasis and code a marker is still the module's citation.
    expect(container.querySelector("strong [data-marker-chip='1']")).not.toBeNull();
    expect(container.querySelector("code [data-unverified-marker]")).not.toBeNull();
    // A hostile file name is an accessible name's text, never markup.
    const chip = screen.getByRole("button", {
      name: 'citation 2: <img src=x onerror="window.pwned=1">.htm, page 2',
    });
    expect(chip.children).toHaveLength(0);
  });

  test("test_a_saved_artifacts_markers_are_chips_from_its_served_figures", () => {
    const committee = parseCommitteeDocument(fixture("fixtures/committee-v1.json"));
    const artifact = committee.body.artifacts[0]!;
    const { container } = render(
      <ArtifactMarkers artifact={artifact}>
        <Markdown text={artifact.markdown} base={2} label="CP-1" />
      </ArtifactMarkers>,
    );
    expect(screen.getByRole("button", { name: "citation 1: CP-1 source, page 7" })).toBeVisible();
    expect(container.querySelector("[data-unverified-marker]")).toHaveTextContent(
      "unverified – page 9",
    );
    expect(container.querySelector("img")).toBeNull();
  });
});

describe("no whole source line outside the drawer (D107)", () => {
  // Every located fact of the demo whose line runs past its excerpt.
  const lined = complete.body.handoffs.flatMap((handoff) =>
    handoff.source_facts
      .filter((fact) => fact.line.recorded && (fact.line.before || fact.line.after))
      .map((fact) => ({ handoff, line: fact.line.before + fact.line.excerpt + fact.line.after })),
  );

  test("test_the_module_views_show_no_whole_source_line", () => {
    expect(lined.length).toBeGreaterThan(0);
    for (const { handoff, line } of lined) {
      const { container, unmount } = render(
        <MemoryRouter>
          <AnalysisSection document={complete} tab={handoff.route_node_id} />
        </MemoryRouter>,
      );
      for (const tab of container.querySelectorAll<HTMLElement>("[data-depth-tab]")) {
        fireEvent.click(tab);
        if (tab.getAttribute("data-depth-tab") === "written") continue; // the answer as written
        expect(container.textContent).not.toContain(line);
      }
      expect(container.querySelector("mark")).toBeNull();
      unmount();
    }
  });

  test("test_the_narrative_and_picker_show_no_whole_source_line", () => {
    const line = "We say Net debt 2.0bn today, before the refinancing closed.";
    const committee = parseCommitteeDocument(fixture("fixtures/committee-v1.json"));
    const figure = committee.body.narrative.flat().find((span) => span.figure)!.figure!;
    const narrative = [
      [
        {
          text: null,
          unverified: null,
          figure: {
            ...figure,
            matched_text: "Net debt 2.0bn today",
            line: {
              before: "We say ",
              excerpt: "Net debt 2.0bn today",
              after: ", before the refinancing closed.",
              recorded: true,
            },
          },
        },
      ],
    ];
    const { container } = render(<Narrative narrative={narrative} />);
    expect(container.querySelector("q.figq")).toHaveTextContent(/^Net debt 2\.0bn today$/);
    expect(container.textContent).not.toContain(line);
    expect(container.querySelector("mark")).toBeNull();

    const report = parseReportDocument(fixture("fixtures/report-v1.json"));
    const record = JSON.stringify({
      citation_rule: "excerpt-of-shown-line",
      citations: [{ page: 4, matched_text: "Net debt 2.0bn today", line_text: line, marker: 1 }],
    });
    const choices = citationsOf([{ ...report.body.artifacts[0]!, record }]);
    expect(choices.map(choiceText)).toEqual(["C1 · excerpt: Net debt 2.0bn today"]);
  });
});

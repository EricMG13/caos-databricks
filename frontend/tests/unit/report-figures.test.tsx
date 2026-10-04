import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { ReportSection } from "@/sections/report/ReportSection";
import { choiceText, citationsOf, figureMarker, paragraphs } from "@/sections/report/figures";
import { EXCERPT_CHARS, clampExcerpt } from "@/evidence/compact";
import { parseReportDocument, type ReportDocument } from "@/wire/v1";

// A figure span names a citation of a verified record; the host fills the
// document, the page and the quote from that record at save. These tests hold
// the picker to offering exactly what the served records carry and to
// composing exactly the `{route_node_id, citation_index}` the save command
// validates -- and nothing about whether the save is valid, which is the
// server's to decide.

const DOC = "d".repeat(64);
const citation = (page: number, matched_text: string) => ({
  document_sha256: DOC,
  page,
  matched_text,
  bboxes: [{ x0: 1.0, y0: 2.0, x1: 3.0, y1: 4.0 }],
});

function withRecords(records: Record<string, unknown>): ReportDocument {
  const raw = JSON.parse(
    readFileSync(resolve(process.cwd(), "fixtures/report-v1.json"), "utf8"),
  ) as { chrome: { actions: unknown[] }; body: { artifacts: Record<string, unknown>[] } };
  const template = raw.body.artifacts[0]!;
  raw.body.artifacts = Object.entries(records).map(([node, record]) => ({
    ...template,
    route_node_id: node,
    record: typeof record === "string" ? record : JSON.stringify(record),
  }));
  raw.chrome.actions = [{ action: "SAVE_REVISION", refusal: null }];
  return parseReportDocument(raw);
}

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

const settle = () => new Promise((resolve) => setTimeout(resolve, 0));

describe("Report figure picker", () => {
  test("test_the_picker_offers_each_citation_of_each_served_record_at_its_own_index", () => {
    const document = withRecords({
      "CP-0": {
        format: 2,
        citations: [citation(3, "Revenue rose to 4.1bn"), citation(9, "Net debt 2.0bn")],
      },
      // A record the client cannot read offers nothing, and a malformed entry
      // is skipped without shifting the index of the entries after it: the
      // index is the server's position in the record, not the picker's.
      "CP-1": "not json",
      "CP-5": { citations: [{ page: "x" }, citation(1, "Coverage 2.1x")] },
    });
    expect(citationsOf(document.body.artifacts)).toEqual([
      {
        route_node_id: "CP-0",
        citation_index: 0,
        unverified: null,
        page: 3,
        matched_text: "Revenue rose to 4.1bn",
        recorded: false,
        marker: null,
      },
      {
        route_node_id: "CP-0",
        citation_index: 1,
        unverified: null,
        page: 9,
        matched_text: "Net debt 2.0bn",
        recorded: false,
        marker: null,
      },
      {
        route_node_id: "CP-5",
        citation_index: 1,
        unverified: null,
        page: 1,
        matched_text: "Coverage 2.1x",
        recorded: false,
        marker: null,
      },
    ]);
  });

  test("test_the_picker_names_each_citation_compactly_by_its_marker_and_excerpt", () => {
    // D107: the marker the module's body cites it by and the excerpt, never
    // the whole source line (the drawer's); a record from before excerpts
    // holds only a quote, labelled so.
    const excerpt = {
      ...citation(4, "Net debt 2.0bn"),
      line_text: "We say Net debt 2.0bn today.",
      marker: 3,
    };
    const choices = citationsOf(
      withRecords({
        "CP-0": { citation_rule: "excerpt-of-shown-line", citations: [excerpt] },
        "CP-1": { citation_rule: "whole-line-as-shown", citations: [citation(5, "Total debt 9")] },
        "CP-2": { citations: [citation(6, "surpassed our investment grade")] },
      }).body.artifacts,
    );
    expect(choices.map(choiceText)).toEqual([
      "C3 · excerpt: Net debt 2.0bn",
      "excerpt: Total debt 9",
      "quote (source line not recorded): surpassed our investment grade",
    ]);
    expect(choices.map(choiceText).join(" ")).not.toContain("We say");
  });

  test("test_a_long_quote_is_clamped_to_about_one_line", () => {
    const long = `${"word ".repeat(60)}end`;
    const choice = {
      route_node_id: "CP-0",
      citation_index: 0,
      unverified: null,
      page: 1,
      matched_text: long,
      recorded: true,
      marker: 1,
    };
    const shown = clampExcerpt(long);
    expect(Array.from(shown)).toHaveLength(EXCERPT_CHARS);
    expect(shown.endsWith("\u2026")).toBe(true);
    expect(choiceText(choice)).toBe(`C1 · excerpt: ${shown}`);
    // Short, it is the quote with its whitespace runs single.
    expect(clampExcerpt("  Net\n debt  2.0bn ")).toBe("Net debt 2.0bn");
    // Counted in code points, so an astral character is never split.
    expect(Array.from(clampExcerpt("\u{1d400}".repeat(200)))).toHaveLength(EXCERPT_CHARS);
  });

  test("test_a_figure_marker_composes_the_span_the_save_command_validates", () => {
    // The marker names its citation in the text, counted from one (N90).
    expect(figureMarker("CP-0", 1)).toBe("[CP-0 #2]");
    const draft = [
      `Net debt closed at ${figureMarker("CP-0", 1)} after the refinancing.`,
      "",
      figureMarker("RN-LITE-01-CP-0", 0),
      "Pasted prose with a footnote [1], a [CP-0 #0] and a digit 4 stays prose, for the server to refuse.",
    ].join("\n");
    expect(paragraphs(draft)).toEqual([
      [
        { text: "Net debt closed at ", figure: null, unverified: null },
        { text: null, figure: { route_node_id: "CP-0", citation_index: 1 }, unverified: null },
        { text: " after the refinancing.", figure: null, unverified: null },
      ],
      [
        {
          text: null,
          figure: { route_node_id: "RN-LITE-01-CP-0", citation_index: 0 },
          unverified: null,
        },
      ],
      [
        {
          text: "Pasted prose with a footnote [1], a [CP-0 #0] and a digit 4 stays prose, for the server to refuse.",
          figure: null,
          unverified: null,
        },
      ],
    ]);
  });

  test("test_a_figure_chosen_in_the_picker_is_saved_as_a_figure_span", async () => {
    const document = withRecords({
      "CP-0": { citations: [citation(3, "Revenue rose to 4.1bn"), citation(9, "Net debt 2.0bn")] },
    });
    const fetchSpy = vi.fn().mockResolvedValueOnce(
      jsonResponse(
        {
          case_id: document.body.case_id,
          run_id: document.body.displayed_run_id,
          revision_id: "00000000-0000-4000-8000-0000000000c6",
          payload_sha256: "e".repeat(64),
        },
        201,
      ),
    );
    vi.stubGlobal("fetch", fetchSpy);
    const { container } = render(
      <MemoryRouter>
        <ReportSection document={document} tab={null} />
      </MemoryRouter>,
    );

    // Before any press, the surface says where a figure goes.
    const draft = screen.getByLabelText("Narrative draft");
    expect(draft).toHaveAccessibleDescription(/figure.*citation picker/i);

    fireEvent.change(draft, { target: { value: "Net debt closed at " } });
    (draft as HTMLTextAreaElement).setSelectionRange(19, 19);
    // Labelled, native and so keyboard operable: a select and a button.
    const picker = screen.getByLabelText("Citation");
    expect(picker.tagName).toBe("SELECT");
    // One control: the picker is the draft's own foot (brief 6.10).
    expect(draft.closest("[data-narrative-composer]")).toContainElement(picker);
    fireEvent.change(picker, { target: { value: "CP-0#1" } });
    fireEvent.click(screen.getByRole("button", { name: "Insert figure" }));
    // A marker the author can read, naming its citation in the text (N90).
    expect((draft as HTMLTextAreaElement).value).toBe("Net debt closed at [CP-0 #2]");
    // Listed under the draft with the quote the chosen citation names.
    expect(container.querySelector("[data-draft-figure='[CP-0 #2]']")).toHaveTextContent(
      "[CP-0 #2] CP-0 · p.9 · quote (source line not recorded): Net debt 2.0bn",
    );

    fireEvent.click(screen.getByRole("button", { name: "Save revision" }));
    await settle();
    expect(JSON.parse(fetchSpy.mock.calls[0]![1].body)).toEqual({
      expected_revision_id: document.body.revision_id,
      narrative: [
        [
          { text: "Net debt closed at ", figure: null, unverified: null },
          { text: null, figure: { route_node_id: "CP-0", citation_index: 1 }, unverified: null },
        ],
      ],
    });
    vi.unstubAllGlobals();
  });

  test("test_the_picker_offers_unverified_citations_labelled_as_the_models_own", async () => {
    // D106: a record's unverified citations are offered after its anchored
    // ones, each at its own index in that list, labelled before the quote,
    // and composed as the unverified span the save command resolves.
    const unverified = {
      source_id: "00000000-0000-4000-8000-0000000000a1",
      page: 12,
      matched_text: "Leverage <b>fell</b> to 3.1x",
      code: "CITATION_NOT_DELIVERED",
    };
    const document = withRecords({
      "CP-0": { citations: [citation(3, "Revenue rose to 4.1bn")], unverified: [unverified] },
      "CP-1": { citations: [], unverified: [{ ...unverified, code: "CITATION_FORGED" }] },
    });
    const choices = citationsOf(document.body.artifacts);
    expect(choices.map((choice) => [choice.citation_index, choice.unverified])).toEqual([
      [0, null],
      [0, "CITATION_NOT_DELIVERED"],
    ]);
    expect(choiceText(choices[1]!)).toBe(
      "unverified \u2013 page 12 · the model's quote · claim lineage: Untraced · not in the delivered evidence: Leverage <b>fell</b> to 3.1x",
    );
    expect(figureMarker("CP-0", 0, true)).toBe("[CP-0 unverified #1]");
    expect(paragraphs("At [CP-0 unverified #1].")).toEqual([
      [
        { text: "At ", figure: null, unverified: null },
        {
          text: null,
          figure: null,
          unverified: { route_node_id: "CP-0", unverified_index: 0 },
        },
        { text: ".", figure: null, unverified: null },
      ],
    ]);

    const fetchSpy = vi.fn().mockResolvedValueOnce(
      jsonResponse(
        {
          case_id: document.body.case_id,
          run_id: document.body.displayed_run_id,
          revision_id: "00000000-0000-4000-8000-0000000000c6",
          payload_sha256: "e".repeat(64),
        },
        201,
      ),
    );
    vi.stubGlobal("fetch", fetchSpy);
    const { container } = render(
      <MemoryRouter>
        <ReportSection document={document} tab={null} />
      </MemoryRouter>,
    );
    fireEvent.change(screen.getByLabelText("Citation"), {
      target: { value: "CP-0 unverified#0" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Insert figure" }));
    const listed = container.querySelector("[data-draft-figure='[CP-0 unverified #1]']");
    expect(listed).toHaveTextContent(
      "CP-0 · unverified \u2013 page 12 · the model's quote · claim lineage: Untraced",
    );
    expect(listed).not.toHaveTextContent(/source line/i);
    fireEvent.click(screen.getByRole("button", { name: "Save revision" }));
    await settle();
    expect(JSON.parse(fetchSpy.mock.calls[0]![1].body).narrative).toEqual([
      [{ text: null, figure: null, unverified: { route_node_id: "CP-0", unverified_index: 0 } }],
    ]);
    vi.unstubAllGlobals();
  });

  test("test_a_report_with_no_readable_citation_offers_no_figure", () => {
    const document = withRecords({ "CP-1": { coverage: "2.1x" } });
    render(
      <MemoryRouter>
        <ReportSection document={document} tab={null} />
      </MemoryRouter>,
    );
    expect(screen.queryByLabelText("Citation")).toBeNull();
    expect(screen.queryByRole("button", { name: "Insert figure" })).toBeNull();
    expect(screen.getByText(/no citation in this report's records/i)).toBeInTheDocument();
  });
});

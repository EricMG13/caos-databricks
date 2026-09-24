import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { ReportSection } from "@/sections/report/ReportSection";
import { citationsOf, figureMarker, paragraphs, withFigure } from "@/sections/report/figures";
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
      { route_node_id: "CP-0", citation_index: 0, page: 3, matched_text: "Revenue rose to 4.1bn" },
      { route_node_id: "CP-0", citation_index: 1, page: 9, matched_text: "Net debt 2.0bn" },
      { route_node_id: "CP-5", citation_index: 1, page: 1, matched_text: "Coverage 2.1x" },
    ]);
  });

  test("test_a_figure_marker_composes_the_span_the_save_command_validates", () => {
    // The draft's own list: `[n]` is its nth entry (N90).
    const figures = [
      { route_node_id: "CP-0", citation_index: 1 },
      { route_node_id: "RN-LITE-01-CP-0", citation_index: 0 },
    ];
    const draft = [
      `Net debt closed at ${figureMarker(1)} after the refinancing.`,
      "",
      figureMarker(2),
      "A bracketed [3] the draft does not list, and a digit 4, stay prose for the server to refuse.",
    ].join("\n");
    expect(paragraphs(draft, figures)).toEqual([
      [
        { text: "Net debt closed at ", figure: null },
        { text: null, figure: { route_node_id: "CP-0", citation_index: 1 } },
        { text: " after the refinancing.", figure: null },
      ],
      [{ text: null, figure: { route_node_id: "RN-LITE-01-CP-0", citation_index: 0 } }],
      [
        {
          text: "A bracketed [3] the draft does not list, and a digit 4, stay prose for the server to refuse.",
          figure: null,
        },
      ],
    ]);
  });

  test("withFigure: a citation inserted twice keeps its number, a new one takes the next", () => {
    const first = withFigure([], { route_node_id: "CP-0", citation_index: 1 });
    expect(first.marker).toBe("[1]");
    const again = withFigure(first.figures, { route_node_id: "CP-0", citation_index: 1 });
    expect(again).toEqual({ figures: first.figures, marker: "[1]" });
    const second = withFigure(again.figures, { route_node_id: "CP-5", citation_index: 0 });
    expect(second.marker).toBe("[2]");
    expect(second.figures).toEqual([
      { route_node_id: "CP-0", citation_index: 1 },
      { route_node_id: "CP-5", citation_index: 0 },
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
    fireEvent.change(picker, { target: { value: "CP-0#1" } });
    fireEvent.click(screen.getByRole("button", { name: "Insert figure" }));
    // A footnote marker the author can read, not a token (N90).
    expect((draft as HTMLTextAreaElement).value).toBe("Net debt closed at [1]");
    // Listed under the draft with the quote the chosen citation names.
    expect(container.querySelector("[data-draft-figure='[1]']")).toHaveTextContent(
      "[1] CP-0 · p.9 · Net debt 2.0bn",
    );

    fireEvent.click(screen.getByRole("button", { name: "Save revision" }));
    await settle();
    expect(JSON.parse(fetchSpy.mock.calls[0]![1].body)).toEqual({
      expected_revision_id: document.body.revision_id,
      narrative: [
        [
          { text: "Net debt closed at ", figure: null },
          { text: null, figure: { route_node_id: "CP-0", citation_index: 1 } },
        ],
      ],
    });
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
    expect(screen.getByText(/no verified citation/i)).toBeInTheDocument();
  });
});

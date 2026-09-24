import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, useLocation } from "react-router";
import { ReportSection } from "@/sections/report/ReportSection";
import { parseReportDocument, type ActionView, type ReportDocument } from "@/wire/v1";

const report = () =>
  parseReportDocument(
    JSON.parse(readFileSync(resolve(process.cwd(), "fixtures/report-v1.json"), "utf8")),
  );

function mount(document: ReportDocument) {
  return render(
    <MemoryRouter>
      <ReportSection document={document} tab={null} />
    </MemoryRouter>,
  );
}

function withActions(actions: ActionView[]): ReportDocument {
  const document = report();
  return { ...document, chrome: { ...document.chrome, actions } };
}

const AVAILABLE: ActionView[] = [
  { action: "SAVE_REVISION", refusal: null },
  { action: "SIGN_OPINION", refusal: null },
  { action: "FREEZE_DELIVERABLE", refusal: null },
  { action: "FILE_DELIVERABLE", refusal: null },
];

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

const settle = () => new Promise((resolve) => setTimeout(resolve, 0));

describe("Report v1", () => {
  test("renders only the exact saved payload as escaped read-only text", () => {
    const document = report();
    const hostile = '<img src=x onerror="window.pwned=1">';
    const { container } = mount(document);

    const root = container.querySelector("[data-report-v1]")!;
    expect(root).toHaveAttribute("data-revision", document.body.revision_id);
    expect(root).toHaveAttribute("data-payload", document.body.payload_sha256);
    expect(root).toHaveTextContent(hostile);
    // Nothing the payload reaches is interactive -- the artifacts, the
    // narrative and the case title alike, whatever the bytes say. The only
    // interactive nodes in the section are the governed controls, composed
    // from `chrome.actions` and never from the payload; asserting over the
    // whole root rather than over the payload's regions is what keeps a field
    // rendered outside them from escaping this check.
    // The one other interactive markup is the revision list's navigation,
    // whose targets are built from decoded UUIDs and never from payload text,
    // and a narrative figure's chip (N59): a button that opens the drawer by
    // the figure's typed identity, its quote only ever text.
    for (const node of root.querySelectorAll(
      "img, script, a, button, input, textarea, [contenteditable]",
    )) {
      expect(
        node.closest("[data-filing-controls], [data-report-revisions], [data-figure-chip]"),
      ).not.toBeNull();
    }
    for (const chip of root.querySelectorAll("[data-figure-chip]")) {
      expect(chip.tagName).toBe("BUTTON");
      expect(chip.children).toHaveLength(0);
    }
    for (const link of root.querySelectorAll("[data-report-revisions] a")) {
      expect(link.getAttribute("href")).toMatch(
        /^\/(report|committee)\/\?case=[0-9a-f-]{36}&run=[0-9a-f-]{36}&revision=[0-9a-f-]{36}$/,
      );
    }
    expect(root).toHaveTextContent(document.body.artifacts[0]!.record);
    expect(root.querySelector("[data-report-limitations]")).toHaveTextContent(
      document.body.artifacts[0]!.limitation_flags[0]!,
    );
    expect(root.querySelector("[data-report-warnings]")).toHaveTextContent(
      document.body.artifacts[0]!.validation_warnings[0]!,
    );
    expect(root).toHaveTextContent(document.body.narrative[0]![1]!.figure!.matched_text);
    expect(root.querySelectorAll("[data-report-artifact]")).toHaveLength(
      document.body.artifacts.length,
    );
  });

  // FE-12: two regions per artifact with the same two names between them is
  // 2N identically named landmarks to a reader jumping by landmark.
  test("test_each_artifact_region_is_named_by_the_route_node_it_is_about", () => {
    const document = report();
    const { container } = mount(document);
    const named = Array.from(container.querySelectorAll("[role='region'][aria-label]")).map(
      (region) => region.getAttribute("aria-label"),
    );
    expect(new Set(named).size).toBe(named.length);
    for (const artifact of document.body.artifacts) {
      expect(named).toContain(`${artifact.route_node_id} saved artifact markdown`);
      expect(named).toContain(`${artifact.route_node_id} saved artifact record`);
    }
  });

  test("test_the_report_places_a_control_for_each_of_the_four_filing_commands", () => {
    const { container } = mount(withActions(AVAILABLE));
    const placed = Array.from(
      container.querySelectorAll("[data-filing-controls] button[data-action]"),
    ).map((control) => control.getAttribute("data-action"));
    expect(placed).toEqual([
      "SAVE_REVISION",
      "SIGN_OPINION",
      "FREEZE_DELIVERABLE",
      "FILE_DELIVERABLE",
    ]);
    for (const control of container.querySelectorAll(
      "[data-filing-controls] button[data-action]",
    )) {
      expect(control).not.toHaveAttribute("aria-disabled");
    }
  });

  test("a refused filing control renders its code and clearance and is not hidden", () => {
    const { container } = mount(
      withActions([
        {
          action: "FREEZE_DELIVERABLE",
          refusal: { code: "DELIVERABLE_NOT_SIGNED", clears: "an approver signs the revision" },
        },
      ]),
    );
    const freeze = container.querySelector("button[data-action='FREEZE_DELIVERABLE']")!;
    expect(freeze).toHaveAttribute("aria-disabled", "true");
    expect(freeze).toHaveAttribute("data-refusal", "DELIVERABLE_NOT_SIGNED");
    expect(container).toHaveTextContent("an approver signs the revision");
    // An action the document does not name at all is unplaced, not available.
    const file = container.querySelector("button[data-action='FILE_DELIVERABLE']")!;
    expect(file).toHaveAttribute("data-refusal", "ACTION_UNPLACED");
  });

  test("test_a_saved_revision_names_the_head_it_was_composed_against", async () => {
    const document = withActions(AVAILABLE);
    const fetchSpy = vi.fn().mockResolvedValueOnce(
      jsonResponse(
        {
          case_id: document.body.case_id,
          run_id: document.body.displayed_run_id,
          revision_id: "00000000-0000-4000-8000-0000000000c4",
          payload_sha256: "b".repeat(64),
        },
        201,
      ),
    );
    vi.stubGlobal("fetch", fetchSpy);

    mount(document);
    fireEvent.change(screen.getByLabelText("Narrative draft"), {
      target: { value: "Leverage held at 4.2x.\n\nCoverage improved." },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save revision" }));
    await settle();

    // `saveRevision` builds this request and `parseRevisionSaved` narrows its
    // receipt; both are driven through the mounted section, never called here.
    const [url, init] = fetchSpy.mock.calls[0]!;
    expect(url).toBe(
      `/api/v1/cases/${document.body.case_id}/runs/${document.body.displayed_run_id}/revisions`,
    );
    expect(init.headers["Idempotency-Key"]).toMatch(/^[0-9a-f-]{36}$/);
    expect(JSON.parse(init.body)).toEqual({
      expected_revision_id: document.body.revision_id,
      narrative: [
        [{ text: "Leverage held at 4.2x.", figure: null }],
        [{ text: "Coverage improved.", figure: null }],
      ],
    });
    expect(await screen.findByText(/00000000-0000-4000-8000-0000000000c4/)).toBeInTheDocument();
    vi.unstubAllGlobals();
  });

  // R24-03: the analyst may leave before a deferred save's answer arrives --
  // another case, or another section -- and its success then names a
  // revision on an address no longer shown; writing it in would navigate
  // them back to the abandoned Report (guarded the way CF-058 guards Create
  // run in `run.test.tsx`'s "answer that lands after the analyst has left").
  test("a Save revision answer that lands after the analyst has left moves nothing", async () => {
    const document = withActions(AVAILABLE);
    let answer!: (response: Response) => void;
    vi.stubGlobal(
      "fetch",
      vi.fn(
        () =>
          new Promise<Response>((resolve) => {
            answer = resolve;
          }),
      ),
    );
    try {
      function Where() {
        return <output data-where>{useLocation().search}</output>;
      }
      const path =
        `/report/?case=${document.body.case_id}` + `&run=${document.body.displayed_run_id}&tab=x`;
      const view = (shown: boolean) => (
        <MemoryRouter initialEntries={[path]}>
          {shown ? <ReportSection document={document} tab={null} /> : null}
          <Where />
        </MemoryRouter>
      );
      const { container, rerender } = render(view(true));
      fireEvent.change(screen.getByLabelText("Narrative draft"), {
        target: { value: "Leverage held at 4.2x." },
      });
      fireEvent.click(screen.getByRole("button", { name: "Save revision" }));
      // The analyst leaves the Report -- the workspace remounts the section
      // tree on a case, run or revision change (`Workspace.tsx`'s `mountKey`),
      // which is exactly what unmounts `FilingControls`.
      rerender(view(false));
      await act(async () => {
        answer(
          jsonResponse(
            {
              case_id: document.body.case_id,
              run_id: document.body.displayed_run_id,
              revision_id: "00000000-0000-4000-8000-0000000000c4",
              payload_sha256: "b".repeat(64),
            },
            201,
          ),
        );
        await new Promise((resolve) => setTimeout(resolve, 0));
      });
      const where = container.querySelector("[data-where]")!;
      expect(where).toHaveTextContent(`case=${document.body.case_id}`);
      expect(where.textContent).not.toContain("revision=");
    } finally {
      vi.unstubAllGlobals();
    }
  });

  test("test_a_run_with_no_revision_offers_the_save_that_makes_its_first", async () => {
    // The document a Report without `?revision` is served for a run nothing
    // has been saved from: no revision, no digest, and only the save offered.
    const saved = report();
    const missing = {
      code: "DELIVERABLE_NOT_FOUND",
      clears: "Name a saved revision of this case.",
    };
    const document = parseReportDocument({
      ...saved,
      chrome: {
        ...saved.chrome,
        actions: [
          { action: "SAVE_REVISION", refusal: null },
          { action: "SIGN_OPINION", refusal: missing },
          { action: "FREEZE_DELIVERABLE", refusal: missing },
          { action: "FILE_DELIVERABLE", refusal: missing },
        ],
      },
      body: { ...saved.body, revision_id: null, payload_sha256: null, narrative: [] },
      observed_empty: false,
    });
    const first = "00000000-0000-4000-8000-0000000000c5";
    const fetchSpy = vi.fn().mockResolvedValueOnce(
      jsonResponse(
        {
          case_id: document.body.case_id,
          run_id: document.body.displayed_run_id,
          revision_id: first,
          payload_sha256: "c".repeat(64),
        },
        201,
      ),
    );
    vi.stubGlobal("fetch", fetchSpy);
    function Where() {
      return <output data-where>{useLocation().search}</output>;
    }
    const { container } = render(
      <MemoryRouter initialEntries={[`/report/?run=${document.body.displayed_run_id}`]}>
        <ReportSection document={document} tab={null} />
        <Where />
      </MemoryRouter>,
    );

    const root = container.querySelector("[data-report-v1]")!;
    expect(root).not.toHaveAttribute("data-revision");
    expect(root).toHaveTextContent("Not yet saved");
    for (const name of ["SIGN_OPINION", "FREEZE_DELIVERABLE", "FILE_DELIVERABLE"]) {
      expect(container.querySelector(`button[data-action='${name}']`)).toHaveAttribute(
        "data-refusal",
        "DELIVERABLE_NOT_FOUND",
      );
    }
    fireEvent.click(screen.getByRole("button", { name: "Sign opinion" }));
    fireEvent.click(screen.getByRole("button", { name: "Save revision" }));
    await settle();

    // Only the save was sent, naming no head because the run has none.
    expect(fetchSpy).toHaveBeenCalledTimes(1);
    expect(JSON.parse(fetchSpy.mock.calls[0]![1].body)).toEqual({
      expected_revision_id: null,
      narrative: [],
    });
    // Its success is what first sets `?revision`.
    await waitFor(() =>
      expect(container.querySelector("[data-where]")).toHaveTextContent(`revision=${first}`),
    );
    vi.unstubAllGlobals();
  });

  test("test_signing_binds_the_payload_digest_on_screen_and_re_reads_the_report", async () => {
    const document = withActions(AVAILABLE);
    const fetchSpy = vi
      .fn()
      .mockResolvedValueOnce(
        jsonResponse({
          case_id: document.body.case_id,
          revision_id: document.body.revision_id,
          payload_sha256: document.body.payload_sha256,
          signed_by: "00000000-0000-4000-8000-00000000000a",
        }),
      )
      .mockResolvedValueOnce(
        jsonResponse({
          ...document,
          chrome: {
            ...document.chrome,
            actions: [
              {
                action: "SIGN_OPINION",
                refusal: {
                  code: "DELIVERABLE_ALREADY_FROZEN",
                  clears: "a later revision is saved",
                },
              },
            ],
          },
        }),
      );
    vi.stubGlobal("fetch", fetchSpy);

    const { container } = mount(document);
    // The filing chain asks once more before each act (finding FE-7).
    fireEvent.click(screen.getByRole("button", { name: "Sign opinion" }));
    fireEvent.click(screen.getByRole("button", { name: "Confirm Sign opinion" }));
    await settle();
    await settle();

    // `signOpinion` and `parseOpinionSigned`, same way.
    const [url, init] = fetchSpy.mock.calls[0]!;
    expect(url).toBe(
      `/api/v1/cases/${document.body.case_id}/revisions/${document.body.revision_id}/signature`,
    );
    expect(JSON.parse(init.body)).toEqual({ payload_sha256: document.body.payload_sha256 });
    // The re-read document, never this control, is what says the act landed.
    expect(fetchSpy.mock.calls[1]![0]).toContain(`/api/v1/cases/${document.body.case_id}/report`);
    expect(container.querySelector("button[data-action='SIGN_OPINION']")).toHaveAttribute(
      "data-refusal",
      "DELIVERABLE_ALREADY_FROZEN",
    );
    vi.unstubAllGlobals();
  });
  test("test_freezing_and_filing_each_bind_the_reviewed_digest_to_their_own_route", async () => {
    const document = withActions(AVAILABLE);
    const receipt = {
      case_id: document.body.case_id,
      run_id: document.body.displayed_run_id,
      revision_id: document.body.revision_id,
      payload_sha256: document.body.payload_sha256,
      frozen_by: "00000000-0000-4000-8000-00000000000b",
      filed_by: "00000000-0000-4000-8000-00000000000c",
    };
    const fetchSpy = vi.fn().mockResolvedValue(jsonResponse(document));
    // `freezeDeliverable`/`parseDeliverableFrozen` and
    // `fileDeliverable`/`parseDeliverableFiled` are driven here through the
    // mounted section; the re-read between them is the same GET as above.
    fetchSpy.mockResolvedValueOnce(
      jsonResponse({
        case_id: receipt.case_id,
        revision_id: receipt.revision_id,
        payload_sha256: receipt.payload_sha256,
        frozen_by: receipt.frozen_by,
      }),
    );
    vi.stubGlobal("fetch", fetchSpy);

    mount(document);
    // The filing chain asks once more before each act (finding FE-7).
    fireEvent.click(screen.getByRole("button", { name: "Freeze deliverable" }));
    fireEvent.click(screen.getByRole("button", { name: "Confirm Freeze deliverable" }));
    await settle();
    await settle();
    expect(fetchSpy.mock.calls[0]![0]).toBe(
      `/api/v1/cases/${receipt.case_id}/revisions/${receipt.revision_id}/freeze`,
    );
    expect(JSON.parse(fetchSpy.mock.calls[0]![1].body)).toEqual({
      payload_sha256: receipt.payload_sha256,
    });

    fetchSpy.mockResolvedValueOnce(jsonResponse(receipt));
    // The filing chain asks once more before each act (finding FE-7).
    fireEvent.click(screen.getByRole("button", { name: "File deliverable" }));
    fireEvent.click(screen.getByRole("button", { name: "Confirm File deliverable" }));
    await settle();
    await settle();
    const filing = fetchSpy.mock.calls.find(([url]) => String(url).endsWith("/filing"))!;
    expect(filing[0]).toBe(
      `/api/v1/cases/${receipt.case_id}/revisions/${receipt.revision_id}/filing`,
    );
    expect(JSON.parse(filing[1].body)).toEqual({ payload_sha256: receipt.payload_sha256 });
    vi.unstubAllGlobals();
  });
});

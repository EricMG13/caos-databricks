// A section that throws renders its region error, not a blank workspace
// (brief 4.4, R4 and decision 6).
import { act, fireEvent, render, within } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { Workspace } from "@/app/Workspace";
import { SectionBoundary, ViewNotLoaded } from "@/states/SectionBoundary";

vi.mock("@/app/views", () => {
  const Throws = () => {
    throw new Error("document-derived text that must never render");
  };
  return {
    SECTION_VIEWS: new Proxy({}, { get: () => Throws }),
    preloadView: () => Promise.resolve(),
  };
});

const DIRECTORY = {
  chrome: {
    subject: null,
    served_role: { global_role: "ANALYST", standing: null },
    actions: [],
  },
  body: { cases: [] },
  observed_at: "2026-09-14T00:00:00Z",
  observed_empty: false,
  status: "complete",
  notes: [],
};

describe("the section render boundary", () => {
  beforeEach(() => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    vi.stubGlobal("fetch", async () => new Response(JSON.stringify(DIRECTORY), { status: 200 }));
  });
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  test("test_a_section_that_throws_renders_its_region_error_not_a_blank_workspace", async () => {
    const { container } = render(
      <MemoryRouter initialEntries={["/directory/"]}>
        <Workspace section="directory" />
      </MemoryRouter>,
    );
    await act(() => new Promise((resolve) => setTimeout(resolve, 0)));
    const error = container.querySelector("main#body [data-surface-state='error']");
    expect(error).not.toBeNull();
    expect(error).toHaveTextContent("RENDER_FAILED");
    // The chrome still draws around the failed region.
    expect(container.querySelector("nav, [role='tablist'], .frame")).not.toBeNull();
    expect(container).not.toHaveTextContent("document-derived text");
  });

  // A boundary that latches until the section is unmounted keeps a refusal on
  // screen over a document that renders perfectly well (brief 4.4, R4).
  test("test_a_render_failure_clears_when_a_new_document_arrives", () => {
    const Throwing = () => {
      throw new Error("document-derived text that must never render");
    };
    const Fine = () => <p data-ok>fine</p>;
    const { container, rerender } = render(
      <SectionBoundary resetOn="2026-09-14T00:00:00Z">
        <Throwing />
      </SectionBoundary>,
    );
    expect(container.querySelector("[data-surface-state='error']")).toHaveTextContent(
      "RENDER_FAILED",
    );
    rerender(
      <SectionBoundary resetOn="2026-09-14T00:00:01Z">
        <Fine />
      </SectionBoundary>,
    );
    expect(container.querySelector("[data-surface-state='error']")).toBeNull();
    expect(container.querySelector("[data-ok]")).not.toBeNull();
    // Recovering re-renders the failure once more, so the leak the boundary
    // exists to stop is asserted on the retry too, not only on the first throw.
    expect(container).not.toHaveTextContent("document-derived text");
  });

  test("a boundary renders its children when nothing throws", () => {
    const { container } = render(
      <SectionBoundary>
        <p data-ok>fine</p>
      </SectionBoundary>,
    );
    expect(container.querySelector("[data-ok]")).not.toBeNull();
  });

  // W7 of the API review: the first failed load is worth another try; a
  // second in a row is a stale page, and only a reload fetches new files.
  test("a view that will not load offers another try, then a reload of the page", () => {
    let attempts = 0;
    const NeverLoads = () => {
      attempts += 1;
      throw new ViewNotLoaded();
    };
    const { container } = render(
      <SectionBoundary resetOn="2026-09-14T00:00:00Z">
        <NeverLoads />
      </SectionBoundary>,
    );
    const error = () => container.querySelector("[data-surface-state='error']") as HTMLElement;
    expect(error()).toHaveTextContent("VIEW_NOT_LOADED");
    expect(error()).toHaveTextContent("Available once it is tried again.");
    const tried = attempts;
    fireEvent.click(within(error()).getByText("Try again"));
    expect(attempts).toBeGreaterThan(tried);
    expect(error()).toHaveTextContent("Available once the page is reloaded.");
    expect(within(error()).queryByText("Try again")).toBeNull();
    expect(within(error()).getByRole("button", { name: "Reload the page" })).toBeVisible();
  });
});

// A section's view is a lazy chunk (N65): while it is in flight the region
// reads as loading, a chunk that fails meets the section boundary, and the
// workspace asks for the chunk when it asks for the document.
import { lazy, type ComponentType } from "react";
import { act, render } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { Workspace } from "@/app/Workspace";

const viewLoad = vi.hoisted(() => ({
  View: null as unknown as ComponentType,
  settle: (_outcome: "view" | "fail") => {},
  preloaded: [] as string[],
}));

vi.mock("@/app/views", () => ({
  // Read at render, so each test mounts the lazy view it built.
  SECTION_VIEWS: new Proxy({}, { get: () => viewLoad.View }),
  preloadView: (section: string) => {
    viewLoad.preloaded.push(section);
    return Promise.resolve();
  },
}));

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

const settle = () => act(() => new Promise((resolve) => setTimeout(resolve, 0)));

function mount() {
  return render(
    <MemoryRouter initialEntries={["/directory/"]}>
      <Workspace section="directory" />
    </MemoryRouter>,
  );
}

describe("a lazy section view", () => {
  beforeEach(() => {
    viewLoad.preloaded = [];
    viewLoad.View = lazy(
      () =>
        new Promise<{ default: ComponentType }>((resolve, reject) => {
          viewLoad.settle = (outcome) =>
            outcome === "view"
              ? resolve({ default: () => <p data-lazy-view>the view</p> })
              : reject(new Error("document-derived text that must never render"));
        }),
    );
    vi.spyOn(console, "error").mockImplementation(() => {});
    vi.stubGlobal("fetch", async () => new Response(JSON.stringify(DIRECTORY), { status: 200 }));
  });
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  test("reads as loading until its chunk lands, then mounts; the chunk is asked for on mount", async () => {
    const { container } = mount();
    expect(viewLoad.preloaded).toEqual(["directory"]);
    await settle();
    // The document is in and the summary drawn; the view is still in flight.
    expect(container.querySelector("main#body [data-summary]")).not.toBeNull();
    expect(container.querySelector("main#body [data-surface-state='loading']")).not.toBeNull();
    expect(container.querySelector("[data-lazy-view]")).toBeNull();
    await act(async () => viewLoad.settle("view"));
    await settle();
    expect(container.querySelector("[data-lazy-view]")).not.toBeNull();
    expect(container.querySelector("main#body [data-surface-state='loading']")).toBeNull();
  });

  test("a chunk that fails to load meets the section boundary, not a blank region", async () => {
    const { container } = mount();
    await settle();
    await act(async () => viewLoad.settle("fail"));
    await settle();
    const error = container.querySelector("main#body [data-surface-state='error']");
    expect(error).toHaveTextContent("RENDER_FAILED");
    expect(container).not.toHaveTextContent("document-derived text");
  });
});

// A section's view is a lazy chunk (N65): while it is in flight the region
// reads as loading, a chunk that fails meets the section boundary, and the
// workspace asks for the chunk when it asks for the document.
import { Suspense, lazy, type ComponentType } from "react";
import { act, fireEvent, render, within } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import type * as Views from "@/app/views";
import { Workspace } from "@/app/Workspace";
import { SectionBoundary, ViewNotLoaded } from "@/states/SectionBoundary";

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
              : reject(new ViewNotLoaded());
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

  test("a chunk that fails to load is told apart from the document's fault", async () => {
    const { container } = mount();
    await settle();
    await act(async () => viewLoad.settle("fail"));
    await settle();
    const error = container.querySelector("main#body [data-surface-state='error']")!;
    expect(error).toHaveTextContent("VIEW_NOT_LOADED");
    expect(error).toHaveTextContent("This part of the workspace did not load.");
  });

  test("a view that throws while drawing is a render failure, not a load one", async () => {
    viewLoad.View = () => {
      throw new Error("document-derived text that must never render");
    };
    const { container } = mount();
    await settle();
    const error = container.querySelector("main#body [data-surface-state='error']")!;
    expect(error).toHaveTextContent("RENDER_FAILED");
    expect(within(error as HTMLElement).queryByText("Try again")).toBeNull();
  });
});

// The real `retryingView`, not the mock above (W7 of the API review): one
// failed fetch of a view's code no longer breaks the section for good.
describe("retryingView", () => {
  test("a view whose code failed once loads on the boundary's next try", async () => {
    const { retryingView } = await vi.importActual<typeof Views>("@/app/views");
    let calls = 0;
    const View = retryingView<object>(() => {
      calls += 1;
      return calls === 1
        ? Promise.reject(new Error("chunk failed"))
        : Promise.resolve(() => <p data-lazy-view>the view</p>);
    });
    vi.spyOn(console, "error").mockImplementation(() => {});
    const { container } = render(
      <SectionBoundary resetOn="2026-09-14T00:00:00Z">
        <Suspense fallback={<p data-loading />}>
          <View />
        </Suspense>
      </SectionBoundary>,
    );
    await settle();
    const error = container.querySelector("[data-surface-state='error']") as HTMLElement;
    expect(error).toHaveTextContent("VIEW_NOT_LOADED");
    // Nothing asks again on its own: React's re-render after the failure
    // meets the same failed view, never a fresh one in a loop.
    await settle();
    expect(calls).toBe(1);
    await act(async () => fireEvent.click(within(error).getByText("Try again")));
    await settle();
    expect(calls).toBe(2);
    expect(container.querySelector("[data-lazy-view]")).not.toBeNull();
    vi.restoreAllMocks();
  });

  test("a view whose code is gone asks twice, then offers a reload of the page", async () => {
    const { retryingView } = await vi.importActual<typeof Views>("@/app/views");
    let calls = 0;
    const View = retryingView<object>(() => {
      calls += 1;
      return Promise.reject(new Error("404 after a deploy"));
    });
    vi.spyOn(console, "error").mockImplementation(() => {});
    const { container } = render(
      <SectionBoundary resetOn="2026-09-14T00:00:00Z">
        <Suspense fallback={<p data-loading />}>
          <View />
        </Suspense>
      </SectionBoundary>,
    );
    await settle();
    const error = () => container.querySelector("[data-surface-state='error']") as HTMLElement;
    await act(async () => fireEvent.click(within(error()).getByText("Try again")));
    await settle();
    await settle();
    expect(calls).toBe(2);
    expect(within(error()).getByRole("button", { name: "Reload the page" })).toBeVisible();
    vi.restoreAllMocks();
  });
});

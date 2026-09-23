// Report and Committee are reachable from inside the workspace (critique P0):
// the rail carries the run on screen and a frozen revision of it, a section
// still waiting on either says what to pick and where, and a region that
// received nothing offers to ask again.
import { readFileSync } from "node:fs";
import { act, fireEvent, render } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { committeeRevisionOf } from "@/app/sections";
import { selectionNeeded } from "@/app/transport";
import { Workspace } from "@/app/Workspace";
import { RegionState } from "@/states/RegionState";
import type { Section } from "@/wire";

const json = (path: string) => JSON.parse(readFileSync(new URL(path, import.meta.url), "utf8"));

const CASE = "00000000-0000-4000-8000-000000000001";
const RUN = "00000000-0000-4000-8000-0000000000b2";
const REVISION = "00000000-0000-4000-8000-0000000000c3";
const FROZEN = "00000000-0000-4000-8000-0000000000c1";
// The run `fixtures/analysis.json` displays.
const DISPLAYED = "00000000-0000-4000-8000-0000000000a1";

/** A tail that never speaks: these tests are about the first read. */
class SilentSource {
  onopen: (() => void) | null = null;
  onerror: (() => void) | null = null;
  readyState = 0;
  constructor(readonly url: string) {}
  addEventListener() {}
  removeEventListener() {}
  close() {}
}

const settle = () => act(() => new Promise((resolve) => setTimeout(resolve, 0)));

async function mount(section: Section, path: string, fetch: ReturnType<typeof vi.fn>) {
  vi.stubGlobal("fetch", fetch);
  vi.stubGlobal("EventSource", SilentSource);
  const view = render(
    <MemoryRouter initialEntries={[path]}>
      <Workspace section={section} />
    </MemoryRouter>,
  );
  await settle();
  return view;
}

const serving = (body: unknown) =>
  vi.fn(async () => new Response(JSON.stringify(body), { status: 200 }));
const railHref = (container: HTMLElement, section: Section) =>
  container.querySelector(`nav.rail a[data-section='${section}']`)?.getAttribute("href");
const region = (container: HTMLElement) => container.querySelector("main#body")!;

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("what Report and Committee wait on", () => {
  test("test_selectionNeeded_names_the_run_or_revision_a_case_section_waits_on", () => {
    expect(selectionNeeded("report", { case: CASE })).toBe("run");
    expect(selectionNeeded("committee", { case: CASE })).toBe("run");
    expect(selectionNeeded("committee", { case: CASE, run: RUN })).toBe("revision");
    expect(selectionNeeded("committee", { case: CASE, run: RUN, revision: REVISION })).toBeNull();
    expect(selectionNeeded("report", { case: CASE, run: RUN })).toBeNull();
    expect(selectionNeeded("analysis", { case: CASE })).toBeNull();
    // With no case there is nothing to choose within: that stays unavailable.
    expect(selectionNeeded("report", {})).toBeNull();
  });

  test("test_committeeRevisionOf_prefers_the_displayed_frozen_revision_then_the_newest", () => {
    const listed = [
      { revision_id: "c", state: "saved" },
      { revision_id: "b", state: "frozen" },
      { revision_id: "a", state: "filed" },
    ];
    expect(committeeRevisionOf(listed, "a")).toBe("a");
    expect(committeeRevisionOf(listed, "c")).toBe("b");
    expect(committeeRevisionOf(listed, null)).toBe("b");
    expect(committeeRevisionOf([{ revision_id: "c", state: "saved" }], "c")).toBeNull();
    expect(committeeRevisionOf([], null)).toBeNull();
  });
});

describe("the rail reaches Report and Committee", () => {
  test("Report opens on the run Analysis displays when the address names none", async () => {
    const { container } = await mount(
      "analysis",
      `/analysis/?case=${CASE}`,
      serving(json("../../fixtures/analysis.json")),
    );
    expect(railHref(container, "report")).toBe(`/report/?case=${CASE}&run=${DISPLAYED}`);
    // No revision is known here, so Committee opens on its own choice.
    expect(railHref(container, "committee")).toBe(`/committee/?case=${CASE}&run=${DISPLAYED}`);
    // Sections that follow the case's latest run are not pinned to this one.
    expect(railHref(container, "run")).toBe(`/run/?case=${CASE}`);
  });

  test("Committee opens on the frozen revision Report lists, and Report links to it", async () => {
    const report = json("../../fixtures/states/report.acts.json");
    report.body.revisions = [
      report.body.revisions[0],
      {
        revision_id: FROZEN,
        payload_sha256: "b".repeat(64),
        saved_at: "2026-09-13T09:00:00Z",
        state: "frozen",
      },
    ];
    const { container } = await mount(
      "report",
      `/report/?case=${CASE}&run=${RUN}&revision=${REVISION}`,
      serving(report),
    );
    expect(railHref(container, "committee")).toBe(
      `/committee/?case=${CASE}&run=${RUN}&revision=${FROZEN}`,
    );
    const rows = region(container).querySelectorAll("[data-report-revisions] tbody tr");
    expect([...rows].map((row) => row.getAttribute("data-state"))).toEqual(["saved", "frozen"]);
    // The displayed revision says so; only a frozen one opens Committee.
    expect(rows[0]).toHaveAttribute("aria-current", "true");
    expect(rows[0]!.querySelector("a")).toBeNull();
    expect(rows[1]!.querySelector("a[aria-label$='in Committee']")).toHaveAttribute(
      "href",
      `/committee/?case=${CASE}&run=${RUN}&revision=${FROZEN}`,
    );
  });
});

describe("a section waiting on the reader", () => {
  test("Report with no run says to choose one in Run and sends nothing", async () => {
    const fetch = serving({});
    const { container } = await mount("report", `/report/?case=${CASE}`, fetch);
    expect(fetch).not.toHaveBeenCalled();
    const state = region(container).querySelector("[data-surface-state='choose']");
    expect(state).toHaveTextContent("Choose a run");
    expect(state!.querySelector("a")).toHaveAttribute("href", `/run/?case=${CASE}`);
    expect(container).not.toHaveTextContent("Unavailable or not permitted.");
    expect(container.querySelector(".verdict")).toHaveTextContent(
      "Choose a run to open this section.",
    );
  });

  test("Committee with no revision says to choose a frozen one in Report", async () => {
    const fetch = serving({});
    const { container } = await mount("committee", `/committee/?case=${CASE}&run=${RUN}`, fetch);
    expect(fetch).not.toHaveBeenCalled();
    const state = region(container).querySelector("[data-surface-state='choose']");
    expect(state).toHaveTextContent("Choose a frozen revision");
    expect(state!.querySelector("a")).toHaveAttribute("href", `/report/?case=${CASE}&run=${RUN}`);
  });
});

describe("a region that received nothing", () => {
  test("offline and refused regions offer to try again; others do not", () => {
    const retry = vi.fn();
    const { container, rerender } = render(
      <RegionState status={{ kind: "offline" }} onRetry={retry}>
        {() => null}
      </RegionState>,
    );
    fireEvent.click(container.querySelector("button")!);
    expect(retry).toHaveBeenCalledTimes(1);
    rerender(
      <RegionState
        status={{
          kind: "error",
          refusal: { code: "STORE_UNAVAILABLE", clears: "the store answers" },
        }}
        onRetry={retry}
      >
        {() => null}
      </RegionState>,
    );
    expect(container.querySelector("button")).toHaveTextContent("TRY AGAIN");
    rerender(
      <RegionState status={{ kind: "unavailable" }} onRetry={retry}>
        {() => null}
      </RegionState>,
    );
    expect(container.querySelector("button")).toBeNull();
  });

  test("trying again sends the section's read once more and shows what arrives", async () => {
    const directory = json("../../fixtures/directory.json");
    const fetch = vi
      .fn()
      .mockRejectedValueOnce(new TypeError("network"))
      .mockResolvedValueOnce(new Response(JSON.stringify(directory), { status: 200 }));
    const { container } = await mount("directory", "/directory/", fetch);
    expect(region(container).querySelector("[data-surface-state='offline']")).not.toBeNull();
    fireEvent.click(region(container).querySelector("button")!);
    await settle();
    expect(fetch).toHaveBeenCalledTimes(2);
    expect(region(container).querySelector("[data-surface-state='offline']")).toBeNull();
  });
});

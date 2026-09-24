// The evidence drawer bound to the visible snapshot, its text layer and the
// highlight geometry (brief 4.4, decisions 7-9; R1 and R2).
import { readFileSync } from "node:fs";
import { act, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { App } from "@/app/App";
import { Workspace } from "@/app/Workspace";
import { fetchPage, pageUrl } from "@/app/transport";
import { toFraction } from "@/evidence/geometry";

const text = (path: string): string => readFileSync(new URL(path, import.meta.url), "utf8");

const CASE = "00000000-0000-4000-8000-000000000001";
const OTHER = "00000000-0000-4000-8000-0000000000ff";
const RUN = "00000000-0000-4000-8000-0000000000a1";
const SOURCE = "f9b54532-f1d3-48b8-bca2-5e29b9d3b16b";
const PAGE_PATH = `/api/v1/cases/${CASE}/runs/${RUN}/sources/${SOURCE}/pages/1`;

type Json = Record<string, any>; // eslint-disable-line @typescript-eslint/no-explicit-any
const analysis = (): Json => JSON.parse(text("../../fixtures/analysis.json"));
const pageDoc = (): Json => JSON.parse(text(`../../fixtures/pages/v1/${SOURCE}.1.json`));

class FakeSource {
  static CONNECTING = 0;
  static OPEN = 1;
  static CLOSED = 2;
  static all: FakeSource[] = [];
  readonly listeners = new Map<string, () => void>();
  readyState = FakeSource.CONNECTING;
  constructor(readonly url: string) {
    FakeSource.all.push(this);
  }
  addEventListener(name: string, handler: () => void) {
    this.listeners.set(name, handler);
  }
  close() {
    this.readyState = FakeSource.CLOSED;
  }
}

let urls: string[] = [];
let sectionBody: (url: string) => Json;
let pageAnswer: (url: string) => { status: number; body: unknown };

beforeEach(() => {
  urls = [];
  FakeSource.all = [];
  sectionBody = () => analysis();
  pageAnswer = () => ({ status: 200, body: pageDoc() });
  vi.stubGlobal("EventSource", FakeSource);
  vi.stubGlobal("fetch", async (url: string) => {
    urls.push(url);
    const { status, body } = url.includes("/pages/")
      ? pageAnswer(url)
      : { status: 200, body: sectionBody(url) };
    return new Response(JSON.stringify(body), { status });
  });
});
afterEach(() => {
  vi.unstubAllGlobals();
  window.history.pushState({}, "", "/");
});

const settle = () => act(() => new Promise((resolve) => setTimeout(resolve, 0)));
const dialog = () => screen.queryByRole("dialog");
const lines = () => document.querySelectorAll("[data-evidence-drawer] [data-page-line]");

async function fire(name: string) {
  act(() => FakeSource.all.at(-1)!.listeners.get(name)?.());
  await settle();
}

async function mount(path: string) {
  const view = render(
    <MemoryRouter initialEntries={[path]}>
      <Workspace section="analysis" />
    </MemoryRouter>,
  );
  await settle();
  return view;
}

async function openFirstFact() {
  const chip = document.querySelector<HTMLButtonElement>(`[data-fact-chip='${SOURCE}']`)!;
  act(() => fireEvent.click(chip));
  await settle();
  return chip;
}

describe("the page geometry", () => {
  test("test_v1_bottom_left_and_v2_top_left_rects_convert_to_the_same_region", () => {
    const v2 = toFraction(
      { x0: 72, y0: 120.5, x1: 460.2, y1: 134 },
      { x0: 0, y0: 0, x1: 612, y1: 792, y_axis: "down" },
    );
    const v1 = toFraction(
      { x0: 82, y0: 812 - 134, x1: 470.2, y1: 812 - 120.5 },
      { x0: 10, y0: 20, x1: 622, y1: 812, y_axis: "up" },
    );
    expect(v2).not.toBeNull();
    expect(v1!.left).toBeCloseTo(v2!.left, 12);
    expect(v1!.top).toBeCloseTo(v2!.top, 12);
    expect(v1!.width).toBeCloseTo(v2!.width, 12);
    expect(v1!.height).toBeCloseTo(v2!.height, 12);
    expect(v2!.top).toBeCloseTo(120.5 / 792, 12);
  });

  test("a rectangle not wholly inside its frame, or a degenerate frame, places nothing", () => {
    const frame = { x0: 0, y0: 0, x1: 100, y1: 100, y_axis: "down" as const };
    expect(toFraction({ x0: 10, y0: 90, x1: 20, y1: 101 }, frame)).toBeNull();
    expect(toFraction({ x0: -1, y0: 10, x1: 20, y1: 20 }, frame)).toBeNull();
    expect(toFraction({ x0: 20, y0: 10, x1: 10, y1: 20 }, frame)).toBeNull();
    expect(toFraction({ x0: 1, y0: 1, x1: 2, y1: 2 }, { ...frame, x1: 0 })).toBeNull();
    expect(toFraction({ x0: 1, y0: 1, x1: Number.NaN, y1: 2 }, frame)).toBeNull();
  });
});

describe("the page read", () => {
  const query = { caseId: CASE, runId: RUN, sourceId: SOURCE, page: 1 };

  test("a page answers for exactly the case, run, source and page requested", async () => {
    expect(pageUrl(query)).toBe(PAGE_PATH);
    expect(await fetchPage(query)).toMatchObject({ kind: "ready" });
    pageAnswer = () => {
      const doc = pageDoc();
      doc["body"].page = 2;
      return { status: 200, body: doc };
    };
    expect(await fetchPage(query)).toMatchObject({
      kind: "error",
      refusal: { code: "WIRE_IDENTITY_MISMATCH" },
    });
    pageAnswer = () => ({ status: 200, body: { ...pageDoc(), extra: true } });
    expect(await fetchPage(query)).toMatchObject({
      kind: "error",
      refusal: { code: "WIRE_SHAPE_INVALID" },
    });
  });

  test("an unavailable page is unavailable and carries nothing", async () => {
    pageAnswer = () => ({ status: 404, body: { code: "PAGE_NOT_AVAILABLE", clears: "x" } });
    expect(await fetchPage(query)).toEqual({ kind: "unavailable" });
  });
});

describe("the evidence drawer", () => {
  test("a source fact opens its page's text layer with the citation highlighted", async () => {
    await mount(`/analysis/?case=${CASE}&tab=rn-cp-0`);
    await openFirstFact();
    expect(dialog()).not.toBeNull();
    expect(urls).toContain(PAGE_PATH);
    expect(dialog()).toHaveTextContent("Text layer from the token index");
    expect(lines()).toHaveLength(3);
    expect(dialog()!.querySelectorAll("[data-highlight]")).toHaveLength(1);
    expect(dialog()!.querySelector("[data-outside-frame]")).toBeNull();
  });

  test("test_a_same_section_case_switch_closes_the_open_evidence", async () => {
    // R1, through App: the Workspace stays mounted across a same-section switch.
    sectionBody = (url) =>
      url.includes(OTHER)
        ? JSON.parse(text("../../fixtures/analysis.json").replaceAll(CASE, OTHER))
        : analysis();
    window.history.pushState({}, "", `/analysis/?case=${CASE}&tab=rn-cp-0`);
    render(<App />);
    await settle();
    await openFirstFact();
    expect(lines()).toHaveLength(3);
    act(() => {
      window.history.pushState({}, "", `/analysis/?case=${OTHER}&tab=rn-cp-0`);
      window.dispatchEvent(new PopStateEvent("popstate"));
    });
    await settle();
    expect(document.querySelector(`[data-fact-chip='${SOURCE}']`)).not.toBeNull();
    expect(dialog()).toBeNull();
  });

  test("test_focus_returns_to_the_section_heading_when_the_opener_disappears", async () => {
    sectionBody = (url) =>
      url.includes(OTHER)
        ? JSON.parse(text("../../fixtures/analysis.json").replaceAll(CASE, OTHER))
        : analysis();
    window.history.pushState({}, "", `/analysis/?case=${CASE}&tab=rn-cp-0`);
    render(<App />);
    await settle();
    const chip = await openFirstFact();
    act(() => {
      window.history.pushState({}, "", `/analysis/?case=${OTHER}&tab=rn-cp-0`);
      window.dispatchEvent(new PopStateEvent("popstate"));
    });
    await settle();
    expect(chip.isConnected).toBe(false);
    expect(document.activeElement).toBe(screen.getByRole("heading", { level: 1 }));
  });

  test("test_withdrawal_updates_the_open_drawer_and_refuses_its_page", async () => {
    // R2: the refetch marks the chip, and the open drawer follows it.
    await mount(`/analysis/?case=${CASE}&tab=rn-cp-0`);
    await openFirstFact();
    expect(lines()).toHaveLength(3);
    const pageReads = urls.filter((url) => url.includes("/pages/")).length;
    sectionBody = () => {
      const doc = analysis();
      doc["body"].handoffs[0].source_facts[0].withdrawn_at = "2026-09-14T10:00:00Z";
      return doc;
    };
    await fire("sources_changed");
    expect(dialog()).not.toBeNull();
    expect(dialog()!.querySelector("[data-withdrawn]")).toHaveTextContent("2026-09-14T10:00:00Z");
    expect(dialog()!.querySelector("[data-page-layer]")).toBeNull();
    expect(lines()).toHaveLength(0);
    expect(urls.filter((url) => url.includes("/pages/"))).toHaveLength(pageReads);
  });

  test("a refused page shows its state and no text", async () => {
    pageAnswer = () => ({ status: 404, body: { code: "PAGE_NOT_AVAILABLE", clears: "x" } });
    await mount(`/analysis/?case=${CASE}&tab=rn-cp-0`);
    await openFirstFact();
    expect(dialog()!.querySelector("[data-page-state='unavailable']")).not.toBeNull();
    expect(lines()).toHaveLength(0);
    expect(dialog()).not.toHaveTextContent("We are transforming");
  });

  test("test_a_rectangle_outside_the_frame_is_not_drawn_and_is_noted", async () => {
    pageAnswer = () => {
      const doc = pageDoc();
      doc["body"].frame = { x0: 0, y0: 0, x1: 612, y1: 130, y_axis: "down" };
      return { status: 200, body: doc };
    };
    await mount(`/analysis/?case=${CASE}&tab=rn-cp-0`);
    await openFirstFact();
    expect(dialog()!.querySelectorAll("[data-highlight]")).toHaveLength(0);
    expect(dialog()!.querySelector("[data-outside-frame]")).toHaveTextContent("1");
    // Only the line wholly inside the frame is placed.
    expect(lines()).toHaveLength(1);
  });

  test("a line the rendered page does not show is marked with every reason the host names (N27)", async () => {
    pageAnswer = () => {
      const doc = pageDoc();
      doc["body"].lines[1].hidden = ["render_mode_3", "near_background"];
      doc["body"].lines[2].hidden = ["under_2pt"];
      return { status: 200, body: doc };
    };
    await mount(`/analysis/?case=${CASE}&tab=rn-cp-0`);
    await openFirstFact();
    const marked = [...lines()].filter((line) => line.hasAttribute("data-hidden"));
    expect(marked.map((line) => line.getAttribute("data-hidden"))).toEqual([
      "render_mode_3 near_background",
      "under_2pt",
    ]);
    // Told, not only drawn: a screen reader hears it on the line itself.
    expect(marked[0]).toHaveTextContent(
      "not visible on the page: drawn invisible (render mode 3), the colour of its background",
    );
    expect(lines()[0]).not.toHaveAttribute("data-hidden");
    const note = dialog()!.querySelector("[data-hidden-lines]")!;
    expect(note).toHaveTextContent("2 lines on this page cannot be seen on the rendered page");
    expect(note).toHaveTextContent(
      "drawn invisible (render mode 3), the colour of its background, under 2 pt",
    );
  });

  test("a page with nothing hidden carries no hidden-text note", async () => {
    await mount(`/analysis/?case=${CASE}&tab=rn-cp-0`);
    await openFirstFact();
    expect(dialog()!.querySelector("[data-hidden-lines]")).toBeNull();
    expect(dialog()!.querySelector("[data-no-rects]")).toBeNull();
  });

  test("test_the_drawer_reads_the_visible_snapshot_not_the_pending_one", async () => {
    await mount(`/analysis/?case=${CASE}&tab=rn-cp-0`);
    await openFirstFact();
    const quote = analysis()["body"].handoffs[0].source_facts[0].matched_text;
    sectionBody = () => {
      const doc = analysis();
      doc["body"].handoffs[0].record_sha256 = "3".repeat(64);
      doc["body"].handoffs[0].source_facts = [];
      return doc;
    };
    await fire("handoff_accepted");
    // A new analytical identity is held: the drawer stays on what is shown.
    expect(document.querySelector("[data-surface-state='stale']")).not.toBeNull();
    expect(dialog()).toHaveTextContent(quote);
    expect(lines()).toHaveLength(3);
  });
});

describe("a narrative figure (N59)", () => {
  const RUN_B = "00000000-0000-4000-8000-0000000000b2";
  const REVISION = "00000000-0000-4000-8000-0000000000c3";
  const FIGURE_SOURCE = "00000000-0000-4000-8000-0000000000a1";
  const FIGURE_PAGE = `/api/v1/cases/${CASE}/runs/${RUN_B}/sources/${FIGURE_SOURCE}/pages/7`;

  test("a committee figure's chip opens its source page, claiming no rectangle", async () => {
    sectionBody = () => JSON.parse(text("../../fixtures/committee-v1.json"));
    pageAnswer = () => {
      const doc = pageDoc();
      Object.assign(doc["body"], {
        run_id: RUN_B,
        source_id: FIGURE_SOURCE,
        page: 7,
        document_sha256: "d".repeat(64),
      });
      return { status: 200, body: doc };
    };
    render(
      <MemoryRouter initialEntries={[`/committee/?case=${CASE}&run=${RUN_B}&revision=${REVISION}`]}>
        <Workspace section="committee" />
      </MemoryRouter>,
    );
    await settle();
    const chip = screen.getByRole("button", { name: "Evidence CP-1 p.7: Coverage 2.1x" });
    expect(chip).toHaveAttribute("aria-expanded", "false");
    act(() => fireEvent.click(chip));
    await settle();
    expect(urls).toContain(FIGURE_PAGE);
    expect(chip).toHaveAttribute("aria-expanded", "true");
    expect(dialog()).toHaveTextContent("CP-1 source dddddddd…dddd · page 7");
    expect(lines()).toHaveLength(3);
    expect(dialog()!.querySelectorAll("[data-highlight]")).toHaveLength(0);
    expect(dialog()!.querySelector("[data-no-rects]")).not.toBeNull();
    expect(dialog()).toHaveTextContent("Coverage 2.1x");
  });
});

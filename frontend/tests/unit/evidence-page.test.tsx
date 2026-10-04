// The evidence drawer bound to the visible snapshot, its text layer and the
// highlight geometry (brief 4.4, decisions 7-9; R1 and R2).
import { readFileSync } from "node:fs";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
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

/** The module's citations lead its Audit tab (D60). */
function openAudit() {
  const tab = document.querySelector<HTMLElement>("[data-depth-tab='audit']");
  if (tab && tab.getAttribute("aria-selected") !== "true") act(() => fireEvent.click(tab));
}

async function openFirstFact() {
  openAudit();
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

  test("a fact the host re-anchored names the page the module cited (D94)", async () => {
    expect(dialog()).toBeNull();
    sectionBody = () => {
      const body = analysis();
      for (const handoff of body.body.handoffs) {
        for (const fact of handoff.source_facts) {
          if (fact.source_id === SOURCE) fact.cited_page = 4;
        }
      }
      return body;
    };
    await mount(`/analysis/?case=${CASE}&tab=rn-cp-0`);
    await openFirstFact();
    expect(dialog()!.querySelector("[data-reanchored]")).toHaveTextContent("Cited p.4, found p.1");
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
    openAudit();
    expect(document.querySelector(`[data-fact-chip='${SOURCE}']`)).not.toBeNull();
    expect(dialog()).toBeNull();
  });

  test("switching cases during inventory close cannot open the old source", async () => {
    sectionBody = (url) =>
      url.includes(OTHER)
        ? JSON.parse(text("../../fixtures/analysis.json").replaceAll(CASE, OTHER))
        : analysis();
    window.history.pushState({}, "", `/analysis/?case=${CASE}&tab=rn-cp-0`);
    render(<App />);
    await settle();
    act(() => fireEvent.click(document.querySelector("[data-documents-open]")!));
    const source = document.querySelector(
      `[data-documents-drawer] [data-register-fact='${SOURCE}']`,
    )!;
    act(() => fireEvent.click(source));
    act(() => {
      window.history.pushState({}, "", `/analysis/?case=${OTHER}&tab=rn-cp-0`);
      window.dispatchEvent(new PopStateEvent("popstate"));
    });
    await settle();
    expect(urls.some((url) => url.includes(OTHER))).toBe(true);
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
    // The event independently rechecks an open page while the section reloads.
    expect(urls.filter((url) => url.includes("/pages/")).length).toBeGreaterThan(pageReads);
  });

  test("a source event rechecks the open page even when the section read fails", async () => {
    let stale = false;
    const firstFetch = globalThis.fetch;
    vi.stubGlobal("fetch", async (...args: Parameters<typeof fetch>) => {
      const url = String(args[0]);
      if (stale && url.includes("/pages/")) return new Response("", { status: 404 });
      if (stale)
        return new Response(JSON.stringify({ code: "STORE_UNAVAILABLE", clears: "retry" }), {
          status: 500,
        });
      return firstFetch(...args);
    });
    await mount(`/analysis/?case=${CASE}&tab=rn-cp-0`);
    await openFirstFact();
    expect(lines()).toHaveLength(3);
    stale = true;
    await fire("sources_changed");
    expect(dialog()).not.toBeNull();
    expect(lines()).toHaveLength(0);
    expect(dialog()!.querySelector('[data-page-state="unavailable"]')).toBeInTheDocument();
  });

  test("a replacement stream rechecks withdrawn evidence when the section read fails", async () => {
    let withdrawn = false;
    const firstFetch = globalThis.fetch;
    vi.stubGlobal("fetch", async (...args: Parameters<typeof fetch>) => {
      const url = String(args[0]);
      if (withdrawn && url.includes("/pages/")) return new Response("", { status: 404 });
      if (withdrawn)
        return new Response(JSON.stringify({ code: "STORE_UNAVAILABLE", clears: "retry" }), {
          status: 500,
        });
      return firstFetch(...args);
    });
    await mount(`/analysis/?case=${CASE}&tab=rn-cp-0`);
    FakeSource.all[0]!.readyState = FakeSource.OPEN;
    await fire("open");
    await openFirstFact();
    expect(lines()).toHaveLength(3);
    withdrawn = true;
    FakeSource.all[0]!.readyState = FakeSource.CLOSED;
    await fire("error");
    await waitFor(() => expect(FakeSource.all).toHaveLength(2), { timeout: 2500 });
    FakeSource.all[1]!.readyState = FakeSource.OPEN;
    await fire("open");
    expect(dialog()).not.toBeNull();
    expect(lines()).toHaveLength(0);
    expect(dialog()!.querySelector('[data-page-state="unavailable"]')).toBeInTheDocument();
  });

  test("a recheck keeps the open page on screen, and one that never answers keeps it", async () => {
    await mount(`/analysis/?case=${CASE}&tab=rn-cp-0`);
    await openFirstFact();
    expect(lines()).toHaveLength(3);
    let drop: () => void = () => {};
    const firstFetch = globalThis.fetch;
    vi.stubGlobal("fetch", (...args: Parameters<typeof fetch>) =>
      String(args[0]).includes("/pages/")
        ? new Promise<Response>((_resolve, reject) => {
            drop = () => reject(new TypeError("offline"));
          })
        : firstFetch(...args),
    );
    // The server ends every tail after five minutes; the browser reopens it.
    FakeSource.all[0]!.readyState = FakeSource.OPEN;
    await fire("open");
    expect(lines()).toHaveLength(3);
    expect(dialog()!.querySelector("[data-page-state]")).toBeNull();
    await act(async () => drop());
    await settle();
    expect(lines()).toHaveLength(3);
    expect(dialog()!.querySelector("[data-page-state]")).toBeNull();
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
      doc["body"].lines[2].hidden = ["colorant_none", "under_2pt"];
      return { status: 200, body: doc };
    };
    await mount(`/analysis/?case=${CASE}&tab=rn-cp-0`);
    await openFirstFact();
    const marked = [...lines()].filter((line) => line.hasAttribute("data-hidden"));
    expect(marked.map((line) => line.getAttribute("data-hidden"))).toEqual([
      "render_mode_3 near_background",
      "colorant_none under_2pt",
    ]);
    // Told, not only drawn: a screen reader hears it on the line itself.
    expect(marked[0]).toHaveTextContent(
      "not visible on the page: drawn invisible (render mode 3), the colour of its background",
    );
    expect(lines()[0]).not.toHaveAttribute("data-hidden");
    const note = dialog()!.querySelector("[data-hidden-lines]")!;
    expect(note).toHaveTextContent("2 lines on this page cannot be seen on the rendered page");
    expect(note).toHaveTextContent(
      "drawn invisible (render mode 3), the colour of its background, painted with no ink (colorant None), under 2 pt",
    );
  });

  test("a page with nothing hidden carries no hidden-text note", async () => {
    await mount(`/analysis/?case=${CASE}&tab=rn-cp-0`);
    await openFirstFact();
    expect(dialog()!.querySelector("[data-hidden-lines]")).toBeNull();
    expect(dialog()!.querySelector("[data-no-rects]")).toBeNull();
  });

  test("the drawer shows the whole source line with the cited excerpt marked", async () => {
    sectionBody = () => {
      const doc = analysis();
      doc["body"].handoffs[0].source_facts[0].line = {
        before: "We do not ",
        excerpt: doc["body"].handoffs[0].source_facts[0].matched_text,
        after: " (unaudited)",
        recorded: true,
      };
      return doc;
    };
    await mount(`/analysis/?case=${CASE}&tab=rn-cp-0`);
    await openFirstFact();
    const quote = analysis()["body"].handoffs[0].source_facts[0].matched_text;
    const shown = dialog()!.querySelector("blockquote.matched")!;
    expect(shown.textContent).toBe(`We do not ${quote} (unaudited)`);
    expect(shown.querySelector("mark")!.textContent).toBe(quote);
    expect(dialog()).toHaveTextContent("Source line · the cited excerpt marked");
  });

  test("test_a_marker_chip_in_the_analysis_opens_the_source_drawer_at_its_line", async () => {
    // D107: the module's text shows [C1] as a chip, never the line; pressed,
    // the source drawer opens at the cited page, the whole line shown there
    // with the excerpt marked -- the one place it is shown.
    sectionBody = () => {
      const doc = analysis();
      doc["body"].handoffs[0].source_facts[0].line = {
        before: "We do not ",
        excerpt: doc["body"].handoffs[0].source_facts[0].matched_text,
        after: " (unaudited)",
        recorded: true,
      };
      return doc;
    };
    await mount(`/analysis/?case=${CASE}&tab=rn-cp-0`);
    const quote = analysis()["body"].handoffs[0].source_facts[0].matched_text;
    // The text's chip (the Audit tab's fact chip names the same citation).
    const chip = document.querySelector<HTMLButtonElement>(
      "[data-analysis] button[data-marker-chip='1']",
    )!;
    expect(chip).toHaveAccessibleName("C1, citation 1: CVNA_10K_Annual_Report_FY2025.htm, page 1");
    expect(chip).toHaveTextContent(/^C1$/);
    expect(chip).toHaveAttribute("aria-haspopup", "dialog");
    expect(document.querySelector("[data-analysis]")!.textContent).not.toContain("We do not");
    // A button: reached and pressed from the keyboard like any control.
    chip.focus();
    expect(document.activeElement).toBe(chip);
    act(() => fireEvent.click(chip));
    await settle();
    expect(urls).toContain(PAGE_PATH);
    expect(chip).toHaveAttribute("aria-expanded", "true");
    const shown = dialog()!.querySelector("blockquote.matched")!;
    expect(shown.textContent).toBe(`We do not ${quote} (unaudited)`);
    expect(shown.querySelector("mark")!.textContent).toBe(quote);
  });

  test("test_each_marker_chip_opens_its_own_citation", async () => {
    // The MK2 audit: C2 and C3 open the second and third citations, by their
    // place in the handoff's source facts, never the first or the next.
    sectionBody = () => {
      const doc = analysis();
      const handoff = doc["body"].handoffs[0];
      const fact = handoff.source_facts[0];
      handoff.source_facts = [1, 2, 3].map((n) => ({
        ...fact,
        page: n,
        filename: `doc-${n}.htm`,
        marker: n,
      }));
      handoff.model_analysis += "\n\nThree figures [C1], [C2] and [C3].";
      return doc;
    };
    await mount(`/analysis/?case=${CASE}&tab=rn-cp-0`);
    for (const n of [2, 3, 1]) {
      const chip = document.querySelector<HTMLButtonElement>(`button[data-marker-chip='${n}']`)!;
      expect(chip).toHaveAccessibleName(`C${n}, citation ${n}: doc-${n}.htm, page ${n}`);
      act(() => fireEvent.click(chip));
      await settle();
      expect(dialog()).toHaveTextContent(`doc-${n}.htm · page ${n}`);
      expect(urls).toContain(`/api/v1/cases/${CASE}/runs/${RUN}/sources/${SOURCE}/pages/${n}`);
      expect(chip).toHaveAttribute("aria-expanded", "true");
      act(() => fireEvent.keyDown(dialog()!, { key: "Escape" }));
      await settle();
    }
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
    const chip = screen.getByRole("button", { name: "CP-1 C1 · p.7, citation 1 of CP-1, page 7" });
    // Compact (D107): the narrative shows the excerpt, never its line or mark.
    expect(document.querySelector("q.figq")).toHaveTextContent("Coverage 2.1x");
    expect(document.querySelector("q.figq mark")).toBeNull();
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
    // D105: the figure's whole line is served with it, its excerpt marked.
    expect(dialog()!.querySelector("blockquote.matched mark")).toHaveTextContent("Coverage 2.1x");
  });

  test("test_an_artifacts_marker_chip_opens_its_citations_source_page", async () => {
    // D107: the saved artifact's [C1] is a chip naming its citation; pressed,
    // it opens the source drawer at that citation's page and line.
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
    const chip = screen.getByRole("button", { name: "C1, citation 1: CP-1 source, page 7" });
    expect(chip).toHaveTextContent(/^C1$/);
    act(() => fireEvent.click(chip));
    await settle();
    expect(urls).toContain(FIGURE_PAGE);
    expect(chip).toHaveAttribute("aria-expanded", "true");
    expect(dialog()!.querySelector("blockquote.matched mark")).toHaveTextContent("Coverage 2.1x");
    // [C2] names an unverified citation: labelled, and nothing to press.
    const inert = document.querySelector("[data-artifact-formatted] [data-unverified-marker]")!;
    expect(inert).toHaveTextContent("citation 2, C2 · unverified – page 9");
    expect(inert.closest("button")).toBeNull();
  });

  test("test_each_artifact_marker_chip_opens_its_own_citation", async () => {
    // The MK2 audit: an artifact's C2 and C3 open its second and third
    // record citations (`citation_index` 1 and 2), each at its own page.
    sectionBody = () => {
      const doc = JSON.parse(text("../../fixtures/committee-v1.json"));
      const artifact = doc["body"].artifacts[0];
      const figure = artifact.figures[0];
      artifact.figures = [0, 1, 2].map((index) => ({
        ...figure,
        citation_index: index,
        page: 7 + index,
        marker: index + 1,
      }));
      artifact.markdown += " Also [C3].";
      artifact.unverified = [];
      return doc;
    };
    render(
      <MemoryRouter initialEntries={[`/committee/?case=${CASE}&run=${RUN_B}&revision=${REVISION}`]}>
        <Workspace section="committee" />
      </MemoryRouter>,
    );
    await settle();
    for (const n of [2, 3]) {
      const page = 6 + n;
      const chip = screen.getByRole("button", {
        name: `C${n}, citation ${n}: CP-1 source, page ${page}`,
      });
      act(() => fireEvent.click(chip));
      await settle();
      expect(dialog()).toHaveTextContent(`page ${page}`);
      expect(urls).toContain(
        `/api/v1/cases/${CASE}/runs/${RUN_B}/sources/${FIGURE_SOURCE}/pages/${page}`,
      );
      act(() => fireEvent.keyDown(dialog()!, { key: "Escape" }));
      await settle();
    }
  });

  const openFigure = async (page: () => { status: number; body: unknown }) => {
    sectionBody = () => JSON.parse(text("../../fixtures/committee-v1.json"));
    pageAnswer = page;
    render(
      <MemoryRouter initialEntries={[`/committee/?case=${CASE}&run=${RUN_B}&revision=${REVISION}`]}>
        <Workspace section="committee" />
      </MemoryRouter>,
    );
    await settle();
    act(() =>
      fireEvent.click(
        screen.getByRole("button", { name: "CP-1 C1 · p.7, citation 1 of CP-1, page 7" }),
      ),
    );
    await settle();
  };

  // Security review note 2: the read binds case, run, source and page; the
  // page must also be of the document the figure names.
  test("a page of another document is refused, and none of its text is shown", async () => {
    await openFigure(() => {
      const doc = pageDoc();
      Object.assign(doc["body"], { run_id: RUN_B, source_id: FIGURE_SOURCE, page: 7 });
      return { status: 200, body: doc };
    });
    expect(dialog()!.querySelector("[data-page-state='error']")).toHaveTextContent(
      "WIRE_IDENTITY_MISMATCH",
    );
    expect(lines()).toHaveLength(0);
  });

  // N93: a saved figure carries its source's withdrawal, so an unavailable
  // page no longer guesses at one; the drawer states a withdrawal it is served.
  test("an unavailable page of a saved figure states only what it is served", async () => {
    await openFigure(() => ({ status: 404, body: { code: "PAGE_NOT_AVAILABLE", clears: "x" } }));
    expect(dialog()!.querySelector("[data-page-state='unavailable']")).not.toHaveTextContent(
      "may have been withdrawn",
    );
  });
});

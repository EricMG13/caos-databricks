// What the workspace does when it stops being live (findings FE-2, FE-3), and
// what it says and where focus goes when the reader moves (FE-4, FE-6).
//
// Each test drives the real `Workspace` through a stubbed `fetch` and a fake
// `EventSource`, the way `workspace-refresh.test.tsx` does: the behaviour is a
// property of the mounted section, not of a function called on its own.
import { readFileSync } from "node:fs";
import { act, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useNavigate } from "react-router";
import { Workspace } from "@/app/Workspace";
import { focusSectionHeading, pageTitle } from "@/app/heading";
import { Announcer, useAnnouncer } from "@/states/Announcer";
import { CommandOutcome } from "@/sections/run/controls";
import { RunSection } from "@/sections/run/RunSection";
import { parseRunSectionDocument, parseUploadDocument } from "@/wire/v1";
import type { Section } from "@/wire";

const text = (path: string): string => readFileSync(new URL(path, import.meta.url), "utf8");
const json = (path: string): Record<string, unknown> => JSON.parse(text(path));

const CASE = "00000000-0000-4000-8000-000000000001";
const OTHER = "00000000-0000-4000-8000-0000000000ff";
const RUN = "00000000-0000-4000-8000-0000000000b2";
const REVISION = "00000000-0000-4000-8000-0000000000c3";

const analysis = () => json("../../fixtures/analysis.json");
const report = () => json("../../fixtures/report-v1.json");

class FakeSource {
  static CONNECTING = 0;
  static OPEN = 1;
  static CLOSED = 2;
  static all: FakeSource[] = [];
  readonly listeners = new Map<string, () => void>();
  readyState = FakeSource.CONNECTING;
  closed = false;
  constructor(readonly url: string) {
    FakeSource.all.push(this);
  }
  addEventListener(name: string, handler: () => void) {
    this.listeners.set(name, handler);
  }
  close() {
    this.closed = true;
    this.readyState = FakeSource.CLOSED;
  }
}

interface Sent {
  url: string;
  answer(body: unknown, status?: number, headers?: Record<string, string>): void;
  fail(): void;
}
let sent: Sent[] = [];

beforeEach(() => {
  sent = [];
  FakeSource.all = [];
  vi.stubGlobal("EventSource", FakeSource);
  vi.stubGlobal(
    "fetch",
    (url: string) =>
      new Promise<Response>((resolve, reject) => {
        sent.push({
          url,
          answer: (body, status = 200, headers = {}) =>
            resolve(new Response(JSON.stringify(body), { status, headers })),
          fail: () => reject(new TypeError("NetworkError")),
        });
      }),
  );
});
afterEach(() => vi.unstubAllGlobals());

const settle = () => act(() => new Promise((resolve) => setTimeout(resolve, 0)));

async function answer(index: number, body: unknown, status = 200, headers = {}) {
  sent[index]!.answer(body, status, headers);
  await settle();
}

async function fire(name: string) {
  const source = FakeSource.all.at(-1)!;
  act(() => source.listeners.get(name)?.());
  await settle();
}

function Switch({ to }: { to: string }) {
  const go = useNavigate();
  return (
    <button type="button" data-switch onClick={() => go(to)}>
      switch
    </button>
  );
}

async function mount(section: Section, path: string, to = `/analysis/?case=${OTHER}`) {
  const view = render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route
          path="*"
          element={
            <>
              <Workspace section={section} />
              <Switch to={to} />
            </>
          }
        />
      </Routes>
    </MemoryRouter>,
  );
  await settle();
  return view;
}

const region = (container: HTMLElement) => container.querySelector("main#body")!;

describe("a workspace that has stopped being live", () => {
  // DocumentReadContext orders Workspace and useDocumentRefetch reads together.
  test.each([true, false])(
    "an older workspace read cannot supersede a command refresh (parent answers first: %s)",
    async (parentFirst) => {
      const fixture = parseUploadDocument(json("../../fixtures/upload.json"));
      const original = {
        ...fixture,
        chrome: { ...fixture.chrome, actions: [{ action: "WITHDRAW_SOURCE", refusal: null }] },
      };
      const source = original.body.sources.find((row) => row.withdrawn_at === null)!;
      const { container } = await mount("upload", `/upload/?case=${original.body.case_id}`);
      await answer(0, original);
      await fire("open");
      fireEvent.click(screen.getByRole("button", { name: `Withdraw ${source.filename}` }));
      fireEvent.click(screen.getByRole("button", { name: "Confirm Withdraw source" }));
      await answer(2, { case_id: original.body.case_id, source_id: source.source_id });
      expect(sent).toHaveLength(4);
      const newer = {
        ...original,
        body: {
          ...original.body,
          sources: original.body.sources.map((row) =>
            row.source_id === source.source_id
              ? { ...row, withdrawn_at: "2026-09-28T09:00:00Z" }
              : row,
          ),
        },
      };
      // Equal timestamps are intentional: request order must not depend on clock precision.
      if (parentFirst) await answer(1, original);
      await answer(3, newer);
      if (!parentFirst) await answer(1, original);
      expect(container.querySelector(`[data-source="${source.source_id}"]`)).toHaveClass("wd");
      // A discarded parent read must release its flight so the next event can refresh.
      await fire("sources_changed");
      expect(sent).toHaveLength(5);
      await answer(4, newer);
    },
  );

  test.each([true, false])(
    "a newer workspace read supersedes an older command refresh (parent answers first: %s)",
    async (parentFirst) => {
      const fixture = parseUploadDocument(json("../../fixtures/upload.json"));
      const original = {
        ...fixture,
        chrome: { ...fixture.chrome, actions: [{ action: "WITHDRAW_SOURCE", refusal: null }] },
      };
      const source = original.body.sources.find((row) => row.withdrawn_at === null)!;
      const { container } = await mount("upload", `/upload/?case=${original.body.case_id}`);
      await answer(0, original);
      fireEvent.click(screen.getByRole("button", { name: `Withdraw ${source.filename}` }));
      fireEvent.click(screen.getByRole("button", { name: "Confirm Withdraw source" }));
      await answer(1, { case_id: original.body.case_id, source_id: source.source_id });
      await fire("sources_changed");
      const newer = {
        ...original,
        body: {
          ...original.body,
          sources: original.body.sources.map((row) =>
            row.source_id === source.source_id
              ? { ...row, withdrawn_at: "2026-09-28T09:00:00Z" }
              : row,
          ),
        },
      };
      if (parentFirst) await answer(3, newer);
      await answer(2, original);
      if (!parentFirst) await answer(3, newer);
      expect(container.querySelector(`[data-source="${source.source_id}"]`)).toHaveClass("wd");
    },
  );

  test("a failed command refresh still reports failure after discarding an older workspace read", async () => {
    const fixture = parseUploadDocument(json("../../fixtures/upload.json"));
    const original = {
      ...fixture,
      chrome: { ...fixture.chrome, actions: [{ action: "WITHDRAW_SOURCE", refusal: null }] },
    };
    const source = original.body.sources.find((row) => row.withdrawn_at === null)!;
    const { container } = await mount("upload", `/upload/?case=${original.body.case_id}`);
    await answer(0, original);
    await fire("open");
    fireEvent.click(screen.getByRole("button", { name: `Withdraw ${source.filename}` }));
    fireEvent.click(screen.getByRole("button", { name: "Confirm Withdraw source" }));
    await answer(2, { case_id: original.body.case_id, source_id: source.source_id });
    await answer(1, original);
    sent[3]!.fail();
    await settle();
    expect(container.querySelector("[data-withdraw-refresh-failed]")).not.toBeNull();
  });

  test("reloading a pending run does not discard a workspace read already in flight", async () => {
    const initial = parseRunSectionDocument(json("../../fixtures/run/frames/1.json"));
    const { container } = await mount("run", `/run/?case=${initial.body.case_id}`);
    await answer(0, initial);
    const next = {
      ...initial,
      body: {
        ...initial.body,
        displayed_run_id: OTHER,
        latest_run_id: OTHER,
        run: { ...initial.body.run!, run_id: OTHER },
        runs: initial.body.runs.map((run) =>
          run.run_id === initial.body.displayed_run_id ? { ...run, run_id: OTHER } : run,
        ),
      },
    };
    await fire("runs_changed");
    await answer(1, next);
    await fire("run_progress");
    fireEvent.click(container.querySelector("[data-surface-state='stale'] button")!);
    await settle();
    // An authoritative refusal must still replace the newly mounted Run reader.
    await answer(2, {}, 404);
    expect(container.querySelector("[data-surface-state='unavailable']")).not.toBeNull();
  });

  // FE-2: the reader keeps what the server last served. Replacing it with
  // "Offline" throws away the document and every unsaved field under it.
  test("test_a_failed_refetch_keeps_the_displayed_document_and_marks_it_not_live", async () => {
    const { container } = await mount("analysis", `/analysis/?case=${CASE}`);
    await answer(0, analysis());
    const shown = () => region(container).querySelector("[data-confidence]")?.textContent ?? null;
    expect(shown()).not.toBeNull();
    await fire("handoff_accepted");
    await act(async () => {
      sent[1]!.fail();
      await settle();
    });
    expect(shown()).not.toBeNull();
    expect(region(container).querySelector("[data-surface-state='offline']")).toBeNull();
    const banner = container.querySelector("[data-not-live='refresh']")!;
    expect(banner).not.toBeNull();
    expect(banner).toHaveAttribute("role", "status");
    // A document that answers again clears it.
    await fire("handoff_accepted");
    await answer(2, analysis());
    expect(container.querySelector("[data-not-live='refresh']")).toBeNull();
  });

  test("test_a_refused_refetch_names_its_code_and_does_not_replace_the_document", async () => {
    const { container } = await mount("analysis", `/analysis/?case=${CASE}`);
    await answer(0, analysis());
    await fire("handoff_accepted");
    await answer(1, { code: "STORE_UNAVAILABLE", clears: "the store answers" }, 503);
    expect(region(container).querySelector("[data-confidence]")).not.toBeNull();
    expect(container.querySelector("[data-not-live='refresh']")).toHaveTextContent(
      "STORE_UNAVAILABLE",
    );
  });

  // FE-2, the consequence that matters: an approver's committee narrative is
  // not kept anywhere else, so a remount loses it.
  test("test_an_unsaved_draft_survives_a_refetch_that_did_not_answer", async () => {
    const { container } = await mount(
      "report",
      `/report/?case=${CASE}&run=${RUN}&revision=${REVISION}`,
    );
    await answer(0, report());
    const draft = () => container.querySelector<HTMLTextAreaElement>("#narrative-draft");
    expect(draft()).not.toBeNull();
    fireEvent.change(draft()!, { target: { value: "Three paragraphs of committee prose." } });
    expect(draft()!.value).toBe("Three paragraphs of committee prose.");
    await fire("filing_changed");
    await act(async () => {
      sent[1]!.fail();
      await settle();
    });
    expect(draft()).not.toBeNull();
    expect(draft()!.value).toBe("Three paragraphs of committee prose.");
  });

  // FE-3: EventSource gives up for good on a non-200 answer. The workspace
  // does not: it says so, and the tail reopens itself.
  test("test_a_refused_tail_says_live_updates_are_paused_and_reopens", async () => {
    vi.useFakeTimers();
    try {
      const view = render(
        <MemoryRouter initialEntries={[`/analysis/?case=${CASE}`]}>
          <Workspace section="analysis" />
        </MemoryRouter>,
      );
      await act(async () => {
        await vi.advanceTimersByTimeAsync(0);
      });
      sent[0]!.answer(analysis());
      await act(async () => {
        await vi.advanceTimersByTimeAsync(0);
      });
      const tail = FakeSource.all[0]!;
      tail.readyState = FakeSource.CLOSED;
      await act(async () => {
        tail.listeners.get("error")?.();
        await vi.advanceTimersByTimeAsync(0);
      });
      // The document read decides: it answers, so the case is still there.
      sent[1]!.answer(analysis());
      await act(async () => {
        await vi.advanceTimersByTimeAsync(0);
      });
      const paused = view.container.querySelector("[data-not-live='tail']")!;
      expect(paused).not.toBeNull();
      expect(paused).toHaveAttribute("role", "status");
      expect(paused).toHaveTextContent("Live updates paused");
      // The banner sits above the index, which is directly before its panel:
      // the wide layout sets those two side by side.
      const tabs = view.container.querySelector("[data-section-tabs]")!;
      expect(paused.compareDocumentPosition(tabs) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
      expect(tabs.nextElementSibling).toHaveAttribute("role", "tabpanel");
      expect(FakeSource.all).toHaveLength(1);
      await act(async () => {
        await vi.advanceTimersByTimeAsync(1_000);
      });
      expect(FakeSource.all).toHaveLength(2);
      await act(async () => {
        FakeSource.all[1]!.listeners.get("open")?.();
        await vi.advanceTimersByTimeAsync(0);
      });
      expect(view.container.querySelector("[data-not-live='tail']")).toBeNull();
    } finally {
      vi.useRealTimers();
    }
  });

  test("test_a_case_that_is_gone_stops_the_tail_and_the_region_is_unavailable", async () => {
    const { container } = await mount("analysis", `/analysis/?case=${CASE}`);
    await answer(0, analysis());
    FakeSource.all[0]!.readyState = FakeSource.CLOSED;
    await fire("error");
    await answer(1, { code: "CASE_NOT_FOUND", clears: "x" }, 404);
    expect(region(container).querySelector("[data-surface-state='unavailable']")).not.toBeNull();
    expect(container.querySelector("[data-not-live='tail']")).toBeNull();
  });
});

describe("where the reader is, and what they are told", () => {
  // FE-4: the tab said "CAOS" on every view, and nothing announced the page.
  test("test_the_page_title_names_the_section_and_the_case", async () => {
    expect(pageTitle("Analysis", null)).toBe("Analysis · CAOS");
    expect(pageTitle("Report", "Carvana Co.")).toBe("Report · Carvana Co. · CAOS");
    await mount("analysis", `/analysis/?case=${CASE}`);
    await answer(0, analysis());
    expect(document.title).toContain("Analysis");
    expect(document.title).toContain("CAOS");
  });

  // FE-4: activating a rail link unmounted the link. Focus fell to <body>,
  // and the next Tab started again at the top of the document.
  test("test_a_navigation_moves_focus_to_the_section_heading", async () => {
    const { container } = await mount("analysis", `/analysis/?case=${CASE}`);
    await answer(0, analysis());
    const heading = screen.getByRole("heading", { level: 1 });
    expect(document.activeElement).not.toBe(heading);
    act(() => fireEvent.click(container.querySelector("[data-switch]")!));
    await settle();
    expect(document.activeElement).toBe(heading);
    expect(heading).toHaveAttribute("tabindex", "-1");
  });

  test("focusSectionHeading is a no-op where there is no workspace on the page", () => {
    expect(() => focusSectionHeading()).not.toThrow();
  });

  // FE-6: one region per section, always there, so a sentence written into it
  // is announced rather than inserted already populated.
  test("test_the_section_carries_one_persistent_polite_live_region", async () => {
    const { container } = await mount("analysis", `/analysis/?case=${CASE}`);
    const announcer = container.querySelectorAll("[data-announcer]");
    expect(announcer).toHaveLength(1);
    expect(announcer[0]).toHaveAttribute("aria-live", "polite");
    expect(announcer[0]).toHaveAttribute("role", "status");
    await answer(0, analysis());
    expect(container.querySelectorAll("[data-announcer]")).toHaveLength(1);
  });
});

describe("what a screen reader is told about a command and a run", () => {
  test("test_a_command_success_is_announced_and_carries_role_status", () => {
    const { container } = render(
      <Announcer>
        <CommandOutcome
          result={{ kind: "ok", status: 201, receipt: {}, replayed: false }}
          success="Run created."
        />
      </Announcer>,
    );
    const note = container.querySelector("[data-command-success]")!;
    expect(note).toHaveAttribute("role", "status");
    expect(container.querySelector("[data-announcer]")).toHaveTextContent("Run created");
  });

  test("useAnnouncer outside a provider says nothing rather than throwing", () => {
    function Says() {
      const say = useAnnouncer();
      return (
        <button type="button" onClick={() => say("nowhere")}>
          say
        </button>
      );
    }
    render(<Says />);
    expect(() => fireEvent.click(screen.getByRole("button", { name: "say" }))).not.toThrow();
  });

  // FE-6: the run's status moves under the reader, driven by the tail.
  test("test_a_run_status_transition_is_announced", () => {
    const first = parseRunSectionDocument(json("../../fixtures/run/frames/1.json"));
    // The fixture stream never ends, so the terminal frame is made here: what
    // is under test is that the move is said, not which status it moved to.
    const ended = json("../../fixtures/run/frames/4.json");
    const endedRun = (ended["body"] as Record<string, unknown>)["run"] as Record<string, unknown>;
    endedRun["status"] = "COMPLETE";
    const later = parseRunSectionDocument(ended);
    const { container, rerender } = render(
      <MemoryRouter>
        <Announcer>
          <RunSection document={first} tab={null} />
        </Announcer>
      </MemoryRouter>,
    );
    expect(container.querySelector("[data-announcer]")).toHaveTextContent("");
    rerender(
      <MemoryRouter>
        <Announcer>
          <RunSection document={later} tab={null} />
        </Announcer>
      </MemoryRouter>,
    );
    expect(container.querySelector("[data-announcer]")).toHaveTextContent(
      `Run ${later.body.run!.status}.`,
    );
  });
});

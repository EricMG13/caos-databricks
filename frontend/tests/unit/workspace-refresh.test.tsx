// The workspace under events (brief 4.4, decisions 2, 5 and 6): which names
// refetch, one fetch in flight, reconnects, refusals, late responses, the
// stale view held until Reload, withdrawal over a stale view, and local state
// kept through an ordinary refresh.
import { readFileSync } from "node:fs";
import { act, fireEvent, render } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useNavigate } from "react-router";
import { Workspace } from "@/app/Workspace";
import type { Section } from "@/wire";

const text = (path: string): string => readFileSync(new URL(path, import.meta.url), "utf8");
const json = (path: string): Record<string, unknown> => JSON.parse(text(path));

const CASE = "00000000-0000-4000-8000-000000000001";
const OTHER = "00000000-0000-4000-8000-0000000000ff";
const RUN = "00000000-0000-4000-8000-0000000000b2";
const REVISION = "00000000-0000-4000-8000-0000000000c3";
// The run `fixtures/analysis.json` displays.
const DISPLAYED = "00000000-0000-4000-8000-0000000000a1";
const analysis = () => json("../../fixtures/analysis.json");
const otherCase = () => JSON.parse(text("../../fixtures/analysis.json").replaceAll(CASE, OTHER));
const model = () => ({
  chrome: {
    subject: { case_id: CASE, title: "Issuer" },
    served_role: { global_role: "READER", standing: "READER" },
    actions: [],
  },
  body: {
    case_id: CASE,
    latest_run_id: RUN,
    displayed_run_id: RUN,
    subject: null,
    forecast: null,
    unavailable_reason: "NO_ACCEPTED_FORECAST",
  },
  observed_at: "2026-09-14T10:00:00Z",
  observed_empty: false,
  status: "complete",
  notes: [],
});
const report = () => ({
  chrome: {
    subject: { case_id: CASE, title: "Issuer" },
    served_role: { global_role: "READER", standing: "READER" },
    actions: [],
  },
  body: {
    case_id: CASE,
    displayed_run_id: RUN,
    revision_id: REVISION,
    payload_sha256: "a".repeat(64),
    case_title: "Issuer",
    artifacts: [],
    narrative: [],
    revisions: [],
  },
  observed_at: "2026-09-14T10:00:00Z",
  observed_empty: false,
  status: "complete",
  notes: [],
});
const committee = () => ({
  ...report(),
  body: {
    ...report().body,
    state: "frozen",
    signed_by: [CASE],
    frozen_by: RUN,
    filed_by: null,
    render_url: "/render",
    package_url: null,
    receipt: null,
  },
});
const filedCommittee = () => json("../../fixtures/committee-v1.json");

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
  signal: AbortSignal | undefined;
  answer(body: unknown, status?: number): void;
  fail(): void;
}
let sent: Sent[] = [];

beforeEach(() => {
  sent = [];
  FakeSource.all = [];
  vi.stubGlobal("EventSource", FakeSource);
  vi.stubGlobal(
    "fetch",
    (url: string, init?: RequestInit) =>
      new Promise<Response>((resolve, reject) => {
        sent.push({
          url,
          signal: init?.signal ?? undefined,
          answer: (body, status = 200) => resolve(new Response(JSON.stringify(body), { status })),
          fail: () => reject(new TypeError("NetworkError")),
        });
      }),
  );
});
afterEach(() => vi.unstubAllGlobals());

const settle = () => act(() => new Promise((resolve) => setTimeout(resolve, 0)));

async function answer(index: number, body: unknown, status = 200) {
  sent[index]!.answer(body, status);
  await settle();
}

async function fire(name: string) {
  const source = FakeSource.all.at(-1)!;
  act(() => source.listeners.get(name)?.());
  await settle();
}

function SwitchCase() {
  const go = useNavigate();
  return (
    <button type="button" data-switch onClick={() => go(`/analysis/?case=${OTHER}&tab=rn-cp-0`)}>
      switch
    </button>
  );
}

const QUALIFICATION = "a".repeat(64);

function AddQualification() {
  const go = useNavigate();
  return (
    <button
      type="button"
      data-qualify
      onClick={() => go(`/analysis/?case=${CASE}&qualification=${QUALIFICATION}&tab=rn-cp-0`)}
    >
      qualify
    </button>
  );
}

async function mount(section: Section, path: string) {
  const view = render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route
          path="*"
          element={
            <>
              <Workspace section={section} />
              <SwitchCase />
              <AddQualification />
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
const confidence = (container: HTMLElement) =>
  region(container).querySelector("[data-confidence]")?.textContent ?? null;

function changed(body: Record<string, unknown>, edit: (b: Record<string, unknown>) => void) {
  const copy = structuredClone(body);
  edit(copy["body"] as Record<string, unknown>);
  return copy;
}

describe("the workspace under its event tail", () => {
  test("test_an_event_refetches_only_the_sections_it_names", async () => {
    await mount("upload", `/upload/?case=${CASE}`);
    expect(sent).toHaveLength(1);
    await answer(0, json("../../fixtures/upload.json"));
    expect(FakeSource.all[0]!.url).toBe(`/api/v1/cases/${CASE}/events`);
    for (const name of ["run_progress", "handoff_accepted", "run_terminal", "runs_changed"]) {
      await fire(name);
    }
    expect(sent).toHaveLength(1);
    await fire("sources_changed");
    expect(sent).toHaveLength(2);
  });

  test("an analysis workspace ignores run progress and refetches on an accepted handoff", async () => {
    await mount("analysis", `/analysis/?case=${CASE}&tab=rn-cp-0`);
    await answer(0, analysis());
    await fire("run_progress");
    expect(sent).toHaveLength(1);
    await fire("handoff_accepted");
    expect(sent).toHaveLength(2);
  });

  test("Model refetches only its named document events", async () => {
    await mount("model", `/model/?case=${CASE}&run=${RUN}`);
    expect(sent[0]!.url).toBe(`/api/v1/cases/${CASE}/model?run=${RUN}`);
    await answer(0, model());
    await fire("run_progress");
    expect(sent).toHaveLength(1);
    for (const name of ["handoff_accepted", "run_terminal", "sources_changed", "runs_changed"]) {
      await fire(name);
      await answer(sent.length - 1, model());
    }
    expect(sent).toHaveLength(5);
  });

  test("Report requires a case and run and refreshes for saved-source or filing changes", async () => {
    // A revision is optional -- absent, the run's head or its first save is
    // served -- but a Report names no run's deliverable without the run.
    await mount("report", `/report/?case=${CASE}`);
    expect(sent).toHaveLength(0);
    await mount("report", `/report/?case=${CASE}&run=${RUN}&revision=${REVISION}`);
    expect(sent[0]!.url).toBe(`/api/v1/cases/${CASE}/report?run=${RUN}&revision=${REVISION}`);
    await answer(0, report());
    for (const name of ["run_progress", "handoff_accepted", "run_terminal", "runs_changed"]) {
      await fire(name);
    }
    expect(sent).toHaveLength(1);
    await fire("sources_changed");
    expect(sent).toHaveLength(2);
    await answer(1, report());
    await fire("filing_changed");
    expect(sent).toHaveLength(3);
  });

  test("Committee requires the same exact selection and refreshes from frozen to filed", async () => {
    await mount("committee", `/committee/?case=${CASE}&run=${RUN}`);
    expect(sent).toHaveLength(0);
    const { container } = await mount(
      "committee",
      `/committee/?case=${CASE}&run=${RUN}&revision=${REVISION}`,
    );
    expect(sent[0]!.url).toBe(`/api/v1/cases/${CASE}/committee?run=${RUN}&revision=${REVISION}`);
    await answer(0, committee());
    for (const name of ["run_progress", "handoff_accepted", "run_terminal", "runs_changed"]) {
      await fire(name);
    }
    expect(sent).toHaveLength(1);
    await fire("sources_changed");
    expect(sent).toHaveLength(2);
    await answer(1, committee());
    await fire("filing_changed");
    expect(sent).toHaveLength(3);
    await answer(2, filedCommittee());
    expect(container.querySelector("[data-committee-filing]")).toHaveAttribute(
      "data-state",
      "filed",
    );
  });

  test("test_names_arriving_mid_flight_cause_exactly_one_more_fetch", async () => {
    // The address names the run, so the tail is open before the first read
    // answers and names can arrive while it is in flight.
    await mount("analysis", `/analysis/?case=${CASE}&run=${DISPLAYED}&tab=rn-cp-0`);
    await fire("handoff_accepted");
    await fire("run_terminal");
    await fire("sources_changed");
    expect(sent).toHaveLength(1);
    await answer(0, analysis());
    expect(sent).toHaveLength(2);
    await answer(1, analysis());
    expect(sent).toHaveLength(2);
  });

  test("test_a_reconnect_refetches_the_visible_documents", async () => {
    await mount("analysis", `/analysis/?case=${CASE}&tab=rn-cp-0`);
    await answer(0, analysis());
    // Every open refetches, the first included: an event landing between the
    // document read and the stream's head is not replayed (finding FE-9).
    await fire("open");
    expect(sent).toHaveLength(2);
    await answer(1, analysis());
    FakeSource.all[0]!.readyState = FakeSource.CONNECTING;
    await fire("error");
    await fire("open");
    expect(sent).toHaveLength(3);
  });

  // MAX-19: an address with no run is answered with the case's latest, but a
  // tail opened on that bare address carries the case's audit actions only.
  // The run on screen never moved until the stream expired.
  test("test_a_view_whose_address_names_no_run_tails_the_run_it_displays", async () => {
    const { container } = await mount("analysis", `/analysis/?case=${CASE}&tab=rn-cp-0`);
    // Nothing to follow yet: the first answer says which run is shown.
    expect(FakeSource.all).toHaveLength(0);
    await answer(0, analysis());
    expect(FakeSource.all).toHaveLength(1);
    expect(FakeSource.all[0]!.url).toBe(`/api/v1/cases/${CASE}/events?run=${DISPLAYED}`);
    // A run event now reaches the view.
    await fire("handoff_accepted");
    expect(sent).toHaveLength(2);
    // A newer run is held for Reload, and the tail stays on the run shown.
    const next = changed(analysis(), (b) => {
      b["displayed_run_id"] = RUN;
      b["latest_run_id"] = RUN;
    });
    await answer(1, next);
    expect(FakeSource.all).toHaveLength(1);
    const stale = region(container).querySelector("[data-surface-state='stale']");
    expect(stale).not.toBeNull();
    // Reload moves the view onto it, and the tail with it.
    act(() => fireEvent.click(stale!.querySelector("button")!));
    await settle();
    expect(FakeSource.all[0]!.closed).toBe(true);
    expect(FakeSource.all.at(-1)!.url).toBe(`/api/v1/cases/${CASE}/events?run=${RUN}`);
  });

  test("a Run view whose address names no run refetches on that run's progress", async () => {
    const frame = json("../../fixtures/run/frames/1.json");
    const shown = ((frame["body"] as Record<string, unknown>)["run"] as Record<string, unknown>)[
      "run_id"
    ] as string;
    await mount("run", `/run/?case=${CASE}`);
    await answer(0, frame);
    expect(FakeSource.all.at(-1)!.url).toBe(`/api/v1/cases/${CASE}/events?run=${shown}`);
    await fire("run_progress");
    expect(sent).toHaveLength(2);
  });

  test("test_a_refused_reconnect_closes_the_tail_and_the_region_is_unavailable", async () => {
    const { container } = await mount("analysis", `/analysis/?case=${CASE}&tab=rn-cp-0`);
    await answer(0, analysis());
    expect(confidence(container)).not.toBeNull();
    FakeSource.all[0]!.readyState = FakeSource.CLOSED;
    await fire("error");
    expect(FakeSource.all[0]!.closed).toBe(true);
    // The refetch decides what the closed stream meant.
    expect(sent).toHaveLength(2);
    await answer(1, { code: "CASE_NOT_FOUND", clears: "x" }, 404);
    expect(region(container).querySelector("[data-surface-state='unavailable']")).not.toBeNull();
    expect(confidence(container)).toBeNull();
  });

  test("a stream closed by a failed connection leaves the region offline, not unavailable", async () => {
    const { container } = await mount("analysis", `/analysis/?case=${CASE}&tab=rn-cp-0`);
    await answer(0, analysis());
    FakeSource.all[0]!.readyState = FakeSource.CLOSED;
    await fire("error");
    await act(async () => {
      sent[1]!.fail();
      await settle();
    });
    expect(region(container).querySelector("[data-surface-state='unavailable']")).toBeNull();
  });

  test("test_a_late_response_after_a_case_switch_is_discarded", async () => {
    const { container } = await mount(
      "analysis",
      `/analysis/?case=${CASE}&run=${DISPLAYED}&tab=rn-cp-0`,
    );
    const first = sent[0]!;
    const firstTail = FakeSource.all[0]!;
    act(() => fireEvent.click(container.querySelector("[data-switch]")!));
    await settle();
    expect(first.signal?.aborted).toBe(true);
    expect(firstTail.closed).toBe(true);
    const other = otherCase();
    other.body.handoffs[0].confidence_score = 7;
    await answer(1, other);
    expect(confidence(container)).toMatch(/^7 /);
    // The other case's address names no run: its tail follows the one shown.
    expect(FakeSource.all.at(-1)!.url).toBe(`/api/v1/cases/${OTHER}/events?run=${DISPLAYED}`);
    // The left case answers late: discarded, never rendered.
    await answer(0, analysis());
    expect(confidence(container)).toMatch(/^7 /);
    expect(region(container).querySelector("[data-surface-state]")).toBeNull();
  });

  test("test_a_new_analytical_identity_is_held_until_reload", async () => {
    const { container } = await mount("analysis", `/analysis/?case=${CASE}&tab=rn-cp-0`);
    await answer(0, analysis());
    expect(confidence(container)).toMatch(/^96 /);
    // Same identity, new figures: an ordinary refresh replaces.
    await fire("handoff_accepted");
    await answer(
      1,
      changed(analysis(), (b) => {
        (b["handoffs"] as Record<string, unknown>[])[0]!["confidence_score"] = 95;
      }),
    );
    expect(confidence(container)).toMatch(/^95 /);
    expect(region(container).querySelector("[data-surface-state='stale']")).toBeNull();
    // A new identity is held: the label shows, the figures do not move.
    await fire("run_terminal");
    const next = changed(analysis(), (b) => {
      b["displayed_run_id"] = RUN;
      b["latest_run_id"] = RUN;
      (b["handoffs"] as Record<string, unknown>[])[0]!["confidence_score"] = 12;
    });
    await answer(2, next);
    const stale = region(container).querySelector("[data-surface-state='stale']");
    expect(stale).not.toBeNull();
    expect(confidence(container)).toMatch(/^95 /);
    // A further refetch of the same pending identity still does not advance.
    await fire("runs_changed");
    await answer(3, next);
    expect(confidence(container)).toMatch(/^95 /);
    act(() => fireEvent.click(stale!.querySelector("button")!));
    await settle();
    expect(confidence(container)).toMatch(/^12 /);
    expect(region(container).querySelector("[data-surface-state='stale']")).toBeNull();
  });

  test("test_withdrawal_applies_to_a_stale_view_without_advancing_its_figures", async () => {
    const { container } = await mount("analysis", `/analysis/?case=${CASE}&tab=rn-cp-0`);
    await answer(0, analysis());
    // The module's citations lead its Audit tab (D60), which stays open
    // across the refresh.
    act(() => fireEvent.click(region(container).querySelector("[data-depth-tab='audit']")!));
    const cited = () => region(container).querySelector("[data-citation]");
    expect(cited()).toHaveAttribute("data-withdrawn", "false");
    await fire("sources_changed");
    await answer(
      1,
      changed(analysis(), (b) => {
        b["displayed_run_id"] = RUN;
        const handoffs = b["handoffs"] as Record<string, unknown>[];
        handoffs[0]!["confidence_score"] = 12;
        const facts = handoffs[0]!["source_facts"] as Record<string, unknown>[];
        facts[0]!["withdrawn_at"] = "2026-09-10T00:00:00Z";
      }),
    );
    expect(region(container).querySelector("[data-surface-state='stale']")).not.toBeNull();
    expect(cited()).toHaveAttribute("data-withdrawn", "true");
    expect(confidence(container)).toMatch(/^96 /);
  });

  test("a 404 on refetch makes the region unavailable at once, stale or not", async () => {
    const { container } = await mount("analysis", `/analysis/?case=${CASE}&tab=rn-cp-0`);
    await answer(0, analysis());
    await fire("run_terminal");
    await answer(
      1,
      changed(analysis(), (b) => (b["displayed_run_id"] = RUN)),
    );
    expect(region(container).querySelector("[data-surface-state='stale']")).not.toBeNull();
    await fire("run_terminal");
    await answer(2, {}, 404);
    expect(region(container).querySelector("[data-surface-state='unavailable']")).not.toBeNull();
    expect(confidence(container)).toBeNull();
  });

  test("test_an_ordinary_refresh_preserves_run_node_selection_and_tab", async () => {
    const { container } = await mount("run", `/run/?case=${CASE}&run=${RUN}`);
    expect(FakeSource.all[0]!.url).toBe(`/api/v1/cases/${CASE}/events?run=${RUN}`);
    await answer(0, json("../../fixtures/run/frames/1.json"));
    const node = () => container.querySelector<HTMLButtonElement>("button.node[data-node='CP-6']")!;
    act(() => fireEvent.click(node()));
    expect(node()).toHaveAttribute("aria-pressed", "true");
    // The v1 chrome declares no tabs; the active tab is the section's default
    // and must survive too.
    const tabs = () => [...container.querySelectorAll("[role='tab'][aria-selected='true']")];
    const tabBefore = tabs().map((tab) => tab.textContent);
    await fire("run_progress");
    await answer(1, json("../../fixtures/run/frames/3.json"));
    expect(node()).toHaveAttribute("data-state", "COMPLETE");
    expect(node()).toHaveAttribute("aria-pressed", "true");
    expect(tabs().map((tab) => tab.textContent)).toEqual(tabBefore);
  });

  // The strip binds a global evidence identity, not the section's document, so
  // naming one in the URL must not tear the section down and re-read it.
  test("test_changing_the_qualification_strip_does_not_remount_the_section", async () => {
    const { container } = await mount("analysis", `/analysis/?case=${CASE}&tab=rn-cp-0`);
    await answer(0, analysis());
    const sections = () =>
      sent.filter((one) => one.url.startsWith(`/api/v1/cases/${CASE}/analysis`));
    expect(sections()).toHaveLength(1);
    const shown = confidence(container);
    act(() => fireEvent.click(container.querySelector("[data-qualify]")!));
    await settle();
    expect(sections()).toHaveLength(1);
    expect(region(container).querySelector("[data-surface-state='loading']")).toBeNull();
    expect(confidence(container)).toBe(shown);
  });
});

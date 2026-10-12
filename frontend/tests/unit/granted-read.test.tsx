// A read under the desk-wide Book grant (spec B9) serves no standing and no
// actions. Analysis and Model then ask the server for nothing a member alone
// may read -- no event stream, no Run, Report, Committee or deliverable, no
// command -- and draw no mutation control. Counted on the requests made.
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { act, render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router";
import { Workspace } from "@/app/Workspace";
import { CASE_SECTIONS } from "@/chrome/compose";
import type { Section } from "@/wire";

const CASE = "00000000-0000-4000-8000-000000000001";
const RUN = "00000000-0000-4000-8000-0000000000a1";

const fixture = (name: string) =>
  JSON.parse(readFileSync(resolve(process.cwd(), "fixtures", name), "utf8"));

/** The fixture as a desk-wide grant serves it: no standing, no actions, no
    other run's id, no digest. */
function granted(name: string, member: boolean) {
  const raw = fixture(name);
  raw.chrome.served_role = {
    global_role: "READER",
    standing: member ? "APPROVER" : null,
  };
  raw.chrome.actions = member ? [{ action: "ADD_TO_BOOK", refusal: null }] : [];
  raw.body.latest_run_id = member ? raw.body.latest_run_id : null;
  raw.body.displayed_run_id = RUN;
  if ("snapshot_sha256" in raw.body) {
    raw.body.snapshot_sha256 = member ? "d".repeat(64) : null;
    raw.body.lines = [];
    raw.body.columns = [];
    raw.body.subject = {
      issuer_id: "CVNA",
      issuer_name: "Carvana Co.",
      reporting_period: "FY2025",
      analysis_date: "2026-09-08",
    };
  }
  return raw;
}

class FakeSource {
  static all: FakeSource[] = [];
  constructor(readonly url: string) {
    FakeSource.all.push(this);
  }
  private listeners = new Map<string, () => void>();
  addEventListener(name: string, listener: () => void) {
    this.listeners.set(name, listener);
  }
  fire(name: string) {
    this.listeners.get(name)?.();
  }
  close() {}
}

let urls: string[] = [];
const settle = () => act(() => new Promise((resolve) => setTimeout(resolve, 20)));

beforeEach(() => {
  urls = [];
  FakeSource.all = [];
  vi.stubGlobal("EventSource", FakeSource);
});
afterEach(() => vi.unstubAllGlobals());

async function mount(section: Section, name: string, member: boolean) {
  vi.stubGlobal("fetch", async (url: string, init?: RequestInit) => {
    urls.push(`${init?.method ?? "GET"} ${url}`);
    return new Response(JSON.stringify(granted(name, member)), { status: 200 });
  });
  render(
    <MemoryRouter initialEntries={[`/${section}/?case=${CASE}&run=${RUN}`]}>
      <Routes>
        <Route path="*" element={<Workspace section={section} />} />
      </Routes>
    </MemoryRouter>,
  );
  await settle();
}

const MEMBER_ONLY = /\/(events|run|report|committee|revisions|upload)\b|\/runs\/|\/members|POST /;

describe.each([
  ["analysis", "analysis.json"],
  ["model", "model.json"],
] as const)("a granted %s read", (section, name) => {
  test("makes one request, the document's, and opens no event stream", async () => {
    await mount(section, name, false);
    expect(
      urls.filter((url) => url.startsWith("GET /api/v1/cases/") && url.includes(`/${section}`)),
    ).toHaveLength(1);
    expect(urls.filter((url) => MEMBER_ONLY.test(url.replace(`/${section}`, "")))).toEqual([]);
    expect(FakeSource.all).toHaveLength(0);
  });

  test("draws no mutation control", async () => {
    await mount(section, name, false);
    expect(
      screen.queryByRole("button", { name: /Add to Book|Withdraw|Approve|Start|Retry|Cancel/ }),
    ).toBeNull();
  });
});

test("a member's read still follows its run's events", async () => {
  await mount("model", "model.json", true);
  expect(FakeSource.all.map((source) => source.url)).toEqual([
    `/api/v1/cases/${CASE}/events?run=${RUN}`,
  ]);
});

describe("a granted rail", () => {
  test("offers no link to a member-only section and following none sends a request", async () => {
    await mount("analysis", "analysis.json", false);
    const rail = screen.getByRole("navigation", { name: "Workspace" });
    // Every case section but the one granted is closed.
    for (const section of CASE_SECTIONS.filter((id) => id !== "analysis")) {
      const link = rail.querySelector(`[data-section="${section}"]`);
      expect(link?.getAttribute("href")).not.toMatch(/case=|run=/);
      expect(link?.getAttribute("aria-label")).toMatch(/Unavailable$/);
    }
    // The page granted is still the page it is on.
    expect(rail.querySelector('[data-section="analysis"]')?.getAttribute("aria-label")).not.toMatch(
      /Unavailable$/,
    );
    const before = urls.length;
    for (const section of ["upload", "run", "report", "committee"]) {
      (rail.querySelector(`[data-section="${section}"]`) as HTMLElement).click();
      await settle();
    }
    expect(urls.slice(before)).toEqual([]);
    expect(FakeSource.all).toHaveLength(0);
  });
});

describe.each([
  ["analysis", "analysis.json"],
  ["model", "model.json"],
] as const)("a member's %s whose first read fails", (section, name) => {
  test.each([
    ["503", () => new Response("{}", { status: 503, headers: { "Retry-After": "1" } })],
    ["offline", () => Promise.reject(new TypeError("network"))],
  ] as const)("opens the tail after a %s and re-reads the document", async (_, failure) => {
    let reads = 0;
    vi.stubGlobal("fetch", async (url: string) => {
      urls.push(`GET ${url}`);
      reads += 1;
      return reads === 1 ? failure() : new Response(JSON.stringify(granted(name, true)));
    });
    render(
      <MemoryRouter initialEntries={[`/${section}/?case=${CASE}&run=${RUN}`]}>
        <Routes>
          <Route path="*" element={<Workspace section={section} />} />
        </Routes>
      </MemoryRouter>,
    );
    await settle();
    expect(FakeSource.all.map((source) => source.url)).toEqual([
      `/api/v1/cases/${CASE}/events?run=${RUN}`,
    ]);
    // The stream's open is what re-reads the document.
    FakeSource.all[0]?.fire("open");
    await settle();
    expect(reads).toBeGreaterThanOrEqual(2);
  });
});

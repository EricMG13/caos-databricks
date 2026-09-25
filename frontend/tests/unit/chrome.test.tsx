import { readFileSync, readdirSync } from "node:fs";
import { resolve } from "node:path";
import type { ReactNode } from "react";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { AppSidebar, railLabel } from "@/chrome/AppSidebar";
import { caseTarget, switcherLines } from "@/chrome/CaseSwitcher";
import { SectionPanel, SectionTabs } from "@/chrome/SectionTabs";
import { SectionSummary } from "@/chrome/SectionSummary";
import { SEVERITY_BADGE, SeverityMark } from "@/chrome/SeverityMark";
import { SiteHeader, TONE_BADGE } from "@/chrome/SiteHeader";
import { isEnabledSection } from "@/app/sections";
import { SidebarProvider, useSidebar } from "@/components/ui/sidebar";
import { TooltipProvider } from "@/components/ui/tooltip";
import { SECTIONS, type AnyDocument, type Ribbon, type Severity } from "@/wire";

const FIXTURES = `${resolve(process.cwd(), "fixtures")}/`;
// Every enabled section reads the v1 wire (brief 4.1, decision 9; slices
// 4.1h-k): its document's `chrome` carries only `{subject, served_role}`
// (composed into the legacy `Chrome` shape by `@/chrome/compose`, not stored
// on the fixture itself), so the generic legacy-chrome fixtures this file
// scans are exactly the disabled sections' own.
const DISABLED = SECTIONS.filter((section) => !isEnabledSection(section));
const documents = (): [string, AnyDocument][] =>
  [
    ...DISABLED.map((section) => `${section}.json`),
    ...readdirSync(`${FIXTURES}states`)
      .filter((name) => DISABLED.some((section) => name.startsWith(`${section}.`)))
      .map((name) => `states/${name}`),
  ].map((name) => [name, JSON.parse(readFileSync(`${FIXTURES}${name}`, "utf8"))]);

/** The sidebar and the header read the sidebar's own state (`useSidebar`). */
function shell(children: ReactNode) {
  return (
    <MemoryRouter>
      <SidebarProvider>{children}</SidebarProvider>
    </MemoryRouter>
  );
}

const QUIET: Ribbon = {
  chips: [],
  execution: null,
  persistence: null,
  approval: null,
  actions: [],
};

describe("the sidebar", () => {
  test("lists the nine sections, each named with its count and one-line state", () => {
    const [, doc] = documents()[0]!;
    render(
      shell(
        <AppSidebar
          section="analysis"
          entries={doc.chrome.rail}
          local={null}
          servedRole={doc.chrome.served_role}
          searchFor={() => ""}
          subject={null}
          caseId={null}
        />,
      ),
    );
    const nav = screen.getByRole("navigation", { name: "Workspace" });
    const links = within(nav).getAllByRole("link");
    expect(links.map((link) => link.getAttribute("data-section"))).toEqual([...SECTIONS]);
    for (const entry of doc.chrome.rail) {
      expect(
        within(nav).getByRole("link", { name: railLabel(entry.section, entry) }),
      ).toBeInTheDocument();
    }
    // The served role is read-only: not a control.
    const role = document.querySelector("[data-served-role]")!;
    expect(role.querySelector("button, a, select, input")).toBeNull();
    // Two foot controls and no more, both refused and both still there.
    const foot = [...document.querySelectorAll("[data-sidebar-foot] button")];
    expect(foot).toHaveLength(2);
    for (const control of foot) expect(control).toHaveAttribute("aria-disabled", "true");
  });

  test("the foot's refused controls are quiet and say why on focus", async () => {
    render(
      shell(
        <TooltipProvider delay={0}>
          <AppSidebar
            section="analysis"
            entries={null}
            local={null}
            servedRole={null}
            searchFor={() => ""}
            subject={null}
            caseId={null}
          />
        </TooltipProvider>,
      ),
    );
    const ask = screen.getByRole("button", { name: /^Ask about/ });
    // No dashed edge in chrome on every page, and no title to draw a second
    // tooltip over the first (brief 5, the chrome).
    expect(ask.className).toContain("aria-disabled:border-transparent");
    expect(ask).not.toHaveAttribute("title");
    // The reason is still its description, and a keyboard reaches it.
    expect(ask).toHaveAccessibleDescription("Ask is not part of this workspace yet.");
    fireEvent.focus(ask);
    const tip = await screen.findByText("Ask is not part of this workspace yet.", {
      selector: "[data-reason-tip] span",
    });
    // With what a title gave a pointer: the code and what clears it.
    expect(tip.closest("[data-reason-tip]")).toHaveTextContent("ASK_UNPLACED — clears when");
  });

  // FE-12: the count and the one-line state are the point of an entry, and
  // with the sidebar collapsed to icons they are all its name carries.
  test("an entry reads its count and state, not only its name", () => {
    render(
      shell(
        <AppSidebar
          section="analysis"
          entries={[
            { section: "directory", count: 4, state: "Served" },
            { section: "admin", count: null, state: "Unavailable" },
          ]}
          local={{ title: "This run", items: [{ label: "CP-6", meta: "RUNNABLE", on: true }] }}
          servedRole={{ role: "READER", standing: "READER" }}
          searchFor={() => ""}
          subject={null}
          caseId={null}
        />,
      ),
    );
    expect(screen.getByRole("link", { name: "Directory, 4, Served" })).toBeInTheDocument();
    const admin = screen.getByRole("link", { name: "Admin, Unavailable" });
    // A section the deployment does not serve says so in words.
    expect(admin).toHaveTextContent("Unavailable");
    // A section the document does not serve at all still says its name.
    expect(screen.getByRole("link", { name: "Book" })).toBeInTheDocument();
    // The section-local list is a named group, not an aria-label on nothing.
    expect(screen.getByRole("group", { name: "This run" })).toBeInTheDocument();
    expect(railLabel("book", undefined)).toBe("Book");
  });

  test("the case switcher keeps the reader's section, else lands on the case's analysis", () => {
    const CASE = "00000000-0000-4000-8000-000000000001";
    expect(caseTarget("run", CASE)).toBe(`/run/?case=${CASE}`);
    expect(caseTarget("upload", CASE)).toBe(`/upload/?case=${CASE}`);
    // Report and Committee need a run or a revision the other case has not got.
    expect(caseTarget("report", CASE)).toBe(`/analysis/?case=${CASE}`);
    expect(caseTarget("directory", CASE)).toBe(`/analysis/?case=${CASE}`);
    expect(caseTarget(null, CASE)).toBe(`/analysis/?case=${CASE}`);
  });

  test("the case switcher names the issuer and its listing, never a cut title", () => {
    const CASE = "00000000-0000-4000-8000-000000000001";
    // The listing a title carries is the second line; the trail has the whole.
    expect(switcherLines("Carvana Co. (NYSE: CVNA)", CASE)).toEqual({
      name: "Carvana Co.",
      detail: "NYSE: CVNA",
    });
    // A parenthesis that is not a listing stays in the name; the short id is beneath.
    expect(switcherLines("Terra Firma (Holdings) plc", CASE)).toEqual({
      name: "Terra Firma (Holdings) plc",
      detail: "Case 00000000",
    });
    expect(switcherLines("Northwind (UK)", CASE)).toEqual({
      name: "Northwind (UK)",
      detail: "Case 00000000",
    });
    expect(switcherLines(null, CASE)).toEqual({ name: "Case", detail: "Case 00000000" });
    expect(switcherLines(null, null)).toEqual({ name: "CAOS", detail: "Credit workspace" });
  });

  test("the trigger in the header opens and closes the sidebar", () => {
    function State() {
      return <output data-sidebar-state>{useSidebar().state}</output>;
    }
    render(
      shell(
        <>
          <SiteHeader label="Analysis" crumb="Carvana Co." subject={null} ribbon={QUIET} />
          <State />
        </>,
      ),
    );
    const state = document.querySelector("[data-sidebar-state]")!;
    expect(state).toHaveTextContent("expanded");
    fireEvent.click(screen.getByRole("button", { name: "Toggle sidebar" }));
    expect(state).toHaveTextContent("collapsed");
  });
});

describe("the header", () => {
  test("names the case, then the section as the page heading", () => {
    render(
      shell(
        <SiteHeader
          label="Analysis"
          crumb="Carvana Co."
          subject={{ case_id: "00000000-0000-4000-8000-000000000001", issuer: "Carvana Co." }}
          ribbon={{ ...QUIET, execution: "RUNNING", chips: [{ label: "Partial", tone: "warn" }] }}
        />,
      ),
    );
    const banner = screen.getByRole("banner");
    expect(within(banner).getByRole("heading", { level: 1 })).toHaveTextContent("Analysis");
    expect(within(banner).getByText("Carvana Co.")).toHaveAttribute(
      "title",
      "00000000-0000-4000-8000-000000000001",
    );
    // The run's state is a word beside its mark; a warning is a toned badge.
    expect(banner.querySelector("[data-state-cell='execution']")).toHaveTextContent("Running");
    expect(within(banner).getByText("Partial")).toHaveAttribute("data-variant", "warning");
    expect(TONE_BADGE.crit).toBe("destructive");
    // No second navigation: the trail is not a landmark (IA_SPEC.md 3).
    expect(screen.queryByRole("navigation")).toBeNull();
  });

  test("has at most three actions and exactly one primary", () => {
    for (const [name, doc] of documents()) {
      const { unmount } = render(
        shell(<SiteHeader label="Admin" crumb={null} subject={null} ribbon={doc.chrome.ribbon} />),
      );
      const banner = screen.getByRole("banner");
      expect(banner.querySelectorAll("[data-primary]"), name).toHaveLength(1);
      expect(doc.chrome.ribbon.actions.length, name).toBeLessThanOrEqual(3);
      expect(
        doc.chrome.ribbon.actions.filter((a) => a.primary),
        name,
      ).toHaveLength(1);
      unmount();
    }
  });

  test("an action that names a tab of this section is live and opens it", () => {
    const opened: string[] = [];
    render(
      shell(
        <SiteHeader
          label="Book"
          crumb={null}
          subject={null}
          ribbon={{
            ...QUIET,
            actions: [{ label: "Compare", primary: true, refusal: null, tab: "compare" }],
          }}
          tabs={["table", "compare"]}
          onTab={(tab) => opened.push(tab)}
        />,
      ),
    );
    const compare = screen.getByRole("button", { name: "Compare" });
    expect(compare).not.toHaveAttribute("aria-disabled");
    fireEvent.click(compare);
    expect(opened).toEqual(["compare"]);
  });

  test("an action naming a tab the section does not have is refused for that, never a live no-op", () => {
    const opened: string[] = [];
    render(
      shell(
        <SiteHeader
          label="Book"
          crumb={null}
          subject={null}
          ribbon={{
            ...QUIET,
            actions: [{ label: "Compare", primary: true, refusal: null, tab: "nope" }],
          }}
          tabs={["table", "compare"]}
          onTab={(tab) => opened.push(tab)}
        />,
      ),
    );
    const compare = screen.getByRole("button", { name: "Compare" });
    expect(compare).toHaveAttribute("aria-disabled", "true");
    // The reason is the missing tab, not a missing API route.
    expect(compare).toHaveAttribute("data-refusal", "VIEW_UNPLACED");
    expect(compare.getAttribute("title")).toContain("nope");
    fireEvent.click(compare);
    expect(opened).toEqual([]);
  });
});

describe("the chrome's refusals", () => {
  test("the legacy fixtures this file scans have not all been served v1", () => {
    // Every case below walks `documents()`. The day the last legacy fixture is
    // served a v1 document, each of them passes over nothing, which is a green
    // suite asserting no behaviour at all.
    expect(documents().length).toBeGreaterThan(0);
  });

  test("every refusal a fixture carries reads as a clause after 'clears when', and names no build phase", () => {
    const clauses: string[] = [];
    const walk = (value: unknown): void => {
      if (Array.isArray(value)) return value.forEach(walk);
      if (typeof value !== "object" || value === null) return;
      const record = value as Record<string, unknown>;
      if (typeof record["code"] === "string" && typeof record["clears"] === "string") {
        clauses.push(record["clears"]);
      }
      Object.values(record).forEach(walk);
    };
    for (const [, doc] of documents()) walk(doc);
    // The remaining legacy fixtures still prove the scanner itself is live.
    expect(clauses.length).toBeGreaterThan(0);
    for (const clause of clauses) {
      // Every surface reads it as "Clears when " + clause + ".".
      expect(clause).toMatch(/^[a-z]/);
      expect(clause.endsWith(".")).toBe(false);
      expect(clause).not.toMatch(/Phase \d|REBUILD_PLAN|backend phase/);
    }
  });

  test("every refused control in the chrome names what clears it today, never a build phase", () => {
    for (const [name, doc] of documents()) {
      const { container, unmount } = render(
        shell(
          <>
            <SiteHeader
              label="Admin"
              crumb={null}
              subject={doc.chrome.subject}
              ribbon={doc.chrome.ribbon}
            />
            <AppSidebar
              section="analysis"
              entries={doc.chrome.rail}
              local={doc.chrome.rail_local}
              servedRole={doc.chrome.served_role}
              searchFor={() => ""}
              subject={doc.chrome.subject}
              caseId={null}
            />
          </>,
        ),
      );
      for (const control of container.querySelectorAll("[aria-disabled='true']")) {
        // Its title, or where a tooltip carries the reason instead, its description.
        const described = control.getAttribute("aria-describedby");
        const said =
          control.getAttribute("title") ??
          (described ? document.getElementById(described)?.textContent : null);
        expect(said, name).toBeTruthy();
        expect(said, name).not.toMatch(/Phase \d|REBUILD_PLAN|backend phase/);
      }
      unmount();
    }
  });
});

describe("the section's views", () => {
  // FE-11: a tab list of no tabs is announced on every page as an empty
  // widget. A v1 document declares none, so none is rendered.
  test("test_no_tablist_is_rendered_when_the_document_declares_no_tabs", () => {
    const { container, rerender } = render(
      <SectionTabs label="Analysis" tabs={[]} active={null} onSelect={() => {}} />,
    );
    expect(container.querySelector("[role='tablist']")).toBeNull();
    // With tabs, each one names the panel it controls, and that panel is
    // labelled by the tab (FE-11).
    rerender(
      <SectionTabs
        label="Analysis"
        tabs={[
          { id: "route", label: "Route", cp: null },
          { id: "frontier", label: "Frontier", cp: null },
        ]}
        active="route"
        onSelect={() => {}}
      />,
    );
    const tab = screen.getByRole("tab", { name: "Route" });
    expect(tab).toHaveAttribute("aria-controls", "tabpanel-route");
    expect(tab).toHaveAttribute("id", "tab-route");
    expect(tab).toHaveAttribute("aria-selected", "true");
    render(
      <SectionPanel tab="route">
        <p>panel body</p>
      </SectionPanel>,
    );
    const panel = screen.getByRole("tabpanel");
    expect(panel).toHaveAttribute("id", "tabpanel-route");
    expect(panel).toHaveAttribute("aria-labelledby", "tab-route");
  });

  test("the views are one tab stop, and a view is selected when focus reaches it", () => {
    const picked: string[] = [];
    render(
      <SectionTabs
        label="Analysis"
        tabs={[
          { id: "a", label: "CP-0", cp: null },
          { id: "b", label: "CP-1", cp: null },
        ]}
        active="a"
        onSelect={(id) => picked.push(id)}
      />,
    );
    const first = screen.getByRole("tab", { name: "CP-0" });
    const second = screen.getByRole("tab", { name: "CP-1" });
    // One tab stop: the selected view; the others are reached by arrows.
    expect(first).toHaveAttribute("tabindex", "0");
    expect(second).toHaveAttribute("tabindex", "-1");
    // Focus arriving on a view selects it (Base UI's activateOnFocus).
    fireEvent.focus(second);
    expect(picked).toEqual(["b"]);
  });
});

describe("severity", () => {
  test("test_severity_renders_shape_and_hue", () => {
    const expected: Record<Severity, [string, string]> = {
      SUCCESS: ["ok", "disc"],
      RUNNING: ["run", "disc"],
      WARNING: ["warn", "triangle"],
      CRITICAL: ["crit", "rounded-square"],
      IDLE: ["idle", "flat-dot"],
      RESTRICTED: ["restricted", "ring"],
    };
    for (const [severity, [hue, shape]] of Object.entries(expected) as [
      Severity,
      [string, string],
    ][]) {
      const { unmount } = render(<SeverityMark severity={severity} />);
      const mark = screen.getByRole("img", { name: severity });
      expect(mark).toHaveClass("glyph", hue);
      expect(mark).toHaveAttribute("data-shape", shape);
      unmount();
    }
    expect(SEVERITY_BADGE.CRITICAL).toBe("destructive");
    expect(SEVERITY_BADGE.IDLE).toBe("outline");
  });

  test("the summary leads with the verdict, its severity and what blocks it", () => {
    const { container } = render(
      <SectionSummary
        verdict={{ severity: "WARNING", conclusion: "Conditional", blocked_on: "CP-6" }}
        brief={{ change: "Changed.", impact: null, action: null, evidence: null, headline: "3" }}
        ribbon={{ ...QUIET, approval: "FULL_COMMITTEE" }}
      />,
    );
    const verdict = container.querySelector("[data-verdict]")!;
    expect(verdict).toHaveAttribute("data-tone", "warn");
    expect(within(verdict as HTMLElement).getByRole("img", { name: "WARNING" })).toBeVisible();
    expect(verdict).toHaveTextContent("Conditional");
    expect(verdict.querySelector("[data-blocked-on]")).toHaveTextContent("Blocked on CP-6");
    expect(verdict.querySelector("[data-state-cell='approval']")).toHaveTextContent(
      "Approval Full committee",
    );
  });
});

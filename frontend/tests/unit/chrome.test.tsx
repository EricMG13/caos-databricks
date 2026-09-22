import { readFileSync, readdirSync } from "node:fs";
import { resolve } from "node:path";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { Rail } from "@/chrome/Rail";
import { Ribbon } from "@/chrome/Ribbon";
import { SeverityMark } from "@/chrome/SeverityMark";
import { VerdictStrip } from "@/chrome/VerdictStrip";
import { isEnabledSection } from "@/app/sections";
import { SECTIONS, type AnyDocument, type Severity } from "@/wire";

const FIXTURES = `${resolve(process.cwd(), "fixtures")}/`;
// Every enabled section reads the v1 wire (brief 4.1, decision 9; slices
// 4.1h-k): its document's `chrome` carries only `{subject, served_role}`
// (composed into the legacy `Chrome` shape by `@/chrome/compose`, not stored
// on the fixture itself), so the generic legacy-chrome fixtures this file
// scans are exactly the five disabled sections' own.
const DISABLED = SECTIONS.filter((section) => !isEnabledSection(section));
const documents = (): [string, AnyDocument][] =>
  [
    ...DISABLED.map((section) => `${section}.json`),
    ...readdirSync(`${FIXTURES}states`)
      .filter((name) => DISABLED.some((section) => name.startsWith(`${section}.`)))
      .map((name) => `states/${name}`),
  ].map((name) => [name, JSON.parse(readFileSync(`${FIXTURES}${name}`, "utf8"))]);

describe("the chrome", () => {
  test("test_rail_lists_nine_sections_with_state_lines", () => {
    const [, doc] = documents()[0]!;
    render(
      <MemoryRouter>
        <Rail
          section="analysis"
          entries={doc.chrome.rail}
          local={null}
          servedRole={doc.chrome.served_role}
          search=""
        />
      </MemoryRouter>,
    );
    const nav = screen.getByRole("navigation", { name: "Workspace" });
    const links = within(nav).getAllByRole("link");
    expect(links.map((link) => link.getAttribute("data-section"))).toEqual([...SECTIONS]);
    for (const entry of doc.chrome.rail) {
      expect(within(nav).getByText(entry.state)).toBeInTheDocument();
    }
    // The served role is read-only: not a control.
    const role = nav.querySelector("[data-served-role]")!;
    expect(role.querySelector("button, a, select, input")).toBeNull();
    // Two foot controls and no more.
    expect(nav.querySelectorAll(".railfoot button")).toHaveLength(2);
  });

  test("test_ribbon_has_exactly_one_primary_action", () => {
    for (const [name, doc] of documents()) {
      const { unmount } = render(
        <Ribbon ribbon={doc.chrome.ribbon} subject={doc.chrome.subject} />,
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

  test("a ribbon action that names a tab of this section is live and opens it", () => {
    const opened: string[] = [];
    render(
      <Ribbon
        ribbon={{
          chips: [],
          execution: "IDLE",
          persistence: "SAVED",
          approval: "UNRATIFIED",
          actions: [{ label: "Compare", primary: true, refusal: null, tab: "compare" }],
        }}
        subject={null}
        tabs={["table", "compare"]}
        onTab={(tab) => opened.push(tab)}
      />,
    );
    const compare = screen.getByRole("button", { name: "Compare" });
    expect(compare).not.toHaveAttribute("aria-disabled");
    fireEvent.click(compare);
    expect(opened).toEqual(["compare"]);
  });

  test("an action naming a tab the section does not have is refused for that, never a live no-op", () => {
    const opened: string[] = [];
    render(
      <Ribbon
        ribbon={{
          chips: [],
          execution: "IDLE",
          persistence: "SAVED",
          approval: "UNRATIFIED",
          actions: [{ label: "Compare", primary: true, refusal: null, tab: "nope" }],
        }}
        subject={null}
        tabs={["table", "compare"]}
        onTab={(tab) => opened.push(tab)}
      />,
    );
    const compare = screen.getByRole("button", { name: "Compare" });
    expect(compare).toHaveAttribute("aria-disabled", "true");
    // The reason is the missing tab, not a missing API route.
    expect(compare).toHaveAttribute("data-refusal", "VIEW_UNPLACED");
    expect(compare.getAttribute("title")).toContain("nope");
    fireEvent.click(compare);
    expect(opened).toEqual([]);
  });

  // "the book's primary Compare opens its Compare tab" stood here, over the
  // legacy `fixtures/book.json`. Task 12.3 served the Book a v1 document, so
  // that fixture is now the v1 shape and this file scans only the legacy ones
  // -- of which Admin's is the last, and its primary action names no tab, so
  // the rule would have no subject there. The behaviour it
  // asserted is not lost: the two cases above drive the same Ribbon over a
  // declared tab and an undeclared one, on a ribbon the test builds rather
  // than on fixture data. What went with it was the fixture assertion, which
  // had no subject left.

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
        <MemoryRouter>
          <Ribbon ribbon={doc.chrome.ribbon} subject={doc.chrome.subject} />
          <Rail
            section="analysis"
            entries={doc.chrome.rail}
            local={doc.chrome.rail_local}
            servedRole={doc.chrome.served_role}
            search=""
          />
        </MemoryRouter>,
      );
      for (const control of container.querySelectorAll("[aria-disabled='true']")) {
        expect(control.getAttribute("title"), name).not.toMatch(
          /Phase \d|REBUILD_PLAN|backend phase/,
        );
      }
      unmount();
    }
  });

  test("test_severity_renders_shape_and_hue", () => {
    const expected: Record<Severity, [string, string]> = {
      SUCCESS: ["ok", "disc"],
      RUNNING: ["run", "disc"],
      WARNING: ["warn", "triangle"],
      CRITICAL: ["crit", "rounded-square"],
      IDLE: ["idle", "flat-dot"],
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
    render(
      <VerdictStrip
        verdict={{ severity: "WARNING", conclusion: "Conditional", blocked_on: "CP-6" }}
      />,
    );
    expect(screen.getByLabelText("Verdict")).toHaveClass("verdict", "warn");
    expect(screen.getByLabelText("Verdict")).toHaveTextContent("blocked on CP-6");
  });
});

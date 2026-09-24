// The header and the summary say what each section's own document says
// (critique P1): no "—" cells, no "No action is offered", no section name as
// the headline figure, and a cell with nothing to say is not drawn.
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { fireEvent, render } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { SectionSummary, headlineOf } from "@/chrome/SectionSummary";
import { SectionTabs } from "@/chrome/SectionTabs";
import { SiteHeader } from "@/chrome/SiteHeader";
import { RUN_SEVERITY, composeChrome, sentence, words } from "@/chrome/compose";
import { SidebarProvider } from "@/components/ui/sidebar";
import {
  parseAnalysisDocument,
  parseDirectoryDocument,
  parseModelDocument,
  parseReportDocument,
  parseRunSectionDocument,
} from "@/wire/v1";

const load = (name: string) =>
  JSON.parse(readFileSync(resolve(process.cwd(), "fixtures", name), "utf8"));

test("test_words_reads_a_code_as_words", () => {
  expect(words("FULL_COMMITTEE")).toBe("full committee");
  expect(words("RUNNING")).toBe("running");
  // A code shown as a label reads as a sentence would.
  expect(sentence("FULL_COMMITTEE")).toBe("Full committee");
  expect(sentence("2 gates open")).toBe("2 gates open");
  expect(RUN_SEVERITY.FAILED).toBe("CRITICAL");
});

test("Analysis names the conclusion, the module to review and the evidence it rests on", () => {
  const chrome = composeChrome("analysis", parseAnalysisDocument(load("analysis.json")));
  // CP-CF, the host's own calculation, runs last but concludes nothing.
  expect(chrome.brief.impact).toBe("Committee Ready · full committee");
  expect(chrome.brief.action).toBe("Review CP-1C before committee.");
  expect(chrome.brief.evidence).toBe("4 citations across 4 documents, 1 withdrawn.");
  expect(chrome.brief.headline).toBe("9/9");
  expect(chrome.verdict).toEqual({
    severity: "WARNING",
    conclusion: "Committee Ready · full committee, with 1 module to review",
    blocked_on: null,
  });
  expect(chrome.ribbon.execution).toBe("COMPLETE");
  expect(JSON.stringify(chrome)).not.toMatch(/No action is offered|"—"/);
});

test("Run names what it waits on: an open gate, else a module held at its gate", () => {
  const chrome = composeChrome("run", parseRunSectionDocument(load("run.json")));
  expect(chrome.ribbon.execution).toBe("RUNNING");
  expect(chrome.ribbon.approval).toBe("gates released");
  expect(chrome.brief.change).toMatch(/^6 of 10 modules complete\. Observed /);
  expect(chrome.brief.impact).toBe("1 module restricted.");
  expect(chrome.verdict.conclusion).toBe("In progress · CP-6 at its gate");
  expect(chrome.verdict.severity).toBe("RUNNING");
});

test("Report says how far the shown revision has gone and what comes next", () => {
  const document = parseReportDocument(load("states/report.acts.json"));
  const chrome = composeChrome("report", document);
  expect(chrome.ribbon.persistence).toBe("saved");
  expect(chrome.ribbon.approval).toBeNull();
  expect(chrome.brief.action).toBe("Sign, then freeze, to send it to committee.");
  expect(chrome.verdict).toMatchObject({ severity: "IDLE", conclusion: "Saved, not yet frozen." });
  const filed = parseReportDocument(load("report-v1.json"));
  expect(composeChrome("report", filed).verdict).toMatchObject({
    severity: "SUCCESS",
    conclusion: "Filed.",
  });
});

test("an empty directory and a run with no forecast say so, and what to do", () => {
  const directory = load("directory.json");
  directory.body.cases = [];
  const empty = composeChrome("directory", parseDirectoryDocument(directory));
  expect(empty.brief.change).toMatch(/^You hold standing on no case yet\./);
  expect(empty.verdict.conclusion).toBe("No cases yet.");
  const model = load("model.json");
  model.body.forecast = null;
  model.body.unavailable_reason = "NO_ACCEPTED_FORECAST";
  const none = composeChrome("model", parseModelDocument(model));
  expect(none.brief.action).toBe("Run a route that includes CP-CF.");
  expect(none.brief.headline).toBeNull();
});

test("a partial document with no notes says so in words, never 'Partial: .'", () => {
  const document = load("analysis.json");
  document.status = "partial";
  document.notes = [];
  const chrome = composeChrome("analysis", parseAnalysisDocument(document));
  expect(chrome.brief.evidence).toBe("Some parts of this document could not be read.");
  expect(chrome.verdict.severity).toBe("WARNING");
  expect(chrome.ribbon.chips[0]).toEqual({ label: "Partial", tone: "warn" });
});

test("a brief cell with nothing to say is not drawn, and an empty brief draws no row", () => {
  const verdict = { severity: "IDLE" as const, conclusion: "Held.", blocked_on: null };
  const quiet = { chips: [], execution: null, persistence: null, approval: null, actions: [] };
  const { container, rerender } = render(
    <SectionSummary
      verdict={verdict}
      ribbon={quiet}
      brief={{ change: "Changed.", impact: null, action: null, evidence: null, headline: "3" }}
    />,
  );
  expect([...container.querySelectorAll("[data-cell]")].map((cell) => cell.textContent)).toEqual([
    "ChangeChanged.",
  ]);
  expect(container.querySelector("[data-headline]")).toHaveTextContent("3");
  // A figure the conclusion already states is not drawn twice.
  expect(
    headlineOf(
      { change: null, impact: null, action: null, evidence: null, headline: "4" },
      { severity: "IDLE", conclusion: "4 cases.", blocked_on: null },
    ),
  ).toBeNull();
  expect(
    headlineOf(
      { change: null, impact: null, action: null, evidence: null, headline: "6/10" },
      { severity: "RUNNING", conclusion: "In progress · CP-6 at its gate", blocked_on: null },
    ),
  ).toBe("6/10");
  rerender(
    <SectionSummary
      verdict={verdict}
      ribbon={quiet}
      brief={{ change: null, impact: null, action: null, evidence: null, headline: null }}
    />,
  );
  expect(container.querySelector("[data-brief]")).toBeNull();
  expect(container.querySelector("[data-headline]")).toBeNull();
});

test("the header names the issuer and draws only the state it has", () => {
  const { container } = render(
    <MemoryRouter>
      <SidebarProvider>
        <SiteHeader
          label="Run"
          crumb="Carvana Co."
          subject={{ case_id: "00000000-0000-4000-8000-000000000001", issuer: "Carvana Co." }}
          ribbon={{
            chips: [],
            execution: "RUNNING",
            persistence: null,
            approval: null,
            actions: [],
          }}
        />
      </SidebarProvider>
    </MemoryRouter>,
  );
  expect(container.querySelector("[data-case]")).toHaveTextContent("Carvana Co.");
  expect(
    [...container.querySelectorAll("[data-state-cell]")].map((cell) =>
      cell.getAttribute("data-state-cell"),
    ),
  ).toEqual(["execution"]);
});

test("a phone picks a view from a native select; a desktop from the tabs", () => {
  const picked: string[] = [];
  const { container } = render(
    <SectionTabs
      label="Analysis"
      tabs={[
        { id: "rn-cp-0", label: "CP-0", cp: "Source readiness", severity: "SUCCESS" },
        { id: "rn-cp-1c", label: "CP-1C", cp: "Peer benchmark", severity: "WARNING" },
      ]}
      active="rn-cp-0"
      onSelect={(id) => picked.push(id)}
    />,
  );
  const select = container.querySelector<HTMLSelectElement>("[data-tab-select]")!;
  expect([...select.options].map((option) => option.text)).toEqual([
    "CP-0 · Source readiness",
    "CP-1C · Peer benchmark · warning",
  ]);
  fireEvent.change(select, { target: { value: "rn-cp-1c" } });
  expect(picked).toEqual(["rn-cp-1c"]);
});

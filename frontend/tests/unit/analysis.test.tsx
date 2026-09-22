// Analysis, /analysis/ (IA_SPEC.md 4.3), v1 wire (brief 4.1, slice 4.1j):
// every accepted handoff in route order, its host-verified source facts, the
// model's own analysis rendered as text and never as markup, and the
// reminder that the host performs no calculation. Pending nodes are named
// with the state the route left them in.
import { readFileSync } from "node:fs";
import { render } from "@testing-library/react";
import { AnalysisSection } from "@/sections/analysis/AnalysisSection";
import { parseAnalysisDocument } from "@/wire/v1";
import type { AnalysisDocument, HandoffView } from "@/wire/v1";

const load = (path: string): unknown =>
  JSON.parse(readFileSync(new URL(path, import.meta.url), "utf8"));

const complete = parseAnalysisDocument(load("../../fixtures/analysis.json"));
const partial = parseAnalysisDocument(load("../../fixtures/states/analysis.partial.json"));

function mount(document: AnalysisDocument) {
  return render(<AnalysisSection document={document} tab={null} />);
}

describe("Analysis", () => {
  test("test_every_enabled_demo_fixture_is_a_valid_v1_document", () => {
    const fixtures = [
      "../../fixtures/analysis.json",
      "../../fixtures/states/analysis.partial.json",
    ];
    for (const path of fixtures) {
      expect(() => parseAnalysisDocument(load(path))).not.toThrow();
    }
  });

  test("test_analysis_renders_markdown_as_text_with_limitations_visible", () => {
    const { container } = mount(complete);
    const cp1c = container.querySelector('[data-handoff="CP-1C"]')!;
    // The model's own prose (headings, emphasis, code) is a `<pre>`'s literal
    // text content, never parsed into markup: no heading, strong or em tag
    // reaches the page, and the raw markdown characters survive verbatim.
    const cp1 = container.querySelector('[data-handoff="CP-1"]')!;
    const pre = cp1.querySelector("[data-model-analysis] pre.model-text")!;
    expect(pre.textContent).toContain("## Normalised financials");
    expect(pre.textContent).toContain("**$769M**");
    expect(pre.querySelector("h1,h2,h3,h4,h5,h6,strong,em,code,ul,ol,li")).toBeNull();
    // Limitation flags are always visible, whether empty or carrying a flag.
    const cp1Flags = cp1.querySelector("[data-limitation-flags]")!;
    expect(cp1Flags.textContent).toContain("none");
    const cp1cFlags = cp1c.querySelector("[data-limitation-flags]")!;
    expect(cp1cFlags.textContent).toContain("PEER_SET_INCOMPLETE");
    expect(cp1cFlags).toBeVisible();
    expect(cp1Flags).toBeVisible();
  });

  test("the three labelled parts render in order for every handoff", () => {
    const { container } = mount(complete);
    for (const handoff of complete.body.handoffs) {
      const card = container.querySelector(`[data-handoff="${handoff.module_id}"]`)!;
      const headings = [...card.querySelectorAll("h3")].map((h) => h.textContent);
      expect(headings).toEqual([
        "Source facts (host-verified citations)",
        "Analysis (model-authored, not host-verified)",
        "Deterministic calculations: none performed by the host",
      ]);
    }
  });

  test("a screening-only handoff shows the screening notice; a full-committee one does not", () => {
    const screening: HandoffView = {
      ...complete.body.handoffs[0]!,
      decision_scope: "SCREENING_ONLY",
      screening_only: true,
    };
    const document: AnalysisDocument = {
      ...complete,
      body: { ...complete.body, handoffs: [screening] },
    };
    const { container } = mount(document);
    const card = container.querySelector(`[data-handoff="${screening.module_id}"]`)!;
    expect(card.querySelector("[data-screening-only]")).toHaveTextContent(
      "SCREENING ONLY: a screen, not committee clearance.",
    );
    // The fixture's own handoffs are all full-committee: none carries the notice.
    const { container: full } = mount(complete);
    expect(full.querySelector("[data-screening-only]")).toBeNull();
  });

  test("source facts name the file, page, matched text and withdrawn state", () => {
    const { container } = mount(complete);
    const cp4 = container.querySelector('[data-handoff="CP-4"]')!;
    const fact = cp4.querySelector("[data-source-facts] [data-citation]")!;
    const withdrawn = complete.body.handoffs.find((h) => h.module_id === "CP-4")!.source_facts[0]!;
    expect(fact).toHaveTextContent(withdrawn.filename);
    expect(fact).toHaveTextContent(`p.${withdrawn.page}`);
    expect(fact).toHaveTextContent(withdrawn.matched_text);
    expect(fact.getAttribute("data-withdrawn")).toBe("true");
    expect(fact).toHaveTextContent(withdrawn.withdrawn_at!);

    const cp0 = container.querySelector('[data-handoff="CP-0"]')!;
    const notWithdrawn = cp0.querySelector("[data-source-facts] [data-citation]")!;
    expect(notWithdrawn.getAttribute("data-withdrawn")).toBe("false");
  });

  test("a handoff with no citation says so rather than rendering nothing", () => {
    const { container } = mount(complete);
    const cp5 = container.querySelector('[data-handoff="CP-5"]')!;
    expect(cp5.querySelector("[data-source-facts]")).toHaveTextContent(
      "No citation is carried on this handoff.",
    );
  });

  test("host_calculation keeps LITE as NONE and labels a host CP-CF forecast", () => {
    const { container } = mount(complete);
    for (const handoff of complete.body.handoffs) {
      expect(handoff.host_calculation).toBe("NONE");
      const card = container.querySelector(`[data-handoff="${handoff.module_id}"]`)!;
      expect(card.querySelector("[data-host-calculation]")).toHaveTextContent(
        "Deterministic calculations: none performed by the host",
      );
    }
    const forecast: HandoffView = {
      ...complete.body.handoffs[0]!,
      module_id: "CP-CF",
      host_calculation: "CP_CF_FORECAST",
    };
    const { container: forecastPage } = mount({
      ...complete,
      body: { ...complete.body, handoffs: [forecast] },
    });
    expect(forecastPage.querySelector("[data-host-calculation]")).toHaveTextContent(
      "Deterministic calculations: CP-CF forecast projection performed by the host",
    );
  });

  test("qa status, committee status, decision scope and confidence are all shown", () => {
    const { container } = mount(complete);
    const cp1c = complete.body.handoffs.find((h) => h.module_id === "CP-1C")!;
    const card = container.querySelector('[data-handoff="CP-1C"]')!;
    expect(card.querySelector("[data-qa-status]")).toHaveTextContent(cp1c.qa_status);
    expect(card.querySelector("[data-committee-status]")).toHaveTextContent(cp1c.committee_status);
    expect(card.querySelector("[data-committee-status]")).toHaveTextContent(cp1c.decision_scope);
    expect(card.querySelector("[data-confidence]")).toHaveTextContent(
      String(cp1c.confidence_score),
    );
    expect(card.querySelector("[data-confidence]")).toHaveTextContent(cp1c.confidence_band);
  });

  test("validation warnings render only when carried", () => {
    const { container } = mount(complete);
    const cp1c = container.querySelector('[data-handoff="CP-1C"]')!;
    expect(cp1c.querySelector("[data-validation-warnings]")).not.toBeNull();
    const cp0 = container.querySelector('[data-handoff="CP-0"]')!;
    expect(cp0.querySelector("[data-validation-warnings]")).toBeNull();
  });

  test("handoffs render in route order, one card per accepted node", () => {
    const { container } = mount(complete);
    const cards = [...container.querySelectorAll("[data-handoff]")].map((el) =>
      el.getAttribute("data-handoff"),
    );
    expect(cards).toEqual(complete.body.handoffs.map((h) => h.module_id));
  });

  test("unaccepted route nodes are named as pending, with the state the route left them in", () => {
    const { container } = mount(partial);
    expect(partial.status).toBe("partial");
    expect(partial.notes).toContain("HANDOFFS_PENDING");
    const rows = [...container.querySelectorAll("[data-pending-node]")];
    expect(rows).toHaveLength(partial.body.pending.length);
    partial.body.pending.forEach((node, index) => {
      const row = rows[index]!;
      expect(row.getAttribute("data-pending-node")).toBe(node.module_id);
      expect(row.getAttribute("data-state")).toBe(node.state);
      expect(row).toHaveTextContent(node.state);
    });
    // A pending node is never also a handoff.
    const handoffIds = new Set(partial.body.handoffs.map((h) => h.module_id));
    for (const node of partial.body.pending) expect(handoffIds.has(node.module_id)).toBe(false);
  });

  test("test_the_pending_list_names_the_node_whose_verdict_ended_the_run", () => {
    // A Blocked verdict accepts nothing, so the node that answered sits in the
    // same list as the nodes that never started. Told apart, or the page says
    // the opposite of what happened about the one node that did run.
    const [answered, ...never] = partial.body.pending;
    const blocked: AnalysisDocument = {
      ...partial,
      body: {
        ...partial.body,
        displayed_run_status: "BLOCKED",
        blocked_by: {
          route_node_id: answered!.route_node_id,
          module_id: answered!.module_id,
          attempt_id: "00000000-0000-4000-8000-0000000000c1",
        },
      },
    };
    const { container } = mount(blocked);

    const panel = container.querySelector("[data-pending]")!;
    expect(panel).toHaveAttribute("data-run-ended", "yes");
    expect(panel).toHaveTextContent(`the run ended BLOCKED on ${answered!.module_id}`);
    const named = container.querySelector(`[data-pending-node="${answered!.module_id}"]`)!;
    expect(named).toHaveAttribute("data-blocking", "yes");
    expect(named).toHaveTextContent("its verdict ended the run");
    for (const node of never) {
      const row = container.querySelector(`[data-pending-node="${node.module_id}"]`)!;
      expect(row).toHaveAttribute("data-blocking", "no");
      expect(row).not.toHaveTextContent("its verdict ended the run");
    }
  });

  test("a run still working names no blocking node", () => {
    const { container } = mount(partial);
    const rows = [...container.querySelectorAll("[data-pending-node]")];
    expect(rows.length).toBeGreaterThan(0);
    for (const row of rows) expect(row).toHaveAttribute("data-blocking", "no");
  });

  test("a run with nothing pending says every pinned node has been accepted", () => {
    const { container } = mount(complete);
    expect(complete.body.pending).toEqual([]);
    expect(container.querySelector("[data-pending]")).toHaveTextContent(
      "Every pinned node on this run has been accepted.",
    );
  });

  test("displayed and latest run are named separately", () => {
    const superseded: AnalysisDocument = {
      ...complete,
      body: { ...complete.body, latest_run_id: "00000000-0000-4000-8000-0000000000b2" },
    };
    const { container } = mount(superseded);
    const stale = container.querySelector("[data-stale-run]");
    expect(stale).not.toBeNull();
    expect(stale).toHaveTextContent(superseded.body.displayed_run_id!);
    expect(stale).toHaveTextContent(superseded.body.latest_run_id!);

    const { container: current } = mount(complete);
    expect(current.querySelector("[data-stale-run]")).toBeNull();
  });

  test("an observed-empty analysis (no handoff, nothing pending) renders no card", () => {
    const empty: AnalysisDocument = {
      ...complete,
      body: {
        case_id: complete.body.case_id,
        latest_run_id: null,
        displayed_run_id: null,
        subject: null,
        displayed_run_status: null,
        blocked_by: null,
        handoffs: [],
        pending: [],
      },
      observed_empty: true,
    };
    const { container } = mount(empty);
    expect(container.querySelectorAll("[data-handoff]")).toHaveLength(0);
    expect(container).toHaveTextContent("No handoff has been accepted on this run yet.");
  });
});

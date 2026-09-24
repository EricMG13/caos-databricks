// `useCommand` and `useRunRefetch` (controls.tsx) are exercised end-to-end
// below: every click on a rendered control drives `useCommand`'s intent
// lifecycle, and every command's success drives `useRunRefetch`'s
// GET-after-success — neither is imported directly, since a hook is reached
// by the component that calls it, not by its own name. `actionOf` is
// imported directly below and given its own small, direct test.
import { readFileSync } from "node:fs";
import { useEffect } from "react";
import { act, fireEvent, render, waitFor } from "@testing-library/react";
import { MemoryRouter, useLocation } from "react-router";
import { sentence } from "@/chrome/compose";
import { actionOf } from "@/sections/run/controls";
import { RunSection } from "@/sections/run/RunSection";
import { COL_GAP, NODE_H, NODE_W, ROW_H, edgesOf, layoutRoute } from "@/sections/run/RouteGraph";
import { parseRunSectionDocument } from "@/wire/v1";
import type { NodeState } from "@/wire";
import type { RunSectionDocument } from "@/wire/v1";

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

const load = (path: string): unknown =>
  JSON.parse(readFileSync(new URL(path, import.meta.url), "utf8"));

const running = parseRunSectionDocument(load("../../fixtures/run.json"));
const routeNotPinned = parseRunSectionDocument(load("../../fixtures/states/run.gate.json"));
const superseded = parseRunSectionDocument(load("../../fixtures/states/run.superseded.json"));
const frames = [1, 2, 3, 4].map((n) =>
  parseRunSectionDocument(load(`../../fixtures/run/frames/${n}.json`)),
);

function mount(document: RunSectionDocument) {
  return render(
    <MemoryRouter>
      <RunSection document={document} tab={null} />
    </MemoryRouter>,
  );
}

/** A document with exactly these served actions, everything else unchanged —
    every action absent from the list is `ACTION_UNPLACED`. */
function withActions(
  document: RunSectionDocument,
  actions: RunSectionDocument["chrome"]["actions"],
): RunSectionDocument {
  return { ...document, chrome: { ...document.chrome, actions } };
}

/** The address the section is composed under. `CreateRunControl` writes the
    new run into it and the workspace reads the run from there, so under a bare
    router a probe is what stands in for the workspace's own read. */
let seenAddress = "";
const address = () => seenAddress;

function Address() {
  const { search } = useLocation();
  useEffect(() => {
    seenAddress = search;
  }, [search]);
  return null;
}

/** An act with a confirm step (finding FE-7) takes two presses: the control
    arms the step, and Confirm sends it. */
function confirmed(container: HTMLElement, action: string) {
  fireEvent.click(container.querySelector(`[data-action="${action}"]`)!);
  fireEvent.click(container.querySelector(`[data-confirm="${action}"] [data-confirm-yes]`)!);
}

function mountAt(document: RunSectionDocument, path: string) {
  seenAddress = "";
  return render(
    <MemoryRouter initialEntries={[path]}>
      <RunSection document={document} tab={null} />
      <Address />
    </MemoryRouter>,
  );
}

/** A case whose run has yet to be created: the one state that serves the
    create form on its own. */
const EMPTY_RUN: RunSectionDocument = withActions(
  {
    ...routeNotPinned,
    body: {
      case_id: routeNotPinned.body.case_id,
      latest_run_id: null,
      displayed_run_id: null,
      runs: [],
      run: null,
      route_choices: [
        {
          profile_id: "FULL_CREDIT_ASSESSMENT",
          selection_id: "default",
          accepts_model_extension: false,
        },
      ],
    },
  },
  [{ action: "CREATE_RUN", refusal: null }],
);

const RUN_B = "11111111-1111-4111-8111-111111111111";

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

const BUNDLE: NodeState[] = ["COMPLETE", "RUNNABLE", "RESTRICTED", "BLOCKED"];

describe("Run", () => {
  test("test_node_states_are_the_bundles_four_with_reasons", () => {
    const { container } = mount(running);
    const nodes = container.querySelectorAll<HTMLButtonElement>("button.node[data-route-node]");
    expect(nodes.length).toBe(running.body.run!.nodes.length);
    const seen = new Set<string>();
    for (const node of nodes) {
      const state = node.dataset["state"] as NodeState;
      expect(BUNDLE).toContain(state);
      seen.add(state);
      expect(node.className).toContain(state.toLowerCase());
      expect(node.querySelector(".st")?.textContent).toContain(sentence(state));
      expect(node.querySelector(".why")?.textContent?.trim().length).toBeGreaterThan(0);
      expect(node.querySelector(".glyph[data-severity]")).not.toBeNull();
    }
    expect([...seen].sort()).toEqual([...BUNDLE].sort());
    const cp6 = container.querySelector('button.node[data-node="CP-6"]');
    expect(cp6).toHaveAttribute("data-state", "RUNNABLE");
    expect(cp6?.querySelector(".glyph")).toHaveAttribute("data-severity", "RUNNING");
    // Every BLOCKED reason names the upstream and the edge type.
    for (const blocked of container.querySelectorAll('button.node[data-state="BLOCKED"]')) {
      const why = blocked.querySelector(".why")?.textContent ?? "";
      expect(why).toMatch(/REQUIRED|OPTIONAL|ADVISORY|QA_GATE|CONDITIONAL/);
    }
    const restricted = container.querySelector('button.node[data-state="RESTRICTED"]');
    // Ran, carrying its limitation: its own ring, never a warning (CF-036).
    expect(restricted?.querySelector(".glyph")).toHaveAttribute("data-severity", "RESTRICTED");
    expect(container.querySelector(".dag[data-route]")).not.toBeNull();
    expect(container.querySelector(".legend")).not.toBeNull();
  });

  test("test_gate_verdict_is_shown_as_the_cause", () => {
    const { container } = mount(running);
    const restricted = container.querySelector('button.node[data-node="CP-1C"]')!;
    expect(restricted.querySelector(".why")?.textContent).toContain("READY_WITH_LIMITATIONS");
    fireEvent.click(restricted);
    const detail = container.querySelector('[data-node-detail="CP-1C"]')!;
    expect(detail.querySelector("[data-gate-verdict]")).toHaveTextContent("READY_WITH_LIMITATIONS");
  });

  test("test_a_gate_condition_is_shown_beside_the_verdict_it_qualifies", () => {
    // The fixtures are a run whose gate cleared every module, so every node
    // carries `gate_reason: null` — which is the case that must render nothing
    // at all rather than an empty row. The other case is built from the same
    // document so the two are one comparison.
    const asked = "The FY2025 audited consolidated statements are not in the pinned set.";
    const blocked = running.body.run!.nodes.find((node) => node.state === "BLOCKED")!;
    const conditional: RunSectionDocument = {
      ...running,
      body: {
        ...running.body,
        run: {
          ...running.body.run!,
          nodes: running.body.run!.nodes.map((node) =>
            node.route_node_id === blocked.route_node_id
              ? { ...node, gate_verdict: "CONDITIONAL", gate_reason: asked }
              : node,
          ),
        },
      },
    };

    const cleared = mount(running);
    fireEvent.click(cleared.container.querySelector(`button.node[data-node="CP-1C"]`)!);
    expect(cleared.container.querySelector("[data-gate-reason]")).toBeNull();

    const { container } = mount(conditional);
    fireEvent.click(container.querySelector(`button.node[data-node="${blocked.module_id}"]`)!);
    const detail = container.querySelector(`[data-node-detail="${blocked.module_id}"]`)!;
    expect(detail.querySelector("[data-gate-verdict]")).toHaveTextContent("CONDITIONAL");
    expect(detail.querySelector("[data-gate-reason]")).toHaveTextContent(asked);
  });

  test("test_the_one_qa_gate_reads_as_a_gate", () => {
    const { container } = mount(running);
    const gates = container.querySelectorAll("[data-gate]");
    expect(gates.length).toBe(1);
    const mark = gates[0]!;
    expect(mark).toHaveTextContent("QA_GATE");
    expect(mark.querySelector(".gatebox")).not.toBeNull();
    expect(mark.getAttribute("data-gate")).toBe("CP-5 → CP-6");
    expect(container.querySelectorAll("svg.edges line.gate").length).toBe(1);
    expect(container.querySelectorAll("svg.edges line.req").length).toBeGreaterThan(0);
    expect(container.querySelectorAll("svg.edges line.cond").length).toBe(1);
  });

  test("test_layout_places_nodes_by_stage_without_overlap", () => {
    const nodes = running.body.run!.nodes;
    const layout = layoutRoute(nodes);
    expect(layout.columns.map((c) => c.stage)).toEqual([0, 1, 2, 3, 4, 5, 100]);
    const byId = new Map(layout.nodes.map((n) => [n.route_node_id, n]));
    for (const node of nodes) {
      const placed = byId.get(node.route_node_id)!;
      expect(placed.col).toBe(layout.columns.findIndex((c) => c.stage === node.stage));
      expect(placed.x).toBe(layout.columns[placed.col]!.x);
      expect(placed.y).toBe(36 + placed.row * ROW_H);
    }
    const slots = new Set(layout.nodes.map((n) => `${n.x},${n.y}`));
    expect(slots.size).toBe(layout.nodes.length);
    const xs = layout.columns.map((c) => c.x);
    for (let i = 1; i < xs.length; i += 1) expect(xs[i]! - xs[i - 1]!).toBe(NODE_W + COL_GAP);
    expect(ROW_H).toBeGreaterThan(NODE_H);
    for (const placed of layout.nodes) {
      expect(placed.x + NODE_W).toBeLessThanOrEqual(layout.width);
      expect(placed.y + NODE_H).toBeLessThanOrEqual(layout.height);
    }
    expect(layoutRoute([])).toEqual({ nodes: [], columns: [], width: 28, height: 46 });
  });

  test("test_edges_are_derived_from_each_node_s_waiting_on_not_a_separate_list", () => {
    const nodes = running.body.run!.nodes;
    const edges = edgesOf(nodes);
    expect(edges.length).toBe(nodes.reduce((n, node) => n + node.waiting_on.length, 0));
    expect(edges.filter((edge) => edge.type === "QA_GATE").length).toBe(1);
    for (const edge of edges) {
      expect(nodes.some((node) => node.route_node_id === edge.to)).toBe(true);
    }
  });

  test("the selected node's edges, attempts and gate verdict are in the right column", () => {
    const { container } = mount(running);
    fireEvent.click(container.querySelector('button.node[data-node="CP-6"]')!);
    const detail = container.querySelector('[data-node-detail="CP-6"]')!;
    expect(detail).toHaveTextContent("QA_GATE rn-cp-5");
    const attempts = container.querySelectorAll(".att[data-attempt]");
    expect(attempts.length).toBe(2);
    expect(attempts[0]).toHaveTextContent("Attempt 1");
    expect(attempts[0]).toHaveTextContent("Not accepted");
    expect(attempts[1]).toHaveTextContent("Attempt unassigned");
  });

  test("test_displayed_run_is_labelled_separately_from_latest", () => {
    const { container } = mount(superseded);
    const row = container.querySelector(`[data-run-row="${superseded.body.displayed_run_id}"]`)!;
    expect(row).toHaveAttribute("data-displayed", "true");
    expect(row).toHaveAttribute("data-latest", "false");
    const latestRow = container.querySelector(`[data-run-row="${superseded.body.latest_run_id}"]`)!;
    expect(latestRow).toHaveAttribute("data-displayed", "false");
    expect(latestRow).toHaveAttribute("data-latest", "true");
    const stale = container.querySelector("[data-stale-run]");
    expect(stale).not.toBeNull();
    expect(stale).toHaveTextContent(superseded.body.displayed_run_id!);
    expect(stale).toHaveTextContent(superseded.body.latest_run_id!);
  });

  test("test_route_not_pinned_is_rendered_as_a_preview", () => {
    expect(routeNotPinned.status).toBe("partial");
    expect(routeNotPinned.notes).toContain("ROUTE_NOT_PINNED");
    const { container } = mount(routeNotPinned);
    expect(container.querySelector("[data-route-not-pinned]")).not.toBeNull();
    expect(container.querySelectorAll("button.node").length).toBe(0);
    expect(container.querySelector(".dag[data-route]")).toHaveAttribute(
      "data-route",
      "0 nodes · 0 edges",
    );
  });

  test("test_run_null_renders_the_defensive_empty_state_rather_than_crashing", () => {
    const empty: RunSectionDocument = {
      ...routeNotPinned,
      body: {
        case_id: routeNotPinned.body.case_id,
        latest_run_id: null,
        displayed_run_id: null,
        runs: [],
        run: null,
        route_choices: [],
      },
      observed_empty: true,
    };
    const { container } = mount(empty);
    expect(container.querySelector("[data-run-empty]")).not.toBeNull();
  });

  test("the stream's frames advance CP-6 to COMPLETE and CP-7 to RUNNABLE", () => {
    const { container, rerender } = mount(frames[0]!);
    expect(container.querySelector('button.node[data-node="CP-6"]')).toHaveAttribute(
      "data-state",
      "RUNNABLE",
    );
    rerender(
      <MemoryRouter>
        <RunSection document={frames[2]!} tab={null} />
      </MemoryRouter>,
    );
    expect(container.querySelector('button.node[data-node="CP-6"]')).toHaveAttribute(
      "data-state",
      "COMPLETE",
    );
    expect(container.querySelector('button.node[data-node="CP-7"]')).toHaveAttribute(
      "data-state",
      "RUNNABLE",
    );
  });

  test("test_a_refused_action_renders_its_code_and_clearance_and_is_not_hidden", () => {
    const doc = withActions(running, [
      {
        action: "PIN_RUN_INPUT",
        refusal: { code: "RUN_NOT_RUNNING", clears: "the run is RUNNING" },
      },
    ]);
    const { container } = mount(doc);
    const pin = container.querySelector('[data-action="PIN_RUN_INPUT"]')!;
    expect(pin).not.toBeNull();
    expect(pin).toHaveAttribute("aria-disabled", "true");
    expect(pin).toHaveAttribute("data-refusal", "RUN_NOT_RUNNING");
    const reason = pin.nextElementSibling;
    expect(reason).toHaveTextContent("Available once the run is RUNNING.");
    expect(pin).toHaveAttribute("title", "RUN_NOT_RUNNING — clears when the run is RUNNING");
  });

  test("test_an_action_absent_from_served_actions_is_action_unplaced_not_available", () => {
    // A served `refusal: null` and an entry missing entirely both look
    // "not refused" if coerced together; they must not be. Absent here means
    // unavailable, shown the same visible way as any other refusal.
    const doc = withActions(running, []);
    const { container } = mount(doc);
    const pin = container.querySelector('[data-action="PIN_RUN_INPUT"]')!;
    expect(pin).toHaveAttribute("aria-disabled", "true");
    expect(pin).toHaveAttribute("data-refusal", "ACTION_UNPLACED");
  });

  test("test_no_run_offers_a_create_run_control_from_route_choices", () => {
    const empty: RunSectionDocument = withActions(
      {
        ...routeNotPinned,
        body: {
          case_id: routeNotPinned.body.case_id,
          latest_run_id: null,
          displayed_run_id: null,
          runs: [],
          run: null,
          route_choices: [
            {
              profile_id: "FULL_CREDIT_ASSESSMENT",
              selection_id: "default",
              accepts_model_extension: false,
            },
          ],
        },
      },
      [{ action: "CREATE_RUN", refusal: null }],
    );
    const { container } = mount(empty);
    expect(container.querySelector("[data-run-empty]")).not.toBeNull();
    expect(container.querySelector("[data-create-run]")).not.toBeNull();
    const select = container.querySelector("[data-route-select]") as HTMLSelectElement;
    expect(select.options.length).toBe(1);
    const button = container.querySelector('[data-action="CREATE_RUN"]')!;
    expect(button).not.toHaveAttribute("aria-disabled");
  });

  // The model extension (§82) is offered on the route the server says can
  // carry it, sent as the analyst chose it, and stated -- never hidden --
  // where it cannot be. The offer is advisory: the command resolves again.
  test("test_the_model_extension_is_sent_as_chosen_on_a_route_that_accepts_it", async () => {
    const caseId = routeNotPinned.body.case_id;
    const doc: RunSectionDocument = {
      ...EMPTY_RUN,
      body: {
        ...EMPTY_RUN.body,
        route_choices: [
          {
            profile_id: "FULL_CREDIT_32",
            selection_id: "RELATIVE_VALUE",
            accepts_model_extension: true,
          },
        ],
      },
    };
    const created = { case_id: caseId, run_id: RUN_B, route_digest: "f".repeat(64) };
    const fetchSpy = vi.fn().mockResolvedValueOnce(jsonResponse(created, 201));
    vi.stubGlobal("fetch", fetchSpy);
    try {
      const { container, getByLabelText } = mountAt(doc, `/run/?case=${caseId}`);
      const box = getByLabelText("Include the model extension (CP-CF)") as HTMLInputElement;
      expect(box.type).toBe("checkbox");
      expect(box).not.toHaveAttribute("aria-disabled");
      expect(box.checked).toBe(false);
      expect(container.querySelector("[data-model-extension-unavailable]")).toBeNull();
      fireEvent.click(box);
      expect(box.checked).toBe(true);
      fireEvent.click(container.querySelector('[data-action="CREATE_RUN"]')!);
      await waitFor(() => expect(fetchSpy).toHaveBeenCalledTimes(1));
      const [, init] = fetchSpy.mock.calls[0]!;
      // The request is `CreateRun`'s four fields exactly: the choice's own
      // advisory flag is read, never forwarded (the wire forbids it).
      expect(JSON.parse((init as RequestInit).body as string)).toEqual({
        profile_id: "FULL_CREDIT_32",
        selection_id: "RELATIVE_VALUE",
        supersedes: null,
        model_extension: true,
      });
    } finally {
      vi.unstubAllGlobals();
    }
  });

  test("test_a_route_that_cannot_carry_the_model_extension_says_so_and_sends_false", async () => {
    const caseId = routeNotPinned.body.case_id;
    const doc: RunSectionDocument = {
      ...EMPTY_RUN,
      body: {
        ...EMPTY_RUN.body,
        route_choices: [
          {
            profile_id: "FULL_CREDIT_32",
            selection_id: "RELATIVE_VALUE",
            accepts_model_extension: true,
          },
          {
            profile_id: "LITE_CREDIT_22",
            selection_id: "LITE_EARNINGS_UPDATE",
            accepts_model_extension: false,
          },
        ],
      },
    };
    const created = { case_id: caseId, run_id: RUN_B, route_digest: "f".repeat(64) };
    const fetchSpy = vi.fn().mockResolvedValueOnce(jsonResponse(created, 201));
    vi.stubGlobal("fetch", fetchSpy);
    try {
      const { container, getByLabelText } = mountAt(doc, `/run/?case=${caseId}`);
      const box = getByLabelText("Include the model extension (CP-CF)") as HTMLInputElement;
      fireEvent.click(box);
      expect(box.checked).toBe(true);
      // Choosing a route that cannot carry it clears the offer and says why.
      fireEvent.change(container.querySelector("[data-route-select]")!, { target: { value: "1" } });
      expect(box).toHaveAttribute("aria-disabled", "true");
      expect(box.checked).toBe(false);
      fireEvent.click(box);
      expect(box.checked).toBe(false);
      const why = container.querySelector("[data-model-extension-unavailable]");
      expect(why).not.toBeNull();
      expect(why).toHaveTextContent("ROUTE_EXTENSION_OWNER_MISSING");
      expect(box).toHaveAttribute("aria-describedby", why!.id);
      // Back on the route that can carry it, it is asked for afresh.
      fireEvent.change(container.querySelector("[data-route-select]")!, { target: { value: "0" } });
      expect(box).not.toHaveAttribute("aria-disabled");
      expect(box.checked).toBe(false);
      fireEvent.change(container.querySelector("[data-route-select]")!, { target: { value: "1" } });
      fireEvent.click(container.querySelector('[data-action="CREATE_RUN"]')!);
      await waitFor(() => expect(fetchSpy).toHaveBeenCalledTimes(1));
      const [, init] = fetchSpy.mock.calls[0]!;
      expect(JSON.parse((init as RequestInit).body as string).model_extension).toBe(false);
    } finally {
      vi.unstubAllGlobals();
    }
  });

  test("test_pinning_a_subject_sends_the_run_subject_view_shows_success_then_refetches", async () => {
    const run = running.body.run!;
    const caseId = running.body.case_id;
    const receipt = {
      run_id: run.run_id,
      source_set_version: run.source_set_version,
      input_fingerprint: "c".repeat(64),
    };
    const fetchSpy = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse(receipt))
      .mockResolvedValueOnce(jsonResponse(running));
    vi.stubGlobal("fetch", fetchSpy);
    try {
      const doc = withActions(running, [{ action: "PIN_RUN_INPUT", refusal: null }]);
      const { container } = mount(doc);
      const issuerId = container.querySelector('[data-field="issuer_id"]') as HTMLInputElement;
      expect(issuerId.value).toBe(run.subject!.issuer_id);
      fireEvent.click(container.querySelector('[data-action="PIN_RUN_INPUT"]')!);

      await waitFor(() => {
        const note = container.querySelector("[data-command-success]");
        expect(note).not.toBeNull();
      });
      const [, init] = fetchSpy.mock.calls[0]!;
      expect(JSON.parse((init as RequestInit).body as string)).toEqual({
        subject: run.subject,
        research: null,
      });
      expect(
        UUID.test(
          ((init as RequestInit).headers as Record<string, string>)["Idempotency-Key"] ?? "",
        ),
      ).toBe(true);

      // One refetch, through the same transport and parser every load uses.
      await waitFor(() => expect(fetchSpy).toHaveBeenCalledTimes(2));
      const [refetchUrl] = fetchSpy.mock.calls[1]!;
      expect(refetchUrl).toBe(`/api/v1/cases/${caseId}/run?run=${run.run_id}`);
    } finally {
      vi.unstubAllGlobals();
    }
  });

  // R24-01: the store requires a validated CP-DR research brief on the two
  // advertised research routes (`LITE_DEEP_RESEARCH`, `DEEP_RESEARCH`) before
  // it will pin their input; the Run section must carry one through, not
  // just a subject. A CP-DR node on the resolved route (pinned at Create run,
  // before any input pin) is the one signal the reader has for "this route
  // needs a brief" -- no new wire field names the route family.
  test("test_a_research_route_shows_and_sends_a_linked_brief", async () => {
    const run = running.body.run!;
    const researchRun = {
      ...run,
      nodes: [
        ...run.nodes,
        {
          route_node_id: "CP-DR",
          module_id: "CP-DR",
          stage: 99,
          state: "RUNNABLE" as NodeState,
          waiting_on: [],
          awaiting_gate: false,
          gate_verdict: null,
          gate_reason: null,
        },
      ],
    };
    const doc = withActions(
      { ...running, body: { ...running.body, run: researchRun } },
      [{ action: "PIN_RUN_INPUT", refusal: null }],
    );
    const receipt = {
      run_id: run.run_id,
      source_set_version: run.source_set_version,
      input_fingerprint: "f".repeat(64),
    };
    const fetchSpy = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse(receipt))
      .mockResolvedValueOnce(jsonResponse(doc));
    vi.stubGlobal("fetch", fetchSpy);
    try {
      const { container } = mount(doc);
      expect(container.querySelector("[data-research-brief]")).not.toBeNull();

      const set = (field: string, value: string) => {
        fireEvent.change(container.querySelector(`[data-field="${field}"]`)!, {
          target: { value },
        });
      };
      set("decision_context", "Test the demand assumption before setting downside");
      set("as_of_date", "2026-09-08");
      set("time_horizon", "Next 12 months");
      set("authorization_basis", "Existing task instruction to research this issuer");
      set("exclusions", "No confidential inputs in public searches; no trade recommendation");
      set("question_id", "RQ-demand");
      set("question", "Does independent evidence support the claimed end of destocking?");
      set("decision_relevance", "Affects the downside demand assumption");
      set("evidence_needed", "Current customer, competitor and industry disclosures");
      set(
        "completion_test",
        "Evidence-weighted answer with contrary evidence and remaining uncertainty",
      );

      fireEvent.click(container.querySelector('[data-action="PIN_RUN_INPUT"]')!);
      await waitFor(() => {
        expect(container.querySelector("[data-command-success]")).not.toBeNull();
      });

      const [, init] = fetchSpy.mock.calls[0]!;
      const sent = JSON.parse((init as RequestInit).body as string);
      expect(sent.subject).toEqual(run.subject);
      expect(sent.research).toEqual({
        decision_context: "Test the demand assumption before setting downside",
        as_of_date: "2026-09-08",
        time_horizon: "Next 12 months",
        budget: "standard",
        authorization_basis: "Existing task instruction to research this issuer",
        exclusions: "No confidential inputs in public searches; no trade recommendation",
        questions: [
          {
            question_id: "RQ-demand",
            question: "Does independent evidence support the claimed end of destocking?",
            decision_relevance: "Affects the downside demand assumption",
            consumer_module_id: "NONE",
            after_module_id: "CP-0",
            evidence_needed: "Current customer, competitor and industry disclosures",
            completion_test:
              "Evidence-weighted answer with contrary evidence and remaining uncertainty",
          },
        ],
      });
    } finally {
      vi.unstubAllGlobals();
    }
  });

  // A non-research route shows no brief fields at all, and the field the
  // form does not render cannot be filled in and sent by mistake.
  test("test_an_ordinary_route_shows_no_brief_fields_and_sends_a_null_research", async () => {
    const run = running.body.run!;
    const doc = withActions(running, [{ action: "PIN_RUN_INPUT", refusal: null }]);
    const receipt = {
      run_id: run.run_id,
      source_set_version: run.source_set_version,
      input_fingerprint: "f".repeat(64),
    };
    const fetchSpy = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse(receipt))
      .mockResolvedValueOnce(jsonResponse(doc));
    vi.stubGlobal("fetch", fetchSpy);
    try {
      const { container } = mount(doc);
      expect(container.querySelector("[data-research-brief]")).toBeNull();
      fireEvent.click(container.querySelector('[data-action="PIN_RUN_INPUT"]')!);
      await waitFor(() => {
        expect(container.querySelector("[data-command-success]")).not.toBeNull();
      });
      const [, init] = fetchSpy.mock.calls[0]!;
      expect(JSON.parse((init as RequestInit).body as string).research).toBeNull();
    } finally {
      vi.unstubAllGlobals();
    }
  });

  // FE-1: two clicks in one frame both read `pending: false`, because the
  // state that renders it has not committed yet. The guard is a ref read and
  // written in the same synchronous step as the send.
  test("test_a_second_press_while_a_command_is_in_flight_sends_nothing", async () => {
    const caseId = routeNotPinned.body.case_id;
    const created = { case_id: caseId, run_id: RUN_B, route_digest: "f".repeat(64) };
    let release!: (response: Response) => void;
    const held = new Promise<Response>((resolve) => {
      release = resolve;
    });
    const fetchSpy = vi.fn().mockImplementation(() => held);
    vi.stubGlobal("fetch", fetchSpy);
    try {
      const { container } = mountAt(EMPTY_RUN, `/run/?case=${caseId}`);
      const create = container.querySelector('[data-action="CREATE_RUN"]')!;
      // Three activations inside one batch: none of them has seen the render
      // that would show the first as pending, which is the double-click the
      // audit reproduced. Only a ref read in the same step as the send can
      // stop the second and third.
      act(() => {
        fireEvent.click(create);
        fireEvent.click(create);
        fireEvent.click(create);
      });
      expect(fetchSpy).toHaveBeenCalledTimes(1);
      // And it says so while it waits, rather than looking idle.
      await waitFor(() => expect(create).toHaveAttribute("aria-busy", "true"));
      expect(create).toHaveAttribute("aria-disabled", "true");
      expect(create).toHaveTextContent("Creating…");
      fireEvent.click(create);
      expect(fetchSpy).toHaveBeenCalledTimes(1);
      await act(async () => {
        release(jsonResponse(created, 201));
        await new Promise((resolve) => setTimeout(resolve, 0));
      });
      await waitFor(() => expect(new URLSearchParams(address()).get("run")).toBe(RUN_B));
    } finally {
      vi.unstubAllGlobals();
    }
  });

  // FE-8 / AR-19: a proxy's HTML 504, a 5xx with no refusal body, and a 201
  // whose body is lost in transfer all become RESPONSE_INVALID. None of them
  // says whether the write committed, so the retry must ask the same question.
  test("test_an_unreadable_answer_keeps_the_key_so_a_retry_cannot_write_twice", async () => {
    const caseId = routeNotPinned.body.case_id;
    const gateway = () =>
      new Response("<html><body><h1>504 Gateway Time-out</h1></body></html>", {
        status: 504,
        headers: { "content-type": "text/html" },
      });
    const fetchSpy = vi
      .fn()
      .mockResolvedValueOnce(gateway())
      .mockResolvedValueOnce(gateway())
      .mockResolvedValueOnce(
        jsonResponse({ case_id: caseId, run_id: RUN_B, route_digest: "f".repeat(64) }, 201),
      );
    vi.stubGlobal("fetch", fetchSpy);
    try {
      const { container } = mountAt(EMPTY_RUN, `/run/?case=${caseId}`);
      const create = container.querySelector('[data-action="CREATE_RUN"]')!;
      fireEvent.click(create);
      await waitFor(() => expect(container.querySelector("[data-command-error]")).not.toBeNull());
      // And it says what a retry would do.
      expect(container.querySelector("[data-command-error]")).toHaveTextContent(
        "Retrying sends the same key",
      );
      fireEvent.click(create);
      await waitFor(() => expect(fetchSpy).toHaveBeenCalledTimes(2));
      fireEvent.click(create);
      await waitFor(() => expect(fetchSpy).toHaveBeenCalledTimes(3));
      const keyOf = (call: number): string =>
        ((fetchSpy.mock.calls[call]![1] as RequestInit).headers as Record<string, string>)[
          "Idempotency-Key"
        ] ?? "";
      expect(UUID.test(keyOf(0))).toBe(true);
      expect(new Set([keyOf(0), keyOf(1), keyOf(2)]).size).toBe(1);
    } finally {
      vi.unstubAllGlobals();
    }
  });

  // MAX-01: a store fault at commit answers a typed STORE_UNAVAILABLE -- and a
  // commit whose acknowledgement was lost faults exactly there, with the case
  // or run already written. The typed code drew a fresh key, so the retry
  // wrote a second one where the same key would have replayed the first.
  test("test_a_store_refusal_after_a_possible_commit_keeps_the_key", async () => {
    const caseId = routeNotPinned.body.case_id;
    const storeDown = () =>
      jsonResponse({ code: "STORE_UNAVAILABLE", clears: "the store answers again" }, 503);
    const fetchSpy = vi
      .fn()
      .mockResolvedValueOnce(storeDown())
      .mockResolvedValueOnce(
        jsonResponse({ case_id: caseId, run_id: RUN_B, route_digest: "f".repeat(64) }, 201),
      );
    vi.stubGlobal("fetch", fetchSpy);
    try {
      const { container } = mountAt(EMPTY_RUN, `/run/?case=${caseId}`);
      const create = container.querySelector('[data-action="CREATE_RUN"]')!;
      fireEvent.click(create);
      await waitFor(() =>
        expect(container.querySelector("[data-refusal='STORE_UNAVAILABLE']")).not.toBeNull(),
      );
      // And it says what a retry would do.
      expect(container.querySelector("[data-command-in-doubt]")).toHaveTextContent(
        "Retrying sends the same key",
      );
      fireEvent.click(create);
      await waitFor(() => expect(fetchSpy).toHaveBeenCalledTimes(2));
      const keyOf = (call: number): string =>
        ((fetchSpy.mock.calls[call]![1] as RequestInit).headers as Record<string, string>)[
          "Idempotency-Key"
        ] ?? "";
      expect(UUID.test(keyOf(0))).toBe(true);
      expect(keyOf(1)).toBe(keyOf(0));
    } finally {
      vi.unstubAllGlobals();
    }
  });

  // FE-8's other half: a receipt that did arrive settles the intent, so the
  // next press is a plainly new one.
  test("a settled answer draws a fresh key for the next press", async () => {
    const run = running.body.run!;
    const fetchSpy = vi.fn().mockResolvedValue(
      jsonResponse({
        run_id: run.run_id,
        source_set_version: run.source_set_version,
        input_fingerprint: "e".repeat(64),
      }),
    );
    vi.stubGlobal("fetch", fetchSpy);
    try {
      const doc = withActions(running, [{ action: "PIN_RUN_INPUT", refusal: null }]);
      const { container } = mount(doc);
      const pin = container.querySelector('[data-action="PIN_RUN_INPUT"]')!;
      fireEvent.click(pin);
      await waitFor(() => expect(container.querySelector("[data-command-success]")).not.toBeNull());
      const first = fetchSpy.mock.calls[0]![1] as RequestInit;
      fireEvent.click(pin);
      await waitFor(() => expect(fetchSpy.mock.calls.length).toBeGreaterThan(2));
      const second = fetchSpy.mock.calls.find(
        ([url], index) => index > 0 && String(url).endsWith("/input"),
      )![1] as RequestInit;
      const keyOf = (init: RequestInit) =>
        (init.headers as Record<string, string>)["Idempotency-Key"];
      expect(keyOf(second)).not.toBe(keyOf(first));
    } finally {
      vi.unstubAllGlobals();
    }
  });

  test("test_the_idempotency_key_is_reused_for_a_retry_of_the_same_body", async () => {
    const fetchSpy = vi
      .fn()
      .mockRejectedValueOnce(new TypeError("Failed to fetch"))
      .mockResolvedValueOnce(
        jsonResponse({
          run_id: running.body.run!.run_id,
          source_set_version: running.body.run!.source_set_version,
          input_fingerprint: "d".repeat(64),
        }),
      )
      // The pin's own success also triggers one refetch (finding 2); a
      // benign fallback answers it so this test, which is about the key
      // alone, need not assert anything about that second read.
      .mockResolvedValue(jsonResponse(running));
    vi.stubGlobal("fetch", fetchSpy);
    try {
      const doc = withActions(running, [{ action: "PIN_RUN_INPUT", refusal: null }]);
      const { container } = mount(doc);
      const pinButton = container.querySelector('[data-action="PIN_RUN_INPUT"]')!;
      fireEvent.click(pinButton); // offline
      await waitFor(() => expect(fetchSpy).toHaveBeenCalledTimes(1));
      fireEvent.click(pinButton); // retry of the identical, unedited subject
      await waitFor(() => expect(fetchSpy).toHaveBeenCalledTimes(2));
      const key1 = (fetchSpy.mock.calls[0]![1] as RequestInit).headers as Record<string, string>;
      const key2 = (fetchSpy.mock.calls[1]![1] as RequestInit).headers as Record<string, string>;
      expect(key2["Idempotency-Key"]).toBe(key1["Idempotency-Key"]);
    } finally {
      vi.unstubAllGlobals();
    }
  });

  test("test_the_idempotency_key_is_replaced_when_the_body_changes_even_after_an_offline_answer", async () => {
    const fetchSpy = vi.fn().mockRejectedValue(new TypeError("Failed to fetch"));
    vi.stubGlobal("fetch", fetchSpy);
    try {
      const doc = withActions(running, [{ action: "PIN_RUN_INPUT", refusal: null }]);
      const { container } = mount(doc);
      const pinButton = container.querySelector('[data-action="PIN_RUN_INPUT"]')!;
      fireEvent.click(pinButton);
      await waitFor(() => expect(fetchSpy).toHaveBeenCalledTimes(1));
      fireEvent.change(container.querySelector('[data-field="issuer_name"]')!, {
        target: { value: "A different name entirely" },
      });
      fireEvent.click(pinButton);
      await waitFor(() => expect(fetchSpy).toHaveBeenCalledTimes(2));
      const key1 = (fetchSpy.mock.calls[0]![1] as { headers: Record<string, string> }).headers[
        "Idempotency-Key"
      ];
      const key2 = (fetchSpy.mock.calls[1]![1] as { headers: Record<string, string> }).headers[
        "Idempotency-Key"
      ];
      expect(key2).not.toBe(key1);
    } finally {
      vi.unstubAllGlobals();
    }
  });

  test("test_create_run_shows_a_success_note_and_names_the_new_run_in_the_address", async () => {
    const caseId = routeNotPinned.body.case_id;
    const newRunId = "11111111-1111-4111-8111-111111111111";
    const created = { case_id: caseId, run_id: newRunId, route_digest: "f".repeat(64) };
    const fetchSpy = vi.fn().mockResolvedValueOnce(jsonResponse(created, 201));
    vi.stubGlobal("fetch", fetchSpy);
    try {
      const { container } = mountAt(EMPTY_RUN, `/run/?case=${caseId}`);
      fireEvent.click(container.querySelector('[data-action="CREATE_RUN"]')!);

      await waitFor(() => {
        const note = container.querySelector("[data-command-success]");
        expect(note).not.toBeNull();
        expect(note).toHaveTextContent("Run created");
      });

      const [createUrl, createInit] = fetchSpy.mock.calls[0]!;
      expect(createUrl).toBe(`/api/v1/cases/${caseId}/runs`);
      expect((createInit as RequestInit).method).toBe("POST");
      expect(JSON.parse((createInit as RequestInit).body as string)).toEqual({
        profile_id: "FULL_CREDIT_ASSESSMENT",
        selection_id: "default",
        supersedes: null,
        model_extension: false,
      });
      expect(
        UUID.test(
          ((createInit as RequestInit).headers as Record<string, string>)["Idempotency-Key"] ?? "",
        ),
      ).toBe(true);

      // The new run is named in the address, and nothing else reads it back:
      // the workspace serves the run the address now names, so a GET from here
      // would either read the wrong run or duplicate that one.
      await waitFor(() => expect(new URLSearchParams(address()).get("run")).toBe(newRunId));
      expect(fetchSpy).toHaveBeenCalledTimes(1);
    } finally {
      vi.unstubAllGlobals();
    }
  });

  // The address is what a reload, a copied link and the workspace's own read
  // all work from, so creating a run must add the run to it without dropping
  // anything already there.
  test("test_creating_a_run_names_it_in_the_address_and_keeps_the_other_parameters", async () => {
    const caseId = routeNotPinned.body.case_id;
    const newRunId = "22222222-2222-4222-8222-222222222222";
    const created = { case_id: caseId, run_id: newRunId, route_digest: "f".repeat(64) };
    vi.stubGlobal("fetch", vi.fn().mockResolvedValueOnce(jsonResponse(created, 201)));
    try {
      const { container } = mountAt(
        EMPTY_RUN,
        `/run/?case=${caseId}&run=00000000-0000-4000-8000-0000000000aa&tab=route`,
      );
      expect(new URLSearchParams(address()).get("run")).not.toBe(newRunId);
      fireEvent.click(container.querySelector('[data-action="CREATE_RUN"]')!);
      await waitFor(() => expect(new URLSearchParams(address()).get("run")).toBe(newRunId));
      const params = new URLSearchParams(address());
      expect(params.get("case")).toBe(caseId);
      expect(params.get("tab")).toBe("route");
    } finally {
      vi.unstubAllGlobals();
    }
  });

  // The analyst may leave while Create run is in flight: its answer names a run
  // on a page no longer shown, and writing it into the address would navigate
  // them back to it (CF-058).
  test("a Create run answer that lands after the analyst has left moves nothing", async () => {
    const caseId = routeNotPinned.body.case_id;
    const created = { case_id: caseId, run_id: RUN_B, route_digest: "f".repeat(64) };
    let answer!: (response: Response) => void;
    vi.stubGlobal(
      "fetch",
      vi.fn(
        () =>
          new Promise<Response>((resolve) => {
            answer = resolve;
          }),
      ),
    );
    try {
      seenAddress = "";
      const view = (shown: boolean) => (
        <MemoryRouter initialEntries={[`/run/?case=${caseId}&tab=route`]}>
          {shown ? <RunSection document={EMPTY_RUN} tab={null} /> : null}
          <Address />
        </MemoryRouter>
      );
      const { container, rerender } = render(view(true));
      fireEvent.click(container.querySelector('[data-action="CREATE_RUN"]')!);
      rerender(view(false));
      await act(async () => {
        answer(jsonResponse(created, 201));
        await new Promise((resolve) => setTimeout(resolve, 0));
      });
      expect(new URLSearchParams(address()).get("run")).toBeNull();
    } finally {
      vi.unstubAllGlobals();
    }
  });

  // A refetch a command started is always older than a document the workspace
  // has since served: the slower one must be dropped, not applied.
  test("test_a_slower_command_refetch_cannot_resurrect_an_older_run_document", async () => {
    const older = withActions(frames[0]!, [{ action: "CANCEL_RUN", refusal: null }]);
    const newer = frames[2]!;
    const receipt = {
      run_id: older.body.run!.run_id,
      run_status: "RUNNING",
      work: { state: "STOPPED", stop_code: null, cancel_requested: false },
    };
    let resolveRefetch!: (response: Response) => void;
    const refetchResponse = new Promise<Response>((resolve) => {
      resolveRefetch = resolve;
    });
    const fetchSpy = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse(receipt))
      .mockImplementationOnce(() => refetchResponse);
    vi.stubGlobal("fetch", fetchSpy);
    try {
      const { container, rerender } = mount(older);
      const cp6 = () => container.querySelector('button.node[data-node="CP-6"]');
      expect(cp6()).toHaveAttribute("data-state", "RUNNABLE");
      confirmed(container, "CANCEL_RUN");
      await waitFor(() => expect(fetchSpy).toHaveBeenCalledTimes(2));

      // The workspace's own read lands while the command's refetch is still
      // open: it is the newer document, so it is the one that stands.
      rerender(
        <MemoryRouter>
          <RunSection document={newer} tab={null} />
        </MemoryRouter>,
      );
      expect(cp6()).toHaveAttribute("data-state", "COMPLETE");

      await act(async () => {
        resolveRefetch(jsonResponse(older));
        await new Promise((resolve) => setTimeout(resolve, 0));
      });
      expect(cp6()).toHaveAttribute("data-state", "COMPLETE");
      expect(container.querySelector("[data-refetch-failed]")).toBeNull();
    } finally {
      vi.unstubAllGlobals();
    }
  });

  test("test_action_of_finds_the_one_entry_for_a_served_action_by_name", () => {
    const actions = [
      { action: "PIN_RUN_INPUT" as const, refusal: null },
      {
        action: "CREATE_RUN" as const,
        refusal: { code: "NOT_AUTHORISED" as const, clears: "the caller holds WRITER standing" },
      },
    ];
    expect(actionOf(actions, "PIN_RUN_INPUT")).toEqual(actions[0]);
    expect(actionOf(actions, "CREATE_RUN")).toEqual(actions[1]);
    expect(actionOf(actions, "CANCEL_RUN")).toBeUndefined();
  });

  test("test_start_and_retry_are_refused_until_a_fingerprint_is_known", () => {
    const doc = withActions(running, [
      { action: "START_RUN", refusal: null },
      { action: "RETRY_RUN", refusal: null },
      { action: "CANCEL_RUN", refusal: null },
    ]);
    const { container } = mount(doc);
    const start = container.querySelector('[data-action="START_RUN"]')!;
    expect(start).toHaveAttribute("aria-disabled", "true");
    expect(start).toHaveAttribute("data-refusal", "COMMAND_EXPECTATION_STALE");
    const retry = container.querySelector('[data-action="RETRY_RUN"]')!;
    expect(retry).toHaveAttribute("aria-disabled", "true");
    const cancel = container.querySelector('[data-action="CANCEL_RUN"]')!;
    expect(cancel).not.toHaveAttribute("aria-disabled");
  });

  // MAX-18: the fingerprint start and retry send lives only in this session. A
  // reload forgets it, and on a run whose subject is pinned and whose gates
  // are both released there is no pin and no approval left to press -- Start
  // and Retry stayed refused COMMAND_EXPECTATION_STALE however many previews
  // were read. A preview carries the pinned input's fingerprint as the server
  // computed it, so reading one is what recovers them.
  test("test_a_preview_read_after_a_reload_makes_start_and_retry_usable", async () => {
    const run = running.body.run!;
    expect(run.gates.every((gate) => gate.state === "RELEASED")).toBe(true);
    const fingerprint = "9".repeat(64);
    const preview = {
      run_id: run.run_id,
      gate: "SOURCE_SET",
      content: "SOURCE SET PREVIEW\n",
      preview_sha256: "8".repeat(64),
      input_fingerprint: fingerprint,
      observed_at: "2026-09-14T10:00:00Z",
    };
    const doc = withActions(running, [
      { action: "PIN_RUN_INPUT", refusal: { code: "RUN_ALREADY_STARTED", clears: "never" } },
      { action: "START_RUN", refusal: null },
      { action: "RETRY_RUN", refusal: null },
    ]);
    const fetchSpy = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse(preview))
      .mockResolvedValueOnce(
        jsonResponse({
          run_id: run.run_id,
          run_status: "RUNNING",
          work: { state: "QUEUED", stop_code: null, cancel_requested: false },
        }),
      )
      .mockResolvedValue(jsonResponse(doc));
    vi.stubGlobal("fetch", fetchSpy);
    try {
      const { container } = mount(doc);
      const start = () => container.querySelector('[data-action="START_RUN"]')!;
      const retry = () => container.querySelector('[data-action="RETRY_RUN"]')!;
      expect(start()).toHaveAttribute("data-refusal", "COMMAND_EXPECTATION_STALE");
      expect(retry()).toHaveAttribute("data-refusal", "COMMAND_EXPECTATION_STALE");

      fireEvent.click(
        container.querySelector('[data-gate-panel="SOURCE_SET"] [data-action="PREVIEW"]')!,
      );
      await waitFor(() => expect(start()).not.toHaveAttribute("aria-disabled"));
      expect(retry()).not.toHaveAttribute("aria-disabled");
      // The preview that was read is still on screen: the panel that read it
      // was not remounted for the fingerprint it carried.
      expect(
        container.querySelector('[data-gate-panel="SOURCE_SET"] [data-gate-preview-content]'),
      ).toHaveTextContent("SOURCE SET PREVIEW");

      fireEvent.click(start());
      await waitFor(() => expect(fetchSpy.mock.calls.length).toBeGreaterThanOrEqual(2));
      const [startUrl, startInit] = fetchSpy.mock.calls[1]!;
      expect(startUrl).toBe(`/api/v1/cases/${running.body.case_id}/runs/${run.run_id}/start`);
      expect(JSON.parse((startInit as RequestInit).body as string)).toEqual({
        input_fingerprint: fingerprint,
      });
    } finally {
      vi.unstubAllGlobals();
    }
  });

  // A parked run's stop code is the store's answer to "why is this stopped";
  // without it an operator sees Start and Retry refused and nothing else.
  test("test_a_parked_run_names_its_stop_code_beside_the_work_controls", () => {
    const parkedRun = {
      ...running.body.run!,
      work: {
        state: "STOPPED" as const,
        stop_code: "EVIDENCE_NOT_AVAILABLE" as const,
        cancel_requested: false,
      },
    };
    const parked = withActions({ ...running, body: { ...running.body, run: parkedRun } }, [
      { action: "START_RUN", refusal: { code: "RUN_ALREADY_STARTED", clears: "never" } },
    ]);
    const { container } = mount(parked);
    const panel = container.querySelector("[data-work-controls]")!;
    const stop = panel.querySelector("[data-stop-code]")!;
    expect(stop).toHaveAttribute("data-stop-code", "EVIDENCE_NOT_AVAILABLE");
    // Stated in words, not by colour: the state and the code are both text.
    expect(stop).toHaveTextContent(/stopped/i);
    expect(stop).toHaveTextContent("EVIDENCE_NOT_AVAILABLE");
    // Labelled for assistive technology as what it is.
    expect(stop).toHaveAccessibleName(/stop code/i);

    const { container: live } = mount(running);
    expect(live.querySelector("[data-stop-code]")).toBeNull();
    const cleared = { ...parkedRun, work: { ...parkedRun.work, stop_code: null } };
    const { container: none } = mount({ ...running, body: { ...running.body, run: cleared } });
    expect(none.querySelector("[data-stop-code]")).toBeNull();
  });

  test("test_the_preview_text_is_shown_exactly_before_approval", async () => {
    const run = routeNotPinned.body.run!;
    const CONTENT = "RESEARCH PLAN PREVIEW\n\n  - line with leading spaces\n  - and a second\n";
    const receipt = {
      run_id: run.run_id,
      gate: "RESEARCH_PLAN",
      content: CONTENT,
      preview_sha256: "a".repeat(64),
      input_fingerprint: "b".repeat(64),
      observed_at: "2026-09-14T10:00:00Z",
    };
    const fetchSpy = vi.fn().mockResolvedValue(jsonResponse(receipt));
    vi.stubGlobal("fetch", fetchSpy);
    try {
      const doc = withActions(routeNotPinned, [{ action: "APPROVE_RESEARCH_PLAN", refusal: null }]);
      const { container } = mount(doc);
      const previewButton = container.querySelector(
        '[data-gate-panel="RESEARCH_PLAN"] [data-action="PREVIEW"]',
      )!;
      fireEvent.click(previewButton);

      const pre = await waitFor(() => {
        const found = container.querySelector(
          '[data-gate-panel="RESEARCH_PLAN"] [data-gate-preview-content]',
        );
        if (!found) throw new Error("preview not yet rendered");
        return found;
      });
      // Exact content, not trimmed or reformatted: invariant 5 binds approval
      // to precisely what was read.
      expect(pre.textContent).toBe(CONTENT);

      const approve = container.querySelector(
        '[data-gate-panel="RESEARCH_PLAN"] [data-action="APPROVE_RESEARCH_PLAN"]',
      )!;
      await waitFor(() => expect(approve).not.toHaveAttribute("aria-disabled"));

      fireEvent.click(approve);
      await waitFor(() => expect(fetchSpy).toHaveBeenCalledTimes(2));
      const [, init] = fetchSpy.mock.calls[1]!;
      expect(JSON.parse((init as RequestInit).body as string)).toEqual({
        preview_sha256: receipt.preview_sha256,
        input_fingerprint: receipt.input_fingerprint,
      });
    } finally {
      vi.unstubAllGlobals();
    }
  });

  test("test_a_stale_preview_is_cleared_when_the_pinned_input_changes", async () => {
    const run = routeNotPinned.body.run!;
    const previewReceipt = {
      run_id: run.run_id,
      gate: "RESEARCH_PLAN",
      content: "FIRST PREVIEW\n",
      preview_sha256: "1".repeat(64),
      input_fingerprint: "2".repeat(64),
      observed_at: "2026-09-14T10:00:00Z",
    };
    const pinReceipt = {
      run_id: run.run_id,
      source_set_version: run.source_set_version,
      input_fingerprint: "3".repeat(64),
    };
    const doc = withActions(routeNotPinned, [
      { action: "APPROVE_RESEARCH_PLAN", refusal: null },
      { action: "PIN_RUN_INPUT", refusal: null },
    ]);
    const fetchSpy = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse(previewReceipt))
      .mockResolvedValueOnce(jsonResponse(pinReceipt))
      // The refetch after the pin still serves the same actions: only the
      // fingerprint moved, not what this actor may do.
      .mockResolvedValueOnce(jsonResponse(doc));
    vi.stubGlobal("fetch", fetchSpy);
    try {
      const { container } = mount(doc);
      fireEvent.click(
        container.querySelector('[data-gate-panel="RESEARCH_PLAN"] [data-action="PREVIEW"]')!,
      );
      await waitFor(() =>
        expect(
          container.querySelector('[data-gate-panel="RESEARCH_PLAN"] [data-gate-preview-content]'),
        ).not.toBeNull(),
      );
      const approveBefore = container.querySelector(
        '[data-gate-panel="RESEARCH_PLAN"] [data-action="APPROVE_RESEARCH_PLAN"]',
      )!;
      expect(approveBefore).not.toHaveAttribute("aria-disabled");

      fireEvent.click(container.querySelector('[data-action="PIN_RUN_INPUT"]')!);
      await waitFor(() =>
        expect(
          container.querySelector('[data-gate-panel="RESEARCH_PLAN"] [data-gate-preview-content]'),
        ).toBeNull(),
      );
      const approveAfter = container.querySelector(
        '[data-gate-panel="RESEARCH_PLAN"] [data-action="APPROVE_RESEARCH_PLAN"]',
      )!;
      expect(approveAfter).toHaveAttribute("aria-disabled", "true");
      expect(approveAfter).toHaveAttribute("data-refusal", "GATE_PREVIEW_NOT_READ");
    } finally {
      vi.unstubAllGlobals();
    }
  });

  // FE-10: the note says this view is behind the run. A document the
  // workspace has since served is that view caught up.
  test("test_a_fresh_document_clears_the_could_not_be_refreshed_note", async () => {
    const older = withActions(frames[0]!, [{ action: "CANCEL_RUN", refusal: null }]);
    const receipt = {
      run_id: older.body.run!.run_id,
      run_status: "RUNNING",
      work: { state: "STOPPED", stop_code: null, cancel_requested: false },
    };
    const fetchSpy = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse(receipt))
      .mockResolvedValueOnce(jsonResponse({ code: "STORE_UNAVAILABLE", clears: "x" }, 503));
    vi.stubGlobal("fetch", fetchSpy);
    try {
      const { container, rerender } = mount(older);
      confirmed(container, "CANCEL_RUN");
      await waitFor(() => expect(container.querySelector("[data-refetch-failed]")).not.toBeNull());
      rerender(
        <MemoryRouter>
          <RunSection document={frames[2]!} tab={null} />
        </MemoryRouter>,
      );
      expect(container.querySelector("[data-refetch-failed]")).toBeNull();
    } finally {
      vi.unstubAllGlobals();
    }
  });

  test("test_start_retry_and_cancel_post_the_expected_url_body_and_idempotency_key", async () => {
    const run = running.body.run!;
    const caseId = running.body.case_id;
    const fingerprint = "4".repeat(64);
    const workReceipt = (state: "QUEUED" | "STOPPED") => ({
      run_id: run.run_id,
      run_status: "RUNNING",
      work: { state, stop_code: null, cancel_requested: false },
    });
    const doc = withActions(running, [
      { action: "PIN_RUN_INPUT", refusal: null },
      { action: "START_RUN", refusal: null },
      { action: "RETRY_RUN", refusal: null },
      { action: "CANCEL_RUN", refusal: null },
    ]);
    const fetchSpy = vi
      .fn()
      .mockResolvedValueOnce(
        jsonResponse({
          run_id: run.run_id,
          source_set_version: run.source_set_version,
          input_fingerprint: fingerprint,
        }),
      )
      // Every refetch still serves the same actions: only the run's own
      // state moved, not what this actor may do.
      .mockResolvedValueOnce(jsonResponse(doc))
      .mockResolvedValueOnce(jsonResponse(workReceipt("QUEUED")))
      .mockResolvedValueOnce(jsonResponse(doc))
      .mockResolvedValueOnce(jsonResponse(workReceipt("QUEUED")))
      .mockResolvedValueOnce(jsonResponse(doc))
      .mockResolvedValueOnce(jsonResponse(workReceipt("STOPPED")))
      .mockResolvedValueOnce(jsonResponse(doc));
    vi.stubGlobal("fetch", fetchSpy);
    try {
      const { container } = mount(doc);
      fireEvent.click(container.querySelector('[data-action="PIN_RUN_INPUT"]')!);
      await waitFor(() => expect(fetchSpy).toHaveBeenCalledTimes(2));

      fireEvent.click(container.querySelector('[data-action="START_RUN"]')!);
      await waitFor(() => expect(fetchSpy).toHaveBeenCalledTimes(4));
      fireEvent.click(container.querySelector('[data-action="RETRY_RUN"]')!);
      await waitFor(() => expect(fetchSpy).toHaveBeenCalledTimes(6));
      confirmed(container, "CANCEL_RUN");
      await waitFor(() => expect(fetchSpy).toHaveBeenCalledTimes(8));

      const [startUrl, startInit] = fetchSpy.mock.calls[2]!;
      expect(startUrl).toBe(`/api/v1/cases/${caseId}/runs/${run.run_id}/start`);
      expect(JSON.parse((startInit as RequestInit).body as string)).toEqual({
        input_fingerprint: fingerprint,
      });

      const [retryUrl, retryInit] = fetchSpy.mock.calls[4]!;
      expect(retryUrl).toBe(`/api/v1/cases/${caseId}/runs/${run.run_id}/retry`);
      expect(JSON.parse((retryInit as RequestInit).body as string)).toEqual({
        input_fingerprint: fingerprint,
      });

      const [cancelUrl, cancelInit] = fetchSpy.mock.calls[6]!;
      expect(cancelUrl).toBe(`/api/v1/cases/${caseId}/runs/${run.run_id}/cancel`);
      expect(JSON.parse((cancelInit as RequestInit).body as string)).toEqual({});

      const keyOf = (init: unknown): string =>
        ((init as RequestInit).headers as Record<string, string>)["Idempotency-Key"] ?? "";
      const [startKey, retryKey, cancelKey] = [
        keyOf(startInit),
        keyOf(retryInit),
        keyOf(cancelInit),
      ];
      for (const key of [startKey, retryKey, cancelKey]) expect(UUID.test(key)).toBe(true);
      expect(new Set([startKey, retryKey, cancelKey]).size).toBe(3);
    } finally {
      vi.unstubAllGlobals();
    }
  });

  // Through the section, not the helpers: the graph, the detail and the run
  // panel all read `blocked_by`, and a reader should find the same answer in
  // each. `rn-cp-6` is the fixture's one RUNNABLE node and holds an unaccepted
  // attempt, which is exactly the shape a validated Blocked verdict leaves.
  test("test_a_blocked_run_names_the_node_whose_verdict_ended_it_or_says_no_node_did", () => {
    const base = running.body.run!;
    const attempt = base.attempts.find((a) => a.route_node_id === "rn-cp-6" && a.ordinal === 1)!;
    const byVerdict: RunSectionDocument = {
      ...running,
      body: {
        ...running.body,
        run: {
          ...base,
          status: "BLOCKED",
          blocked_by: {
            route_node_id: "rn-cp-6",
            module_id: "CP-6",
            attempt_id: attempt.attempt_id,
          },
        },
      },
    };
    const { container, unmount } = mount(byVerdict);
    const node = container.querySelector<HTMLButtonElement>(
      "button.node[data-route-node='rn-cp-6']",
    )!;
    expect(node.getAttribute("data-blocking")).toBe("yes");
    expect(node.textContent).toMatch(/blocked the run/i);
    expect(node.textContent).toContain("answered Blocked");
    expect(node.textContent).not.toMatch(/frontier/i);
    expect(node.classList.contains("running")).toBe(false);
    for (const other of container.querySelectorAll(
      "button.node:not([data-route-node='rn-cp-6'])",
    )) {
      expect(other.getAttribute("data-blocking")).toBe("no");
    }
    const panel = container.querySelector("[data-blocked-by]")!;
    expect(panel.getAttribute("data-blocked-by")).toBe("CP-6");
    expect(panel.textContent).toBe("CP-6 answered Blocked on attempt 1 · rn-cp-6");
    fireEvent.click(node);
    const detail = container.querySelector("[data-node-detail='CP-6']")!;
    expect(detail.textContent).toContain("answered Blocked · ended the run");
    expect(detail.textContent).not.toContain("did not run");
    const rows = container.querySelectorAll("[data-blocking-attempt]");
    expect(rows).toHaveLength(1);
    expect(rows[0]!.textContent).toContain("Blocked · not accepted");
    unmount();

    // The other way a run ends BLOCKED (§39): no verdict, so no node is named
    // and the RUNNABLE node simply did not run.
    const emptied: RunSectionDocument = {
      ...running,
      body: { ...running.body, run: { ...base, status: "BLOCKED", blocked_by: null } },
    };
    const second = mount(emptied);
    const idle = second.container.querySelector("button.node[data-route-node='rn-cp-6']")!;
    expect(idle.getAttribute("data-blocking")).toBe("no");
    expect(idle.textContent).toMatch(/did not run/i);
    expect(second.container.querySelector("[data-blocked-by]")!.textContent).toBe(
      "no node's verdict — the frontier emptied with required work unfinished",
    );
    expect(second.container.querySelectorAll("[data-blocking-attempt]")).toHaveLength(0);
    second.unmount();

    // A running run has no such line at all.
    const third = mount(running);
    expect(third.container.querySelector("[data-blocked-by]")).toBeNull();
    third.unmount();
  });

  // The successor link (§72), both ends, in the run panel: a run says which
  // run it answers, and a run that has been answered says by which. A run with
  // neither carries no such line, so nothing here renders "none" as a link.
  test("test_the_run_panel_names_the_run_a_successor_replaces", () => {
    const base = running.body.run!;
    const earlier = "00000000-0000-4000-8000-0000000000e1";
    const later = "00000000-0000-4000-8000-0000000000e2";
    const successor: RunSectionDocument = {
      ...running,
      body: { ...running.body, run: { ...base, supersedes: earlier } },
    };
    const first = mount(successor);
    const supersedes = first.container.querySelector("[data-supersedes]")!;
    expect(supersedes.textContent).toContain(earlier);
    expect(supersedes.querySelector("a")!.getAttribute("href")).toContain(`run=${earlier}`);
    expect(first.container.querySelector("[data-superseded-by]")).toBeNull();
    first.unmount();

    const answered: RunSectionDocument = {
      ...running,
      body: {
        ...running.body,
        run: { ...base, status: "BLOCKED", blocked_by: null, superseded_by: later },
      },
    };
    const second = mount(answered);
    const supersededBy = second.container.querySelector("[data-superseded-by]")!;
    expect(supersededBy.textContent).toContain(later);
    expect(supersededBy.querySelector("a")!.getAttribute("href")).toContain(`run=${later}`);
    expect(second.container.querySelector("[data-supersedes]")).toBeNull();
    second.unmount();

    const third = mount(running);
    expect(third.container.querySelector("[data-supersedes]")).toBeNull();
    expect(third.container.querySelector("[data-superseded-by]")).toBeNull();
    third.unmount();
  });

  // A BLOCKED run nobody has answered is what a successor is for: the create
  // control offers `supersedes` pre-filled with it, the analyst may clear it,
  // and the body sent carries whatever the field holds. A run already
  // answered, or one that is not BLOCKED, offers nothing to pre-fill.
  test("test_a_blocked_run_not_yet_answered_offers_supersedes_prefilled", async () => {
    const base = running.body.run!;
    const caseId = running.body.case_id;
    const choices = [
      {
        profile_id: "LITE_CREDIT_22",
        selection_id: "LITE_EARNINGS_UPDATE",
        accepts_model_extension: false,
      },
    ];
    const blocked: RunSectionDocument = withActions(
      {
        ...running,
        body: {
          ...running.body,
          route_choices: choices,
          run: { ...base, status: "BLOCKED", blocked_by: null },
        },
      },
      [{ action: "CREATE_RUN", refusal: null }],
    );
    const created = { case_id: caseId, run_id: base.run_id, route_digest: "f".repeat(64) };
    const fetchSpy = vi.fn().mockResolvedValueOnce(jsonResponse(created, 201));
    vi.stubGlobal("fetch", fetchSpy);
    try {
      const { container, unmount } = mountAt(blocked, `/run/?case=${caseId}`);
      const field = container.querySelector<HTMLInputElement>("[data-supersedes-input]")!;
      expect(field.value).toBe(base.run_id);
      fireEvent.click(container.querySelector('[data-action="CREATE_RUN"]')!);
      await waitFor(() => expect(fetchSpy).toHaveBeenCalledTimes(1));
      const [, init] = fetchSpy.mock.calls[0]!;
      expect(JSON.parse((init as RequestInit).body as string).supersedes).toBe(base.run_id);
      unmount();
    } finally {
      vi.unstubAllGlobals();
    }

    const answered: RunSectionDocument = withActions(
      {
        ...running,
        body: {
          ...running.body,
          route_choices: choices,
          run: {
            ...base,
            status: "BLOCKED",
            blocked_by: null,
            superseded_by: "00000000-0000-4000-8000-0000000000e2",
          },
        },
      },
      [{ action: "CREATE_RUN", refusal: null }],
    );
    const second = mount(answered);
    const answeredField =
      second.container.querySelector<HTMLInputElement>("[data-supersedes-input]")!;
    expect(answeredField.value).toBe("");
    second.unmount();

    const third = mount(
      withActions({ ...running, body: { ...running.body, route_choices: choices } }, [
        { action: "CREATE_RUN", refusal: null },
      ]),
    );
    const runningField =
      third.container.querySelector<HTMLInputElement>("[data-supersedes-input]")!;
    expect(runningField.value).toBe("");
    third.unmount();
  });

  test("test_every_enabled_demo_fixture_is_a_valid_v1_document", () => {
    const fixtures = [
      "../../fixtures/run.json",
      "../../fixtures/states/run.gate.json",
      "../../fixtures/states/run.superseded.json",
      "../../fixtures/run/frames/1.json",
      "../../fixtures/run/frames/2.json",
      "../../fixtures/run/frames/3.json",
      "../../fixtures/run/frames/4.json",
    ];
    for (const path of fixtures) {
      expect(() => parseRunSectionDocument(load(path))).not.toThrow();
    }
  });
});

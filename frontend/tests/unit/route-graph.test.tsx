// The route diagram brings the stages where the work is into view (critique:
// a wide route hid its frontier past the panel's right edge), once per route.
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { render } from "@testing-library/react";
import {
  edgesOf,
  focusOf,
  layoutRoute,
  routeOf,
  RouteGraph,
  stageLabel,
} from "@/sections/run/RouteGraph";
import { cardReasonOf } from "@/sections/run/reason";
import { parseRunSectionDocument } from "@/wire/v1";

const run = () => {
  const text = readFileSync(resolve(process.cwd(), "fixtures/run.json"), "utf8");
  const document = parseRunSectionDocument(JSON.parse(text));
  if (!document.body.run) throw new Error("the run fixture displays a run");
  return document.body.run;
};

function graph(view: ReturnType<typeof run>) {
  return (
    <RouteGraph
      nodes={view.nodes}
      attempts={view.attempts}
      status={view.status}
      blockedBy={view.blocked_by}
      selected={null}
      onSelect={() => {}}
    />
  );
}

test("the route opens scrolled to the node the work waits on, and only once", () => {
  const view = run();
  // `rn-cp-6` is the frontier node waiting on its gate in the fixture.
  const target = layoutRoute(view.nodes).nodes.find((node) => node.route_node_id === "rn-cp-6");
  const { container, rerender } = render(graph(view));
  const dag = container.querySelector<HTMLDivElement>(".dag")!;
  // jsdom lays nothing out, so the panel is 0 wide and the target sits at the edge.
  expect(dag.scrollLeft).toBe(target!.x);
  // A reader who scrolls away is not pulled back by the next refetch.
  dag.scrollLeft = 0;
  rerender(graph(run()));
  expect(dag.scrollLeft).toBe(0);
});

test("an edge the host names by its module is drawn to that module's node", () => {
  // The host names a node `RN-{profile}-{selection}-{stage}-{module}` and an
  // edge's source by its module (`EdgeView(source="CP-5")`): read by route
  // node id alone, the canvas drew no line and no gate from a real host.
  const view = run();
  const rn = (module: string) => `RN-FULL_CREDIT_32-RELATIVE_VALUE-${module}`;
  const host = view.nodes.map((node) => ({
    ...node,
    route_node_id: rn(node.module_id),
    waiting_on: node.waiting_on.map((edge) => ({
      ...edge,
      source: view.nodes.find((n) => n.route_node_id === edge.source)?.module_id ?? edge.source,
    })),
  }));
  const edges = edgesOf(host);
  expect(edges.length).toBeGreaterThan(0);
  for (const edge of edges)
    expect(host.some((node) => node.route_node_id === edge.from)).toBe(true);
  const { container } = render(graph({ ...view, nodes: host }));
  expect(container.querySelectorAll(".dag .edges path").length).toBe(edges.length);
  expect(container.querySelector("[data-gate]")).toHaveAttribute("data-gate", "CP-5 → CP-6");
});

test("a node card says its reason without the edges it names (D72)", () => {
  const blocked = {
    state: "BLOCKED" as const,
    waiting_on: [
      { source: "CP-2", type: "REQUIRED" as const },
      { source: "CP-3", type: "REQUIRED" as const },
    ],
    gate_verdict: null,
    awaiting_gate: false,
  };
  expect(cardReasonOf(blocked, "RUNNING")).toBe("waits on 2 edges");
  expect(cardReasonOf({ ...blocked, state: "RESTRICTED" }, "RUNNING")).toBe("runs without 2 edges");
  expect(cardReasonOf({ ...blocked, state: "RUNNABLE", awaiting_gate: true }, "RUNNING")).toBe(
    "awaiting the gate",
  );
  expect(cardReasonOf({ ...blocked, state: "COMPLETE" }, "RUNNING")).toBe("accepted");
  // The gate's own verdict is the cause, and short: it stays on the card.
  expect(
    cardReasonOf(
      { ...blocked, state: "RESTRICTED", gate_verdict: "READY_WITH_LIMITATIONS" },
      "RUNNING",
    ),
  ).toBe("READY_WITH_LIMITATIONS");
  expect(cardReasonOf(blocked, "BLOCKED", true)).toBe("answered Blocked · ended the run");
});

test("a stage column is numbered, and the host's CP-CF extension is named", () => {
  expect(stageLabel(3)).toBe("Stage 3");
  expect(stageLabel(100)).toBe("Extension");
  const { container } = render(graph(run()));
  const heads = [...container.querySelectorAll(".stagehdr")].map((head) => head.textContent);
  expect(heads).toContain("Extension");
  expect(heads).not.toContain("Stage 100");
});

test("an edge is drawn square, through gutters and row gaps, never through a node", () => {
  const view = run();
  const layout = layoutRoute(view.nodes);
  const placed = (id: string) => layout.nodes.find((node) => node.route_node_id === id)!;
  // Adjacent columns: out, down the gutter before the target, in.
  const next = routeOf(placed("rn-cp-5"), placed("rn-cp-6"));
  expect(next.d).toMatch(/^M [\d.]+ [\d.]+ H [\d.]+ V [\d.]+ H [\d.]+$/);
  expect(next.at.x).toBe(placed("rn-cp-6").x - 20);
  // Across a column: along the gap above the target's row, never a diagonal.
  const across = routeOf(placed("rn-cp-4"), placed("rn-cp-7"));
  expect(across.d).not.toMatch(/ L /);
  const lane = placed("rn-cp-7").y - 6;
  expect(across.d).toContain(`V ${lane} H`);
  // The same column: straight down.
  expect(routeOf(placed("rn-cp-6"), placed("rn-cp-6a")).d).toMatch(/^M [\d.]+ [\d.]+ V [\d.]+$/);
  // Drawn as paths, the gate's diamond in the gutter before the node it holds.
  const { container } = render(graph(view));
  expect(container.querySelectorAll("svg.edges path").length).toBeGreaterThan(0);
  expect(container.querySelectorAll("svg.edges line")).toHaveLength(0);
  expect(focusOf(view.nodes, view.attempts, view.status, view.blocked_by)).toBe("rn-cp-6");
});

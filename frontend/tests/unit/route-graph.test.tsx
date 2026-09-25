// The route diagram brings the stages where the work is into view (critique:
// a wide route hid its frontier past the panel's right edge), once per route.
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { render } from "@testing-library/react";
import { focusOf, layoutRoute, routeOf, RouteGraph, stageLabel } from "@/sections/run/RouteGraph";
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

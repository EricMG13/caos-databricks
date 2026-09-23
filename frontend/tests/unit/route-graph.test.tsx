// The route diagram brings the stages where the work is into view (critique:
// a wide route hid its frontier past the panel's right edge), once per route.
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { render } from "@testing-library/react";
import { layoutRoute, RouteGraph } from "@/sections/run/RouteGraph";
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

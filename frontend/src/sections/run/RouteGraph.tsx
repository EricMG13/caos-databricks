// The resolved route as a DAG: one column per stage, one row per node in the
// stage, typed edges as SVG lines, the one QA_GATE drawn through a diamond.
// Node states are the bundle's four; edges come from each node's own
// `waiting_on` (v1 carries no separate edge list — brief 4.1, slice 4.1i).
import { useLayoutEffect, useRef } from "react";
import { RouteLegend } from "./RouteLegend";
import { blockingOf, cardReasonOf, reasonOf, runningOf, stateWordOf } from "./reason";
import { SeverityMark } from "@/chrome/SeverityMark";
import { sentence } from "@/chrome/compose";
import type { AttemptView, BlockedByView } from "./types";
import type { EdgeType, NodeState, Severity } from "@/wire";
import type { NodeView, RunView } from "@/wire/v1";

type RouteEdgeView = RunView["edges"][number];

// Sized for the type floors (DESIGN.md: 10px labels, 11px mono data): the id,
// the state and two whole lines of reason. At the old 7.5px text the node was
// 128 x 76; at 62 tall the second reason line was cut through the middle. Both
// sizes are set on each node and stage header here, not in caos.css, so each
// is one number.
/** The stage `caos/graph/route.py` appends the host's CP-CF extension at
    (`MODEL_STAGE`); on the canvas it is named, not numbered. */
const MODEL_STAGE = 100;

/** A stage column's heading: "Stage n" for the bundle's, a word for the host's. */
export function stageLabel(stage: number): string {
  return stage === MODEL_STAGE ? "Extension" : `Stage ${stage}`;
}

export const NODE_W = 152;
export const NODE_H = 92;
export const COL_GAP = 40;
export const ROW_H = NODE_H + 12;
const PAD_X = 14;
// Below a stage header clamped at two lines: 8px down, two 12.5px lines.
const TOP = 36;
const PAD_BOTTOM = 10;

export interface PlacedNode {
  route_node_id: string;
  stage: number;
  col: number;
  row: number;
  x: number;
  y: number;
}
export interface RouteLayout {
  nodes: PlacedNode[];
  columns: { stage: number; x: number }[];
  width: number;
  height: number;
}

/** Pure: columns by ascending stage, rows in the given order within a stage. */
export function layoutRoute(nodes: Pick<NodeView, "route_node_id" | "stage">[]): RouteLayout {
  const stages = [...new Set(nodes.map((node) => node.stage))].sort((a, b) => a - b);
  const columns = stages.map((stage, col) => ({ stage, x: PAD_X + col * (NODE_W + COL_GAP) }));
  const rows = new Map<number, number>();
  const placed = nodes.map((node) => {
    const col = stages.indexOf(node.stage);
    const row = rows.get(node.stage) ?? 0;
    rows.set(node.stage, row + 1);
    return {
      route_node_id: node.route_node_id,
      stage: node.stage,
      col,
      row,
      x: PAD_X + col * (NODE_W + COL_GAP),
      y: TOP + row * ROW_H,
    };
  });
  const deepest = Math.max(0, ...rows.values());
  return {
    nodes: placed,
    columns,
    width: PAD_X * 2 + stages.length * NODE_W + Math.max(0, stages.length - 1) * COL_GAP,
    height: TOP + deepest * ROW_H + PAD_BOTTOM,
  };
}

const EDGE_CLASS: Record<EdgeType, string> = {
  REQUIRED: "req",
  OPTIONAL: "opt",
  ADVISORY: "adv",
  QA_GATE: "gate",
  CONDITIONAL: "cond",
};

/** The tone a node is drawn in. `blocking` is the node whose Blocked verdict
    ended the run: its state is RUNNABLE, and the tone is the run's. */
export function severityOf(
  node: Pick<NodeView, "state">,
  running: boolean,
  blocking = false,
): Severity {
  if (blocking) return "CRITICAL";
  const by: Record<NodeState, Severity> = {
    COMPLETE: "SUCCESS",
    RUNNABLE: running ? "RUNNING" : "IDLE",
    RESTRICTED: "RESTRICTED",
    BLOCKED: "CRITICAL",
  };
  return by[node.state];
}

/** An edge drawn square (brief 6.6): out of its source's right side, down or
    up in the gutter after it, along the gap above its target's row when it
    passes other columns, and into its target's left side from the gutter
    before it -- never through another node. `at` is where the gutter before
    the target meets the target's row: a gate's diamond sits there. */
export interface EdgeRoute {
  d: string;
  at: { x: number; y: number };
}

export function routeOf(from: PlacedNode, to: PlacedNode): EdgeRoute {
  if (from.col === to.col) {
    const x = from.x + NODE_W / 2;
    const down = to.row > from.row;
    const y1 = down ? from.y + NODE_H : from.y;
    const y2 = down ? to.y : to.y + NODE_H;
    return { d: `M ${x} ${y1} V ${y2}`, at: { x, y: (y1 + y2) / 2 } };
  }
  const x1 = from.x + NODE_W;
  const y1 = from.y + NODE_H / 2;
  const y2 = to.y + NODE_H / 2;
  const before = to.x - COL_GAP / 2;
  const at = { x: before, y: y2 };
  if (to.col === from.col + 1) return { d: `M ${x1} ${y1} H ${before} V ${y2} H ${to.x}`, at };
  const after = x1 + COL_GAP / 2;
  const lane = to.y - (ROW_H - NODE_H) / 2;
  return { d: `M ${x1} ${y1} H ${after} V ${lane} H ${before} V ${y2} H ${to.x}`, at };
}

interface EdgeLine {
  from: string;
  to: string;
  type: EdgeType;
}

/** Every edge the route carries, as the route's own list serves it (D73) --
    met or not, so a finished route still draws as its graph; a node's
    `waiting_on` is only what it still waits for, and is its reason, not the
    route's shape. The host names both ends by module (`CP-5`) and a node by
    its route node id (`RN-…-CP-5`); a route holds each module once
    (`ROUTE_DUPLICATE_MODULE`), so an end resolves to its node either way
    (F415). */
export function edgesOf(
  nodes: readonly Pick<NodeView, "route_node_id" | "module_id">[],
  edges: readonly RouteEdgeView[],
): EdgeLine[] {
  const ids = new Set(nodes.map((node) => node.route_node_id));
  const byModule = new Map(nodes.map((node) => [node.module_id, node.route_node_id]));
  const nodeOf = (end: string) => (ids.has(end) ? end : (byModule.get(end) ?? end));
  return edges.map((edge) => ({
    from: nodeOf(edge.source),
    to: nodeOf(edge.target),
    type: edge.type,
  }));
}

/** Where the work is: a running node, then a blocking one, then one waiting on
    a gate, then the frontier; a finished route shows its end. The canvas
    opens scrolled to it, and Run's rail opens on it, so the two agree. */
export function focusOf(
  nodes: NodeView[],
  attempts: AttemptView[],
  status: RunView["status"],
  blockedBy: BlockedByView | null,
): string | null {
  const first = (test: (node: NodeView) => boolean) => nodes.find(test)?.route_node_id;
  return (
    first((node) => runningOf(node, attempts, status)) ??
    first((node) => blockingOf(node, blockedBy)) ??
    first((node) => node.awaiting_gate) ??
    first((node) => node.state === "RUNNABLE") ??
    nodes.at(-1)?.route_node_id ??
    null
  );
}

export function RouteGraph({
  nodes,
  edges: routeEdges,
  attempts,
  status,
  blockedBy,
  selected,
  onSelect,
}: {
  nodes: NodeView[];
  /** The pinned route's own edges (D73). */
  edges: readonly RouteEdgeView[];
  attempts: AttemptView[];
  status: RunView["status"];
  blockedBy: BlockedByView | null;
  selected: string | null;
  onSelect: (routeNodeId: string) => void;
}) {
  const layout = layoutRoute(nodes);
  const at = new Map(layout.nodes.map((placed) => [placed.route_node_id, placed]));
  const moduleOf = new Map(nodes.map((node) => [node.route_node_id, node.module_id]));
  const edges = edgesOf(nodes, routeEdges);
  const lines: { key: string; cls: string; d: string }[] = [];
  let gate: { at: EdgeRoute["at"]; from: string; to: string } | null = null;
  for (const edge of edges) {
    const from = at.get(edge.from);
    const to = at.get(edge.to);
    if (!from || !to) continue;
    const route = routeOf(from, to);
    if (edge.type === "QA_GATE" && !gate) {
      gate = {
        at: route.at,
        from: moduleOf.get(edge.from) ?? edge.from,
        to: moduleOf.get(edge.to) ?? edge.to,
      };
    }
    lines.push({ key: `${edge.from}→${edge.to}`, cls: EDGE_CLASS[edge.type], d: route.d });
  }
  // A wide route hid its frontier past the panel's right edge (critique): the
  // stages where the work is are brought into view once per route, and never
  // again, so a reader's own scrolling is left alone.
  const box = useRef<HTMLDivElement>(null);
  const shown = useRef<string | null>(null);
  const focus = focusOf(nodes, attempts, status, blockedBy);
  const focusX = focus === null ? null : (at.get(focus)?.x ?? null);
  const routeKey = nodes.map((node) => node.route_node_id).join("|");
  useLayoutEffect(() => {
    const dag = box.current;
    if (!dag || focusX === null || shown.current === routeKey) return;
    shown.current = routeKey;
    dag.scrollLeft = Math.max(0, focusX - dag.clientWidth / 3);
  }, [routeKey, focusX]);
  return (
    <>
      <div ref={box} className="dag" data-route={`${nodes.length} nodes · ${edges.length} edges`}>
        <div className="dagbox" style={{ width: layout.width, height: layout.height }}>
          <svg
            className="edges"
            viewBox={`0 0 ${layout.width} ${layout.height}`}
            preserveAspectRatio="none"
            aria-hidden="true"
          >
            {lines.map(({ key, cls, d }) => (
              <path key={key} className={cls} d={d} />
            ))}
          </svg>
          {layout.columns.map((column) => (
            <span
              key={column.stage}
              className="stagehdr"
              style={{ left: column.x, width: NODE_W }}
              title={stageLabel(column.stage)}
            >
              {stageLabel(column.stage)}
            </span>
          ))}
          {nodes.map((node) => {
            const placed = at.get(node.route_node_id);
            if (!placed) return null;
            const running = runningOf(node, attempts, status);
            const blocking = blockingOf(node, blockedBy);
            const on = node.route_node_id === selected;
            const cls = `node ${node.state.toLowerCase()}${running ? " running" : ""}${blocking ? " blocking" : ""}${node.awaiting_gate ? " gate" : ""}${on ? " sel" : ""}`;
            return (
              <button
                key={node.route_node_id}
                type="button"
                className={cls}
                data-node={node.module_id}
                data-route-node={node.route_node_id}
                // The card is sized for the id and its state; the catalog's
                // name and the whole reason, edges named, are its tooltip and
                // description (D72).
                title={[
                  node.module_name === node.module_id ? null : node.module_name,
                  reasonOf(node, status, blocking),
                ]
                  .filter(Boolean)
                  .join("\n")}
                data-state={node.state}
                data-blocking={blocking ? "yes" : "no"}
                aria-pressed={on}
                style={{ left: placed.x, top: placed.y, width: NODE_W, height: NODE_H }}
                onClick={() => onSelect(node.route_node_id)}
              >
                <span className="id">{node.module_id}</span>
                <span className="st">
                  <SeverityMark
                    severity={severityOf(node, running, blocking)}
                    pulse={running}
                    decorative
                  />
                  {sentence(stateWordOf(node, status, running, blocking))}
                </span>
                <span className="why">{cardReasonOf(node, status, blocking)}</span>
              </button>
            );
          })}
          {gate ? (
            <div
              className="gatemark"
              data-gate={`${gate.from} → ${gate.to}`}
              style={{ left: gate.at.x, top: gate.at.y }}
            >
              <span className="gatebox" aria-hidden="true" />
              {/* The legend keys the diamond; its name is said, not printed
                  across the gutter where it ran into both nodes. */}
              <span className="gatelbl sr-only">QA_GATE</span>
            </div>
          ) : null}
        </div>
      </div>
      <RouteLegend />
    </>
  );
}

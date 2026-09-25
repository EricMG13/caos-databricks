// The resolved route as a DAG: one column per stage, one row per node in the
// stage, typed edges as SVG lines, the one QA_GATE drawn through a diamond.
// Node states are the bundle's four; edges come from each node's own
// `waiting_on` (v1 carries no separate edge list — brief 4.1, slice 4.1i).
import { useLayoutEffect, useRef } from "react";
import { RouteLegend } from "./RouteLegend";
import { blockingOf, reasonOf, runningOf, stateWordOf } from "./reason";
import { SeverityMark } from "@/chrome/SeverityMark";
import { sentence } from "@/chrome/compose";
import type { AttemptView, BlockedByView } from "./types";
import type { EdgeType, NodeState, Severity } from "@/wire";
import type { NodeView, RunView } from "@/wire/v1";

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

interface Segment {
  x1: number;
  y1: number;
  x2: number;
  y2: number;
}
function segment(from: PlacedNode, to: PlacedNode): Segment {
  if (from.col === to.col) {
    const down = to.row > from.row;
    return {
      x1: from.x + NODE_W / 2,
      y1: down ? from.y + NODE_H : from.y,
      x2: to.x + NODE_W / 2,
      y2: down ? to.y : to.y + NODE_H,
    };
  }
  return { x1: from.x + NODE_W, y1: from.y + NODE_H / 2, x2: to.x, y2: to.y + NODE_H / 2 };
}

interface EdgeLine {
  from: string;
  to: string;
  type: EdgeType;
}

/** Every edge the route carries, derived from each node's own `waiting_on`. */
export function edgesOf(
  nodes: readonly Pick<NodeView, "route_node_id" | "waiting_on">[],
): EdgeLine[] {
  const lines: EdgeLine[] = [];
  for (const node of nodes) {
    for (const edge of node.waiting_on) {
      lines.push({ from: edge.source, to: node.route_node_id, type: edge.type });
    }
  }
  return lines;
}

/** Where the work is: a running node, then a blocking one, then one waiting on
    a gate, then the frontier; a finished route shows its end. */
function focusOf(
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
  attempts,
  status,
  blockedBy,
  selected,
  onSelect,
}: {
  nodes: NodeView[];
  attempts: AttemptView[];
  status: RunView["status"];
  blockedBy: BlockedByView | null;
  selected: string | null;
  onSelect: (routeNodeId: string) => void;
}) {
  const layout = layoutRoute(nodes);
  const at = new Map(layout.nodes.map((placed) => [placed.route_node_id, placed]));
  const moduleOf = new Map(nodes.map((node) => [node.route_node_id, node.module_id]));
  const edges = edgesOf(nodes);
  const lines: { key: string; cls: string; seg: Segment }[] = [];
  let gate: { seg: Segment; from: string; to: string } | null = null;
  for (const edge of edges) {
    const from = at.get(edge.from);
    const to = at.get(edge.to);
    if (!from || !to) continue;
    const seg = segment(from, to);
    if (edge.type === "QA_GATE" && !gate) {
      gate = {
        seg,
        from: moduleOf.get(edge.from) ?? edge.from,
        to: moduleOf.get(edge.to) ?? edge.to,
      };
    }
    lines.push({ key: `${edge.from}→${edge.to}`, cls: EDGE_CLASS[edge.type], seg });
  }
  const gateMid = gate
    ? { x: (gate.seg.x1 + gate.seg.x2) / 2, y: (gate.seg.y1 + gate.seg.y2) / 2 }
    : null;
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
            {lines.map(({ key, cls, seg }) => (
              <line key={key} className={cls} x1={seg.x1} y1={seg.y1} x2={seg.x2} y2={seg.y2} />
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
                // The card is sized for the id; the catalog's name is the tooltip.
                title={node.module_name}
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
                <span className="why">{reasonOf(node, status, blocking)}</span>
              </button>
            );
          })}
          {gate && gateMid ? (
            <div
              className="gatemark"
              data-gate={`${gate.from} → ${gate.to}`}
              style={{ left: gateMid.x, top: gateMid.y }}
            >
              <span className="gatebox" aria-hidden="true" />
              <span className="gatelbl">QA_GATE</span>
            </div>
          ) : null}
        </div>
      </div>
      <RouteLegend />
    </>
  );
}

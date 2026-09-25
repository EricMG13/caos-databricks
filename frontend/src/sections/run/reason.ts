// Node states are the bundle's, recomputed from accepted attempts — never
// stored (CLAUDE.md invariant 10, "recovery is recomputation"). `reasonOf`
// renders the wire's own words: `gate_verdict` when the gate named one
// (CLAUDE.md Phase 5 ledger, "the workspace cannot show the cause" — now it
// can), else the typed edges this node is waiting on.
import type { AttemptView, BlockedByView } from "./types";
import type { NodeView, RunView } from "@/wire/v1";

/** Every direct edge this node names, as `TYPE source`. */
function edgesOf(node: Pick<NodeView, "waiting_on">): string {
  return node.waiting_on.map((edge) => `${edge.type} ${edge.source}`).join(" · ");
}

/** Whether the run has stopped moving. `RUNNING` is the only state with work
    ahead of it; the other four are ends, and a node's readiness on an ended run
    says what was ready when it stopped, not what happens next. */
function ended(status: RunView["status"]): boolean {
  return status !== "RUNNING";
}

/** The cause the wire carries for this node's state: the gate's own verdict
    when the gate named one, else the typed edges it names. Never invented.

    The run's status is read too, because a node state alone cannot say it. Node
    states are recomputed from accepted artifacts (invariant 10), so a node the
    run never reached is RUNNABLE on an ended run exactly as it would be on a
    live one -- and the page said "in the frontier" beside a Status of BLOCKED.
    The state is right; reading it without the run's status was not. */
export function reasonOf(
  node: Pick<NodeView, "state" | "waiting_on" | "gate_verdict" | "awaiting_gate">,
  status: RunView["status"],
  blocking = false,
): string {
  const edges = edgesOf(node);
  // First, because it is the one fact about this node the wire states
  // outright (`blocked_by`, §68): its validated Blocked verdict ended the run.
  // Its state is still RUNNABLE -- a Blocked verdict accepts nothing -- and
  // read without this it said "did not run", the opposite of what happened.
  // The gate's READY is not repeated here: it is why the node ran, and the
  // detail lists it on its own row.
  if (blocking) return "answered Blocked · ended the run";
  // Before the gate's verdict, because the verdict is about whether this node
  // *could* run and the run has stopped either way. CP-5 on a blocked run reads
  // `gate_verdict: READY` with every input met, and "READY" alone beside a
  // Status of BLOCKED tells a reader the opposite of what happened. The verdict
  // is kept, after the fact that overrides it.
  if (ended(status) && node.state === "RUNNABLE") {
    const rest = [node.gate_verdict, edges].filter(Boolean).join(" · ");
    return rest ? `did not run · ${rest}` : "did not run";
  }
  if (node.gate_verdict) return edges ? `${node.gate_verdict} · ${edges}` : node.gate_verdict;
  if (node.state === "BLOCKED") return edges ? `waits on ${edges}` : "blocked with no named edge";
  if (node.state === "RUNNABLE") {
    // Ready, and the run stopped first. Said without a cause, because the cause
    // belongs to whichever node ended the run and this one cannot name it.
    if (ended(status)) return edges ? `did not run · ${edges}` : "did not run";
    if (node.awaiting_gate) return edges ? `awaiting the gate · ${edges}` : "awaiting the gate";
    return edges ? `in the frontier · ${edges}` : "in the frontier";
  }
  if (node.state === "COMPLETE") return edges ? `accepted · ${edges}` : "accepted";
  return edges || "restricted";
}

/** What a node card says (D72): the reason without the edges it names. The
    card is a code and a state; the edges are the canvas's lines, listed in
    full in the Selected node card and on the card's own tooltip. Where the
    edges are all the reason has, the card counts them. */
export function cardReasonOf(
  node: Pick<NodeView, "state" | "waiting_on" | "gate_verdict" | "awaiting_gate">,
  status: RunView["status"],
  blocking = false,
): string {
  const count = node.waiting_on.length;
  const edges = `${count} ${count === 1 ? "edge" : "edges"}`;
  if (!blocking && !node.gate_verdict && count) {
    if (node.state === "BLOCKED") return `waits on ${edges}`;
    if (node.state === "RESTRICTED") return `runs without ${edges}`;
  }
  return reasonOf({ ...node, waiting_on: [] }, status, blocking);
}

/** A node is drawn running while it holds an attempt not yet accepted —
    recomputed from the attempts the wire carries, never a stored flag.

    An ended run has nothing running, whatever its nodes hold. A validated
    Blocked verdict accepts nothing, so the very node whose answer ended the run
    keeps an unaccepted attempt and was drawn pulsing next to a Status of
    BLOCKED. */
export function runningOf(
  node: Pick<NodeView, "route_node_id" | "state">,
  attempts: readonly AttemptView[],
  status: RunView["status"],
): boolean {
  return (
    !ended(status) &&
    node.state === "RUNNABLE" &&
    attempts.some((attempt) => attempt.route_node_id === node.route_node_id && !attempt.accepted)
  );
}

/** Whether this node is the one whose validated Blocked verdict ended the
    run. Read from the wire's `blocked_by`, never inferred from an unaccepted
    attempt: a node the run never reached holds one of those too, and the two
    are opposite facts. */
export function blockingOf(
  node: Pick<NodeView, "route_node_id">,
  blockedBy: BlockedByView | null,
): boolean {
  return blockedBy !== null && blockedBy.route_node_id === node.route_node_id;
}

/** The state word the graph draws under a node's id: the bundle's state, and
    for RUNNABLE what that means on this run -- running, ended it, did not run,
    or in the frontier. FRONTIER is never said of a run that has ended. */
export function stateWordOf(
  node: Pick<NodeView, "state">,
  status: RunView["status"],
  running: boolean,
  blocking: boolean,
): string {
  if (node.state !== "RUNNABLE") return node.state;
  if (blocking) return "RUNNABLE · BLOCKED THE RUN";
  if (running) return "RUNNABLE · RUNNING";
  if (ended(status)) return "RUNNABLE · DID NOT RUN";
  return "RUNNABLE · FRONTIER";
}

/** The run panel's line on why a BLOCKED run ended, or null on any other run.
    Two different things (§39, §68): a node's validated Blocked verdict, named
    with its attempt; or the route's own rule, when the frontier emptied with
    required work unfinished and no node was asked. The wire carries `null` for
    the second and this says so, rather than naming a node that does not
    exist. */
export function blockedByOf(
  run: Pick<RunView, "status" | "blocked_by"> & { attempts: readonly AttemptView[] },
): string | null {
  if (run.status !== "BLOCKED") return null;
  const by = run.blocked_by;
  if (by === null) return "no node's verdict — the frontier emptied with required work unfinished";
  const attempt = run.attempts.find((a) => a.attempt_id === by.attempt_id);
  const which =
    attempt === undefined
      ? "an unlisted attempt"
      : attempt.ordinal === null
        ? "an unassigned attempt"
        : `attempt ${attempt.ordinal}`;
  return `${by.module_id} answered Blocked on ${which} · ${by.route_node_id}`;
}

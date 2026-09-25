// The right column is about the selected node: its state and reason, the
// edges that place it and those it still waits on, the gate's own verdict
// when it named one, and its attempts.
// No accept action here (brief 4.1: commands are 4.2).
import { severityOf } from "./RouteGraph";
import { blockingOf, reasonOf, runningOf } from "./reason";
import { SeverityMark, toneOf } from "@/chrome/SeverityMark";
import { sentence } from "@/chrome/compose";
import { stamp } from "@/ds/format";
import type { AttemptView, BlockedByView } from "./types";
import type { NodeView, RunView } from "@/wire/v1";

export function NodeDetail({
  node,
  edges,
  attempts,
  status,
  blockedBy,
}: {
  node: NodeView;
  /** The pinned route's own edges (D73): this node's incoming ones are its
      placing edges, met or not. */
  edges: RunView["edges"];
  attempts: AttemptView[];
  status: RunView["status"];
  blockedBy: BlockedByView | null;
}) {
  const incoming = edges.filter((edge) => edge.target === node.module_id);
  const running = runningOf(node, attempts, status);
  const blocking = blockingOf(node, blockedBy);
  const severity = severityOf(node, running, blocking);
  const mine = attempts.filter((attempt) => attempt.route_node_id === node.route_node_id);
  return (
    <>
      <section className="pnl" data-node-detail={node.module_id}>
        <header>
          <h2>Selected node</h2>
          <span className="cp">
            {node.module_name === node.module_id ? "" : `${node.module_name} · `}
            {node.module_id} · {node.route_node_id}
          </span>
          <span className={`tag ${toneOf(severity)} right`}>
            <SeverityMark severity={severity} pulse={running} />
            {sentence(node.state)}
          </span>
        </header>
        <div className="pb">
          <dl className="kv">
            <dt>Reason</dt>
            <dd className="wrap">{reasonOf(node, status, blocking)}</dd>
            <dt>Stage</dt>
            <dd>{node.stage}</dd>
            {/* Every edge that places the node on the route, and apart from
                them the ones it still waits for: the wire's `waiting_on` is
                only the unmet, so a completed node read "none" here (N106). */}
            <dt>Edges in</dt>
            <dd data-edges-in>
              {incoming.length
                ? incoming.map((edge) => `${edge.type} ${edge.source}`).join(" · ")
                : "none"}
            </dd>
            <dt>Waiting on</dt>
            <dd data-waiting-on>
              {node.waiting_on.length
                ? node.waiting_on.map((edge) => `${edge.type} ${edge.source}`).join(" · ")
                : "nothing"}
            </dd>
            <dt>Awaiting gate</dt>
            <dd>{node.awaiting_gate ? "yes" : "no"}</dd>
            {node.gate_verdict ? (
              <>
                <dt>Gate verdict</dt>
                <dd data-gate-verdict>{node.gate_verdict}</dd>
              </>
            ) : null}
            {/* The gate's own words for a verdict it did not clear: under §61 a
                CONDITIONAL one names a source the pinned set does not carry,
                and supplying that source is what a successor run is for. The
                module wrote it, so it is labelled as the gate's statement and
                not as the workspace's. */}
            {node.gate_reason ? (
              <>
                <dt>Gate condition</dt>
                <dd className="wrap" data-gate-reason>
                  {node.gate_reason}
                </dd>
              </>
            ) : null}
          </dl>
        </div>
      </section>
      <section className="pnl">
        <header>
          <h2>Attempts — {node.module_id}</h2>
          <span className="cp">one row per try</span>
        </header>
        <div className="pb flush">
          {mine.length ? (
            mine.map((attempt) => {
              // The attempt the wire names as the one that answered Blocked
              // (§68). Not accepted -- a Blocked verdict accepts nothing --
              // and said so beside the verdict rather than instead of it.
              const verdict = blockedBy !== null && attempt.attempt_id === blockedBy.attempt_id;
              return (
                <div
                  key={attempt.attempt_id}
                  className="att attempt"
                  data-attempt={attempt.ordinal ?? "—"}
                  {...(verdict ? { "data-blocking-attempt": "" } : {})}
                >
                  <span className="a">Attempt {attempt.ordinal ?? "unassigned"}</span>
                  <span>
                    started <time dateTime={attempt.started_at}>{stamp(attempt.started_at)}</time>
                  </span>
                  <span className={attempt.accepted ? "t-ok" : verdict ? "t-crit" : "t-run"}>
                    {attempt.accepted
                      ? "Accepted"
                      : verdict
                        ? "Blocked · not accepted"
                        : "Not accepted"}
                  </span>
                </div>
              );
            })
          ) : (
            <div className="att">
              <span className="a">none</span>
              <span>no attempt recorded for {node.module_id}</span>
              <span>—</span>
            </div>
          )}
        </div>
      </section>
    </>
  );
}

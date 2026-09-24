// Run — the resolved route and its frontier (IA_SPEC.md 4.5), cut over to the
// v1 wire (brief 4.1, slice 4.1i). No stages list, no selection state on the
// wire, no charge or generation id, no plan-gate approve/reserve and no
// accept action: those arrive with commands (4.2). `displayed_run_id` and
// `latest_run_id` are two identities and are never collapsed into one.
import { useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router";
import {
  CreateRunControl,
  GatePanelControl,
  PinInputControl,
  WorkControls,
  actionOf,
  useRunRefetch,
} from "./controls";
import { NodeDetail } from "./NodeDetail";
import { blockedByOf } from "./reason";
import { RouteGraph } from "./RouteGraph";
import type { GateView } from "./types";
import { SEVERITY_BADGE, SeverityMark } from "@/chrome/SeverityMark";
import { isParked, sentence, words } from "@/chrome/compose";
import { Badge } from "@/components/ui/badge";
import { shortDigest, stamp } from "@/ds/format";
import { NODE_SEVERITY } from "@/sections/analysis/tone";
import { useAnnouncer } from "@/states/Announcer";
import type { NodeState } from "@/wire";
import type { RunSectionDocument } from "@/wire/v1";

const STATES: NodeState[] = ["COMPLETE", "RUNNABLE", "RESTRICTED", "BLOCKED"];
const GATE_LABEL: Record<GateView["gate"], string> = {
  SOURCE_SET: "Source set",
  RESEARCH_PLAN: "Research plan",
};

function runHref(caseId: string, runId: string): string {
  return `?case=${encodeURIComponent(caseId)}&run=${encodeURIComponent(runId)}`;
}

export function RunSection({ document }: { document: RunSectionDocument; tab: string | null }) {
  // A governed write's receipt is never the document: a success refetches
  // through the same transport and parser every load uses, so `live` is what
  // renders below, not the possibly-stale `document` prop (brief 4.2,
  // decision 12). `document` still drives it: a fresh prop (a navigation, the
  // workspace's own SSE-triggered load) always supersedes a local refetch.
  const { live, failed: refetchFailed, refetch } = useRunRefetch(document, document.body.case_id);
  const body = live.body;
  const actions = live.chrome.actions;
  const [choice, setChoice] = useState<{ run: string; node: string } | null>(null);
  // The fingerprint a start or retry must send: whichever of a pin, a preview
  // or an approval was last read in this session (`controls.tsx`, brief 4.2
  // decision 1), else the run read's own `input_fingerprint` (N48), so a
  // reload keeps them usable. Two holds of the session's: `pinned` keys the
  // gate panels and moves only on a pin or an approval, and `known` is what
  // start and retry send and moves on a preview too -- which must not remount
  // the panel that read it (MAX-18).
  const [pinned, setPinned] = useState<string | null>(null);
  const [known, setKnown] = useState<string | null>(null);
  const learn = useCallback((fingerprint: string) => {
    setPinned(fingerprint);
    setKnown(fingerprint);
  }, []);
  // The run's status changes under the reader, driven by the event tail and
  // never by a press: a screen reader is told when it moves, terminal states
  // included, in the section's own live region (WCAG 4.1.3, finding FE-6).
  const say = useAnnouncer();
  const status = body.run?.status ?? null;
  const said = useRef<string | null>(null);
  useEffect(() => {
    if (status === null) return;
    if (said.current !== null && said.current !== status) say(`Run ${status}.`);
    said.current = status;
  }, [status, say]);

  const refetchNote = refetchFailed ? (
    <div className="note" data-refetch-failed>
      The run could not be refreshed after that command. Reload to see its current state.
    </div>
  ) : null;

  // Defensive: the transport classes `run: null` as observed-empty and never
  // mounts this view for it, but a direct caller (a unit test, a future
  // composer) may still hand one over — this names it rather than crashing.
  if (body.run === null) {
    return (
      <>
        <section className="pnl" data-run-empty>
          <header>
            <h2>No run</h2>
          </header>
          <div className="pb">This case has no run to show.</div>
        </section>
        {refetchNote}
        <CreateRunControl
          caseId={body.case_id}
          action={actionOf(actions, "CREATE_RUN")}
          choices={body.route_choices}
        />
      </>
    );
  }

  const run = body.run;
  const stale =
    body.displayed_run_id !== null &&
    body.latest_run_id !== null &&
    body.displayed_run_id !== body.latest_run_id;
  const chosen = choice?.run === run.run_id ? choice.node : null;
  const selectedId =
    (chosen && run.nodes.some((node) => node.route_node_id === chosen) ? chosen : null) ??
    run.nodes[0]?.route_node_id ??
    null;
  const selected = run.nodes.find((node) => node.route_node_id === selectedId) ?? null;
  const tally = STATES.map((state) => ({
    state,
    count: run.nodes.filter((node) => node.state === state).length,
  }));
  const blockedBy = blockedByOf(run);

  return (
    <div className="cols two" data-run={run.run_id}>
      <div className="col">
        {body.runs.length > 1 ? (
          <section className="pnl" data-run-selector>
            <header>
              <h2>Runs</h2>
              <span className="cp">displayed and latest are named separately</span>
            </header>
            <div className="pb flush">
              {body.runs.map((summary) => {
                const displayed = summary.run_id === body.displayed_run_id;
                const latest = summary.run_id === body.latest_run_id;
                const label = displayed
                  ? latest
                    ? "Displayed · latest"
                    : "Displayed · not latest"
                  : latest
                    ? "Latest"
                    : "";
                return (
                  <Link
                    key={summary.run_id}
                    className={`att${displayed ? " sel" : ""}`}
                    data-run-row={summary.run_id}
                    data-displayed={displayed}
                    data-latest={latest}
                    to={runHref(body.case_id, summary.run_id)}
                  >
                    <span className="a" data-stop-code={summary.stop_code ?? undefined}>
                      {isParked(summary)
                        ? `Parked · ${summary.stop_code}`
                        : sentence(summary.status)}
                    </span>
                    <time dateTime={summary.created_at}>{stamp(summary.created_at)}</time>
                    <span>{label}</span>
                  </Link>
                );
              })}
            </div>
          </section>
        ) : null}
        {stale ? (
          <div className="note" data-stale-run>
            <b>This run is not the latest.</b> Displayed run {body.displayed_run_id}; the latest run
            for this case is {body.latest_run_id}.
          </div>
        ) : null}
        <section className="pnl">
          <header>
            <h2>Resolved route</h2>
            <span className="cp">
              build {run.build_id ?? "not pinned"} · digest{" "}
              {shortDigest(run.route_digest, "not pinned")}
            </span>
            <span className="tag right">{run.nodes.length} nodes</span>
            <span className="flex flex-wrap gap-1.5" data-tally>
              {tally.map(({ state, count }) => (
                <Badge
                  key={state}
                  variant={SEVERITY_BADGE[NODE_SEVERITY[state]]}
                  className="gap-1.5"
                  data-tally-state={state}
                >
                  <SeverityMark severity={NODE_SEVERITY[state]} decorative />
                  {count} {words(state)}
                </Badge>
              ))}
            </span>
          </header>
          {run.route_digest === null ? (
            <div className="note" data-route-not-pinned>
              The route is not yet pinned; nothing has run.
            </div>
          ) : null}
          <div className="pb flush">
            <RouteGraph
              nodes={run.nodes}
              attempts={run.attempts}
              status={run.status}
              blockedBy={run.blocked_by}
              selected={selectedId}
              onSelect={(routeNodeId) => setChoice({ run: run.run_id, node: routeNodeId })}
            />
          </div>
        </section>
        <details className="help">
          <summary>What the module states mean</summary>
          COMPLETE has an accepted artifact. RUNNABLE is next in line while the run is running, and
          did not run once it has ended, unless its Blocked verdict ended the run, which the node
          says. RESTRICTED ran and carries its limitation forward. BLOCKED names what it waits on.
          States are worked out from accepted attempts each time; they are never stored.
        </details>
        {/* The run's acts, in the order they happen, beside the route they act
            on -- not stacked in the right column, which is always about the
            selected thing (DESIGN.md; critique: a nine-panel second menu). */}
        <section className="actgroup" aria-labelledby="run-acts-heading">
          <h2 id="run-acts-heading" className="grouphead">
            Act on this run
          </h2>
          <PinInputControl
            caseId={body.case_id}
            runId={run.run_id}
            action={actionOf(actions, "PIN_RUN_INPUT")}
            initial={run.subject}
            // The resolved route is pinned at Create run (§ create_run), so a
            // CP-DR node is already on `run.nodes` before any input is
            // pinned: the one signal this reader needs to require a research
            // brief on the advertised research routes (R24-01), without a
            // new wire field naming the route family.
            requiresResearch={run.nodes.some((node) => node.module_id === "CP-DR")}
            onPinned={learn}
            onRefetch={refetch}
          />
          {run.gates.map((gate) => (
            // Keyed on the input's fingerprint: a pin (or an approval that
            // moved it), here or by someone else as the run read shows it,
            // remounts the panel, clearing any preview read under the input
            // that changed rather than leaving a stale digest approvable
            // (brief 4.2 review finding 3). A preview moves neither (MAX-18).
            <GatePanelControl
              key={`${gate.gate}:${run.input_fingerprint ?? "none"}:${pinned ?? "none"}`}
              caseId={body.case_id}
              runId={run.run_id}
              gate={gate.gate}
              state={gate.state}
              action={actionOf(
                actions,
                gate.gate === "SOURCE_SET" ? "APPROVE_SOURCE_SET" : "APPROVE_RESEARCH_PLAN",
              )}
              onFingerprint={learn}
              onPreviewed={setKnown}
              onRefetch={refetch}
            />
          ))}
          <WorkControls
            caseId={body.case_id}
            runId={run.run_id}
            // What this session last read first: a start after a preview
            // asserts the input that preview showed, and a re-pin by someone
            // else since is then refused, not silently sent. The run read's
            // own is what a reload has (N48).
            fingerprint={known ?? run.input_fingerprint}
            work={run.work}
            actions={actions}
            onRefetch={refetch}
          />
          <CreateRunControl
            // A BLOCKED run nobody has answered is what a successor is for
            // (§72): offer it pre-filled. Keyed on the run so the offer follows
            // the displayed run rather than the first one this panel mounted for.
            key={run.run_id}
            caseId={body.case_id}
            action={actionOf(actions, "CREATE_RUN")}
            choices={body.route_choices}
            supersedes={run.status === "BLOCKED" && run.superseded_by === null ? run.run_id : null}
          />
        </section>
      </div>
      <div className="col right">
        {refetchNote}
        {selected ? (
          <NodeDetail
            node={selected}
            attempts={run.attempts}
            status={run.status}
            blockedBy={run.blocked_by}
          />
        ) : null}
        <section className="pnl">
          <header>
            <h2>Run</h2>
            <span className="cp">{run.run_id}</span>
          </header>
          <div className="pb">
            <dl className="kv">
              <dt>Status</dt>
              <dd className="prose">
                {isParked({ status: run.status, stop_code: run.work?.stop_code ?? null })
                  ? `Parked · ${run.work?.stop_code}`
                  : sentence(run.status)}
              </dd>
              {blockedBy !== null ? (
                <>
                  <dt>Blocked by</dt>
                  <dd className="wrap" data-blocked-by={run.blocked_by?.module_id ?? "none"}>
                    {blockedBy}
                  </dd>
                </>
              ) : null}
              {run.supersedes !== null ? (
                <>
                  <dt>Supersedes</dt>
                  <dd className="wrap" data-supersedes>
                    run <Link to={runHref(body.case_id, run.supersedes)}>{run.supersedes}</Link>
                  </dd>
                </>
              ) : null}
              {run.superseded_by !== null ? (
                <>
                  <dt>Superseded by</dt>
                  <dd className="wrap" data-superseded-by>
                    run{" "}
                    <Link to={runHref(body.case_id, run.superseded_by)}>{run.superseded_by}</Link>
                  </dd>
                </>
              ) : null}
              <dt>Created</dt>
              <dd>
                <time dateTime={run.created_at}>{stamp(run.created_at)}</time>
              </dd>
              <dt>Route digest</dt>
              <dd className="wrap" title={run.route_digest ?? "not pinned"}>
                {shortDigest(run.route_digest, "not pinned")}
              </dd>
              <dt>Build</dt>
              <dd>{run.build_id ?? "not pinned"}</dd>
              <dt>Source set</dt>
              <dd>{run.source_set_version ?? "not pinned"}</dd>
              {run.subject ? (
                <>
                  <dt>Subject</dt>
                  <dd className="prose">
                    {run.subject.issuer_name} · {run.subject.reporting_period}
                  </dd>
                </>
              ) : null}
            </dl>
          </div>
        </section>
        <section className="pnl">
          <header>
            <h2>Gates</h2>
            {/* "2 of 2" read as done while a gate was still open. */}
            <span className="cp">
              {run.gates.filter((gate) => gate.state === "RELEASED").length} of {run.gates.length}{" "}
              released
            </span>
          </header>
          <div className="pb flush">
            {run.gates.length ? (
              run.gates.map((gate) => (
                <div key={gate.gate} className="att" data-gate-row={gate.gate}>
                  <span className="a">{GATE_LABEL[gate.gate]}</span>
                  <span className={gate.state === "RELEASED" ? "t-ok" : "t-run"}>
                    {sentence(gate.state)}
                  </span>
                </div>
              ))
            ) : (
              <div className="att">
                <span className="a">none</span>
                <span>no gate recorded for this run</span>
              </div>
            )}
          </div>
        </section>
      </div>
    </div>
  );
}

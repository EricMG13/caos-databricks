// Analysis (IA_SPEC.md 4.3), v1 wire (brief 4.1, slice 4.1j). Every accepted
// handoff in route order carries the host's own facts, the model's own
// analysis and the reminder that the host performs no calculation; a pending
// node is named with the state the route left it in, never invented.
//
// Each source fact opens the evidence drawer by its identity (brief 4.4,
// decision 9); the drawer reads the page's text layer and places the stored
// rectangles over it.
import { NODE_SEVERITY, nodeTone } from "./tone";
import { SeverityMark } from "@/chrome/SeverityMark";
import { useEvidence } from "@/evidence/EvidenceContext";
import type { AnalysisDocument, CitationView, HandoffView, PendingNode } from "@/wire/v1";

const SCREENING_NOTICE = "SCREENING ONLY: a screen, not committee clearance.";

function SourceFacts({ record, facts }: { record: string; facts: readonly CitationView[] }) {
  const { openFact, activeFact } = useEvidence();
  return (
    <section className="pnl" data-source-facts>
      <header>
        <h3>Source facts (host-verified citations)</h3>
        <span className="tag">{facts.length}</span>
      </header>
      {facts.length === 0 ? (
        <div className="pb note">No citation is carried on this handoff.</div>
      ) : (
        <ul className="pb flush plain">
          {facts.map((fact, index) => (
            <li
              key={`${fact.document_sha256}-${index}`}
              className="ev"
              data-citation
              data-withdrawn={fact.withdrawn_at !== null}
            >
              <span className="h">
                <button
                  type="button"
                  className={`chip${fact.withdrawn_at !== null ? " withdrawn" : ""}`}
                  aria-label={`Evidence ${fact.filename} p.${fact.page}${fact.withdrawn_at !== null ? " · source withdrawn" : ""}`}
                  aria-haspopup="dialog"
                  aria-expanded={activeFact?.record_sha256 === record && activeFact.index === index}
                  data-fact-chip={fact.source_id}
                  onClick={(event) =>
                    openFact(
                      { record_sha256: record, source_id: fact.source_id, page: fact.page, index },
                      event.currentTarget,
                    )
                  }
                >
                  p.{fact.page}
                </button>{" "}
                {fact.filename} · p.{fact.page}
              </span>
              <blockquote className="matched" style={{ margin: 0 }}>
                {fact.matched_text}
              </blockquote>
              {fact.withdrawn_at !== null ? (
                <div className="note limitation" data-withdrawn-at={fact.withdrawn_at}>
                  <b>This source has been withdrawn</b> at {fact.withdrawn_at}. The citation stays
                  so the conclusion that rests on it stays explicable.
                </div>
              ) : null}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

/** The model's own prose, rendered as text. Markdown syntax is never parsed
    into markup: a heading or emphasis character reaches the page as itself. */
function ModelAnalysis({ text }: { text: string }) {
  return (
    <section className="pnl" data-model-analysis>
      <header>
        <h3>Analysis (model-authored, not host-verified)</h3>
      </header>
      <div className="pb">
        <pre className="model-text">{text}</pre>
      </div>
    </section>
  );
}

function HostCalculation({ calculation }: { calculation: HandoffView["host_calculation"] }) {
  return (
    <section className="pnl" data-host-calculation>
      <header>
        <h3>
          {calculation === "CP_CF_FORECAST"
            ? "Deterministic calculations: CP-CF forecast projection performed by the host"
            : "Deterministic calculations: none performed by the host"}
        </h3>
      </header>
    </section>
  );
}

function HandoffCard({ handoff }: { handoff: HandoffView }) {
  return (
    <section className="pnl" data-handoff={handoff.module_id}>
      <header>
        <h2>{handoff.module_id}</h2>
        <span className="cp">{handoff.route_node_id}</span>
        <span className="right">
          <span className="tag" data-qa-status>
            {handoff.qa_status}
          </span>
        </span>
      </header>
      <div className="pb col">
        <dl className="kv">
          <dt>Committee status</dt>
          <dd data-committee-status>
            {handoff.committee_status} · {handoff.decision_scope}
          </dd>
          <dt>Confidence</dt>
          <dd data-confidence>
            {handoff.confidence_score} · {handoff.confidence_band}
          </dd>
          <dt>Accepted</dt>
          <dd>
            <time dateTime={handoff.accepted_at}>{handoff.accepted_at}</time>
          </dd>
        </dl>
        {handoff.screening_only ? (
          <div className="note" data-screening-only>
            <b>{SCREENING_NOTICE}</b>
          </div>
        ) : null}
        <div className="note" data-limitation-flags>
          <b>Limitation flags.</b>{" "}
          {handoff.limitation_flags.length ? handoff.limitation_flags.join(", ") : "none"}
        </div>
        {handoff.validation_warnings.length ? (
          <div className="note" data-validation-warnings>
            <b>Validation warnings.</b> {handoff.validation_warnings.join(", ")}
          </div>
        ) : null}
        <SourceFacts record={handoff.record_sha256} facts={handoff.source_facts} />
        <ModelAnalysis text={handoff.model_analysis} />
        <HostCalculation calculation={handoff.host_calculation} />
      </div>
    </section>
  );
}

function PendingList({
  pending,
  runStatus,
  blockedBy,
}: {
  pending: readonly PendingNode[];
  runStatus: AnalysisDocument["body"]["displayed_run_status"];
  blockedBy: AnalysisDocument["body"]["blocked_by"];
}) {
  // "Pending" is a claim about the future, and an ended run has none. The list
  // is recomputed from accepted artifacts, so a node the run never reached
  // looks exactly like one whose turn has not come; only the run's own status
  // tells them apart. A Blocked verdict accepts nothing, so the node that
  // answered and ended the run sits in this list too -- named here as what it
  // is, rather than left among the nodes that never started.
  const ended = runStatus !== null && runStatus !== "RUNNING";
  return (
    <section className="pnl" data-pending data-run-ended={ended ? "yes" : "no"}>
      <header>
        <h2>{ended ? "Nodes that did not run" : "Pending nodes"}</h2>
        <span className="cp">
          {ended
            ? `the run ended ${runStatus}${blockedBy ? ` on ${blockedBy.module_id}` : ""}`
            : "not yet accepted"}
        </span>
        <span className="right">
          <span className="tag">{pending.length}</span>
        </span>
      </header>
      {pending.length === 0 ? (
        <div className="pb note">Every pinned node on this run has been accepted.</div>
      ) : (
        <ul className="pb flush plain">
          {pending.map((node) => (
            <li
              key={node.route_node_id}
              className="frontier"
              data-pending-node={node.module_id}
              data-state={node.state}
              data-blocking={blockedBy?.route_node_id === node.route_node_id ? "yes" : "no"}
            >
              <span className="id">{node.module_id}</span>
              <span className="cp">{node.route_node_id}</span>
              {blockedBy?.route_node_id === node.route_node_id ? (
                <span className="cp" data-blocking-note>
                  its verdict ended the run · attempt {blockedBy.attempt_id}
                </span>
              ) : null}
              <span className={`tag ${nodeTone(node.state)}`}>
                <SeverityMark severity={NODE_SEVERITY[node.state]} /> {node.state}
              </span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

export function AnalysisSection({ document }: { document: AnalysisDocument; tab: string | null }) {
  const { body } = document;
  const stale =
    body.displayed_run_id !== null &&
    body.latest_run_id !== null &&
    body.displayed_run_id !== body.latest_run_id;
  return (
    <div className="col" data-analysis>
      {stale ? (
        <div className="note" data-stale-run>
          <b>This is not the latest run.</b> Displayed run {body.displayed_run_id}; the latest run
          for this case is {body.latest_run_id}.
        </div>
      ) : null}
      <section className="pnl">
        <header>
          <h2>Handoffs</h2>
          {body.subject ? (
            <span className="cp">
              {body.subject.issuer_name} · {body.subject.reporting_period}
            </span>
          ) : null}
          <span className="right">
            <span className="tag ok">{body.handoffs.length} ACCEPTED</span>
          </span>
        </header>
        {body.handoffs.length === 0 ? (
          <div className="pb note">No handoff has been accepted on this run yet.</div>
        ) : null}
      </section>
      {body.handoffs.map((handoff) => (
        <HandoffCard key={handoff.route_node_id} handoff={handoff} />
      ))}
      <PendingList
        pending={body.pending}
        runStatus={body.displayed_run_status}
        blockedBy={body.blocked_by}
      />
    </div>
  );
}

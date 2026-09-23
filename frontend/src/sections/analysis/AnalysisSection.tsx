// Analysis (IA_SPEC.md 4.3), v1 wire (brief 4.1, slice 4.1j), laid out as the
// legacy desk's three panes and improved (2026-09-23 critique): the modules are
// the section's tabs; the body is the evidence rail (what the run rests on and
// the selected module's own citations), the selected module, and a right
// column that is always about the selected thing -- its provenance.
//
// Each source fact opens the evidence drawer by its identity (brief 4.4,
// decision 9); the drawer reads the page's text layer and places the stored
// rectangles over it. The model's prose is text, never markup.
import { useState } from "react";
import { Link } from "react-router";
import { Figures, type FigurePick } from "./figures";
import { conclusionOf, handoffSeverity, moduleName } from "./modules";
import { NODE_SEVERITY, nodeTone } from "./tone";
import { sectionPath } from "@/app/sections";
import { SeverityMark } from "@/chrome/SeverityMark";
import { words } from "@/chrome/compose";
import { formatDecimal } from "@/charts";
import { Button } from "@/components/ui/button";
import { shortDigest, stamp } from "@/ds/format";
import { useEvidence } from "@/evidence/EvidenceContext";
import type { AnalysisDocument, CitationView, HandoffView, PendingNode } from "@/wire/v1";

const SCREENING_NOTICE = "Screening only: a screen, not committee clearance.";
/** Model prose beyond this many characters is shown on request: a handoff may
    carry 25 MB, and rendering all of it at once stalls the page. */
export const PROSE_SHOWN = 20_000;

type Handoffs = AnalysisDocument["body"]["handoffs"];

/** The documents this run's conclusions rest on: each cited document once,
    with the pages cited and how often, and whether it has been withdrawn. */
export function sourceRegister(handoffs: Handoffs) {
  const byDocument = new Map<
    string,
    { filename: string; pages: Set<number>; count: number; withdrawn: boolean }
  >();
  for (const fact of handoffs.flatMap((handoff) => handoff.source_facts)) {
    const entry = byDocument.get(fact.document_sha256) ?? {
      filename: fact.filename,
      pages: new Set<number>(),
      count: 0,
      withdrawn: false,
    };
    entry.pages.add(fact.page);
    entry.count += 1;
    entry.withdrawn ||= fact.withdrawn_at !== null;
    byDocument.set(fact.document_sha256, entry);
  }
  return [...byDocument.entries()]
    .map(([digest, entry]) => ({ digest, ...entry, pages: [...entry.pages].sort((a, b) => a - b) }))
    .sort((a, b) => b.count - a.count || a.filename.localeCompare(b.filename));
}

function SourceRegister({ handoffs }: { handoffs: Handoffs }) {
  const register = sourceRegister(handoffs);
  const most = Math.max(1, ...register.map((entry) => entry.count));
  return (
    <section className="pnl" data-source-register aria-labelledby="source-register-heading">
      <header>
        <h2 id="source-register-heading">What this run rests on</h2>
        <span className="tag">{register.length}</span>
      </header>
      {register.length === 0 ? (
        <p className="pb note">No accepted module cites a source yet.</p>
      ) : (
        <ul className="pb flush plain register">
          {register.map((entry) => (
            <li
              key={entry.digest}
              data-register-document={entry.digest}
              data-withdrawn={entry.withdrawn}
            >
              <span className="nm" title={entry.filename}>
                {entry.filename}
              </span>
              <span className="meta">
                {entry.withdrawn ? <span className="tag warn">Withdrawn</span> : null}p.
                {entry.pages.join(", ")} · {entry.count}{" "}
                {entry.count === 1 ? "citation" : "citations"}
              </span>
              {/* Host-verified counts, drawn solid (the citations are the host's). */}
              <span className="bar" aria-hidden="true">
                <span style={{ width: `${(entry.count / most) * 100}%` }} />
              </span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

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
              className="ev fact"
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
                  <b>This source has been withdrawn</b> at {stamp(fact.withdrawn_at)}. The citation
                  stays so the conclusion that rests on it stays explicable.
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
  const [all, setAll] = useState(false);
  const cut = !all && text.length > PROSE_SHOWN;
  return (
    <section className="pnl" data-model-analysis>
      <header>
        <h3>Analysis (model-authored, not host-verified)</h3>
      </header>
      <div className="pb">
        <pre className="model-text">{cut ? text.slice(0, PROSE_SHOWN) : text}</pre>
        {cut ? (
          <Button
            type="button"
            variant="outline"
            size="sm"
            className="mt-3"
            data-prose-rest
            onClick={() => setAll(true)}
          >
            Show the remaining {(text.length - PROSE_SHOWN).toLocaleString("en-US")} characters
          </Button>
        ) : null}
      </div>
    </section>
  );
}

function HostCalculation({ handoff, model }: { handoff: HandoffView; model: string }) {
  return handoff.host_calculation === "CP_CF_FORECAST" ? (
    <p className="note" data-host-calculation>
      Deterministic calculations: CP-CF forecast projection performed by the host.{" "}
      {/* The projection itself is read in Model, beside its passport. */}
      <Link to={model}>Open the projection in Model</Link>
    </p>
  ) : (
    <p className="note" data-host-calculation>
      Deterministic calculations: none performed by the host. Every figure in this module is the
      model&apos;s.
    </p>
  );
}

function ModuleView({
  handoff,
  model,
  onPick,
}: {
  handoff: HandoffView;
  model: string;
  onPick: (pick: FigurePick) => void;
}) {
  const severity = handoffSeverity(handoff);
  return (
    <article className="module" data-handoff={handoff.module_id} aria-labelledby="module-heading">
      <header className="modhead">
        <SeverityMark severity={severity} decorative />
        <h2 id="module-heading">{moduleName(handoff.module_id)}</h2>
        {moduleName(handoff.module_id) === handoff.module_id ? null : (
          <span className="code">{handoff.module_id}</span>
        )}
        <span className="right">
          <span className={`tag ${severity === "SUCCESS" ? "ok" : "warn"}`} data-qa-status>
            {handoff.qa_status}
          </span>
        </span>
      </header>
      <dl className="kv status">
        <dt>Committee status</dt>
        <dd className="prose" data-committee-status>
          {handoff.committee_status} · {words(handoff.decision_scope)}
        </dd>
        <dt>Confidence</dt>
        <dd className="prose" data-confidence>
          {handoff.confidence_score} · {words(handoff.confidence_band)}
        </dd>
        <dt>Accepted</dt>
        <dd>
          <time dateTime={handoff.accepted_at}>{stamp(handoff.accepted_at)}</time>
        </dd>
        <dt>Limitations</dt>
        <dd data-limitation-flags>
          {handoff.limitation_flags.length ? handoff.limitation_flags.join(", ") : "none"}
        </dd>
      </dl>
      {handoff.screening_only ? (
        <div className="note" data-screening-only>
          <b>{SCREENING_NOTICE}</b>
        </div>
      ) : null}
      {handoff.validation_warnings.length ? (
        <div className="note" data-validation-warnings>
          <b>Validation warnings.</b> {handoff.validation_warnings.join(", ")}
        </div>
      ) : null}
      <Figures handoff={handoff} onPick={onPick} />
      <ModelAnalysis text={handoff.model_analysis} />
      <HostCalculation handoff={handoff} model={model} />
    </article>
  );
}

/** The right column: always about the selected thing -- here, where the
    selected module's conclusion came from. */
function Picked({ pick }: { pick: FigurePick }) {
  return (
    <section className="pnl" data-picked aria-labelledby="picked-heading" aria-live="polite">
      <header>
        <h2 id="picked-heading">Selected figure</h2>
      </header>
      <dl className="pb kv">
        <dt>Figure</dt>
        <dd>{pick.figure}</dd>
        <dt>Mark</dt>
        <dd>{pick.label}</dd>
        <dt>Value</dt>
        <dd className="mono tabular" data-picked-value>
          {pick.value === null
            ? "n/a"
            : `${formatDecimal(pick.value)}${pick.unit ? ` ${pick.unit}` : ""}`}
        </dd>
        <dt>Origin</dt>
        <dd>Model-authored, not host-verified</dd>
        <dt>Table</dt>
        <dd className="mono">{pick.table}</dd>
        <dt>Stated source</dt>
        <dd>{pick.source ?? "not stated"}</dd>
      </dl>
    </section>
  );
}

function Provenance({ handoff }: { handoff: HandoffView }) {
  return (
    <section className="pnl" data-provenance aria-labelledby="provenance-heading">
      <header>
        <h2 id="provenance-heading">Where this came from</h2>
      </header>
      <dl className="pb kv">
        <dt>Route node</dt>
        <dd className="mono">{handoff.route_node_id}</dd>
        <dt>Artifact</dt>
        <dd className="mono" title={handoff.artifact_sha256}>
          {shortDigest(handoff.artifact_sha256)}
        </dd>
        <dt>Record</dt>
        <dd className="mono" title={handoff.record_sha256}>
          {shortDigest(handoff.record_sha256)}
        </dd>
        <dt>Accepted</dt>
        <dd>
          <time dateTime={handoff.accepted_at}>{stamp(handoff.accepted_at)}</time>
        </dd>
        <dt>Decision scope</dt>
        <dd className="prose">{words(handoff.decision_scope)}</dd>
        <dt>Citations</dt>
        <dd>{handoff.source_facts.length}</dd>
      </dl>
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
        <h2>
          {pending.length === 0
            ? "Route complete"
            : ended
              ? "Nodes that did not run"
              : "Pending nodes"}
        </h2>
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
                <SeverityMark severity={NODE_SEVERITY[node.state]} decorative /> {node.state}
              </span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

export function AnalysisSection({
  document,
  tab,
}: {
  document: AnalysisDocument;
  tab: string | null;
}) {
  const { body } = document;
  const stale =
    body.displayed_run_id !== null &&
    body.latest_run_id !== null &&
    body.displayed_run_id !== body.latest_run_id;
  // The tab is the selected module's route node; without one (a direct render,
  // or a module that has left the document) the conclusion is shown.
  const handoff =
    body.handoffs.find((entry) => entry.route_node_id === tab) ?? conclusionOf(body.handoffs);
  // The right column follows the pressed mark while its module is shown.
  const [picked, setPicked] = useState<{ route: string; pick: FigurePick } | null>(null);
  const pick = picked && handoff && picked.route === handoff.route_node_id ? picked.pick : null;
  const model = `${sectionPath("model")}?${new URLSearchParams({
    case: body.case_id,
    ...(body.displayed_run_id ? { run: body.displayed_run_id } : {}),
  }).toString()}`;
  return (
    <div className="analysis" data-analysis>
      {stale ? (
        <div className="note" data-stale-run>
          <b>This is not the latest run.</b> Displayed run {body.displayed_run_id}; the latest run
          for this case is {body.latest_run_id}.
        </div>
      ) : null}
      {handoff === null ? (
        <section className="pnl">
          <header>
            <h2>Handoffs</h2>
          </header>
          <div className="pb note">No handoff has been accepted on this run yet.</div>
        </section>
      ) : (
        <div className="panes">
          <aside className="pane evidence" aria-label="Evidence">
            {body.subject ? (
              <p className="issuer">
                <b>{body.subject.issuer_name}</b> · {body.subject.reporting_period}
              </p>
            ) : null}
            <SourceRegister handoffs={body.handoffs} />
            <SourceFacts record={handoff.record_sha256} facts={handoff.source_facts} />
          </aside>
          <div className="pane main">
            <ModuleView
              key={handoff.route_node_id}
              handoff={handoff}
              model={model}
              onPick={(next) => setPicked({ route: handoff.route_node_id, pick: next })}
            />
          </div>
          <aside className="pane context" aria-label="Selected module">
            {pick ? <Picked pick={pick} /> : null}
            <Provenance handoff={handoff} />
          </aside>
        </div>
      )}
      <PendingList
        pending={body.pending}
        runStatus={body.displayed_run_status}
        blockedBy={body.blocked_by}
      />
    </div>
  );
}

// The saved Report payload, read only. Text stays text: this surface never
// interprets markdown, follows evidence, or offers a legacy draft action.
import { useState } from "react";
import { FilingControls } from "./FilingControls";
import { scrollArtifact } from "@/controls/scroll";
import { NoteList } from "@/ds/atoms";
import type { ReportDocument } from "@/wire/v1";

/* Keyboard scroll makes static, wide canonical text reachable in every browser. */
/* eslint-disable jsx-a11y/no-noninteractive-element-interactions */
function Artifact({ artifact }: { artifact: ReportDocument["body"]["artifacts"][number] }) {
  return (
    <section className="pnl" data-report-artifact={artifact.route_node_id}>
      <header>
        <h2>{artifact.route_node_id}</h2>
        <span className="cp">
          {artifact.qa_status} · {artifact.committee_status}
        </span>
      </header>
      <div className="pb">
        <dl className="kv">
          <dt>Artifact</dt>
          <dd>sha256:{artifact.artifact_sha256}</dd>
          <dt>Record</dt>
          <dd>sha256:{artifact.record_sha256}</dd>
          <dt>Scope</dt>
          <dd>{artifact.decision_scope}</dd>
        </dl>
        <pre
          className="tscroll artifact-scroll"
          data-report-artifact-text
          aria-label={`${artifact.route_node_id} saved artifact markdown`}
          role="region"
          tabIndex={0} // NOSONAR typescript:S6845 -- role="region" above makes this
          // element a keyboard-scrollable landmark (WCAG 2.1.1), not the
          // plain-<pre>-with-tabIndex the rule exists to catch.
          onKeyDown={scrollArtifact}
        >
          {artifact.markdown}
        </pre>
        <pre
          className="tscroll artifact-scroll"
          data-report-artifact-record
          aria-label={`${artifact.route_node_id} saved artifact record`}
          role="region"
          tabIndex={0} // NOSONAR typescript:S6845 -- role="region" above makes this
          // element a keyboard-scrollable landmark (WCAG 2.1.1), not the
          // plain-<pre>-with-tabIndex the rule exists to catch.
          onKeyDown={scrollArtifact}
        >
          {artifact.record}
        </pre>
        <NoteList label="Limitations." values={artifact.limitation_flags} data-report-limitations />
        <NoteList
          label="Validation warnings."
          values={artifact.validation_warnings}
          data-report-warnings
        />
      </div>
    </section>
  );
}
/* eslint-enable jsx-a11y/no-noninteractive-element-interactions */

export function ReportSection({ document }: { document: ReportDocument; tab: string | null }) {
  // The filing controls re-read this section's own document after an act, and
  // a fresh document from the parent always supersedes that local copy --
  // adjusted during render, React's own pattern, as Directory and Upload do.
  const [live, setLive] = useState(document);
  const [seen, setSeen] = useState(document);
  if (document !== seen) {
    setSeen(document);
    setLive(document);
  }
  const { body } = live;
  return (
    <div
      className="col"
      data-report-v1
      data-revision={body.revision_id ?? undefined}
      data-payload={body.payload_sha256 ?? undefined}
    >
      <section className="pnl">
        <header>
          <h2>{body.case_title}</h2>
          {/* A run nothing has been saved from is served its accepted
              artifacts as a first save would carry them, and says so. */}
          <span className="cp">{body.revision_id === null ? "NOT YET SAVED" : "SAVED REPORT"}</span>
        </header>
        <div className="pb">
          <dl className="kv">
            <dt>Case</dt>
            <dd>{body.case_id}</dd>
            <dt>Run</dt>
            <dd>{body.displayed_run_id}</dd>
            <dt>Revision</dt>
            <dd>{body.revision_id ?? "Not yet saved"}</dd>
            <dt>Payload</dt>
            <dd>{body.payload_sha256 === null ? "None" : `sha256:${body.payload_sha256}`}</dd>
          </dl>
        </div>
      </section>
      {body.artifacts.map((artifact) => (
        <Artifact key={artifact.route_node_id} artifact={artifact} />
      ))}
      <FilingControls document={live} onRefreshed={setLive} />
      <section className="pnl" data-report-narrative>
        <header>
          <h2>Narrative</h2>
          <span className="tag">{body.narrative.length}</span>
        </header>
        <div className="pb">
          {body.narrative.map((spans, index) => (
            <p key={index} data-report-paragraph={index}>
              {spans.map((span, spanIndex) => (
                <span key={spanIndex}>
                  {span.text}
                  {span.figure
                    ? ` [${span.figure.route_node_id} · p.${span.figure.page} · ${span.figure.matched_text}]`
                    : null}
                </span>
              ))}
            </p>
          ))}
        </div>
      </section>
    </div>
  );
}

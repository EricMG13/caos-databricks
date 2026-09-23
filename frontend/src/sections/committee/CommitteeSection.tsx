import { sentence } from "@/chrome/compose";
import { scrollArtifact } from "@/controls/scroll";
import { NoteList } from "@/ds/atoms";
import type { CommitteeDocument } from "@/wire/v1";

/* Keyboard scroll makes static, wide canonical text reachable in every browser. */
/* eslint-disable jsx-a11y/no-noninteractive-element-interactions */
function Artifact({ artifact }: { artifact: CommitteeDocument["body"]["artifacts"][number] }) {
  return (
    <section className="pnl" data-committee-artifact={artifact.route_node_id}>
      <header>
        <h2>{artifact.route_node_id}</h2>
        <span className="cp">
          {sentence(artifact.qa_status)} · {sentence(artifact.committee_status)}
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
          data-committee-artifact-text
          aria-label="Saved artifact markdown"
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
          data-committee-artifact-record
          aria-label="Saved artifact record"
          role="region"
          tabIndex={0} // NOSONAR typescript:S6845 -- role="region" above makes this
          // element a keyboard-scrollable landmark (WCAG 2.1.1), not the
          // plain-<pre>-with-tabIndex the rule exists to catch.
          onKeyDown={scrollArtifact}
        >
          {artifact.record}
        </pre>
        <NoteList label="Limitations." values={artifact.limitation_flags} />
        <NoteList label="Validation warnings." values={artifact.validation_warnings} />
      </div>
    </section>
  );
}
/* eslint-enable jsx-a11y/no-noninteractive-element-interactions */

function Filing({ document }: { document: CommitteeDocument }) {
  const { body } = document;
  const receipt = body.receipt;
  return (
    <section className="pnl" data-committee-filing data-state={body.state}>
      <header>
        <h2>Committee state</h2>
        <span className="tag">{body.state}</span>
      </header>
      <div className="pb">
        <dl className="kv">
          <dt>Signers</dt>
          <dd>{body.signed_by.join(", ")}</dd>
          <dt>Frozen by</dt>
          <dd>{body.frozen_by}</dd>
          <dt>Filed by</dt>
          <dd>{body.filed_by ?? "—"}</dd>
        </dl>
        {receipt ? (
          <dl className="kv" data-committee-receipt>
            <dt>Receipt case</dt>
            <dd>{receipt.case_id}</dd>
            <dt>Receipt run</dt>
            <dd>{receipt.run_id}</dd>
            <dt>Receipt revision</dt>
            <dd>{receipt.revision_id}</dd>
            <dt>Receipt payload</dt>
            <dd>sha256:{receipt.payload_sha256}</dd>
            <dt>Receipt signer</dt>
            <dd>{receipt.signed_by}</dd>
            <dt>Receipt freezer</dt>
            <dd>{receipt.frozen_by}</dd>
            <dt>Receipt filer</dt>
            <dd>{receipt.filed_by}</dd>
            <dt>Renderer</dt>
            <dd>sha256:{receipt.renderer_sha256}</dd>
            <dt>Filed event</dt>
            <dd>sha256:{receipt.filed_event_sha256}</dd>
          </dl>
        ) : null}
      </div>
    </section>
  );
}

export function CommitteeSection({
  document,
}: {
  document: CommitteeDocument;
  tab: string | null;
}) {
  const { body } = document;
  return (
    <div
      className="col"
      data-committee-v1
      data-case={body.case_id}
      data-run={body.displayed_run_id}
      data-revision={body.revision_id}
      data-payload={body.payload_sha256}
    >
      <section className="pnl">
        <header>
          <h2>{body.case_title}</h2>
          <span className="cp">Saved committee</span>
        </header>
        <div className="pb">
          <dl className="kv">
            <dt>Case</dt>
            <dd>{body.case_id}</dd>
            <dt>Run</dt>
            <dd>{body.displayed_run_id}</dd>
            <dt>Revision</dt>
            <dd>{body.revision_id}</dd>
            <dt>Payload</dt>
            <dd>sha256:{body.payload_sha256}</dd>
          </dl>
        </div>
      </section>
      {body.artifacts.map((artifact) => (
        <Artifact key={artifact.route_node_id} artifact={artifact} />
      ))}
      <section className="pnl" data-committee-narrative>
        <header>
          <h2>Narrative</h2>
          <span className="tag">{body.narrative.length}</span>
        </header>
        <div className="pb">
          {body.narrative.map((spans, index) => (
            <p key={index}>
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
      <Filing document={document} />
    </div>
  );
}

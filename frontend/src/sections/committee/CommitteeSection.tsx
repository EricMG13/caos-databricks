import { DownloadIcon, FileTextIcon } from "lucide-react";
import { sentence } from "@/chrome/compose";
import { buttonVariants } from "@/components/ui/button";
import { RefusedControl } from "@/controls/RefusedControl";
import { scrollArtifact } from "@/controls/scroll";
import { NoteList } from "@/ds/atoms";
import { shortDigest } from "@/ds/format";
import { Narrative } from "@/evidence/Narrative";
import type { Refusal } from "@/wire";
import type { CommitteeDocument } from "@/wire/v1";

/** The package is the filed revision's: a frozen one has none to download. */
const PACKAGE_NOT_FILED: Refusal = {
  code: "PACKAGE_NOT_FILED",
  clears: "the revision is filed",
};

/** The saved paper as the renderer draws it, and once filed, the package
    (N4). Both are the host's own reads; the page only links them. */
function Downloads({ body }: { body: CommitteeDocument["body"] }) {
  const look = buttonVariants({ variant: "outline", size: "sm" });
  return (
    <div className="flex flex-wrap items-start gap-2" data-committee-downloads>
      <a className={look} href={body.render_url} data-committee-render>
        <FileTextIcon aria-hidden="true" />
        Open the rendered paper
      </a>
      {body.package_url ? (
        <a className={look} href={body.package_url} download data-committee-package>
          <DownloadIcon aria-hidden="true" />
          Download the package (.zip)
        </a>
      ) : (
        <RefusedControl refusal={PACKAGE_NOT_FILED}>Download the package (.zip)</RefusedControl>
      )}
    </div>
  );
}

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

/** An id or digest short on the page, whole in its title. */
function Short({ value, prefix = "" }: { value: string; prefix?: string }) {
  return (
    <span className="font-mono" title={`${prefix}${value}`}>
      {prefix}
      {shortDigest(value)}
    </span>
  );
}

/** The filed deliverable as paper (N62): ink on cream in either theme, and
    only once filed -- the one moment the product exists to reach. What the
    committee reads (the narrative with its figures), who stands behind it,
    and the digests that bind it. The full receipt stays below as the record. */
function Paper({ body }: { body: CommitteeDocument["body"] }) {
  const receipt = body.receipt;
  return (
    <article className="paper" data-paper data-committee-narrative aria-labelledby="paper-title">
      <header className="paper-mast">
        <span>Credit committee paper</span>
        <Short value={body.case_id} />
      </header>
      <p className="paper-stamp">Filed</p>
      <h2 id="paper-title">{body.case_title}</h2>
      <p className="paper-sub">
        Revision <Short value={body.revision_id} /> · run <Short value={body.displayed_run_id} />
      </p>
      <h3>Narrative</h3>
      <div className="paper-body">
        <Narrative narrative={body.narrative} />
      </div>
      <dl className="paper-sign">
        <dt>Signed by</dt>
        <dd>
          {body.signed_by.map((signer, index) => (
            <span key={`${signer}-${index}`}>
              {index ? ", " : null}
              <Short value={signer} />
            </span>
          ))}
        </dd>
        <dt>Frozen by</dt>
        <dd>
          <Short value={body.frozen_by} />
        </dd>
        {body.filed_by ? (
          <>
            <dt>Filed by</dt>
            <dd>
              <Short value={body.filed_by} />
            </dd>
          </>
        ) : null}
      </dl>
      <footer className="paper-filed">
        Payload <Short value={body.payload_sha256} prefix="sha256:" />
        {receipt ? (
          <>
            {" "}
            · filed event <Short value={receipt.filed_event_sha256} prefix="sha256:" />
          </>
        ) : null}
      </footer>
    </article>
  );
}

export function CommitteeSection({
  document,
}: {
  document: CommitteeDocument;
  tab: string | null;
}) {
  const { body } = document;
  const filed = body.state === "filed";
  return (
    <div
      className="col"
      data-committee-v1
      data-case={body.case_id}
      data-run={body.displayed_run_id}
      data-revision={body.revision_id}
      data-payload={body.payload_sha256}
    >
      {filed ? (
        <>
          <Paper body={body} />
          <Downloads body={body} />
        </>
      ) : (
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
            <Downloads body={body} />
          </div>
        </section>
      )}
      {body.artifacts.map((artifact) => (
        <Artifact key={artifact.route_node_id} artifact={artifact} />
      ))}
      {filed ? null : (
        <section className="pnl" data-committee-narrative>
          <header>
            <h2>Narrative</h2>
            <span className="tag">{body.narrative.length}</span>
          </header>
          <div className="pb">
            <Narrative narrative={body.narrative} />
          </div>
        </section>
      )}
      <Filing document={document} />
    </div>
  );
}

// The saved Report payload, read only. The saved Markdown is drawn as
// elements, never markup (D60), with its exact text a tab away; this surface
// offers no legacy draft action. A narrative figure is
// a chip that opens its source page (N59).
import { useState } from "react";
import { Link } from "react-router";
import { FilingControls } from "./FilingControls";
import { sectionPath } from "@/app/sections";
import { SeverityMark } from "@/chrome/SeverityMark";
import { sentence } from "@/chrome/compose";
import { ArtifactTexts } from "@/ds/ArtifactMarkdown";
import { NoteList } from "@/ds/atoms";
import { shortDigest, stamp } from "@/ds/format";
import { Narrative } from "@/evidence/Narrative";
import type { Severity } from "@/wire";
import type { ReportDocument, RevisionSummary } from "@/wire/v1";

function Artifact({ artifact }: { artifact: ReportDocument["body"]["artifacts"][number] }) {
  return (
    <section className="pnl" data-report-artifact={artifact.route_node_id}>
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
          <dd className="prose">{sentence(artifact.decision_scope)}</dd>
        </dl>
        <ArtifactTexts
          markdown={artifact.markdown}
          record={artifact.record}
          label={`${artifact.route_node_id} saved artifact`}
          section="report"
        />
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

/** How far a revision has gone, drawn as DESIGN.md's shapes: a flat dot for
    saved, a disc for frozen and waiting on committee, filed as done. */
const REVISION_STATE: Record<RevisionSummary["state"], { label: string; severity: Severity }> = {
  saved: { label: "Saved", severity: "IDLE" },
  frozen: { label: "Frozen · awaiting committee", severity: "RUNNING" },
  filed: { label: "Filed", severity: "SUCCESS" },
};

/** The run's revisions, newest first: where a reader picks one to read here,
    and the one front door to Committee for a revision once it is frozen. */
function Revisions({ body }: { body: ReportDocument["body"] }) {
  const run = new URLSearchParams({ case: body.case_id, run: body.displayed_run_id });
  const at = (section: "report" | "committee", revision: string) =>
    `${sectionPath(section)}?${run.toString()}&revision=${encodeURIComponent(revision)}`;
  return (
    <section className="pnl" data-report-revisions>
      <header>
        <h2>Revisions</h2>
        <span className="tag">{body.revisions.length}</span>
      </header>
      {body.revisions.length === 0 ? (
        <p className="pb note">
          Nothing has been saved from this run yet. A save makes the first revision.
        </p>
      ) : (
        <div className="tscroll" tabIndex={0} role="region" aria-label="Revisions">
          <table className="tbl revisions">
            <caption className="sr-only">This run&apos;s revisions, newest first</caption>
            <thead>
              <tr>
                <th scope="col" className="l">
                  Revision
                </th>
                <th scope="col">Saved</th>
                <th scope="col" className="l">
                  State
                </th>
                <th scope="col">
                  <span className="sr-only">Open</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {body.revisions.map((revision) => {
                const shown = revision.revision_id === body.revision_id;
                const state = REVISION_STATE[revision.state];
                return (
                  <tr
                    key={revision.revision_id}
                    aria-current={shown ? "true" : undefined}
                    data-revision-row={revision.revision_id}
                    data-state={revision.state}
                  >
                    <td className="l mono" title={revision.revision_id}>
                      {shortDigest(revision.revision_id)}
                    </td>
                    <td>
                      <time className="ts" dateTime={revision.saved_at}>
                        {stamp(revision.saved_at)}
                      </time>
                    </td>
                    <td className="l">
                      <span className="revstate">
                        <SeverityMark severity={state.severity} decorative />
                        {state.label}
                      </span>
                    </td>
                    <td className="acts">
                      {shown ? (
                        <span className="note">Shown</span>
                      ) : (
                        <Link
                          to={at("report", revision.revision_id)}
                          aria-label={`Open revision ${revision.revision_id}`}
                        >
                          Open
                        </Link>
                      )}
                      {revision.state === "saved" ? null : (
                        <Link
                          to={at("committee", revision.revision_id)}
                          aria-label={`Open revision ${revision.revision_id} in Committee`}
                        >
                          Committee
                        </Link>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

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
          <span className="cp">{body.revision_id === null ? "Not yet saved" : "Saved report"}</span>
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
      <Revisions body={body} />
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
          <Narrative narrative={body.narrative} />
        </div>
      </section>
    </div>
  );
}

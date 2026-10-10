// Analysis, v1 wire (brief 4.1, slice 4.1j). The modules are
// the section's tabs; the selected module fills the width in the five places
// every module shares (D60, `module.tsx`): its host facts, the model's view
// beside its key figures and caveats, the figures, the reader-facing
// sections, and one card of tabs -- Appendix, Audit, As written. What the run
// rests on is audit material: a count in the module's header opens it in the
// evidence drawer, and the Audit tab lists it with the module's own
// host-verified citations.
//
// Each source fact opens the evidence drawer by its identity (brief 4.4,
// decision 9); the drawer reads the page's text layer and places the stored
// rectangles over it. The model's Markdown is drawn as elements, never markup.
import { useCallback, useMemo, useRef, useState } from "react";
import { Dialog } from "@base-ui/react/dialog";
import { Link, useLocation, useSearchParams } from "react-router";
import { Figures, type FigurePick } from "./figures";
import { Depth, Lead, ModuleFacts, ReaderParts, useModuleParts, type DepthTab } from "./module";
import { NODE_SEVERITY, conclusionOf, handoffSeverity, nodeTone } from "./tone";
import { sectionPath } from "@/app/sections";
import { SeverityMark } from "@/chrome/SeverityMark";
import { formatDecimal } from "@/charts";
import { ModuleRefLink } from "@/ds/ModelMarkdown";
import { stamp } from "@/ds/format";
import type { ModuleRef } from "@/ds/markdown";
import { useEvidence, type FactIdentity } from "@/evidence/EvidenceContext";
import { Overlay } from "@/evidence/Overlay";
import { QUOTE_LABEL } from "@/evidence/TracedLine";
import { BlockedQuotes, NOT_LINKED, UnverifiedFacts } from "@/evidence/Unverified";
import { clampExcerpt } from "@/evidence/compact";
import { HandoffMarkers } from "@/evidence/Markers";
import type { AnalysisDocument, CitationView, HandoffView, PendingNode } from "@/wire/v1";

export { PROSE_SHOWN } from "./module";

const SCREENING_NOTICE = "Screening only: a screen, not committee clearance.";

type Handoffs = AnalysisDocument["body"]["handoffs"];

/** The documents this run's conclusions rest on: each cited document once,
    with the pages cited and how often, and whether it has been withdrawn. */
export function sourceRegister(handoffs: Handoffs) {
  const byDocument = new Map<
    string,
    {
      filename: string;
      pages: Set<number>;
      count: number;
      withdrawn: boolean;
      citations: { moduleId: string; identity: FactIdentity; withdrawn: boolean }[];
    }
  >();
  for (const handoff of handoffs) {
    for (const [index, fact] of handoff.source_facts.entries()) {
      const entry = byDocument.get(fact.document_sha256) ?? {
        filename: fact.filename,
        pages: new Set<number>(),
        count: 0,
        withdrawn: false,
        citations: [],
      };
      entry.pages.add(fact.page);
      entry.count += 1;
      entry.withdrawn ||= fact.withdrawn_at !== null;
      entry.citations.push({
        moduleId: handoff.module_id,
        withdrawn: fact.withdrawn_at !== null,
        identity: {
          record_sha256: handoff.record_sha256,
          source_id: fact.source_id,
          page: fact.page,
          index,
        },
      });
      byDocument.set(fact.document_sha256, entry);
    }
  }
  return [...byDocument.entries()]
    .map(([digest, entry]) => ({ digest, ...entry, pages: [...entry.pages].sort((a, b) => a - b) }))
    .sort((a, b) => b.count - a.count || a.filename.localeCompare(b.filename));
}

function SourceRegister({
  register,
  onOpen,
  closeOnOpen = false,
}: {
  register: ReturnType<typeof sourceRegister>;
  onOpen?: (identity: FactIdentity, opener: HTMLElement) => void;
  closeOnOpen?: boolean;
}) {
  const { openFact } = useEvidence();
  const open = onOpen ?? openFact;
  if (register.length === 0) {
    return <p className="note">No accepted module cites a source yet.</p>;
  }
  return (
    <ul className="plain register" data-source-register>
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
            {entry.pages.join(", ")} · {entry.count} {entry.count === 1 ? "citation" : "citations"}
          </span>
          <ul className="plain register-citations">
            {entry.citations.map(({ moduleId, identity, withdrawn }, citationIndex) => {
              const button = (
                <button
                  type="button"
                  className={`chip${withdrawn ? " withdrawn" : ""}`}
                  aria-label={`Read ${entry.filename} p.${identity.page} cited by ${moduleId}, citation ${citationIndex + 1}${withdrawn ? " · source withdrawn" : ""}`}
                  aria-haspopup="dialog"
                  data-register-fact={identity.source_id}
                  onClick={(event) => open(identity, event.currentTarget)}
                >
                  {moduleId} · p.{identity.page} · citation {citationIndex + 1}
                </button>
              );
              return (
                <li key={`${identity.record_sha256}-${identity.index}`}>
                  {closeOnOpen ? <Dialog.Close render={button} /> : button}
                </li>
              );
            })}
          </ul>
        </li>
      ))}
    </ul>
  );
}

/** Each source a located citation of this run names, by its file name: what
    an unverified citation's model-named source is called where it is known. */
export function sourceNames(handoffs: Handoffs): Map<string, string> {
  return new Map(
    handoffs.flatMap((handoff) =>
      handoff.source_facts.map((fact) => [fact.source_id, fact.filename] as const),
    ),
  );
}

function SourceFacts({
  record,
  facts,
  unverified,
}: {
  record: string;
  facts: readonly CitationView[];
  unverified: number;
}) {
  const { openFact, activeFact } = useEvidence();
  if (facts.length === 0) {
    return (
      <p className="note" data-source-facts>
        {unverified
          ? "No citation of this handoff was located by the host; its unverified citations are listed below."
          : "No citation is carried on this handoff."}
      </p>
    );
  }
  return (
    <ul className="plain facts" data-source-facts>
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
              aria-label={`${fact.marker === null ? `p.${fact.page}, evidence` : `C${fact.marker}, citation ${fact.marker}:`} ${fact.filename}, page ${fact.page}${fact.withdrawn_at !== null ? " · source withdrawn" : ""}`}
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
              {fact.marker === null ? `p.${fact.page}` : `C${fact.marker}`}
            </button>{" "}
            {fact.filename} · p.{fact.page}
          </span>
          {/* Compact (D107): the excerpt, about one line; its whole source line
              is the drawer's to show, one press away. */}
          <span className="excerpt" data-fact-excerpt>
            {fact.line.recorded ? null : (
              <span className="lbl" data-line-not-recorded>
                {QUOTE_LABEL}:{" "}
              </span>
            )}
            <q>{clampExcerpt(fact.matched_text)}</q>
          </span>
          {fact.linked ? null : (
            <div className="note" data-not-linked>
              {NOT_LINKED}
            </div>
          )}
          {fact.withdrawn_at !== null ? (
            <div className="note limitation" data-withdrawn-at={fact.withdrawn_at}>
              <b>This source has been withdrawn</b> at {stamp(fact.withdrawn_at)}. The citation
              stays so the conclusion that rests on it stays explicable.
            </div>
          ) : null}
        </li>
      ))}
    </ul>
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

/** The pressed mark, said beside the figures it came from. */
function Picked({ pick }: { pick: FigurePick }) {
  const amount = (value: string) => `${formatDecimal(value)}${pick.unit ? ` ${pick.unit}` : ""}`;
  return (
    <section className="pnl" data-picked aria-labelledby="picked-heading" aria-live="polite">
      <header>
        <h3 id="picked-heading">Selected figure</h3>
        <span className="cp">{pick.figure}</span>
      </header>
      <dl className="pb kv picked">
        <dt>Mark</dt>
        <dd>{pick.label}</dd>
        <dt>Value</dt>
        <dd className="mono tabular" data-picked-value>
          {/* An interquartile bar is no one figure: Q1 to Q3, each as served. */}
          {pick.interval
            ? `${amount(pick.interval.from)} to ${amount(pick.interval.to)}`
            : pick.value === null
              ? "n/a"
              : amount(pick.value)}
        </dd>
        <dt>Origin</dt>
        <dd>
          {pick.computed
            ? `Computed here: ${pick.computed}, not served`
            : pick.origin === null
              ? "Computed here: the stated total less the running level, not served"
              : "Model-authored, not host-verified"}
        </dd>
        <dt>Table</dt>
        <dd className="mono">{pick.table}</dd>
        <dt>Stated source</dt>
        <dd>{pick.source ?? "not stated"}</dd>
      </dl>
    </section>
  );
}

function ModuleView({
  handoff,
  handoffs,
  subject,
  model,
  tab,
  onTab,
}: {
  handoff: HandoffView;
  handoffs: Handoffs;
  subject: string | null;
  model: string;
  tab: DepthTab;
  onTab: (tab: DepthTab) => void;
}) {
  const severity = handoffSeverity(handoff);
  const read = useModuleParts(handoff);
  const reader = (read?.parts.reader ?? []).filter((part) => part !== read?.contrary);
  const { hash } = useLocation();
  const { openFact } = useEvidence();
  const register = sourceRegister(handoffs);
  const [pick, setPick] = useState<FigurePick | null>(null);
  const [opener, setOpener] = useState<HTMLElement | null>(null);
  const pendingFact = useRef<FactIdentity | null>(null);
  const citations = register.reduce((sum, entry) => sum + entry.count, 0);
  const withdrawn = register.filter((entry) => entry.withdrawn).length;
  return (
    <article className="module" data-handoff={handoff.module_id} aria-labelledby="module-heading">
      <header className="modhead">
        <SeverityMark severity={severity} decorative />
        <h2 id="module-heading">{handoff.module_name}</h2>
        {handoff.module_name === handoff.module_id ? null : (
          <span className="code">{handoff.module_id}</span>
        )}
        <span className="right">
          <span className={`tag ${severity === "SUCCESS" ? "ok" : "warn"}`} data-qa-status>
            {handoff.qa_status}
          </span>
        </span>
      </header>
      <ModuleFacts
        handoff={handoff}
        subject={subject}
        documents={
          <button
            type="button"
            className="evidence-count"
            aria-haspopup="dialog"
            data-documents-open
            onClick={(event) => setOpener(event.currentTarget)}
          >
            Run evidence · {register.length} {register.length === 1 ? "document" : "documents"} ·{" "}
            {citations} {citations === 1 ? "citation" : "citations"}
            {withdrawn ? (
              <span className="withdrawn">
                {" "}
                · <span className="glyph warn" aria-hidden="true" /> {withdrawn} withdrawn
              </span>
            ) : null}
          </button>
        }
      />
      <Lead handoff={handoff} read={read} screening={SCREENING_NOTICE} />
      <Figures
        handoff={handoff}
        calculation={<HostCalculation handoff={handoff} model={model} />}
        onPick={(next) => setPick(next)}
      />
      {pick ? <Picked pick={pick} /> : null}
      {reader.length ? <ReaderParts parts={reader} /> : null}
      <Depth
        key={hash}
        handoff={handoff}
        read={read}
        tab={tab}
        onTab={onTab}
        sourceFacts={
          <SourceFacts
            record={handoff.record_sha256}
            facts={handoff.source_facts}
            unverified={handoff.unverified_facts.length}
          />
        }
        unverifiedFacts={
          <UnverifiedFacts entries={handoff.unverified_facts} names={sourceNames(handoffs)} />
        }
        documents={<SourceRegister register={register} />}
        onPick={(next) => setPick(next)}
      />
      {opener ? (
        <Overlay
          look="drawer"
          opener={opener}
          onClose={() => {
            const selectedFact = pendingFact.current;
            pendingFact.current = null;
            setOpener(null);
            if (selectedFact && opener?.isConnected) openFact(selectedFact, opener);
          }}
          title="What this run rests on"
          data-documents-drawer
        >
          <div className="db">
            <p className="note">
              Every document the run&apos;s accepted modules cite, once, with the pages cited.
              Counts are the host&apos;s.
            </p>
            <SourceRegister
              register={register}
              closeOnOpen
              onOpen={(identity) => {
                pendingFact.current = identity;
              }}
            />
          </div>
        </Overlay>
      ) : null}
    </article>
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
        {pending.length ? (
          <span className="right">
            <span className="tag">{pending.length}</span>
          </span>
        ) : null}
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
              <span className="cp">
                {node.module_name === node.module_id ? "" : `${node.module_name} · `}
                {node.route_node_id}
              </span>
              {blockedBy?.route_node_id === node.route_node_id ? (
                <span className="cp" data-blocking-note>
                  its verdict ended the run · attempt {blockedBy.attempt_id}
                </span>
              ) : null}
              {blockedBy?.route_node_id === node.route_node_id ? (
                <BlockedQuotes blocked={blockedBy} />
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

/** A module reference (`[CP-1B B2]`) as a way there: the module's tab, and
    the register opened in its appendix. A module this run did not accept
    reads as its name alone. */
function useModuleLinks(handoffs: Handoffs) {
  const [params] = useSearchParams();
  const nodes = useMemo(
    () => new Map(handoffs.map((entry) => [entry.module_id, entry.route_node_id])),
    [handoffs],
  );
  return useCallback(
    (ref: ModuleRef) => {
      const label = `${ref.module}${ref.register ? ` · ${ref.register}` : ""}${ref.note ? ` ${ref.note}` : ""}`;
      const node = nodes.get(ref.module);
      if (node === undefined) {
        return (
          <span className="ref" data-ref={ref.module} title="Not a module accepted on this run">
            {label}
          </span>
        );
      }
      const next = new URLSearchParams(params);
      next.set("tab", node);
      return (
        <Link
          className="ref"
          data-ref={ref.module}
          to={{
            search: `?${next.toString()}`,
            hash: ref.register ? `register-${encodeURIComponent(ref.register)}` : "",
          }}
        >
          {label}
        </Link>
      );
    },
    [nodes, params],
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
  const [depth, setDepth] = useState<DepthTab>("appendix");
  const link = useModuleLinks(body.handoffs);
  const model = `${sectionPath("model")}?${new URLSearchParams({
    case: body.case_id,
    ...(body.displayed_run_id ? { run: body.displayed_run_id } : {}),
  }).toString()}`;
  return (
    <ModuleRefLink value={link}>
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
          <HandoffMarkers key={handoff.route_node_id} handoff={handoff}>
            <ModuleView
              key={handoff.route_node_id}
              handoff={handoff}
              handoffs={body.handoffs}
              subject={
                body.subject
                  ? `${body.subject.issuer_name} · ${body.subject.reporting_period}`
                  : null
              }
              model={model}
              tab={depth}
              onTab={setDepth}
            />
          </HandoffMarkers>
        )}
        <PendingList
          pending={body.pending}
          runStatus={body.displayed_run_status}
          blockedBy={body.blocked_by}
        />
      </div>
    </ModuleRefLink>
  );
}

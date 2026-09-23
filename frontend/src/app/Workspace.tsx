// One screen. The chrome never changes; only the body does (IA_SPEC.md 1).
import { useCallback, useEffect, useMemo, useRef, useState, type ComponentType } from "react";
import { useSearchParams } from "react-router";
import {
  INITIAL,
  accepts,
  analyticalIdentity,
  displayedRunIdOf,
  issue,
  navigate,
  refetches,
  tailed,
  ticket,
  withWithdrawals,
  withdrawalsOf,
  type Authority,
} from "./authority";
import { focusSectionHeading, pageTitle } from "./heading";
import { SECTION_LABELS, isEnabledSection } from "./sections";
import { VisibleSnapshotContext, type VisibleSnapshot } from "./snapshot";
import { LedgerProvider } from "./ledger";
import { eventsUrl, openTail } from "./sse";
import {
  OFFLINE_WORDING,
  fetchSection,
  sectionUrl,
  type RegionStatus,
  type WorkspaceDocument,
} from "./transport";
import { SECTION_VIEWS } from "./views";
import { DecisionBrief } from "@/chrome/DecisionBrief";
import { Rail } from "@/chrome/Rail";
import { Ribbon } from "@/chrome/Ribbon";
import { SectionPanel, SectionTabs } from "@/chrome/SectionTabs";
import { VerdictStrip } from "@/chrome/VerdictStrip";
import { QualificationStrip } from "@/chrome/QualificationStrip";
import { composeChrome, markDisabled } from "@/chrome/compose";
import { fallbackChrome } from "@/chrome/fallback";
import { EvidenceProvider } from "@/evidence/EvidenceContext";
import { Announcer } from "@/states/Announcer";
import { NotLive, PageAlert } from "@/states/PageAlert";
import { RegionState } from "@/states/RegionState";
import { SectionBoundary } from "@/states/SectionBoundary";
import type { Chrome, Section } from "@/wire";

const LOADING: RegionStatus = { kind: "loading" };
const UNAVAILABLE: RegionStatus = { kind: "unavailable" };

/** The chrome composed for a v1 document. A disabled section never fetches,
    so it never reaches here with a document to compose from. */
function chromeOf(section: Section, status: RegionStatus): Chrome | null {
  if (!("document" in status)) return null;
  return isEnabledSection(section) ? composeChrome(section, status.document) : null;
}

interface Keyed<T> {
  key: string;
  value: T;
}

/** What the region holds: the displayed answer, a newer one about a different
    analytical identity that waits for Reload (decision 6), and the refetch
    that did not answer at all, which is shown beside the displayed document
    rather than in place of it (finding FE-2). */
interface Held {
  displayed: RegionStatus;
  pending: RegionStatus | null;
  interrupted: RegionStatus | null;
}

/** A refetch under the same identity replaces the view; a different identity
    is held as pending. A refetch that answers `unavailable` -- a 404, standing
    lost -- replaces at once: a safety change never waits for Reload. A refetch
    that answers nothing at all (offline, a refusal) replaces nothing: the
    reader keeps the document they are reading and the draft they are writing,
    and is told the view is no longer live. */
function adopt(section: Section, current: Held | null, next: RegionStatus): Held {
  const fresh = { displayed: next, pending: null, interrupted: null };
  if (!current || !("document" in current.displayed)) return fresh;
  const shown = current.displayed;
  if (!("document" in next)) {
    return next.kind === "unavailable" ? fresh : { ...current, interrupted: next };
  }
  const identity = analyticalIdentity(section, shown.document);
  if (identity === null || identity === analyticalIdentity(section, next.document)) return fresh;
  return { displayed: shown, pending: next, interrupted: null };
}

/** What the reader is told when a refetch did not answer: the typed code where
    there was one, never engine text. */
function interruption(status: RegionStatus): string {
  const why = status.kind === "error" ? `${status.refusal.code}. ` : `${OFFLINE_WORDING} `;
  return `${why}This view is the last document the server served, and no longer updates on its own.`;
}

const PAUSED_WORDING =
  "Live updates paused. The event stream was refused; this view reconnects on its own.";

/** The displayed document, marked stale over a pending one and carrying that
    one's withdrawals, never its figures. */
function visible(held: Held): RegionStatus {
  const { displayed, pending } = held;
  if (!pending || !("document" in displayed) || !("document" in pending)) return displayed;
  return {
    kind: "stale",
    document: withWithdrawals(displayed.document, withdrawalsOf(pending.document)),
  };
}

export function Workspace({ section }: { section: Section }) {
  const [params] = useSearchParams();
  const caseId = params.get("case");
  const runId = params.get("run");
  const revisionId = params.get("revision");
  const qualificationEvidence = params.get("qualification");
  const carried = new URLSearchParams();
  if (caseId) carried.set("case", caseId);
  if (runId) carried.set("run", runId);
  if (revisionId) carried.set("revision", revisionId);
  if (qualificationEvidence) carried.set("qualification", qualificationEvidence);
  const caseSearch = carried.toString();
  const fixture = import.meta.env.MODE === "demo" ? params.get("fixture") : null;
  // A disabled section, or a case section with no case, sends no request and
  // opens no tail: it is `unavailable` in every mode (brief 4.1, decision 9).
  const requested =
    sectionUrl(section, { case: caseId, run: runId, revision: revisionId, fixture }) !== null;
  // Everything the reader sees is keyed on the request that produced it, so a
  // navigation shows `loading` without a render-time state write. The
  // qualification hash is not part of it: it binds global evidence the strip
  // reads for itself and names no section request, so keying on it would tear
  // the section down — and its open tail with it — for a label change.
  const key = `${section}|${caseId ?? ""}|${runId ?? ""}|${revisionId ?? ""}|${fixture ?? ""}`;
  const [held, setHeld] = useState<Keyed<Held> | null>(null);
  const [tabChoice, setTabChoice] = useState<Keyed<string> | null>(null);
  const [tail, setTail] = useState<Keyed<boolean> | null>(null);
  const authority = useRef<Authority>(INITIAL);

  useEffect(() => {
    if (!requested) return undefined;
    authority.current = navigate(authority.current, caseId);
    // At most one fetch in flight; a name arriving mid-flight marks it dirty
    // and exactly one more fetch follows (decision 5).
    let flight: { controller: AbortController; dirty: boolean } | null = null;
    const put = (next: (current: Held | null) => Held) =>
      setHeld((current) => ({ key, value: next(current?.key === key ? current.value : null) }));

    // Answers with what the read said, so a refused reconnect can be decided
    // on the document rather than on the stream EventSource will not describe.
    const load = (): Promise<RegionStatus | null> => {
      if (flight) {
        flight.dirty = true;
        return Promise.resolve(null);
      }
      const mine = { controller: new AbortController(), dirty: false };
      flight = mine;
      authority.current = issue(authority.current);
      const sent = ticket(authority.current);
      return fetchSection(
        section,
        { case: caseId, run: runId, revision: revisionId, fixture },
        mine.controller.signal,
      ).then((next) => {
        // A late response, for a case or run the user has left, is discarded.
        if (!accepts(authority.current, sent)) return null;
        flight = null;
        put((current) => adopt(section, current, next));
        if (mine.dirty) load();
        return next;
      });
    };
    const cancel = () => {
      flight?.controller.abort();
      flight = null;
      authority.current = issue(authority.current);
    };

    // A section no event refetches opens no stream -- Directory, and Book,
    // which is portfolio-scoped and which no case event names. The tail opens
    // before the first fetch so a fixture stream's frame counter is reset
    // before the document it drives.
    const stream =
      caseId && tailed(section)
        ? openTail(eventsUrl(caseId, runId, fixture), {
            onEvent: (name) => {
              if (refetches(name, section)) void load();
            },
            // Every open, the first included: an event landing between the
            // document read and the stream's head is not replayed, and the
            // one-flight rule coalesces the read this doubles (finding FE-9).
            onOpen: () => void load(),
            // A closed stream is a refusal or, in Firefox, a connection that
            // never opened: EventSource cannot tell them apart. The document
            // read can, so it decides: a case that is gone stops the tail, and
            // anything else is waited out and tried again.
            onRefused: async () => {
              const answer = await load();
              return {
                stop: answer?.kind === "unavailable",
                retryAfterSeconds:
                  answer?.kind === "error" ? (answer.retryAfterSeconds ?? null) : null,
              };
            },
            onLive: (live) => setTail({ key, value: live }),
          })
        : null;
    void load();
    return () => {
      stream?.close();
      cancel();
    };
  }, [requested, section, caseId, runId, revisionId, fixture, key]);

  const reload = useCallback(() => {
    setHeld((current) =>
      current?.value.pending
        ? {
            key: current.key,
            value: { displayed: current.value.pending, pending: null, interrupted: null },
          }
        : current,
    );
    // The button that was pressed is gone with the state it cleared, so focus
    // lands on the heading of the region it just replaced (finding FE-4).
    focusSectionHeading();
  }, []);

  const current = requested && held?.key === key ? held.value : null;
  const status = useMemo(
    () => (requested ? (current ? visible(current) : LOADING) : UNAVAILABLE),
    [requested, current],
  );
  const latest = current?.pending ?? current?.displayed ?? null;
  // The refetch that did not answer says the view is not live and replaces
  // nothing (FE-2).
  const interrupted = current?.interrupted ?? null;
  const document = "document" in status ? status.document : null;
  const displayedRunId = document ? displayedRunIdOf(section, document) : null;
  // The view is mounted under what it is about, never under `observed_at`, so
  // an ordinary refresh keeps its local selection (R5).
  const displayedRevisionId =
    document && "revision_id" in document.body ? document.body.revision_id : null;
  const mountKey = `${caseId ?? ""}|${displayedRunId ?? ""}|${displayedRevisionId ?? ""}`;
  const snapshot = useMemo<VisibleSnapshot | null>(
    () =>
      document
        ? {
            key: `${section}|${caseId ?? ""}|${displayedRunId ?? ""}|${displayedRevisionId ?? ""}`,
            caseId,
            displayedRunId,
            document,
            withdrawals:
              latest && "document" in latest ? withdrawalsOf(latest.document) : new Map(),
          }
        : null,
    [document, section, caseId, displayedRunId, displayedRevisionId, latest],
  );
  // A tail the server refused says so while there is still a document it was
  // following; a region with none is already saying more than that (FE-3).
  const paused = document !== null && tail?.key === key && !tail.value;
  const chrome = chromeOf(section, status);
  const activeTab =
    (tabChoice?.key === key ? tabChoice.value : null) ?? chrome?.tabs[0]?.id ?? null;
  const subject = chrome?.subject?.issuer ?? caseId;
  // The tab says which section of which case is on screen (WCAG 2.4.2).
  useEffect(() => {
    globalThis.document.title = pageTitle(SECTION_LABELS[section], subject);
  }, [section, subject]);
  // A navigation replaces the region under the control that was activated, so
  // focus moves to the heading of what arrived rather than falling to the
  // document (WCAG 2.4.3, finding FE-4). The first render is not a navigation.
  const arrived = useRef<string | null>(null);
  useEffect(() => {
    if (arrived.current !== null && arrived.current !== key) focusSectionHeading();
    arrived.current = key;
  }, [key]);
  // ponytail: one erasure, here rather than nine in the registry. `section`
  // is a runtime value, so the lookup yields the union of nine differently
  // typed views and no document satisfies them all; the registry has already
  // checked each view against its own document, and a disabled section never
  // reaches this render with a document to mount.
  const View = SECTION_VIEWS[section] as ComponentType<{
    document: WorkspaceDocument;
    tab: string | null;
  }>;
  // With no document there is still a section: the bands carry its state.
  const fallback = fallbackChrome(status);

  return (
    <div className="ap" data-section={section}>
      <Ribbon
        ribbon={(chrome ?? fallback).ribbon}
        subject={chrome?.subject ?? null}
        tabs={chrome?.tabs.map((tab) => tab.id)}
        onTab={(id) => setTabChoice({ key, value: id })}
      />
      <DecisionBrief brief={(chrome ?? fallback).brief} />
      <SectionTabs
        label={SECTION_LABELS[section]}
        tabs={chrome?.tabs ?? []}
        active={activeTab}
        onSelect={(id) => setTabChoice({ key, value: id })}
      />
      <VerdictStrip verdict={(chrome ?? fallback).verdict} />
      <QualificationStrip evidenceSha256={qualificationEvidence} />
      <div className="frame">
        <Rail
          section={section}
          entries={markDisabled(chrome?.rail ?? null)}
          local={chrome?.rail_local ?? null}
          servedRole={chrome?.served_role ?? null}
          search={caseSearch ? `?${caseSearch}` : ""}
        />
        <main className="body" id="body" aria-label={SECTION_LABELS[section]}>
          <Announcer>
            {status.kind === "offline" ? <PageAlert sentence={OFFLINE_WORDING} /> : null}
            {/* Neither replaces the document: they say it is not live. */}
            {interrupted ? <NotLive mark="refresh" sentence={interruption(interrupted)} /> : null}
            {paused ? <NotLive mark="tail" sentence={PAUSED_WORDING} /> : null}
            <VisibleSnapshotContext.Provider value={snapshot}>
              {/* The evidence surface is bound to the section it was opened
                  on (brief 4.4, decision 9): the key closes it on a section
                  change, which the workspace itself no longer does -- the rail
                  outlives a navigation so the link that was activated keeps
                  its place (finding FE-4). */}
              <EvidenceProvider key={section}>
                {/* The snapshot ledger outlives the documents a section renders,
                    so it sits above the boundary and the mount key. */}
                <LedgerProvider>
                  <RegionState status={status} onReload={reload}>
                    {(doc) => (
                      // A render failure is about the document that caused it:
                      // the next one served clears it, without waiting for a
                      // navigation to unmount the boundary.
                      <SectionBoundary key={mountKey} resetOn={doc.observed_at}>
                        <SectionPanel tab={activeTab}>
                          <View key={mountKey} document={doc} tab={activeTab} />
                        </SectionPanel>
                      </SectionBoundary>
                    )}
                  </RegionState>
                </LedgerProvider>
              </EvidenceProvider>
            </VisibleSnapshotContext.Provider>
          </Announcer>
        </main>
      </div>
    </div>
  );
}

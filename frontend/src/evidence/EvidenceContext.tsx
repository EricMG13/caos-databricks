// One evidence drawer and one passport for the whole workspace. Openers are
// passed from the click that opened them; there is no second inspector.
//
// A v1 source fact is opened by its identity, never by a copy of the citation
// (brief 4.4, decision 9): each render re-resolves it against the visible
// snapshot, so a case or run switch closes it, a withdrawal updates it, and a
// pending document the user has not reloaded never reaches it.
import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { EvidenceDrawer } from "./EvidenceDrawer";
import { MetricPassport } from "./MetricPassport";
import { SourceDrawer } from "./SourceDrawer";
import { useVisibleSnapshot, type VisibleSnapshot } from "@/app/snapshot";
import type { Citation, Passport } from "@/wire";
import { shortDigest } from "@/ds/format";
import type { CitationView, ReportDocument } from "@/wire/v1";

type NarrativeFigure = NonNullable<ReportDocument["body"]["narrative"][number][number]["figure"]>;

/** Which citation of which accepted record: `index` within its source facts. */
export interface FactIdentity {
  record_sha256: string;
  source_id: string;
  page: number;
  index: number;
}

interface Evidence {
  openCitation(citation: Citation, opener: HTMLElement): void;
  /** Open the metric passport overlay. Its caller is the Book, which adapts
      a v1 `BookPassport` to this shape in `sections/book/passport.ts`; it had
      none while the Book was its unavailable shell and was kept for the reason
      the note in `app/authority.ts` gives. `test_passport_contract`, pinned by
      name in `tests/test_phase_exits.py`, still renders `MetricPassport`
      directly, because what it holds is the ten fields rather than the route
      a caller takes to them. */
  openPassport(passport: Passport, opener: HTMLElement): void;
  openFact(identity: FactIdentity, opener: HTMLElement): void;
  activeChip: string | null;
  activeFact: FactIdentity | null;
}

const Context = createContext<Evidence>({
  openCitation() {},
  openPassport() {},
  openFact() {},
  activeChip: null,
  activeFact: null,
});

export function useEvidence(): Evidence {
  return useContext(Context);
}

/** One opening of a surface. `id` keys it: a surface opened again while the
    last one is still leaving mounts afresh, rather than taking over the one
    that is closing and being closed with it. */
interface Open<T> {
  subject: T;
  opener: HTMLElement;
  id: number;
}

/** A saved narrative's figure as the drawer reads a citation (N59). It names
    its document, source, page and quote but stores no rectangle and no file
    name, so it claims none: the drawer says nothing is highlighted, and the
    heading names the document by its digest. */
function figureFact(figure: NarrativeFigure): CitationView {
  return {
    document_sha256: figure.document_sha256,
    source_id: figure.source_id,
    filename: `${figure.route_node_id} source ${shortDigest(figure.document_sha256)}`,
    page: figure.page,
    matched_text: figure.matched_text,
    rects: figure.rects,
    withdrawn_at: figure.withdrawn_at,
  };
}

/** The citation a fact identity names in the visible snapshot; a saved
    narrative's figure carries its rectangles and withdrawal as a citation does (N93). */
function resolveFact(
  snapshot: VisibleSnapshot,
  identity: FactIdentity,
): { fact: CitationView } | null {
  const body = snapshot.document.body;
  if ("narrative" in body) {
    const figure = body.narrative
      .flat()
      .find(
        ({ figure }) =>
          figure?.record_sha256 === identity.record_sha256 &&
          figure.citation_index === identity.index &&
          figure.source_id === identity.source_id &&
          figure.page === identity.page,
      )?.figure;
    return figure ? { fact: figureFact(figure) } : null;
  }
  if (!("handoffs" in body)) return null;
  for (const handoff of body.handoffs) {
    if (handoff.record_sha256 !== identity.record_sha256) continue;
    const fact = handoff.source_facts[identity.index];
    if (fact && fact.source_id === identity.source_id && fact.page === identity.page) {
      return { fact };
    }
  }
  return null;
}

export function EvidenceProvider({ children }: { children: ReactNode }) {
  const snapshot = useVisibleSnapshot();
  const [citation, setCitation] = useState<Open<Citation> | null>(null);
  const [passport, setPassport] = useState<Open<Passport> | null>(null);
  const [fact, setFact] = useState<(Open<FactIdentity> & { key: string }) | null>(null);
  const snapshotKey = snapshot?.key ?? null;
  const opens = useRef(0);
  const openCitation = useCallback(
    (subject: Citation, opener: HTMLElement) =>
      setCitation({ subject, opener, id: (opens.current += 1) }),
    [],
  );
  const openPassport = useCallback(
    (subject: Passport, opener: HTMLElement) =>
      setPassport({ subject, opener, id: (opens.current += 1) }),
    [],
  );
  const openFact = useCallback(
    (subject: FactIdentity, opener: HTMLElement) => {
      if (snapshotKey !== null) {
        setFact({ subject, opener, key: snapshotKey, id: (opens.current += 1) });
      }
    },
    [snapshotKey],
  );
  // A close clears only the opening it belongs to, never one made since.
  const closing =
    <T extends { id: number }>(
      set: (update: (current: T | null) => T | null) => void,
      id: number,
    ) =>
    () =>
      set((current) => (current?.id === id ? null : current));
  // Bound to the snapshot it was opened on: another key, or a citation that
  // is no longer there, closes it for good rather than hiding it.
  const resolved =
    fact && snapshot && snapshot.key === fact.key ? resolveFact(snapshot, fact.subject) : null;
  // Closed on the snapshot that took the citation away, not on every render:
  // the sentinel is React's own pattern for state derived from a prop, and an
  // unconditional render-phase write is a re-render loop waiting for a
  // `resolveFact` that answers differently twice.
  const [seenSnapshot, setSeenSnapshot] = useState(snapshot);
  if (snapshot !== seenSnapshot) {
    setSeenSnapshot(snapshot);
    if (fact && !resolved) setFact(null);
  }
  const shown = resolved ? fact : null;
  const value = useMemo(
    () => ({
      openCitation,
      openPassport,
      openFact,
      activeChip: citation?.subject.chip ?? null,
      activeFact: shown?.subject ?? null,
    }),
    [openCitation, openPassport, openFact, citation, shown],
  );
  const address =
    snapshot?.caseId && snapshot.displayedRunId
      ? { caseId: snapshot.caseId, runId: snapshot.displayedRunId }
      : null;
  return (
    <Context.Provider value={value}>
      {children}
      {passport ? (
        <MetricPassport
          key={passport.id}
          passport={passport.subject}
          opener={passport.opener}
          onClose={closing(setPassport, passport.id)}
        />
      ) : null}
      {citation ? (
        <EvidenceDrawer
          key={citation.id}
          citation={citation.subject}
          opener={citation.opener}
          onClose={closing(setCitation, citation.id)}
        />
      ) : null}
      {shown && resolved && snapshot ? (
        <SourceDrawer
          key={`${snapshot.key}|${shown.id}`}
          fact={resolved.fact}
          address={address}
          withdrawnAt={
            snapshot.withdrawals.get(resolved.fact.source_id) ?? resolved.fact.withdrawn_at
          }
          opener={shown.opener}
          onClose={closing(setFact, shown.id)}
        />
      ) : null}
    </Context.Provider>
  );
}

// Citation markers as chips (D107; owner, 4 October 2026: "Compact, source on
// click"). A module's body cites by `[C<n>]`; each marker is drawn as a small
// chip. An anchored citation's chip opens the source drawer at its page,
// where its whole line is shown with the excerpt marked -- the one place the
// full line is shown. An unverified one's chip is labelled "unverified – page
// N" and opens nothing: no located source exists to open (D106). A number
// no citation holds, or a record from before markers, leaves the bracket as
// written. React escapes every character.
import type { ReactNode } from "react";
import { CitationMarkerLink } from "@/ds/ModelMarkdown";
import type { CitationView, HandoffView, ReportArtifact } from "@/wire/v1";
import { useEvidence, type FactIdentity } from "./EvidenceContext";

/** How an unverified marker reads: its page, as the model gave it. */
export function unverifiedMarkerLabel(page: number): string {
  return `unverified – page ${page}`;
}

/** The chip for an anchored citation: `C<n>`, named "citation n" with where
    it opens, pressed to open the source drawer at `identity`. */
export function MarkerChip({
  n,
  place,
  identity,
  withdrawn,
}: {
  n: number;
  /** Where it opens, for its accessible name: "10-K.htm, page 4". */
  place: string;
  identity: FactIdentity;
  withdrawn: boolean;
}) {
  const { openFact, activeFact } = useEvidence();
  const open =
    activeFact !== null &&
    activeFact.record_sha256 === identity.record_sha256 &&
    activeFact.index === identity.index;
  return (
    <button
      type="button"
      className={`chip cmark${withdrawn ? " withdrawn" : ""}`}
      aria-label={`citation ${n}: ${place}${withdrawn ? " · source withdrawn" : ""}`}
      aria-haspopup="dialog"
      aria-expanded={open}
      data-marker-chip={n}
      onClick={(event) => openFact(identity, event.currentTarget)}
    >
      C{n}
    </button>
  );
}

/** The chip for an unverified citation: labelled, inert, never a control. */
export function UnverifiedMarker({ n, page }: { n: number; page: number }) {
  return (
    <span className="chip cmark unverified" data-marker-chip={n} data-unverified-marker>
      <span className="sr-only">citation {n}, </span>
      <span aria-hidden="true">C{n} · </span>
      {unverifiedMarkerLabel(page)}
    </span>
  );
}

type Draw = (n: number) => ReactNode;

/** A chip per marker place, from a list of `[marker, draw]`. */
function drawer(entries: readonly (readonly [number | null, () => ReactNode])[]): Draw {
  const byMarker = new Map<number, () => ReactNode>();
  for (const [marker, draw] of entries) if (marker !== null) byMarker.set(marker, draw);
  return (n) => byMarker.get(n)?.() ?? null;
}

const factPlace = (fact: CitationView) => `${fact.filename}, page ${fact.page}`;

/** A module view's markers: its source facts and unverified citations. */
export function HandoffMarkers({
  handoff,
  children,
}: {
  handoff: HandoffView;
  children: ReactNode;
}) {
  const draw = drawer([
    ...handoff.source_facts.map(
      (fact, index) =>
        [
          fact.marker,
          () => (
            <MarkerChip
              n={fact.marker!}
              place={factPlace(fact)}
              withdrawn={fact.withdrawn_at !== null}
              identity={{
                record_sha256: handoff.record_sha256,
                source_id: fact.source_id,
                page: fact.page,
                index,
              }}
            />
          ),
        ] as const,
    ),
    ...handoff.unverified_facts.map(
      (entry) =>
        [entry.marker, () => <UnverifiedMarker n={entry.marker!} page={entry.page} />] as const,
    ),
  ]);
  return <CitationMarkerLink value={draw}>{children}</CitationMarkerLink>;
}

/** A saved artifact's markers (Report, Committee): what the read served as
    its marked figures and unverified citations. */
export function ArtifactMarkers({
  artifact,
  children,
}: {
  artifact: ReportArtifact;
  children: ReactNode;
}) {
  const draw = drawer([
    ...artifact.figures.map(
      (figure) =>
        [
          figure.marker,
          () => (
            <MarkerChip
              n={figure.marker!}
              place={`${figure.route_node_id} source, page ${figure.page}`}
              withdrawn={figure.withdrawn_at !== null}
              identity={{
                record_sha256: figure.record_sha256,
                source_id: figure.source_id,
                page: figure.page,
                index: figure.citation_index,
              }}
            />
          ),
        ] as const,
    ),
    ...artifact.unverified.map(
      (entry) =>
        [entry.marker, () => <UnverifiedMarker n={entry.marker!} page={entry.page} />] as const,
    ),
  ]);
  return <CitationMarkerLink value={draw}>{children}</CitationMarkerLink>;
}

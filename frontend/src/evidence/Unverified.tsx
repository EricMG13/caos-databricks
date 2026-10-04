// A citation the host could not anchor (D106; owner, 4 October 2026: "Yes;
// show as unverified"). It is the model's own locator and quote: labelled
// "unverified – page N" before its text, as the model's quote, its claim
// Deploy V's lineage class "Untraced", and why in plain words. Never the
// host-verified well, never a `<mark>`, never a "Source line", and never
// opened in a drawer: there is no line, rectangle or located document to show.
// React escapes the quote: it is the model's text, which the host did not find.
import { Digest } from "@/ds/Digest";
import type { BlockedByView, UnverifiedCitationView } from "@/wire/v1";
import { useEvidence } from "./EvidenceContext";

type Code = UnverifiedCitationView["code"];

/** Why a citation is unverified, in the reader's words, for every code the
    wire names (a code it adds later fails the read until this names it). */
export const UNVERIFIED_REASONS: Record<Code, string> = {
  CITATION_NOT_LOCATED: "not located",
  CITATION_AMBIGUOUS: "ambiguous",
  CITATION_NOT_DELIVERED: "not in the delivered evidence",
};

/** What an anchored citation the answer's body does not carry says (D106). */
export const NOT_LINKED = "Not linked to a statement in the answer.";
/** The same, inline: beside a narrative figure, and beside an unverified
    quote's reason where no statement of the answer carries it either. */
export const NOT_LINKED_SHORT = "not linked to a statement in the answer";

/** The label every surface puts before an unverified quote. */
export function unverifiedLabel(entry: { page: number; code: Code; linked?: boolean }): string {
  const reasons = [
    UNVERIFIED_REASONS[entry.code],
    ...(entry.linked === false ? [NOT_LINKED_SHORT] : []),
  ];
  return `unverified \u2013 page ${entry.page} · the model's quote · claim lineage: Untraced · ${reasons.join(" · ")}`;
}

/** One module's unverified citations, each labelled first. `names` gives a
    source's file name where this run's located citations name the same
    source; the model's id is not otherwise looked up. */
export function UnverifiedFacts({
  entries,
  names,
}: {
  entries: readonly UnverifiedCitationView[];
  names: ReadonlyMap<string, string>;
}) {
  return (
    <ul className="plain facts" data-unverified-facts>
      {entries.map((entry, index) => (
        <li key={index} className="ev" data-unverified-citation={entry.code}>
          <div className="lbl">
            {unverifiedLabel(entry)} · {names.get(entry.source_id) ?? `source ${entry.source_id}`}
          </div>
          <blockquote className="unverified-quote">{entry.matched_text}</blockquote>
        </li>
      ))}
    </ul>
  );
}

/** A short excerpt of a quote for a compact display (D107): its first twelve
    words, elided after. The full line is the source drawer's to show. */
export function shortExcerpt(quote: string): string {
  const words = quote.split(/\s+/).filter(Boolean);
  return words.length > 12 ? `${words.slice(0, 12).join(" ")}\u2026` : words.join(" ");
}

/** The identity a Blocked answer's located quote opens the source drawer by:
    no accepted record holds it, so it is keyed by the verdict's attempt. */
export function blockedRecord(blocked: BlockedByView): string {
  return `blocked:${blocked.attempt_id}`;
}

/** A Blocked answer's quotes, as the host judged them (D106; owner: "Show its
    quotes"), compact (D107): document · page · a short excerpt, each located
    one opening its page in the source drawer, where its line is shown with
    the excerpt marked; each unverified one labelled as the model's own. A
    verdict recorded before the quotes were kept says so, and kept quotes
    that cannot be read are their typed refusal, here and nowhere else. */
export function BlockedQuotes({ blocked }: { blocked: BlockedByView }) {
  const { openFact } = useEvidence();
  if (!blocked.quotes_recorded) {
    return (
      <p className="note" data-blocked-quotes="not-recorded">
        Quotes not recorded for this block.
      </p>
    );
  }
  if (blocked.quotes_refusal !== null) {
    return (
      <p className="note limitation" data-blocked-quotes="unreadable">
        This block's quotes could not be read ({blocked.quotes_refusal.code}).{" "}
        {blocked.quotes_refusal.clears}
      </p>
    );
  }
  return (
    <div data-blocked-quotes="recorded">
      <div className="lbl">The Blocked answer's quotes · check the block against the sources</div>
      <ul className="plain blocked-quotes">
        {blocked.verified.map((quote, index) => (
          <li key={`v${index}`} data-blocked-quote="verified">
            <button
              type="button"
              className="chip"
              aria-haspopup="dialog"
              aria-label={`Open the source of verified quote ${index + 1}, page ${quote.page}`}
              data-blocked-chip={quote.source_id}
              onClick={(event) =>
                openFact(
                  {
                    record_sha256: blockedRecord(blocked),
                    source_id: quote.source_id,
                    page: quote.page,
                    index,
                  },
                  event.currentTarget,
                )
              }
            >
              p.{quote.page}
            </button>{" "}
            Verified · <Digest value={quote.document_sha256} prefix="sha256:" /> · page {quote.page}{" "}
            · <q>{shortExcerpt(quote.matched_text)}</q>
            {quote.linked ? null : <span className="lbl"> · {NOT_LINKED_SHORT}</span>}
          </li>
        ))}
        {blocked.unverified.map((entry, index) => (
          <li key={`u${index}`} data-blocked-quote="unverified">
            <span className="lbl">{unverifiedLabel(entry)}</span> ·{" "}
            <q className="figq-unverified">{shortExcerpt(entry.matched_text)}</q>
          </li>
        ))}
      </ul>
    </div>
  );
}

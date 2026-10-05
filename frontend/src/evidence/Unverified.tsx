// A citation the host could not anchor (D106; owner, 4 October 2026: "Yes;
// show as unverified"). It is the model's own locator and quote: labelled
// "unverified – page N" before its text, as the model's quote, its claim
// Deploy V's lineage class "Untraced", and why in plain words. Never the
// host-verified well, never a `<mark>`, never a "Source line", and never
// opened in a drawer: there is no line, rectangle or located document to show.
// React escapes the quote: it is the model's text, which the host did not find.
import type { UnverifiedCitationView } from "@/wire/v1";

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

/** The label every surface puts before an unverified quote. */
export function unverifiedLabel(entry: { page: number; code: Code }): string {
  return `unverified – page ${entry.page} · the model's quote · claim lineage: Untraced · ${UNVERIFIED_REASONS[entry.code]}`;
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

// What a draft may say about a figure, and what the picker may offer for one.
//
// A figure span names a citation of a verified record by its route node and
// its position in that record's `citations` -- nothing else. The host fills
// the document, the page and the quote from the accepted record at save, and
// refuses a reference it cannot resolve, so nothing here decides whether a
// figure is valid. The picker only offers the citations the served Report
// document's own records carry, at the index the server will read them by.
import { unverifiedLabel } from "@/evidence/Unverified";
import type { NarrativeDraft, ReportDocument, UnverifiedCitationView } from "@/wire/v1";

/** One citation a figure may name, and what the author is shown for it. */
export interface CitationChoice {
  route_node_id: string;
  /** Its place in the record's `citations`, or, for an unverified one, in
      its `unverified` list (D106). */
  citation_index: number;
  /** Why it is unverified, for a citation the host could not anchor; null
      for a host-verified one. */
  unverified: UnverifiedCitationView["code"] | null;
  page: number;
  matched_text: string;
  /** The evidence line the quote anchored in, where the record holds it
      (D105): an excerpt record's `line_text`, or the quote under a whole-line
      rule. Null for a record from before them, whose quote is any run. */
  line: string | null;
}

// The rules under which a quote is its own whole line (`citations.py`).
const WHOLE_LINE_RULES = new Set(["whole-line", "whole-line-as-shown"]);
// The codes an unverified citation may carry (`handoff.UNVERIFIED_CODES`).
const UNVERIFIED_CODES = new Set([
  "CITATION_NOT_LOCATED",
  "CITATION_AMBIGUOUS",
  "CITATION_NOT_DELIVERED",
]);

/** A record's unverified citations as choices, each at its own index. */
function unverifiedOf(routeNodeId: string, entries: unknown): CitationChoice[] {
  if (!Array.isArray(entries)) return [];
  return entries.flatMap((entry: unknown, index) => {
    const { page, matched_text, code } = (entry ?? {}) as Record<string, unknown>;
    if (typeof page !== "number" || !Number.isInteger(page) || typeof matched_text !== "string")
      return [];
    if (typeof code !== "string" || !UNVERIFIED_CODES.has(code)) return [];
    return [
      {
        route_node_id: routeNodeId,
        citation_index: index,
        unverified: code as UnverifiedCitationView["code"],
        page,
        matched_text,
        line: null,
      },
    ];
  });
}

/** Every well-formed citation of every served record, in record order. A
    record the client cannot read offers nothing, and a malformed entry is
    skipped without renumbering the ones after it: `citation_index` is the
    entry's position in the record the server resolves, never a count of what
    this list kept. */
export function citationsOf(artifacts: ReportDocument["body"]["artifacts"]): CitationChoice[] {
  const choices: CitationChoice[] = [];
  for (const artifact of artifacts) {
    let record: unknown;
    try {
      record = JSON.parse(artifact.record);
    } catch {
      continue;
    }
    const { citations, citation_rule, unverified } = (record ?? {}) as Record<string, unknown>;
    if (!Array.isArray(citations)) continue;
    const whole = typeof citation_rule === "string" && WHOLE_LINE_RULES.has(citation_rule);
    citations.forEach((entry: unknown, index) => {
      const { page, matched_text, line_text } = (entry ?? {}) as Record<string, unknown>;
      if (typeof page !== "number" || !Number.isInteger(page) || typeof matched_text !== "string")
        return;
      choices.push({
        route_node_id: artifact.route_node_id,
        citation_index: index,
        unverified: null,
        page,
        matched_text,
        line: typeof line_text === "string" ? line_text : whole ? matched_text : null,
      });
    });
    choices.push(...unverifiedOf(artifact.route_node_id, unverified));
  }
  return choices;
}

/** The draft's marker for one figure (N90): the route node and the citation's
    place in its record, counted from one, in brackets -- `[CP-0 #2]`. It is
    read, not a token, and it names its citation in the text itself, so it
    survives a paste and cannot be re-pointed by anything outside the draft.
    A bare `[1]` (a footnote in pasted prose) names nothing and stays prose,
    for the server to refuse as a digit. It never reaches the server as text:
    `paragraphs` turns each one into a figure span. */
export function figureMarker(
  routeNodeId: string,
  citationIndex: number,
  unverified = false,
): string {
  return `[${routeNodeId} ${unverified ? "unverified " : ""}#${citationIndex + 1}]`;
}

// A figure marker; with "unverified " it names an unverified citation (D106).
const MARKER = /\[([^\s[\]#]+) (unverified )?#([1-9][0-9]{0,5})\]/g;

/** One paragraph per non-empty line; within it, prose spans around one figure
    span per marker. Anything else stays prose -- a bracketed number, a marker
    counted from zero -- so a digit still reaches the server as text and is
    refused there `NARRATIVE_FIGURE_UNREFERENCED`. Whether a marker names a
    citation the records carry is the server's to judge, not this file's. */
export function paragraphs(draft: string): NarrativeDraft[][] {
  return draft
    .split("\n")
    .map((line) => line.trim())
    .filter((line) => line.length > 0)
    .map((line) => {
      const spans: NarrativeDraft[] = [];
      let at = 0;
      for (const match of line.matchAll(MARKER)) {
        if (match.index > at)
          spans.push({ text: line.slice(at, match.index), figure: null, unverified: null });
        const index = Number(match[3]) - 1;
        spans.push(
          match[2]
            ? {
                text: null,
                figure: null,
                unverified: { route_node_id: match[1]!, unverified_index: index },
              }
            : {
                text: null,
                figure: { route_node_id: match[1]!, citation_index: index },
                unverified: null,
              },
        );
        at = match.index + match[0].length;
      }
      if (at < line.length) spans.push({ text: line.slice(at), figure: null, unverified: null });
      return spans;
    });
}

/** How a picker or draft list names a citation (D105): its whole source line
    with the quote set in guillemets where its words run there exactly once,
    whole words only (F504: a substring search would mark "4.1" inside
    "14.1"); the quote labelled as one where the record holds no line; and an
    unverified one labelled so, as the model's quote (D106). */
export function choiceText(choice: CitationChoice): string {
  if (choice.unverified !== null)
    return `${unverifiedLabel({ page: choice.page, code: choice.unverified })}: ${choice.matched_text}`;
  if (choice.line === null) return `quote (source line not recorded): ${choice.matched_text}`;
  const place = wordPlace(choice.line, choice.matched_text);
  if (place === null || choice.line === choice.matched_text) return `source line: ${choice.line}`;
  const [at, end] = place;
  return `source line: ${choice.line.slice(0, at)}«${choice.line.slice(at, end)}»${choice.line.slice(end)}`;
}

/** Where `quote`'s words run as consecutive whole words of `line`, NFC as the
    host compares them: the one place, as `[start, end)` offsets, or null for
    none or more than one, which marks nothing. */
export function wordPlace(line: string, quote: string): [number, number] | null {
  const words = quote
    .split(/\s+/)
    .filter(Boolean)
    .map((word) => word.normalize("NFC"));
  const units = [...line.matchAll(/\S+/g)].map((found) => ({
    start: found.index,
    end: found.index + found[0].length,
    word: found[0].normalize("NFC"),
  }));
  if (words.length === 0) return null;
  const places: [number, number][] = [];
  for (let at = 0; at + words.length <= units.length; at += 1) {
    if (words.every((word, offset) => units[at + offset]!.word === word)) {
      places.push([units[at]!.start, units[at + words.length - 1]!.end]);
    }
  }
  return places.length === 1 ? places[0]! : null;
}

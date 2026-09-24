// What a draft may say about a figure, and what the picker may offer for one.
//
// A figure span names a citation of a verified record by its route node and
// its position in that record's `citations` -- nothing else. The host fills
// the document, the page and the quote from the accepted record at save, and
// refuses a reference it cannot resolve, so nothing here decides whether a
// figure is valid. The picker only offers the citations the served Report
// document's own records carry, at the index the server will read them by.
import type { NarrativeDraft, ReportDocument } from "@/wire/v1";

/** One citation a figure may name, and what the author is shown for it. */
export interface CitationChoice {
  route_node_id: string;
  citation_index: number;
  page: number;
  matched_text: string;
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
    const citations = (record as { citations?: unknown } | null)?.citations;
    if (!Array.isArray(citations)) continue;
    citations.forEach((entry: unknown, index) => {
      const { page, matched_text } = (entry ?? {}) as Record<string, unknown>;
      if (typeof page !== "number" || !Number.isInteger(page) || typeof matched_text !== "string")
        return;
      choices.push({
        route_node_id: artifact.route_node_id,
        citation_index: index,
        page,
        matched_text,
      });
    });
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
export function figureMarker(routeNodeId: string, citationIndex: number): string {
  return `[${routeNodeId} #${citationIndex + 1}]`;
}

const MARKER = /\[([^\s[\]#]+) #([1-9][0-9]{0,5})\]/g;

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
        if (match.index > at) spans.push({ text: line.slice(at, match.index), figure: null });
        spans.push({
          text: null,
          figure: { route_node_id: match[1]!, citation_index: Number(match[2]) - 1 },
        });
        at = match.index + match[0].length;
      }
      if (at < line.length) spans.push({ text: line.slice(at), figure: null });
      return spans;
    });
}

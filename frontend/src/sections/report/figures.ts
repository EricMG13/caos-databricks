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

/** A figure the draft names: which citation of which record. */
export interface FigureRef {
  route_node_id: string;
  citation_index: number;
}

/** The draft's marker for its nth figure, a footnote number the author reads
    (`[1]`) rather than a token (N90). The number is the figure's place in the
    draft's own list, never in the picker's, so a refetch that reorders the
    picker cannot re-point a marker. It never reaches the server as text:
    `paragraphs` turns each one into a figure span. */
export function figureMarker(n: number): string {
  return `[${n}]`;
}

/** The draft's figure list with `ref` in it, and the marker that names it:
    a citation inserted twice is one figure with one number. */
export function withFigure(
  figures: readonly FigureRef[],
  ref: FigureRef,
): { figures: FigureRef[]; marker: string } {
  const at = figures.findIndex(
    (known) =>
      known.route_node_id === ref.route_node_id && known.citation_index === ref.citation_index,
  );
  if (at !== -1) return { figures: [...figures], marker: figureMarker(at + 1) };
  const next = [
    ...figures,
    { route_node_id: ref.route_node_id, citation_index: ref.citation_index },
  ];
  return { figures: next, marker: figureMarker(next.length) };
}

const MARKER = /\[(\d{1,3})\]/g;

/** One paragraph per non-empty line; within it, prose spans around one figure
    span per marker the draft's figure list names. Anything else stays prose,
    a bracketed number typed by hand included, so a digit still reaches the
    server as text and is refused there `NARRATIVE_FIGURE_UNREFERENCED` -- the
    rule is the server's, not this file's. */
export function paragraphs(draft: string, figures: readonly FigureRef[]): NarrativeDraft[][] {
  return draft
    .split("\n")
    .map((line) => line.trim())
    .filter((line) => line.length > 0)
    .map((line) => {
      const spans: NarrativeDraft[] = [];
      let at = 0;
      for (const match of line.matchAll(MARKER)) {
        const figure = figures[Number(match[1]) - 1];
        if (!figure) continue;
        if (match.index > at) spans.push({ text: line.slice(at, match.index), figure: null });
        spans.push({
          text: null,
          figure: { route_node_id: figure.route_node_id, citation_index: figure.citation_index },
        });
        at = match.index + match[0].length;
      }
      if (at < line.length) spans.push({ text: line.slice(at), figure: null });
      return spans;
    });
}

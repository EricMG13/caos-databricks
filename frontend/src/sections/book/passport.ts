// A v1 `CitationView` as the one passport overlay reads it. The overlay's
// `Citation` predates the v1 wire and is the shape `test_passport_contract`
// holds; this is the adapter, and it adds nothing the document does not say.
//
// `bboxes` is `[]` not because the host has no rectangle -- it anchored the
// quote and serves `CitationView.rects` -- but because this overlay predates
// the v1 wire and has no page frame to place a rectangle against. So the chip
// names the document, the page and the quote, and shows no silhouette.
import type { Citation } from "@/wire";
import type { CitationView } from "@/wire/v1";

export function citationOf(fact: CitationView, observedAt: string): Citation {
  return {
    chip: `${fact.filename} p.${fact.page}`,
    document_sha256: fact.document_sha256,
    source_label: fact.filename,
    page: fact.page,
    bboxes: [],
    matched_text: fact.matched_text,
    line: fact.line,
    observed_at: observedAt,
    render_url: null,
    withdrawn_at: fact.withdrawn_at,
    cited_page: fact.cited_page,
    linked: fact.linked,
  };
}

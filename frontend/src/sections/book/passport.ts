// The v1 `BookPassport` as the one passport overlay reads it. The overlay's
// `Passport` predates the v1 wire and is the shape `test_passport_contract`
// holds; this is the adapter, and it adds nothing the document does not say.
//
// Two fields are deliberately empty rather than filled. `bboxes` is `[]` not
// because the host has no rectangle -- it anchored the quote and serves
// `CitationView.rects` -- but because this overlay predates the v1 wire and has
// no page frame to place a rectangle against. The v1 `SourceDrawer` is the one
// that fetches a frame, and it resolves a fact against a document carrying
// `handoffs`, which the Book's does not. So the chip names the document, the
// page and the quote, and shows no silhouette. `deviation` is `null` because
// every column here is one calculator's one spelling, so nothing deviates --
// two spellings sharing a column is the thing that cannot arise, not a thing
// that is unchecked.
import type { Citation, Passport, ResearchLink } from "@/wire";
import type { BookCell, BookColumn, BookRow, CitationView } from "@/wire/v1";
import { displayDecimal, hundredfold } from "@/ds/format";

export function citationOf(fact: CitationView, observedAt: string): Citation {
  return {
    chip: `${fact.filename} p.${fact.page}`,
    document_sha256: fact.document_sha256,
    source_label: fact.filename,
    page: fact.page,
    bboxes: [],
    matched_text: fact.matched_text,
    observed_at: observedAt,
    render_url: null,
    withdrawn_at: fact.withdrawn_at,
  };
}

/** How each unit the column declares reads (N60). A currency figure's
    currency and scale are the row's, stated beside it. */
const SHOWN: Record<BookColumn["unit"], (value: string) => string> = {
  percent: (value) => `${displayDecimal(hundredfold(value), 1)}%`,
  multiple: (value) => `${displayDecimal(value)}x`,
  count: (value) => displayDecimal(value, 0),
  currency: (value) => displayDecimal(value),
  none: (value) => displayDecimal(value),
};

/** What a cell reads: the figure rounded for display in its column's unit,
    or the typed reason the projection has none for it. */
export function shownValue(cell: BookCell, unit: BookColumn["unit"]): string {
  return cell.value === null ? (cell.unavailable_reason ?? "Not served") : SHOWN[unit](cell.value);
}

export function passportOf(
  row: BookRow,
  column: BookColumn,
  cell: BookCell,
  observedAt: string,
): Passport {
  const passport = cell.passport;
  const research: ResearchLink[] = passport.supporting_research.map((link) => ({
    title: link.route_node_id,
    module_id: link.module_id,
    state: link.qa_status,
  }));
  return {
    label: `${row.title} · ${column.label}`,
    value: shownValue(cell, column.unit),
    unit:
      column.unit === "currency" && row.currency && row.scale
        ? `${row.currency} ${row.scale}`
        : null,
    definition: passport.definition,
    period: passport.period,
    scenario: passport.scenario,
    reporting_period: passport.reporting_period,
    computed_at: passport.computed_at,
    snapshot: passport.snapshot,
    method: passport.method,
    derivation: passport.derivation,
    citations: passport.citations.map((fact) => citationOf(fact, observedAt)),
    supporting_research: research,
    driver: null,
    deviation: null,
  };
}

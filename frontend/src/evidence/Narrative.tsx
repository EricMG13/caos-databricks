// A saved narrative as Report and Committee show it (N59): its text is text,
// and each figure is compact (D107): its excerpt clamped to about one line and
// a chip naming its module and marker that opens the source drawer at its
// page, where the whole line is shown with the excerpt marked. A figure
// naming an unverified citation (D106) is labelled so before the model's
// quote, with no chip: there is no located source to open. The figure names
// its record, citation, source and page on the wire, so nothing here looks it
// up elsewhere.
import { clampExcerpt } from "./compact";
import { useEvidence } from "./EvidenceContext";
import { QUOTE_LABEL } from "./TracedLine";
import { NOT_LINKED_SHORT, markerPrefix, unverifiedLabel } from "./Unverified";
import type { ReportDocument } from "@/wire/v1";

/** Report's and Committee's narrative: the same saved shape. */
export function Narrative({ narrative }: { narrative: ReportDocument["body"]["narrative"] }) {
  const { openFact, activeFact } = useEvidence();
  return (
    <>
      {narrative.map((spans, index) => (
        <p key={index} data-narrative-paragraph={index}>
          {spans.map((span, spanIndex) => {
            const figure = span.figure;
            const unverified = span.unverified;
            if (unverified) {
              return (
                <span key={spanIndex} data-unverified-figure={unverified.route_node_id}>
                  <span className="lbl">
                    {unverified.route_node_id} {markerPrefix(unverified.marker)}
                    {unverifiedLabel(unverified)}:{" "}
                  </span>
                  <q className="figq-unverified">{clampExcerpt(unverified.matched_text)}</q>{" "}
                </span>
              );
            }
            if (!figure) return <span key={spanIndex}>{span.text}</span>;
            const open =
              activeFact !== null &&
              activeFact.record_sha256 === figure.record_sha256 &&
              activeFact.index === figure.citation_index;
            return (
              <span key={spanIndex} data-figure={figure.route_node_id}>
                {span.text}
                {figure.line.recorded ? null : (
                  <span className="lbl" data-line-not-recorded>
                    {QUOTE_LABEL}:{" "}
                  </span>
                )}
                <q className="figq">{clampExcerpt(figure.matched_text)}</q>{" "}
                {figure.linked ? null : (
                  <span className="lbl" data-not-linked>
                    ({NOT_LINKED_SHORT}){" "}
                  </span>
                )}
                <button
                  type="button"
                  className="chip"
                  aria-label={`${figure.marker === null ? "Evidence" : `citation ${figure.marker}:`} ${figure.route_node_id} p.${figure.page}${figure.line.recorded ? "" : `, ${QUOTE_LABEL.toLowerCase()}`}`}
                  aria-expanded={open}
                  data-figure-chip={figure.source_id}
                  onClick={(event) =>
                    openFact(
                      {
                        record_sha256: figure.record_sha256,
                        source_id: figure.source_id,
                        page: figure.page,
                        index: figure.citation_index,
                      },
                      event.currentTarget,
                    )
                  }
                >
                  {figure.route_node_id}
                  {figure.marker === null ? "" : ` C${figure.marker}`} · p.{figure.page}
                </button>
              </span>
            );
          })}
        </p>
      ))}
    </>
  );
}

// A saved narrative as Report and Committee show it (N59): its text is text,
// and each figure is the whole line its quote rests on, the quote marked
// (D105), plus a chip that opens the source drawer at its page. The figure names its record, citation, source and page
// on the wire, so nothing here looks it up elsewhere.
import { useEvidence } from "./EvidenceContext";
import { QUOTE_LABEL, TracedLine, lineText } from "./TracedLine";
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
                <q className="figq">
                  <TracedLine line={figure.line} />
                </q>{" "}
                <button
                  type="button"
                  className="chip"
                  aria-label={`Evidence ${figure.route_node_id} p.${figure.page}${figure.line.recorded ? "" : `, ${QUOTE_LABEL.toLowerCase()}`}: ${lineText(figure.line)}`}
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
                  {figure.route_node_id} · p.{figure.page}
                </button>
              </span>
            );
          })}
        </p>
      ))}
    </>
  );
}

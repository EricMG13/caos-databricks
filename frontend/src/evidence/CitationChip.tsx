// The chip shows `D-04 p.68 ¶2`, not a document name. Its click passes the
// opener to the one evidence drawer (IA_SPEC.md 4.3, 5).
import type { MouseEvent } from "react";
import { useEvidence } from "./EvidenceContext";
import type { Citation } from "@/wire";

export function CitationChip({
  citation,
  linked = false,
}: {
  citation: Citation;
  linked?: boolean;
}) {
  const { openCitation, activeChip } = useEvidence();
  const open = activeChip === citation.chip;
  // Invariant 1: a withdrawn source stays cited, so the conclusion stays
  // explicable -- and the chip says it is withdrawn, as shape as well as hue.
  const withdrawn = citation.withdrawn_at ?? null;
  return (
    <button
      type="button"
      className={`chip${linked ? " linked" : ""}${withdrawn ? " withdrawn" : ""}`}
      aria-label={`Evidence ${citation.chip}${withdrawn ? " · source withdrawn" : ""}`}
      title={withdrawn ? `Source withdrawn ${withdrawn}; a read of it now refuses` : undefined}
      aria-expanded={open}
      aria-haspopup="dialog"
      data-chip={citation.chip}
      onClick={(event: MouseEvent<HTMLButtonElement>) =>
        openCitation(citation, event.currentTarget)
      }
    >
      {citation.chip}
    </button>
  );
}

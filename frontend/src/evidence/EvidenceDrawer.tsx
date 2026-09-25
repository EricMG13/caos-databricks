// The one evidence surface: the page render with its rectangle(s), the matched
// text, the observation time. Opened from a chip with its opener passed;
// Escape returns focus to that opener (IA_SPEC.md 5, 7).
import { Digest } from "@/ds/Digest";
import { Overlay } from "./Overlay";
import type { BBox, Citation } from "@/wire";

function rect(box: BBox) {
  const [x, y, w, h] = box;
  return { left: `${x * 100}%`, top: `${y * 100}%`, width: `${w * 100}%`, height: `${h * 100}%` };
}

/** A page silhouette when the host serves no render: lines, not text. */
function PageSilhouette() {
  const lines = Array.from({ length: 22 }, (_, i) => i);
  return (
    <svg viewBox="0 0 400 520" aria-hidden="true" focusable="false">
      <rect width="400" height="520" fill="var(--paper-bg)" />
      {lines.map((i) => (
        <rect
          key={i}
          x="34"
          y={40 + i * 20}
          width={i % 5 === 4 ? 180 : 332}
          height="5"
          rx="1"
          fill={i % 2 ? "var(--paper-line-soft)" : "var(--paper-line)"}
        />
      ))}
    </svg>
  );
}

export function EvidenceDrawer({
  citation,
  opener,
  onClose,
}: {
  citation: Citation;
  opener: HTMLElement | null;
  onClose: () => void;
}) {
  return (
    <Overlay
      look="drawer"
      opener={opener}
      onClose={onClose}
      title={`${citation.source_label} · page ${citation.page}`}
      lead={
        <span className="chip" aria-hidden="true">
          {citation.chip}
        </span>
      }
      data-evidence-drawer
    >
      <div className="db">
        <div className="lbl">Page render · rectangle from the token index</div>
        <div className="pagerender">
          {citation.render_url ? (
            <img
              src={citation.render_url}
              alt={`${citation.source_label}, page ${citation.page}`}
            />
          ) : (
            <PageSilhouette />
          )}
          {citation.bboxes.map((box, i) => (
            <div key={i} className="bbox" style={rect(box)} aria-hidden="true">
              {i === 0 ? <span className="lb">{citation.chip}</span> : null}
            </div>
          ))}
        </div>
        <div className="lbl">Matched text</div>
        <blockquote className="matched" style={{ margin: 0 }}>
          <mark>{citation.matched_text}</mark>
        </blockquote>
        <dl className="kv">
          <dt>Document</dt>
          <dd>
            <Digest value={citation.document_sha256} prefix="sha256:" />
          </dd>
          <dt>Observed</dt>
          <dd>
            <time dateTime={citation.observed_at}>{citation.observed_at}</time>
          </dd>
          <dt>Rectangles</dt>
          <dd>{citation.bboxes.length}</dd>
          {citation.withdrawn_at ? (
            <>
              <dt>Withdrawn</dt>
              <dd data-withdrawn>
                <time dateTime={citation.withdrawn_at}>{citation.withdrawn_at}</time>
              </dd>
            </>
          ) : null}
        </dl>
        {citation.withdrawn_at ? (
          <div className="note limitation">
            <b>This source has been withdrawn.</b> The citation stays so the conclusion that rests
            on it stays explicable; a read of the source now refuses at the boundary.
          </div>
        ) : null}
        <div className="focusnote">
          <b>Escape</b> returns focus to the chip that opened this.
        </div>
      </div>
    </Overlay>
  );
}

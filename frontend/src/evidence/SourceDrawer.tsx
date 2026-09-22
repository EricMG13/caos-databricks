// The evidence drawer for a v1 source fact (brief 4.4, decisions 7-9): the
// page's text layer from the token index with the citation's stored
// rectangles over it, placed by one geometry function. There is no page
// render. A withdrawn source shows its withdrawal and reads no page; a page
// the server refuses shows its state and no text.
import { useEffect, useId, useState } from "react";
import { toFraction, type Box } from "./geometry";
import { OFFLINE_WORDING, UNAVAILABLE_WORDING, fetchPage, type PageStatus } from "@/app/transport";
import { useModalA11y } from "@/ds/use-modal-a11y";
import type { CitationView, PageDocument } from "@/wire/v1";

const place = (box: Box) => ({
  left: `${box.left * 100}%`,
  top: `${box.top * 100}%`,
  width: `${box.width * 100}%`,
  height: `${box.height * 100}%`,
});

function TextLayer({ page, fact }: { page: PageDocument; fact: CitationView }) {
  const { frame, lines } = page.body;
  const width = frame.x1 - frame.x0;
  const height = frame.y1 - frame.y0;
  const highlights = fact.rects.flatMap((rect) => toFraction(rect, frame) ?? []);
  const outside = fact.rects.length - highlights.length;
  return (
    <>
      <div
        className="pagerender"
        style={
          width > 0 && height > 0
            ? { aspectRatio: `${width} / ${height}`, containerType: "inline-size" }
            : undefined
        }
      >
        {lines.map((line, index) => {
          const box = toFraction(line, frame);
          if (box === null) return null;
          return (
            <span
              key={index}
              data-page-line
              style={{
                ...place(box),
                position: "absolute",
                // The line's own height, in the container's width units.
                fontSize: `${box.height * (height / width) * 80}cqw`,
                lineHeight: 1.2,
                whiteSpace: "nowrap",
                overflow: "hidden",
              }}
            >
              {line.text}
            </span>
          );
        })}
        {highlights.map((box, index) => (
          <div key={index} className="bbox" data-highlight aria-hidden="true" style={place(box)} />
        ))}
      </div>
      {outside > 0 ? (
        <div className="note limitation" data-outside-frame>
          {outside} of {fact.rects.length} rectangles lie outside the page frame and are not drawn.
        </div>
      ) : null}
      {page.status === "partial" ? (
        <div className="note" data-page-partial>
          {page.notes.join(", ")}
        </div>
      ) : null}
    </>
  );
}

function PageState({ status }: { status: PageStatus | null }) {
  if (status === null) return <div data-page-state="loading">Reading the page…</div>;
  if (status.kind === "unavailable") {
    return <div data-page-state="unavailable">{UNAVAILABLE_WORDING}</div>;
  }
  if (status.kind === "offline") return <div data-page-state="offline">{OFFLINE_WORDING}</div>;
  if (status.kind === "error") return <div data-page-state="error">{status.refusal.code}</div>;
  return null;
}

export interface PageAddress {
  caseId: string;
  runId: string;
}

export function SourceDrawer({
  fact,
  address,
  withdrawnAt,
  opener,
  onClose,
}: {
  fact: CitationView;
  /** Null when the view names no case or run: no page can be addressed. */
  address: PageAddress | null;
  withdrawnAt: string | null;
  opener: HTMLElement;
  onClose: () => void;
}) {
  const ref = useModalA11y<HTMLDivElement>(onClose, opener);
  // Declared after the modal hook, so its cleanup runs after the opener's
  // restore: an opener that has left the page hands focus to the heading.
  useEffect(
    () => () => {
      if (opener.isConnected) return;
      const heading = document.querySelector<HTMLElement>(".ap h1");
      if (!heading) return;
      if (!heading.hasAttribute("tabindex")) heading.tabIndex = -1;
      heading.focus();
    },
    [opener],
  );
  const titleId = useId();
  // The page read is bound to the address it was asked for; a response under
  // any other address, or for a source withdrawn since, is never shown.
  const pageKey =
    address && withdrawnAt === null
      ? `${address.caseId}|${address.runId}|${fact.source_id}|${fact.page}`
      : null;
  const [page, setPage] = useState<{ key: string; status: PageStatus } | null>(null);
  const caseId = address?.caseId ?? null;
  const runId = address?.runId ?? null;
  useEffect(() => {
    if (pageKey === null || caseId === null || runId === null) return undefined;
    const controller = new AbortController();
    void fetchPage(
      { caseId, runId, sourceId: fact.source_id, page: fact.page },
      controller.signal,
    ).then((status) => {
      if (!controller.signal.aborted) setPage({ key: pageKey, status });
    });
    return () => controller.abort();
  }, [pageKey, caseId, runId, fact.source_id, fact.page]);
  const status = pageKey !== null && page?.key === pageKey ? page.status : null;

  return (
    <>
      <div className="scrim" aria-hidden="true" onClick={onClose} />
      <div
        ref={ref}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        className="drawer"
        data-evidence-drawer
      >
        <div className="dhead">
          <h2 id={titleId}>
            {fact.filename} · page {fact.page}
          </h2>
          <button type="button" className="close focus-ring" onClick={onClose}>
            ESC · CLOSE
          </button>
        </div>
        <div className="db">
          {withdrawnAt !== null ? (
            <div className="note limitation" data-withdrawn>
              <b>This source has been withdrawn</b> at{" "}
              <time dateTime={withdrawnAt}>{withdrawnAt}</time>. The citation stays so the
              conclusion that rests on it stays explicable; its page is no longer read.
            </div>
          ) : pageKey === null ? null : (
            <div data-page-layer>
              <div className="lbl">Text layer from the token index</div>
              {status !== null && "document" in status ? (
                <TextLayer page={status.document} fact={fact} />
              ) : (
                <PageState status={status} />
              )}
            </div>
          )}
          <div className="lbl">Matched text</div>
          <blockquote className="matched" style={{ margin: 0 }}>
            <mark>{fact.matched_text}</mark>
          </blockquote>
          <dl className="kv">
            <dt>Document</dt>
            <dd title={fact.document_sha256}>sha256 {fact.document_sha256.slice(0, 12)}…</dd>
            <dt>Rectangles</dt>
            <dd>{fact.rects.length}</dd>
          </dl>
          <div className="focusnote">
            <b>Escape</b> returns focus to the chip that opened this.
          </div>
        </div>
      </div>
    </>
  );
}

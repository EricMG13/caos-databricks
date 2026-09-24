// The evidence drawer for a v1 source fact (brief 4.4, decisions 7-9): the
// page's text layer from the token index with the citation's stored
// rectangles over it, placed by one geometry function. There is no page
// render. A withdrawn source shows its withdrawal and reads no page; a page
// the server refuses shows its state and no text.
import { useEffect, useState } from "react";
import { toFraction, type Box } from "./geometry";
import { Overlay } from "./Overlay";
import { OFFLINE_WORDING, UNAVAILABLE_WORDING, fetchPage, type PageStatus } from "@/app/transport";
import type { CitationView, PageDocument, PageLine } from "@/wire/v1";

const place = (box: Box) => ({
  left: `${box.left * 100}%`,
  top: `${box.top * 100}%`,
  width: `${box.width * 100}%`,
  height: `${box.height * 100}%`,
});

type HiddenReason = PageLine["hidden"][number];

/** Why a line is not visible on the rendered page, in the reader's words
    (N27), for every reason the wire names. The wire's list is closed: a
    reason the host adds later fails the page read whole (it is refused, not
    shown unmarked) until the wire and this map name it, and the compiler
    asks for its words here the moment the wire does. */
const HIDDEN: Record<HiddenReason, string> = {
  render_mode_3: "drawn invisible (render mode 3)",
  near_background: "the colour of its background",
  under_2pt: "under 2 pt",
  optional_content_off: "on a layer switched off",
  painted_over: "painted over",
  colorant_none: "painted with no ink (colorant None)",
};
const hiddenWords = (reasons: readonly HiddenReason[]) =>
  reasons.map((reason) => HIDDEN[reason]).join(", ");

function TextLayer({ page, fact }: { page: PageDocument; fact: CitationView }) {
  const { frame, lines } = page.body;
  const width = frame.x1 - frame.x0;
  const height = frame.y1 - frame.y0;
  const highlights = fact.rects.flatMap((rect) => toFraction(rect, frame) ?? []);
  const outside = fact.rects.length - highlights.length;
  // Only the lines the layer places: the note says they are outlined above.
  const hidden = lines.filter((line) => line.hidden.length > 0 && toFraction(line, frame) !== null);
  const reasons = [...new Set(hidden.flatMap((line) => line.hidden))];
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
              data-hidden={line.hidden.length ? line.hidden.join(" ") : undefined}
              title={
                line.hidden.length
                  ? `Not visible on the page: ${hiddenWords(line.hidden)}`
                  : undefined
              }
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
              {line.hidden.length ? (
                <span className="sr-only">
                  {" "}
                  (not visible on the page: {hiddenWords(line.hidden)})
                </span>
              ) : null}
            </span>
          );
        })}
        {highlights.map((box, index) => (
          <div key={index} className="bbox" data-highlight aria-hidden="true" style={place(box)} />
        ))}
      </div>
      {hidden.length > 0 ? (
        <div className="note limitation" data-hidden-lines>
          <b>
            {hidden.length === 1 ? "1 line" : `${hidden.length} lines`} on this page cannot be seen
            on the rendered page
          </b>{" "}
          ({hiddenWords(reasons)}).{" "}
          {hidden.length === 1
            ? "It is outlined in dashes above: read it before you rely on this page."
            : "They are outlined in dashes above: read them before you rely on this page."}
        </div>
      ) : null}
      {fact.rects.length === 0 ? (
        <div className="note" data-no-rects>
          No rectangle is stored for this quote, so nothing on the page is highlighted; the quote is
          below.
        </div>
      ) : null}
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

function PageState({ status, saved }: { status: PageStatus | null; saved: boolean }) {
  if (status === null) return <div data-page-state="loading">Reading the page…</div>;
  if (status.kind === "unavailable") {
    return (
      <div data-page-state="unavailable">
        {UNAVAILABLE_WORDING}
        {saved
          ? // A saved narrative's figure carries no withdrawal of its own (the
            // wire does not serve one), and the host no longer reads a
            // withdrawn source's pages: say which that may be.
            " Its source may have been withdrawn since this revision was saved."
          : null}
      </div>
    );
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
  saved = false,
  opener,
  onClose,
}: {
  fact: CitationView;
  /** Null when the view names no case or run: no page can be addressed. */
  address: PageAddress | null;
  withdrawnAt: string | null;
  /** A saved narrative's figure (N59), whose withdrawal the wire does not serve. */
  saved?: boolean;
  opener: HTMLElement;
  onClose: () => void;
}) {
  // The overlay returns focus to an opener still on the page and does nothing
  // for one that has left it; this hands focus to the heading instead.
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
    <Overlay
      look="drawer"
      opener={opener}
      onClose={onClose}
      title={`${fact.filename} · page ${fact.page}`}
      data-evidence-drawer
    >
      <div className="db">
        {withdrawnAt !== null ? (
          <div className="note limitation" data-withdrawn>
            <b>This source has been withdrawn</b> at{" "}
            <time dateTime={withdrawnAt}>{withdrawnAt}</time>. The citation stays so the conclusion
            that rests on it stays explicable; its page is no longer read.
          </div>
        ) : pageKey === null ? null : (
          <div data-page-layer>
            <div className="lbl">Text layer from the token index</div>
            {status !== null && "document" in status ? (
              // The read is bound to case, run, source and page; the page must
              // also be of the document the citation names, or it is not shown.
              status.document.body.document_sha256 === fact.document_sha256 ? (
                <TextLayer page={status.document} fact={fact} />
              ) : (
                <div data-page-state="error">WIRE_IDENTITY_MISMATCH</div>
              )
            ) : (
              <PageState status={status} saved={saved} />
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
    </Overlay>
  );
}

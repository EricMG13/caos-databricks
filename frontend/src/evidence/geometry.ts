// Page geometry (brief 4.4, decision 8). The page read sends a frame in the
// coordinates its rectangles were stored in: a `caos.pdfminer` v2 or plain-text
// page is y down from its crop, a v1 page is pdfminer's layout space, y up.
// One pure function places both the text lines and the citation rectangles,
// so a highlight and the words it covers can never disagree about the page.
import type { FrameView } from "@/wire/v1";

export interface Rect {
  readonly x0: number;
  readonly y0: number;
  readonly x1: number;
  readonly y1: number;
}

/** A placement as fractions of the frame, measured from its top-left corner. */
export interface Box {
  readonly left: number;
  readonly top: number;
  readonly width: number;
  readonly height: number;
}

/** The rectangle as fractions of its frame, or null when it cannot be placed:
    a non-finite coordinate, an empty frame, an inverted rectangle, or one not
    wholly inside the frame. Nothing is clipped -- a clipped highlight would
    claim a region the stored rectangle does not. */
export function toFraction(rect: Rect, frame: FrameView): Box | null {
  const values = [rect.x0, rect.y0, rect.x1, rect.y1, frame.x0, frame.y0, frame.x1, frame.y1];
  if (!values.every(Number.isFinite)) return null;
  const width = frame.x1 - frame.x0;
  const height = frame.y1 - frame.y0;
  if (!(width > 0 && height > 0)) return null;
  if (rect.x0 > rect.x1 || rect.y0 > rect.y1) return null;
  if (rect.x0 < frame.x0 || rect.x1 > frame.x1 || rect.y0 < frame.y0 || rect.y1 > frame.y1) {
    return null;
  }
  const top = frame.y_axis === "down" ? rect.y0 - frame.y0 : frame.y1 - rect.y1;
  return {
    left: (rect.x0 - frame.x0) / width,
    top: top / height,
    width: (rect.x1 - rect.x0) / width,
    height: (rect.y1 - rect.y0) / height,
  };
}

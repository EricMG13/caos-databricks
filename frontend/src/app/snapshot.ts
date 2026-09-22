// The visible snapshot (brief 4.4, decisions 6 and 9): the document the user
// is actually looking at, which a stale view keeps while a newer one waits for
// Reload. The evidence drawer re-resolves its citation against this, never
// against the pending document. Interface only; slice 4.4d provides it.
import { createContext, useContext } from "react";
import type { SectionDocument } from "@/wire/v1";

export interface VisibleSnapshot {
  /** `${section}|${case}|${displayedRunId}`: what the view is mounted under. */
  readonly key: string;
  readonly caseId: string | null;
  readonly displayedRunId: string | null;
  /** The displayed document, not a pending one. */
  readonly document: SectionDocument;
  /** Live withdrawals by `source_id` (withdrawn_at), applied even to a stale view. */
  readonly withdrawals: ReadonlyMap<string, string>;
}

/** No provider means no snapshot: a consumer must render nothing it cannot bind. */
export const VisibleSnapshotContext = createContext<VisibleSnapshot | null>(null);

export function useVisibleSnapshot(): VisibleSnapshot | null {
  return useContext(VisibleSnapshotContext);
}

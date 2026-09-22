// One region, eight ways: the seven states of IA_SPEC.md 6 rendered distinctly,
// and `ready`, which renders its children with no marker of its own.
import type { ReactNode } from "react";
import { UNAVAILABLE_WORDING, type RegionStatus } from "@/app/transport";
import { SurfaceState } from "@/ds/SurfaceState";

export function RegionState<D>({
  status,
  children,
  onReload,
}: {
  status: RegionStatus<D>;
  children: (document: D) => ReactNode;
  onReload?: () => void;
}) {
  switch (status.kind) {
    case "ready":
      return <>{children(status.document)}</>;
    case "loading":
      return <SurfaceState kind="loading" />;
    case "observed-empty":
      return (
        <>
          <SurfaceState
            kind="observed-empty"
            detail={
              <>
                Observed at{" "}
                <time className="ts" dateTime={status.observed_at}>
                  {status.observed_at}
                </time>
                . Nothing is inferred from silence.
              </>
            }
          />
          {children(status.document)}
        </>
      );
    case "unavailable":
      return <SurfaceState kind="unavailable" title={UNAVAILABLE_WORDING} />;
    case "offline":
      // The one sentence lives in the page-level alert; the region carries the marker.
      return <SurfaceState kind="offline" />;
    case "error":
      return (
        <SurfaceState
          kind="error"
          title={status.refusal.code}
          detail={<>Clears when {status.refusal.clears}</>}
        />
      );
    case "stale":
      return (
        <>
          <SurfaceState
            kind="stale"
            detail="The authority changed underneath this view. The lens moves only through an explicit reload."
            supporting={
              onReload ? (
                <button type="button" className="rb acc" onClick={onReload}>
                  RELOAD
                </button>
              ) : null
            }
          />
          {children(status.document)}
        </>
      );
    case "partial":
      return (
        <>
          <SurfaceState
            kind="partial"
            detail={
              status.notes.length ? (
                <>
                  {status.notes.map((note) => (
                    <span key={note} className="block">
                      {note}
                    </span>
                  ))}
                </>
              ) : (
                "Rendered with warning status."
              )
            }
          />
          {children(status.document)}
        </>
      );
  }
}

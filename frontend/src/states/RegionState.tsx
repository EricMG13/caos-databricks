// One region, nine ways: the seven states of IA_SPEC.md 6 rendered distinctly,
// `choose`, which says what the reader must pick and where, and `ready`, which
// renders its children with no marker of its own.
import type { ReactNode } from "react";
import { Link } from "react-router";
import { UNAVAILABLE_WORDING, type RegionStatus, type SelectionNeed } from "@/app/transport";
import { Button, buttonVariants } from "@/components/ui/button";
import { refusalText } from "@/controls/RefusedControl";
import type { Refusal } from "@/wire";
import { SurfaceState } from "@/ds/SurfaceState";

const CHOICES: Record<SelectionNeed, { title: string; detail: string; link: string }> = {
  run: {
    title: "Choose a run",
    detail: "Report and Committee each read one run of this case. Run lists them.",
    link: "Open Run",
  },
  revision: {
    title: "Choose a frozen revision",
    detail:
      "Committee reads a revision once it is frozen. Report lists this run's revisions and how far each has gone.",
    link: "Open Report",
  },
};

/** What a refused or unreadable section read means, in the reader's terms;
    the code stays beside it for anyone who needs to quote it. */
const REGION_PLAIN: Record<string, string> = {
  STORE_UNAVAILABLE: "The store did not answer.",
  RESPONSE_INVALID: "The server's answer could not be read.",
  WIRE_SHAPE_INVALID: "The server's answer could not be read.",
  WIRE_IDENTITY_MISMATCH: "The answer was about a different case or run.",
  RENDER_FAILED: "This section could not be drawn.",
  VIEW_NOT_LOADED: "This part of the workspace did not load.",
};

export function regionSentence(refusal: Refusal): string {
  return REGION_PLAIN[refusal.code] ?? "This section could not be read.";
}

/** Sends the section's read again, for a state that says nothing arrived. */
function RetryButton({ onRetry }: { onRetry: () => void }) {
  return (
    <Button type="button" variant="outline" size="sm" onClick={onRetry}>
      Try again
    </Button>
  );
}

export function RegionState<D>({
  status,
  children,
  onReload,
  onRetry,
}: {
  status: RegionStatus<D>;
  children: (document: D) => ReactNode;
  onReload?: () => void;
  onRetry?: () => void;
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
      // The one sentence lives in the page-level alert; the region carries the
      // marker and the way to ask again.
      return (
        <SurfaceState
          kind="offline"
          supporting={onRetry ? <RetryButton onRetry={onRetry} /> : null}
        />
      );
    case "error":
      return (
        <SurfaceState
          kind="error"
          title={regionSentence(status.refusal)}
          detail={
            <>
              {refusalText(status.refusal)} <code>{status.refusal.code}</code>
            </>
          }
          supporting={
            onRetry ? (
              <RetryButton onRetry={onRetry} />
            ) : onReload ? (
              <Button type="button" size="sm" onClick={onReload}>
                Reload the page
              </Button>
            ) : null
          }
        />
      );
    case "choose": {
      const choice = CHOICES[status.need];
      return (
        <SurfaceState
          kind="choose"
          title={choice.title}
          detail={choice.detail}
          supporting={
            <Link className={buttonVariants({ size: "sm" })} to={status.href}>
              {choice.link}
            </Link>
          }
        />
      );
    }
    case "stale":
      return (
        <>
          <SurfaceState
            kind="stale"
            detail="The authority changed underneath this view. The lens moves only through an explicit reload."
            supporting={
              onReload ? (
                <Button type="button" size="sm" onClick={onReload}>
                  Reload
                </Button>
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

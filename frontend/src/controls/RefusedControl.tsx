// Every governed action renders visible and, when refused, refused with its
// typed code and what clears it. aria-disabled, never disabled, never hidden
// (IA_SPEC.md 2; DESIGN.md "Rules with teeth").
import type { ReactNode } from "react";
import { ActionReason } from "@/ds/ActionReason";
import type { Refusal } from "@/wire";

/** A governed action this section's own document does not name is refused,
    not simulated.

    The clearance says what is actually missing. Until Task 12.1 that was the
    route: the store calls existed and no HTTP path reached them. Every v1
    command has one now, so an unplaced control no longer means "nothing
    performs it" -- it means the section it is drawn in composes its
    `chrome.actions` from a read that judges no such action, and until one
    does, pressing it could only guess. */
export const ACTION_UNPLACED: Refusal = {
  code: "ACTION_UNPLACED",
  clears:
    "this section's own document names it in chrome.actions, which needs a read that can judge it",
};

export function refusalText(refusal: Refusal): string {
  return `${refusal.code} — clears when ${refusal.clears}`;
}

export function RefusedControl({
  refusal,
  onClick,
  className = "",
  reasonDisplay = "inline",
  busy = false,
  children,
  ...rest
}: {
  refusal: Refusal | null;
  onClick?: () => void;
  className?: string;
  reasonDisplay?: "inline" | "hidden";
  /** A command this control sent has not answered yet. */
  busy?: boolean;
  children: ReactNode;
  "aria-label"?: string;
}) {
  const effective = refusal ?? (onClick ? null : ACTION_UNPLACED);
  return (
    <ActionReason
      reason={effective ? refusalText(effective) : null}
      reasonDisplay={reasonDisplay}
      busy={busy}
      onClick={onClick}
      className={`${className}${effective ? " refused" : ""}`}
      data-refusal={effective?.code}
      {...rest}
    >
      {children}
    </ActionReason>
  );
}

/** The refusal on its own, for a ladder step or a panel foot. */
export function RefusalNote({ refusal }: { refusal: Refusal }) {
  return (
    <div className="refusal" data-refusal={refusal.code}>
      <code>{refusal.code}</code>
      <div className="cl">
        Clears when <b>{refusal.clears}</b>
      </div>
    </div>
  );
}

// Every governed action renders visible and, when refused, refused with its
// typed code and what clears it. aria-disabled, never disabled, never hidden
// (IA_SPEC.md 2; DESIGN.md "Rules with teeth").
import type { ReactNode } from "react";
import { ActionReason, type ControlLook } from "@/ds/ActionReason";
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

/** What a refusal means in the reader's terms, where its own `clears` is
    written for the workspace rather than for them (critique P1). */
const PLAIN: Record<string, string> = {
  ACTION_UNPLACED: "Not offered on this page yet.",
  ASK_UNPLACED: "Ask is not part of this workspace yet.",
  SIGN_OUT_UNPLACED: "Sign out through your organisation's sign-in page.",
  VIEW_UNPLACED: "This section has no such view.",
  GATE_PREVIEW_NOT_READ: "Read the preview before approving.",
  COMMAND_EXPECTATION_STALE: "Preview again: the run changed since you looked.",
  CAPABILITY_UNAVAILABLE: "Not available in this deployment.",
};

/** One plain sentence: the curated one, else the server's own instruction
    (written as one: "Sign in."), else what the workspace waits on. The code
    is never in it; it travels in `refusalDetail`. */
export function refusalText(refusal: Refusal): string {
  const plain = PLAIN[refusal.code];
  if (plain) return plain;
  const clears = refusal.clears.trim();
  const first = clears.charAt(0);
  if (first !== first.toLowerCase()) return clears;
  return `Available once ${clears.replace(/[.]$/, "")}.`;
}

/** The fuller account a pointer or a support request needs: the typed code
    and exactly what clears it. */
export function refusalDetail(refusal: Refusal): string {
  return `${refusal.code} — clears when ${refusal.clears}`;
}

export function RefusedControl({
  refusal,
  onClick,
  className = "",
  reasonDisplay = "inline",
  busy = false,
  variant,
  size,
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
} & ControlLook) {
  const effective = refusal ?? (onClick ? null : ACTION_UNPLACED);
  return (
    <ActionReason
      reason={effective ? refusalText(effective) : null}
      reasonTitle={effective ? refusalDetail(effective) : undefined}
      reasonDisplay={reasonDisplay}
      busy={busy}
      onClick={onClick}
      variant={variant}
      size={size}
      className={className}
      data-refusal={effective?.code}
      {...rest}
    >
      {children}
    </ActionReason>
  );
}

/** The refusal on its own, for a ladder step or a panel foot: the plain
    sentence first, the code after it for anyone who needs to quote it. */
export function RefusalNote({ refusal }: { refusal: Refusal }) {
  return (
    <div className="refusal" data-refusal={refusal.code} title={refusalDetail(refusal)}>
      <span className="cl">{refusalText(refusal)}</span> <code>{refusal.code}</code>
    </div>
  );
}

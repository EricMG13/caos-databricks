// The desk convention for "this action exists but can't fire yet": the control
// stays focusable (aria-disabled, never the native disabled attribute), the
// click is guarded, and the *why* is announced three ways — title for pointer
// hover, aria-describedby for assistive tech, and (by default) a visible
// adjacent reason line for sighted keyboard/touch users, who a title alone
// never reaches. The reason text must never enter the button's accessible
// name: name-based queries and muscle memory both depend on the label staying
// stable whether or not the action is currently available.

import {
  useEffect,
  useId,
  useRef,
  useState,
  type ButtonHTMLAttributes,
  type CSSProperties,
  type ReactNode,
} from "react";

interface ActionReasonProps extends Omit<
  ButtonHTMLAttributes<HTMLButtonElement>,
  "onClick" | "title" | "aria-disabled" | "aria-describedby"
> {
  /** Non-empty → the action is inert and this explains why. Null/undefined → live. */
  reason?: string | null;
  /** Pointer explanation for a live action. An inert reason always takes precedence. */
  actionTitle?: string;
  /** "inline" renders the visible reason line; "hidden" keeps it sr-only for
   * tight toolbars where title + screen-reader coverage must suffice. */
  reasonDisplay?: "inline" | "hidden";
  onClick?: () => void;
  children: ReactNode;
}

const FLASH_MS = 4000;
const FLASH_MAX_WIDTH = 280;

const flashPosition = (button: HTMLButtonElement | null): CSSProperties => {
  const rect = button?.getBoundingClientRect();
  return rect
    ? {
        position: "fixed",
        top: rect.bottom + 6,
        left: Math.max(8, rect.right - FLASH_MAX_WIDTH),
        maxWidth: FLASH_MAX_WIDTH,
      }
    : {};
};

const useReasonFlash = (reasonDisplay: "inline" | "hidden") => {
  const buttonRef = useRef<HTMLButtonElement | null>(null);
  const [flashPos, setFlashPos] = useState<CSSProperties | null>(null);
  const flashTimer = useRef<number | null>(null);
  useEffect(
    () => () => {
      if (flashTimer.current !== null) window.clearTimeout(flashTimer.current);
    },
    [],
  );
  const reveal = () => {
    if (reasonDisplay !== "hidden") return;
    setFlashPos(flashPosition(buttonRef.current));
    if (flashTimer.current !== null) window.clearTimeout(flashTimer.current);
    flashTimer.current = window.setTimeout(() => setFlashPos(null), FLASH_MS);
  };
  return { buttonRef, flashPos, reveal };
};

function ActionReasonMessage({
  inert,
  reasonId,
  reason,
  flashPos,
  reasonDisplay,
}: {
  inert: boolean;
  reasonId: string;
  reason?: string | null;
  flashPos: CSSProperties | null;
  reasonDisplay: "inline" | "hidden";
}) {
  if (!inert) return null;
  const flash = flashPos !== null;
  const showInline = reasonDisplay === "inline" || flash;
  return (
    <span
      id={reasonId}
      role={flash ? "status" : undefined}
      className={
        showInline ? `caos-action-reason${flash ? " caos-action-reason-pop" : ""}` : "sr-only"
      }
      style={flash ? (flashPos ?? undefined) : undefined}
    >
      {reason}
    </span>
  );
}

export function ActionReason({
  reason,
  actionTitle,
  reasonDisplay = "inline",
  onClick,
  children,
  type = "button",
  ...rest
}: ActionReasonProps) {
  const reasonId = useId();
  const inert = Boolean(reason);
  const { buttonRef, flashPos, reveal } = useReasonFlash(reasonDisplay);
  // A guarded click must never look ignored: in the "hidden" variant the
  // reason surfaces for a few seconds after the attempt (announced via
  // role=status).
  const handleClick = inert ? reveal : onClick;
  return (
    <>
      <button
        ref={buttonRef}
        type={type}
        aria-disabled={inert || undefined}
        title={reason || actionTitle || undefined}
        aria-describedby={inert ? reasonId : undefined}
        onClick={handleClick}
        {...rest}
      >
        {children}
      </button>
      <ActionReasonMessage
        inert={inert}
        reasonId={reasonId}
        reason={reason}
        flashPos={flashPos}
        reasonDisplay={reasonDisplay}
      />
    </>
  );
}

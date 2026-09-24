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
import type { VariantProps } from "class-variance-authority";
import { Button, type buttonVariants } from "@/components/ui/button";

/** A control's weight: shadcn's button variants and sizes (D35). */
export type ControlLook = VariantProps<typeof buttonVariants>;

interface ActionReasonProps
  extends
    Omit<
      ButtonHTMLAttributes<HTMLButtonElement>,
      "onClick" | "title" | "aria-disabled" | "aria-describedby" | "aria-busy"
    >,
    ControlLook {
  /** Non-empty → the action is inert and this explains why. Null/undefined → live. */
  reason?: string | null;
  /** The pointer's fuller detail for an inert action (the refusal code and what
   * clears it); the reason stays what is shown and announced. */
  reasonTitle?: string;
  /** Pointer explanation for a live action. An inert reason always takes precedence. */
  actionTitle?: string;
  /** "inline" renders the visible reason line; "hidden" keeps it sr-only for
   * tight toolbars where title + screen-reader coverage must suffice. */
  reasonDisplay?: "inline" | "hidden";
  /** A request this control started is still in flight: the control is inert
   * until it answers, and says so rather than looking idle. */
  busy?: boolean;
  onClick?: () => void;
  children: ReactNode;
}

const FLASH_MS = 4000;
const FLASH_MAX_WIDTH = 280;

/** Room a flashed reason needs below its control; with less (the sidebar's
    foot sits on the viewport's edge) it opens above instead. */
const FLASH_ROOM = 48;

const flashPosition = (button: HTMLButtonElement | null): CSSProperties => {
  const rect = button?.getBoundingClientRect();
  if (!rect) return {};
  const left = Math.max(8, rect.right - FLASH_MAX_WIDTH);
  return window.innerHeight - rect.bottom < FLASH_ROOM
    ? {
        position: "fixed",
        bottom: window.innerHeight - rect.top + 6,
        left,
        maxWidth: FLASH_MAX_WIDTH,
      }
    : { position: "fixed", top: rect.bottom + 6, left, maxWidth: FLASH_MAX_WIDTH };
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
        showInline
          ? flash
            ? "z-50 rounded-md bg-foreground px-3 py-1.5 text-xs text-background shadow-md"
            : "mt-1 block basis-full text-xs text-muted-foreground"
          : "sr-only"
      }
      style={flash ? (flashPos ?? undefined) : undefined}
    >
      {reason}
    </span>
  );
}

export function ActionReason({
  reason,
  reasonTitle,
  actionTitle,
  reasonDisplay = "inline",
  busy = false,
  onClick,
  children,
  type = "button",
  variant = "outline",
  size = "sm",
  ...rest
}: ActionReasonProps) {
  const reasonId = useId();
  const inert = Boolean(reason);
  const { buttonRef, flashPos, reveal } = useReasonFlash(reasonDisplay);
  // A guarded click must never look ignored: in the "hidden" variant the
  // reason surfaces for a few seconds after the attempt (announced via
  // role=status).
  const handleClick = inert ? reveal : onClick;
  // While a request is in flight the visible text is the state ("Creating…"),
  // so a fixed aria-label would override the one thing that changed. The
  // label returns with the idle text.
  const { "aria-label": label, ...attributes } = rest;
  return (
    <>
      <Button
        ref={buttonRef}
        variant={variant}
        size={size}
        type={type}
        aria-disabled={inert || busy || undefined}
        aria-busy={busy || undefined}
        aria-label={busy ? undefined : label}
        title={(reason && (reasonTitle || reason)) || actionTitle || undefined}
        aria-describedby={inert ? reasonId : undefined}
        onClick={busy ? undefined : handleClick}
        {...attributes}
      >
        {children}
      </Button>
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

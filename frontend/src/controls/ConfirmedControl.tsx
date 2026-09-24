// An act the v1 wire offers no way back from asks once more before it is sent
// (WCAG 3.3.4, finding FE-7): sign, freeze, file, withdraw, revoke and cancel.
// The second step is inline rather than a dialog -- it is the same panel, the
// same reading order, and it names what the press would bind: the act, the
// thing it acts on and the short form of the digest the server will compare.
// Confirm takes focus when the step opens; Cancel and Escape put it back on
// the control that opened it (IA_SPEC.md 7, the opener rule).
import {
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  type KeyboardEvent,
  type ReactNode,
} from "react";
import { RefusedControl } from "./RefusedControl";
import { focusSectionHeading } from "@/app/heading";
import { Button } from "@/components/ui/button";
import type { ControlLook } from "@/ds/ActionReason";
import { shortDigest } from "@/ds/format";
import type { Refusal } from "@/wire";

/** What the second step names. `digest` is the payload the act binds, shown
    in its short form; null where the act binds none. */
export interface ConfirmStep {
  act: string;
  subject: string;
  digest: string | null;
}

export function confirmSentence(step: ConfirmStep): string {
  const digest = step.digest === null ? "" : ` · sha256:${shortDigest(step.digest)}`;
  return `${step.act} — ${step.subject}${digest}. This cannot be undone.`;
}

/** Focus for a reader whose control has just left the page: the heading of
    the nearest panel or group around it that is still there, else the
    section's own. `around` is the control's ancestors, nearest first, read
    before it went. */
function landNear(around: readonly HTMLElement[]): void {
  const survivor = around.find((element) => element.isConnected);
  const heading = survivor
    ?.closest<HTMLElement>("[role='group'], section")
    ?.querySelector<HTMLElement>("h2, h3");
  if (!heading) {
    focusSectionHeading();
    return;
  }
  if (!heading.hasAttribute("tabindex")) heading.tabIndex = -1;
  heading.focus();
}

export function ConfirmedControl({
  action,
  refusal,
  busy,
  step,
  onConfirm,
  className = "",
  reasonDisplay = "inline",
  variant,
  size,
  children,
  ...rest
}: ControlLook & {
  /** The command's name, on the control and on its confirm step, so both
      halves of one act are found the same way. */
  action: string;
  refusal: Refusal | null;
  busy: boolean;
  step: ConfirmStep;
  /** Undefined where this section's document names no such action at all:
      the control is then `ACTION_UNPLACED`, as it is without a confirm step. */
  onConfirm: (() => void) | undefined;
  className?: string;
  /** "hidden" where a list states one shared refusal once, above its rows. */
  reasonDisplay?: "inline" | "hidden";
  children: ReactNode;
  "aria-label"?: string;
}) {
  const [armed, setArmed] = useState(false);
  const holder = useRef<HTMLDivElement>(null);
  const confirm = useRef<HTMLButtonElement>(null);
  const wasArmed = useRef(false);
  useEffect(() => {
    if (armed) confirm.current?.focus();
    else if (wasArmed.current) {
      holder.current?.querySelector<HTMLElement>("[data-confirm-open]")?.focus();
    }
    wasArmed.current = armed;
  }, [armed]);
  // An act whose success the re-read answers by taking this control away --
  // a withdrawn source's row offers no second withdrawal, a revoked member's
  // row is gone -- leaves focus on a node no longer in the document, and the
  // browser drops it to <body>: the reader starts again at the top of the
  // page (WCAG 2.4.3, DF-7). A layout cleanup runs while the node is still
  // attached, so it can tell whether focus was in here; where focus lands is
  // decided once the commit that removed it is done.
  useLayoutEffect(() => {
    const node = holder.current;
    return () => {
      if (!node?.contains(document.activeElement)) return;
      const around: HTMLElement[] = [];
      for (let at = node.parentElement; at; at = at.parentElement) around.push(at);
      queueMicrotask(() => {
        const active = document.activeElement;
        if (active === null || active === document.body) landNear(around);
      });
    };
  }, []);
  // Escape is handled on the step's own buttons, which are where focus is put
  // when it opens: a listener on the wrapper would be a keyboard handler on a
  // div, which is the shape the workspace does not write.
  const escape = (event: KeyboardEvent<HTMLButtonElement>) => {
    if (event.key !== "Escape") return;
    event.stopPropagation();
    setArmed(false);
  };
  return (
    <div className="confirm" ref={holder}>
      {armed ? (
        <div
          className="note warn"
          role="group"
          aria-label={`Confirm ${step.act}`}
          data-confirm={action}
        >
          <p data-confirm-sentence>{confirmSentence(step)}</p>
          <div className="mt-2 flex flex-wrap gap-2">
            <Button
              type="button"
              ref={confirm}
              variant="destructive"
              size="sm"
              data-confirm-yes
              onKeyDown={escape}
              onClick={() => {
                setArmed(false);
                onConfirm?.();
              }}
            >
              Confirm {step.act}
            </Button>
            <Button
              type="button"
              variant="outline"
              size="sm"
              data-confirm-no
              onKeyDown={escape}
              onClick={() => setArmed(false)}
            >
              Go back
            </Button>
          </div>
        </div>
      ) : (
        <RefusedControl
          refusal={refusal}
          busy={busy}
          className={className}
          variant={variant}
          size={size}
          reasonDisplay={reasonDisplay}
          data-action={action}
          data-confirm-open=""
          onClick={onConfirm ? () => setArmed(true) : undefined}
          {...rest}
        >
          {children}
        </RefusedControl>
      )}
    </div>
  );
}

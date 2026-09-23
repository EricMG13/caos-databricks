// An act the v1 wire offers no way back from asks once more before it is sent
// (WCAG 3.3.4, finding FE-7): sign, freeze, file, withdraw, revoke and cancel.
// The second step is inline rather than a dialog -- it is the same panel, the
// same reading order, and it names what the press would bind: the act, the
// thing it acts on and the short form of the digest the server will compare.
// Confirm takes focus when the step opens; Cancel and Escape put it back on
// the control that opened it (IA_SPEC.md 7, the opener rule).
import { useEffect, useRef, useState, type KeyboardEvent, type ReactNode } from "react";
import { RefusedControl } from "./RefusedControl";
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

export function ConfirmedControl({
  action,
  refusal,
  busy,
  step,
  onConfirm,
  className = "",
  children,
  ...rest
}: {
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
          <button
            type="button"
            ref={confirm}
            className="rb crit"
            data-confirm-yes
            onKeyDown={escape}
            onClick={() => {
              setArmed(false);
              onConfirm?.();
            }}
          >
            Confirm {step.act}
          </button>
          <button
            type="button"
            className="rb"
            data-confirm-no
            onKeyDown={escape}
            onClick={() => setArmed(false)}
          >
            Cancel
          </button>
        </div>
      ) : (
        <RefusedControl
          refusal={refusal}
          busy={busy}
          className={className}
          reasonDisplay="inline"
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

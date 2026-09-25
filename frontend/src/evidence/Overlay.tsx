// The one overlay the evidence surfaces share (N64): the evidence drawer and
// the source drawer as a side sheet, the metric passport as a dialog. Base
// UI's Dialog owns the modal behaviour -- the focus trap, Escape and an
// outside press closing only the topmost of nested overlays, the scroll lock,
// and the page behind made inert. What it is told here is where focus goes on
// close: the opener the caller passed, never one inferred from where focus
// happened to be (WebKit does not focus a clicked button), and only while
// that opener is still on the page (FE-4); otherwise nothing,
// and the caller's own fallback places it.
import { useState, type ReactNode } from "react";
import { Dialog } from "@base-ui/react/dialog";
import { Button } from "@/components/ui/button";

export function Overlay({
  look,
  opener,
  onClose,
  title,
  lead,
  children,
  ...data
}: {
  look: "drawer" | "modal";
  opener: HTMLElement | null;
  onClose: () => void;
  title: ReactNode;
  /** Drawn before the title in the head: the evidence drawer's chip. */
  lead?: ReactNode;
  children: ReactNode;
} & { [attribute: `data-${string}`]: string | boolean | undefined }) {
  // Closed here first, and the owner told only once the close has finished:
  // unmounted mid-close, the dialog would hand focus to whatever held it
  // before, not to the opener, and skip its exit.
  const [open, setOpen] = useState(true);
  return (
    <Dialog.Root
      open={open}
      onOpenChange={(next) => {
        if (!next) setOpen(false);
      }}
      onOpenChangeComplete={(next) => {
        if (!next) onClose();
      }}
    >
      <Dialog.Portal>
        <Dialog.Backdrop className="scrim" />
        <Dialog.Popup
          className={look}
          // Base UI makes the page behind inert; a screen reader is also told
          // the dialog is modal, which is what it is.
          aria-modal="true"
          finalFocus={() => (opener?.isConnected ? opener : false)}
          {...data}
        >
          <div className="dhead">
            {lead}
            <Dialog.Title>{title}</Dialog.Title>
            <Dialog.Close
              render={<Button type="button" variant="ghost" size="sm" className="ml-auto" />}
            >
              Close
              <kbd className="rounded border px-1 font-mono text-[11px] text-muted-foreground">
                Esc
              </kbd>
            </Dialog.Close>
          </div>
          {children}
        </Dialog.Popup>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

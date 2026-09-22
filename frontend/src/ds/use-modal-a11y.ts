import { useEffect, useRef } from "react";

// Body scroll-lock is refcounted across all open overlays, not saved/restored
// per-modal: lock on first open, and on the last close clear the inline style
// outright rather than restore a captured one.
// ponytail: module-global counter — fine for one window; a portal/iframe multi-
// document app would need per-document state.
let scrollLockCount = 0;

// Shared topmost-overlay registry. Every useModalA11y instance registers a
// window-level keydown listener, and stopPropagation() on a window listener
// does not stop OTHER listeners on the same target. Each instance pushes a
// token on mount, pops it on unmount, and only the topmost (most recently
// opened) instance's Escape handler actually calls onClose.
const overlayStack: symbol[] = [];
function isTopOverlay(token: symbol): boolean {
  return overlayStack[overlayStack.length - 1] === token;
}

// Modal behavior in one place:
//   • Escape closes (topmost overlay only).
//   • Focus trap — Tab cycles within the dialog.
//   • Focus restore — returns focus to the opener that was passed in. The
//     opener is never inferred from document.activeElement: WebKit does not
//     focus a button on click, and an inferred opener drops focus to the
//     landmark on cancel (IA_SPEC.md 7).
//   • Body scroll-lock while open.
// Attach the returned ref to the dialog panel and pair it with
// role="dialog" aria-modal="true".
export function useModalA11y<T extends HTMLElement = HTMLDivElement>(
  onClose: () => void,
  opener: HTMLElement | null,
) {
  const ref = useRef<T>(null);
  // Keep the latest onClose in a ref so the setup effect runs exactly once (on
  // mount) yet always calls the current handler.
  const onCloseRef = useRef(onClose);
  const openerRef = useRef(opener);
  useEffect(() => {
    onCloseRef.current = onClose;
    openerRef.current = opener;
  });
  useEffect(() => {
    const panel = ref.current;
    if (!panel) return;
    const restoreTo = openerRef.current;
    const token = Symbol("modal-a11y-overlay");
    overlayStack.push(token);
    if (scrollLockCount === 0) document.body.style.overflow = "hidden";
    scrollLockCount++;
    if (!panel.hasAttribute("tabindex")) panel.tabIndex = -1;

    const focusables = (): HTMLElement[] =>
      Array.from(
        panel.querySelectorAll<HTMLElement>(
          'a[href],button:not([disabled]),textarea:not([disabled]),input:not([disabled]),select:not([disabled]),[tabindex]:not([tabindex="-1"])',
        ),
      ).filter((el) => el.offsetParent !== null || el.getClientRects().length > 0);

    // Prefer the first form field; else the first focusable; else the panel itself.
    const initial = focusables();
    const firstField = initial.find((el) => /^(INPUT|TEXTAREA|SELECT)$/.test(el.tagName));
    (firstField ?? initial[0] ?? panel)?.focus?.();

    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.stopPropagation();
        if (!isTopOverlay(token)) return;
        onCloseRef.current();
        return;
      }
      if (e.key !== "Tab" || !isTopOverlay(token)) return;
      const els = focusables();
      if (els.length === 0) {
        e.preventDefault();
        panel.focus();
        return;
      }
      const first = els[0];
      const last = els[els.length - 1];
      const active = document.activeElement as HTMLElement | null;
      if (!active || !panel.contains(active)) {
        e.preventDefault();
        first?.focus();
      } else if (e.shiftKey && (active === first || active === panel)) {
        e.preventDefault();
        last?.focus();
      } else if (!e.shiftKey && active === last) {
        e.preventDefault();
        first?.focus();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("keydown", onKey);
      const i = overlayStack.indexOf(token);
      if (i !== -1) overlayStack.splice(i, 1);
      scrollLockCount = Math.max(0, scrollLockCount - 1);
      if (scrollLockCount === 0) document.body.style.overflow = "";
      restoreTo?.focus?.();
    };
  }, []);

  return ref;
}

// Where focus goes when the thing that held it is gone: a navigation that
// replaced the region, a Reload that cleared the button pressed, a drawer
// whose opener has left the page (IA_SPEC.md 7, finding FE-4). One place, so
// the workspace and the evidence drawers cannot disagree about it.
//
// The section heading rather than the landmark: it names the view the reader
// has just arrived at, and reading continues from it in document order.

/** The title the browser tab carries: the section, the case it is about where
    there is one, and the workspace. */
export function pageTitle(section: string, subject: string | null): string {
  return subject ? `${section} · ${subject} · CAOS` : `${section} · CAOS`;
}

/** Move focus to the section heading. A heading is not focusable by default,
    so it is made programmatically focusable and never a tab stop. */
export function focusSectionHeading(): void {
  const heading = globalThis.document?.querySelector<HTMLElement>("[data-workspace] h1");
  if (!heading) return;
  if (!heading.hasAttribute("tabindex")) heading.tabIndex = -1;
  heading.focus();
}

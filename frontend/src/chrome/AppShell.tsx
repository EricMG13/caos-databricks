// The frame every page shares: the sidebar, then the inset that holds the
// header and the body. A demo build says so above the header, on every page.
import type { CSSProperties, ReactNode } from "react";
import { SeverityMark } from "./SeverityMark";
import { SidebarInset, SidebarProvider } from "@/components/ui/sidebar";

export function AppShell({
  section,
  label,
  sidebar,
  header,
  children,
}: {
  /** The section on screen, or "absent" for a route that names none. */
  section: string;
  /** The body landmark's name: the section's. */
  label: string;
  sidebar: ReactNode;
  header: ReactNode;
  children: ReactNode;
}) {
  return (
    // `module-workbench` is every section's density (body padding and gaps, the
    // 13rem sidebar) and the module index's wide layout: its rules are in caos.css.
    <SidebarProvider
      data-workspace
      data-section={section}
      className="module-workbench"
      style={{ "--sidebar-width": "13rem" } as CSSProperties}
    >
      {sidebar}
      <SidebarInset className="min-w-0">
        {import.meta.env.MODE === "demo" ? (
          // The thin form (D66): a line in the header's own colour, the words
          // in the warning hue beside its mark, so the demonstration says what
          // it is without setting every page's first impression.
          <aside
            aria-label="Demonstration mode"
            data-demo-banner
            className="flex items-center justify-center gap-1.5 border-b bg-background px-4 py-1 text-xs font-medium text-warning md:rounded-t-xl"
          >
            <SeverityMark severity="WARNING" decorative />
            Read-only demonstration · sample decisions · nothing is persisted
          </aside>
        ) : null}
        {header}
        <main id="body" aria-label={label} className="flex min-w-0 flex-1 flex-col">
          {children}
        </main>
      </SidebarInset>
    </SidebarProvider>
  );
}

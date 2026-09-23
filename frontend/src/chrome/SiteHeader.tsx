// What am I looking at, and is it trustworthy? The case and the section as a
// trail, the section's name as the page heading, then the document's warnings
// and the run's state, the section's actions (at most three, exactly one
// primary; IA_SPEC.md 3) and the reader's theme.
import { SeverityMark } from "./SeverityMark";
import { ThemeToggle } from "./ThemeToggle";
import { RUN_SEVERITY, sentence } from "./compose";
import { Badge } from "@/components/ui/badge";
import { BreadcrumbItem, BreadcrumbList, BreadcrumbSeparator } from "@/components/ui/breadcrumb";
import { Separator } from "@/components/ui/separator";
import { SidebarTrigger } from "@/components/ui/sidebar";
import { RefusedControl } from "@/controls/RefusedControl";
import type { Ribbon, Severity, Subject, Tone } from "@/wire";

export const TONE_BADGE = {
  ok: "success",
  warn: "warning",
  crit: "destructive",
  acc: "info",
  neutral: "outline",
} as const satisfies Record<Tone, string>;

function runSeverity(status: string): Severity {
  return (RUN_SEVERITY as Record<string, Severity>)[status] ?? "IDLE";
}

export function SiteHeader({
  label,
  crumb,
  subject,
  ribbon,
  tabs,
  onTab,
}: {
  /** The section's name: the page heading. */
  label: string;
  /** What the section is about, ahead of it in the trail, where there is one. */
  crumb: string | null;
  subject: Subject | null;
  ribbon: Ribbon;
  /** The section's own tabs. An action naming any other tab opens nothing, so it
      stays refused, for that reason, rather than becoming a live control that
      does nothing. */
  tabs?: readonly string[];
  /** Opens a tab of this section: the one kind of action the workspace performs itself. */
  onTab?: (tab: string) => void;
}) {
  const actions = ribbon.actions.slice(0, 3);
  return (
    <header className="sticky top-0 z-20 flex h-14 shrink-0 items-center gap-2 border-b bg-background px-3 md:px-4 md:first:rounded-t-xl">
      <SidebarTrigger className="-ml-1" />
      <Separator orientation="vertical" className="mx-1 my-4" />
      <BreadcrumbList className="min-w-0 flex-nowrap">
        {crumb ? (
          <>
            <BreadcrumbItem className="max-w-[38vw] min-w-0 shrink-[4] sm:max-w-none">
              {/* The issuer is what a reader recognises; the case id stays reachable. */}
              <span className="truncate" title={subject?.case_id} data-case={subject?.case_id}>
                {crumb}
              </span>
            </BreadcrumbItem>
            <BreadcrumbSeparator />
          </>
        ) : null}
        <BreadcrumbItem className="min-w-0">
          {/* Focusable, never a tab stop: it is where focus lands after a
              navigation, a Reload, or a drawer whose opener has gone (FE-4). */}
          <h1 tabIndex={-1} className="truncate text-sm font-medium text-foreground">
            {label}
          </h1>
        </BreadcrumbItem>
      </BreadcrumbList>
      <div className="ml-auto flex shrink-0 items-center gap-2">
        {ribbon.chips.map((chip, index) => (
          <Badge key={index} variant={TONE_BADGE[chip.tone]} data-chip={chip.tone}>
            {chip.label}
          </Badge>
        ))}
        {ribbon.execution === null ? null : (
          <Badge
            variant="outline"
            className="hidden gap-1.5 sm:inline-flex"
            data-state-cell="execution"
          >
            <SeverityMark severity={runSeverity(ribbon.execution)} decorative />
            <span className="sr-only">Run </span>
            {sentence(ribbon.execution)}
          </Badge>
        )}
        {actions.map((action, index) => {
          const tab = action.tab !== undefined && tabs?.includes(action.tab) ? action.tab : null;
          // A tab the section does not have is the reason, not a missing route.
          const refusal =
            action.refusal ??
            (action.tab !== undefined && tab === null
              ? { code: "VIEW_UNPLACED", clears: `this section has a ${action.tab} tab` }
              : null);
          return (
            <RefusedControl
              key={index}
              refusal={refusal}
              onClick={tab !== null && onTab ? () => onTab(tab) : undefined}
              reasonDisplay="hidden"
              variant={action.primary ? "default" : "outline"}
              size="sm"
              data-primary={action.primary || undefined}
            >
              {action.label}
            </RefusedControl>
          );
        })}
        <ThemeToggle />
      </div>
    </header>
  );
}

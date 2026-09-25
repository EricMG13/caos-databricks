// The section at a glance: the single conclusion it supports, with its
// severity as shape and hue and the one thing blocking it; one headline
// figure; then what changed, what it means, what to do and on what evidence
// (IA_SPEC.md 3). Every cell is composed from the document's own facts, and a
// cell with nothing to say is not drawn (critique P1).
import { useId, useState } from "react";
import { SeverityMark, toneOf } from "./SeverityMark";
import { sentence } from "./compose";
import { Button } from "@/components/ui/button";
import type { Brief, Ribbon, Verdict } from "@/wire";

const CELLS: { key: keyof Omit<Brief, "headline">; label: string }[] = [
  { key: "change", label: "Change" },
  { key: "impact", label: "Impact" },
  { key: "action", label: "Next step" },
  { key: "evidence", label: "Evidence" },
];

/** The headline figure, unless the conclusion already says it ("4 cases."
    beside a bare 4 is the same fact twice). */
export function headlineOf(brief: Brief, verdict: Verdict): string | null {
  const figure = brief.headline;
  if (figure === null) return null;
  const said = verdict.conclusion.split(/[^0-9/.,]+/).some((token) => token === figure);
  return said ? null : figure;
}

/** Persistence and approval: each drawn only when the document says something
    about it. Execution is the header's. */
const STATE_CELLS = [
  { key: "persistence", label: "Revision" },
  { key: "approval", label: "Approval" },
] as const;

export function SectionSummary({
  verdict,
  brief,
  ribbon,
  compact = false,
}: {
  verdict: Verdict;
  brief: Brief;
  ribbon: Ribbon;
  /** One line, the brief on request: a section whose view is open (an
      Analysis module) gives the first screen to the view. */
  compact?: boolean;
}) {
  const cells = CELLS.filter((cell) => brief[cell.key]);
  const states = STATE_CELLS.filter(({ key }) => ribbon[key] !== null);
  const headline = headlineOf(brief, verdict);
  const [opened, setOpened] = useState(false);
  const briefId = useId();
  const briefShown = cells.length > 0 && (!compact || opened);
  return (
    <section
      aria-label="Summary"
      className="overflow-hidden rounded-xl bg-card text-card-foreground ring-1 ring-foreground/10"
      data-summary
      data-compact={compact || undefined}
    >
      <div
        className={
          compact
            ? "flex flex-wrap items-center gap-x-6 gap-y-1 px-4 py-2"
            : "flex flex-wrap items-start gap-x-8 gap-y-3 p-4"
        }
      >
        <div
          className={`min-w-0 flex-1 basis-80 ${compact ? "flex flex-wrap items-baseline gap-x-4" : ""}`}
          data-verdict={verdict.severity}
          data-tone={toneOf(verdict.severity)}
        >
          <p
            className={`flex items-baseline gap-2.5 font-semibold tracking-tight text-balance ${compact ? "text-sm" : "text-base"}`}
          >
            <SeverityMark severity={verdict.severity} pulse />
            <span>{verdict.conclusion}</span>
          </p>
          {verdict.blocked_on || states.length ? (
            <p
              className={`flex flex-wrap gap-x-4 gap-y-1 text-sm text-muted-foreground ${compact ? "" : "mt-1 pl-5"}`}
            >
              {verdict.blocked_on ? (
                <span data-blocked-on>
                  Blocked on <span className="font-mono text-foreground">{verdict.blocked_on}</span>
                </span>
              ) : null}
              {states.map(({ key, label }) => (
                <span key={key} data-state-cell={key}>
                  {label} <span className="text-foreground">{sentence(ribbon[key] ?? "")}</span>
                </span>
              ))}
            </p>
          ) : null}
        </div>
        {headline === null ? null : compact ? (
          <p className="text-sm text-muted-foreground" data-headline>
            <span className="font-mono font-semibold text-foreground tabular-nums">{headline}</span>
            {brief.headline_label ? ` ${brief.headline_label}` : null}
          </p>
        ) : (
          <p className="text-right" data-headline>
            <span className="block font-mono text-2xl leading-none font-semibold tracking-tight tabular-nums">
              {headline}
            </span>
            {brief.headline_label ? (
              <span className="mt-1 block text-xs text-muted-foreground">
                {brief.headline_label}
              </span>
            ) : null}
          </p>
        )}
        {compact && cells.length ? (
          <Button
            type="button"
            variant="ghost"
            size="sm"
            aria-expanded={opened}
            aria-controls={opened ? briefId : undefined}
            data-brief-toggle
            onClick={() => setOpened((open) => !open)}
          >
            {opened ? "Hide brief" : "Brief"}
          </Button>
        ) : null}
      </div>
      {briefShown ? (
        <dl
          id={briefId}
          className="grid gap-x-8 gap-y-3 border-t bg-muted/40 px-4 py-3 sm:grid-cols-2 xl:grid-cols-4"
          data-brief
        >
          {cells.map((cell) => (
            <div key={cell.key} className="min-w-0" data-cell={cell.key}>
              <dt className="text-xs font-medium text-muted-foreground">{cell.label}</dt>
              <dd className="mt-0.5 text-sm text-pretty">{brief[cell.key]}</dd>
            </div>
          ))}
        </dl>
      ) : null}
    </section>
  );
}

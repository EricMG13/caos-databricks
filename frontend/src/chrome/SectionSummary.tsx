// The section at a glance: the single conclusion it supports, with its
// severity as shape and hue and the one thing blocking it; one headline
// figure; then what changed, what it means, what to do and on what evidence
// Every cell is composed from the document's own facts, and a
// cell with nothing to say is not drawn (critique P1).
import { useEffect, useId, useRef, useState, type ReactNode, type RefObject } from "react";
import { SeverityMark, toneOf } from "./SeverityMark";
import { Button } from "@/components/ui/button";
import type { Brief, Ribbon, Verdict } from "@/wire";

const CELLS: { key: keyof Omit<Brief, "headline">; label: string }[] = [
  { key: "change", label: "Change" },
  { key: "impact", label: "Impact" },
  { key: "action", label: "Next step" },
  { key: "evidence", label: "Evidence" },
];

/** The headline figure, unless the conclusion already says it ("4 cases"
    beside a bare 4 is the same fact twice). Said means said with what it
    counts: "1 run parked" does not state a headline of 1 case (D70). */
export function headlineOf(brief: Brief, verdict: Verdict): string | null {
  const figure = brief.headline;
  if (figure === null) return null;
  const label = brief.headline_label;
  const said = label
    ? verdict.conclusion.includes(`${figure} ${label}`)
    : verdict.conclusion.split(/[^0-9/.,]+/).some((token) => token === figure);
  return said ? null : figure;
}

/** A date or a stamp, as the brief's cells print them ("2026-09-09",
    "2026-09-09 14:33Z"). */
const STAMP = /(\d{4}-\d{2}-\d{2}(?: \d{2}:\d{2}(?::\d{2})?Z)?)/;

/** A cell's text with each date or stamp kept whole: a narrow cell broke
    "2026-09-09" after its hyphen, mid-date. */
export function keepStamps(text: string): ReactNode[] {
  return text.split(STAMP).map((part, index) =>
    index % 2 ? (
      <span key={index} className="whitespace-nowrap">
        {part}
      </span>
    ) : (
      part
    ),
  );
}

/** Persistence and approval: each drawn only when the document says something
    about it. Execution is the header's. */
const STATE_CELLS = [
  { key: "persistence", label: "Revision" },
  { key: "approval", label: "Approval" },
] as const;

/** While the summary is on screen below the sticky header (3.5rem), the
    page says so on its root (`data-summary-in-view`), and the header's
    warning chips, which say what the verdict says, give way to it. Where
    there is no observer the root is never marked and the chips stay. */
function useInView(target: RefObject<HTMLElement | null>) {
  useEffect(() => {
    const node = target.current;
    if (!node || typeof IntersectionObserver === "undefined") return;
    const root = document.documentElement;
    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry?.isIntersecting) root.dataset["summaryInView"] = "";
        else delete root.dataset["summaryInView"];
      },
      { rootMargin: "-56px 0px 0px 0px" },
    );
    observer.observe(node);
    return () => {
      observer.disconnect();
      delete root.dataset["summaryInView"];
    };
  }, [target]);
}

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
  const self = useRef<HTMLElement>(null);
  useInView(self);
  return (
    <section
      ref={self}
      aria-label="Summary"
      className="overflow-hidden rounded-xl bg-card text-card-foreground ring-1 ring-foreground/10"
      data-summary
      data-compact={compact || undefined}
    >
      {/* A reading measure (D64): the card spans the body like every card
          under it, but its verdict, headline and cells stop at 78rem rather
          than spreading across a wide desk screen. */}
      <div
        className={
          compact
            ? "flex max-w-[78rem] flex-wrap items-center gap-x-6 gap-y-1 px-4 py-2"
            : "flex max-w-[78rem] flex-wrap items-start gap-x-8 gap-y-3 p-4"
        }
        data-summary-measure
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
                  {/* As composed: the section's own words in sentence case, the
                      bundle's statuses as the bundle spells them (D65). */}
                  {label} <span className="text-foreground">{ribbon[key]}</span>
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
          // Beside the verdict it closes the row, right-aligned; wrapped under it
          // at a zoomed width it aligns with the verdict's words.
          <p className="pl-5 text-left sm:pl-0 sm:text-right" data-headline>
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
          className="grid gap-x-8 gap-y-3 border-t bg-muted/40 px-4 py-3 sm:grid-cols-2 xl:grid-cols-[repeat(4,minmax(0,17.5rem))]"
          data-brief
        >
          {cells.map((cell) => (
            <div key={cell.key} className="min-w-0" data-cell={cell.key}>
              <dt className="text-xs font-medium text-muted-foreground">{cell.label}</dt>
              <dd className="mt-0.5 text-sm text-pretty">{keepStamps(brief[cell.key] ?? "")}</dd>
            </div>
          ))}
        </dl>
      ) : null}
    </section>
  );
}

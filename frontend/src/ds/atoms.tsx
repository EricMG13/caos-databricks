// The shared status tag. Severity → colour through sev.ts; the word carries
// the meaning, the hue never alone.

import type { ReactNode } from "react";
import { sevSurface } from "./sev";

export function Tag({ sev, children }: { sev?: string; children: ReactNode }) {
  const s = sev || "idle";
  const { color: c, borderColor, background } = sevSurface(s);
  const isIdle = s === "idle" || s === "queued" || c === "var(--caos-idle)";
  const textColor = isIdle ? "var(--caos-muted)" : c;
  return (
    <span
      className="tabular text-caos-xs uppercase tracking-wider px-1.5 py-px rounded border inline-flex items-center gap-1 whitespace-nowrap"
      style={{ color: textColor, borderColor, background }}
    >
      {children}
    </span>
  );
}

/** A labelled list of server strings, or the word "none": limitation flags,
    validation warnings. A `data-*` marker names the note for a test. */
export function NoteList({
  label,
  values,
  ...marks
}: {
  label: string;
  values: readonly string[];
  [mark: `data-${string}`]: string | boolean | undefined;
}) {
  return (
    <div className="note" {...marks}>
      <b>{label}</b> {values.length ? values.join(", ") : "none"}
    </div>
  );
}

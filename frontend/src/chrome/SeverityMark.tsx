// Severity is shape and hue, never hue alone (DESIGN.md): success and running
// are a disc, warning a triangle, critical a rounded square, idle a flat dot,
// and a restricted node -- ran, carrying its limitation -- a ring.
import type { Severity } from "@/wire";

export const SHAPES: Record<Severity, { cls: string; shape: string }> = {
  SUCCESS: { cls: "ok", shape: "disc" },
  RUNNING: { cls: "run", shape: "disc" },
  WARNING: { cls: "warn", shape: "triangle" },
  CRITICAL: { cls: "crit", shape: "rounded-square" },
  IDLE: { cls: "idle", shape: "flat-dot" },
  RESTRICTED: { cls: "restricted", shape: "ring" },
};

export function toneOf(severity: Severity): string {
  return SHAPES[severity].cls;
}

/** A severity worn by a badge: its tone, beside the mark that carries its shape. */
export const SEVERITY_BADGE = {
  SUCCESS: "success",
  RUNNING: "info",
  WARNING: "warning",
  CRITICAL: "destructive",
  IDLE: "outline",
  RESTRICTED: "outline",
} as const satisfies Record<Severity, string>;

export function SeverityMark({
  severity,
  pulse = false,
  label,
  decorative = false,
}: {
  severity: Severity;
  pulse?: boolean;
  /** Accessible name; defaults to the severity word. */
  label?: string;
  /** Set where a word beside the mark already says it, so a screen reader
      hears the severity once, not twice (critique). */
  decorative?: boolean;
}) {
  const { cls, shape } = SHAPES[severity];
  return (
    <span
      className={`glyph ${cls}${pulse && severity === "RUNNING" ? " caos-running" : ""}`}
      {...(decorative ? { "aria-hidden": true } : { role: "img", "aria-label": label ?? severity })}
      data-shape={shape}
      data-severity={severity}
    />
  );
}

// Severity is shape and hue, never hue alone (DESIGN.md): success and running
// are a disc, warning a triangle, critical a rounded square, idle a flat dot.
import type { Severity } from "@/wire";

export const SHAPES: Record<Severity, { cls: string; shape: string }> = {
  SUCCESS: { cls: "ok", shape: "disc" },
  RUNNING: { cls: "run", shape: "disc" },
  WARNING: { cls: "warn", shape: "triangle" },
  CRITICAL: { cls: "crit", shape: "rounded-square" },
  IDLE: { cls: "idle", shape: "flat-dot" },
};

export function toneOf(severity: Severity): string {
  return SHAPES[severity].cls;
}

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

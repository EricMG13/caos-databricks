// Severity / state → CSS color utilities. Pure, no React.

export const SEV_COLOR: Record<string, string> = {
  critical: "var(--caos-critical)",
  high: "var(--caos-critical-bright)",
  warning: "var(--caos-warning)",
  medium: "var(--caos-warning)",
  ok: "var(--caos-success)",
  pass: "var(--caos-success)",
  low: "var(--caos-muted)",
  info: "var(--caos-accent)",
  running: "var(--caos-accent)",
  idle: "var(--caos-idle)",
  held: "var(--caos-warning)",
  blocked: "var(--caos-critical)",
  queued: "var(--caos-idle)",
  clear: "var(--caos-success)",
  conditional: "var(--caos-warning)",
};

/** CSS color for a severity/state token (falls back to idle). */
export const sevVar = (sev: string): string => SEV_COLOR[sev] || "var(--caos-idle)";

/** Status-tinted surface — the canonical { color, borderColor, background }
 *  triple for severity-colored cards and tags. Uses color-mix so it works for
 *  both hex and CSS-var severity colors. */
export function sevSurface(
  sev: string,
  opts?: { border?: number; wash?: number },
): { color: string; borderColor: string; background: string } {
  const c = sevVar(sev);
  const border = opts?.border ?? 38;
  const wash = opts?.wash ?? 10;
  return {
    color: c,
    borderColor: `color-mix(in srgb, ${c} ${border}%, transparent)`,
    background: `color-mix(in srgb, ${c} ${wash}%, transparent)`,
  };
}

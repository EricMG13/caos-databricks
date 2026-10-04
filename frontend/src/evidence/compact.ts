// A citation as a compact display shows it (D107; owner, 4 October 2026:
// "Compact, source on click"): its excerpt clamped to about one line. The
// whole source line is shown in the source drawer alone.

/** The longest excerpt a compact display shows (D107): about one line. */
export const EXCERPT_CHARS = 120;

/** A quote as a compact display shows it: its whitespace runs as single
    spaces, and past `EXCERPT_CHARS` characters (code points, as
    `render.clamped` counts them) cut with an ellipsis. The full line is the
    source drawer's to show. */
export function clampExcerpt(quote: string): string {
  const flat = quote.split(/\s+/).filter(Boolean).join(" ");
  const chars = Array.from(flat);
  if (chars.length <= EXCERPT_CHARS) return flat;
  return `${chars
    .slice(0, EXCERPT_CHARS - 1)
    .join("")
    .trimEnd()}…`;
}

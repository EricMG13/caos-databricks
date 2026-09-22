// The two display forms every section spells the same way: a timestamp
// shortened to the minute, and a digest elided in the middle. One copy each,
// so a row in Directory and a row in Upload cannot drift apart.

/** `2026-09-09T14:30:00Z` reads `2026-09-09 14:30Z`. */
export function stamp(iso: string): string {
  return iso.replace("T", " ").replace(/:\d\d(?:\.\d+)?Z$/, "Z");
}

/** `0b582ff0…30df` -- the full digest travels in the element's title. A
    digest of 16 characters or fewer is left whole: the short form is 13, so
    eliding one that short hides characters and saves nothing. `fallback`
    is what a missing digest reads as (Run: "not pinned"). */
export function shortDigest(digest: string | null, fallback = "—"): string {
  if (digest === null) return fallback;
  return digest.length > 16 ? `${digest.slice(0, 8)}…${digest.slice(-4)}` : digest;
}

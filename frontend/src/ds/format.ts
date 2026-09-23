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

/** A decimal string for reading: thousands grouped and `places` fraction
    digits, rounded half away from zero on the digits themselves, never through
    a float. `500.000000` reads `500.00`; the exact value stays in the passport.
    Anything that is not a plain decimal is returned as it came. */
export function displayDecimal(value: string, places = 2): string {
  const match = /^(-?)(\d+)(?:\.(\d+))?$/.exec(value);
  if (!match) return value;
  const [, sign, whole, fraction = ""] = match;
  const digits = fraction.padEnd(places + 1, "0");
  let scaled = BigInt(`${whole}${digits.slice(0, places)}`);
  if (digits[places]! >= "5") scaled += 1n;
  const text = scaled.toString().padStart(places + 1, "0");
  const integer = text.slice(0, text.length - places).replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  const shown = places ? `${integer}.${text.slice(text.length - places)}` : integer;
  return scaled === 0n ? shown : `${sign}${shown}`;
}

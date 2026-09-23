// Exact decimals. The API serves every figure as a decimal string; a chart
// prints it as served (digit grouping is string work, never a float round
// trip) and adds, subtracts and apportions it exactly, as integers counted in
// a power of ten (BigInt). `toNumber` is the one conversion to a float, and it
// places marks; it never prints one.
import type { Datum, Decimal, Origin } from "./types";

const DECIMAL = /^-?\d+(\.\d+)?$/;

/** The wire's pattern for an exact decimal. */
export function isDecimal(value: string): boolean {
  return DECIMAL.test(value);
}

/** Digits after the point: "12.340" has 3. */
export function placesOf(value: Decimal): number {
  const point = value.indexOf(".");
  return point === -1 ? 0 : value.length - point - 1;
}

/** `value` as a count of 10^-places: ("12.34", 3) is 12340n. `places` must
    be at least the value's own, or a digit would be lost. */
export function toScaled(value: Decimal, places: number): bigint {
  if (placesOf(value) > places) throw new RangeError("places below the value's own");
  const negative = value.startsWith("-");
  const [whole = "0", fraction = ""] = (negative ? value.slice(1) : value).split(".");
  const count = BigInt(`${whole}${fraction.padEnd(places, "0")}`);
  return negative ? -count : count;
}

/** The inverse of `toScaled`: (12340n, 3) is "12.340". */
export function fromScaled(count: bigint, places: number): Decimal {
  const negative = count < 0n;
  const digits = (negative ? -count : count).toString().padStart(places + 1, "0");
  const cut = digits.length - places;
  const fraction = places > 0 ? `.${digits.slice(cut)}` : "";
  return `${negative ? "-" : ""}${digits.slice(0, cut)}${fraction}`;
}

/** Groups of three by a loop rather than a lookahead regex: the same
    super-linear shape `check-vocabulary.mjs` avoids (javascript:S8786). */
function group(digits: string): string {
  let out = "";
  for (let at = 0; at < digits.length; at += 1) {
    if (at > 0 && (digits.length - at) % 3 === 0) out += ",";
    out += digits[at];
  }
  return out;
}

/** The value as served, its whole digits grouped: "1234567.50" reads
    "1,234,567.50". `signed` marks a value above zero with "+", for a change. */
export function formatDecimal(value: Decimal, signed = false): string {
  const negative = value.startsWith("-");
  const [whole = "", fraction] = (negative ? value.slice(1) : value).split(".");
  const sign = negative ? "-" : signed && /[1-9]/.test(value) ? "+" : "";
  return `${sign}${group(whole)}${fraction === undefined ? "" : `.${fraction}`}`;
}

// ponytail: geometry only. A double holds 15-17 significant digits, far past
// one pixel of any chart, so a longer figure still lands on the right pixel;
// its label is still the string. Nothing this returns is ever printed.
/** A decimal as a number, to place a mark. */
export function toNumber(value: Decimal): number {
  return Number(value);
}

/** Each part's share of their sum in percent, to one decimal, apportioned by
    largest remainder so the shares sum to exactly 100.0. The parts are
    non-negative counts at one scale; a sum of zero has no shares. */
export function percentShares(parts: readonly bigint[]): Decimal[] | null {
  const whole = parts.reduce((sum, part) => sum + part, 0n);
  if (whole <= 0n) return null;
  const tenths = parts.map((part) => (part * 1000n) / whole);
  const order = parts
    .map((part, index) => ({ index, remainder: (part * 1000n) % whole }))
    .sort((a, b) => {
      if (a.remainder === b.remainder) return a.index - b.index;
      return a.remainder > b.remainder ? -1 : 1;
    });
  let short = 1000n - tenths.reduce((sum, tenth) => sum + tenth, 0n);
  for (const { index } of order) {
    if (short === 0n) break;
    tenths[index] = (tenths[index] ?? 0n) + 1n;
    short -= 1n;
  }
  return tenths.map((tenth) => fromScaled(tenth, 1));
}

/** A datum read for drawing: an exact decimal, or null and why. A string the
    wire's pattern refuses is never drawn; it is named as refused instead. */
export interface ReadValue {
  value: Decimal | null;
  reason: string | null;
  origin: Origin | null;
}

export const UNSERVED = "Not served";
export const INEXACT = "Not an exact decimal";
export const UNAVAILABLE = "Unavailable";

export function readDatum(datum: Datum | undefined): ReadValue {
  if (datum === undefined) return { value: null, reason: UNSERVED, origin: null };
  const origin = datum.origin ?? null;
  if (datum.value === null) return { value: null, reason: datum.reason || UNAVAILABLE, origin };
  if (!isDecimal(datum.value)) return { value: null, reason: INEXACT, origin };
  return { value: datum.value, reason: null, origin };
}

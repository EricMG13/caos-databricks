// A stack, exact. Each category's segments stack in series order, up from
// zero for values at or above it and down for values below, so an
// elimination hangs under the axis rather than eating the segment above it.
// Sums are integer counts at the finest decimal place (BigInt). Normalised,
// a segment is its share of the category's whole, and the printed shares are
// apportioned by largest remainder to sum to exactly 100.0.
import { fromScaled, percentShares, placesOf, toNumber, toScaled } from "./decimal";
import type { Cell } from "./series";
import type { Decimal } from "./types";

export interface Segment {
  cell: Cell;
  /** Value-space ends; percent of the whole when normalised. Geometry only. */
  from: number;
  to: number;
  /** Sits on another segment, so the 2px surface gap comes off its start. */
  stacked: boolean;
  /** Its share of the whole in percent, one decimal; normalised only. */
  share: Decimal | null;
  /** Why no segment is drawn: the value's own reason, or no share of a whole. */
  gap: string | null;
}

export interface StackTotal {
  /** Where the label sits: the end of the part above zero. */
  at: Decimal;
  /** The net total, above-zero part plus below. */
  net: Decimal;
}

export const NO_SHARE = "A negative value has no share of a whole";
export const NO_WHOLE = "No whole to share: the values sum to zero";

/** Every cell of `cells` as a segment, category by category, and each
    category's total: `null` wherever a value is unavailable, since a sum with
    a part missing is not the total. */
export function stackOf(
  cells: readonly Cell[],
  categories: number,
  normalised: boolean,
): { segments: Segment[]; totals: (StackTotal | null)[] } {
  const places = Math.max(
    0,
    ...cells.flatMap((cell) => (cell.value === null ? [] : [placesOf(cell.value)])),
  );
  const segments: Segment[] = [];
  const totals: (StackTotal | null)[] = [];
  for (let index = 0; index < categories; index += 1) {
    const column = cells.filter((cell) => cell.index === index);
    const stacked = normalised ? shares(column, places) : absolute(column, places);
    segments.push(...stacked.segments);
    totals.push(stacked.total);
  }
  return { segments, totals };
}

function absolute(column: readonly Cell[], places: number) {
  let above = 0n;
  let below = 0n;
  let whole = true;
  const segments = column.map((cell): Segment => {
    if (cell.value === null) {
      whole = false;
      return { cell, from: 0, to: 0, stacked: false, share: null, gap: cell.reason };
    }
    const amount = toScaled(cell.value, places);
    const negative = amount < 0n;
    const start = negative ? below : above;
    const end = start + amount;
    if (negative) below = end;
    else above = end;
    return {
      cell,
      from: toNumber(fromScaled(start, places)),
      to: toNumber(fromScaled(end, places)),
      stacked: start !== 0n,
      share: null,
      gap: null,
    };
  });
  const total = whole
    ? { at: fromScaled(above, places), net: fromScaled(above + below, places) }
    : null;
  return { segments, total };
}

function shares(column: readonly Cell[], places: number) {
  const parts = column.map((cell) => (cell.value === null ? null : toScaled(cell.value, places)));
  const counted = parts.map((part) => (part !== null && part >= 0n ? part : 0n));
  const whole = counted.reduce((sum, part) => sum + part, 0n);
  const percents = percentShares(counted);
  let reached = 0n;
  const segments = column.map((cell, at): Segment => {
    const part = parts[at] ?? null;
    if (part === null || part < 0n || percents === null) {
      const gap = part === null ? cell.reason : part < 0n ? NO_SHARE : NO_WHOLE;
      return { cell, from: 0, to: 0, stacked: false, share: null, gap };
    }
    const start = reached;
    reached += part;
    return {
      cell,
      // ponytail: a ratio of two exact counts, for geometry only; the last
      // segment ends at whole / whole, exactly 100, so the stack fills.
      from: (Number(start) / Number(whole)) * 100,
      to: (Number(reached) / Number(whole)) * 100,
      stacked: start !== 0n,
      share: percents[at] ?? null,
      gap: null,
    };
  });
  return { segments, total: null };
}

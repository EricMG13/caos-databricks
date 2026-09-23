// A bridge, exact. Totals are stated by the data; each delta moves a running
// level kept as an integer count of the finest decimal place any step carries
// (BigInt), so 0.1 + 0.2 is exactly 0.3 and 9007199254740993 stays odd. Where
// the steps before a stated total do not reach it, an explicit "Unreconciled"
// residual step carries the exact difference: a bar is never bent to make a
// bridge close, and a total is never recomputed.
import { fromScaled, placesOf, readDatum, toScaled } from "./decimal";
import type { Decimal, Origin, WaterfallStep } from "./types";

export interface BridgeStep {
  key: string;
  label: string;
  kind: "total" | "delta" | "residual";
  /** As served; the residual's is the difference computed here. */
  value: Decimal | null;
  /** Why the value is unavailable. */
  reason: string | null;
  /** `null` for the residual: nobody served it. */
  origin: Origin | null;
  /** The levels the bar runs between, exact at the bridge's finest place;
      `null` for an unavailable step, drawn as a gap. */
  start: Decimal | null;
  end: Decimal | null;
  /** The residual's stated total, which the steps before it do not reach. */
  before?: string;
}

export const UNRECONCILED = "Unreconciled";

/** The bridge's steps with their levels, and a residual step before every
    stated total the running level does not reach. A bridge without an
    opening total starts from zero. An unavailable delta moves nothing, so the
    next total's residual carries what it would have explained; an
    unavailable total anchors nothing, and the level runs on past it. */
export function bridgeOf(steps: readonly WaterfallStep[]): BridgeStep[] {
  const read = steps.map((step) => ({ step, ...readDatum(step) }));
  const places = Math.max(
    0,
    ...read.flatMap(({ value }) => (value === null ? [] : [placesOf(value)])),
  );
  const exact = (count: bigint) => fromScaled(count, places);
  const out: BridgeStep[] = [];
  let level = 0n;
  read.forEach(({ step, value, reason }, index) => {
    const key = step.key ?? `${index}`;
    const base = { key, label: step.label, kind: step.kind, origin: step.origin };
    if (value === null) {
      out.push({ ...base, value: null, reason, start: null, end: null });
      return;
    }
    const amount = toScaled(value, places);
    if (step.kind === "delta") {
      out.push({ ...base, value, reason: null, start: exact(level), end: exact(level + amount) });
      level += amount;
      return;
    }
    if (index > 0 && level !== amount) {
      out.push({
        key: `${key}:unreconciled`,
        label: UNRECONCILED,
        kind: "residual",
        value: exact(amount - level),
        reason: null,
        origin: null,
        start: exact(level),
        end: exact(amount),
        before: step.label,
      });
    }
    out.push({ ...base, value, reason: null, start: exact(0n), end: exact(amount) });
    level = amount;
  });
  return out;
}

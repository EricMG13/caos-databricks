// Band 4: the single conclusion this section currently supports, its severity
// as shape and hue, and the one thing blocking it.
import { SeverityMark, toneOf } from "./SeverityMark";
import type { Verdict } from "@/wire";

export function VerdictStrip({ verdict }: { verdict: Verdict }) {
  return (
    <section className={`verdict ${toneOf(verdict.severity)}`} aria-label="Verdict">
      <span className="sig">
        <SeverityMark severity={verdict.severity} pulse />
        {verdict.severity}
      </span>
      <span className="txt">
        {verdict.conclusion}
        {verdict.blocked_on ? <span> · blocked on {verdict.blocked_on}</span> : null}
      </span>
    </section>
  );
}

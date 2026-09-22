// The metric passport: exactly the ten fields of IA_SPEC.md 4.4, for an actual
// and for a projected cell alike. A projected cell also names its driver and
// the driver's evidence.
import { useId, type ReactNode } from "react";
import { CitationChip } from "./CitationChip";
import { useModalA11y } from "@/ds/use-modal-a11y";
import { PASSPORT_FIELDS, type Passport, type PassportField } from "@/wire";

export const PASSPORT_LABELS: Record<PassportField, string> = {
  definition: "Definition",
  period: "Period",
  scenario: "Scenario",
  reporting_period: "Reporting period",
  computed_at: "Computed at",
  snapshot: "Snapshot",
  method: "Method",
  derivation: "Derivation",
  citations: "Citations",
  supporting_research: "Supporting research",
};

// Typed over every field, so a missing renderer fails tsc.
const RENDERERS: Record<PassportField, (passport: Passport) => ReactNode> = {
  definition: (p) => p.definition,
  period: (p) => <code>{p.period}</code>,
  scenario: (p) => p.scenario,
  reporting_period: (p) => <code>{p.reporting_period}</code>,
  computed_at: (p) => <code>{p.computed_at}</code>,
  snapshot: (p) => <code>{p.snapshot}</code>,
  method: (p) => p.method,
  derivation: (p) => <code>{p.derivation}</code>,
  citations: (p) => (
    <span className="pillrow">
      {p.citations.map((citation) => (
        <CitationChip key={citation.chip} citation={citation} />
      ))}
    </span>
  ),
  supporting_research: (p) => (
    <>
      {p.supporting_research.map((link) => (
        <div key={link.module_id + link.title} className="reslink">
          <span className="t">{link.title}</span>
          <span className="m">
            {link.module_id} · {link.state}
          </span>
        </div>
      ))}
    </>
  ),
};

export function PassportFields({ passport }: { passport: Passport }) {
  return (
    <dl className="ppfull" data-passport>
      {PASSPORT_FIELDS.map((field) => (
        <div key={field} className="contents" data-passport-field={field}>
          <dt>{PASSPORT_LABELS[field]}</dt>
          <dd>{RENDERERS[field](passport)}</dd>
        </div>
      ))}
      {passport.driver ? (
        <div className="contents" data-passport-field="driver">
          <dt>Driver</dt>
          <dd>
            {passport.driver.name} · <code>{passport.driver.value}</code>{" "}
            <CitationChip citation={passport.driver.citation} />
          </dd>
        </div>
      ) : null}
      {passport.deviation ? (
        <div className="contents" data-passport-field="deviation">
          <dt>Deviation</dt>
          <dd>
            <span className="dev">{passport.deviation.amount}</span> · restatement offered:{" "}
            {passport.deviation.restatement}
          </dd>
        </div>
      ) : null}
    </dl>
  );
}

export function MetricPassport({
  passport,
  opener,
  onClose,
}: {
  passport: Passport;
  opener: HTMLElement | null;
  onClose: () => void;
}) {
  const ref = useModalA11y<HTMLDivElement>(onClose, opener);
  const titleId = useId();
  return (
    <>
      <div className="scrim" aria-hidden="true" onClick={onClose} />
      <div ref={ref} role="dialog" aria-modal="true" aria-labelledby={titleId} className="modal">
        <div className="dhead">
          <h2 id={titleId}>Passport · {passport.label}</h2>
          <button type="button" className="close focus-ring" onClick={onClose}>
            ESC · CLOSE
          </button>
        </div>
        <div className="ppval">
          <span className="v">{passport.value}</span>
          {passport.unit ? <span className="u">{passport.unit}</span> : null}
          {passport.driver ? <span className="tag acc badge">PROJECTED</span> : null}
        </div>
        <PassportFields passport={passport} />
      </div>
    </>
  );
}

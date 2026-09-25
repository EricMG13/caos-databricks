// The edge legend under the DAG: one entry per edge type, in the bundle's
// words, each one's meaning in its title, and the one rule the soft edges
// share said once, so the key is one line at 1280 px (brief 6.6).
const ENTRIES: [string, string, string][] = [
  ["req", "REQUIRED", "Blocks until its source is accepted."],
  ["opt", "OPTIONAL", "Soft until the source is READY."],
  ["adv", "ADVISORY", "Soft until the source is READY."],
  ["cond", "CONDITIONAL", "A frozen predicate."],
  ["gate", "QA_GATE", "The one gate."],
];

export function RouteLegend() {
  return (
    <div className="legend">
      {ENTRIES.map(([cls, code, meaning]) => (
        <span key={cls} title={meaning}>
          <i className={cls} />
          <code>{code}</code>
        </span>
      ))}
      <span className="legend-note">Soft edges block once the source is READY.</span>
    </div>
  );
}

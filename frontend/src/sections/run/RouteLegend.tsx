// The edge legend under the DAG: one entry per edge type, in the bundle's words.
const ENTRIES: [string, string][] = [
  ["req", "REQUIRED · blocks"],
  ["opt", "OPTIONAL · soft until the source is READY"],
  ["adv", "ADVISORY · soft until the source is READY"],
  ["cond", "CONDITIONAL · frozen predicate"],
  ["gate", "QA_GATE · the one gate"],
];

export function RouteLegend() {
  return (
    <div className="legend">
      {ENTRIES.map(([cls, label]) => (
        <span key={cls}>
          <i className={cls} />
          {label}
        </span>
      ))}
    </div>
  );
}

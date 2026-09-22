// Band 2: what changed, what it means, what to do, on what evidence. Four
// cells plus one headline figure, always open, never optional (IA_SPEC.md 3).
import type { Brief } from "@/wire";

const CELLS: { key: keyof Omit<Brief, "headline">; label: string }[] = [
  { key: "change", label: "CHANGE" },
  { key: "impact", label: "IMPACT" },
  { key: "action", label: "ACTION" },
  { key: "evidence", label: "EVIDENCE" },
];

export function DecisionBrief({ brief }: { brief: Brief }) {
  return (
    <section className="brief" aria-label="Decision brief">
      {CELLS.map((cell) => (
        <div key={cell.key} className="bc">
          <span className="k">{cell.label}</span>
          <span className="t">{brief[cell.key]}</span>
        </div>
      ))}
      <div className="bc">
        <span className="headline tabular">{brief.headline}</span>
      </div>
    </section>
  );
}

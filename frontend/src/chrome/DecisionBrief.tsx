// Band 2: what changed, what it means, what to do, on what evidence, plus one
// headline figure (IA_SPEC.md 3). A cell the document has nothing for is not
// drawn, and a brief with nothing to say is no band at all (critique P1).
import type { Brief } from "@/wire";

const CELLS: { key: keyof Omit<Brief, "headline">; label: string }[] = [
  { key: "change", label: "CHANGE" },
  { key: "impact", label: "IMPACT" },
  { key: "action", label: "ACTION" },
  { key: "evidence", label: "EVIDENCE" },
];

export function DecisionBrief({ brief }: { brief: Brief }) {
  const cells = CELLS.filter((cell) => brief[cell.key]);
  if (cells.length === 0 && brief.headline === null) return null;
  return (
    <section className="brief" aria-label="Decision brief">
      {cells.map((cell) => (
        <div key={cell.key} className="bc" data-cell={cell.key}>
          <span className="k">{cell.label}</span>
          <span className="t">{brief[cell.key]}</span>
        </div>
      ))}
      {brief.headline === null ? null : (
        <div className="bc">
          <span className="headline tabular">{brief.headline}</span>
        </div>
      )}
    </section>
  );
}

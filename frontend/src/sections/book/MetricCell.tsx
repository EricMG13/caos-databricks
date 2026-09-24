// One cell of the book: a button that opens the passport with its opener
// passed. A cell the projection could not compute shows its typed reason in
// place of a figure and still carries a passport, because why there is no
// figure is part of what the passport says.
import type { BookCell, BookColumn } from "@/wire/v1";
import { shownValue } from "./passport";

export function MetricCell({
  cell,
  unit,
  label,
  selected,
  onSelect,
}: {
  cell: BookCell;
  unit: BookColumn["unit"];
  label: string;
  selected: boolean;
  onSelect: (opener: HTMLElement) => void;
}) {
  const shown = shownValue(cell, unit);
  return (
    <button
      type="button"
      className="cellbtn"
      data-cell={cell.column}
      data-unit={unit}
      data-unavailable={cell.unavailable_reason ?? undefined}
      aria-pressed={selected}
      aria-label={`${label} · ${shown}`}
      onClick={(event) => onSelect(event.currentTarget)}
    >
      {shown}
    </button>
  );
}

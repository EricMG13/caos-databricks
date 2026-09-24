// One cell of the book: a button that opens the passport with its opener
// passed. A cell the projection could not compute shows its typed reason in
// place of a figure and still carries a passport, because why there is no
// figure is part of what the passport says.
import type { BookCell } from "@/wire/v1";
import { shownValue } from "./passport";

export function MetricCell({
  cell,
  label,
  selected,
  onSelect,
}: {
  cell: BookCell;
  label: string;
  selected: boolean;
  onSelect: (opener: HTMLElement) => void;
}) {
  return (
    <button
      type="button"
      className="cellbtn"
      data-cell={cell.column}
      data-unavailable={cell.unavailable_reason ?? undefined}
      aria-pressed={selected}
      aria-label={`${label} · ${shownValue(cell)}`}
      onClick={(event) => onSelect(event.currentTarget)}
    >
      {shownValue(cell)}
    </button>
  );
}

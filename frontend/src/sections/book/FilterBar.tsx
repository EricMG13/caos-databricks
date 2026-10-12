// The Book's filters (spec B12): one chip per active filter, and an editor
// that adds one. The editor follows the column: a range for a figure, a notch
// range for an agency's rating, a set of the values the issuers hold for any
// other column. Nothing is applied until the bounds read as exact decimals.
import { useState } from "react";
import { isDecimal, placesOf, toScaled } from "@/charts/decimal";
import { Button } from "@/components/ui/button";
import { cellOf, type BookIssuer } from "./filter";
import { agencyOf, BASIS_LABELS, columnLabel, IDENTIFIER_LABELS, type Unit } from "./columns";
import {
  MOODYS_SCALE,
  SP_FITCH_SCALE,
  type Basis,
  type BookView,
  type ColumnKey,
  type Filter,
} from "./view";

function valueLabel(column: ColumnKey, value: string): string {
  if (column === "id:filed") return value === "true" ? "Yes" : "No";
  return value;
}

function describe(filter: Filter, units: readonly Unit[], basis: Basis): string {
  if (filter.kind === "range") {
    // A column that follows the basis switch says which basis it is read in now.
    const label = columnLabel(filter.column, units);
    const name = filter.column.includes("@") ? label : `${label} (${BASIS_LABELS[basis]})`;
    if (filter.min !== null && filter.max !== null)
      return `${name}: ${filter.min} to ${filter.max}`;
    return filter.min !== null
      ? `${name}: at least ${filter.min}`
      : `${name}: at most ${filter.max}`;
  }
  if (filter.kind === "set") {
    const values = filter.values.map((value) => valueLabel(filter.column, value));
    return `${columnLabel(filter.column, units)}: ${values.join(", ")}`;
  }
  return `${IDENTIFIER_LABELS[filter.agency]}: ${filter.best} to ${filter.worst}`;
}

/** Why the bounds cannot be applied, or null when they can. */
function rangeProblem(min: string, max: string): string | null {
  if (min === "" && max === "") return "Enter a minimum, a maximum or both.";
  for (const bound of [min, max]) {
    if (bound !== "" && !isDecimal(bound)) return "Bounds are decimal figures, such as 5 or -2.5.";
  }
  if (min !== "" && max !== "") {
    const places = Math.max(placesOf(min), placesOf(max));
    if (toScaled(min, places) > toScaled(max, places)) return "The minimum is above the maximum.";
  }
  return null;
}

function RangeEditor({ column, onAdd }: { column: ColumnKey; onAdd: (filter: Filter) => void }) {
  const [min, setMin] = useState("");
  const [max, setMax] = useState("");
  const problem = rangeProblem(min.trim(), max.trim());
  return (
    <>
      <label className="fld">
        Minimum
        <input inputMode="decimal" value={min} onChange={(e) => setMin(e.target.value)} />
      </label>
      <label className="fld">
        Maximum
        <input inputMode="decimal" value={max} onChange={(e) => setMax(e.target.value)} />
      </label>
      {problem && (min !== "" || max !== "") ? (
        <p className="fld-hint" role="alert">
          {problem}
        </p>
      ) : null}
      <Button
        type="button"
        variant="outline"
        size="sm"
        aria-disabled={problem !== null || undefined}
        onClick={() => {
          if (problem !== null) return;
          onAdd({
            kind: "range",
            column,
            min: min.trim() === "" ? null : min.trim(),
            max: max.trim() === "" ? null : max.trim(),
          });
        }}
      >
        Apply filter
      </Button>
    </>
  );
}

function NotchEditor({
  agency,
  onAdd,
}: {
  agency: "moodys" | "sp" | "fitch";
  onAdd: (filter: Filter) => void;
}) {
  const scale = agency === "moodys" ? MOODYS_SCALE : SP_FITCH_SCALE;
  const [best, setBest] = useState(scale[0]!);
  const [worst, setWorst] = useState(scale[scale.length - 1]!);
  const problem = scale.indexOf(best) > scale.indexOf(worst);
  return (
    <>
      <label className="fld">
        Best rating
        <select value={best} onChange={(e) => setBest(e.target.value)}>
          {scale.map((label) => (
            <option key={label}>{label}</option>
          ))}
        </select>
      </label>
      <label className="fld">
        Worst rating
        <select value={worst} onChange={(e) => setWorst(e.target.value)}>
          {scale.map((label) => (
            <option key={label}>{label}</option>
          ))}
        </select>
      </label>
      {problem ? (
        <p className="fld-hint" role="alert">
          The best rating is below the worst.
        </p>
      ) : null}
      <Button
        type="button"
        variant="outline"
        size="sm"
        aria-disabled={problem || undefined}
        onClick={() => {
          if (!problem) onAdd({ kind: "notch", agency, best, worst });
        }}
      >
        Apply filter
      </Button>
    </>
  );
}

function SetEditor({
  column,
  issuers,
  onAdd,
}: {
  column: ColumnKey;
  issuers: BookIssuer[];
  onAdd: (filter: Filter) => void;
}) {
  const [chosen, setChosen] = useState<string[]>([]);
  const held = [
    ...new Set(issuers.flatMap((issuer) => cellOf(issuer, column, "LTM") ?? [])),
  ].sort();
  return (
    <>
      <fieldset className="book-group">
        <legend>Values</legend>
        {held.map((value) => (
          <label key={value} className="fopt">
            <input
              type="checkbox"
              checked={chosen.includes(value)}
              onChange={() =>
                setChosen(
                  chosen.includes(value) ? chosen.filter((v) => v !== value) : [...chosen, value],
                )
              }
            />
            {valueLabel(column, value)}
          </label>
        ))}
      </fieldset>
      <Button
        type="button"
        variant="outline"
        size="sm"
        aria-disabled={chosen.length === 0 || undefined}
        onClick={() => {
          if (chosen.length > 0) onAdd({ kind: "set", column, values: chosen });
        }}
      >
        Apply filter
      </Button>
    </>
  );
}

function Editor({
  column,
  issuers,
  onAdd,
}: {
  column: ColumnKey;
  issuers: BookIssuer[];
  onAdd: (filter: Filter) => void;
}) {
  if (column.startsWith("m:")) return <RangeEditor key={column} column={column} onAdd={onAdd} />;
  const agency = agencyOf(column);
  if (agency !== null) return <NotchEditor key={column} agency={agency} onAdd={onAdd} />;
  return <SetEditor key={column} column={column} issuers={issuers} onAdd={onAdd} />;
}

export function FilterBar({
  view,
  units,
  issuers,
  onChange,
}: {
  view: BookView;
  units: readonly Unit[];
  issuers: BookIssuer[];
  onChange: (filters: Filter[]) => void;
}) {
  const [open, setOpen] = useState(false);
  const [column, setColumn] = useState<ColumnKey | "">("");
  const add = (filter: Filter) => {
    onChange([...view.filters, filter]);
    setOpen(false);
    setColumn("");
  };
  return (
    <div className="book-filters" data-filters>
      {view.filters.length > 0 ? (
        <ul className="pillrow" aria-label="Active filters">
          {view.filters.map((filter, index) => {
            const text = describe(filter, units, view.basis);
            return (
              <li key={`${text}:${index}`} className="pill">
                {text}
                <button
                  type="button"
                  className="book-x"
                  aria-label={`Remove filter ${text}`}
                  onClick={() => onChange(view.filters.filter((_, at) => at !== index))}
                >
                  ×
                </button>
              </li>
            );
          })}
        </ul>
      ) : null}
      <Button
        type="button"
        variant="outline"
        size="sm"
        aria-expanded={open}
        onClick={() => setOpen(!open)}
      >
        Add filter
      </Button>
      {open ? (
        <div className="book-editor">
          <label className="fld">
            Filter column
            <select value={column} onChange={(e) => setColumn(e.target.value as ColumnKey | "")}>
              <option value="">Choose a column</option>
              {view.columns.map((key) => (
                <option key={key} value={key}>
                  {columnLabel(key, units)}
                </option>
              ))}
            </select>
          </label>
          {column !== "" ? <Editor column={column} issuers={issuers} onAdd={add} /> : null}
        </div>
      ) : null}
    </div>
  );
}

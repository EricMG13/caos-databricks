// The column chooser (spec B12): every identifier and every metric in the
// catalogue, one checkbox per column. A metric is offered once for the basis
// switch ("follows basis") and once per basis, since each basis is a column of
// its own. Issuer and reporting period are locked: shown, checked, disabled.
import { BASES, IDENTIFIERS, IDENTIFIER_LABELS, columnLabel, type Unit } from "./columns";
import { LOCKED, type BookView, type ColumnKey } from "./view";

function Choice({
  column,
  name,
  view,
  onChange,
}: {
  column: ColumnKey;
  name: string;
  view: BookView;
  onChange: (columns: ColumnKey[]) => void;
}) {
  const locked = LOCKED.includes(column);
  const checked = view.columns.includes(column);
  return (
    <label className="fopt">
      <input
        type="checkbox"
        checked={checked}
        aria-disabled={locked || undefined}
        title={locked ? "Always shown" : undefined}
        onChange={() => {
          if (locked) return;
          onChange(checked ? view.columns.filter((c) => c !== column) : [...view.columns, column]);
        }}
      />
      {name}
    </label>
  );
}

/** Columns the view holds that the chooser would not otherwise list: a stored or
    linked metric the catalogue does not carry. They stay removable. */
function orphans(view: BookView, units: readonly Unit[]): ColumnKey[] {
  const known = new Set<ColumnKey>(IDENTIFIERS.map((id): ColumnKey => `id:${id}`));
  for (const unit of units) {
    known.add(`m:${unit.line_id}`);
    for (const basis of BASES) known.add(`m:${unit.line_id}@${basis}`);
  }
  return view.columns.filter((column) => !known.has(column));
}

export function ColumnChooser({
  view,
  units,
  onChange,
}: {
  view: BookView;
  units: readonly Unit[];
  onChange: (columns: ColumnKey[]) => void;
}) {
  return (
    <div className="book-chooser" data-column-chooser>
      <fieldset className="book-group">
        <legend>Identifiers</legend>
        {IDENTIFIERS.map((id) => (
          <Choice
            key={id}
            column={`id:${id}`}
            name={IDENTIFIER_LABELS[id]}
            view={view}
            onChange={onChange}
          />
        ))}
      </fieldset>
      {orphans(view, units).length > 0 ? (
        <fieldset className="book-group">
          <legend>Not in the catalogue</legend>
          {orphans(view, units).map((column) => (
            <Choice
              key={column}
              column={column}
              name={`${column.replace(/^m:/, "")} (not in this Book's catalogue)`}
              view={view}
              onChange={onChange}
            />
          ))}
        </fieldset>
      ) : null}
      <fieldset className="book-group">
        <legend>Metrics</legend>
        {units.map((unit) => (
          <div key={unit.line_id} className="book-metric">
            <Choice
              column={`m:${unit.line_id}`}
              name={`${unit.label} · Follows basis`}
              view={view}
              onChange={onChange}
            />
            {BASES.map((basis) => {
              const column: ColumnKey = `m:${unit.line_id}@${basis}`;
              return (
                <Choice
                  key={basis}
                  column={column}
                  name={`${columnLabel(column, units)}`}
                  view={view}
                  onChange={onChange}
                />
              );
            })}
          </div>
        ))}
      </fieldset>
    </div>
  );
}

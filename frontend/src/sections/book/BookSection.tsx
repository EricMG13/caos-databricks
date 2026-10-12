// Book, /book/: the desk-wide Book, one row per issuer. Each row is the
// issuer's displayed book entry as the server serves it; the client filters and
// sorts them (spec B12-B15). The view (basis, columns, filters, sort, currency)
// lives in the URL and the last one is remembered in the browser. The section
// composes a view and grants nothing: every field is read from the document,
// figures are re-spelled the way the Model grid spells them and never computed
// on, and nothing here derives, compares or judges an entry.
import { memo, useCallback, useEffect, useId, useMemo } from "react";
import { Link, useSearchParams } from "react-router";
import { Button } from "@/components/ui/button";
import type { BookDocument } from "@/wire/v1";
import { spelled } from "@/sections/model/grid";
import { BASES, BASIS_LABELS, columnLabel, unitLookup, type Unit } from "./columns";
import { applyView, cellOf, metricOf, type BookIssuer } from "./filter";
import {
  DEFAULT_VIEW,
  fromParams,
  toParams,
  type Basis,
  type BookView,
  type ColumnKey,
} from "./view";

const VIEW_KEYS = ["basis", "col", "f", "sort", "cur"] as const;
const STORAGE_KEY = "caos.book.view";

/** The remembered view, as its query text. A browser that refuses storage
    (private mode, a policy) leaves the view to the URL alone: that is the
    documented fail-open, and nothing else is caught. */
function remembered(): string | null {
  try {
    return window.localStorage.getItem(STORAGE_KEY);
  } catch (error) {
    if (error instanceof DOMException) return null;
    throw error;
  }
}

function remember(view: BookView): void {
  try {
    window.localStorage.setItem(STORAGE_KEY, toParams(view).toString());
  } catch (error) {
    if (!(error instanceof DOMException)) throw error;
  }
}

function NotStated() {
  return (
    <span className="na">
      <span aria-hidden="true">—</span>
      <span className="sr-only">Not stated</span>
    </span>
  );
}

function MetricCell({
  issuer,
  column,
  basis,
  unit,
}: {
  issuer: BookIssuer;
  column: ColumnKey;
  basis: Basis;
  unit: Unit | undefined;
}) {
  const value = cellOf(issuer, column, basis);
  if (value === null) return <NotStated />;
  return (
    <span title={value}>
      {unit ? spelled({ unit: unit.unit, unit_label: null }, value) : value}
    </span>
  );
}

/** The fiscal year a projected basis' figure is for, as the cell's description. */
function yearOf(issuer: BookIssuer, column: ColumnKey, basis: Basis): string | undefined {
  const year = issuer.displayed.fiscal_years[metricOf(column, basis)?.basis ?? basis];
  return year === undefined || cellOf(issuer, column, basis) === null ? undefined : `FY${year}`;
}

function IdentifierCell({ issuer, column }: { issuer: BookIssuer; column: ColumnKey }) {
  const value = cellOf(issuer, column, "LTM");
  if (value === null) return <NotStated />;
  if (column === "id:filed") return <>{value === "true" ? "Yes" : "No"}</>;
  return <>{value}</>;
}

function Sorter({
  column,
  view,
  units,
  isMoney,
  onSort,
}: {
  column: ColumnKey;
  view: BookView;
  units: readonly Unit[];
  isMoney: (column: ColumnKey) => boolean;
  onSort: (sort: BookView["sort"]) => void;
}) {
  // A money sort with no currency chosen orders nothing, so it claims nothing.
  const inert = isMoney(column) && view.currency === null;
  const active = view.sort?.column === column && !inert ? view.sort.dir : null;
  const pending = view.sort?.column === column ? view.sort.dir : null;
  const next = pending === null ? "asc" : pending === "asc" ? "desc" : null;
  const basis = column.startsWith("m:") && !column.includes("@") ? BASIS_LABELS[view.basis] : null;
  return (
    <th
      scope="col"
      className={column.startsWith("m:") ? undefined : "l"}
      aria-sort={active === null ? "none" : active === "asc" ? "ascending" : "descending"}
    >
      <button
        type="button"
        className="book-sort"
        onClick={() => onSort(next === null ? null : { column, dir: next })}
      >
        {columnLabel(column, units)}
        {basis ? (
          <>
            {" "}
            <span className="cu">{basis}</span>
          </>
        ) : null}
        <span aria-hidden="true">{active === null ? "" : active === "asc" ? " ▲" : " ▼"}</span>
      </button>
    </th>
  );
}

const IssuerRow = memo(function IssuerRow({
  issuer,
  view,
  unitFor,
}: {
  issuer: BookIssuer;
  view: BookView;
  unitFor: (column: ColumnKey) => Unit | undefined;
}) {
  const entry = issuer.displayed;
  const query = `?case=${encodeURIComponent(entry.case_id)}&run=${encodeURIComponent(entry.run_id)}`;
  return (
    <tr data-issuer={issuer.issuer_key} data-entry={entry.entry_id}>
      {view.columns.map((column) => {
        if (column === "id:issuer_name")
          return (
            <th key={column} scope="row" className="l wrap" data-column={column}>
              <Link to={`/analysis/${query}`}>{entry.issuer_name}</Link>
              <div className="book-acts">
                {entry.filed ? <span className="pill">Filed</span> : null}
                {entry.sources_withdrawn ? (
                  <span className="pill warn">Sources withdrawn</span>
                ) : null}
                <Link to={`/model/${query}`} aria-label={`Open model for ${entry.issuer_name}`}>
                  Open model
                </Link>
              </div>
            </th>
          );
        const metric = column.startsWith("m:");
        return (
          <td
            key={column}
            data-column={column}
            className={metric ? "num" : "l"}
            aria-description={metric ? yearOf(issuer, column, view.basis) : undefined}
          >
            {metric ? (
              <MetricCell
                issuer={issuer}
                column={column}
                basis={view.basis}
                unit={unitFor(column)}
              />
            ) : (
              <IdentifierCell issuer={issuer} column={column} />
            )}
          </td>
        );
      })}
    </tr>
  );
});

export function BookSection({ document }: { document: BookDocument; tab: string | null }) {
  const { issuers, metric_catalogue: units } = document.body;
  const [params, setParams] = useSearchParams();
  const view = useMemo(() => fromParams(params), [params]);
  const ids = useId();

  const update = (next: BookView) => {
    const merged = new URLSearchParams(params);
    for (const key of VIEW_KEYS) merged.delete(key);
    for (const [key, value] of toParams(next)) merged.append(key, value);
    setParams(merged, { replace: true });
    remember(next);
  };

  // With no view in the URL, the last remembered view is the view.
  useEffect(() => {
    if (VIEW_KEYS.some((key) => params.has(key))) return;
    const stored = remembered();
    if (stored === null) return;
    const merged = new URLSearchParams(params);
    for (const [key, value] of toParams(fromParams(new URLSearchParams(stored)))) {
      merged.append(key, value);
    }
    setParams(merged, { replace: true });
    // Every change through `update` writes the view's keys, so this runs once.
  }, [params, setParams]);

  const currencies = useMemo(
    () => [...new Set(issuers.flatMap((issuer) => issuer.displayed.currency ?? []))].sort(),
    [issuers],
  );
  // A currency no displayed issuer holds is no currency (a stale link or memory).
  const effective = useMemo(
    () =>
      view.currency !== null && !currencies.includes(view.currency)
        ? { ...view, currency: null }
        : view,
    [view, currencies],
  );
  const unitFor = useMemo(() => unitLookup(units), [units]);
  const kept = useMemo(() => applyView(issuers, effective, units), [issuers, effective, units]);
  const money = useCallback((column: ColumnKey) => unitFor(column)?.unit === "MONEY", [unitFor]);
  const needsCurrency =
    (view.sort !== null && money(view.sort.column)) ||
    view.filters.some((filter) => filter.kind === "range" && money(filter.column));
  return (
    <div className="col" data-book-v2>
      <section className="pnl">
        <header>
          <h2>Issuers</h2>
        </header>
        <div className="pb book-bar">
          <fieldset className="book-basis">
            <legend>Basis</legend>
            {BASES.map((basis: Basis) => (
              <label key={basis} className="fopt">
                <input
                  type="radio"
                  name={`${ids}-basis`}
                  checked={view.basis === basis}
                  onChange={() => update({ ...view, basis })}
                />
                {BASIS_LABELS[basis]}
              </label>
            ))}
          </fieldset>
          {needsCurrency ? (
            <label className="fld">
              Currency
              <select
                value={effective.currency ?? ""}
                onChange={(e) => update({ ...view, currency: e.target.value || null })}
              >
                <option value="">Choose a currency</option>
                {currencies.map((code) => (
                  <option key={code}>{code}</option>
                ))}
              </select>
            </label>
          ) : null}
          <Button type="button" variant="ghost" size="sm" onClick={() => update(DEFAULT_VIEW)}>
            Reset view
          </Button>
        </div>
        <div className="pb">
          {needsCurrency && effective.currency === null ? (
            <p className="fld-hint">
              Amounts are native to each issuer: choose a currency to compare them. No conversion is
              made.
            </p>
          ) : null}
        </div>
        <div
          className="pb tscroll book-scroll"
          tabIndex={0}
          role="region"
          aria-label="Issuers table"
        >
          <table className="tbl dense pin-first book-grid">
            <caption className="sr-only">Issuers in the Book</caption>
            <thead>
              <tr>
                {view.columns.map((column) => (
                  <Sorter
                    key={column}
                    column={column}
                    view={effective}
                    units={units}
                    isMoney={money}
                    onSort={(sort) => update({ ...view, sort })}
                  />
                ))}
              </tr>
            </thead>
            {kept.map((issuer) => (
              <tbody key={issuer.issuer_key}>
                <IssuerRow issuer={issuer} view={view} unitFor={unitFor} />
              </tbody>
            ))}
          </table>
        </div>
        <footer className="pb book-foot">
          {issuers.length === 0 ? <p className="note">No issuers in the Book.</p> : null}
          {issuers.length > 0 && kept.length === 0 ? (
            <p className="note">No issuer matches this view.</p>
          ) : null}
          <p className="note" data-book-count>
            {`${kept.length} of ${issuers.length} issuers`}
          </p>
        </footer>
      </section>
    </div>
  );
}

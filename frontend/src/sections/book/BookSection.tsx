// Book, /book/: the desk-wide Book, one row per issuer. Each row is the
// issuer's displayed book entry as the server serves it: the issuer, its
// reporting period, its analyst-stated sector, its composite rating and LTM
// revenue. The section composes a view and grants nothing: every field is read from the
// document, and nothing here derives, compares or judges an entry. The column
// chooser, filters and history arrive with the Book's own view (spec B12-B15).
import type { BookDocument } from "@/wire/v1";
import { spelled } from "@/sections/model/grid";
import { columnLabel, unitLookup, type Unit } from "./columns";
import { cellOf, metricOf, type BookIssuer } from "./filter";
import type { Basis, ColumnKey } from "./view";

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

export function BookSection({ document }: { document: BookDocument; tab: string | null }) {
  const issuers = document.body.issuers;
  const units = document.body.metric_catalogue;
  const unitFor = unitLookup(units);
  return (
    <div className="col" data-book-v2>
      <section className="pnl">
        <header>
          <h2>Issuers</h2>
          <span className="cp">{issuers.length} issuers</span>
        </header>
        <div className="pb tscroll" tabIndex={0} role="region" aria-label="Issuers in the Book">
          <table className="tbl pin-first book-grid">
            <caption className="sr-only">Issuers in the Book</caption>
            <thead>
              <tr>
                <th scope="col">Issuer</th>
                <th scope="col">Reporting period</th>
                <th scope="col">Sector</th>
                <th scope="col">Composite</th>
                <th scope="col">Currency</th>
                <th scope="col">Unit</th>
                <th scope="col">{columnLabel("m:revenue@LTM", units)}</th>
              </tr>
            </thead>
            <tbody>
              {issuers.map((issuer) => (
                <tr
                  key={issuer.issuer_key}
                  data-issuer={issuer.issuer_key}
                  data-entry={issuer.displayed.entry_id}
                >
                  <th scope="row" className="l wrap">
                    {issuer.displayed.issuer_name}
                  </th>
                  <td className="l">{issuer.displayed.reporting_period}</td>
                  <td className="l">{issuer.displayed.sector}</td>
                  <td className="l">{issuer.displayed.composite}</td>
                  <td className="l">{issuer.displayed.currency ?? <NotStated />}</td>
                  <td className="l">{issuer.displayed.unit ?? <NotStated />}</td>
                  <td className="num" aria-description={yearOf(issuer, "m:revenue", "LTM")}>
                    <MetricCell
                      issuer={issuer}
                      column="m:revenue"
                      basis="LTM"
                      unit={unitFor("m:revenue")}
                    />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}

// Book, /book/: the desk-wide Book, one row per issuer. Each row is the
// issuer's displayed book entry as the server serves it: the issuer, its
// reporting period, its analyst-stated sector and its composite rating. The
// section composes a view and grants nothing: every field is read from the
// document, and nothing here derives, compares or judges an entry. The column
// chooser, filters and history arrive with the Book's own view (spec B12-B15).
import type { BookDocument } from "@/wire/v1";

export function BookSection({ document }: { document: BookDocument; tab: string | null }) {
  const issuers = document.body.issuers;
  return (
    <div className="col" data-book-v2>
      <section className="pnl">
        <header>
          <h2>Issuers</h2>
          <span className="cp">{issuers.length} issuers</span>
        </header>
        <div className="pb tscroll" tabIndex={0} role="region" aria-label="Issuers in the Book">
          <table className="tbl pin-first">
            <caption className="sr-only">Issuers in the Book</caption>
            <thead>
              <tr>
                <th scope="col">Issuer</th>
                <th scope="col">Reporting period</th>
                <th scope="col">Sector</th>
                <th scope="col">Composite</th>
              </tr>
            </thead>
            <tbody>
              {issuers.map(({ issuer_key: key, displayed: entry }) => (
                <tr key={key} data-issuer={key} data-entry={entry.entry_id}>
                  <th scope="row" className="l wrap">
                    {entry.issuer_name}
                  </th>
                  <td className="l">{entry.reporting_period}</td>
                  <td className="l">{entry.sector}</td>
                  <td className="l">{entry.composite}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}

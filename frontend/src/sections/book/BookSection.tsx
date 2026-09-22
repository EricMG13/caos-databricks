// Book, /book/ (IA_SPEC.md 4.4): the credit, across the portfolio. One table
// per accepted period, credits down the side and the served columns across;
// selecting any cell opens the metric passport. The section composes a view
// and grants nothing: every figure and every passport field is read from the
// document, and nothing here derives, compares or judges a run.
//
// Each credit binds the accepted snapshot this document names it under, so a
// later document carrying a different snapshot for a bound credit is refused
// and said so on the row; only the explicit switch moves the lens
// (IA_SPEC.md 5, `@/app/authority`'s `bind` and `release`).
import { useEffect, useState } from "react";
import { MetricCell } from "./MetricCell";
import { passportOf } from "./passport";
import { useLedger } from "@/app/ledger";
import { useEvidence } from "@/evidence/EvidenceContext";
import type { Refusal } from "@/wire";
import type { BookColumn, BookDocument, BookPeriod, BookRow } from "@/wire/v1";

/** Every period any credit carries, in the order the first credit to carry it
    states: the comparison is over what was served, never a period this view
    filled in. */
function periodsOf(rows: readonly BookRow[]): string[] {
  const seen: string[] = [];
  for (const row of rows) {
    for (const period of row.periods) {
      const key = `${period.case} · ${period.period_id}`;
      if (!seen.includes(key)) seen.push(key);
    }
  }
  return seen;
}

function periodOf(row: BookRow, key: string): BookPeriod | null {
  return row.periods.find((period) => `${period.case} · ${period.period_id}` === key) ?? null;
}

/** Why a credit shows no figure, in the document's own words. */
function reasonOf(row: BookRow): string | null {
  if (row.refusal) return `${row.refusal.code} · ${row.refusal.clears}`;
  if (row.unavailable_reason) {
    const ended =
      row.displayed_run_status && row.displayed_run_status !== "RUNNING"
        ? ` · the run ended ${row.displayed_run_status}`
        : "";
    return `${row.unavailable_reason}${ended}`;
  }
  return null;
}

export function BookSection({ document }: { document: BookDocument; tab: string | null }) {
  const { body, observed_at: observedAt } = document;
  const [selected, setSelected] = useState<string | null>(null);
  const [refusedLens, setRefusedLens] = useState<Record<string, Refusal>>({});
  const { openPassport } = useEvidence();
  const ledger = useLedger();

  const rows = body.rows;
  useEffect(() => {
    const refused: Record<string, Refusal> = {};
    for (const row of rows) {
      if (row.snapshot === null) continue;
      const refusal = ledger.bind(row.case_id, row.snapshot);
      if (refusal) refused[row.case_id] = refusal;
    }
    // eslint-disable-next-line react-hooks/set-state-in-effect -- the ledger is the external system this view synchronises with
    setRefusedLens(refused);
  }, [rows, ledger]);

  const switchLens = (row: BookRow) => {
    ledger.release(row.case_id);
    if (row.snapshot !== null) ledger.bind(row.case_id, row.snapshot);
    setRefusedLens((current) => {
      const next = { ...current };
      delete next[row.case_id];
      return next;
    });
  };

  const select = (row: BookRow, column: BookColumn, key: string, opener: HTMLElement) => {
    const period = periodOf(row, key);
    const cell = period?.cells.find((entry) => entry.column === column.key);
    if (!cell) return;
    setSelected(`${row.case_id}|${key}|${column.key}`);
    openPassport(passportOf(row, column, cell, observedAt), opener);
  };

  return (
    <div className="col" data-book-v1>
      <section className="pnl">
        <header>
          <h2>Basis</h2>
          <span className="cp">{body.rows.length} credits</span>
        </header>
        <div className="pb">
          <dl className="kv">
            <dt>Period</dt>
            <dd data-basis-period>{body.basis.period}</dd>
            <dt>Scenario</dt>
            <dd>{body.basis.scenario}</dd>
            <dt>Accepted only</dt>
            <dd>{String(body.basis.accepted_only)}</dd>
          </dl>
          {import.meta.env.MODE === "demo" ? (
            // The fixture is fuller than any run a workspace press makes by
            // default; the demonstration says which runs alone can fill it.
            <p className="note" data-demo-book-note>
              <b>A forecast reaches the Book only from one kind of run.</b> The figures shown here
              are demonstration fixtures. The server serves a Book cell only for a run on
              FULL_CREDIT_32 / RELATIVE_VALUE created with the model extension (CP-CF); a run on any
              other pathway, or created without the extension, has no accepted forecast to compare.
            </p>
          ) : null}
        </div>
      </section>
      {periodsOf(rows).length === 0 && rows.length > 0 ? (
        // Every credit on a LITE route is `NO_ACCEPTED_FORECAST`, so this is
        // the ordinary state, not an edge: without it the page drew a credit
        // count over nothing at all and said why for none of them.
        <section className="pnl">
          <header>
            <h2>Credits</h2>
            <span className="cp">no accepted forecast to compare</span>
          </header>
          <div className="pb">
            <ul className="lst" data-book-credits>
              {rows.map((row) => (
                <li key={row.case_id} data-case={row.case_id}>
                  {row.title}
                  <div className="lbl">{row.snapshot ?? reasonOf(row)}</div>
                </li>
              ))}
            </ul>
          </div>
        </section>
      ) : null}
      {periodsOf(rows).map((key) => (
        <section className="pnl" key={key}>
          <header>
            <h2>{key}</h2>
          </header>
          <div className="pb">
            <table className="tbl">
              <caption className="lbl">Credits compared on {key}</caption>
              <thead>
                <tr>
                  <th scope="col">Credit</th>
                  <th scope="col">Units</th>
                  {body.columns.map((column) => (
                    <th scope="col" key={column.key}>
                      {column.label}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => {
                  const period = periodOf(row, key);
                  return (
                    <tr key={row.case_id} data-case={row.case_id}>
                      <th scope="row" className="l wrap">
                        {row.title}
                        <div className="lbl">{row.snapshot ?? reasonOf(row)}</div>
                        {refusedLens[row.case_id] ? (
                          <div className="note" data-lens-refused={row.case_id}>
                            {refusedLens[row.case_id]?.clears}{" "}
                            <button
                              type="button"
                              className="focus-ring"
                              onClick={() => switchLens(row)}
                            >
                              Switch the lens
                            </button>
                          </div>
                        ) : null}
                      </th>
                      <td className="l">
                        {row.currency && row.scale ? `${row.currency} · ${row.scale}` : "—"}
                      </td>
                      {body.columns.map((column) => {
                        const cell = period?.cells.find((entry) => entry.column === column.key);
                        return (
                          <td className="l" key={column.key}>
                            {cell ? (
                              <MetricCell
                                cell={cell}
                                label={`${row.title} ${column.label} ${key}`}
                                selected={selected === `${row.case_id}|${key}|${column.key}`}
                                onSelect={(opener) => select(row, column, key, opener)}
                              />
                            ) : (
                              <span className="tag">NOT SERVED</span>
                            )}
                          </td>
                        );
                      })}
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </section>
      ))}
    </div>
  );
}
